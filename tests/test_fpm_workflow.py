"""Authorization, compatibility and approval contracts before native UI wiring."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin/ach_customizer"))
import ach_customizer_fpm_apply as core
import ach_customizer_fpm_workflow as workflow

SOURCE = b"""[global]
pid=/tmp/example.pid
[www]
pm=dynamic
listen=/tmp/php-cgi-85.sock
pm.max_children=50
pm.start_servers=5
pm.min_spare_servers=5
pm.max_spare_servers=20
"""
VALUES = {"php_version": "85", "max_children": "20", "start_servers": "5",
          "min_spare_servers": "5", "max_spare_servers": "10", "max_requests": "300"}


class TestManualFpmWorkflow(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name)
        self.config_root=self.base/"php"
        self.config=(self.config_root/"85"/"etc"/"php-fpm.conf")
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(SOURCE)
        self.config.chmod(0o644)
        self.state_dir=self.base/"data"
        self.state_dir.mkdir(mode=0o700)
        self.state={"revision":0,"enabled":True,"modules":{"php_fpm_file_preview":True}}
        self.panel=types.SimpleNamespace(get_panel_version=lambda:"8.0.7",get_webserver=lambda:"nginx")
        self.impact={
            "schema":1,"state":"File Mapping","scope":"shared_service","version":"85",
            "matched_sites":[{"id":3,"site_key":"example-a.test"},{"id":6,"site_key":"example-b.test"}],
            "unresolved_sites":[],"site_count":2,"other_php_sites_count":0,
            "dependency_sha256":"a"*64,
            "note":"FILE mapping, not effective runtime",
        }
        self.calls=[]
        def hooks(_version, _desired):
            def record_validate(): self.calls.append("validate")
            def record_activate(): self.calls.append("activate")
            def record_verify(): self.calls.append("verify")
            return record_validate, record_activate, record_verify
        self.controller=workflow.ManualFpmWorkflow(
            public=self.panel, config_root=self.config_root,data_dir=self.state_dir,
            state_reader=lambda:self.state,
            impact_lookup=lambda panel, version, source:self.impact,
            hooks_factory=hooks)
        self.flask=types.ModuleType("flask")
        self.flask.session={"uid":1,"login":True}
        self.flask.request=types.SimpleNamespace(method="POST")
        self.flask.has_request_context=lambda:True
        patcher=patch.dict(sys.modules,{"flask":self.flask})
        patcher.start()
        self.addCleanup(patcher.stop)

    def payload(self):
        prepared=self.controller.prepare(VALUES)
        return {**VALUES, "approved_scope":workflow.APPROVAL_SCOPE,
                "expected_revision":str(prepared["monitor_revision"]),
                "expected_before":prepared["plan"]["before_sha256"],
                "expected_after":prepared["plan"]["after_sha256"],
                "expected_impact":prepared["impact_sha256"]}

    def rollback_payload(self, operation_id):
        detail = self.controller.recovery({"php_version": "85"})
        self.assertTrue(detail["safe_rollback_file_match"])
        return {"php_version": "85", "operation_id": operation_id,
                "approved_scope": workflow.APPROVAL_SCOPE,
                "expected_impact": detail["impact_sha256"],
                "expected_recovery": detail["recovery_decision_sha256"]}

    def test_valid_full_admin_prepare_and_apply_then_recover(self):
        payload=self.payload()
        self.assertEqual(payload["expected_revision"],"0")
        self.assertEqual(self.config.read_bytes(),SOURCE)
        applied=self.controller.apply(payload)
        self.assertEqual(applied["state"],"Applied")
        self.assertEqual(self.calls,["validate","validate","activate","verify"])
        status=self.controller.recovery({"php_version":"85"})
        self.assertEqual(status["state"],"Applied")
        recovered=self.controller.rollback(self.rollback_payload(applied["operation_id"]))
        self.assertEqual(recovered["state"],"Rolled Back")
        self.assertEqual(self.config.read_bytes(),SOURCE)

    def test_controller_uses_original_effective_values_to_verify_auto_restore(self):
        expectations=[]
        def hooks(_version, desired):
            expectations.append(dict(desired))
            def validate(): pass
            def activate(): pass
            def verify():
                from ach_customizer_monitor import preview_php_fpm
                observed=preview_php_fpm(self.config_root,"85",desired)
                if observed["state"]!="File Match":
                    raise RuntimeError("Runtime verification expected a different FPM policy")
                if desired["pm.max_children"]==20:
                    raise RuntimeError("Injected downstream failure after candidate reload")
            return validate,activate,verify
        self.controller.hooks_factory=hooks
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.apply(self.payload())
        self.assertEqual(caught.exception.stage,"apply")
        self.assertEqual(expectations[0]["pm.max_children"],20)
        self.assertEqual(expectations[1]["pm.max_children"],50)
        self.assertEqual(expectations[1]["pm.max_spare_servers"],20)
        self.assertEqual(expectations[1]["pm.max_requests"],0)
        self.assertEqual(self.config.read_bytes(),SOURCE)
        self.assertFalse((self.state_dir/core.JOURNAL).exists())
        self.assertFalse((self.state_dir/core.SNAPSHOT).exists())

    def test_primary_session_and_temporary_markers_are_denied_before_any_planning(self):
        normal=dict(self.flask.session)
        checks=(
            ({"login":True,"uid":2},"POST",True),
            ({"login":True,"uid":"1"},"POST",True),
            ({"login":True,"uid":True},"POST",True),
            ({"login":False,"uid":1},"POST",True),
            ({**normal,"tmp_login":True},"POST",True),
            ({**normal,"tmp_login_id":""},"POST",True),
            ({**normal,"tmp_login_expire":0},"POST",True),
            (normal,"GET",True),
            (normal,"POST",False),
        )
        for session,method,context in checks:
            with self.subTest(session=session,method=method,context=context):
                self.flask.session=session
                self.flask.request.method=method
                self.flask.has_request_context=lambda context=context:context
                for call,args in ((self.controller.prepare,VALUES),
                                  (self.controller.apply,VALUES),
                                  (self.controller.recovery,{}),
                                  (self.controller.rollback,{})):
                    with self.assertRaises(core.FpmApplyError) as caught:
                        call(args)
                    self.assertEqual(caught.exception.stage,"fpm_authorization")
        self.assertEqual(self.config.read_bytes(),SOURCE)
        self.assertEqual(list(self.state_dir.iterdir()),[])

    def test_approval_and_staleness_fails_before_mutation(self):
        payload=self.payload()
        for change in ({"approved_scope":None},
                       {"expected_revision":"2"},
                       {"expected_after":"0"*64},
                       {"expected_impact":"0"*64}):
            with self.subTest(change=change),self.assertRaises(core.FpmApplyError):
                self.controller.apply({**payload,**change})
            self.assertEqual(self.config.read_bytes(),SOURCE)
            self.assertEqual(list(self.state_dir.iterdir()),[])
        self.impact["matched_sites"][1]["site_key"]="renamed.test"
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.apply(payload)
        self.assertEqual(caught.exception.stage,"fpm_conflict")

    def test_last_moment_site_mapping_change_blocks_apply_before_backup(self):
        payload=self.payload()
        count=0
        def changing_impact(_panel,_version,_source):
            nonlocal count
            count+=1
            if count==2:
                self.impact["matched_sites"][1]["site_key"]="site-b-renamed.test"
            return self.impact
        self.controller.impact_lookup=changing_impact
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.apply(payload)
        self.assertEqual(caught.exception.stage,"fpm_conflict")
        self.assertEqual(self.config.read_bytes(),SOURCE)
        self.assertFalse((self.state_dir/core.JOURNAL).exists())
        self.assertFalse((self.state_dir/core.SNAPSHOT).exists())

    def test_last_moment_monitor_change_blocks_apply_under_state_lock(self):
        payload=self.payload()
        count=0
        def changing_state():
            nonlocal count
            count+=1
            if count == 2:
                self.state["revision"]=1
            return self.state
        self.controller.state_reader=changing_state
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.apply(payload)
        self.assertEqual(caught.exception.stage,"fpm_conflict")
        self.assertEqual(self.config.read_bytes(),SOURCE)
        self.assertFalse((self.state_dir/core.JOURNAL).exists())

    def test_impact_counts_and_identifiers_fail_closed(self):
        original=[dict(site) for site in self.impact["matched_sites"]]
        self.impact["site_count"]=3
        with self.assertRaises(core.FpmApplyError):
            self.controller.prepare(VALUES)
        self.impact["site_count"]=2
        self.impact["matched_sites"][1]["id"]=3
        with self.assertRaises(core.FpmApplyError):
            self.controller.prepare(VALUES)
        self.impact["matched_sites"]=original
        self.impact["matched_sites"][0]["site_key"]="../unsafe"
        with self.assertRaises(core.FpmApplyError):
            self.controller.prepare(VALUES)

    def test_unresolved_sites_and_unsupported_version_reject(self):
        self.impact["unresolved_sites"].append({"id":12,"reason":"not verified"})
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.prepare(VALUES)
        self.assertEqual(caught.exception.stage,"fpm_impact")
        self.impact["unresolved_sites"].clear()
        self.panel.get_panel_version=lambda:"8.0.8"
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.prepare(VALUES)
        self.assertEqual(caught.exception.stage,"fpm_compatibility")
        self.panel.get_panel_version=lambda:"8.0.7"
        self.panel.get_webserver=lambda:"apache"
        with self.assertRaises(core.FpmApplyError):
            self.controller.prepare(VALUES)
        self.assertEqual(self.config.read_bytes(),SOURCE)

    def test_recovery_authorized_even_after_monitor_off(self):
        payload=self.payload()
        result=self.controller.apply(payload)
        self.state["enabled"]=False
        self.state["modules"]["php_fpm_file_preview"]=False
        with self.assertRaises(core.FpmApplyError):
            self.controller.prepare(VALUES)
        self.assertEqual(self.controller.recovery({})["state"],"Applied")
        self.assertEqual(self.controller.rollback(
            self.rollback_payload(result["operation_id"]))["state"],"Rolled Back")
        self.assertEqual(self.config.read_bytes(),SOURCE)

    def test_wrong_rollback_id_and_missing_approval_do_not_touch_file(self):
        payload=self.payload()
        result=self.controller.apply(payload)
        after=self.config.read_bytes()
        for args in ({"operation_id":result["operation_id"]},
                     {"operation_id":"0"*32,"approved_scope":workflow.APPROVAL_SCOPE},
                     {"operation_id":"bad","approved_scope":workflow.APPROVAL_SCOPE}):
            with self.assertRaises(core.FpmApplyError):
                self.controller.rollback(args)
            self.assertEqual(self.config.read_bytes(),after)

    def test_rollback_requires_new_site_removed_site_and_reassignment_approval(self):
        for change in ("added", "removed", "reassigned"):
            with self.subTest(change=change):
                self.impact = {
                    **self.impact,
                    "matched_sites": [
                        {"id": 3, "site_key": "example-a.test"},
                        {"id": 6, "site_key": "example-b.test"}
                    ],
                    "site_count": 2,
                    "other_php_sites_count": 0,
                    "dependency_sha256": "a" * 64,
                }
                applied = self.controller.apply(self.payload())
                stale = self.rollback_payload(applied["operation_id"])
                applied_bytes = self.config.read_bytes()
                if change == "added":
                    self.impact["matched_sites"].append({"id": 9, "site_key": "new-php85.test"})
                    self.impact["site_count"] = 3
                elif change == "removed":
                    self.impact["matched_sites"].pop()
                    self.impact["site_count"] = 1
                else:
                    self.impact["matched_sites"].pop()
                    self.impact["other_php_sites_count"] = 1
                with self.assertRaises(core.FpmApplyError) as caught:
                    self.controller.rollback(stale)
                self.assertEqual(caught.exception.stage, "fpm_conflict")
                self.assertEqual(self.config.read_bytes(), applied_bytes)
                self.assertTrue((self.state_dir / core.JOURNAL).exists())
                fresh = self.rollback_payload(applied["operation_id"])
                self.assertNotEqual(fresh["expected_impact"], stale["expected_impact"])
                status = self.controller.recovery({})
                self.assertEqual(status["restoration_changes"], [
                    {"setting": "pm.max_children", "current": 20, "baseline": 50},
                    {"setting": "pm.max_spare_servers", "current": 10, "baseline": 20},
                    {"setting": "pm.max_requests", "current": 300, "baseline": 0},
                ])
                self.assertEqual(self.controller.rollback(fresh)["state"], "Rolled Back")
                self.assertEqual(self.config.read_bytes(), SOURCE)

    def test_stale_dependency_or_unknown_routing_retains_recovery(self):
        applied = self.controller.apply(self.payload())
        old = self.rollback_payload(applied["operation_id"])
        self.impact["dependency_sha256"] = "b" * 64
        with self.assertRaises(core.FpmApplyError):
            self.controller.rollback(old)
        updated = self.rollback_payload(applied["operation_id"])
        self.assertNotEqual(old["expected_recovery"], updated["expected_recovery"])

        self.impact["state"] = "Needs Review"
        status = self.controller.recovery({})
        self.assertFalse(status["safe_rollback_file_match"])
        self.assertIn("manual_recovery", status)
        self.assertEqual(status["shared_impact"]["state"], "Needs Review")
        with self.assertRaises(core.FpmApplyError):
            self.controller.rollback(updated)
        self.assertTrue((self.state_dir / core.JOURNAL).exists())
        self.impact["state"] = "File Mapping"
        self.assertEqual(self.controller.rollback(
            self.rollback_payload(applied["operation_id"]))["state"], "Rolled Back")

    def test_last_moment_site_change_blocks_rollback_inside_core_lock(self):
        applied = self.controller.apply(self.payload())
        after = self.config.read_bytes()
        count = 0

        def changing_impact(_panel, _version, _source):
            nonlocal count
            count += 1
            if count == 3:
                self.impact["dependency_sha256"] = "c" * 64
            return self.impact

        self.controller.impact_lookup = changing_impact
        old = self.rollback_payload(applied["operation_id"])
        with self.assertRaises(core.FpmApplyError) as caught:
            self.controller.rollback(old)
        self.assertEqual(caught.exception.stage, "fpm_conflict")
        self.assertEqual(self.config.read_bytes(), after)
        self.assertTrue((self.state_dir / core.JOURNAL).exists())
        self.assertEqual(self.controller.rollback(
            self.rollback_payload(applied["operation_id"]))["state"], "Rolled Back")


if __name__=="__main__":
    unittest.main()
