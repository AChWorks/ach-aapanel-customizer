import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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



class DomainDB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.pids = ()

    def where(self, clause, pids):
        self.calls.append(('where', clause, pids))
        assert clause == 'pid IN (' + ','.join('?' for _ in pids) + ')'
        self.pids = pids
        return self

    def order(self, order):
        self.calls.append(('order', order))
        assert order == 'pid asc, id asc'
        return self

    def limit(self, expression):
        self.calls.append(('limit', expression))
        assert expression == '0,1001'
        return self

    def field(self, fields):
        self.calls.append(('field', fields))
        assert fields == 'id,pid,name,port'
        return self

    def select(self):
        self.calls.append(('select',))
        return sorted(
            (row for row in self.rows if row.get('pid') in self.pids),
            key=lambda row: (row.get('pid', 0), row.get('id', 0)),
        )[:1001]


class Panel:
    def __init__(self, rows, domains=None):
        self.db = SiteDB(rows)
        self.domain_db = DomainDB(domains if domains is not None else [])

    def M(self, table):
        if table == 'sites':
            return self.db
        if table == 'domain':
            return self.domain_db
        raise AssertionError('unexpected table')


class WebsiteDiscoveryTests(unittest.TestCase):
    def test_dynamic_non_wordpress_pagination_is_read_only(self):
        panel = Panel([{'id': i, 'name': f'example{i}.test', 'path': '/srv/www/' + str(i), 'status': '1'} for i in range(1, 5)])
        data = monitor.get_site_page(panel, page=2, page_size=2)
        self.assertEqual(data['inventory_schema'], 2)
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


    def test_native_binding_lifecycle_keeps_site_id_even_if_site_key_is_not_bound(self):
        site_name = 'old.example.test'
        alias = 'new.example.test'
        domains = [{'id': 10, 'pid': 6, 'name': site_name, 'port': 80}]
        panel = Panel([{'id': 6, 'name': site_name, 'path': '/srv/site', 'status': 1}], domains)
        created = monitor.get_site_page(panel)['sites'][0]
        self.assertEqual(created['id'], 6)
        self.assertTrue(created['canonical_domain_bound'])
        self.assertEqual(created['bound_domains'], [{'name': site_name, 'port': 80}])

        domains.append({'id': 11, 'pid': 6, 'name': alias, 'port': 80})
        added = monitor.get_site_page(panel)['sites'][0]
        self.assertEqual(len(added['bound_domains']), 2)

        domains.pop(0)
        switched = monitor.get_site_page(panel)['sites'][0]
        self.assertEqual(switched['id'], 6)
        self.assertEqual(switched['name'], site_name)
        self.assertFalse(switched['canonical_domain_bound'])
        self.assertEqual(switched['bound_domains'], [{'name': alias, 'port': 80}])
        self.assertTrue(all(call[0] != 'update' for call in panel.domain_db.calls))

    def test_bound_domains_are_one_bounded_query_for_the_current_site_page_only(self):
        panel = Panel(
            [{'id': i, 'name': f'site{i}.test', 'status': 1} for i in range(1, 4)],
            [{'id': i, 'pid': i, 'name': f'active{i}.test', 'port': 80 if i < 3 else 8443}
             for i in range(1, 4)],
        )
        page = monitor.get_site_page(panel, page=2, page_size=2)
        self.assertEqual([s['id'] for s in page['sites']], [3])
        self.assertEqual(page['sites'][0]['bound_domains'], [{'name': 'active3.test', 'port': 8443}])
        self.assertFalse(page['sites'][0]['canonical_domain_bound'])
        self.assertEqual(panel.domain_db.calls, [
            ('where', 'pid IN (?)', (3,)), ('order', 'pid asc, id asc'),
            ('limit', '0,1001'), ('field', 'id,pid,name,port'), ('select',),
        ])

    def test_empty_site_page_skips_domain_query(self):
        panel = Panel([])
        self.assertEqual(monitor.get_site_page(panel)['sites'], [])
        self.assertEqual(panel.domain_db.calls, [])

    def test_duplicate_site_id_is_rejected_before_domain_query(self):
        panel = Panel([{'id': 3, 'name': 'a.test'}, {'id': 3, 'name': 'b.test'}])
        with self.assertRaisesRegex(RuntimeError, 'duplicate site IDs'):
            monitor.get_site_page(panel)
        self.assertEqual(panel.domain_db.calls, [])

    def test_domain_response_byte_limits_preserve_realistic_names_and_fail_closed(self):
        site = [{'id': 3, 'name': 'site.test'}]
        valid = [
            {'id': 1, 'pid': 3, 'name': '*.example.test', 'port': 80},
            {'id': 2, 'pid': 3, 'name': 'مثال.ایران', 'port': 443},
            {'id': 3, 'pid': 3, 'name': 'api.example.test', 'port': 8443},
        ]
        self.assertEqual(monitor.get_site_page(Panel(site, valid))['sites'][0]['bound_domains'],
                         [{'name': item['name'], 'port': item['port']} for item in valid])
        oversized = [dict(valid[0], name='a' * (monitor.MAX_DOMAIN_NAME_BYTES + 1))]
        with self.assertRaisesRegex(RuntimeError, 'domain name exceeds'):
            monitor.get_site_page(Panel(site, oversized))
        # The bounded record count is not enough when every string is large.
        rows = [dict(valid[0], id=i, name='a' * 1020 + str(i)) for i in range(1, 300)]
        with self.assertRaisesRegex(RuntimeError, 'response text limit'):
            monitor.get_site_page(Panel(site, rows))
        bad_unicode = [dict(valid[0], name='\ud800')]
        with self.assertRaisesRegex(RuntimeError, 'domain encoding'):
            monitor.get_site_page(Panel(site, bad_unicode))

    def test_domain_query_never_silently_accepts_ambiguous_or_oversized_rows(self):
        site = [{'id': 3, 'name': 'site.test'}]
        normal = {'id': 1, 'pid': 3, 'name': 'site.test', 'port': 80}
        bad_responses = [
            [normal, dict(normal, id=2)],
            [dict(normal, name='')],
            [dict(normal, port=0)],
            [dict(normal, port='80;DROP TABLE')],
            [dict(normal, pid=4)],
            [dict(normal, name=None)],
            [dict(normal, port=65536)],
            [dict(normal, id=0)],
            [dict(normal, id='2.4')],
            [dict(normal, pid=3.9)],
            [None],
            [dict(normal, id=i, name=f'alias{i}.test') for i in range(1001)],
        ]
        for rows in bad_responses:
            with self.subTest(rows=len(rows)):
                panel = Panel(site)
                panel.domain_db.select = lambda rows=rows: rows
                with self.assertRaises(RuntimeError):
                    monitor.get_site_page(panel)
        panel = Panel(site)
        panel.domain_db.select = lambda: {'unexpected': 'type'}
        with self.assertRaisesRegex(RuntimeError, 'did not return a list'):
            monitor.get_site_page(panel)


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
        self.assertEqual(result['implicit_defaults'], [])
        self.assertEqual(self.pool.read_bytes(), before)

    def test_detect_shared_pool_drift_and_preserve_bytes(self):
        self.pool.write_text(self.pool.read_text().replace('pm.max_children = 20', 'pm.max_children = 80'), encoding='utf-8')
        before = self.pool.read_bytes()
        result = self.preview()
        self.assertEqual(result['state'], 'File Drift')
        self.assertEqual(result['changes'], [{'setting': 'pm.max_children', 'desired': 20, 'actual': 80}])
        self.assertEqual(self.pool.read_bytes(), before)

    def test_native_aapanel_omitted_max_requests_uses_php_default_zero(self):
        # aaPanel's real native PHP 8.5 php-fpm.conf puts the www pool in the
        # root file and omits pm.max_requests; PHP-FPM -tt reports default 0.
        self.pool.unlink()
        root_conf = self.root / '85' / 'etc' / 'php-fpm.conf'
        native_values = dict(EXPECTED, **{'pm.max_requests': '0'})
        root_conf.write_text('[global]\n[www]\npm = dynamic\n'
                             + ''.join(f'{k} = {v}\n' for k, v in native_values.items()
                                       if k != 'pm.max_requests')
                             + 'listen = /tmp/php-cgi-85.sock\n'
                             + 'pm.status_path = /phpfpm_85_status\n', encoding='utf-8')
        before = root_conf.read_bytes()
        result = self.preview(native_values)
        self.assertEqual(result['state'], 'File Match')
        self.assertEqual(result['changes'], [])
        self.assertEqual(result['implicit_defaults'],
                         [{'setting': 'pm.max_requests', 'value': 0, 'origin': 'PHP-FPM default'}])
        self.assertEqual(root_conf.read_bytes(), before)
        drift = self.preview(EXPECTED)
        self.assertEqual(drift['state'], 'File Drift')
        self.assertEqual(drift['changes'],
                         [{'setting': 'pm.max_requests', 'desired': 300, 'actual': 0}])
        # Do not infer defaults for mandatory pool capacity limits.
        root_conf.write_text(root_conf.read_text().replace('pm.max_children = 20\n', ''),
                             encoding='utf-8')
        self.assertEqual(self.preview(native_values)['state'], 'Needs Review')

    def test_malformed_directives_never_activate_implicit_default(self):
        # A missing '=' must not be mistaken for an omitted optional setting.
        # Syntactically malformed names and unknown pm.* keys are also unsafe.
        self.pool.unlink()
        root_conf = self.root / '85' / 'etc' / 'php-fpm.conf'
        desired_zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        valid = ('[global]\n[www]\npm = dynamic\n'
                 + ''.join(f'{k} = {v}\n' for k, v in desired_zero.items()
                           if k != 'pm.max_requests'))
        cases = (
            'pm.max_requests',
            'pm.max_requests: 300',
            'pm.max_requests: 300 = 0',
            'pm.max_requests 300 = 0',
            'pm.max_requests =',
            'pm.max_requests = nonsense',
            'pm.max_requets = 0',
            'bad bare directive',
            '[www',
        )
        for line in cases:
            with self.subTest(line=line):
                root_conf.write_text(valid + line + '\n', encoding='utf-8')
                before = root_conf.read_bytes()
                for desired in (desired_zero, EXPECTED):
                    result = self.preview(desired)
                    self.assertEqual(result['state'], 'Needs Review', result)
                    self.assertEqual(root_conf.read_bytes(), before)

    def test_mixed_case_pm_directive_is_not_treated_as_omitted(self):
        self.pool.unlink()
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        desired_zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        required = ''.join(f'{k} = {v}\n' for k, v in EXPECTED.items()
                           if k != 'pm.max_requests')
        # The lowercase pm mode plus uppercase max_requests used to produce
        # a false File Match for desired=0. The uppercase mode is separately
        # checked without relying on that pre-existing failure.
        for mode in ('pm', 'PM'):
            for key in ('PM.MAX_REQUESTS', 'Pm.Max_Requests'):
                with self.subTest(mode=mode, key=key):
                    main.write_text(f'[global]\n[www]\n{mode} = dynamic\n' + required
                                    + f'{key} = 300\nPM.STATUS_PATH = /fpm-status\n'
                                    + 'env[PATH] = /bin\nphp_admin_value[error_log] = /tmp/php.log\n',
                                    encoding='utf-8')
                    before = main.read_bytes()
                    match = self.preview(EXPECTED)
                    self.assertEqual(match['state'], 'File Match', match)
                    self.assertEqual(match['implicit_defaults'], [])
                    drift = self.preview(desired_zero)
                    self.assertEqual(drift['state'], 'File Drift', drift)
                    self.assertEqual(drift['changes'],
                                     [{'setting': 'pm.max_requests', 'desired': 0, 'actual': 300}])
                    self.assertEqual(main.read_bytes(), before)

    def test_mixed_case_duplicates_sections_and_unknown_pm_fail_closed(self):
        self.pool.unlink()
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        desired_zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        native = ('[global]\n[www]\npm = dynamic\n'
                  + ''.join(f'{k} = {v}\n' for k, v in EXPECTED.items()
                            if k != 'pm.max_requests'))
        cases = (
            native + 'pm.max_requests=0\nPM.MAX_REQUESTS=300\n',
            native + 'PM.MAX_CHILDREN=20\n',
            native + 'PM = dynamic\n',
            native + 'Pm.Unknown_Option=300\n',
            native.replace('[www]', '[WWW]'),
            native + '[WWW]\nPM.MAX_REQUESTS=300\n',
            native.replace('[www]', '[wWw]'),
        )
        for case in cases:
            with self.subTest(case=case[-75:]):
                main.write_text(case, encoding='utf-8')
                before = main.read_bytes()
                for expected in (desired_zero, EXPECTED):
                    result = self.preview(expected)
                    self.assertEqual(result['state'], 'Needs Review', result)
                    self.assertEqual(main.read_bytes(), before)

    def test_include_in_active_www_pool_fails_closed(self):
        self.pool.unlink()
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        desired_zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        required = ''.join(f'{k} = {v}\n' for k, v in EXPECTED.items()
                           if k != 'pm.max_requests')
        for included in ('pm.max_requests = 300\n',
                         'PM.MAX_REQUESTS = 300\n',
                         '[www]\npm.max_requests=300\n',
                         ''):
            with self.subTest(included=included):
                main.write_text('[global]\n[www]\npm=dynamic\n' + required
                                + 'include=php-fpm.d/*.conf\n', encoding='utf-8')
                self.pool.write_text(included, encoding='utf-8')
                before_main = main.read_bytes()
                before_pool = self.pool.read_bytes()
                result = self.preview(desired_zero)
                self.assertEqual(result['state'], 'Needs Review', result)
                self.assertEqual(main.read_bytes(), before_main)
                self.assertEqual(self.pool.read_bytes(), before_pool)

    def test_root_include_case_and_cross_file_pool_duplicates(self):
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        before_pool = self.pool.read_bytes()
        main.write_text('include=php-fpm.d/*.conf\n', encoding='utf-8')
        before_main = main.read_bytes()
        self.assertEqual(self.preview()['state'], 'File Match')
        self.assertEqual((main.read_bytes(), self.pool.read_bytes()),
                         (before_main, before_pool))
        # Unlike ordinary FPM options, the special include label is
        # case-sensitive in upstream PHP-FPM and these variants are invalid.
        for label in ('InClUdE', 'INCLUDE', 'Include'):
            for prefix in ('', '[global]\n'):
                with self.subTest(label=label, prefix=prefix):
                    main.write_text(f'{prefix}{label}=php-fpm.d/*.conf\n',
                                    encoding='utf-8')
                    before = (main.read_bytes(), self.pool.read_bytes())
                    result = self.preview()
                    self.assertEqual(result['state'], 'Needs Review', result)
                    self.assertIn('include', result['reason'].lower())
                    self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)
        # A mixed-case include must not bypass duplicate or include checks,
        # regardless of its order relative to an otherwise accepted include.
        for entries in (('include', 'InClUdE'), ('INCLUDE', 'include'),
                        ('include', 'include')):
            with self.subTest(entries=entries):
                main.write_text(''.join(f'{label}=php-fpm.d/*.conf\n'
                                        for label in entries), encoding='utf-8')
                before = (main.read_bytes(), self.pool.read_bytes())
                self.assertEqual(self.preview()['state'], 'Needs Review')
                self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)
        # Two explicit [www] pools in different files are not one supported pool.
        main.write_text('include=php-fpm.d/*.conf\n', encoding='utf-8')
        other = self.pool.parent / 'another.conf'
        other.write_text('[www]\npm=dynamic\npm.max_requests=300\n', encoding='utf-8')
        before = (main.read_bytes(), self.pool.read_bytes(), other.read_bytes())
        self.assertEqual(self.preview()['state'], 'Needs Review')
        self.assertEqual((main.read_bytes(), self.pool.read_bytes(), other.read_bytes()), before)

    def test_special_include_inside_www_and_nested_include_fail_closed(self):
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        current_pool = self.pool.read_text(encoding='utf-8')
        for label in ('include', 'InClUdE', 'INCLUDE'):
            with self.subTest(label=label, location='pool'):
                self.pool.write_text(current_pool + f'{label}=other/*.conf\n',
                                     encoding='utf-8')
                before = (main.read_bytes(), self.pool.read_bytes())
                result = self.preview()
                self.assertEqual(result['state'], 'Needs Review', result)
                self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)
            with self.subTest(label=label, location='root-www'):
                self.pool.write_text(current_pool, encoding='utf-8')
                main.write_text('[www]\npm=dynamic\n' +
                                f'{label}=php-fpm.d/*.conf\n', encoding='utf-8')
                before = (main.read_bytes(), self.pool.read_bytes())
                self.assertEqual(self.preview()['state'], 'Needs Review')
                self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)
            main.write_text('include=php-fpm.d/*.conf\n', encoding='utf-8')
        self.pool.write_text(current_pool, encoding='utf-8')

    def test_canonical_include_preserves_optional_default_and_explicit_values(self):
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        main.write_text('[global]\ninclude=php-fpm.d/*.conf\n', encoding='utf-8')
        values = ''.join(f'{key}={value}\n' for key, value in EXPECTED.items()
                         if key != 'pm.max_requests')
        zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        for declared in (None, 0, 300):
            with self.subTest(declared=declared):
                extra = '' if declared is None else f'pm.max_requests={declared}\n'
                self.pool.write_text('[www]\npm=dynamic\n' + values + extra,
                                     encoding='utf-8')
                before = (main.read_bytes(), self.pool.read_bytes())
                actual = 0 if declared is None else declared
                for desired in (zero, EXPECTED):
                    result = self.preview(desired)
                    self.assertEqual(result['state'],
                                     'File Match' if actual == int(desired['pm.max_requests'])
                                     else 'File Drift')
                    if declared is None:
                        self.assertEqual(result['implicit_defaults'], [
                            {'setting': 'pm.max_requests', 'value': 0,
                             'origin': 'PHP-FPM default'}])
                    else:
                        self.assertEqual(result['implicit_defaults'], [])
                    self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)

    def test_unscoped_included_policy_is_never_silently_ignored(self):
        main = self.root / '85' / 'etc' / 'php-fpm.conf'
        desired_zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        native = ('[global]\ninclude=php-fpm.d/*.conf\n[www]\npm=dynamic\n'
                  + ''.join(f'{k} = {v}\n' for k, v in EXPECTED.items()
                            if k != 'pm.max_requests'))
        for fragment in ('pm.max_requests = 300\n', 'PM.MAX_REQUESTS = 300\n',
                         'pm = dynamic\n', 'Pm.Unknown = 2\n'):
            with self.subTest(fragment=fragment):
                main.write_text(native, encoding='utf-8')
                self.pool.write_text(fragment, encoding='utf-8')
                before = (main.read_bytes(), self.pool.read_bytes())
                result = self.preview(desired_zero)
                self.assertEqual(result['state'], 'Needs Review', result)
                self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)
        # A canonical root include followed by an explicit pool with a genuine
        # omission is still a supported, read-only case.
        main.write_text('[global]\ninclude=php-fpm.d/*.conf\n', encoding='utf-8')
        self.pool.write_text('[www]\npm = dynamic\n'
                             + ''.join(f'{k} = {v}\n' for k, v in EXPECTED.items()
                                       if k != 'pm.max_requests'), encoding='utf-8')
        before = (main.read_bytes(), self.pool.read_bytes())
        self.assertEqual(self.preview(desired_zero)['state'], 'File Match')
        self.assertEqual(self.preview(EXPECTED)['state'], 'File Drift')
        self.assertEqual((main.read_bytes(), self.pool.read_bytes()), before)

    def test_explicit_optional_directive_retains_no_implicit_default(self):
        self.pool.unlink()
        root_conf = self.root / '85' / 'etc' / 'php-fpm.conf'
        desired_zero = dict(EXPECTED, **{'pm.max_requests': '0'})
        native = ('[global]\n[www]\npm = dynamic\n'
                  + ''.join(f'{k} = {v}\n' for k, v in desired_zero.items()
                            if k != 'pm.max_requests')
                  + 'listen = /tmp/php-cgi-85.sock\n'
                  + 'pm.status_path = /phpfpm_85_status\n'
                  + 'php_admin_value[error_log] = /tmp/php-fpm.log\n')
        for explicit in (0, 300):
            with self.subTest(explicit=explicit):
                root_conf.write_text(native + f'pm.max_requests = {explicit}\n', encoding='utf-8')
                before = root_conf.read_bytes()
                for desired in (desired_zero, EXPECTED):
                    result = self.preview(desired)
                    self.assertEqual(result['implicit_defaults'], [])
                    self.assertEqual(result['state'],
                                     'File Match' if explicit == int(desired['pm.max_requests'])
                                     else 'File Drift')
                    self.assertEqual(root_conf.read_bytes(), before)
        root_conf.write_text(native + 'pm.max_requests = 0\npm.max_requests = 0\n', encoding='utf-8')
        before = root_conf.read_bytes()
        self.assertEqual(self.preview(desired_zero)['state'], 'Needs Review')
        self.assertEqual(root_conf.read_bytes(), before)

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

    def test_nested_include_in_pool_is_not_silently_accepted(self):
        self.pool.write_text(self.pool.read_text() + 'include=other/*.conf\n', encoding='utf-8')
        result = self.preview()
        self.assertEqual(result['state'], 'Needs Review')
        self.assertIn('include', result['reason'])

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


