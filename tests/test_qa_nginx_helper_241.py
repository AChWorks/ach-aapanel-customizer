"""Safe offline test of the Nginx Helper 2.4.1 QA harness itself.

The real vendor methods are exercised only in the isolated aaPanel guest; they
are not copied into this repository. These checks catch accidental execution
of unsupported versions and ensure failed fixture runs clean their own files.
"""
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

    def test_vendor_failure_cleans_only_isolated_fixture(self):
        result = self.run_harness("2.4.1")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("injected vendor failure", result.stderr)
        self.assertEqual(list(self.temp.iterdir()), [])
        # The installed plugin source/fixture files must not be modified.
        self.assertIn("FastCGI_Purger", self.fastcgi.read_text(encoding="utf-8"))
        self.assertIn("class Purger", self.purger.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
