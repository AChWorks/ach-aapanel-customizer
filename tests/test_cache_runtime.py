"""Synthetic native WP FastCGI HEAD probe: no DNS, user credentials or writes."""
from pathlib import Path
from unittest.mock import patch
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(ROOT))
import ach_customizer_cache_runtime as runtime
from ach_customizer_monitor import MonitorInputError


class Response:
    def __init__(self, status, value):
        self.status = status
        self.value = value
    def getheader(self, key, default=""):
        if isinstance(self.value, dict):
            return self.value.get(key, default)
        return self.value if key == "X-Cache" else default
    def read(self, size):
        assert size == 0


class Connection:
    def __init__(self, response, calls):
        self.response, self.calls = response, calls
        self.closed = False
    def request(self, method, path, headers):
        self.calls.append((method, path, headers))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True


class RuntimePrivateCacheTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-cache-runtime-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.name = "qa-wp.example.test"
        self.site = {
            "id": 9, "name": self.name, "status": "1",
            "bound_domains": [{"name": self.name, "port": 80}],
        }
        self.audit = {
            "site_id": 9, "site_key": self.name,
            "state": "Source Observed", "zone_state": "Direct Zone",
            "php_version": "85",
        }
        self.vhost = self.root / (self.name + ".conf")
        self.vhost.write_text(
            "server {\n include enable-php-85-wpfastcgi.conf;\n}\n")
        self.calls = []
        self.connections = []
        self.responses = [Response(200, "BYPASS From " + self.name) for _ in range(4)]

    def factory(self):
        connection = Connection(self.responses[len(self.connections)], self.calls)
        self.connections.append(connection)
        return connection

    def observe(self):
        return runtime.probe_private_cache(
            self.site, self.audit,
            vhost_root=str(self.root), connection_factory=self.factory)

    def test_bounded_bypass_observation_keeps_safety_and_purge_unverified(self):
        got = self.observe()
        self.assertEqual(got["state"], "Observed BYPASS")
        self.assertTrue(got["private_probe_bypass_observed"])
        self.assertFalse(got["cache_safe_verified"])
        self.assertFalse(got["purge_supported"])
        self.assertFalse(got["runtime_verified"])
        self.assertTrue(got["read_only"])
        self.assertEqual([x["path"] for x in got["probes"]],
                         ["/", "/", "/wp-json/", "/wp-json/"])
        self.assertEqual([x["scenario"] for x in got["probes"]],
                         ["authorization", "cookie", "authorization", "cookie"])
        self.assertEqual(len(self.calls), 4)
        for method, path, headers in self.calls:
            self.assertEqual(method, "HEAD")
            self.assertEqual(headers["Host"], self.name)
            self.assertIn(path, ("/", "/wp-json/"))
            self.assertEqual(sum(k in headers for k in ("Cookie", "Authorization")), 1)
            self.assertNotIn("Authorization", headers.get("Cookie", ""))
        self.assertTrue(all(c.closed for c in self.connections))

    def test_any_cached_synthetic_identity_request_fails_positive(self):
        self.responses[2] = Response(200, "HIT From " + self.name)
        got = self.observe()
        self.assertEqual(got["state"], "Needs Review")
        self.assertFalse(got["private_probe_bypass_observed"])
        self.assertEqual(got["probes"][2]["cache"], "HIT")
        self.assertEqual(len(self.calls), 4)

    def test_unexpected_host_or_missing_cache_header_is_not_evidence(self):
        self.responses[0] = Response(200, "BYPASS From another.test")
        got = self.observe()
        self.assertEqual(got["state"], "Unavailable")
        self.assertFalse(got["private_probe_bypass_observed"])
        self.assertEqual(got["probes"][0]["cache"], "Not Observed")

    def test_redirects_are_not_accepted_even_with_bypass_header(self):
        self.responses[1] = Response(301, "BYPASS From " + self.name)
        got = self.observe()
        self.assertEqual(got["state"], "Unavailable")
        self.assertFalse(got["private_probe_bypass_observed"])

    def test_mismatched_or_uninspected_source_cannot_touch_network(self):
        for source in (
            {**self.audit, "state": "Partial"},
            {**self.audit, "site_key": "other.test"},
            {**self.audit, "zone_state": "No Direct Directive"},
        ):
            with self.subTest(source=source):
                self.audit = source
                got = self.observe()
                self.assertEqual(got["state"], "Needs Review")
                self.assertFalse(self.calls)

    def test_stock_php_or_multiple_includes_is_unsupported(self):
        for variant in (
            "include enable-php-85.conf;",
            "include enable-php-85-wpfastcgi.conf;\n"
            "include enable-php-81-wpfastcgi.conf;",
        ):
            self.vhost.write_text("server {\n" + variant + "\n}\n")
            with self.subTest(variant=variant):
                got = self.observe()
                self.assertEqual(got["state"], "Unsupported")
                self.assertFalse(self.calls)

    def managed(self, native_handler="stock"):
        # The real source audit sets this only for a twice-scanned, exact
        # journal/byte-owned live site Cache include (phase=applied).
        self.audit.update(
            managed_cache_handler=native_handler, cache_zone="ACHFC_9",
            cache_directory="/www/server/ach-customizer-fastcgi/site-9",
        )
        extension = self.root / "extension" / self.name / "*.conf"
        suffix = "-wpfastcgi" if native_handler == "wpfastcgi" else ""
        self.vhost.write_text(
            "server {\n include " + str(extension) + ";\n"
            " include enable-php-85" + suffix + ".conf;\n}\n")
        self.responses = [Response(200, {
            "X-ACh-Cache": "BYPASS", "X-ACh-Cache-Site": "9",
        }) for _ in range(4)]
        self.connections.clear()
        self.calls.clear()

    def test_applied_managed_stock_cache_observes_all_private_head_bypass(self):
        self.managed()
        got = self.observe()
        self.assertEqual(got["state"], "Observed BYPASS")
        self.assertTrue(got["private_probe_bypass_observed"])
        self.assertFalse(got["runtime_verified"])
        self.assertFalse(got["cache_safe_verified"])
        self.assertFalse(got["purge_supported"])
        self.assertEqual(len(got["probes"]), 4)
        self.assertTrue(all(x["cache"] == "BYPASS" for x in got["probes"]))
        self.assertTrue(all(c.closed for c in self.connections))

    def test_managed_stock_cached_identity_request_is_not_accepted(self):
        self.managed()
        self.responses[1] = Response(200, {
            "X-ACh-Cache": "HIT", "X-ACh-Cache-Site": "9",
        })
        got = self.observe()
        self.assertEqual(got["state"], "Needs Review")
        self.assertEqual(got["probes"][1]["cache"], "HIT")
        self.assertFalse(got["private_probe_bypass_observed"])

    def test_managed_ignores_native_or_other_site_cache_markers(self):
        self.managed()
        self.responses[0] = Response(200, {
            "X-ACh-Cache": "BYPASS", "X-ACh-Cache-Site": "other",
            "X-Cache": "BYPASS From " + self.name,
        })
        got = self.observe()
        self.assertEqual(got["state"], "Unavailable")
        self.assertEqual(got["probes"][0]["cache"], "Not Observed")
        self.assertFalse(got["private_probe_bypass_observed"])

    def test_managed_wordpress_handler_uses_owned_cache_marker(self):
        self.managed("wpfastcgi")
        self.assertEqual(self.observe()["state"], "Observed BYPASS")

    def test_managed_probe_refuses_unapplied_or_drifted_source_before_http(self):
        for change in (
            {"managed_cache_handler": "pending"},
            {"managed_cache_handler": "forged"},
            {"cache_zone": "WORDPRESS"},
            {"cache_directory": "/www/server/fastcgi_cache"},
        ):
            with self.subTest(change=change):
                self.managed()
                self.audit.update(change)
                got = self.observe()
                self.assertEqual(got["state"], "Needs Review")
                self.assertFalse(self.calls)

    def test_managed_probe_refuses_changed_extension_precedence(self):
        self.managed()
        correct = self.vhost.read_text()
        for text in (
            correct.replace("include enable-php-85.conf;", "include enable-php-81.conf;"),
            correct.replace(" include enable-php-85.conf;", ""),
            correct.replace("server {\n", "server {\n location ~ \\.php$ { return 200; }\n"),
            correct.replace("server {\n", "server {\n include enable-php-85.conf;\n"),
        ):
            with self.subTest(vhost=text):
                self.calls.clear()
                self.connections.clear()
                self.vhost.write_text(text)
                got = self.observe()
                self.assertEqual(got["state"], "Needs Review")
                self.assertFalse(self.calls)
                self.vhost.write_text(correct)

    def woo(self):
        self.responses = [
            Response(200, "BYPASS From " + self.name) for _ in range(9)
        ]
        return runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=self.factory)

    def test_default_woo_guest_routes_9_of_9_without_credentials(self):
        got = self.woo()
        self.assertEqual(got["schema"], 2)
        self.assertEqual(got["profile"], "woocommerce_default")
        self.assertEqual(got["state"], "Observed BYPASS")
        self.assertTrue(got["default_guest_bypass_observed"])
        self.assertTrue(got["private_probe_bypass_observed"])
        self.assertFalse(got["runtime_verified"])
        self.assertFalse(got["cache_safe_verified"])
        self.assertFalse(got["purge_supported"])
        self.assertEqual(len(self.calls), 9)
        self.assertEqual([x["route"] for x in got["probes"][4:]],
                         ["cart", "checkout", "account", "store-cart", "store-checkout"])
        self.assertEqual([x["path"] for x in got["probes"][4:]],
                         ["/cart/", "/checkout/", "/my-account/",
                          "/wp-json/wc/store/v1/cart/",
                          "/wp-json/wc/store/v1/checkout/"])
        for method, path, headers in self.calls[4:]:
            self.assertEqual(method, "HEAD")
            self.assertEqual(headers, {"Host": self.name})
        self.assertTrue(all(x["scenario"] == "anonymous" for x in got["probes"][4:]))
        self.assertIn("responding VHost", got["note"])
        self.assertIn("Page slugs can be customized", got["note"])
        self.assertTrue(all(c.closed for c in self.connections))

    def test_woo_guest_hit_is_a_visible_review_not_a_false_success(self):
        self.responses = [
            Response(200, "BYPASS From " + self.name) for _ in range(9)
        ]
        self.responses[6] = Response(200, "HIT From " + self.name)
        got = runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=self.factory)
        self.assertEqual(got["state"], "Needs Review")
        self.assertIn("anonymous WooCommerce", got["reason"])
        self.assertEqual(got["probes"][6]["route"], "account")
        self.assertFalse(got["default_guest_bypass_observed"])
        self.assertFalse(got["private_probe_bypass_observed"])
        self.assertEqual(len(self.calls), 9)

    def test_woo_default_custom_slug_redirect_remains_unavailable(self):
        self.responses = [
            Response(200, "BYPASS From " + self.name) for _ in range(9)
        ]
        self.responses[4] = Response(301, "BYPASS From " + self.name)
        got = runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=self.factory)
        self.assertEqual(got["state"], "Unavailable")
        self.assertIn("customized slugs", got["reason"])
        self.assertFalse(got["default_guest_bypass_observed"])
        self.assertEqual(got["probes"][4]["http_status"], 301)

    def test_woo_missing_cache_header_cannot_verify_guest_routes(self):
        self.responses = [
            Response(200, "BYPASS From " + self.name) for _ in range(9)
        ]
        self.responses[7] = Response(200, "BYPASS From other.test")
        got = runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=self.factory)
        self.assertEqual(got["state"], "Unavailable")
        self.assertEqual(got["probes"][7]["cache"], "Not Observed")
        self.assertFalse(got["default_guest_bypass_observed"])

    def test_woo_profile_is_fixed_and_source_guards_precede_transport(self):
        for profile in (None, 1, "", "https://outside.test", {}, [], "WooCommerce"):
            with self.subTest(profile=profile):
                with self.assertRaises(MonitorInputError):
                    runtime.probe_private_cache(
                        self.site, self.audit, profile=profile,
                        vhost_root=str(self.root), connection_factory=self.factory)
        self.assertEqual(self.calls, [])
        self.audit["state"] = "Partial"
        got = self.woo()
        self.assertEqual(got["state"], "Needs Review")
        self.assertEqual(got["probes"], [])
        self.assertFalse(got["default_guest_bypass_observed"])
        self.assertEqual(self.calls, [])

    def test_woo_transport_failure_no_partial_verification(self):
        self.responses = [
            Response(200, "BYPASS From " + self.name) for _ in range(9)
        ]
        class Failing(Connection):
            def request(self, method, path, headers):
                if path == "/my-account/":
                    raise ConnectionError("private runtime detail")
                super().request(method, path, headers)
        def factory():
            conn = Failing(self.responses[len(self.connections)], self.calls)
            self.connections.append(conn)
            return conn
        got = runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=factory)
        self.assertEqual(got["state"], "Unavailable")
        self.assertEqual(len(got["probes"]), 6)
        self.assertFalse(got["default_guest_bypass_observed"])
        self.assertNotIn("private runtime detail", str(got))
        self.assertTrue(all(c.closed for c in self.connections))

    def test_partial_woo_hit_then_transport_failure_remains_needs_review(self):
        self.responses = [
            Response(200, "BYPASS From " + self.name) for _ in range(9)
        ]
        self.responses[4] = Response(200, "HIT From " + self.name)
        class Failing(Connection):
            def request(self, method, path, headers):
                if path == "/checkout/":
                    raise ConnectionError("late HTTP timeout")
                super().request(method, path, headers)
        def factory():
            conn = Failing(self.responses[len(self.connections)], self.calls)
            self.connections.append(conn)
            return conn
        got = runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=factory)
        self.assertEqual(got["state"], "Needs Review")
        self.assertEqual(len(got["probes"]), 5)
        self.assertFalse(got["default_guest_bypass_observed"])
        self.assertEqual(got["probes"][4]["cache"], "HIT")
        self.assertNotIn("late HTTP timeout", str(got))

    def test_woo_connect_error_does_not_leak_exception(self):
        def factory():
            raise OSError("private connector reason")
        got = runtime.probe_private_cache(
            self.site, self.audit, profile="woocommerce_default",
            vhost_root=str(self.root), connection_factory=factory)
        self.assertEqual(got["state"], "Unavailable")
        self.assertEqual(got["reason"], "Origin-local HTTP connection failed")
        self.assertEqual(got["probes"], [])
        self.assertNotIn("private connector reason", str(got))

    def test_unverified_site_identity_rejected_before_http(self):
        for site in (
            {**self.site, "name": "bad/host"},
            {**self.site, "status": "0"},
            {**self.site, "bound_domains": []},
            {**self.site, "id": True},
        ):
            with self.subTest(site=site):
                with self.assertRaises(MonitorInputError):
                    runtime.probe_private_cache(
                        site, self.audit, vhost_root=str(self.root),
                        connection_factory=self.factory)
                self.assertFalse(self.calls)

    def test_connection_error_is_bounded_and_not_leaked(self):
        def disconnected():
            class Broken:
                def request(self, *args, **kwargs): raise ConnectionError("private state")
                def close(self): pass
            return Broken()
        result = runtime.probe_private_cache(
            self.site, self.audit, vhost_root=str(self.root),
            connection_factory=disconnected)
        self.assertEqual(result["state"], "Unavailable")
        self.assertEqual(result["reason"], "Origin-local HTTP request failed")
        self.assertNotIn("private state", str(result))

    def test_no_outbound_host_or_caller_url_reaches_transport(self):
        with patch.object(runtime.http.client, "HTTPConnection",
                          side_effect=AssertionError("must use injected factory")):
            self.assertEqual(self.observe()["state"], "Observed BYPASS")
        self.assertEqual(self.calls[0][2]["Host"], self.name)


if __name__ == "__main__":
    unittest.main()
