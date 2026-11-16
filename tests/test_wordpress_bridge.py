"""Independent WordPress companion: source-only PHP stubs and deterministic ZIP."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "wordpress" / "ach-aapanel-bridge"
PHP = shutil.which("php")
ENTRY = PLUGIN / "ach-aapanel-bridge.php"


def php_run(source):
    return subprocess.run(
        [PHP, "-n", "-d", "display_errors=1", "-r", source],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=20
    )


@unittest.skipUnless(PHP, "PHP CLI unavailable; GitHub CI requires PHP lint")
class WordPressBridgeRuntimeTests(unittest.TestCase):
    def test_syntax_all_entrypoints(self):
        for path in sorted(PLUGIN.rglob("*.php")):
            with self.subTest(path=path.name):
                result = subprocess.run(
                    [PHP, "-n", "-l", str(path)],
                    capture_output=True, text=True, timeout=20
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_boot_only_registers_admin_menu(self):
        source = f"""
        define('ABSPATH', '/not-a-wordpress-install/');
        $actions = [];
        function add_action($name, $handler) {{ global $actions; $actions[$name] = $handler; }}
        require {json.dumps(str(ENTRY))};
        echo json_encode(array_keys($actions), JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["admin_menu"])

    def test_unauthorized_admin_page_refused(self):
        source = f"""
        define('ABSPATH', '/test/');
        function add_action($name, $handler) {{}}
        function current_user_can($capability) {{ return false; }}
        function esc_html__($value, $domain) {{ return $value; }}
        function wp_die($message, $title = '', $args = []) {{ throw new Exception('DENIED:' . $args['response']); }}
        require {json.dumps(str(ENTRY))};
        try {{
            \\AChWorks\\AaPanelBridge\\Plugin::renderAdminPage();
        }} catch (Exception $e) {{
            echo $e->getMessage();
        }}
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "DENIED:403")

    def test_admin_diagnostics_escape_runtime_data(self):
        source = f"""
        define('ABSPATH', '/test/');
        define('RT_WP_NGINX_HELPER_CACHE_PATH', '<script>alert(1)</script>');
        function add_action($name, $handler) {{}}
        function current_user_can($capability) {{ return true; }}
        function __($str, $domain) {{ return $str; }}
        function esc_html__($str, $domain) {{ return $str; }}
        function esc_html($value) {{ return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }}
        $GLOBALS['nginx_helper_admin'] = (object)['options' => [
            'purge_method'=>'unlink_files', 'enable_purge' => 1
        ]];
        require {json.dumps(str(ENTRY))};
        \\AChWorks\\AaPanelBridge\\Plugin::renderAdminPage();
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("<script>", result.stdout)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", result.stdout)
        self.assertIn("Not connected", result.stdout)
        self.assertIn("unlink_files", result.stdout)
        self.assertIn("requires generation-aware site ownership checks", result.stdout)

    def test_runtime_status_never_infers_safe_purge(self):
        with tempfile.TemporaryDirectory(prefix="ach-bridge-test-") as work:
            plugin = Path(work) / "nginx-helper" / "nginx-helper.php"
            plugin.parent.mkdir()
            plugin.write_text("<?php // stub; never executed", encoding="utf-8")
            source = f"""
            define('ABSPATH', '/test/');
            define('WP_PLUGIN_DIR', {json.dumps(work)});
            define('RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache');
            function is_plugin_active($name) {{ return true; }}
            function is_plugin_active_for_network($name) {{ return false; }}
            $GLOBALS['nginx_helper_admin'] = (object)['options' => [
                'purge_method' => 'get_request', 'enable_purge' => 0
            ]];
            require {json.dumps(str(PLUGIN / 'includes/class-nginx-helper-status.php'))};
            echo json_encode(\\AChWorks\\AaPanelBridge\\NginxHelperStatus::inspect(), JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(result.stdout)
            self.assertTrue(info["installed"])
            self.assertEqual(info["activation"], "active")
            self.assertEqual(info["purge_method"], "get_request")
            self.assertEqual(info["effective_cache_path"], "/www/server/fastcgi_cache")
            self.assertIs(info["automatic_purge_enabled"], False)
            self.assertIs(info["safe_purge_all_verified"], False)
            self.assertIs(info["customizer_invalidation_connected"], False)

    def test_frontend_runtime_identifies_active_helper_without_admin_functions(self):
        with tempfile.TemporaryDirectory(prefix="ach-bridge-helper-") as work:
            plugin = Path(work) / "nginx-helper" / "nginx-helper.php"
            plugin.parent.mkdir()
            plugin.write_text("<?php // stub", encoding="utf-8")
            source = f"""
            define('ABSPATH', '/test/');
            define('WP_PLUGIN_DIR', {json.dumps(work)});
            function get_option($key, $default) {{ return ['nginx-helper/nginx-helper.php']; }}
            function get_site_option($key, $default) {{ return []; }}
            $GLOBALS['nginx_helper_admin'] = (object)['options' =>
                ['purge_method'=>'unlink_files','enable_purge'=>1]];
            require {json.dumps(str(PLUGIN / 'includes/class-nginx-helper-status.php'))};
            echo json_encode(\\AChWorks\\AaPanelBridge\\NginxHelperStatus::inspect(),
                JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(result.stdout)
            self.assertEqual(info["activation"], "active")
            self.assertEqual(info["purge_method"], "unlink_files")
            self.assertTrue(info["automatic_purge_enabled"])

    def test_generation_scoped_url_mapping_validates_cache_header_and_peer(self):
        with tempfile.TemporaryDirectory(prefix="ach-bridge-map-") as work:
            base = Path(work) / "site9"
            base.mkdir(mode=0o700)
            peer = Path(work) / "site10"
            peer.mkdir(mode=0o700)
            site_key = "qa-wp.example"
            generation = "a" * 32
            key = "httpsGET" + site_key + "/article/" + "|" + generation
            from hashlib import md5
            digest = md5(key.encode()).hexdigest()
            target_dir = base / digest[-1] / digest[-3:-1]
            target_dir.mkdir(parents=True, mode=0o700)
            target_dir.parent.chmod(0o700)
            target_dir.chmod(0o700)
            target = target_dir / digest
            target.write_bytes(b"NGINX-HEADER\nKEY: " + key.encode() + b"\nprivate test")
            target.chmod(0o600)
            peer_key = "httpsGET" + site_key + "/article/|" + "b"*32
            peer_hash = md5(peer_key.encode()).hexdigest()
            peer_dir = peer / peer_hash[-1] / peer_hash[-3:-1]
            peer_dir.mkdir(parents=True)
            peer_file = peer_dir / peer_hash
            peer_file.write_bytes(b"PEER")
            st = base.stat()
            manifest = {"cache_directory": str(base),
                        "cache_identity": [st.st_dev, st.st_ino],
                        "site_id": 9, "site_key": site_key,
                        "cache_generation": generation}
            source = f"""
            define('ABSPATH', '/test/');
            require {json.dumps(str(PLUGIN / 'includes/class-nginx-helper-status.php'))};
            require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
            function wp_parse_url($url) {{ return parse_url($url); }}
            $manifest = json_decode({json.dumps(json.dumps(manifest))}, true);
            $url = 'https://qa-wp.example/article/';
            $deny = '/nonexistent/denied';
            $output = [];
            foreach ([$url, $url . '?a=1',
                'http://qa-wp.example/article/',
                'https://other.example/article/',
                'https://qa-wp.example:443/article/',
                'https://qa-wp.example/a/../article/',
                'https://qa-wp.example/%61rticle/',
                'https://qa-wp.example//article/',
                'https://qa-wp.example/article/#abc'] as $u) {{
                $output[] = \\AChWorks\\AaPanelBridge\\CacheInvalidation::selectVerifiedFile(
                    $manifest, $u, $deny);
            }}
            echo json_encode($output, JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
            self.assertEqual(actual[0], str(target))
            self.assertEqual(actual[1:], ["/nonexistent/denied"] * 8)
            self.assertTrue(target.exists())
            self.assertTrue(peer_file.exists())
            target.write_bytes(b"NOT THE SAVED NGINX KEY\n")
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)[0], "/nonexistent/denied")

    def test_post_save_uses_wordpress_four_argument_action_contract(self):
        # WP's wp_after_insert_post() function emits ID, WP_Post, update,
        # post_before in this order; the first parameter is NOT a WP_Post.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $ref = new ReflectionMethod(
            \AChWorks\AaPanelBridge\CacheInvalidation::class, 'afterPostSaved');
        echo json_encode(array_map(static function($p) {{ return $p->getName(); }},
            $ref->getParameters()), JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
            ['postId', 'post', 'update', 'postBefore'])
        self.assertIn(
            "add_action('wp_after_insert_post', [__CLASS__, 'afterPostSaved'], 50, 4)",
            (PLUGIN / 'includes/class-cache-invalidation.php').read_text())

    def test_post_save_guards_status_and_invalidates_both_slug_versions(self):
        source = f"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['slugs'] = [];
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return []; }}
        function home_url($path) {{ return 'https://qa.example/'; }}
        function get_permalink($post) {{
            $GLOBALS['slugs'][] = $post->post_name;
            return 'https://qa.example/' . $post->post_name . '/';
        }}
        $cls = \\AChWorks\\AaPanelBridge\\CacheInvalidation::class;
        $new = (object)['ID'=>7,'post_type'=>'post',
            'post_status'=>'publish','post_name'=>'new'];
        $old = (object)['ID'=>7,'post_type'=>'post',
            'post_status'=>'publish','post_name'=>'old'];
        $cls::afterPostSaved(7, $new, true, $old);
        $first = $GLOBALS['slugs'];
        $GLOBALS['slugs'] = [];
        $draft = (object)['ID'=>7,'post_type'=>'post',
            'post_status'=>'draft','post_name'=>'new'];
        $cls::afterPostSaved(7, $draft, true, $old);
        $second = $GLOBALS['slugs'];
        $GLOBALS['slugs'] = [];
        $cls::afterPostSaved(8, $new, true, $old);
        $cls::afterPostSaved(7, $draft, true, null);
        echo json_encode([$first, $second, $GLOBALS['slugs']],
            JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         [["new", "old"], ["new", "old"], []])

    def test_permanent_delete_captures_published_url_then_discards_pending(self):
        # A permanent delete has separate before_delete_post and
        # after_delete_post hooks. No vendor purge occurs until the latter.
        source = f"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return []; }}
        function home_url($path) {{ return 'https://qa.example/'; }}
        function get_permalink($post) {{
            return 'https://qa.example/' . $post->post_name . '/';
        }}
        $cls = \\AChWorks\\AaPanelBridge\\CacheInvalidation::class;
        $public = (object)['ID'=>41,'post_type'=>'post',
            'post_status'=>'publish','post_name'=>'deleted-slug'];
        $draft = (object)['ID'=>42,'post_type'=>'post',
            'post_status'=>'draft','post_name'=>'draft'];
        $wrong = (object)['ID'=>43,'post_type'=>'post',
            'post_status'=>'publish','post_name'=>'not-43'];
        $cls::capturePostDeletion(41, $public);
        $cls::capturePostDeletion(42, $draft);
        $cls::capturePostDeletion(44, $wrong);
        $property = new ReflectionProperty($cls, 'pendingDeleteUrls');
        $before = $property->getValue();
        // The public callback has no active Nginx Helper or manifest in this
        // fixture, but a successful delete still releases its pending state.
        $cls::afterPostDeleted(41, $public);
        $after = $property->getValue();
        echo json_encode([$before, $after], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        before, after = json.loads(result.stdout)
        self.assertEqual(before, {"41": [
            "https://qa.example/", "https://qa.example/deleted-slug/"]})
        self.assertEqual(after, [])
        source_code = (PLUGIN / 'includes/class-cache-invalidation.php').read_text()
        self.assertIn(
            "add_action('before_delete_post', [__CLASS__, 'capturePostDeletion'], 10, 2)",
            source_code)
        self.assertIn(
            "add_action('after_delete_post', [__CLASS__, 'afterPostDeleted'], 10, 2)",
            source_code)

    def test_public_term_archives_include_parent_and_exclude_private_taxonomies(self):
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        function get_object_taxonomies($type) {{
            return $type === 'post' ? ['category', 'post_tag', 'secret'] : [];
        }}
        function is_taxonomy_viewable($taxonomy) {{ return $taxonomy !== 'secret'; }}
        function is_taxonomy_hierarchical($taxonomy) {{ return $taxonomy === 'category'; }}
        function get_the_terms($post, $taxonomy) {{
            if ($taxonomy === 'category') {{
                return [(object)['term_id'=>12,'slug'=>'child'],
                        (object)['term_id'=>12,'slug'=>'child']];
            }}
            if ($taxonomy === 'post_tag') {{
                return [(object)['term_id'=>30,'slug'=>'topic']];
            }}
            throw new Exception('Private taxonomy must never be inspected');
        }}
        function get_ancestors($termId, $taxonomy, $type) {{
            return $taxonomy === 'category' && $termId === 12 ? [9] : [];
        }}
        function get_term($id, $taxonomy) {{
            return $id === 9 ? (object)['term_id'=>9,'slug'=>'parent'] : false;
        }}
        function is_wp_error($value) {{ return false; }}
        function get_term_link($term, $taxonomy) {{
            return 'https://qa.example/' . $taxonomy . '/' . $term->slug . '/';
        }}
        $ref = new ReflectionMethod(
            \AChWorks\AaPanelBridge\CacheInvalidation::class, 'postArchiveUrls');
        $post = (object)['ID'=>7,'post_type'=>'post','post_status'=>'publish'];
        echo json_encode($ref->invoke(null, $post), JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout), [
            'https://qa.example/category/child/',
            'https://qa.example/category/parent/',
            'https://qa.example/post_tag/topic/',
        ])

    def test_term_hooks_handle_append_noop_append_add_and_replacement(self):
        # Core wp_add_object_terms() delegates with append=true; its
        # old_tt_ids hook argument is always [], even for existing terms.
        # Only real pre-add events can start an assignment snapshot.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['relations'] = [10];
        $GLOBALS['category'] = 'old';
        $GLOBALS['home_calls'] = 0;
        $GLOBALS['archive_queries'] = [];
        $GLOBALS['post_urls'] = [];
        function wp_get_object_terms($id, $taxonomy, $args) {{
            if ($args['fields'] !== 'tt_ids') throw new Exception('Wrong fields');
            return $GLOBALS['relations'];
        }}
        function get_post($id) {{
            return $id === 7 ? (object)[
                'ID'=>7,'post_type'=>'post','post_status'=>'publish'] : null;
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
        function is_taxonomy_hierarchical($tax) {{ return false; }}
        function get_permalink($post) {{
            $url = 'https://qa.example/' . $GLOBALS['category'] . '/story/';
            $GLOBALS['post_urls'][] = $url;
            return $url;
        }}
        function home_url($path) {{
            $GLOBALS['home_calls']++;
            return 'https://qa.example/';
        }}
        function get_terms($args) {{
            $GLOBALS['archive_queries'][] = $args;
            return array_map(static fn($tt) => (object)[
                'term_id'=>$tt,'slug'=>'tt-' . $tt
            ], $args['term_taxonomy_id']);
        }}
        function get_term_link($term, $tax) {{
            return 'https://qa.example/category/' . $term->slug . '/';
        }}
        function is_wp_error($x) {{ return false; }}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $adds = new ReflectionProperty($cls, 'pendingTermPermalinks');
        $dels = new ReflectionProperty($cls, 'pendingTermRemovals');

        // wp_add_object_terms($post, [existingA]) -> append=true;
        // WordPress fires set_object_terms without add_term_relationship.
        $cls::afterPostTermsSet(7, [10], [10], 'category', true, []);
        $appendNoop = [$GLOBALS['home_calls'], $GLOBALS['archive_queries']];

        // Genuine append must fire pre-add, with an actual old relationship.
        $cls::captureTermPermalink(7, 11, 'category');
        $savedAppend = $adds->getValue();
        $GLOBALS['relations'] = [10, 11];
        $GLOBALS['category'] = 'appended';
        $cls::afterPostTermsSet(7, [11], [11], 'category', true, []);
        $afterAppend = [
            $GLOBALS['home_calls'], $GLOBALS['archive_queries'],
            $adds->getValue()
        ];

        // Identical append=false replacement has no pre-add/delete events.
        $cls::afterPostTermsSet(7, [10, 11], [10, 11],
            'category', false, [11, 10]);
        $unchangedReplace = $GLOBALS['home_calls'];

        // Real replacement: first add new, then delete obsolete term.
        $cls::captureTermPermalink(7, 12, 'category');
        $savedReplace = $adds->getValue();
        $GLOBALS['relations'] = [10, 11, 12];
        $cls::captureTermRemoval(7, [10], 'category');
        $GLOBALS['relations'] = [11, 12];
        $GLOBALS['category'] = 'replacement';
        $cls::afterTermRemoval(7, [10], 'category');
        $duringReplace = [
            $GLOBALS['home_calls'], $adds->getValue(), $dels->getValue()
        ];
        $cls::afterPostTermsSet(7, [11, 12], [11, 12],
            'category', false, [10, 11]);
        $afterReplace = [
            $GLOBALS['home_calls'], $GLOBALS['archive_queries'],
            $adds->getValue(), $dels->getValue()
        ];
        $cls::afterPostTermsSet(8, [12], [12], 'category', true, []);
        echo json_encode([
            $appendNoop, $savedAppend, $afterAppend, $unchangedReplace,
            $savedReplace, $duringReplace, $afterReplace
        ], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        (noop, saved_append, appended, unchanged,
         saved_replace, in_replace, replaced) = json.loads(result.stdout)
        self.assertEqual(noop, [0, []])
        self.assertEqual(saved_append, {'7': {'category': {
            'url': 'https://qa.example/old/story/', 'before': {'10': 10}
        }}})
        self.assertEqual(appended[0], 1)
        self.assertEqual(appended[1][0]['term_taxonomy_id'], [10, 11])
        self.assertEqual(appended[2], [])
        self.assertEqual(unchanged, 1)
        self.assertEqual(saved_replace, {'7': {'category': {
            'url': 'https://qa.example/appended/story/', 'before': {
                "10": 10, "11": 11
            }
        }}})  # JSON key shape normalized below
        self.assertEqual(in_replace[0], 1, "mid-replacement must not purge")
        self.assertEqual(in_replace[2], [], "delete state consumed")
        self.assertEqual(replaced[0], 2)
        self.assertEqual(replaced[1][1]['term_taxonomy_id'], [10, 11, 12])
        self.assertEqual(replaced[2:], [[], []])
        entry = (PLUGIN / 'includes/class-cache-invalidation.php').read_text()
        for hook, method, args in (
            ('add_term_relationship', 'captureTermPermalink', 3),
            ('set_object_terms', 'afterPostTermsSet', 6),
            ('delete_term_relationships', 'captureTermRemoval', 3),
            ('deleted_term_relationships', 'afterTermRemoval', 3),
        ):
            self.assertIn(
                f"add_action('{hook}', [__CLASS__, '{method}'], "
                f"{20 if hook.startswith('deleted') or hook == 'set_object_terms' else 10}, {args})",
                entry,
            )

    def test_standalone_term_removal_cannot_contaminate_later_assignment(self):
        # wp_remove_object_terms() fires delete_term_relationships and
        # deleted_term_relationships but never set_object_terms.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['relations'] = [20, 21];
        $GLOBALS['category'] = 'old';
        $GLOBALS['home_calls'] = 0;
        $GLOBALS['archive_ids'] = [];
        function get_post($id) {{
            return $id === 11 ? (object)[
                'ID'=>11,'post_type'=>'post','post_status'=>'publish'] : null;
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
        function is_taxonomy_hierarchical($tax) {{ return false; }}
        function wp_get_object_terms($id, $tax, $args) {{ return $GLOBALS['relations']; }}
        function get_permalink($post) {{
            return 'https://qa.example/' . $GLOBALS['category'] . '/story/';
        }}
        function home_url($path) {{
            $GLOBALS['home_calls']++;
            return 'https://qa.example/';
        }}
        function get_terms($args) {{
            $GLOBALS['archive_ids'][] = $args['term_taxonomy_id'];
            return array_map(static fn($tt) => (object)[
                'term_id'=>$tt,'slug'=>'tt-'.$tt
            ], $args['term_taxonomy_id']);
        }}
        function get_term_link($term, $tax) {{
            return 'https://qa.example/category/' . $term->slug . '/';
        }}
        function is_wp_error($v) {{ return false; }}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $addState = new ReflectionProperty($cls, 'pendingTermPermalinks');
        $delState = new ReflectionProperty($cls, 'pendingTermRemovals');

        // Standalone removal of term 20, NO set_object_terms.
        $cls::captureTermRemoval(11, [20], 'category');
        $saved = $delState->getValue();
        $GLOBALS['relations'] = [21];
        $GLOBALS['category'] = 'middle';
        $cls::afterTermRemoval(11, [20], 'category');
        $afterDirect = [
            $GLOBALS['home_calls'], $GLOBALS['archive_ids'],
            $addState->getValue(), $delState->getValue()
        ];

        // A later independent assignment in SAME request must capture
        // /middle/story/ (not stale /old/story/).
        $cls::captureTermPermalink(11, 22, 'category');
        $newSaved = $addState->getValue();
        $GLOBALS['relations'] = [21, 22];
        $GLOBALS['category'] = 'new';
        $cls::afterPostTermsSet(11, [22], [22], 'category', true, []);
        $afterNew = [
            $GLOBALS['home_calls'], $GLOBALS['archive_ids'],
            $addState->getValue()
        ];

        // Core emits delete hooks even when the requested association is
        // already absent; comparing actual relations avoids false purges.
        $cls::captureTermRemoval(11, [20], 'category');
        $cls::afterTermRemoval(11, [20], 'category');
        $absentRemoval = [$GLOBALS['home_calls'], $delState->getValue()];

        // Delete-only wp_set_object_terms([]) includes delete pair THEN set.
        $cls::captureTermRemoval(11, [21], 'category');
        $GLOBALS['relations'] = [22];
        $GLOBALS['category'] = 'after-delete';
        $cls::afterTermRemoval(11, [21], 'category');
        $cls::afterPostTermsSet(11, [], [], 'category', false, [21, 22]);
        $deleteOnly = [
            $GLOBALS['home_calls'], $GLOBALS['archive_ids'],
            $addState->getValue(), $delState->getValue()
        ];

        // An interrupted pre-delete has no post callback. The next
        // pre-delete must replace (not reuse) its unconsumed snapshot.
        $cls::captureTermRemoval(11, [22], 'category');
        $unmatched = $delState->getValue();
        $GLOBALS['category'] = 'other';
        $cls::captureTermRemoval(11, [99], 'category');
        $overwritten = $delState->getValue();
        $cls::afterTermRemoval(11, [99], 'category');
        $afterNoChange = [$GLOBALS['home_calls'], $delState->getValue()];

        echo json_encode([
            $saved, $afterDirect, $newSaved, $afterNew, $absentRemoval,
            $deleteOnly, $unmatched, $overwritten, $afterNoChange
        ], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        (saved, after_direct, new_saved, after_new, absent, delete_only,
         unmatched, overwritten, no_change) = json.loads(result.stdout)
        self.assertEqual(saved['11']['category']['url'],
                         'https://qa.example/old/story/')
        self.assertEqual(after_direct, [1, [[20, 21]], [], []])
        self.assertEqual(new_saved['11']['category']['url'],
                         'https://qa.example/middle/story/')
        self.assertEqual(after_new, [2, [[20, 21], [21, 22]], []])
        self.assertEqual(absent, [2, []])
        self.assertEqual(delete_only, [
            3, [[20, 21], [21, 22], [21, 22]], [], []
        ])
        self.assertEqual(unmatched['11']['category']['url'],
                         'https://qa.example/after-delete/story/')
        self.assertEqual(overwritten['11']['category']['url'],
                         'https://qa.example/other/story/')
        self.assertEqual(no_change, [3, []])

    def test_term_capture_excludes_nonpublic_and_unrelated_posts(self):
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        function get_post($id) {{
            return $id === 7 ? (object)[
                'ID'=>7,'post_type'=>'post','post_status'=>'draft'] : null;
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $cls::captureTermPermalink(7, 10, 'category');
        $cls::captureTermRemoval(7, [10], 'category');
        $cls::captureTermPermalink(8, 10, 'category');
        $cls::captureTermRemoval(8, [10], 'category');
        $cls::afterPostTermsSet(7, [10], [10], 'category', false, []);
        $cls::afterTermRemoval(7, [10], 'category');
        echo json_encode([
            (new ReflectionProperty($cls,'pendingTermPermalinks'))->getValue(),
            (new ReflectionProperty($cls,'pendingTermRemovals'))->getValue(),
        ], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout), [[], []])

    def test_post_save_and_deletion_capture_archive_urls(self):
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($taxonomy) {{ return true; }}
        function is_taxonomy_hierarchical($taxonomy) {{ return false; }}
        function get_the_terms($post, $taxonomy) {{
            return [(object)['term_id'=>17,'slug'=>'news']];
        }}
        function is_wp_error($value) {{ return false; }}
        function get_term_link($term, $taxonomy) {{
            return 'https://qa.example/category/' . $term->slug . '/';
        }}
        function home_url($path) {{ return 'https://qa.example/'; }}
        function get_permalink($post) {{
            return 'https://qa.example/' . $post->post_name . '/';
        }}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $post = (object)['ID'=>31,'post_type'=>'post',
            'post_status'=>'publish','post_name'=>'news-item'];
        $cls::capturePostDeletion(31, $post);
        $prop = new ReflectionProperty($cls, 'pendingDeleteUrls');
        $stored = $prop->getValue();
        $cls::afterPostDeleted(31, $post);
        $cleared = $prop->getValue();
        $ref = new ReflectionMethod($cls, 'postArchiveUrls');
        echo json_encode([$stored, $cleared, $ref->invoke(null, $post)],
            JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        stored, cleared, archive = json.loads(result.stdout)
        self.assertEqual(stored, {'31': [
            'https://qa.example/',
            'https://qa.example/news-item/',
            'https://qa.example/category/news/',
        ]})
        self.assertEqual(cleared, [])
        self.assertEqual(archive, ['https://qa.example/category/news/'])

    def test_shared_save_delete_dispatch_uses_only_verified_generation_files(self):
        # Execute the same private dispatch used by WordPress save/deletion.
        # The vendor-purger stub calls the real scoped file selector while
        # dispatch runs; it must select one exact method-specific file.
        from hashlib import md5

        with tempfile.TemporaryDirectory(prefix="ach-bridge-dispatch-") as work:
            base, peer = Path(work) / "site-9", Path(work) / "site-10"
            base.mkdir(mode=0o700)
            peer.mkdir(mode=0o700)
            generation, site_key = "a" * 32, "qa.example"

            def cache_object(scheme, path, *, method="GET", root=base,
                             gen=generation, key_override=None):
                key = scheme + method + site_key + path + "|" + gen
                digest = md5(key.encode("ascii")).hexdigest()
                folder = root / digest[-1] / digest[-3:-1]
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                folder.parent.chmod(0o700)
                folder.chmod(0o700)
                entry = folder / digest
                entry.write_bytes(b"NGINX-HEADER\nKEY: " +
                                  (key_override or key).encode("ascii") + b"\nbody")
                entry.chmod(0o600)
                return entry

            present = {}
            for scheme, method, path in [
                ("http", "GET", "/"), ("http", "HEAD", "/"),
                ("https", "GET", "/"), ("https", "HEAD", "/"),
                ("https", "GET", "/article/"), ("https", "HEAD", "/article/"),
                ("http", "GET", "/old/"), ("http", "HEAD", "/old/"),
                ("http", "GET", "/category/old/"),
                ("http", "HEAD", "/category/old/"),
                ("https", "GET", "/category/new/"),
                ("https", "HEAD", "/category/new/"),
            ]:
                present[(scheme, method, path)] = cache_object(
                    scheme, path, method=method)

            # Old-generation objects, the physical peer and a wrong KEY
            # must not enter the vendor. A valid same-site decoy checks that
            # temporary HEAD selection cannot affect a different vendor URL.
            bad = cache_object("https", "/old/", method="HEAD", key_override="wrong-key")
            stale = cache_object("http", "/article/", method="HEAD", gen="b" * 32)
            peer_file = cache_object("http", "/", method="HEAD", root=peer)
            decoy = cache_object("https", "/decoy/", method="HEAD")
            st = base.stat()
            manifest = {
                "site_id": 9, "site_key": site_key, "cache_directory": str(base),
                "cache_identity": [st.st_dev, st.st_ino],
                "cache_generation": generation,
            }
            urls = [
                "https://qa.example/", "https://qa.example/article/",
                "https://qa.example/article/", "http://qa.example/old/",
                "https://qa.example/old/",
                "https://qa.example/category/new/",
                "http://qa.example/category/old/",
                "https://another.example/",
                "https://qa.example/article/?private=1",
                "https://qa.example/%61rticle/",
                "https://qa.example/../old/", "http://qa.example:8080/",
            ]
            source = rf"""
            define('ABSPATH', '/fixture/');
            class FastCGI_Purger {{
                public array $calls = [];
                public function purge_url($url, $feed) {{
                    $selector = new ReflectionMethod(
                        \AChWorks\AaPanelBridge\CacheInvalidation::class,
                        'selectFileForManifest');
                    $selected = $selector->invoke(null, $GLOBALS['manifest'],
                        $url, '/nonexistent/denied');
                    $other = $selector->invoke(null, $GLOBALS['manifest'],
                        'https://qa.example/decoy/', '/nonexistent/denied');
                    $this->calls[] = [$url, $feed, $selected, $other];
                }}
            }}
            require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
            function wp_parse_url($url) {{ return parse_url($url); }}
            $manifest = json_decode({json.dumps(json.dumps(manifest))}, true);
            $urls = json_decode({json.dumps(json.dumps(urls))}, true);
            $purger = new FastCGI_Purger();
            $selector = static function (string $url, string $method) use ($manifest): string {{
                return \AChWorks\AaPanelBridge\CacheInvalidation::selectVerifiedFile(
                    $manifest, $url, '/nonexistent/denied', $method);
            }};
            $dispatch = new ReflectionMethod(
                \AChWorks\AaPanelBridge\CacheInvalidation::class, 'dispatchPublicUrls');
            $dispatch->invoke(null, $urls, $manifest, $purger, $selector);
            $scope = new ReflectionMethod(
                \AChWorks\AaPanelBridge\CacheInvalidation::class, 'selectFileForManifest');
            $ordinaryVendor = $scope->invoke(null, $manifest,
                'https://qa.example/decoy/', '/nonexistent/denied');
            echo json_encode([$purger->calls, $ordinaryVendor], JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls, ordinary = json.loads(result.stdout)
            expected = [
                [f"{scheme}://qa.example{path}", False,
                 str(present[(scheme, method, path)]), "/nonexistent/denied"]
                for scheme, method, path in [
                    ("http", "GET", "/"), ("http", "HEAD", "/"),
                    ("https", "GET", "/"), ("https", "HEAD", "/"),
                    ("https", "GET", "/article/"), ("https", "HEAD", "/article/"),
                    ("http", "GET", "/old/"), ("http", "HEAD", "/old/"),
                    ("https", "GET", "/category/new/"),
                    ("https", "HEAD", "/category/new/"),
                    ("http", "GET", "/category/old/"),
                    ("http", "HEAD", "/category/old/"),
                ]
            ]
            self.assertEqual(calls, expected)
            # With no active Bridge dispatch, vendor behavior stays GET.
            self.assertEqual(ordinary, "/nonexistent/denied")
            for file in [*present.values(), stale, bad, peer_file, decoy]:
                self.assertTrue(file.exists(), "Stub must not unlink fixtures")

    def test_category_permalink_old_and_new_use_existing_scoped_dispatch(self):
        # Both distinct canonical post paths MUST pass through the same exact
        # GET/HEAD, HTTP/HTTPS generation and site-isolation checks.
        from hashlib import md5

        with tempfile.TemporaryDirectory(prefix="ach-bridge-category-") as work:
            base, peer = Path(work) / "site-9", Path(work) / "site-17"
            base.mkdir(mode=0o700)
            peer.mkdir(mode=0o700)
            site_key, generation = "qa.example", "a" * 32

            def cache_object(scheme, method, path, *, directory=base,
                             gen=generation, header_key=None):
                key = f"{scheme}{method}{site_key}{path}|{gen}"
                digest = md5(key.encode()).hexdigest()
                folder = directory / digest[-1] / digest[-3:-1]
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                folder.parent.chmod(0o700)
                folder.chmod(0o700)
                item = folder / digest
                item.write_bytes(b"NGINX\nKEY: " +
                                 (header_key or key).encode() + b"\nbody")
                item.chmod(0o600)
                return item

            objects = {}
            for path in ("/old/story/", "/new/story/"):
                for scheme in ("http", "https"):
                    for method in ("GET", "HEAD"):
                        objects[(scheme, method, path)] = cache_object(
                            scheme, method, path)

            wrong_gen = cache_object("http", "HEAD", "/old/story/",
                                     gen="b" * 32)
            wrong_key = cache_object("https", "GET", "/decoy/",
                                     header_key="not-the-real-cache-key")
            peer_object = cache_object("https", "HEAD", "/old/story/",
                                       directory=peer)
            st = base.stat()
            manifest = {"site_key": site_key, "cache_directory": str(base),
                        "cache_identity": [st.st_dev, st.st_ino],
                        "cache_generation": generation}
            source = rf"""
            define('ABSPATH', '/fixture/');
            class FastCGI_Purger {{
                public array $calls = [];
                public function purge_url($url, $feed) {{
                    $map = new ReflectionMethod(
                        \AChWorks\AaPanelBridge\CacheInvalidation::class,
                        'selectFileForManifest');
                    $selected = $map->invoke(null, $GLOBALS['manifest'],
                        $url, '/denied');
                    $this->calls[] = [$url, $feed, $selected];
                }}
            }}
            require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
            function wp_parse_url($url) {{ return parse_url($url); }}
            function home_url($path) {{ return 'https://qa.example/'; }}
            function get_permalink($post) {{ return 'https://qa.example/new/story/'; }}
            function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
            $manifest = json_decode({json.dumps(json.dumps(manifest))}, true);
            $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
            $urlsMethod = new ReflectionMethod($cls, 'changedTermUrls');
            $urls = $urlsMethod->invoke(null,
                (object)['ID'=>11], 'category', [],
                'https://qa.example/old/story/');
            $purger = new FastCGI_Purger();
            $selector = static fn($url, $method): string =>
                $cls::selectVerifiedFile($manifest, $url, '/denied', $method);
            $dispatch = new ReflectionMethod($cls, 'dispatchPublicUrls');
            $dispatch->invoke(null, $urls, $manifest, $purger, $selector);
            echo json_encode([$urls, $purger->calls], JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            urls, calls = json.loads(result.stdout)
            self.assertEqual(urls, [
                "https://qa.example/",
                "https://qa.example/old/story/",
                "https://qa.example/new/story/",
            ])
            expected = [
                [f"{scheme}://{site_key}{path}", False,
                 str(objects[(scheme, method, path)])]
                for path in ("/old/story/", "/new/story/")
                for scheme in ("http", "https")
                for method in ("GET", "HEAD")
            ]
            self.assertEqual(calls, expected)
            for item in [*objects.values(), wrong_gen, wrong_key, peer_object]:
                self.assertTrue(item.is_file())

    def test_head_mapping_has_distinct_key_and_rejects_invalid_method(self):
        from hashlib import md5

        with tempfile.TemporaryDirectory(prefix="ach-bridge-head-") as work:
            root = Path(work) / "site-9"
            root.mkdir(mode=0o700)
            st = root.stat()
            manifest = {
                "site_key": "qa.example", "cache_directory": str(root),
                "cache_identity": [st.st_dev, st.st_ino],
                "cache_generation": "f" * 32,
            }
            paths = {}
            for method in ("GET", "HEAD"):
                key = f"https{method}qa.example/article/|{'f' * 32}"
                hash_ = md5(key.encode()).hexdigest()
                folder = root / hash_[-1] / hash_[-3:-1]
                folder.mkdir(parents=True, mode=0o700)
                folder.parent.chmod(0o700)
                file = folder / hash_
                file.write_bytes(b"NGINX-HEADER\nKEY: " + key.encode() + b"\nbody")
                file.chmod(0o600)
                paths[method] = str(file)
            source = rf"""
            define('ABSPATH', '/fixture/');
            require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
            function wp_parse_url($url) {{ return parse_url($url); }}
            $m = json_decode({json.dumps(json.dumps(manifest))}, true);
            $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
            $u = 'https://qa.example/article/';
            echo json_encode([
                $cls::selectVerifiedFile($m, $u, '/denied'),
                $cls::selectVerifiedFile($m, $u, '/denied', 'HEAD'),
                $cls::selectVerifiedFile($m, $u, '/denied', 'POST'),
                $cls::selectVerifiedFile($m, $u, '/denied', 'head'),
                $cls::selectVerifiedFile($m, $u.'?q=1', '/denied', 'HEAD'),
                $cls::selectVerifiedFile($m, 'https://other.example/article/', '/denied', 'HEAD')
            ], JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [
                paths["GET"], paths["HEAD"], "/denied", "/denied",
                "/denied", "/denied",
            ])

    def test_dispatch_restores_vendor_context_on_exception(self):
        with tempfile.TemporaryDirectory(prefix="ach-bridge-unwind-") as work:
            root = Path(work) / "site-9"
            root.mkdir(mode=0o700)
            entry = root / "head-test"
            entry.write_bytes(b"fixture")
            source = rf"""
            define('ABSPATH', '/fixture/');
            class FastCGI_Purger {{
                public function purge_url($url, $feed) {{
                    throw new RuntimeException('vendor failure');
                }}
            }}
            require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
            function wp_parse_url($url) {{ return parse_url($url); }}
            $m = ['site_key'=>'qa.example', 'cache_directory'=>{json.dumps(str(root))}];
            $selector = static fn($url, $method): string =>
                $method === 'HEAD' ? {json.dumps(str(entry))} : '';
            $dispatch = new ReflectionMethod(
                \AChWorks\AaPanelBridge\CacheInvalidation::class, 'dispatchPublicUrls');
            $caught = false;
            try {{
                $dispatch->invoke(null, ['https://qa.example/article/'],
                    $m, new FastCGI_Purger(), $selector);
            }} catch (RuntimeException $e) {{
                $caught = $e->getMessage() === 'vendor failure';
            }}
            $state = new ReflectionProperty(
                \AChWorks\AaPanelBridge\CacheInvalidation::class, 'activeUrlPurge');
            echo json_encode([$caught, $state->getValue()], JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [True, None])

    def test_missing_helper_stays_unverified_without_settings(self):
        source = f"""
        define('ABSPATH', '/test/');
        define('WP_PLUGIN_DIR', '/not-an-installed-helper-directory');
        require {json.dumps(str(PLUGIN / 'includes/class-nginx-helper-status.php'))};
        echo json_encode(\\AChWorks\\AaPanelBridge\\NginxHelperStatus::inspect(), JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info["activation"], "not_installed")
        self.assertIsNone(info["purge_method"])
        self.assertIsNone(info["effective_cache_path"])
        self.assertIsNone(info["automatic_purge_enabled"])


class WordPressBridgePackagingTests(unittest.TestCase):
    def test_header_slug_version_and_external_update_uri(self):
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertIn("Plugin Name: ACh aaPanel Bridge", entry)
        self.assertIn("Version: 0.1.8", entry)
        self.assertIn("Text Domain: ach-aapanel-bridge", entry)
        self.assertIn("Update URI: https://github.com/AChWorks/", entry)
        self.assertNotIn("Requires Plugins:", entry)
        self.assertNotIn("register_activation_hook", entry)

    def test_deterministic_standalone_zip(self):
        from scripts.build_wordpress_bridge import build

        with tempfile.TemporaryDirectory(prefix="ach-bridge-archive-") as work:
            a, b = Path(work) / "one.zip", Path(work) / "two.zip"
            first, second = build(a), build(b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(first["version"], "0.1.8")
            with ZipFile(a) as package:
                names = package.namelist()
                self.assertEqual(len(names), 5)
                self.assertTrue(all(p.startswith("ach-aapanel-bridge/") for p in names))
                self.assertIn("ach-aapanel-bridge/ach-aapanel-bridge.php", names)
                self.assertFalse(any("/.." in p or "__pycache__" in p for p in names))


if __name__ == "__main__":
    unittest.main()
