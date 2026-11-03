"""Regression tests for bounded, origin-local /etc/hosts inspection."""
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
from ach_customizer_hosts import HostsInspectionError, inspect_local_hosts
import ach_customizer_main as endpoint


class LocalHostsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "hosts"
        self.write("127.0.0.1 localhost\n::1 localhost\n")

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        self.path.chmod(0o644)

    def inspect(self, names=None):
        return inspect_local_hosts(names or ["example.test"], source_path=str(self.path))

    def test_no_match_does_not_claim_dns_or_gateway_reachability(self):
        before = self.path.read_bytes()
        r = self.inspect()
        self.assertEqual(r["state"], "No Local Loopback Entry")
        self.assertEqual(r["entries"], [])
        self.assertFalse(r["gateway_verified"])
        self.assertFalse(r["resolver_verified"])
        self.assertFalse(r["remote_dns_verified"])
        self.assertFalse(r["fix_supported"])
        self.assertTrue(r["read_only"])
        self.assertEqual(r["hosts_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.path.read_bytes(), before)

    def test_ipv4_ipv6_and_mapped_loopback_with_duplicate_hostname_entries(self):
        self.write("127.0.0.2 example.test Other.Example\n"
                   "::1 example.test\n"
                   "::ffff:127.0.0.1 example.test\n"
                   "203.0.113.8 example.test\n"
                   "2001:db8::1 other.test\n")
        r = self.inspect()
        self.assertEqual(r["state"], "Local Loopback Entry")
        self.assertEqual(len(r["entries"]), 4)
        self.assertEqual([x["loopback"] for x in r["entries"]],
                         [True, True, True, False])
        self.assertEqual([x["line"] for x in r["entries"]], [1, 2, 3, 4])
        self.assertEqual({x["domain"] for x in r["entries"]}, {"example.test"})
        self.assertIn("may be intentional", r["note"].lower())

    def test_nonloopback_mapping_only_is_not_loopback(self):
        self.write("203.0.113.1 example.test example.test\n")
        r = self.inspect()
        self.assertEqual(r["state"], "No Local Loopback Entry")
        self.assertEqual(len(r["entries"]), 1)
        self.assertEqual(r["entries"][0]["address"], "203.0.113.1")
        self.assertFalse(r["entries"][0]["loopback"])

    def test_idna_case_and_terminal_dot_are_normalized(self):
        self.write("127.0.0.1 XN--MGBH0FB.XN--MGBA3A4F16A.\n")
        r = self.inspect(["مثال.ایران", "مثال.ایران."])
        # Each name gets a canonical IDNA match; the result never expands wildcards.
        self.assertEqual(r["state"], "Local Loopback Entry")
        self.assertEqual(len(r["domains"]), 1)
        self.assertEqual(len(r["entries"]), 1)

    def test_hash_comments_do_not_create_false_match(self):
        self.write("127.0.0.1 localhost # example.test\n")
        self.assertEqual(self.inspect()["entries"], [])

    def test_mixed_wildcard_binding_keeps_uncertainty_without_fabricating_match(self):
        r = self.inspect(["example.test", "*.example.test"])
        self.assertEqual(r["state"], "Needs Review")
        self.assertEqual(r["uninspected_wildcards"], ["*.example.test"])
        self.write("127.0.0.1 example.test\n")
        r = self.inspect(["example.test", "*.example.test"])
        self.assertEqual(r["state"], "Local Loopback Entry")
        self.assertEqual(len(r["entries"]), 1)
        with self.assertRaises(HostsInspectionError):
            self.inspect(["*.example.test"])

    def test_ambiguous_or_invalid_native_domain_fails_before_file_read(self):
        for value in ("../passwd", "example test", "http://host", "a"*255,
                      "site#evil", "", "bad..host", "foo..", "*.*"):
            with self.subTest(domain=value):
                with self.assertRaises(HostsInspectionError):
                    inspect_local_hosts([value], source_path=str(self.path))

    def test_invalid_ip_line_fails_closed_not_success(self):
        self.write("not-an-ip example.test\n")
        with self.assertRaises(HostsInspectionError):
            self.inspect()

    def test_malformed_line_without_alias_rejected(self):
        self.write("127.0.0.1\n")
        with self.assertRaises(HostsInspectionError):
            self.inspect()

    def test_symlinked_file_and_ancestor_refused(self):
        original = self.root / "saved"
        original.write_text("127.0.0.1 example.test\n")
        self.path.unlink()
        self.path.symlink_to(original)
        with self.assertRaises(OSError):
            self.inspect()
        self.path.unlink()
        self.write("127.0.0.1 example.test\n")
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            inspect_local_hosts(["example.test"], source_path=str(alias / "hosts"))

    def test_group_writable_or_hardlinked_source_refused(self):
        self.write("127.0.0.1 example.test\n")
        self.path.chmod(0o666)
        with self.assertRaises(HostsInspectionError):
            self.inspect()
        self.path.chmod(0o644)
        hardlink = self.root / "copy"
        os.link(self.path, hardlink)
        with self.assertRaises(HostsInspectionError):
            self.inspect()

    def test_bounded_sizes_line_counts_and_matches(self):
        self.write("127.0.0.1 localhost\n" * 2050)
        with self.assertRaises(HostsInspectionError):
            self.inspect()
        self.write("127.0.0.1 example.test\n" * 101)
        with self.assertRaises(HostsInspectionError):
            self.inspect()
        self.write("x" * 65537)
        with self.assertRaises(HostsInspectionError):
            self.inspect()

    def test_matches_only_requested_domains_preserves_other_file_text(self):
        self.write("127.0.0.1 localhost internal-only.test\n"
                   "127.0.0.1 example.test\n"
                   "192.0.2.3 unrelated.test\n")
        before = self.path.read_bytes()
        r = self.inspect()
        self.assertEqual(len(r["entries"]), 1)
        self.assertNotIn("internal-only.test", str(r))
        self.assertNotIn("unrelated.test", str(r))
        self.assertEqual(self.path.read_bytes(), before)


class NativeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = endpoint.ach_customizer_main()
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        patcher = patch.object(endpoint, "_STATE_DIR", self.state.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.reads = 0

    def panel(self, changed=False):
        module = types.ModuleType("public")
        outer = self

        class SiteQuery:
            def where(self, expression, values):
                assert expression == "id=?" and tuple(values) == (7,)
                return self
            def field(self, fields):
                assert fields == "id,name,path,status"
                return self
            def find(self):
                outer.reads += 1
                return {"id": 7, "name": "site.test",
                        "path": "/changed" if changed and outer.reads == 3 else "/www/site.test",
                        "status": "1"}

        class DomainQuery:
            def where(self, expression, values):
                assert expression == "pid IN (?)" and tuple(values) == (7,)
                return self
            def order(self, expression):
                assert expression == "pid asc, id asc"
                return self
            def limit(self, expression):
                assert expression == "0,1001"
                return self
            def field(self, fields):
                assert fields == "id,pid,name,port"
                return self
            def select(self):
                return [{"id": 41, "pid": 7, "name": "site.test", "port": 80},
                        {"id": 42, "pid": 7, "name": "*.site.test", "port": 443}]
        module.M = lambda name: SiteQuery() if name == "sites" else DomainQuery()
        return module

    @staticmethod
    def flask(uid=1, method="POST", temporary=False):
        module = types.ModuleType("flask")
        module.has_request_context = lambda: True
        module.request = types.SimpleNamespace(method=method)
        module.session = {"login": True, "uid": uid}
        if temporary:
            module.session["tmp_login"] = True
        return module

    def test_full_admin_post_uses_native_domains_not_untrusted_input(self):
        response = {"schema":1, "state":"Needs Review", "read_only":True}
        with patch.dict(sys.modules, {"public":self.panel(), "flask":self.flask()}):
            with patch.object(endpoint, "inspect_hosts_file", return_value=response) as spy:
                result = self.plugin.inspect_local_hosts(
                    {"site_id":"7", "domains":["attacker.test"], "path":"/etc/shadow"})
        self.assertTrue(result["status"], result)
        self.assertEqual(result["site_id"], 7)
        self.assertEqual(result["site_key"], "site.test")
        self.assertEqual(spy.call_args.args[0], ["site.test", "*.site.test"])
        self.assertEqual(self.reads, 3)
        self.assertTrue(result["activity_logged"])
        from ach_customizer_activity import read_activity
        activity = read_activity(self.state.name, module="websites", limit=10)
        self.assertTrue(any(entry["action"] == "inspect_local_hosts" and
                            entry["outcome"] == "Needs Review" for entry in activity))
        self.assertFalse(Path(self.state.name, "ach_customizer.state.json").exists())

    def test_secondary_temporary_and_get_rejected_before_filesystem_inspection(self):
        for access in (self.flask(uid=2), self.flask(temporary=True),
                       self.flask(method="GET")):
            with patch.dict(sys.modules, {"flask":access, "public":self.panel()}):
                with patch.object(endpoint, "inspect_hosts_file", side_effect=AssertionError("Must not read")):
                    response = self.plugin.inspect_local_hosts({"site_id":"7"})
            self.assertFalse(response["status"])
            self.assertEqual(response["stage"], "hosts_authorization")
        self.assertEqual(self.reads, 0)

    def test_site_change_during_inspection_fails_closed(self):
        with patch.dict(sys.modules, {"flask":self.flask(), "public":self.panel(changed=True)}):
            with patch.object(endpoint, "inspect_hosts_file", return_value={"schema":1}) as spy:
                response = self.plugin.inspect_local_hosts({"site_id":"7"})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")
        self.assertIn("changed", response["msg"])
        self.assertTrue(response["activity_logged"])
        from ach_customizer_activity import read_activity
        activity = read_activity(self.state.name, module="websites", limit=10)
        self.assertTrue(any(entry["action"] == "hosts_inspection" and
                            entry["error_class"] == "HostsInspectionError" for entry in activity))
        self.assertEqual(spy.call_count, 1)

    def test_invalid_site_id_never_reads_hosts(self):
        with patch.dict(sys.modules, {"flask":self.flask(), "public":self.panel()}):
            with patch.object(endpoint, "inspect_hosts_file", side_effect=AssertionError("not reached")):
                response = self.plugin.inspect_local_hosts({"site_id":"../../etc"})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")


if __name__ == "__main__":
    unittest.main()
