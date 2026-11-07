"""Native authorization, site binding and revision gates for site-only 404."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PACKAGE))
import ach_customizer_main as backend
import ach_customizer_status_manage as manager
from ach_customizer_status_pages import render_page


class NativeStatusManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch_state = patch.object(backend, "_STATE_DIR", self.tmp.name)
        self.patch_state.start()
        self.addCleanup(self.patch_state.stop)
        self.plugin = backend.ach_customizer_main()
        self.site = dict(id=7, name="demo.test", path="/www/demo.test", status="1")
        self.seen = 0
        self.version = "8.0.7"
        self.engine = "nginx"
        self.same_root_sites = 1

    def public(self):
        module = types.ModuleType("public")
        outer = self

        class Query:
            def __init__(self):
                self.by_root = False

            def where(self, expression, params):
                self.by_root = expression == "path=?"
                if self.by_root:
                    assert params == (outer.site["path"],), "Native site root query must be bound"
                return self

            def field(self, *args):
                return self

            def limit(self, n):
                assert n == "0,2"
                return self

            def select(self):
                assert self.by_root
                return [
                    {"id": outer.site["id"] + offset, "path": outer.site["path"]}
                    for offset in range(outer.same_root_sites)
                ]

            def find(self):
                outer.seen += 1
                return dict(outer.site)

        module.M = lambda table: Query() if table == "sites" else None
        module.get_webserver = lambda: outer.engine
        module.get_panel_version = lambda: outer.version
        return module

    @staticmethod
    def flask(uid=1, method="POST", temporary=False):
        m = types.ModuleType("flask")
        m.has_request_context = lambda: True
        m.request = types.SimpleNamespace(method=method)
        m.session = {"login": True, "uid": uid}
        if temporary:
            m.session["tmp_login_id"] = "temp"
        return m

    @staticmethod
    def bindings(_panel, sites):
        for item in sites:
            item["bound_domains"] = [{"name": item["name"], "port": 80}]
            item["canonical_domain_bound"] = True

    def args(self, action="apply", **fields):
        values = {
            "site_action": action, "scope": "site",
            "site_id": "7", "template": "404", "locale": "en",
            "site_approval": "apply_exact_site_404" if action == "apply"
                             else "restore_exact_site_404" if action == "restore" else "",
            "expected_revision": "0",
            "expected_site_key": "demo.test",
            "expected_site_snapshot": json.dumps([
                7, "demo.test", "/www/demo.test", "1", [["demo.test", 80]]
            ], separators=(",", ":")),
            "expected_page_sha256": "a" * 64,
            "expected_vhost_sha256": "b" * 64,
            "expected_render_sha256": render_page("en", "404")["rendered_sha256"],
            "expected_recovery_id": "c" * 32,
        }
        values.update(fields)
        return values

    def run_api(self, args, flask=None, manager_result=None):
        if flask is None:
            flask = self.flask()
        if manager_result is None:
            manager_result = {"state": "Applied", "changed": True,
                              "site_id": 7, "page_file_sha256": "a" * 64,
                              "recovery_id": "c" * 32,
                              "read_only": False, "mode": "native_existing_404_file"}
        with patch.dict(sys.modules, {"public": self.public(), "flask": flask}), \
             patch.object(backend, "_bound_domains_for_sites", side_effect=self.bindings), \
             patch.object(manager, "manage_site_404", return_value=manager_result) as applied:
            return self.plugin.status_manage(args), applied.call_args

    def test_apply_enforces_primary_admin_native_identity_and_hash_contract(self):
        response, call = self.run_api(self.args())
        self.assertTrue(response["status"], response)
        self.assertEqual(response["state"], "Applied")
        self.assertEqual(response["site_action"], "apply")
        self.assertEqual(response["verified_site_snapshot"],
                         self.args()["expected_site_snapshot"])
        self.assertEqual(call.args[0], "apply")
        self.assertEqual(call.args[1]["name"], "demo.test")
        self.assertEqual(call.kwargs["expected_current"], "a" * 64)
        self.assertEqual(call.kwargs["expected_vhost"], "b" * 64)
        self.assertEqual(call.kwargs["expected_render"],
                         render_page("en", "404")["rendered_sha256"])
        self.assertEqual(call.kwargs["expected_recovery"], "c" * 32)

    def test_apply_activity_records_saved_recovery_id_not_request_id(self):
        from ach_customizer_activity import read_activity
        response, _call = self.run_api(self.args())
        self.assertTrue(response["status"])
        self.assertNotEqual(response["request_id"], response["recovery_id"])
        events = read_activity(self.tmp.name, module="status_pages", limit=10)
        self.assertTrue(events)
        self.assertEqual(events[0]["operation_id"], response["request_id"])
        self.assertEqual(events[0]["recovery_id"], response["recovery_id"])
        self.assertEqual(events[0]["stage"], "complete")

    def test_uncertain_failure_keeps_verified_recovery_identity(self):
        from ach_customizer_activity import read_activity
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(backend, "_bound_domains_for_sites", side_effect=self.bindings), \
             patch.object(manager, "manage_site_404", side_effect=manager.StatusManageError(
                 "uncertain", "An interrupted recovery journal was preserved",
                 recovery_id="c" * 32)):
            result = self.plugin.status_manage(self.args())
        self.assertFalse(result["status"], result)
        self.assertEqual(result["stage"], "status_manage_uncertain")
        self.assertTrue(result["recovery_required"])
        self.assertEqual(result["recovery_id"], "c" * 32)
        event = read_activity(self.tmp.name, module="status_pages", limit=10)[0]
        self.assertEqual(event["recovery_id"], "c" * 32)
        self.assertEqual(event["operation_id"], result["operation_id"])

    def test_backup_failure_reports_controlled_stage_without_false_restore(self):
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(backend, "_bound_domains_for_sites", side_effect=self.bindings), \
             patch.object(manager, "manage_site_404", side_effect=manager.StatusManageError(
                 "backup", "Original bytes could not be stored")):
            result = self.plugin.status_manage(self.args())
        self.assertFalse(result["status"])
        self.assertEqual(result["stage"], "status_manage_backup")
        self.assertNotIn("recovery_required", result)
        self.assertNotIn("recovery_id", result)

    def test_recheck_is_read_only_but_not_an_auth_bypass(self):
        response, call = self.run_api(
            self.args("recheck"),
            manager_result={"state": "Unmanaged", "changed": False,
                            "site_id": 7, "page_file_sha256": "a" * 64,
                            "rendered_sha256": "b" * 64,
                            "before_sha256": None, "after_sha256": None,
                            "recovery_id": None, "read_only": True,
                            "mode": "native_existing_404_file"})
        self.assertTrue(response["status"])
        self.assertEqual(call.args[0], "recheck")

    def test_orphan_recheck_is_visible_as_warning_without_a_restore_identity(self):
        from ach_customizer_activity import read_activity
        response, call = self.run_api(
            self.args("recheck"),
            manager_result={"state": "Orphan Backup", "changed": False,
                            "site_id": 7, "page_file_sha256": "a" * 64,
                            "rendered_sha256": "b" * 64,
                            "before_sha256": "a" * 64,
                            "after_sha256": None, "recovery_id": None,
                            "read_only": True, "mode": "native_existing_404_file"})
        self.assertTrue(response["status"], response)
        self.assertEqual(response["state"], "Orphan Backup")
        self.assertIsNone(response["recovery_id"])
        self.assertTrue(response["read_only"])
        self.assertEqual(call.args[0], "recheck")
        rows = read_activity(self.tmp.name, module="status_pages", limit=10)
        self.assertTrue(any(row["action"] == "status_recheck" and
                            row["level"] == "WARNING" and
                            row["outcome"] == "Orphan Backup"
                            for row in rows), rows)

    def test_denied_sessions_and_missing_approval_never_reach_manager(self):
        for args, flask in (
            (self.args(), self.flask(uid=2)),
            (self.args(), self.flask(method="GET")),
            (self.args(), self.flask(temporary=True)),
            (self.args(site_approval=""), self.flask()),
            (self.args("restore", site_approval=""), self.flask()),
            (self.args(template="502"), self.flask()),
            (self.args(scope="global"), self.flask()),
        ):
            with self.subTest(args=args["site_action"], uid=flask.session["uid"]):
                response, call = self.run_api(args, flask)
                self.assertFalse(response["status"], response)
                self.assertIsNone(call)

    def test_rejects_wrong_panel_engine_site_binding_and_revision(self):
        cases = [
            ("version", {"version": "8.1.1"}, {}),
            ("engine", {"engine": "apache"}, {}),
            ("site", {"site": dict(id=7, name="renamed.test",
                                   path="/www/demo.test", status="1")}, {}),
            ("revision", {}, {"expected_revision": "9"}),
            ("domain", {}, {"expected_site_snapshot": json.dumps([
                7, "demo.test", "/www/demo.test", "1", [["demo.test", 443]]
            ])}),
        ]
        for name, changes, args in cases:
            with self.subTest(name=name):
                self.version = "8.0.7"
                self.engine = "nginx"
                self.site = dict(id=7, name="demo.test", path="/www/demo.test", status="1")
                for key, value in changes.items():
                    setattr(self, key, value)
                response, call = self.run_api(self.args(**args))
                self.assertFalse(response["status"], response)
                self.assertIsNone(call)

    def test_shared_or_unresolved_native_root_blocks_404_write(self):
        for count in (0, 2):
            with self.subTest(native_site_count=count):
                self.same_root_sites = count
                response, call = self.run_api(self.args())
                self.assertFalse(response["status"])
                self.assertIn("document root", response["msg"])
                self.assertIsNone(call)
        self.same_root_sites = 1

    def test_root_sharing_discovered_after_write_is_uncertain_and_requires_recovery(self):
        def changed_after_mutation(*args, **kwargs):
            self.same_root_sites = 2
            return {
                "state": "Applied", "changed": True, "site_id": 7,
                "page_file_sha256": "a" * 64, "recovery_id": "c" * 32,
                "read_only": False, "mode": "native_existing_404_file"
            }
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}),              patch.object(backend, "_bound_domains_for_sites", side_effect=self.bindings),              patch.object(manager, "manage_site_404", side_effect=changed_after_mutation):
            response = self.plugin.status_manage(self.args())
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "status_manage_uncertain")
        self.assertTrue(response["recovery_required"])
        self.same_root_sites = 1

    def test_backend_failure_does_not_hide_recovery_required_stage(self):
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(backend, "_bound_domains_for_sites", side_effect=self.bindings), \
             patch.object(manager, "manage_site_404", side_effect=manager.StatusManageError(
                 "uncertain", "404 transaction uncertain; journal preserved")):
            result = self.plugin.status_manage(self.args())
        self.assertFalse(result["status"])
        self.assertEqual(result["stage"], "status_manage_uncertain")
        self.assertTrue(result["recovery_required"])
        self.assertIn("journal", result["msg"])


if __name__ == "__main__":
    unittest.main()
