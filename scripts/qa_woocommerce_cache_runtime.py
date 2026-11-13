#!/usr/bin/env python3
"""Isolated real WooCommerce FastCGI cache check in authorized aaPanel QA only.

Runs a loopback Nginx with a temporary cache directory; it does not edit
native aaPanel VHosts, live Nginx settings, customer accounts or cache trees.
Creates two disposable WordPress customers and removes them in finally.
The real store database is used; do NOT run on a production site.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from http.cookies import SimpleCookie

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
from ach_customizer_cache_policy import generate_reference  # noqa: E402


# All inputs are fixed code/actions; no credentials or account cookies in argv.
WP_ACTION = r"""
define('WP_USE_THEMES', false);
chdir($argv[1]);
require 'wp-load.php';
$in = json_decode(stream_get_contents(STDIN), true);
if (!is_array($in) || !function_exists('WC')) { fwrite(STDERR,"Woo unavailable"); exit(3); }
add_filter('pre_wp_mail','__return_true');
$run_id = $in['run_id'] ?? null;
if (!is_string($run_id) || !preg_match('/\A[0-9a-f]{32}\z/', $run_id)) {
  fwrite(STDERR,'Invalid QA run identity'); exit(3);
}
$names = array('a'=>'achqa_cache_a_'.$run_id, 'b'=>'achqa_cache_b_'.$run_id);
if ($in['op'] === 'observe') {
  $present = array();
  foreach ($names as $login) {
    if (get_user_by('login', $login)) $present[] = $login;
  }
  echo json_encode(array('present'=>$present));
} elseif ($in['op'] === 'prepare') {
  $users = array(); $products = array();
  foreach (get_posts(array('post_type'=>'product','post_status'=>'publish','posts_per_page'=>30)) as $p) {
    $product = wc_get_product($p->ID);
    if ($product && $product->is_type('simple') && $product->is_purchasable())
      $products[] = array('id'=>$p->ID,'name'=>$p->post_title);
  }
  if (count($products)<2) { fwrite(STDERR,'Need two buyable real Woo products'); exit(4); }
  // Check both names BEFORE any write, not after creating the first user.
  foreach ($names as $login) {
    if (get_user_by('login',$login)) { fwrite(STDERR,'QA identity already in use'); exit(4); }
  }
  $created = array();
  try {
    foreach ($names as $suffix=>$user) {
      $id = wp_insert_user(array('user_login'=>$user,'user_pass'=>wp_generate_password(40,true,true),
           'user_email'=>$user.'@example.invalid','role'=>'customer','display_name'=>$user));
      if (is_wp_error($id)) { throw new RuntimeException('QA user creation failed'); }
      $created[] = $id;
      $expiration = time()+1200;
      $token = WP_Session_Tokens::get_instance($id)->create($expiration);
      $cookie = wp_generate_auth_cookie($id,$expiration,'logged_in',$token);
      $users[] = array('id'=>$id,'login'=>$user,'cookie'=>LOGGED_IN_COOKIE.'='.$cookie);
    }
  } catch (Throwable $e) {
    require_once ABSPATH.'wp-admin/includes/user.php';
    foreach ($created as $id) wp_delete_user($id);
    fwrite(STDERR,'QA customer preparation failed; caller will independently reconcile exact run');
    exit(5);
  }
  echo json_encode(array('users'=>$users,'products'=>array_slice($products,0,2),
        'cart_page'=>get_option('woocommerce_cart_page_id'),
        'checkout_page'=>get_option('woocommerce_checkout_page_id'),
        'account_page'=>get_option('woocommerce_myaccount_page_id'),
        'permalink'=>get_option('permalink_structure'),
        'woo'=>WC_VERSION));
} elseif ($in['op'] === 'remove') {
  require_once ABSPATH.'wp-admin/includes/user.php';
  global $wpdb;
  $removed = 0; $unresolved = array();
  foreach ($names as $login) {
    $user = get_user_by('login',$login);
    if (!$user) continue;
    // The unique, pre-observed login AND its exact generated email prove
    // which accounts this run may delete, even after a partial PHP exit.
    if ($user->user_email !== $login.'@example.invalid') {
      $unresolved[] = $login;
      continue;
    }
    $deleted_session = $wpdb->delete($wpdb->prefix.'woocommerce_sessions',
                   array('session_key'=>(string)$user->ID),array('%s'));
    if ($deleted_session === false) { $unresolved[] = $login; continue; }
    if (wp_delete_user($user->ID)) $removed++;
    else $unresolved[] = $login;
  }
  echo json_encode(array('removed'=>$removed,'unresolved'=>$unresolved));
} else { fwrite(STDERR,'Unknown QA action'); exit(8); }
"""


def wp_action(php, root, data):
    action = data["op"]
    try:
        p = subprocess.run(
            [php, "-d", "display_errors=0", "-r", WP_ACTION, str(root)],
            input=json.dumps(data), text=True, capture_output=True, timeout=35)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("WordPress QA %s exceeded 35 seconds" % action) from exc
    if p.returncode:
        raise RuntimeError("WordPress QA %s failed (exit %s)" % (action,p.returncode))
    try:
        return json.loads(p.stdout)
    except (ValueError, TypeError) as exc:
        # PHP prepare output contains signed session cookies; never echo it.
        raise RuntimeError("WordPress QA %s returned invalid JSON" % action) from exc


def qa_usernames(run_id):
    if not isinstance(run_id,str) or not re.fullmatch(r"[0-9a-f]{32}",run_id):
        raise ValueError("Invalid QA run identity")
    return ["achqa_cache_%s_%s" % (suffix,run_id) for suffix in ("a","b")]


def observe_qa_accounts(php, root, run_id):
    result = wp_action(php,root,{"op":"observe","run_id":run_id})
    expected = set(qa_usernames(run_id))
    if (not isinstance(result,dict) or not isinstance(result.get("present"),list)
            or any(x not in expected for x in result["present"])):
        raise RuntimeError("WordPress QA account observation is invalid")
    return set(result["present"])


def claim_qa_accounts(php, root, temp):
    # A confirmed empty exact-name preflight precedes the FIRST DB mutation.
    # A run-specific recovery identity is then persisted before prepare.
    run_id = secrets.token_hex(16)
    if observe_qa_accounts(php,root,run_id):
        raise RuntimeError("Generated QA identities already exist; refusing preparation")
    recovery = temp/"qa-account-recovery.json"
    fd = os.open(recovery,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as handle:
        json.dump({"run_id":run_id,"usernames":qa_usernames(run_id),
                   "site_root":str(root),"status":"prepare_or_cleanup_unknown"},handle)
        handle.flush()
        os.fsync(handle.fileno())
    return run_id


def validate_prepared_accounts(data, run_id):
    expected = qa_usernames(run_id)
    if (not isinstance(data,dict) or not isinstance(data.get("users"),list)
            or len(data["users"]) != 2 or
            [x.get("login") for x in data["users"] if isinstance(x,dict)] != expected or
            any(not isinstance(x.get("id"),int) or x["id"] <= 0 or
                    not isinstance(x.get("cookie"),str) or "=" not in x["cookie"]
                    for x in data["users"] if isinstance(x,dict))):
        raise RuntimeError("WordPress QA prepare returned incomplete identities")
    return data


def cleanup_qa_accounts(php, root, run_id):
    """Reconcile exact run users even if PHP prepare/remove response was lost.

    A successful remove response alone is not proof. Independent fresh observe
    is authoritative for actual absence. Errors include exact non-secret
    usernames so the retained recovery manifest remains actionable.
    """
    attempted = 0
    operation_error = None
    try:
        result = wp_action(php,root,{"op":"remove","run_id":run_id})
        if (not isinstance(result,dict) or
                type(result.get("removed")) is not int or
                not 0 <= result["removed"] <= 2 or
                not isinstance(result.get("unresolved"),list)):
            raise RuntimeError("Invalid QA cleanup response")
        attempted = result["removed"]
    except Exception as exc:
        operation_error = str(exc)
    try:
        observed = observe_qa_accounts(php,root,run_id)
    except Exception as exc:
        raise RuntimeError("QA account deletion unverified for exact users %s; %s" %
                           (", ".join(qa_usernames(run_id)), str(exc))) from exc
    if observed:
        raise RuntimeError("QA accounts remain for exact users: "+", ".join(sorted(observed))+
                           ("; cleanup call: "+operation_error if operation_error else ""))
    return attempted


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_store_site(root, hostname, site_id):
    with sqlite3.connect("file:/www/server/panel/data/default.db?mode=ro",
                         uri=True) as db:
        row = db.execute("select name,path,status from sites where id=?",
                         (site_id,)).fetchone()
    if row != (hostname, str(root), "1"):
        raise RuntimeError("Native aaPanel registered site identity mismatch")


def config_text(tmp, port, root, hostname, plan, php):
    return (
        "user www www;\nworker_processes 2;\npid %s;\n"
        "error_log %s notice;\nevents { worker_connections 256; }\n"
        "http {\n access_log off;\n"
        "lua_package_path \"/www/server/nginx/lib/lua/?.lua;;\";\n"
        "include /www/server/nginx/conf/mime.types;\n"
        "fastcgi_ignore_headers Cache-Control Expires Set-Cookie;\n"
        "fastcgi_cache_key \"$scheme$request_method$host$request_uri\";\n"
        "%s\nserver {\nlisten 127.0.0.1:%s;\nserver_name %s;\n"
        "root %s;\nindex index.php;\n"
        "location / { try_files $uri $uri/ /index.php?$args; }\n"
        "%s\ninclude /www/server/nginx/conf/enable-php-%s.conf;\n"
        "}\n}\n"
        % (tmp/"nginx.pid", tmp/"nginx.error.log",plan["global_http_fragment"],
           port, hostname, root, plan["site_server_fragment"], php)
    )


class Client:
    def __init__(self, port, hostname, cookie=""):
        self.port = port
        self.host = hostname
        self.cookies = {}
        if cookie:
            k, v = cookie.split("=", 1)
            self.cookies[k] = v

    def get(self, path, method="GET"):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": self.host, "User-Agent": "ACh-QA-Woo-Isolation/1"}
        if self.cookies:
            headers["Cookie"] = "; ".join(k+"="+v for k,v in self.cookies.items())
        try:
            con.request(method, path, headers=headers)
            response = con.getresponse()
            body = response.read(500000).decode("utf-8", "replace")
            for key, value in response.getheaders():
                if key.lower() != "set-cookie":
                    continue
                jar = SimpleCookie()
                try:
                    jar.load(value)
                except Exception:
                    continue
                for name, item in jar.items():
                    if item["max-age"] == "0" or item.value == "":
                        self.cookies.pop(name, None)
                    else:
                        self.cookies[name] = item.value
            return {"status": response.status,
                    "cache": response.getheader("X-ACh-Cache"),
                    "site": response.getheader("X-ACh-Cache-Site"),
                    "body": body}
        finally:
            con.close()


def exercise_store_clients(port, hostname, site_id, users, *, allow_pre_warmed=False):
    """Exercise one real Woo storefront with two independent logged-in sessions.

    The caller owns setup and exact-account cleanup. Native mode permits an
    already-warm public Cache but still requires an actual HIT.
    """
    public = Client(port,hostname)
    anonymous = [public.get("/") for _ in range(2)]
    # Warm only publicly cacheable homepage traffic; private traffic always bypasses.
    if any(r["status"]!=200 for r in anonymous):
        raise AssertionError("Real anonymous WordPress homepage not HTTP 200")
    cache_states = [r["cache"] for r in anonymous]
    if allow_pre_warmed:
        if cache_states not in (["MISS", "HIT"], ["HIT", "HIT"]):
            raise AssertionError("Native Woo storefront did not use private site Cache")
    elif cache_states != ["MISS", "HIT"]:
        raise AssertionError("Real anonymous Woo storefront did not warm public Cache")
    a,b = (Client(port,hostname,u["cookie"]) for u in users["users"])
    names = [u["login"] for u in users["users"]]
    profile = "?page_id="+str(users["account_page"])
    for client,login,other in ((a,names[0],names[1]),(b,names[1],names[0])):
        r = client.get("/"+profile)
        if r["status"]!=200 or r["cache"]!="BYPASS" or login not in r["body"] or other in r["body"]:
            raise AssertionError("Logged-in Woo account identity or bypass not verified")
    for client,product in zip((a,b),users["products"]):
        r = client.get("/?add-to-cart="+str(product["id"]))
        if r["cache"] not in ("BYPASS",None):
            raise AssertionError("Add-to-cart was cacheable")
    cart = "?page_id="+str(users["cart_page"])
    checkout = "?page_id="+str(users["checkout_page"])
    for client,mine,other in ((a,users["products"][0],users["products"][1]),
                              (b,users["products"][1],users["products"][0])):
        for label,path in (("cart",cart),("checkout",checkout),("account",profile)):
            r=client.get("/"+path)
            if r["status"]!=200 or r["cache"]!="BYPASS":
                raise AssertionError(label+" did not bypass for logged-in customer")
        # Woo Cart/Checkout blocks hydrate items via the Store API.
        # Their HTML shell is not evidence of product isolation.
        api = client.get("/?rest_route=/wc/store/v1/cart")
        if api["status"] != 200 or api["cache"] != "BYPASS":
            raise AssertionError("Live Woo Store API cart was not private: HTTP=%s cache=%s" %
                                 (api["status"],api["cache"]))
        try:
            products = [int(item["id"]) for item in json.loads(api["body"])["items"]]
        except (ValueError,KeyError,TypeError) as exc:
            raise AssertionError("Woo Store API cart response invalid") from exc
        if int(mine["id"]) not in products or int(other["id"]) in products:
            raise AssertionError("Real Woo Store API cart isolation failed: found product IDs %s" % products)
    for path in ("/?rest_route=/wc/v3/orders","/?wc-ajax=get_refreshed_fragments",
                 "/wp-login.php","/?wc-api=qa_cache_no_gateway"):
        resp=public.get(path)
        if resp["cache"] not in ("BYPASS",None):
            raise AssertionError("Private Woo/WordPress API or login was cached: "+path)
    for client in (a,b):
        r=client.get("/")
        if r["status"]!=200 or r["cache"]!="BYPASS":
            raise AssertionError("Logged-in public URI served shared Cache")
    if any(r["site"] != str(site_id) for r in anonymous):
        raise AssertionError("Expected plugin Cache site markers absent")
    return {"native_id":site_id,"woo_version":users["woo"],
        "wp_permalink":users["permalink"] or "plain",
        "anonymous_cache": [r["cache"] for r in anonymous],
        "session_a_authenticated":True,"session_b_authenticated":True,
        "different_real_cart_items":True,"cart_checkout_account":"BYPASS",
        "logged_in_public":"BYPASS",
        "api_login_webhook_requests":"BYPASS_or_uncacheable",
        "nginx_syntax":"PASS","qa_cache_isolated":True}


def run(args):
    if os.geteuid() != 0 or not args.explicit_nonproduction_qa:
        raise RuntimeError("Requires root in authorized isolated QA guest and --explicit-nonproduction-qa")
    root = Path(args.site_root)
    if (not root.is_dir() or not root.is_absolute() or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", args.host) or
            str(root) != os.path.realpath(root)):
        raise RuntimeError("Invalid native QA site root or host")
    assert_store_site(root, args.host, args.site_id)
    wp_php = args.wp_php or "/www/server/php/"+args.php_version+"/bin/php"
    needed = [args.nginx, wp_php,
              "/www/server/nginx/conf/fastcgi.conf",
              "/www/server/nginx/conf/pathinfo.conf",
              "/www/server/nginx/conf/enable-php-"+args.php_version+".conf",
              "/tmp/php-cgi-"+args.php_version+".sock"]
    if not all(Path(p).exists() for p in needed):
        raise RuntimeError("Required guest Nginx/PHP socket or source absent")
    native_config = ["/www/server/nginx/conf/nginx.conf",
        "/www/server/panel/vhost/nginx/0.fastcgi_cache.conf",
        "/www/server/panel/vhost/nginx/"+args.host+".conf",
        "/www/server/panel/vhost/rewrite/"+args.host+".conf"]
    before = {p:file_digest(p) for p in native_config}
    run_id = None
    removed_accounts = 0
    started = False
    start_attempted = False
    verified = {}
    www = pwd.getpwnam("www")
    temp = Path(tempfile.mkdtemp(prefix="ach-woo-real-cache-"))
    safe_remove = True
    try:
        temp.chmod(0o755)
        (temp/"logs").mkdir(mode=0o755)
        for part in ("fastcgi.conf", "pathinfo.conf"):
            shutil.copyfile("/www/server/nginx/conf/"+part, temp/part)
            (temp/part).chmod(0o644)
        (temp/"cache").mkdir(mode=0o755)
        plan = generate_reference(args.site_id, args.php_version,
                                  cache_root=str(temp/"cache"),
                                  cache_generation=secrets.token_hex(16))
        site_cache = Path(plan["cache_directory"])
        site_cache.mkdir(mode=0o750)
        os.chown(site_cache, www.pw_uid, www.pw_gid)
        # Must never reference real native cache paths.
        if str(site_cache).startswith("/www/server/"):
            raise RuntimeError("QA cache path is not isolated")
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        conf = temp/"nginx.conf"
        conf.write_text(config_text(temp,port,root,args.host,plan,args.php_version))
        run_cmd = [args.nginx,"-p",str(temp)+"/","-c",str(conf)]
        try:
            try:
                check = subprocess.run([*run_cmd,"-t"],capture_output=True,
                                       text=True,timeout=12)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Standalone Nginx syntax check timed out") from exc
            if check.returncode: raise RuntimeError("Standalone Nginx syntax failed: "+check.stderr[-800:])
            run_id = claim_qa_accounts(wp_php,root,temp)
            users = validate_prepared_accounts(
                wp_action(wp_php,root,{"op":"prepare","run_id":run_id}),run_id)
            start_attempted = True
            try:
                started_cmd = subprocess.run(run_cmd,capture_output=True,
                                             text=True,timeout=12)
            except subprocess.TimeoutExpired as exc:
                safe_remove = False  # A daemon may have started before timeout.
                raise RuntimeError("Standalone Nginx start timed out; retained recovery files") from exc
            if started_cmd.returncode:
                raise RuntimeError("Standalone Nginx startup failed: "+started_cmd.stderr[-800:])
            started = True
            for i in range(30):
                try:
                    Client(port,args.host).get("/?qa_ready_check=1")
                    break
                except OSError:
                    time.sleep(0.12)
            else:
                raise RuntimeError("Standalone Nginx listener not ready")
            verified=exercise_store_clients(port,args.host,args.site_id,users)
        finally:
            errors=[]
            pidfile = temp/"nginx.pid"
            if started or (start_attempted and pidfile.exists()):
                try:
                    stopped = subprocess.run([*run_cmd,"-s","quit"],
                                             capture_output=True,text=True,timeout=12)
                    if stopped.returncode:
                        safe_remove = False
                        errors.append("Standalone Nginx quit was rejected")
                except (subprocess.TimeoutExpired,OSError) as exc:
                    safe_remove = False
                    errors.append("Standalone Nginx stop unconfirmed: "+type(exc).__name__)
                for _ in range(50):
                    if not pidfile.exists():break
                    time.sleep(0.1)
                if pidfile.exists():
                    safe_remove = False
                    errors.append("Standalone Nginx pid not retired")
            if run_id is not None:
                try:
                    removed_accounts=cleanup_qa_accounts(wp_php,root,run_id)
                except Exception as exc:
                    safe_remove = False
                    errors.append("Exact QA account cleanup/recheck failed: %s; recovery file: %s" %
                                  (str(exc),temp/"qa-account-recovery.json"))
            changed=[p for p in native_config if file_digest(p)!=before[p]]
            if changed:
                errors.append("Native config changed unexpectedly: "+", ".join(changed))
            if errors:
                raise RuntimeError("; ".join(errors))
    finally:
        if safe_remove:
            shutil.rmtree(temp)
        else:
            print("Incomplete QA cleanup or Nginx stop; retained recovery root: "+str(temp),
                  file=sys.stderr)
    print(json.dumps({"result":"PASS","checks":verified,
         "preserved_native_configs":len(before),
         "ephemeral_qa_users_removed":removed_accounts,
         "loopback_nginx_stopped":True,"temporary_test_files_removed":True},sort_keys=True))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--site-id",type=int,required=True)
    p.add_argument("--host",required=True)
    p.add_argument("--site-root",required=True)
    p.add_argument("--php-version",choices=("81","85"),default="85")
    p.add_argument("--nginx",default="/www/server/nginx/sbin/nginx")
    p.add_argument("--wp-php",default=None)
    p.add_argument("--explicit-nonproduction-qa",action="store_true")
    run(p.parse_args())
