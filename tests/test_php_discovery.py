"""Bounded aaPanel PHP-version discovery: no runtime commands or host writes."""
import hashlib
import json
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / 'plugin' / 'ach_customizer'
sys.path.insert(0, str(PLUGIN))
import ach_customizer_monitor as monitor
import ach_customizer_main as endpoint


class PHPDiscoveryFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ach-php-discover-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'php'
        self.root.mkdir()

    def make(self, code, *, binary=True, config=True):
        v = self.root / code
        v.mkdir()
        if binary:
            (v / 'sbin').mkdir()
            exe = v / 'sbin' / 'php-fpm'
            exe.write_bytes(b'\x7fELF' + b'test' * 15)
            exe.chmod(0o755)
        if config:
            (v / 'etc').mkdir()
            (v / 'etc' / 'php-fpm.conf').write_text('[www]\n', encoding='utf-8')
        return v

    def scan(self):
        return monitor.discover_php_fpm_versions(str(self.root))

    def test_php81_php85_future_and_older_versions_remain_discoverable(self):
        self.make('81')
        v85 = self.make('85')
        self.make('810')
        self.make('80')
        self.make('83', binary=False)
        (self.root / '84').symlink_to(v85, target_is_directory=True)
        (self.root / 'unrelated.txt').write_text('ignored')
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}
        result = self.scan()
        self.assertEqual(result['schema'], 1)
        self.assertEqual(result['state'], 'Partial')
        self.assertTrue(result['read_only'])
        self.assertFalse(result['runtime_verified'])
        versions = {v['code']: v for v in result['versions']}
        self.assertEqual([v['code'] for v in result['versions']],
                         ['80', '81', '83', '84', '85', '810'])
        self.assertEqual(versions['80']['state'], 'File Preview Candidate')
        self.assertTrue(versions['80']['preview_candidate'])
        self.assertEqual(versions['80']['manual_apply_adapter'], 'none')
        self.assertFalse(versions['80']['apply_eligible'])
        self.assertEqual(versions['81']['label'], 'PHP 8.1')
        self.assertEqual(versions['81']['state'], 'File Preview Candidate')
        self.assertTrue(versions['81']['preview_candidate'])
        self.assertEqual(versions['81']['manual_apply_adapter'], 'guarded_php81')
        self.assertTrue(versions['85']['preview_candidate'])
        self.assertEqual(versions['85']['manual_apply_adapter'], 'guarded_php85')
        self.assertEqual(versions['810']['label'], 'PHP 8.10')
        self.assertFalse(versions['83']['binary_present'])
        self.assertFalse(versions['83']['preview_candidate'])
        self.assertIn('linked', versions['84']['reason'])
        self.assertFalse(versions['84']['config_present'])
        self.assertTrue(all(not v['apply_eligible'] for v in result['versions']))
        self.assertEqual({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}, before)

    def test_php81_and_php85_are_file_preview_candidates_not_write_approval(self):
        for code in ('81', '85'):
            v = self.make(code)
            (v / 'etc' / 'php-fpm.conf').write_text(
                '[global]\n[www]\npm = dynamic\n'
                'pm.max_children = 20\npm.start_servers = 5\n'
                'pm.min_spare_servers = 5\npm.max_spare_servers = 10\n'
                'pm.max_requests = 300\n'
                'listen = /tmp/php-cgi-' + code + '.sock\n', encoding='utf-8'
            )
        discovered = {v['code']: v for v in self.scan()['versions']}
        expected = {'pm.max_children': '20', 'pm.start_servers': '5',
                    'pm.min_spare_servers': '5', 'pm.max_spare_servers': '10',
                    'pm.max_requests': '300'}
        for code in ('81', '85'):
            with self.subTest(code=code):
                self.assertTrue(discovered[code]['preview_candidate'])
                self.assertFalse(discovered[code]['apply_eligible'])
                preview = monitor.preview_php_fpm(self.root, code, expected)
                self.assertEqual(preview['state'], 'File Match')
                self.assertEqual(preview['scope'], 'shared_service')
                self.assertEqual(preview['version'], code)
                self.assertIn('not verified', preview['note'])
                self.assertEqual(preview['changes'], [])

    def test_nonexecutable_binary_and_linked_config_never_become_candidates(self):
        v82 = self.make('82')
        (v82 / 'sbin' / 'php-fpm').chmod(0o644)
        v86 = self.make('86')
        source = v86 / 'etc' / 'php-fpm.conf'
        source.unlink()
        source.symlink_to(v82 / 'etc' / 'php-fpm.conf')
        versions = {v['code']: v for v in self.scan()['versions']}
        self.assertFalse(versions['82']['binary_present'])
        self.assertFalse(versions['82']['preview_candidate'])
        self.assertFalse(versions['86']['config_present'])
        self.assertFalse(versions['86']['preview_candidate'])

    def test_original_php_root_replaced_mid_scan_returns_no_stale_versions(self):
        self.make('81')
        prior = self.root.parent / 'old-php-root'
        old_stat = os.stat
        mutated = False

        def racing_stat(path, *args, **kwargs):
            nonlocal mutated
            meta = old_stat(path, *args, **kwargs)
            if path == 'php-fpm.conf' and not mutated:
                mutated = True
                self.root.rename(prior)
                self.root.mkdir()
                self.make('85')
            return meta

        with patch.object(os, 'stat', side_effect=racing_stat):
            result = self.scan()
        self.assertTrue(mutated)
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['versions'], [])
        self.assertIn('changed during inspection', result['reason'])

    def test_php_binary_replaced_mid_scan_cannot_be_reported_present(self):
        folder = self.make('81')
        binary = folder / 'sbin' / 'php-fpm'
        old_stat = os.stat
        mutated = False

        def racing_stat(path, *args, **kwargs):
            nonlocal mutated
            meta = old_stat(path, *args, **kwargs)
            if path == 'php-fpm.conf' and not mutated:
                mutated = True
                binary.rename(binary.with_name('php-fpm.replaced'))
                binary.write_bytes(b'\x7fELF' + b'NEW!' * 15)
                binary.chmod(0o755)
            return meta

        with patch.object(os, 'stat', side_effect=racing_stat):
            result = self.scan()
        self.assertTrue(mutated)
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['versions'], [])

    def test_new_php_version_appearing_mid_scan_invalidates_inventory(self):
        self.make('81')
        old_stat = os.stat
        mutated = False

        def racing_stat(path, *args, **kwargs):
            nonlocal mutated
            meta = old_stat(path, *args, **kwargs)
            if path == 'php-fpm.conf' and not mutated:
                mutated = True
                self.make('85')
            return meta

        with patch.object(os, 'stat', side_effect=racing_stat):
            result = self.scan()
        self.assertTrue(mutated)
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['versions'], [])

    def test_php_ancestor_path_rebound_mid_scan_refuses_detached_tree(self):
        self.make('81')
        previous_parent = self.root.parent.with_name(self.root.parent.name + '-detached')
        self.addCleanup(shutil.rmtree, previous_parent, ignore_errors=True)
        old_stat = os.stat
        mutated = False

        def racing_stat(path, *args, **kwargs):
            nonlocal mutated
            meta = old_stat(path, *args, **kwargs)
            if path == 'php-fpm.conf' and not mutated:
                mutated = True
                self.root.parent.rename(previous_parent)
                self.root.parent.mkdir()
                self.root.mkdir()
                self.make('85')
            return meta

        with patch.object(os, 'stat', side_effect=racing_stat):
            result = self.scan()
        self.assertTrue(mutated)
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['versions'], [])

    def test_missing_root_no_fake_installation_or_service_assertion(self):
        result = monitor.discover_php_fpm_versions(str(self.root / 'absent'))
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['versions'], [])
        self.assertFalse(result['runtime_verified'])
        self.assertIn('missing or inaccessible', result['reason'])

    def test_symlinked_root_cannot_be_traversed(self):
        root_link = self.root.parent / 'linked'
        self.make('81')
        root_link.symlink_to(self.root, target_is_directory=True)
        result = monitor.discover_php_fpm_versions(str(root_link))
        self.assertEqual(result['versions'], [])
        self.assertEqual(result['state'], 'Needs Review')

    def test_symlinked_ancestor_and_relative_paths_are_rejected(self):
        self.make('81')
        parent_link = self.root.parent / 'linked-parent'
        parent_link.symlink_to(self.root.parent, target_is_directory=True)
        result = monitor.discover_php_fpm_versions(str(parent_link / 'php'))
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['versions'], [])
        for value in ('relative/php', '../etc', '/tmp/../etc'):
            with self.subTest(path=value), self.assertRaises(monitor.MonitorInputError):
                monitor.discover_php_fpm_versions(value)

    def test_unrelated_root_entries_and_many_installed_versions_do_not_block_inspection(self):
        for i in range(140):
            (self.root / ('other-' + str(i))).mkdir()
        self.make('74')
        codes = [str(i) for i in range(81, 90)] + [
            '8' + str(i) for i in range(10, 41)]
        for code in codes:
            self.make(code)
        result = self.scan()
        self.assertEqual(result['state'], 'Observed')
        self.assertEqual(len(result['versions']), len(codes) + 1)
        self.assertEqual(result['versions'][0]['code'], '74')
        self.assertTrue(result['versions'][0]['preview_candidate'])
        self.assertEqual(result['versions'][0]['manual_apply_adapter'], 'none')
        self.assertFalse(any(v['apply_eligible'] for v in result['versions']))


class NativePHPDiscoveryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = endpoint.ach_customizer_main()
        self.tmp = tempfile.TemporaryDirectory(prefix='ach-php-discovery-state-')
        self.addCleanup(self.tmp.cleanup)
        st = patch.object(endpoint, '_STATE_DIR', self.tmp.name)
        st.start()
        self.addCleanup(st.stop)

    @staticmethod
    def flask(uid=1, *, temporary=False, method='POST', context=True):
        obj = types.ModuleType('flask')
        obj.request = types.SimpleNamespace(method=method)
        obj.session = {'login': True, 'uid': uid}
        if temporary:
            obj.session['tmp_login_id'] = ''
        obj.has_request_context = lambda: context
        return obj

    def test_primary_post_returns_only_bounded_read_only_discovery(self):
        data = monitor.discover_php_fpm_versions('/missing/ach/php-test')
        with patch.dict(sys.modules, {'flask': self.flask()}):
            with patch.object(monitor, 'discover_php_fpm_versions', return_value=data) as spy:
                result = self.plugin.get_php_versions({'root': '/etc', 'php_version': '85'})
        self.assertTrue(result['status'], result)
        self.assertTrue(result['read_only'])
        self.assertFalse(result['runtime_verified'])
        spy.assert_called_once_with('/www/server/php')
        self.assertRegex(result['operation_id'], r'^[0-9a-f]{32}$')

    def test_partial_discovery_generates_a_private_warning_record(self):
        from ach_customizer_activity import read_activity
        response = {"schema": 1, "state": "Partial", "versions": [],
                    "read_only": True, "runtime_verified": False,
                    "reason": "Missing PHP binary", "note": "Observed files only"}
        with patch.dict(sys.modules, {'flask': self.flask()}):
            with patch.object(monitor, 'discover_php_fpm_versions', return_value=response):
                observed = self.plugin.get_php_versions({})
        self.assertTrue(observed['status'])
        self.assertEqual(observed['state'], 'Partial')
        self.assertTrue(observed['activity_logged'])
        entries = read_activity(self.tmp.name, module='php_fpm', limit=10)
        self.assertTrue(any(e['action'] == 'get_php_versions' and e['level'] == 'WARNING'
                            and e['outcome'] == 'Partial' and e['target'] == 'native-php'
                            for e in entries))

    def test_nonprimary_temporary_get_and_missing_context_never_inspect(self):
        for login in (self.flask(uid=2), self.flask(temporary=True),
                      self.flask(method='GET'), self.flask(context=False)):
            with self.subTest(login=login.session, method=login.request.method):
                with patch.dict(sys.modules, {'flask': login}):
                    with patch.object(monitor, 'discover_php_fpm_versions',
                                      side_effect=AssertionError('must not inspect')) as spy:
                        result = self.plugin.get_php_versions({})
                self.assertFalse(result['status'])
                self.assertEqual(result['stage'], 'php_versions_authorization')
                spy.assert_not_called()

    def test_discovery_exception_is_contained_and_operation_logged(self):
        with patch.dict(sys.modules, {'flask': self.flask()}):
            with patch.object(monitor, 'discover_php_fpm_versions',
                              side_effect=monitor.MonitorInputError('PHP inventory exceeds limit')):
                result = self.plugin.get_php_versions({})
        self.assertFalse(result['status'])
        self.assertEqual(result['stage'], 'php_versions_discovery')
        self.assertIn('exceeds limit', result['msg'])
        self.assertRegex(result['operation_id'], r'^[0-9a-f]{32}$')
        self.assertTrue(result['activity_logged'])

    def test_failed_php_discovery_is_classified_in_php_fpm_activity(self):
        from ach_customizer_activity import read_activity
        with patch.dict(sys.modules, {'flask': self.flask(uid=2)}):
            denied = self.plugin.get_php_versions({})
        self.assertFalse(denied['status'])
        with patch.dict(sys.modules, {'flask': self.flask()}):
            with patch.object(monitor, 'discover_php_fpm_versions',
                              side_effect=monitor.MonitorInputError('PHP inventory exceeds limit')):
                failed = self.plugin.get_php_versions({})
        self.assertFalse(failed['status'])
        php_events = read_activity(self.tmp.name, module='php_fpm', limit=10)
        for stage in ('php_versions_authorization', 'php_versions_discovery'):
            self.assertTrue(any(item['stage'] == stage and item['level'] == 'ERROR'
                                and item['module'] == 'php_fpm'
                                for item in php_events), stage)


    def test_cached_monitor_helper_cannot_break_native_entrypoint(self):
        """Cold entrypoint against a warm pre-0.1.9 helper remains usable.

        In-memory aaPanel update reproduction: no panel restart, host file scan,
        session extraction, or real PHP-FPM operation.
        """
        prior = monitor.discover_php_fpm_versions
        try:
            del monitor.discover_php_fpm_versions

            # The module imported under the normal name is cached but lacks the
            # new symbol. Import the *actual* new main source as aaPanel would.
            spec = importlib.util.spec_from_file_location(
                'ach_customizer_main_cached_monitor_fixture',
                PLUGIN / 'ach_customizer_main.py'
            )
            self.assertIsNotNone(spec)
            updated = importlib.util.module_from_spec(spec)
            with patch('os.scandir',
                       side_effect=AssertionError('No PHP discovery during import')):
                spec.loader.exec_module(updated)
            plugin = updated.ach_customizer_main()
            public = types.ModuleType('public')

            class SiteQuery:
                def where(self, *args): return self
                def field(self, *args): return self
                def find(self):
                    return {'id': 7, 'name': 'site.test',
                            'path': '/www/site.test', 'status': '1'}

            class DomainQuery:
                def where(self, *args): return self
                def order(self, *args): return self
                def limit(self, *args): return self
                def field(self, *args): return self
                def select(self):
                    return [{'id': 20, 'pid': 7,
                             'name': 'site.test', 'port': 80}]

            public.M = lambda table: SiteQuery() if table == 'sites' else DomainQuery()
            snapshot = json.dumps([7, 'site.test', '/www/site.test',
                                   '1', [['site.test', 80]]])
            with patch.object(updated, '_STATE_DIR', self.tmp.name):
                # Old in-memory monitor still serves the independent endpoints.
                self.assertTrue(plugin.get_overview({})['status'])
                with patch.dict(sys.modules, {'public': public, 'flask': self.flask()}):
                    with patch.object(updated, 'get_site_page',
                                      return_value={'page': 1, 'page_size': 25,
                                                    'sites': [], 'has_more': False,
                                                    'schema': 2}):
                        sites = plugin.get_sites({'page': 1, 'page_size': 25})
                    self.assertTrue(sites['status'], sites)
                    with patch.object(updated, 'inspect_hosts_file',
                                      return_value={'schema': 1, 'read_only': True,
                                                    'state': 'No Local Loopback Entry',
                                                    'entries': []}) as reader:
                        hosts = plugin.inspect_local_hosts({
                            'site_id': '7', 'expected_site_key': 'site.test',
                            'expected_site_snapshot': snapshot,
                        })
                    self.assertTrue(hosts['status'], hosts)
                    reader.assert_called_once_with(['site.test'])

                    with patch('os.scandir',
                               side_effect=AssertionError('Stale module must not scan files')):
                        outdated = plugin.get_php_versions({})
                        self.assertFalse(outdated['status'], outdated)
                        self.assertEqual(outdated['stage'], 'php_versions_discovery')
                        self.assertIn('Restart aaPanel panel service (not server)',
                                      outdated['msg'])
                        self.assertTrue(outdated['activity_logged'])
                        self.assertNotIn('/www/server/php', str(outdated))
                        for session in (self.flask(uid=2),
                                        self.flask(temporary=True),
                                        self.flask(method='GET'),
                                        self.flask(context=False)):
                            with patch.dict(sys.modules, {'flask': session}):
                                denied = plugin.get_php_versions({})
                            self.assertEqual(denied['stage'],
                                             'php_versions_authorization')
                            self.assertNotIn('outdated', denied['msg'])
                    from ach_customizer_activity import read_activity
                    events = read_activity(self.tmp.name, module='php_fpm', limit=20)
                    self.assertTrue(any(
                        e['stage'] == 'php_versions_discovery'
                        and e['level'] == 'ERROR'
                        and e['error_class'] == 'MonitorInputError'
                        for e in events
                    ))
        finally:
            monitor.discover_php_fpm_versions = prior

        # An updated helper can answer a new authorized request normally.
        expected = prior('/missing/ach/php-test')
        with patch.object(updated, '_STATE_DIR', self.tmp.name):
            with patch.dict(sys.modules, {'flask': self.flask()}):
                with patch.object(monitor, 'discover_php_fpm_versions',
                                  return_value=expected) as discover:
                    current = plugin.get_php_versions({'root': '/etc'})
        self.assertTrue(current['status'], current)
        self.assertEqual(current['schema'], 1)
        self.assertTrue(current['read_only'])
        self.assertFalse(current['runtime_verified'])
        discover.assert_called_once_with('/www/server/php')


if __name__ == '__main__':
    unittest.main()
