"""Isolated aaPanel/Nginx FastCGI source-only cache diagnosis and drift tests."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_cache_audit as audit


class FastCgiCacheSourceTests(unittest.TestCase):
    class Query:
        def __init__(self, panel):
            self.panel = panel
        def order(self, s):
            assert s == "id asc"
            return self
        def limit(self, s):
            assert s == "0,101"
            return self
        def field(self, s):
            assert s == "id,name"
            return self
        def select(self):
            self.panel.reads += 1
            return [dict(x) for x in self.panel.rows[:101]]

    class Panel:
        def __init__(self, rows):
            self.rows = rows
            self.reads = 0
            self.engine = "nginx"
            self.version = "8.0.7"
        def get_webserver(self):
            return self.engine
        def get_panel_version(self):
            return self.version
        def M(self, name):
            assert name == "sites"
            return FastCgiCacheSourceTests.Query(self)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-fastcgi-cache-source-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.nginx = self.root / "nginx"
        self.nginx.mkdir()
        self.vhost = self.root / "vhost"
        self.vhost.mkdir()
        self.rewrites = self.root / "rewrite"
        self.rewrites.mkdir()
        self.panel = self.Panel([
            {"id": 4, "name": "wp.test"},
            {"id": 6, "name": "shop.test"},
        ])
        (self.nginx / "nginx.conf").write_text(
            "http {\n fastcgi_cache_path /www/server/fastcgi_cache "
            "levels=1:2 keys_zone=WORDPRESS:100m inactive=60m;\n}\n")
        self.native_snippet = (
            "location ~ \\.php$ {\n include fastcgi.conf;\n"
            " fastcgi_pass unix:/tmp/php-cgi-85.sock;\n"
            " fastcgi_cache WORDPRESS;\n"
            " fastcgi_cache_key \"$scheme$request_method$host$request_uri\";\n"
            " fastcgi_cache_bypass $skip_cache $http_authorization;\n"
            " fastcgi_no_cache $skip_cache $http_authorization;\n"
            " fastcgi_cache_valid 200 10m;\n"
            "}\n"
            "location ~ /purge(/.*) {\n"
            " fastcgi_cache_purge WORDPRESS \"$scheme$request_method$host$1\";\n}\n"
        )
        (self.nginx / "enable-php-85-wpfastcgi.conf").write_text(self.native_snippet)
        (self.nginx / "fastcgi.conf").write_text(
            "fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        )
        for site in self.panel.rows:
            self.make_vhost(site["name"])

    def make_vhost(self, name, variant="enable-php-85-wpfastcgi.conf"):
        (self.vhost / (name + ".conf")).write_text(
            "server {\n server_name " + name + ";\n"
            " include " + variant + ";\n}\n")

    def inspect(self):
        return audit.inspect_site_fastcgi_cache(
            self.panel, 4, "wp.test",
            vhost_root=str(self.vhost), nginx_root=str(self.nginx),
            rewrite_root=str(self.rewrites))

    def test_exact_native_cache_sources_and_shared_zone_are_observations_only(self):
        files = [self.nginx / "nginx.conf",
                 self.nginx / "enable-php-85-wpfastcgi.conf",
                 self.vhost / "wp.test.conf", self.vhost / "shop.test.conf"]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        result = self.inspect()
        self.assertEqual(result["state"], "Source Observed", result)
        self.assertEqual(result["site_id"], 4)
        self.assertEqual(result["cache_zone"], "WORDPRESS")
        self.assertEqual(result["zone_state"], "Direct Zone")
        self.assertTrue(result["global_zone_directly_declared"])
        self.assertTrue(result["bypass_directive_seen"])
        self.assertTrue(result["no_cache_directive_seen"])
        self.assertTrue(result["host_key_variable_seen"])
        self.assertTrue(result["purge_directive_seen"])
        self.assertEqual(result["other_sites_same_zone"],
                         [{"id": 6, "site_key": "shop.test"}])
        self.assertEqual(result["unresolved_other_sites"], 0)
        self.assertIn("SHARED_ZONE_REFERENCES", result["findings"])
        self.assertIn("PURGE_DIRECTIVE_OBSERVED", result["findings"])
        self.assertIn("PRIVATE_ROUTE_RUNTIME_TEST_REQUIRED", result["findings"])
        self.assertNotIn("NO_DIRECT_CACHE_BYPASS", result["findings"])
        for key in ("read_only", "runtime_verified", "cache_safe_verified",
                    "purge_supported", "fix_supported"):
            self.assertEqual(result[key], key == "read_only")
        self.assertRegex(result["source_sha256"], r"^[0-9a-f]{64}$")
        self.assertGreaterEqual(self.panel.reads, 2)
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in files})

    def test_bypass_and_write_controls_are_distinct_and_missing_guards_reported(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        php.write_text(self.native_snippet.replace(
            " fastcgi_cache_bypass $skip_cache $http_authorization;\n", ""
        ).replace(
            " fastcgi_no_cache $skip_cache $http_authorization;\n", ""
        ).replace(
            "$scheme$request_method$host$request_uri", "$scheme$request_uri"
        ).replace(
            " fastcgi_cache_valid 200 10m;",
            " fastcgi_cache_methods GET HEAD POST;\n fastcgi_cache_valid 200 10m;"
        ))
        got = self.inspect()
        self.assertEqual(got["state"], "Source Observed", got)
        self.assertIn("NO_DIRECT_CACHE_BYPASS", got["findings"])
        self.assertIn("NO_DIRECT_CACHE_WRITE_GUARD", got["findings"])
        self.assertIn("HOST_PARTITION_NOT_OBSERVED", got["findings"])
        self.assertIn("NON_GET_CACHE_METHOD", got["findings"])

    def test_ignore_response_header_is_review_signal_not_data_leak_assertion(self):
        snippet = self.nginx / "enable-php-85-wpfastcgi.conf"
        snippet.write_text(self.native_snippet.replace(
            " fastcgi_cache_valid 200 10m;",
            " fastcgi_ignore_headers Cache-Control Set-Cookie;\n"
            " fastcgi_cache_valid 200 10m;"
        ))
        got = self.inspect()
        self.assertEqual(got["ignore_headers"], ["Cache-Control", "Set-Cookie"])
        self.assertIn("RESPONSE_CACHE_HEADER_IGNORED", got["findings"])
        self.assertFalse(got["cache_safe_verified"])
        self.assertNotIn("PERSONAL_DATA_LEAK", got["findings"])

    def test_nested_parameters_are_fingerprinted_and_unrecognized_routes_refused(self):
        first = self.inspect()
        self.assertEqual(first["state"], "Source Observed")
        param = self.nginx / "fastcgi.conf"
        param.write_text(
            param.read_text() + "fastcgi_no_cache $http_authorization;\n")
        changed = self.inspect()
        self.assertEqual(changed["state"], "Source Observed", changed)
        self.assertNotEqual(changed["source_sha256"], first["source_sha256"])
        snippet = self.nginx / "enable-php-85-wpfastcgi.conf"
        snippet.write_text(self.native_snippet.replace(
            "include fastcgi.conf;", "include /tmp/cache-external.conf;"))
        self.assertEqual(self.inspect()["state"], "Needs Review")
        snippet.write_text(self.native_snippet)
        param.write_text("include /tmp/unknown-cache-settings.conf;\n")
        self.assertEqual(self.inspect()["state"], "Needs Review")
        param.write_text("fastcgi_pass unix:/tmp/other-fpm.sock;\n")
        self.assertEqual(self.inspect()["state"], "Needs Review")

    def test_lowercase_response_header_names_are_not_missed(self):
        snippet = self.nginx / "enable-php-85-wpfastcgi.conf"
        snippet.write_text(self.native_snippet.replace(
            " fastcgi_cache_valid 200 10m;",
            " fastcgi_ignore_headers set-cookie cache-control;\n"
            " fastcgi_cache_valid 200 10m;"
        ))
        result = self.inspect()
        self.assertEqual(result["state"], "Source Observed", result)
        self.assertEqual(result["ignore_headers"], ["Cache-Control", "Set-Cookie"])
        self.assertIn("RESPONSE_CACHE_HEADER_IGNORED", result["findings"])

    def test_incomplete_other_site_is_partial_and_cannot_infer_complete_scope(self):
        self.make_vhost("shop.test", "/tmp/operator-overrides.conf")
        result = self.inspect()
        self.assertEqual(result["state"], "Partial", result)
        self.assertEqual(result["unresolved_other_sites"], 1)
        self.assertEqual(result["other_sites_same_zone"], [])
        self.assertIn("incomplete", result["reason"])
        self.assertFalse(result["cache_safe_verified"])

    def test_direct_no_cache_is_not_equivalent_to_loaded_cache_disabled(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        php.write_text(self.native_snippet.replace(
            " fastcgi_cache WORDPRESS;", " fastcgi_cache off;"))
        got = self.inspect()
        self.assertEqual(got["state"], "Source Observed", got)
        self.assertEqual(got["zone_state"], "Direct Off")
        self.assertIsNone(got["cache_zone"])
        self.assertNotIn("PRIVATE_ROUTE_RUNTIME_TEST_REQUIRED", got["findings"])
        php.write_text(self.native_snippet.replace(
            " fastcgi_cache WORDPRESS;", ""))
        got = self.inspect()
        self.assertEqual(got["state"], "Source Observed")
        self.assertEqual(got["zone_state"], "No Direct Directive")
        self.assertIsNone(got["cache_zone"])

    def test_duplicate_and_inline_cache_directives_are_needs_review(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        php.write_text(self.native_snippet.replace(
            " fastcgi_cache WORDPRESS;",
            " fastcgi_cache WORDPRESS;\n fastcgi_cache OTHER;"))
        got = self.inspect()
        self.assertEqual(got["state"], "Needs Review", got)
        self.assertIsNone(got["source_sha256"])
        php.write_text(self.native_snippet.replace(
            " fastcgi_cache WORDPRESS;", " location ~ x { fastcgi_cache WORDPRESS; }"
        ))
        self.assertEqual(self.inspect()["state"], "Needs Review")

    def test_symlink_and_untrusted_directive_do_not_get_source_confidence(self):
        site = self.vhost / "wp.test.conf"
        site.unlink()
        site.symlink_to("/etc/hosts")
        got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertFalse(got["cache_safe_verified"])
        site.unlink()
        self.make_vhost("wp.test", "enable-php-85-wpfastcgi.conf")
        site.write_text(site.read_text() + " include /tmp/external-cache.conf;\n")
        self.assertEqual(self.inspect()["state"], "Needs Review")

    def test_site_extension_with_unverified_location_is_refused_not_ignored(self):
        site = self.vhost / "wp.test.conf"
        extension_dir = self.vhost / "extension" / "wp.test"
        extension_dir.mkdir(parents=True)
        (extension_dir / "custom.conf").write_text(
            "location /private { fastcgi_cache WORDPRESS; }\n")
        site.write_text(site.read_text().replace(
            "}\n", " include " + str(extension_dir / "*.conf") + ";\n}\n"))
        self.assertEqual(self.inspect()["state"], "Needs Review")
        (extension_dir / "custom.conf").write_text("access_log off;\n")
        self.assertEqual(self.inspect()["state"], "Source Observed")

    def test_source_change_during_scan_rejects_all_positive_claims(self):
        original = audit._site_source
        calls = 0
        def reconfigure(*args, **kwargs):
            nonlocal calls
            found = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                snippet = self.nginx / "enable-php-85-wpfastcgi.conf"
                snippet.write_text(snippet.read_text() + "# regenerated\n")
            return found
        with patch.object(audit, "_site_source", side_effect=reconfigure):
            got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertIsNone(got["source_sha256"])
        self.assertEqual(got["other_sites_same_zone"], [])

    def test_unsupported_panel_and_large_native_site_inventory_are_not_proven(self):
        self.panel.rows = [
            {"id": i, "name": "site" + str(i) + ".test"} for i in range(1, 102)
        ]
        self.assertEqual(self.inspect()["state"], "Needs Review")
        self.panel.rows = [{"id": 4, "name": "wp.test"}]
        self.panel.engine = "apache"
        self.assertEqual(self.inspect()["state"], "Needs Review")
        self.panel.engine = "nginx"
        self.panel.version = "8.1.0"
        self.assertEqual(self.inspect()["state"], "Needs Review")


if __name__ == "__main__":
    unittest.main()
