"""Native aaPanel full-primary-admin/selection bindings for stopped-site HTTP503."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/"plugin"/"ach_customizer"
sys.path.insert(0,str(ROOT))
import ach_customizer_main as backend
import ach_customizer_status_stopped as target
from ach_customizer_status_pages import render_page
from ach_customizer_activity import read_activity

class StoppedApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patcher=patch.object(backend,"_STATE_DIR",self.tmp.name)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.plugin=backend.ach_customizer_main()
        self.site={"id":7,"name":"demo.test","path":"/www/demo.test","status":"1"}
        self.engine="nginx"
        self.version="8.0.7"
        self.same_root=1
        self.flask=types.ModuleType("flask")
        self.flask.session={"login":True,"uid":1}
        self.flask.has_request_context=lambda:True
        self.flask.request=types.SimpleNamespace(method="POST")
        self.public=types.ModuleType("public")
        self.public.M=lambda table:self.Query(self) if table=="sites" else None
        self.public.get_webserver=lambda:self.engine
        self.public.get_panel_version=lambda:self.version
        self.result={"schema":1,"mode":"native_stopped_http503","state":"Armed",
                     "site_id":7,"site_key":"demo.test","site_status":"1",
                     "vhost_sha256":"b"*64,"rendered_sha256":render_page("en","stopped")["rendered_sha256"],
                     "served_sha256":"d"*64,"recovery_id":"f"*32,
                     "read_only":False,"changed":True,"runtime_verified":False,
                     "impact":"Native SiteStop/Start"}
    class Query:
        def __init__(self,outer):
            self.outer=outer;self.root=False
        def where(self,key,params):
            self.root=key=="path=?"
            if self.root:assert params==(self.outer.site["path"],)
            else:assert key=="id=?" and params==(self.outer.site["id"],)
            return self
        def field(self,*args):return self
        def limit(self,limit):
            assert limit=="0,2";return self
        def select(self):
            assert self.root
            return [{"id":self.outer.site["id"]+i,"path":self.outer.site["path"]}
                    for i in range(self.outer.same_root)]
        def find(self):
            assert not self.root
            return dict(self.outer.site)
    @staticmethod
    def bindings(panel,sites):
        for site in sites:
            site["bound_domains"]=[{"name":site["name"],"port":80}]
    def payload(self,action="apply",**extra):
        result={"scope":"site","site_id":"7","template":"stopped",
                "locale":"en","stopped_action":action,
                "stopped_approval":action+"_exact_native_stopped503_reload",
                "expected_revision":"0","expected_site_key":"demo.test",
                "expected_site_snapshot":json.dumps([
                    7,"demo.test","/www/demo.test",str(self.site["status"]),[["demo.test",80]]
                ],separators=(",",":")),
                "expected_vhost_sha256":"a"*64,
                "expected_render_sha256":render_page("en","stopped")["rendered_sha256"],
                "expected_recovery_id":"f"*32}
        result.update(extra);return result
    def invoke(self,action="apply",**extra):
        with patch.dict(sys.modules,{"flask":self.flask,"public":self.public}), \
             patch.object(backend,"_bound_domains_for_sites",side_effect=self.bindings), \
             patch.object(target,"manage_stopped",return_value=self.result) as delegate:
            output=self.plugin.status_stopped(self.payload(action,**extra))
        return output,delegate
    def test_exact_native_site_approval_and_data_binding(self):
        out,delegate=self.invoke()
        self.assertTrue(out["status"],out)
        self.assertEqual(out["verified_site_snapshot"],self.payload()["expected_site_snapshot"])
        self.assertEqual(out["stopped_action"],"apply")
        self.assertEqual(delegate.call_count,1)
        self.assertEqual(delegate.call_args.args[0],"apply")
        self.assertEqual(delegate.call_args.args[1]["name"],"demo.test")
        self.assertEqual(delegate.call_args.kwargs["expected_render"],
                         self.payload()["expected_render_sha256"])
        self.assertEqual(delegate.call_args.kwargs["expected_vhost"],"a"*64)
        self.assertEqual(delegate.call_args.kwargs["expected_recovery"],"f"*32)
        records=read_activity(self.tmp.name,module="status_pages",limit=15)
        self.assertTrue(records)
        self.assertEqual(records[0]["recovery_id"],"f"*32)
        self.assertEqual(records[0]["action"],"status_stopped_apply")
    def test_primary_admin_and_temporary_identity_denied_before_delegation(self):
        for uid,temp,method in ((2,False,"POST"),(1,True,"POST"),(1,False,"GET")):
            self.flask.session={"login":True,"uid":uid}
            if temp:self.flask.session["tmp_login_id"]="T"
            self.flask.request.method=method
            out,delegate=self.invoke()
            self.assertFalse(out["status"],out)
            self.assertEqual(out["stage"],"status_stopped_authorization")
            self.assertEqual(delegate.call_count,0)
    def test_wrong_approval_scope_site_snapshot_and_root_denied(self):
        for change in ({"stopped_approval":""},{"scope":"global"},
                       {"template":"404"},{"expected_site_snapshot":"[]"},
                       {"expected_site_key":"other.test"}):
            out,delegate=self.invoke(**change)
            self.assertFalse(out["status"],out)
            self.assertEqual(delegate.call_count,0)
        self.same_root=2
        out,delegate=self.invoke()
        self.assertFalse(out["status"],out)
        self.assertEqual(delegate.call_count,0)
    def test_stopped_site_cannot_be_armed_but_can_recheck_or_restore(self):
        self.site["status"]="0"
        self.result.update(state="Applied",site_status="0",runtime_verified=True)
        out,delegate=self.invoke()
        self.assertFalse(out["status"],out)
        self.assertEqual(delegate.call_count,0)
        self.result.update(state="Restored",read_only=False)
        out,delegate=self.invoke("restore")
        self.assertTrue(out["status"],out)
        self.assertEqual(delegate.call_args.args[0],"restore")
    def test_stale_brand_revision_and_wrong_panel_version_denied(self):
        out,delegate=self.invoke(expected_revision="12")
        self.assertFalse(out["status"],out)
        self.assertEqual(delegate.call_count,0)
        self.version="8.0.8"
        out,delegate=self.invoke()
        self.assertFalse(out["status"],out)
        self.assertEqual(delegate.call_count,0)
    def test_preserve_recovery_id_on_uncertain_outcome(self):
        with patch.dict(sys.modules,{"flask":self.flask,"public":self.public}), \
             patch.object(backend,"_bound_domains_for_sites",side_effect=self.bindings), \
             patch.object(target,"manage_stopped",side_effect=target.ExtensionError(
                 "uncertain","Restart or inspect before retry",recovery_id="c"*32)):
            result=self.plugin.status_stopped(self.payload())
        self.assertFalse(result["status"],result)
        self.assertTrue(result["recovery_required"])
        self.assertEqual(result["recovery_id"],"c"*32)
        self.assertEqual(result["stage"],"status_stopped_uncertain")
