"""Offline rejection tests for the exact-source-pinned Nginx Helper QA harness.

The approved upstream vendor methods are exercised in the isolated aaPanel QA
guest; CI uses synthetic PHP only to prove it is rejected without execution.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "scripts" / "qa_nginx_helper_241.php"
PHP = shutil.which("php")


@unittest.skipUnless(PHP, "PHP CLI is not available on this test runner")
class NginxHelperQaHarnessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="ach-helper-qa-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.plugin = self.root / "nginx-helper"
        admin = self.plugin / "admin"
        admin.mkdir(parents=True)
        self.purger = admin / "class-purger.php"
        self.fastcgi = admin / "class-fastcgi-purger.php"
        self.purger.write_text("<?php class Purger {}\n", encoding="utf-8")
        self.fastcgi.write_text(
            "<?php class FastCGI_Purger {\n"
            "  public function purge_url($url, $feed = true) {\n"
            "    throw new RuntimeException('injected vendor failure');\n"
            "  }\n"
            "}\n", encoding="utf-8",
        )
        self.temp = self.root / "isolated-tmp"
        self.temp.mkdir()

    def run_harness(self, version):
        (self.plugin / "nginx-helper.php").write_text(
            "<?php\n/**\n * Plugin Name:       Nginx Helper\n"
            f" * Version:           {version}\n */\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["TMPDIR"] = str(self.temp)
        return subprocess.run(
            [PHP, "-n", str(QA), str(self.plugin)],
            capture_output=True, text=True, timeout=20, check=False,
            env=environment,
        )

    def test_unsupported_version_is_rejected_before_vendor_execution(self):
        result = self.run_harness("2.4.2")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("pinned to Nginx Helper v2.4.1", result.stderr)
        self.assertEqual(list(self.temp.iterdir()), [])

    def test_spoofed_241_header_modified_vendor_code_never_executes(self):
        # A malicious class body must not run just because nginx-helper.php
        # declares the accepted version. We observe an external sentinel.
        marker = self.root / "executable-class-was-loaded"
        self.purger.write_text(
            "<?php file_put_contents(" + json.dumps(str(marker)) +
            ", 'UNEXPECTED'); class Purger {}\n",
            encoding="utf-8",
        )
        result = self.run_harness("2.4.1")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("source SHA-256 mismatch: class-purger.php", result.stderr)
        self.assertFalse(marker.exists(), "Unverified vendor PHP was executed")
        self.assertEqual(list(self.temp.iterdir()), [], "Rejected code left a fixture")
        self.assertIn("FastCGI_Purger", self.fastcgi.read_text(encoding="utf-8"))

    def test_missing_vendor_class_rejected_without_fixture(self):
        self.purger.unlink()
        result = self.run_harness("2.4.1")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("source is incomplete", result.stderr)
        self.assertEqual(list(self.temp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
