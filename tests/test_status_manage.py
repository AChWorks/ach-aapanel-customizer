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
        self.route_guard = patch.object(
            manager, "verify_configured_site_404",
            side_effect=lambda site, **kwargs: {
                "configured_static_http_80": True,
                "loaded_workers_verified": False,
                "nginx_dump_sha256": "a" * 64,
                "vhost_sha256": hashlib.sha256(self.vhost.read_bytes()).hexdigest(),
            })
        self.route_guard.start()
        self.addCleanup(self.route_guard.stop)
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

    def test_atomic_backup_publication_failure_matrix_preserves_404(self):
        # No fault before or at the final no-clobber rename may publish a
        # partially written original-byte backup.
        original_create = manager._create_data
        def truncated_temp(fd, name, content):
            if ".before." not in name:
                return original_create(fd, name, content)
            descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                 0o600, dir_fd=fd)
            try:
                os.write(descriptor, content[:7])
            finally:
                os.close(descriptor)
            raise OSError("injected interrupted byte write")
        with patch.object(manager, "_create_data", side_effect=truncated_temp):
            with self.assertRaisesRegex(manager.StatusManageError, "backup publication failed"):
                self.run_manager()
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertFalse((self.state / "ach_customizer.site404.9.before").exists())
        self.assertFalse(list(self.state.glob(".*.before.*.tmp")))

        with patch.object(manager, "_rename_noreplace",
                          side_effect=FileExistsError("other backup writer")):
            with self.assertRaisesRegex(manager.StatusManageError, "backup publication failed"):
                self.run_manager()
        self.assertFalse((self.state / "ach_customizer.site404.9.before").exists())
        self.assertFalse(list(self.state.glob(".*.before.*.tmp")))
        self.assertEqual(self.page.read_bytes(), self.original)

        actual_fsync = manager.os.fsync
        def fail_initial(fd):
            raise OSError("backup file fsync interruption")
        with patch.object(manager.os, "fsync", side_effect=fail_initial):
            with self.assertRaisesRegex(manager.StatusManageError, "backup publication failed"):
                self.run_manager()
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertFalse((self.state / "ach_customizer.site404.9.before").exists())
        self.assertFalse(list(self.state.glob(".*.before.*.tmp")))

    def test_backup_directory_fsync_uncertainty_is_complete_orphan(self):
        actual = manager.os.fsync
        counter = 0
        def uncertain_parent(fd):
            nonlocal counter
            counter += 1
            if counter == 3:
                raise OSError("post-publication fsync not acknowledged")
            return actual(fd)
        with patch.object(manager.os, "fsync", side_effect=uncertain_parent):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "backup_uncertain")
        self.assertIsNone(self.recovery())
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertEqual((self.state / "ach_customizer.site404.9.before").read_bytes(),
                         self.original)
        self.assertEqual(self.run_manager("recheck")["state"], "Orphan Backup")
        self.assertFalse(list(self.state.glob(".*.before.*.tmp")))

    def test_initial_journal_fsync_failures_never_write_site(self):
        # The original-byte backup is already complete at the journal
        # boundary. A prepared record may or may not be durably published.
        actual = manager.os.fsync
        for stage in (4, 6):
            with self.subTest(initial_journal_fsync_number=stage):
                count = 0
                def fail_at_journal(fd):
                    nonlocal count
                    count += 1
                    if count == stage:
                        raise OSError("prepared journal interruption")
                    return actual(fd)
                with patch.object(manager.os, "fsync", side_effect=fail_at_journal):
                    with self.assertRaises(manager.StatusManageError) as ctx:
                        self.run_manager()
                self.assertEqual(ctx.exception.stage, "journal_prepared")
                self.assertEqual(self.page.read_bytes(), self.original)
                self.assertEqual(
                    (self.state / "ach_customizer.site404.9.before").read_bytes(),
                    self.original)
                rechecked = self.run_manager("recheck")
                self.assertIn(rechecked["state"], ("Orphan Backup", "Recovery Required"))
                self.assertEqual(self.page.read_bytes(), self.original)
                # Restore test fixture for next subcase without overwriting a
                # live website or pretending uncertain durable record success.
                journal = self.state / "ach_customizer.site404.9.json"
                if journal.exists():
                    journal.unlink()
                self.assertEqual(self.run_manager("recheck")["state"], "Orphan Backup")
                # This is a disposable fixture; reset the intact original
                # state to give the next case all backup/journal fsync steps.
                (self.state / "ach_customizer.site404.9.before").unlink()
                self.assertEqual(self.run_manager("recheck")["state"], "Unmanaged")

    def test_exact_404_http_match_without_route_evidence_cannot_write(self):
        # The historic fake HTTP matcher is insufficient by itself. A
        # separately proven configured Nginx scope is mandatory.
        import ach_customizer_status_routing as route
        with patch.object(manager, "verify_configured_site_404",
                          side_effect=route.RouteGuardError("unsupported nested includes")):
            with self.assertRaises(manager.StatusManageError) as ctx:
                self.run_manager()
        self.assertEqual(ctx.exception.stage, "runtime")
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertIsNone(self.recovery())
        self.assertFalse((self.state / "ach_customizer.site404.9.before").exists())

    def test_nginx_dump_drift_during_matching_http_probe_refuses_apply(self):
        common = {
            "configured_static_http_80": True,
            "loaded_workers_verified": False,
            "vhost_sha256": self.vhost_sha,
        }
        with patch.object(manager, "verify_configured_site_404", side_effect=[
                dict(common, nginx_dump_sha256="a" * 64),
                dict(common, nginx_dump_sha256="b" * 64)]):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "runtime")
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertIsNone(self.recovery())
        self.assertFalse((self.state / "ach_customizer.site404.9.before").exists())

    def test_exchange_failure_before_swap_rechecks_and_restores_original(self):
        # Kernel exchange unavailable or failed before doing anything: leave
        # private staged proposed bytes, require explicit recovery, never
        # invent a successful Apply.
        with patch.object(manager, "_exchange_site_with_stage",
                          side_effect=OSError("failed before exchange")):
            with self.assertRaises(manager.StatusManageError) as ctx:
                self.run_manager()
        self.assertEqual(ctx.exception.stage, "uncertain")
        self.assertEqual(self.page.read_bytes(), self.original)
        record = self.recovery()
        staged = self.site_root / manager.STAGING_DIRECTORY / manager._staging_name(
            record["operation_id"], "apply")
        self.assertEqual(staged.read_bytes(), self.render["html"].encode())
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        restored = self.run_manager("restore", expected_recovery=record["operation_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(restored["changed"])
        self.assertFalse(staged.exists())
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_exchange_preserves_independent_editor_replacement_between_checks(self):
        # An uncooperative editor atomically replaces the destination at the
        # precise last kernel operation, AFTER our final digest/inode checks.
        original_exchange = manager._exchange_site_with_stage
        outsider = b"independent editor's latest 404 bytes\n"
        swaps = 0

        def intervening_exchange(stage_fd, stage_name, site_fd):
            nonlocal swaps
            swaps += 1
            if swaps == 1:
                replacement = self.site_root / "third-party-new.html"
                replacement.write_bytes(outsider)
                replacement.chmod(0o644)
                os.replace(replacement, self.page)
            return original_exchange(stage_fd, stage_name, site_fd)

        with patch.object(manager, "_exchange_site_with_stage",
                          side_effect=intervening_exchange):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        # The editor's bytes are back at their original filename. A previous
        # os.replace-only implementation silently overwrote these bytes.
        self.assertIn(error.exception.stage, ("uncertain", "concurrency"))
        self.assertGreaterEqual(swaps, 2)
        self.assertEqual(self.page.read_bytes(), outsider)
        self.assertEqual(self.recovery()["phase"], "prepared")
        self.assertEqual((self.state / "ach_customizer.site404.9.before").read_bytes(),
                         self.original)
        self.assertEqual(self.run_manager("recheck")["state"], "Drift")

    def test_exchange_preserves_third_party_update_after_swap(self):
        original_exchange = manager._exchange_site_with_stage
        outsider = b"new site bytes after exchange\n"
        count = 0

        def edit_installed_after_exchange(stage_fd, stage_name, site_fd):
            nonlocal count
            original_exchange(stage_fd, stage_name, site_fd)
            count += 1
            if count == 1:
                replacement = self.site_root / "independent.tmp"
                replacement.write_bytes(outsider)
                replacement.chmod(0o644)
                os.replace(replacement, self.page)

        with patch.object(manager, "_exchange_site_with_stage",
                          side_effect=edit_installed_after_exchange):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(self.page.read_bytes(), outsider)
        recovery = self.recovery()
        staged_name = manager._staging_name(recovery["operation_id"], "apply")
        displaced = self.site_root / manager.STAGING_DIRECTORY / staged_name
        self.assertTrue(displaced.exists(), "Retain displaced original inode")
        self.assertEqual(displaced.read_bytes(), self.original)
        self.assertEqual(self.run_manager("recheck")["state"], "Drift")
        with self.assertRaisesRegex(manager.StatusManageError, "recoverable Apply exchange"):
            self.run_manager("restore", expected_recovery=recovery["operation_id"])

    def test_exchange_lost_acknowledgment_does_not_discard_displaced_inode(self):
        # Simulate a syscall that changed the directory but whose result was
        # lost before userspace could acknowledge the swap.
        original_exchange = manager._exchange_site_with_stage

        def swap_then_lose_reply(stage_fd, stage_name, site_fd):
            original_exchange(stage_fd, stage_name, site_fd)
            raise OSError("simulated lost exchange acknowledgment")

        with patch.object(manager, "_exchange_site_with_stage",
                          side_effect=swap_then_lose_reply):
            with self.assertRaises(manager.StatusManageError) as error:
                self.run_manager()
        self.assertEqual(error.exception.stage, "uncertain")
        recovery = self.recovery()
        staged_name = manager._staging_name(recovery["operation_id"], "apply")
        displaced = self.site_root / manager.STAGING_DIRECTORY / staged_name
        self.assertEqual(displaced.read_bytes(), self.original)
        self.assertEqual(self.page.read_bytes(), self.render["html"].encode())
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        restored = self.run_manager("restore", expected_recovery=recovery["operation_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertFalse(displaced.exists())
        self.assertEqual(self.recovery()["phase"], "restored")
        self.assertEqual(self.run_manager("recheck")["state"], "Restored")

    def test_private_stage_directory_must_not_be_a_symlink(self):
        alien = self.other_root
        (self.site_root / manager.STAGING_DIRECTORY).symlink_to(alien, target_is_directory=True)
        with self.assertRaises(Exception):
            self.run_manager()
        self.assertEqual(self.page.read_bytes(), self.original)
        self.assertEqual(self.other_file.read_bytes(), b"other untouched site")
        self.assertEqual(self.recovery()["phase"], "restored")

    def test_private_stage_is_not_traversable_to_web_workers(self):
        done = self.run_manager()
        self.assertEqual(done["state"], "Applied")
        staging = self.site_root / manager.STAGING_DIRECTORY
        self.assertEqual(staging.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(staging.iterdir()), [])
        self.assertTrue(self.other_file.exists())

    def test_backup_no_clobber_preserves_existing_bytes(self):
        permanent = "backup-preserved"
        temporary = "complete-temp"
        (self.state / permanent).write_bytes(b"Existing original")
        (self.state / temporary).write_bytes(b"New original")
        with self.assertRaises(FileExistsError):
            manager._rename_noreplace(self.fd, temporary, permanent)
        self.assertEqual((self.state / permanent).read_bytes(), b"Existing original")
        self.assertEqual((self.state / temporary).read_bytes(), b"New original")

    def test_noop_apply_requires_journal_vhost_provenance(self):
        first = self.run_manager()
        self.vhost.write_text(self.vhost.read_text() +
                              "# independent VHost regeneration without 404 change\n")
        newer = hashlib.sha256(self.vhost.read_bytes()).hexdigest()
        self.assertNotEqual(self.vhost_sha, newer)
        with self.assertRaises(manager.StatusManageError) as ctx:
            self.run_manager(expected_current=self.sha, expected_vhost=newer)
        self.assertEqual(ctx.exception.stage, "recovery")
        self.assertEqual(self.recovery()["operation_id"], first["recovery_id"])
        self.assertEqual(self.page.read_bytes(), self.render["html"].encode())
        self.assertEqual(self.recovery()["source_vhost_sha256"], self.vhost_sha)

    def test_orphaned_backup_after_prepared_journal_fault_can_resume_only_with_fresh_apply_proof(self):
        # A successful durable backup followed by a failed initial journal
        # write leaves the site's original bytes untouched. A later explicit
        # approved Apply with full new HTTP/source preflight should reuse the
        # *exact same* backup, not overwrite it or require manual deletion.
        original = self.original
        with patch.object(manager, "_save_journal",
                          side_effect=OSError("prepared journal not saved")):
            with self.assertRaisesRegex(manager.StatusManageError, "recovery journal not confirmed"):
                self.run_manager()
        self.assertIsNone(self.recovery())
        backup = self.state / "ach_customizer.site404.9.before"
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(self.page.read_bytes(), original)
        orphan = self.run_manager("recheck")
        self.assertEqual(orphan["state"], "Orphan Backup")
        self.assertEqual(orphan["before_sha256"], self.before_sha)
        self.assertIsNone(orphan["recovery_id"])
        self.assertIsNone(orphan["after_sha256"])
        applied = self.run_manager("apply")
        self.assertEqual(applied["state"], "Applied")
        self.assertTrue(applied["changed"])
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(self.recovery()["phase"], "applied")
        restored = self.run_manager("restore", expected_recovery=applied["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.page.read_bytes(), original)

    def test_orphaned_backup_with_drift_or_without_fresh_proof_refuses_write(self):
        with patch.object(manager, "_save_journal",
                          side_effect=OSError("prepared journal not saved")):
            with self.assertRaisesRegex(manager.StatusManageError, "recovery journal not confirmed"):
                self.run_manager()
        backup = self.state / "ach_customizer.site404.9.before"
        saved_backup = backup.read_bytes()
        self.page.write_bytes(b"Third-party content after crash")
        orphan = self.run_manager("recheck")
        self.assertEqual(orphan["state"], "Orphan Drift")
        self.assertIsNone(orphan["recovery_id"])
        with self.assertRaises(manager.StatusManageError) as error:
            self.run_manager(expected_current=hashlib.sha256(self.page.read_bytes()).hexdigest())
        self.assertEqual(error.exception.stage, "recovery")
        self.assertEqual(self.page.read_bytes(), b"Third-party content after crash")
        self.assertEqual(backup.read_bytes(), saved_backup)
        self.assertIsNone(self.recovery())
        self.page.write_bytes(self.original)
        self.fail_probe_numbers = {1}
        self.probes = 0
        with self.assertRaises(manager.StatusManageError):
            self.run_manager()
        self.assertEqual(backup.read_bytes(), saved_backup)
        self.assertIsNone(self.recovery())
        self.fail_probe_numbers = set()
        with self.assertRaises(manager.StatusManageError):
            self.run_manager("restore", expected_recovery="a" * 32)
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_orphan_retry_cannot_mutate_site_if_new_prepared_journal_also_fails(self):
        with patch.object(manager, "_save_journal",
                          side_effect=OSError("no prepared journal persisted")):
            for _ in range(2):
                with self.assertRaisesRegex(manager.StatusManageError, "recovery journal not confirmed"):
                    self.run_manager()
                self.assertEqual(self.page.read_bytes(), self.original)
                self.assertIsNone(self.recovery())
        self.assertEqual(self.run_manager("recheck")["state"], "Orphan Backup")
        self.assertEqual((self.state / "ach_customizer.site404.9.before").read_bytes(),
                         self.original)

    def test_orphan_matching_selected_render_does_not_discard_backup_without_journal(self):
        with patch.object(manager, "_save_journal",
                          side_effect=OSError("prepared write failed")):
            with self.assertRaisesRegex(manager.StatusManageError, "recovery journal not confirmed"):
                self.run_manager()
        # User changes the selected brand so the newly rendered 404 equals
        # the saved existing page. There is no durable transaction to claim.
        with self.assertRaises(manager.StatusManageError) as error:
            manager.manage_site_404(
                "apply", self.site, locale="en", html=self.original.decode(),
                expected_current=self.before_sha, expected_vhost=self.vhost_sha,
                expected_render=self.before_sha, data_fd=self.fd,
                vhost_root=str(self.vhosts), probe=self.fake_probe,
                site_root_prefix=str(self.root) + "/")
        self.assertEqual(error.exception.stage, "recovery")
        self.assertIsNone(self.recovery())
        self.assertEqual((self.state / "ach_customizer.site404.9.before").read_bytes(),
                         self.original)
        self.assertEqual(self.page.read_bytes(), self.original)

    def test_prepared_journal_with_third_party_drift_is_drift_not_recovery_ready(self):
        previous_save = manager._save_journal
        def fault(fd, site_id, record):
            if record["phase"] == "applied":
                raise OSError("final journal not persisted")
            return previous_save(fd, site_id, record)
        with patch.object(manager, "_save_journal", side_effect=fault):
            with self.assertRaises(manager.StatusManageError):
                self.run_manager()
        self.assertEqual(self.recovery()["phase"], "prepared")
        self.page.write_bytes(b"<html>Independent operator change</html>")
        recheck = self.run_manager("recheck")
        self.assertEqual(recheck["state"], "Drift")
        self.assertEqual(self.page.read_bytes(),
                         b"<html>Independent operator change</html>")

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
