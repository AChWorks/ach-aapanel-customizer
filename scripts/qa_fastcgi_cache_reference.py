#!/usr/bin/env python3
"""Disposable native Nginx/PHP-FPM smoke of the reference-only cache policy.

Run only inside the authorized isolated aaPanel QA guest as root; never on
Production. Creates a unique temporary Nginx configuration, two synthetic PHP
sites and two physical cache directories, runs a private loopback Nginx
listener, verifies cache/response and site-purge isolation, then quits only
this Nginx instance and removes only the test-owned temporary workspace.
Does not change installed aaPanel plugin, real VHosts, native cache or FPM.
"""

import argparse
import os
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                        "plugin" / "ach_customizer"))
from ach_customizer_cache_policy import generate_reference


PHP = r'''<?php
header('Content-Type: text/plain');
if (strpos($_SERVER['REQUEST_URI'], '/cookie-response') === 0) {
    header('Set-Cookie: qa_probe=synthetic; Path=/');
}
if (strpos($_SERVER['REQUEST_URI'], '/private-response') === 0) {
    header('Cache-Control: private, no-store');
}
if (strpos($_SERVER['REQUEST_URI'], '/max-age-zero') === 0) {
    header('Cache-Control: public, max-age=0');
}
if (strpos($_SERVER['REQUEST_URI'], '/vary-response') === 0) {
    header('Vary: Accept-Language');
}
if (strpos($_SERVER['REQUEST_URI'], '/expires-zero') === 0) {
    header('X-Accel-Expires: 0');
}
echo $_SERVER['HTTP_HOST'] . ':' . $_SERVER['REQUEST_URI'] . ':' .
     bin2hex(random_bytes(8));
'''


def render_config(tmp, port, plans):
    http = "\n".join(p["global_http_fragment"] for p in plans)
    sites = []
    for site_id, hostname, plan in ((7, "qa-cache-a.test", plans[0]),
                                    (8, "qa-cache-b.test", plans[1])):
        docroot = tmp / ("site-" + str(site_id))
        docroot.mkdir(mode=0o755)
        (docroot / "index.php").write_text(PHP, encoding="utf-8")
        docroot.chmod(0o755)
        sites.append(
            "server {\n listen 127.0.0.1:%d;\n server_name %s;\n"
            " root %s;\n index index.php;\n"
            " location / { try_files $uri $uri/ /index.php?$args; }\n"
            "%s\n}\n" % (
                port, hostname, docroot, plan["site_server_fragment"]))
    return (
        "user www www;\nworker_processes 1;\n"
        "pid %s;\nerror_log %s notice;\n"
        "events { worker_connections 128; }\n"
        "http {\n access_log off;\n"
        "lua_package_path \"/www/server/nginx/lib/lua/?.lua;;\";\n"
        "include /www/server/nginx/conf/mime.types;\n"
        "include %s;\n"
        # Model the actual aaPanel global response-header-ignore pattern.
        "fastcgi_ignore_headers Cache-Control Expires Set-Cookie;\n"
        "fastcgi_cache_key \"$scheme$request_method$host$request_uri\";\n"
        "%s\n%s\n}\n" % (
            tmp / "nginx.pid", tmp / "nginx.error.log",
            tmp / "fastcgi.conf", http, "\n".join(sites))
    )


def request(port, hostname, path="/", *, method="GET", headers=None):
    hdr = {"Host": hostname}
    hdr.update(headers or {})
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path),
        headers=hdr, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.headers.get("X-ACh-Cache"), resp.read().decode()


def assert_pair(port, host, path, expected, *, headers=None):
    first = request(port, host, path, headers=headers)
    second = request(port, host, path, headers=headers)
    if first[0] != 200 or second[0] != 200:
        raise AssertionError((host, path, first, second))
    if [first[1], second[1]] != list(expected):
        raise AssertionError(
            "%s %s cache statuses %r, expected %r" %
            (host, path, [first[1], second[1]], expected))
    if expected[1] == "HIT":
        assert first[2] == second[2], (host, path, first, second)
    else:
        assert first[2] != second[2], (host, path, first, second)
    return first, second


