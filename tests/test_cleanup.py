"""Regression for native aaPanel icon ownership, without privileged paths."""
import importlib.util
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "plugin" / "ach_customizer"
SPEC = importlib.util.spec_from_file_location("ach_customizer_cleanup", PACKAGE / "ach_customizer_cleanup.py")
CLEANUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEANUP)


class IconRemovalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ach-owned-icon-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.panel = self.root / "panel"
        self.source_parent = self.panel / "plugin" / "ach_customizer"
        self.target_parent = self.panel / "BTPanel" / "static" / "img" / "soft_ico"
        self.source_parent.mkdir(parents=True)
        self.target_parent.mkdir(parents=True)
        self.source = self.source_parent / "icon.png"
        self.target = self.target_parent / "ico-ach_customizer.png"
        self.contents = (PACKAGE / "icon.png").read_bytes()
        self.source.write_bytes(self.contents)
        self.target.write_bytes(self.contents)

    def cleanup_icon(self):
        output = StringIO()
        with redirect_stdout(output):
            result = CLEANUP.cleanup_owned_icon(
                trusted_root=str(self.root),
                panel_components=("panel",),
                expected_uid=os.geteuid(),
            )
        return result, output.getvalue()

    def assert_preserved(self):
        removed, output = self.cleanup_icon()
        self.assertFalse(removed, output)
        self.assertIn("preserved", output)

    def test_expected_owned_icon_removed_then_idempotent(self):
        removed, output = self.cleanup_icon()
        self.assertTrue(removed, output)
        self.assertFalse(self.target.exists())
        self.assertTrue(self.source.exists())
        self.assert_preserved()
        self.assertFalse(self.target.exists())

    def test_tampered_icon_is_preserved(self):
        self.target.write_bytes(b"unrelated content")
        self.assert_preserved()
        self.assertEqual(self.target.read_bytes(), b"unrelated content")

    def test_destination_final_component_symlink_is_preserved(self):
        destination = self.root / "external-icon"
        destination.write_bytes(self.contents)
        self.target.unlink()
        self.target.symlink_to(destination)
        self.assert_preserved()
        self.assertEqual(destination.read_bytes(), self.contents)
        self.assertTrue(self.target.is_symlink())

    def test_source_final_component_symlink_is_preserved(self):
        source = self.root / "external-source-icon"
        self.source.rename(source)
        self.source.symlink_to(source)
        self.assert_preserved()
        self.assertEqual(self.target.read_bytes(), self.contents)

    def test_destination_parent_symlink_cannot_unlink_external_file(self):
        external = self.root / "external-destination"
        self.target_parent.rename(external)
        self.target_parent.symlink_to(external, target_is_directory=True)
        self.assert_preserved()
        self.assertEqual((external / self.target.name).read_bytes(), self.contents)

    def test_source_parent_symlink_causes_safe_preservation(self):
        external = self.root / "external-source"
        self.source_parent.rename(external)
        self.source_parent.symlink_to(external, target_is_directory=True)
        self.assert_preserved()
        self.assertEqual(self.target.read_bytes(), self.contents)

    def test_intermediate_destination_parent_symlink_is_rejected(self):
        original = self.root / "external-btpanel"
        old = self.panel / "BTPanel"
        old.rename(original)
        old.symlink_to(original, target_is_directory=True)
        self.assert_preserved()
        self.assertEqual((original / "static" / "img" / "soft_ico" / self.target.name).read_bytes(), self.contents)

    def test_shared_panel_parent_symlink_is_rejected(self):
        real = self.root / "external-panel"
        self.panel.rename(real)
        self.panel.symlink_to(real, target_is_directory=True)
        self.assert_preserved()
        self.assertEqual((real / "BTPanel" / "static" / "img" / "soft_ico" / self.target.name).read_bytes(), self.contents)

    def test_group_world_writable_parent_is_rejected(self):
        parent = self.panel / "BTPanel" / "static" / "img"
        old = parent.stat().st_mode & 0o777
        parent.chmod(0o777)
        try:
            self.assert_preserved()
            self.assertEqual(self.target.read_bytes(), self.contents)
        finally:
            parent.chmod(old)

    def test_hardlinked_icon_is_not_unlinked(self):
        self.target.unlink()
        os.link(self.source, self.target)
        self.assert_preserved()
        self.assertTrue(self.target.exists())
        self.assertEqual(self.target.stat().st_nlink, 2)

    def test_directory_instead_of_icon_is_not_unlinked(self):
        self.target.unlink()
        self.target.mkdir()
        self.assert_preserved()
        self.assertTrue(self.target.is_dir())

    def test_unexpected_directory_owner_is_rejected(self):
        output = StringIO()
        with redirect_stdout(output):
            result = CLEANUP.cleanup_owned_icon(
                trusted_root=str(self.root),
                panel_components=("panel",),
                expected_uid=os.geteuid() + 1,
            )
        self.assertFalse(result)
        self.assertEqual(self.target.read_bytes(), self.contents)


if __name__ == "__main__":
    unittest.main()