class SharedPHPFileImpactTests(unittest.TestCase):
    """Conventional native Nginx site file links, not effective runtime."""

    class SitesQuery:
        def __init__(self, rows):
            self.rows = rows
            self.calls = []

        def order(self, key):
            assert key == 'id asc'
            return self

        def limit(self, limit):
            assert limit == '0,101'
            return self

        def field(self, fields):
            assert fields == 'id,name'
            return self

        def select(self):
            return self.rows[:101]

    class Panel:
        def __init__(self, rows):
            self.query = SharedPHPFileImpactTests.SitesQuery(rows)

        def M(self, table):
            assert table == 'sites'
            return self.query

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-fpm-impact-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.nginx = self.base / 'nginx-conf'
        self.vhosts = self.base / 'vhosts'
        self.nginx.mkdir()
        self.vhosts.mkdir()
        self.rewrites = self.base / 'rewrites'
        self.rewrites.mkdir()
        self.pool = self.base / 'php-fpm.conf'
        self.pool.write_text(
            '[global]\n[www]\npm = dynamic\n'
            'pm.max_children = 50\npm.start_servers = 5\n'
            'pm.min_spare_servers = 5\npm.max_spare_servers = 20\n'
            'listen = /tmp/php-cgi-85.sock\n', encoding='utf-8'
        )
        (self.nginx / 'enable-php-85.conf').write_text(
            'location ~ \\.php$ {\n'
            'fastcgi_pass unix:/tmp/php-cgi-85.sock;\n}\n',
            encoding='utf-8'
        )
        (self.nginx / 'enable-php-00.conf').write_text(
            'location ~ [^/]\\.php(/|$) { return 404; }\n', encoding='utf-8'
        )
        self.rows = [
            {'id': 3, 'name': 'site-a.example.test'},
            {'id': 6, 'name': 'site-b.example.test'},
            {'id': 7, 'name': 'static.example.test'},
        ]
        for site in self.rows:
            self.vhost(site['name']).write_text(
                'server {\n  server_name ' + site['name'] + ';\n'
                '  include enable-php-' +
                ('00' if site['id'] == 7 else '85') + '.conf;\n}\n',
                encoding='utf-8'
            )

    def vhost(self, name):
        return self.vhosts / (name + '.conf')

    def inspect(self, rows=None):
        return monitor.inspect_php_fpm_site_impact(
            self.Panel(self.rows if rows is None else rows),
            '85', self.pool,
            vhost_root=self.vhosts, nginx_conf_root=self.nginx,
            rewrite_root=self.rewrites,
        )

    def test_all_native_website_ids_are_scoped_by_shared_file_and_socket(self):
        files = [self.pool, self.nginx / 'enable-php-85.conf'] + [
            self.vhost(row['name']) for row in self.rows
        ]
        before = {str(p): p.read_bytes() for p in files}
        got = self.inspect()
        self.assertEqual(got['schema'], 1)
        self.assertEqual(got['state'], 'File Mapping')
        self.assertIs(got['manual_apply_eligible'], True)
        self.assertEqual(got['site_count'], 3)
        self.assertEqual(got['other_php_sites_count'], 1)
        self.assertEqual(got['matched_sites'], [
            {'id': 3, 'site_key': 'site-a.example.test'},
            {'id': 6, 'site_key': 'site-b.example.test'},
        ])
        self.assertEqual(got['unresolved_sites'], [])
        self.assertRegex(got['dependency_sha256'], r'^[0-9a-f]{64}$')
        self.assertIn('not proof of effective routing', got['note'])
        self.assertEqual({str(p): p.read_bytes() for p in files}, before)

    def test_missing_or_indirect_site_link_is_review_not_per_site_false_ownership(self):
        self.vhost('site-b.example.test').write_text(
            'server {\n include /tmp/operator-php.conf;\n}\n')
        got = self.inspect()
        self.assertEqual(got['state'], 'Needs Review')
        self.assertEqual(got['matched_sites'], [{'id': 3, 'site_key': 'site-a.example.test'}])
        self.assertEqual(got['unresolved_sites'][0]['id'], 6)
        self.assertEqual(got['site_count'], 3)

    def test_wp_fastcgi_variant_and_direct_fastcgi_override_are_ambiguous(self):
        self.vhost('site-b.example.test').write_text(
            'server {\n include enable-php-85-wpfastcgi.conf;\n}\n')
        self.assertEqual([s['id'] for s in self.inspect()['unresolved_sites']], [6])
        self.vhost('site-b.example.test').write_text(
            'server {\n include enable-php-85.conf;\n'
            ' fastcgi_pass unix:/tmp/other.sock;\n}\n')
        self.assertEqual([s['id'] for s in self.inspect()['unresolved_sites']], [6])

    def test_additional_or_indirect_includes_fail_closed_even_with_php_include(self):
        vhost = self.vhost('site-b.example.test')
        before = vhost.read_bytes()
        for added in (
            ' include /tmp/operator.conf;\n',
            ' include /tmp/fastcgi-override.conf;\n',
            ' include /tmp/cycle.conf;\n',
            ' location /x { include /tmp/nested.conf; }\n',
            ' include /tmp/symlinked.conf;\n',
        ):
            with self.subTest(added=added):
                vhost.write_text('server {\n include enable-php-85.conf;\n' + added + '}\n')
                raw = vhost.read_bytes()
                got = self.inspect()
                self.assertEqual(got['state'], 'Needs Review')
                self.assertEqual([site['id'] for site in got['unresolved_sites']], [6])
                self.assertNotIn('dependency_sha256', got)
                self.assertEqual(vhost.read_bytes(), raw, 'Monitor must not edit VHost')
        vhost.write_bytes(before)
        self.assertEqual(self.inspect()['state'], 'File Mapping')

    def test_accepted_dependency_contents_and_identity_bind_impact(self):
        baseline = self.inspect()
        vhost = self.vhost('site-a.example.test')
        vhost.write_text(vhost.read_text() + '# operator comment\n')
        updated = self.inspect()
        self.assertEqual(updated['state'], 'File Mapping')
        self.assertNotEqual(baseline['dependency_sha256'], updated['dependency_sha256'])
        include = self.nginx / 'enable-php-85.conf'
        include.write_text(include.read_text() + '# in-place include change\n')
        self.assertNotEqual(updated['dependency_sha256'], self.inspect()['dependency_sha256'])

    def test_native_fastcgi_parameter_dependency_is_bounded_and_fingerprinted(self):
        include = self.nginx / 'enable-php-85.conf'
        include.write_text(
            'location ~ \\.php$ {\n include fastcgi.conf;\n'
            ' fastcgi_pass unix:/tmp/php-cgi-85.sock;\n}\n')
        params = self.nginx / 'fastcgi.conf'
        params.write_text('fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n')
        initial = self.inspect()
        self.assertEqual(initial['state'], 'File Mapping')
        params.write_text(params.read_text() + '# changed safe parameter file\n')
        self.assertNotEqual(initial['dependency_sha256'], self.inspect()['dependency_sha256'])
        params.write_text('include dangerous.conf;\n')
        self.assertEqual(self.inspect()['state'], 'Needs Review')
        self.assertEqual(self.inspect()['site_count'], 0)
        params.unlink()
        params.symlink_to(include)
        self.assertEqual(self.inspect()['state'], 'Needs Review')

    def test_both_native_fastcgi_and_pathinfo_dependencies_are_fingerprinted(self):
        include = self.nginx / 'enable-php-85.conf'
        include.write_text(
            'location ~ [^/]\\.php(/|$) {\n'
            ' include fastcgi.conf;\n include pathinfo.conf;\n'
            ' fastcgi_pass unix:/tmp/php-cgi-85.sock;\n}\n')
        (self.nginx / 'fastcgi.conf').write_text(
            'fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n')
        pathinfo = self.nginx / 'pathinfo.conf'
        pathinfo.write_text('set $path_info "";\nfastcgi_param PATH_INFO $path_info;\n')
        first = self.inspect()
        self.assertEqual(first['state'], 'File Mapping')
        pathinfo.write_text(pathinfo.read_text() + '# benign modification\n')
        self.assertNotEqual(first['dependency_sha256'], self.inspect()['dependency_sha256'])
        pathinfo.write_text('include unexpected.conf;\n')
        self.assertEqual(self.inspect()['state'], 'Needs Review')
        pathinfo.write_text('fastcgi_pass unix:/tmp/other.sock;\n')
        self.assertEqual(self.inspect()['state'], 'Needs Review')

    def test_exact_native_rewrite_include_is_safe_bounded_and_bound_to_approval(self):
        vhost = self.vhost('site-a.example.test')
        rewrite = self.rewrites / 'site-a.example.test.conf'
        vhost.write_text(
            'server {\n include enable-php-85.conf;\n include ' + str(rewrite) + ';\n}\n')
        rewrite.write_text('location / {\n rewrite ^(.*)$ /index.php?s=$1 last;\n}\n')
        initial = self.inspect()
        self.assertEqual(initial['state'], 'File Mapping')
        self.assertEqual(len(initial['matched_sites']), 2)
        rewrite.write_text(rewrite.read_text() + '# unrelated reload-safe note\n')
        updated = self.inspect()
        self.assertEqual(updated['state'], 'File Mapping')
        self.assertNotEqual(initial['dependency_sha256'], updated['dependency_sha256'])
        for unsafe in ('include /tmp/hidden.conf;\n',
                       'fastcgi_pass unix:/tmp/hidden.sock;\n',
                       'proxy_pass http://127.0.0.1:7777;\n'):
            with self.subTest(unsafe=unsafe):
                rewrite.write_text(unsafe)
                rejected = self.inspect()
                self.assertEqual(rejected['state'], 'Needs Review')
                self.assertEqual([s['id'] for s in rejected['unresolved_sites']], [3])
                self.assertNotIn('dependency_sha256', rejected)
        rewrite.unlink()
        rewrite.symlink_to(self.pool)
        self.assertEqual(self.inspect()['state'], 'Needs Review')

    def test_consistent_upstream_policy_for_native_parameter_dependencies(self):
        include = self.nginx / 'enable-php-85.conf'
        include.write_text(
            'location ~ \\.php$ {\n include fastcgi.conf;\n'
            ' include pathinfo.conf;\n'
            ' fastcgi_pass unix:/tmp/php-cgi-85.sock;\n}\n'
        )
        params = {
            name: self.nginx / name
            for name in ('fastcgi.conf', 'pathinfo.conf')
        }
        defaults = {
            'fastcgi.conf': 'fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n',
            'pathinfo.conf': 'fastcgi_param PATH_INFO $path_info;\n',
        }
        for name, path in params.items():
            path.write_text(defaults[name])
        good = self.inspect()
        self.assertEqual(good['state'], 'File Mapping')
        routes = (
            'fastcgi_pass unix:/tmp/other.sock;',
            'proxy_pass http://backend;',
            'uwsgi_pass backend;',
            'scgi_pass backend;',
            'grpc_pass grpc://backend;',
            'memcached_pass backend;',
        )
        for name, path in params.items():
            for route in routes:
                with self.subTest(dependency=name, route=route):
                    invalid = defaults[name] + route + '\n'
                    path.write_text(invalid)
                    rejected = self.inspect()
                    self.assertEqual(rejected['state'], 'Needs Review')
                    self.assertEqual(rejected['site_count'], 0)
                    self.assertEqual(rejected['matched_sites'], [])
                    self.assertNotIn('dependency_sha256', rejected)
                    self.assertEqual(path.read_text(), invalid)
            path.write_text(defaults[name] + '# grpc_pass grpc://ignored;\n')
            accepted = self.inspect()
            self.assertEqual(accepted['state'], 'File Mapping')
            self.assertNotEqual(accepted['dependency_sha256'], good['dependency_sha256'])
            path.write_text(defaults[name])
        self.assertEqual(self.inspect()['state'], 'File Mapping')

    def test_consistent_upstream_policy_for_vhost_and_native_rewrite(self):
        vhost = self.vhost('site-a.example.test')
        original = vhost.read_text()
        rewrite = self.rewrites / 'site-a.example.test.conf'
        valid_rewrite = 'location / {\n rewrite ^(.*)$ /index.php?s=$1 last;\n}\n'
        rewrite.write_text(valid_rewrite)
        routed_vhost = original.replace(
            'include enable-php-85.conf;',
            'include enable-php-85.conf;\n include ' + str(rewrite) + ';'
        )
        vhost.write_text(routed_vhost)
        good = self.inspect()
        self.assertEqual(good['state'], 'File Mapping')
        routes = (
            'fastcgi_pass unix:/tmp/other.sock;',
            'proxy_pass http://backend;',
            'uwsgi_pass backend;',
            'scgi_pass backend;',
            'grpc_pass grpc://backend;',
            'memcached_pass backend;',
        )
        for route in routes:
            for surface, file, base in (
                ('vhost', vhost, routed_vhost),
                ('rewrite', rewrite, valid_rewrite),
            ):
                with self.subTest(surface=surface, route=route):
                    if surface == 'vhost':
                        invalid = base.replace(
                            '\n}\n', '\n location /unsupported {\n  ' + route + '\n }\n}\n', 1
                        )
                    else:
                        invalid = base + '\nlocation /unsupported {\n ' + route + '\n}\n'
                    file.write_text(invalid)
                    rejected = self.inspect()
                    self.assertEqual(rejected['state'], 'Needs Review')
                    self.assertEqual([s['id'] for s in rejected['unresolved_sites']], [3])
                    self.assertNotIn('dependency_sha256', rejected)
                    self.assertEqual(file.read_text(), invalid)
                    file.write_text(base)
        rewrite.write_text(valid_rewrite + '# memcached_pass disabled;\n')
        accepted = self.inspect()
        self.assertEqual(accepted['state'], 'File Mapping')
        self.assertNotEqual(accepted['dependency_sha256'], good['dependency_sha256'])
        rewrite.write_text(valid_rewrite)
        self.assertEqual(self.inspect()['state'], 'File Mapping')

    def test_changed_nest_dir_or_hardlinked_vhost_is_not_trusted(self):
        ordinary = self.vhost('site-a.example.test')
        hardlink = self.vhosts / 'duplicate.conf'
        hardlink.hardlink_to(ordinary)
        self.assertEqual(self.inspect()['state'], 'Needs Review')
        hardlink.unlink()
        safe = self.inspect()
        self.assertEqual(safe['state'], 'File Mapping')
        alias = self.base / 'vhost-parent-link'
        alias.symlink_to(self.vhosts, target_is_directory=True)
        linked = monitor.inspect_php_fpm_site_impact(
            self.Panel(self.rows), '85', self.pool,
            vhost_root=alias, nginx_conf_root=self.nginx, rewrite_root=self.rewrites,
        )
        self.assertEqual(linked['state'], 'Needs Review')

    def test_unknown_filename_is_review_without_escaping_vhost_root(self):
        self.rows.append({'id': 8, 'name': '../other'})
        got = self.inspect()
        self.assertEqual(got['state'], 'Needs Review')
        self.assertEqual(got['unresolved_sites'], [
            {'id': 8, 'site_key': '../other', 'reason': 'Unsupported VHost filename'}
        ])

    def test_symlinked_and_oversized_site_vhosts_are_reviewed_not_followed(self):
        site = self.vhost('site-b.example.test')
        site.unlink()
        site.symlink_to(self.pool)
        self.assertEqual([s['id'] for s in self.inspect()['unresolved_sites']], [6])
        site.unlink()
        site.write_text('x' * (monitor.MAX_NGINX_SITE_BYTES + 1))
        self.assertEqual([s['id'] for s in self.inspect()['unresolved_sites']], [6])

    def test_php_snippet_counts_every_active_fastcgi_destination_fail_closed(self):
        include = self.nginx / 'enable-php-85.conf'
        baseline = include.read_bytes()
        good = self.inspect()
        self.assertEqual(good['state'], 'File Mapping')

        routes = {
            'named-upstream': 'location /legacy-php/ {\n fastcgi_pass php_alt_backend;\n}\n',
            'variable-upstream': 'location /dynamic/ {\n fastcgi_pass $backend;\n}\n',
            'other-unix-socket': 'location /other/ {\n fastcgi_pass unix:/tmp/other.sock;\n}\n',
            'tcp-backend': 'location /legacy/ {\n fastcgi_pass 127.0.0.1:9000;\n}\n',
            'unknown-fastcgi-shape': 'location /other/ {\n fastcgi_pass unix:/tmp/other.sock extra;\n}\n',
            'proxy-upstream': 'location /proxy/ {\n proxy_pass http://127.0.0.1:8000;\n}\n',
            'uwsgi-upstream': 'location /uwsgi/ {\n uwsgi_pass backend;\n}\n',
            'grpc-upstream': 'location /grpc/ {\n grpc_pass grpc://backend;\n}\n',
        }
        for name, appended in routes.items():
            with self.subTest(route=name):
                modified = baseline + appended.encode('utf-8')
                include.write_bytes(modified)
                got = self.inspect()
                self.assertEqual(got['state'], 'Needs Review')
                self.assertEqual(got['site_count'], 0)
                self.assertEqual(got['matched_sites'], [])
                self.assertNotIn('dependency_sha256', got)
                self.assertEqual(include.read_bytes(), modified, 'Inspection is read only')

        include.write_text('location ~ \\.php$ {\n fastcgi_pass php_alt_backend;\n}\n')
        self.assertEqual(self.inspect()['state'], 'Needs Review')
        include.write_bytes(baseline + b'# fastcgi_pass php_alt_backend;\n')
        ignored_comment = self.inspect()
        self.assertEqual(ignored_comment['state'], 'File Mapping')
        self.assertNotEqual(ignored_comment['dependency_sha256'], good['dependency_sha256'])
        include.write_bytes(baseline)
        self.assertEqual(self.inspect()['state'], 'File Mapping')

    def test_nginx_hash_tokenization_preserves_active_same_line_routing(self):
        # Nginx recognizes '#' as a comment only at an argument boundary.
        # Do not discard active directives after a quoted/unquoted/escaped hash.
        safe = (
            'set $marker "tag#1"; # grpc_pass grpc://commented;\n'
            "set $single 'tag#2'; # proxy_pass http://commented;\n"
            'set $plain tag#3; # memcached_pass commented;\n'
            r'set $escaped tag\#4; # fastcgi_pass backend;' + '\n'
            '# fastcgi_pass another_backend;\n'
        )
        active = monitor._active_nginx_text(safe)
        self.assertIn('"tag#1"', active)
        self.assertIn("'tag#2'", active)
        self.assertIn("tag#3", active)
        self.assertIn(r'tag\#4', active)
        self.assertNotIn('grpc_pass', active)
        self.assertNotIn('proxy_pass', active)
        self.assertNotIn('memcached_pass', active)
        self.assertNotIn('fastcgi_pass', active)

        variants = {
            'double-quoted': 'set $marker "tag#1"; fastcgi_pass unix:/tmp/other.sock;',
            'single-quoted': "set $marker 'tag#1'; grpc_pass grpc://backend;",
            'unquoted-token': 'set $marker tag#1; proxy_pass http://backend;',
            'escaped-hash': r'set $marker tag\#1; memcached_pass backend;',
            'escaped-double-quote': 'set $marker "tag\\"#1"; grpc_pass grpc://backend;',
            'multiple-directives': 'set $marker "tag#1"; set $next "ok"; fastcgi_pass php_alt_backend;',
            'quoted-multiline': 'set $marker "line\n#literal"; grpc_pass grpc://backend;',
        }
        include = self.nginx / 'enable-php-85.conf'
        baseline = include.read_text()
        expected = self.inspect()
        self.assertEqual(expected['state'], 'File Mapping')
        for label, statement in variants.items():
            with self.subTest(variant=label):
                self.assertTrue(
                    any(name in monitor._active_nginx_text(statement) for name in
                        ('fastcgi_pass', 'proxy_pass', 'grpc_pass', 'memcached_pass'))
                )
                include.write_text(baseline + 'location /legacy {\n ' + statement + '\n}\n')
                rejected = self.inspect()
                self.assertEqual(rejected['state'], 'Needs Review')
                self.assertEqual(rejected['matched_sites'], [])
                self.assertEqual(rejected['site_count'], 0)
                self.assertNotIn('dependency_sha256', rejected)
        for ambiguous in ('set $marker "unclosed;\n',
                          "set $marker 'unclosed;\n",
                          'set $marker "ok"bad;\n',
                          'set $marker ' + '\\'):
            with self.subTest(ambiguous=ambiguous):
                include.write_text(baseline + ambiguous)
                self.assertEqual(self.inspect()['state'], 'Needs Review')
        include.write_text(baseline + '\n# fastcgi_pass another_backend;\n')
        allowed_comment = self.inspect()
        self.assertEqual(allowed_comment['state'], 'File Mapping')
        self.assertNotEqual(allowed_comment['dependency_sha256'], expected['dependency_sha256'])
        include.write_text(baseline + 'location /safe {\n set $marker "tag#1";\n}\n')
        self.assertEqual(self.inspect()['state'], 'File Mapping')

    def test_native_dependencies_keep_active_routes_after_literal_hash(self):
        php = self.nginx / 'enable-php-85.conf'
        php.write_text('location ~ \\.php$ {\n include fastcgi.conf;\n'
                       ' include pathinfo.conf;\n'
                       ' fastcgi_pass unix:/tmp/php-cgi-85.sock;\n}\n')
        params = {
            self.nginx / 'fastcgi.conf':
                'fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n',
            self.nginx / 'pathinfo.conf': 'fastcgi_param PATH_INFO $path_info;\n',
        }
        for file, data in params.items():
            file.write_text(data)
        rewrite = self.rewrites / 'site-a.example.test.conf'
        rewrite.write_text('location / {\n rewrite ^(.*)$ /index.php?s=$1 last;\n}\n')
        vhost = self.vhost('site-a.example.test')
        original_vhost = vhost.read_text()
        vhost.write_text(original_vhost.replace(
            'include enable-php-85.conf;',
            'include enable-php-85.conf;\n include ' + str(rewrite) + ';'
        ))
        files = {
            **params,
            rewrite: rewrite.read_text(),
            vhost: vhost.read_text(),
        }
        good = self.inspect()
        self.assertEqual(good['state'], 'File Mapping')
        for file, data in files.items():
            with self.subTest(file=file.name):
                statement = 'set $marker "tag#1"; grpc_pass grpc://backend;'
                if file == vhost:
                    invalid = data.replace(
                        '\n}\n',
                        '\n location /hidden {\n ' + statement + '\n }\n}\n',
                        1,
                    )
                elif file == rewrite:
                    invalid = data + '\nlocation /hidden {\n ' + statement + '\n}\n'
                else:
                    invalid = data + statement + '\n'
                file.write_text(invalid)
                rejected = self.inspect()
                self.assertEqual(rejected['state'], 'Needs Review')
                self.assertNotIn('dependency_sha256', rejected)
                self.assertEqual(file.read_text(), invalid)
                file.write_text(data)
                self.assertEqual(self.inspect()['state'], 'File Mapping')
        for file, data in files.items():
            with self.subTest(commented_file=file.name):
                file.write_text(data + '\n# grpc_pass grpc://commented;\n')
                allowed = self.inspect()
                self.assertEqual(allowed['state'], 'File Mapping')
                self.assertNotEqual(allowed['dependency_sha256'], good['dependency_sha256'])
                file.write_text(data)

    def test_socket_mismatch_invalidates_global_mapping_before_site_scan(self):
        include = self.nginx / 'enable-php-85.conf'
        include.write_text('fastcgi_pass unix:/tmp/unrelated.sock;\n')
        got = self.inspect()
        self.assertEqual(got['state'], 'Needs Review')
        self.assertIn('not mapped', got['reason'])
        self.assertEqual(got['matched_sites'], [])
        self.assertEqual(got['site_count'], 0)

    def test_missing_ambiguous_pool_socket_is_not_fabricated(self):
        self.pool.write_text(self.pool.read_text() + 'listen = /tmp/second.sock\n')
        got = self.inspect()
        self.assertEqual(got['state'], 'Needs Review')
        self.assertIn('single literal Unix socket', got['reason'])
        self.assertEqual(got['matched_sites'], [])

    def test_too_many_sites_fail_closed_instead_of_partial_shared_pool_claim(self):
        rows = [{'id': i, 'name': 's{}.example.test'.format(i)} for i in range(1, 102)]
        got = self.inspect(rows)
        self.assertEqual(got['state'], 'Needs Review')
        self.assertEqual(got['site_count'], 0)
        self.assertEqual(got['matched_sites'], [])
        self.assertIn('exceeds bounded', got['reason'])

    def test_duplicate_identity_never_returns_partial_success(self):
        duplicate = [self.rows[0], dict(self.rows[0])]
        got = self.inspect(duplicate)
        self.assertEqual(got['state'], 'Needs Review')
        self.assertEqual(got['matched_sites'], [])
        self.assertEqual(got['site_count'], 0)
        self.assertIn('Duplicate', got['reason'])

    def test_missing_site_does_not_claim_complete_mapping(self):
        self.vhost('site-b.example.test').unlink()
        got = self.inspect()
        self.assertEqual(got['state'], 'Needs Review')
        self.assertEqual([s['id'] for s in got['unresolved_sites']], [6])

    def test_alt_php_version_or_noncanonical_socket_does_not_overclaim(self):
        (self.nginx / 'enable-php-84.conf').write_text(
            'location ~ \\.php$ {\n fastcgi_pass unix:/tmp/php-cgi-84.sock;\n}\n')
        self.vhost('site-b.example.test').write_text(
            'server {\n include enable-php-84.conf;\n}\n')
        got = self.inspect()
        self.assertEqual(got['state'], 'File Mapping')
        self.assertEqual([s['id'] for s in got['matched_sites']], [3])
        self.assertEqual(got['other_php_sites_count'], 2)
        (self.nginx / 'enable-php-84.conf').write_text(
            'location ~ \\.php$ {\n fastcgi_pass unix:/tmp/php-cgi-85.sock;\n}\n')
        self.assertEqual(self.inspect()['state'], 'Needs Review')
        (self.nginx / 'enable-php-84.conf').write_text(
            'location ~ \\.php$ {\n fastcgi_pass unix:/tmp/php-cgi-84.sock;\n}\n')
        self.assertEqual(self.inspect()['state'], 'File Mapping')
        self.pool.write_text(self.pool.read_text().replace(
            '/tmp/php-cgi-85.sock', '127.0.0.1:10851'))
        self.assertEqual(self.inspect()['state'], 'Needs Review')


    def _native_qa_shapes(self):
        """The exact aaPanel 8.0.7 VHost include shapes observed in QA."""
        for site_id, site_name in ((3, 'site-a.example.test'), (6, 'site-b.example.test')):
            extension = self.vhosts / 'extension' / site_name
            extension.mkdir(parents=True)
            (extension / 'site_total.conf').write_text(
                'access_log syslog:server=unix:/tmp/site_total.sock,nohostname,tag='
                + str(site_id) + '__access site_total;\n', encoding='utf-8'
            )
            rewrite = self.rewrites / (site_name + '.conf')
            rewrite.write_text('location / {\n try_files $uri $uri/ /index.php?$args;\n}\n')
            php = ('enable-php-85-wpfastcgi.conf' if site_id == 6 else
                   'enable-php-85.conf')
            self.vhost(site_name).write_text(
                'server {\n server_name ' + site_name + ';\n'
                ' include ' + str(extension) + '/*.conf;\n'
                ' include ' + php + ';\n'
                ' include ' + str(rewrite) + ';\n}\n', encoding='utf-8'
            )
        (self.nginx / 'fastcgi.conf').write_text(
            'fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n')
        (self.nginx / 'enable-php-85-wpfastcgi.conf').write_text(
            'set $skip_cache 0;\n'
            'if ($request_method = POST) { set $skip_cache 1; }\n'
            'location ~ [^/]\\.php(/|$) {\n'
            ' try_files $uri $uri/ /index.php?$args;\n'
            ' fastcgi_pass unix:/tmp/php-cgi-85.sock;\n'
            ' include fastcgi.conf;\n'
            ' fastcgi_cache_bypass $skip_cache;\n'
            ' fastcgi_cache WORDPRESS;\n}\n'
            'location ~ /purge(/.*) { allow 127.0.0.1; deny all;\n'
            ' fastcgi_cache_purge WORDPRESS "$scheme$request_method$host$1";\n}\n',
            encoding='utf-8')

    def test_native_site_extension_glob_and_wordpress_fastcgi_mapping(self):
        self._native_qa_shapes()
        got = self.inspect()
        self.assertEqual(got['state'], 'File Mapping', got)
        self.assertIs(got['manual_apply_eligible'], False)
        self.assertEqual([s['id'] for s in got['matched_sites']], [3, 6])
        self.assertEqual(got['other_php_sites_count'], 1)
        self.assertRegex(got['dependency_sha256'], '^[0-9a-f]{64}$')
        self.assertIn('not proof of effective routing', got['note'])

    def test_native_extension_changes_invalidate_approval_identity(self):
        self._native_qa_shapes()
        good = self.inspect()
        self.assertEqual(good['state'], 'File Mapping', good)
        overlay = self.vhosts / 'extension' / 'site-a.example.test' / 'site_total.conf'
        overlay.write_text(overlay.read_text() + '\n# changed comment\n')
        self.assertNotEqual(self.inspect()['dependency_sha256'], good['dependency_sha256'])
        overlay.write_text('access_log off;\ninclude /tmp/hidden.conf;\n')
        bad = self.inspect()
        self.assertEqual(bad['state'], 'Needs Review')
        self.assertEqual([s['id'] for s in bad['unresolved_sites']], [3])
        self.assertNotIn('dependency_sha256', bad)
        overlay.write_text('access_log off;\n')
        approved = self.inspect()
        self.assertEqual(approved['state'], 'File Mapping', approved)
        (overlay.parent / 'extra.conf').write_text('error_log /tmp/qa-error.log warn;\n')
        self.assertNotEqual(self.inspect()['dependency_sha256'], approved['dependency_sha256'])
        (overlay.parent / 'extra.conf').write_text('location ~ \\.php$ { return 403; }\n')
        self.assertEqual(self.inspect()['state'], 'Needs Review')

    def test_native_extension_concurrent_change_refuses_stable_mapping(self):
        self._native_qa_shapes()
        overlay = self.vhosts / 'extension' / 'site-a.example.test' / 'site_total.conf'
        read_file = monitor._bounded_file_text
        changed = False

        def mutate_after_first_read(path, *args, **kwargs):
            nonlocal changed
            result = read_file(path, *args, **kwargs)
            if Path(path) == overlay and not changed:
                changed = True
                overlay.write_text(overlay.read_text() + '# concurrent change\n')
            return result

        with patch.object(monitor, '_bounded_file_text', side_effect=mutate_after_first_read):
            got = self.inspect()
        self.assertTrue(changed)
        self.assertEqual(got['state'], 'Needs Review', got)
        self.assertNotIn('dependency_sha256', got)
        # A fresh, stable scan is allowed to show read-only attribution.
        self.assertEqual(self.inspect()['state'], 'File Mapping')

    def test_native_extension_glob_rejects_unsafe_or_ambiguous_shapes(self):
        self._native_qa_shapes()
        extension = self.vhosts / 'extension' / 'site-a.example.test'
        overlay = extension / 'site_total.conf'
        original = overlay.read_text()
        for attack in (
            'fastcgi_pass unix:/tmp/other.sock;',
            'proxy_pass http://backend;',
            'include /tmp/other.conf;',
            'location /hidden { return 200; }',
            'access_log off; fastcgi_pass unix:/tmp/other.sock;',
        ):
            with self.subTest(attack=attack):
                overlay.write_text(attack + '\n')
                bad = self.inspect()
                self.assertEqual(bad['state'], 'Needs Review')
                self.assertNotIn('dependency_sha256', bad)
        overlay.write_text(original)
        self.assertEqual(self.inspect()['state'], 'File Mapping')
        overlay.unlink()
        overlay.symlink_to(self.pool)
        self.assertEqual(self.inspect()['state'], 'Needs Review')
        overlay.unlink()
        overlay.write_text(original)
        self.assertEqual(self.inspect()['state'], 'File Mapping')
        moved = extension.parent / 'old-extension'
        extension.rename(moved)
        extension.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.inspect()['state'], 'Needs Review')

    def test_wordpress_fastcgi_socket_or_indirect_routing_fails_closed(self):
        self._native_qa_shapes()
        php = self.nginx / 'enable-php-85-wpfastcgi.conf'
        before = php.read_text()
        self.assertEqual(self.inspect()['state'], 'File Mapping')
        for changed in (
            before.replace('/tmp/php-cgi-85.sock', '/tmp/php-cgi-81.sock'),
            before + '\nfastcgi_pass unix:/tmp/other.sock;\n',
            before + '\ninclude /tmp/unsafe.conf;\n',
            before + '\nproxy_pass http://backend;\n',
        ):
            with self.subTest(changed=changed[-40:]):
                php.write_text(changed)
                got = self.inspect()
                self.assertEqual(got['state'], 'Needs Review')
                self.assertNotIn('dependency_sha256', got)
        php.write_text(before)
        self.assertEqual(self.inspect()['state'], 'File Mapping')


if __name__ == '__main__':
    unittest.main()
