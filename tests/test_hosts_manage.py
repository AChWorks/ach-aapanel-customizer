"""Isolated real-filesystem regression tests for opt-in hosts alias removal."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_hosts_manage as manager
from ach_customizer_hosts import inspect_local_hosts


class HostsRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ach-hosts-remediate-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.origin = root / "origin"
        self.origin.mkdir(mode=0o700)
        self.source = self.origin / "hosts"
        self.state = root / "state"
        self.state.mkdir(mode=0o700)
        self.site = {"id": 7, "name": "site.test", "path": "/www/site.test",
                     "status": "1", "bound_domains": [
                         {"name": "site.test", "port": 80},
                         {"name": "alias.test", "port": 80},
                         {"name": "*.wild.test", "port": 443}]}
        self.domains = ["site.test", "alias.test", "*.wild.test"]
        self.write(b"127.0.0.1 localhost\n127.0.0.2 site.test\n")

    def write(self, payload):
        self.source.write_bytes(payload)
        self.source.chmod(0o644)

    def remove(self, *, domain="site.test", expected_sha=None):
        return manager.remove_loopback_alias(
            site=self.site, domains=self.domains, domain=domain,
            expected_sha=expected_sha or hashlib.sha256(self.source.read_bytes()).hexdigest(),
            source_path=str(self.source), data_dir=str(self.state))

    def restore(self, recovery_id):
        return manager.restore_loopback_alias(
            site=self.site, expected_recovery_id=recovery_id,
            source_path=str(self.source), data_dir=str(self.state))

    def recovery(self):
        return manager.inspect_recovery(self.site, source_path=str(self.source),
                                        data_dir=str(self.state))

    def test_remove_single_alias_with_saved_recovery_and_restore(self):
        before = self.source.read_bytes()
        result = self.remove()
        self.assertEqual(result["state"], "Alias Removed")
        self.assertEqual(result["removed_aliases"], 1)
        self.assertFalse(result["remote_dns_verified"])
        self.assertEqual(self.source.read_bytes(), b"127.0.0.1 localhost\n")
        self.assertEqual(self.recovery()["state"], "Applied")
        self.assertEqual(inspect_local_hosts(self.domains, source_path=str(self.source))["state"],
                         "Needs Review")
        restored = self.restore(result["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.recovery()["state"], "restored")

    def test_large_hosts_source_and_many_unrelated_aliases_remain_removable(self):
        unrelated = " ".join(f"alias{i}.test" for i in range(160))
        original = (b"# unrelated entry\n" * 2130 +
                    ("127.0.0.1 " + unrelated + " site.test\n").encode())
        self.write(original)
        result = self.remove()
        self.assertEqual(result["removed_aliases"], 1)
        self.assertEqual(self.source.read_bytes(),
                         original.replace(b" site.test\n", b"\n"))
        self.restore(result["recovery_id"])
        self.assertEqual(self.source.read_bytes(), original)

    def test_preserve_unrelated_names_and_comments_including_crlf(self):
        original = (b"# first\r\n127.0.0.1 localhost site.test OTHER.test # keep me\r\n"
                    b"::1 alias.test\n::ffff:127.0.0.9 site.test\n"
                    b"192.0.2.4 site.test\n127.0.0.7 unrelated.test\n")
        self.write(original)
        response = self.remove()
        self.assertEqual(response["removed_aliases"], 2)
        self.assertEqual(self.source.read_bytes(), (
            b"# first\r\n127.0.0.1 localhost OTHER.test # keep me\r\n"
            b"::1 alias.test\n192.0.2.4 site.test\n127.0.0.7 unrelated.test\n"))
        self.restore(response["recovery_id"])
        self.assertEqual(self.source.read_bytes(), original)

    def test_reject_unreviewed_or_unbound_domains(self):
        before = self.source.read_bytes()
        for domain in ("localhost", "other.test", "*.wild.test", "SITE.TEST", "../../etc"):
            with self.subTest(domain=domain):
                with self.assertRaises(manager.HostsManageError):
                    self.remove(domain=domain)
                self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_reject_missing_current_loopback_and_stale_digest(self):
        self.write(b"192.0.2.4 site.test\n")
        with self.assertRaisesRegex(manager.HostsManageError, "no current loopback"):
            self.remove()
        self.write(b"127.0.0.1 site.test\n")
        with self.assertRaisesRegex(manager.HostsManageError, "after inspection"):
            self.remove(expected_sha="a" * 64)
        self.assertEqual(self.source.read_bytes(), b"127.0.0.1 site.test\n")

    def test_rename_symlink_and_untrusted_source_not_written(self):
        original = self.source.read_bytes()
        target = self.origin / "another"
        target.write_bytes(original)
        target.chmod(0o644)
        self.source.unlink()
        self.source.symlink_to(target)
        with self.assertRaises(OSError):
            self.remove(expected_sha=hashlib.sha256(original).hexdigest())
        self.assertEqual(target.read_bytes(), original)
        self.source.unlink()
        self.write(original)
        self.source.chmod(0o666)
        with self.assertRaises(manager.HostsManageError):
            self.remove()
        self.assertEqual(self.source.read_bytes(), original)

    def test_current_journal_refuses_new_write_and_changed_file_refuses_restore(self):
        first = self.remove()
        with self.assertRaisesRegex(manager.HostsManageError, "active hosts recovery"):
            self.remove(domain="alias.test")
        self.source.write_bytes(b"127.0.0.1 localhost\n127.0.0.9 unrelated.test\n")
        with self.assertRaisesRegex(manager.HostsManageError, "changed since Apply"):
            self.restore(first["recovery_id"])
        self.assertEqual(self.recovery()["state"], "Needs Review")

    def test_provisional_write_failure_can_reconcile_without_source_edit(self):
        import ach_customizer_hosts_manage as m
        old_replace = m.os.replace
        def deny_hosts_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            if dst == "hosts":
                raise PermissionError("fixture denied rename")
            return old_replace(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        original = self.source.read_bytes()
        with patch.object(m.os, "replace", side_effect=deny_hosts_replace):
            with self.assertRaisesRegex(manager.HostsManageError, "uncertain"):
                self.remove()
        self.assertEqual(self.source.read_bytes(), original)
        record = self.recovery()
        self.assertEqual(record["state"], "Not Applied")
        restored = self.restore(record["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.source.read_bytes(), original)

    def test_read_only_recovery_does_not_create_state(self):
        before = list(self.state.iterdir())
        self.assertEqual(self.recovery()["state"], "None")
        self.assertEqual(list(self.state.iterdir()), before)

    def test_reinserted_alias_can_be_removed_again_without_losing_previous_recovery(self):
        previous = self.remove()
        self.write(b"127.0.0.1 localhost\n127.0.0.2 site.test\n")
        self.assertEqual(self.recovery()["state"], "Not Applied")
        newer = self.remove()
        self.assertNotEqual(previous["recovery_id"], newer["recovery_id"])
        self.assertEqual(self.source.read_bytes(), b"127.0.0.1 localhost\n")
        archives = list(self.state.glob("ach_customizer.hosts.7.*.json"))
        self.assertEqual(len(archives), 1)
        self.assertIn(previous["recovery_id"], archives[0].name)
        self.restore(newer["recovery_id"])
        self.assertEqual(self.source.read_bytes(),
                         b"127.0.0.1 localhost\n127.0.0.2 site.test\n")

    def test_journal_restored_state_does_not_certify_subsequent_external_changes(self):
        previous = self.remove()
        self.restore(previous["recovery_id"])
        self.source.write_bytes(b"127.0.0.1 localhost\n127.0.0.7 unrelated.test\n")
        self.assertEqual(self.recovery()["state"], "Needs Review")

    def test_source_ownership_drift_keeps_read_only_diagnostic_available(self):
        applied = self.remove()
        self.source.chmod(0o666)
        self.assertEqual(self.recovery(),
                         {"state": "Needs Review", "recovery_id": applied["recovery_id"],
                          "domain": "site.test"})
        with self.assertRaises(manager.HostsManageError):
            self.restore(applied["recovery_id"])

    def test_site_identity_change_blocks_restore_even_if_file_matches(self):
        previous = self.remove()
        self.site["path"] = "/www/reassigned"
        self.assertEqual(self.recovery(),
                         {"state": "Needs Review", "recovery_id": None, "domain": None})
        with self.assertRaisesRegex(manager.HostsManageError, "Invalid hosts recovery record"):
            self.restore(previous["recovery_id"])

    def test_original_backup_integrity_required_for_restore(self):
        first = self.remove()
        backups = list(self.state.glob("*.backup"))
        self.assertEqual(len(backups), 1)
        backups[0].write_bytes(b"incorrect backup")
        with self.assertRaisesRegex(manager.HostsManageError, "integrity"):
            self.restore(first["recovery_id"])
        self.assertEqual(self.recovery()["state"], "Applied")

    def test_stale_file_change_immediately_before_replace_is_refused(self):
        import ach_customizer_hosts_manage as m
        original = m._read_source
        reads = 0
        def race(parent):
            nonlocal reads
            reads += 1
            if reads == 2:
                self.source.write_bytes(b"127.0.0.1 changed.test\n")
            return original(parent)
        with patch.object(m, "_read_source", side_effect=race):
            with self.assertRaisesRegex(manager.HostsManageError, "after review"):
                self.remove()
        self.assertEqual(self.source.read_bytes(), b"127.0.0.1 changed.test\n")
        self.assertEqual(self.recovery()["state"], "Needs Review")


class OneClickHostsTests(unittest.TestCase):
    """Actual origin file is the source, not a WP status/site inventory."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-hosts-one-click-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        directory = root / "origin"
        directory.mkdir(mode=0o700)
        self.source = directory / "hosts"
        self.state = root / "state"
        self.state.mkdir(mode=0o700)

    def write(self, payload):
        self.source.write_bytes(payload)
        self.source.chmod(0o644)

    def inspect(self):
        return manager.inspect_available_aliases(source_path=str(self.source))

    def remove(self, domain):
        return manager.remove_available_alias(
            domain=domain, source_path=str(self.source), data_dir=str(self.state))

    def test_success_and_failed_deleted_site_are_equally_visible(self):
        self.write(b"127.0.0.1 localhost\n"
                   b"127.0.0.1 success.test failed.test # peer context\r\n"
                   b"::1 failed.test\n192.0.2.3 success.test\n"
                   b"127.0.0.7 peer.test\n")
        before = self.source.read_bytes()
        snapshot = self.inspect()
        self.assertEqual(snapshot["state"], "Aliases Found")
        self.assertEqual([(x["domain"], x["address"]) for x in snapshot["entries"]],
                         [("success.test", "127.0.0.1"), ("failed.test", "127.0.0.1"),
                          ("failed.test", "::1"), ("peer.test", "127.0.0.7")])
        self.assertEqual(self.source.read_bytes(), before)
        result = self.remove("failed.test")
        self.assertEqual(result["state"], "Alias Removed")
        self.assertEqual(result["removed_aliases"], 2)
        self.assertEqual(
            self.source.read_bytes(),
            b"127.0.0.1 localhost\n"
            b"127.0.0.1 success.test # peer context\r\n"
            b"192.0.2.3 success.test\n127.0.0.7 peer.test\n")
        self.assertEqual([x["domain"] for x in self.inspect()["entries"]],
                         ["success.test", "peer.test"])
        self.assertEqual(self.remove("failed.test")["state"], "Already Absent")
        self.assertEqual(self.remove("success.test")["removed_aliases"], 1)
        self.assertEqual([x["domain"] for x in self.inspect()["entries"]], ["peer.test"])
        self.assertEqual(len(list(self.state.glob("*.backup"))), 0)

    def test_cr_only_comment_line_preserves_next_unrelated_mapping(self):
        original = (b"127.0.0.1 remove.test #note\r"
                    b"127.0.0.2 unrelated.test\n")
        self.write(original)
        before = self.inspect()
        self.assertEqual([entry["domain"] for entry in before["entries"]],
                         ["remove.test", "unrelated.test"])
        removed = self.remove("remove.test")
        self.assertEqual(removed["state"], "Alias Removed")
        self.assertEqual(removed["removed_aliases"], 1)
        self.assertEqual(self.source.read_bytes(),
                         b"#note\r127.0.0.2 unrelated.test\n")
        self.assertEqual([entry["domain"] for entry in self.inspect()["entries"]],
                         ["unrelated.test"])

    def test_last_alias_can_be_removed_to_zero_length_file(self):
        self.write(b"127.0.0.1 orphan.test")
        before = self.inspect()
        self.assertEqual(before["state"], "Aliases Found")
        self.assertEqual([entry["domain"] for entry in before["entries"]],
                         ["orphan.test"])
        removed = self.remove("orphan.test")
        self.assertTrue(removed["changed"])
        self.assertEqual(removed["removed_aliases"], 1)
        self.assertEqual(removed["state"], "Alias Removed")
        self.assertEqual(self.source.read_bytes(), b"")
        self.assertEqual(self.source.stat().st_size, 0)
        inspected = self.inspect()
        self.assertEqual(inspected["state"], "No Aliases")
        self.assertEqual(inspected["entries"], [])
        # The older selected-site diagnostic also remains usable after a
        # one-click removal empties the actual shared Hosts source.
        self.assertEqual(inspect_local_hosts(["orphan.test"],
                         source_path=str(self.source))["state"],
                         "No Local Loopback Entry")
        self.assertEqual(inspected["hosts_sha256"], hashlib.sha256(b"").hexdigest())
        again = self.remove("orphan.test")
        self.assertEqual(again["state"], "Already Absent")
        self.assertFalse(again["changed"])
        self.assertEqual(again["removed_aliases"], 0)
        self.assertEqual(self.source.read_bytes(), b"")

    def test_unrelated_malformed_or_non_utf8_lines_do_not_block_exact_removal(self):
        original = (b"invalid line without ip\n" +
                    b"bad\xff # foreign tool\n" +
                    b"127.0.0.1 localhost removable.test other.test #keep\n")
        self.write(original)
        self.assertEqual([x["domain"] for x in self.inspect()["entries"]],
                         ["removable.test", "other.test"])
        self.assertEqual(self.remove("removable.test")["state"], "Alias Removed")
        self.assertEqual(self.source.read_bytes(), (
            b"invalid line without ip\n" +
            b"bad\xff # foreign tool\n" +
            b"127.0.0.1 localhost other.test #keep\n"))

    def test_only_listed_hostname_is_eligible_and_system_names_are_preserved(self):
        self.write(b"127.0.0.1 localhost ip6-loopback other.test\n")
        original = self.source.read_bytes()
        for domain in ("localhost", "ip6-localhost", "ip6-loopback",
                       "OTHER.test", "../etc/passwd", "*.other.test", ""):
            with self.subTest(domain=domain):
                with self.assertRaises(manager.HostsManageError):
                    self.remove(domain)
                self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.inspect()["entries"][0]["domain"], "other.test")

    def test_external_edit_detected_before_publication_is_not_discarded(self):
        self.write(b"127.0.0.1 localhost\n127.0.0.1 remove.test\n")
        original = manager._read_source
        calls = 0

        def foreign_edit(parent):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.write(self.source.read_bytes() + b"127.0.0.7 foreign.test\n")
            return original(parent)

        with patch.object(manager, "_read_source", side_effect=foreign_edit):
            with self.assertRaisesRegex(manager.HostsManageError, "refresh local aliases"):
                self.remove("remove.test")
        self.assertEqual(self.source.read_bytes(),
                         b"127.0.0.1 localhost\n127.0.0.1 remove.test\n"
                         b"127.0.0.7 foreign.test\n")

    def test_uncertain_direct_write_never_fabricates_historical_restore_id(self):
        self.write(b"127.0.0.1 localhost\n127.0.0.1 remove.test\n")
        original = self.source.read_bytes()
        with patch.object(manager, "_replace_source",
                          side_effect=manager.HostsManageError(
                              "simulated private failure", "f" * 32)):
            with self.assertRaisesRegex(manager.HostsManageError,
                                        "refresh local aliases") as error:
                self.remove("remove.test")
        self.assertIsNone(error.exception.recovery_id)
        self.assertNotIn("simulated private failure", str(error.exception))
        self.assertEqual(self.source.read_bytes(), original)

    def test_symbolic_link_does_not_redirect_a_click(self):
        self.write(b"127.0.0.1 one.test\n")
        target = self.source.parent / "other"
        target.write_bytes(self.source.read_bytes())
        target.chmod(0o644)
        self.source.unlink()
        self.source.symlink_to(target)
        with self.assertRaises(OSError):
            self.remove("one.test")
        self.assertEqual(target.read_bytes(), b"127.0.0.1 one.test\n")


