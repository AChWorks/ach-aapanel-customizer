import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / 'plugin' / 'ach_customizer'


class PackageContractTests(unittest.TestCase):
    def test_manifest_matches_native_entrypoint(self):
        info = json.loads((PACKAGE / 'info.json').read_text())
        self.assertEqual(info['name'], 'ach_customizer')
        self.assertEqual(info['checks'], '/www/server/panel/plugin/ach_customizer')
        main = (PACKAGE / 'ach_customizer_main.py').read_text()
        self.assertIn('class ach_customizer_main:', main)
        self.assertNotIn('def _check(', main)
        self.assertNotIn('ServiceReload(', main)
        self.assertNotIn('ExecShell(', main)
        self.assertNotIn('def apply(', main)

    def test_build_is_reproducible_and_contents_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'dev.zip'
            cmd = [sys.executable, str(ROOT / 'scripts' / 'build_plugin.py'), '--output', str(target)]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            first = target.read_bytes()
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            self.assertEqual(target.read_bytes(), first)
            with ZipFile(target) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), 6)
                self.assertTrue(all(n.startswith('ach_customizer/') and '..' not in n for n in names))
                self.assertIn('ach_customizer/info.json', names)
                self.assertIn('ach_customizer/install.sh', names)
                self.assertIn('ach_customizer/icon.png', names)
                self.assertTrue(archive.read('ach_customizer/icon.png').startswith(b'\x89PNG'))

    def test_native_ui_is_english_only_without_translation_dependency(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('lang="en"', html)
        self.assertIn('dir="ltr"', html)
        self.assertIn('bt-form', html)
        self.assertNotIn('data-i18n', html)
        self.assertNotIn('navigator.language', html)

    def test_installer_does_not_purge_settings_or_services(self):
        script = (PACKAGE / 'install.sh').read_text()
        for forbidden in ('rm -rf', 'systemctl', 'service nginx', 'service php', 'crontab', 'reload'):
            self.assertNotIn(forbidden, script)
        for action in ('install', 'uninstall'):
            result = subprocess.run(['/bin/sh', str(PACKAGE / 'install.sh'), action], check=True, capture_output=True, text=True)
            self.assertIn('ACh aaPanel Customizer', result.stdout)


if __name__ == '__main__':
    unittest.main()
