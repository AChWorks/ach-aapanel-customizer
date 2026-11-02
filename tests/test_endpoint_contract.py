"""Exercise the actual aaPanel-style entrypoint as a class, not only its helpers."""

import importlib.util
import sys
import types
import tempfile
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


class MemoryDomainQuery:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.pids = ()

    def where(self, clause, values):
        assert clause == 'pid IN (' + ','.join('?' for _ in values) + ')'
        self.pids = values
        return self

    def order(self, key):
        assert key == 'pid asc, id asc'
        return self

    def limit(self, expression):
        assert expression == '0,1001'
        return self

    def field(self, projection):
        assert projection == 'id,pid,name,port'
        return self

    def select(self):
        return [row for row in self.rows if row['pid'] in self.pids]


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = MODULE.ach_customizer_main()
        self.state_dir = tempfile.TemporaryDirectory(prefix="ach-endpoint-state-")
        self.addCleanup(self.state_dir.cleanup)
        state_path = patch.object(MODULE, "_STATE_DIR", self.state_dir.name)
        state_path.start()
        self.addCleanup(state_path.stop)

    def test_no_auth_bypassing_dynamic_check_or_mutation_entrypoint(self):
        self.assertNotIn('_check', vars(MODULE.ach_customizer_main))
        for name in vars(MODULE.ach_customizer_main):
            self.assertFalse(name.startswith(('apply_', 'reload_', 'restart_', 'update_')))
        response = self.plugin.get_overview({})
        self.assertTrue(response['status'])
        self.assertEqual(response['mode'], 'Monitor')
        self.assertIs(response['enforcement'], False)

    def test_primary_administrator_only_post_can_change_monitor_flags(self):
        flask_stub = types.ModuleType("flask")
        flask_stub.session = {"uid": 1, "login": True}
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        with patch.dict(sys.modules, {"flask": flask_stub}):
            response = self.plugin.set_control({"control": "overall", "enabled": "false", "expected_revision": "0"})
            self.assertTrue(response["status"], response)
            self.assertFalse(response["overall_enabled"])
            self.assertEqual(response["mode"], "Disabled")
            self.assertFalse(response["enforcement"])
            self.assertEqual(response["state_revision"], 1)
            self.assertTrue(response["changed"])
            self.assertEqual(self.plugin.get_overview({})["state_revision"], 1)
            duplicate = self.plugin.set_control({"control": "overall", "enabled": "false", "expected_revision": "1"})
            self.assertTrue(duplicate["status"])
            self.assertFalse(duplicate["changed"])
            self.assertEqual(duplicate["state_revision"], 1)
            flask_stub.session["uid"] = 2
            refused = self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})
            self.assertFalse(refused["status"])
            self.assertEqual(refused["stage"], "monitor_authorization")
            flask_stub.session["uid"] = 1
            flask_stub.request.method = "GET"
            refused = self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})
            self.assertEqual(refused["stage"], "monitor_authorization")
            flask_stub.request.method = "POST"
            flask_stub.session["login"] = False
            refused = self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})
            self.assertEqual(refused["stage"], "monitor_authorization")
            self.assertEqual(self.plugin.get_overview({})["state_revision"], 1)
            flask_stub.session["login"] = True
            flask_stub.has_request_context = lambda: False
            self.assertEqual(
                self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})["stage"],
                "monitor_authorization",
            )


    def test_optimistic_revision_rejection_through_authenticated_endpoint(self):
        flask_stub = types.ModuleType("flask")
        flask_stub.session = {"uid": 1, "login": True}
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        with patch.dict(sys.modules, {"flask": flask_stub}):
            first = self.plugin.set_control({
                "control": "overall", "enabled": "false", "expected_revision": "0"
            })
            self.assertTrue(first["status"], first)
            conflict = self.plugin.set_control({
                "control": "overall", "enabled": "true", "expected_revision": "0"
            })
            self.assertFalse(conflict["status"])
            self.assertEqual(conflict["stage"], "monitor_state_write")
            self.assertIn("revision changed", conflict["msg"])
            self.assertEqual(self.plugin.get_overview({})["state_revision"], 1)
            missing = self.plugin.set_control({
                "control": "overall", "enabled": "true"
            })
            self.assertFalse(missing["status"])
            self.assertIn("revision", missing["msg"])
            valid = self.plugin.set_control({
                "control": "overall", "enabled": "true", "expected_revision": "1"
            })
            self.assertTrue(valid["status"])
            self.assertEqual(valid["state_revision"], 2)

    def test_disabled_monitors_do_not_inspect_websites_or_shared_fpm(self):
        import ach_customizer_state as state

        state.set_enabled("site_inventory", False, directory=self.state_dir.name, expected_revision=0)
        with patch.object(MODULE, "get_site_page", side_effect=AssertionError("must not scan")) as sites_call:
            blocked = self.plugin.get_sites({})
            self.assertFalse(blocked["status"])
            self.assertIn("disabled", blocked["msg"])
            sites_call.assert_not_called()

        state.set_enabled("overall", False, directory=self.state_dir.name, expected_revision=1)
        with patch.object(MODULE, "preview_php_fpm", side_effect=AssertionError("must not inspect")) as fpm_call:
            blocked = self.plugin.preview_php_fpm({})
            self.assertFalse(blocked["status"])
            self.assertIn("disabled", blocked["msg"])
            fpm_call.assert_not_called()
        overview = self.plugin.get_overview({})
        self.assertFalse(overview["enforcement"])
        self.assertEqual(overview["modules"]["site_inventory"], "Disabled")
        self.assertEqual(overview["modules"]["php_fpm_file_preview"], "Disabled")

    def test_corrupted_monitor_state_is_visible_not_silently_reset(self):
        from pathlib import Path
        from ach_customizer_state import STATE_FILE
        file = Path(self.state_dir.name) / STATE_FILE
        file.write_text("{invalid")
        file.chmod(0o600)
        error = self.plugin.get_overview({})
        self.assertFalse(error["status"])
        self.assertEqual(error["stage"], "monitor_state_read")
        self.assertTrue(error["operation_id"])
        self.assertFalse(self.plugin.get_sites({})["status"])
        self.assertEqual(file.read_text(), "{invalid")

    def test_actual_entrypoint_can_query_sites_and_handles_error(self):
        query = MemorySiteQuery([
            {'id': 11, 'name': 'simple.test', 'path': '/test/simple', 'status': 1},
            {'id': 12, 'name': 'static.test', 'path': '/test/static', 'status': 0},
        ])
        panel = types.ModuleType('public')
        domains = MemoryDomainQuery([{'id': 1, 'pid': 11, 'name': 'simple.test', 'port': 80}])
        def database(table):
            assert table in ('sites', 'domain')
            return query if table == 'sites' else domains
        panel.M = database
        with patch.dict(sys.modules, {'public': panel}):
            ok = self.plugin.get_sites({'page': '1', 'page_size': '1'})
            self.assertTrue(ok['status'])
            self.assertEqual(ok['inventory_schema'], 2)
            self.assertEqual(ok['sites'][0]['name'], 'simple.test')
            self.assertTrue(ok['has_more'])
            err = self.plugin.get_sites({'page': '-1'})
            self.assertIs(err['status'], False)
            self.assertEqual(err['stage'], 'website_discovery')
            self.assertTrue(err['operation_id'])

    def test_ui_rejects_older_panel_backend_without_fabricating_empty_bindings(self):
        html = (PLUGIN_DIR / 'index.html').read_text(encoding='utf-8')
        self.assertIn('r.inventory_schema !== 2', html)
        self.assertIn('!Array.isArray(site.bound_domains)', html)
        self.assertIn('Inventory API mismatch:', html)
        self.assertNotIn('(site.bound_domains || [])', html)

    def test_inventory_tracks_added_renamed_and_removed_sites(self):
        query = MemorySiteQuery([{'id': 10, 'name': 'first.example', 'path': '/srv/one', 'status': 1}])
        panel = types.ModuleType('public')
        domains = MemoryDomainQuery([{'id': 1, 'pid': 10, 'name': 'first.example', 'port': 80}])
        panel.M = lambda table: query if table == 'sites' else domains if table == 'domain' else None
        with patch.dict(sys.modules, {'public': panel}):
            original = self.plugin.get_sites({})
            self.assertEqual([row['name'] for row in original['sites']], ['first.example'])
            query.rows.append({'id': 20, 'name': 'static.example', 'path': '/srv/static', 'status': 1})
            added = self.plugin.get_sites({})
            self.assertEqual([row['name'] for row in added['sites']], ['first.example', 'static.example'])
            query.rows[0]['name'] = 'renamed.example'
            renamed = self.plugin.get_sites({})
            self.assertEqual(renamed['sites'][0]['name'], 'renamed.example')
            self.assertFalse(renamed['sites'][0]['canonical_domain_bound'])
            self.assertEqual(renamed['sites'][0]['bound_domains'][0]['name'], 'first.example')
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
