#!/usr/bin/env python3
"""Run sanitized IR/NL-shaped source and real Nginx/PHP-FPM acceptance.

Only on the authorized retained aaPanel QA guest. No live aaPanel DB/VHost,
production config, private site, global cache, panel worker or service
mutation. Start/stop a task-owned Nginx process with temporary config/cache
and loopback-only high ports; use the existing native PHP-FPM socket for
synthetic PHP pages. This is a runtime fixture, not a native UI Apply test.
"""
import argparse
import hashlib
import functools
import http.client
import ssl
from unittest.mock import patch
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[2] / "plugin/ach_customizer")
PARSER.add_argument("--well-known", type=Path, default=Path(__file__).resolve().parents[1] / "fixtures/native-well-known.conf")
PARSER.add_argument("--cache-force-https-only", action="store_true", help="Exercise fresh guarded Force HTTPS Cache lifecycle on isolated Nginx")
PARSER.add_argument("--status-only", action="store_true", help="Run the nested NL status evidence/lifecycle without repeating Guard or Cache writes")
ARGS = PARSER.parse_args()
sys.path.insert(0, str(ARGS.plugin_root))
import ach_customizer_cache_audit as audit
import ach_customizer_cache_manage as manage
import ach_customizer_cache_policy as policy
import ach_customizer_cache_wordpress as wp
import ach_customizer_cache_runtime as runtime
import ach_customizer_origin_http as origin
import ach_customizer_wp_settings as settings
import ach_customizer_monitor as monitor
import ach_customizer_vhost_drift as drift
import ach_customizer_nginx_security as guard
import ach_customizer_status_extension as status
import ach_customizer_status_site_file as status_file

NGINX = "/www/server/nginx/sbin/nginx"
NATIVE_CONF = Path("/www/server/nginx/conf")
ALT = """add_header Alt-Svc 'quic=":443"; h3=":443"; h3-29=":443"; h3-27=":443";h3-25=":443"; h3-T050=":443"; h3-Q050=":443";h3-Q049=":443"; h3-Q048=":443"; h3-Q046=":443"; h3-Q043=":443"';"""
HSTS = 'add_header Strict-Transport-Security "max-age=31536000";'
PEER = """location = /app/health.php {
    try_files $uri =404;
    fastcgi_pass unix:/tmp/php-cgi-85.sock;
    fastcgi_index index.php;
    include fastcgi.conf;
    include pathinfo.conf;
}
location = /app/old { return 307 https://PEER/app/new$is_args$args; }
location ^~ /app/retired/ { return 410; }
"""
PHP = r"""<?php
header('Content-Type: text/plain');
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
if ($path === '/private.php') header('Cache-Control: private, no-store');
if ($path === '/cookie.php') header('Set-Cookie: fixture=synthetic; Path=/');
if ($path === '/vary.php') header('Vary: X-Fixture');
if ($path === '/expired.php') header('Expires: Thu, 01 Jan 1970 00:00:00 GMT');
if ($path === '/accel.php') header('X-Accel-Expires: 0');
echo "fixture:" . $path . ":" . bin2hex(random_bytes(8));
"""


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.start, self.size = 0, len(rows)
        self.fields = None
        self.path = None
    def order(self, key):
        assert key == "id asc"
        return self
    def limit(self, bounds):
        self.start, self.size = map(int, bounds.split(","))
        return self
    def field(self, fields):
        self.fields = fields.split(",")
        return self
    def where(self, expr, args):
        assert expr == "path=?"
        self.path = args[0]
        return self
    def select(self):
        rows = [r for r in self.rows if self.path is None or r["path"] == self.path]
        return [{k: r[k] for k in self.fields} if self.fields else dict(r)
                for r in rows[self.start:self.start+self.size]]


class Panel:
    def __init__(self, rows):
        self.rows = rows
    def M(self, name):
        assert name == "sites"
        return Query(self.rows)
    def get_webserver(self):
        return "nginx"
    def get_panel_version(self):
        return "8.0.7"


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise RuntimeError("Command failed: " + str(argv[0]) + " " + result.stderr[-1600:])
    return result.stdout


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")


def high_port():
    # Check both TCP and UDP before handing a loopback-only port to our
    # independent worker. A race is handled by process-start failure.
    with socket.socket() as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        tcp.bind(("127.0.0.1", 0))
        port = tcp.getsockname()[1]
        udp.bind(("127.0.0.1", port))
        return port


