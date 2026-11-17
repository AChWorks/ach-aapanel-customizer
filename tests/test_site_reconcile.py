"""End-to-end composition and stale-review refusal for selected native sites."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_site_changes import Panel
from ach_customizer_site_changes import compare, save_reviewed_baseline
import ach_customizer_site_reconcile as reconcile
import ach_customizer_main as main


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="ach-reconcile-")
        self.addCleanup(self.folder.cleanup)
        self.panel = Panel()
        self.site = {
            "id": 3, "name": "static.example.test", "path": "/srv/static", "status": 1,
            "bound_domains": [{"name": "static.example.test", "port": 80}],
        }
        self.vhost = {
            "schema": 1, "site_id": 3, "site_key": self.site["name"],
            "state": "File Match", "read_only": True, "runtime_verified": False,
            "fix_supported": False, "vhost_sha256": "b" * 64,
            "native_root": "/srv/static", "vhost_root": "/srv/static",
            "native_names": ["static.example.test"], "vhost_names": ["static.example.test"],
            "listen_ports": [80], "findings": [], "reason": "", "note": "File only.",
        }
        self.cache_source = {
            "state": "Source Observed", "source_sha256": "c" * 64,
            "php_version": None, "findings": [], "other_sites_same_zone": [],
            "other_sites_same_directory": [], "reason": "",
        }
        self.cache = {"state": "Unmanaged", "recovery_id": None,
                      "runtime_verified": False, "note": "No managed Cache."}
        self.vhost_patch = patch.object(reconcile, "inspect_vhost_drift",
                                        return_value=self.vhost)
        self.cache_patch = patch.object(reconcile, "inspect_site_fastcgi_cache",
                                        return_value=self.cache_source)
        self.journal_patch = patch.object(reconcile, "manage_cache",
                                          return_value=self.cache)
        for active in (self.vhost_patch, self.cache_patch, self.journal_patch):
            active.start()
            self.addCleanup(active.stop)

    def observe(self):
        return reconcile.inspect_selected_site(
            self.panel, dict(self.site), current_site=lambda: dict(self.site),
            directory=self.folder.name)

    def save(self):
        preview = compare(self.panel, directory=self.folder.name)
        return save_reviewed_baseline(
            self.panel, directory=self.folder.name,
            expected_revision=preview["baseline_revision"],
            expected_monitor_revision=preview["monitor_revision"],
            expected_source_sha256=preview["source_sha256"], reviewed="true")

    def test_new_site_baseline_and_real_native_domain_diff(self):
        missing = self.observe()
        self.assertEqual(missing["state"], "Changes Observed")
        self.assertEqual(missing["baseline"]["state"], "Baseline Missing")
        self.assertFalse(missing["apply_supported"])
        self.assertFalse(missing["restore_supported"])
        self.assertFalse(missing["runtime_verified"])
        self.save()
        self.assertEqual(self.observe()["baseline"]["state"], "Unchanged")
        self.panel.domains.append({
            "id": 99, "pid": 3, "name": "alias.example.test", "port": 80})
        self.site["bound_domains"].append({"name": "alias.example.test", "port": 80})
        changed = self.observe()
        self.assertEqual(changed["state"], "Changes Observed")
        self.assertEqual(changed["baseline"]["state"], "Changed")
        self.assertEqual(changed["baseline"]["fields"], ["bound_domains"])
        self.assertNotEqual(changed["baseline"]["before"], changed["baseline"]["after"])
        self.assertEqual(changed["vhost"]["state"], "File Match")
        self.assertFalse(changed["auto_reconcile"])

    def test_added_site_identified_without_silent_baseline_adoption(self):
        self.save()
        self.panel.sites.append(
            {"id": 25, "name": "new.example.test", "path": "/srv/new", "status": 1})
        self.panel.domains.append(
            {"id": 26, "pid": 25, "name": "new.example.test", "port": 80})
        self.site.update(id=25, name="new.example.test", path="/srv/new",
                         bound_domains=[{"name": "new.example.test", "port": 80}])
        self.vhost["site_id"] = 25
        self.vhost["site_key"] = "new.example.test"
        result = self.observe()
        self.assertEqual(result["baseline"]["state"], "Added")
        self.assertEqual(result["baseline"]["after"]["id"], 25)
        self.assertFalse(result["apply_supported"])

    def test_regeneration_divergence_and_saved_recovery_needs_review(self):
        self.save()
        self.vhost["state"] = "File Drift"
        self.vhost["findings"] = ["BOUND_HOST_MISSING_IN_VHOST"]
        self.cache.update(state="Needs Review", recovery_id="d" * 32,
                          journal_phase="applied", note="Managed source changed.")
        r = self.observe()
        self.assertEqual(r["state"], "Needs Review")
        self.assertEqual(r["baseline"]["state"], "Unchanged")
        self.assertEqual(r["cache_recovery"]["recovery_id"], "d" * 32)
        self.assertEqual(r["cache_recovery"]["state"], "Needs Review")
        self.assertFalse(r["restore_supported"])
        reconcile.manage_cache.assert_called_with(
            "recheck", self.site, self.panel, data_dir=self.folder.name)

    def test_unverified_cache_source_is_visible_and_does_not_claim_php(self):
        self.cache_source.update(state="Partial", php_version="85",
                                 reason="Unresolved native extension.")
        r = self.observe()
        self.assertEqual(r["state"], "Needs Review")
        self.assertEqual(r["php_policy"]["state"], "Not Inspected")
        self.assertIsNone(r["cache_source"]["php_version"])

    def test_shared_php_policy_drift_and_peer_scope(self):
        self.save()
        self.cache_source["php_version"] = "85"
        policy = {
            "schema": 1, "version": "85", "policy_revision": 7,
            "monitor_revision": 0, "saved": True,
            "desired": {"pm.max_children": 30},
        }
        impact = {"schema": 1, "state": "File Match", "matched_sites": [
            {"id": 3, "site_key": "static.example.test"},
            {"id": 6, "site_key": "wp.example.test"}], "unresolved_sites": []}
        with patch.object(reconcile, "get_policy", return_value=policy), \
             patch.object(reconcile, "observe", return_value=({
                 "state": "File Drift", "changes": [{"key": "pm.max_children",
                 "desired": 30, "current": 20}], "source": "/tmp/php"
             }, "e" * 64)), \
             patch.object(reconcile, "inspect_php_fpm_site_impact",
                          return_value=impact):
            result = self.observe()
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(result["php_policy"]["state"], "File Drift")
        self.assertEqual(result["php_policy"]["desired"]["pm.max_children"], 30)
        self.assertEqual(len(result["php_policy"]["shared_impact"]["matched_sites"]), 2)
        self.assertFalse(result["apply_supported"])

    def test_native_id_reused_or_site_changed_during_read_refuses_report(self):
        self.save()
        with self.assertRaisesRegex(reconcile.ReconciliationError, "selected site"):
            reconcile.inspect_selected_site(
                self.panel, self.site,
                current_site=lambda: {**self.site, "name": "different.example.test"},
                directory=self.folder.name)

    def test_baseline_or_monitor_race_refuses_combined_result(self):
        self.save()
        actual = reconcile.read_baseline
        reads = 0
        def mutate_baseline(dir):
            nonlocal reads
            reads += 1
            original = actual(dir)
            if reads == 2:
                return {**original, "revision": original["revision"] + 1}
            return original
        with patch.object(reconcile, "read_baseline", side_effect=mutate_baseline):
            with self.assertRaisesRegex(reconcile.ReconciliationError, "baseline changed"):
                self.observe()
        policy = reconcile.read_state(self.folder.name)
        with patch.object(reconcile, "read_state", side_effect=[
                policy, {**policy, "revision": policy["revision"] + 1}]):
            with self.assertRaisesRegex(reconcile.ReconciliationError, "Monitor changed"):
                self.observe()

    def test_late_policy_revision_race_rejects_combined_evidence(self):
        self.save()
        self.cache_source["php_version"] = "85"
        good = {"schema": 1, "version": "85", "policy_revision": 2,
                "saved": True, "desired": {"pm.max_children": 50}}
        changed = {**good, "policy_revision": 3}
        with patch.object(reconcile, "get_policy",
                          side_effect=[good, good, changed]), \
             patch.object(reconcile, "observe", return_value=({
                 "state": "File Match", "changes": [],
                 "source": "/tmp/php-fpm.conf"
             }, "f" * 64)), \
             patch.object(reconcile, "inspect_php_fpm_site_impact",
                          return_value={"state": "File Match", "matched_sites": [],
                                        "unresolved_sites": []}):
            with self.assertRaisesRegex(reconcile.ReconciliationError, "policy changed"):
                self.observe()

    def test_late_vhost_regeneration_rejects_stale_combined_evidence(self):
        self.save()
        different = {**self.vhost, "vhost_sha256": "f" * 64}
        with patch.object(reconcile, "inspect_vhost_drift",
                          side_effect=[self.vhost, different]):
            with self.assertRaisesRegex(reconcile.ReconciliationError,
                                        "VHost changed"):
                self.observe()

    def test_recheck_exception_reports_review_without_losing_other_evidence(self):
        self.save()
        with patch.object(reconcile, "manage_cache",
                          side_effect=reconcile.CacheManageError("recovery", "Journal conflict")):
            response = self.observe()
        self.assertEqual(response["cache_recovery"]["state"], "Needs Review")
        self.assertIn("Journal conflict", response["cache_recovery"]["note"])
        self.assertEqual(response["state"], "Needs Review")


class ReconciliationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.main = main.ach_customizer_main()
        self.site = {"id": 3, "name": "static.example.test", "path": "/srv/static",
                     "status": "1", "bound_domains": [
                         {"name": "static.example.test", "port": 80}]}
        self.temp = tempfile.TemporaryDirectory(prefix="ach-reconcile-endpoint-")
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(main, "_STATE_DIR", self.temp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.args = {
            "site_id": "3", "expected_site_key": "static.example.test",
            "expected_site_snapshot":
                '[3,"static.example.test","/srv/static","1",[["static.example.test",80]]]'
        }

    @staticmethod
    def flask(uid=1, method="POST", tmp=False):
        module = types.ModuleType("flask")
        module.has_request_context = lambda: True
        module.request = types.SimpleNamespace(method=method)
        module.session = {"login": True, "uid": uid}
        if tmp:
            module.session["tmp_login_id"] = "temporary"
        return module

    def test_only_primary_admin_post_is_allowed_to_read_site_recovery(self):
        for values in ({"uid": 2}, {"method": "GET"}, {"tmp": True}):
            with self.subTest(values=values), \
                 patch.dict(sys.modules, {"flask": self.flask(**values)}), \
                 patch.object(self.main, "_selected_native_website") as selected, \
                 patch.object(self.main, "_require_enabled") as monitor, \
                 patch.object(reconcile, "inspect_selected_site") as inspect:
                r = self.main.inspect_site_reconciliation(self.args)
                self.assertFalse(r["status"], r)
                self.assertEqual(r["stage"], "website_reconciliation_authorization")
                selected.assert_not_called()
                monitor.assert_not_called()
                inspect.assert_not_called()

    def test_selected_baseline_action_requires_primary_admin_post(self):
        import ach_customizer_site_changes as changes
        for values in ({"uid": 2}, {"method": "GET"}, {"tmp": True}):
            with self.subTest(values=values), \
                 patch.dict(sys.modules, {"flask": self.flask(**values)}), \
                 patch.object(self.main, "_selected_native_website") as selected, \
                 patch.object(self.main, "_require_enabled") as monitor, \
                 patch.object(changes, "save_reviewed_selected_site_baseline") as save:
                r = self.main.save_selected_site_baseline(self.args)
                self.assertFalse(r["status"], r)
                self.assertEqual(r["stage"], "website_selected_baseline_authorization")
                selected.assert_not_called()
                monitor.assert_not_called()
                save.assert_not_called()

    def test_selected_baseline_action_uses_native_reader_not_client_path(self):
        import ach_customizer_site_changes as changes
        approved = {
            "schema": 1, "scope": "selected_site_only",
            "state": "Selected Site Baseline Saved",
            "site_id": 3, "site_key": "static.example.test",
            "baseline_revision": 2, "source_sha256": "a" * 64,
            "baseline_sha256": "b" * 64, "changed": True,
            "runtime_verified": False,
        }
        with patch.dict(sys.modules, {"flask": self.flask()}), \
             patch.object(self.main, "_require_enabled") as monitor, \
             patch.object(self.main, "_selected_native_website",
                          return_value=(object(), self.site, lambda: self.site)), \
             patch.object(changes, "save_reviewed_selected_site_baseline",
                          return_value=approved) as save:
            result = self.main.save_selected_site_baseline({
                **self.args, "expected_revision": "1",
                "expected_monitor_revision": "0",
                "expected_source_sha256": "a" * 64,
                "reviewed": "true", "apply": "true",
                "path": "/etc/passwd", "site_key": "attacker.test",
                "recovery_id": "f" * 32,
            })
        self.assertTrue(result["status"], result)
        self.assertEqual(result["scope"], "selected_site_only")
        self.assertEqual(result["baseline_sha256"], "b" * 64)
        self.assertEqual(monitor.call_args.args, ("site_inventory",))
        kwargs = save.call_args.kwargs
        self.assertIs(kwargs["selected_site"], self.site)
        self.assertEqual(kwargs["current_site"](), self.site)
        self.assertEqual(kwargs["expected_revision"], "1")
        self.assertEqual(kwargs["expected_monitor_revision"], "0")
        self.assertEqual(kwargs["expected_source_sha256"], "a" * 64)
        self.assertEqual(kwargs["reviewed"], "true")
        self.assertNotIn("apply", kwargs)
        self.assertNotIn("path", kwargs)
        self.assertNotIn("recovery_id", kwargs)
        self.assertEqual(kwargs["directory"], main._STATE_DIR)

    def test_endpoint_preserves_native_id_and_comparison_only_arguments(self):
        response = {"schema": 1, "site_id": 3, "site_key": "static.example.test",
                    "state": "Needs Review", "read_only": True, "apply_supported": False,
                    "cache_recovery": {"state": "Needs Review", "recovery_id": "b" * 32}}
        with patch.dict(sys.modules, {"flask": self.flask()}), \
             patch.object(self.main, "_require_enabled"), \
             patch.object(self.main, "_selected_native_website",
                          return_value=(object(), self.site, lambda: self.site)), \
             patch.object(reconcile, "inspect_selected_site",
                          return_value=response) as inspect:
            r = self.main.inspect_site_reconciliation({
                **self.args, "approved": "true", "apply": "true",
                "path": "/etc/passwd", "recovery_id": "a" * 32})
        self.assertTrue(r["status"], r)
        self.assertEqual(r["cache_recovery"]["recovery_id"], "b" * 32)
        kwargs = inspect.call_args.kwargs
        self.assertEqual(kwargs["current_site"](), self.site)
        self.assertEqual(inspect.call_args.args[1], self.site)
        self.assertEqual(kwargs["directory"], main._STATE_DIR)
        self.assertNotIn("approved", kwargs)

    def assert_domain_failure(self, response, *, directory, stage, cause, error_class):
        import re
        from ach_customizer_activity import read_activity

        self.assertFalse(response["status"], response)
        self.assertEqual(response["stage"], stage)
        self.assertIn(cause, response["msg"])
        self.assertRegex(response["operation_id"], r"^[0-9a-f]{32}$")
        self.assertTrue(response["activity_logged"], response)
        events = read_activity(directory)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["operation_id"], response["operation_id"])
        self.assertEqual(event["module"], "websites")
        self.assertEqual(event["action"], stage)
        self.assertEqual(event["stage"], stage)
        self.assertEqual(event["level"], "ERROR")
        self.assertEqual(event["outcome"], "failed")
        self.assertEqual(event["error_class"], error_class)
        self.assertIn(cause, event["detail"])
        self.assertEqual(event["recovery_id"], "")

    def test_scoped_save_real_domain_races_keep_reason_and_write_nothing(self):
        from copy import deepcopy
        from ach_customizer_site_changes import read_baseline
        from ach_customizer_state import set_enabled

        failures = (
            ("baseline", "Site baseline revision changed; Compare again"),
            ("monitor", "Website Monitor revision changed; Compare again"),
            ("source", "Native sites changed since comparison; Compare again"),
        )
        for failure, cause in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(
                    prefix="ach-endpoint-race-") as directory:
                panel = Panel()
                preview = compare(panel, directory=directory)
                if failure == "baseline":
                    save_reviewed_baseline(
                        panel, directory=directory,
                        expected_revision=preview["baseline_revision"],
                        expected_monitor_revision=preview["monitor_revision"],
                        expected_source_sha256=preview["source_sha256"],
                        reviewed="true")
                elif failure == "monitor":
                    set_enabled("php_fpm_file_preview", False, directory=directory,
                                expected_revision=preview["monitor_revision"])
                else:
                    # Drift on a different website must still block the full
                    # source comparison; it cannot be accepted by this Save.
                    panel.sites[1]["path"] = "/srv/peer-changed"
                baseline_before = read_baseline(directory)
                native_before = deepcopy((panel.sites, panel.domains))
                with patch.object(main, "_STATE_DIR", directory), \
                     patch.dict(sys.modules, {"flask": self.flask()}), \
                     patch.object(self.main, "_selected_native_website",
                                  return_value=(panel, self.site, lambda: self.site)):
                    result = self.main.save_selected_site_baseline({
                        **self.args,
                        "expected_revision": preview["baseline_revision"],
                        "expected_monitor_revision": preview["monitor_revision"],
                        "expected_source_sha256": preview["source_sha256"],
                        "reviewed": "true",
                    })
                self.assert_domain_failure(
                    result, directory=directory,
                    stage="website_selected_baseline_save",
                    cause=cause, error_class="SiteChangesError")
                self.assertEqual(read_baseline(directory), baseline_before)
                self.assertEqual((panel.sites, panel.domains), native_before)

    def test_late_vhost_and_php_revision_fail_at_real_reconciliation_boundary(self):
        from copy import deepcopy
        from ach_customizer_site_changes import read_baseline
        for failure, cause in (
                ("vhost", "Generated VHost changed during review; inspect again"),
                ("policy", "Saved shared PHP policy changed during review")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(
                    prefix="ach-endpoint-review-") as directory:
                panel = Panel()
                preview = compare(panel, directory=directory)
                save_reviewed_baseline(
                    panel, directory=directory,
                    expected_revision=preview["baseline_revision"],
                    expected_monitor_revision=preview["monitor_revision"],
                    expected_source_sha256=preview["source_sha256"],
                    reviewed="true")
                baseline_before = read_baseline(directory)
                native_before = deepcopy((panel.sites, panel.domains))
                vhost = {"state": "File Match", "vhost_sha256": "a" * 64}
                other_vhost = {**vhost, "vhost_sha256": "b" * 64}
                source = {"state": "Source Observed", "php_version":
                          "85" if failure == "policy" else None}
                initial_policy = {"saved": False, "policy_revision": 2,
                                  "desired": None}
                changed_policy = {**initial_policy, "policy_revision": 3}
                with patch.object(main, "_STATE_DIR", directory), \
                     patch.dict(sys.modules, {"flask": self.flask()}), \
                     patch.object(self.main, "_selected_native_website",
                                  return_value=(panel, self.site, lambda: self.site)), \
                     patch.object(reconcile, "inspect_vhost_drift",
                                  side_effect=([vhost, other_vhost]
                                               if failure == "vhost" else
                                               [vhost, vhost])), \
                     patch.object(reconcile, "inspect_site_fastcgi_cache",
                                  return_value=source), \
                     patch.object(reconcile, "manage_cache",
                                  return_value={"state": "Unmanaged", "note": ""}), \
                     patch.object(reconcile, "get_policy",
                                  side_effect=([initial_policy, changed_policy]
                                               if failure == "policy" else [])) as get_policy:
                    result = self.main.inspect_site_reconciliation(self.args)
                self.assert_domain_failure(
                    result, directory=directory,
                    stage="website_reconciliation_read",
                    cause=cause, error_class="ReconciliationError")
                self.assertEqual(read_baseline(directory), baseline_before)
                self.assertEqual((panel.sites, panel.domains), native_before)
                self.assertEqual(get_policy.call_count, 2 if failure == "policy" else 0)

    def test_reconciliation_nested_site_compare_error_retains_safe_reason(self):
        # The combined reader invokes site_changes.compare(), which has its
        # own typed failures and must not lose those details at this endpoint.
        from ach_customizer_site_changes import read_baseline, SiteChangesError
        from copy import deepcopy

        with tempfile.TemporaryDirectory(prefix="ach-reconcile-source-") as directory:
            panel = Panel()
            before = read_baseline(directory)
            native_before = deepcopy((panel.sites, panel.domains))
            with patch.object(main, "_STATE_DIR", directory), \
                 patch.dict(sys.modules, {"flask": self.flask()}), \
                 patch.object(self.main, "_selected_native_website",
                              return_value=(panel, self.site, lambda: self.site)), \
                 patch("ach_customizer_site_changes.get_site_page",
                       side_effect=SiteChangesError(
                           "Native site or binding records changed during inspection; compare again")):
                result = self.main.inspect_site_reconciliation(self.args)
            self.assert_domain_failure(
                result, directory=directory,
                stage="website_reconciliation_read",
                cause="Native site or binding records changed during inspection; compare again",
                error_class="SiteChangesError")
            self.assertEqual(read_baseline(directory), before)
            self.assertEqual((panel.sites, panel.domains), native_before)

    def test_unexpected_save_and_read_errors_are_redacted_in_browser_and_activity(self):
        from ach_customizer_activity import read_activity
        import ach_customizer_site_changes as changes

        for endpoint, source in (
                ("save_selected_site_baseline", changes),
                ("inspect_site_reconciliation", reconcile)):
            for error_type in (OSError, ValueError, RuntimeError):
                with self.subTest(endpoint=endpoint, error_type=error_type.__name__), \
                     tempfile.TemporaryDirectory(prefix="ach-unexpected-") as directory:
                    secret = "SYNTHETIC-CREDENTIAL-DO-NOT-DISCLOSE"
                    target = ("save_reviewed_selected_site_baseline"
                              if endpoint == "save_selected_site_baseline"
                              else "inspect_selected_site")
                    with patch.object(main, "_STATE_DIR", directory), \
                         patch.dict(sys.modules, {"flask": self.flask()}), \
                         patch.object(self.main, "_require_enabled"), \
                         patch.object(self.main, "_selected_native_website",
                                      return_value=(object(), self.site, lambda: self.site)), \
                         patch.object(source, target, side_effect=error_type(secret)):
                        result = getattr(self.main, endpoint)(self.args)
                    self.assertFalse(result["status"], result)
                    self.assertEqual(result["msg"],
                                     "Unexpected plugin error; inspect Activity using Operation ID")
                    self.assertNotIn(secret, str(result))
                    events = read_activity(directory)
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0]["error_class"], error_type.__name__)
                    self.assertEqual(events[0]["detail"], "")
                    self.assertNotIn(secret, str(events))
                    self.assertEqual(events[0]["operation_id"], result["operation_id"])



if __name__ == "__main__":
    unittest.main()
