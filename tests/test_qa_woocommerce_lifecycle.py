"""Failure injection for the nonproduction real-Woo QA customer's lifecycle.

All WordPress/database and Nginx operations are simulated. No live sites,
credentials, network listeners or native aaPanel assets are touched.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import types
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1]/"scripts"/"qa_woocommerce_cache_runtime.py"
spec = importlib.util.spec_from_file_location("woo_qa_lifecycle",SOURCE)
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
REAL_WP_ACTION = qa.wp_action

TOKEN = "0123456789abcdef0123456789abcdef"
OTHER_TOKEN = "ffffffffffffffffffffffffffffffff"


class FakeWordPress:
    def __init__(self):
        self.accounts = {}
        self.calls = []
        self.fail_prepare = None
        self.skip_cleanup = set()
        self.fail_observe_after_remove = False
        self.prepare_response = None
        self.permalink = ""

    def __call__(self, php, root, data):
        op = data["op"]
        run_id = data["run_id"]
        names = qa.qa_usernames(run_id)
        self.calls.append((op,tuple(names)))
        if op == "observe":
            if self.fail_observe_after_remove and any(k == "remove" for k,_ in self.calls):
                raise RuntimeError("mock observation unavailable")
            return {"present":[name for name in names if name in self.accounts]}
        if op == "prepare":
            for i,name in enumerate(names):
                self.accounts[name] = name+"@example.invalid"
                if self.fail_prepare == i+1:
                    raise subprocess.TimeoutExpired(["php","-r","<no secrets>"],35)
            if self.fail_prepare == "bad-json":
                raise RuntimeError("WordPress QA prepare returned invalid JSON")
            if self.prepare_response is not None:
                return self.prepare_response
            return {"users":[{"id":i+11,"login":name,
                               "cookie":"wordpress_logged_in_qa=synthetic-%s"%i}
                               for i,name in enumerate(names)],
                    "products":[{"id":101,"name":"Product A"},{"id":102,"name":"Product B"}],
                    "cart_page":7,"checkout_page":8,"account_page":9,
                    "page_paths":({"cart":"/cart/", "checkout":"/checkout/",
                                   "account":"/my-account/"}
                                  if self.permalink else
                                  {"cart":"/?page_id=7", "checkout":"/?page_id=8",
                                   "account":"/?page_id=9"}),
                    "permalink":self.permalink,"woo":"11.2.2"}
        if op == "remove":
            removed = 0
            for name in names:
                if name in self.accounts and name not in self.skip_cleanup:
                    del self.accounts[name]
                    removed += 1
            return {"removed":removed,
                    "unresolved":[n for n in names if n in self.accounts]}
        raise AssertionError("unexpected mock operation "+op)


class WooQALifecycleTests(unittest.TestCase):
    def setUp(self):
        self.parent = tempfile.TemporaryDirectory(prefix="ach-woo-unit-")
        self.addCleanup(self.parent.cleanup)
        self.root = Path(self.parent.name)/"real-woo-root"
        self.root.mkdir()
        self.temp_roots = []
        self.wordpress = FakeWordPress()
        self.nginx_stop_mode = "ok"
        self.nginx_start_mode = "ok"
        real_exists = Path.exists
        real_mkdtemp = tempfile.mkdtemp
        guest_requirements = {
            "/fake/bin/nginx", "/fake/bin/php",
            "/www/server/nginx/conf/fastcgi.conf",
            "/www/server/nginx/conf/pathinfo.conf",
            "/www/server/nginx/conf/enable-php-85.conf",
            "/tmp/php-cgi-85.sock",
        }

        def exists(path):
            if str(path) in guest_requirements:
                return True
            return real_exists(path)

        def mkdtemp(*, prefix):
            path = Path(real_mkdtemp(prefix=prefix,dir=self.parent.name))
            self.temp_roots.append(path)
            return str(path)

        def subprocess_run(argv, **kwargs):
            if "-t" in argv:
                return subprocess.CompletedProcess(argv,0,"","")
            if "-s" in argv:
                if self.nginx_stop_mode == "timeout":
                    raise subprocess.TimeoutExpired(argv,kwargs.get("timeout",12))
                if self.nginx_stop_mode == "reject":
                    return subprocess.CompletedProcess(argv,1,"","rejected")
                return subprocess.CompletedProcess(argv,0,"","")
            if self.nginx_start_mode == "timeout":
                raise subprocess.TimeoutExpired(argv,kwargs.get("timeout",12))
            return subprocess.CompletedProcess(argv,0,"","")

        def generate_reference(site_id, php_version, *, cache_root, cache_generation):
            return {"cache_directory":cache_root+"/site-"+str(site_id),
                    "global_http_fragment":"", "site_server_fragment":""}

        patches = [
            mock.patch.object(qa.Path,"exists",exists),
            mock.patch.object(qa.tempfile,"mkdtemp",side_effect=mkdtemp),
            mock.patch.object(qa.os,"geteuid",return_value=0),
            mock.patch.object(qa.os,"chown",return_value=None),
            mock.patch.object(qa.pwd,"getpwnam",return_value=types.SimpleNamespace(pw_uid=1,pw_gid=1)),
            mock.patch.object(qa,"assert_store_site",return_value=None),
            mock.patch.object(qa,"file_digest",return_value="preexisting-source-sha"),
            mock.patch.object(qa.shutil,"copyfile",side_effect=lambda src,dst: Path(dst).write_text("fixture",encoding="utf-8")),
            mock.patch.object(qa,"generate_reference",side_effect=generate_reference),
            mock.patch.object(qa,"wp_action",side_effect=self.wordpress),
            mock.patch.object(qa.subprocess,"run",side_effect=subprocess_run),
            mock.patch.object(qa.secrets,"token_hex",return_value=TOKEN),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.args = types.SimpleNamespace(site_id=10,host="qa21-woocommerce-native.test",
            site_root=str(self.root),php_version="85",nginx="/fake/bin/nginx",
            wp_php="/fake/bin/php",explicit_nonproduction_qa=True)

    def run_qa(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            qa.run(self.args)
            return json.loads(out.getvalue())

    def test_normal_prepare_cleanup_and_no_wildcard_deletion(self):
        previous = "achqa_cache_a_"+OTHER_TOKEN
        self.wordpress.accounts[previous] = previous+"@example.invalid"

        def response(client, path, method="GET"):
            logged = bool(client.cookies)
            if path == "/":
                if logged:return {"status":200,"cache":"BYPASS","site":"10","body":"private"}
                num = getattr(self,"public_count",0)
                self.public_count = num+1
                return {"status":200,"cache":"MISS" if num==0 else "HIT",
                        "site":"10","body":"public"}
            if path.startswith("/?page_id=9"):
                marker = 1 if "synthetic-1" in str(client.cookies) else 0
                return {"status":200,"cache":"BYPASS","site":"10",
                        "body":qa.qa_usernames(TOKEN)[marker]}
            if path.startswith("/?rest_route=/wc/store/v1/cart"):
                marker = 1 if "synthetic-1" in str(client.cookies) else 0
                return {"status":200,"cache":"BYPASS","site":"10",
                        "body":json.dumps({"items":[{"id":101+marker}]})}
            return {"status":200,"cache":"BYPASS","site":"10","body":"private"}

        with mock.patch.object(qa.Client,"get",autospec=True,side_effect=response):
            result = self.run_qa()
        self.assertEqual(result["result"],"PASS")
        self.assertEqual(result["ephemeral_qa_users_removed"],2)
        self.assertEqual(result["checks"]["anonymous_cache"],["MISS","HIT"])
        self.assertEqual(self.wordpress.accounts,{previous:previous+"@example.invalid"})
        self.assertFalse(self.temp_roots[0].exists())
        self.assertEqual([op for op,_ in self.wordpress.calls],
                         ["observe","prepare","remove","observe"])

    def test_pretty_permalink_real_account_paths_are_not_redirects(self):
        self.wordpress.permalink = "/%postname%/"
        seen = []

        def response(client, path, method="GET"):
            seen.append(path)
            logged = bool(client.cookies)
            if path == "/":
                if logged:
                    return {"status":200,"cache":"BYPASS","site":"10","body":"private"}
                count = getattr(self,"public_count",0)
                self.public_count = count+1
                return {"status":200,"cache":"MISS" if count==0 else "HIT",
                        "site":"10","body":"public"}
            if path.startswith("/?page_id="):
                return {"status":301,"cache":"BYPASS","site":"10","body":""}
            if path == "/my-account/":
                marker = 1 if "synthetic-1" in str(client.cookies) else 0
                return {"status":200,"cache":"BYPASS","site":"10",
                        "body":qa.qa_usernames(TOKEN)[marker]}
            if path.startswith("/?rest_route=/wc/store/v1/cart"):
                marker = 1 if "synthetic-1" in str(client.cookies) else 0
                return {"status":200,"cache":"BYPASS","site":"10",
                        "body":json.dumps({"items":[{"id":101+marker}]})}
            return {"status":200,"cache":"BYPASS","site":"10","body":"private"}

        with mock.patch.object(qa.Client,"get",autospec=True,side_effect=response):
            result = self.run_qa()
        self.assertEqual(result["result"],"PASS")
        self.assertEqual(self.wordpress.accounts,{})
        self.assertIn("/my-account/",seen)
        self.assertIn("/cart/",seen)
        self.assertIn("/checkout/",seen)
        self.assertFalse(any(path.startswith("/?page_id=") for path in seen))

    def test_invalid_canonical_page_target_still_cleans_qa_users(self):
        self.wordpress.prepare_response = {
            "users":[{"id":11,"login":qa.qa_usernames(TOKEN)[0],"cookie":"a=b"},
                     {"id":12,"login":qa.qa_usernames(TOKEN)[1],"cookie":"a=c"}],
            "page_paths":{"cart":"//foreign.site/","checkout":"/checkout/",
                          "account":"/my-account/"}}
        with self.assertRaisesRegex(RuntimeError,"invalid canonical"):
            self.run_qa()
        self.assertEqual(self.wordpress.accounts,{})
        self.assertFalse(self.temp_roots[-1].exists())

    def test_preparation_timeout_after_first_or_second_customer_is_cleaned(self):
        for count in (1,2):
            with self.subTest(created=count):
                self.wordpress.accounts.clear()
                self.wordpress.calls.clear()
                self.wordpress.fail_prepare = count
                with self.assertRaises(subprocess.TimeoutExpired):
                    self.run_qa()
                self.assertEqual(self.wordpress.accounts,{})
                self.assertEqual([op for op,_ in self.wordpress.calls],
                                 ["observe","prepare","remove","observe"])
                self.assertFalse(self.temp_roots[-1].exists())

    def test_malformed_prepare_response_still_cleans_exact_accounts(self):
        self.wordpress.fail_prepare = "bad-json"
        with self.assertRaisesRegex(RuntimeError,"invalid JSON"):
            self.run_qa()
        self.assertEqual(self.wordpress.accounts,{})
        self.assertFalse(self.temp_roots[-1].exists())

    def test_incomplete_prepare_payload_still_cleans_exact_accounts(self):
        self.wordpress.prepare_response = {"users":[]}
        with self.assertRaisesRegex(RuntimeError,"incomplete identities"):
            self.run_qa()
        self.assertEqual(self.wordpress.accounts,{})

    def test_unresolved_cleanup_retains_exact_private_manifest(self):
        self.wordpress.skip_cleanup.add(qa.qa_usernames(TOKEN)[1])
        with mock.patch.object(qa.Client,"get",side_effect=RuntimeError("synthetic runtime failure")):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaisesRegex(
                    RuntimeError,"QA accounts remain for exact users") as error:
                self.run_qa()
        self.assertIn(qa.qa_usernames(TOKEN)[1],str(error.exception))
        recovery=self.temp_roots[-1]/"qa-account-recovery.json"
        self.assertTrue(recovery.is_file())
        self.assertEqual(stat.S_IMODE(recovery.stat().st_mode),0o600)
        manifest=json.loads(recovery.read_text())
        self.assertEqual(manifest["usernames"],qa.qa_usernames(TOKEN))
        self.assertNotIn("cookie",manifest)
        self.assertEqual(list(self.wordpress.accounts),[qa.qa_usernames(TOKEN)[1]])
        # This is only the simulated, task-owned test directory.
        shutil.rmtree(self.temp_roots[-1])

    def test_cleanup_response_loss_can_be_reconciled_from_observation(self):
        self.wordpress.fail_prepare = None
        self.wordpress.accounts = {name:name+"@example.invalid" for name in qa.qa_usernames(TOKEN)}
        real_fake = self.wordpress
        def lost_response(php,root,data):
            if data["op"] == "remove":
                real_fake(php,root,data)
                raise RuntimeError("simulated PHP remove response lost")
            return real_fake(php,root,data)
        with mock.patch.object(qa,"wp_action",side_effect=lost_response):
            self.assertEqual(qa.cleanup_qa_accounts("php",self.root,TOKEN),0)
        self.assertEqual(self.wordpress.accounts,{})

    def test_cleanup_verification_failure_preserves_manifest(self):
        self.wordpress.fail_observe_after_remove = True
        with mock.patch.object(qa.Client,"get",side_effect=RuntimeError("stop before responses")):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaisesRegex(
                    RuntimeError,"unverified for exact users"):
                self.run_qa()
        self.assertTrue((self.temp_roots[-1]/"qa-account-recovery.json").exists())
        shutil.rmtree(self.temp_roots[-1])

    def test_generated_login_collision_never_deletes_preexisting_user(self):
        same = qa.qa_usernames(TOKEN)[0]
        self.wordpress.accounts[same] = same+"@example.invalid"
        with self.assertRaisesRegex(RuntimeError,"identities already exist"):
            self.run_qa()
        self.assertEqual(self.wordpress.accounts,{same:same+"@example.invalid"})
        self.assertEqual([op for op,_ in self.wordpress.calls],["observe"])
        self.assertFalse(self.temp_roots[-1].exists())

    def test_nginx_stop_timeout_retains_source_and_does_not_claim_success(self):
        self.nginx_stop_mode = "timeout"
        with mock.patch.object(qa.Client,"get",side_effect=RuntimeError("synthetic handler failure")):
            with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
                with self.assertRaisesRegex(RuntimeError,"Nginx stop unconfirmed"):
                    self.run_qa()
        self.assertIn("retained recovery root",diagnostic.getvalue())
        self.assertTrue((self.temp_roots[-1]/"nginx.conf").exists())
        self.assertEqual(self.wordpress.accounts,{})
        shutil.rmtree(self.temp_roots[-1])

    def test_php_subprocess_timeout_is_safe_to_report(self):
        with mock.patch.object(qa.subprocess,"run",
                               side_effect=subprocess.TimeoutExpired(["php"],35)):
            with self.assertRaisesRegex(RuntimeError,"WordPress QA prepare exceeded 35 seconds"):
                REAL_WP_ACTION("php",self.root,{"op":"prepare","run_id":TOKEN})

    def test_malformed_php_stdout_is_not_echoed(self):
        private_body = "SensitiveCookieValue_invalid-json"
        with mock.patch.object(qa.subprocess,"run",
                               return_value=subprocess.CompletedProcess(
                                   ["php"],0,private_body,"")):
            with self.assertRaisesRegex(RuntimeError,"WordPress QA prepare returned invalid JSON") as e:
                REAL_WP_ACTION("php",self.root,{"op":"prepare","run_id":TOKEN})
        self.assertNotIn(private_body,str(e.exception))

    def test_nginx_start_timeout_does_not_claim_success(self):
        self.nginx_start_mode = "timeout"
        with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
            with self.assertRaisesRegex(RuntimeError,"Nginx start timed out"):
                self.run_qa()
        self.assertTrue((self.temp_roots[-1]/"nginx.conf").exists())
        self.assertIn("retained recovery root",diagnostic.getvalue())
        self.assertEqual(self.wordpress.accounts,{})
        shutil.rmtree(self.temp_roots[-1])


if __name__ == "__main__":
    unittest.main()
