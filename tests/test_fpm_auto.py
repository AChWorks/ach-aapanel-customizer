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
VENDOR_BYTES = (BASELINE
    .replace(b"pm.max_children=50", b"pm.max_children=80")
    .replace(b"pm.start_servers=5", b"pm.start_servers=10")
    .replace(b"pm.min_spare_servers=5", b"pm.min_spare_servers=10")
    .replace(b"pm.max_spare_servers=20", b"pm.max_spare_servers=30"))


class NativeEventWindowTests(unittest.TestCase):
    def test_early_native_progress_is_retried_until_terminal(self):
        start = {"status":0}
        completed = {"status":1}
        calls = [
            {"state":"No new owned event","changed":False},
            {"state":"Processed","changed":False,"services":[{"state":"Witness Armed"}]},
            {"state":"No new owned event","changed":False},
            {"state":"Processed","changed":True,"services":[{"state":"Applied"}]},
        ]
        events = [start,start,start,completed]
        with (patch.object(worker,"run",side_effect=calls) as run,
              patch.object(worker,"_native_progress",side_effect=events) as progress,
              patch.object(worker.os.path,"lexists",return_value=False),
              patch.object(worker.time,"sleep") as sleep,
              patch.object(worker.time,"monotonic",side_effect=range(12))):
            outcome=worker._run_event_window(budget_seconds=20,interval_seconds=.2)
        self.assertTrue(outcome["changed"])
        self.assertEqual(run.call_count,4)
        self.assertEqual(progress.call_count,4)
        self.assertEqual(sleep.call_count,3)

    def test_terminal_or_unavailable_progress_exits_without_polling(self):
        for progress in (None,{"status":1}):
            with self.subTest(progress=progress):
                with (patch.object(worker,"run",return_value={"state":"No new owned event"}) as run,
                      patch.object(worker,"_native_progress",return_value=progress),
                      patch.object(worker.time,"sleep") as sleep):
                    outcome=worker._run_event_window()
                self.assertEqual(outcome["state"],"No new owned event")
                run.assert_called_once_with()
                sleep.assert_not_called()

    def test_active_window_is_strictly_bounded(self):
        with (patch.object(worker,"run",return_value={"state":"No new owned event"}) as run,
              patch.object(worker,"_native_progress",return_value={"status":0}),
              patch.object(worker.time,"sleep") as sleep,
              patch.object(worker.time,"monotonic",side_effect=[0,1,3,4,8])):
            worker._run_event_window(budget_seconds=3,interval_seconds=.2)
        self.assertEqual(run.call_count,2)
        self.assertEqual(sleep.call_count,1)

    def test_terminal_reader_failure_does_not_forge_completion(self):
        with (patch.object(worker,"run",return_value={"state":"No new owned event"}) as run,
              patch.object(worker,"_native_progress",side_effect=[{"status":0},worker.native.TerminalError("bad source")]),
              patch.object(worker.time,"sleep"),
              patch.object(worker.time,"monotonic",side_effect=[0,1])):
            with self.assertRaises(worker.native.TerminalError):
                worker._run_event_window()
        self.assertEqual(run.call_count,2)

    def test_missing_native_progress_is_an_expected_absent_event(self):
        with (patch.object(worker.native,"_native_supported"),
              patch.object(worker.native,"_progress",side_effect=FileNotFoundError(2,"transient"))):
            self.assertIsNone(worker._native_progress())


class StandaloneNativeImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-fpm-native-bootstrap-")
        self.addCleanup(temp.cleanup)
        self.panel = Path(temp.name) / "panel"
        (self.panel / "class").mkdir(parents=True)
        (self.panel / "class_v2").mkdir()
        (self.panel / "class" / "public.py").write_text("SENTINEL = 'aaPanel'\n")

    def test_native_import_roots_are_canonical_and_repeatable(self):
        import importlib.machinery
        with patch.object(worker.sys, "path", list(sys.path)):
            worker._configure_native_python_paths(self.panel)
            expected = [str(self.panel), str(self.panel / "class"),
                        str(self.panel / "class_v2")]
            self.assertEqual(worker.sys.path[:3], expected)
            source = importlib.machinery.PathFinder.find_spec(
                "public", worker.sys.path)
            self.assertIsNotNone(source)
            self.assertEqual(Path(source.origin), self.panel / "class/public.py")
            worker._configure_native_python_paths(self.panel)
            self.assertEqual(worker.sys.path[:3], expected)

    def test_unsafe_or_missing_native_source_never_enters_sys_path(self):
        for broken in ("symlink", "group_writable", "missing"):
            with self.subTest(broken=broken):
                source = self.panel / "class_v2"
                if broken == "symlink":
                    source.rmdir()
                    source.symlink_to(self.panel / "class")
                elif broken == "group_writable":
                    source.chmod(0o770)
                else:
                    source.rmdir()
                before = list(sys.path)
                with patch.object(worker.sys, "path", list(before)):
                    with self.assertRaises(worker.FpmAutoError):
                        worker._configure_native_python_paths(self.panel)
                    self.assertEqual(worker.sys.path, before)
                if source.is_symlink():
                    source.unlink()
                elif source.exists():
                    source.chmod(0o700)
                    source.rmdir()
                source.mkdir(mode=0o700)

    def test_relative_python_root_is_rejected(self):
        with self.assertRaises(worker.FpmAutoError):
            worker._configure_native_python_paths("relative/panel")


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
        ram = patch.object(worker, "_native_memory_mib", return_value=4096)
        ram.start()
        self.addCleanup(ram.stop)
        native_setter = patch.object(worker, "_verified_native_fpm_setter", return_value=None)
        native_setter.start()
        self.addCleanup(native_setter.stop)

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
            expected_policy_revision=self.settings["revision"],
            expected_monitor_revision=0,
            expected_impact=self._controller()._prepare(
                worker._args("85", self.settings["profiles"]["85"]))["impact_sha256"],
            reviewed=True, controller_factory=self.factory)

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
        # Emulate the verified aaPanel setter's four numeric substitutions
        # while retaining other pool directives (including max_requests).
        import re
        content = self.config.read_bytes()
        expected = worker._native_php_tuning(4096)
        for key, value in expected.items():
            pattern = rb"(?m)^([ \\t]*" + re.escape(key.encode()) + rb"[ \\t]*=[ \\t]*)[0-9]+"
            content, count = re.subn(pattern, lambda m: m.group(1) + str(value).encode(), content)
            if count != 1:
                raise AssertionError("Native fixture missing " + key)
        self.config.write_bytes(content)
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

    def test_complete_138_site_mapping_can_enable_auto_without_any_host_write(self):
        self.impact["matched_sites"]=[
            {"id":i+3,"site_key":f"site-{i:04d}.example.test"}
            for i in range(138)]
        self.impact["site_count"]=138
        before=self.config.read_bytes()
        result=self._enable()
        self.assertTrue(result["enabled"],result)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertFalse((self.state/recovery.JOURNAL).exists())
        self.assertEqual(self.calls,[])
        saved=worker.inspect("85",data_dir=str(self.state))
        self.assertTrue(saved["enabled"])
        disabled=worker.set_enabled(
            "85",False,data_dir=str(self.state),
            expected_auto_revision=saved["state_revision"])
        self.assertFalse(disabled["enabled"])
        self.assertEqual(self.config.read_bytes(),before)

    def test_reviewed_impact_identity_rejects_all_stale_site_owners(self):
        from ach_customizer_state import set_enabled as monitor_toggle
        args = worker._args("85", DESIRED)
        approved=self._controller()._prepare(args)["impact_sha256"]
        scenarios=[
            ("added", lambda: self.impact["matched_sites"].append(
                {"id":8,"site_key":"new.example"})),
            ("removed",lambda:self.impact["matched_sites"].pop()),
            ("reassigned",lambda:self.impact["matched_sites"][0].update(
                site_key="new-owner.example")),
            ("dependency",lambda:self.impact.update(dependency_sha256="b"*64)),
        ]
        for name,mutate in scenarios:
            with self.subTest(name=name):
                self.impact["matched_sites"]=[{"id":3,"site_key":"native.example"}]
                self.impact["site_count"]=1
                self.impact["dependency_sha256"]="a"*64
                mutate()
                self.impact["site_count"]=len(self.impact["matched_sites"])
                with self.assertRaises((worker.FpmAutoError, recovery.FpmApplyError)):
                    worker.set_enabled("85",True,data_dir=str(self.state),
                        expected_auto_revision=0,expected_policy_revision=1,
                        expected_monitor_revision=0,expected_impact=approved,
                        reviewed=True,controller_factory=self.factory)
                self.assertFalse(worker.inspect("85",data_dir=str(self.state))["enabled"])
        self.impact["matched_sites"]=[{"id":3,"site_key":"native.example"}]
        self.impact["site_count"]=1
        self.impact["dependency_sha256"]="a"*64
        for forged in ("q"*64,"",None):
            with self.subTest(forged=forged):
                with self.assertRaises(worker.FpmAutoError):
                    worker.set_enabled("85",True,data_dir=str(self.state),
                        expected_auto_revision=0,expected_policy_revision=1,
                        expected_monitor_revision=0,expected_impact=forged,
                        reviewed=True,controller_factory=self.factory)
        with self.assertRaises(worker.FpmAutoError):
            worker.set_enabled("85",True,data_dir=str(self.state),
                expected_auto_revision=0,expected_policy_revision=2,
                expected_monitor_revision=0,expected_impact=approved,
                reviewed=True,controller_factory=self.factory)
        # Changing Monitor without disabling the FPM module is also material.
        monitor_toggle("site_inventory",False,directory=str(self.state),expected_revision=0)
        with self.assertRaises(worker.FpmAutoError):
            worker.set_enabled("85",True,data_dir=str(self.state),
                expected_auto_revision=0,expected_policy_revision=1,
                expected_monitor_revision=0,expected_impact=approved,
                reviewed=True,controller_factory=self.factory)
        result=worker.set_enabled("85",True,data_dir=str(self.state),
            expected_auto_revision=0,expected_policy_revision=1,
            expected_monitor_revision=1,expected_impact=approved,
            reviewed=True,controller_factory=self.factory)
        self.assertTrue(result["enabled"])
        result=worker.set_enabled("85",False,data_dir=str(self.state),
            expected_auto_revision=result["state_revision"])
        self.assertFalse(result["enabled"])

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

    def test_failed_native_init_removed_site_repairs_proven_optimizer(self):
        from unittest.mock import Mock
        self._enable()
        self._start()
        self.assertEqual(self._run()["services"][0]["state"], "Witness Armed")
        self._vendor_reset()
        self._terminal()
        # Native WP deletes the site record after post-optimizer install
        # failure, while unrelated PHP sites continue using this same pool.
        self.impact["matched_sites"] = [{"id": 17, "site_key": "peer.example"}]
        lookup = Mock()
        lookup.where.return_value.field.return_value.find.return_value = []
        lookup.where.return_value.count.return_value = 0
        self.panel.M = Mock(return_value=lookup)
        result = self._run()
        self.assertTrue(result["changed"], result)
        self.assertEqual(result["services"][0]["state"], "Applied")
        from ach_customizer_monitor import preview_php_fpm
        self.assertEqual(preview_php_fpm(
            self.php_root,"85",DESIRED)["state"],"File Match")
        self.assertEqual(self.calls.count("reload"), 1)
        self.assertEqual(self._run()["changed"], False)
        self.assertGreaterEqual(self.panel.M.call_count,2)

    def test_failed_native_init_existing_other_php_site_never_repairs(self):
        from unittest.mock import Mock
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        self.impact["matched_sites"] = [{"id": 17, "site_key": "peer.example"}]
        lookup = Mock()
        lookup.where.return_value.field.return_value.find.return_value = {"id":3}
        self.panel.M = Mock(return_value=lookup)
        result = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"),0)

    def test_native_failed_cleanup_with_existing_domain_binding_never_repairs(self):
        from unittest.mock import Mock
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        self.impact["matched_sites"] = [{"id": 17, "site_key": "peer.example"}]
        def lookup(kind):
            ref = Mock()
            ref.where.return_value.field.return_value.find.return_value = []
            ref.where.return_value.count.return_value = (
                1 if kind == "domain" else 0)
            return ref
        self.panel.M = Mock(side_effect=lookup)
        result = self._run()
        self.assertFalse(result["changed"])
        self.assertEqual(self.config.read_bytes(), VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"), 0)

    def test_native_success_without_attributed_site_never_repairs(self):
        from unittest.mock import Mock
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self.lock_path.unlink()
        self.event = {**self.event, "status": 1, "steps": [1, 1, 1, 1],
                      "mtime_ns": time.time_ns(), "token": "a"*64}
        self.impact["matched_sites"] = [{"id": 17, "site_key": "peer.example"}]
        self.panel.M = Mock()
        result = self._run()
        self.assertFalse(result["changed"])
        self.panel.M.assert_not_called()
        self.assertEqual(self.config.read_bytes(), VENDOR_BYTES)

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

    def test_fpm_setter_source_drift_refuses_without_host_mutation(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        with patch.object(worker,"_verified_native_fpm_setter",
                          side_effect=worker.FpmAutoError("Native writer drift")):
            with self.assertRaisesRegex(worker.FpmAutoError,"writer drift"):
                self._run()
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"),0)

    def test_native_memory_change_after_witness_refuses_without_rewrite(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        with patch.object(worker,"_native_memory_mib",return_value=2048):
            with self.assertRaisesRegex(worker.FpmAutoError,"physical-memory tier"):
                self._run()
        self.assertEqual(self.config.read_bytes(),VENDOR_BYTES)
        self.assertEqual(self.calls.count("reload"),0)

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

    def test_admin_edit_after_native_optimizer_is_not_overwritten(self):
        for changed_key, changed_value in (
            ("pm.max_children", "61"),
            ("pm.start_servers", "7"),
            ("pm.min_spare_servers", "6"),
            ("pm.max_spare_servers", "18"),
            ("pm.max_requests", "999"),
        ):
            with self.subTest(setting=changed_key):
                # Each case is a separate guarded native event.
                self.config.write_bytes(BASELINE)
                if self.marker.exists():
                    self.marker.unlink()
                status=worker.inspect("85",data_dir=str(self.state))
                if status["enabled"]:
                    worker.set_enabled("85",False,data_dir=str(self.state),
                                       expected_auto_revision=status["state_revision"])
                self._enable()
                self._start()
                self._run()
                self._vendor_reset()
                current=self.config.read_bytes()
                key=changed_key.encode()
                import re
                matches=list(re.finditer(rb"(?m)^"+re.escape(key)+rb"\s*=\s*\d+",current))
                if matches:
                    match=matches[0]
                    modified=(current[:match.start()]+key+b" = "+changed_value.encode()
                              +current[match.end():])
                else:
                    modified=current+b"pm.max_requests = "+changed_value.encode()+b"\n"
                self.config.write_bytes(modified)
                self._terminal()
                with self.assertRaisesRegex(worker.FpmAutoError,
                                            "optimizer output|max_requests"):
                    self._run()
                self.assertEqual(self.config.read_bytes(), modified)
                self.assertEqual(self.calls.count("reload"), 0)

    def test_unrelated_directives_are_preserved_by_native_auto_repair(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self.config.write_bytes(self.config.read_bytes() +
                                b"request_terminate_timeout = 23s\n")
        self._terminal()
        result=self._run()
        self.assertTrue(result["changed"])
        self.assertIn(b"request_terminate_timeout = 23s\n",self.config.read_bytes())
        self.assertEqual(self.calls.count("reload"),1)

    def test_source_ownership_is_rechecked_inside_final_apply_cas(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        real=worker.recovery.apply
        captured=[]
        def race(*args, **kwargs):
            verifier=kwargs["auto_source_verify"]
            def before_mutation():
                value=verifier()
                captured.append(value)
                if len(captured)==1:
                    self.config.write_bytes(self.config.read_bytes().replace(
                        b"pm.max_children=80",b"pm.max_children=68"))
                return value
            kwargs["auto_source_verify"]=before_mutation
            return real(*args,**kwargs)
        with patch.object(worker.recovery,"apply",side_effect=race):
            with self.assertRaises(recovery.FpmApplyError):
                self._run()
        self.assertGreaterEqual(len(captured),1)
        self.assertIn(b"pm.max_children=68",self.config.read_bytes())
        self.assertEqual(self.calls.count("reload"),0)

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

    def test_emergency_disable_during_long_reload_is_durable_and_auto_completed(self):
        import threading
        import time as clock
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        entered=threading.Event()
        finish=threading.Event()
        results=[]
        errors=[]
        def slow_factory():
            controller=self._controller()
            real=controller.hooks_factory
            def hooks(version, desired):
                validate, activate, verify = real(version, desired)
                if desired.get("pm.max_children") == 20:
                    def long_reload():
                        entered.set()
                        if not finish.wait(timeout=12):
                            raise AssertionError("long reload was never released")
                        activate()
                    return validate, long_reload, verify
                return validate, activate, verify
            controller.hooks_factory=hooks
            return controller
        self.factory=slow_factory
        def run_thread():
            try:
                results.append(self._run())
            except BaseException as exc:
                errors.append(exc)
        task=threading.Thread(target=run_thread, name="isolated-shared-fpm-repair")
        task.start()
        try:
            self.assertTrue(entered.wait(timeout=5),"guarded FPM operation did not reach reload")
            before=clock.monotonic()
            queued=worker.request_disable("85",data_dir=str(self.state),
                                          expected_auto_revision=0)
            self.assertLess(clock.monotonic()-before,5)
            self.assertTrue(queued["pending_disable"])
            self.assertTrue(queued["enabled"])
            self.assertEqual(queued["last_state"],"Pending Disable")
            self.assertTrue((self.state/worker._revoke_name("85")).is_file())
            # The current operation finishes at its safe transaction
            # boundary, but no new automatic mutation is authorized.
        finally:
            finish.set()
            task.join(timeout=12)
        self.assertFalse(task.is_alive(),"shared lock was not released")
        self.assertEqual(errors,[])
        self.assertEqual(len(results),1)
        self.assertTrue(results[0]["changed"])
        self.assertTrue(results[0]["revocation_completed"])
        status=worker.inspect("85",data_dir=str(self.state))
        self.assertFalse(status["enabled"])
        self.assertFalse(status["pending_disable"])
        self.assertEqual(status["last_state"],"Disabled")
        self.assertRegex(status["last_operation"],"^[0-9a-f]{32}$")
        self.assertFalse((self.state/worker._revoke_name("85")).exists())
        before_count=self.calls.count("reload")
        self.config.write_bytes(BASELINE)
        self.marker.unlink()
        self._start()
        self._terminal()
        self.assertFalse(self._run()["changed"])
        self.assertEqual(self.calls.count("reload"),before_count)
        again=worker.request_disable("85",data_dir=str(self.state),
                                     expected_auto_revision=0)
        self.assertFalse(again["enabled"])
        self.assertFalse(again["pending_disable"])

    def test_sigkill_at_atomic_disable_publication_preserves_complete_intent(self):
        self._enable()
        fd=worker._open_state_dir(str(self.state))
        try:
            request=worker._read(fd)["profiles"]["85"]
        finally:
            os.close(fd)
        published=worker.native._publish_manual_review_noreplace
        pid=os.fork()
        if pid==0:
            try:
                def abrupt(*args):
                    published(*args)
                    os._exit(78)
                with patch.object(worker.native,"_publish_manual_review_noreplace",
                                  side_effect=abrupt):
                    fd=worker._open_state_dir(str(self.state))
                    try:
                        worker._publish_revoke(fd,"85",request)
                    finally:
                        os.close(fd)
            except BaseException:
                os._exit(96)
            os._exit(97)
        child,status=os.waitpid(pid,0)
        self.assertEqual(child,pid)
        self.assertTrue(os.WIFEXITED(status),status)
        self.assertEqual(os.WEXITSTATUS(status),78)
        filename=self.state/worker._revoke_name("85")
        self.assertEqual(filename.stat().st_nlink,1)
        self.assertEqual(filename.stat().st_mode&0o777,0o600)
        self.assertTrue(worker.inspect("85",data_dir=str(self.state))["pending_disable"])
        # A later worker honors the completed intent even though the first
        # process was killed before directory fsync/HTTP acknowledgment.
        state=worker.run(data_dir=str(self.state),controller_factory=self.factory,
                         terminal_reader=lambda:None)
        self.assertTrue(state["revocation_completed"])
        self.assertFalse(worker.inspect("85",data_dir=str(self.state))["enabled"])
        self.assertFalse(filename.exists())

    def test_policy_off_commit_crash_before_revoke_unlink_stays_visible_and_recovers(self):
        """A durable policy-off does not mean the canonical request is retired."""
        self._enable()
        fd=worker._open_state_dir(str(self.state))
        try:
            original=worker._read(fd)["profiles"]["85"]
            worker._publish_revoke(fd,"85",original)
        finally:
            os.close(fd)
        # An independently enabled sibling remains untouched by 85 cleanup.
        fd=worker._open_state_dir(str(self.state))
        try:
            current=worker._read(fd)
            sibling={**current["profiles"]["85"],"enabled_ns":123456,
                     "active":None,"last_token":None,"last_operation":None}
            worker._save(fd,{**current,"revision":current["revision"]+1,
                             "profiles":{**current["profiles"],"81":sibling}})
        finally:
            os.close(fd)
        canonical=self.state/worker._revoke_name("85")
        assert canonical.is_file()
        child=os.fork()
        if child == 0:
            try:
                actual_unlink=worker.os.unlink
                def crash_before_unlink(path,*args,**kwargs):
                    if path == worker._revoke_name("85"):
                        os._exit(83)
                    return actual_unlink(path,*args,**kwargs)
                with patch.object(worker.os,"unlink",side_effect=crash_before_unlink):
                    fd=worker._open_state_dir(str(self.state))
                    lock=worker._exclusive_lock(fd)
                    try:
                        worker._consume_revoke_locked(fd,"85")
                    finally:
                        os.close(lock)
                        os.close(fd)
            except BaseException:
                os._exit(92)
            os._exit(93)
        pid,status=os.waitpid(child,0)
        self.assertEqual(pid,child)
        self.assertTrue(os.WIFEXITED(status))
        self.assertEqual(os.WEXITSTATUS(status),83)
        persisted=worker.inspect("85",data_dir=str(self.state))
        self.assertFalse(persisted["enabled"])
        self.assertTrue(canonical.exists())
        self.assertEqual(canonical.stat().st_mode & 0o777,0o600)
        self.assertTrue(persisted["pending_disable"])
        self.assertEqual(persisted["last_state"],"Pending Disable")
        self.assertTrue(worker.any_pending_disable(data_dir=str(self.state)))
        # A fresh Disable is not needed to finish the crash-recovered request.
        before=self.config.read_bytes()
        calls_before=list(self.calls)
        finished=worker.run(data_dir=str(self.state),
                            controller_factory=self.factory,
                            terminal_reader=lambda:None)
        self.assertTrue(finished["revocation_completed"])
        self.assertFalse(finished["changed"])
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.calls,calls_before)
        self.assertFalse(canonical.exists())
        completed=worker.inspect("85",data_dir=str(self.state))
        self.assertFalse(completed["enabled"])
        self.assertFalse(completed["pending_disable"])
        self.assertEqual(completed["last_state"],"Disabled")
        self.assertFalse(worker.any_pending_disable(data_dir=str(self.state)))
        self.assertTrue(worker.inspect("81",data_dir=str(self.state))["enabled"])
        approved=self._enable()
        self.assertTrue(approved["enabled"])
        self.assertFalse(worker.inspect("85",data_dir=str(self.state))["pending_disable"])

    def test_post_policy_off_lock_busy_worker_preserves_timer_and_uninstall(self):
        """Real independent-process flock must not strand a disabled profile."""
        import ach_customizer_fpm_watcher as watcher
        import contextlib
        import io
        self._enable()
        fd=worker._open_state_dir(str(self.state))
        try:
            before=worker._read(fd)
            current=before["profiles"]["85"]
            worker._publish_revoke(fd,"85",current)
            disabled={**current,"enabled":False,"active":None,"last_state":"Disabled"}
            worker._save(fd,{**before,"revision":before["revision"]+1,
                             "profiles":{**before["profiles"],"85":disabled}})
        finally:
            os.close(fd)
        unit_dir=self.base/"systemd-qa-units"
        unit_dir.mkdir(mode=0o700)
        watcher._ensure_units(unit_dir)
        ready_read,ready_write=os.pipe()
        release_read,release_write=os.pipe()
        child=os.fork()
        if child == 0:
            os.close(ready_read)
            os.close(release_write)
            try:
                shared_fd=worker._open_state_dir(str(self.state))
                lock_fd=worker._exclusive_lock(shared_fd)
                os.write(ready_write,b"1")
                os.read(release_read,1)
                os.close(lock_fd)
                os.close(shared_fd)
                os._exit(0)
            except BaseException:
                os._exit(97)
        os.close(ready_write)
        os.close(release_read)
        try:
            self.assertEqual(os.read(ready_read,1),b"1")
            self.assertFalse(worker.inspect("85",data_dir=str(self.state))["enabled"])
            self.assertTrue(worker.inspect("85",data_dir=str(self.state))["pending_disable"])
            real_run=worker.run
            real_any_enabled=worker.any_enabled
            real_any_pending=worker.any_pending_disable
            output=io.StringIO()
            with patch.object(worker,"run",side_effect=lambda:real_run(
                    data_dir=str(self.state),controller_factory=self.factory,
                    terminal_reader=lambda:None)), patch.object(
                    worker,"any_enabled",side_effect=lambda *a,**k:real_any_enabled(
                    data_dir=str(self.state))), patch.object(
                    worker,"any_pending_disable",side_effect=lambda *a,**k:real_any_pending(
                    data_dir=str(self.state))),patch.object(
                    watcher,"_stop") as stop,contextlib.redirect_stdout(output):
                self.assertEqual(worker.main(["run"]),0)
                stop.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["state"],"Pending Disable")
            self.assertTrue((self.state/worker._revoke_name("85")).exists())
            with patch.object(watcher,"_stop") as stop,patch.object(
                    watcher,"_run") as run_systemctl:
                with self.assertRaisesRegex(watcher.FpmWatcherError,"pending"):
                    watcher.uninstall(data_dir=str(self.state),unit_root=unit_dir)
                stop.assert_not_called()
                run_systemctl.assert_not_called()
            self.assertEqual(len(list(unit_dir.glob(watcher.UNIT+".*"))),3)
        finally:
            os.write(release_write,b"x")
            os.close(release_write)
            os.close(ready_read)
            pid,status=os.waitpid(child,0)
            self.assertEqual(pid,child)
            self.assertTrue(os.WIFEXITED(status),status)
            self.assertEqual(os.WEXITSTATUS(status),0)
        previously=self.config.read_bytes()
        completed=worker.run(data_dir=str(self.state),controller_factory=self.factory,
                             terminal_reader=lambda:None)
        self.assertTrue(completed["revocation_completed"])
        self.assertEqual(completed["state"],"Disabled")
        self.assertEqual(self.config.read_bytes(),previously)
        self.assertEqual(self.calls,[])
        self.assertFalse(worker.inspect("85",data_dir=str(self.state))["pending_disable"])
        with patch.object(watcher,"_stop") as stop,patch.object(
                watcher,"_run") as run_systemctl:
            watcher.uninstall(data_dir=str(self.state),unit_root=unit_dir)
            stop.assert_called_once_with()
            run_systemctl.assert_called_once_with("daemon-reload")
        self.assertEqual(list(unit_dir.glob(watcher.UNIT+".*")),[])
        self.assertTrue(self._enable()["enabled"])

    def test_failed_directory_fsync_after_revoke_unlink_never_stops_retry(self):
        """An uncertain unlink must not stop timer from an exception path."""
        import ach_customizer_fpm_watcher as watcher
        import contextlib
        import io
        import stat
        self._enable()
        fd=worker._open_state_dir(str(self.state))
        try:
            profile=worker._read(fd)["profiles"]["85"]
            worker._publish_revoke(fd,"85",profile)
        finally:
            os.close(fd)
        canonical=self.state/worker._revoke_name("85")
        self.assertTrue(canonical.is_file())
        real_fsync=os.fsync
        observed=[False]
        def failed_ack(fd):
            if (not canonical.exists() and stat.S_ISDIR(os.fstat(fd).st_mode)
                    and not observed[0]):
                observed[0]=True
                raise OSError("synthetic revocation directory fsync failure")
            return real_fsync(fd)
        real_run=worker.run
        real_any_enabled=worker.any_enabled
        real_any_pending=worker.any_pending_disable
        output=io.StringIO()
        with patch.object(worker,"run",side_effect=lambda:real_run(
                data_dir=str(self.state),controller_factory=self.factory,
                terminal_reader=lambda:None)),patch.object(
                worker,"any_enabled",side_effect=lambda *a,**k:real_any_enabled(
                data_dir=str(self.state))),patch.object(
                worker,"any_pending_disable",side_effect=lambda *a,**k:real_any_pending(
                data_dir=str(self.state))),patch.object(
                worker.os,"fsync",side_effect=failed_ack),patch.object(
                watcher,"_stop") as stop,contextlib.redirect_stderr(output):
            self.assertEqual(worker.main(["run"]),1)
            stop.assert_not_called()
        self.assertTrue(observed[0])
        self.assertIn("OSError",output.getvalue())
        self.assertFalse(worker.inspect("85",data_dir=str(self.state))["enabled"])
        self.assertEqual(self.config.read_bytes(),BASELINE)
        self.assertEqual(self.calls,[])
        # Once filesystem access returns, the next invocation can verify
        # the directory and finish without rewriting PHP-FPM.
        done=worker.run(data_dir=str(self.state),controller_factory=self.factory,
                        terminal_reader=lambda:None)
        self.assertEqual(done["state"],"Disabled")
        self.assertFalse(done["changed"])
        self.assertFalse(worker.any_pending_disable(data_dir=str(self.state)))
        self.assertTrue(self._enable()["enabled"])

    def test_unverified_directory_sync_refuses_last_watcher_stop(self):
        with patch.object(worker.os,"fsync",
                          side_effect=OSError("synthetic journal directory sync error")):
            with self.assertRaisesRegex(worker.FpmAutoError,"durability unverified"):
                worker.any_pending_disable(data_dir=str(self.state))
        self.assertFalse(worker.any_pending_disable(data_dir=str(self.state)))

    def test_pending_disable_recovers_after_cancellation_process_crash(self):
        self._enable()
        fd=worker._open_state_dir(str(self.state))
        try:
            data=worker._read(fd)
            worker._publish_revoke(fd,"85",data["profiles"]["85"])
            self.assertIsNotNone(worker._read_revoke(fd,"85"))
        finally:
            os.close(fd)
        status=worker.inspect("85",data_dir=str(self.state))
        self.assertTrue(status["pending_disable"])
        # Simulate restart with no vendor progress at all; a timer worker
        # must complete the durable request before looking for an event.
        result=worker.run(data_dir=str(self.state),controller_factory=self.factory,
                          terminal_reader=lambda:None)
        self.assertFalse(result["changed"])
        self.assertTrue(result["revocation_completed"])
        self.assertFalse(worker.inspect("85",data_dir=str(self.state))["enabled"])
        self.assertFalse((self.state/worker._revoke_name("85")).exists())
        second=worker.run(data_dir=str(self.state),controller_factory=self.factory,
                          terminal_reader=lambda:None)
        self.assertEqual(second["state"],"Disabled")

    def test_emergency_disable_preserves_other_enabled_php_service(self):
        self._enable()
        fd=worker._open_state_dir(str(self.state))
        try:
            store=worker._read(fd)
            unrelated={**store["profiles"]["85"],"enabled_ns":12345,
                       "active":None,"last_token":None,"last_operation":None}
            worker._save(fd,{**store,"revision":store["revision"]+1,
                             "profiles":{**store["profiles"],"81":unrelated}})
        finally:
            os.close(fd)
        result=worker.request_disable("85",data_dir=str(self.state),
                                      expected_auto_revision=0)
        self.assertFalse(result["enabled"])
        self.assertFalse(result["pending_disable"])
        self.assertTrue(worker.inspect("81",data_dir=str(self.state))["enabled"])
        self.assertTrue(worker.any_enabled(data_dir=str(self.state)))

    def test_sigkill_after_committed_native_apply_recovers_exact_operation(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        pid=os.fork()
        if pid == 0:
            try:
                native_apply=worker.recovery.apply
                def interrupted(*args,**kwargs):
                    result=native_apply(*args,**kwargs)
                    os._exit(77)  # committed host journal; no worker ACK
                with patch.object(worker.recovery,"apply",side_effect=interrupted):
                    self._run()
            except BaseException:
                os._exit(91)
            os._exit(92)
        child,status=os.waitpid(pid,0)
        self.assertEqual(child,pid)
        self.assertTrue(os.WIFEXITED(status),status)
        self.assertEqual(os.WEXITSTATUS(status),77,
                         "Child must have terminated after committed host Apply")
        fd=worker._open_state_dir(str(self.state))
        try:
            committed=recovery._read_journal(fd,"85")
        finally:
            os.close(fd)
        self.assertEqual(committed["phase"],"applied")
        self.assertEqual(committed["schema"],2)
        self.assertEqual(committed["event_token"],self.event["token"])
        previous=worker.inspect("85",data_dir=str(self.state))
        self.assertIsNone(previous["last_operation"])
        self.assertEqual(previous["last_state"],"Witness Armed")
        recovered=self._run()
        self.assertEqual(recovered["services"][0]["state"],"Applied")
        self.assertEqual(recovered["services"][0]["operation_id"],
                         committed["operation_id"])
        self.assertFalse(recovered["changed"],
                         "Recovery acknowledgment does not perform a new host write")
        self.assertEqual(self.calls.count("reload"),0,
                         "Parent must not reload FPM on journal-only replay")
        current=worker.inspect("85",data_dir=str(self.state))
        self.assertEqual(current["last_operation"],committed["operation_id"])
        self.assertEqual(current["last_state"],"Applied")
        self.assertEqual(self._run()["changed"],False)
        self.assertEqual(self.calls.count("reload"),0)

    def test_failed_final_ack_commit_replays_exact_host_journal(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        genuine=worker._save
        failed=[False]
        def fail_before_ack(fd,value):
            profile=value["profiles"]["85"]
            if profile["last_state"]=="Applied" and not failed[0]:
                failed[0]=True
                raise OSError("synthetic interrupted final automatic-state fsync")
            return genuine(fd,value)
        with patch.object(worker,"_save",side_effect=fail_before_ack):
            with self.assertRaises(OSError):
                self._run()
        prior_reload=self.calls.count("reload")
        self.assertEqual(prior_reload,1)
        fd=worker._open_state_dir(str(self.state))
        try:
            committed=recovery._read_journal(fd,"85")
        finally:
            os.close(fd)
        self.assertEqual(committed["phase"],"applied")
        self.assertIsNone(worker.inspect("85",data_dir=str(self.state))["last_operation"])
        answer=self._run()
        self.assertFalse(answer["changed"])
        self.assertEqual(answer["services"][0]["operation_id"],committed["operation_id"])
        self.assertEqual(self.calls.count("reload"),prior_reload)
        self.assertEqual(worker.inspect("85",data_dir=str(self.state))["last_state"],"Applied")

    def test_uncertain_final_ack_fsync_does_not_erase_committed_identity(self):
        self._enable()
        self._start()
        self._run()
        self._vendor_reset()
        self._terminal()
        genuine=worker._save
        failed=[False]
        def failure_after_commit(fd,value):
            result=genuine(fd,value)
            if value["profiles"]["85"]["last_state"]=="Applied" and not failed[0]:
                failed[0]=True
                raise OSError("synthetic final directory fsync after rename")
            return result
        with patch.object(worker,"_save",side_effect=failure_after_commit):
            with self.assertRaises(OSError):
                self._run()
        recorded=worker.inspect("85",data_dir=str(self.state))
        self.assertEqual(recorded["last_state"],"Applied")
        self.assertRegex(recorded["last_operation"],r"^[0-9a-f]{32}$")
        self.assertFalse(self._run()["changed"])
        self.assertEqual(self.calls.count("reload"),1)

    def test_uncertain_or_conflicting_committed_recovery_refuses_replay(self):
        for phase in ("uncertain","applied"):
            with self.subTest(phase=phase):
                self.config.write_bytes(BASELINE)
                if self.marker.exists():
                    self.marker.unlink()
                status=worker.inspect("85",data_dir=str(self.state))
                if status["enabled"]:
                    worker.set_enabled("85",False,data_dir=str(self.state),
                                       expected_auto_revision=status["state_revision"])
                self._enable()
                self._start()
                self._run()
                self._vendor_reset()
                self._terminal()
                native_apply=worker.recovery.apply
                def crash(*args,**kwargs):
                    result=native_apply(*args,**kwargs)
                    raise OSError("synthetic crash after host journal fsync")
                with patch.object(worker.recovery,"apply",side_effect=crash):
                    with self.assertRaises(OSError):
                        self._run()
                from json import loads,dumps
                name=self.state/recovery._recovery_names("85")[0]
                record=loads(name.read_text())
                record["phase"]=phase
                if phase=="applied":
                    record["after_sha256"]="a"*64
                name.write_text(dumps(record)+"\n")
                name.chmod(0o600)
                with self.assertRaises(recovery.FpmApplyError):
                    self._run()
                self.assertNotEqual(worker.inspect("85",data_dir=str(self.state))["last_state"],
                                    "Applied")
                # Restore disposable fixtures to a new versioned run.
                name.unlink()
                (self.state/recovery._recovery_names("85")[1]).unlink()

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
