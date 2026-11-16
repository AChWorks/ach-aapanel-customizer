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

    def test_shared_save_delete_dispatch_uses_only_verified_generation_files(self):
        # Execute the same private dispatch used by live WordPress hooks with
        # an Nginx-shaped on-disk fixture and a faithful vendor-purger stub.
        from hashlib import md5

        with tempfile.TemporaryDirectory(prefix="ach-bridge-dispatch-") as work:
            base = Path(work) / "site-9"
            peer = Path(work) / "site-10"
            base.mkdir(mode=0o700)
            peer.mkdir(mode=0o700)
            generation = "a" * 32
            site_key = "qa.example"
            stored = []

            def cache_object(scheme, path, *, key_override=None, gen=generation,
                             root=base):
                key = scheme + "GET" + site_key + path + "|" + gen
                digest = md5(key.encode("ascii")).hexdigest()
                folder = root / digest[-1] / digest[-3:-1]
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                folder.parent.chmod(0o700)
                folder.chmod(0o700)
                entry = folder / digest
                entry.write_bytes(
                    b"NGINX-HEADER\nKEY: " +
                    (key_override or key).encode("ascii") + b"\nbody"
                )
                entry.chmod(0o600)
                return entry

            for scheme, path in [
                ("http", "/"), ("https", "/"), ("https", "/article/"),
                ("http", "/old/"),
            ]:
                stored.append(cache_object(scheme, path))
            # A matching hash without an exact saved KEY must not purge.
            bad = cache_object("https", "/old/", key_override="wrong-key")
            stale = cache_object("http", "/article/", gen="b" * 32)
            peer_file = cache_object("http", "/", root=peer)
            info = base.stat()
            manifest = {
                "site_id": 9,
                "site_key": site_key,
                "cache_directory": str(base),
                "cache_identity": [info.st_dev, info.st_ino],
                "cache_generation": generation,
            }
            urls = [
                "https://qa.example/", "https://qa.example/article/",
                "https://qa.example/article/", "http://qa.example/old/",
                "https://qa.example/old/", "https://another.example/",
                "https://qa.example/article/?private=1",
                "https://qa.example/%61rticle/",
                "https://qa.example/../old/", "http://qa.example:8080/",
            ]
            source = f"""
            define('ABSPATH', '/fixture/');
            class FastCGI_Purger {{
                public array $calls = [];
                public function purge_url($url, $recursive) {{
                    $this->calls[] = [$url, $recursive];
                }}
            }}
            require {json.dumps(str(PLUGIN / 'includes/class-cache-invalidation.php'))};
            function wp_parse_url($url) {{ return parse_url($url); }}
            $manifest = json_decode({json.dumps(json.dumps(manifest))}, true);
            $urls = json_decode({json.dumps(json.dumps(urls))}, true);
            $purger = new FastCGI_Purger();
            $selector = static function (string $url) use ($manifest): string {{
                return \\AChWorks\\AaPanelBridge\\CacheInvalidation::selectVerifiedFile(
                    $manifest, $url, '/nonexistent/denied');
            }};
            $dispatch = new ReflectionMethod(
                \\AChWorks\\AaPanelBridge\\CacheInvalidation::class, 'dispatchPublicUrls');
            $dispatch->invoke(null, $urls, $manifest, $purger, $selector);
            echo json_encode($purger->calls, JSON_THROW_ON_ERROR);
            """
            result = php_run(source)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = json.loads(result.stdout)
            self.assertEqual(calls, [
                ["http://qa.example/", False],
                ["https://qa.example/", False],
                ["https://qa.example/article/", False],
                ["http://qa.example/old/", False],
            ])
            for file in [*stored, stale, bad, peer_file]:
                self.assertTrue(file.exists(), "Vendor stub must not delete fixtures")

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
        self.assertIn("Version: 0.1.5", entry)
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
            self.assertEqual(first["version"], "0.1.5")
            with ZipFile(a) as package:
                names = package.namelist()
                self.assertEqual(len(names), 5)
                self.assertTrue(all(p.startswith("ach-aapanel-bridge/") for p in names))
                self.assertIn("ach-aapanel-bridge/ach-aapanel-bridge.php", names)
                self.assertFalse(any("/.." in p or "__pycache__" in p for p in names))


if __name__ == "__main__":
    unittest.main()
