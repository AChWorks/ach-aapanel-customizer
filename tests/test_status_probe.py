"""Explicit local-only HTTP/80 404 response evidence (never an Apply)."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import time
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PACKAGE))
import ach_customizer_status_probe as probe
import ach_customizer_main as backend
from ach_customizer_status_pages import render_page

class HTTPProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.site_root = self.root / "sites" / "demo.test"
        self.site_root.mkdir(parents=True)
        self.vhost_root = self.root / "panel" / "vhost" / "nginx"
        self.vhost_root.mkdir(parents=True)
        self.render = render_page("en", "404")
        self.page = self.site_root / "404.html"
        self.page.write_bytes(self.render["html"].encode("utf8"))
        self.vhost = self.vhost_root / "demo.test.conf"
        self.vhost.write_text(
            "server { listen 80; server_name demo.test;\n"
            "include " + str(self.vhost_root) + "/extension/demo.test/*.conf;\n}\n"
        )
        self.site = {"id": 7, "name": "demo.test",
                     "path": str(self.site_root), "status": "1",
                     "bound_domains": [{"name": "demo.test", "port": 80}]}
        self.status = 404
        self.payload = self.page.read_bytes()
        self.headers = {}
        self.seen = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.seen.append((self.path, self.headers.get("Host"),
                                   self.headers.get("Cookie"),
                                   self.headers.get("Authorization")))
                if getattr(owner, "on_request", None):
                    owner.on_request()
                slow = getattr(owner, "slow_response", None)
                if slow:
                    owner.emit_slow_response(self, slow)
                    return
                self.send_response(owner.status)
                for name, value in owner.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(owner.payload)))
                self.end_headers()
                self.wfile.write(owner.payload)

            def log_message(self, *args, **kwargs):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def emit_slow_response(self, handler, mode):
        """Send bytes frequently enough to dodge ordinary socket timeouts."""
        try:
            if mode == "headers":
                handler.wfile.write(b"HTTP/1.1 404 Not Found\r\nX-Padding: ")
                handler.wfile.flush()
                for _ in range(12):
                    handler.wfile.write(b"x")
                    handler.wfile.flush()
                    time.sleep(.12)
            else:
                handler.send_response(404)
                if mode == "body_length":
                    handler.send_header("Content-Length", str(len(self.payload)))
                elif mode == "body_chunked":
                    handler.send_header("Transfer-Encoding", "chunked")
                handler.end_headers()
                for _ in range(12):
                    if mode == "body_chunked":
                        handler.wfile.write(b"1\r\nx\r\n")
                    else:
                        handler.wfile.write(b"x")
                    handler.wfile.flush()
                    time.sleep(.12)
                if mode == "body_chunked":
                    handler.wfile.write(b"0\r\n\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def scan(self, **kwargs):
        return probe.probe_site_404(
            self.site, locale="en", rendered_sha256=self.render["rendered_sha256"],
            rendered_html=self.render["html"], vhost_root=str(self.vhost_root),
            connection_factory=lambda host, port, timeout: http.client.HTTPConnection(
                host, self.http.server_port, timeout=timeout),
            token_factory=lambda: "a" * 32, **kwargs)

    def test_real_loopback_http404_matches_bundled_page_and_site_file(self):
        result = self.scan()
        self.assertEqual(result["state"], "HTTP Match")
        self.assertEqual(result["http_status"], 404)
        self.assertTrue(result["http_404_observed"])
        self.assertTrue(result["body_matches_file"])
        self.assertTrue(result["body_matches_render"])
        self.assertEqual(result["body_sha256"], self.render["rendered_sha256"])
        self.assertEqual(self.seen, [("/ach-status-probe-" + "a" * 32,
                                      "demo.test", None, None)])
        self.assertFalse(result["apply_supported"])
        self.assertFalse(result["nginx_runtime_verified"])
        self.assertTrue(result["read_only"])
        self.assertEqual(result["adoption_preview"]["state"], "Needs Review")
        self.assertFalse(result["adoption_preview"]["apply_supported"])
        self.assertEqual(result["adoption_preview"]["route_source_state"], "None")

    def test_native_vhost_route_and_matching_http_are_still_not_apply_authorization(self):
        self.vhost.write_text("server { listen 80; server_name demo.test;\n"
                              "error_page 404 /404.html;\n}\n")
        result = self.scan()
        preview = result["adoption_preview"]
        self.assertEqual(result["state"], "HTTP Match")
        self.assertEqual(preview["state"], "Matches Preview")
        self.assertEqual(preview["route_source_state"], "Native VHost")
        self.assertEqual(preview["current_sha256"], result["body_sha256"])
        self.assertFalse(preview["requires_backup"])
        self.assertFalse(preview["ownership_verified"])
        self.assertFalse(preview["recovery_verified"])
        self.assertFalse(preview["apply_supported"])

    def test_redirect_and_soft_404_do_not_claim_matching_or_follow_redirect(self):
        for code in (200, 302, 500, 502):
            with self.subTest(code=code):
                self.status = code
                self.headers = {"Location": "http://example.com/"}
                result = self.scan()
                self.assertEqual(result["state"], "HTTP Mismatch")
                self.assertFalse(result["body_matches_file"])
                self.assertFalse(result["http_404_observed"])
                self.assertEqual(result["http_status"], code)
        self.assertEqual(len(self.seen), 4, "Never make a second redirected request")

    def test_404_with_different_body_proves_only_status_not_selected_page(self):
        self.payload = b"another server's 404\n"
        result = self.scan()
        self.assertEqual(result["state"], "HTTP Mismatch")
        self.assertTrue(result["http_404_observed"])
        self.assertFalse(result["body_matches_file"])
        self.assertFalse(result["body_matches_render"])
        self.assertNotEqual(result["body_sha256"], result["page_file_sha256"])

    def test_changed_site_content_matches_current_file_but_not_selected_render(self):
        other = b"<html>existing operator 404</html>"
        self.page.write_bytes(other)
        self.payload = other
        result = self.scan()
        self.assertEqual(result["state"], "HTTP Match")
        self.assertTrue(result["body_matches_file"])
        self.assertFalse(result["body_matches_render"])
        self.assertEqual(result["page_file_sha256"], hashlib.sha256(other).hexdigest())
        self.assertEqual(result["adoption_preview"]["state"], "Needs Review")
        self.vhost.write_text("server { listen 80; server_name demo.test;\n"
                              "error_page 404 /404.html;\n}\n")
        matched = self.scan()
        self.assertEqual(matched["adoption_preview"]["state"], "Backup Required")
        self.assertTrue(matched["adoption_preview"]["requires_backup"])
        self.assertFalse(matched["adoption_preview"]["ownership_verified"])
        self.assertFalse(matched["adoption_preview"]["recovery_verified"])
        self.assertFalse(matched["adoption_preview"]["apply_supported"])

    def test_oversized_or_encoded_response_never_claims_verified(self):
        self.payload = b"x" * (probe.MAX_BODY_BYTES + 1)
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["http_status"])
        self.assertIsNone(result["body_sha256"])
        self.payload = self.page.read_bytes()
        self.headers = {"Content-Encoding": "gzip"}
        self.assertEqual(self.scan()["state"], "Needs Review")

    def test_unbound_stopped_or_unsafe_host_never_contacts_any_service(self):
        for modifications in (
            {"status": "0"},
            {"bound_domains": []},
            {"bound_domains": [{"name":"demo.test","port":443}]},
            {"name":"invalid\r\nHost: evil.test"},
            {"name":"localhost"},
        ):
            with self.subTest(modifications=modifications):
                source = self.site.copy()
                self.site.update(modifications)
                with self.assertRaises(probe.StatusProbeError):
                    self.scan()
                self.site = source
        self.assertEqual(self.seen, [])

    def test_source_missing_or_symlinked_prevents_request(self):
        self.page.unlink()
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(self.seen, [])
        self.page.symlink_to(self.vhost)
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(self.seen, [])

    def test_total_deadline_covers_slow_headers_and_all_body_framing(self):
        for mode in ("headers", "body_length", "body_chunked", "body_no_length"):
            with self.subTest(mode=mode):
                self.slow_response = mode
                start = time.monotonic()
                result = self.scan(total_timeout=.55)
                elapsed = time.monotonic() - start
                self.assertLess(elapsed, 1.15, mode)
                self.assertEqual(result["state"], "Needs Review")
                self.assertIsNone(result["http_status"])
                self.assertFalse(result["body_matches_file"])
                self.assertIn("deadline", result["reason"])
        self.slow_response = None
        self.assertEqual(self.scan()["state"], "HTTP Match")

    def test_same_filename_extension_rewrites_cannot_keep_http_match(self):
        extension = self.vhost_root / "extension" / "demo.test"
        extension.mkdir(parents=True)
        fragment = extension / "operator.conf"
        fragment.write_text("error_page 404 /404.html;\n")
        for replacement in ("error_page 404 /different.html;\n",
                            "error_page 404 /404.html; # changed\n"):
            with self.subTest(replacement=replacement):
                original = fragment.read_text()
                self.on_request = lambda: fragment.write_text(replacement)
                result = self.scan()
                self.assertEqual(result["state"], "Needs Review")
                self.assertIsNone(result["http_status"])
                self.on_request = None
                fragment.write_text(original)

    def test_atomic_fragment_replacement_with_identical_bytes_changes_inode(self):
        extension = self.vhost_root / "extension" / "demo.test"
        extension.mkdir(parents=True)
        fragment = extension / "operator.conf"
        fragment.write_bytes(b"error_page 404 /404.html;\n")
        def replace():
            new = extension / "replacement.tmp"
            new.write_bytes(fragment.read_bytes())
            os.replace(new, fragment)
        self.on_request = replace
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["http_status"])

    def test_same_byte_page_and_vhost_atomic_replacement_discard_positive(self):
        for original in (self.page, self.vhost):
            with self.subTest(file=original.name):
                def replace():
                    replacement = original.with_suffix(".replacement")
                    replacement.write_bytes(original.read_bytes())
                    os.replace(replacement, original)
                self.on_request = replace
                result = self.scan()
                self.assertEqual(result["state"], "Needs Review")
                self.assertIsNone(result["http_status"])
                self.on_request = None

    def test_rebound_extension_directory_cannot_keep_positive(self):
        extension = self.vhost_root / "extension" / "demo.test"
        extension.mkdir(parents=True)
        fragment = extension / "operator.conf"
        fragment.write_bytes(b"error_page 404 /404.html;\n")
        def swap():
            extension.rename(extension.with_name("demo.previous"))
            extension.mkdir()
            (extension / "operator.conf").write_bytes(
                b"error_page 404 /404.html;\n")
        self.on_request = swap
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["http_status"])

    def test_source_rewritten_while_http_response_is_read_discards_proof(self):
        self.on_request = lambda: self.page.write_bytes(b"replaced mid-request")
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["http_status"])

    def test_vhost_changed_while_http_response_is_read_discards_proof(self):
        self.on_request = lambda: self.vhost.write_bytes(
            self.vhost.read_bytes() + b"\n#changed")
        result = self.scan()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["http_status"])


if __name__ == "__main__":
    unittest.main()


class NativeProbeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = patch.object(backend, "_STATE_DIR", self.tmp.name)
        self.st.start()
        self.addCleanup(self.st.stop)
        self.plugin = backend.ach_customizer_main()
        self.site = {"id": 7, "name": "demo.test", "path": "/www/demo.test", "status": "1"}
        self.seen = 0

    def public(self, mutate_at=None, engine="nginx"):
        result = types.ModuleType("public")
        outer = self
        class Query:
            def where(self, *args): return self
            def field(self, *args): return self
            def find(self):
                outer.seen += 1
                rec = dict(outer.site)
                if outer.seen == mutate_at:
                    rec["path"] = "/www/moved-elsewhere"
                return rec
        result.M = lambda name: Query() if name == "sites" else None
        result.get_webserver = lambda: engine
        return result

    def probe_args(self, **kwargs):
        import json
        data = {
            "site_id": "7", "template": "404", "locale": "en",
            "expected_site_key": "demo.test",
            "expected_site_snapshot": json.dumps([
                7, "demo.test", "/www/demo.test", "1", [["demo.test", 80]]
            ], separators=(",", ":"))
        }
        data.update(kwargs)
        return data

    @staticmethod
    def flask(uid=1, method="POST", temporary=False):
        module = types.ModuleType("flask")
        module.has_request_context = lambda: True
        module.request = types.SimpleNamespace(method=method)
        module.session = {"login": True, "uid": uid}
        if temporary:
            module.session["tmp_login_id"] = "temporary"
        return module

    @staticmethod
    def bound(_panel, items):
        for item in items:
            item["bound_domains"] = [{"name": item["name"], "port": 80}]
            item["canonical_domain_bound"] = True

    @staticmethod
    def observed(**overrides):
        record = {
            "schema": 1, "site_id": 7, "site_key": "demo.test", "template": "404",
            "locale": "en", "read_only": True, "apply_supported": False,
            "nginx_runtime_verified": False, "state": "HTTP Mismatch",
        }
        record.update(overrides)
        return record

    def test_stale_new_probe_helper_does_not_break_existing_plugin_endpoints(self):
        with patch.dict(sys.modules, {
            "ach_customizer_status_probe": None, "flask": self.flask()
        }):
            response = self.plugin.status_probe(self.probe_args())
            preview = self.plugin.status_preview({
                "site_id": "", "template": "404", "locale": "en"
            })
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "status_probe")
        self.assertIn("Restart aaPanel panel service", response["msg"])
        self.assertTrue(preview["status"], preview)
        self.assertEqual(self.seen, 0)

    def test_native_preferences_change_mid_probe_revokes_evidence(self):
        import copy
        state = backend.read_preferences(self.tmp.name)
        changed = copy.deepcopy(state)
        changed["revision"] = 1
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(backend, "_bound_domains_for_sites", side_effect=self.bound), \
             patch.object(backend, "read_preferences", side_effect=[state, changed]), \
             patch.object(probe, "probe_site_404", return_value=self.observed(state="HTTP Match")):
            response = self.plugin.status_probe(self.probe_args())
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "status_probe")
        self.assertIn("branding", response["msg"])

    def test_successful_probe_writes_bounded_plugin_activity_only(self):
        from ach_customizer_activity import read_activity
        with patch.dict(sys.modules, {
            "public": self.public(), "flask": self.flask()
        }), patch.object(backend, "_bound_domains_for_sites", side_effect=self.bound), \
             patch.object(probe, "probe_site_404",
                          return_value=self.observed(state="HTTP Match")):
            response = self.plugin.status_probe(self.probe_args())
        self.assertTrue(response["status"])
        self.assertTrue(response["activity_logged"])
        entries = read_activity(self.tmp.name, module="status_pages", limit=10)
        self.assertTrue(any(
            e["action"] == "status_probe" and e["module"] == "status_pages"
            and e["target"] == "site:7" and e["outcome"] == "HTTP Match"
            and e["operation_id"] == response["request_id"]
            for e in entries
        ))
        self.assertFalse(any("evil.example" in str(e) for e in entries))

    def test_stale_operator_site_selection_never_runs_network_probe(self):
        import copy
        base = copy.deepcopy(self.site)
        for description, changes, port in (
            ("rename", {"name": "new-site.test"}, 80),
            ("document root", {"path": "/www/reassigned-root"}, 80),
            ("stopped", {"status": "0"}, 80),
            ("site ID reassigned", {"id": 8}, 80),
            ("same-site domain rebinding", {}, 443),
        ):
            with self.subTest(change=description):
                self.seen = 0
                self.site = dict(base, **changes)
                def changed_domains(_panel, items):
                    for item in items:
                        item["bound_domains"] = [
                            {"name": item["name"], "port": port}]
                with patch.dict(sys.modules, {
                    "public": self.public(), "flask": self.flask()
                }), patch.object(backend, "_bound_domains_for_sites",
                                 side_effect=changed_domains), patch.object(
                    probe, "probe_site_404",
                    side_effect=AssertionError("HTTP request must not happen")
                ) as network:
                    response = self.plugin.status_probe(self.probe_args())
                self.assertFalse(response["status"])
                self.assertEqual(response["stage"], "status_probe")
                self.assertIn("refresh native website inventory", response["msg"])
                network.assert_not_called()
        self.site = base

    def test_missing_or_wrong_client_snapshot_never_runs_network_probe(self):
        for override in (
            {"expected_site_key": "different.test"},
            {"expected_site_snapshot": ""},
            {"expected_site_snapshot": "{}"},
            {"expected_site_snapshot": '[7,"demo.test","/www/other","1",[]]'},
        ):
            with self.subTest(override=override), patch.dict(sys.modules, {
                "public": self.public(), "flask": self.flask()
            }), patch.object(backend, "_bound_domains_for_sites",
                              side_effect=self.bound), patch.object(
                    probe, "probe_site_404",
                    side_effect=AssertionError("HTTP request must not happen")) as network:
                response = self.plugin.status_probe(self.probe_args(**override))
                self.assertFalse(response["status"])
                self.assertIn("refresh native website inventory", response["msg"])
                network.assert_not_called()

    def test_native_full_admin_post_uses_only_authoritative_site_and_domain(self):
        request = self.probe_args(
            host="evil.example", url="http://evil.example/private",
            port="54321", path="/etc/passwd")
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}),              patch.object(backend, "_bound_domains_for_sites", side_effect=self.bound),              patch.object(probe, "probe_site_404", return_value=self.observed()) as spy:
            response = self.plugin.status_probe(request)
        self.assertTrue(response["status"], response)
        self.assertEqual(self.seen, 3)
        spy.assert_called_once()
        self.assertEqual(spy.call_args.args[0]["path"], "/www/demo.test")
        self.assertEqual(spy.call_args.args[0]["bound_domains"],
                         [{"name": "demo.test", "port": 80}])
        self.assertEqual(set(spy.call_args.kwargs), {
            "delivery", "locale", "rendered_sha256", "rendered_html"
        })
        self.assertEqual(spy.call_args.kwargs["delivery"], "extension")
        self.assertEqual(response["state"], "HTTP Mismatch")
        self.assertEqual(response["selection_source"], "Global default")

    def test_nonprimary_get_and_temporary_sessions_cannot_probe(self):
        for flask in (self.flask(uid=2), self.flask(method="GET"),
                      self.flask(temporary=True)):
            with self.subTest(session=flask.session), patch.dict(
                sys.modules, {"public": self.public(), "flask": flask}
            ), patch.object(probe, "probe_site_404",
                            side_effect=AssertionError("must not probe")) as spy:
                response = self.plugin.status_probe(self.probe_args())
                self.assertFalse(response["status"])
                self.assertEqual(response["stage"], "status_authorization")
                spy.assert_not_called()
        self.assertEqual(self.seen, 0)

    def test_reject_non404_without_ever_contacting_site(self):
        with patch.dict(sys.modules, {
            "public": self.public(), "flask": self.flask()
        }), patch.object(probe, "probe_site_404",
                         side_effect=AssertionError("must not probe")) as spy:
            response = self.plugin.status_probe({
                "site_id": "7", "template": "502", "locale": "fa"
            })
            self.assertEqual(response["stage"], "status_probe")
            self.assertFalse(response["status"])
            spy.assert_not_called()
        self.assertEqual(self.seen, 1, "Site ID validated but no probe made")

    def test_wrong_web_engine_denies_network_probe(self):
        with patch.dict(sys.modules, {
            "public": self.public(engine="apache"), "flask": self.flask()
        }), patch.object(probe, "probe_site_404",
                         side_effect=AssertionError("must not probe")) as spy:
            response = self.plugin.status_probe(self.probe_args())
            self.assertFalse(response["status"])
            self.assertEqual(response["stage"], "status_probe")
            self.assertIn("Nginx", response["msg"])
            spy.assert_not_called()

    def test_site_change_during_http_probe_never_returns_positive_result(self):
        with patch.dict(sys.modules, {
            "public": self.public(mutate_at=3), "flask": self.flask()
        }), patch.object(backend, "_bound_domains_for_sites", side_effect=self.bound),              patch.object(probe, "probe_site_404",
                          return_value=self.observed(state="HTTP Match")):
            response = self.plugin.status_probe(self.probe_args())
            self.assertFalse(response["status"])
            self.assertIn("changed", response["msg"])
            self.assertEqual(response["stage"], "status_probe")
