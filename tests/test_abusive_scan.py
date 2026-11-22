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
        self.daemon = True
        self.calls = []
        self.nft_sets = set()
        self.nft_inspection_failed = False
        self.log_sha = "3" * 64

    def runner(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] == "nft":
            self.assertEqual(argv, ["nft", "-j", "list", "sets"])
            if self.nft_inspection_failed:
                return SimpleNamespace(returncode=1, stdout="", stderr="unavailable")
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "nftables": [{"metainfo": {"json_schema_version": 1}}] +
                    [{"set": {"family": "inet", "table": "f2b-table",
                              "name": name}} for name in sorted(self.nft_sets)]
            }), stderr="")
        self.assertEqual(argv[0], "fail2ban-client")
        if argv[1] == "-t":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[1] == "reload":
            if self.fail_reload:
                return SimpleNamespace(returncode=1, stdout="", stderr="intentional")
            self.live = (self.jail / "ach-customizer-scan-23.local").exists()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[1] == "status" and len(argv) == 2:
            return SimpleNamespace(returncode=0 if self.daemon else 255,
                stdout="Status" if self.daemon else "", stderr="")
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

    def test_writable_log_directory_cannot_authorize_root_firewall(self):
        # A www-owned parent can replace even a root-owned, 0644 log.
        self.log_dir.chmod(0o777)
        try:
            preview = self.execute("preview")
            self.assertEqual(preview["state"], "Needs Review")
            self.assertIn("replaceable", preview["reason"])
            self.assertIsNone(preview["log_path"])
            with self.assertRaisesRegex(scan.AbuseError, "replaceable"):
                self.execute("apply", approved=True, expected_plan="0" * 64)
            self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
        finally:
            self.log_dir.chmod(0o755)

    def test_writable_log_file_cannot_authorize_root_firewall(self):
        self.log.chmod(0o666)
        try:
            with patch.object(scan, "_source_safe", return_value=(self.log_sha, "")):
                with self.assertRaisesRegex(scan.AbuseError, "replaceable"):
                    scan._site_log(self.site, vhost_root=self.vhosts, log_dir=self.log_dir)
        finally:
            self.log.chmod(0o644)

    def test_foreign_log_owner_refused_even_if_mode_readonly(self):
        # Simulate a root-run app inspecting a foreign-owned native log.
        with patch.object(scan, "_source_safe", return_value=(self.log_sha, "")):
            with patch.object(scan.os, "geteuid", return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(scan.AbuseError, "replaceable"):
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
        self.assertEqual(self.execute("recheck")["state"], "Recovery Required")
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

    def test_stopped_daemon_never_creates_a_new_jail_or_recovery_state(self):
        self.daemon = False
        report = self.execute("preview")
        self.assertEqual(report["state"], "Dependency Missing")
        self.assertIn("Start the Fail2ban daemon", report["reason"])
        with patch.object(scan, "_source_safe", return_value=(self.log_sha, "")):
            ready_sha = scan.plan(self.site, vhost_root=self.vhosts,
                                  log_dir=self.log_dir)
        with self.assertRaisesRegex(scan.AbuseError, "Start the Fail2ban daemon"):
            self.execute("apply", approved=True, expected_plan=ready_sha)
        self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
        self.assertFalse((self.data / scan._journal_name(23)).exists())

    def test_filter_covers_expected_probes_and_not_generic_paths(self):
        text = scan.FILTER_TEXT
        self.assertIn("HTTP/(?:1[.]0|1[.]1|2", text)
        self.assertIn("3(?:[.]0)?", text)
        self.assertIn(r"\[\]", text)
        self.assertNotIn(".well-known", text)
        self.assertNotIn("/oauth/", text)
        self.assertEqual(scan._policy({"maxretry": "3"})["maxretry"], 3)

    def test_crash_after_live_reload_before_applied_journal_is_recoverable(self):
        ready = self.execute("preview")
        original = scan._save
        def lose_ack(fd, site_id, row):
            if row["phase"] == "applied":
                raise OSError("simulated ack failure after live Fail2ban reload")
            return original(fd, site_id, row)
        with patch.object(scan, "_save", side_effect=lose_ack):
            with self.assertRaises(scan.AbuseError) as failure:
                self.execute("apply", approved=True,
                             expected_plan=ready["plan_sha256"])
        self.assertEqual(failure.exception.stage, "uncertain")
        self.assertRegex(failure.exception.recovery_id, r"^[a-f0-9]{32}$")
        self.assertTrue(self.live)
        with patch.object(scan, "LOG_DIR", self.log_dir):
            saved = scan._journal(self.fd, 23)
        self.assertEqual(saved["phase"], "prepared")
        recheck = self.execute("recheck")
        self.assertEqual(recheck["state"], "Recovery Required")
        self.assertEqual(recheck["journal_phase"], "prepared")
        self.assertEqual(recheck["recovery_id"], saved["recovery_id"])
        self.assertFalse(recheck["runtime_verified"])
        restored = self.execute("restore", approved=True,
                                recovery_id=saved["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(self.live)
        self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
        self.assertEqual(self.peer.read_text(), "unchanged")

    def test_deleted_site_orphan_inventory_and_exact_restore(self):
        ready = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=ready["plan_sha256"])
        self.assertTrue(self.live)
        with patch.object(scan, "LOG_DIR", self.log_dir):
            native_exists = lambda _id: False
            missing = lambda item: item == 23
            absent_list = scan.manage_orphans(
                "orphan_list", data_fd=self.fd,
                native_site_absent=native_exists, jail_dir=self.jail)
            self.assertEqual(absent_list["orphans"], [])
            listed = scan.manage_orphans(
                "orphan_list", data_fd=self.fd,
                native_site_absent=missing, jail_dir=self.jail)
            self.assertEqual(len(listed["orphans"]), 1)
            orphan = listed["orphans"][0]
            self.assertEqual(orphan["site_id"], 23)
            self.assertEqual(orphan["site_key"], "test.example")
            self.assertEqual(orphan["recovery_id"], applied["recovery_id"])
            self.assertTrue(orphan["recoverable"])
            with self.assertRaises(scan.AbuseError):
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd, native_site_absent=missing,
                    site_id=23, recovery_id=applied["recovery_id"], runner=self.runner,
                    jail_dir=self.jail, approved=False)
            with self.assertRaisesRegex(scan.AbuseError, "still exists"):
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd, native_site_absent=native_exists,
                    site_id=23, recovery_id=applied["recovery_id"], runner=self.runner,
                    jail_dir=self.jail, approved=True)
            restored = scan.manage_orphans(
                "orphan_restore", data_fd=self.fd, native_site_absent=missing,
                site_id=23, recovery_id=applied["recovery_id"], runner=self.runner,
                jail_dir=self.jail, approved=True)
            self.assertEqual(restored["state"], "Restored")
            self.assertTrue(restored["orphan_restored"])
            self.assertFalse(self.live)
            self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
            self.assertEqual(self.peer.read_text(), "unchanged")
            self.assertEqual(scan.manage_orphans(
                "orphan_list", data_fd=self.fd, native_site_absent=missing,
                jail_dir=self.jail)["orphans"], [])

    def test_deleted_site_missing_log_offline_restore_and_online_completion(self):
        preview = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=preview["plan_sha256"])
        self.log.unlink()
        self.vhost.unlink()
        (self.root / "site").rmdir()
        self.daemon = False
        # Fixture site and native log are gone; the DB callback also reports
        # the native site ID absent for both independent ownership checks.
        with patch.object(scan, "LOG_DIR", self.log_dir):
            absent = lambda site_id: site_id == 23
            inventory = scan.manage_orphans(
                "orphan_list", data_fd=self.fd,
                native_site_absent=absent, jail_dir=self.jail)
            self.assertTrue(inventory["orphans"][0]["recoverable"])
            pending = scan.manage_orphans(
                "orphan_restore", data_fd=self.fd,
                native_site_absent=absent, site_id=23,
                recovery_id=applied["recovery_id"], approved=True,
                runner=self.runner, jail_dir=self.jail)
            self.assertEqual(pending["state"], "Recovery Required")
            self.assertFalse(pending["orphan_restored"])
            self.assertFalse(pending["runtime_verified"])
            self.assertTrue(pending["changed"])
            self.assertEqual(pending["recovery_id"], applied["recovery_id"])
            self.assertEqual(pending["journal_phase"], "restore_pending")
            self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
            self.assertEqual(json.loads((self.data / scan._journal_name(23)).read_text())["phase"], "restore_pending")
            # Retry while daemon is down: no repeated write, no false success.
            second = scan.manage_orphans(
                "orphan_restore", data_fd=self.fd,
                native_site_absent=absent, site_id=23,
                recovery_id=applied["recovery_id"], approved=True,
                runner=self.runner, jail_dir=self.jail)
            self.assertFalse(second["changed"])
            self.assertEqual(second["state"], "Recovery Required")
            self.assertEqual(second["journal_phase"], "restore_pending")
            self.assertFalse(second["runtime_verified"])
            pending_list = scan.manage_orphans(
                "orphan_list", data_fd=self.fd,
                native_site_absent=absent, jail_dir=self.jail)
            self.assertEqual(pending_list["orphans"][0]["recovery_id"],
                             applied["recovery_id"])
            self.assertEqual(pending_list["orphans"][0]["journal_phase"], "restore_pending")
            self.assertTrue(pending_list["orphans"][0]["recoverable"])
            self.assertEqual(self.peer.read_text(), "unchanged")
            self.daemon = True
            complete = scan.manage_orphans(
                "orphan_restore", data_fd=self.fd,
                native_site_absent=absent, site_id=23,
                recovery_id=applied["recovery_id"], approved=True,
                runner=self.runner, jail_dir=self.jail)
        self.assertEqual(complete["state"], "Restored")
        self.assertTrue(complete["runtime_verified"])
        self.assertTrue(complete["orphan_restored"])
        self.assertEqual(complete["journal_phase"], "restored")
        self.assertEqual(json.loads((self.data / scan._journal_name(23)).read_text())["phase"], "restored")
        self.assertFalse(self.live)
        self.assertIn(["nft", "-j", "list", "sets"], self.calls)
        self.assertEqual(self.peer.read_text(), "unchanged")

    def test_offline_unlink_before_pending_checkpoint_crash_can_recover(self):
        ready = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=ready["plan_sha256"])
        self.log.unlink()
        self.daemon = False
        real_save = scan._save
        def fail_pending_commit(fd, site_id, row):
            if row["phase"] == "restore_pending":
                raise OSError("simulated fsync failure after exact owned unlink")
            return real_save(fd, site_id, row)
        with patch.object(scan, "LOG_DIR", self.log_dir), patch.object(
                scan, "_save", side_effect=fail_pending_commit):
            with self.assertRaisesRegex(scan.AbuseError, "pending recovery journal") as fail:
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd,
                    native_site_absent=lambda _: True,
                    site_id=23, recovery_id=applied["recovery_id"],
                    approved=True, runner=self.runner, jail_dir=self.jail)
            self.assertEqual(fail.exception.stage, "uncertain")
            self.assertEqual(fail.exception.recovery_id, applied["recovery_id"])
        # An old applied journal + absent source is still a durable recovery
        # handle, NOT proof of successful firewall cleanup.
        self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
        current = json.loads((self.data / scan._journal_name(23)).read_text())
        self.assertEqual(current["phase"], "applied")
        with patch.object(scan, "LOG_DIR", self.log_dir):
            rows = scan.manage_orphans(
                "orphan_list", data_fd=self.fd,
                native_site_absent=lambda _: True, jail_dir=self.jail)["orphans"]
            self.assertEqual(rows[0]["state"], "Recovery Required")
            self.assertTrue(rows[0]["recoverable"])
            self.assertEqual(rows[0]["recovery_id"], applied["recovery_id"])
            self.daemon = True
            restored = scan.manage_orphans(
                "orphan_restore", data_fd=self.fd,
                native_site_absent=lambda _: True,
                site_id=23, recovery_id=applied["recovery_id"],
                approved=True, runner=self.runner, jail_dir=self.jail)
        self.assertEqual(restored["state"], "Restored")
        self.assertTrue(restored["runtime_verified"])
        self.assertEqual(json.loads(
            (self.data / scan._journal_name(23)).read_text())["phase"], "restored")

    def test_orphan_offline_rejects_foreign_jail_and_revived_site(self):
        preview = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=preview["plan_sha256"])
        self.log.unlink()
        self.daemon = False
        jailfile = self.jail / "ach-customizer-scan-23.local"
        old = jailfile.read_bytes()
        with patch.object(scan, "LOG_DIR", self.log_dir):
            with self.assertRaisesRegex(scan.AbuseError, "still exists"):
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd,
                    native_site_absent=lambda _: False, site_id=23,
                    recovery_id=applied["recovery_id"], approved=True,
                    runner=self.runner, jail_dir=self.jail)
            with self.assertRaisesRegex(scan.AbuseError, "Recovery ID"):
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd,
                    native_site_absent=lambda _: True, site_id=23,
                    recovery_id="0"*32, approved=True,
                    runner=self.runner, jail_dir=self.jail)
            jailfile.write_bytes(b"foreign rules")
            with self.assertRaisesRegex(scan.AbuseError, "foreign"):
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd,
                    native_site_absent=lambda _: True, site_id=23,
                    recovery_id=applied["recovery_id"], approved=True,
                    runner=self.runner, jail_dir=self.jail)
            self.assertEqual(jailfile.read_bytes(), b"foreign rules")
            self.assertEqual(json.loads((self.data / scan._journal_name(23)).read_text())["phase"], "applied")
        self.assertNotEqual(old, b"foreign rules")

    def test_orphan_held_pending_for_lingering_nftables_action(self):
        preview = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=preview["plan_sha256"])
        self.nft_sets = {"addr6-set-ach-customizer-scan-23-udp",
                         "addr-set-sshd"}
        self.log.unlink()
        with patch.object(scan, "LOG_DIR", self.log_dir):
            with self.assertRaisesRegex(scan.AbuseError, "still present") as failure:
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd,
                    native_site_absent=lambda _: True, site_id=23,
                    recovery_id=applied["recovery_id"], approved=True,
                    runner=self.runner, jail_dir=self.jail)
            self.assertEqual(failure.exception.stage, "uncertain")
            self.assertEqual(failure.exception.recovery_id, applied["recovery_id"])
            self.assertEqual(json.loads((self.data / scan._journal_name(23)).read_text())["phase"], "applied")
            self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
            # A foreign sshd set does not block completion or get modified.
            self.nft_sets = {"addr-set-sshd"}
            finished = scan.manage_orphans(
                "orphan_restore", data_fd=self.fd,
                native_site_absent=lambda _: True, site_id=23,
                recovery_id=applied["recovery_id"], approved=True,
                runner=self.runner, jail_dir=self.jail)
        self.assertEqual(finished["state"], "Restored")
        self.assertEqual(self.nft_sets, {"addr-set-sshd"})
        self.assertEqual(self.peer.read_text(), "unchanged")

    def test_unverifiable_nft_inventory_does_not_complete_journal(self):
        preview = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=preview["plan_sha256"])
        self.nft_inspection_failed = True
        with self.assertRaisesRegex(scan.AbuseError, "inspection failed") as failed:
            self.execute("restore", approved=True,
                         recovery_id=applied["recovery_id"])
        self.assertEqual(failed.exception.stage, "uncertain")
        self.assertFalse((self.jail / "ach-customizer-scan-23.local").exists())
        self.assertEqual(json.loads((self.data / scan._journal_name(23)).read_text())["phase"], "applied")
        self.nft_inspection_failed = False
        ok = self.execute("restore", approved=True,
                          recovery_id=applied["recovery_id"])
        self.assertEqual(ok["state"], "Restored")

    def test_normal_site_restore_does_not_retire_jail_while_daemon_down(self):
        preview = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=preview["plan_sha256"])
        self.daemon = False
        with self.assertRaisesRegex(scan.AbuseError, "Start Fail2ban"):
            self.execute("restore", approved=True,
                         recovery_id=applied["recovery_id"])
        self.assertTrue((self.jail / "ach-customizer-scan-23.local").exists())
        self.assertEqual(json.loads((self.data / scan._journal_name(23)).read_text())["phase"], "applied")

    def test_foreign_shared_filter_does_not_block_exact_owned_restore(self):
        ready = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=ready["plan_sha256"])
        foreign_filter = self.filter / scan.FILTER_NAME
        foreign_filter.write_text("# Another administrator's altered filter\n")
        with self.assertRaisesRegex(scan.AbuseError, "Foreign"):
            self.execute("apply", approved=True,
                         expected_plan=ready["plan_sha256"])
        changed = self.execute("recheck")
        self.assertEqual(changed["state"], "Needs Review")
        self.assertEqual(changed["recovery_id"], applied["recovery_id"])
        restored = self.execute("restore", approved=True,
                                recovery_id=applied["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(foreign_filter.read_text(),
                         "# Another administrator's altered filter\n")
        self.assertEqual(self.peer.read_text(), "unchanged")

    def test_orphan_changed_jail_is_visible_but_not_removed(self):
        before = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=before["plan_sha256"])
        foreign = self.jail / "ach-customizer-scan-23.local"
        foreign.write_text("foreign system-managed jail")
        with patch.object(scan, "LOG_DIR", self.log_dir):
            entries = scan.manage_orphans(
                "orphan_list", data_fd=self.fd, native_site_absent=lambda _: True,
                jail_dir=self.jail)["orphans"]
            self.assertEqual(entries[0]["state"], "Needs Review")
            self.assertFalse(entries[0]["recoverable"])
            with self.assertRaisesRegex(scan.AbuseError, "refusing foreign"):
                scan.manage_orphans(
                    "orphan_restore", data_fd=self.fd,
                    native_site_absent=lambda _: True, site_id=23,
                    recovery_id=applied["recovery_id"], runner=self.runner,
                    jail_dir=self.jail, approved=True)
        self.assertEqual(foreign.read_text(), "foreign system-managed jail")
        self.assertEqual(self.peer.read_text(), "unchanged")

    def test_native_rename_and_log_rotation_recheck_restore(self):
        before = self.execute("preview")
        applied = self.execute("apply", approved=True,
                               expected_plan=before["plan_sha256"])
        # Normal native log reopening preserves the selected absolute
        # filename; do not bind lifecycle to a single old inode.
        self.log.rename(self.log_dir / "test.example.log.1")
        self.log.write_text("")
        self.assertEqual(self.execute("recheck")["state"], "Applied")
        self.site["name"] = "renamed.example"
        self.site["bound_domains"] = [{"name": "renamed.example", "port": 80}]
        # Its native ID still exists: not an orphan merely because the name
        # or native VHost changed. Existing journal grants exact Restore.
        with patch.object(scan, "LOG_DIR", self.log_dir):
            self.assertEqual(scan.manage_orphans(
                "orphan_list", data_fd=self.fd, native_site_absent=lambda _: False,
                jail_dir=self.jail)["orphans"], [])
        restore = self.execute("restore", approved=True,
                               recovery_id=applied["recovery_id"])
        self.assertEqual(restore["state"], "Restored")
        self.assertFalse(self.live)


if __name__ == "__main__":
    unittest.main()
