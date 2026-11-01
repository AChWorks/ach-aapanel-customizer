import json
import shlex
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

    def test_uninstall_only_removes_byte_identical_product_icon(self):
        script = (PACKAGE / 'install.sh').read_text(encoding='utf-8')
        self.assertIn('plugin_icon=/www/server/panel/plugin/ach_customizer/icon.png', script)
        self.assertIn('copied_icon=/www/server/panel/BTPanel/static/img/soft_ico/ico-ach_customizer.png', script)
        self.assertIn('[ ! -L "$plugin_icon" ]', script)
        self.assertIn('[ ! -L "$copied_icon" ]', script)
        self.assertIn('cmp -s "$plugin_icon" "$copied_icon"', script)
        self.assertIn('rm -f -- "$copied_icon"', script)
        self.assertNotIn('rm -rf', script)
        self.assertNotIn('rm -f -- "$plugin_icon"', script)

    def test_icon_cleanup_shell_behavior_with_isolated_files(self):
        script = (PACKAGE / 'install.sh').read_text(encoding='utf-8')
        begin = script.index('cleanup_owned_icon() {')
        end = script.index('\n}\n', begin) + 2
        function = script[begin:end]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'plugin-icon.png'
            copied = root / 'copied-icon.png'
            source_bytes = (PACKAGE / 'icon.png').read_bytes()
            source.write_bytes(source_bytes)

            def invoke():
                command = (
                    'plugin_icon=' + shlex.quote(str(source)) + '\n' +
                    'copied_icon=' + shlex.quote(str(copied)) + '\n' +
                    function + '\ncleanup_owned_icon\n'
                )
                return subprocess.run(['/bin/sh', '-eu', '-c', command],
                                      check=True, capture_output=True, text=True)

            copied.write_bytes(b'owned by another component')
            self.assertIn('preserved', invoke().stdout)
            self.assertEqual(copied.read_bytes(), b'owned by another component')
            copied.write_bytes(source_bytes)
            self.assertIn('removed verified', invoke().stdout)
            self.assertFalse(copied.exists())
            self.assertIn('preserved', invoke().stdout)
            self.assertFalse(copied.exists())

            target = root / 'other-component-file.png'
            target.write_bytes(source_bytes)
            copied.symlink_to(target)
            self.assertIn('preserved', invoke().stdout)
            self.assertTrue(copied.is_symlink())
            self.assertEqual(target.read_bytes(), source_bytes)
            copied.unlink()
            copied.write_bytes(source_bytes)
            original = root / 'real-icon.png'
            source.rename(original)
            source.symlink_to(original)
            self.assertIn('preserved', invoke().stdout)
            self.assertTrue(copied.exists())

    def test_installer_does_not_purge_settings_or_services(self):
        script = (PACKAGE / 'install.sh').read_text()
        for forbidden in ('rm -rf', 'systemctl', 'service nginx', 'service php', 'crontab', 'reload'):
            self.assertNotIn(forbidden, script)
        for action in ('install', 'uninstall'):
            result = subprocess.run(['/bin/sh', str(PACKAGE / 'install.sh'), action], check=True, capture_output=True, text=True)
            self.assertIn('ACh aaPanel Customizer', result.stdout)


if __name__ == '__main__':
    unittest.main()
