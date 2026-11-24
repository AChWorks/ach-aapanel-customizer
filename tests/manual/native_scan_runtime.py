#!/usr/bin/env python3
"""Real isolated Nginx scanner lifecycle. Run only on retained QA or equivalent
non-production Linux host with Nginx Lua, HTTP/2+3, curl and openssl.
Uses an independent master, loopback-only listeners and task-owned files.
Never changes installed Nginx config, native sites, system services or firewall.
Pass the exact candidate native ZIP (imports directly from ZIP).
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import os
import pwd
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(sys.argv[1]).resolve()) + "/ach_customizer")
import ach_customizer_nginx_security as guard

NGINX = "/www/server/nginx/sbin/nginx"
LUA_PATH = "/www/server/nginx/lib/lua/?.lua;;"
POLICY = {"maxretry": 3, "findtime": 3, "bantime": 4}
NAME = "scan-a.invalid"
PEER = "scan-b.invalid"

def check(label, actual, expected):
    assert actual == expected, (label, actual, expected)
    print("PASS", label, actual, flush=True)

def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

class Upstream(BaseHTTPRequestHandler):
    calls = 0
    def do_GET(self):
        Upstream.calls += 1
        self.send_response(200)
        self.send_header("Content-Length", "6")
        self.end_headers()
        self.wfile.write(b"origin")
    def log_message(self, *_args):
        pass

def run():
    with tempfile.TemporaryDirectory(prefix="ach-native-scan-") as raw:
        d = Path(raw)
        d.chmod(0o755)
        vhosts = d / "vhosts"; vhosts.mkdir()
        state = d / "state"; state.mkdir(mode=0o700)
        conf = d / "nginx.conf"
        startup_log = d / "startup.log"
        cert, key = d / "cert.pem", d / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-nodes", "-days", "1", "-subj", "/CN=" + NAME,
                        "-keyout", str(key), "-out", str(cert)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        http_port, tls_port = port(), port()
        while tls_port == http_port:
            tls_port = port()
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        t = threading.Thread(target=upstream.serve_forever, daemon=True)
        t.start()
        # Use the already-running native PHP-FPM socket only for synthetic
        # files under this fixture. No service/pool or native site is edited.
        php_socket = Path("/tmp/php-cgi-85.sock")
        assert php_socket.is_socket(), "Native PHP 8.5 socket is unavailable"
        php_marker = d / "php-calls"
        php_marker.touch()
        www = pwd.getpwnam("www")
        os.chown(php_marker, www.pw_uid, www.pw_gid)
        php_marker.chmod(0o600)
        def native_site(site_id, name):
            root = d / name; root.mkdir()
            ext = vhosts / "extension" / name; ext.mkdir(parents=True)
            (root / "backups").mkdir()
            php = ('<?php file_put_contents(' + repr(str(php_marker))
                   + ', "called\\n", FILE_APPEND | LOCK_EX); echo "fixture-php";')
            for path in (root / "health.php", root / "backups/proof.php"):
                path.write_text(php)
            if site_id == 102:
                # Task-only deterministic allocation, not a traffic flood.
                # Fill the slab class used by IPv4 keys, then release only
                # the synthetic keys (never flush a real ban or counter).
                (ext / "fixture-capacity.conf").write_text("""
