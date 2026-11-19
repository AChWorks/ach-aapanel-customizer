"""aaPanel native primary-admin API boundaries for FPM automatic repair."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0,str(PLUGIN))
import ach_customizer_main as main
import ach_customizer_fpm_watcher as watcher
import ach_customizer_fpm_auto as auto


class FpmAutoApiTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="ach-fpm-auto-api-")
        self.addCleanup(tmp.cleanup)
        state=patch.object(main,"_STATE_DIR",tmp.name)
        state.start();self.addCleanup(state.stop)
        self.plugin=main.ach_customizer_main()
        self.flask=types.ModuleType("flask")
        self.flask.request=types.SimpleNamespace(method="POST")
        self.flask.session={"login":True,"uid":1}
        self.flask.has_request_context=lambda:True
        active=patch.dict(sys.modules,{"flask":self.flask})
        active.start();self.addCleanup(active.stop)

    def test_inspect_without_saved_policy_does_not_touch_host(self):
        with patch.object(watcher,"health",return_value={
                "watcher_ready":False,"watcher_status":"absent"}):
            observed=self.plugin.fpm_auto_manage({
                "auto_action":"inspect","php_version":"85"})
        self.assertTrue(observed["status"],observed)
        self.assertFalse(observed["enabled"])
        self.assertEqual(observed["scope"],"shared_service")
        self.assertEqual(observed["state_revision"],0)

    def test_enable_requires_real_admin_and_gives_explicit_expected_state(self):
        result={"version":"85","enabled":True,"state_revision":1,
                "last_state":"Armed","watch_scope":"verified_native_wp_terminal"}
        with patch.object(watcher,"enable",return_value=result) as on,patch.object(
                watcher,"health",return_value={"watcher_ready":True}):
            reply=self.plugin.fpm_auto_manage({
                "auto_action":"enable","php_version":"85",
                "expected_auto_revision":"0","expected_policy_revision":"1",
                "expected_monitor_revision":"0","expected_impact":"d"*64,
                "reviewed":"true"})
            self.assertTrue(reply["status"],reply)
            self.assertTrue(reply["enabled"])
            self.assertTrue(reply["watcher_ready"])
            on.assert_called_once_with("85",data_dir=main._STATE_DIR,
                                       expected_auto_revision="0",
                                       expected_policy_revision="1",
                                       expected_monitor_revision="0",
                                       expected_impact="d"*64,reviewed=True)

        self.flask.session={"login":True,"uid":2}
        with patch.object(watcher,"enable") as on:
            denied=self.plugin.fpm_auto_manage({
                "auto_action":"enable","php_version":"85",
                "reviewed":"true"})
        self.assertFalse(denied["status"])
        self.assertEqual(denied["stage"],"fpm_auto_authorization")
        on.assert_not_called()

    def test_disable_still_available_with_monitor_disabled(self):
        with patch.object(main.ach_customizer_main,"_require_enabled",
                          side_effect=RuntimeError("Monitor disabled")) as monitor,patch.object(
                watcher,"disable",return_value={"version":"85","enabled":False,
                "state_revision":2,"last_state":"Disabled"}) as stop,patch.object(
                watcher,"health",return_value={"watcher_ready":False}):
            response=self.plugin.fpm_auto_manage({
                "auto_action":"disable","php_version":"85",
                "expected_auto_revision":"1"})
        self.assertTrue(response["status"],response)
        self.assertFalse(response["enabled"])
        stop.assert_called_once()
        monitor.assert_not_called()

    def test_disable_can_ack_durable_pending_while_php_monitor_is_off(self):
        with patch.object(main.ach_customizer_main,"_require_enabled",
                          side_effect=RuntimeError("Monitor off")) as guard, patch.object(
                watcher,"disable",return_value={"version":"85","enabled":True,
                    "pending_disable":True,"state_revision":4,
                    "last_state":"Pending Disable"}) as stop, patch.object(
                watcher,"health",return_value={"watcher_ready":True}):
            result=self.plugin.fpm_auto_manage({
                "auto_action":"disable","php_version":"85","expected_auto_revision":"2"})
        self.assertTrue(result["status"],result)
        self.assertTrue(result["enabled"])
        self.assertTrue(result["pending_disable"])
        self.assertEqual(result["last_state"],"Pending Disable")
        guard.assert_not_called()
        stop.assert_called_once()

    def test_unapproved_or_unknown_action_does_not_toggle_watcher(self):
        for action in ("ignore","", "enable_no_review"):
            with patch.object(watcher,"enable") as on,patch.object(watcher,"disable") as off:
                res=self.plugin.fpm_auto_manage({"auto_action":action,"php_version":"85"})
            self.assertFalse(res["status"])
            on.assert_not_called()
            off.assert_not_called()
        with patch.object(watcher,"enable",side_effect=auto.FpmAutoError(
                "Explicit approval of shared PHP policy required")) as on:
            res=self.plugin.fpm_auto_manage({
                "auto_action":"enable","php_version":"85","reviewed":"false"})
        self.assertFalse(res["status"])
        self.assertEqual(res["stage"],"fpm_auto_management")
        on.assert_called_once()