def request(name, port, path="/index.php", *, tls=False, protocol=None, headers=(), source=None):
    url = ("https" if tls else "http") + f"://{name}:{port}{path}"
    args = ["curl", "--noproxy", "*", "--silent", "--show-error", "--max-time", "8",
            "--connect-timeout", "3", "--resolve", f"{name}:{port}:127.0.0.1",
            "-k", "-D", "-", url]
    if source:
        args.extend(("--interface", source))
    if protocol:
        args.insert(1, protocol)
    for header in headers:
        args.extend(("-H", header))
    raw = run(args)
    header, _, body = raw.partition("\n\n")
    lines = header.splitlines()
    if not lines or not lines[0].startswith("HTTP/"):
        raise RuntimeError("Invalid HTTP response")
    values = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            values.setdefault(key.lower(), []).append(value.strip())
    return {"status": int(lines[0].split()[1]), "protocol": lines[0].split()[0],
            "headers": values, "body": body}


def response_semantics(row):
    return {k: row["headers"].get(k, []) for k in (
        "strict-transport-security", "alt-svc", "x-frame-options",
        "x-content-type-options", "content-security-policy")}


def process(conf, directory, callback):
    # Explicit temp paths, log and pid make this process independent from
    # aaPanel's live Nginx worker and configuration.
    argv = [NGINX, "-p", str(directory) + "/", "-c", str(conf), "-g", "daemon off;"]
    run(argv + ["-t"])
    with (directory / "worker-output.log").open("ab") as output:
        child = subprocess.Popen(argv, stdout=output, stderr=output)
        try:
            deadline = time.monotonic() + 8
            while True:
                pidfile = directory / "fixture.pid"
                pid = pidfile.read_text().strip() if pidfile.is_file() else ""
                if pid == str(child.pid):
                    break
                if child.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Isolated Nginx did not start: exit=%s pidfile=%r stderr=%s log=%s" % (
                        child.poll(), pid,
                        (directory / "worker-output.log").read_text(errors="replace")[-2000:],
                        (directory / "error.log").read_text(errors="replace")[-2000:]))
                time.sleep(.1)
            return callback()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


