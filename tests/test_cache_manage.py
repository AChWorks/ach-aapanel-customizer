"""Guarded native Cache operation ownership, recovery and failure tests."""
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'/'ach_customizer'))
import ach_customizer_cache_manage as cache


REAL_COMPATIBILITY = cache._compatibility


class CachePeerDirectoryIdentityTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory(prefix='ach-cache-peer-')
        self.addCleanup(td.cleanup)
        self.base=Path(td.name)
        self.selected=self.base/'selected'
        self.selected.mkdir()
        self.distinct=self.base/'separate'
        self.distinct.mkdir()
        s=os.stat(self.selected)
        self.identity=(s.st_dev,s.st_ino)

    def check(self, peer_path):
        return cache._verify_cache_peer_isolation(
            str(self.selected),self.identity,
            [{'id':8,'directory':str(peer_path)}])

    def test_distinct_verified_peer_directory_is_supported(self):
        report=self.check(self.distinct)
        self.assertEqual(len(report[0]),1)
        self.assertEqual(report[0][0][0],8)
        self.assertEqual(report[0][0][1],str(self.distinct))
        self.assertNotEqual(report[0][0][2][-1],self.identity)
        self.assertEqual(report[1],())

    def test_same_directory_canonical_path_is_rejected(self):
        with self.assertRaisesRegex(cache.CacheManageError,'physically overlap'):
            self.check(self.selected)

    def test_external_bind_mount_identity_alias_is_rejected(self):
        # A Linux bind mount reports the source directory's dev/inode at
        # its otherwise different canonical destination. Model that exact
        # kernel identity relation without requiring mount privileges.
        actual=cache._cache_directory_identity_chain
        def bound(path):
            chain=actual(path)
            return chain[:-1]+(self.identity,) if path==str(self.distinct) else chain
        with patch.object(cache,'_cache_directory_identity_chain',
                          side_effect=bound):
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'physically overlap'):
                self.check(self.distinct)

    def _selected_cache_object(self):
        first = self.selected/'8'
        second = first/'aa'
        second.mkdir(parents=True,exist_ok=True)
        leaf = second/('b'*29+'aa8')
        leaf.write_bytes(b'selected-cache-object-unmodified')
        return first, second, leaf

    def test_nested_peer_bind_directory_is_rejected_without_changing_cache(self):
        first, second, leaf = self._selected_cache_object()
        from hashlib import sha256
        before = sha256(leaf.read_bytes()).hexdigest()
        fs=os.stat(first)
        # Actual bind mount of selected/8 to peer/8 is exercised in
        # isolated native QA; the local unit focuses on the same dev/inode.
        nested=((str(self.distinct),str(self.distinct/'8'),'814',
                (fs.st_dev,fs.st_ino)),)
        with patch.object(cache,'_cache_peer_mounts',return_value=nested):
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'subtrees physically overlap'):
                self.check(self.distinct)
        self.assertEqual(sha256(leaf.read_bytes()).hexdigest(),before)

    def test_nested_peer_bind_cache_file_is_rejected(self):
        first, second, leaf = self._selected_cache_object()
        fs=os.stat(leaf)
        nested=((str(self.distinct),str(self.distinct/'8'/'aa'/leaf.name),'816',
                (fs.st_dev,fs.st_ino)),)
        with patch.object(cache,'_cache_peer_mounts',return_value=nested):
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'subtrees physically overlap'):
                self.check(self.distinct)
        self.assertEqual(leaf.read_bytes(),b'selected-cache-object-unmodified')

    def test_first_level_symlink_to_selected_cache_is_denied_unchanged(self):
        first, _, leaf = self._selected_cache_object()
        import hashlib
        before = hashlib.sha256(leaf.read_bytes()).hexdigest()
        (self.distinct/'8').symlink_to(first, target_is_directory=True)
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'subtrees physically overlap'):
            self.check(self.distinct)
        self.assertEqual(hashlib.sha256(leaf.read_bytes()).hexdigest(), before)

    def test_second_level_symlink_to_selected_cache_is_denied_unchanged(self):
        _, second, leaf = self._selected_cache_object()
        before = leaf.read_bytes()
        (self.distinct/'8').mkdir()
        (self.distinct/'8'/'aa').symlink_to(second, target_is_directory=True)
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'subtrees physically overlap'):
            self.check(self.distinct)
        self.assertEqual(leaf.read_bytes(), before)

    def test_individual_cache_file_symlink_is_denied_unchanged(self):
        _, _, leaf = self._selected_cache_object()
        before = leaf.read_bytes()
        peer_file = self.distinct/'8'/'aa'/leaf.name
        peer_file.parent.mkdir(parents=True)
        peer_file.symlink_to(leaf)
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'subtrees physically overlap'):
            self.check(self.distinct)
        self.assertEqual(leaf.read_bytes(), before)

    def test_multi_hop_symlink_under_independent_parent_is_denied(self):
        _, second, leaf = self._selected_cache_object()
        outer = self.base/'external-cache-directory'
        outer.mkdir()
        (outer/'aa').symlink_to(second, target_is_directory=True)
        (self.distinct/'8').symlink_to(outer, target_is_directory=True)
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'subtrees physically overlap'):
            self.check(self.distinct)
        self.assertEqual(leaf.read_bytes(), b'selected-cache-object-unmodified')

    def test_independent_peer_symlink_target_remains_supported(self):
        _, _, leaf = self._selected_cache_object()
        independent = self.base/'independent-cache-content'
        (independent/'aa').mkdir(parents=True)
        (independent/'aa'/leaf.name).write_bytes(b'peer-only-cache-content')
        (self.distinct/'8').symlink_to(independent, target_is_directory=True)
        result = self.check(self.distinct)
        self.assertEqual(result[1], ())  # No bind mounts.
        self.assertEqual(len(result[2]), 1)
        self.assertEqual(result[2][0][1], '8')
        self.assertEqual(leaf.read_bytes(), b'selected-cache-object-unmodified')

    def test_unresolved_symlink_peer_target_is_non_authorizing(self):
        (self.distinct/'8').symlink_to(self.base/'absent-physical-cache',
                                      target_is_directory=True)
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'physical separation is unverified'):
            self.check(self.distinct)

    def test_symlink_swap_changes_preflight_identity_without_deletion(self):
        _, _, leaf = self._selected_cache_object()
        one = self.base/'independent-one'
        two = self.base/'independent-two'
        one.mkdir(); two.mkdir()
        link = self.distinct/'8'
        link.symlink_to(one, target_is_directory=True)
        old = self.check(self.distinct)
        link.unlink()
        link.symlink_to(two, target_is_directory=True)
        new = self.check(self.distinct)
        self.assertNotEqual(old, new)
        self.assertEqual(leaf.read_bytes(), b'selected-cache-object-unmodified')

    def test_unrelated_nested_mount_on_same_device_remains_authorized(self):
        first, second, leaf = self._selected_cache_object()
        other = self.base/'other-physical-subtree'
        other.mkdir()
        st = os.stat(other)
        nested=((str(self.distinct),str(self.distinct/'8'),'815',
                 (st.st_dev,st.st_ino)),)
        with patch.object(cache,'_cache_peer_mounts',return_value=nested):
            observed=self.check(self.distinct)
        self.assertEqual(observed[1],nested)

    def test_bind_of_selected_ancestor_is_rejected_as_overlap(self):
        parent=os.stat(self.base)
        nested=((str(self.distinct),str(self.distinct/'8'),'817',
                 (parent.st_dev,parent.st_ino)),)
        with patch.object(cache,'_cache_peer_mounts',return_value=nested):
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'subtrees physically overlap'):
                self.check(self.distinct)

    def test_nested_peer_mount_path_inspection_is_anchored(self):
        from io import StringIO
        first, second, leaf=self._selected_cache_object()
        peer_first=self.distinct/'8'
        peer_first.mkdir()
        row=('11 10 0:1 / '+str(peer_first)+' rw,relatime - ext4 /dev/vda1 rw\n')
        with patch('builtins.open',side_effect=lambda *a,**kw: StringIO(row)):
            found=cache._cache_peer_mounts(str(self.selected),{str(self.distinct)})
        self.assertEqual(len(found),1)
        self.assertEqual(found[0][0],str(self.distinct))
        self.assertEqual(found[0][1],str(peer_first))
        st=os.stat(peer_first)
        self.assertEqual(found[0][3],(st.st_dev,st.st_ino))

    def test_nested_symlink_mount_target_is_non_authorizing(self):
        first, second, leaf=self._selected_cache_object()
        linked=self.distinct/'8'
        linked.symlink_to(first,target_is_directory=True)
        with self.assertRaises(OSError):
            cache._cache_mount_target_identity(str(linked/'aa'))
        with self.assertRaises(cache.CacheManageError):
            cache._cache_mount_target_identity(str(linked))

    def test_nested_or_ancestor_cache_path_is_rejected(self):
        child=self.selected/'child'
        child.mkdir()
        for peer in (self.base,child):
            with self.subTest(peer=str(peer)):
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'physically overlap'):
                    self.check(peer)

    def test_symlinked_peer_and_symlinked_ancestor_fail_closed(self):
        linked=self.base/'linked'
        linked.symlink_to(self.selected,target_is_directory=True)
        child=self.selected/'child'
        child.mkdir()
        for peer in (linked,linked/'child'):
            with self.subTest(peer=str(peer)):
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'physical separation is unverified'):
                    self.check(peer)

    def test_missing_or_non_directory_peer_is_non_authorizing(self):
        file=self.base/'not-directory'
        file.write_text('not a cache')
        for peer in (self.base/'missing',file):
            with self.subTest(peer=str(peer)):
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'physical separation is unverified'):
                    self.check(peer)
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'Unverified registered Cache directory path'):
            cache._verify_cache_peer_isolation(
                str(self.selected),self.identity,[{'id':8,'directory':None}])

    def test_unreadable_peer_is_non_authorizing(self):
        blocked=self.base/'unreadable'
        blocked.mkdir()
        blocked.chmod(0)
        try:
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'physical separation is unverified'):
                self.check(blocked)
        finally:
            blocked.chmod(0o700)

    def test_selected_identity_drift_blocks_clear(self):
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'physical identity changed'):
            cache._verify_cache_peer_isolation(
                str(self.selected),(self.identity[0],self.identity[1]+1),
                [{'id':8,'directory':str(self.distinct)}])

    def test_missing_peer_inventory_blocks_even_when_no_peers_are_reported(self):
        with self.assertRaisesRegex(cache.CacheManageError,
                                    'inventory unavailable'):
            cache._verify_cache_peer_isolation(str(self.selected),self.identity,None)

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
                'unresolved_other_sites':0,'other_sites_same_directory':[],
                'other_sites_same_zone':[],'source_sha256':'a'*64,
                'physical_peer_cache_paths':[]}),
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

    def test_bridge_actions_require_applied_site_owned_recovery_and_fresh_source(self):
        from ach_customizer_cache_bridge import BridgeError
        with patch('ach_customizer_cache_bridge.enable') as enable, \
             patch('ach_customizer_cache_bridge.disable') as disable, \
             patch('ach_customizer_cache_bridge.inspect', return_value='Provisioned') as inspect, \
             patch.object(cache, '_cache_observation', return_value={
                 'state':'Applied','runtime_verified':True}), \
             patch.object(cache, '_verify_cache_peer_isolation', return_value=((19,23),)):
            with self.assertRaisesRegex(cache.CacheManageError,'Explicit'):
                cache.manage_cache('bridge_enable', self.site, public=object(),
                    approved=False, **self.kwargs())
            self.assertFalse(enable.called)
            result = self.apply()
            fd=cache._open_state_dir(str(self.state))
            try:
                record=cache._record_read(fd,7)
            finally:
                os.close(fd)
            # The site-owned stock PHP Cache is a supported bridge target;
            # there is no need to convert its native PHP handler.
            self.assertNotIn('native_handler',record)
            self.assertFalse(enable.called)
            with self.assertRaisesRegex(cache.CacheManageError,'matching recovery'):
                cache.manage_cache('bridge_enable', self.site, public=object(),
                    approved=True,recovery_id='a'*32, **self.kwargs())
            with patch.object(cache,'inspect_site_fastcgi_cache',return_value={
                'state':'Source Observed','zone_state':'Direct Zone',
                'cache_zone':'ACHFC_7','cache_directory':record['cache_directory'],
                'unresolved_other_sites':1, 'other_sites_same_directory':[],
                'other_sites_same_zone':[],'physical_peer_cache_paths':[]}):
                with self.assertRaisesRegex(cache.CacheManageError,'isolation'):
                    cache.manage_cache('bridge_enable', self.site, public=object(),
                        approved=True,recovery_id=result['recovery_id'],**self.kwargs())
            self.assertFalse(enable.called)
            enable.return_value=True
            accepted=cache.manage_cache('bridge_enable', self.site, public=object(),
                approved=True,recovery_id=result['recovery_id'],**self.kwargs())
            self.assertEqual(accepted['state'],'Provisioned')
            self.assertTrue(accepted['changed'])
            self.assertFalse(accepted['runtime_verified'])
            self.assertFalse(accepted['purge_supported'])
            self.assertEqual(enable.call_count,1)
            self.assertEqual(enable.call_args.args[0],self.site)
            self.assertEqual(enable.call_args.args[2]['op'],result['recovery_id'])
            ins=cache.manage_cache('bridge_inspect', self.site, public=object(),
                approved=False, **self.kwargs())
            self.assertEqual(ins['state'],'Provisioned')
            self.assertTrue(ins['read_only'])
            inspect.assert_called_once()
            self.assertFalse(disable.called)
            disable.return_value=True
            done=cache.manage_cache('bridge_disable',self.site,public=object(),
                approved=True,**self.kwargs())
            self.assertEqual(done['state'],'Not Provisioned')
            self.assertTrue(done['changed'])
            disable.assert_called_once()

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

    def test_restored_renamed_site_requires_fresh_approval_and_archives_old_journal(self):
        first=self.apply()
        cache.manage_cache('restore',self.site,approved=True,
                           recovery_id=first['recovery_id'],**self.kwargs())
        journal=self.state/cache._names(7)[2]
        old=json.loads(journal.read_text())
        old['site_key']='prior-qa.test'
        journal.write_text(json.dumps(old))
        saved=journal.read_bytes()
        commands=list(self.commands)
        plan=self.preview()
        self.assertEqual(plan['state'],'Ready for Review')
        self.assertFalse(plan['runtime_verified'])
        self.assertIn('Historical restored recovery',plan['note'])
        self.assertIn('prior-qa.test',plan['note'])
        self.assertIn('application continuity is NOT established',plan['note'])
        self.assertEqual(journal.read_bytes(),saved)
        self.assertEqual(self.commands,commands)
        with self.assertRaisesRegex(cache.CacheManageError,'approval'):
            cache.manage_cache('apply',self.site,public=object(),
                expected_source=plan['source_sha256'],
                expected_proposal=plan['proposal_sha256'],
                cache_generation=plan['cache_generation'],
                approved=False,**self.kwargs())
        self.assertEqual(journal.read_bytes(),saved)
        second=cache.manage_cache('apply',self.site,public=object(),
            expected_source=plan['source_sha256'],
            expected_proposal=plan['proposal_sha256'],
            cache_generation=plan['cache_generation'],
            approved=True,**self.kwargs())
        self.assertEqual(second['state'],'Applied')
        self.assertEqual(cache.manage_cache('recheck',self.site,
                                            **self.kwargs())['state'],'Applied')
        active=json.loads(journal.read_text())
        self.assertEqual(active['site_key'],'qa.test')
        self.assertNotEqual(active['cache_generation'],old['cache_generation'])
        self.assertNotEqual(active['op'],old['op'])
        archived=self.state/(cache._names(7)[2]+'.'+old['op']+'.restored')
        self.assertEqual(json.loads(archived.read_text()),old)
        self.assertTrue((self.ext/(cache._names(7)[1]+'.'+old['op']+'.retained')).is_file())
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=second['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_restored_stock_site_renamed_to_wpfastcgi_is_a_new_approved_generation(self):
        first=self.apply()
        cache.manage_cache('restore',self.site,approved=True,
                           recovery_id=first['recovery_id'],**self.kwargs())
        original=json.loads((self.state/cache._names(7)[2]).read_text())
        self.assertNotIn('native_handler',original)
        renamed='renamed-woo.test'
        new_ext=self.ext.parent/renamed
        self.ext.rename(new_ext)
        prior_vhost=self.vhost/'qa.test.conf'
        new_vhost=self.vhost/(renamed+'.conf')
        new_vhost.write_text(prior_vhost.read_text().replace('qa.test',renamed).replace(
            'enable-php-85.conf','enable-php-85-wpfastcgi.conf'))
        prior_vhost.unlink()
        self.site['name']=renamed
        self.site['bound_domains']=[{'name':renamed,'port':80}]
        self.ext=new_ext
        (self.nginx/'enable-php-85-wpfastcgi.conf').write_text(
            cache.WP_NATIVE_CANONICAL.replace('NATIVE_PHP','85'))
        self.sources=cache._site_sources(
            self.site,'85',native_handler='wpfastcgi',
            vhost_root=str(self.vhost),nginx_root=str(self.nginx))
        self.assertEqual(self.sources['native_handler'],'wpfastcgi')
        current_native=dict(self.native,zone_state='Direct Zone',
                            cache_zone='WORDPRESS',purge_directive_seen=True)
        def compatible(site,public,**kw):
            reference=cache.generate_reference(
                7,'85',cache_generation=kw.get('cache_generation'),
                native_handler='wpfastcgi')
            return current_native,reference,self.sources
        with patch.object(cache,'_compatibility',side_effect=compatible):
            plan=self.preview()
            self.assertEqual(plan['state'],'Ready for Review')
            self.assertEqual(plan['native_handler'],'wpfastcgi')
            self.assertIn('qa.test',plan['note'])
            self.assertIn('renamed-woo.test',plan['note'])
            self.assertIn('stock handler',plan['note'])
            self.assertIn('wpfastcgi handler',plan['note'])
            second=cache.manage_cache('apply',self.site,public=object(),
                expected_source=plan['source_sha256'],
                expected_proposal=plan['proposal_sha256'],
                cache_generation=plan['cache_generation'],approved=True,
                **self.kwargs())
        self.assertEqual(second['state'],'Applied')
        self.assertNotEqual(original['cache_generation'],plan['cache_generation'])
        self.assertEqual(cache.manage_cache('recheck',self.site,
                                           **self.kwargs())['state'],'Applied')
        current=json.loads((self.state/cache._names(7)[2]).read_text())
        self.assertEqual(current['site_key'],renamed)
        self.assertEqual(current['native_handler'],'wpfastcgi')
        self.assertEqual(json.loads((self.state/(
            cache._names(7)[2]+'.'+original['op']+'.restored')).read_text()),original)
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=second['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_restored_wpfastcgi_to_stock_can_reapply_with_fresh_approval(self):
        """Restore retires old WP handler Cache; a native stock switch is reversible.

        This is a new generation, not adoption of the old WordPress fragment.
        The original journal and retained bytes remain under their original ID.
        """
        vhost=self.vhost/'qa.test.conf'
        stock_vhost=vhost.read_text()
        vhost.write_text(stock_vhost.replace(
            'enable-php-85.conf','enable-php-85-wpfastcgi.conf'))
        (self.nginx/'enable-php-85-wpfastcgi.conf').write_text(
            cache.WP_NATIVE_CANONICAL.replace('NATIVE_PHP','85'))
        self.sources=cache._site_sources(
            self.site,'85',native_handler='wpfastcgi',
            vhost_root=str(self.vhost),nginx_root=str(self.nginx))
        wordpress_native=dict(self.native,zone_state='Direct Zone',
                             cache_zone='WORDPRESS',purge_directive_seen=True)
        def wp_compatible(site,public,**kw):
            reference=cache.generate_reference(
                7,'85',cache_generation=kw.get('cache_generation'),
                native_handler='wpfastcgi')
            return wordpress_native,reference,self.sources
        with patch.object(cache,'_compatibility',side_effect=wp_compatible):
            first=self.apply()
        journal=self.state/cache._names(7)[2]
        prior=json.loads(journal.read_text())
        self.assertEqual(prior['native_handler'],'wpfastcgi')
        self.assertEqual(cache.manage_cache('restore',self.site,
            approved=True,recovery_id=first['recovery_id'],**self.kwargs())['state'],
            'Restored')
        original_bytes=journal.read_bytes()
        restored_prior=json.loads(original_bytes)
        self.assertEqual(restored_prior['phase'],'restored')
        self.assertEqual(cache.manage_cache('recheck',self.site,
            **self.kwargs())['state'],'Restored')
        vhost.write_text(stock_vhost)
        self.sources=cache._site_sources(self.site,'85',
            native_handler='stock',vhost_root=str(self.vhost),
            nginx_root=str(self.nginx))
        self.assertEqual(cache.manage_cache('recheck',self.site,
            **self.kwargs())['state'],'Needs Review',
            'Historical source drift remains diagnostic until new approval')
        before_commands=list(self.commands)
        prior_ext=self.ext/(cache._names(7)[1]+'.'+prior['op']+'.retained')
        original_ext=prior_ext.read_bytes()
        prior_ext.write_bytes(original_ext+b'# tampered restored fragment\n')
        with self.assertRaisesRegex(cache.CacheManageError,'byte-identical'):
            self.preview()
        self.assertEqual(journal.read_bytes(),original_bytes)
        prior_ext.write_bytes(original_ext)
        with patch.object(cache,'_path_owned',return_value=(19,24)):
            with self.assertRaisesRegex(cache.CacheManageError,'identity'):
                self.preview()
        self.assertEqual(journal.read_bytes(),original_bytes)
        plan=self.preview()
        self.assertEqual(plan['state'],'Ready for Review')
        self.assertEqual(plan['native_handler'],'stock')
        self.assertIn('wpfastcgi handler',plan['note'])
        self.assertIn('stock handler',plan['note'])
        self.assertEqual(journal.read_bytes(),original_bytes)
        self.assertEqual(self.commands,before_commands)
        with patch('ach_customizer_cache_bridge.inspect',return_value='Not Provisioned'):
            with self.assertRaisesRegex(cache.CacheManageError,'approval'):
                cache.manage_cache('apply',self.site,public=object(),
                    expected_source=plan['source_sha256'],
                    expected_proposal=plan['proposal_sha256'],
                    cache_generation=plan['cache_generation'],
                    approved=False,**self.kwargs())
            self.assertEqual(journal.read_bytes(),original_bytes)
            second=cache.manage_cache('apply',self.site,public=object(),
                expected_source=plan['source_sha256'],
                expected_proposal=plan['proposal_sha256'],
                cache_generation=plan['cache_generation'],
                approved=True,**self.kwargs())
        self.assertEqual(second['state'],'Applied')
        self.assertNotEqual(second['recovery_id'],first['recovery_id'])
        current=json.loads(journal.read_text())
        self.assertNotIn('native_handler',current)
        self.assertNotEqual(current['cache_generation'],prior['cache_generation'])
        archived=self.state/(cache._names(7)[2]+'.'+prior['op']+'.restored')
        self.assertEqual(json.loads(archived.read_text()),restored_prior)
        self.assertTrue((self.ext/(cache._names(7)[1]+'.'+prior['op']+'.retained')).is_file())
        self.assertEqual(cache.manage_cache('recheck',self.site,
            **self.kwargs())['state'],'Applied')
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=second['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_changed_restored_identity_fails_without_pinned_bytes_or_inode(self):
        first=self.apply()
        cache.manage_cache('restore',self.site,approved=True,
                           recovery_id=first['recovery_id'],**self.kwargs())
        journal=self.state/cache._names(7)[2]
        original=json.loads(journal.read_text())
        changed=dict(original,site_key='old-site.test')
        journal.write_text(json.dumps(changed))
        snippet=self.ext/(cache._names(7)[1]+'.'+first['recovery_id']+'.retained')
        saved_snippet=snippet.read_bytes()
        attempts=[
            ('schema1',dict(changed,schema=1)),
            ('null inode',dict(changed,cache_identity=None)),
            ('unrestored',dict(changed,phase='applied')),
        ]
        for label,record in attempts:
            with self.subTest(label=label):
                if record['schema']==1:
                    record.pop('cache_identity')
                journal.write_text(json.dumps(record))
                with self.assertRaises(cache.CacheManageError):
                    self.preview()
                self.assertEqual(json.loads(journal.read_text()),record)
        journal.write_text(json.dumps(changed))
        snippet.write_bytes(saved_snippet+b'# external drift')
        with self.assertRaisesRegex(cache.CacheManageError,'byte-identical'):
            self.preview()
        self.assertEqual(snippet.read_bytes(),saved_snippet+b'# external drift')
        snippet.write_bytes(saved_snippet)
        active=self.ext/cache._names(7)[1]
        active.write_bytes(saved_snippet)
        active.chmod(0o600)
        try:
            with self.assertRaisesRegex(cache.CacheManageError,'byte-identical'):
                self.preview()
        finally:
            active.unlink()
        with patch.object(cache,'_path_owned',return_value=(19,24)):
            with self.assertRaisesRegex(cache.CacheManageError,'physical identity'):
                self.preview()
        self.assertEqual(json.loads(journal.read_text()),changed)
        self.assertEqual(self.preview()['state'],'Ready for Review')

    def test_applied_recovery_is_never_rebound_after_site_key_change(self):
        first=self.apply()
        journal=self.state/cache._names(7)[2]
        before=journal.read_bytes()
        self.site['name']='new-site.test'
        with self.assertRaisesRegex(cache.CacheManageError,'Recheck/Restore'):
            self.preview()
        observed=cache.manage_cache('recheck',self.site,**self.kwargs())
        self.assertEqual(observed['state'],'Needs Review')
        self.assertEqual(observed['recovery_id'],first['recovery_id'])
        self.assertEqual(journal.read_bytes(),before)

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

    def prepared_without_directory(self):
        """Simulate Apply's durable prepared checkpoint after the writer lock."""
        plan=self.preview()
        reference,gb,eb=cache._fragments(7,'85',plan['cache_generation'])
        record={
            'schema':2,'site_id':7,'site_key':'qa.test','php_version':'85',
            'op':'e'*32,'phase':'prepared','cache_identity':None,
            'cache_generation':plan['cache_generation'],
            'source_sha':plan['source_sha256'],
            'proposal_sha':plan['proposal_sha256'],
            'vhost_sha':self.sources['vhost_sha'],
            'main_sha':self.sources['main_sha'],'php_sha':self.sources['php_sha'],
            'global_sha':cache._hash(gb),'extension_sha':cache._hash(eb),
            'cache_directory':reference['cache_directory'],
            'probe_status':200,
        }
        fd=cache._open_state_dir(str(self.state))
        try:
            lock=cache._exclusive_lock(fd)
            try:
                cache._record_save(fd,record)
            finally:
                os.close(lock)
        finally:
            os.close(fd)
        return record

    def test_prepublication_journal_can_be_safely_reconciled_without_reload(self):
        record=self.prepared_without_directory()
        journal=self.state/cache._names(7)[2]
        saved=journal.read_bytes()
        before=list(self.commands)
        result=cache.manage_cache('recheck',self.site,public=object(),**self.kwargs())
        self.assertEqual(result['state'],'Recovery Required')
        self.assertEqual(result['journal_phase'],'prepared')
        self.assertEqual(result['recovery_scope'],'prepublication')
        self.assertEqual(result['recovery_id'],record['op'])
        self.assertFalse(result['runtime_verified'])
        self.assertTrue(result['read_only'])
        self.assertEqual(journal.read_bytes(),saved)
        self.assertEqual(self.commands,before)
        with self.assertRaisesRegex(cache.CacheManageError,'approval'):
            cache.manage_cache('restore',self.site,approved=False,
                recovery_id=record['op'],**self.kwargs())
        self.assertEqual(journal.read_bytes(),saved)
        restored=cache.manage_cache('restore',self.site,public=object(),approved=True,
                recovery_id=record['op'],**self.kwargs())
        self.assertEqual(restored['state'],'Restored')
        self.assertEqual(restored['recovery_scope'],'prepublication')
        self.assertEqual(restored['journal_phase'],'restored')
        self.assertFalse(restored['changed'])
        self.assertFalse(restored['runtime_verified'])
        self.assertEqual(self.commands,before)
        finalized=journal.read_bytes()
        recheck=cache.manage_cache('recheck',self.site,public=object(),**self.kwargs())
        self.assertEqual(recheck['state'],'Restored')
        self.assertEqual(recheck['journal_phase'],'restored')
        self.assertEqual(recheck['recovery_scope'],'prepublication')
        self.assertEqual(recheck['recovery_id'],record['op'])
        self.assertFalse(recheck['runtime_verified'], 'Cache was never activated')
        self.assertIn('already finalized',recheck['note'])
        self.assertEqual(journal.read_bytes(),finalized)
        self.assertEqual(self.commands,before)
        applied=self.apply()
        self.assertEqual(applied['state'],'Applied')
        self.assertTrue(self.cache_created)
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=applied['recovery_id'],**self.kwargs())['state'],'Restored')

    def test_prepublication_partial_physical_setup_fails_closed(self):
        record=self.prepared_without_directory()
        reference,gb,eb=cache._fragments(7,'85',record['cache_generation'])
        journal=self.state/cache._names(7)[2]
        saved=journal.read_bytes()
        before=list(self.commands)
        global_name,ext_name,_=cache._names(7)
        for label,path,bytes_,mode in (
            ('global fragment',self.vhost/global_name,gb,0o600),
            ('extension fragment',self.ext/ext_name,eb,0o600),
            ('untrusted file permission',self.vhost/global_name,gb,0o644),
            ('physical directory',None,None,None),
        ):
            with self.subTest(label=label):
                if path is not None:
                    path.write_bytes(bytes_)
                    path.chmod(mode)
                else:
                    self.cache_created=True
                observed=cache.manage_cache('recheck',self.site,public=object(),**self.kwargs())
                self.assertEqual(observed['state'],'Needs Review')
                self.assertEqual(observed['recovery_id'],record['op'])
                self.assertFalse(observed['runtime_verified'])
                self.assertNotIn('recovery_scope',observed)
                self.assertEqual(journal.read_bytes(),saved)
                self.assertEqual(self.commands,before)
                with self.assertRaises(cache.CacheManageError):
                    cache.manage_cache('restore',self.site,public=object(),approved=True,
                        recovery_id=record['op'],**self.kwargs())
                self.assertEqual(journal.read_bytes(),saved)
                self.assertEqual(self.commands,before)
                if path is not None:
                    path.unlink()
                else:
                    self.cache_created=False
        self.assertEqual(cache.manage_cache('recheck',self.site,public=object(),
                                           **self.kwargs())['state'],'Recovery Required')

    def test_restored_fragments_reappearing_are_never_reported_applied(self):
        applied=self.apply()
        rid=applied['recovery_id']
        self.assertEqual(cache.manage_cache('restore',self.site,approved=True,
            recovery_id=rid,**self.kwargs())['state'],'Restored')
        global_name,ext_name,journal_name=cache._names(7)
        g=self.vhost/global_name
        e=self.ext/ext_name
        journal=self.state/journal_name
        saved=journal.read_bytes()
        before=list(self.commands)
        for fragments in ((g,), (g,e)):
            with self.subTest(active=len(fragments)):
                for path in fragments:
                    path.write_bytes(Path(str(path)+'.'+rid+'.retained').read_bytes())
                def probe_must_not_run(*_a,**_kw):
                    raise AssertionError('Restored journal cannot be classified as Applied')
                options={**self.kwargs(),'probe':probe_must_not_run}
                state=cache.manage_cache('recheck',self.site,**options)
                self.assertEqual(state['state'],'Needs Review')
                self.assertEqual(state['journal_phase'],'restored')
                self.assertEqual(state['recovery_id'],rid)
                self.assertFalse(state['runtime_verified'])
                self.assertEqual(saved,journal.read_bytes())
                self.assertEqual(before,self.commands)
                with self.assertRaisesRegex(cache.CacheManageError,'already-restored'):
                    cache.manage_cache('restore',self.site,approved=True,
                        recovery_id=rid,**self.kwargs())
                for path in fragments:
                    path.unlink()
                self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                                 'Restored')

    def test_foreign_extension_fragment_blocks_prepublication_and_restored_recovery(self):
        foreign=self.ext/'foreign_routing.conf'
        journal=self.state/cache._names(7)[2]
        record=self.prepared_without_directory()
        saved=journal.read_bytes()
        commands=list(self.commands)
        foreign.write_text('location / { return 200; }\n')
        foreign.chmod(0o600)
        result=cache.manage_cache('recheck',self.site,public=object(),**self.kwargs())
        self.assertEqual(result['state'],'Needs Review')
        self.assertEqual(result['recovery_id'],record['op'])
        self.assertFalse(result['runtime_verified'])
        self.assertIn('extension inventory',result['note'])
        with self.assertRaisesRegex(cache.CacheManageError,'extension inventory'):
            cache.manage_cache('restore',self.site,public=object(),approved=True,
                recovery_id=record['op'],**self.kwargs())
        self.assertEqual(saved,journal.read_bytes())
        self.assertEqual(commands,self.commands)
        foreign.unlink()
        self.assertEqual(cache.manage_cache('recheck',self.site,public=object(),
                                          **self.kwargs())['state'],'Recovery Required')
        cache.manage_cache('restore',self.site,public=object(),approved=True,
                           recovery_id=record['op'],**self.kwargs())
        applied=self.apply()
        cache.manage_cache('restore',self.site,approved=True,
                           recovery_id=applied['recovery_id'],**self.kwargs())
        restored_bytes=journal.read_bytes()
        previous=list(self.commands)
        foreign.write_text('location ~ \\.php { fastcgi_cache WORDPRESS; }\n')
        foreign.chmod(0o600)
        result=cache.manage_cache('recheck',self.site,**self.kwargs())
        self.assertEqual(result['state'],'Needs Review')
        self.assertEqual(result['journal_phase'],'restored')
        self.assertEqual(result['recovery_id'],applied['recovery_id'])
        self.assertFalse(result['runtime_verified'])
        self.assertEqual(restored_bytes,journal.read_bytes())
        self.assertEqual(previous,self.commands)
        foreign.unlink()
        self.assertEqual(cache.manage_cache('recheck',self.site,**self.kwargs())['state'],
                         'Restored')

    def test_prepublication_full_source_inventory_drift_cannot_finalize(self):
        record=self.prepared_without_directory()
        journal=self.state/cache._names(7)[2]
        saved=journal.read_bytes()
        before=list(self.commands)
        with patch.object(cache,'inspect_site_fastcgi_cache',return_value={
                'state':'Source Observed','source_sha256':'b'*64,
                'unresolved_other_sites':0}):
            result=cache.manage_cache('recheck',self.site,public=object(),**self.kwargs())
            self.assertEqual(result['state'],'Needs Review')
            self.assertEqual(result['recovery_id'],record['op'])
            self.assertFalse(result['runtime_verified'])
            with self.assertRaisesRegex(cache.CacheManageError,'inventory changed'):
                cache.manage_cache('restore',self.site,public=object(),approved=True,
                    recovery_id=record['op'],**self.kwargs())
        self.assertEqual(saved,journal.read_bytes())
        self.assertEqual(before,self.commands)
        self.assertEqual(cache.manage_cache('recheck',self.site,public=object(),
                                          **self.kwargs())['state'],'Recovery Required')

    def test_native_php_switch_reports_versions_without_authorizing_restore(self):
        applied = self.apply()
        journal = self.state / cache._names(7)[2]
        saved = journal.read_bytes()
        old_commands = list(self.commands)
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        switched = original.replace('include enable-php-85.conf;',
                                    'include enable-php-81.conf;')
        self.assertNotEqual(switched, original)
        try:
            vhost.write_text(switched)
            observed = cache.manage_cache('recheck', self.site, public=object(),
                                          **self.kwargs())
            self.assertEqual(observed['state'], 'Needs Review')
            self.assertEqual(observed['journal_phase'], 'applied')
            self.assertEqual(observed['recovery_id'], applied['recovery_id'])
            self.assertFalse(observed['runtime_verified'])
            self.assertIn('PHP 8.5', observed['note'])
            self.assertIn('PHP 8.1', observed['note'])
            self.assertIn('Recheck', observed['note'])
            self.assertEqual(saved, journal.read_bytes())
            self.assertEqual(old_commands, self.commands)
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'PHP 8\\.5.*PHP 8\\.1'):
                cache.manage_cache('restore', self.site, approved=True,
                                   recovery_id=applied['recovery_id'],
                                   **self.kwargs())
            self.assertEqual(saved, journal.read_bytes())
            self.assertEqual(old_commands, self.commands)
        finally:
            vhost.write_text(original)
        verified = cache.manage_cache('recheck', self.site, **self.kwargs())
        self.assertEqual(verified['state'], 'Applied')
        self.assertEqual(verified['recovery_id'], applied['recovery_id'])
        cache.manage_cache('restore', self.site, approved=True,
                           recovery_id=applied['recovery_id'], **self.kwargs())
        self.assertEqual(cache.manage_cache('recheck', self.site,
                                            **self.kwargs())['state'], 'Restored')

    def regenerated_audit(self, *args, **kwargs):
        # The separate native/peer audit was validated independently; model
        # its prepublication vs published Cache source state without bypassing
        # the selected VHost drift and source checks under test.
        if (self.vhost / cache._names(self.site['id'])[0]).exists():
            return {
                **self.native, 'zone_state': 'Direct Zone',
                'cache_zone': 'ACHFC_' + str(self.site['id']),
                'cache_directory': self.ref['cache_directory'],
            }
        return self.native

    def test_regenerated_native_cache_full_preview_apply_recheck_restore(self):
        # Keep the actual _compatibility(), _site_sources() and VHost drift
        # checks in the operator path; only the separate global/peer source
        # audit and process/cache-identity effects use the existing fixtures.
        panel = SimpleNamespace(
            get_webserver=lambda: 'nginx',
            get_panel_version=lambda: '8.0.7',
        )
        vhost = self.vhost / 'qa.test.conf'
        old = vhost.read_bytes()
        mask = self.vhost / 'sub_dir' / self.site['name'] / '*.conf'
        regenerated = old.decode().replace(
            'root ' + self.site['path'] + ';',
            'root ' + self.site['path'] + '/;').replace(
            ' include ' + str(self.ext) + '/*.conf;',
            ' include ' + str(mask) + ';\n'
            ' include ' + str(self.ext) + '/*.conf;')
        vhost.write_text(regenerated)
        with patch.object(cache, '_compatibility',
                          side_effect=REAL_COMPATIBILITY), patch.object(
                cache, 'inspect_site_fastcgi_cache', side_effect=self.regenerated_audit):
            plan = cache.preview_cache_activation(
                self.site, panel, data_dir=str(self.state),
                vhost_root=str(self.vhost), nginx_root=str(self.nginx),
                probe=self.probe)
            self.assertEqual(plan['state'], 'Ready for Review', plan)
            self.assertTrue(plan['apply_supported'])
            self.assertEqual(vhost.read_text(), regenerated)
            self.assertFalse(list(self.state.iterdir()))
            applied = cache.manage_cache(
                'apply', self.site, public=panel,
                expected_source=plan['source_sha256'],
                expected_proposal=plan['proposal_sha256'],
                cache_generation=plan['cache_generation'], approved=True,
                **self.kwargs())
            self.assertEqual(applied['state'], 'Applied', applied)
            self.assertEqual(cache.manage_cache(
                'recheck', self.site, **self.kwargs())['state'], 'Applied')
            restored = cache.manage_cache(
                'restore', self.site, public=panel, approved=True,
                recovery_id=applied['recovery_id'], **self.kwargs())
            self.assertEqual(restored['state'], 'Restored', restored)
            self.assertEqual(cache.manage_cache(
                'recheck', self.site, **self.kwargs())['state'], 'Restored')
        self.assertEqual(vhost.read_text(), regenerated)
        self.assertNotEqual(vhost.read_bytes(), old)

    def test_cache_native_root_mismatch_blocks_preview_and_approved_apply(self):
        panel = SimpleNamespace(
            get_webserver=lambda: 'nginx',
            get_panel_version=lambda: '8.0.7',
        )
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        with patch.object(cache, '_compatibility',
                          side_effect=REAL_COMPATIBILITY), patch.object(
                cache, 'inspect_site_fastcgi_cache', side_effect=self.regenerated_audit):
            # Existing layout also passes all original readiness gates.
            before = cache.preview_cache_activation(
                self.site, panel, data_dir=str(self.state),
                vhost_root=str(self.vhost), nginx_root=str(self.nginx),
                probe=self.probe)
            self.assertEqual(before['state'], 'Ready for Review')
            different = original.replace(
                'root ' + self.site['path'] + ';',
                'root ' + str(self.root / 'other') + ';')
            vhost.write_text(different)
            with self.assertRaises(cache.CacheManageError) as preview:
                cache.preview_cache_activation(
                    self.site, panel, data_dir=str(self.state),
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx),
                    probe=self.probe)
            self.assertEqual(preview.exception.stage, 'compatibility')
            with self.assertRaises(cache.CacheManageError) as apply:
                cache.manage_cache(
                    'apply', self.site, public=panel,
                    expected_source=before['source_sha256'],
                    expected_proposal=before['proposal_sha256'],
                    cache_generation=before['cache_generation'],
                    approved=True, **self.kwargs())
            self.assertEqual(apply.exception.stage, 'compatibility')
        self.assertFalse((self.ext / 'ach_customizer_cache_7.conf').exists())
        self.assertFalse((self.vhost / '0.ach_customizer_cache_7.conf').exists())
        self.assertFalse(self.commands)

    def test_quote_and_escape_balancing_never_authorizes_nested_cache_include(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        mask = self.vhost / 'sub_dir' / self.site['name'] / '*.conf'
        variations = (
            ('set $before "}";', 'set $after "{";', 'location = /nested {'),
            (r'set $before \};', r'set $after \{;', 'if ($request_uri = /nested) {'),
        )
        panel = SimpleNamespace(
            get_webserver=lambda: 'nginx', get_panel_version=lambda: '8.0.7')
        for before, after, nested in variations:
            with self.subTest(before=before):
                vhost.write_text(original.replace(
                    ' include ' + str(self.ext) + '/*.conf;',
                    ' ' + before + '\n ' + nested + '\n'
                    ' include ' + str(mask) + ';\n'
                    ' }\n ' + after + '\n'
                    ' include ' + str(self.ext) + '/*.conf;'))
                with self.assertRaises(cache.CacheManageError) as rejected:
                    cache._site_sources(
                        self.site, '85', vhost_root=str(self.vhost),
                        nginx_root=str(self.nginx))
                self.assertEqual(rejected.exception.stage, 'compatibility')
                with patch.object(cache, '_compatibility',
                                  side_effect=REAL_COMPATIBILITY), patch.object(
                        cache, 'inspect_site_fastcgi_cache',
                        side_effect=self.regenerated_audit):
                    with self.assertRaises(cache.CacheManageError) as readiness:
                        cache.preview_cache_activation(
                            self.site, panel, data_dir=str(self.state),
                            vhost_root=str(self.vhost), nginx_root=str(self.nginx),
                            probe=self.probe)
                    self.assertEqual(readiness.exception.stage, 'compatibility')
        self.assertFalse(self.commands)
        self.assertFalse(list(self.state.iterdir()))

    def test_native_807_unused_subdir_source_is_accepted(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        mask_dir = self.vhost / 'sub_dir' / self.site['name']
        vhost.write_text(original.replace(
            ' include ' + str(self.ext) + '/*.conf;',
            ' include ' + str(mask_dir) + '/*.conf;\n'
            ' include ' + str(self.ext) + '/*.conf;'))
        try:
            report = cache._site_sources(self.site, '85',
                vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertIn('vhost_sha', report)
        finally:
            vhost.write_text(original)

    def test_native_ssl_helper_selected_source_recheck_requires_exact_template(self):
        helper = self.vhost / "well-known" / "qa.test.conf"
        helper.parent.mkdir()
        template = (ROOT / "tests/fixtures/native-well-known.conf").read_bytes()
        helper.write_bytes(template)
        vhost = self.vhost / "qa.test.conf"
        vhost.write_text(vhost.read_text().replace(
            " include enable-php-", " include " + str(helper) + ";\n include enable-php-"))
        source = cache._site_sources(self.site, "85",
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        self.assertIn("vhost_sha", source)
        helper.write_bytes(template + b"\nreturn 403;\n")
        with self.assertRaisesRegex(cache.CacheManageError, "well-known"):
            cache._site_sources(self.site, "85",
                vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        self.assertFalse(self.commands)
        self.assertFalse(list(self.state.iterdir()))

    def test_native_807_subdir_route_cannot_bypass_cache_preflight(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        mask_dir = self.vhost / 'sub_dir' / self.site['name']
        mask_dir.mkdir(parents=True)
        vhost.write_text(original.replace(
            ' include ' + str(self.ext) + '/*.conf;',
            ' include ' + str(mask_dir) + '/*.conf;\n'
            ' include ' + str(self.ext) + '/*.conf;'))
        (mask_dir / 'foreign.conf').write_text(
            'location /private { fastcgi_pass unix:/tmp/other.sock; }\n')
        try:
            with self.assertRaises(cache.CacheManageError) as observed:
                cache._site_sources(self.site, '85',
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertEqual(observed.exception.stage, 'compatibility')
            self.assertFalse(list(self.state.iterdir()))
            self.assertFalse(self.commands)
        finally:
            vhost.write_text(original)

    def test_native_subdir_nested_in_location_rejects_cache_preflight(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        mask = self.vhost / 'sub_dir' / self.site['name'] / '*.conf'
        vhost.write_text(original.replace(
            ' include ' + str(self.ext) + '/*.conf;',
            ' location = /custom { include ' + str(mask) + '; }\n'
            ' include ' + str(self.ext) + '/*.conf;'))
        try:
            with self.assertRaises(cache.CacheManageError) as observed:
                cache._site_sources(self.site, '85',
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertEqual(observed.exception.stage, 'compatibility')
            self.assertFalse(list(self.state.iterdir()))
            self.assertFalse(self.commands)
        finally:
            vhost.write_text(original)

    def test_native_new_site_missing_extension_include_is_guided_without_write(self):
        vhost = self.vhost / 'qa.test.conf'
        initial = vhost.read_text()
        missing = initial.replace(' include ' + str(self.ext) + '/*.conf;\n', '')
        self.assertNotEqual(missing, initial)
        try:
            vhost.write_text(missing)
            before = vhost.read_bytes()
            with self.assertRaises(cache.CacheManageError) as observed:
                cache._site_sources(self.site, '85',
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertEqual(observed.exception.stage, 'compatibility')
            self.assertEqual(observed.exception.reason_code,
                             'native_extension_include_missing')
            self.assertIn('site statistics may add it later', str(observed.exception))
            self.assertEqual(vhost.read_bytes(), before)
            self.assertFalse(list(self.state.iterdir()))
            self.assertFalse(self.commands)
            # The operator can use the native aaPanel VHost editor. A fresh
            # inspection after that independent action is still mandatory.
            vhost.write_text(initial)
            self.assertIn('vhost_sha', cache._site_sources(
                self.site, '85', vhost_root=str(self.vhost),
                nginx_root=str(self.nginx)))
        finally:
            vhost.write_text(initial)

    def test_missing_extension_allows_absent_or_verified_inert_native_sources(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        missing = original.replace(
            ' include ' + str(self.ext) + '/*.conf;\n', '')
        self.assertNotEqual(original, missing)

        def assert_guided():
            with self.assertRaises(cache.CacheManageError) as observed:
                cache._site_sources(self.site, '85',
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertEqual(observed.exception.stage, 'compatibility')
            self.assertEqual(observed.exception.reason_code,
                             'native_extension_include_missing')
            self.assertEqual(vhost.read_text(), missing)
            self.assertFalse(list(self.state.iterdir()))
            self.assertFalse(self.commands)

        try:
            vhost.write_text(missing)
            assert_guided()  # Existing, empty site Extension directory.
            self.ext.rmdir()
            assert_guided()  # Site directory not yet created by site_total.
            self.ext.parent.rmdir()
            assert_guided()  # Entire native Extension parent still absent.
            self.ext.mkdir(parents=True)
            (self.ext / 'site_total.conf').write_text(
                'access_log syslog:server=unix:/tmp/site_total.sock,'
                'nohostname,tag=7__access site_total;\n')
            assert_guided()  # On-disk aaPanel analytics, independently inspected.
        finally:
            vhost.write_text(original)

    def test_missing_extension_unverified_files_never_recommend_wildcard(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        missing = original.replace(
            ' include ' + str(self.ext) + '/*.conf;\n', '')
        self.assertNotEqual(original, missing)

        def assert_rejected():
            with self.assertRaises(cache.CacheManageError) as observed:
                cache._site_sources(self.site, '85',
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertEqual(observed.exception.stage, 'compatibility')
            self.assertIsNone(observed.exception.reason_code)
            self.assertIn('Extension directory is unverified',
                          str(observed.exception))
            self.assertIn('before adding a wildcard include',
                          str(observed.exception))
            self.assertEqual(vhost.read_text(), missing)
            self.assertFalse(list(self.state.iterdir()))
            self.assertFalse(self.commands)

        try:
            vhost.write_text(missing)
            for name, body in (
                ('foreign.conf', 'location /private { return 200; }\n'),
                ('foreign.conf', 'access_log off;\n'),
                ('site_total.conf', 'proxy_pass http://foreign;\n'),
                ('site_total.conf',
                 'access_log off; fastcgi_pass unix:/tmp/php.sock;\n'),
            ):
                with self.subTest(name=name, body=body):
                    path = self.ext / name
                    path.write_text(body)
                    try:
                        assert_rejected()
                    finally:
                        path.unlink()
            linked = self.ext / 'site_total.conf'
            linked.symlink_to(self.nginx / 'fastcgi.conf')
            try:
                assert_rejected()
            finally:
                linked.unlink()
            # Also inspect unsafe directory identity/permissions, even when
            # no foreign .conf currently exists. Do not rely on root bypass.
            original_mode = self.ext.stat().st_mode & 0o777
            for mode in (0o000, 0o777):
                with self.subTest(mode=oct(mode)):
                    self.ext.chmod(mode)
                    try:
                        assert_rejected()
                    finally:
                        self.ext.chmod(original_mode)
            # An unreadable Extension parent must not be accepted merely
            # because root can traverse it with elevated privileges.
            parent = self.ext.parent
            parent_mode = parent.stat().st_mode & 0o777
            parent.chmod(0o000)
            try:
                assert_rejected()
            finally:
                parent.chmod(parent_mode)
            moved = self.ext.with_name('qa-held')
            self.ext.rename(moved)
            try:
                self.ext.symlink_to(moved, target_is_directory=True)
                assert_rejected()
            finally:
                self.ext.unlink()
                moved.rename(self.ext)
            # The parent cannot be an alias either, even when the site
            # directory inside the alias would otherwise be empty.
            parent = self.ext.parent
            moved = parent.with_name('extension-held')
            parent.rename(moved)
            try:
                parent.symlink_to(moved, target_is_directory=True)
                assert_rejected()
            finally:
                parent.unlink()
                moved.rename(parent)
        finally:
            vhost.write_text(original)

    def test_edited_or_ambiguous_extension_source_does_not_offer_stock_hint(self):
        vhost = self.vhost / 'qa.test.conf'
        initial = vhost.read_text()
        extension = ' include ' + str(self.ext) + '/*.conf;'
        for replacement in (
            '#'+extension,
            ' include /other/extension/other.test/*.conf;',
            extension + '\n' + extension,
            ' include enable-php-81.conf;',
            ' fastcgi_cache WORDPRESS;'
        ):
            with self.subTest(replacement=replacement):
                try:
                    vhost.write_text(initial.replace(extension, replacement))
                    with self.assertRaises(cache.CacheManageError) as observed:
                        cache._site_sources(self.site, '85',
                            vhost_root=str(self.vhost), nginx_root=str(self.nginx))
                    self.assertIsNone(observed.exception.reason_code)
                finally:
                    vhost.write_text(initial)

    def test_multiple_or_unrecognized_native_php_includes_fail_closed(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        try:
            for replacement in (
                'include enable-php-81.conf;\n include enable-php-85.conf;',
                'include enable-php-74.conf;\n include enable-php-85.conf;',
                'include enable-php-74.conf;',
            ):
                with self.subTest(replacement=replacement):
                    vhost.write_text(original.replace(
                        'include enable-php-85.conf;', replacement))
                    with self.assertRaisesRegex(
                            cache.CacheManageError,
                            'Unsupported selected native VHost include order'):
                        cache._site_sources(self.site, '85',
                                            vhost_root=str(self.vhost),
                                            nginx_root=str(self.nginx))
        finally:
            vhost.write_text(original)

    def test_reverse_php_version_switch_is_also_diagnostic_only(self):
        (self.nginx / 'enable-php-81.conf').write_text(
            (self.nginx / 'enable-php-85.conf').read_text().replace(
                'php-cgi-85.sock', 'php-cgi-81.sock'))
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        try:
            vhost.write_text(original.replace('enable-php-85.conf',
                                              'enable-php-81.conf'))
            compatible = cache._site_sources(self.site, '81',
                vhost_root=str(self.vhost), nginx_root=str(self.nginx))
            self.assertIn('vhost_sha', compatible)
            vhost.write_text(original)
            with self.assertRaisesRegex(cache.CacheManageError,
                                         'PHP 8\\.1.*PHP 8\\.5.*Recheck'):
                cache._site_sources(self.site, '81',
                    vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        finally:
            vhost.write_text(original)

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
            (self.vhost/'qa.test.conf',' add_header X-ACh-Cache-Site forged;\n',
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

    def test_native_server_hsts_kept_by_managed_php_with_recovery(self):
        """A real aaPanel HTTPS site's HSTS must survive Cache Apply/Restore."""
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        hsts = 'add_header Strict-Transport-Security "max-age=31536000";'
        vhost.write_text(original.replace(
            ' include enable-php-85.conf;',
            ' ' + hsts + '\n include enable-php-85.conf;'))
        sources = cache._site_sources(
            self.site, '85', vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        self.assertEqual(sources['inherited_hsts'], hsts)

        def native_compat(site, public, **kwargs):
            return (self.native, cache.generate_reference(
                7, '85', cache_generation=kwargs.get('cache_generation'),
                inherited_hsts=sources['inherited_hsts']), sources)

        with patch.object(cache, '_compatibility', side_effect=native_compat):
            preview = self.preview()
            self.assertTrue(preview['preserved_server_hsts'])
            applied = self.apply()
            self.assertEqual(applied['state'], 'Applied')
            journal_path = self.state / cache._names(7)[2]
            journal = json.loads(journal_path.read_text())
            self.assertEqual(journal['inherited_hsts'], hsts)
            self.assertEqual(cache._record_decode(journal_path.read_bytes(), 7), journal)
            fragment = (self.ext / cache._names(7)[1]).read_text()
            self.assertEqual(fragment.count('    ' + hsts + '\n'), 1)
            self.assertIn('add_header X-ACh-Cache-Site 7 always;', fragment)
            self.assertEqual(
                cache.manage_cache('recheck', self.site, public=object(),
                                   **self.kwargs())['state'], 'Applied')

            # Recheck and recovery must not trust a different native HSTS.
            changed = vhost.read_text().replace('31536000', '63072000')
            vhost.write_text(changed)
            self.assertEqual(
                cache.manage_cache('recheck', self.site, public=object(),
                                   **self.kwargs())['state'], 'Needs Review')
            with self.assertRaises(cache.CacheManageError):
                cache.manage_cache('restore', self.site, recovery_id=applied['recovery_id'],
                                   approved=True, **self.kwargs())
            self.assertTrue((self.ext / cache._names(7)[1]).exists())
            vhost.write_text(original.replace(
                ' include enable-php-85.conf;',
                ' ' + hsts + '\n include enable-php-85.conf;'))
            self.assertEqual(cache.manage_cache(
                'restore', self.site, recovery_id=applied['recovery_id'],
                approved=True, **self.kwargs())['state'], 'Restored')
            self.assertNotIn('ach_customizer_cache_7.conf', [p.name for p in self.ext.iterdir()])
            self.assertEqual(
                cache.manage_cache('recheck', self.site, public=object(),
                                   **self.kwargs())['state'], 'Restored')

    def test_hsts_changes_between_preview_and_fragment_publication_rejected(self):
        """A stale approved proposal must not publish newly observed HSTS."""
        preview = self.preview()
        header = 'add_header Strict-Transport-Security "max-age=31536000";'
        current = cache._site_sources(
            self.site, '85', vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        observed = dict(current, inherited_hsts=header)
        with patch.object(cache, '_site_sources', return_value=observed):
            with self.assertRaisesRegex(cache.CacheManageError,
                                        'proposal changed after approval'):
                cache.manage_cache(
                    'apply', self.site, public=object(), approved=True,
                    cache_generation=preview['cache_generation'],
                    expected_source=preview['source_sha256'],
                    expected_proposal=preview['proposal_sha256'],
                    **self.kwargs())
        self.assertFalse((self.state / cache._names(7)[2]).exists())
        self.assertFalse((self.ext / cache._names(7)[1]).exists())
        self.assertFalse((self.vhost / cache._names(7)[0]).exists())

    def test_unverified_native_response_headers_are_not_replaced(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        valid = 'add_header Strict-Transport-Security "max-age=31536000";'
        cases = (
            'add_header X-ACh-Cache forged;',
            'add_header X-ACh-Cache-Site 8 always;',
            'location /private { ' + valid + ' }',
            'server { ' + valid + ' }',
            'if ($host = "qa.test") { ' + valid + ' }',
            'add_header_inherit merge;',
            'add_header Cache-Control private;',
            'add_header Set-Cookie "session=example";',
            'add_header X-Test first second third;',
        )
        for extra in cases:
            with self.subTest(extra=extra):
                vhost.write_text(original.replace(
                    ' include enable-php-85.conf;',
                    ' ' + extra + '\n include enable-php-85.conf;'))
                with self.assertRaises(cache.CacheManageError):
                    cache._site_sources(self.site, '85', vhost_root=str(self.vhost),
                                        nginx_root=str(self.nginx))
        vhost.write_text(original)

    def test_mixed_server_headers_preserved_for_stock_and_native_wordpress(self):
        vhost = self.vhost / 'qa.test.conf'
        original = vhost.read_text()
        headers = [
            'add_header Strict-Transport-Security "max-age=31536000";',
            """add_header Alt-Svc 'quic=":443"; h3=":443"';""",
            'add_header Content-Security-Policy "default-src self; object-src none" always;',
        ]
        vhost.write_text(original.replace(' include enable-php-85.conf;',
            ' ' + '\n '.join(headers) + '\n include enable-php-85.conf;'))
        sources = cache._site_sources(self.site, '85',
            vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        self.assertIsNone(sources['inherited_hsts'])
        self.assertEqual(sources['inherited_headers'], headers)
        def compat(site, public, **kw):
            return (self.native, cache.generate_reference(
                7, '85', cache_generation=kw.get('cache_generation'),
                inherited_headers=headers), sources)
        with patch.object(cache, '_compatibility', side_effect=compat):
            applied = self.apply()
            journal = json.loads((self.state / cache._names(7)[2]).read_text())
            self.assertEqual(journal['inherited_headers'], headers)
            self.assertEqual(cache._record_decode(json.dumps(journal), 7), journal)
            ext = (self.ext / cache._names(7)[1]).read_text()
            for header in headers:
                self.assertEqual(ext.count(header), 1)
            self.assertEqual(cache.manage_cache('restore', self.site,
                recovery_id=applied['recovery_id'], approved=True, **self.kwargs())['state'], 'Restored')
        from ach_customizer_cache_policy import WP_NATIVE_CANONICAL
        vhost.write_text(vhost.read_text().replace('enable-php-85.conf;', 'enable-php-85-wpfastcgi.conf;'))
        (self.nginx/'enable-php-85-wpfastcgi.conf').write_text(WP_NATIVE_CANONICAL.replace('NATIVE_PHP','85'))
        wp = cache._site_sources(self.site, '85', native_handler='wpfastcgi',
            vhost_root=str(self.vhost), nginx_root=str(self.nginx))
        self.assertIsNone(wp['inherited_hsts'])
        self.assertNotIn('inherited_headers', wp)

    def test_hsts_journal_is_strict_and_legacy_journal_still_reads(self):
        applied = self.apply()
        journal = json.loads((self.state / cache._names(7)[2]).read_text())
        self.assertNotIn('inherited_hsts', journal)
        self.assertEqual(cache._record_decode(json.dumps(journal), 7), journal)
        for unsafe in ('add_header X-Test ok;', 'add_header Strict-Transport-Security "$var";',
                       'add_header Strict-Transport-Security "max-age=31536000";\ninclude /etc/passwd;',
                       None, True, 15):
            with self.subTest(unsafe=unsafe):
                forged = dict(journal, inherited_hsts=unsafe)
                with self.assertRaises(cache.CacheManageError):
                    cache._record_decode(json.dumps(forged), 7)

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


    def test_site_cache_file_clear_requires_fresh_applied_identity_and_consent(self):
        with patch.object(cache, '_scan_site_cache_files') as physical:
            with self.assertRaises(cache.CacheManageError):
                cache.manage_cache('clear_files', self.site,
                    approved=True, recovery_id='a'*32, **self.kwargs())
            physical.assert_not_called()
            applied = self.apply()
            unchanged = list(self.commands)
            for approved, recovery in ((False, applied['recovery_id']),
                                       (True, 'f'*32), (True, None)):
                with self.subTest(approved=approved, recovery=recovery):
                    with self.assertRaises(cache.CacheManageError):
                        cache.manage_cache('clear_files', self.site,
                            public=object(), approved=approved,
                            recovery_id=recovery, **self.kwargs())
            physical.assert_not_called()
            physical.side_effect = [2, 2]
            cleared = cache.manage_cache('clear_files', self.site,
                public=object(), approved=True,
                recovery_id=applied['recovery_id'], **self.kwargs())
            self.assertEqual(cleared['state'], 'Applied')
            self.assertTrue(cleared['changed'])
            self.assertEqual(cleared['cache_files_removed'], 2)
            self.assertFalse(cleared['purge_supported'])
            self.assertEqual(cleared['recovery_id'], applied['recovery_id'])
            self.assertEqual(physical.call_count, 2)
            self.assertEqual(physical.call_args.kwargs, {'remove':True})
            self.assertEqual(self.commands, unchanged, 'File clear must not reload Nginx')
            self.assertEqual(cache.manage_cache('recheck',self.site,
                 public=object(), **self.kwargs())['state'], 'Applied')
            fd = cache._open_state_dir(str(self.state))
            try:
                self.assertEqual(cache._record_read(fd, 7)['phase'], 'applied')
            finally:
                os.close(fd)

    def test_manual_url_clear_requires_applied_recheck_and_only_target_url(self):
        with patch.object(cache, '_clear_site_cache_url', return_value=2) as targeted, \
             patch.object(cache, '_scan_site_cache_files', return_value=4) as scan:
            with self.assertRaises(cache.CacheManageError):
                cache.manage_cache('clear_url', self.site, public=object(),
                    approved=True, recovery_id='f'*32, cache_url_path='/news/',
                    **self.kwargs())
            targeted.assert_not_called()
            applied = self.apply()
            for approval, operation in ((False, applied['recovery_id']),
                                         (True, 'f'*32)):
                with self.assertRaises(cache.CacheManageError):
                    cache.manage_cache('clear_url', self.site, public=object(),
                        approved=approval, recovery_id=operation,
                        cache_url_path='/news/', **self.kwargs())
            targeted.assert_not_called()
            outcome = cache.manage_cache('clear_url', self.site, public=object(),
                approved=True, recovery_id=applied['recovery_id'],
                cache_url_path='/news/', **self.kwargs())
            self.assertEqual(outcome['state'], 'Applied')
            self.assertEqual(outcome['cache_url_path'], '/news/')
            self.assertEqual(outcome['cache_files_removed'], 2)
            self.assertEqual(targeted.call_count, 1)
            self.assertEqual(targeted.call_args.args,
                (7,[19,23], 'qa.test', self._active_cache_generation(), '/news/'))
            scan.assert_not_called()
            self.assertEqual(self.commands.count((cache.NGINX,'-s','reload',
                '-c',str(self.nginx/'nginx.conf'))),1)

    def _active_cache_generation(self):
        fd=cache._open_state_dir(str(self.state))
        try:
            return cache._record_read(fd,7)['cache_generation']
        finally:
            os.close(fd)

    def test_manual_url_clear_blocks_physical_peer_drift_before_any_delete(self):
        applied=self.apply()
        with patch.object(cache, '_verify_cache_peer_isolation',
                side_effect=cache.CacheManageError('compatibility',
                    'Registered Cache directories physically overlap')):
            with patch.object(cache, '_clear_site_cache_url') as targeted:
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'physically overlap'):
                    cache.manage_cache('clear_url', self.site, public=object(),
                        approved=True, recovery_id=applied['recovery_id'],
                        cache_url_path='/', **self.kwargs())
                targeted.assert_not_called()

    def test_manual_url_clear_uncertain_outcome_requires_recheck(self):
        applied=self.apply()
        with patch.object(cache, '_scan_site_cache_files',return_value=0), \
             patch.object(cache, '_clear_site_cache_url',
                 side_effect=OSError('unlink failed')):
            with self.assertRaises(cache.CacheManageError) as caught:
                cache.manage_cache('clear_url', self.site, public=object(),
                    approved=True, recovery_id=applied['recovery_id'],
                    cache_url_path='/news/', **self.kwargs())
        self.assertEqual(caught.exception.stage,'uncertain')
        self.assertEqual(caught.exception.recovery_id,applied['recovery_id'])
        self.assertEqual(cache.manage_cache('recheck',self.site,
            public=object(),**self.kwargs())['state'], 'Applied')

    def test_cache_file_clear_blocks_new_physical_peer_alias_before_unlink(self):
        applied = self.apply()
        with patch.object(cache, '_scan_site_cache_files') as physical:
            with patch.object(cache, 'inspect_site_fastcgi_cache', return_value={
                    'state':'Source Observed','zone_state':'Direct Zone',
                    'cache_zone':'ACHFC_7','cache_directory':self.ref['cache_directory'],
                    'unresolved_other_sites':0,
                    'other_sites_same_directory':[{'id':8,'site_key':'peer.test'}],
                    'other_sites_same_zone':[] }):
                with self.assertRaisesRegex(cache.CacheManageError, 'isolation'):
                    cache.manage_cache('clear_files', self.site,
                        public=object(), approved=True,
                        recovery_id=applied['recovery_id'], **self.kwargs())
            physical.assert_not_called()

    def test_cache_clear_rejects_unresolved_peer_identity_before_unlink(self):
        applied = self.apply()
        source = {
            'state':'Source Observed','zone_state':'Direct Zone',
            'cache_zone':'ACHFC_7','cache_directory':self.ref['cache_directory'],
            'unresolved_other_sites':0,'other_sites_same_directory':[],
            'other_sites_same_zone':[],
            'physical_peer_cache_paths':[{'id':8,'directory':None}],
        }
        with patch.object(cache,'inspect_site_fastcgi_cache',return_value=source):
            with patch.object(cache, '_scan_site_cache_files') as scanner:
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'physical separation is unverified'):
                    cache.manage_cache('clear_files',self.site,public=object(),
                        approved=True,recovery_id=applied['recovery_id'],
                        **self.kwargs())
                scanner.assert_not_called()

    def test_cache_clear_refuses_discovered_peer_alias_before_unlink(self):
        applied=self.apply()
        source = {
            'state':'Source Observed','zone_state':'Direct Zone',
            'cache_zone':'ACHFC_7','cache_directory':self.ref['cache_directory'],
            'unresolved_other_sites':0,'other_sites_same_directory':[],
            'other_sites_same_zone':[], 'purge_scope':'Unknown',
            'physical_peer_cache_paths':[
                {'id':8,'directory':'/some/other/canonical/cache'}
            ],
        }
        with patch.object(cache,'inspect_site_fastcgi_cache',return_value=source):
            with patch.object(cache,'_verify_cache_peer_isolation',
                              side_effect=cache.CacheManageError(
                                  'compatibility','Registered Cache directories physically overlap'
                              )) as verifier:
                with patch.object(cache,'_scan_site_cache_files') as scanner:
                    with self.assertRaisesRegex(cache.CacheManageError,
                                                'physically overlap'):
                        cache.manage_cache('clear_files',self.site,public=object(),
                            approved=True,recovery_id=applied['recovery_id'],
                            **self.kwargs())
                    scanner.assert_not_called()
                    verifier.assert_called_once()

    def test_cache_clear_allows_verified_distinct_peer_even_if_purge_scope_unknown(self):
        applied = self.apply()
        source = {
            'state':'Source Observed','zone_state':'Direct Zone',
            'cache_zone':'ACHFC_7','cache_directory':self.ref['cache_directory'],
            'unresolved_other_sites':0,'other_sites_same_directory':[],
            'other_sites_same_zone':[], 'purge_scope':'Unknown',
            'physical_peer_cache_paths':[
                {'id':8,'directory':'/a/separate/peer/cache'}
            ],
        }
        with patch.object(cache,'inspect_site_fastcgi_cache',return_value=source):
            with patch.object(cache,'_verify_cache_peer_isolation',
                              return_value=((8,'/a/separate/peer/cache',((1,2),(3,4))),)) as physical:
                with patch.object(cache,'_scan_site_cache_files',
                                  side_effect=[3,3]) as scanner:
                    result=cache.manage_cache('clear_files',self.site,public=object(),
                        approved=True,recovery_id=applied['recovery_id'],
                        **self.kwargs())
        self.assertEqual(result['cache_files_removed'],3)
        self.assertEqual(physical.call_count,3)
        self.assertEqual(scanner.call_count,2)

    def test_cache_clear_topology_changes_before_unlink(self):
        applied = self.apply()
        with patch.object(cache,'_verify_cache_peer_isolation',
                          side_effect=[('initial',),('changed',)]) as verify:
            with patch.object(cache,'_scan_site_cache_files',
                              return_value=1) as scanner:
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'not fully confirmed'):
                    cache.manage_cache('clear_files',self.site,public=object(),
                        approved=True,recovery_id=applied['recovery_id'],
                        **self.kwargs())
                self.assertEqual(verify.call_count,2)
                scanner.assert_called_once_with(7,[19,23])


    def test_nested_bind_alias_denies_manual_clear_before_first_unlink(self):
        applied = self.apply()
        source = {
            'state':'Source Observed', 'zone_state':'Direct Zone',
            'cache_zone':'ACHFC_7', 'cache_directory':self.ref['cache_directory'],
            'unresolved_other_sites':0, 'other_sites_same_directory':[],
            'other_sites_same_zone':[], 'purge_scope':'Unknown',
            'physical_peer_cache_paths':[
                {'id':8, 'directory':'/www/server/fastcgi_cache'}
            ],
        }
        # Both Cache roots appear independent; one peer child is an external
        # bind destination pointing to a selected-site child inode.
        selected=((1,1),(19,22),(19,23))
        peer=((1,1),(19,22),(19,48),(19,49))
        def inode_chain(path):
            if path == self.ref['cache_directory']:
                return selected
            if path == '/www/server/fastcgi_cache':
                return peer
            raise AssertionError('unexpected filesystem identity request')
        mount=((source['physical_peer_cache_paths'][0]['directory'],
                '/www/server/fastcgi_cache/8','814',(19,77)),)
        with patch.object(cache,'inspect_site_fastcgi_cache',return_value=source):
            with patch.object(cache,'_cache_directory_identity_chain',
                              side_effect=inode_chain):
                with patch.object(cache,'_cache_peer_mounts',return_value=mount):
                    with patch.object(cache,'_cache_peer_symlink_targets',
                                      return_value=((),set())):
                        with patch.object(cache,'_selected_cache_contains_mount_identity',
                                          return_value=True):
                            with patch.object(cache,'_scan_site_cache_files') as scanner:
                                with self.assertRaisesRegex(cache.CacheManageError,
                                                            'subtrees physically overlap'):
                                    cache.manage_cache('clear_files',self.site,
                                        public=object(), approved=True,
                                        recovery_id=applied['recovery_id'],**self.kwargs())
                                scanner.assert_not_called()

    def test_cache_clear_physical_peer_symlink_refused_before_any_file_walk(self):
        applied = self.apply()
        selected = self.root/'selected-cache-fixture'
        peer = self.root/'independent-peer-fixture'
        (selected/'8'/'aa').mkdir(parents=True)
        peer.mkdir()
        token = 'b'*29+'aa8'
        proof = selected/'8'/'aa'/token
        proof.write_bytes(b'keep-selected-cache-object')
        (peer/'8').symlink_to(selected/'8', target_is_directory=True)
        actual_guard = cache._verify_cache_peer_isolation
        st = os.stat(selected)
        source = {
            'state':'Source Observed','zone_state':'Direct Zone',
            'cache_zone':'ACHFC_7','cache_directory':self.ref['cache_directory'],
            'unresolved_other_sites':0,'other_sites_same_directory':[],
            'other_sites_same_zone':[], 'purge_scope':'Unknown',
            'physical_peer_cache_paths':[{'id':8,'directory':str(peer)}],
        }
        def physical(*_):
            return actual_guard(str(selected),(st.st_dev,st.st_ino),
                                source['physical_peer_cache_paths'])
        with patch.object(cache,'inspect_site_fastcgi_cache',return_value=source):
            with patch.object(cache,'_verify_cache_peer_isolation',
                              side_effect=physical):
                with patch.object(cache,'_scan_site_cache_files') as scanner:
                    with self.assertRaisesRegex(cache.CacheManageError,
                                                'subtrees physically overlap'):
                        cache.manage_cache('clear_files',self.site,
                            public=object(),approved=True,
                            recovery_id=applied['recovery_id'],**self.kwargs())
                    scanner.assert_not_called()
        self.assertEqual(proof.read_bytes(), b'keep-selected-cache-object')

    def test_cache_file_clear_refuses_restored_and_changed_source(self):
        applied = self.apply()
        with patch.object(cache, '_scan_site_cache_files') as physical:
            native = self.vhost/'qa.test.conf'
            original = native.read_bytes()
            native.write_bytes(original + bytes([10]) + b'# drift' + bytes([10]))
            with self.assertRaisesRegex(cache.CacheManageError, 'not verified Applied'):
                cache.manage_cache('clear_files', self.site, public=object(),
                    approved=True, recovery_id=applied['recovery_id'], **self.kwargs())
            native.write_bytes(original)
            physical.assert_not_called()
            cache.manage_cache('restore', self.site, public=object(), approved=True,
                recovery_id=applied['recovery_id'], **self.kwargs())
            with self.assertRaises(cache.CacheManageError):
                cache.manage_cache('clear_files', self.site, public=object(),
                    approved=True, recovery_id=applied['recovery_id'], **self.kwargs())
            physical.assert_not_called()

    def test_partial_cache_file_clear_is_uncertain_with_recovery_identity(self):
        applied = self.apply()
        with patch.object(cache, '_scan_site_cache_files',
                          side_effect=[4, OSError('simulated mid-unlink error')]):
            with self.assertRaises(cache.CacheManageError) as caught:
                cache.manage_cache('clear_files', self.site,
                    public=object(), approved=True,
                    recovery_id=applied['recovery_id'], **self.kwargs())
        self.assertEqual(caught.exception.stage, 'uncertain')
        self.assertEqual(caught.exception.recovery_id, applied['recovery_id'])
        self.assertEqual(cache.manage_cache('recheck', self.site,
              public=object(), **self.kwargs())['state'], 'Applied')

    def test_physical_cache_clear_rejects_foreign_nodes_and_preserves_peer(self):
        root = self.root / 'cache-root'
        root.mkdir()
        a = root / 'site-7'
        b = root / 'site-8'
        for site_dir, prefix, suffix in ((a, 'c', '4a'), (b, 'd', '5b')):
            leaf = site_dir / prefix / suffix
            leaf.mkdir(parents=True)
            site_dir.chmod(0o750)
            (site_dir / prefix).chmod(0o700)
            leaf.chmod(0o700)
            obj = leaf / ('0'*29+suffix+prefix)
            obj.write_bytes(b'generated-cache-data')
            obj.chmod(0o600)
        owner = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        cache_identity = (a.stat().st_dev, a.stat().st_ino)
        with patch.object(cache,'CACHE_ROOT',str(root)), \
             patch.object(cache, '_path_owned', return_value=cache_identity), \
             patch.object(cache.pwd, 'getpwnam', return_value=owner):
            foreign = a/'unexpected.txt'
            foreign.write_bytes(b'untouched')
            with self.assertRaises(cache.CacheManageError):
                cache._scan_site_cache_files(7, cache_identity)
            self.assertEqual(len(list(a.rglob('0'*29+'4ac'))), 1)
            foreign.unlink()
            # A symlink hidden among otherwise legitimate files is rejected.
            linked = a/'c'/'4a'/('0'*29+'4ad')
            linked.symlink_to('/etc/hosts')
            with self.assertRaises(cache.CacheManageError):
                cache._scan_site_cache_files(7, cache_identity)
            self.assertEqual(len(list(a.rglob('0'*29+'4ac'))), 1)
            linked.unlink()
            self.assertEqual(cache._scan_site_cache_files(7, cache_identity), 1)
            self.assertEqual(cache._scan_site_cache_files(7, cache_identity,
                             remove=True), 1)
            self.assertEqual(len(list(a.rglob('0'*29+'4ac'))), 0)
            self.assertTrue((b/'d'/'5b'/('0'*29+'5bd')).is_file())
            self.assertTrue((a/'c'/'4a').is_dir())
            self.assertEqual(cache._scan_site_cache_files(7, cache_identity), 0)



    def _configure_native_wordpress(self):
        from ach_customizer_cache_policy import WP_NATIVE_CANONICAL
        vhost=self.vhost/'qa.test.conf'
        text=vhost.read_text().replace(
            'include enable-php-85.conf;',
            'add_header Strict-Transport-Security "max-age=31536000";\n'
            ' include enable-php-85-wpfastcgi.conf;')
        vhost.write_text(text)
        (self.nginx/'enable-php-85-wpfastcgi.conf').write_text(
            WP_NATIVE_CANONICAL.replace('NATIVE_PHP','85'))
        return cache._site_sources(
            self.site,'85',native_handler='wpfastcgi',
            vhost_root=str(self.vhost),nginx_root=str(self.nginx))

    def test_known_native_wordpress_php_and_headers_generate_distinct_source(self):
        source=self._configure_native_wordpress()
        self.assertEqual(source['native_handler'],'wpfastcgi')
        self.assertIsNone(source['inherited_hsts'])
        self.assertEqual(len(source['php_sha']),64)
        from ach_customizer_cache_policy import WP_PHP_RESPONSE_DIRECTIVES
        generation='b'*32
        plan=cache.generate_reference(7,'85',cache_generation=generation,
                                      native_handler='wpfastcgi')
        other=cache.generate_reference(7,'85',cache_generation=generation)
        self.assertNotEqual(plan['proposal_sha256'],other['proposal_sha256'])
        self.assertEqual(plan['native_handler'],'wpfastcgi')
        self.assertIn('try_files $uri $uri/ /index.php?$args;',plan['site_server_fragment'])
        self.assertNotIn('include pathinfo.conf;',plan['site_server_fragment'])
        self.assertIn('fastcgi_cache ACHFC_7;',plan['site_server_fragment'])
        self.assertNotIn('fastcgi_cache WORDPRESS;',plan['site_server_fragment'])
        self.assertIn('fastcgi_ignore_headers Set-Cookie;',plan['site_server_fragment'])
        for directive in WP_PHP_RESPONSE_DIRECTIVES:
            self.assertIn(directive,plan['site_server_fragment'])
        self.assertNotIn('fastcgi_cache_purge',plan['site_server_fragment'])
        self.assertNotIn('add_header Strict-Transport-Security "max-age=31536000"',
                         plan['site_server_fragment'])

    def test_native_wordpress_drift_and_foreign_php_fail_closed(self):
        sources=self._configure_native_wordpress()
        php=self.nginx/'enable-php-85-wpfastcgi.conf'
        original=php.read_text()
        for before,after in (
                ('try_files $uri $uri/ /index.php?$args;','try_files $uri =404;'),
                ('fastcgi_cache WORDPRESS;','fastcgi_cache FOREIGN;'),
                ('fastcgi_cache_bypass $skip_cache;','fastcgi_cache_bypass off;'),
                ('fastcgi_cache_purge WORDPRESS','fastcgi_cache_purge FOREIGN'),
                ('add_header X-Content-Type-Options nosniff;',''),
                ('add_header Strict-Transport-Security','add_header X-Fake-Header'),
                ('fastcgi_cache_valid 200 1d;','fastcgi_cache_valid 200 30d;'),
                ('allow 127.0.0.1;','allow all;'),
                ('fastcgi_pass unix:/tmp/php-cgi-85.sock;',
                 'fastcgi_pass unix:/tmp/php-cgi-81.sock;'),
        ):
            with self.subTest(change=before):
                self.assertIn(before,original)
                php.write_text(original.replace(before,after))
                with self.assertRaisesRegex(cache.CacheManageError,
                                            'WordPress handler differs'):
                    cache._site_sources(self.site,'85',native_handler='wpfastcgi',
                                        vhost_root=str(self.vhost),
                                        nginx_root=str(self.nginx))
        php.write_text(original)
        self.assertEqual(
            cache._site_sources(self.site,'85',native_handler='wpfastcgi',
                                vhost_root=str(self.vhost),
                                nginx_root=str(self.nginx)),sources)

    def test_wordpress_native_approved_lifecycle_and_journal(self):
        self.sources=self._configure_native_wordpress()
        self.native=dict(self.native,zone_state='Direct Zone',
                         cache_zone='WORDPRESS',purge_directive_seen=True)
        def wp_compat(site,public,**kw):
            return (self.native,
                    cache.generate_reference(
                        site['id'],'85',
                        cache_generation=kw.get('cache_generation'),
                        native_handler='wpfastcgi'),
                    self.sources)
        with patch.object(cache,'_compatibility',side_effect=wp_compat):
            plan=self.preview()
            self.assertEqual(plan['native_handler'],'wpfastcgi')
            self.assertFalse(plan['preserved_server_hsts'])
            applied=cache.manage_cache(
                'apply',self.site,public=object(),
                expected_source=plan['source_sha256'],
                expected_proposal=plan['proposal_sha256'],
                cache_generation=plan['cache_generation'],
                approved=True,**self.kwargs())
        self.assertEqual(applied['state'],'Applied')
        journal=self.state/cache._names(7)[2]
        record=json.loads(journal.read_text())
        self.assertEqual(record['native_handler'],'wpfastcgi')
        self.assertEqual(record['phase'],'applied')
        _, owned_extension=cache._expected_files(record)
        self.assertIn(b'try_files $uri $uri/ /index.php?$args;',owned_extension)
        rechecked=cache.manage_cache(
            'recheck',self.site,public=object(),**self.kwargs())
        self.assertEqual(rechecked['state'],'Applied')
        restored=cache.manage_cache(
            'restore',self.site,public=object(),recovery_id=applied['recovery_id'],
            approved=True,**self.kwargs())
        self.assertEqual(restored['state'],'Restored')
        self.assertFalse((self.ext/cache._names(7)[1]).exists())
        self.assertEqual(json.loads(journal.read_text())['phase'],'restored')
        record['native_handler']='unknown'
        with self.assertRaisesRegex(cache.CacheManageError,'Untrusted'):
            cache._record_decode(json.dumps(record),7)
        record.pop('native_handler')
        # A historical stock-PHP journal remains decodable as before.
        record['phase']='restored'
        self.assertNotIn('native_handler',cache._record_decode(json.dumps(record),7))


class CacheExactUrlFileTests(unittest.TestCase):
    """One URL's real Nginx levels=1:2 key files, not a recursive purge."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ach-cache-url-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.parent = self.base/'cache'
        self.parent.mkdir()
        self.selected = self.parent/'site-7'
        self.selected.mkdir(mode=0o750)
        self.peer = self.parent/'site-8'
        self.peer.mkdir(mode=0o750)
        s = self.selected.stat()
        self.identity = (s.st_dev, s.st_ino)
        self.generation = 'a'*32
        self.owner = SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
        for target in ('CACHE_ROOT',):
            p = patch.object(cache, target, str(self.parent))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(cache, '_path_owned', return_value=self.identity)
        p.start(); self.addCleanup(p.stop)
        p = patch.object(cache.pwd, 'getpwnam', return_value=self.owner)
        p.start(); self.addCleanup(p.stop)

    def object(self, *, scheme='http', method='GET', path='/news/',
               host='qa.test', generation=None, target=None, corrupt=False):
        gen = self.generation if generation is None else generation
        key = (scheme + method + host + path + '|' + gen).encode('ascii')
        import hashlib
        digest = hashlib.md5(key).hexdigest()
        directory = (target or self.selected)/digest[-1]/digest[-3:-1]
        directory.mkdir(parents=True, exist_ok=True)
        directory.parent.chmod(0o700)
        directory.chmod(0o700)
        cached = directory/digest
        cached.write_bytes(b'\0'*337+b'KEY: '+(b'untrusted' if corrupt else key)+b'\n'+b'HTTP/1.1 200 OK\r\n\r\n')
        cached.chmod(0o600)
        return cached

    def clear(self, path='/news/'):
        return cache._clear_site_cache_url(7, self.identity, 'qa.test', self.generation, path)

    def test_exact_four_keys_only_and_no_missing_file_failure(self):
        targets = [self.object(scheme=s, method=m)
                   for s in ('http', 'https') for m in ('GET', 'HEAD')]
        old = self.object(generation='b'*32)
        other = self.object(path='/another/')
        aliased = self.object(host='alias.qa.test')
        peer = self.object(target=self.peer)
        self.assertEqual(self.clear(), 4)
        self.assertTrue(all(not p.exists() for p in targets))
        self.assertTrue(all(p.is_file() for p in (old, other, aliased, peer)))
        self.assertEqual(self.clear(), 0)

    def test_foreign_object_elsewhere_is_unaffected_by_targeted_clear(self):
        cache_file = self.object()
        unrelated = self.selected/'foreign-note.txt'
        unrelated.write_text('not a Cache object')
        self.assertEqual(self.clear(),1)
        self.assertFalse(cache_file.exists())
        self.assertEqual(unrelated.read_text(),'not a Cache object')

    def test_single_target_file_and_root_path(self):
        root = self.object(path='/')
        self.assertEqual(self.clear('/'), 1)
        self.assertFalse(root.exists())
        self.assertEqual(self.clear('/'), 0)

    def test_wrong_key_header_cannot_delete_matching_md5_filename(self):
        forged = self.object(corrupt=True)
        original = forged.read_bytes()
        with self.assertRaisesRegex(cache.CacheManageError, 'KEY header'):
            self.clear()
        self.assertEqual(forged.read_bytes(), original)

    def test_symlink_file_is_not_followed_or_deleted(self):
        target = self.base/'retain'
        target.write_text('protected')
        file = self.object()
        file.unlink()
        file.symlink_to(target)
        with self.assertRaisesRegex(cache.CacheManageError, 'Untrusted Cache key file'):
            self.clear()
        self.assertTrue(file.is_symlink())
        self.assertEqual(target.read_text(), 'protected')

    def test_symlink_directory_does_not_escape_cache_root(self):
        file = self.object()
        parent = file.parent
        renamed = parent.with_name(parent.name+'-held')
        parent.rename(renamed)
        parent.symlink_to(renamed, target_is_directory=True)
        with self.assertRaisesRegex(cache.CacheManageError, 'Untrusted Cache key directory'):
            self.clear()
        self.assertTrue((renamed/file.name).is_file())

    def test_hardlink_file_is_not_modified(self):
        original = self.object()
        peer_link = self.base/'also-linked'
        os.link(original, peer_link)
        with self.assertRaisesRegex(cache.CacheManageError, 'Untrusted Cache key file'):
            self.clear()
        self.assertTrue(original.is_file())
        self.assertTrue(peer_link.is_file())

    def test_untrusted_path_has_no_filesystem_effect(self):
        file = self.object()
        for invalid in ('', 'news/', 'https://qa.test/news/',
                        '//qa.test/news/', '/news?draft=1', '/news#anchor',
                        '/fa%20name/', '/a//b/', '/a/./b', '/a/../b',
                        '/a\\b', '/a b', '/☃/', '/'+'x'*1024, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(cache.CacheManageError):
                    self.clear(invalid)
                self.assertTrue(file.is_file())

if __name__=='__main__':
    unittest.main()
