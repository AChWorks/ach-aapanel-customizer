"""Native primary-admin authorization and per-site binding for Cache controls."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'/'ach_customizer'))
import ach_customizer_main as main
import ach_customizer_cache_manage as manager


class CacheEndpointTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory(prefix='ach-cache-endpoint-')
        self.addCleanup(td.cleanup)
        state=patch.object(main,'_STATE_DIR',td.name)
        state.start()
        self.addCleanup(state.stop)
        self.plugin=main.ach_customizer_main()
        self.site={'id':7,'name':'qa.test','path':'/www/wwwroot/qa.test','status':'1',
                   'bound_domains':[{'name':'qa.test','port':80}]}
        self.checks=0

    @staticmethod
    def flask(*,uid=1,method='POST',temporary=False):
        module=types.ModuleType('flask')
        module.has_request_context=lambda:True
        module.request=types.SimpleNamespace(method=method)
        module.session={'login':True,'uid':uid}
        if temporary: module.session['tmp_login_id']='temp'
        return module

    def selected(self,*unused):
        self.checks+=1
        def current():
            self.checks+=1
            return dict(self.site)
        return object(),dict(self.site),current

    def args(self):
        return {'site_id':'7','expected_site_key':'qa.test',
                'expected_site_snapshot':'[7,"qa.test","/www/wwwroot/qa.test","1",[["qa.test",80]]]'}

    def test_primary_admin_post_gate_runs_before_native_site_inspection(self):
        for kwargs in ({'uid':2},{'method':'GET'},{'temporary':True}):
            with self.subTest(kwargs=kwargs):
                self.checks=0
                with patch.dict(sys.modules,{'flask':self.flask(**kwargs)}),\
                     patch.object(self.plugin,'_require_enabled'),\
                     patch.object(self.plugin,'_selected_native_website',
                                  side_effect=self.selected) as pick,\
                     patch.object(manager,'manage_cache') as operation,\
                     patch.object(manager,'preview_cache_activation') as readiness:
                    for endpoint, payload in (
                         ('preview_cache_activation',self.args()),
                         ('manage_cache_policy',{**self.args(),'cache_action':'apply','approved':'true'}),
                         ('manage_cache_policy',{**self.args(),'cache_action':'clear_files',
                                                 'approved':'true','recovery_id':'f'*32}),
                         ('manage_cache_policy',{**self.args(),'cache_action':'clear_url',
                                                 'cache_url_path':'/news/', 'approved':'true',
                                                 'recovery_id':'f'*32})):
                        result=getattr(self.plugin,endpoint)(payload)
                        self.assertFalse(result['status'],result)
                        self.assertEqual(result['stage'],'cache_authorization')
                    pick.assert_not_called()
                    operation.assert_not_called()
                    readiness.assert_not_called()
                    self.assertEqual(self.checks,0)

    def test_native_site_identity_and_explicit_reviewed_fields_are_forwarded(self):
        sample={'schema':1,'state':'Applied','changed':True,'site_id':7,
                'recovery_id':'f'*32,'runtime_verified':True,'purge_supported':False}
        with patch.dict(sys.modules,{'flask':self.flask()}),\
             patch.object(self.plugin,'_require_enabled'),\
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected),\
             patch.object(manager,'manage_cache',return_value=sample) as operation:
            result=self.plugin.manage_cache_policy({
                **self.args(),'cache_action':'apply',
                'expected_source_sha256':'a'*64,
                'expected_proposal_sha256':'b'*64,
                'cache_generation':'c'*32,
                'approved':'true',
                'cache_root':'/tmp/untrusted',
                'site_key':'different.test'})
            self.assertTrue(result['status'],result)
            self.assertEqual(result['state'],'Applied')
            self.assertEqual(operation.call_count,1)
            args,kw=operation.call_args
            self.assertEqual(args[0],'apply')
            self.assertEqual(args[1],self.site)
            self.assertEqual(kw['approved'],True)
            self.assertEqual(kw['expected_source'],'a'*64)
            self.assertEqual(kw['expected_proposal'],'b'*64)
            self.assertEqual(kw['cache_generation'],'c'*32)
            self.assertNotIn('cache_root',kw)
            self.assertNotIn('site_key',kw)

    def test_site_cache_clear_uses_primary_admin_site_snapshot_and_no_paths(self):
        sample={'schema':1,'state':'Applied','changed':True,'site_id':7,
                'site_key':'qa.test','journal_phase':'applied',
                'recovery_id':'f'*32,'runtime_verified':True,
                'purge_supported':False,'cache_files_removed':2}
        with patch.dict(sys.modules,{'flask':self.flask()}), \
             patch.object(self.plugin,'_require_enabled'), \
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected), \
             patch.object(manager,'manage_cache',return_value=sample) as operation:
            result=self.plugin.manage_cache_policy({
                **self.args(), 'cache_action':'clear_files',
                'recovery_id':'f'*32,'approved':'true',
                'cache_directory':'/etc','cache_root':'/tmp','purge_all':'true'})
            self.assertTrue(result['status'],result)
            self.assertEqual(result['cache_files_removed'],2)
            self.assertEqual(operation.call_args.args[:2],('clear_files',self.site))
            kwargs=operation.call_args.kwargs
            self.assertEqual(kwargs['recovery_id'],'f'*32)
            self.assertEqual(kwargs['approved'],True)
            self.assertNotIn('cache_root',kwargs)
            self.assertNotIn('cache_directory',kwargs)
            self.assertNotIn('purge_all',kwargs)
            self.assertEqual(self.checks,2)

    def test_exact_site_url_clear_passes_only_canonical_path_and_recovery(self):
        sample={'schema':1,'state':'Applied','changed':True,'site_id':7,
                'site_key':'qa.test','journal_phase':'applied',
                'recovery_id':'f'*32,'runtime_verified':True,
                'purge_supported':False,'cache_files_removed':1,
                'cache_url_path':'/news/'}
        with patch.dict(sys.modules,{'flask':self.flask()}), \
             patch.object(self.plugin,'_require_enabled'), \
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected), \
             patch.object(manager,'manage_cache',return_value=sample) as operation:
            result=self.plugin.manage_cache_policy({
                **self.args(),'cache_action':'clear_url','cache_url_path':'/news/',
                'recovery_id':'f'*32,'approved':'true',
                'site_key':'other.invalid', 'cache_root':'/etc',
                'source_path':'/etc/passwd','purge_all':'true'})
            self.assertTrue(result['status'],result)
            self.assertEqual(result['cache_url_path'],'/news/')
            self.assertEqual(operation.call_args.args,('clear_url',self.site,operation.call_args.args[2]))
            self.assertEqual(operation.call_args.kwargs['cache_url_path'],'/news/')
            self.assertEqual(operation.call_args.kwargs['recovery_id'],'f'*32)
            self.assertTrue(operation.call_args.kwargs['approved'])
            self.assertNotIn('cache_root',operation.call_args.kwargs)
            self.assertNotIn('source_path',operation.call_args.kwargs)
            self.assertNotIn('purge_all',operation.call_args.kwargs)
            self.assertEqual(self.checks,2)

    def test_native_route_action_is_not_reused_as_cache_operation(self):
        sample={'schema':1,'state':'Unmanaged','site_id':7,
                'recovery_id':None,'read_only':True,'runtime_verified':False,
                'purge_supported':False}
        with patch.dict(sys.modules,{'flask':self.flask()}),\
             patch.object(self.plugin,'_require_enabled'),\
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected),\
             patch.object(manager,'manage_cache',return_value=sample) as operation:
            valid=self.plugin.manage_cache_policy(
                {**self.args(),'cache_action':'recheck'})
            self.assertTrue(valid['status'],valid)
            self.assertEqual(valid['state'],'Unmanaged')
            self.assertEqual(operation.call_count,1)
            self.assertEqual(operation.call_args.args[0],'recheck')
            operation.reset_mock()
            # The aaPanel router rejects a posted 'action' before our method.
            # Even direct invocation must not interpret the obsolete form key.
            invalid=self.plugin.manage_cache_policy(
                {**self.args(),'action':'recheck'})
            self.assertFalse(invalid['status'])
            self.assertEqual(invalid['stage'],'cache_manage')
            operation.assert_not_called()

    def test_uncertain_cache_operation_preserves_distinct_diagnostic_recovery_id(self):
        op='c'*32
        problem=manager.CacheManageError(
            'uncertain', 'Nginx reload not yet observed', recovery_id=op)
        entries=[]
        with patch.dict(sys.modules,{'flask':self.flask()}),\
             patch.object(self.plugin,'_require_enabled'),\
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected),\
             patch.object(manager,'manage_cache',side_effect=problem),\
             patch.object(main,'append_activity',side_effect=lambda data,entry:entries.append(entry) or True):
            reply=self.plugin.manage_cache_policy(
                {**self.args(),'cache_action':'apply','approved':'true'})
            self.assertFalse(reply['status'])
            self.assertEqual(reply['stage'],'cache_manage')
            self.assertEqual(reply['recovery_id'],op)
            self.assertNotEqual(reply['operation_id'],op)
            self.assertEqual(reply['request_id'],reply['operation_id'])
            self.assertEqual(len(entries),1)
            self.assertEqual(entries[0]['recovery_id'],op)
            self.assertEqual(entries[0]['operation_id'],reply['operation_id'])
            self.assertEqual(entries[0]['outcome'],'failed')

    def test_readiness_requires_stable_native_identity(self):
        plan={'schema':1,'state':'Ready for Review','site_id':7,
              'site_key':'qa.test','read_only':True}
        with patch.dict(sys.modules,{'flask':self.flask()}),\
             patch.object(self.plugin,'_require_enabled'),\
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected),\
             patch.object(manager,'preview_cache_activation',return_value=plan) as preview:
            result=self.plugin.preview_cache_activation(self.args())
            self.assertTrue(result['status'],result)
            self.assertEqual(result['state'],'Ready for Review')
            self.assertEqual(preview.call_count,1)

    def test_native_missing_extension_hint_is_read_only_preview_only(self):
        cause=manager.CacheManageError('compatibility',
            'Native aaPanel site VHost is missing the per-site extension include.',
            reason_code='native_extension_include_missing')
        with patch.dict(sys.modules,{'flask':self.flask()}),\
             patch.object(self.plugin,'_require_enabled'),\
             patch.object(self.plugin,'_selected_native_website',
                          side_effect=self.selected),\
             patch.object(manager,'preview_cache_activation',side_effect=cause):
            failed=self.plugin.preview_cache_activation(self.args())
        self.assertFalse(failed['status'])
        self.assertEqual(failed['stage'],'cache_activation_preview')
        self.assertEqual(failed['reason_code'],'native_extension_include_missing')
        self.assertNotIn('recovery_id',failed)
        self.assertNotIn('apply_supported',failed)
        # It is diagnostic metadata, never passed to the mutating route.
        other=self.plugin._fail('cache_manage',cause,'a'*32)
        self.assertNotIn('reason_code',other)


    def test_wordpress_one_click_has_native_admin_gate_and_exact_site_binding(self):
        import ach_customizer_cache_wordpress as bridge
        answer = {"schema": 1, "state": "Connected", "site_id": 7,
                  "site_key": "qa.test", "recovery_id": "f" * 32}
        for auth in ({"uid": 2}, {"method": "GET"}, {"temporary": True}):
            with self.subTest(auth=auth), \
                 patch.dict(sys.modules, {"flask": self.flask(**auth)}), \
                 patch.object(self.plugin, "_require_enabled"), \
                 patch.object(self.plugin, "_selected_native_website") as choose, \
                 patch.object(bridge, "setup") as setup:
                response = self.plugin.manage_wordpress_cache({
                    **self.args(), "wordpress_cache_action": "setup", "approved": "true"})
                self.assertFalse(response["status"])
                choose.assert_not_called()
                setup.assert_not_called()
        with patch.dict(sys.modules, {"flask": self.flask()}), \
             patch.object(self.plugin, "_require_enabled"), \
             patch.object(self.plugin, "_selected_native_website", side_effect=self.selected), \
             patch.object(bridge, "setup", return_value=answer) as setup:
            response = self.plugin.manage_wordpress_cache({
                **self.args(), "wordpress_cache_action": "setup", "approved": "true",
                "wp_root": "/etc", "cache_directory": "/www/server/fastcgi_cache",
                "site_id_override": 999, "php_version": "unsafe"})
            self.assertTrue(response["status"], response)
            self.assertEqual(response["state"], "Connected")
            setup.assert_called_once()
            self.assertEqual(setup.call_args.args[0], self.site)

    def test_wordpress_one_click_requires_selected_action_not_duplicate_checkbox(self):
        import ach_customizer_cache_wordpress as bridge
        with patch.dict(sys.modules, {"flask": self.flask()}), \
             patch.object(self.plugin, "_require_enabled"), \
             patch.object(self.plugin, "_selected_native_website", side_effect=self.selected) as choose, \
             patch.object(bridge, "setup") as setup:
            for payload in (
                {**self.args(), "wordpress_cache_action": "setup", "approved": "false"},
                {**self.args(), "wordpress_cache_action": "unknown", "approved": "true"},
            ):
                self.assertFalse(self.plugin.manage_wordpress_cache(payload)["status"])
            choose.assert_not_called()
            setup.assert_not_called()

    def test_wordpress_setup_failures_report_recovery_and_precise_step(self):
        import ach_customizer_cache_wordpress as bridge
        problem = bridge.WordpressCacheError("wordpress", "Site .user.ini was modified",
                                              recovery_id="f" * 32)
        with patch.dict(sys.modules, {"flask": self.flask()}), \
             patch.object(self.plugin, "_require_enabled"), \
             patch.object(self.plugin, "_selected_native_website", side_effect=self.selected), \
             patch.object(bridge, "setup", side_effect=problem):
            response = self.plugin.manage_wordpress_cache({
                **self.args(), "wordpress_cache_action": "setup", "approved": "true"})
            self.assertFalse(response["status"])
            self.assertEqual(response["stage"], "wordpress_cache_setup")
            self.assertIn("Site .user.ini", response["msg"])
            self.assertEqual(response["recovery_id"], "f" * 32)

if __name__=='__main__':
    unittest.main()
