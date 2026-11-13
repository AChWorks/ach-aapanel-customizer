#!/usr/bin/env python3
"""Real native-aaPanel WooCommerce cache A/B QA, with no Nginx mutation.

Run only in an explicitly authorized isolated nonproduction guest AFTER the
primary administrator has used Customizer's guarded Cache Apply and Recheck.
Never enables, purges, reloads, restores or modifies native Nginx configuration.
It temporarily creates two real Woo customers, and verifies exact cleanup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

import qa_woocommerce_cache_runtime as woo


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_native(args, *, nginx_root="/www/server/nginx/conf",
                    vhost_root="/www/server/panel/vhost/nginx",
                    data_dir="/www/server/panel/data",
                    policy_path="/www/server/panel/plugin/ach_customizer/ach_customizer_cache_policy.py"):
    """Bound source/operation identity before creating any QA customers."""
    site_id, hostname = args.site_id, args.host
    if (not 1 <= site_id <= 2147483647 or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", hostname)):
        raise RuntimeError("Invalid native QA website identity")
    if not re.fullmatch(r"[0-9a-f]{32}", args.expected_recovery_id):
        raise RuntimeError("Expected exact applied recovery ID is required")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_policy_sha256):
        raise RuntimeError("Expected exact installed policy SHA256 is required")
    if digest(policy_path) != args.expected_policy_sha256:
        raise RuntimeError("Installed Cache policy source identity mismatch")

    journal = Path(data_dir)/("ach_customizer.cache.%d.json" % site_id)
    record = json.loads(journal.read_bytes())
    if (type(record) is not dict or record.get("schema") != 2 or
            record.get("site_id") != site_id or
            record.get("site_key") != hostname or
            record.get("php_version") != args.php_version or
            record.get("phase") != "applied" or
            record.get("op") != args.expected_recovery_id or
            not isinstance(record.get("cache_identity"), list) or
            len(record["cache_identity"]) != 2 or
            any(type(x) is not int or x <= 0 for x in record["cache_identity"])):
        raise RuntimeError("Native Cache is not the exact approved Applied generation")

    plan = woo.generate_reference(site_id, args.php_version,
                                  cache_generation=record["cache_generation"])
    if (record["cache_directory"] != plan["cache_directory"] or
            record["global_sha"] != hashlib.sha256(plan["global_http_fragment"].encode()).hexdigest() or
            record["extension_sha"] != hashlib.sha256(plan["site_server_fragment"].encode()).hexdigest()):
        raise RuntimeError("Saved Cache policy does not match installed generation")
    cache_root = Path(record["cache_directory"])
    if not cache_root.is_dir() or cache_root.is_symlink():
        raise RuntimeError("Native site-owned cache directory is missing or aliased")
    identity = cache_root.stat()
    if [identity.st_dev, identity.st_ino] != record["cache_identity"]:
        raise RuntimeError("Native site-owned cache directory identity changed")

    vhost = Path(vhost_root)/(hostname+".conf")
    rewrite = Path(vhost_root).parent/"rewrite"/(hostname+".conf")
    main = Path(nginx_root)/"nginx.conf"
    php = Path(nginx_root)/("enable-php-"+args.php_version+".conf")
    fastcgi = Path(nginx_root)/"fastcgi.conf"
    pathinfo = Path(nginx_root)/"pathinfo.conf"
    global_conf = Path(vhost_root)/("0.ach_customizer_cache_%d.conf" % site_id)
    extension_conf = Path(vhost_root)/"extension"/hostname/("ach_customizer_cache_%d.conf" % site_id)
    native_sources = [journal,vhost,rewrite,main,php,fastcgi,pathinfo,global_conf,
                      extension_conf,Path(policy_path)]
    for source in native_sources:
        if not source.is_file() or source.is_symlink():
            raise RuntimeError("Native Cache QA source missing/aliased: "+source.name)
    if (stat.S_IMODE(global_conf.stat().st_mode) != 0o600 or
            stat.S_IMODE(extension_conf.stat().st_mode) != 0o600):
        raise RuntimeError("Installed Cache source ownership mode is unexpected")
    content=vhost.read_text(encoding="utf-8")
    if (content.count("include enable-php-"+args.php_version+".conf;") != 1 or
            re.search(r"include\s+enable-php-[^;]*wpfastcgi\.conf;",content) or
            content.count("include "+str(Path(vhost_root)/"extension"/hostname/"*.conf")+";") != 1):
        raise RuntimeError("Native VHost does not use the supported stock PHP/extension sources")
    if (digest(global_conf) != record["global_sha"] or
            digest(extension_conf) != record["extension_sha"] or
            digest(main) != record["main_sha"] or
            hashlib.sha256(vhost.read_bytes()+b"\0"+rewrite.read_bytes()).hexdigest() != record["vhost_sha"] or
            hashlib.sha256(php.read_bytes()+b"\0"+fastcgi.read_bytes()+b"\0"+pathinfo.read_bytes()).hexdigest() != record["php_sha"]):
        raise RuntimeError("Native Cache source differs from saved approved generation")
    check = subprocess.run([args.nginx,"-t"],capture_output=True,text=True,timeout=12)
    if check.returncode:
        raise RuntimeError("Native Nginx syntax check failed; do not test sessions")
    return {str(source):digest(source) for source in native_sources}


def probe_https(args):
    """Check validated TLS, native site identity and Cache before user writes."""
    ca = Path(args.tls_ca_file or "")
    if (not args.tls_ca_file or not ca.is_absolute() or
            not ca.is_file() or ca.is_symlink()):
        raise RuntimeError("HTTPS native QA requires an absolute regular CA certificate file")
    try:
        result = woo.Client(443, args.host, tls_ca_file=str(ca)).get("/")
    except (OSError, ValueError) as exc:
        raise RuntimeError("HTTPS native TLS/site readiness failed before customer creation") from exc
    if (result["status"] != 200 or result["site"] != str(args.site_id) or
            result["cache"] not in ("MISS", "HIT")):
        raise RuntimeError("HTTPS native listener lacks the approved site Cache response")
    return result["cache"]


def run(args):
    if (os.geteuid() != 0 or not args.explicit_nonproduction_qa or
            socket.gethostname() != args.expected_guest_hostname):
        raise RuntimeError("Authorized isolated QA guest/root/explicit opt-in required")
    root=Path(args.site_root)
    if (not root.is_dir() or not root.is_absolute() or
            str(root) != os.path.realpath(root)):
        raise RuntimeError("Invalid registered native WordPress root")
    woo.assert_store_site(root,args.host,args.site_id)
    php=args.wp_php or "/www/server/php/"+args.php_version+"/bin/php"
    if not Path(php).is_file():
        raise RuntimeError("Native QA WordPress PHP binary is missing")
    before=snapshot_native(args)
    transport = getattr(args, "transport", "http")
    if transport not in ("http", "https", "both"):
        raise RuntimeError("Unsupported native QA transport")
    https_ready = None
    if transport in ("https", "both"):
        https_ready = probe_https(args)
    elif getattr(args, "tls_ca_file", None):
        raise RuntimeError("CA option requires HTTPS transport")
    temp=Path(tempfile.mkdtemp(prefix="ach-woo-native-ab-"))
    temp.chmod(0o700)
    run_id=None
    removed=0
    verified={}
    safe_remove=True
    try:
        try:
            run_id=woo.claim_qa_accounts(php,root,temp)
            users=woo.validate_prepared_accounts(
                woo.wp_action(php,root,{"op":"prepare","run_id":run_id}),run_id)
            if transport in ("http", "both"):
                http_checks = woo.exercise_store_clients(
                    80,args.host,args.site_id,users,allow_pre_warmed=True)
                verified = http_checks if transport == "http" else {"http": http_checks}
            if transport in ("https", "both"):
                https_checks = woo.exercise_store_clients(
                    443,args.host,args.site_id,users,allow_pre_warmed=True,
                    tls_ca_file=args.tls_ca_file)
                verified = (https_checks if transport == "https"
                            else {**verified, "https": https_checks})
        finally:
            errors=[]
            if run_id is not None:
                try:
                    removed=woo.cleanup_qa_accounts(php,root,run_id)
                except Exception as exc:
                    safe_remove=False
                    errors.append("Exact customer cleanup/recheck failed: %s; manifest: %s" %
                                  (str(exc),temp/"qa-account-recovery.json"))
            try:
                after=snapshot_native(args)
                if after != before:
                    errors.append("Native site/cache source changed during A/B acceptance")
            except Exception as exc:
                errors.append("Native post-test source verification failed: "+str(exc))
            if errors:
                safe_remove=False
                raise RuntimeError("; ".join(errors))
    finally:
        if safe_remove:
            shutil.rmtree(temp)
        else:
            print("Native Woo QA incomplete; task-owned recovery retained: "+str(temp),
                  file=sys.stderr)
    print(json.dumps({"result":"PASS","checks":verified,"native_qa":True,
                      "runner_direct_nginx_mutations":0,
                      "transport":transport,
                      "https_preflight_cache":https_ready,
                      "pre_post_native_source_sha_match":True,
                      "native_config_sources_verified":len(before),
                      "ephemeral_qa_users_removed":removed,
                      "temporary_test_files_removed":True},sort_keys=True))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--site-id",type=int,required=True)
    p.add_argument("--host",required=True)
    p.add_argument("--site-root",required=True)
    p.add_argument("--php-version",choices=("81","85"),default="85")
    p.add_argument("--expected-guest-hostname",required=True)
    p.add_argument("--expected-recovery-id",required=True)
    p.add_argument("--expected-policy-sha256",required=True)
    p.add_argument("--nginx",default="/www/server/nginx/sbin/nginx")
    p.add_argument("--wp-php",default=None)
    p.add_argument("--transport",choices=("http","https","both"),default="http")
    p.add_argument("--tls-ca-file",default=None,
                   help="Absolute PEM CA for validated site-SNI TLS on native port 443")
    p.add_argument("--explicit-nonproduction-qa",action="store_true")
    run(p.parse_args())
