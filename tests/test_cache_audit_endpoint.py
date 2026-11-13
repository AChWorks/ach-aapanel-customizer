"""Native full-admin site-bound FastCGI cache text-only inspection endpoint."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_cache_audit as audit
import ach_customizer_main as endpoint


class NativeCacheAuditEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ach-cache-endpoint-")
        self.addCleanup(self.temp.cleanup)
        state = patch.object(endpoint, "_STATE_DIR", self.temp.name)
        state.start()
        self.addCleanup(state.stop)
        self.plugin = endpoint.ach_customizer_main()
        self.reads = 0

    @staticmethod
    def snapshot():
        return json.dumps([7, "site.test", "/www/site.test", "1",
                           [["site.test", 80]]], separators=(",", ":"))

    @staticmethod
    def flask(uid=1, method="POST", temporary=False):
        module = types.ModuleType("flask")
        module.has_request_context = lambda: True
        module.request = types.SimpleNamespace(method=method)
        module.session = {"uid": uid, "login": True}
        if temporary:
            module.session["tmp_login_id"] = "temporary"
        return module

    def native(self, *, drift=None):
        public = types.ModuleType("public")
        outer = self
        class Site:
            def where(self, expr, args):
                assert expr == "id=?" and args == (7,)
                return self
            def field(self, cols):
                assert cols == "id,name,path,status"
                return self
            def find(self):
                outer.reads += 1
                return {
                    "id": 7, "name": "site.test",
                    "path": "/changed" if drift == "path" and outer.reads == 3 else "/www/site.test",
                    "status": "1",
                }
        class Domain:
            def where(self, expr, args):
                assert expr == "pid IN (?)" and args == (7,)
                return self
            def order(self, val):
                assert val == "pid asc, id asc"
                return self
            def limit(self, val):
                assert val == "0,1001"
                return self
            def field(self, val):
                assert val == "id,pid,name,port"
                return self
            def select(self):
                return [{
                    "id": 41, "pid": 7, "port": 80,
                    "name": "other.test" if drift == "domain" and outer.reads == 3
                            else "site.test",
                }]
        public.M = lambda name: Site() if name == "sites" else Domain()
        return public

    @staticmethod
    def sample(state="Source Observed"):
        return {
            "schema": 1, "state": state, "site_id": 7, "site_key": "site.test",
            "read_only": True, "cache_safe_verified": False,
            "runtime_verified": False, "fix_supported": False, "purge_supported": False,
            "zone_state": "Direct Zone", "cache_zone": "WORDPRESS",
            "global_zone_directly_declared": True,
            "aaPanel_global_include_observed": False,
            "cache_directory": "/www/server/fastcgi_cache",
            "global_ignore_headers": [], "purge_scope": "No Registered Directory Peer",
            "other_sites_same_directory": [],
            "bypass_directive_seen": True, "no_cache_directive_seen": True,
            "host_key_variable_seen": True, "purge_directive_seen": True,
            "ignore_headers": [], "findings": ["PRIVATE_ROUTE_RUNTIME_TEST_REQUIRED"],
            "other_sites_same_zone": [], "unresolved_other_sites": 0,
            "inspected_sites": 1, "source_sha256": "a" * 64,
            "reason": "", "note": audit.NOTE,
        }

    def args(self):
        return {
            "site_id": "7", "expected_site_key": "site.test",
            "expected_site_snapshot": self.snapshot(),
            "site_key": "arbitrary.test", "config_root": "/etc/shadow",
            "vhost_root": "/tmp/evil", "url": "http://attacker.test",
        }

    def test_full_admin_uses_verified_native_record_only_and_logs_warning(self):
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         return_value=self.sample()) as inspect:
            response = self.plugin.inspect_fastcgi_cache(self.args())
        self.assertTrue(response["status"], response)
        self.assertTrue(response["read_only"])
        self.assertFalse(response["fix_supported"])
        self.assertFalse(response["cache_safe_verified"])
        self.assertEqual(response["site_id"], 7)
        self.assertRegex(response["request_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(inspect.call_count, 1)
        self.assertEqual(inspect.call_args.args[1:], (7, "site.test"))
        self.assertEqual(inspect.call_args.kwargs, {})
        self.assertEqual(self.reads, 3)
        from ach_customizer_activity import read_activity
        rows = read_activity(self.temp.name, module="websites", limit=10)
        self.assertTrue(any(x["action"] == "inspect_fastcgi_cache" and
                            x["level"] == "WARNING" for x in rows), rows)

    def test_helper_inspection_uses_native_document_root_not_caller_path(self):
        from ach_customizer_cache_helper import inspect_nginx_helper_files
        expected = inspect_nginx_helper_files("/missing/native/site")
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         return_value=self.sample()), \
            patch("ach_customizer_cache_helper.inspect_nginx_helper_files",
                  return_value=expected) as scan:
            response = self.plugin.inspect_fastcgi_cache(self.args())
        self.assertTrue(response["status"], response)
        self.assertEqual(response["nginx_helper"], expected)
        scan.assert_called_once_with("/www/site.test")

    def test_nonprimary_get_or_temporary_identity_denied_before_read(self):
        for access in (self.flask(uid=2), self.flask(method="GET"),
                       self.flask(temporary=True)):
            with self.subTest(access=access.session), patch.dict(sys.modules, {
                "public": self.native(), "flask": access
            }), patch.object(audit, "inspect_site_fastcgi_cache",
                             side_effect=AssertionError("unauthorized")) as inspect:
                result = self.plugin.inspect_fastcgi_cache(self.args())
            self.assertFalse(result["status"])
            self.assertEqual(result["stage"], "cache_authorization")
            inspect.assert_not_called()
        self.assertEqual(self.reads, 0)

    def test_bogus_or_oversized_selection_never_reads_cache_sources(self):
        for snapshot in ("", "invalid", "[]", '{"id":7}', "x" * 110001,
                         json.dumps([7, "site.test", "/www/site.test", "1",
                                     [["site.test", "80"]]])):
            self.reads = 0
            with self.subTest(size=len(snapshot)), patch.dict(sys.modules, {
                    "public": self.native(), "flask": self.flask()
            }), patch.object(audit, "inspect_site_fastcgi_cache",
                             side_effect=AssertionError("untrusted selection")) as spy:
                args = self.args()
                args["expected_site_snapshot"] = snapshot
                reply = self.plugin.inspect_fastcgi_cache(args)
            self.assertFalse(reply["status"], reply)
            self.assertEqual(reply["stage"], "cache_inspection")
            spy.assert_not_called()
            self.assertEqual(self.reads, 0)

    def test_stale_site_snapshot_refuses_source_before_read(self):
        for change in ("precondition", "path", "domain"):
            self.reads = 0
            args = self.args()
            if change == "precondition":
                args["expected_site_key"] = "forged.test"
            with patch.dict(sys.modules, {
                "public": self.native(drift=None if change == "precondition" else change),
                "flask": self.flask()
            }), patch.object(audit, "inspect_site_fastcgi_cache",
                             return_value=self.sample()) as spy:
                reply = self.plugin.inspect_fastcgi_cache(args)
            self.assertFalse(reply["status"], reply)
            self.assertEqual(reply["stage"], "cache_inspection")
            if change == "precondition":
                spy.assert_not_called()
            else:
                spy.assert_called_once()
            self.assertNotIn("other.test", str(reply))

    def test_exception_details_not_exposed_and_plugin_log_preserved(self):
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         side_effect=OSError("secret operator path")):
            response = self.plugin.inspect_fastcgi_cache(self.args())
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "cache_inspection")
        self.assertNotIn("secret operator path", str(response))
        self.assertIn("Operation ID", response["msg"])
        from ach_customizer_activity import read_activity
        rows = read_activity(self.temp.name, module="websites", limit=10)
        self.assertTrue(any(
            x["action"] == "cache_inspection" and x["level"] == "ERROR"
            and x["error_class"] == "OSError" for x in rows
        ))

    def test_old_cached_panel_module_denied_with_actionable_failure(self):
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask(),
                "ach_customizer_cache_audit": None
        }):
            response = self.plugin.inspect_fastcgi_cache(self.args())
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "cache_inspection")
        self.assertIn("restart aaPanel", response["msg"])
        self.assertEqual(self.reads, 0)
        self.assertTrue(self.plugin.get_overview({})["status"])


    def test_private_probe_uses_current_native_identity_and_rechecks_source(self):
        from ach_customizer_cache_runtime import probe_private_cache
        result = {
            "schema": 1, "state": "Observed BYPASS",
            "site_id": 7, "site_key": "site.test",
            "private_probe_bypass_observed": True,
        }
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         return_value=self.sample()) as audit_call, \
             patch("ach_customizer_cache_runtime.probe_private_cache",
                   return_value=result) as probe:
            got = self.plugin.probe_private_cache(self.args())
        self.assertTrue(got["status"], got)
        self.assertEqual(got["state"], "Observed BYPASS")
        self.assertEqual(audit_call.call_count, 2)
        self.assertEqual(audit_call.call_args.args[1:], (7, "site.test"))
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(probe.call_args.args[0]["name"], "site.test")
        self.assertEqual(probe.call_args.args[1]["source_sha256"], "a" * 64)
        self.assertEqual(self.reads, 3)

    def test_woo_profile_uses_native_authorization_and_snapshot(self):
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         return_value=self.sample()) as inspect, \
             patch("ach_customizer_cache_runtime.probe_private_cache",
                   return_value={"state": "Observed BYPASS"}) as probe:
            got = self.plugin.probe_private_cache({
                **self.args(), "probe_profile": "woocommerce_default"})
        self.assertTrue(got["status"], got)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(probe.call_args.kwargs["profile"], "woocommerce_default")
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(self.reads, 3)

    def test_woo_source_drift_revokes_both_success_claims(self):
        result = {"schema": 2, "state": "Observed BYPASS",
                  "private_probe_bypass_observed": True,
                  "default_guest_bypass_observed": True,
                  "profile": "woocommerce_default"}
        other = {**self.sample(), "source_sha256": "b"*64}
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         side_effect=[self.sample(), other]), \
             patch("ach_customizer_cache_runtime.probe_private_cache",
                   return_value=result):
            got = self.plugin.probe_private_cache({
                **self.args(), "probe_profile": "woocommerce_default"})
        self.assertTrue(got["status"], got)
        self.assertEqual(got["state"], "Needs Review")
        self.assertFalse(got["private_probe_bypass_observed"])
        self.assertFalse(got["default_guest_bypass_observed"])
        self.assertEqual(self.reads, 3)

    def test_woo_profile_refuses_arbitrary_profile_before_native_read(self):
        for profile in (None, [], {}, "https://invalid.example", "guest"):
            self.reads = 0
            with patch.dict(sys.modules, {
                    "public": self.native(), "flask": self.flask()
            }), patch("ach_customizer_cache_runtime.probe_private_cache") as probe:
                got = self.plugin.probe_private_cache({
                    **self.args(), "probe_profile": profile})
            self.assertFalse(got["status"])
            self.assertEqual(got["stage"], "cache_runtime_probe")
            self.assertEqual(self.reads, 0)
            probe.assert_not_called()

    def test_private_probe_source_changed_cannot_claim_success(self):
        from ach_customizer_cache_runtime import probe_private_cache
        result = {"schema": 1, "state": "Observed BYPASS",
                  "private_probe_bypass_observed": True}
        other = {**self.sample(), "source_sha256": "b" * 64}
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         side_effect=[self.sample(), other]), \
             patch("ach_customizer_cache_runtime.probe_private_cache",
                   return_value=result):
            got = self.plugin.probe_private_cache(self.args())
        self.assertTrue(got["status"], got)
        self.assertEqual(got["state"], "Needs Review")
        self.assertFalse(got["private_probe_bypass_observed"])
        self.assertIn("changed", got["reason"])

    def test_private_probe_rejects_nonprimary_or_get_without_any_http(self):
        with patch.dict(sys.modules, {
                "public": self.native(), "flask": self.flask(uid=2)
        }), patch("ach_customizer_cache_runtime.probe_private_cache") as probe:
            got = self.plugin.probe_private_cache(self.args())
        self.assertFalse(got["status"])
        self.assertEqual(got["stage"], "cache_authorization")
        probe.assert_not_called()
        self.assertEqual(self.reads, 0)

    def test_private_probe_changed_native_site_rejects_racy_result(self):
        with patch.dict(sys.modules, {
                "public": self.native(drift="domain"), "flask": self.flask()
        }), patch.object(audit, "inspect_site_fastcgi_cache",
                         return_value=self.sample()), \
             patch("ach_customizer_cache_runtime.probe_private_cache",
                   return_value={"state": "Observed BYPASS"}):
            got = self.plugin.probe_private_cache(self.args())
        self.assertFalse(got["status"])
        self.assertEqual(got["stage"], "cache_runtime_probe")
        self.assertEqual(self.reads, 3)

if __name__ == "__main__":
    unittest.main()
