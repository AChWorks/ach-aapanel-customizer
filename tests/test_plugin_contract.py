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
                self.assertEqual(len(names), 36)
                self.assertTrue(all(n.startswith('ach_customizer/') and '..' not in n for n in names))
                self.assertIn('ach_customizer/info.json', names)
                self.assertIn('ach_customizer/install.sh', names)
                self.assertIn('ach_customizer/ach_customizer_cleanup.py', names)
                self.assertIn('ach_customizer/ach_customizer_state.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_apply.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_workflow.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_pages.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_inspect.py', names)
                self.assertIn('ach_customizer/ach_customizer_hosts.py', names)
                self.assertIn('ach_customizer/status_pages/manifest.json', names)
                for language in ('en', 'fa'):
                    for name in ('403', '404', '429', '500', '502', '503', '504',
                                 '50x', 'new-site', 'stopped', 'unbound'):
                        self.assertIn(f'ach_customizer/status_pages/{language}/{name}.html', names)

                self.assertIn('ach_customizer/icon.png', names)
                self.assertTrue(archive.read('ach_customizer/icon.png').startswith(b'\x89PNG'))
                from scripts.build_plugin import _content_timestamp
                self.assertNotEqual(_content_timestamp(b'before'),
                                    _content_timestamp(b'after!'),
                                    'Equal-length source edits must invalidate a prior Python mtime cache')
                for info in archive.infolist():
                    self.assertEqual(info.date_time, _content_timestamp(archive.read(info)),
                                     'Member mtimes must be deterministic content fingerprints')

    def test_native_ui_is_english_only_without_translation_dependency(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('lang="en"', html)
        self.assertIn('dir="ltr"', html)
        self.assertIn('bt-form', html)
        self.assertNotIn('data-i18n', html)
        self.assertNotIn('navigator.language', html)

    def test_installer_guards_cleanup_and_does_not_mutate_services(self):
        shell = (PACKAGE / 'install.sh').read_text(encoding='utf-8')
        helper = (PACKAGE / 'ach_customizer_cleanup.py').read_text(encoding='utf-8')
        self.assertIn('panel_python=/www/server/panel/pyenv/bin/python3', shell)
        self.assertIn('ach_customizer_cleanup.py', shell)
        self.assertIn('[ ! -L "$cleanup" ]', shell)
        self.assertIn('[ ! -L "$directory" ]', shell)
        self.assertIn('trusted_helper_path', shell)
        self.assertIn('icon copy preserved', shell)
        for requirement in (
            'os.O_NOFOLLOW',
            'os.O_DIRECTORY',
            'os.fstat',
            'os.unlink',
            'dir_fd=destination_parent',
            'st_nlink != 1',
            'entry.st_uid != expected_uid',
            'entry.st_mode & 0o022',
        ):
            self.assertIn(requirement, helper)
        self.assertNotIn('rm -rf', shell)
        self.assertNotIn('rm -f', shell)
        self.assertNotIn('rmtree(', helper)

    def test_installer_does_not_purge_settings_or_services(self):
        script = (PACKAGE / 'install.sh').read_text()
        for forbidden in ('rm -rf', 'systemctl', 'service nginx', 'service php', 'crontab', 'reload'):
            self.assertNotIn(forbidden, script)
        for action in ('install', 'uninstall'):
            result = subprocess.run(['/bin/sh', str(PACKAGE / 'install.sh'), action], check=True, capture_output=True, text=True)
            self.assertIn('ACh aaPanel Customizer', result.stdout)
            if action == 'uninstall':
                self.assertIn('PHP-FPM settings may include previously applied changes', result.stdout)
                self.assertIn('recovery records are preserved', result.stdout)
                self.assertIn('reinstall the plugin', result.stdout)
                self.assertNotIn('no services, jobs or host configurations to revert', result.stdout)


if __name__ == '__main__':
    unittest.main()
