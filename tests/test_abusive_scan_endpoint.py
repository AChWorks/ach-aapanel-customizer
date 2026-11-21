"""Real native entrypoint contract for the P0 Fail2ban integration.

No system firewall or guest service is touched; the host-level Ban/Unban
acceptance is recorded separately on the retained aaPanel QA VM.
"""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0,str(PLUGIN))
SPEC=importlib.util.spec_from_file_location("ach_customizer_main",PLUGIN/"ach_customizer_main.py")
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
import ach_customizer_abusive_scan as scan
import ach_customizer_nginx_security as guard
from ach_customizer_activity import read_activity

SITE={"id":9,"name":"cache.example.test","path":"/www/acdomains/cache.example.test",
      "status":1,"bound_domains":[{"name":"cache.example.test","port":80}]}
REPORT={
    "schema":1,"mode":scan.MODE,"ruleset":scan.RULESET,
    "site_id":9,"site_key":SITE["name"],"state":"Unmanaged",
    "reason":"Site-owned log verified","recovery_id":None,"journal_phase":None,
    "runtime_verified":False,"changed":False,"read_only":True,
    "firewall_scope":"origin_wide_web_ports","log_scope":"selected_native_site",
    "vhost_sha256":"a"*64,"plan_sha256":"b"*64,
    "log_path":"/www/wwwlogs/cache.example.test.log",
}
class ScannerEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.plugin=MODULE.ach_customizer_main()
        tmp=tempfile.TemporaryDirectory(prefix="ach-scan-endpoint-")
        self.addCleanup(tmp.cleanup)
        self.data=Path(tmp.name)
        self.patch=patch.object(MODULE,"_STATE_DIR",str(self.data))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.flask=types.ModuleType("flask")
        self.flask.session={"uid":1,"login":True}
        self.flask.request=types.SimpleNamespace(method="POST")
        self.flask.has_request_context=lambda: True
        self.public=types.ModuleType("public")
        self.patch_public=patch.dict(sys.modules,{
            "flask":self.flask,"public":self.public})
        self.patch_public.start()
        self.addCleanup(self.patch_public.stop)

    def _patch(self):
        return (
            patch.object(self.plugin,"_require_enabled",return_value=None),
            patch.object(self.plugin,"_selected_native_website",
                         return_value=(self.public,SITE,lambda:SITE)),
        )

    def test_authorization_precedes_identity_and_external_system(self):
        with self._patch()[0],self._patch()[1] as select,patch.object(
                scan,"manage") as manage,patch.object(guard,"manage_guard") as ng:
            for name,auth,method,ctx in [
                ("secondary",{"uid":2,"login":True},"POST",True),
                ("guest",{"uid":1,"login":False},"POST",True),
                ("temporary",{"uid":1,"login":True,"tmp_login":True},"POST",True),
                ("get",{"uid":1,"login":True},"GET",True),
                ("no-context",{"uid":1,"login":True},"POST",False)]:
                with self.subTest(name=name):
                    self.flask.session=auth
                    self.flask.request.method=method
                    self.flask.has_request_context=lambda ctx=ctx:ctx
                    result=self.plugin.manage_abusive_scan({
                        "site_id":"999","scan_action":"apply","approved":"true"})
                    self.assertFalse(result["status"],result)
                    self.assertEqual(result["stage"],"abusive_scan_authorization")
                    select.assert_not_called()
                    manage.assert_not_called()
                    ng.assert_not_called()

    def test_preview_and_apply_require_actual_guard_and_selected_identity(self):
        with self._patch()[0],self._patch()[1] as select,patch.object(
                scan,"manage",return_value=dict(REPORT)) as manage,patch.object(
                guard,"manage_guard",return_value={
                    "state":"Unmanaged","runtime_verified":False
                }) as ng:
            preview=self.plugin.manage_abusive_scan({"scan_action":"preview"})
            self.assertTrue(preview["status"],preview)
            self.assertEqual(preview["state"],"Unmanaged")
            self.assertEqual(preview["site_key"],SITE["name"])
            ng.assert_not_called()
            failed=self.plugin.manage_abusive_scan({
                "scan_action":"apply","approved":"true",
                "expected_plan_sha256":"b"*64})
            self.assertFalse(failed["status"],failed)
            self.assertEqual(failed["stage"],"abusive_scan_manage")
            self.assertIn("Nginx sensitive-path guard",failed["msg"])
            self.assertEqual(manage.call_count,1)
            self.assertEqual(select.call_count,2)
            self.assertEqual(read_activity(str(self.data),module="websites")[0]["target"],"9")
            ng.return_value={"state":"Applied","runtime_verified":True}
            manage.return_value=dict(REPORT,state="Applied",reason="Active",changed=True,
                   read_only=False,runtime_verified=True,recovery_id="c"*32,
                   journal_phase="applied")
            ok=self.plugin.manage_abusive_scan({
                "site_id":"9","scan_action":"apply","approved":"true",
                "maxretry":"7","findtime":"300","bantime":"1800",
                "expected_plan_sha256":"b"*64})
            self.assertTrue(ok["status"],ok)
            self.assertEqual(ok["recovery_id"],"c"*32)
            self.assertEqual(manage.call_args.args[:2],("apply",SITE))
            self.assertEqual(manage.call_args.kwargs["params"],
                             {"maxretry":"7","findtime":"300","bantime":"1800"})
            self.assertEqual(manage.call_args.kwargs["expected_plan"],"b"*64)

    def test_uncertain_apply_exposes_only_trusted_recovery_and_activity(self):
        with self._patch()[0],self._patch()[1],patch.object(
                guard,"manage_guard",return_value={
                    "state":"Applied","runtime_verified":True}),patch.object(
                scan,"manage",side_effect=scan.AbuseError(
                    "uncertain","Fail2ban reload unconfirmed",
                    recovery_id="d"*32)):
            result=self.plugin.manage_abusive_scan({
                "scan_action":"apply","approved":"true"})
            self.assertFalse(result["status"],result)
            self.assertEqual(result["stage"],"abusive_scan_manage")
            self.assertIn("reload unconfirmed",result["msg"])
            self.assertEqual(result["recovery_id"],"d"*32)
            self.assertRegex(result["operation_id"],r"^[0-9a-f]{32}$")
            self.assertNotEqual(result["operation_id"],result["recovery_id"])
            row=read_activity(str(self.data),module="websites")[0]
            self.assertEqual(row["stage"],"abusive_scan_uncertain")
            self.assertEqual(row["target"],"9")
            self.assertEqual(row["recovery_id"],"d"*32)


if __name__=="__main__":
    unittest.main()
