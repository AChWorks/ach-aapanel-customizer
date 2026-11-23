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

    def test_native_version_handshake_is_baked_into_loaded_python_and_shipped_ui(self):
        import re
        info = json.loads((PACKAGE / 'info.json').read_text())
        main = (PACKAGE / 'ach_customizer_main.py').read_text()
        ui = (PACKAGE / 'index.html').read_text()
        worker = re.search(r"(?m)^WORKER_SOURCE_VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'$", main)
        shipped = re.search(r"var shippedUiVersion = '([0-9]+\.[0-9]+\.[0-9]+)'", ui)
        self.assertIsNotNone(worker)
        self.assertIsNotNone(shipped)
        self.assertEqual(info['versions'], worker.group(1))
        self.assertEqual(info['versions'], shipped.group(1))
        self.assertIn('worker_source_version', main)
        self.assertNotIn("json.load(open", main)

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
                from scripts.build_plugin import FILES
                self.assertEqual(len(names), len(FILES))
                self.assertTrue(all(n.startswith('ach_customizer/') and '..' not in n for n in names))
                self.assertIn('ach_customizer/info.json', names)
                self.assertIn('ach_customizer/install.sh', names)
                self.assertIn('ach_customizer/LICENSE', names)
                self.assertEqual(archive.read('ach_customizer/LICENSE'),
                                 (ROOT / 'LICENSE').read_bytes())
                self.assertIn(b'Mozilla Public License Version 2.0',
                              archive.read('ach_customizer/LICENSE'))
                self.assertIn('ach_customizer/ach_customizer_cleanup.py', names)
                self.assertIn('ach_customizer/ach_customizer_state.py', names)
                self.assertIn('ach_customizer/ach_customizer_cache_helper.py', names)
                self.assertIn('ach_customizer/ach_customizer_cache_bridge.py', names)
                self.assertIn('ach_customizer/ach_customizer_nginx_security.py', names)
                self.assertIn('ach_customizer/ach_customizer_abusive_scan.py', names)
                self.assertIn('ach_customizer/ach_customizer_site_changes.py', names)
                self.assertIn('ach_customizer/ach_customizer_site_reconcile.py', names)
                self.assertIn('ach_customizer/ach_customizer_activity.py', names)
                self.assertIn('ach_customizer/ach_customizer_lifecycle.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_apply.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_workflow.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_policy.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_pages.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_inspect.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_probe.py', names)
                self.assertIn('ach_customizer/ach_customizer_php_runtime.py', names)
                self.assertIn('ach_customizer/ach_customizer_php_topology.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_extension.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_site_file.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_unbound.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_tls.py', names)
                self.assertIn('ach_customizer/ach_customizer_wp_settings.py', names)
                self.assertIn('ach_customizer/ach_customizer_wp_xmlrpc.py', names)
                self.assertIn('ach_customizer/ach_customizer_wp_urls.py', names)
                self.assertIn('ach_customizer/ach_customizer_status_stopped.py', names)
                self.assertNotIn('ach_customizer/ach_customizer_status_manage.py', names)
                self.assertNotIn('ach_customizer/ach_customizer_status_routing.py', names)
                self.assertIn('ach_customizer/ach_customizer_hosts.py', names)
                self.assertIn('ach_customizer/ach_customizer_hosts_manage.py', names)
                self.assertIn('ach_customizer/ach_customizer_wp_terminal.py', names)
                self.assertIn('ach_customizer/ach_customizer_wp_watcher.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_auto.py', names)
                self.assertIn('ach_customizer/ach_customizer_fpm_watcher.py', names)
                self.assertIn('ach_customizer/ach_customizer_cache_audit.py', names)
                self.assertIn('ach_customizer/ach_customizer_cache_policy.py', names)
                self.assertIn('ach_customizer/ach_customizer_cache_manage.py', names)
                self.assertIn('ach_customizer/ach_customizer_cache_runtime.py', names)
                self.assertEqual(
                    {Path(x).name for x in names if x.endswith('.py')},
                    {p.name for p in PACKAGE.glob('*.py') if p.is_file()},
                    'Every shipped Python module must exist in the ZIP')
                self.assertIn('ach_customizer/ach_customizer_vhost_drift.py', names)
                self.assertIn('ach_customizer/ach_customizer_nginx_observation.py', names)
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

    def test_native_zip_refuses_missing_license_without_partial_archive(self):
        from unittest.mock import patch
        from scripts import build_plugin

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'candidate.zip'
            with patch.object(build_plugin, 'ROOT', Path(tmp)):
                with self.assertRaisesRegex(ValueError, 'package license'):
                    build_plugin.build(path)
            self.assertFalse(path.exists())

    def test_native_ui_is_english_only_without_translation_dependency(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('lang="en"', html)
        self.assertIn('dir="ltr"', html)
        self.assertIn('bt-form', html)
        self.assertNotIn('data-i18n', html)
        self.assertNotIn('navigator.language', html)

    def test_home_disclosure_distinguishes_monitor_from_opt_in_auto_repair(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        main = (PACKAGE / 'ach_customizer_main.py').read_text(encoding='utf-8')
        self.assertIn('<summary>Advanced: plugin monitoring controls</summary>', html)
        self.assertIn('These controls determine whether Customizer inspections', html)
        self.assertIn('They do not stop PHP or Nginx services or enable automatic repair.', html)
        self.assertIn('Disabling the overall or PHP check also suspends any separately enabled PHP auto-repair.', html)
        for control in ('ach-monitor-enabled', 'ach-site-enabled', 'ach-fpm-enabled'):
            self.assertIn('id="' + control + '"', html)
        self.assertIn('Monitor switches do not directly change services or enable automatic repair.', main)
        self.assertIn('disabling Overall Monitor or PHP-FPM preview also blocks opted-in PHP-FPM repair.', main)
        self.assertIn('Monitor disabled: existing services keep running, but related inspections/manual workflows and already opted-in PHP-FPM automatic repair cannot run.', main)

    def test_dense_tables_preserve_readable_activity_and_website_columns(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('.ach-scroll > table { min-width:640px; }', html)
        self.assertIn('class="ach-website-table"', html)
        self.assertIn('.ach-activity-table { table-layout:fixed; }', html)
        self.assertIn('.ach-activity-table td:nth-child(2) { white-space:nowrap; }', html)
        self.assertIn("$('<time>').addClass('ach-activity-time').attr('datetime', entry.time_utc)", html)

    def test_home_starts_with_four_task_launchers_and_no_unconditional_writes(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<h4 data-home-only>Home</h4>', html)
        self.assertIn('aria-label="Common tasks"', html)
        for control, task in (
                ('ach-overview-browse-sites', 'Manage a website'),
                ('ach-home-php', 'Inspect PHP services'),
                ('ach-home-status', 'Design an error page'),
                ('ach-home-activity', 'Review recent activity')):
            self.assertIn('id="' + control + '" type="button" class="ach-task-link"', html)
            self.assertIn('<strong>' + task + '</strong>', html)
        self.assertIn("root.find('#ach-home-php').on('click'", html)
        self.assertIn("if (title && title.focus) title.focus({preventScroll:true});", html)
        self.assertIn("root.find('[data-destination]').on('click'", html)
        self.assertIn("root.find('[data-task]').on('click'", html)

    def test_fpm_auto_disclosure_rejects_retired_profile_upgrade_promise(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        validator = (PACKAGE / 'ach_customizer_fpm_auto.py').read_text(encoding='utf-8')
        self.assertIn('Only current lifecycle-bearing automatic profiles are supported.', html)
        self.assertIn('A separate explicit Enable requires fresh source and policy verification', html)
        self.assertIn('retired pre-Stable WordPress-only formats have no automatic migration or fallback.', html)
        self.assertNotIn('Previously enabled WordPress-only profiles need to be disabled and enabled again', html)
        self.assertIn('or not isinstance(profile["lifecycle"], dict)', validator)

    def test_checkbox_text_flow_and_guard_option_remain_readable(self):
        import re
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        # A label with text + code + emphasis must not make each fragment
        # a separate flex item that collapses into vertical letter columns.
        generic = re.search(
            r'#ach-customizer \.ach-main label:has\(> input\[type="checkbox"\]\)\s*\{([^}]+)\}',
            html)
        self.assertIsNotNone(generic)
        self.assertIn('display:block', generic.group(1))
        self.assertNotIn('inline-flex', generic.group(1))
        note = re.search(
            r'#ach-customizer \.ach-main \.ach-note > label:has\(> input\[type="checkbox"\]\)\s*\{([^}]+)\}',
            html)
        self.assertIsNotNone(note)
        self.assertIn('display:block', note.group(1))
        self.assertIn('class="ach-guard-option"', html)
        self.assertIn('id="ach-guard-block-xmlrpc" /><span>', html)
        self.assertIn('grid-template-columns:16px minmax(0,1fr)', html)
        self.assertIn('#ach-customizer .ach-view code { white-space:nowrap; }', html)
        self.assertIn('<summary>What changes when I enable this?</summary>', html)
        self.assertIn('Check protection readiness', html)
        self.assertIn('Recheck current protection', html)
        # Each formerly detached flex label/select pair is one wrapping
        # field, across Routing, PHP-FPM, and Activity.
        for control_id in (
            'ach-hosts-alias-select', 'ach-scan-maxretry',
            'ach-scan-findtime', 'ach-scan-bantime',
            'ach-scan-orphan-choice', 'ach-wp-settings-kind',
            'ach-wp-settings-debug', 'ach-wp-settings-interval',
            'ach-php-version', 'ach-activity-level', 'ach-activity-module',
        ):
            field = re.search(
                r'<div class="ach-inline-field"(?:\s+[^>]*)?>\s*'
                r'<label for="' + re.escape(control_id) +
                r'">.*?</label>\s*<(?:input|select)\s+id="' +
                re.escape(control_id) + r'"', html, re.S)
            self.assertIsNotNone(field, control_id)

    def test_complex_operator_notes_offer_scannable_guidance(self):
        html = (PACKAGE / 'index.html').read_text(encoding='utf-8')
        for heading in (
            'What does each WordPress operation change?',
            'How to complete orphan-jail recovery',
            'Which sources are compared?',
            'Supported source and exact Nginx changes',
            'What does the Cache audit check?',
            'When does PHP-FPM automatic repair run?',
            'Delivery requirements and recovery',
            'Which HTTPS connections are affected?',
        ):
            self.assertIn('<summary>' + heading + '</summary>', html)
        self.assertIn('Before changing WordPress HTTPS URLs:', html)
        self.assertIn('Firewall impact:', html)
        self.assertIn('Existing bans are <strong>not yet verified removed</strong>', html)
        self.assertIn('This is <strong>not</strong> Nginx Helper Purge All.', html)

    def test_installer_guards_cleanup_and_does_not_mutate_services(self):
        shell = (PACKAGE / 'install.sh').read_text(encoding='utf-8')
        helper = (PACKAGE / 'ach_customizer_cleanup.py').read_text(encoding='utf-8')
        self.assertIn('panel_python=/www/server/panel/pyenv/bin/python3', shell)
        self.assertIn('ach_customizer_cleanup.py', shell)
        self.assertIn('ach_customizer_lifecycle.py', shell)
        self.assertIn('log_lifecycle install_registered', shell)
        self.assertIn('log_lifecycle "$lifecycle_event"', shell)
        self.assertIn('uninstall_cleanup_unavailable', shell)
        self.assertIn('uninstall_icon_preserved', shell)
        self.assertIn('uninstall_icon_removed', shell)
        self.assertIn('lifecycle Activity persistence unconfirmed', shell)
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
        self.assertIn('Status Pages extensions, Nginx assets and recovery journals are preserved', shell)
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
