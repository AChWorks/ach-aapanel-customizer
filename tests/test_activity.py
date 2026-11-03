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

    def test_unexpected_exceptions_do_not_persist_details(self):
        with patch.object(main, "_STATE_DIR", self.directory):
            main.ach_customizer_main._fail("monitor_state_read", RuntimeError("SECRET"), "a" * 32)
        item = activity.read_activity(self.directory)[0]
        self.assertEqual(item["error_class"], "RuntimeError")
        self.assertEqual(item["detail"], "")
        self.assertNotIn("SECRET", json.dumps(item))
