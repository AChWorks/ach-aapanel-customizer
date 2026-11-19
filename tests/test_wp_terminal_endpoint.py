"""Native aaPanel authenticated route gate for opt-in WP terminal automation."""
import importlib.util
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

    def test_authorization_failure_precedes_policy_access(self):
        with patch.object(MODULE.ach_customizer_main,"_status_primary_admin_post",side_effect=PermissionError("admin")), \
                patch("ach_customizer_wp_watcher.enable") as enable:
            result=self.plugin.wp_terminal_manage({"terminal_action":"enable","reviewed":"true"})
            self.assertFalse(result["status"])
            enable.assert_not_called()


if __name__=='__main__':
    unittest.main()