location = /fixture-fill {
    content_by_lua_block {
        local d = ngx.shared.ach_customizer_scan_state
        for i=1,100000 do
            local ok, err = d:safe_add(string.format([[fixture:%050d]], i), 1, 60)
            if not ok then ngx.say(i-1, [[:]], err); return end
        end
        ngx.say([[not-full]])
    }
}
location = /fixture-release {
    content_by_lua_block {
        local d = ngx.shared.ach_customizer_scan_state
        for i=1,tonumber(ngx.var.arg_count) do
            d:delete(string.format([[fixture:%050d]], i))
        end
        ngx.say([[released]])
    }
}
""")
            # Representative native extension appears before location selection.
            # Only the test loopback addresses may present a real-IP header.
            (vhosts / (name + ".conf")).write_text(
                "server {\n"
                f"listen 127.0.0.1:{http_port};\n"
                f"listen [::1]:{http_port};\n"
                f"listen 127.0.0.1:{tls_port} ssl;\n"
                f"listen 127.0.0.1:{tls_port} quic"
                + (" reuseport" if site_id == 101 else "") + ";\n"
                "http2 on;\n"
                f"ssl_certificate {cert};\nssl_certificate_key {key};\n"
                f"server_name {name};\nroot {root};\n"
                f"include {ext}/*.conf;\n"
                "set_real_ip_from 127.0.0.1;\nset_real_ip_from ::1;\n"
                "real_ip_header X-Real-IP;\n"
                "location ^~ /uploads/ { return 200 'location'; }\n"
                "location ~ [.]php$ { include /www/server/nginx/conf/fastcgi.conf; "
                "fastcgi_pass unix:/tmp/php-cgi-85.sock; }\n"
                + (f"location / {{ proxy_pass http://127.0.0.1:{upstream.server_port}; "
                   "proxy_cache fixture_cache; proxy_cache_valid 200 1m; "
                   "add_header X-Fixture-Cache $upstream_cache_status; }\n"
                   if site_id == 101 else "location / { return 200 'peer'; }\n")
                + "}\n")
            return {"id":site_id, "name":name, "path":str(root), "status":"1",
                    "bound_domains":[{"name":name,"port":80}]}
        site = native_site(101, NAME)
        peer = native_site(102, PEER)
        conf.write_text("daemon off;\nworker_processes 2;\nuser www www;\n"
                        f"pid {d}/nginx.pid;\nerror_log {d}/error.log notice;\n"
                        "events { worker_connections 128; }\nhttp {\n"
                        f' lua_package_path "{LUA_PATH}";\n'
                        " access_log off;\n"
                        + "".join(f" {part}_temp_path {d}/{part}-temp;\n"
                                  for part in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
                        + f" proxy_cache_path {d}/cache keys_zone=fixture_cache:1m inactive=1m;\n"
                        f" include {vhosts}/*.conf;\n}}\n")
        args = [NGINX, "-p", raw + "/", "-e", str(startup_log), "-c", str(conf)]
        def runner(argv, **kwargs):
            return subprocess.run([argv[0], "-p", raw + "/", "-e", str(startup_log)] + argv[1:], **kwargs)
        subprocess.run(args + ["-t"], check=True)
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
        def request(path="/", *, host=NAME, ip="198.51.100.1", dest="127.0.0.1", source=None):
            c = http.client.HTTPConnection(dest, http_port, timeout=3,
                                            source_address=(source, 0) if source else None)
            try:
                headers = {"Host":host,"Connection":"close"}
                if ip is not None: headers["X-Real-IP"] = ip
                c.request("GET", path, headers=headers)
                r = c.getresponse()
                return r.status, r.read(), r.getheader("X-Fixture-Cache")
            finally:
                c.close()
        def status(path="/", **kw): return request(path, **kw)[0]
        def probe(s, op, kind): return guard._probe(s, op, kind, port=http_port)
        def operate(action, s=site, **kw):
            return guard.manage_guard(action, s, data_fd=fd,
                vhost_root=str(vhosts), nginx_conf=str(conf), nginx=NGINX,
                runner=runner, probe=probe, **kw)
        def enable(s=site, **kw):
            p = operate("preview", s, **kw)
            check("read-only eligible "+s["name"], p["state"], "Unmanaged")
            return operate("apply", s, approved=True,
                           expected_vhost=p["vhost_sha256"],
                           expected_proposal=p["proposal_sha256"], **kw)
        def restore(s=site):
            r=operate("recheck",s)
            return operate("restore",s,approved=True,
                           expected_vhost=r["vhost_sha256"],
                           expected_recovery=r["recovery_id"])
        def curl(protocol, ip, path="/", host=NAME):
            option={"2":"--http2","3":"--http3-only"}[protocol]
            res=subprocess.run(["curl","--noproxy","*","--silent","--show-error",
                "--max-time","5","-k",option,"--resolve",
                f"{host}:{tls_port}:127.0.0.1","-H","X-Real-IP: "+ip,
                "-o","/dev/null","-w","%{http_version} %{http_code}",
                f"https://{host}:{tls_port}{path}"],
                text=True,capture_output=True,check=True).stdout.split()
            check("negotiated HTTP/"+protocol,res[0],protocol)
            return int(res[1])
        try:
            for i in range(40):
                if proc.poll() is not None: raise RuntimeError("Isolated Nginx exited")
                try:
                    if status(ip=None)==200: break
                except OSError: time.sleep(.1)
            else: raise RuntimeError("Isolated Nginx not ready")
            check("baseline origin", status(), 200)
            check("native PHP baseline", request("/health.php")[1], b"fixture-php")
            check("sensitive PHP baseline before Guard", request("/backups/proof.php")[1], b"fixture-php")
            check("PHP actually executed twice", php_marker.read_text().splitlines(), ["called", "called"])
            result=enable(scan_policy=POLICY,block_xmlrpc=True)
            check("real Apply",result["state"],"Applied")
            check("verified active policy",operate("recheck")["scan_policy"],POLICY)
            check("single exact shared declaration",(vhosts/guard.SCAN_ZONE_FILE).read_bytes(),guard.SCAN_ZONE_BYTES)
            check("cache request",status("/cached"),200)
            check("cache hit",request("/cached")[2],"HIT")
            calls=Upstream.calls
            for _ in range(4):check("ordinary not counted",status("/cached"),200)
            for _ in range(4):check("optional XML-RPC not counted",status("/xmlrpc.php"),403)
            check("still ordinary",status("/cached"),200)
            for path in ("/.env","/nested/.env","/uploads/test.php"):
                check("pre-location sensitive path",status(path),403)
            check("blocked before cached response",status("/cached"),429)
            check("no upstream call",Upstream.calls,calls)
            before_php = php_marker.read_bytes()
            for _ in range(3):
                check("sensitive denied before FastCGI",status("/backups/proof.php",ip="198.51.100.20"),403)
            check("blocked before FastCGI",status("/health.php",ip="198.51.100.20"),429)
            check("no PHP execution after denial",php_marker.read_bytes(),before_php)
            check("other client can execute PHP",request("/health.php",ip="198.51.100.21")[1],b"fixture-php")
            check("peer unaffected",status(host=PEER),200)
            check("other IP unaffected",status(ip="198.51.100.2"),200)
            for _ in range(3):check("IPv6 attack",status("/.env",ip="2001:db8::1",dest="::1"),403)
            check("IPv6 blocked",status(ip="2001:db8::1",dest="::1"),429)
            with ThreadPoolExecutor(max_workers=8) as pool:
                values=list(pool.map(lambda _:status("/.env",ip="198.51.100.3"),range(12)))
            assert all(x in (403,429) for x in values),values
            check("concurrent workers share block",status(ip="198.51.100.3"),429)
            for _ in range(3):check("untrusted header not selected",status("/.env",ip="198.51.100.4",source="127.0.0.2"),403)
            check("untrusted sender blocked",status(ip="198.51.100.4",source="127.0.0.2"),429)
            check("forged identity not blocked",status(ip="198.51.100.4"),200)
            # A native reload preserves a current block, not just the source.
            subprocess.run(args+["-s","reload"],check=True)
            check("reload preserves active block",status(ip="198.51.100.3"),429)
            time.sleep(4.3)
            check("block expires",status(),200)
            check("IPv6 block expires",status(ip="2001:db8::1",dest="::1"),200)
            check("fixed window first hit",status("/.env",ip="198.51.100.5"),403)
            time.sleep(3.2)
            for _ in range(2):check("new observation window",status("/.env",ip="198.51.100.5"),403)
            check("expired counter not carried",status(ip="198.51.100.5"),200)
            # Same in-memory policy across the real HTTP/2 and HTTP/3 paths.
            check("HTTP/2 malicious",curl("2","198.51.100.6","/.env"),403)
            check("HTTP/3 malicious",curl("3","198.51.100.6","/.env"),403)
            check("HTTP/2 third hit",curl("2","198.51.100.6","/.env"),403)
            check("HTTP/3 shared block",curl("3","198.51.100.6"),429)
            check("HTTP/2 peer unaffected",curl("2","198.51.100.6",host=PEER),200)
            peer_result=enable(peer,scan_policy=POLICY)
            check("second site independent Apply",peer_result["state"],"Applied")
            for _ in range(3):check("peer hit",status("/.env",host=PEER,ip="198.51.100.7"),403)
            check("peer own block",status(host=PEER,ip="198.51.100.7"),429)
            check("same IP on first site",status(ip="198.51.100.7"),200)
            check("first site exact Restore",restore()["state"],"Restored")
            check("first site no guard",status("/.env"),200)
            check("second site remains applied",operate("recheck",peer)["state"],"Applied")
            check("peer Restore",restore(peer)["state"],"Restored")
            # Reapply creates a new generation. Missing shared zone is a
            # runtime failure; static protection and exact Restore remain.
            capacity_policy = dict(POLICY, bantime=60)
            p=operate("preview",scan_policy=capacity_policy)
            r=operate("apply",approved=True,scan_policy=capacity_policy,
                      expected_vhost=p["vhost_sha256"],expected_proposal=p["proposal_sha256"])
            check("new generation",r["recovery_id"] != result["recovery_id"],True)
            for _ in range(3):check("capacity fixture establishes ban",status("/.env",ip="198.51.100.30"),403)
            check("ban before saturation",status(ip="198.51.100.30"),429)
            filled = request("/fixture-fill",host=PEER)[1].decode().strip()
            amount, why = filled.split(":",1)
            check("bounded shared zone reaches capacity",why,"no memory")
            assert 0 < int(amount) < 100000, filled
            print("PASS synthetic shared allocations", amount, flush=True)
            check("active ban survives safe allocation pressure",status(ip="198.51.100.30"),429)
            denied = request("/.env",ip="198.51.100.31")
            check("capacity fallback static 403",denied[0],403)
            check("capacity fallback proof",denied[1].endswith(guard.SCAN_FALLBACK.encode()),True)
            check("unblocked ordinary request under pressure",status(ip="198.51.100.31"),200)
            check("peer ordinary request under pressure",status(host=PEER),200)
            check("release only synthetic capacity keys",request("/fixture-release?count="+amount,host=PEER)[1].strip(),b"released")
            check("active ban survives fixture release",status(ip="198.51.100.30"),429)
            for _ in range(3):check("counter recovers after capacity release",status("/.env",ip="198.51.100.31"),403)
            check("new block after capacity release",status(ip="198.51.100.31"),429)
            (vhosts/guard.SCAN_ZONE_FILE).unlink()
            subprocess.run(args+["-t"],check=True)
            subprocess.run(args+["-s","reload"],check=True)
            deadline=time.monotonic()+4
            while True:
                rr=request("/.env",ip=None)
                if rr[1].endswith(guard.SCAN_FALLBACK.encode()): break
                if time.monotonic()>deadline:raise AssertionError(rr)
                time.sleep(.1)
            check("missing zone keeps static denial",rr[0],403)
            check("ordinary fallback allowed",status(ip="198.51.100.8"),200)
            check("exact recovery after zone loss",operate("recheck")["state"],"Recovery Required")
            check("fallback Restore",restore()["state"],"Restored")
            subprocess.run(args+["-t"],check=True)
            check("peer after cleanup",status(host=PEER),200)
        finally:
            os.close(fd)
            # Only the isolated foreground process we started; never use
            # systemctl or the origin Nginx PID.
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
            upstream.shutdown();upstream.server_close();t.join(timeout=2)
            print("isolated master stopped",proc.poll() is not None,flush=True)
    print("PASS isolated runtime fixture cleaned",not Path(raw).exists(),flush=True)

if __name__ == "__main__":
    run()
