"""Exercise the actual aaPanel-style entrypoint as a class, not only its helpers."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parent.parent / 'plugin' / 'ach_customizer'
SPEC = importlib.util.spec_from_file_location('ach_customizer_main', PLUGIN_DIR / 'ach_customizer_main.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MemorySiteQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.count = 0

    def order(self, key):
        assert key == 'id asc'
        return self

    def limit(self, expression):
        self.start, self.count = map(int, expression.split(','))
        return self

    def field(self, projection):
        assert projection == 'id,name,path,status'
        return self

    def select(self):
        return self.rows[self.start:self.start + self.count]


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = MODULE.ach_customizer_main()

    def test_no_auth_bypassing_dynamic_check_or_mutation_entrypoint(self):
        self.assertNotIn('_check', vars(MODULE.ach_customizer_main))
        for name in vars(MODULE.ach_customizer_main):
            self.assertFalse(name.startswith(('apply_', 'reload_', 'restart_', 'update_')))
        response = self.plugin.get_overview({})
        self.assertTrue(response['status'])
        self.assertEqual(response['mode'], 'Monitor')
        self.assertIs(response['enforcement'], False)

    def test_actual_entrypoint_can_query_sites_and_handles_error(self):
        query = MemorySiteQuery([
            {'id': 11, 'name': 'simple.test', 'path': '/test/simple', 'status': 1},
            {'id': 12, 'name': 'static.test', 'path': '/test/static', 'status': 0},
        ])
        panel = types.ModuleType('public')
        def database(table):
            assert table == 'sites'
            return query
        panel.M = database
        with patch.dict(sys.modules, {'public': panel}):
            ok = self.plugin.get_sites({'page': '1', 'page_size': '1'})
            self.assertTrue(ok['status'])
            self.assertEqual(ok['sites'][0]['name'], 'simple.test')
            self.assertTrue(ok['has_more'])
            err = self.plugin.get_sites({'page': '-1'})
            self.assertIs(err['status'], False)
            self.assertEqual(err['stage'], 'website_discovery')
            self.assertTrue(err['operation_id'])

    def test_inventory_tracks_added_renamed_and_removed_sites(self):
        query = MemorySiteQuery([{'id': 10, 'name': 'first.example', 'path': '/srv/one', 'status': 1}])
        panel = types.ModuleType('public')
        panel.M = lambda table: query if table == 'sites' else None
        with patch.dict(sys.modules, {'public': panel}):
            original = self.plugin.get_sites({})
            self.assertEqual([row['name'] for row in original['sites']], ['first.example'])
            query.rows.append({'id': 20, 'name': 'static.example', 'path': '/srv/static', 'status': 1})
            added = self.plugin.get_sites({})
            self.assertEqual([row['name'] for row in added['sites']], ['first.example', 'static.example'])
            query.rows[0]['name'] = 'renamed.example'
            renamed = self.plugin.get_sites({})
            self.assertEqual(renamed['sites'][0]['name'], 'renamed.example')
            query.rows.pop(0)
            removed = self.plugin.get_sites({})
            self.assertEqual([row['id'] for row in removed['sites']], [20])

    def test_fpm_preview_is_read_only_and_reports_unsupported_layout(self):
        payload = dict(php_version='85', max_children='20', start_servers='5',
                       min_spare_servers='5', max_spare_servers='10', max_requests='300')
        with patch.object(MODULE, 'preview_php_fpm', return_value={'state': 'Needs Review', 'scope': 'shared_service'}) as call:
            result = self.plugin.preview_php_fpm(payload)
        self.assertTrue(result['status'])
        self.assertEqual(result['scope'], 'shared_service')
        self.assertTrue(result['operation_id'])
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0], '/www/server/php')
        broken = self.plugin.preview_php_fpm(dict(payload, php_version='../etc'))
        self.assertIs(broken['status'], False)
        self.assertEqual(broken['stage'], 'php_fpm_file_preview')


if __name__ == '__main__':
    unittest.main()
