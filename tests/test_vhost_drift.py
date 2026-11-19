"""Generated Nginx VHost vs native DB: read-only, bounded drift signals."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_vhost_drift as drift
import ach_customizer_main as main


class GeneratedVhostDriftTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-vhost-drift-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "alpha.test.conf"
        self.site = {
            "id": 7, "name": "alpha.test", "path": "/www/alpha",
            "status": "1", "bound_domains": [
                {"name": "alpha.test", "port": 80},
                {"name": "www.alpha.test", "port": 443},
            ],
        }
        self.panel = types.SimpleNamespace(
            get_webserver=lambda: "nginx", get_panel_version=lambda: "8.0.7")
        self.write(
            "server {\n listen 80; listen 443 ssl;\n"
            " server_name alpha.test www.alpha.test;\n"
            " root /www/alpha;\n"
            " # root /etc/secret;\n"
            r" location ~ \.php$ { fastcgi_pass unix:/tmp/php-cgi-85.sock; }" + "\n"
            "}\n"
        )

    def write(self, content):
        self.path.write_text(content, encoding="utf-8")

    def inspect(self):
        return drift.inspect_vhost_drift(self.panel, self.site,
                                         vhost_root=str(self.path.parent))

    def test_file_match_even_with_escaped_php_location_and_comments(self):
        expected = self.path.read_bytes()
        result = self.inspect()
        self.assertEqual(result["state"], "File Match", result)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["native_names"], ["alpha.test", "www.alpha.test"])
        self.assertEqual(result["vhost_names"], result["native_names"])
        self.assertEqual(result["listen_ports"], [80, 443])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["fix_supported"])
        self.assertTrue(result["read_only"])
        self.assertEqual(expected, self.path.read_bytes())

    def test_actual_aapanel_807_nested_location_and_if_shape(self):
        # Mirrors observed native guest source shape; no claims about nginx -T.
        self.write(
            "server\n{\n listen 80;\n server_name alpha.test www.alpha.test;\n"
            " root /www/alpha;\n include enable-php-85.conf;\n"
            " #SSL-START SSL related configuration\n"
            r" location ~ ^/(\.user.ini|\.htaccess|\.git|\.env)" + "\n { return 404; }\n"
            r" location ~ \.well-known{ allow all; }" + "\n"
            r' if ( $uri ~ "^/\.well-known/.*\.(php|jsp|py)$" ) {' + "\n"
            " return 403;\n }\n"
            r" location ~ .*\.(js|css)?$" + "\n { expires 12h; }\n"
            " access_log /var/log/nginx/alpha.test.log;\n}\n"
        )
        got = self.inspect()
        self.assertEqual(got["state"], "File Match", got)
        self.assertEqual(got["listen_ports"], [80])

    def test_detects_root_and_missing_extra_generated_names(self):
        self.write("server {\n server_name alpha.test stale.test;\n"
                   " root /www/another; listen 80;\n}\n")
        got = self.inspect()
        self.assertEqual(got["state"], "File Drift", got)
        self.assertEqual(got["findings"], [
            "DOCUMENT_ROOT_MISMATCH", "BOUND_HOST_MISSING_IN_VHOST",
            "VHOST_HOST_NOT_IN_NATIVE_BINDINGS",
        ])
        self.assertEqual(got["vhost_root"], "/www/another")
        self.assertIn("stale.test", got["vhost_names"])

    def test_native_document_roots_across_approved_custom_layouts(self):
        """The native record, not /www/wwwroot, determines the VHost root."""
        roots = (
            "/www/acdomains/alpha.test",
            "/www/other-sites/alpha.test",
            "/home/websites/alpha.test",
            "/mnt/data/alpha.test",
        )
        for root in roots:
            with self.subTest(root=root):
                self.site["path"] = root
                self.write(
                    "server { listen 80; server_name alpha.test www.alpha.test;"
                    " root " + root + "; }\n")
                source = self.path.read_bytes()
                matching = self.inspect()
                self.assertEqual(matching["state"], "File Match", matching)
                self.assertEqual(matching["native_root"], root)
                self.assertEqual(matching["vhost_root"], root)
                self.assertEqual(self.path.read_bytes(), source)
                self.site["path"] = root + "-relocated"
                stale = self.inspect()
                self.assertEqual(stale["state"], "File Drift", stale)
                self.assertEqual(stale["findings"], ["DOCUMENT_ROOT_MISMATCH"])
                self.assertFalse(stale["fix_supported"])
                self.assertEqual(self.path.read_bytes(), source)

    def test_only_one_terminal_document_root_slash_is_equivalent(self):
        cases = (
            ("/www/alpha", "/www/alpha", "File Match"),
            ("/www/alpha", "/www/alpha/", "File Match"),
            ("/www/alpha/", "/www/alpha", "File Match"),
            ("/www/alpha/", "/www/alpha/", "File Match"),
            ("/www/alpha", "/www/other/", "File Drift"),
            ("/www/alpha", "/www/alpha//", "Needs Review"),
            ("/www/alpha", "/www/alpha/./", "Needs Review"),
            ("/www/alpha", "/www/alpha/../alpha", "Needs Review"),
            ("/www/alpha/./", "/www/alpha/./", "Needs Review"),
            ("/www/alpha//", "/www/alpha//", "Needs Review"),
        )
        for native, generated, expected in cases:
            with self.subTest(native=native, generated=generated):
                self.site["path"] = native
                self.write(
                    "server { listen 80; server_name alpha.test www.alpha.test;"
                    " root " + generated + "; }\n")
                report = self.inspect()
                self.assertEqual(report["state"], expected, report)
                if expected == "File Drift":
                    self.assertEqual(report["findings"], ["DOCUMENT_ROOT_MISMATCH"])
                elif expected == "File Match":
                    self.assertEqual(report["findings"], [])

    def test_refuses_ambiguous_or_nested_directives(self):
        sources = [
            "server { server_name alpha.test www.alpha.test; root /www/alpha;"
            " location /secret { root /var/www; } }",
            "server { server_name alpha.test www.alpha.test; root /www/alpha;"
            " root /other; }",
            "server { server_name alpha.test www.alpha.test; root /www/alpha; }"
            " server { root /www/alpha; }",
            "server { server_name alpha.test www.alpha.test; root /www/alpha;"
            " listen unix:/tmp/nginx.sock; }",
            "server { server_name alpha.test www.alpha.test; root $document_root; }",
            "server { root /www/alpha; server_name alpha.test www.alpha.test;",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.write(source)
                got = self.inspect()
                self.assertEqual(got["state"], "Needs Review", got)
                self.assertIsNone(got["vhost_sha256"])
                self.assertEqual(got["findings"], [])

    def test_noncanonical_trailing_dots_never_produce_file_match(self):
        original = self.path.read_text()
        for invalid in ("alpha.test..", "alpha.test...", "www.alpha.test..",
                        "alpha..test", "*.alpha.test"):
            with self.subTest(generated=invalid):
                self.write(original.replace("server_name alpha.test www.alpha.test;",
                    "server_name " + invalid + " www.alpha.test;"))
                report = self.inspect()
                self.assertEqual(report["state"], "Needs Review", report)
                self.assertEqual(report["findings"], [])
                self.assertIsNone(report["vhost_sha256"])
        self.write(original)
        for invalid in ("alpha.test..", "alpha.test..."):
            with self.subTest(registered=invalid):
                self.site["bound_domains"][0]["name"] = invalid
                report = self.inspect()
                self.assertEqual(report["state"], "Needs Review", report)
                self.assertEqual(report["findings"], [])
        self.site["bound_domains"][0]["name"] = "alpha.test"
        # Only one terminal root dot is a supported DNS spelling variant.
        self.write(original.replace("server_name alpha.test www.alpha.test;",
                                    "server_name ALPHA.TEST. www.alpha.test;"))
        self.site["bound_domains"][0]["name"] = "alpha.test."
        report = self.inspect()
        self.assertEqual(report["state"], "File Match", report)
        self.assertEqual(report["native_names"], ["alpha.test", "www.alpha.test"])
        self.assertEqual(report["vhost_names"], report["native_names"])

    def test_no_untrusted_source_paths_or_hostnames(self):
        for key in ("../other", "a/b", "*.example.com", "bad site"):
            with self.subTest(key=key):
                self.site["name"] = key
                self.assertEqual(self.inspect()["state"], "Needs Review")
        self.site["name"] = "alpha.test"
        self.site["bound_domains"][0]["name"] = "../other"
        self.assertEqual(self.inspect()["state"], "Needs Review")

    def test_no_symlink_or_source_swap_accepted(self):
        original = self.path.with_suffix(".saved")
        self.path.rename(original)
        self.path.symlink_to(original)
        self.assertEqual(self.inspect()["state"], "Needs Review")
        self.path.unlink()
        original.rename(self.path)
        first = self.path.read_text()
        reads = 0
        actual = drift._bounded_file_text
        def change_between_scans(*args, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 2:
                self.write(first.replace("root /www/alpha", "root /www/changed"))
            return actual(*args, **kwargs)
        with patch.object(drift, "_bounded_file_text", side_effect=change_between_scans):
            got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertIn("changed", got["reason"])

    def test_unsupported_panel_never_reads_source(self):
        self.panel.get_panel_version = lambda: "8.0.8"
        with patch.object(drift, "_bounded_file_text", side_effect=AssertionError):
            result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")


class VhostEndpointTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-vhost-endpoint-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.patch_dir = patch.object(main, "_STATE_DIR", self.root)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)
        self.plugin = main.ach_customizer_main()
        self.reads = 0

    def flask(self, uid=1, method="POST", temporary=False):
        mod = types.ModuleType("flask")
        mod.has_request_context = lambda: True
        mod.request = types.SimpleNamespace(method=method)
        mod.session = {"login": True, "uid": uid}
        if temporary:
            mod.session["tmp_login_id"] = "temporary"
        return mod

    def public(self, change_on_read=None):
        public = types.ModuleType("public")
        outer = self
        class Query:
            def __init__(self, table):
                self.table = table
            def where(self, expr, args):
                assert (self.table, expr, args) in (
                    ("sites", "id=?", (7,)), ("domain", "pid IN (?)", (7,)))
                return self
            def field(self, cols):
                assert cols == ("id,name,path,status" if self.table == "sites" else
                                "id,pid,name,port")
                return self
            def find(self):
                outer.reads += 1
                return {"id": 7, "name": "alpha.test", "path": (
                    "/other" if change_on_read == outer.reads else "/www/alpha"),
                    "status": "1"}
            def order(self, value):
                assert value == "pid asc, id asc"
                return self
            def limit(self, value):
                assert value == "0,257"
                return self
            def select(self):
                return [{"id": 25, "pid": 7, "port": 80, "name": "alpha.test"}]
        public.M = lambda table: Query(table)
        return public

    def args(self):
        import json
        return {"site_id": "7", "expected_site_key": "alpha.test",
                "expected_site_snapshot": json.dumps([
                    7, "alpha.test", "/www/alpha", "1", [["alpha.test", 80]]]),
                "vhost_root": "/etc/shadow", "path": "/etc/shadow"}

    @staticmethod
    def sample():
        return {"schema": 1, "site_id": 7, "site_key": "alpha.test",
                "state": "File Match", "read_only": True,
                "runtime_verified": False, "fix_supported": False,
                "vhost_sha256": "a" * 64, "native_root": "/www/alpha",
                "vhost_root": "/www/alpha", "native_names": ["alpha.test"],
                "vhost_names": ["alpha.test"], "listen_ports": [80],
                "findings": [], "reason": "", "note": drift.NOTE}

    def test_full_admin_identity_snapshot_and_nopath_response(self):
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(drift, "inspect_vhost_drift", return_value=self.sample()) as check:
            got = self.plugin.inspect_native_vhost(self.args())
        self.assertTrue(got["status"], got)
        self.assertEqual(self.reads, 3)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(check.call_args.args[1]["path"], "/www/alpha")
        self.assertEqual(check.call_args.kwargs, {})
        self.assertNotIn("/etc/shadow", str(got))

    def test_authorization_and_stale_snapshot_rejected_without_file_read(self):
        for session in (self.flask(uid=2), self.flask(method="GET"),
                        self.flask(temporary=True)):
            with self.subTest(session=session.session), patch.dict(sys.modules, {
                "public": self.public(), "flask": session
            }), patch.object(drift, "inspect_vhost_drift") as check:
                got = self.plugin.inspect_native_vhost(self.args())
            self.assertFalse(got["status"])
            self.assertEqual(got["stage"], "website_vhost_authorization")
            check.assert_not_called()
        args = self.args()
        args["expected_site_snapshot"] = "[]"
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(drift, "inspect_vhost_drift") as check:
            got = self.plugin.inspect_native_vhost(args)
        self.assertFalse(got["status"])
        check.assert_not_called()

    def test_site_drift_during_read_does_not_report_success(self):
        self.reads = 0
        with patch.dict(sys.modules, {"public": self.public(change_on_read=2),
                                     "flask": self.flask()}), \
             patch.object(drift, "inspect_vhost_drift", return_value=self.sample()):
            got = self.plugin.inspect_native_vhost(self.args())
        self.assertFalse(got["status"])
        self.assertEqual(got["stage"], "website_vhost_inspection")


if __name__ == "__main__":
    unittest.main()