def force_https_lifecycle(directory, confdir, vhosts, main, rows, panel, selected, cert,
                          http_port, tls_port):
    """Real source validation and real Nginx reloads with only fixture-local paths.

    Native source files retain their actual 80/443 shape; the independent
    process receives a copy with just the listener ports mapped to high
    loopback ports. The generated owned extensions stay byte-identical.
    """
    live = directory / "runtime-vhosts"
    live.mkdir()
    live_main = confdir / "runtime.conf"
    state = directory / "cache-state"
    state.mkdir(mode=0o700)
    cache_root = str(directory / "managed-cache")
    selected_names = {r["name"] for r in selected}
    for row in selected:
        path = vhosts / (row["name"] + ".conf")
        write(path, path.read_text().replace(
            " ssl_certificate ", ' if ($server_port !~ 443) { rewrite ^(/.*)$ https://$host$1 permanent; }\n ssl_certificate ', 1))
        # Match the actual IR database: only port 80 is registered even
        # though the native VHost listens on both 80 and 443.
        row["bound_domains"] = [{"name":row["name"],"port":80}]
        if row is selected[0]:
            root = Path(row["path"])
            # Real PHP canonical /index.php -> / redirect, just as observed
            # on the WordPress site. All other routes still execute PHP.
            write(root/"index.php", PHP.replace(
                "$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);",
                "$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);\n"
                "if ($path === '/index.php') { header('Location: https://' . $_SERVER['HTTP_HOST'] . '/', true, 301); exit; }"))
            (root/"wp-json").mkdir()
            write(root/"wp-json"/"index.php", PHP)
    original = {p: p.read_bytes() for p in vhosts.glob("*.conf")}
    def render_runtime():
        for path in live.glob("*.conf"):
            path.unlink()
        for path in vhosts.glob("*.conf"):
            write(live/path.name,path.read_text().replace(
                "listen 80;",f"listen 127.0.0.1:{http_port};").replace(
                "listen 443 ssl;",f"listen 127.0.0.1:{tls_port} ssl;").replace(
                "listen 443 quic;",f"listen 127.0.0.1:{tls_port} quic;").replace(
                "$server_port !~ 443",f"$server_port !~ ^{tls_port}$"))
        write(live_main,main.read_text().replace(str(vhosts)+"/*.conf",str(live)+"/*.conf"))
    render_runtime()
    commands = []
    def runner(argv, **kwargs):
        assert argv[0]==NGINX and argv[-2:]==["-c",str(main)]
        assert argv[1] in ("-t","-s")
        render_runtime()
        commands.append(argv[1])
        return subprocess.run([NGINX,"-p",str(directory)+"/"]+argv[1:-1]+[str(live_main)],**kwargs)
    context = ssl.create_default_context(cafile=str(cert))
    def probe(site, *, marker=None):
        return manage._probe(site, marker=marker, http_port=http_port,
                             https_port=tls_port,tls_context=context)
    ref = functools.partial(policy.generate_reference,cache_root=cache_root)
    owned = functools.partial(manage._path_owned,cache_root=cache_root)
    kw = {"vhost_root":str(vhosts),"nginx_root":str(confdir),"data_dir":str(state),"probe":probe}
    peer = next(row for row in rows if row["name"] not in selected_names)
    def exercise():
        outputs=[]
        peer_before=probe(peer)
        for row, expected in zip(selected, ((301,301),(301,200))):
            assert probe(row)==expected, (row["name"],probe(row),expected)
            # A bad trust store must not reach PHP nor authorize any write.
            try:
                manage._probe(row,http_port=http_port,https_port=tls_port)
            except manage.CacheManageError as exc:
                assert "certificate verification" in str(exc), str(exc)
            else:
                raise AssertionError("Untrusted fixture certificate was accepted")
            plan=manage.preview_cache_activation(row,panel,**kw)
            assert (plan["php_probe_status"],plan["php_probe_https_status"])==expected
            assert not list(state.glob("ach_customizer.cache.%d.json"%row["id"]))
            applied=manage.manage_cache("apply",row,panel,approved=True,
                expected_source=plan["source_sha256"],expected_proposal=plan["proposal_sha256"],
                cache_generation=plan["cache_generation"],runner=runner,**kw)
            assert applied["state"]=="Applied" and applied["runtime_verified"],applied
            assert probe(row,marker=row["id"])==expected
            assert manage.manage_cache("recheck",row,panel,**kw)["state"]=="Applied"
            fd=manage._open_state_dir(str(state))
            try:
                saved=manage._record_read(fd,row["id"])
                assert manage._saved_probe_status(saved)==expected
            finally:
                os.close(fd)
            if row is selected[0]:
                source=audit.inspect_site_fastcgi_cache(panel,row["id"],row["name"],
                    vhost_root=str(vhosts),nginx_root=str(confdir),rewrite_root=str(vhosts.parent/"rewrite"))
                observed=runtime.probe_private_cache(row,source,vhost_root=str(vhosts),
                    connection_factory=lambda: http.client.HTTPConnection("127.0.0.1",http_port,timeout=4),
                    https_factory=lambda: origin.https_connection(row["name"],tls_port,context=context))
                assert observed["state"]=="Observed BYPASS",observed
                assert all(p["scheme"]=="HTTPS" for p in observed["probes"]),observed
            restored=manage.manage_cache("restore",row,panel,approved=True,
                recovery_id=applied["recovery_id"],runner=runner,**kw)
            assert restored["state"]=="Restored" and restored["runtime_verified"],restored
            assert probe(row)==expected
            assert manage.manage_cache("recheck",row,panel,**kw)["state"]=="Restored"
            assert probe(peer)==peer_before
            outputs.append({"handler":plan["native_handler"],"http_https_status":expected,
                "apply_recheck_restore":"PASS","invalid_certificate":"rejected",
                "peer":"unchanged"})
        assert commands.count("-s")==4,commands
        assert {p:p.read_bytes() for p in original}==original
        return outputs
    with patch.object(manage,"CACHE_ROOT",cache_root), patch.object(manage,"DATA_DIR",str(state)), \
         patch.object(manage,"_path_owned",owned), patch.object(manage,"generate_reference",ref), \
         patch.object(policy,"generate_reference",ref),patch.object(runtime,"CACHE_ROOT",cache_root):
        return process(live_main,directory,exercise)


