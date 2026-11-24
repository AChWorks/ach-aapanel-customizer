"""Independent WordPress companion: source-only PHP stubs and deterministic ZIP."""
import gettext
import json
import re
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

    def test_boot_registers_only_locale_loader_and_admin_menu_when_disconnected(self):
        source = f"""
        define('ABSPATH', '/not-a-wordpress-install/');
        $actions = [];
        function add_action($name, $handler) {{ global $actions; $actions[$name] = $handler; }}
        require {json.dumps(str(ENTRY))};
        echo json_encode(array_keys($actions), JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["init", "admin_menu"])

    def test_bundled_text_domain_registered_at_init(self):
        source = f"""
        define('ABSPATH', '/test/');
        $actions = [];
        $loaded = [];
        function add_action($name, $handler) {{ global $actions; $actions[$name] = $handler; }}
        function plugin_basename($file) {{ return 'ach-aapanel-bridge/ach-aapanel-bridge.php'; }}
        function load_plugin_textdomain($domain, $unused, $path) {{
            $GLOBALS['loaded'][] = [$domain, $unused, $path];
        }}
        require {json.dumps(str(ENTRY))};
        $before = $loaded;
        $actions['init']();
        echo json_encode([$before, $loaded], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            [], [["ach-aapanel-bridge", False, "ach-aapanel-bridge/languages"]]
        ])

    def test_admin_locale_rendering_preserves_brand_and_technical_values(self):
        with (PLUGIN / "languages/ach-aapanel-bridge-fa_IR.mo").open("rb") as mo:
            fa = gettext.GNUTranslations(mo)
        translations = {k: v for k, v in fa._catalog.items() if k}
        # An external catalog cannot replace the literal page/menu brand.
        translations["ACh aaPanel Bridge"] = "DO NOT DISPLAY"
        for locale in ("en_US", "fa_IR", "untranslated"):
            with self.subTest(locale=locale):
                table = translations if locale == "fa_IR" else {}
                source = f"""
                define('ABSPATH', '/test/');
                define('RT_WP_NGINX_HELPER_CACHE_PATH', '/www/cache/<path>');
                $GLOBALS['translations'] = json_decode(
                    {json.dumps(json.dumps(table, ensure_ascii=False))}, true);
                function add_action($name, $handler) {{}}
                function current_user_can($capability) {{ return true; }}
                function __($str, $domain) {{
                    if ($domain !== 'ach-aapanel-bridge') throw new Exception('unexpected domain');
                    return $GLOBALS['translations'][$str] ?? $str;
                }}
                function esc_html($value) {{
                    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
                }}
                function esc_html__($str, $domain) {{ return esc_html(__($str, $domain)); }}
                function add_management_page($title,$menu,$cap,$slug,$cb) {{
                    $GLOBALS['menu'] = [$title,$menu,$cap,$slug];
                }}
                $GLOBALS['nginx_helper_admin'] = (object)['options'=>[
                    'purge_method'=>'unlink_files', 'enable_purge'=>1
                ]];
                require {json.dumps(str(ENTRY))};
                \\AChWorks\\AaPanelBridge\\Plugin::registerAdminPage();
                ob_start();
                \\AChWorks\\AaPanelBridge\\Plugin::renderAdminPage();
                $html=ob_get_clean();
                echo json_encode([$GLOBALS['menu'],$html], JSON_THROW_ON_ERROR);
                """
                result = php_run(source)
                self.assertEqual(result.returncode, 0, result.stderr)
                menu, html = json.loads(result.stdout)
                self.assertEqual(menu, ["ACh aaPanel Bridge", "ACh aaPanel Bridge",
                                        "manage_options", "ach-aapanel-bridge"])
                self.assertIn("<h1><bdi>ACh aaPanel Bridge</bdi></h1>", html)
                self.assertNotIn("DO NOT DISPLAY", html)
                self.assertEqual(html.count("<table "), 2)
                self.assertEqual(html.count("</table>"), 2)
                self.assertEqual(html.count("<tr>"), 8)
                self.assertIn('dir="ltr"', html)
                self.assertIn("unlink_files</code>", html)
                self.assertIn("/www/cache/&lt;path&gt;</code>", html)
                for key in ("Not connected", "No verified native-managed site manifest",
                            "Readiness", "Configured cache path", "Important:",
                            "Not verified / blocked", "Unavailable"):
                    self.assertIn(table.get(key, key), html)
                if locale == "fa_IR":
                    self.assertNotIn(">Not connected<", html)
                    self.assertNotIn("No verified native-managed site manifest", html)

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

    def test_toolbar_purge_requires_valid_frontend_nonce_user_and_method(self):
        source = f"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['authorized'] = true;
        $GLOBALS['nonce_valid'] = true;
        $GLOBALS['admin_request'] = false;
        function is_admin() {{ return $GLOBALS['admin_request']; }}
        function current_user_can($name) {{
            return $GLOBALS['authorized'] && $name === 'Nginx Helper | Purge cache';
        }}
        function wp_verify_nonce($nonce, $action) {{
            return $GLOBALS['nonce_valid'] && $nonce === 'verified-only'
                && $action === 'nginx_helper-purge_all';
        }}
        $url = 'https://qa.example/story/';
        $_SERVER['REQUEST_METHOD'] = 'GET';
        $_GET = ['nginx_helper_action'=>'purge',
                 'nginx_helper_urls'=>'current-url',
                 '_wpnonce'=>'verified-only'];
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $out = [];
        foreach (['GET','POST'] as $method) {{
            $_SERVER['REQUEST_METHOD'] = $method;
            $out[] = $cls::reconcileToolbarPurge($url);
        }}
        $_SERVER['REQUEST_METHOD'] = 'GET';
        $GLOBALS['authorized'] = false;
        $out[] = $cls::reconcileToolbarPurge($url);
        $GLOBALS['authorized'] = true;
        $GLOBALS['nonce_valid'] = false;
        $out[] = $cls::reconcileToolbarPurge($url);
        $GLOBALS['nonce_valid'] = true;
        $GLOBALS['admin_request'] = true;
        $out[] = $cls::reconcileToolbarPurge($url);
        $GLOBALS['admin_request'] = false;
        foreach ([
          ['nginx_helper_action'=>'purge','nginx_helper_urls'=>'all',
            '_wpnonce'=>'verified-only'],
          ['nginx_helper_action'=>'purge','nginx_helper_urls'=>'current-url'],
          ['nginx_helper_action'=>'purge','nginx_helper_urls'=>'current-url',
            '_wpnonce'=>['bad-array']],
        ] as $query) {{
          $_GET = $query;
          $out[] = $cls::reconcileToolbarPurge($url);
        }}
        echo json_encode($out, JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         ["https://qa.example/story/"] * 8)

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
        # A WordPress append no-op fires set_object_terms with old_tt_ids=[]
        # but does not insert a relationship. The Bridge does not subscribe
        # to this final action or mistake its old_tt_ids for a real delta.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['relations'] = [10];
        $GLOBALS['category'] = 'old';
        $GLOBALS['home_calls'] = 0;
        $GLOBALS['archive_queries'] = [];
        $GLOBALS['cache_events'] = [];
        function get_post($id) {{
            return $id === 7 ? (object)[
                'ID'=>7, 'post_type'=>'post', 'post_status'=>'publish'] : null;
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
        function is_taxonomy_hierarchical($tax) {{ return false; }}
        function wp_get_object_terms($id, $taxonomy, $args) {{
            if ($args['fields'] !== 'tt_ids') throw new Exception('Wrong fields');
            return $GLOBALS['relations'];
        }}
        function get_permalink($post) {{
            return 'https://qa.example/' . $GLOBALS['category'] . '/story/';
        }}
        function home_url($path) {{
            $GLOBALS['home_calls']++;
            return 'https://qa.example/';
        }}
        function wp_cache_delete($id, $group) {{
            $GLOBALS['cache_events'][] = ['object', $id, $group];
        }}
        function wp_cache_set_terms_last_changed() {{
            $GLOBALS['cache_events'][] = ['term-version'];
        }}
        function get_terms($args) {{
            $GLOBALS['archive_queries'][] = $args['term_taxonomy_id'];
            return array_map(static fn($tt) => (object)[
                'term_id'=>$tt, 'slug'=>'tt-' . $tt
            ], $args['term_taxonomy_id']);
        }}
        function get_term_link($term, $tax) {{
            return 'https://qa.example/category/' . $term->slug . '/';
        }}
        function is_wp_error($value) {{ return false; }}

        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $adds = new ReflectionProperty($cls, 'pendingTermAdds');
        $dels = new ReflectionProperty($cls, 'pendingTermRemovals');

        // WordPress append=true with an already assigned term: no pre/post add.
        $appendNoop = [$GLOBALS['home_calls'], $GLOBALS['cache_events']];

        // Genuine append: pre-insert -> commit -> post-insert.
        $cls::captureTermAddition(7, 11, 'category');
        $oldAppend = $adds->getValue()[7]['category'][0]['url'];
        $GLOBALS['relations'] = [10, 11];
        $GLOBALS['category'] = 'appended';
        $cls::afterTermAddition(7, 11, 'category');
        $appended = [$GLOBALS['home_calls'], $GLOBALS['archive_queries'],
            $adds->getValue(), $GLOBALS['cache_events']];

        // A no-op replacement has no add/delete relationship events.
        $unchanged = $GLOBALS['home_calls'];

        // Replacement: first real addition, then removal, each has its
        // own paired callback. The old and current URLs are recomputed.
        $cls::captureTermAddition(7, 12, 'category');
        $GLOBALS['relations'] = [10, 11, 12];
        $cls::afterTermAddition(7, 12, 'category');
        $duringReplace = $GLOBALS['home_calls'];
        $cls::captureTermRemoval(7, [10], 'category');
        $oldRemove = $dels->getValue()[7]['category'][0]['url'];
        $GLOBALS['relations'] = [11, 12];
        $GLOBALS['category'] = 'replacement';
        $cls::afterTermRemoval(7, [10], 'category');
        $replaced = [$GLOBALS['home_calls'], $GLOBALS['archive_queries'],
            $adds->getValue(), $dels->getValue(), $GLOBALS['cache_events']];

        echo json_encode([$appendNoop, $oldAppend, $appended, $unchanged,
            $duringReplace, $oldRemove, $replaced], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        (noop, original, appended, unchanged, during, old_remove,
         replaced) = json.loads(result.stdout)
        self.assertEqual(noop, [0, []])
        self.assertEqual(original, 'https://qa.example/old/story/')
        self.assertEqual(appended[0], 1)
        self.assertEqual(appended[1], [[10, 11]])
        self.assertEqual(appended[2], [])
        self.assertEqual(appended[3], [
            ['object', 7, 'category_relationships'], ['term-version']
        ])
        self.assertEqual(unchanged, 1)
        self.assertEqual(during, 2)
        self.assertEqual(old_remove, 'https://qa.example/appended/story/')
        self.assertEqual(replaced[0], 3)
        self.assertEqual(replaced[1], [[10, 11], [10, 11, 12], [10, 11, 12]])
        self.assertEqual(replaced[2:4], [[], []])
        self.assertEqual(replaced[4], [
            ['object', 7, 'category_relationships'], ['term-version'],
            ['object', 7, 'category_relationships'], ['term-version']
        ])
        entry = (PLUGIN / 'includes/class-cache-invalidation.php').read_text()
        for hook, method, priority, args in (
            ('add_term_relationship', 'captureTermAddition', 10, 3),
            ('added_term_relationship', 'afterTermAddition', 20, 3),
            ('delete_term_relationships', 'captureTermRemoval', 10, 3),
            ('deleted_term_relationships', 'afterTermRemoval', 20, 3),
        ):
            self.assertIn(
                f"add_action('{hook}', [__CLASS__, '{method}'], {priority}, {args})",
                entry,
            )
        self.assertNotIn("add_action('set_object_terms'", entry)

    def test_nested_relationship_pairs_keep_outer_snapshots_and_all_archives(self):
        # wp_set_object_terms and wp_remove_object_terms can reenter through
        # third-party callbacks on their pre-mutation actions. Both post-hooks
        # must reconcile their OWN pre-mutation frames in reverse call order.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['rels'] = [30];
        $GLOBALS['links'] = [];
        $GLOBALS['archives'] = [];
        $GLOBALS['purges'] = 0;
        function get_post($id) {{
            return $id === 7 ? (object)[
                'ID'=>7, 'post_type'=>'post','post_status'=>'publish'] : null;
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
        function is_taxonomy_hierarchical($tax) {{ return false; }}
        function wp_get_object_terms($id, $taxonomy, $args) {{
            return $GLOBALS['rels'];
        }}
        function get_permalink($post) {{
            $chosen = min($GLOBALS['rels']);
            $url = 'https://qa.example/' . $chosen . '/story/';
            $GLOBALS['links'][] = $url;
            return $url;
        }}
        function home_url($path) {{
            $GLOBALS['purges']++;
            return 'https://qa.example/';
        }}
        function get_terms($args) {{
            $ids = $args['term_taxonomy_id'];
            $GLOBALS['archives'][] = $ids;
            return array_map(static fn($tt) =>
                (object)['term_id'=>$tt,'slug'=>'tt-' . $tt], $ids);
        }}
        function get_term_link($term, $tax) {{
            return 'https://qa.example/category/' . $term->slug . '/';
        }}
        function is_wp_error($value) {{ return false; }}
        function wp_cache_delete($id, $group) {{}}
        function wp_cache_set_terms_last_changed() {{}}

        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $adds = new ReflectionProperty($cls, 'pendingTermAdds');
        $dels = new ReflectionProperty($cls, 'pendingTermRemovals');

        // Outer B pre-insert, then inner C pre-insert+commit+post, then
        // outer B commits. B becomes the canonical category (20 < 30).
        $cls::captureTermAddition(7, 20, 'category');
        $cls::captureTermAddition(7, 40, 'category');
        $GLOBALS['rels'] = [30, 40];
        $cls::afterTermAddition(7, 40, 'category');
        $GLOBALS['rels'] = [30, 40, 20];
        $cls::afterTermAddition(7, 20, 'category');
        $added = [$GLOBALS['purges'], $GLOBALS['archives'],
            $GLOBALS['links'], $adds->getValue(), $dels->getValue()];

        // Reset only observational counters, NOT pending Bridge state.
        $GLOBALS['rels'] = [10, 20, 30];
        $GLOBALS['links'] = [];
        $GLOBALS['archives'] = [];
        $GLOBALS['purges'] = 0;

        // Outer deletion removes 10, inner deletion removes 20, then
        // the original outer deletion commits. Final canonical category 30.
        $cls::captureTermRemoval(7, [10], 'category');
        $cls::captureTermRemoval(7, [20], 'category');
        $GLOBALS['rels'] = [10, 30];
        $cls::afterTermRemoval(7, [20], 'category');
        $GLOBALS['rels'] = [30];
        $cls::afterTermRemoval(7, [10], 'category');
        $removed = [$GLOBALS['purges'], $GLOBALS['archives'],
            $GLOBALS['links'], $adds->getValue(), $dels->getValue()];

        echo json_encode([$added, $removed], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        added, removed = json.loads(result.stdout)
        self.assertEqual(added[0], 2, "both nested/outer adds committed")
        self.assertEqual(added[1], [[30, 40], [30, 40, 20]],
                         "must include newly affected B archive")
        self.assertIn('https://qa.example/20/story/', added[2],
                      "outer post-insert must inspect new canonical permalink")
        self.assertEqual(added[3:], [[], []], "no leaked addition frame")
        self.assertEqual(removed[0], 2, "both deletions committed")
        self.assertEqual(removed[1], [[10, 20, 30], [10, 20, 30]],
                         "must include all affected nested old/new archives")
        self.assertIn('https://qa.example/30/story/', removed[2],
                      "outer post-delete must inspect final permalink")
        self.assertEqual(removed[3:], [[], []], "no leaked removal frame")

    def test_nested_ineligible_failed_sql_and_unrelated_keys_do_not_collide(self):
        # Same-key null frames (post temporarily nonpublic), SQL no-ops,
        # another post and a second taxonomy must not consume the outer
        # valid frame or dispatch unrelated URLs.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['sets'] = [
            '7:category'=>[30], '7:post_tag'=>[100],
            '8:category'=>[80]
        ];
        $GLOBALS['post7status'] = 'publish';
        $GLOBALS['home_calls'] = 0;
        $GLOBALS['post_urls'] = [];
        function get_post($id) {{
            if (!in_array($id,[7,8],true)) return null;
            return (object)[
                'ID'=>$id, 'post_type'=>'post',
                'post_status'=>$id===7
                    ? $GLOBALS['post7status'] : 'publish'
            ];
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category','post_tag']; }}
        function is_taxonomy_viewable($tax) {{
            return in_array($tax, ['category','post_tag'], true);
        }}
        function wp_get_object_terms($id,$tax,$args) {{
            return $GLOBALS['sets'][$id.':'.$tax] ?? [];
        }}
        function get_permalink($post) {{
            $ids = $GLOBALS['sets'][$post->ID.':category'] ?? [];
            $url = 'https://qa.example/' . $post->ID . '-' . min($ids) . '/story/';
            $GLOBALS['post_urls'][] = $url;
            return $url;
        }}
        function home_url($path) {{
            ++$GLOBALS['home_calls'];
            return 'https://qa.example/';
        }}
        function get_terms($args) {{ return []; }}
        function wp_cache_delete($id,$key) {{}}
        function wp_cache_set_terms_last_changed() {{}}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $adds = new ReflectionProperty($cls,'pendingTermAdds');
        $dels = new ReflectionProperty($cls,'pendingTermRemovals');

        // Outer valid post7/category pre-add frame.
        $cls::captureTermAddition(7, 20, 'category');

        // Temporarily nonpublic nested post7/category frame must still
        // balance its post-event, without consuming outer valid frame.
        $GLOBALS['post7status']='draft';
        $cls::captureTermAddition(7, 21, 'category');
        $cls::afterTermAddition(7, 21, 'category');
        $GLOBALS['post7status']='publish';
        $afterNull = $adds->getValue();

        // Unrelated post 8/category nested between outer pre/post.
        $cls::captureTermAddition(8, 81, 'category');
        $GLOBALS['sets']['8:category']=[80,81];
        $cls::afterTermAddition(8, 81, 'category');
        $afterPost8 = [$GLOBALS['home_calls'], $adds->getValue()];

        // Unrelated taxonomy on the original post.
        $cls::captureTermAddition(7, 101, 'post_tag');
        $GLOBALS['sets']['7:post_tag']=[100,101];
        $cls::afterTermAddition(7, 101, 'post_tag');
        $afterTag = [$GLOBALS['home_calls'], $adds->getValue()];

        // Now outer post7/category insertion finally commits.
        $GLOBALS['sets']['7:category']=[30,20];
        $cls::afterTermAddition(7, 20, 'category');
        $afterOuter = [$GLOBALS['home_calls'], $adds->getValue()];

        // A nested SQL INSERT can fail while core still emits its
        // post-insert hook. Its unchanged before/after is a no-op and
        // does not consume the enclosing successful pre-insert frame.
        $cls::captureTermAddition(7, 22, 'category');
        $cls::captureTermAddition(7, 23, 'category');
        $cls::afterTermAddition(7, 23, 'category');
        $afterFailedInner = [$GLOBALS['home_calls'], $adds->getValue()];
        $GLOBALS['sets']['7:category']=[30,20,22];
        $cls::afterTermAddition(7, 22, 'category');
        $afterSuccess = [
            $GLOBALS['home_calls'], $adds->getValue(), $dels->getValue()
        ];
        echo json_encode([
            $afterNull, $afterPost8, $afterTag, $afterOuter,
            $afterFailedInner, $afterSuccess, $GLOBALS['post_urls']
        ], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        (after_null, post8, tag, outer, failed_inner,
         success, urls) = json.loads(result.stdout)
        self.assertEqual(len(after_null['7']['category']), 1)
        self.assertEqual(post8[0], 1)
        self.assertEqual(len(post8[1]['7']['category']), 1)
        self.assertEqual(tag[0], 2)
        self.assertEqual(len(tag[1]['7']['category']), 1)
        self.assertEqual(outer, [3, []])
        self.assertEqual(failed_inner[0], 3)
        self.assertEqual(len(failed_inner[1]['7']['category']), 1)
        self.assertEqual(success, [4, [], []])
        self.assertIn('https://qa.example/7-20/story/', urls)
        self.assertIn('https://qa.example/8-80/story/', urls)

    def test_partial_success_wordpress_error_then_removal_and_noop_are_isolated(self):
        # Actual WordPress sequence: one successful INSERT fires pre/post add;
        # a subsequent wp_insert_term returns WP_Error and set_object_terms
        # never fires. Later operations must still purge independently.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['relations'] = [20];
        $GLOBALS['category'] = 'old';
        $GLOBALS['home_calls'] = 0;
        $GLOBALS['archives'] = [];
        function get_post($id) {{
            return $id === 11 ? (object)[
                'ID'=>11, 'post_type'=>'post', 'post_status'=>'publish'] : null;
        }}
        function is_post_type_viewable($type) {{ return $type === 'post'; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return $tax === 'category'; }}
        function is_taxonomy_hierarchical($tax) {{ return false; }}
        function wp_get_object_terms($id, $taxonomy, $args) {{
            return $GLOBALS['relations'];
        }}
        function get_permalink($post) {{
            return 'https://qa.example/' . $GLOBALS['category'] . '/story/';
        }}
        function home_url($path) {{
            $GLOBALS['home_calls']++;
            return 'https://qa.example/';
        }}
        function wp_cache_delete($id, $group) {{}}
        function wp_cache_set_terms_last_changed() {{}}
        function get_terms($args) {{
            $GLOBALS['archives'][] = $args['term_taxonomy_id'];
            return array_map(static fn($tt) => (object)[
                'term_id'=>$tt, 'slug'=>'tt-' . $tt
            ], $args['term_taxonomy_id']);
        }}
        function get_term_link($term, $tax) {{
            return 'https://qa.example/category/' . $term->slug . '/';
        }}
        function is_wp_error($value) {{ return false; }}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $adds = new ReflectionProperty($cls, 'pendingTermAdds');
        $dels = new ReflectionProperty($cls, 'pendingTermRemovals');

        // First of two requested adds commits; second fails with WP_Error
        // before WordPress's final set_object_terms event.
        $cls::captureTermAddition(11, 21, 'category');
        $GLOBALS['relations'] = [20, 21];
        $cls::afterTermAddition(11, 21, 'category');
        $afterError = [$GLOBALS['home_calls'], $GLOBALS['archives'],
            $adds->getValue(), $dels->getValue()];

        // Separate standalone removal A. Must not be suppressed by the
        // first, now failed, enclosing assignment.
        $cls::captureTermRemoval(11, [20], 'category');
        $GLOBALS['relations'] = [21];
        $GLOBALS['category'] = 'middle';
        $cls::afterTermRemoval(11, [20], 'category');
        $afterRemoval = [$GLOBALS['home_calls'], $GLOBALS['archives'],
            $adds->getValue(), $dels->getValue()];

        // wp_add_object_terms(B): B already exists; core fires only
        // set_object_terms, not pre/post add. Bridge must stay idle.
        $appendNoop = [$GLOBALS['home_calls'], $GLOBALS['archives']];

        // Subsequent unrelated append C in SAME PHP request must capture
        // actual /middle/story/ rather than old /old/story/.
        $cls::captureTermAddition(11, 22, 'category');
        $newUrl = $adds->getValue()[11]['category'][0]['url'];
        $GLOBALS['relations'] = [21, 22];
        $GLOBALS['category'] = 'new';
        $cls::afterTermAddition(11, 22, 'category');
        $afterNext = [$GLOBALS['home_calls'], $GLOBALS['archives'],
            $adds->getValue(), $dels->getValue()];

        // An absent relationship can emit the delete pair even when
        // WordPress's DELETE affected no row.
        $cls::captureTermRemoval(11, [20], 'category');
        $cls::afterTermRemoval(11, [20], 'category');
        $absent = [$GLOBALS['home_calls'], $adds->getValue(), $dels->getValue()];

        // Deletion-only wp_set_object_terms([]) does not require a
        // successful final set event either.
        $cls::captureTermRemoval(11, [21], 'category');
        $GLOBALS['relations'] = [22];
        $GLOBALS['category'] = 'after-delete';
        $cls::afterTermRemoval(11, [21], 'category');
        $afterDeleteOnly = [$GLOBALS['home_calls'], $adds->getValue(),
            $dels->getValue()];

        // Same-object nested removals preserve each independent snapshot.
        // Neither simulated SQL DELETE changes the current relationships.
        $cls::captureTermRemoval(11, [22], 'category');
        $GLOBALS['category'] = 'independent';
        $cls::captureTermRemoval(11, [99], 'category');
        $newDelUrl = $dels->getValue()[11]['category'][1]['url'];
        $cls::afterTermRemoval(11, [99], 'category');
        $cls::afterTermRemoval(11, [22], 'category');
        $last = [$GLOBALS['home_calls'], $adds->getValue(), $dels->getValue()];

        echo json_encode([$afterError, $afterRemoval, $appendNoop, $newUrl,
            $afterNext, $absent, $afterDeleteOnly, $newDelUrl, $last],
            JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        (failed, removed, noop, url, subsequent, absent, delete_only,
         next_delete_url, last) = json.loads(result.stdout)
        self.assertEqual(failed, [1, [[20, 21]], [], []])
        self.assertEqual(removed, [2, [[20, 21], [20, 21]], [], []])
        self.assertEqual(noop, [2, [[20, 21], [20, 21]]])
        self.assertEqual(url, 'https://qa.example/middle/story/')
        self.assertEqual(subsequent, [
            3, [[20, 21], [20, 21], [21, 22]], [], []
        ])
        self.assertEqual(absent, [3, [], []])
        self.assertEqual(delete_only, [4, [], []])
        self.assertEqual(next_delete_url,
                         'https://qa.example/independent/story/')
        self.assertEqual(last, [4, [], []])

    def test_post_add_without_persisted_relation_cannot_purge(self):
        # WordPress fires added_term_relationship after an attempted insert,
        # even if $wpdb->insert fails. Compare actual persisted relations.
        source = rf"""
        define('ABSPATH', '/fixture/');
        require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
        $GLOBALS['relations'] = [8];
        $GLOBALS['home_calls'] = 0;
        function get_post($id) {{
            return (object)['ID'=>8, 'post_type'=>'post', 'post_status'=>'publish'];
        }}
        function is_post_type_viewable($type) {{ return true; }}
        function get_object_taxonomies($type) {{ return ['category']; }}
        function is_taxonomy_viewable($tax) {{ return true; }}
        function wp_get_object_terms($id, $tax, $args) {{
            return $GLOBALS['relations'];
        }}
        function get_permalink($post) {{ return 'https://qa.example/story/'; }}
        function home_url($path) {{ $GLOBALS['home_calls']++; return 'https://qa.example/'; }}
        function wp_cache_delete($id, $group) {{}}
        function wp_cache_set_terms_last_changed() {{}}
        $cls = \AChWorks\AaPanelBridge\CacheInvalidation::class;
        $cls::captureTermAddition(8, 9, 'category');
        // Simulate failed SQL insertion, no database delta.
        $cls::afterTermAddition(8, 9, 'category');
        $state = (new ReflectionProperty($cls,'pendingTermAdds'))->getValue();
        echo json_encode([$GLOBALS['home_calls'], $state], JSON_THROW_ON_ERROR);
        """
        result = php_run(source)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout), [0, []])

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
        $cls::captureTermAddition(7, 10, 'category');
        $cls::captureTermRemoval(7, [10], 'category');
        $cls::captureTermAddition(8, 10, 'category');
        $cls::captureTermRemoval(8, [10], 'category');
        $cls::afterTermAddition(7, 10, 'category');
        $cls::afterTermRemoval(7, [10], 'category');
        $cls::afterTermAddition(8, 10, 'category');
        $cls::afterTermRemoval(8, [10], 'category');
        echo json_encode([
            (new ReflectionProperty($cls,'pendingTermAdds'))->getValue(),
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
        import re
        self.assertRegex(entry, r"(?m)^ \* Version: (?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}$")
        self.assertIn("Text Domain: ach-aapanel-bridge", entry)
        self.assertIn("Domain Path: /languages", entry)
        self.assertIn("Update URI: https://github.com/AChWorks/", entry)
        self.assertNotIn("Requires Plugins:", entry)
        self.assertNotIn("register_activation_hook", entry)

    def test_standard_wordpress_readme_matches_plugin_version(self):
        import re
        readme = (PLUGIN / "readme.txt").read_text(encoding="utf-8")
        entry = ENTRY.read_text(encoding="utf-8")
        version = re.search(r"(?m)^ \* Version: ([0-9]+(?:\.[0-9]+){2})$", entry)
        self.assertIsNotNone(version)
        self.assertTrue(readme.startswith("=== ACh aaPanel Bridge ===\n"))
        self.assertIn(f"Stable tag: {version.group(1)}", readme)
        self.assertRegex(readme, r"(?m)^Tested up to: [0-9]+\.[0-9]+(?:\.[0-9]+)?$")
        self.assertLessEqual(len(readme.splitlines()[5]), 150)
        for section in ("Description", "Installation", "Frequently Asked Questions", "Changelog"):
            with self.subTest(section=section):
                self.assertIn(f"== {section} ==", readme)
        self.assertIn("Nginx Helper", readme)
        self.assertIn("Purge All", readme)
        self.assertIn("Not connected", readme)
        self.assertIn("Cache Restore", readme)
        self.assertIn("License: MPL-2.0", readme)
        self.assertIn("License URI: https://www.mozilla.org/en-US/MPL/2.0/", readme)
        self.assertIn(" * License: MPL-2.0", entry)

    def test_invalid_or_duplicate_readme_tag_rejected_before_packaging(self):
        import re
        from unittest.mock import patch
        from scripts import build_wordpress_bridge as builder

        with tempfile.TemporaryDirectory(prefix="ach-bridge-readme-") as work:
            source = Path(work) / "plugin"
            shutil.copytree(PLUGIN, source)
            readme_file = source / "readme.txt"
            original = readme_file.read_text(encoding="utf-8")
            stable = re.search(r"(?m)^Stable tag: ([0-9.]+)$", original)
            self.assertIsNotNone(stable)
            correct = f"Stable tag: {stable.group(1)}"
            candidates = {
                "mismatch": original.replace(correct, "Stable tag: 0.0.0", 1),
                "duplicate": original.replace(correct, f"{correct}\n{correct}", 1),
            }
            for label, content in candidates.items():
                with self.subTest(label=label):
                    readme_file.write_text(content, encoding="utf-8")
                    destination = Path(work) / f"{label}.zip"
                    with patch.object(builder, "PLUGIN", source):
                        with self.assertRaisesRegex(ValueError, "Stable tag"):
                            builder.build(destination)
                    self.assertFalse(destination.exists())

    def test_builder_refuses_overwriting_a_source_member(self):
        from unittest.mock import patch
        from scripts import build_wordpress_bridge as builder

        with tempfile.TemporaryDirectory(prefix="ach-bridge-source-") as work:
            source = Path(work) / "plugin"
            shutil.copytree(PLUGIN, source)
            original = (source / "readme.txt").read_bytes()
            with patch.object(builder, "PLUGIN", source):
                with self.assertRaisesRegex(ValueError, "must not overwrite"):
                    builder.build(source / "readme.txt")
            self.assertEqual((source / "readme.txt").read_bytes(), original)

    def test_builder_missing_member_does_not_leave_partial_zip(self):
        from unittest.mock import patch
        from scripts import build_wordpress_bridge as builder

        with tempfile.TemporaryDirectory(prefix="ach-bridge-missing-") as work:
            source = Path(work) / "plugin"
            shutil.copytree(PLUGIN, source)
            (source / "includes/class-plugin.php").unlink()
            output = Path(work) / "candidate.zip"
            with patch.object(builder, "PLUGIN", source):
                with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
                    builder.build(output)
            self.assertFalse(output.exists())

    def test_missing_repo_license_refuses_unlicensed_bridge_zip(self):
        from unittest.mock import patch
        from scripts import build_wordpress_bridge as builder

        with tempfile.TemporaryDirectory(prefix="ach-bridge-license-") as work:
            destination = Path(work) / "candidate.zip"
            with patch.object(builder, "ROOT", Path(work)):
                with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
                    builder.build(destination)
            self.assertFalse(destination.exists())

    def test_persian_catalog_matches_all_literal_messages_and_plugin_description(self):
        messages = set()
        for source in PLUGIN.rglob("*.php"):
            messages.update(re.findall(
                r"(?:esc_html__|__)\(\s*'([^']*)'\s*,\s*'ach-aapanel-bridge'\s*\)",
                source.read_text(encoding="utf-8")))
        description = re.search(r"(?m)^ \* Description: (.+)$",
                                ENTRY.read_text(encoding="utf-8"))
        self.assertIsNotNone(description)
        messages.add(description.group(1))
        self.assertNotIn("ACh aaPanel Bridge", messages)

        # All current messages are singular/context-free. Support normal
        # gettext continuation lines as produced by standard PO editors.
        def read_catalog(path):
            entries = {}
            current = {}
            field = None
            def flush():
                if "msgid" in current:
                    key = current["msgid"]
                    self.assertNotIn(key, entries)
                    entries[key] = current.get("msgstr", "")
                current.clear()
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    flush()
                    field = None
                elif line.startswith("#"):
                    self.assertFalse(line.startswith("#, fuzzy"), line)
                elif line.startswith("msgid ") or line.startswith("msgstr "):
                    name, value = line.split(" ", 1)
                    if name == "msgid" and "msgid" in current:
                        flush()
                    field = name
                    current[field] = json.loads(value)
                elif line.startswith('"'):
                    self.assertIsNotNone(field, line)
                    current[field] += json.loads(line)
                else:
                    self.fail("Unexpected non-singular catalog entry: " + line)
            flush()
            entries.pop("", None)
            return entries

        languages = PLUGIN / "languages"
        template = read_catalog(languages / "ach-aapanel-bridge.pot")
        po = read_catalog(languages / "ach-aapanel-bridge-fa_IR.po")
        with (languages / "ach-aapanel-bridge-fa_IR.mo").open("rb") as file:
            mo = gettext.GNUTranslations(file)
        self.assertEqual(set(template), messages)
        self.assertTrue(all(not value for value in template.values()))
        self.assertEqual(set(po), messages)
        self.assertEqual({key: value for key, value in mo._catalog.items() if key}, po)
        self.assertEqual(mo.info()["language"], "fa_IR")
        for key, translated in po.items():
            self.assertTrue(re.search(r"[\u0600-\u06ff]", translated), key)
            self.assertNotEqual(key, translated)
        self.assertEqual(mo.gettext("ACh aaPanel Bridge"), "ACh aaPanel Bridge")
        self.assertEqual(mo.gettext("unlink_files"), "unlink_files")

    def test_deterministic_standalone_zip(self):
        from scripts.build_wordpress_bridge import build

        with tempfile.TemporaryDirectory(prefix="ach-bridge-archive-") as work:
            a, b = Path(work) / "one.zip", Path(work) / "two.zip"
            first, second = build(a), build(b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(first["sha256"], second["sha256"])
            import re
            source_version = re.search(r"(?m)^ \* Version: ([0-9.]+)$", ENTRY.read_text())
            self.assertIsNotNone(source_version)
            self.assertEqual(first["version"], source_version.group(1))
            with ZipFile(a) as package:
                names = package.namelist()
                self.assertEqual(len(names), 9)
                self.assertTrue(all(p.startswith("ach-aapanel-bridge/") for p in names))
                self.assertIn("ach-aapanel-bridge/ach-aapanel-bridge.php", names)
                self.assertIn("ach-aapanel-bridge/readme.txt", names)
                self.assertIn("ach-aapanel-bridge/LICENSE", names)
                for name in ("ach-aapanel-bridge.pot", "ach-aapanel-bridge-fa_IR.po",
                             "ach-aapanel-bridge-fa_IR.mo"):
                    member = "languages/" + name
                    self.assertEqual(package.read("ach-aapanel-bridge/" + member),
                                     (PLUGIN / member).read_bytes())
                self.assertEqual(package.read("ach-aapanel-bridge/LICENSE"),
                                 (ROOT / "LICENSE").read_bytes())
                self.assertNotIn("ach-aapanel-bridge/README.md", names)
                self.assertEqual(
                    package.read("ach-aapanel-bridge/readme.txt"),
                    (PLUGIN / "readme.txt").read_bytes(),
                )
                self.assertFalse(any("/.." in p or "__pycache__" in p for p in names))


if __name__ == "__main__":
    unittest.main()
