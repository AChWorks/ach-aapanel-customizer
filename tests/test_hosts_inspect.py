"""Regression tests for bounded, origin-local /etc/hosts inspection."""
import hashlib
import json
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
import ach_customizer_hosts as hosts
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

    def test_empty_hosts_file_after_one_click_is_valid_no_aliases(self):
        self.write("")
        inspected = self.inspect()
        self.assertEqual(inspected["state"], "No Local Loopback Entry")
        self.assertEqual(inspected["entries"], [])
        self.assertEqual(inspected["hosts_sha256"], hashlib.sha256(b"").hexdigest())
        self.assertTrue(inspected["read_only"])
        self.assertFalse(inspected["remote_dns_verified"])
        self.assertEqual(self.path.read_bytes(), b"")

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

    def test_atomic_pathname_replacement_during_read_refuses_old_inode(self):
        """Atomic rename during read must fail, regardless of which guard fires."""
        self.write("127.0.0.1 example.test\n")
        old_content = self.path.read_bytes()
        replacement = self.root / "next-hosts"
        replacement.write_text("192.0.2.20 example.test\n", encoding="utf-8")
        replacement.chmod(0o644)
        original_read = os.read
        replaced = False

        def read_and_replace(fd, count):
            nonlocal replaced
            content = original_read(fd, count)
            if not replaced:
                os.replace(replacement, self.path)
                replaced = True
            return content

        with patch.object(hosts.os, "read", side_effect=read_and_replace):
            with self.assertRaisesRegex(HostsInspectionError, "Hosts (?:file changed during inspection|source changed; retry)"):
                self.inspect()
        self.assertTrue(replaced)
        self.assertNotEqual(self.path.read_bytes(), old_content)

    def test_symlink_and_removal_replacements_during_read_are_controlled(self):
        original_read = os.read
        for kind in ("symlink", "missing"):
            with self.subTest(kind=kind):
                if self.path.is_symlink() or self.path.exists():
                    self.path.unlink()
                self.write("127.0.0.1 example.test\n")
                replacement = self.root / "safe-source"
                replacement.write_text("127.0.0.1 unrelated.test\n", encoding="utf-8")
                replaced = False

                def read_and_swap(fd, count):
                    nonlocal replaced
                    content = original_read(fd, count)
                    if not replaced:
                        self.path.unlink()
                        if kind == "symlink":
                            self.path.symlink_to(replacement)
                        replaced = True
                    return content

                with patch.object(hosts.os, "read", side_effect=read_and_swap):
                    with self.assertRaisesRegex(HostsInspectionError, "Hosts (?:file changed during inspection|source changed; retry)"):
                        self.inspect()
                self.assertTrue(replaced)
                if self.path.is_symlink():
                    self.path.unlink()

    def test_replacement_detected_by_pathname_even_with_frozen_fd_metadata(self):
        """Prove the new path check independently of fstat's unlink detection.

        Real Linux rename generally also updates the old inode link count or
        ctime; freeze only second-fstat *test evidence* so that pathname
        revalidation is the rejecting guard.
        """
        self.write("127.0.0.1 example.test\n")
        successor = self.root / "next-hosts"
        successor.write_text("203.0.113.90 example.test\n")
        successor.chmod(0o644)
        original_read = os.read
        original_fstat = os.fstat
        first_stat = None

        def frozen_fstat(fd):
            nonlocal first_stat
            if first_stat is None:
                first_stat = original_fstat(fd)
            return first_stat

        def replacement(fd, count):
            chunk = original_read(fd, count)
            if successor.exists():
                os.replace(successor, self.path)
            return chunk

        with patch.object(hosts.os, "read", side_effect=replacement), \
             patch.object(hosts.os, "fstat", side_effect=frozen_fstat):
            with self.assertRaisesRegex(HostsInspectionError, "Hosts source changed; retry"):
                self.inspect()
        self.assertEqual(self.path.read_text(), "203.0.113.90 example.test\n")

    def test_in_place_modification_during_read_still_refused(self):
        self.write("127.0.0.1 example.test\n")
        original_read = os.read
        changed = False

        def read_and_edit(fd, count):
            nonlocal changed
            chunk = original_read(fd, count)
            if not changed:
                self.path.write_text("127.0.0.1 example.test changed.test\n")
                changed = True
            return chunk

        with patch.object(hosts.os, "read", side_effect=read_and_edit):
            with self.assertRaisesRegex(HostsInspectionError, "Hosts file changed"):
                self.inspect()
        self.assertTrue(changed)

    def test_large_valid_line_counts_and_alias_lists_stay_inspectable(self):
        self.write("127.0.0.1 localhost\n" * 2150 +
                   "127.0.0.2 example.test\n")
        observed = self.inspect()
        self.assertEqual(observed["entries"][0]["line"], 2151)
        self.write("127.0.0.1 " + " ".join(
            f"alias{i}.test" for i in range(170)) + " example.test\n")
        self.assertEqual(self.inspect()["entries"][0]["domain"], "example.test")
        # A moderately large valid Hosts source is not rejected merely
        # because it exceeds the previous 64 KiB read capacity.
        self.write("127.0.0.1 localhost\n" * 4000 +
                   "127.0.0.2 example.test\n")
        self.assertEqual(self.inspect()["entries"][0]["line"], 4001)
        self.write("x" * (hosts.MAX_BYTES + 1))
        with self.assertRaises(HostsInspectionError):
            self.inspect()

    def test_more_than_100_site_domains_can_be_inspected_without_cap(self):
        domains = [f"alias{i}.example.test" for i in range(1, 142)]
        self.write("127.0.0.1 alias141.example.test\n")
        observed = self.inspect(domains)
        self.assertEqual(len(observed["domains"]), 141)
        self.assertEqual(observed["entries"][0]["domain"], "alias141.example.test")

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

    @staticmethod
    def snapshot(*, site_name="site.test", path="/www/site.test",
                 status="1", domains=None):
        # The browser receives these fields from the validated native page.
        if domains is None:
            domains = [["*.site.test", 443], ["site.test", 80]]
        return json.dumps([7, site_name, path, status, domains],
                          separators=(",", ":"), ensure_ascii=False)

    def panel(self, changed=False, domains_changed=False, site_name="site.test",
              prechanged_domains=False, prechanged_path=False,
              prechanged_status=False):
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
                return {"id": 7, "name": site_name,
                        "path": "/changed" if prechanged_path or changed and outer.reads == 3
                                else "/www/site.test",
                        "status": "0" if prechanged_status else "1"}

        class DomainQuery:
            def where(self, expression, values):
                assert expression == "pid IN (?)" and tuple(values) == (7,)
                return self
            def order(self, expression):
                assert expression == "pid asc, id asc"
                return self
            def limit(self, expression):
                assert expression == "0,257"
                return self
            def field(self, fields):
                assert fields == "id,pid,name,port"
                return self
            def select(self):
                return [{"id": 41, "pid": 7, "name": "site.test", "port": 80},
                        {"id": 42, "pid": 7,
                         "name": "changed.test" if prechanged_domains or
                                domains_changed and outer.reads == 3
                         else "*.site.test", "port": 443}]
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

    def test_cached_older_hosts_helper_fails_only_hosts_without_breaking_overview(self):
        """In-place aaPanel import must not turn unrelated endpoints into 500s.

        A persistent panel Python process can hold a previous Hosts module
        lacking the latest snapshot helper until an authorized panel restart.
        """
        original = hosts.native_site_snapshot
        try:
            del hosts.native_site_snapshot
            overview = self.plugin.get_overview({})
            self.assertTrue(overview["status"], overview)
            with patch.dict(sys.modules, {"flask": self.flask(), "public": self.panel()}):
                with patch.object(endpoint, "inspect_hosts_file",
                                  side_effect=AssertionError("No source read while module is stale")) as reader:
                    result = self.plugin.inspect_local_hosts({
                        "site_id": "7", "expected_site_key": "site.test",
                        "expected_site_snapshot": self.snapshot(),
                    })
            self.assertFalse(result["status"])
            self.assertEqual(result["stage"], "hosts_inspection")
            self.assertIn("Restart aaPanel panel service", result["msg"])
            self.assertNotIn("Traceback", str(result))
            self.assertTrue(result["activity_logged"])
            self.assertEqual(self.reads, 0)
            reader.assert_not_called()

            # The authorization gate still precedes the backend-version check.
            with patch.dict(sys.modules, {"flask": self.flask(temporary=True)}):
                denied = self.plugin.inspect_local_hosts({
                    "site_id": "7", "expected_site_key": "site.test",
                    "expected_site_snapshot": self.snapshot(),
                })
            self.assertEqual(denied["stage"], "hosts_authorization")
            self.assertNotIn("outdated", denied["msg"])
        finally:
            hosts.native_site_snapshot = original

    def test_full_admin_post_uses_native_domains_not_untrusted_input(self):
        response = {"schema":1, "state":"Needs Review", "read_only":True}
        with patch.dict(sys.modules, {"public":self.panel(), "flask":self.flask()}):
            with patch.object(endpoint, "inspect_hosts_file", return_value=response) as spy:
                result = self.plugin.inspect_local_hosts(
                    {"site_id":"7", "expected_site_key":"site.test", "expected_site_snapshot":self.snapshot(),
                     "domains":["attacker.test"], "path":"/etc/shadow"})
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
                    response = self.plugin.inspect_local_hosts({"site_id":"7", "expected_site_key":"site.test", "expected_site_snapshot":self.snapshot()})
            self.assertFalse(response["status"])
            self.assertEqual(response["stage"], "hosts_authorization")
        self.assertEqual(self.reads, 0)

    def test_site_change_during_inspection_fails_closed(self):
        with patch.dict(sys.modules, {"flask":self.flask(), "public":self.panel(changed=True)}):
            with patch.object(endpoint, "inspect_hosts_file", return_value={"schema":1}) as spy:
                response = self.plugin.inspect_local_hosts({"site_id":"7", "expected_site_key":"site.test", "expected_site_snapshot":self.snapshot()})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")
        self.assertIn("changed", response["msg"])
        self.assertTrue(response["activity_logged"])
        from ach_customizer_activity import read_activity
        activity = read_activity(self.state.name, module="websites", limit=10)
        self.assertTrue(any(entry["action"] == "hosts_inspection" and
                            entry["error_class"] == "HostsInspectionError" for entry in activity))
        self.assertEqual(spy.call_count, 1)

    def test_native_endpoint_reads_real_bounded_file_and_persists_success_activity(self):
        """Join native-site selection, the actual hosts parser and Activity.

        The read fixture is isolated. Neither the endpoint nor its parser may
        modify it, infer remote DNS, or expose unrelated local aliases.
        """
        with tempfile.TemporaryDirectory(prefix="ach-hosts-integration-") as temp:
            source = Path(temp) / "hosts"
            content = ("127.0.0.2 site.test another-internal.test\n"
                       "203.0.113.4 unrelated-local.test\n")
            source.write_text(content, encoding="utf-8")
            source.chmod(0o644)
            before = source.read_bytes()
            with patch.dict(sys.modules, {"public": self.panel(), "flask": self.flask()}):
                with patch.object(endpoint, "inspect_hosts_file",
                                  side_effect=lambda names: inspect_local_hosts(
                                      names, source_path=str(source))) as inspected:
                    response = self.plugin.inspect_local_hosts(
                        {"site_id": "7", "expected_site_key": "site.test", "expected_site_snapshot":self.snapshot(),
                         "domains": ["attacker.example"], "source_path": "/etc/shadow"})
                    activity = self.plugin.get_activity({"module": "websites"})
            self.assertTrue(response["status"], response)
            self.assertEqual(response["site_id"], 7)
            self.assertEqual(response["site_key"], "site.test")
            self.assertEqual(response["state"], "Local Loopback Entry")
            self.assertEqual(response["hosts_sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual(response["domains"], ["site.test"])
            self.assertEqual(response["uninspected_wildcards"], ["*.site.test"])
            self.assertEqual(len(response["entries"]), 1)
            self.assertEqual(response["entries"][0]["address"], "127.0.0.2")
            self.assertFalse(response["resolver_verified"])
            self.assertFalse(response["gateway_verified"])
            self.assertFalse(response["fix_supported"])
            self.assertTrue(response["activity_logged"])
            self.assertTrue(activity["status"], activity)
            self.assertTrue(any(e["action"] == "inspect_local_hosts" and
                                e["outcome"] == "Local Loopback Entry" for e in activity["entries"]))
            self.assertNotIn("another-internal.test", str(response))
            self.assertNotIn("unrelated-local.test", str(response))
            self.assertNotIn("attacker.example", str(response))
            self.assertEqual(source.read_bytes(), before)
            inspected.assert_called_once_with(["site.test", "*.site.test"])
            self.assertEqual(self.reads, 3)

    def test_bound_domain_change_during_inspection_requires_recheck(self):
        """A site with an unchanged ID/name may still change its bound domains."""
        with patch.dict(sys.modules, {"flask": self.flask(),
                                      "public": self.panel(domains_changed=True)}):
            with patch.object(endpoint, "inspect_hosts_file", return_value={"schema": 1}) as inspected:
                response = self.plugin.inspect_local_hosts({"site_id": "7", "expected_site_key": "site.test", "expected_site_snapshot":self.snapshot()})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")
        self.assertIn("bound domains changed", response["msg"])
        self.assertNotIn("domains", response)
        self.assertEqual(self.reads, 3)
        inspected.assert_called_once()

    def test_unexpected_file_io_error_has_no_internal_details_in_browser_reply(self):
        with patch.dict(sys.modules, {"public": self.panel(), "flask": self.flask()}):
            with patch.object(endpoint, "inspect_hosts_file",
                              side_effect=OSError("private filesystem failure detail")):
                response = self.plugin.inspect_local_hosts({"site_id": "7", "expected_site_key": "site.test", "expected_site_snapshot":self.snapshot()})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")
        self.assertNotIn("private filesystem", str(response))
        self.assertIn("Operation ID", response["msg"])
        self.assertTrue(response["activity_logged"])
        from ach_customizer_activity import read_activity
        entries = read_activity(self.state.name, module="websites", limit=10)
        self.assertTrue(any(e["action"] == "hosts_inspection" and
                            e["error_class"] == "OSError" and
                            "private filesystem" not in e["detail"] for e in entries))

    def test_pre_request_domain_or_site_metadata_drift_never_reads_hosts(self):
        """The browser selected a *previous* native inventory snapshot.

        aaPanel changes domain bindings independently of sites.name, so a
        valid site ID/name is not enough to approve this inspection.
        """
        for change in ({"prechanged_domains": True},
                       {"prechanged_path": True},
                       {"prechanged_status": True}):
            with self.subTest(change=change):
                self.reads = 0
                with patch.dict(sys.modules, {"flask": self.flask(),
                                              "public": self.panel(**change)}):
                    with patch.object(endpoint, "inspect_hosts_file",
                                      side_effect=AssertionError("stale selection must not read")) as inspect:
                        result = self.plugin.inspect_local_hosts({
                            "site_id": "7", "expected_site_key": "site.test",
                            "expected_site_snapshot": self.snapshot(),
                        })
                self.assertFalse(result["status"])
                self.assertEqual(result["stage"], "hosts_inspection")
                self.assertIn("identity or bound domains changed", result["msg"])
                self.assertNotIn("changed.test", str(result))
                inspect.assert_not_called()
                self.assertEqual(self.reads, 2)

    def test_snapshot_domain_order_is_canonical_and_comparison_only(self):
        """Changing database row order must not fabricate a stale selection."""
        with patch.dict(sys.modules, {"flask": self.flask(), "public": self.panel()}):
            with patch.object(endpoint, "inspect_hosts_file", return_value={
                    "schema": 1, "state": "No Local Loopback Entry"}) as inspect:
                result = self.plugin.inspect_local_hosts({
                    "site_id": "7", "expected_site_key": "site.test",
                    "expected_site_snapshot": self.snapshot(
                        domains=[["*.site.test", 443], ["site.test", 80]]),
                    "domains": ["attacker.example"], "source_path": "/etc/shadow",
                })
        self.assertTrue(result["status"], result)
        inspect.assert_called_once_with(["site.test", "*.site.test"])
        self.assertEqual(self.reads, 3)

    def test_malformed_or_missing_snapshot_fails_before_hosts_access(self):
        for snapshot in ("", "not json", "[]", "[true]", " " * 110001,
                         json.dumps([7, "site.test", "/www/site.test", "1",
                                     [["site.test", True]]] ),
                         self.snapshot(domains=[["attacker.example", 80]])):
            with self.subTest(snapshot=str(snapshot)[:30]):
                self.reads = 0
                with patch.dict(sys.modules, {"flask": self.flask(), "public": self.panel()}):
                    with patch.object(endpoint, "inspect_hosts_file",
                                      side_effect=AssertionError("must not read")) as inspect:
                        response = self.plugin.inspect_local_hosts({
                            "site_id": "7", "expected_site_key": "site.test",
                            "expected_site_snapshot": snapshot,
                        })
                self.assertFalse(response["status"])
                self.assertEqual(response["stage"], "hosts_inspection")
                inspect.assert_not_called()

    def test_reassigned_site_id_is_denied_before_file_read(self):
        """An inventory site key is a stale-selection precondition, not authority."""
        with patch.dict(sys.modules, {"flask": self.flask(),
                                      "public": self.panel(site_name="reassigned.test")}):
            with patch.object(endpoint, "inspect_hosts_file",
                              side_effect=AssertionError("must not inspect")) as inspected:
                response = self.plugin.inspect_local_hosts(
                    {"site_id": "7", "expected_site_key": "site.test", "expected_site_snapshot":self.snapshot()})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")
        self.assertIn("identity or bound domains changed", response["msg"])
        self.assertNotIn("reassigned.test", str(response))
        inspected.assert_not_called()
        self.assertEqual(self.reads, 2)

    def test_missing_site_identity_precondition_is_rejected(self):
        with patch.dict(sys.modules, {"flask": self.flask(), "public": self.panel()}):
            with patch.object(endpoint, "inspect_hosts_file",
                              side_effect=AssertionError("must not inspect")) as inspected:
                response = self.plugin.inspect_local_hosts({"site_id": "7"})
        self.assertFalse(response["status"])
        self.assertIn("Refresh the native website inventory", response["msg"])
        self.assertEqual(self.reads, 0)
        inspected.assert_not_called()

    def test_invalid_site_id_never_reads_hosts(self):
        with patch.dict(sys.modules, {"flask":self.flask(), "public":self.panel()}):
            with patch.object(endpoint, "inspect_hosts_file", side_effect=AssertionError("not reached")):
                response = self.plugin.inspect_local_hosts({"site_id":"../../etc", "expected_site_key":"site.test", "expected_site_snapshot":self.snapshot()})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "hosts_inspection")


if __name__ == "__main__":
    unittest.main()
