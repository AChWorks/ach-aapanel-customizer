"""Source/preflight and cleanup tests for real native-aaPanel Woo A/B QA.

All native files, account calls and Nginx commands are fixtures/mocks.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1]/"scripts"/"qa_woocommerce_native_cache_runtime.py"
spec = importlib.util.spec_from_file_location("native_woo_qa",SOURCE)
import sys
sys.path.insert(0,str(SOURCE.parent))
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)

TOKEN="a"*32


def digest(data):
    return hashlib.sha256(data).hexdigest()


class NativeWooCachePreflightTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix="ach-native-woo-unit-")
        self.addCleanup(self.t.cleanup)
        self.base=Path(self.t.name)
        self.nginx=self.base/"nginx"
        self.vhost=self.base/"vhosts"
        self.data=self.base/"data"
        self.policy=self.base/"plugin"/"cache.py"
        self.php_path=self.base/"fake-php"
        for p in [self.nginx,self.vhost,self.data,self.policy.parent,
                  self.base/"rewrite",self.vhost/"extension"/"woo.test"]:
            p.mkdir(parents=True,exist_ok=True)
        self.php_path.write_text("fake")
        self.site=self.base/"site"
        self.site.mkdir()
        self.zone=self.base/"cache"/"site-10"
        self.zone.mkdir(parents=True)
        self.files={
            "vhost":self.vhost/"woo.test.conf",
            "rewrite":self.base/"rewrite"/"woo.test.conf",
            "main":self.nginx/"nginx.conf",
            "php":self.nginx/"enable-php-85.conf",
            "fastcgi":self.nginx/"fastcgi.conf",
            "pathinfo":self.nginx/"pathinfo.conf",
            "global":self.vhost/"0.ach_customizer_cache_10.conf",
            "extension":self.vhost/"extension"/"woo.test"/"ach_customizer_cache_10.conf",
            "journal":self.data/"ach_customizer.cache.10.json",
        }
        contents={
            "vhost":("server { include "+str(self.vhost/"extension"/"woo.test"/"*.conf")+
                     "; include enable-php-85.conf; }\n"),
            "rewrite":"# native rewrite\n",
            "main":"http { include vhosts; }\n",
            "php":"location ~ \\.php { fastcgi_pass php85; }\n",
            "fastcgi":"fastcgi_param SCRIPT_NAME foo;\n",
            "pathinfo":"fastcgi_param PATH_INFO bar;\n",
            "global":"global-site-10\n",
            "extension":"extension-site-10\n",
        }
        for k,v in contents.items():
            self.files[k].write_text(v)
        self.files["global"].chmod(0o600)
        self.files["extension"].chmod(0o600)
        self.policy.write_text("exact-policy-fixture")
        self.reference={"cache_directory":str(self.zone),
            "global_http_fragment":contents["global"],
            "site_server_fragment":contents["extension"]}
        si=self.zone.stat()
        self.record={
            "schema":2,"site_id":10,"site_key":"woo.test","php_version":"85",
            "phase":"applied","op":TOKEN,"cache_generation":"b"*32,
            "cache_identity":[si.st_dev,si.st_ino],
            "cache_directory":str(self.zone),
            "global_sha":digest(contents["global"].encode()),
            "extension_sha":digest(contents["extension"].encode()),
            "vhost_sha":digest(self.files["vhost"].read_bytes()+b"\0"+self.files["rewrite"].read_bytes()),
            "main_sha":qa.digest(self.files["main"]),
            "php_sha":digest(self.files["php"].read_bytes()+b"\0"+
                             self.files["fastcgi"].read_bytes()+b"\0"+
                             self.files["pathinfo"].read_bytes()),
        }
        self.save_record()
        self.args=types.SimpleNamespace(site_id=10,host="woo.test",site_root=str(self.site),
            php_version="85",expected_guest_hostname="aac-native-qa",
            expected_recovery_id=TOKEN,expected_policy_sha256=qa.digest(self.policy),
            nginx=str(self.base/"nginx-binary"),wp_php=str(self.php_path),
            explicit_nonproduction_qa=True)
        self.gen=patch.object(qa.woo,"generate_reference",return_value=self.reference)
        self.check=patch.object(qa.subprocess,"run",return_value=subprocess.CompletedProcess(
            ["nginx","-t"],0,"",""))
        self.gen.start();self.check.start()
        self.addCleanup(self.gen.stop);self.addCleanup(self.check.stop)

    def save_record(self):
        self.files["journal"].write_text(json.dumps(self.record))

    def snapshot(self):
        return qa.snapshot_native(
            self.args,nginx_root=str(self.nginx),vhost_root=str(self.vhost),
            data_dir=str(self.data),policy_path=str(self.policy))

    def test_exact_applied_native_sources_accept(self):
        self.assertEqual(len(self.snapshot()),10)

    def test_wrong_recovery_is_rejected(self):
        self.args.expected_recovery_id="c"*32
        with self.assertRaisesRegex(RuntimeError,"exact approved Applied"):
            self.snapshot()

    def test_restored_phase_cannot_probe_as_applied(self):
        self.record["phase"]="restored"
        self.save_record()
        with self.assertRaisesRegex(RuntimeError,"exact approved Applied"):
            self.snapshot()

    def test_modified_or_missing_extension_is_rejected(self):
        self.files["extension"].write_text("untrusted")
        with self.assertRaisesRegex(RuntimeError,"source differs"):
            self.snapshot()
        self.files["extension"].unlink()
        with self.assertRaisesRegex(RuntimeError,"missing/aliased"):
            self.snapshot()

    def test_old_wordpress_fastcgi_include_is_rejected(self):
        path=self.files["vhost"]
        path.write_text(path.read_text().replace(
            "include enable-php-85.conf;","include enable-php-85-wpfastcgi.conf;"))
        with self.assertRaisesRegex(RuntimeError,"supported stock PHP"):
            self.snapshot()

    def test_policy_hash_mismatch_is_rejected(self):
        self.args.expected_policy_sha256="f"*64
        with self.assertRaisesRegex(RuntimeError,"policy source identity"):
            self.snapshot()

    def test_aliased_cache_physical_directory_is_rejected(self):
        other=self.base/"foreign-cache"
        other.mkdir()
        shutil.rmtree(self.zone)
        self.zone.symlink_to(other,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,"missing or aliased"):
            self.snapshot()

    def test_nginx_syntax_must_pass(self):
        with patch.object(qa.subprocess,"run",return_value=subprocess.CompletedProcess(
            ["nginx","-t"],1,"","synthetic failure")):
            with self.assertRaisesRegex(RuntimeError,"Nginx syntax"):
                self.snapshot()

    def test_native_runner_verifies_cleanup_without_mutating_nginx(self):
        users={"users":[{"id":1,"login":"a","cookie":"auth=a"},
                        {"id":2,"login":"b","cookie":"auth=b"}],
               "products":[{"id":1},{"id":2}],"cart_page":1,
               "checkout_page":2,"account_page":3,"woo":"11.2.2"}
        patches=[
            patch.object(qa.os,"geteuid",return_value=0),
            patch.object(qa.socket,"gethostname",return_value="aac-native-qa"),
            patch.object(qa.woo,"assert_store_site",return_value=None),
            patch.object(qa,"snapshot_native",return_value={"a":"sha"}),
            patch.object(qa.woo,"claim_qa_accounts",return_value=TOKEN),
            patch.object(qa.woo,"wp_action",return_value=users),
            patch.object(qa.woo,"validate_prepared_accounts",return_value=users),
            patch.object(qa.woo,"exercise_store_clients",return_value={"different_real_cart_items":True}),
            patch.object(qa.woo,"cleanup_qa_accounts",return_value=2),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                qa.run(self.args)
            result=json.loads(output.getvalue())
        self.assertEqual(result["result"],"PASS")
        self.assertEqual(result["ephemeral_qa_users_removed"],2)
        self.assertEqual(result["native_nginx_mutations"],0)

    def test_unknown_account_cleanup_retains_exact_recovery_manifest(self):
        # Real mkdtemp belongs under this test's automatically cleaned root,
        # so an intentionally uncertain cleanup never pollutes host /tmp.
        retained = self.base/"task-owned-recovery"
        def make_temp(*, prefix):
            self.assertEqual(prefix,"ach-woo-native-ab-")
            retained.mkdir(mode=0o700)
            return str(retained)

        def claim(_php,_root,temp):
            manifest=temp/"qa-account-recovery.json"
            manifest.write_text(json.dumps({
                "run_id":TOKEN,"usernames":qa.woo.qa_usernames(TOKEN),
                "site_root":str(self.site),"status":"prepare_or_cleanup_unknown"}))
            manifest.chmod(0o600)
            return TOKEN

        patches=[
            patch.object(qa.os,"geteuid",return_value=0),
            patch.object(qa.socket,"gethostname",return_value="aac-native-qa"),
            patch.object(qa.woo,"assert_store_site",return_value=None),
            patch.object(qa,"snapshot_native",return_value={"a":"sha"}),
            patch.object(qa.tempfile,"mkdtemp",side_effect=make_temp),
            patch.object(qa.woo,"claim_qa_accounts",side_effect=claim),
            patch.object(qa.woo,"wp_action",return_value={"users":[]}),
            patch.object(qa.woo,"validate_prepared_accounts",return_value={"users":[]}),
            patch.object(qa.woo,"exercise_store_clients",side_effect=RuntimeError("failure")),
            patch.object(qa.woo,"cleanup_qa_accounts",side_effect=RuntimeError("unknown cleanup")),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patches:stack.enter_context(patcher)
            with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
                with self.assertRaisesRegex(RuntimeError,"cleanup/recheck failed"):
                    qa.run(self.args)
            self.assertIn("recovery retained",diagnostic.getvalue())
            manifest=retained/"qa-account-recovery.json"
            self.assertEqual(json.loads(manifest.read_text())["run_id"],TOKEN)
            self.assertEqual(manifest.stat().st_mode & 0o777,0o600)


if __name__=="__main__":
    unittest.main()
