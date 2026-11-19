"""Native aaPanel authenticated route gate for opt-in WP terminal automation."""
import errno
import importlib.util
import json
import os
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
SPEC = importlib.util.spec_from_file_location("ach_customizer_main_wp_endpoint", PLUGIN / "ach_customizer_main.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WordPressTerminalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = MODULE.ach_customizer_main()
        directory = tempfile.TemporaryDirectory(prefix="ach-wp-endpoint-")
        self.addCleanup(directory.cleanup)
        p=patch.object(MODULE, "_STATE_DIR", directory.name)
        p.start(); self.addCleanup(p.stop)
        gate=patch.object(MODULE.ach_customizer_main,"_status_primary_admin_post",return_value=None)
        gate.start(); self.addCleanup(gate.stop)
        public=types.ModuleType("public")
        public.get_panel_version=lambda: "8.0.7"
        public.get_webserver=lambda: "nginx"
        pub=patch.dict(sys.modules, {"public":public})
        pub.start();self.addCleanup(pub.stop)

    def test_defaults_are_disabled_and_inspect_has_no_mutation(self):
        result=self.plugin.wp_terminal_manage({"terminal_action":"inspect"})
        self.assertTrue(result["status"],result)
        self.assertFalse(result["enabled"])
        self.assertIs(result["auto_hosts"],False)
        self.assertEqual(result["scope"],"failed_native_single_site_wp_toolkit")
        self.assertEqual(result["last_recovery"],None)

    def test_enable_requires_native_version_and_explicit_review(self):
        with patch("ach_customizer_wp_watcher.enable") as enable:
            refused=self.plugin.wp_terminal_manage({"terminal_action":"enable"})
            self.assertFalse(refused["status"])
            enable.assert_not_called()
            with patch.object(sys.modules["public"],"get_panel_version",return_value="8.0.8"):
                refused=self.plugin.wp_terminal_manage({"terminal_action":"enable","reviewed":"true"})
                self.assertFalse(refused["status"])
                enable.assert_not_called()
            enable.return_value={"enabled":True,"revision":1}
            accepted=self.plugin.wp_terminal_manage({"terminal_action":"enable","reviewed":"true"})
            self.assertTrue(accepted["status"],accepted)
            self.assertEqual(accepted["enabled"],True)
            enable.assert_called_once()

    def test_disable_is_available_without_review_and_restore_has_its_own_approval(self):
        with patch("ach_customizer_wp_watcher.disable",return_value={"enabled":False}) as disable, \
                patch("ach_customizer_wp_terminal.restore",return_value={"state":"Restored","recovery_id":"b"*32}) as restore:
            response=self.plugin.wp_terminal_manage({"terminal_action":"disable"})
            self.assertTrue(response["status"])
            disable.assert_called_once()
            refused=self.plugin.wp_terminal_manage({"terminal_action":"restore","recovery_id":"b"*32})
            self.assertFalse(refused["status"])
            restore.assert_not_called()
            accepted=self.plugin.wp_terminal_manage({"terminal_action":"restore","recovery_id":"b"*32,"reviewed":"true"})
            self.assertTrue(accepted["status"])
            restore.assert_called_once_with("b"*32,data_dir=MODULE._STATE_DIR)

    def test_abandon_requires_distinct_review_and_recheck_never_edits(self):
        with patch("ach_customizer_wp_terminal.abandon_witness",return_value={"state":"Witness Abandoned"}) as abandon, \
                patch("ach_customizer_wp_terminal.recheck_recovery",return_value={"state":"No Recovery"}) as recheck:
            denied=self.plugin.wp_terminal_manage({"terminal_action":"abandon"})
            self.assertFalse(denied["status"])
            abandon.assert_not_called()
            checked=self.plugin.wp_terminal_manage({"terminal_action":"recheck"})
            self.assertTrue(checked["status"],checked)
            recheck.assert_called_once()
            response=self.plugin.wp_terminal_manage({"terminal_action":"abandon","reviewed":"true"})
            self.assertTrue(response["status"],response)
            abandon.assert_called_once()

    def test_wp_terminal_error_activity_uses_lifecycle_not_monitor(self):
        import json
        from ach_customizer_activity import LOG_NAME
        response=self.plugin.wp_terminal_manage({"terminal_action":"enable"})
        self.assertFalse(response["status"])
        events=[json.loads(x) for x in (Path(MODULE._STATE_DIR)/LOG_NAME).read_text().splitlines()]
        event=events[-1]
        self.assertEqual(event["module"],"lifecycle")
        self.assertEqual(event["action"],"wp_terminal_management")
        self.assertEqual(event["stage"],"wp_terminal_management")
        self.assertNotIn("password",json.dumps(event))

    def test_activity_read_projects_manual_identity_only_to_primary_admin(self):
        import ach_customizer_wp_terminal as worker
        with worker._locked_state(MODULE._STATE_DIR) as fd:
            worker._prepare_manual_review(fd,"c"*32,"manual-review.example")
        response=self.plugin.get_activity({"module":"lifecycle","limit":50})
        self.assertTrue(response["status"],response)
        manual=[e for e in response["entries"]
                if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(manual),1)
        self.assertEqual(manual[0]["target"],"manual-review.example")
        self.assertEqual(manual[0]["operation_id"],"c"*32)
        # A denied request must never disclose private journal contents.
        with patch.object(MODULE.ach_customizer_main,"_status_primary_admin_post",
                          side_effect=PermissionError("not primary")):
            denied=self.plugin.get_activity({"module":"lifecycle"})
        self.assertFalse(denied["status"])
        self.assertNotIn("entries",denied)
        self.assertNotIn("manual-review.example",str(denied))

    def test_raw_general_log_failures_preserve_authorized_durable_evidence(self):
        import ach_customizer_activity as activity
        import ach_customizer_wp_terminal as terminal
        operation = "e" * 32
        domain = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 61))
        self.assertEqual(len(domain), 253)
        with terminal._locked_state(MODULE._STATE_DIR) as fd:
            terminal._prepare_manual_review(fd, operation, domain)
        general = activity.record(
            level="INFO", module="lifecycle", action="native_test",
            operation_id="f" * 32, stage="fixture", outcome="Observed")
        activity.append_activity(MODULE._STATE_DIR, general)
        log_stat = (Path(MODULE._STATE_DIR) / activity.LOG_NAME).stat()
        original_open, original_read = os.open, os.read

        for code, at in ((errno.EIO, "read"), (errno.EACCES, "open"), (errno.ELOOP, "open")):
            with self.subTest(errno=code, at=at):
                def failing_open(path, flags, *args, **kwargs):
                    if at == "open" and path == activity.LOG_NAME:
                        raise (PermissionError if code == errno.EACCES else OSError)(
                            code, "synthetic-private-file-detail")
                    return original_open(path, flags, *args, **kwargs)
                def failing_read(fd, length):
                    current = os.fstat(fd)
                    if (at == "read" and
                            (current.st_dev, current.st_ino) ==
                            (log_stat.st_dev, log_stat.st_ino)):
                        raise OSError(code, "synthetic-private-file-detail")
                    return original_read(fd, length)
                with patch.object(activity.os, "open", side_effect=failing_open), patch.object(
                        activity.os, "read", side_effect=failing_read):
                    response = self.plugin.get_activity({"module": "lifecycle"})
                self.assertTrue(response["status"], response)
                self.assertIn("General Activity log unavailable", response["activity_warning"])
                self.assertEqual(
                    [(row["operation_id"], row["target"]) for row in response["entries"]
                     if row["action"] == "wp_terminal_manual_review"],
                    [(operation, domain)])
                self.assertNotIn("synthetic-private-file-detail", json.dumps(response))

        with patch.object(MODULE.ach_customizer_main, "_status_primary_admin_post",
                          side_effect=PermissionError("primary admin required")), patch.object(
                terminal, "manual_review_activity", side_effect=AssertionError(
                    "authorization must precede evidence access")):
            denied = self.plugin.get_activity({"module": "lifecycle"})
        self.assertFalse(denied["status"])
        self.assertEqual(denied["stage"], "activity_authorization")
        self.assertNotIn(domain, json.dumps(denied))
        self.assertNotIn("entries", denied)

    def test_general_log_error_without_durable_evidence_does_not_fabricate_success(self):
        import ach_customizer_activity as activity
        general = activity.record(
            level="INFO", module="lifecycle", action="native_test",
            operation_id="f" * 32, stage="fixture", outcome="Observed")
        activity.append_activity(MODULE._STATE_DIR, general)
        original_open = os.open
        def failing_open(path, flags, *args, **kwargs):
            if path == activity.LOG_NAME:
                raise PermissionError(errno.EACCES, "synthetic-private-file-detail")
            return original_open(path, flags, *args, **kwargs)
        with patch.object(activity.os, "open", side_effect=failing_open):
            response = self.plugin.get_activity({"module": "lifecycle"})
        self.assertFalse(response["status"], response)
        self.assertEqual(response["stage"], "activity_read",
            "File read availability is not a primary-admin authorization failure")
        self.assertNotIn("entries", response)
        self.assertNotIn("synthetic-private-file-detail", json.dumps(response))

    def test_resident_old_helper_blocks_enable_but_preserves_emergency_disable(self):
        import ach_customizer_wp_terminal as terminal
        with patch.object(terminal,"MANUAL_REVIEW_CONTRACT","durable-manual-review-v2"):
            with patch("ach_customizer_wp_watcher.enable") as enable, patch(
                    "ach_customizer_wp_watcher.disable",return_value={"enabled":False}) as disable:
                for action in ("inspect","enable","recheck","abandon","restore"):
                    outcome=self.plugin.wp_terminal_manage(
                        {"terminal_action":action,"reviewed":"true","recovery_id":"a"*32})
                    self.assertFalse(outcome["status"],outcome)
                    self.assertEqual(outcome["reason_code"],"resident_wp_helper_stale")
                enable.assert_not_called()
                safe=self.plugin.wp_terminal_manage({"terminal_action":"disable"})
                self.assertTrue(safe["status"],safe)
                disable.assert_called_once()
            read=self.plugin.get_activity({})
            self.assertTrue(read["status"],read)
            self.assertIn("Resident WP helper stale",read["activity_warning"])

    def test_authorization_failure_precedes_policy_access(self):
        with patch.object(MODULE.ach_customizer_main,"_status_primary_admin_post",side_effect=PermissionError("admin")), \
                patch("ach_customizer_wp_watcher.enable") as enable:
            result=self.plugin.wp_terminal_manage({"terminal_action":"enable","reviewed":"true"})
            self.assertFalse(result["status"])
            enable.assert_not_called()


if __name__=='__main__':
    unittest.main()
