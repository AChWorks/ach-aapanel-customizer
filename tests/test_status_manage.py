"""Isolated, non-privileged file-only 404 transaction and fault recovery tests."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_status_manage as manager
from ach_customizer_status_inspect import inspect_site_files
from ach_customizer_status_pages import render_page


class Site404TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-status-manage-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.site_root = self.root / "sites" / "demo.test"
        self.site_root.mkdir(parents=True)
        self.other_root = self.root / "sites" / "other.test"
        self.other_root.mkdir()
        self.other_file = self.other_root / "404.html"
        self.other_file.write_bytes(b"other untouched site")
        self.page = self.site_root / "404.html"
        self.original = b"<html>Operator-owned existing 404</html>\n"
        self.page.write_bytes(self.original)
        self.page.chmod(0o644)
        self.vhosts = self.root / "nginx"
        self.vhosts.mkdir()
        self.vhost = self.vhosts / "demo.test.conf"
        self.vhost.write_text("server { listen 80; server_name demo.test;\n"
                              "error_page 404 /404.html;\n}\n")
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.fd = os.open(str(self.state), os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.site = {
            "id": 9, "name": "demo.test", "path": str(self.site_root),
            "status": "1", "bound_domains": [{"name": "demo.test", "port": 80}],
        }
        self.render = render_page("en", "404")
        self.sha = self.render["rendered_sha256"]
        self.probes = 0
        self.fail_probe_numbers = set()
        self.vhost_sha = hashlib.sha256(self.vhost.read_bytes()).hexdigest()
        self.before_sha = hashlib.sha256(self.original).hexdigest()

    def fake_probe(self, site, *, locale, rendered_sha256, rendered_html, vhost_root):
        self.probes += 1
        inspection = inspect_site_files(
            site, locale=locale, template="404",
            rendered_sha256=rendered_sha256, rendered_html=rendered_html,
            vhost_root=vhost_root, source_fingerprint=True)
        data = self.page.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        matching = self.probes not in self.fail_probe_numbers
        return {
            "state": "HTTP Match" if matching else "HTTP Mismatch",
            "http_status": 404, "body_sha256": sha if matching else "0" * 64,
            "body_matches_file": matching,
            "adoption_preview": {
                "route_source_state": inspection["route_source_state"],
                "current_sha256": inspection["page_file_sha256"],
                "proposed_sha256": rendered_sha256,
                "vhost_sha256": inspection["vhost_sha256"],
                "apply_supported": False,
            },
        }

    def run_manager(self, action="apply", **options):
        return manager.manage_site_404(
            action, self.site, locale="en", html=self.render["html"],
            expected_current=options.get("expected_current", self.before_sha),
            expected_vhost=options.get("expected_vhost", self.vhost_sha),
            expected_render=options.get("expected_render", self.sha),
            expected_recovery=options.get("expected_recovery"),
            data_fd=self.fd, vhost_root=str(self.vhosts), probe=self.fake_probe,
            site_root_prefix=str(self.root) + "/",
        )

    def recovery(self):
        journal = self.state / "ach_customizer.site404.9.json"
        return json.loads(journal.read_text()) if journal.exists() else None

    def test_apply_recheck_idempotence_restore_and_preserve_other_site(self):
        self.assertEqual(self.run_manager("recheck")["state"], "Unmanaged")
        r = self.run_manager()
        self.assertEqual(r["state"], "Applied")
        self.assertTrue(r["changed"])
        self.assertEqual(self.page.read_bytes(), self.render["html"].encode())
        self.assertEqual(self.page.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.recovery()["phase"], "applied")
        self.assertEqual(self.run_manager("recheck")["state"], "Applied")
        self.assertEqual(self.run_manager(expected_current=self.sha)["state"], "Already Applied")
        restored = self.run_manager("restore", expected_recovery=r["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertTrue(restored["changed"])
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertEqual(self.run_manager("recheck")["state"], "Restored")
        self.assertEqual(self.run_manager("restore", expected_recovery=r["recovery_id"])["state"],
                         "Already Restored")
        self.assertEqual(self.other_file.read_bytes(), b"other untouched site")
        self.assertEqual(self.recovery()["phase"], "restored")
        self.assertEqual((self.state / "ach_customizer.site404.9.before").read_bytes(),
                         self.original)

    def test_stale_preflight_never_creates_backup(self):
        for options in ({"expected_current": "0" * 64},
                        {"expected_vhost": "1" * 64},
                        {"expected_render": "2" * 64}):
            with self.subTest(options=options), self.assertRaises(manager.StatusManageError):
                self.run_manager(**options)
        self.assertIsNone(self.recovery())
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_unrelated_vhost_and_unproven_http_cannot_authorize_write(self):
        self.vhost.write_text("server { error_page 404 /different.html; }\n")
        with self.assertRaises(manager.StatusManageError) as ctx:
            self.run_manager(expected_vhost=hashlib.sha256(self.vhost.read_bytes()).hexdigest())
        self.assertEqual(ctx.exception.stage, "runtime")
        self.assertIsNone(self.recovery())
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_missing_symlink_and_unexpected_permissions_are_ineligible(self):
        self.page.chmod(0o666)
        with self.assertRaises(manager.StatusManageError):
            self.run_manager()
        self.page.chmod(0o644)
        self.page.unlink()
        self.page.symlink_to(self.other_file)
        with self.assertRaises(Exception):
            self.run_manager()
        self.page.unlink()
        with self.assertRaises(manager.StatusManageError):
            self.run_manager()
        self.assertIsNone(self.recovery())

    def test_failed_postcheck_rolls_back_original_bytes_and_http(self):
        self.fail_probe_numbers = {2}
        with self.assertRaises(manager.StatusManageError) as ctx:
            self.run_manager()
        self.assertEqual(ctx.exception.stage, "recovered")
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertEqual(self.recovery()["phase"], "restored")
        self.assertEqual(self.other_file.read_bytes(), b"other untouched site")

    def test_uncertain_postcheck_preserves_prepared_journal_for_later_restore(self):
        self.fail_probe_numbers = {2, 3}
        with self.assertRaises(manager.StatusManageError) as ctx:
            self.run_manager()
        self.assertEqual(ctx.exception.stage, "uncertain")
        self.assertEqual(self.recovery()["phase"], "prepared")
        # Auto rollback did restore file, but HTTP evidence was unavailable.
        self.assertEqual(self.page.read_bytes(), self.original)
        self.fail_probe_numbers = set()
        r = self.run_manager("restore", expected_recovery=self.recovery()["operation_id"])
        self.assertEqual(r["state"], "Restored")
        self.assertFalse(r["changed"])
        self.assertEqual(self.recovery()["phase"], "restored")

    def test_external_edited_file_blocks_restore_and_reapply(self):
        result = self.run_manager()
        self.page.write_bytes(b"manual third-party update")
        self.assertEqual(self.run_manager("recheck")["state"], "Drift")
        with self.assertRaises(manager.StatusManageError):
            self.run_manager("restore", expected_recovery=result["recovery_id"])
        with self.assertRaises(manager.StatusManageError):
            self.run_manager(expected_current=hashlib.sha256(self.page.read_bytes()).hexdigest())
        self.assertEqual(self.page.read_bytes(), b"manual third-party update")
        self.assertEqual(self.recovery()["phase"], "applied")

    def test_restore_rejects_wrong_recovery_id_and_rebound_website(self):
        result = self.run_manager()
        with self.assertRaises(manager.StatusManageError) as ctx:
            self.run_manager("restore", expected_recovery="0" * 32)
        self.assertEqual(ctx.exception.stage, "concurrency")
        self.site["name"] = "renamed.test"
        with self.assertRaises(manager.StatusManageError) as ctx:
            self.run_manager("restore", expected_recovery=result["recovery_id"])
        self.assertEqual(ctx.exception.stage, "identity")
        self.assertEqual(self.recovery()["phase"], "applied")

    def test_interrupted_write_preserves_recovery_and_refuses_blind_retry(self):
        with patch.object(manager, "_replace_site", side_effect=OSError("simulated disk fault")):
            with self.assertRaises(manager.StatusManageError) as ctx:
                self.run_manager()
        self.assertEqual(ctx.exception.stage, "recovered")
        self.assertEqual(self.recovery()["phase"], "restored")
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_file_permission_change_during_probe_fails_before_recovery_write(self):
        original = self.fake_probe
        def intervening_chmod(*args, **kwargs):
            result = original(*args, **kwargs)
            self.page.chmod(0o664)
            return result
        with patch.object(self, "fake_probe", side_effect=intervening_chmod):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "ownership")
        self.assertIsNone(self.recovery())
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_final_recovery_journal_failure_never_claims_apply_success(self):
        previous_save = manager._save_journal
        stages = []
        def injected_save(fd, site_id, record):
            stages.append(record["phase"])
            if record["phase"] == "applied":
                raise OSError("final fsync not acknowledged")
            return previous_save(fd, site_id, record)
        with patch.object(manager, "_save_journal", side_effect=injected_save):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(stages, ["prepared", "applied"])
        self.assertEqual(self.recovery()["phase"], "prepared")
        self.assertEqual(self.page.read_bytes(), self.render["html"].encode())
        rechecked = self.run_manager("recheck")
        self.assertEqual(rechecked["state"], "Recovery Required")
        restored = self.run_manager(
            "restore", expected_recovery=rechecked["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertEqual(self.recovery()["phase"], "restored")

    def test_restore_http_fault_rechecks_as_recovery_required_then_recovers(self):
        applied = self.run_manager()
        self.fail_probe_numbers = {4}
        with self.assertRaises(manager.StatusManageError) as error:
            self.run_manager("restore", expected_recovery=applied["recovery_id"])
        self.assertEqual(error.exception.stage, "postcheck")
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertEqual(self.recovery()["phase"], "applied")
        # The original site bytes were restored, but successful HTTP wasn't
        # observed. Never claim 'Drift' that blocks explicit recovery.
        rechecked = self.run_manager("recheck")
        self.assertEqual(rechecked["state"], "Recovery Required")
        self.fail_probe_numbers = set()
        recovered = self.run_manager(
            "restore", expected_recovery=rechecked["recovery_id"])
        self.assertEqual(recovered["state"], "Restored")
        self.assertFalse(recovered["changed"])
        self.assertEqual(self.recovery()["phase"], "restored")

    def test_vhost_source_drift_blocks_restore_and_does_not_overwrite(self):
        applied = self.run_manager()
        self.vhost.write_text("server { listen 80; server_name demo.test;\n"
                              "error_page 404 /404.html;\n# third-party edit\n}\n")
        review = self.run_manager("recheck")
        self.assertNotEqual(review["state"], "Applied")
        with self.assertRaises(manager.StatusManageError) as error:
            self.run_manager(
                "restore", expected_recovery=applied["recovery_id"])
        self.assertEqual(error.exception.stage, "runtime")
        self.assertEqual(self.page.read_bytes(), self.render["html"].encode())
        self.assertEqual(self.recovery()["phase"], "applied")

    def test_external_file_rewrite_during_probe_stops_before_backup(self):
        original = self.fake_probe
        def concurrently_changed(*args, **kwargs):
            observed = original(*args, **kwargs)
            self.page.write_bytes(b"new third-party bytes")
            return observed
        with patch.object(self, "fake_probe", side_effect=concurrently_changed):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "concurrency")
        self.assertEqual(self.page.read_bytes(), b"new third-party bytes")
        self.assertIsNone(self.recovery())

    def test_target_root_is_not_user_controlled(self):
        with self.assertRaises(manager.StatusManageError):
            manager.manage_site_404(
                "apply", self.site, locale="en", html=self.render["html"],
                data_fd=self.fd, vhost_root=str(self.vhosts), probe=self.fake_probe,
            )
        self.assertIsNone(self.recovery())


if __name__ == "__main__":
    unittest.main()
