"""Real embedded PHP lifecycle with file-backed, filterable WordPress role stubs.

The separate PHP processes matter: WP_Role::add_cap mutates its in-memory
capabilities even when durable option persistence is rejected.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"))
from ach_customizer_cache_wordpress import PHP_BRIDGE

PHP = shutil.which("php")

WP_BOOTSTRAP = r"""<?php
define('ABSPATH', __DIR__ . '/');
define('WP_PLUGIN_DIR', __DIR__ . '/wp-content/plugins');
define('RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/ach-customizer-fastcgi/site-7');

function fixture_read($filename, $default) {
    $path = __DIR__ . '/' . $filename;
    return file_exists($path) ? json_decode(file_get_contents($path), true) : $default;
}
function fixture_write($filename, $value) {
    file_put_contents(__DIR__ . '/' . $filename, json_encode($value));
}
class FilteredPersistedRole {
    public array $capabilities;
    public function __construct() {
        $this->capabilities = fixture_read('role.json', []);
    }
    public function has_cap($cap) {
        $filtered = fixture_read('filter.json', []);
        return array_key_exists($cap, $filtered)
            ? (bool)$filtered[$cap] : (bool)($this->capabilities[$cap] ?? false);
    }
    private function persist($cap, $which) {
        if (!file_exists(__DIR__ . '/persist-fail')) {
            fixture_write('role.json', $this->capabilities);
        }
        $mark = __DIR__ . '/interrupt-' . $which . '-' . $cap;
        if (file_exists($mark)) {
            unlink($mark);
            exit(77);
        }
    }
    public function add_cap($cap, $grant=true) {
        $this->capabilities[$cap] = (bool)$grant;
        $this->persist($cap, 'add');
    }
    public function remove_cap($cap) {
        unset($this->capabilities[$cap]);
        $this->persist($cap, 'remove');
    }
}
function get_role($role) {
    if ($role !== 'administrator') return null;
    static $admin = null;
    return $admin ??= new FilteredPersistedRole();
}
function get_site_option($key, $default=false) {
    if ($key !== 'rt_wp_nginx_helper_options') return $default;
    return fixture_read('options.json', $default);
}
function update_site_option($key, $value) {
    fixture_write('options.json', $value);
    return true;
}
function is_plugin_active($name) {
    $active = fixture_read('active.json', []);
    return in_array($name, $active, true);
}
function is_wp_error($obj) { return false; }
function activate_plugin($name) {
    $active = fixture_read('active.json', []);
    if (!in_array($name, $active, true)) $active[] = $name;
    fixture_write('active.json', $active);
    return null;
}
function deactivate_plugins($name) {
    $active = fixture_read('active.json', []);
    fixture_write('active.json', array_values(array_diff($active, [$name])));
}
"""


@unittest.skipUnless(PHP, "PHP CLI required for WordPress role persistence regressions")
class WordPressPersistedRolePHPTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-wp-role-persistence-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "wp-load.php").write_text(WP_BOOTSTRAP)
        path = self.root / "wp-admin/includes/plugin.php"
        path.parent.mkdir(parents=True)
        path.write_text("<?php // Wordpress plugin function stub\n")
        for name in ("nginx-helper/nginx-helper.php",
                     "ach-aapanel-bridge/ach-aapanel-bridge.php"):
            plugin = self.root / "wp-content/plugins" / name
            plugin.parent.mkdir(parents=True, exist_ok=True)
            plugin.write_text("<?php // installed plugin fixture\n")

    def save(self, file, obj):
        (self.root / file).write_text(json.dumps(obj))

    def load(self, file):
        return json.loads((self.root / file).read_text())

    def php(self, action, **kwargs):
        result = subprocess.run(
            [PHP, "-d", "display_errors=stderr", "-r", PHP_BRIDGE],
            cwd=self.root,
            input=json.dumps({"action": action, **kwargs}),
            capture_output=True, text=True, timeout=12, check=False)
        replies = [x.removeprefix("ACH_WORDPRESS_CACHE_RESULT=")
                   for x in result.stdout.splitlines()
                   if x.startswith("ACH_WORDPRESS_CACHE_RESULT=")]
        return result, json.loads(replies[0]) if len(replies) == 1 else None

    def inspect(self):
        r, output = self.php("inspect")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNotNone(output)
        return output["previous"]

    def connect(self):
        return self.php("connect",
                        expected_cache_path="/www/server/ach-customizer-fastcgi/site-7")

    def restore(self, baseline):
        return self.php("restore", previous=baseline)

    def test_filter_true_but_role_key_absent_is_restored_to_absent(self):
        self.save("role.json", {})
        self.save("filter.json", {"Nginx Helper | Config": True,
                                  "Nginx Helper | Purge cache": True})
        old = self.inspect()
        self.assertEqual(set(old["admin_caps_stored"].values()), {None})
        self.assertEqual(set(old["admin_caps_effective"].values()), {True})
        connected, _ = self.connect()
        self.assertEqual(connected.returncode, 0, connected.stderr)
        fresh = self.inspect()
        self.assertEqual(set(fresh["admin_caps_stored"].values()), {True})
        result, _ = self.restore(old)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.load("role.json"))
        self.assertEqual(set(self.inspect()["admin_caps_effective"].values()), {True})

    def test_stored_true_and_filtered_false_must_never_erase_grant(self):
        self.save("role.json", {"Nginx Helper | Config": True})
        self.save("filter.json", {"Nginx Helper | Config": False})
        old = self.inspect()
        self.assertIs(old["admin_caps_stored"]["Nginx Helper | Config"], True)
        self.assertIs(old["admin_caps_effective"]["Nginx Helper | Config"], False)
        failed, _ = self.connect()
        self.assertEqual(failed.returncode, 17, failed.stderr)
        self.assertEqual(self.load("role.json"), {"Nginx Helper | Config": True})
        restored, _ = self.restore(old)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(self.load("role.json"), {"Nginx Helper | Config": True})

    def test_durable_storage_failure_is_visible_in_next_php_process(self):
        self.save("role.json", {})
        (self.root / "persist-fail").touch()
        connected, _ = self.connect()
        # The native subprocess alone sees a mutated in-memory WP_Role.
        self.assertEqual(connected.returncode, 0, connected.stderr)
        self.assertEqual(self.load("role.json"), {})
        fresh = self.inspect()
        self.assertEqual(set(fresh["admin_caps_stored"].values()), {None})
        self.assertEqual(set(fresh["admin_caps_effective"].values()), {False})
        (self.root / "persist-fail").unlink()
        retried, _ = self.connect()
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(set(self.inspect()["admin_caps_stored"].values()), {True})

    def test_mixed_stored_true_false_restored_without_boolean_coercion(self):
        self.save("role.json", {"Nginx Helper | Config": True,
                                "Nginx Helper | Purge cache": False})
        old = self.inspect()
        connected, _ = self.connect()
        self.assertEqual(connected.returncode, 0, connected.stderr)
        self.assertEqual(set(self.inspect()["admin_caps_stored"].values()), {True})
        restored, _ = self.restore(old)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(self.load("role.json"),
                         {"Nginx Helper | Config": True, "Nginx Helper | Purge cache": False})

    def test_interrupted_connect_and_restore_reuse_original_snapshot(self):
        self.save("role.json", {})
        original = self.inspect()
        (self.root / "interrupt-add-Nginx Helper | Config").touch()
        interrupted, _ = self.connect()
        self.assertEqual(interrupted.returncode, 77, interrupted.stderr)
        self.assertEqual(self.load("role.json"), {"Nginx Helper | Config": True})
        connected, _ = self.connect()
        self.assertEqual(connected.returncode, 0, connected.stderr)
        self.assertEqual(set(self.inspect()["admin_caps_stored"].values()), {True})
        (self.root / "interrupt-remove-Nginx Helper | Config").touch()
        interrupted, _ = self.restore(original)
        self.assertEqual(interrupted.returncode, 77, interrupted.stderr)
        self.assertEqual(self.load("role.json"),
                         {"Nginx Helper | Purge cache": True})
        restored, _ = self.restore(original)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertFalse(self.load("role.json"))

    def test_legacy_filtered_metadata_does_not_change_persisted_grants(self):
        self.save("role.json", {"Nginx Helper | Config": True})
        saved = self.inspect()
        del saved["admin_caps_stored"]
        saved["admin_caps"] = {"Nginx Helper | Config": False,
                               "Nginx Helper | Purge cache": False}
        restored, _ = self.restore(saved)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(self.load("role.json"), {"Nginx Helper | Config": True})


if __name__ == "__main__":
    unittest.main()
