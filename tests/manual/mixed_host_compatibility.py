#!/usr/bin/env python3
"""Run sanitized IR/NL-shaped source and real Nginx/PHP-FPM acceptance.

Only on the authorized retained aaPanel QA guest. No live aaPanel DB/VHost,
production config, private site, global cache, panel worker or service
mutation. Start/stop a task-owned Nginx process with temporary config/cache
and loopback-only high ports; use the existing native PHP-FPM socket for
synthetic PHP pages. This is a runtime fixture, not a native UI Apply test.
"""
import argparse
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
ARGS = PARSER.parse_args()
sys.path.insert(0, str(ARGS.plugin_root))
import ach_customizer_cache_audit as audit
import ach_customizer_cache_manage as manage
import ach_customizer_cache_policy as policy
import ach_customizer_cache_wordpress as wp
import ach_customizer_wp_settings as settings
import ach_customizer_monitor as monitor
import ach_customizer_vhost_drift as drift

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


def request(name, port, path="/index.php", *, tls=False, protocol=None, headers=()):
    url = ("https" if tls else "http") + f"://{name}:{port}{path}"
    args = ["curl", "--noproxy", "*", "--silent", "--show-error", "--max-time", "8",
            "--connect-timeout", "3", "--resolve", f"{name}:{port}:127.0.0.1",
            "-k", "-D", "-", url]
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
            while not (directory / "fixture.pid").is_file():
                if child.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Isolated Nginx did not start: " +
                                       (directory / "error.log").read_text(errors="replace")[-1500:])
                time.sleep(.1)
            assert int((directory / "fixture.pid").read_text()) == child.pid
            return callback()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


def profile(base, label, wp_count, php_count):
    directory = base / label
    directory.mkdir()
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
         "-keyout", str(key), "-out", str(cert), "-subj", "/CN=qa.invalid", "-days", "1"])
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
        row = {"id": 100+i, "name": name, "path": str(root), "status": 1,
               "bound_domains": [{"name": name, "port": 80}, {"name": name, "port": 443}]}
        rows.append(row)
        for leaf in ("index.php", "private.php", "cookie.php", "vary.php", "expired.php", "accel.php", "app/health.php"):
            write(root / leaf, PHP)
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
          f"error_log {directory}/error.log notice;\nevents {{ worker_connections 128; }}\n"
          f"http {{\n access_log off;\n{extra} include {vhosts}/*.conf;\n}}\n")
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
    assert result["vhost_file_match"] == len(rows)
    pool = directory / "pool.conf"
    write(pool, "[www]\nlisten = /tmp/php-cgi-85.sock\n")
    impact = monitor.inspect_php_fpm_site_impact(panel, "85", pool,
        vhost_root=str(vhosts), nginx_conf_root=str(confdir), rewrite_root=str(rewrite))
    assert impact["state"] == "File Mapping" and len(impact["matched_sites"]) == len(rows), impact
    result["fpm_attributed"] = len(impact["matched_sites"])
    # The stock site chosen for runtime has no foreign selected-route writer.
    selected = [rows[0], rows[-1]]
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
        results = [profile(base,"ir",6,2),profile(base,"nl",1,5)]
        print(json.dumps({"profiles":results,"fixture_cleanup":"automatic on exit"}),flush=True)
