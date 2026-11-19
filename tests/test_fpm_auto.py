"""Isolated auto PHP-FPM repeat-repair tests; never operate native services."""
import hashlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin/ach_customizer"))
import ach_customizer_fpm_apply as recovery
import ach_customizer_fpm_auto as worker
import ach_customizer_fpm_policy as desired_policy
import ach_customizer_fpm_workflow as workflow

BASELINE = (b"[global]\npid=/tmp/php-auto-test.pid\n[www]\npm=dynamic\n"
            b"listen=/tmp/php-cgi-85.sock\npm.max_children=50\n"
            b"pm.start_servers=5\npm.min_spare_servers=5\n"
            b"pm.max_spare_servers=20\n")
DESIRED = {"pm.max_children": 20, "pm.start_servers": 5,
           "pm.min_spare_servers": 5, "pm.max_spare_servers": 10,
           "pm.max_requests": 300}
VENDOR_BYTES = BASELINE.replace(b"pm.max_children=50", b"pm.max_children=80")


class AutoNativeFpmTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-auto-fpm-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.php_root = self.base / "php"
        self.config = self.php_root / "85" / "etc" / "php-fpm.conf"
        self.config.parent.mkdir(parents=True)
        self.config.write_bytes(BASELINE)
        self.config.chmod(0o644)
        self.marker = self.config.parent / "php-fpm.conf_record"
        self.state = self.base / "state"
        self.state.mkdir(mode=0o700)
        self.settings = {"schema": 1, "revision": 1, "profiles": {"85": DESIRED}}
        self._policy()
        self.calls = []
        self.impact = {"schema":1, "state":"File Mapping", "scope":"shared_service",
                       "version":"85", "matched_sites":[{"id":3,"site_key":"native.example"}],
                       "unresolved_sites":[], "site_count":1,"other_php_sites_count":0,
                       "dependency_sha256":"a"*64,"manual_apply_eligible":True,
                       "reason":"","note":"isolated site fixture"}
        self.panel = types.SimpleNamespace(get_panel_version=lambda:"8.0.7",
                                            get_webserver=lambda:"nginx")
        self.token = 0
        self.event = None
        self.factory = self._controller
        self.lock_path = self.base / "native-wp.lock"
        self.batch_path = self.base / "native-batch.lock"
        locks = (patch.object(worker.native, "LOCK", str(self.lock_path)),
                 patch.object(worker.native, "BATCH_LOCK", str(self.batch_path)))
        for mock in locks:
            mock.start()
            self.addCleanup(mock.stop)

    def _policy(self):
        path = self.state / desired_policy.POLICY_FILE
        path.write_text(json.dumps(self.settings, sort_keys=True) + "\n")
        path.chmod(0o600)

    def _controller(self):
        def hooks(_version, desired):
            def validate():
                self.calls.append("validate")
            def activate():
                self.calls.append("reload")
            def verify():
                self.calls.append("verify")
                from ach_customizer_monitor import preview_php_fpm
                result = preview_php_fpm(self.php_root, "85", desired)
                if result["state"] != "File Match":
                    raise AssertionError("Expected exact runtime target after reload")
            return validate, activate, verify
        return workflow.ManualFpmWorkflow(
            public=self.panel, config_root=self.php_root, data_dir=self.state,
            impact_lookup=lambda _panel, _version, _source:self.impact,
            hooks_factory=hooks)

    def _enable(self):
        return worker.set_enabled("85", True, data_dir=str(self.state),
            expected_auto_revision=worker.inspect("85",data_dir=str(self.state))["state_revision"],
            expected_policy_revision=self.settings["revision"],reviewed=True,
            controller_factory=self.factory)

    def _start(self):
        self.token += 1
        self.lock_path.write_text("native in progress")
        self.event = {"status": 0, "steps": [1, 1, 1, 0],
                      "dev": 2, "ino": self.token + 100, "domain": "native.example",
                      "mtime_ns": time.time_ns(),
                      "token": hashlib.sha256(("start-"+str(self.token)).encode()).hexdigest()}
        return self.event

    def _terminal(self):
        self.lock_path.unlink()
        self.event = {**self.event, "status": 1, "steps": [1, 1, 1, -1],
                      "mtime_ns": time.time_ns(),
                      "token": hashlib.sha256(("terminal-"+str(self.token)).encode()).hexdigest()}
        return self.event

    def _mark_optimized(self):
        self.marker.write_bytes(b" ")
        self.marker.chmod(0o644)

    def _vendor_reset(self):
        self.config.write_bytes(VENDOR_BYTES)
        self._mark_optimized()

    def _run(self):
        return worker.run(data_dir=str(self.state), controller_factory=self.factory,
                          terminal_reader=lambda:self.event)

    def test_default_disabled_and_opt_in_has_no_host_write(self):
        self.assertFalse(worker.inspect("85",data_dir=str(self.state))["enabled"])
        self.assertEqual(self._run()["state"], "Disabled")
        with self.assertRaisesRegex(worker.FpmAutoError, "Explicit approval"):
            worker.set_enabled("85",True,data_dir=str(self.state),
                               expected_auto_revision=0,expected_policy_revision=1,
                               reviewed=False,controller_factory=self.factory)
        self._enable()
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertTrue(worker.inspect("85",data_dir=str(self.state))["enabled"])
        self.assertEqual(self._run()["changed"],False)

    def test_two_distinct_vendor_resets_auto_repair_and_archive_prior_recovery(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        one=self._run()
        self.assertEqual(one["services"][0]["state"],"Applied")
        first=one["services"][0]["operation_id"]
        self.assertEqual(worker.inspect("85",data_dir=str(self.state))["last_operation"],first)
        self.assertEqual(self._run()["changed"],False)
        self.assertEqual(self.calls.count("reload"),1)
        self.assertEqual(recovery.recovery_status(self.php_root,self.state,"85")["state"],"Applied")

        # Vendor v2 only optimizes when its per-PHP sidecar is absent.
        # Re-install/re-optimization is modeled by removing this marker
        # before starting a distinct native task in isolated fixtures.
        self.marker.unlink()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        second=self._run()
        self.assertEqual(second["services"][0]["state"],"Applied")
        latest=second["services"][0]["operation_id"]
        self.assertNotEqual(latest,first)
        self.assertEqual(self.calls.count("reload"),2)
        archived="ach_customizer.fpm85.auto."+first
        self.assertEqual((self.state/(archived+".before")).read_bytes(),VENDOR_BYTES)
        prior=json.loads((self.state/(archived+".journal")).read_text())
        self.assertEqual(prior["operation_id"],first)
        self.assertEqual(prior["schema"],2)
        self.assertEqual(recovery.recovery_status(self.php_root,self.state,"85")["operation_id"],latest)

        self.marker.unlink()
        self._start()
        self._run()
        self._mark_optimized()
        self._terminal()
        noop=self._run()
        self.assertEqual(noop["services"][0]["state"],"No Vendor FPM Change")
        self.assertEqual(self.calls.count("reload"),2)
        self.assertEqual(self._run()["changed"],False)
        result=worker.set_enabled("85",False,data_dir=str(self.state),
                    expected_auto_revision=worker.inspect("85",data_dir=str(self.state))["state_revision"])
        self.assertFalse(result["enabled"])
        self.config.write_bytes(BASELINE)
        self._start()
        self._run()
        self._terminal()
        self.assertFalse(self._run()["changed"])
        self.assertEqual(self.config.read_bytes(),BASELINE)

    def test_manual_php_tuning_before_wp_is_not_overwritten_without_vendor_change(self):
        self._enable()
        intentionally_changed = BASELINE.replace(b"pm.max_children=50",
                                                  b"pm.max_children=70")
        self.config.write_bytes(intentionally_changed)
        self._start()
        observed = self._run()
        self.assertEqual(observed["services"][0]["state"], "Witness Armed")
        self._mark_optimized()
        self._terminal()
        result = self._run()
        self.assertEqual(result["services"][0]["state"],"No Vendor FPM Change")
        self.assertEqual(self.config.read_bytes(),intentionally_changed)
        self.assertEqual(self.calls.count("reload"),0)
        self.assertFalse((self.state / recovery.JOURNAL).exists())

    def test_final_event_without_preterminal_witness_never_writes(self):
        self._enable()
        self._start()
        self._vendor_reset()
        self._terminal()
        value=self._run()
        self.assertFalse(value["changed"])
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"),0)

    def test_native_site_in_other_php_pool_never_restores_unrelated_service(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        self.impact["matched_sites"][0]["site_key"] = "other-php85.example"
        result = self._run()
        self.assertFalse(result["changed"], result)
        self.assertEqual(result["services"], [])
        self.assertEqual(self.config.read_bytes(), VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"), 0)
        self.assertFalse((self.state / recovery.JOURNAL).exists())
        self.impact["matched_sites"][0]["site_key"] = "native.example"
        # Retry of the same terminal after the attribution adapter becomes
        # verified is safe and repairs the correctly owned shared service.
        result = self._run()
        self.assertTrue(result["changed"], result)
        self.assertEqual(result["services"][0]["state"], "Applied")

    def test_vendor_marker_preexisting_at_start_prevents_auto_overwrite(self):
        self._enable()
        self._mark_optimized()
        self._start()
        result = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(result["services"], [])
        self.config.write_bytes(VENDOR_BYTES)
        self._terminal()
        result = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(self.config.read_bytes(), VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"), 0)

    def test_vendor_failure_before_optimizer_finishes_retires_witness_without_write(self):
        self._enable()
        self._start()
        self._run()
        self._terminal()
        result = self._run()
        self.assertEqual(result["services"][0]["state"],"No Native FPM Optimization")
        self.assertFalse(result["changed"])
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertEqual(self.calls.count("reload"), 0)
        self.assertEqual(self._run()["changed"], False)

    def test_native_optimizer_crash_after_config_change_without_marker_refuses(self):
        self._enable()
        self._start()
        self._run()
        # The verified writer normally creates a marker only *after* the
        # FPM config write succeeds. Simulate an interruption in between.
        self.config.write_bytes(VENDOR_BYTES)
        self._terminal()
        with self.assertRaisesRegex(
                worker.FpmAutoError, "without an optimization completion marker"):
            self._run()
        self.assertEqual(self.config.read_bytes(), VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"), 0)
        self.assertEqual(worker.inspect("85", data_dir=str(self.state))["last_state"],
                         "Repair refused at FpmAutoError")

    def test_foreign_vendor_marker_never_authorizes_fpm_change(self):
        self._enable()
        self._start()
        self._run()
        self.config.write_bytes(VENDOR_BYTES)
        self.marker.write_text("foreign marker")
        self.marker.chmod(0o644)
        self._terminal()
        with self.assertRaises(worker.FpmAutoError):
            self._run()
        self.assertEqual(self.config.read_bytes(), VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"), 0)

    def test_invalid_or_corrupt_auto_state_rejected_without_repair(self):
        self._enable()
        path = self.state / worker.AUTO_FILE
        baseline = path.read_bytes()
        path.chmod(0o666)
        from ach_customizer_state import StateError
        with self.assertRaises(StateError):
            worker.inspect("85",data_dir=str(self.state))
        path.chmod(0o600)
        path.write_text("{}")
        with self.assertRaises(worker.FpmAutoError):
            self._run()
        path.write_bytes(baseline)
        path.chmod(0o600)

    def test_preterminal_progress_change_or_task_lock_blocks_unsafe_delivery(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        self.lock_path.write_text("still running")
        blocked=self._run()
        self.assertFalse(blocked["changed"])
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        self.lock_path.unlink()
        self.event={**self.event,"ino":self.event["ino"]+1}
        ignored=self._run()
        self.assertFalse(ignored["changed"])
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)

    def test_saved_policy_change_or_disabled_monitor_blocks_repair(self):
        self._enable()
        self.settings["profiles"]["85"] = {**DESIRED,"pm.max_children":30}
        self.settings["revision"] = 2
        self._policy()
        self._start()
        with self.assertRaisesRegex(worker.FpmAutoError,"changed"):
            self._run()
        self.assertEqual(self.config.read_bytes(),BASELINE)
        self.settings["profiles"]["85"] = dict(DESIRED)
        self.settings["revision"] = 3
        self._policy()
        from ach_customizer_state import set_enabled
        set_enabled("php_fpm_file_preview",False,directory=str(self.state),expected_revision=0)
        # A new start is blocked because the Monitor gate is checked on
        # prepare(), before any trusted host mutation.
        with self.assertRaises((worker.FpmAutoError, recovery.FpmApplyError)):
            self._run()
        self.assertEqual(self.config.read_bytes(),BASELINE)

    def test_unverified_impact_and_manual_recovery_cannot_be_overwritten(self):
        self._enable()
        self.impact["unresolved_sites"] = [{"id":7,"site_key":"ambiguous.example","reason":"socket unknown"}]
        self._start()
        # Native site creation can be incomplete at start; witness is only
        # read-only, so the snapshot must still arm.
        self.assertEqual(self._run()["services"][0]["state"],"Witness Armed")
        self._vendor_reset()
        self._terminal()
        with self.assertRaises(recovery.FpmApplyError):
            self._run()
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        # The same terminal is retryable when source/site mapping becomes
        # trustworthy; it must not require another click or vendor event.
        self.impact["unresolved_sites"] = []
        controller=self._controller()
        # A previous approved manual Apply remains a separate recovery owner.
        prepared=controller._prepare({"php_version":"85",**{
            k.removeprefix("pm."):v for k,v in DESIRED.items()}})
        plan=prepared["plan"]
        self.assertEqual(recovery.apply(self.php_root,self.state,"85",DESIRED,
            expected_before=plan["before_sha256"],expected_after=plan["after_sha256"],
            validate=lambda:None,activate=lambda:None,verify=lambda:None,
            verify_restored=lambda:None)["state"],"Applied")
        self.config.write_bytes(VENDOR_BYTES)
        with self.assertRaisesRegex(recovery.FpmApplyError,"previous PHP-FPM operation"):
            self._run()
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)

    def test_failed_reload_restores_original_and_keeps_token_retryable(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        def failing_factory():
            controller=self._controller()
            normal=controller.hooks_factory
            def hooks(version,desired):
                validate,activate,verify=normal(version,desired)
                if desired["pm.max_children"]==20:
                    def failed():
                        raise OSError("synthetic active service failure")
                    return validate,failed,verify
                return validate,activate,verify
            controller.hooks_factory=hooks
            return controller
        self.factory=failing_factory
        with self.assertRaises(recovery.FpmApplyError):
            self._run()
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        self.assertIsNone(worker.inspect("85",data_dir=str(self.state))["last_operation"])
        self.factory=self._controller
        # Failed runtime verification leaves a durable uncertain journal,
        # which must not be silently retired by automation.
        with self.assertRaises(recovery.FpmApplyError) as blocked:
            self._run()
        self.assertEqual(blocked.exception.stage,"recovery")
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)

    def test_stale_replay_and_failed_owner_archive_refuse(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        event=self._terminal()
        done=self._run()
        op=done["services"][0]["operation_id"]
        self.config.write_bytes(BASELINE)
        self.assertFalse(self._run()["changed"],"Replayed terminal must not fight later admin edits")
        assert worker.inspect("85",data_dir=str(self.state))["last_operation"] == op
        self.marker.unlink()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        path=self.state / ("ach_customizer.fpm85.auto."+op+".before")
        path.write_text("foreign");path.chmod(0o600)
        with self.assertRaises(recovery.FpmApplyError):
            self._run()
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)


if __name__=="__main__":
    unittest.main()
