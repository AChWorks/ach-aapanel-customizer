"""Fixture systemd configuration: no shared host unit mutations."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_wp_terminal as worker
import ach_customizer_wp_watcher as watcher


class WatcherTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-wp-units-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.units = self.root / "units"
        self.units.mkdir(mode=0o700)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)
        self.panel_python = self.root / "python3"
        self.plugin_worker = self.root / "worker.py"
        self.panel_python.write_text("#!/bin/sh\n")
        self.plugin_worker.write_text("print('fixture')\n")
        patcher = patch.multiple(watcher, PANEL_PYTHON=str(self.panel_python),
                                 PLUGIN_WORKER=str(self.plugin_worker))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_health_discriminates_active_units_unsupported_source_and_missing_unit(self):
        from unittest.mock import Mock
        with patch.object(worker,"_native_supported"), patch.object(watcher,"_run"):
            self.assertFalse(watcher.health(unit_root=self.units)["watcher_ready"])
            watcher._ensure_units(self.units)
            with patch.object(watcher.subprocess,"run",return_value=Mock(returncode=0)):
                result=watcher.health(unit_root=self.units)
                self.assertTrue(result["watcher_ready"])
                self.assertTrue(result["watcher_source_verified"])
            with patch.object(watcher.subprocess,"run",return_value=Mock(returncode=3)):
                result=watcher.health(unit_root=self.units)
                self.assertFalse(result["watcher_ready"])
                self.assertEqual(result["watcher_status"],"Watcher units inactive")
        with patch.object(worker,"_native_supported",side_effect=worker.TerminalError("Changed source")):
            result=watcher.health(unit_root=self.units)
            self.assertFalse(result["watcher_source_verified"])
            self.assertEqual(result["watcher_status"],"Unsupported native source")

    def test_disabled_by_default_no_systemd_units_created(self):
        self.assertFalse(worker.inspect(data_dir=str(self.data))["enabled"])
        self.assertEqual(list(self.units.iterdir()), [])

    def test_enable_creates_only_owned_units_and_disabled_fallback(self):
        with patch.object(worker,"_native_supported"), patch.object(watcher,"_run") as systemctl:
            result=watcher.enable(data_dir=str(self.data),unit_root=self.units)
            self.assertTrue(result["enabled"])
            self.assertEqual({x.name for x in self.units.iterdir()},
                             {"ach-customizer-wp-terminal."+suffix for suffix in ("path","service","timer")})
            for suffix,expected in watcher.UNITS.items():
                self.assertEqual((self.units / (watcher.UNIT+"."+suffix)).read_text(),expected)
            # Equivalent deployment is idempotent; no foreign unit overwritten.
            watcher.enable(data_dir=str(self.data),unit_root=self.units)
            self.assertTrue(systemctl.called)
            result=watcher.disable(data_dir=str(self.data))
            self.assertFalse(result["enabled"])
            self.assertEqual(worker.inspect(data_dir=str(self.data))["last_reason"],"Disabled")
            watcher.uninstall(data_dir=str(self.data),unit_root=self.units)
            self.assertEqual(list(self.units.iterdir()), [])

    def test_reject_foreign_units_and_no_policy_activation(self):
        path=self.units / (watcher.UNIT+".path")
        path.write_text("[Unit]\nDescription=foreign owner\n")
        path.chmod(0o644)
        with patch.object(worker,"_native_supported"), patch.object(watcher,"_run"):
            with self.assertRaises(watcher.WatcherError):
                watcher.enable(data_dir=str(self.data),unit_root=self.units)
            self.assertFalse(worker.inspect(data_dir=str(self.data))["enabled"])
            self.assertIn("foreign owner", path.read_text())

    def test_failed_service_activation_does_not_enable_policy(self):
        def failing(*args):
            if args[0]=="enable":
                raise watcher.WatcherError("systemctl failed")
        with patch.object(worker,"_native_supported"),patch.object(watcher,"_run",side_effect=failing):
            with self.assertRaises(watcher.WatcherError):
                watcher.enable(data_dir=str(self.data),unit_root=self.units)
            self.assertFalse(worker.inspect(data_dir=str(self.data))["enabled"])

    def test_emergency_disable_is_effective_despite_service_manager_failure(self):
        worker.set_enabled(True,data_dir=str(self.data))
        with patch.object(watcher,"_run",side_effect=watcher.WatcherError("systemctl failed")):
            with self.assertRaises(watcher.WatcherError):
                watcher.disable(data_dir=str(self.data))
        self.assertFalse(worker.inspect(data_dir=str(self.data))["enabled"])


if __name__=='__main__':
    unittest.main()
