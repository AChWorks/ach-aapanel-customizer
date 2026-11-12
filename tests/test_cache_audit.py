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

    def global_cache_fixture(self):
        # Models the actual aaPanel 8.0.7 main -> top-level *.conf inclusion.
        (self.nginx / "nginx.conf").write_text(
            "events {}\nhttp {\n include " + str(self.vhost) + "/*.conf;\n}\n"
        )
        cache = self.vhost / "0.fastcgi_cache.conf"
        cache.write_text(
            'fastcgi_cache_key "$scheme$request_method$host$request_uri";\n'
            'fastcgi_cache_path /www/server/fastcgi_cache levels=1:2 '
            'keys_zone=WORDPRESS:100m inactive=60m max_size=1g;\n'
            'fastcgi_cache_use_stale error timeout invalid_header http_500;\n'
            'fastcgi_ignore_headers Cache-Control Expires Set-Cookie;\n'
        )
        return cache

    def test_regenerated_native_subdir_is_checked_for_selected_and_peer_sites(self):
        self.global_cache_fixture()
        selected = self.vhost / "wp.test.conf"
        peer = self.vhost / "shop.test.conf"

        def with_subdir(vhost, key):
            original = vhost.read_text()
            mask = self.vhost / "sub_dir" / key / "*.conf"
            vhost.write_text(original.replace(
                "include enable-php-85-wpfastcgi.conf;",
                "include " + str(mask) + ";\n"
                "include enable-php-85-wpfastcgi.conf;"))
            return mask.parent

        peer_dir = with_subdir(peer, "shop.test")
        self.assertEqual(self.inspect()["state"], "Source Observed")
        peer_dir.mkdir(parents=True)
        self.assertEqual(self.inspect()["state"], "Source Observed")
        (peer_dir / "foreign.conf").write_text(
            "location /checkout { fastcgi_cache WORDPRESS; }\n")
        unresolved = self.inspect()
        self.assertEqual(unresolved["state"], "Partial", unresolved)
        self.assertEqual(unresolved["unresolved_other_sites"], 1)
        self.assertEqual(unresolved["purge_scope"], "Unknown")
        self.assertFalse(unresolved["purge_supported"])
        (peer_dir / "foreign.conf").unlink()

        selected_dir = with_subdir(selected, "wp.test")
        self.assertEqual(self.inspect()["state"], "Source Observed")
        selected_dir.mkdir(parents=True)
        (selected_dir / "foreign.conf").write_text(
            "location /pay { fastcgi_no_cache off; }\n")
        refused = self.inspect()
        self.assertEqual(refused["state"], "Needs Review")
        self.assertIsNone(refused["source_sha256"])
        self.assertFalse(refused["purge_supported"])
        (selected_dir / "foreign.conf").unlink()

        selected_dir.rmdir()
        selected_dir.symlink_to(peer_dir, target_is_directory=True)
        self.assertEqual(self.inspect()["state"], "Needs Review")
        selected_dir.unlink()
        self.assertEqual(self.inspect()["state"], "Source Observed")

    def test_global_aaPanel_cache_include_is_fingerprinted_and_flags_shared_physical_purge(self):
        cache = self.global_cache_fixture()
        result = self.inspect()
        self.assertEqual(result["state"], "Source Observed", result)
        self.assertEqual(result["cache_zone"], "WORDPRESS")
        self.assertEqual(result["php_version"], "85")
        self.assertFalse(result["global_zone_directly_declared"])
        self.assertTrue(result["aaPanel_global_include_observed"])
        self.assertEqual(result["cache_directory"],"/www/server/fastcgi_cache")
        self.assertEqual(result["global_ignore_headers"],
                         ["Cache-Control","Expires","Set-Cookie"])
        self.assertEqual(result["ignore_headers"],["Cache-Control","Expires","Set-Cookie"])
        self.assertEqual(result["purge_scope"],"Shared Registered Directory")
        self.assertEqual(result["other_sites_same_zone"],
                         [{"id":6,"site_key":"shop.test"}])
        self.assertEqual(result["other_sites_same_directory"],
                         [{"id":6,"site_key":"shop.test"}])
        self.assertIn("GLOBAL_RESPONSE_CACHE_HEADER_IGNORED",result["findings"])
        self.assertIn("SHARED_CACHE_DIRECTORY_PURGE_RISK",result["findings"])
        self.assertNotIn("ZONE_DECLARATION_NOT_IN_MAIN_FILE",result["findings"])
        self.assertFalse(result["purge_supported"])
        self.assertFalse(result["cache_safe_verified"])
        before=result["source_sha256"]
        cache.write_text(cache.read_text().replace("inactive=60m","inactive=20m"))
        self.assertNotEqual(self.inspect()["source_sha256"],before)

    def test_global_include_does_not_make_uncached_site_look_active(self):
        self.global_cache_fixture()
        (self.nginx / "enable-php-85-wpfastcgi.conf").write_text(
            self.native_snippet.replace(" fastcgi_cache WORDPRESS;",""))
        observed=self.inspect()
        self.assertEqual(observed["state"],"Source Observed")
        self.assertEqual(observed["zone_state"],"No Direct Directive")
        self.assertIsNone(observed["cache_zone"])
        self.assertIsNone(observed["cache_directory"])
        self.assertEqual(observed["purge_scope"],"Unknown")
        self.assertEqual(observed["other_sites_same_directory"],[])
        self.assertEqual(observed["global_ignore_headers"],
                         ["Cache-Control","Expires","Set-Cookie"])
        self.assertNotIn("GLOBAL_RESPONSE_CACHE_HEADER_IGNORED",observed["findings"])
        self.assertTrue(observed["host_key_variable_seen"])  # observed global source only

    def test_global_cache_include_requires_known_literal_main_reference(self):
        cache=self.global_cache_fixture()
        (self.nginx/"nginx.conf").write_text("events {}\nhttp {}\n")
        self.assertEqual(self.inspect()["state"],"Needs Review")
        self.assertIn("unverified Nginx include",self.inspect()["reason"])
        (self.nginx/"nginx.conf").write_text(
            "events {}\nhttp {\n include " + str(self.vhost) + "/*.conf;\n}\n")
        cache.unlink()
        cache.symlink_to("/etc/hosts")
        got=self.inspect()
        self.assertEqual(got["state"],"Needs Review")
        self.assertIsNone(got["source_sha256"])
        self.assertIsNone(got["cache_directory"])

    def test_unmodelled_global_cache_control_remains_needs_review(self):
        cache=self.global_cache_fixture()
        for extra in ("fastcgi_cache_background_update on;",
                      "fastcgi_cache_path /tmp/reused keys_zone=WORDPRESS:1m;",
                      "fastcgi_cache_use_stale error; fastcgi_ignore_headers Set-Cookie;"):
            with self.subTest(extra=extra):
                cache.write_text(
                    'fastcgi_cache_key "$scheme$request_method$host$request_uri";\n'
                    'fastcgi_cache_path /www/server/fastcgi_cache keys_zone=WORDPRESS:100m;\n'
                    +extra+"\n"
                )
                got=self.inspect()
                self.assertEqual(got["state"],"Needs Review",got)
                self.assertFalse(got["purge_supported"])
                self.assertIsNone(got["cache_directory"])

    def test_global_cache_directory_collision_reports_other_zone_peer(self):
        self.global_cache_fixture()
        # A different zone label does not establish a different directory.
        cache=self.vhost/"0.fastcgi_cache.conf"
        cache.write_text(cache.read_text() +
            'fastcgi_cache_path /www/server/fastcgi_cache keys_zone=ALTERNATE:50m;\n')
        php=self.nginx/"enable-php-81-wpfastcgi.conf"
        php.write_text(self.native_snippet.replace(
            "fastcgi_cache WORDPRESS;","fastcgi_cache ALTERNATE;").replace(
            "php-cgi-85.sock","php-cgi-81.sock"))
        self.make_vhost("shop.test","enable-php-81-wpfastcgi.conf")
        got=self.inspect()
        self.assertEqual(got["state"],"Source Observed",got)
        self.assertEqual(got["other_sites_same_zone"],[])
        self.assertEqual(got["other_sites_same_directory"],
                         [{"id":6,"site_key":"shop.test"}])
        self.assertEqual(got["purge_scope"],"Shared Registered Directory")
        self.assertIn("SHARED_CACHE_DIRECTORY_PURGE_RISK",got["findings"])

    def test_global_cache_include_must_be_direct_http_child(self):
        self.global_cache_fixture()
        include = " include " + str(self.vhost) + "/*.conf;\n"
        for content in (
                "events {\n" + include + "}\nhttp {}\n",
                "stream {\n" + include + "}\nhttp {}\n",
                "http {\n server {\n" + include + " }\n}\n",
                "http {\n map $uri $key {\n" + include + " }\n}\n",
                "server {\n" + include + "}\nhttp {}\n",
        ):
            with self.subTest(config=content):
                (self.nginx / "nginx.conf").write_text(content)
                result = self.inspect()
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertIsNone(result["source_sha256"])
                self.assertIsNone(result["cache_directory"])
                self.assertEqual(result["purge_scope"], "Unknown")
        # A literal brace in a quoted log format is not an Nginx block.
        (self.nginx / "nginx.conf").write_text(
            "events {}\nstream { server { listen 1111; } }\n"
            "http {\n log_format test '$uri {literal}';\n"
            + include + "}\n"
        )
        result = self.inspect()
        self.assertEqual(result["state"], "Source Observed", result)
        self.assertTrue(result["aaPanel_global_include_observed"])

    def test_global_file_rejects_uninspected_nested_or_secondary_active_directives(self):
        global_file = self.global_cache_fixture()
        original = global_file.read_text()
        for extra in (
                "include /etc/nginx/cache-other.conf;",
                "include /etc/nginx/cache-extra/*.conf;",
                "fastcgi_cache_lock on;",
                "server { fastcgi_ignore_headers Set-Cookie; }",
                "map $http_cookie $private { default 0; }",
                "fastcgi_cache_key '$scheme$host'; include another.conf;",
                "some_extension ignored;",
        ):
            with self.subTest(extra=extra):
                global_file.write_text(original + extra + "\n")
                result = self.inspect()
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertIsNone(result["source_sha256"])
                self.assertIsNone(result["cache_directory"])
                self.assertEqual(result["other_sites_same_directory"], [])
                self.assertFalse(result["purge_supported"])
        global_file.write_text(original + "# inert comment\n")
        self.assertEqual(self.inspect()["state"], "Source Observed")

    def test_global_stale_options_require_supported_nginx_literals(self):
        global_file = self.global_cache_fixture()
        original = global_file.read_text()
        previous = "fastcgi_cache_use_stale error timeout invalid_header http_500;"
        for valid in ("off", "error", "timeout updating http_500 http_503",
                      "http_403 http_404 http_429 invalid_header"):
            with self.subTest(valid=valid):
                global_file.write_text(original.replace(
                    previous, "fastcgi_cache_use_stale " + valid + ";"))
                result = self.inspect()
                self.assertEqual(result["state"], "Source Observed", result)
                self.assertIsNotNone(result["source_sha256"])
        for invalid in ("http_502", "off error", "error error", "bogus",
                        "error http_999", "off timeout"):
            with self.subTest(invalid=invalid):
                global_file.write_text(original.replace(
                    previous, "fastcgi_cache_use_stale " + invalid + ";"))
                result = self.inspect()
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertIsNone(result["source_sha256"])
                self.assertIsNone(result["cache_directory"])
                self.assertEqual(result["purge_scope"], "Unknown")

    def test_cache_directory_aliases_never_report_no_peer(self):
        global_file = self.global_cache_fixture()
        original = global_file.read_text()
        php = self.nginx / "enable-php-81-wpfastcgi.conf"
        php.write_text(self.native_snippet.replace(
            "fastcgi_cache WORDPRESS;", "fastcgi_cache ALTERNATE;"
        ).replace("php-cgi-85.sock", "php-cgi-81.sock"))
        self.make_vhost("shop.test", "enable-php-81-wpfastcgi.conf")
        for alias in ("/www/server/fastcgi_cache/",
                      "/www/server/./fastcgi_cache",
                      "/www/server/fastcgi_cache/.",
                      "/www/server/cache/../fastcgi_cache",
                      "/www/server//fastcgi_cache",
                      "//www/server/fastcgi_cache"):
            with self.subTest(alias=alias):
                global_file.write_text(original +
                    "fastcgi_cache_path " + alias +
                    " keys_zone=ALTERNATE:50m;\n")
                result = self.inspect()
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertIsNone(result["source_sha256"])
                self.assertIsNone(result["cache_directory"])
                self.assertEqual(result["purge_scope"], "Unknown")
                self.assertFalse(result["purge_supported"])
        # Two different canonical path strings may alias via a mount or
        # symlink, so source-only data cannot certify physical isolation.
        global_file.write_text(original +
            "fastcgi_cache_path /www/server/another-cache keys_zone=ALTERNATE:50m;\n")
        result = self.inspect()
        self.assertEqual(result["state"], "Source Observed", result)
        self.assertEqual(result["other_sites_same_zone"], [])
        self.assertEqual(result["other_sites_same_directory"], [])
        self.assertEqual(result["cache_directory"], "/www/server/fastcgi_cache")
        self.assertEqual(result["purge_scope"], "Unknown")
        self.assertFalse(result["purge_supported"])

    def test_internal_native_peer_directory_list_reports_distinct_and_unresolved(self):
        global_file=self.global_cache_fixture()
        original=global_file.read_text()
        php=self.nginx/'enable-php-81-wpfastcgi.conf'
        php.write_text(self.native_snippet.replace(
            'fastcgi_cache WORDPRESS;', 'fastcgi_cache ALTERNATE;'
        ).replace('php-cgi-85.sock','php-cgi-81.sock'))
        self.make_vhost('shop.test','enable-php-81-wpfastcgi.conf')

        def inspect_internal():
            return audit.inspect_site_fastcgi_cache(
                self.panel,4,'wp.test',vhost_root=str(self.vhost),
                nginx_root=str(self.nginx),
                rewrite_root=str(self.rewrites),include_physical_peers=True)

        global_file.write_text(original+
            'fastcgi_cache_path /www/server/another-cache '
            'keys_zone=ALTERNATE:50m;\n')
        plain=self.inspect()
        self.assertNotIn('physical_peer_cache_paths',plain)
        separate=inspect_internal()
        self.assertEqual(separate['state'],'Source Observed',separate)
        self.assertEqual(separate['purge_scope'],'Unknown')
        self.assertEqual(separate['physical_peer_cache_paths'],[
            {'id':6,'directory':'/www/server/another-cache'}])

        global_file.write_text(original)
        unresolved=inspect_internal()
        self.assertEqual(unresolved['state'],'Source Observed',unresolved)
        self.assertEqual(unresolved['physical_peer_cache_paths'],[
            {'id':6,'directory':None}])

    def test_double_leading_slash_selected_cache_directory_needs_review(self):
        global_file = self.global_cache_fixture()
        global_file.write_text(global_file.read_text().replace(
            "fastcgi_cache_path /www/server/fastcgi_cache ",
            "fastcgi_cache_path //www/server/fastcgi_cache "))
        result = self.inspect()
        self.assertEqual(result["state"], "Needs Review", result)
        self.assertIsNone(result["source_sha256"])
        self.assertIsNone(result["cache_directory"])
        self.assertEqual(result["purge_scope"], "Unknown")
        self.assertFalse(result["purge_supported"])

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

    def test_quoted_security_relevant_header_and_method_arguments(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        php.write_text(self.native_snippet.replace(
            " fastcgi_cache_valid 200 10m;",
            " fastcgi_ignore_headers \"Set-Cookie\" 'CACHE-CONTROL';\n"
            ' fastcgi_cache_methods GET HEAD "post";\n'
            " fastcgi_cache_valid 200 10m;"
        ))
        result = self.inspect()
        self.assertEqual(result["state"], "Source Observed", result)
        self.assertEqual(result["ignore_headers"], ["Cache-Control", "Set-Cookie"])
        self.assertIn("RESPONSE_CACHE_HEADER_IGNORED", result["findings"])
        self.assertIn("NON_GET_CACHE_METHOD", result["findings"])

    def test_ambiguous_quotes_and_escapes_never_suppress_security_findings(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        for arguments in ('"Set-Cookie', 'Set-Cookie\\\\', '"Set-Cookie Cache-Control"',
                          'Set-Cookie"Cache-Control"'):
            with self.subTest(arguments=arguments):
                php.write_text(self.native_snippet.replace(
                    " fastcgi_cache_valid 200 10m;",
                    " fastcgi_ignore_headers " + arguments + ";\n"
                    " fastcgi_cache_valid 200 10m;"
                ))
                result = self.inspect()
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertIsNone(result["source_sha256"])

    def test_conflicting_keys_in_different_sources_are_not_aggregated(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        vhost = self.vhost / "wp.test.conf"
        for parent, child in (("$scheme$host$request_uri", "$scheme$request_uri"),
                              ("$scheme$request_uri", "$scheme$host$request_uri")):
            with self.subTest(parent=parent):
                vhost.write_text(
                    "server {\n server_name wp.test;\n"
                    ' fastcgi_cache_key "' + parent + '";\n'
                    " include enable-php-85-wpfastcgi.conf;\n}\n")
                php.write_text(self.native_snippet.replace(
                    "$scheme$request_method$host$request_uri", child))
                result = self.inspect()
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertFalse(result["host_key_variable_seen"])
                self.assertIsNone(result["source_sha256"])

    def test_unmodelled_cache_controls_and_parameter_routing_require_review(self):
        php = self.nginx / "enable-php-85-wpfastcgi.conf"
        for directive in ("fastcgi_cache_use_stale updating;",
                          "fastcgi_cache_background_update on;",
                          "fastcgi_cache_revalidate on;",
                          "fastcgi_cache_lock on;"):
            with self.subTest(directive=directive):
                php.write_text(self.native_snippet.replace(
                    " fastcgi_cache_valid 200 10m;",
                    " " + directive + "\n fastcgi_cache_valid 200 10m;"))
                self.assertEqual(self.inspect()["state"], "Needs Review")
        php.write_text(self.native_snippet)
        params = self.nginx / "fastcgi.conf"
        params.write_text("location /private { return 200; }\n")
        self.assertEqual(self.inspect()["state"], "Needs Review")

    def test_platform_identity_change_during_scan_is_not_observed(self):
        initial = self.inspect()
        self.assertEqual(initial["state"], "Source Observed")
        original = audit._site_source
        called = False
        def mutate_platform(*args, **kwargs):
            nonlocal called
            value = original(*args, **kwargs)
            if not called:
                self.panel.version = "9.0.0"
                called = True
            return value
        with patch.object(audit, "_site_source", side_effect=mutate_platform):
            result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["source_sha256"])

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
        self.assertIsNone(got["php_version"])
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
