"""Version-specific Nginx/PHP-FPM site FILE topology, with no service writes."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_php_topology as topo


class SiteTopologyTests(unittest.TestCase):
    class Query:
        def __init__(self, parent):
            self.parent = parent

        def order(self, value):
            assert value == "id asc"
            return self

        def limit(self, value):
            assert value == "0,101"
            return self

        def field(self, value):
            assert value == "id,name"
            return self

        def select(self):
            self.parent.reads += 1
            return [dict(r) for r in self.parent.rows[:101]]

    class Panel:
        def __init__(self, rows):
            self.rows = rows
            self.reads = 0
            self.webserver = "nginx"
            self.version = "8.0.7"

        def M(self, table):
            assert table == "sites"
            return SiteTopologyTests.Query(self)

        def get_webserver(self):
            return self.webserver

        def get_panel_version(self):
            return self.version

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-fpm-site-topology-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.php = self.root / "php"
        self.php.mkdir()
        self.vhosts = self.root / "vhosts"
        self.vhosts.mkdir()
        self.nginx = self.root / "nginx"
        self.nginx.mkdir()
        self.rewrites = self.root / "rewrite"
        self.rewrites.mkdir()
        self.socket81 = str(self.root / "pool-81.sock")
        self.socket85 = str(self.root / "pool-85-custom.sock")
        self.setup_php("81", self.socket81)
        self.setup_php("85", self.socket85)
        for ver, socket in (("81", self.socket81), ("85", self.socket85)):
            (self.nginx / ("enable-php-" + ver + ".conf")).write_text(
                "location ~ \\.php$ {\n include fastcgi.conf;\n"
                " fastcgi_pass unix:" + socket + ";\n}\n")
        (self.nginx / "fastcgi.conf").write_text(
            "fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n"
        )
        (self.nginx / "enable-php-00.conf").write_text(
            "location ~ [^/]\\.php(/|$) { return 404; }\n"
        )
        self.rows = [
            {"id": 3, "name": "first.test"},
            {"id": 4, "name": "wordpress.test"},
            {"id": 6, "name": "other.test"},
            {"id": 7, "name": "static.test"},
        ]
        self.panel = self.Panel(self.rows)
        for site in self.rows:
            source = "81" if site["id"] in (3, 4) else "85" if site["id"] == 6 else "00"
            (self.vhosts / (site["name"] + ".conf")).write_text(
                "server {\n server_name " + site["name"] +
                ";\n include enable-php-" + source + ".conf;\n}\n"
            )

    def setup_php(self, version, socket):
        root = self.php / version
        (root / "etc").mkdir(parents=True)
        (root / "sbin").mkdir()
        binary = root / "sbin" / "php-fpm"
        binary.write_bytes(b"\x7fELF" + b"stub" * 5)
        binary.chmod(0o755)
        (root / "etc" / "php-fpm.conf").write_text(
            "[global]\n[www]\npm = dynamic\n"
            "pm.max_children = 20\nlisten = " + socket + "\n"
        )

    def inspect(self, version="81", **fields):
        return topo.inspect_php_fpm_site_topology(
            self.panel, str(self.php), version,
            vhost_root=str(self.vhosts), nginx_conf_root=str(self.nginx),
            rewrite_root=str(self.rewrites), **fields
        )

    def test_php81_maps_its_exact_socket_and_sites_without_affecting_php85(self):
        files = list(self.root.rglob("*.conf")) + list(self.root.rglob("php-fpm"))
        before = {str(p): hashlib.sha256(p.read_bytes()).digest() for p in files}
        got = self.inspect(observed_runtime_socket=self.socket81)
        self.assertEqual(got["state"], "File Mapping", got)
        self.assertEqual(got["pool"], "www")
        self.assertEqual(got["socket_path"], self.socket81)
        self.assertEqual(got["matched_sites"], [
            {"id": 3, "site_key": "first.test"},
            {"id": 4, "site_key": "wordpress.test"},
        ])
        self.assertEqual(got["other_sites"], [
            {"id": 6, "site_key": "other.test", "version": "85",
             "socket_path": self.socket85},
            {"id": 7, "site_key": "static.test", "version": "00",
             "socket_path": None},
        ])
        self.assertEqual(got["site_count"], 4)
        self.assertEqual(got["unresolved_sites"], [])
        self.assertRegex(got["source_sha256"], r"^[a-f0-9]{64}$")
        self.assertGreaterEqual(self.panel.reads, 2)
        self.assertIs(got["read_only"], True)
        self.assertIs(got["apply_eligible"], False)
        self.assertIs(got["runtime_verified"], False)
        self.assertIn("not loaded", got["note"].lower().replace("not loaded nginx", "not loaded"))
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).digest()
                                  for p in files})

    def test_php85_reverse_view_and_no_cross_version_false_link(self):
        got = self.inspect("85")
        self.assertEqual(got["state"], "File Mapping")
        self.assertEqual([r["id"] for r in got["matched_sites"]], [6])
        self.assertEqual(got["other_sites"][0]["version"], "81")
        self.assertEqual(got["other_sites"][0]["socket_path"], self.socket81)

    def test_native_wp_fastcgi_remains_read_only_when_verified(self):
        (self.nginx / "enable-php-81-wpfastcgi.conf").write_text(
            "location ~ \\.php$ {\n include fastcgi.conf;\n"
            " fastcgi_pass unix:" + self.socket81 + ";\n}\n")
        vhost = self.vhosts / "wordpress.test.conf"
        vhost.write_text(vhost.read_text().replace(
            "enable-php-81.conf", "enable-php-81-wpfastcgi.conf"))
        got = self.inspect()
        self.assertEqual(got["state"], "File Mapping", got)
        self.assertEqual(len(got["matched_sites"]), 2)
        self.assertFalse(got["apply_eligible"])

    def test_ambiguous_other_version_is_partial_not_complete_impact(self):
        snippet = self.nginx / "enable-php-85.conf"
        snippet.write_text(snippet.read_text().replace(self.socket85, self.socket81))
        got = self.inspect()
        self.assertEqual(got["state"], "Partial", got)
        self.assertEqual([s["id"] for s in got["unresolved_sites"]], [6])
        self.assertIsNone(got["source_sha256"])
        self.assertEqual(len(got["matched_sites"]), 2)

    def test_other_version_uninstalled_or_multiple_pool_is_unresolved(self):
        binary = self.php / "85" / "sbin" / "php-fpm"
        binary.unlink()
        got = self.inspect()
        self.assertEqual(got["state"], "Partial", got)
        self.assertEqual(got["unresolved_sites"][0]["id"], 6)
        binary.write_bytes(b"binary-restored")
        binary.chmod(0o755)
        config = self.php / "85" / "etc" / "php-fpm.conf"
        config.write_text(config.read_text() + "\n[backup]\nlisten = /tmp/alt.sock\n")
        got = self.inspect()
        self.assertEqual(got["state"], "Partial", got)
        self.assertEqual([r["id"] for r in got["unresolved_sites"]], [6])

    def test_selected_pool_include_and_service_socket_conflict_refuse_mapping(self):
        config = self.php / "81" / "etc" / "php-fpm.conf"
        config.write_text(config.read_text() + "\ninclude = php-fpm.d/*.conf\n")
        self.assertEqual(self.inspect()["state"], "Needs Review")
        config.write_text(config.read_text().replace("include = php-fpm.d/*.conf\n", ""))
        self.assertEqual(self.inspect(observed_runtime_socket="/tmp/other.sock")["state"],
                         "Needs Review")
        self.assertIn("differ", self.inspect(
            observed_runtime_socket="/tmp/other.sock")["reason"])

    def test_untrusted_vhost_and_site_db_growth_fail_without_write(self):
        vhost = self.vhosts / "first.test.conf"
        vhost.unlink()
        vhost.symlink_to("/etc/hosts")
        got = self.inspect()
        self.assertEqual(got["state"], "Partial")
        self.assertEqual([r["id"] for r in got["unresolved_sites"]], [3])
        vhost.unlink()
        self.panel.rows = [
            {"id": i, "name": "many" + str(i) + ".test"} for i in range(101)]
        got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertEqual(got["site_count"], 0)

    def test_inflight_regeneration_cannot_return_complete_file_mapping(self):
        original = topo.inspect_php_fpm_site_impact
        calls = 0
        def mutate(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original(*args, **kwargs)
            if calls == 1:
                (self.vhosts / "first.test.conf").write_text(
                    "server {\n include enable-php-85.conf;\n}\n")
            return result
        with patch.object(topo, "inspect_php_fpm_site_impact", side_effect=mutate):
            got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertEqual(got["matched_sites"], [])

    def test_other_php_source_edit_changes_complete_mapping_digest(self):
        first = self.inspect()
        self.assertEqual(first["state"], "File Mapping")
        conf = self.php / "85" / "etc" / "php-fpm.conf"
        conf.write_text(conf.read_text() + "# independent operator note\n")
        second = self.inspect()
        self.assertEqual(second["state"], "File Mapping", second)
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])

    def test_versioned_php_source_changes_during_mapping_invalidate_all_attribution(self):
        original = topo.inspect_php_fpm_site_impact
        called = 0
        def change_other_source(*args, **kwargs):
            nonlocal called
            called += 1
            found = original(*args, **kwargs)
            if called == 1:
                conf = self.php / "85" / "etc" / "php-fpm.conf"
                conf.write_text(conf.read_text() + "\n# concurrent aaPanel regeneration\n")
            return found
        with patch.object(topo, "inspect_php_fpm_site_impact",
                          side_effect=change_other_source):
            result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(result["site_count"], 0)
        self.assertEqual(result["matched_sites"], [])
        self.assertFalse(result["apply_eligible"])

    def test_missing_native_api_attribute_keeps_topology_non_authorizing(self):
        self.panel = object()
        got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertFalse(got["apply_eligible"])
        self.assertIsNone(got["source_sha256"])
        self.assertEqual(got["matched_sites"], [])

    def test_alternate_engine_version_or_incomplete_installed_source_is_not_mapped(self):
        for webserver, version in (("apache", "8.0.7"), ("nginx", "8.1.1")):
            self.panel.webserver = webserver
            self.panel.version = version
            self.assertEqual(self.inspect()["state"], "Needs Review")
        self.panel.webserver = "nginx"
        self.panel.version = "8.0.7"
        (self.php / "81" / "etc" / "php-fpm.conf").unlink()
        got = self.inspect()
        self.assertEqual(got["state"], "Needs Review")
        self.assertFalse(got["apply_eligible"])


if __name__ == "__main__":
    unittest.main()
