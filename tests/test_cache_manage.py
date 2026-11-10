"""Guarded native Cache operation ownership, recovery and failure tests."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'/'ach_customizer'))
import ach_customizer_cache_manage as cache


class CacheManageTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory(prefix='ach-cache-manage-')
        self.addCleanup(td.cleanup)
        self.root=Path(td.name)
        self.vhost=self.root/'vhost';self.vhost.mkdir()
        self.ext=self.vhost/'extension'/'qa.test';self.ext.mkdir(parents=True)
        self.nginx=self.root/'nginx';self.nginx.mkdir()
        self.state=self.root/'state';self.state.mkdir()
        self.site={'id':7,'name':'qa.test','path':str(self.root/'www'),'status':'1',
                   'bound_domains':[{'name':'qa.test','port':80}]}
        (self.root/'www').mkdir()
        (self.vhost/'qa.test.conf').write_text(
            'server {\n listen 80;\n server_name qa.test;\n root '+self.site['path']+';\n'
            ' include '+str(self.ext)+'/*.conf;\n'
            ' include enable-php-85.conf;\n}\n')
        (self.nginx/'nginx.conf').write_text(
            'events {}\nhttp {\n include '+str(self.vhost)+'/*.conf;\n}\n')
        (self.nginx/'enable-php-85.conf').write_text(
            'location ~ [^/]\\.php(/|$) {\n try_files $uri =404;\n'
            ' fastcgi_pass unix:/tmp/php-cgi-85.sock;\n'
            ' fastcgi_index index.php;\n include fastcgi.conf;\n'
            ' include pathinfo.conf;\n}\n')
        (self.nginx/'fastcgi.conf').write_text(
            'fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n')
        (self.nginx/'pathinfo.conf').write_text(
            'fastcgi_param SCRIPT_FILENAME $document_root$real_script_name;\n'
            'fastcgi_param SCRIPT_NAME $real_script_name;\n'
            'fastcgi_param PATH_INFO $path_info;\n')
        self.cache_created=False
        self.sources=cache._site_sources(self.site,'85',vhost_root=str(self.vhost),
                                         nginx_root=str(self.nginx))
        self.ref=cache.generate_reference(7,'85')
        self.native={'state':'Source Observed','zone_state':'No Direct Directive',
                     'php_version':'85','source_sha256':'a'*64,
                     'unresolved_other_sites':0,'purge_directive_seen':False}
        self.commands=[]
        self.patchers=[
            patch.object(cache,'_compatibility',side_effect=lambda site,public,**kw:
                (self.native,cache.generate_reference(
                    7,'85',cache_generation=kw.get('cache_generation')),self.sources)),
            patch.object(cache,'_path_owned',
                side_effect=lambda site_id, **kw:
                (19,23) if self.cache_created else None),
            patch.object(cache,'_create_site_cache',
                side_effect=lambda site_id: setattr(self,'cache_created',True)),
            patch.object(cache,'inspect_site_fastcgi_cache',return_value={
                'state':'Source Observed','zone_state':'Direct Zone',
                'cache_zone':'ACHFC_7','cache_directory':self.ref['cache_directory'],
                'unresolved_other_sites':0}),
        ]
        for p in self.patchers:
            p.start();self.addCleanup(p.stop)

    def runner(self,args,*,capture_output,timeout,check):
        self.commands.append(tuple(args))
        return SimpleNamespace(returncode=0,stderr=b'')

    @staticmethod
    def probe(site,*,marker=None):
        if marker not in (None,7):
            raise AssertionError('unexpected marker')
        return 200

    def kwargs(self):
        return {'data_dir':str(self.state),'vhost_root':str(self.vhost),
                'nginx_root':str(self.nginx),'runner':self.runner,'probe':self.probe}

    def preview(self):
        return cache.preview_cache_activation(
            self.site,object(),data_dir=str(self.state),
            vhost_root=str(self.vhost),nginx_root=str(self.nginx),
            probe=self.probe)

    def apply(self,**kw):
        plan=self.preview()
        return cache.manage_cache('apply',self.site,public=object(),
            expected_source=kw.get('source',plan['source_sha256']),
            expected_proposal=kw.get('proposal',plan['proposal_sha256']),
            cache_generation=kw.get('generation',plan['cache_generation']),
            approved=kw.get('approved',True),**self.kwargs())

    def test_read_only_preview_and_exact_approval(self):
        result=self.preview()
        self.assertEqual(result['state'],'Ready for Review')
        self.assertTrue(result['read_only'])
        self.assertFalse(result['runtime_verified'])
        self.assertFalse(list(self.state.iterdir()))
        with self.assertRaises(cache.CacheManageError):
            cache.manage_cache('apply',self.site,public=object(),
                approved=False,**self.kwargs())
        with self.assertRaises(cache.CacheManageError):
            cache.manage_cache('apply',self.site,public=object(),
                expected_source='b'*64,expected_proposal=result['proposal_sha256'],
                cache_generation=result['cache_generation'],
                approved=True,**self.kwargs())
        self.assertFalse((self.ext/'ach_customizer_cache_7.conf').exists())

    def test_unmanaged_recheck_never_creates_a_lock_or_recovery_state(self):
        self.assertFalse(list(self.state.iterdir()))
        before_commands = list(self.commands)
        observed = cache.manage_cache('recheck', self.site, **self.kwargs())
        self.assertEqual(observed['state'], 'Unmanaged')
        self.assertTrue(observed['read_only'])
        self.assertFalse(observed['runtime_verified'])
        self.assertFalse(list(self.state.iterdir()))
        self.assertEqual(self.commands, before_commands)

    def test_recheck_with_missing_lock_preserves_existing_recovery(self):
        applied = self.apply()
        lock = self.state/'ach_customizer.state.lock'
        self.assertTrue(lock.exists())
        lock.unlink()  # Isolated fixture for an inconsistent lock/journal pair.
        journal = self.state/cache._names(7)[2]
        before_journal = journal.read_bytes()
        before_commands = list(self.commands)
        observed = cache.manage_cache('recheck', self.site, **self.kwargs())
        self.assertEqual(observed['state'], 'Needs Review')
        self.assertEqual(observed['recovery_id'], applied['recovery_id'])
        self.assertFalse(observed['runtime_verified'])
        self.assertFalse(lock.exists())
        self.assertEqual(journal.read_bytes(), before_journal)
        self.assertEqual(self.commands, before_commands)

    def test_preflight_requires_healthy_php_route_before_operator_consent(self):
        def php_404(site, *, marker=None):
            raise cache.CacheManageError('probe','Registered PHP /index.php is not healthy')
        with self.assertRaises(cache.CacheManageError) as raised:
            cache.preview_cache_activation(
                self.site,object(),data_dir=str(self.state),
                vhost_root=str(self.vhost),nginx_root=str(self.nginx),
                probe=php_404)
        self.assertEqual(raised.exception.stage,'probe')
        self.assertFalse((self.state/cache._names(7)[2]).exists())
        self.assertFalse((self.ext/cache._names(7)[1]).exists())

    def test_generation_is_part_of_fresh_operator_approval_and_journal(self):
        a=self.preview()
        b=self.preview()
        self.assertRegex(a['cache_generation'],r'^[0-9a-f]{32}$')
        self.assertNotEqual(a['cache_generation'],b['cache_generation'])
        self.assertNotEqual(a['proposal_sha256'],b['proposal_sha256'])
        with self.assertRaises(cache.CacheManageError):
            cache.manage_cache('apply',self.site,public=object(),
                expected_source=a['source_sha256'],
                expected_proposal=a['proposal_sha256'],
                cache_generation=b['cache_generation'],
                approved=True,**self.kwargs())
        self.assertFalse((self.state/cache._names(7)[2]).exists())
        applied=cache.manage_cache('apply',self.site,public=object(),
                expected_source=a['source_sha256'],
                expected_proposal=a['proposal_sha256'],
                cache_generation=a['cache_generation'],
                approved=True,**self.kwargs())
        self.assertEqual(applied['state'],'Applied')
        fd=cache._open_state_dir(str(self.state))
        try:
            journal=cache._record_read(fd,7)
        finally:
            os.close(fd)
        self.assertEqual(journal['cache_generation'],a['cache_generation'])
        self.assertEqual(journal['proposal_sha'],a['proposal_sha256'])

    def test_apply_recheck_restore_journal_files_and_no_vendor_edit(self):
        old_vhost=(self.vhost/'qa.test.conf').read_bytes()
        old_main=(self.nginx/'nginx.conf').read_bytes()
        out=self.apply()
        self.assertEqual(out['state'],'Applied')
        self.assertTrue(out['runtime_verified'])
        self.assertFalse(out['purge_supported'])
        gid, eid, _=cache._names(7)
        self.assertIn('fastcgi_cache_path', (self.vhost/gid).read_text())
        self.assertIn('X-ACh-Cache-Site 7', (self.ext/eid).read_text())
        self.assertEqual(self.commands.count((cache.NGINX,'-s','reload','-c',str(self.nginx/'nginx.conf'))),1)
        observed=cache.manage_cache('recheck',self.site,**self.kwargs())
        self.assertEqual(observed['state'],'Applied')
        recordfd=cache._open_state_dir(str(self.state))
        try:
            record=cache._record_read(recordfd,7)
        finally:
            os.close(recordfd)
        self.assertEqual(record['phase'],'applied')
        self.assertEqual(cache.verified_cache_extension(
            self.ext,7,'qa.test',eid,(self.ext/eid).read_text(),
            state_dir=str(self.state)),record)
        self.assertEqual(cache.verified_cache_global(
            str(self.vhost),7,gid,state_dir=str(self.state)),record)
        with self.assertRaises(cache.CacheManageError):
            cache.verified_cache_extension(self.ext,7,'qa.test',eid,
                                             'location / { return 200; }',
                                             state_dir=str(self.state))
        result=cache.manage_cache('restore',self.site,approved=True,
                  recovery_id=out['recovery_id'],**self.kwargs())
        self.assertEqual(result['state'],'Restored')
        self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],'Restored')
        self.assertFalse((self.vhost/gid).exists())
        self.assertFalse((self.ext/eid).exists())
        self.assertTrue((self.vhost/(gid+'.'+out['recovery_id']+'.retained')).exists())
        self.assertTrue((self.ext/(eid+'.'+out['recovery_id']+'.retained')).exists())
        self.assertEqual(old_vhost,(self.vhost/'qa.test.conf').read_bytes())
        self.assertEqual(old_main,(self.nginx/'nginx.conf').read_bytes())
        self.assertEqual(self.commands.count((cache.NGINX,'-s','reload','-c',str(self.nginx/'nginx.conf'))),2)

    def test_reapply_after_restore_preserves_previous_recovery_journal(self):
        first=self.apply()
        old_key=next(line for line in
            (self.ext/cache._names(7)[1]).read_text().splitlines()
            if 'fastcgi_cache_key ' in line)
        cache.manage_cache('restore',self.site,approved=True,
                           recovery_id=first['recovery_id'],**self.kwargs())
        # A previously created site-owned cache directory must be proven
        # physically identical and free of mount/symlink aliases.
        with patch.object(cache,'_path_owned',return_value=(19,23)):
            second=self.apply()
            self.assertEqual(second['state'],'Applied')
            self.assertNotEqual(second['recovery_id'],first['recovery_id'])
            new_key=next(line for line in
                (self.ext/cache._names(7)[1]).read_text().splitlines()
                if 'fastcgi_cache_key ' in line)
            self.assertNotEqual(old_key,new_key)
            self.assertRegex(old_key,r'\|[0-9a-f]{32}"')
            self.assertRegex(new_key,r'\|[0-9a-f]{32}"')
            archived=self.state/(cache._names(7)[2]+'.'+first['recovery_id']+'.restored')
            self.assertTrue(archived.is_file())
            self.assertEqual(archived.stat().st_mode & 0o777,0o600)
            import json
            old=json.loads(archived.read_text())
            self.assertEqual(old['phase'],'restored')
            self.assertEqual(old['op'],first['recovery_id'])
            self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                             'Applied')
            self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
                recovery_id=second['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_recheck_detects_each_native_source_drift_without_writing(self):
        applied=self.apply()
        global_path=self.vhost/cache._names(7)[0]
        extension_path=self.ext/cache._names(7)[1]
        journal=self.state/cache._names(7)[2]
        for path, label in (
            (self.nginx/'nginx.conf','main Nginx'),
            (self.vhost/'qa.test.conf','VHost/rewrite'),
            (self.nginx/'enable-php-85.conf','PHP handler/parameters'),
            (self.nginx/'pathinfo.conf','PHP handler/parameters'),
            (self.nginx/'fastcgi.conf','PHP handler/parameters'),
        ):
            with self.subTest(path=str(path)):
                original=path.read_bytes()
                path.write_bytes(original+b'\n# native regeneration\n')
                previous=(journal.read_bytes(), global_path.read_bytes(),
                          extension_path.read_bytes(), len(self.commands))
                observed=cache.manage_cache('recheck',self.site,**self.kwargs())
                self.assertEqual(observed['state'],'Needs Review')
                self.assertFalse(observed['runtime_verified'])
                self.assertEqual(observed['recovery_id'],applied['recovery_id'])
                self.assertIn(label, observed['note'])
                self.assertEqual(previous,
                    (journal.read_bytes(),global_path.read_bytes(),
                     extension_path.read_bytes(),len(self.commands)))
                with self.assertRaisesRegex(cache.CacheManageError, 'changed since approval'):
                    cache.manage_cache('restore',self.site,approved=True,
                        recovery_id=applied['recovery_id'],**self.kwargs())
                path.write_bytes(original)
                self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                                 'Applied')
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=applied['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_recheck_detects_physical_directory_replacement_and_alias(self):
        applied=self.apply()
        journal=self.state/cache._names(7)[2]
        saved=journal.read_bytes()
        self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                         'Applied')
        for observed, label in ((lambda *_a,**_k:(19,24),'physical identity'),
                                (lambda *_a,**_k:(_ for _ in ()).throw(
                                    cache.CacheManageError('ownership','Unexpected bind mount')),
                                 'Unexpected bind mount')):
            with self.subTest(label=label):
                with patch.object(cache,'_path_owned',side_effect=observed):
                    result=cache.manage_cache('recheck',self.site,**self.kwargs())
                    self.assertEqual(result['state'],'Needs Review')
                    self.assertFalse(result['runtime_verified'])
                    self.assertEqual(result['recovery_id'],applied['recovery_id'])
                    self.assertIn(label, result['note'])
                    with self.assertRaises(cache.CacheManageError):
                        cache.manage_cache('restore',self.site,approved=True,
                            recovery_id=applied['recovery_id'],**self.kwargs())
                self.assertEqual(journal.read_bytes(),saved)
        self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                         'Applied')
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=applied['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_old_archived_generation_cannot_reactivate_before_any_write(self):
        first_plan=self.preview()
        first=cache.manage_cache('apply',self.site,public=object(),
            expected_source=first_plan['source_sha256'],
            expected_proposal=first_plan['proposal_sha256'],
            cache_generation=first_plan['cache_generation'],
            approved=True,**self.kwargs())
        cache.manage_cache('restore',self.site,approved=True,
            recovery_id=first['recovery_id'],**self.kwargs())
        second=self.apply()
        cache.manage_cache('restore',self.site,approved=True,
            recovery_id=second['recovery_id'],**self.kwargs())
        archive=self.state/(cache._names(7)[2]+'.'+first['recovery_id']+'.restored')
        self.assertTrue(archive.is_file())
        before={str(path):path.read_bytes() for path in self.state.iterdir() if path.is_file()}
        before_commands=list(self.commands)
        with self.assertRaisesRegex(cache.CacheManageError, 'already activated'):
            cache.preview_cache_activation(self.site,object(),
                cache_generation=first_plan['cache_generation'],
                vhost_root=str(self.vhost),nginx_root=str(self.nginx),
                data_dir=str(self.state),probe=self.probe)
        with self.assertRaisesRegex(cache.CacheManageError, 'already activated'):
            cache.manage_cache('apply',self.site,public=object(),
                expected_source=first_plan['source_sha256'],
                expected_proposal=first_plan['proposal_sha256'],
                cache_generation=first_plan['cache_generation'],
                approved=True,**self.kwargs())
        self.assertEqual(before,{str(path):path.read_bytes()
                                for path in self.state.iterdir() if path.is_file()})
        self.assertEqual(self.commands,before_commands)
        self.assertFalse((self.ext/cache._names(7)[1]).exists())
        third=self.apply()
        self.assertEqual(third['state'],'Applied')
        self.assertNotEqual(third['recovery_id'],second['recovery_id'])
        self.assertIn('fastcgi_cache_key', (self.ext/cache._names(7)[1]).read_text())
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=third['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_prepublication_journal_can_be_safely_reconciled_without_reload(self):
        plan=self.preview()
        reference,gb,eb=cache._fragments(7,'85',plan['cache_generation'])
        identity=self.sources
        record={
            'schema':2,'site_id':7,'site_key':'qa.test','php_version':'85',
            'op':'e'*32,'phase':'prepared','cache_identity':None,
            'cache_generation':plan['cache_generation'],
            'source_sha':plan['source_sha256'],
            'proposal_sha':plan['proposal_sha256'],
            'vhost_sha':identity['vhost_sha'],
            'main_sha':identity['main_sha'],'php_sha':identity['php_sha'],
            'global_sha':cache._hash(gb),'extension_sha':cache._hash(eb),
            'cache_directory':reference['cache_directory'],
            'probe_status':200,
        }
        fd=cache._open_state_dir(str(self.state))
        try:
            cache._record_save(fd,record)
        finally:
            os.close(fd)
        before=list(self.commands)
        result=cache.manage_cache('recheck',self.site,**self.kwargs())
        self.assertEqual(result['state'],'Needs Review')
        self.assertEqual(result['recovery_id'],'e'*32)
        restored=cache.manage_cache('restore',self.site,approved=True,
                recovery_id='e'*32,**self.kwargs())
        self.assertEqual(restored['state'],'Restored')
        self.assertFalse(restored['changed'])
        self.assertEqual(self.commands,before)
        applied=self.apply()
        self.assertEqual(applied['state'],'Applied')
        self.assertTrue(self.cache_created)
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=applied['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_stock_php_and_header_preflight_guards(self):
        def inspect():
            return cache._site_sources(self.site,'85',vhost_root=str(self.vhost),
                                       nginx_root=str(self.nginx))
        original=inspect()
        cases=(
            (self.nginx/'enable-php-85.conf', ' include pathinfo.conf;\n',
             'Native PHP handler'),
            (self.nginx/'pathinfo.conf', 'fastcgi_param PATH_INFO $path_info;',
             'PATH_INFO parameters'),
        )
        for path, needle, message in cases:
            with self.subTest(path=str(path)):
                data=path.read_text()
                self.assertIn(needle,data)
                path.write_text(data.replace(needle,''))
                with self.assertRaisesRegex(cache.CacheManageError,message):
                    inspect()
                path.write_text(data)
        self.assertEqual(inspect(),original)
        for path, addition, message in (
            (self.vhost/'qa.test.conf',' add_header Content-Security-Policy "default-src self";\n',
             'VHost response headers'),
            (self.nginx/'nginx.conf',' add_header X-Frame-Options SAMEORIGIN always;\n',
             'HTTP-level response headers'),
        ):
            with self.subTest(path=str(path)):
                data=path.read_text()
                if path.name == 'nginx.conf':
                    path.write_text(data.replace(' include '+str(self.vhost)+'/*.conf;',
                        addition+' include '+str(self.vhost)+'/*.conf;'))
                else:
                    path.write_text(data.replace('}\n',addition+'}\n',1))
                with self.assertRaisesRegex(cache.CacheManageError,message):
                    inspect()
                path.write_text(data)
        self.assertEqual(inspect(),original)

    def test_reapply_rejects_tampered_retained_source_without_mutation(self):
        first=self.apply()
        cache.manage_cache('restore',self.site,approved=True,
                           recovery_id=first['recovery_id'],**self.kwargs())
        path=self.ext/(cache._names(7)[1]+'.'+first['recovery_id']+'.retained')
        data=path.read_bytes()
        path.write_bytes(data+b'# extra\n')
        with patch.object(cache,'_path_owned',return_value=(19,23)):
            with self.assertRaises(cache.CacheManageError):
                self.preview()
        self.assertEqual(path.read_bytes(),data+b'# extra\n')
        self.assertFalse((self.ext/cache._names(7)[1]).exists())

    def test_failed_syntax_never_triggers_reload_and_restores_source(self):
        class FailAfterPublish:
            count=0
            def __call__(obj,args,*,capture_output,timeout,check):
                if '-t' in args:
                    obj.count+=1
                return SimpleNamespace(returncode=(1 if obj.count==2 else 0),stderr=b'QA')
        runner=FailAfterPublish()
        plan=self.preview()
        with self.assertRaises(cache.CacheManageError) as caught:
            cache.manage_cache('apply',self.site,public=object(),
                expected_source=plan['source_sha256'],
                expected_proposal=plan['proposal_sha256'],
                cache_generation=plan['cache_generation'],
                approved=True,runner=runner,**{
                    key:value for key,value in self.kwargs().items() if key!='runner'})
        self.assertEqual(caught.exception.stage,'recovered')
        self.assertEqual(runner.count,3)
        self.assertFalse((self.ext/cache._names(7)[1]).exists())
        self.assertFalse((self.vhost/cache._names(7)[0]).exists())
        self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                         'Recovery Required')
        restored=cache.manage_cache('restore',self.site,
            recovery_id=caught.exception.recovery_id,approved=True,**self.kwargs())
        self.assertEqual(restored['state'],'Restored')

    def test_nginx_reload_poll_is_read_only_and_bounded(self):
        failures = {'n': 0}
        def delayed_probe(site, *, marker=None):
            failures['n'] += 1
            if failures['n'] <= 2:
                raise cache.CacheManageError('probe', 'stale Nginx worker')
            return 301
        with patch.object(cache.time, 'sleep') as sleep:
            result = cache._await_php_route(
                self.site, marker=7, expected_status=301, probe=delayed_probe)
        self.assertEqual(result, 301)
        self.assertEqual(failures['n'], 3)
        self.assertEqual(sleep.call_count, 2)
        def never(site, *, marker=None):
            raise cache.CacheManageError('probe','worker not yet updated')
        with patch.object(cache.time, 'sleep') as sleep:
            with self.assertRaises(cache.CacheManageError):
                cache._await_php_route(
                    self.site, marker=None, expected_status=301, probe=never)
        self.assertEqual(sleep.call_count, 8)

    def test_loopback_php_probe_rejects_error_pages_and_fake_marker(self):
        class Response:
            def __init__(self,code,marker=None,cache_status=None):
                self.status=code
                self.fields={'X-ACh-Cache-Site':marker,
                             'X-ACh-Cache':cache_status}
            def getheader(self,name):return self.fields.get(name)
            def read(self,count):return b''
        class Connection:
            def __init__(self,response):self.response=response
            def request(self,*args,**kw):
                self.requested=(args,kw)
            def getresponse(self):return self.response
            def close(self):pass
        cases=((404,None,None,False),
               (404,'7','BYPASS',False),
               (301,'7',None,False),
               (200,'7','BYPASS',True),
               (301,'7','MISS',True))
        for code,marker,upstream,accepted in cases:
            with self.subTest(code=code,marker=marker,upstream=upstream):
                connection=Connection(Response(code,marker,upstream))
                with patch.object(cache.http.client,'HTTPConnection',
                                  return_value=connection):
                    if accepted:
                        self.assertEqual(cache._probe(self.site,marker=7),code)
                    else:
                        with self.assertRaises(cache.CacheManageError):
                            cache._probe(self.site,marker=7)
                self.assertEqual(connection.requested[0][:2],
                                 ('HEAD','/index.php'))
                self.assertEqual(connection.requested[1]['headers']['Host'],
                                 'qa.test')

    def test_unowned_existing_config_refused_without_writes(self):
        path=self.ext/cache._names(7)[1]
        path.write_text('location ~ \\.php$ { return 200; }')
        with self.assertRaises(Exception):
            self.preview()
        self.assertEqual(path.read_text(),'location ~ \\.php$ { return 200; }')
        self.assertEqual(list(self.state.iterdir()),[])

    def test_real_source_audit_recognizes_only_journal_owned_cache(self):
        import ach_customizer_cache_audit as audit
        class Query:
            def order(self, value): return self
            def limit(self, value): return self
            def field(self, value): return self
            def select(self): return [{'id': 7, 'name': 'qa.test'}]
        class Panel:
            def get_webserver(self): return 'nginx'
            def get_panel_version(self): return '8.0.7'
            def M(self, what): return Query()
        def inspect():
            return audit.inspect_site_fastcgi_cache(
                Panel(), 7, 'qa.test', vhost_root=str(self.vhost),
                nginx_root=str(self.nginx),
                rewrite_root=str(self.root/'rewrite'))
        with patch.object(cache, 'DATA_DIR', str(self.state)):
            before=inspect()
            self.assertEqual(before['zone_state'], 'No Direct Directive', before)
            self.assertEqual(before['state'], 'Source Observed', before)
            applied=self.apply()
            observed=inspect()
            self.assertEqual(observed['state'], 'Source Observed', observed)
            self.assertEqual(observed['zone_state'], 'Direct Zone', observed)
            self.assertEqual(observed['cache_zone'], 'ACHFC_7')
            self.assertEqual(observed['cache_directory'], self.ref['cache_directory'])
            self.assertEqual(observed['other_sites_same_zone'], [])
            self.assertEqual(observed['other_sites_same_directory'], [])
            self.assertNotEqual(before['source_sha256'],observed['source_sha256'])
            self.assertFalse(observed['cache_safe_verified'])
            path=self.vhost/cache._names(7)[0]
            source=path.read_bytes()
            path.write_bytes(source+b'fastcgi_cache_path /tmp/rogue keys_zone=BAD:10m;\n')
            self.assertEqual(inspect()['state'],'Needs Review')
            path.write_bytes(source)
            restored=cache.manage_cache('restore',self.site,approved=True,
                        recovery_id=applied['recovery_id'],**self.kwargs())
            self.assertEqual(restored['state'],'Restored')
            after=inspect()
            self.assertEqual(after['state'],'Source Observed',after)
            self.assertEqual(after['zone_state'],'No Direct Directive',after)

    def test_mutated_journal_and_wrong_recovery_do_not_modify_sources(self):
        applied=self.apply()
        with self.assertRaises(cache.CacheManageError):
            cache.manage_cache('restore',self.site,approved=True,
                recovery_id='f'*32,**self.kwargs())
        self.assertTrue((self.ext/cache._names(7)[1]).exists())
        journal=self.state/cache._names(7)[2]
        journal.write_text('{"broken":true}')
        journal.chmod(0o600)
        with self.assertRaises(cache.CacheManageError):
            cache.manage_cache('restore',self.site,approved=True,
                recovery_id=applied['recovery_id'],**self.kwargs())
        self.assertTrue((self.ext/cache._names(7)[1]).exists())


if __name__=='__main__':
    unittest.main()
