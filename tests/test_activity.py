"""Plugin-owned, bounded, structured activity and native authorization."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parent.parent / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_activity as activity
import ach_customizer_main as main


class ActivityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-activity-")
        self.addCleanup(tmp.cleanup)
        self.directory = tmp.name
        env = patch.dict(os.environ, {"ACH_CUSTOMIZER_ACTIVITY_LEVEL": "DEBUG"})
        env.start()
        self.addCleanup(env.stop)

    def event(self, n=1, **overrides):
        values = dict(
            level="ERROR" if n % 2 else "INFO", module="php_fpm",
            action="fpm_apply", operation_id=f"{n:032x}",
            stage="reload", outcome="Failed" if n % 2 else "Applied",
            target="PHP85-shared", error_class="FpmApplyError" if n % 2 else "",
            detail="FPM reload failed" if n % 2 else "",
            recovery_id=f"{n:032x}" if not n % 2 else ""
        )
        values.update(overrides)
        return activity.record(**values)

    def test_initial_read_does_not_mutate_state(self):
        self.assertEqual(activity.read_activity(self.directory), [])
        self.assertEqual(list(Path(self.directory).iterdir()), [])

    def test_append_filter_schema_permissions_and_no_secrets(self):
        a, b = self.event(1), self.event(2, module="websites", action="inventory")
        self.assertTrue(activity.append_activity(self.directory, a))
        self.assertTrue(activity.append_activity(self.directory, b))
        path = Path(self.directory) / activity.LOG_NAME
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(activity.read_activity(self.directory), [b, a])
        self.assertEqual(activity.read_activity(self.directory, level="ERROR", module="php_fpm"), [a])
        self.assertEqual(activity.read_activity(self.directory, level="INFO", module="php_fpm"), [])
        self.assertTrue(a["time_utc"].endswith("+00:00"))
        self.assertEqual(len(json.loads(path.read_text().splitlines()[0])), 12)
        self.assertNotIn("password", path.read_text())

    def test_reject_invalid_records_and_control_chars(self):
        with self.assertRaises(activity.ActivityError):
            self.event(2, operation_id="bad")
        with self.assertRaises(activity.ActivityError):
            self.event(2, module="credentials")
        self.assertEqual(self.event(2, detail="a\n\tb")["detail"], "a  b")
        with self.assertRaises(activity.ActivityError):
            activity.append_activity(self.directory, {**self.event(), "secret": "never"})
        self.assertFalse((Path(self.directory) / activity.LOG_NAME).exists())

    def test_critical_manual_review_bypasses_verbosity_and_deduplicates_after_crash(self):
        candidate=self.event(16,level="WARNING",module="lifecycle",
            action="wp_terminal_manual_review",stage="native_terminal",
            outcome="Manual Review Required",target="failed.test",detail=
            "Exact native WP failed-install alias observed; Hosts unchanged; inspect Activity and remove manually",
            recovery_id="")
        with patch.dict(os.environ,{"ACH_CUSTOMIZER_ACTIVITY_LEVEL":"ERROR"}):
            self.assertTrue(activity.append_activity(self.directory,candidate,
                          mandatory_manual_review=True))
            self.assertTrue(activity.append_activity(self.directory,candidate,
                          mandatory_manual_review=True))
            self.assertEqual(len(activity.read_activity(self.directory)),1)
            with self.assertRaises(activity.ActivityError):
                activity.append_activity(
                    self.directory,{**candidate,"target":"different.test"},
                    mandatory_manual_review=True)
            with self.assertRaisesRegex(activity.ActivityError,"Only immutable"):
                activity.append_activity(self.directory,self.event(17),
                                         mandatory_manual_review=True)
        self.assertEqual(len(activity.read_activity(self.directory)),1)

    def test_rotation_is_bounded_and_recent_first(self):
        with patch.object(activity, "MAX_LOG_BYTES", 4096):
            for n in range(1, 37):
                activity.append_activity(self.directory, self.event(n, detail="e" * 120))
            recent = activity.read_activity(self.directory)
        self.assertGreater(len(recent), 2)
        self.assertLess(len(recent), 36)
        self.assertEqual(recent[0]["operation_id"], f"{36:032x}")
        for name in (activity.LOG_NAME, activity.LOG_NAME + ".1"):
            self.assertLessEqual((Path(self.directory) / name).stat().st_size, 4096)

    def test_intermediate_symlink_directory_is_rejected_on_read_and_write(self):
        real = Path(self.directory) / "real" / "activity"
        real.mkdir(parents=True)
        redirected = Path(self.directory) / "redirect"
        redirected.symlink_to(real.parent, target_is_directory=True)
        other = redirected / "activity"
        with self.assertRaises(activity.ActivityError):
            activity.append_activity(str(other), self.event())
        with self.assertRaises(activity.ActivityError):
            activity.read_activity(str(other))
        self.assertEqual(list(real.iterdir()), [])

    def test_symlink_and_corrupted_record_fail_closed(self):
        outside = Path(self.directory) / "outside"
        outside.write_text("unchanged")
        (Path(self.directory) / activity.LOG_NAME).symlink_to(outside)
        with self.assertRaises((OSError, activity.ActivityError)):
            activity.append_activity(self.directory, self.event())
        self.assertEqual(outside.read_text(), "unchanged")
        (Path(self.directory) / activity.LOG_NAME).unlink()
        (Path(self.directory) / activity.LOG_NAME).write_text("invalid json\n")
        (Path(self.directory) / activity.LOG_NAME).chmod(0o600)
        with self.assertRaises(activity.ActivityError):
            activity.read_activity(self.directory)

    def test_primary_admin_read_only_endpoint_and_denials(self):
        flask = types.ModuleType("flask")
        flask.has_request_context = lambda: True
        flask.request = types.SimpleNamespace(method="POST")
        flask.session = {"login": True, "uid": 1}
        entry = self.event()
        activity.append_activity(self.directory, entry)
        with patch.object(main, "_STATE_DIR", self.directory), patch.dict(sys.modules, {"flask": flask}):
            result = main.ach_customizer_main().get_activity({"level": "ERROR", "module": "php_fpm"})
            self.assertTrue(result["status"])
            self.assertEqual(result["entries"], [entry])
            for session, method in (
                ({"login": True, "uid": 2}, "POST"),
                ({"login": True, "uid": 1, "tmp_login_id": ""}, "POST"),
                ({"login": True, "uid": 1}, "GET"),
            ):
                flask.session, flask.request.method = session, method
                denied = main.ach_customizer_main().get_activity({})
                self.assertFalse(denied["status"])
                self.assertEqual(denied["stage"], "activity_authorization")
            self.assertEqual(len(activity.read_activity(self.directory, module="diagnostics")), 3)

    def test_logging_error_cannot_change_applied_outcome(self):
        applied = {"status": True, "request_id": "b" * 32, "operation_id": "a" * 32, "state": "Applied"}
        with patch.object(main, "append_activity", side_effect=activity.ActivityError("disk")):
            result = main.ach_customizer_main._activity_result(applied, "php_fpm", "fpm_apply")
        self.assertTrue(result["status"])
        self.assertEqual(result["operation_id"], "a" * 32)
        self.assertFalse(result["activity_logged"])
        self.assertIn("persistence", result["activity_warning"])

    def test_unexpected_fpm_exception_keeps_real_error_class_without_leaking_details(self):
        from unittest.mock import Mock
        fake_public = types.ModuleType("public")
        fake_public.WriteLog = Mock(return_value=1)
        with patch.object(main, "_STATE_DIR", self.directory), patch.dict(
                sys.modules, {"public": fake_public}), patch.object(
                main, "ManualFpmWorkflow") as factory:
            factory.return_value.rollback.side_effect = RuntimeError(
                "PRIVATE debug context should not reach browser or activity history")
            response = main.ach_customizer_main().fpm_rollback({})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "fpm_rollback")
        self.assertNotIn("PRIVATE", json.dumps(response))
        self.assertEqual(activity.read_activity(self.directory)[0]["error_class"],
                         "RuntimeError")
        self.assertNotIn("PRIVATE", json.dumps(activity.read_activity(self.directory)))

    def test_debug_success_is_silent_at_info_but_visible_with_debug(self):
        with patch.object(main, "_STATE_DIR", self.directory), patch.dict(
                os.environ, {"ACH_CUSTOMIZER_ACTIVITY_LEVEL": "INFO"}):
            info = main.ach_customizer_main().get_overview({})
            self.assertTrue(info["status"])
            self.assertEqual(activity.read_activity(self.directory), [])
        with patch.object(main, "_STATE_DIR", self.directory):
            debug = main.ach_customizer_main().get_overview({})
            self.assertTrue(debug["status"])
            entries = activity.read_activity(self.directory)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["level"], "DEBUG")
            self.assertEqual(entries[0]["action"], "get_overview")

    def test_degraded_php_mapping_is_a_warning_without_fabricating_failure(self):
        with patch.object(main, "_STATE_DIR", self.directory):
            response = {"status": True, "operation_id": "a" * 32,
                        "state": "File Drift",
                        "shared_impact": {"state": "Needs Review"}}
            logged = main.ach_customizer_main._activity_result(
                response, "php_fpm", "preview_php_fpm", target="85")
            self.assertTrue(logged["status"])
            result = activity.read_activity(self.directory)[0]
            self.assertEqual(result["level"], "WARNING")
            self.assertEqual(result["outcome"], "Needs Review")

    def test_unexpected_native_inventory_error_is_safe_for_browser_and_logged_by_class(self):
        fake_flask = types.ModuleType("flask")
        fake_flask.session = {"login": True, "uid": 1}
        fake_flask.request = types.SimpleNamespace(method="POST")
        fake_flask.has_request_context = lambda: True
        fake_public = types.ModuleType("public")
        with patch.object(main, "_STATE_DIR", self.directory), patch.dict(
                sys.modules, {"flask": fake_flask, "public": fake_public}), patch.object(
                main, "get_site_page",
                side_effect=RuntimeError("SECRET-DATABASE-CREDENTIAL")):
            response = main.ach_customizer_main().status_sites({"page": "1"})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "status_sites_read")
        self.assertNotIn("SECRET-DATABASE-CREDENTIAL", json.dumps(response))
        event = activity.read_activity(self.directory)[0]
        self.assertEqual(event["error_class"], "RuntimeError")
        self.assertEqual(event["detail"], "")
        self.assertNotIn("SECRET-DATABASE-CREDENTIAL", json.dumps(event))

    def test_absent_recovery_reference_is_not_rendered_as_none(self):
        with patch.object(main, "_STATE_DIR", self.directory):
            result = main.ach_customizer_main._activity_result(
                {"status": True, "request_id": "c" * 32,
                 "operation_id": None, "state": "No Recovery"},
                "php_fpm", "fpm_recovery")
            self.assertTrue(result["status"])
        entry = activity.read_activity(self.directory)[0]
        self.assertEqual(entry["recovery_id"], "")
        self.assertEqual(entry["outcome"], "No Recovery")

    def test_concurrent_appends_preserve_unique_operation_records(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert all(pool.map(lambda n: activity.append_activity(
                self.directory, self.event(n)), range(1, 61)))
        entries = activity.read_activity(self.directory, limit=100)
        self.assertEqual(len(entries), 60)
        self.assertEqual(len({entry["operation_id"] for entry in entries}), 60)

    def test_php_preview_site_mapping_exception_does_not_disclose_private_text(self):
        secret = "SYNTHETIC-PASSWORD-DO-NOT-EXPOSE"
        data = {"state": "File Drift", "source": "/www/server/php/85/etc/php-fpm.conf",
                "version": "85", "changes": []}
        from ach_customizer_fpm_policy import observe, get_policy
        with patch.object(main, "_STATE_DIR", self.directory), patch(
                "ach_customizer_fpm_policy.observe", return_value=(data, "a"*64)), patch(
                "ach_customizer_fpm_policy.get_policy",
                return_value={"saved": False, "policy_revision": 0}), patch.object(
                main, "inspect_php_fpm_site_impact",
                side_effect=RuntimeError(secret)), patch.dict(
                sys.modules, {"public": types.ModuleType("public")}):
            response = main.ach_customizer_main().preview_php_fpm(
                {"php_version": "85"})
        self.assertTrue(response["status"])
        self.assertEqual(response["shared_impact"]["state"], "Needs Review")
        self.assertNotIn(secret, json.dumps(response))
        self.assertEqual(response["shared_impact"]["matched_sites"], [])
        history = activity.read_activity(self.directory)
        self.assertEqual(history[0]["level"], "WARNING")
        self.assertEqual(history[0]["error_class"], "RuntimeError")
        self.assertEqual(history[0]["operation_id"], response["operation_id"])
        self.assertNotIn(secret, json.dumps(history))

    def test_unexpected_exceptions_do_not_persist_details(self):
        with patch.object(main, "_STATE_DIR", self.directory):
            main.ach_customizer_main._fail("monitor_state_read", RuntimeError("SECRET"), "a" * 32)
        item = activity.read_activity(self.directory)[0]
        self.assertEqual(item["error_class"], "RuntimeError")
        self.assertEqual(item["detail"], "")
        self.assertNotIn("SECRET", json.dumps(item))
