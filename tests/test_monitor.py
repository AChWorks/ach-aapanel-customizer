import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / 'plugin' / 'ach_customizer' / 'ach_customizer_monitor.py'
spec = importlib.util.spec_from_file_location('ach_customizer_monitor', MODULE)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

EXPECTED = {
    'pm.max_children': '20',
    'pm.start_servers': '5',
    'pm.min_spare_servers': '5',
    'pm.max_spare_servers': '10',
    'pm.max_requests': '300',
}


class SiteDB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.start = 0
        self.size = 0

    def order(self, order):
        self.calls.append(('order', order))
        return self

    def limit(self, expression):
        self.calls.append(('limit', expression))
        start, size = expression.split(',')
        self.start, self.size = int(start), int(size)
        return self

    def field(self, fields):
        self.calls.append(('field', fields))
        return self

    def select(self):
        self.calls.append(('select',))
        return self.rows[self.start:self.start + self.size]


class Panel:
    def __init__(self, rows):
        self.db = SiteDB(rows)

    def M(self, table):
        if table != 'sites':
            raise AssertionError('unexpected table')
        return self.db


class WebsiteDiscoveryTests(unittest.TestCase):
    def test_dynamic_non_wordpress_pagination_is_read_only(self):
        panel = Panel([{'id': i, 'name': f'example{i}.test', 'path': '/srv/www/' + str(i), 'status': '1'} for i in range(1, 5)])
        data = monitor.get_site_page(panel, page=2, page_size=2)
        self.assertEqual([s['id'] for s in data['sites']], [3, 4])
        self.assertFalse(data['has_more'])
        self.assertEqual([s['classification'] for s in data['sites']], ['Needs Review'] * 2)
        self.assertEqual(data['sites'][0]['panel_status'], '1')
        self.assertEqual(panel.db.calls, [('order', 'id asc'), ('limit', '2,3'), ('field', 'id,name,path,status'), ('select',)])

    def test_site_disabled_status_is_preserved(self):
        panel = Panel([{'id': 1, 'name': 'static.example', 'path': '/srv/www/static', 'status': 0}])
        self.assertEqual(monitor.get_site_page(panel)['sites'][0]['panel_status'], '0')

    def test_pagination_bounds_and_invalid_response(self):
        for value in ('0', '-1', '1;DROP TABLE', '100001', ''):
            with self.subTest(value=value), self.assertRaises(monitor.MonitorInputError):
                monitor.get_site_page(Panel([]), page=value)
        with self.assertRaises(monitor.MonitorInputError):
            monitor.get_site_page(Panel([]), page_size=101)
        with self.assertRaises(RuntimeError):
            monitor.get_site_page(Panel([{'id': 'abc', 'name': 'bad.example'}]))


class PHPMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pool = self.root / '85' / 'etc' / 'php-fpm.d' / 'www.conf'
        self.pool.parent.mkdir(parents=True)
        (self.pool.parent.parent / 'php-fpm.conf').write_text('include=php-fpm.d/*.conf\n', encoding='utf-8')
        self.pool.write_text('[www]\npm = dynamic\n' + ''.join(f'{k} = {v}\n' for k, v in EXPECTED.items()), encoding='utf-8')

    def preview(self, expected=None):
        return monitor.preview_php_fpm(self.root, '85', expected if expected is not None else EXPECTED)

    def test_in_sync_has_no_mutation(self):
        before = self.pool.read_bytes()
        result = self.preview()
        self.assertEqual(result['state'], 'File Match')
        self.assertEqual(result['scope'], 'shared_service')
        self.assertEqual(result['changes'], [])
        self.assertEqual(self.pool.read_bytes(), before)

    def test_detect_shared_pool_drift_and_preserve_bytes(self):
        self.pool.write_text(self.pool.read_text().replace('pm.max_children = 20', 'pm.max_children = 80'), encoding='utf-8')
        before = self.pool.read_bytes()
        result = self.preview()
        self.assertEqual(result['state'], 'File Drift')
        self.assertEqual(result['changes'], [{'setting': 'pm.max_children', 'desired': 20, 'actual': 80}])
        self.assertEqual(self.pool.read_bytes(), before)

    def test_unknown_or_ambiguous_configuration_needs_review(self):
        self.pool.write_text('[www]\npm = dynamic\npm.max_children = 20\n', encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')
        other = self.root / '85' / 'etc' / 'php-fpm.conf'
        other.write_text('include=php-fpm.d/*.conf\n[www]\npm = dynamic\n' + ''.join(f'{k}={v}\n' for k, v in EXPECTED.items()), encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')

    def test_duplicate_and_symlink_configuration_is_rejected(self):
        self.pool.write_text('[www]\npm = dynamic\npm.max_children = 20\npm.max_children = 25\n', encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')
        self.pool.unlink()
        source = self.root / 'external.conf'
        source.write_text('[www]\npm = dynamic\npm.max_children=20\n', encoding='utf-8')
        self.pool.symlink_to(source)
        self.assertEqual(self.preview()['state'], 'Needs Review')

    def test_unknown_include_and_non_dynamic_mode_needs_review(self):
        main = self.pool.parent.parent / 'php-fpm.conf'
        main.write_text('include=/untrusted/other/*.conf\n', encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')
        main.write_text('include=php-fpm.d/*.conf\n', encoding='utf-8')
        self.pool.write_text(self.pool.read_text().replace('pm = dynamic', 'pm = ondemand'), encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')
        self.pool.write_text(self.pool.read_text().replace('pm = ondemand', 'pm = dynamic'), encoding='utf-8')
        main.write_text('[global]\n', encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')

    def test_invalid_policy_fails_without_file_access(self):
        for version in ('../85', 'abc', '85/x', '', '0085'):
            with self.subTest(version=version), self.assertRaises(monitor.MonitorInputError):
                monitor.preview_php_fpm(self.root, version, EXPECTED)
        bad = dict(EXPECTED, **{'pm.min_spare_servers': '30'})
        with self.assertRaises(monitor.MonitorInputError):
            self.preview(bad)
        bad = dict(EXPECTED, **{'pm.max_children': '1; rm -rf /'})
        with self.assertRaises(monitor.MonitorInputError):
            self.preview(bad)

    def test_missing_version_and_many_includes(self):
        self.assertEqual(monitor.preview_php_fpm(self.root, '84', EXPECTED)['state'], 'Needs Review')
        for i in range(33):
            (self.pool.parent / f'pool{i}.conf').write_text('[other]\n', encoding='utf-8')
        self.assertEqual(self.preview()['state'], 'Needs Review')


if __name__ == '__main__':
    unittest.main()
