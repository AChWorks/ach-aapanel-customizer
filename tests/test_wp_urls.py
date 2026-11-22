"""One-time native WordPress canonical HTTPS URL fixes and partial recovery."""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(ROOT))
import ach_customizer_wp_urls as urls
import ach_customizer_main as backend
from ach_customizer_state import _open_state_dir


class URLsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-wp-url-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "site"
        self.root.mkdir()
        self.data = Path(self.tmp.name) / "state"
        self.data.mkdir(mode=0o700)
        self.fd = _open_state_dir(str(self.data))
        self.addCleanup(os.close, self.fd)
        self.site = {"id": 8, "name": "wp.example.test", "path": str(self.root),
                     "status": 1, "bound_domains": [
                        {"name": "wp.example.test", "port": 80},
                        {"name": "example.test", "port": 443}
                     ]}
        self.public = object()
        self.original = {"home": "http://wp.example.test/",
                         "siteurl": "http://example.test:80/wp"}
        self.values = dict(self.original)
        self.process_commands = []
        self.config_sha = b"<?php native config"
        self.expected_php = "/www/server/php/85/bin/php"
        p = patch.object(urls, "_site_source", side_effect=self.source)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(urls, "_read_file", return_value=(b"<?php WordPress loader", None))
        p.start()
        self.addCleanup(p.stop)
        self.fail_after_first = False

    def source(self, site, public, *, vhost_root):
        self.assertIs(site, self.site)
        self.assertIs(public, self.public)
        self.assertEqual(vhost_root, "/www/server/panel/vhost/nginx")
        return self.config_sha, "/www/server/php/85/bin/php", "85"

    def runner(self, command, **kw):
        self.process_commands.append((command, kw))
        self.assertEqual(command[:4], ["runuser", "-u", "www", "--"])
        self.assertEqual(command[4], self.expected_php)
        self.assertEqual(kw["cwd"], self.site["path"])
        data = json.loads(kw["input"])
        if data["action"] == "set":
            if data["before"] != self.values:
                return types.SimpleNamespace(returncode=14, stdout="",
                    stderr="WordPress URLs changed before write")
            for key in urls.KEYS:
                self.values[key] = data["after"][key]
                if key == "home" and self.fail_after_first:
                    self.fail_after_first = False
                    return types.SimpleNamespace(returncode=15, stdout="",
                        stderr="Failure updating siteurl")
        return types.SimpleNamespace(
            returncode=0, stderr="",
            stdout="ACH_WP_URL_RESULT=" + json.dumps(self.values) + "\n",
        )

    def call(self, action, **kwargs):
        return urls.manage_urls(action, self.site, self.public, data_fd=self.fd,
                                runner=self.runner, **kwargs)

    def recheck(self):
        return self.call("recheck")

    def apply(self):
        preview = self.recheck()
        return self.call("apply", expected_source=preview["source_sha256"])

    def restore(self):
        current = self.recheck()
        return self.call("restore",
                         expected_source=current["source_sha256"],
                         expected_recovery=current["recovery_id"])

    def test_normal_home_siteurl_scheme_conversion_and_exact_recovery(self):
        preview = self.recheck()
        self.assertEqual(preview["state"], "Source Ready")
        self.assertEqual(preview["urls_before"], self.original)
        self.assertEqual(preview["urls_target"], {
            "home": "https://wp.example.test/",
            "siteurl": "https://example.test/wp",
        })
        self.assertFalse(list(self.data.iterdir()))
        applied = self.apply()
        self.assertEqual(applied["state"], "Applied")
        self.assertTrue(applied["runtime_verified"])
        self.assertEqual(self.recheck()["state"], "Applied")
        self.assertEqual(self.recheck()["recovery_id"], applied["recovery_id"])
        restored = self.restore()
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.values, self.original)
        self.assertEqual(self.recheck()["state"], "Restored")
        saved = json.loads((self.data / urls._name(8)).read_text())
        self.assertEqual(saved["phase"], "restored")
        self.assertEqual(saved["original"], self.original)
        self.assertEqual(saved["target"], preview["urls_target"])
        self.assertTrue(all(c["timeout"] == 45 for _, c in self.process_commands))

    def test_no_update_when_both_options_already_https(self):
        self.values = {"home": "https://wp.example.test",
                       "siteurl": "https://example.test/wp"}
        ready = self.recheck()
        self.assertEqual(ready["state"], "Already Configured")
        with self.assertRaisesRegex(urls.WPSettingsError, "already HTTPS"):
            self.call("apply", expected_source=ready["source_sha256"])
        self.assertFalse(list(self.data.iterdir()))

    def test_partial_php_write_can_be_restored_without_reapplying(self):
        self.fail_after_first = True
        with self.assertRaises(urls.WPSettingsError) as err:
            self.apply()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(self.values["home"], "https://wp.example.test/")
        self.assertEqual(self.values["siteurl"], self.original["siteurl"])
        self.assertEqual(self.recheck()["state"], "Recovery Required")
        recovered = self.restore()
        self.assertEqual(recovered["state"], "Restored")
        self.assertEqual(self.values, self.original)

    def test_foreign_wordpress_change_must_not_be_overwritten(self):
        self.apply()
        self.values["home"] = "https://new-cdn.example.com/"
        self.assertEqual(self.recheck()["state"], "Recovery Required")
        with self.assertRaisesRegex(urls.WPSettingsError, "independently"):
            self.restore()
        self.assertEqual(self.values["home"], "https://new-cdn.example.com/")

    def test_stale_preview_does_not_create_journal(self):
        old = self.recheck()
        self.values["home"] += "changed"
        with self.assertRaisesRegex(urls.WPSettingsError, "changed after Recheck"):
            self.call("apply", expected_source=old["source_sha256"])
        self.assertFalse(list(self.data.iterdir()))

    def test_unrelated_wp_config_or_php_version_changes_do_not_block_url_restore(self):
        applied = self.apply()
        self.config_sha = b"<?php unrelated WP_DEBUG changed after URL Apply"
        self.expected_php = "/www/server/php/81/bin/php"
        with patch.object(urls, "_site_source", side_effect=lambda *a, **kw:
                          (self.config_sha, "/www/server/php/81/bin/php", "81")):
            self.assertEqual(self.recheck()["state"], "Applied")
            self.assertEqual(self.restore()["state"], "Restored")
        self.assertEqual(self.values, self.original)
        self.assertTrue(applied["recovery_id"])

    def test_reapply_after_restored_option_changed_by_admin(self):
        first = self.apply()
        self.restore()
        self.values = {"home": "http://example.test/", "siteurl": "http://wp.example.test/"}
        review = self.recheck()
        self.assertEqual(review["state"], "Source Ready")
        self.assertNotEqual(review["source_sha256"], first["source_sha256"])
        fresh = self.call("apply", expected_source=review["source_sha256"])
        self.assertEqual(fresh["state"], "Applied")
        self.assertNotEqual(fresh["recovery_id"], first["recovery_id"])
        self.assertEqual(self.restore()["state"], "Restored")
        self.assertEqual(self.values["home"], "http://example.test/")

    def test_unsupported_hosts_credentials_or_fragments_cannot_change_wp(self):
        for bad in (
            "http://foreign.example.net/path",
            "http://user:pass@wp.example.test",
            "ftp://wp.example.test",
            "http://wp.example.test/?token=1",
            "http://wp.example.test/#app",
            "http://wp.example.test:broken",
            "http://wp.example.test\r\n",
        ):
            with self.subTest(bad=bad):
                self.values["home"] = bad
                with self.assertRaises(urls.WPSettingsError):
                    self.recheck()
                self.assertFalse(list(self.data.iterdir()))

    def test_only_one_known_http_url_is_updated(self):
        self.values["home"] = "https://wp.example.test/news"
        r = self.apply()
        self.assertEqual(r["state"], "Applied")
        self.assertEqual(self.values["home"], "https://wp.example.test/news")
        self.assertEqual(self.values["siteurl"], "https://example.test/wp")
        self.restore()
        self.assertEqual(self.values["home"], "https://wp.example.test/news")

    def test_wrong_recovery_id_refuses_restore(self):
        self.apply()
        fresh = self.recheck()
        with self.assertRaisesRegex(urls.WPSettingsError, "Recovery ID changed"):
            self.call("restore", expected_source=fresh["source_sha256"],
                      expected_recovery="0" * 32)
        self.assertEqual(self.recheck()["state"], "Applied")

    def test_invalid_journal_refused_without_run(self):
        record = self.data / urls._name(8)
        record.write_text("{}")
        record.chmod(0o600)
        with self.assertRaisesRegex(urls.WPSettingsError, "Invalid"):
            self.recheck()
        self.assertFalse(self.process_commands)

    def test_unchanged_restored_recovery_can_be_applied_again(self):
        first = self.apply()
        self.restore()
        second = self.apply()
        self.assertNotEqual(first["recovery_id"], second["recovery_id"])

    def test_php_bridge_never_targets_nondatabase_site_files(self):
        self.assertIn("require 'wp-load.php';", urls.PHP)
        self.assertIn("update_option($key", urls.PHP)
        self.assertIn("is_multisite()", urls.PHP)
        self.assertIn("defined('WP_HOME')", urls.PHP)
        self.assertIn("defined('WP_SITEURL')", urls.PHP)
        self.assertNotIn("file_put_contents", urls.PHP)


class URLSEndpointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = backend.ach_customizer_main()

    def test_primary_admin_post_required_before_site_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, (
                patch.object(backend, "_STATE_DIR", tmp)), (
                patch.object(backend.ach_customizer_main, "_status_primary_admin_post",
                             side_effect=PermissionError("No primary admin"))):
            r = self.plugin.wp_settings_manage({
                "settings_action": "apply", "settings_kind": "https",
                "desired": "https", "approved": "true"
            })
        self.assertFalse(r["status"])
        self.assertIn("authorization", r["stage"])

    def test_https_dispatch_is_selected_site_scoped(self):
        from contextlib import nullcontext
        site = {"id": 8, "name": "wp.example.test", "path": "/www/wwwroot/wp.example.test",
                "status": 1, "bound_domains": [
                    {"name": "wp.example.test", "port": 80}]}
        public = types.ModuleType("public")
        public.get_webserver = lambda: "nginx"
        response = {
            "schema": 1, "site_id": 8, "site_key": site["name"],
            "kind": "https", "state": "Applied", "changed": True,
            "source_sha256": "a" * 64, "recovery_id": "b" * 32,
        }
        with tempfile.TemporaryDirectory() as tmp, (
                patch.dict(sys.modules, {"public": public})), (
                patch.object(backend, "_STATE_DIR", tmp)), (
                patch.object(backend.ach_customizer_main, "_status_primary_admin_post")), (
                patch.object(backend.ach_customizer_main, "_require_enabled")), (
                patch.object(backend.ach_customizer_main, "_selected_native_website",
                             return_value=(public, site, lambda: dict(site)))), (
                patch("ach_customizer_cache_wordpress._site_lock",
                      return_value=nullcontext())), (
                patch.object(urls, "manage_urls", return_value=response)) as managed:
            result = self.plugin.wp_settings_manage({
                "settings_action": "apply", "settings_kind": "https",
                "desired": "https", "site_id": "8", "approved": "true",
                "expected_source_sha256": "c" * 64
            })
        self.assertTrue(result["status"], result)
        self.assertEqual(result["kind"], "https")
        self.assertEqual(managed.call_args.args[:3], ("apply", site, public))
        self.assertEqual(managed.call_args.kwargs["expected_source"], "c" * 64)


if __name__ == "__main__":
    unittest.main()
