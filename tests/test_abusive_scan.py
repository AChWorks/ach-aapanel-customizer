"""P0 Fail2ban scanner ownership, native log and recovery contract.

No test accesses system Fail2ban, host firewall or live Nginx.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_abusive_scan as scan


class ScannerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-scan-p0-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.filter = self.root / "filter.d"
        self.jail = self.root / "jail.d"
        self.log_dir = self.root / "wwwlogs"
        self.vhosts = self.root / "vhosts"
        self.data = self.root / "paneldata"
        for p in (self.filter, self.jail, self.log_dir, self.vhosts, self.data):
            p.mkdir()
        self.fd = os.open(self.data, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.site = {
            "id": 23, "name": "test.example",
            "path": str(self.root / "site"), "status": "1",
            "bound_domains": [{"name": "test.example", "port": 80}],
        }
        (self.root / "site").mkdir()
        self.log = self.log_dir / "test.example.log"
        self.log.write_text('203.0.113.42 - - [21/Nov/2026:20:00:00 +0000] "GET /.env HTTP/1.1" 403 42 "-" "-"\n')
        self.vhost = self.vhosts / "test.example.conf"
        self.vhost.write_text("server {\naccess_log " + str(self.log) + ";\n}\n")
        self.peer = self.root / "peer"
        self.peer.write_text("unchanged")
        self.live = False
        self.fail_reload = False
        self.calls = []
        self.log_sha = "3" * 64

    def runner(self, argv, **kw):
        self.calls.append(list(argv))
        self.assertEqual(argv[0], "fail2ban-client")
        if argv[1] == "-t":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[1] == "reload":
            if self.fail_reload:
                return SimpleNamespace(returncode=1, stdout="", stderr="intentional")
            self.live = (self.jail / "ach-customizer-scan-23.local").exists()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[1] == "status":
            return SimpleNamespace(returncode=0 if self.live else 255,
                stdout="Status for the jail: ach-customizer-scan-23" if self.live else "",
                stderr="")
        raise AssertionError(argv)

    def execute(self, action, **kwargs):
        with (patch.object(scan, "LOG_DIR", self.log_dir),
              patch.object(scan, "_source_safe",
                           return_value=(self.log_sha, "unused"))):
            return scan.manage(
                action, self.site, data_fd=self.fd, runner=self.runner,
                filter_dir=self.filter, jail_dir=self.jail,
                vhost_root=self.vhosts, log_dir=self.log_dir, **kwargs)

    def test_real_vhost_combined_log_exclusivity(self):
        with patch.object(scan, "_source_safe", return_value=(self.log_sha, "")):
            self.assertEqual(scan._site_log(self.site, vhost_root=self.vhosts,
                                            log_dir=self.log_dir),
                             (self.log_sha, str(self.log)))
            self.vhost.write_text(self.vhost.read_text() + "\naccess_log /dev/null;\n")
            # /dev/null may be used for sub-locations; it is not the
            # selected site's second native combined access log.
            self.assertEqual(scan._site_log(self.site, vhost_root=self.vhosts,
                                            log_dir=self.log_dir)[1], str(self.log))
            self.vhost.write_text(self.vhost.read_text() +
                "access_log " + str(self.log_dir / "foreign.log") + ";\n")
            with self.assertRaisesRegex(scan.AbuseError, "uniquely owned"):
                scan._site_log(self.site, vhost_root=self.vhosts, log_dir=self.log_dir)

    def test_plan_apply_recheck_restore_exact_owned_jail(self):
        preview = self.execute("preview")
        self.assertEqual(preview["state"], "Unmanaged")
        self.assertEqual(len(preview["plan_sha256"]), 64)
        self.assertFalse(preview["runtime_verified"])
        with self.assertRaisesRegex(scan.AbuseError, "authorization required"):
            self.execute("apply", expected_plan=preview["plan_sha256"])
        with self.assertRaisesRegex(scan.AbuseError, "readiness changed"):
            self.execute("apply", approved=True, expected_plan="0"*64)
        apply = self.execute("apply", approved=True,
                             expected_plan=preview["plan_sha256"])
        self.assertTrue(apply["runtime_verified"])
        self.assertEqual(apply["state"], "Applied")
        self.assertEqual(self.execute("recheck")["state"], "Applied")
        self.assertEqual(self.peer.read_text(), "unchanged")
        jailtext = (self.jail / "ach-customizer-scan-23.local").read_text()
        self.assertIn("logpath = " + str(self.log), jailtext)
        self.assertIn('protocol="tcp"', jailtext)
        self.assertIn('protocol="udp"', jailtext)
        self.assertIn("ach-customizer-scan-23-tcp", jailtext)
        self.assertIn("ach-customizer-scan-23-udp", jailtext)
        self.assertNotIn("accept = true", jailtext)
        journal = json.loads((self.data / scan._journal_name(23)).read_text())
        self.assertEqual(journal["phase"], "applied")
        self.assertEqual(journal["recovery_id"], apply["recovery_id"])
        self.assertEqual(os.stat(self.data / scan._journal_name(23)).st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(scan.AbuseError, "Recovery ID"):
            self.execute("restore", approved=True, recovery_id="0"*32)
        restored = self.execute("restore", approved=True,
                                recovery_id=apply["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
        self.assertEqual(self.execute("recheck")["state"], "Restored")
        self.assertEqual(self.peer.read_text(), "unchanged")
        self.assertTrue((self.filter / scan.FILTER_NAME).is_file())

    def test_failed_reload_preserves_recovery_and_converges(self):
        preview = self.execute("preview")
        self.fail_reload = True
        with self.assertRaises(scan.AbuseError) as error:
            self.execute("apply", approved=True,
                         expected_plan=preview["plan_sha256"])
        self.assertEqual(error.exception.stage, "uncertain")
        recovery_id = error.exception.recovery_id
        self.assertEqual(self.execute("recheck")["state"], "Needs Review")
        self.fail_reload = False
        restored = self.execute("restore", approved=True, recovery_id=recovery_id)
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(self.live)

    def test_foreign_config_retained_and_journal_protected(self):
        foreign = self.jail / "ach-customizer-scan-23.local"
        foreign.write_text("foreign")
        self.assertEqual(self.execute("preview")["state"], "Needs Review")
        with self.assertRaises(scan.AbuseError):
            self.execute("apply", approved=True, expected_plan="0"*64)
        self.assertEqual(foreign.read_text(), "foreign")

    def test_invalid_policy_or_native_log_never_applies(self):
        for bad in ({"maxretry":"0"}, {"findtime":"1.0"},
                    {"bantime":"inf"}, {"maxretry":True}):
            with self.subTest(bad=bad), self.assertRaises(scan.AbuseError):
                self.execute("preview", params=bad)
        self.log.unlink()
        self.log.symlink_to(self.peer)
        self.assertEqual(self.execute("preview")["state"], "Needs Review")
        self.assertIsNone(self.execute("preview").get("plan_sha256"))
        with self.assertRaises(scan.AbuseError):
            self.execute("apply", approved=True, expected_plan="0"*64)

    def test_source_ownership_changed_since_preview_refused(self):
        first = self.execute("preview")
        self.vhost.write_text(self.vhost.read_text() + "# aaPanel regeneration\n")
        # The independent checker now sees a new native-source digest.
        with patch.object(scan, "_source_safe",
                          side_effect=[("4"*64, ""), ("4"*64, "")]):
            with patch.object(scan, "LOG_DIR", self.log_dir):
                with self.assertRaisesRegex(scan.AbuseError, "readiness changed"):
                    scan.manage("apply", self.site, data_fd=self.fd,
                                approved=True, expected_plan=first["plan_sha256"],
                                runner=self.runner, filter_dir=self.filter,
                                jail_dir=self.jail, vhost_root=self.vhosts,
                                log_dir=self.log_dir)
        self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())

    def test_filter_covers_expected_probes_and_not_generic_paths(self):
        text = scan.FILTER_TEXT
        self.assertIn("HTTP/(?:1[.]0|1[.]1|2", text)
        self.assertIn("3(?:[.]0)?", text)
        self.assertIn(r"\[\]", text)
        self.assertNotIn(".well-known", text)
        self.assertNotIn("/oauth/", text)
        self.assertEqual(scan._policy({"maxretry": "3"})["maxretry"], 3)


if __name__ == "__main__":
    unittest.main()