def run(nginx, php_version):
    if os.geteuid() != 0:
        raise SystemExit("QA script needs root inside the isolated guest")
    if php_version not in ("81", "85"):
        raise SystemExit("Only QA-verified PHP 8.1/8.5 adapters supported")
    for path in (Path(nginx), Path("/www/server/nginx/conf/fastcgi.conf"),
                 Path("/tmp/php-cgi-" + php_version + ".sock")):
        if not path.exists():
            raise SystemExit("Required guest Nginx/PHP85 file/socket missing: " + str(path))
    www = pwd.getpwnam("www")
    with tempfile.TemporaryDirectory(prefix="ach-cache-reference-") as td:
        tmp = Path(td)
        tmp.chmod(0o755)
        (tmp / "logs").mkdir(mode=0o755)  # Nginx binary opens prefix/logs before parsing error_log.
        copy = tmp / "fastcgi.conf"
        shutil.copyfile("/www/server/nginx/conf/fastcgi.conf", copy)
        copy.chmod(0o644)
        cache_root = str(tmp / "cache")
        (tmp / "cache").mkdir(mode=0o755)
        plans = [
            generate_reference(n, php_version, cache_root=cache_root)
            for n in (7, 8)
        ]
        for plan in plans:
            directory = Path(plan["cache_directory"])
            directory.mkdir(mode=0o750)
            os.chown(directory, www.pw_uid, www.pw_gid)
            directory.chmod(0o750)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        conf = tmp / "nginx.conf"
        conf.write_text(render_config(tmp, port, plans), encoding="utf-8")
        config_args = [nginx, "-p", str(tmp) + "/", "-c", str(conf)]
        checked = subprocess.run([*config_args, "-t"],
                                 capture_output=True, text=True)
        if checked.returncode:
            raise AssertionError(
                "Native Nginx -t failed: " + checked.stderr[-2000:])
        started = False
        try:
            running = subprocess.run(config_args,
                                     capture_output=True, text=True)
            if running.returncode:
                raise AssertionError(
                    "Isolated Nginx failed: " + running.stderr[-2000:])
            started = True
            for _ in range(30):
                try:
                    request(port, "qa-cache-a.test")
                    break
                except (ConnectionError, OSError):
                    time.sleep(0.1)
            else:
                raise AssertionError("Nginx loopback listener not ready")
            # Warm independent per-site cache objects.
            a_first, a_hit = assert_pair(
                port,"qa-cache-a.test","/",("HIT","HIT"))
            b_first, b_hit = assert_pair(
                port,"qa-cache-b.test","/",("MISS","HIT"))
            assert a_hit[2] != b_hit[2]
            # All private request categories must not read or write cache.
            private = [
                ("/", {"Cookie":"wordpress_logged_in_qa=synthetic"}),
                ("/", {"Cookie":"woocommerce_items_in_cart=1"}),
                ("/", {"Authorization":"Bearer qa-synthetic"}),
                ("/", {"Cache-Control":"no-cache"}),
                ("/cart/", {}), ("/checkout/",{}),
                ("/my-account/", {}), ("/wp-admin/",{}),
                ("/wp-json/wc/v3/orders", {}),
                ("/api/webhook", {}), ("/?add-to-cart=1", {})
            ]
            for path, headers in private:
                assert_pair(port,"qa-cache-a.test",path,
                            ("BYPASS","BYPASS"),headers=headers)
            for path in ("/cookie-response", "/private-response",
                         "/max-age-zero", "/vary-response", "/expires-zero"):
                assert_pair(port,"qa-cache-a.test",path,("MISS","MISS"))
            # A POST must bypass even the warm public URL.
            first = request(port,"qa-cache-a.test","/",method="POST")
            assert first[1] in ("BYPASS", None), first
            # Simulate *only* a site-owned unlink_files/Purge All, NEVER
            # delete a shared aaPanel directory or Nginx Helper data.
            acache = Path(plans[0]["cache_directory"])
            bcache = Path(plans[1]["cache_directory"])
            assert acache.is_dir() and bcache.is_dir()
            files_a = list(acache.rglob("*"))
            files_b = list(bcache.rglob("*"))
            assert any(x.is_file() for x in files_a), "A was not cached"
            assert any(x.is_file() for x in files_b), "B was not cached"
            for entry in sorted(files_a, key=lambda p: len(p.parts), reverse=True):
                if entry.is_file():
                    entry.unlink()
                elif entry.is_dir():
                    entry.rmdir()
            a_after = request(port, "qa-cache-a.test")
            b_after = request(port, "qa-cache-b.test")
            assert a_after[1] == "MISS", a_after
            assert b_after[1] == "HIT" and b_after[2] == b_hit[2], b_after
            print("NATIVE PASS: nginx -t; independent site A/B MISS-HIT; private "
                  "authorization/cookie/route/query BYPASS; upstream response "
                  "Set-Cookie/private/max-age=0/Vary/X-Accel-Expires MISS-MISS; "
                  "POST bypass; physical A-only removal left B HIT.")
            print("POLICY IDs:", plans[0]["proposal_sha256"],
                  plans[1]["proposal_sha256"])
        finally:
            if started:
                stopped = subprocess.run(
                    [*config_args, "-s", "quit"],
                    capture_output=True, text=True)
                if stopped.returncode:
                    raise AssertionError(
                        "Isolated Nginx quit unconfirmed: " + stopped.stderr[-1500:])
                for _ in range(40):
                    if not (tmp/"nginx.pid").exists():
                        break
                    time.sleep(0.1)
                if (tmp/"nginx.pid").exists():
                    raise AssertionError("Isolated Nginx process not confirmed stopped")
    print("CLEANUP PASS: only script-owned Nginx process and temporary root retired")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--nginx", default="/www/server/nginx/sbin/nginx")
    p.add_argument("--php-version", choices=("81", "85"), default="85")
    args = p.parse_args()
    run(args.nginx, args.php_version)
