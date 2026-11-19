"""No systemd or host writes: FPM opt-in service lifecycle tests."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN=Path(__file__).resolve().parents[1]/"plugin"/"ach_customizer"
sys.path.insert(0,str(PLUGIN))
import ach_customizer_fpm_watcher as service
import ach_customizer_fpm_auto as auto


class FpmWatcherTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="ach-fpm-units-")
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.python=self.root/"panel-python"
        self.worker=self.root/"worker.py"
        self.python.write_bytes(b"native python placeholder")
        self.worker.write_bytes(b"native worker placeholder")
        for name,val in (("PANEL_PYTHON",str(self.python)),("PLUGIN_WORKER",str(self.worker))):
            task=patch.object(service,name,val)
            task.start();self.addCleanup(task.stop)

    def test_install_is_explicit_and_units_are_verified_without_overwrite(self):
        self.assertFalse(any(self.root.glob("ach-customizer-fpm-auto.*")))
        service._ensure_units(self.root)
        self.assertEqual(len(list(self.root.glob("ach-customizer-fpm-auto.*"))),3)
        for extension,text in service.UNITS.items():
            path=self.root/(service.UNIT+"."+extension)
            self.assertTrue(service._trusted(path,text))
            self.assertEqual(path.stat().st_mode & 0o777,0o644)
        service._ensure_units(self.root)
        path=self.root/(service.UNIT+".service")
        path.write_text("foreign")
        with self.assertRaises(service.FpmWatcherError):
            service._ensure_units(self.root)
        self.assertEqual(path.read_text(),"foreign")

    def test_enable_only_after_verified_source_and_disabled_cleanup(self):
        recorded=[]
        original=service._ensure_units
        with patch.object(service.native,"_native_supported"),patch.object(
             service,"_ensure_units",side_effect=lambda:original(self.root)),patch.object(
             service,"_run",side_effect=lambda *args:recorded.append(args)),patch.object(
             auto,"any_enabled",return_value=False),patch.object(
             auto,"set_enabled",return_value={"enabled":True,"state_revision":1}) as toggle:
            result=service.enable("85",data_dir=str(self.root),
                                  expected_auto_revision=0,expected_policy_revision=1,
                                  reviewed=True)
        self.assertTrue(result["enabled"])
        self.assertEqual(recorded[0],("daemon-reload",))
        self.assertIn(("enable","--now",service.UNIT+".path",service.UNIT+".timer"),recorded)
        toggle.assert_called_once()

    def test_disable_turns_off_persistent_intent_before_stopping_units(self):
        order=[]
        with patch.object(auto,"set_enabled",side_effect=lambda *a,**k:(
             order.append("policy_off") or {"enabled":False})),patch.object(
             auto,"any_enabled",return_value=False),patch.object(
             service,"_stop",side_effect=lambda:order.append("units_off")):
            outcome=service.disable("85",data_dir=str(self.root),
                                    expected_auto_revision=1)
        self.assertFalse(outcome["enabled"])
        self.assertEqual(order,["policy_off","units_off"])

    def test_uninstall_preserves_recovery_and_only_removes_owned_units(self):
        service._ensure_units(self.root)
        marker=self.root/"durable-state"
        marker.write_text("do not remove")
        with patch.object(auto,"inspect",return_value={"enabled":False}),patch.object(
                service,"_stop"),patch.object(service,"_run"):
            service.uninstall(data_dir=str(self.root),unit_root=self.root)
        self.assertEqual(marker.read_text(),"do not remove")
        self.assertEqual(list(self.root.glob(service.UNIT+".*")),[])


if __name__=="__main__":
    unittest.main()
