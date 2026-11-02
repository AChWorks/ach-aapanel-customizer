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


if __name__ == '__main__':
    unittest.main()
