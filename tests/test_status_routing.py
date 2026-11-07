"""Fail-closed source-only nginx -T gating for narrowly supported static 404."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_status_routing as route


class ConfiguredRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-route-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.www = self.root / "sites" / "demo.test"
        self.www.mkdir(parents=True)
        (self.www / "404.html").write_text("original page")
        self.vhosts = self.root / "nginx"
        self.vhosts.mkdir()
        self.conf = self.vhosts / "demo.test.conf"
        self.conf.write_text(self.static_vhost())
        self.site = {
            "id": 7, "name": "demo.test", "path": str(self.www),
            "status": "1",
            "bound_domains": [{"name": "demo.test", "port": 80}],
        }
        self.other = self.root / "nginx.conf"

    def static_vhost(self):
        return (
            "server {\n"
            "    listen 80;\n"
            "    server_name demo.test;\n"
            "    root " + str(self.root / "sites" / "demo.test") + ";\n"
            "    error_page 404 /404.html;\n"
            "    index index.html;\n"
            "}\n"
        )

    def dump(self, other=None):
        if other is None:
            other = "worker_processes 1;\nevents { worker_connections 64; }\n"
        return (f"# configuration file {self.other}:\n{other}\n"
                f"# configuration file {self.conf}:\n{self.conf.read_text()}\n")

    def validate(self, dump=None):
        if dump is None:
            dump = self.dump()
        return route.verify_configured_site_404(
            self.site, vhost_root=str(self.vhosts),
            capture=lambda: dump,
            runtime=lambda files: {
                "native_http80_process_verified": True,
                "runtime_generation_sha256": "e" * 64,
            })

    def assert_rejects(self, vhost=None, other=None):
        if vhost is not None:
            self.conf.write_text(vhost)
        with self.assertRaises(route.RouteGuardError):
            self.validate(self.dump(other))

    def test_one_static_http_vhost_matches_configured_dump(self):
        result = self.validate()
        self.assertTrue(result["configured_static_http_80"])
        self.assertFalse(result["loaded_workers_verified"])
        self.assertFalse(result["https_verified"])
        self.assertEqual(len(result["nginx_dump_sha256"]), 64)

    def test_unrecognized_routing_layers_fail_closed(self):
        for addition in (
            "include /www/server/panel/vhost/rewrite/demo.test.conf;",
            "location / { try_files $uri /index.html; }",
            "location = /404.html { alias /tmp/other; }",
            "rewrite ^ /other last;",
            "fastcgi_intercept_errors on;",
            "proxy_intercept_errors on;",
            "server_name demo.test another.test;",
            "error_page 404 /alternative.html;",
            "listen 443 ssl;",
        ):
            with self.subTest(addition=addition):
                source = self.static_vhost().replace(
                    "    index index.html;\n",
                    "    index index.html;\n    " + addition + "\n")
                self.assert_rejects(vhost=source)
        self.conf.write_text(self.static_vhost())

    def test_unknown_site_alias_and_additional_consumer_fail_closed(self):
        self.assert_rejects(other=(
            "http { server { root " + str(self.www) + "; } }\n"
        ))
        self.assert_rejects(other=(
            "http { server { alias " + str(self.www) + "/404.html; } }\n"
        ))
        self.assert_rejects(other=(
            "server { server_name demo.test; root /other/site; }\n"
        ))
        self.assert_rejects(other="server { root \"" + str(self.www) + "\"; }\n")
        self.assert_rejects(other="server { alias " + str(self.root / "sites") + "; }\n")
        self.assert_rejects(other="server { root $document_root; }\n")
        self.assert_rejects(other="server { root /tmp/../sites/demo.test; }\n")

    def test_another_site_has_distinct_literal_root(self):
        other_root = self.root / "sites" / "other.test"
        other_root.mkdir()
        result = self.validate(self.dump(
            "server { listen 80; server_name other.test; root "
            + str(other_root) + "; }"))
        self.assertTrue(result["configured_static_http_80"])

    def test_indirect_symlink_consumers_cannot_pass_positive_guard(self):
        other_root = self.root / "sites" / "other.test"
        other_root.mkdir()
        conf = ("server { listen 80; server_name other.test; root "
                + str(other_root) + "; }\n")
        # The other site's literal root differs, but its 404 is the target.
        (other_root / "404.html").symlink_to(self.www / "404.html")
        self.assert_rejects(other=conf)
        (other_root / "404.html").unlink()
        deep = other_root / "nested"
        deep.mkdir()
        (deep / "surprise").symlink_to(self.www / "404.html")
        self.assert_rejects(other=conf)
        (deep / "surprise").unlink()
        (other_root / "unrelated-link").symlink_to(self.root / "unrelated")
        self.assert_rejects(other=conf)

    def test_disjoint_external_root_graph_is_bound_to_file_identity(self):
        other_root = self.root / "sites" / "other.test"
        other_root.mkdir()
        (other_root / "404.html").write_text("independent 404")
        conf = ("server { listen 80; server_name other.test; root "
                + str(other_root) + "; }\n")
        first = self.validate(self.dump(conf))
        self.assertTrue(first["configured_static_http_80"])
        self.assertEqual(len(first["external_graph_sha256"]), 64)
        (other_root / "additional.html").write_text("new independent file")
        second = self.validate(self.dump(conf))
        self.assertNotEqual(first["external_graph_sha256"],
                            second["external_graph_sha256"])

    def test_unknown_other_site_routes_fail_closed(self):
        other_root = self.root / "sites" / "other.test"
        other_root.mkdir()
        server = ("server { listen 80; server_name other.test; root "
                  + str(other_root) + "; ")
        for extension in (
                "location / { try_files $uri /index.html; }",
                "location / { proxy_pass http://127.0.0.1:8080; }",
                "rewrite ^/ /index.html last;",
                "fastcgi_pass unix:/tmp/application.sock;",
                "server { listen 80; server_name third.test; }"):
            with self.subTest(extension=extension):
                self.assert_rejects(other=server + extension + " }")

    def test_uninspectable_external_roots_and_aliases_fail_closed(self):
        other_root = self.root / "sites" / "other.test"
        # A configured but missing root cannot be established as exclusive.
        self.assert_rejects(other=("server { root " + str(other_root) + "; }\n"))
        other_root.mkdir()
        self.assert_rejects(other=("server { alias " + str(other_root) + "; }\n"))
        self.assert_rejects(other="server { listen 80; server_name other.test; }\n")

    def test_trust_boundaries_require_literal_site_and_binding(self):
        cases = [
            {"bound_domains": [{"name": "demo.test", "port": 443}]},
            {"bound_domains": [{"name": "demo.test", "port": 80},
                               {"name": "second.test", "port": 443}]},
            {"name": "*.demo.test"},
            {"status": "0"},
            {"path": "/tmp/../bad"},
        ]
        for replace in cases:
            with self.subTest(replace=replace):
                candidate = dict(self.site, **replace)
                with self.assertRaises(route.RouteGuardError):
                    route.verify_configured_site_404(
                        candidate, vhost_root=str(self.vhosts),
                        capture=lambda: self.dump(),
                        runtime=lambda files: {
                            "native_http80_process_verified": True,
                            "runtime_generation_sha256": "e" * 64,
                        })

    def test_dump_source_consistency_and_duplicate_headers(self):
        expected = self.dump()
        self.conf.write_text(self.static_vhost() + "# changed after dump\n")
        with self.assertRaises(route.RouteGuardError):
            self.validate(expected)
        self.conf.write_text(self.static_vhost())
        with self.assertRaises(route.RouteGuardError):
            self.validate(expected + f"# configuration file {self.conf}:\nserver {{}}\n")
        with self.assertRaises(route.RouteGuardError):
            self.validate("the nginx dump did not contain the required header")
        with self.assertRaises(route.RouteGuardError):
            self.validate("# configuration file /tmp/../escape.conf:\nserver {}")

    def test_root_owned_no_group_world_writable_source(self):
        self.conf.chmod(0o666)
        with self.assertRaises(route.RouteGuardError):
            self.validate()
        self.conf.chmod(0o644)
        self.conf.unlink()
        self.conf.symlink_to(self.other)
        with self.assertRaises((route.RouteGuardError, OSError)):
            self.validate()

    def test_unrecognized_configuration_source_must_not_infer_loaded_workers(self):
        result = self.validate()
        self.assertFalse(result["loaded_workers_verified"])
        self.assertTrue(result["native_http80_process_verified"])

    def test_native_runtime_identity_must_be_positive_and_well_formed(self):
        for proof in ({}, {"native_http80_process_verified": False,
                           "runtime_generation_sha256": "e" * 64},
                      {"native_http80_process_verified": True,
                       "runtime_generation_sha256": "not-a-sha"}):
            with self.subTest(proof=proof), self.assertRaises(route.RouteGuardError):
                route.verify_configured_site_404(
                    self.site, vhost_root=str(self.vhosts),
                    capture=lambda: self.dump(), runtime=lambda files: proof)


if __name__ == "__main__":
    unittest.main()
