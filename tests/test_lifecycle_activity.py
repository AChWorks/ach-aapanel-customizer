"""Native lifecycle event contracts without privileged or Production paths."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parent.parent / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_activity as activity
import ach_customizer_lifecycle as lifecycle
import ach_customizer_state as state


class LifecycleActivityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-lifecycle-")
        self.addCleanup(temp.cleanup)
        self.directory = temp.name
        level = patch.dict(os.environ, {"ACH_CUSTOMIZER_ACTIVITY_LEVEL": "DEBUG"})
        level.start()
        self.addCleanup(level.stop)

    def test_reinstall_and_uninstall_events_are_durable_bounded_and_separate_from_operator_state(self):
        persistent = Path(self.directory) / "operator-recovery.json"
        persistent.write_bytes(b"EXISTING-RECOVERY-DO-NOT-DELETE")
        original = persistent.read_bytes()
        sequence = (
            ("install_registered", "install", "install_hook", "registered", "INFO", ""),
            ("install_registered", "install", "install_hook", "registered", "INFO", ""),
            ("uninstall_icon_removed", "uninstall", "icon_cleanup", "removed", "INFO", ""),
            ("uninstall_icon_preserved", "uninstall", "icon_cleanup", "preserved", "WARNING", "IconCleanupFailed"),
            ("uninstall_cleanup_unavailable", "uninstall", "icon_cleanup", "unavailable", "WARNING", "IconCleanupUnavailable"),
        )
        for event, _, _, _, _, _ in sequence:
            entry, saved = lifecycle.record_lifecycle(event, directory=self.directory)
            self.assertIs(saved, True)
            self.assertEqual(len(entry["operation_id"]), 32)
        events = list(reversed(activity.read_activity(self.directory, module="lifecycle")))
        self.assertEqual(len(events), len(sequence))
        self.assertEqual(len({entry["operation_id"] for entry in events}), len(sequence))
        for entry, (_, action, stage, outcome, level, error_class) in zip(events, sequence):
            self.assertEqual((entry["module"], entry["action"], entry["stage"],
                              entry["outcome"], entry["level"], entry["error_class"]),
                             ("lifecycle", action, stage, outcome, level, error_class))
            self.assertEqual(entry["target"], "ach_customizer")
        self.assertEqual(persistent.read_bytes(), original)
        self.assertEqual((Path(self.directory) / activity.LOG_NAME).stat().st_mode & 0o777, 0o600)

    def test_reject_unknown_lifecycle_event_without_file_creation(self):
        with self.assertRaises(ValueError):
            lifecycle.record_lifecycle("arbitrary_destroy", directory=self.directory)
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(lifecycle.main(["uninstall", "dangerous-extra"]), 2)
        self.assertIn("invalid lifecycle", errors.getvalue())
        self.assertEqual(list(Path(self.directory).iterdir()), [])

    def test_errors_are_explicit_and_never_include_privileged_exception_message(self):
        with patch.object(lifecycle, "record_lifecycle", side_effect=OSError("SYNTHETIC-SECRET")):
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(lifecycle.main(["install_registered"]), 1)
        self.assertIn("persistence unconfirmed", errors.getvalue())
        self.assertNotIn("SYNTHETIC-SECRET", errors.getvalue())

    def test_directory_symlink_does_not_write_external_activity(self):
        with tempfile.TemporaryDirectory(prefix="ach-lifecycle-outside-") as outside:
            marker = Path(outside) / "marker"
            marker.write_text("UNCHANGED")
            link = Path(self.directory) / "link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(activity.ActivityError):
                lifecycle.record_lifecycle("uninstall_icon_preserved", directory=str(link))
            self.assertEqual(marker.read_text(), "UNCHANGED")
            self.assertEqual(sorted(x.name for x in Path(outside).iterdir()), ["marker"])

    def test_log_level_filters_without_false_persistence_failure(self):
        with patch.dict(os.environ, {"ACH_CUSTOMIZER_ACTIVITY_LEVEL": "ERROR"}):
            entry, persisted = lifecycle.record_lifecycle(
                "install_registered", directory=self.directory)
        self.assertEqual(entry["level"], "INFO")
        self.assertIsNone(persisted)
        self.assertEqual(activity.read_activity(self.directory), [])

    def test_uninstall_does_not_mutate_monitor_state(self):
        state.set_enabled("overall", False, directory=self.directory, expected_revision=0)
        before = (Path(self.directory) / state.STATE_FILE).read_bytes()
        lifecycle.record_lifecycle("uninstall_icon_removed", directory=self.directory)
        self.assertEqual((Path(self.directory) / state.STATE_FILE).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
