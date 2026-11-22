"""Recoverable WordPress XML-RPC MU-plugin policy, real owned-file lifecycle."""
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0,str(ROOT))
import ach_customizer_wp_xmlrpc as xmlrpc
from ach_customizer_state import _open_state_dir


class XmlrpcTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="ach-wp-xmlrpc-")
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.root=self.base/"site"
        self.root.mkdir()
        self.content=self.root/"wp-content"
        self.content.mkdir(mode=0o700)
        self.data=self.base/"data"
        self.data.mkdir(mode=0o700)
        self.fd=_open_state_dir(str(self.data))
        self.addCleanup(os.close,self.fd)
        self.site={"id":9,"name":"wp.example.test","path":str(self.root),
                   "status":1,"bound_domains":[{"name":"wp.example.test","port":80}]}
        self.public=object()
        self.patches=[
            patch.object(xmlrpc,"_docroot",side_effect=lambda site,public:
                         os.open(str(self.root),os.O_RDONLY|os.O_DIRECTORY)),
            patch.object(xmlrpc,"_site_source",return_value=(b"<?php native config","/usr/bin/php","85")),
            patch.object(xmlrpc,"_read_file",
                         return_value=(b"<?php define('XMLRPC_REQUEST',true); require 'wp-load.php';",None)),
            patch.object(xmlrpc,"_lint",return_value=None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def probe(self,site):
        self.assertEqual(site,self.site)
        p=self.content/"mu-plugins"/xmlrpc.FILE_NAME
        if not p.exists():
            return 200,None
        raw=p.read_text()
        match=re.search(r"X-ACh-XMLRPC-Proof: (ach-xmlrpc-[0-9a-f]{24})",raw)
        assert match, "Managed PHP plugin has no proof"
        return 403,match.group(1)

    def call(self,action,**kwargs):
        return xmlrpc.manage_xmlrpc(action,self.site,self.public,data_fd=self.fd,
                                    probe=self.probe,**kwargs)

    def recheck(self):
        return self.call("recheck")

    def apply(self):
        r=self.recheck()
        self.assertEqual(r["state"],"Source Ready")
        return self.call("apply",expected_source=r["source_sha256"])

    def restore(self):
        r=self.recheck()
        return self.call("restore",expected_source=r["source_sha256"],
                         expected_recovery=r["recovery_id"])

    def test_normal_apply_recheck_restore_creates_and_removes_owned_mu_dir(self):
        before=list(self.content.iterdir())
        self.assertEqual(before,[])
        ready=self.recheck()
        self.assertEqual(ready["state"],"Source Ready")
        self.assertFalse(ready["runtime_verified"])
        applied=self.apply()
        self.assertEqual(applied["state"],"Applied")
        self.assertTrue(applied["runtime_verified"])
        managed=self.content/"mu-plugins"/xmlrpc.FILE_NAME
        self.assertTrue(managed.is_file())
        self.assertEqual(managed.stat().st_mode & 0o777,0o644)
        self.assertIn(b"XMLRPC_REQUEST",managed.read_bytes())
        self.assertEqual(self.recheck()["state"],"Applied")
        restored=self.restore()
        self.assertEqual(restored["state"],"Restored")
        self.assertTrue(restored["runtime_verified"])
        self.assertFalse((self.content/"mu-plugins").exists())
        self.assertEqual(self.recheck()["state"],"Restored")
        self.assertEqual(list(self.content.iterdir()),before)

    def test_preexisting_mu_dir_and_foreign_plugin_are_preserved(self):
        mu=self.content/"mu-plugins"
        mu.mkdir(mode=0o700)
        foreign=mu/"trusted-operator-plugin.php"
        foreign.write_text("<?php // third-party")
        initial=foreign.read_bytes()
        self.apply()
        self.restore()
        self.assertTrue(mu.is_dir())
        self.assertEqual(foreign.read_bytes(),initial)
        self.assertFalse((mu/xmlrpc.FILE_NAME).exists())

    def test_foreign_target_plugin_blocks_apply_without_backup_or_clobber(self):
        mu=self.content/"mu-plugins"
        mu.mkdir(mode=0o700)
        foreign=mu/xmlrpc.FILE_NAME
        foreign.write_text("<?php // foreign owner")
        foreign.chmod(0o644)
        self.assertEqual(self.recheck()["state"],"Conflict")
        with self.assertRaises(xmlrpc.WPSettingsError):
            self.call("apply",expected_source=self.recheck()["source_sha256"])
        self.assertEqual(foreign.read_text(),"<?php // foreign owner")
        self.assertEqual(list(self.data.iterdir()),[])

    def test_source_change_denies_stale_apply(self):
        expected=self.recheck()["source_sha256"]
        with patch.object(xmlrpc,"_site_source",return_value=(b"<?php changed config","/usr/bin/php","85")):
            with self.assertRaisesRegex(xmlrpc.WPSettingsError,"changed"):
                self.call("apply",expected_source=expected)
        self.assertFalse((self.content/"mu-plugins").exists())

    def test_exact_recovery_id_and_owned_file_hash_are_mandatory(self):
        self.apply()
        r=self.recheck()
        with self.assertRaises(xmlrpc.WPSettingsError):
            self.call("restore",expected_source=r["source_sha256"],
                      expected_recovery="0"*32)
        target=self.content/"mu-plugins"/xmlrpc.FILE_NAME
        target.write_text(target.read_text()+"\n// foreign changed")
        with self.assertRaisesRegex(xmlrpc.WPSettingsError,"changed"):
            self.restore()
        self.assertTrue(target.exists())

    def test_interrupted_publication_with_prepared_journal_can_restore(self):
        from ach_customizer_status_extension import ExtensionError
        with patch.object(xmlrpc,"_publish_complete",
                          side_effect=ExtensionError("publication","simulated")):
            r=self.recheck()
            with self.assertRaises(xmlrpc.WPSettingsError) as err:
                self.call("apply",expected_source=r["source_sha256"])
        self.assertEqual(err.exception.stage,"uncertain")
        self.assertRegex(err.exception.recovery_id,r"^[a-f0-9]{32}$")
        self.assertEqual(self.recheck()["state"],"Recovery Required")
        self.assertEqual(self.restore()["state"],"Restored")
        self.assertFalse((self.content/"mu-plugins").exists())

    def test_interrupted_restore_after_unlink_is_idempotently_recoverable(self):
        self.apply()
        with patch.object(xmlrpc,"_settled",
                          side_effect=xmlrpc.WPSettingsError("postcheck","simulated")):
            with self.assertRaises(xmlrpc.WPSettingsError) as err:
                self.restore()
        self.assertEqual(err.exception.stage,"uncertain")
        self.assertEqual(self.recheck()["state"],"Recovery Required")
        self.assertEqual(self.restore()["state"],"Restored")
        self.assertFalse((self.content/"mu-plugins").exists())

    def test_symlinked_mu_dir_is_never_followed(self):
        other=self.base/"foreign"
        other.mkdir()
        (self.content/"mu-plugins").symlink_to(other,target_is_directory=True)
        with self.assertRaises(xmlrpc.WPSettingsError):
            self.recheck()
        self.assertEqual(list(other.iterdir()),[])

    def test_invalid_site_binding_never_changes_existing_websites(self):
        self.site["status"]=0
        with self.assertRaises(xmlrpc.WPSettingsError):
            self.recheck()
        self.site["status"]=1
        self.site["bound_domains"]=[]
        with self.assertRaises(xmlrpc.WPSettingsError):
            self.recheck()
        self.assertFalse((self.content/"mu-plugins").exists())


if __name__=="__main__":
    unittest.main()


class XmlrpcBackendAuthorizationTests(unittest.TestCase):
    def test_primary_admin_and_explicit_apply_authorization_required(self):
        import ach_customizer_main as backend
        plugin=backend.ach_customizer_main()
        with tempfile.TemporaryDirectory() as temp, patch.object(
                backend, "_STATE_DIR",temp),patch.object(
                backend.ach_customizer_main,"_status_primary_admin_post",
                side_effect=PermissionError("not authorized")):
            denied=plugin.wp_settings_manage({
                "settings_action":"recheck","settings_kind":"xmlrpc","desired":"block"})
            self.assertFalse(denied["status"])
            self.assertIn("authorization",denied["stage"])
        public=types.ModuleType("public")
        public.get_webserver=lambda:"nginx"
        with tempfile.TemporaryDirectory() as temp, patch.dict(
                sys.modules,{"public":public}), patch.object(
                backend, "_STATE_DIR",temp),patch.object(
                backend.ach_customizer_main,"_status_primary_admin_post"),patch.object(
                backend.ach_customizer_main,"_require_enabled"):
            denied=plugin.wp_settings_manage({
                "settings_action":"apply","settings_kind":"xmlrpc","desired":"block"})
            self.assertFalse(denied["status"])
            self.assertIn("authorize",denied["msg"])
            denied=plugin.wp_settings_manage({
                "settings_action":"recheck","settings_kind":"xmlrpc","desired":"foo"})
            self.assertFalse(denied["status"])
            self.assertIn("Block XML-RPC",denied["msg"])

    def test_exact_selected_site_and_recovery_are_passed_to_guarded_xmlrpc_manager(self):
        import ach_customizer_main as backend
        from contextlib import nullcontext
        site={"id":9,"name":"site.test","path":"/www/wwwroot/site.test",
              "status":1,"bound_domains":[{"name":"site.test","port":80}]}
        public=types.ModuleType("public")
        public.get_webserver=lambda:"nginx"
        expected={
            "schema":1,"site_id":9,"site_key":"site.test",
            "kind":"xmlrpc","state":"Applied","source_sha256":"b"*64,
            "recovery_id":"c"*32,"changed":True,"runtime_verified":True
        }
        with tempfile.TemporaryDirectory() as temp,patch.dict(
                sys.modules,{"public":public}),patch.object(
                backend,"_STATE_DIR",temp),patch.object(
                backend.ach_customizer_main,"_status_primary_admin_post"),patch.object(
                backend.ach_customizer_main,"_require_enabled"),patch.object(
                backend.ach_customizer_main,"_selected_native_website",
                return_value=(public,site,lambda:dict(site))),patch(
                "ach_customizer_cache_wordpress._site_lock",
                return_value=nullcontext()),patch.object(
                xmlrpc,"manage_xmlrpc",return_value=expected) as apply:
            result=backend.ach_customizer_main().wp_settings_manage({
                "settings_action":"apply","settings_kind":"xmlrpc",
                "desired":"block","approved":"true",
                "expected_source_sha256":"a"*64})
            self.assertTrue(result["status"],result)
            self.assertEqual(result["recovery_id"],"c"*32)
            self.assertEqual(apply.call_args.args[:3],("apply",site,public))
            self.assertEqual(apply.call_args.kwargs["expected_source"],"a"*64)
