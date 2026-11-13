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
