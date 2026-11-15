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
        self.assertIn("Version: 0.1.0", entry)
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
            self.assertEqual(first["version"], "0.1.0")
            with ZipFile(a) as package:
                names = package.namelist()
                self.assertEqual(len(names), 4)
                self.assertTrue(all(p.startswith("ach-aapanel-bridge/") for p in names))
                self.assertIn("ach-aapanel-bridge/ach-aapanel-bridge.php", names)
                self.assertFalse(any("/.." in p or "__pycache__" in p for p in names))


if __name__ == "__main__":
    unittest.main()