if __name__ == "__main__":
    unittest.main()


class NativeHostsManagementEndpointTests(unittest.TestCase):
    def setUp(self):
        import ach_customizer_main as endpoint
        self.endpoint = endpoint
        self.plugin = endpoint.ach_customizer_main()
        self.temp = tempfile.TemporaryDirectory(prefix="ach-hosts-api-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source_dir = root / "origin"
        self.source_dir.mkdir(mode=0o700)
        self.source = self.source_dir / "hosts"
        self.source.write_bytes(b"127.0.0.1 localhost\n127.0.0.2 site.test\n")
        self.source.chmod(0o644)
        self.data = root / "data"
        self.data.mkdir(mode=0o700)
        self.site = {"id": 7, "name": "site.test", "path": "/www/site.test",
                     "status": "1", "bound_domains": [{"name": "site.test", "port": 80}]}
        state_patcher = patch.object(endpoint, "_STATE_DIR", str(self.data))
        state_patcher.start()
        self.addCleanup(state_patcher.stop)
        self.read_count = 0

    @staticmethod
    def flask(uid=1, method="POST", temporary=False):
        import types
        module = types.ModuleType("flask")
        module.has_request_context = lambda: True
        module.request = types.SimpleNamespace(method=method)
        module.session = {"login": True, "uid": uid}
        if temporary:
            module.session["tmp_login"] = True
        return module

    def selected_site(self, _args):
        def current():
            self.read_count += 1
            return dict(self.site)
        return None, dict(self.site), current

    def call(self, action, *, flask=None, reviewed="true", domain="site.test", recovery_id=None):
        import ach_customizer_hosts_manage as mod
        original_remove, original_restore = mod.remove_loopback_alias, mod.restore_loopback_alias
        def removed(**kwargs):
            return original_remove(source_path=str(self.source), **kwargs)
        def restored(**kwargs):
            return original_restore(source_path=str(self.source), **kwargs)
        args = {"site_id": "7", "expected_site_key": "site.test",
                "expected_site_snapshot": "verified by stub",
                "hosts_action": action, "reviewed": reviewed,
                "domain": domain,
                "expected_hosts_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                "recovery_id": recovery_id, "source_path": "/etc/shadow"}
        with patch.dict(sys.modules, {"flask": flask or self.flask()}), \
             patch.object(self.plugin, "_selected_native_website", side_effect=self.selected_site), \
             patch.object(mod, "remove_loopback_alias", side_effect=removed), \
             patch.object(mod, "restore_loopback_alias", side_effect=restored):
            return self.plugin.manage_local_hosts(args)

    def test_one_click_source_driven_without_site_or_watcher_and_primary_admin_gate(self):
        from ach_customizer_activity import read_activity
        import ach_customizer_hosts_manage as mod
        original_inspect, original_remove = mod.inspect_available_aliases, mod.remove_available_alias
        self.source.write_bytes(
            b"127.0.0.1 localhost\n127.0.0.1 success.test failed.test\n"
            b"127.0.0.7 absent-site.test\n")
        self.source.chmod(0o644)
        def inspected(**kwargs):
            return original_inspect(source_path=str(self.source), **kwargs)
        def removed(**kwargs):
            return original_remove(source_path=str(self.source), **kwargs)

        with patch.object(mod, "inspect_available_aliases", side_effect=inspected), \
             patch.object(mod, "remove_available_alias", side_effect=removed):
            for access in (self.flask(uid=2), self.flask(temporary=True),
                           self.flask(method="GET")):
                with self.subTest(access=access.session):
                    with patch.dict(sys.modules, {"flask": access}):
                        denied = self.plugin.remove_hosts_alias({"domain":"absent-site.test"})
                        self.assertFalse(denied["status"])
                        self.assertEqual(denied["stage"], "hosts_authorization")
                        denied_read = self.plugin.inspect_hosts_aliases({})
                        self.assertFalse(denied_read["status"])
            with patch.dict(sys.modules, {"flask": self.flask()}):
                current = self.plugin.inspect_hosts_aliases({"site_id":"99999"})
                self.assertTrue(current["status"], current)
                self.assertEqual(
                    [x["domain"] for x in current["entries"]],
                    ["success.test", "failed.test", "absent-site.test"])
                self.assertEqual(self.read_count, 0)
                applied = self.plugin.remove_hosts_alias(
                    {"domain":"absent-site.test", "source_path":"/etc/shadow"})
                self.assertTrue(applied["status"], applied)
                self.assertTrue(applied["changed"])
                self.assertEqual(applied["domain"], "absent-site.test")
                self.assertEqual(applied["removed_aliases"], 1)
                again = self.plugin.remove_hosts_alias({"domain":"absent-site.test"})
                self.assertTrue(again["status"])
                self.assertEqual(again["state"], "Already Absent")
                self.assertFalse(again["changed"])
                self.assertEqual(self.read_count, 0)
        self.assertEqual(self.source.read_bytes(),
                         b"127.0.0.1 localhost\n127.0.0.1 success.test failed.test\n")
        audit = read_activity(str(self.data), module="websites")
        self.assertTrue(any(event["action"] == "remove_hosts_alias" and
                            event["target"] == "absent-site.test" and
                            event["outcome"] == "Alias Removed" for event in audit))

    def test_last_alias_authorized_endpoint_removes_to_empty_and_reinspects(self):
        import ach_customizer_hosts_manage as mod
        original_inspect, original_remove = mod.inspect_available_aliases, mod.remove_available_alias
        self.source.write_bytes(b"127.0.0.1 orphan.test")
        self.source.chmod(0o644)

        def inspected(**kwargs):
            return original_inspect(source_path=str(self.source), **kwargs)

        def removed(**kwargs):
            return original_remove(source_path=str(self.source), **kwargs)

        with patch.object(mod, "inspect_available_aliases", side_effect=inspected), \
             patch.object(mod, "remove_available_alias", side_effect=removed):
            with patch.dict(sys.modules, {"flask": self.flask(uid=2)}):
                denied = self.plugin.remove_hosts_alias({"domain": "orphan.test"})
                self.assertFalse(denied["status"])
                self.assertEqual(self.source.read_bytes(), b"127.0.0.1 orphan.test")
            with patch.dict(sys.modules, {"flask": self.flask()}):
                visible = self.plugin.inspect_hosts_aliases({})
                self.assertTrue(visible["status"])
                self.assertEqual(visible["entries"][0]["domain"], "orphan.test")
                response = self.plugin.remove_hosts_alias({"domain": "orphan.test"})
                self.assertTrue(response["status"], response)
                self.assertEqual(response["state"], "Alias Removed")
                self.assertEqual(self.source.read_bytes(), b"")
                after = self.plugin.inspect_hosts_aliases({})
                self.assertTrue(after["status"], after)
                self.assertEqual(after["state"], "No Aliases")
                self.assertEqual(after["entries"], [])
                repeated = self.plugin.remove_hosts_alias({"domain": "orphan.test"})
                self.assertTrue(repeated["status"], repeated)
                self.assertEqual(repeated["state"], "Already Absent")
                self.assertFalse(repeated["changed"])

    def test_real_source_delete_and_restore_via_panel_endpoint(self):
        original = self.source.read_bytes()
        applied = self.call("remove")
        self.assertTrue(applied["status"], applied)
        self.assertTrue(applied["activity_logged"])
        self.assertEqual(applied["state"], "Alias Removed")
        self.assertEqual(self.source.read_bytes(), b"127.0.0.1 localhost\n")
        self.assertEqual(self.read_count, 2)
        restored = self.call("restore", recovery_id=applied["recovery_id"])
        self.assertTrue(restored["status"], restored)
        self.assertTrue(restored["activity_logged"])
        self.assertEqual(self.source.read_bytes(), original)
        from ach_customizer_activity import read_activity
        logged = read_activity(str(self.data), module="websites")
        self.assertTrue(any(entry["action"] == "manage_local_hosts" and
                            entry["recovery_id"] == applied["recovery_id"] for entry in logged))

    def test_authorization_gate_blocks_non_admin_and_unreviewed(self):
        original = self.source.read_bytes()
        for access in (self.flask(uid=2), self.flask(temporary=True),
                       self.flask(method="GET")):
            with self.subTest(access=access.session):
                result = self.call("remove", flask=access)
                self.assertFalse(result["status"])
                self.assertEqual(result["stage"], "hosts_authorization")
        denied = self.call("remove", reviewed="false")
        self.assertFalse(denied["status"])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.read_count, 0)

    def test_uncertain_postwrite_failure_persists_exact_recovery_correlation(self):
        from ach_customizer_activity import read_activity
        original = self.source.read_bytes()
        original_save = manager._save_record

        def fail_after_source_write(fd, site, row):
            if row["phase"] == "applied":
                raise OSError("PRIVATE failure injected after replacement")
            return original_save(fd, site, row)

        with patch.object(manager, "_save_record", side_effect=fail_after_source_write):
            failed = self.call("remove")
        self.assertIs(failed["status"], False)
        self.assertEqual(failed["stage"], "hosts_management")
        self.assertTrue(failed["activity_logged"])
        recovery_id = failed["recovery_id"]
        self.assertRegex(recovery_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(failed["operation_id"], recovery_id)
        self.assertEqual(failed["request_id"], failed["operation_id"])
        self.assertEqual(self.source.read_bytes(), b"127.0.0.1 localhost\n")
        self.assertNotIn("PRIVATE", str(failed))

        events = read_activity(str(self.data), module="websites")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["action"], "hosts_management")
        self.assertEqual(event["stage"], "hosts_management")
        self.assertEqual(event["outcome"], "failed")
        self.assertEqual(event["error_class"], "HostsManageError")
        self.assertEqual(event["recovery_id"], recovery_id)
        self.assertEqual(event["operation_id"], failed["operation_id"])
        self.assertEqual(event["target"], "7")
        self.assertNotIn("PRIVATE", str(event))
        self.assertEqual(manager.inspect_recovery(
            self.site, source_path=str(self.source), data_dir=str(self.data)),
            {"state": "Applied", "recovery_id": recovery_id, "domain": "site.test"})

        restored = self.call("restore", recovery_id=recovery_id)
        self.assertTrue(restored["status"], restored)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(read_activity(str(self.data), module="websites")[0]["recovery_id"],
                         recovery_id)
        self.assertEqual(manager.inspect_recovery(
            self.site, source_path=str(self.source), data_dir=str(self.data))["state"],
            "restored")

    def test_uncertain_prewrite_failure_retains_recovery_and_not_applied_state(self):
        from ach_customizer_activity import read_activity
        original_replace = manager.os.replace

        def fail_source_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            if dst == "hosts":
                raise PermissionError("PRIVATE prewrite rename failure")
            return original_replace(src, dst, src_dir_fd=src_dir_fd,
                                    dst_dir_fd=dst_dir_fd)

        with patch.object(manager.os, "replace", side_effect=fail_source_replace):
            failed = self.call("remove")
        self.assertFalse(failed["status"])
        self.assertRegex(failed["recovery_id"], r"^[0-9a-f]{32}$")
        events = read_activity(str(self.data), module="websites")
        self.assertEqual(events[0]["recovery_id"], failed["recovery_id"])
        self.assertEqual(events[0]["operation_id"], failed["operation_id"])
        self.assertEqual(events[0]["target"], "7")
        self.assertNotIn("PRIVATE", str(events[0]))
        state = manager.inspect_recovery(
            self.site, source_path=str(self.source), data_dir=str(self.data))
        self.assertEqual(state["state"], "Not Applied")
        self.assertEqual(state["recovery_id"], failed["recovery_id"])

    def test_failed_hosts_authorization_and_preflight_never_fabricate_recovery(self):
        from ach_customizer_activity import read_activity
        before = self.source.read_bytes()
        for denied in (self.call("remove", flask=self.flask(uid=2)),
                       self.call("remove", reviewed="false"),
                       self.call("remove", domain="unrelated.test"),
                       self.call("restore", recovery_id="f" * 32)):
            self.assertFalse(denied["status"])
            self.assertNotIn("recovery_id", denied)
            self.assertEqual(self.source.read_bytes(), before)
        entries = read_activity(str(self.data), module="websites", limit=20)
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(row["recovery_id"] == "" for row in entries))
        # Activity is newest first: failed preflight after selection, then
        # failed authorization/approval before native site selection.
        self.assertEqual([row["target"] for row in entries], ["7", "7", "", ""])

    def test_restore_external_source_drift_logs_saved_recovery_and_needs_review(self):
        from ach_customizer_activity import read_activity
        applied = self.call("remove")
        self.assertTrue(applied["status"])
        self.source.write_bytes(b"127.0.0.1 localhost\n127.0.0.8 peer.test\n")
        denied = self.call("restore", recovery_id=applied["recovery_id"])
        self.assertFalse(denied["status"])
        self.assertEqual(denied["stage"], "hosts_management")
        self.assertEqual(denied["recovery_id"], applied["recovery_id"])
        latest = read_activity(str(self.data), module="websites")[0]
        self.assertEqual(latest["recovery_id"], applied["recovery_id"])
        self.assertEqual(latest["operation_id"], denied["operation_id"])
        self.assertEqual(latest["target"], "7")
        self.assertEqual(manager.inspect_recovery(
            self.site, source_path=str(self.source), data_dir=str(self.data))["state"],
            "Needs Review")
        self.assertEqual(self.source.read_bytes(),
                         b"127.0.0.1 localhost\n127.0.0.8 peer.test\n")

    def test_foreign_exception_recovery_id_is_not_trusted_for_hosts_failure(self):
        from ach_customizer_activity import read_activity

        class UntrustedError(RuntimeError):
            recovery_id = "a" * 32

        failed = self.plugin._fail("hosts_management", UntrustedError("private"),
                                   "c" * 32)
        self.assertFalse(failed["status"])
        self.assertNotIn("recovery_id", failed)
        self.assertEqual(read_activity(str(self.data), module="websites")[0]["recovery_id"], "")

    def test_unbound_alias_and_wrong_recovery_refused_without_modification(self):
        before = self.source.read_bytes()
        wrong = self.call("remove", domain="unrelated.test")
        self.assertFalse(wrong["status"])
        self.assertEqual(wrong["stage"], "hosts_management")
        self.assertEqual(self.source.read_bytes(), before)
        wrong_rec = self.call("restore", recovery_id="a"*32)
        self.assertFalse(wrong_rec["status"])
        self.assertEqual(self.source.read_bytes(), before)
