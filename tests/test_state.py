"""Behavioral tests for root-owned, code-independent Monitor state lifecycle."""

import fcntl
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

PACKAGE = Path(__file__).resolve().parent.parent / "plugin" / "ach_customizer"
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
import ach_customizer_state as state


class MonitorStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-monitor-state-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state_file = self.root / state.STATE_FILE
        self.lock_file = self.root / state.LOCK_FILE

    def test_reads_are_side_effect_free_and_default_to_monitor(self):
        snapshot = state.read_state(self.root)
        self.assertEqual(snapshot, {
            "schema_version": 1,
            "revision": 0,
            "enabled": True,
            "modules": {"site_inventory": True, "php_fpm_file_preview": True},
        })
        self.assertEqual(list(self.root.iterdir()), [])

    def test_atomic_persistence_idempotence_and_independent_module_flags(self):
        original, changed = state.set_enabled("overall", False, directory=self.root, expected_revision=0)
        self.assertTrue(changed)
        self.assertFalse(original["enabled"])
        self.assertEqual(original["revision"], 1)
        self.assertEqual(stat.S_IMODE(self.state_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.lock_file.stat().st_mode), 0o600)
        disk_bytes = self.state_file.read_bytes()
        duplicate, changed = state.set_enabled("overall", False, directory=self.root, expected_revision=1)
        self.assertFalse(changed)
        self.assertEqual(duplicate, original)
        self.assertEqual(self.state_file.read_bytes(), disk_bytes)

        updated, changed = state.set_enabled("site_inventory", False, directory=self.root, expected_revision=1)
        self.assertTrue(changed)
        self.assertEqual(updated["revision"], 2)
        self.assertFalse(updated["modules"]["site_inventory"])
        self.assertTrue(updated["modules"]["php_fpm_file_preview"])
        self.assertFalse(updated["enabled"])
        self.assertEqual(state.read_state(self.root), updated)
        self.assertEqual(sorted(file.name for file in self.root.iterdir()),
                         sorted([state.STATE_FILE, state.LOCK_FILE]))
        restored, changed = state.set_enabled("overall", True, directory=self.root, expected_revision=2)
        self.assertTrue(changed)
        self.assertTrue(restored["enabled"])
        self.assertFalse(restored["modules"]["site_inventory"])
        self.assertEqual(restored["revision"], 3)

    def test_invalid_controls_and_enabled_tokens_never_write(self):
        for control, value in [
            ("new_module", True), ("../outside", False),
            ("overall", "yes"), ("overall", "1"),
            ("overall", 1), ("site_inventory", None),
        ]:
            with self.subTest(control=control, value=value):
                with self.assertRaises(state.StateError):
                    state.set_enabled(control, value, directory=self.root, expected_revision=0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_corrupt_or_unsupported_persisted_state_fails_closed(self):
        for contents in [
            b"{", b'{}', b'{"schema_version":2}', b'\xff',
            json.dumps({
                "schema_version": 1, "revision": 1, "enabled": "false",
                "modules": {"site_inventory": True, "php_fpm_file_preview": True}
            }).encode("utf8"),
            b"x" * (state.MAX_STATE_BYTES + 1),
        ]:
            with self.subTest(data=contents[:40]):
                self.state_file.write_bytes(contents)
                self.state_file.chmod(0o600)
                with self.assertRaises(state.StateError):
                    state.read_state(self.root)
                with self.assertRaises(state.StateError):
                    state.set_enabled("overall", False, directory=self.root, expected_revision=0)
                self.assertEqual(self.state_file.read_bytes(), contents)

    def test_symlink_state_and_parent_never_follow_untrusted_location(self):
        external = self.root / "external"
        external.write_text("must survive")
        self.state_file.symlink_to(external)
        with self.assertRaises(state.StateError):
            state.read_state(self.root)
        with self.assertRaises(state.StateError):
            state.set_enabled("overall", False, directory=self.root, expected_revision=0)
        self.assertEqual(external.read_text(), "must survive")
        self.state_file.unlink()
        redirected = self.root.parent / (self.root.name + "-link")
        self.addCleanup(lambda: redirected.unlink(missing_ok=True))
        redirected.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            state.read_state(redirected)

    def test_hardlink_and_permissive_state_files_refused(self):
        external = self.root / "external"
        external.write_text("preserve")
        os.link(external, self.state_file)
        with self.assertRaises(state.StateError):
            state.read_state(self.root)
        self.state_file.unlink()
        self.state_file.write_text("{}")
        self.state_file.chmod(0o644)
        with self.assertRaises(state.StateError):
            state.read_state(self.root)
        self.assertEqual(external.read_text(), "preserve")

    def test_busy_writer_fails_closed_without_mutation(self):
        lock_fd = os.open(self.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(state, "LOCK_TIMEOUT_SECONDS", 0.08):
                with self.assertRaisesRegex(state.StateError, "busy"):
                    state.set_enabled("overall", False, directory=self.root, expected_revision=0)
            self.assertFalse(self.state_file.exists())
        finally:
            os.close(lock_fd)

    def test_default_flag_recovery_after_code_replacement(self):
        # The code directory is not part of the state path. A new instance
        # reads and updates exactly the state saved by the earlier instance.
        first, _ = state.set_enabled("php_fpm_file_preview", False, directory=self.root, expected_revision=0)
        after_simulated_reinstall = state.read_state(str(self.root))
        self.assertEqual(first, after_simulated_reinstall)
        self.assertFalse(after_simulated_reinstall["modules"]["php_fpm_file_preview"])
        self.assertEqual(len(list(self.root.glob("*.tmp"))), 0)


    def test_concurrent_revision_conflict_cannot_silently_overwrite(self):
        first, changed = state.set_enabled(
            "overall", False, directory=self.root, expected_revision="0"
        )
        self.assertTrue(changed)
        self.assertEqual(first["revision"], 1)
        with self.assertRaisesRegex(state.StateError, "revision changed"):
            state.set_enabled("overall", True, directory=self.root, expected_revision=0)
        with self.assertRaisesRegex(state.StateError, "revision changed"):
            state.set_enabled("overall", False, directory=self.root, expected_revision=0)
        self.assertEqual(state.read_state(self.root), first)
        current, changed = state.set_enabled(
            "overall", True, directory=self.root, expected_revision="1"
        )
        self.assertTrue(changed)
        self.assertEqual(current["revision"], 2)
        self.assertTrue(current["enabled"])

    def test_invalid_optimistic_revisions_cannot_write_or_create_locks(self):
        for revision in (None, -1, True, False, "01", "1.0", "", "+1", " 1", 1.5,
                         {}, [], "99999999999999999999999", 2147483648):
            with self.subTest(revision=revision):
                with self.assertRaises(state.StateError):
                    state.set_enabled(
                        "overall", False, directory=self.root,
                        expected_revision=revision
                    )
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