def profile(base, label, wp_count, php_count):
    directory = base / label
    directory.mkdir()
    (directory / "logs").mkdir()
    confdir = directory / "native"
    vhosts = directory / "vhost"
    rewrite = directory / "rewrite"
    for p in (confdir, vhosts, rewrite):
        p.mkdir()
    for name in ("enable-php-85.conf", "enable-php-85-wpfastcgi.conf",
                 "fastcgi.conf", "pathinfo.conf"):
        shutil.copyfile(NATIVE_CONF / name, confdir / name)
    rows = []
    before_sources = {}
    cert = directory / "fixture.crt"
    key = directory / "fixture.key"
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-subj", "/CN=qa.invalid", "-days", "1",
         "-addext", "subjectAltName="+",".join("DNS:site-%d.%s.test"%(i+1,label) for i in range(wp_count+php_count))])
    legacy = directory / "legacy-cache"
    legacy.mkdir()
    www = pwd.getpwnam("www")
    os.chown(legacy, www.pw_uid, www.pw_gid)
    write(vhosts / "0.fastcgi_cache.conf",
          f'fastcgi_cache_key "$scheme$request_method$host$request_uri";\n'
          f"fastcgi_cache_path {legacy} levels=1:2 keys_zone=WORDPRESS:10m inactive=60m;\n"
          "fastcgi_cache_use_stale error timeout invalid_header http_500;\n"
          "fastcgi_ignore_headers Cache-Control Expires Set-Cookie;\n")
    for i in range(wp_count+php_count):
        wordpress = i < wp_count
        name = f"site-{i+1}.{label}.test"
        root = directory / ("acdomains" if label == "ir" or i % 2 else "wwwroot") / name
        root.mkdir(parents=True)
        ext = vhosts / "extension" / name
        ext.mkdir(parents=True)
        write(rewrite / (name + ".conf"), "")
        registered = root
        # One observed NL application uses aaPanel's legitimate public
        # subdirectory. Parent status files exist but are not served.
        nested = label == "nl" and i == wp_count + 1
        if nested:
            write(registered / "404.html", "unserved parent 404")
            write(registered / "502.html", "unserved parent 502")
            root = registered / "public"
            root.mkdir()
        row = {"id": 100+i, "name": name, "path": str(registered), "status": 1,
               "bound_domains": [{"name": name, "port": 80}, {"name": name, "port": 443}]}
        rows.append(row)
        for leaf in ("index.php", "private.php", "cookie.php", "vary.php", "expired.php", "accel.php", "app/health.php"):
            write(root / leaf, PHP)
        if not nested:
            write(root / "404.html", "fixture 404")
            write(root / "502.html", "fixture 502")
        if wordpress:
            write(root / "wp-config.php", "<?php\ndefine('RT_WP_NGINX_HELPER_CACHE_PATH','/www/server/fastcgi_cache');\nrequire_once ABSPATH . 'wp-settings.php';\n")
            for leaf in ("wp-load.php", "wp-settings.php", "wp-cron.php"):
                write(root / leaf, "<?php /* source fixture, not real WordPress */\n")
            write(root / ".user.ini", f"open_basedir={root}/:/tmp/:/dev/shm/nginx-cache/wp\n")
        if label == "nl" and i == wp_count:
            write(ext / "application.conf", PEER.replace("PEER", name))
        ssl_helper = ""
        if label == "ir" and not wordpress:
            helper = vhosts / "well-known" / (name + ".conf")
            helper.parent.mkdir(exist_ok=True)
            shutil.copyfile(ARGS.well_known, helper)
            ssl_helper = f" include {helper};\n"
        php = "85-wpfastcgi" if wordpress else "85"
        source = (
            f"server {{\n listen 80;\n listen 443 ssl;\n listen 443 quic;\n http2 on;\n"
            f" server_name {name};\n root {root};\n index index.php index.html;\n"
            f" include {ext}/*.conf;\n{ssl_helper}"
            f" ssl_certificate {cert};\n ssl_certificate_key {key};\n"
            f" {HSTS}\n {ALT}\n"
            + (" add_header Content-Security-Policy \"default-src self\" always;\n" if not wordpress else "")
            + " error_page 404 /404.html;\n error_page 502 /502.html;\n"
            f" include enable-php-{php}.conf;\n include {rewrite / (name+'.conf')};\n}}\n"
        )
        path = vhosts / (name + ".conf")
        write(path, source)
        before_sources[path] = source
    http_port, tls_port = high_port(), high_port()
    assert http_port != tls_port
    main = confdir / "nginx.conf"
    extra = "".join(f" {part}_temp_path {directory}/{part}-temp;\n"
                    for part in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
    write(main, f"user www www;\nworker_processes 1;\npid {directory}/fixture.pid;\n"
          f"lock_file {directory}/fixture.lock;\nerror_log {directory}/error.log notice;\nevents {{ worker_connections 128; }}\n"
          f'http {{\n access_log off;\n lua_package_path "/www/server/nginx/lib/lua/?.lua;;";\n{extra} include {vhosts}/*.conf;\n}}\n')
    panel = Panel(rows)
    kw = {"vhost_root": str(vhosts), "nginx_root": str(confdir)}
    result = {"profile": label, "registered": len(rows), "wordpress": wp_count,
              "source_ready": 0, "wordpress_assignment": 0, "vhost_file_match": 0,
              "wp_edit_preview": 0}
    for row in rows:
        result["vhost_file_match"] += drift.inspect_vhost_drift(panel,row,vhost_root=str(vhosts))["state"] == "File Match"
    for row in rows[:wp_count]:
        observed, _, _ = manage._compatibility(row, panel, **kw)
        assert observed["state"] == "Source Observed" and not observed["unresolved_other_sites"], observed
        result["source_ready"] += 1
        assert settings._site_source(row,panel,vhost_root=str(vhosts))[2] == "85"
        result["wordpress_assignment"] += 1
        edits = wp._edits(row)
        assert edits["wp_before"] != edits["wp_after"] and edits["ini_before"] != edits["ini_after"]
        result["wp_edit_preview"] += 1
    assert result["vhost_file_match"] == len(rows) - (label == "nl")
    result["native_nested_root"] = int(label == "nl")
    pool = directory / "pool.conf"
    write(pool, "[www]\nlisten = /tmp/php-cgi-85.sock\n")
    impact = monitor.inspect_php_fpm_site_impact(panel, "85", pool,
        vhost_root=str(vhosts), nginx_conf_root=str(confdir), rewrite_root=str(rewrite))
    assert impact["state"] == "File Mapping" and len(impact["matched_sites"]) == len(rows), impact
    result["fpm_attributed"] = len(impact["matched_sites"])
    # The real topologies include a public-root application and unrelated
    # foreign routes; neither may block a scoped server-owned extension.
    for row in rows:
        guard._source_safe(row, vhost_root=str(vhosts), nginx_conf=str(main))
        for code in ("404", "50x"):
            status._source(row, code, str(vhosts), str(main))
    result["guard_source_ready"] = len(rows)
    result["status_extension_source_ready"] = len(rows)
    # The stock site chosen for runtime has no foreign selected-route writer.
    selected = [rows[0], rows[-1]]
    if ARGS.cache_force_https_only:
        result["force_https_cache_lifecycle"] = force_https_lifecycle(
            directory,confdir,vhosts,main,rows,panel,selected,cert,http_port,tls_port)
        print(json.dumps(result),flush=True)
        return result
    generated = []
    for row, handler in zip(selected, ("wpfastcgi", "stock")):
        sources = manage._site_sources(row,"85",native_handler=handler,**kw)
        generated.append((row,policy.generate_reference(row["id"],"85",
            native_handler=handler, inherited_hsts=sources["inherited_hsts"],
            inherited_headers=sources.get("inherited_headers"),
            cache_generation=("b" if handler == "wpfastcgi" else "a")*32,
            cache_root=str(directory/"private-cache"))))
    # Only the independent runtime clone uses different listeners.
    for path, source in before_sources.items():
        write(path, source.replace("listen 80;", f"listen 127.0.0.1:{http_port};")
              .replace("listen 443 ssl;", f"listen 127.0.0.1:{tls_port} ssl;")
              .replace("listen 443 quic;", f"listen 127.0.0.1:{tls_port} quic;"))
    peer = rows[wp_count]["name"]
    def peer_requests():
        if label != "nl":
            return []
        health = request(peer,http_port,"/app/health.php")
        moved = request(peer,http_port,"/app/old")
        retired = request(peer,http_port,"/app/retired/example")
        assert health["status"] == 200 and health["body"].startswith("fixture:/app/health.php:")
        assert moved["status"] == 307 and moved["headers"]["location"] == [f"https://{peer}/app/new"]
        assert retired["status"] == 410
        return [health["status"],moved["status"],retired["status"]]
    def baseline():
        out = {}
        for row in selected:
            response = request(row["name"],tls_port,tls=True,protocol="--http2")
            assert response["status"] == 200 and response["body"].startswith("fixture:/index.php:")
            out[row["name"]] = response_semantics(response)
        return out, peer_requests()
    # #146: reuse these observed native layouts, including stock and WP
    # handlers, the well-known include and a nested public root. No new
    # compatibility matrix or live aaPanel mutation is required.
    if not ARGS.status_only:
        scan_state = directory / "scanner-state"
        scan_state.mkdir(mode=0o700)
        def scan_runner(argv, **kwargs):
            assert argv[0] == NGINX and argv[-2:] == ["-c", str(main)]
            assert argv[1] in ("-t", "-s")
            return subprocess.run([NGINX, "-p", str(directory)+"/"] + argv[1:], **kwargs)
        def scan_lifecycle():
            fd = os.open(scan_state, os.O_RDONLY | os.O_DIRECTORY)
            out = []
            try:
                targets = [rows[0], rows[-1] if label == "ir" else rows[wp_count+1]]
                for target in targets:
                    name = target["name"]
                    other = rows[-1 if target is rows[0] else 0]["name"]
                    def query(path="/index.php", host=name):
                        return request(host,http_port,path,source="127.0.0.2")["status"]
                    assert query() == 200 and query(host=other) == 200
                    opts = dict(data_fd=fd, vhost_root=str(vhosts), nginx_conf=str(main),
                        nginx=NGINX, runner=scan_runner,
                        probe=lambda site,op,kind: guard._probe(site,op,kind,port=http_port))
                    policy = {"maxretry":3,"findtime":30,"bantime":30}
                    preview = guard.manage_guard("preview",target,scan_policy=policy,**opts)
                    assert preview["state"] == "Unmanaged",preview
                    applied = guard.manage_guard("apply",target,approved=True,scan_policy=policy,
                        expected_vhost=preview["vhost_sha256"],
                        expected_proposal=preview["proposal_sha256"],**opts)
                    assert applied["state"]=="Applied",applied
                    assert [query("/.env") for _ in range(3)] == [403,403,403]
                    assert query() == 429 and query(host=other) == 200
                    assert request(name,http_port)["status"]==200
                    checked = guard.manage_guard("recheck",target,**opts)
                    assert checked["state"]=="Applied" and checked["scan_policy"]==policy,checked
                    restored = guard.manage_guard("restore",target,approved=True,
                        expected_vhost=checked["vhost_sha256"],
                        expected_recovery=checked["recovery_id"],**opts)
                    assert restored["state"]=="Restored" and query()==200,restored
                    assert query(host=other)==200
                    out.append({"site":name,"apply_recheck_restore":"PASS","same_ip_peer":"200"})
                return out
            finally:
                os.close(fd)
        result["scanner_lifecycle"] = process(main,directory,scan_lifecycle)
    if label == "nl":
        target = rows[wp_count+1]
        parent = Path(target["path"])
        assert (parent / "502.html").read_text() == "unserved parent 502"
        for code in ("404", "502"):
            try:
                status_file._source(target, code, str(vhosts))
            except status.ExtensionError:
                pass
            else:
                raise AssertionError("File writer must not adopt the unserved parent")
        state = directory / "recovery"
        state.mkdir()
        html = "<html><body>Scoped error fixture</body></html>"
        rendered = hashlib.sha256(html.encode()).hexdigest()
        def scoped_runner(argv, **kwargs):
            # Signal ONLY the isolated task-owned master selected by its
            # exact pid and prefix; never invoke aaPanel's live reload.
            assert argv[0] == NGINX and argv[-2:] == ["-c", str(main)]
            assert argv[1] in ("-t", "-s")
            return subprocess.run([NGINX, "-p", str(directory)+"/"] + argv[1:], **kwargs)
        def guard_probe(site, op, kind):
            return guard._probe(site, op, kind, port=http_port)
        def status_probe(site, code, op):
            return status._probe(site, code, op, port=http_port)
        def lifecycle():
            peer_before = peer_requests()
            old_404 = status_probe(target, "404", None)
            assert old_404[0] == 404, old_404
            native_before = guard._source_safe(target,vhost_root=str(vhosts),nginx_conf=str(main))[0]
            fd=os.open(state,os.O_RDONLY|os.O_DIRECTORY)
            try:
                if not ARGS.status_only:
                    gkw=dict(data_fd=fd,approved=True,vhost_root=str(vhosts),
                        nginx_conf=str(main),nginx=NGINX,runner=scoped_runner,probe=guard_probe)
                    preview=guard.manage_guard("preview",target,**gkw)
                    applied=guard.manage_guard("apply",target,expected_vhost=native_before,
                        expected_proposal=preview["proposal_sha256"],**gkw)
                    assert applied["state"] == "Applied", applied
                    assert request(target["name"],http_port,"/index.php")["status"] == 200
                    assert peer_requests()==peer_before
                    rechecked=guard.manage_guard("recheck",target,**gkw)
                    assert rechecked["state"]=="Applied",rechecked
                    restored=guard.manage_guard("restore",target,
                        expected_vhost=rechecked["vhost_sha256"],
                        expected_recovery=applied["recovery_id"],**gkw)
                    assert restored["state"] == "Restored", restored
                skw=dict(html=html,data_fd=fd,vhost_root=str(vhosts),nginx_conf=str(main),
                    public_root=str(directory/"status-assets"),nginx=NGINX,
                    runner=scoped_runner,probe=status_probe)
                # R139-01: an ordinary real 404 body identical to the
                # render is a read-only match, not an owned generation.
                served404 = parent / "public" / "404.html"
                write(served404, html)
                try:
                    same=status.preview_site_404_extension(target,locale="en",
                        rendered_sha256=rendered,vhost_root=str(vhosts),
                        nginx_conf=str(main),probe=status_probe)
                    assert same["body_sha256"]==rendered and same["body_matches_render"],same
                    assert not same["adoption_preview"]["ownership_verified"]
                    assert not same["adoption_preview"]["recovery_verified"]
                    assert not list(state.glob("*status*"))
                finally:
                    served404.unlink()
                assert status_probe(target,"404",None)==old_404
                served502=parent/"public"/"502.html"
                for code in ("404", "502", "50x"):
                    vhost_sha,_,served,raw_sha=status._source(target,code,str(vhosts),str(main))
                    assert served==str(parent/"public")
                    if code=="404":
                        pre=status.preview_site_404_extension(target,locale="en",
                            rendered_sha256=rendered,vhost_root=str(vhosts),
                            nginx_conf=str(main),probe=status_probe)
                        current=pre["body_sha256"]
                        assert current==old_404[1] and pre["page_file_sha256"] is None
                        assert not pre["body_matches_render"]
                    else:
                        def forbidden_probe(*args):
                            raise AssertionError("Unmanaged 502/50x must not request HTTP")
                        def observe():
                            plan=status.preview_site_502(target,locale="en",
                                rendered_sha256=rendered,rendered_html=html,
                                vhost_root=str(vhosts),nginx_conf=str(main),template=code)
                            checked=status.manage_site_extension("recheck",target,code=code,
                                expected_current=None,expected_vhost=None,expected_render=None,
                                expected_recovery=None,**{**skw,"probe":forbidden_probe})
                            assert checked["state"]=="Unmanaged" and not checked["runtime_verified"]
                            assert checked["verification_scope"]=="source_only"
                            assert checked["page_file_sha256"]==plan["page_file_sha256"]
                            return checked["page_file_sha256"]
                        assert observe()==hashlib.sha256(b"").hexdigest()
                        write(served502,"actual served 502")
                        current=hashlib.sha256(b"actual served 502").hexdigest()
                        assert observe()==current
                        served502.unlink()
                        served502.symlink_to(parent/"502.html")
                        try:
                            for read in (
                                lambda: status.preview_site_502(target,locale="en",
                                    rendered_sha256=rendered,rendered_html=html,
                                    vhost_root=str(vhosts),nginx_conf=str(main),template=code),
                                lambda: status.manage_site_extension("recheck",target,code=code,
                                    expected_current=None,expected_vhost=None,expected_render=None,
                                    expected_recovery=None,**{**skw,"probe":forbidden_probe})):
                                try:
                                    read()
                                except status.ExtensionError as exc:
                                    assert exc.stage=="source",exc
                                else:
                                    raise AssertionError("Uninspectable served 502 accepted")
                        finally:
                            served502.unlink()
                        if code=="502":
                            write(served502,"actual served 502")
                        else:
                            current=hashlib.sha256(b"").hexdigest()
                    params=dict(code=code,expected_current=current,
                        expected_vhost=vhost_sha,expected_render=rendered,expected_recovery=None)
                    applied=status.manage_site_extension("apply",target,**params,**skw)
                    assert applied["state"]=="Applied",applied
                    if code=="404":
                        ordinary=request(target["name"],http_port,"/missing-fixture.css")
                        assert ordinary["status"]==404 and ordinary["body"]==html, ordinary
                    assert peer_requests()==peer_before
                    params["expected_recovery"]=applied["recovery_id"]
                    restored=status.manage_site_extension("restore",target,**params,**skw)
                    assert restored["state"]==("Restored" if code=="404" else "Source Restored"),restored
                    assert status_probe(target,"404",None)==old_404
                    assert (parent/"404.html").read_text()=="unserved parent 404"
                    assert (parent/"502.html").read_text()=="unserved parent 502"
                    assert not (parent/"public"/"404.html").exists()
                    if code=="502":
                        assert served502.read_text()=="actual served 502"
                        served502.unlink()
                    assert not served502.exists()
                return {"guard":"not repeated" if ARGS.status_only else "Applied/Restored",
                    "404":"matching and differing native HTTP; Applied/Restored; real missing CSS",
                    "502":"present/absent/uninspectable; source-only Recheck; Applied/Source Restored",
                    "502_50x_recheck":"source preflight agrees; no ordinary HTTP used",
                    "50x":"Applied/Source Restored; all four proof statuses",
                    "unserved_parent":"unchanged","file_writer":"refused","peer_routes":"unchanged"}
            finally:
                os.close(fd)
        result["nested_root_runtime"] = process(main,directory,lifecycle)
        if ARGS.status_only:
            print(json.dumps(result),flush=True)
            return result
    old_headers, old_peer = process(main,directory,baseline)
    owned = directory / "private-cache"
    owned.mkdir()
    for row, ref in generated:
        path = Path(ref["cache_directory"])
        path.mkdir()
        os.chown(path,www.pw_uid,www.pw_gid)
        write(vhosts / f"0.fixture-{row['id']}.conf",ref["global_http_fragment"])
        write(vhosts/"extension"/row["name"]/"fixture-runtime.conf",ref["site_server_fragment"])
    def managed():
        out = []
        for row in selected:
            name = row["name"]
            first = request(name,tls_port,tls=True,protocol="--http2")
            second = request(name,tls_port,tls=True,protocol="--http2")
            assert first["status"] == second["status"] == 200
            assert first["headers"]["x-ach-cache"] == ["MISS"] and second["headers"]["x-ach-cache"] == ["HIT"]
            assert first["body"] == second["body"]
            assert response_semantics(first) == old_headers[name], (name,response_semantics(first),old_headers[name])
            quic = request(name,tls_port,tls=True,protocol="--http3-only")
            assert quic["protocol"] == "HTTP/3" and quic["status"] == 200, quic
            assert response_semantics(quic) == old_headers[name]
            for header in ("Cookie: fixture=1","Authorization: Bearer fixture"):
                response = request(name,tls_port,tls=True,headers=(header,))
                assert response["headers"]["x-ach-cache"] == ["BYPASS"], response
            # The global legacy ignore_headers are intentionally active; the
            # managed location must still reject every private response.
            for path in ("/private.php","/cookie.php","/vary.php","/expired.php","/accel.php"):
                a = request(name,tls_port,path,tls=True)
                b = request(name,tls_port,path,tls=True)
                assert a["status"] == b["status"] == 200
                assert a["headers"]["x-ach-cache"] == b["headers"]["x-ach-cache"] == ["MISS"], (path,a,b)
                assert a["body"] != b["body"], path
            out.append({"handler":"wpfastcgi" if row is selected[0] else "stock",
                        "header_semantics":"unchanged", "cache":"MISS/HIT",
                        "auth_cookie":"BYPASS", "private_response_pairs":5,
                        "quic":quic["protocol"]})
        assert peer_requests() == old_peer
        return out
    result["runtime"] = process(main,directory,managed)
    result["peer_routes_preserved"] = old_peer
    print(json.dumps(result),flush=True)
    return result


if __name__ == "__main__":
    if os.geteuid() != 0 or not Path(NGINX).is_file():
        raise SystemExit("Run only as root in the authorized native QA guest")
    with tempfile.TemporaryDirectory(prefix="achqa-mixed-hosts-",dir="/www") as folder:
        base = Path(folder)
        base.chmod(0o755)
        results = ([profile(base,"ir",2,1)] if ARGS.cache_force_https_only else
                   [profile(base,"nl",1,5)] if ARGS.status_only else
                   [profile(base,"ir",6,2),profile(base,"nl",1,5)])
        print(json.dumps({"profiles":results,"fixture_cleanup":"automatic on exit"}),flush=True)
