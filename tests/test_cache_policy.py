"""Isolated reference-only FastCGI safety template and native endpoint tests."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_cache_policy as policy
import ach_customizer_cache_audit as audit
import ach_customizer_main as endpoint


class CachePolicyRenderTests(unittest.TestCase):
    def test_separate_site_zones_and_physical_paths(self):
        a = policy.generate_reference(7, "81")
        b = policy.generate_reference(8, "85")
        self.assertEqual(a["state"], "Reference Only")
        self.assertEqual(a["cache_zone"], "ACHFC_7")
        self.assertEqual(b["cache_zone"], "ACHFC_8")
        self.assertNotEqual(a["cache_directory"], b["cache_directory"])
        self.assertNotIn("/www/server/fastcgi_cache/", a["cache_directory"])
        self.assertTrue(a["read_only"])
        for name in ("installed","runtime_verified","safe_verified",
                     "apply_supported","purge_supported"):
            self.assertFalse(a[name])
        self.assertIn("php-cgi-81.sock", a["site_server_fragment"])
        self.assertIn("php-cgi-85.sock", b["site_server_fragment"])
        self.assertIn("fastcgi_cache ACHFC_7;", a["site_server_fragment"])
        self.assertNotIn("fastcgi_cache_purge", a["site_server_fragment"])
        self.assertNotIn("unlink", a["site_server_fragment"])
        self.assertIn("fastcgi_cache_bypass", a["site_server_fragment"])
        self.assertIn("fastcgi_no_cache", a["site_server_fragment"])
        self.assertIn("$http_authorization", a["site_server_fragment"])
        self.assertIn("$http_cookie", a["site_server_fragment"])
        self.assertIn("$upstream_http_set_cookie", a["site_server_fragment"])
        self.assertIn("$upstream_http_vary", a["site_server_fragment"])
        self.assertIn("no-store", a["global_http_fragment"])
        self.assertIn("private", a["global_http_fragment"])
        self.assertIn("max-age", a["global_http_fragment"])
        self.assertIn("wp-json", a["site_server_fragment"])
        self.assertIn("checkout", a["site_server_fragment"])
        self.assertEqual(a["proposal_sha256"],
                         policy.generate_reference(7, "81")["proposal_sha256"])
        self.assertNotEqual(a["proposal_sha256"], b["proposal_sha256"])
        self.assertNotIn("site-8", a["global_http_fragment"])
        self.assertNotIn("$achfc_8", a["global_http_fragment"])

    def test_invalid_inputs_rejected_without_config_interpolation(self):
        for bad in (None, "1", 0, -1, True, 2147483648, 1.0, "7; include /etc/passwd"):
            with self.subTest(bad=bad), self.assertRaises(policy.CachePolicyError):
                policy.generate_reference(bad, "85")
        for version in ("70", "80", "86", "810", None, 85, True, "85;\ninclude foo"):
            with self.subTest(version=version), self.assertRaises(policy.CachePolicyError):
                policy.generate_reference(7, version)
        for root in ("/tmp/../etc", "/tmp//cache", "tmp/cache", "/tmp/cache/",
                     "/tmp/./cache", "/tmp/cache/..", "/tmp/cache/.",
                     "/tmp/cache;include", "/tmp space", "/tmp/cache\n"):
            with self.subTest(root=root), self.assertRaises(policy.CachePolicyError):
                policy.generate_reference(7, "85", cache_root=root)

    def test_reference_in_qa_path_is_not_marked_activated(self):
        out = policy.generate_reference(9, "85", cache_root="/tmp/ach-cache-qa")
        self.assertEqual(out["cache_directory"], "/tmp/ach-cache-qa/site-9")
        self.assertIn("keys_zone=ACHFC_9:10m", out["global_http_fragment"])
        self.assertIn("$achfc_9_private_response", out["site_server_fragment"])
        self.assertTrue(out["proposal_sha256"])


class CachePolicyEndpointTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="ach-cache-preview-")
        self.addCleanup(t.cleanup)
        state = patch.object(endpoint, "_STATE_DIR", t.name)
        state.start()
        self.addCleanup(state.stop)
        self.plugin = endpoint.ach_customizer_main()
        self.site = {"id":7,"name":"site.test","path":"/www/site.test",
                     "status":"1","bound_domains":[{"name":"site.test","port":80}]}
        self.checks = 0

    @staticmethod
    def flask(uid=1, method="POST", temporary=False):
        module=types.ModuleType("flask")
        module.has_request_context=lambda: True
        module.request=types.SimpleNamespace(method=method)
        module.session={"login":True,"uid":uid}
        if temporary:
            module.session["tmp_login_id"]="temporary"
        return module

    def audit(self, state="Source Observed", zone="Direct Zone", version="85"):
        return {"state":state,"zone_state":zone,"php_version":version,
                "source_sha256":"a"*64}

    def current_site(self):
        self.checks+=1
        return dict(self.site)

    def run_preview(self, fake_audit, *, uid=1, method="POST", temporary=False):
        with patch.dict(sys.modules, {"flask":self.flask(uid,method,temporary)}), \
            patch.object(self.plugin, "_require_enabled"), \
            patch.object(self.plugin, "_selected_native_website",
                         return_value=(object(),dict(self.site),self.current_site)) as select, \
            patch.object(audit, "inspect_site_fastcgi_cache",
                         return_value=fake_audit) as inspect:
            out=self.plugin.preview_cache_safety({
                "site_id":"7","expected_site_key":"site.test",
                "expected_site_snapshot":"unmodified native bound snapshot",
                "fake_site":"evil.test","cache_root":"/etc"})
        return out,select,inspect

    def test_preview_is_strictly_read_only_and_bound_to_native_selection(self):
        r,select,inspect=self.run_preview(self.audit())
        self.assertTrue(r["status"],r)
        self.assertEqual(r["state"],"Reference Only")
        self.assertEqual(r["site_id"],7)
        self.assertEqual(r["site_key"],"site.test")
        self.assertEqual(r["source_sha256"],"a"*64)
        self.assertEqual(r["cache_directory"],
                         "/www/server/ach-customizer-fastcgi/site-7")
        self.assertFalse(r["apply_supported"])
        self.assertFalse(r["purge_supported"])
        self.assertEqual(select.call_count,1)
        self.assertEqual(inspect.call_args.args[1:],(7,"site.test"))
        self.assertEqual(inspect.call_count,1)
        self.assertEqual(self.checks,1)
        self.assertNotIn("evil.test",str(r))
        self.assertNotIn("/etc",r["global_http_fragment"])

    def test_partial_missing_direct_zone_or_unsupported_version_no_reference(self):
        for state,zone,version in (
            ("Partial","Direct Zone","85"),("Needs Review","Direct Zone","85"),
            ("Source Observed","No Direct Directive","85"),
            ("Source Observed","Direct Zone","86"),
            ("Source Observed","Direct Zone",None)
        ):
            with self.subTest(state=state,zone=zone,version=version):
                r,_,_=self.run_preview(self.audit(state,zone,version))
                self.assertTrue(r["status"],r)
                self.assertEqual(r["state"],"Needs Review")
                self.assertEqual(r["global_http_fragment"],"")
                self.assertEqual(r["site_server_fragment"],"")
                self.assertIsNone(r["proposal_sha256"])
                self.assertFalse(r["apply_supported"])

    def test_denies_nonprimary_get_temporary_before_native_or_source(self):
        for kw in ({"uid":2},{"method":"GET"},{"temporary":True}):
            self.checks=0
            r,select,inspect=self.run_preview(self.audit(),**kw)
            self.assertFalse(r["status"])
            self.assertEqual(r["stage"],"cache_authorization")
            self.assertEqual(self.checks,0)
            select.assert_not_called()
            inspect.assert_not_called()

    def test_native_identity_drift_fails_closed(self):
        def changed():
            value=dict(self.site)
            value["path"]="/other-site"
            return value
        with patch.dict(sys.modules,{"flask":self.flask()}), \
            patch.object(self.plugin, "_require_enabled"), \
            patch.object(self.plugin, "_selected_native_website",
                         return_value=(object(),dict(self.site),changed)), \
            patch.object(audit,"inspect_site_fastcgi_cache",
                         return_value=self.audit()):
            got=self.plugin.preview_cache_safety({"site_id":"7"})
        self.assertFalse(got["status"])
        self.assertEqual(got["stage"],"cache_reference_preview")
        self.assertNotIn("site_server_fragment",got)


if __name__=="__main__":
    unittest.main()
