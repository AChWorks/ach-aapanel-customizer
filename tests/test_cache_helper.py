"""No-execution Nginx Helper source evidence and unsupported-state regression."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_cache_helper as helper


SOURCE = b"""<?php
/**
 * Plugin Name:       Nginx Helper
 * Version:           2.4.1
 * Author:            rtCamp
 */
"""


class NginxHelperInspectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-nginx-helper-inspect-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wp = self.root / "wp-includes"
        self.plugins = self.root / "wp-content" / "plugins"
        self.plugin = self.plugins / "nginx-helper"
        self.wp.mkdir()
        (self.wp / "version.php").write_text("<?php $wp_version='7.1';\n")
        self.plugins.mkdir(parents=True)

    def inspect(self):
        return helper.inspect_nginx_helper_files(str(self.root))

    def test_known_241_files_are_not_mistaken_for_active_or_purge_safe(self):
        self.plugin.mkdir()
        (self.plugin / "nginx-helper.php").write_bytes(SOURCE)
        before = sorted(str(p) for p in self.root.rglob("*"))
        result = self.inspect()
        self.assertEqual(result["state"], "Installed")
        self.assertEqual(result["version"], "2.4.1")
        for key in ("active_verified", "purge_method_verified",
                    "cache_path_verified", "purge_safe_verified"):
            self.assertIs(result[key], False)
        self.assertIn("get_request", result["note"])
        self.assertIn("unlink_files", result["note"])
        self.assertIn("cache generation", result["note"])
        self.assertIn("recursively deletes", result["note"])
        self.assertFalse(result["reason"])
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)

    def test_absence_is_not_a_claim_about_active_wordpress_plugins(self):
        result = self.inspect()
        self.assertEqual(result["state"], "Not Installed")
        self.assertIsNone(result["version"])
        self.assertFalse(result["active_verified"])
        self.assertIn("Must-use or alternate", result["note"])
        (self.wp / "version.php").unlink()
        result = self.inspect()
        self.assertEqual(result["state"], "Not Observed")
        self.assertIn("subdirectory installs", result["note"])

    def test_other_version_is_not_claimed_compatible(self):
        self.plugin.mkdir()
        (self.plugin / "nginx-helper.php").write_bytes(SOURCE.replace(b"2.4.1", b"2.4.2"))
        result = self.inspect()
        self.assertEqual(result["state"], "Installed")
        self.assertEqual(result["version"], "2.4.2")
        self.assertIn("not verified", result["note"])
        self.assertFalse(result["purge_safe_verified"])

    def test_incomplete_metadata_and_symlinked_plugin_file_need_review(self):
        self.plugin.mkdir()
        source = self.plugin / "nginx-helper.php"
        for data in (b"<?php /* unrelated plugin */", SOURCE.replace(b"Nginx Helper", b"Different")):
            source.write_bytes(data)
            result = self.inspect()
            self.assertEqual(result["state"], "Needs Review")
            self.assertIsNone(result["version"])
            self.assertTrue(result["reason"])
        source.unlink()
        external = self.root / "outside.php"
        external.write_bytes(SOURCE)
        source.symlink_to(external)
        result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")
        self.assertFalse(result["purge_safe_verified"])
        self.assertNotIn(str(external), result["reason"])

    def test_rejects_symlinked_parent_and_oversized_source(self):
        outsider = self.root / "other"
        outsider.mkdir()
        (outsider / "nginx-helper.php").write_bytes(SOURCE)
        self.plugin.symlink_to(outsider, target_is_directory=True)
        self.assertEqual(self.inspect()["state"], "Needs Review")
        self.plugin.unlink()
        self.plugin.mkdir()
        (self.plugin / "nginx-helper.php").write_bytes(SOURCE + b" " * 32769)
        self.assertEqual(self.inspect()["state"], "Needs Review")

    def test_invalid_native_root_never_opens_untrusted_paths(self):
        for root in (None, "", "/tmp/../etc", "/tmp//site", "/tmp/site/",
                     "relative/site", "/tmp/./site", True, "/"):
            with self.subTest(root=root):
                result = helper.inspect_nginx_helper_files(root)
                self.assertEqual(result["state"], "Needs Review")
                self.assertIn("native document root", result["reason"].lower())
                self.assertFalse(result["purge_safe_verified"])

    def test_unstable_two_pass_source_stays_needs_review(self):
        self.plugin.mkdir()
        (self.plugin / "nginx-helper.php").write_bytes(SOURCE)
        scan = helper._scan
        calls = 0
        def mutate(root):
            nonlocal calls
            calls += 1
            found = scan(root)
            if calls == 1:
                (self.plugin / "nginx-helper.php").write_bytes(
                    SOURCE.replace(b"2.4.1", b"2.4.2"))
            return found
        with patch.object(helper, "_scan", side_effect=mutate):
            result = self.inspect()
        self.assertEqual(calls, 2)
        self.assertEqual(result["state"], "Needs Review")
        self.assertFalse(result["purge_safe_verified"])

    def test_wordpress_core_and_plugin_scanner_does_not_execute_code(self):
        self.plugin.mkdir()
        malicious = b"<?php die('not allowed to execute');\n" + SOURCE
        (self.plugin / "nginx-helper.php").write_bytes(malicious)
        result = self.inspect()
        self.assertEqual(result["state"], "Installed")
        self.assertFalse(result["active_verified"])


if __name__ == "__main__":
    unittest.main()
