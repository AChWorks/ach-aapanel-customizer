"""One-click WordPress connection regression: no repeated path edits."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"))
import ach_customizer_cache_wordpress as wp


class WordpressConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-wp-connect-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.site_dir = self.root / "wordpress"
        self.site_dir.mkdir()
        self.site = {"id": 7, "name": "wp.example.test", "path": str(self.site_dir)}
        self.cache = wp.CACHE_ROOT + "/site-7"
        self.config = self.site_dir / "wp-config.php"
        self.original_config = (
            "<?php\n"
            "define( 'DB_PASSWORD', 'leave-this-alone' );\n"
            "define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n"
            "require_once ABSPATH . 'wp-settings.php';\n"
        ).encode()
        self.config.write_bytes(self.original_config)
        self.ini = self.site_dir / ".user.ini"
        self.original_ini = ("open_basedir=" + str(self.site_dir) + "/:/tmp/\n").encode()
        self.ini.write_bytes(self.original_ini)
        self.previous = {"nginx_helper": False, "bridge": False,
                         "options_present": False,
                         "options": {"enable_purge": None, "cache_method": None,
                                     "purge_method": None}}
        self.connected = False
        self.events = []

    def fake_cache(self, action, site, *args, **kwargs):
        self.events.append(("cache", action))
        if action == "recheck":
            return {"state": "Applied" if self.connected else "Unmanaged",
                    "site_id": 7, "site_key": self.site["name"],
                    "runtime_verified": self.connected,
                    "recovery_id": "f" * 32 if self.connected else None}
        if action == "apply":
            self.connected = True
            return {"state": "Applied", "recovery_id": "f" * 32}
        if action == "bridge_enable":
            return {"state": "Provisioned"}
        if action == "restore":
            self.connected = False
            return {"state": "Restored"}
        raise AssertionError(action)

    def fake_php(self, site, version, command, **kwargs):
        self.events.append(("php", command))
        if command == "inspect":
            return {"previous": self.previous,
                    "active_helper": True, "active_bridge": True,
                    "options": {"enable_purge": 1, "purge_method": "unlink_files"}}
        return {"active_helper": True, "active_bridge": True}

    def start(self):
        patches = [
            patch.object(wp, "_site_root", return_value=str(self.site_dir)),
            patch.object(wp, "_native_record", side_effect=lambda *a: self.fake_cache("recheck", self.site)),
            patch.object(wp, "preview_cache_activation",
                         return_value={"native_handler": "wpfastcgi", "php_version": "85",
                                       "source_sha256": "a" * 64,
                                       "proposal_sha256": "b" * 64,
                                       "cache_generation": "c" * 32}),
            patch("ach_customizer_cache_audit.inspect_site_fastcgi_cache",
                  return_value={"php_version": "85"}),
            patch.object(wp, "_php", side_effect=self.fake_php),
            patch.object(wp, "manage_cache", side_effect=self.fake_cache),
            patch.object(wp, "_immutable", return_value=False),
            patch.object(wp, "_reload_php"),
            patch.object(wp, "_active_php", return_value="85"),
            patch("ach_customizer_cache_bridge.disable"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_single_click_configures_both_files_and_bridge_and_no_second_edits(self):
        self.start()
        first = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(first["state"], "Connected")
        self.assertIn(self.cache.encode(), self.config.read_bytes())
        self.assertIn((self.cache + "/").encode(), self.ini.read_bytes())
        self.assertIn(b"leave-this-alone", self.config.read_bytes())
        saved = (self.config.read_bytes(), self.ini.read_bytes())
        second = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(second["state"], "Connected")
        self.assertFalse(second["changed"])
        self.assertEqual((self.config.read_bytes(), self.ini.read_bytes()), saved)
        self.assertEqual(sum(e == ("cache", "apply") for e in self.events), 1)
        self.assertEqual(sum(e == ("cache", "bridge_enable") for e in self.events), 2)
        record = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertEqual(record["phase"], "connected")
        self.assertEqual(record["recovery_id"], "f" * 32)

    def test_one_click_disconnect_restores_original_lines_without_extra_steps(self):
        self.start()
        wp.setup(self.site, object(), data_dir=str(self.root))
        reply = wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(reply["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertIn(("php", "suspend"), self.events)
        self.assertIn(("php", "restore"), self.events)
        self.assertIn(("cache", "restore"), self.events)
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["changed"], False)
        with patch.object(wp, "_native_record", return_value={
                "state": "Restored", "recovery_id": "f" * 32,
                "runtime_verified": True}):
            self.assertEqual(
                wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                "Not Connected")

    def test_preexisting_native_cache_is_not_rolled_back_by_disconnect(self):
        # A site may already have a manually Applied native Cache before
        # WordPress Helper was installed. One-click owns only WP integration.
        self.connected = True
        self.start()
        first = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(first["state"], "Connected")
        journal = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertFalse(journal["cache_owned"])
        self.assertNotIn(("cache", "apply"), self.events)
        outcome = wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(outcome["state"], "Restored")
        self.assertTrue(self.connected, "Existing native Cache must remain Applied")
        self.assertNotIn(("cache", "restore"), self.events)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Not Connected")
        # The site can reconnect without reparing or reapplying the
        # previous native Cache generation or re-editing its owner file.
        again = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(again["state"], "Connected")
        self.assertTrue(self.connected)
        self.assertNotIn(("cache", "restore"), self.events)

    def test_missing_helper_fails_before_any_cache_write(self):
        self.start()
        with patch.object(wp, "_php", side_effect=wp.WordpressCacheError(
                "wordpress", "Required WordPress plugin missing: nginx-helper")):
            with self.assertRaisesRegex(wp.WordpressCacheError, "plugin missing"):
                wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertFalse((self.root / "ach_customizer.nginx-helper.7.json").exists())

    def test_custom_cache_path_must_not_be_overwritten(self):
        self.config.write_bytes(self.original_config.replace(
            b"/www/server/fastcgi_cache", b"/home/operator/custom-cache"))
        with patch.object(wp, "_immutable", return_value=False):
            with self.assertRaisesRegex(wp.WordpressCacheError, "custom"):
                wp._edits(self.site)
        self.assertIn(b"/home/operator/custom-cache", self.config.read_bytes())

    def test_atomic_editor_preserves_unrelated_settings(self):
        before, _ = wp._read_file(str(self.site_dir), "wp-config.php")
        after = before.replace(b"/www/server/fastcgi_cache", self.cache.encode())
        wp._replace_file(str(self.site_dir), "wp-config.php", before, after)
        self.assertIn(b"DB_PASSWORD", self.config.read_bytes())
        self.assertEqual(self.config.read_bytes(), after)
        with self.assertRaisesRegex(wp.WordpressCacheError, "modified"):
            wp._replace_file(str(self.site_dir), "wp-config.php", before, b"bad")

    def test_symlink_is_not_a_site_config(self):
        self.ini.unlink()
        self.ini.symlink_to(self.config)
        with self.assertRaises(OSError):
            wp._read_file(str(self.site_dir), ".user.ini")

    def test_bootstrap_only_adds_native_extension_before_php_block(self):
        vhost = self.root / "vhosts"
        vhost.mkdir()
        (vhost / "extension").mkdir()
        original = (b"server\n{\n    listen 80;\n    server_name wp.example.test;\n" +
                    ("    root " + str(self.site_dir) + ";\n").encode() +
                    b"    #PHP-INFO-START  PHP configuration\n"
                    b"    include enable-php-85-wpfastcgi.conf;\n"
                    b"    #PHP-INFO-END\n}\n")
        path = vhost / "wp.example.test.conf"
        path.write_bytes(original)
        with patch("ach_customizer_cache_manage.VHOST_ROOT", str(vhost)), \
             patch("ach_customizer_cache_manage._missing_extension_inventory"):
            self.assertTrue(wp._bootstrap_site_extension(self.site))
            self.assertTrue((vhost / "extension" / "wp.example.test").is_dir())
            line = b"    include " + str(vhost / "extension" / "wp.example.test" / "*.conf").encode() + b";\n"
            self.assertEqual(path.read_bytes().count(line), 1)
            self.assertEqual(path.read_bytes().replace(line, b"", 1), original)
            self.assertLess(path.read_bytes().find(b"root "), path.read_bytes().find(line))
            self.assertLess(path.read_bytes().find(line), path.read_bytes().find(b"#PHP-INFO-START"))

if __name__ == "__main__":
    unittest.main()
