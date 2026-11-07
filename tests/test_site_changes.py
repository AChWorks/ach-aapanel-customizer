"""Native site lifecycle baseline: bounded source-only regressions."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugin" / "ach_customizer"))
from ach_customizer_site_changes import (
    BASELINE_FILE, SiteChangesError, compare, read_baseline, save_reviewed_baseline,
)


class Query:
    def __init__(self, panel, table):
        self.panel, self.table = panel, table
        self.start, self.count, self.pids = 0, 0, []

    def order(self, value):
        assert value == ("id asc" if self.table == "sites" else "pid asc, id asc")
        return self

    def limit(self, value):
        self.start, self.count = map(int, value.split(","))
        return self

    def field(self, value):
        assert value == ("id,name,path,status" if self.table == "sites" else "id,pid,name,port")
        return self

    def where(self, clause, values):
        assert clause == "pid IN (" + ",".join("?" for _ in values) + ")"
        self.pids = values
        return self

    def select(self):
        if self.table == "sites":
            self.panel.site_queries += 1
            if self.panel.on_site_scan:
                self.panel.on_site_scan(self.panel.site_queries)
            return [dict(v) for v in self.panel.sites[self.start:self.start + self.count]]
        return [dict(v) for v in self.panel.domains if v["pid"] in self.pids][
            self.start:self.start + self.count]


class Panel:
    def __init__(self):
        self.sites = [
            {"id": 3, "name": "static.example.test", "path": "/srv/static", "status": 1},
            {"id": 6, "name": "wp.example.test", "path": "/srv/wp", "status": 1},
        ]
        self.domains = [
            {"id": 13, "pid": 3, "name": "static.example.test", "port": 80},
            {"id": 16, "pid": 6, "name": "wp.example.test", "port": 443},
        ]
        self.site_queries = 0
        self.on_site_scan = None

    def M(self, table):
        assert table in ("sites", "domain")
        return Query(self, table)


class SiteChangesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ach-site-baseline-")
        self.addCleanup(self.directory.cleanup)
        self.panel = Panel()

    def preview(self):
        return compare(self.panel, directory=self.directory.name)

    def save(self, preview, *, reviewed="true", revision=None, digest=None):
        return save_reviewed_baseline(
            self.panel, directory=self.directory.name,
            expected_revision=preview["baseline_revision"] if revision is None else revision,
            expected_monitor_revision=preview["monitor_revision"],
            expected_source_sha256=preview["source_sha256"] if digest is None else digest,
            reviewed=reviewed)

    def test_explicit_baseline_new_renamed_removed_domain_and_noop(self):
        initial = self.preview()
        self.assertEqual(initial["state"], "Baseline Missing")
        self.assertEqual(initial["changes"], [])
        self.assertFalse(Path(self.directory.name, BASELINE_FILE).exists())
        saved = self.save(initial)
        self.assertTrue(saved["changed"])
        self.assertEqual(saved["baseline_revision"], 1)
        self.assertEqual(self.preview()["state"], "No Changes")
        self.assertFalse(self.save(self.preview())["changed"])
        self.panel.sites[1].update(name="renamed.example.test", path="/srv/moved")
        self.panel.domains[1]["name"] = "new-bound.example.test"
        self.panel.sites.append(
            {"id": 9, "name": "new.example.test", "path": "/srv/new", "status": 0})
        self.panel.sites.pop(0)
        self.panel.domains.pop(0)
        drift = self.preview()
        self.assertEqual(drift["state"], "Changes Observed")
        self.assertEqual([(e["id"], e["kind"]) for e in drift["changes"]],
                         [(3, "Removed"), (6, "Changed"), (9, "Added")])
        self.assertEqual(drift["changes"][1]["fields"],
                         ["name", "document_root", "bound_domains"])
        self.assertFalse(drift["runtime_verified"])
        self.assertTrue(drift["read_only"])
        self.assertIn("No effective Nginx routing", drift["note"])
        self.assertEqual(self.save(drift)["baseline_revision"], 2)
        self.assertEqual(self.preview()["state"], "No Changes")
        self.assertEqual(read_baseline(self.directory.name)["revision"], 2)

    def test_confirmation_stale_source_and_revision_fail_closed(self):
        initial = self.preview()
        with self.assertRaisesRegex(SiteChangesError, "review confirmation"):
            self.save(initial, reviewed=False)
        self.assertFalse(Path(self.directory.name, BASELINE_FILE).exists())
        self.panel.sites[0]["status"] = 0
        with self.assertRaisesRegex(SiteChangesError, "changed since comparison"):
            self.save(initial)
        fresh = self.preview()
        self.save(fresh)
        with self.assertRaisesRegex(SiteChangesError, "revision changed"):
            self.save(fresh)
        with self.assertRaisesRegex(SiteChangesError, "source fingerprint"):
            self.save(self.preview(), digest="x" * 64)
        self.assertEqual(read_baseline(self.directory.name)["revision"], 1)

    def test_double_scan_detects_change_without_partial_write(self):
        def mutate(call):
            if call == 2:
                self.panel.sites[0]["status"] = 0
        self.panel.on_site_scan = mutate
        with self.assertRaisesRegex(SiteChangesError, "changed during inspection"):
            self.preview()
        self.assertFalse(Path(self.directory.name, BASELINE_FILE).exists())

    def test_locked_rescan_rejects_race(self):
        initial = self.preview()  # site-query #2
        def mutate(call):
            if call == 6:
                self.panel.sites[0]["status"] = 0
        self.panel.on_site_scan = mutate
        with self.assertRaisesRegex(SiteChangesError, "changed during inspection"):
            self.save(initial)
        self.assertFalse(Path(self.directory.name, BASELINE_FILE).exists())

    def test_too_many_duplicate_and_invalid_domains(self):
        self.panel.sites = [
            {"id": i, "name": f"site{i}.test", "path": "/srv/x", "status": 1}
            for i in range(1, 102)]
        with self.assertRaisesRegex(SiteChangesError, "More than 100"):
            self.preview()
        self.panel.sites = self.panel.sites[:2]
        self.panel.sites[1]["id"] = 1
        with self.assertRaisesRegex((SiteChangesError, RuntimeError), "Duplicate|Unsorted|duplicate"):
            self.preview()
        self.panel.sites[1]["id"] = 2
        self.panel.domains[0]["pid"] = 1
        self.panel.domains[0]["port"] = 0
        with self.assertRaisesRegex((SiteChangesError, RuntimeError), "invalid|Invalid"):
            self.preview()

    def test_strict_native_fields_reject_lossy_records_without_baseline(self):
        for field, value in (
            ("path", None), ("path", ""), ("path", 42),
            ("status", None), ("status", False), ("status", []),
            ("id", True), ("id", 2.0), ("id", "0003"),
        ):
            with self.subTest(field=field, value=value):
                original = self.panel.sites[0][field]
                self.panel.sites[0][field] = value
                try:
                    with self.assertRaises((SiteChangesError, RuntimeError)):
                        self.preview()
                    self.assertFalse(Path(self.directory.name, BASELINE_FILE).exists())
                finally:
                    self.panel.sites[0][field] = original
        # Legitimate integer/string native status representations remain
        # observable and changing them triggers a comparison.
        initial = self.preview()
        self.save(initial)
        self.panel.sites[0]["status"] = "0"
        changed = self.preview()
        self.assertEqual(changed["state"], "Changes Observed")
        self.assertIn("panel_status", changed["changes"][0]["fields"])

    def test_bounded_domain_pagination_preserves_100_by_24_capacity(self):
        self.panel.sites = [
            {"id": i, "name": f"site{i}.test", "path": f"/srv/{i}", "status": 1}
            for i in range(1, 101)
        ]
        for count in (10, 11, 24):
            with self.subTest(bindings_per_site=count):
                self.panel.domains = [
                    {"id": i * 100 + j, "pid": i,
                     "name": f"alias{j}.site{i}.test", "port": 80 + j}
                    for i in range(1, 101) for j in range(count)
                ]
                observed = self.preview()
                self.assertEqual(observed["site_count"], 100)
                records = (observed["initial_sites"] if count == 10 else
                           [item["after"] for item in observed["changes"]])
                self.assertEqual(len(records), 100)
                self.assertEqual(len(records[30]["bound_domains"]), count)
                self.assertEqual(self.save(observed)["state"], "Baseline Saved")
                self.assertEqual(self.preview()["state"], "No Changes")
        self.panel.sites.append(
            {"id": 101, "name": "overflow.test", "path": "/srv/overflow", "status": 1}
        )
        with self.assertRaisesRegex(SiteChangesError, "More than 100"):
            self.preview()

    def test_domain_id_reused_across_batches_and_midpage_drift_fail_closed(self):
        self.panel.sites = [
            {"id": i, "name": f"site{i}.test", "path": f"/srv/{i}", "status": 1}
            for i in range(1, 22)
        ]
        self.panel.domains = [
            {"id": 10, "pid": 1, "name": "one.test", "port": 80},
            {"id": 10, "pid": 21, "name": "twentyone.test", "port": 80},
        ]
        with self.assertRaisesRegex(SiteChangesError, "duplicated across"):
            self.preview()
        self.panel.domains[1]["id"] = 11
        self.panel.site_queries = 0
        def change(call):
            if call == 3:
                self.panel.domains[1]["name"] = "drift.test"
        self.panel.on_site_scan = change
        with self.assertRaisesRegex(SiteChangesError, "changed during inspection"):
            self.preview()

    def test_monitor_policy_races_and_revision_cas_reject_commit(self):
        from ach_customizer_state import read_state, set_enabled
        for key in ("overall", "site_inventory"):
            with self.subTest(disabled=key):
                self.panel = Panel()
                with tempfile.TemporaryDirectory(prefix="ach-site-policy-race-") as directory:
                    baseline = compare(self.panel, directory=directory)
                    def toggle(call):
                        if call == 4:
                            set_enabled(key, False, directory=directory,
                                        expected_revision=0)
                    self.panel.on_site_scan = toggle
                    with self.assertRaisesRegex(SiteChangesError, "disabled"):
                        save_reviewed_baseline(
                            self.panel, directory=directory,
                            expected_revision=0, expected_monitor_revision=0,
                            expected_source_sha256=baseline["source_sha256"],
                            reviewed="true")
                    self.assertFalse(Path(directory, BASELINE_FILE).exists())
        self.panel = Panel()
        preview = self.preview()
        set_enabled("php_fpm_file_preview", False,
                    directory=self.directory.name, expected_revision=0)
        self.assertEqual(read_state(self.directory.name)["revision"], 1)
        with self.assertRaisesRegex(SiteChangesError, "Monitor revision changed"):
            self.save(preview)
        self.assertFalse(Path(self.directory.name, BASELINE_FILE).exists())

    def test_baseline_atomic_faults_and_uncertain_rename_reconciliation(self):
        import ach_customizer_site_changes as site_changes
        initial = self.preview()
        target = Path(self.directory.name, BASELINE_FILE)
        with patch.object(site_changes.os, "fsync", side_effect=OSError("file fsync fault")):
            with self.assertRaises(OSError):
                self.save(initial)
        self.assertFalse(target.exists())
        self.assertFalse(list(Path(self.directory.name).glob(".ach_customizer.sites.*.tmp")))
        with patch.object(site_changes.os, "replace", side_effect=OSError("rename fault")):
            with self.assertRaises(OSError):
                self.save(initial)
        self.assertFalse(target.exists())

        class InterruptedStream:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def write(self, data):
                raise OSError("partial original baseline write")
        with patch.object(site_changes.os, "fdopen", return_value=InterruptedStream()):
            with self.assertRaisesRegex(OSError, "partial"):
                self.save(initial)
        self.assertFalse(target.exists())
        self.assertFalse(list(Path(self.directory.name).glob(".ach_customizer.sites.*.tmp")))

        actual_fsync = site_changes.os.fsync
        counts = 0
        def after_replace(fd):
            nonlocal counts
            counts += 1
            if counts == 2:
                raise OSError("directory fsync uncertain")
            return actual_fsync(fd)
        with patch.object(site_changes.os, "fsync", side_effect=after_replace):
            with self.assertRaisesRegex(SiteChangesError, "uncertain"):
                self.save(initial)
        self.assertEqual(counts, 2)
        self.assertEqual(read_baseline(self.directory.name)["revision"], 1)
        latest = self.preview()
        self.assertEqual(latest["state"], "No Changes")
        with self.assertRaisesRegex(SiteChangesError, "revision changed"):
            self.save(initial)
        self.assertEqual(self.save(latest)["state"], "Baseline Unchanged")
        self.assertEqual(read_baseline(self.directory.name)["revision"], 1)
        self.assertFalse(list(Path(self.directory.name).glob(".ach_customizer.sites.*.tmp")))

    def test_stray_temp_and_hardlinks_cannot_fabricate_recovery(self):
        root = Path(self.directory.name)
        stray = root / ".ach_customizer.sites.crashed.tmp"
        stray.write_text("incomplete staging artifact")
        stray.chmod(0o600)
        observed = self.preview()
        self.assertEqual(observed["state"], "Baseline Missing")
        self.save(observed)
        self.assertEqual(stray.read_text(), "incomplete staging artifact")
        baseline = root / BASELINE_FILE
        mirror = root / "unexpected-hardlink"
        os.link(baseline, mirror)
        with self.assertRaisesRegex(SiteChangesError, "Untrusted"):
            self.preview()
        self.assertEqual(mirror.read_bytes(), baseline.read_bytes())

    def test_tamper_permissions_and_linked_baseline_fail_closed(self):
        self.save(self.preview())
        target = Path(self.directory.name, BASELINE_FILE)
        original = target.read_bytes()
        tampered = json.loads(original)
        tampered["sites"][0]["name"] = "wrong.test"
        target.write_text(json.dumps(tampered))
        with self.assertRaisesRegex(SiteChangesError, "baseline fingerprint"):
            self.preview()
        target.unlink()
        outside = Path(self.directory.name, "preserved.json")
        outside.write_bytes(original)
        target.symlink_to(outside)
        with self.assertRaisesRegex(SiteChangesError, "baseline"):
            self.preview()
        self.assertEqual(outside.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()


class NativeEndpointTests(unittest.TestCase):
    """Security/Monitor contract exercises the actual plugin class routing."""

    def setUp(self):
        import importlib.util
        import types
        from unittest.mock import patch
        self.temp = tempfile.TemporaryDirectory(prefix="ach-site-endpoint-")
        self.addCleanup(self.temp.cleanup)
        spec = importlib.util.spec_from_file_location(
            "ach_customizer_site_endpoint_main", Path(__file__).resolve().parent.parent
            / "plugin" / "ach_customizer" / "ach_customizer_main.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        state_patch = patch.object(self.module, "_STATE_DIR", self.temp.name)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.flask = types.ModuleType("flask")
        self.flask.session = {"uid": 1, "login": True}
        self.flask.request = types.SimpleNamespace(method="POST")
        self.flask.has_request_context = lambda: True
        self.panel = Panel()
        self.public = types.ModuleType("public")
        self.public.M = self.panel.M
        flask_patch = patch.dict(sys.modules, {"flask": self.flask, "public": self.public})
        flask_patch.start()
        self.addCleanup(flask_patch.stop)
        self.controller = self.module.ach_customizer_main()

    def test_full_primary_admin_only_and_read_only_compare(self):
        for session, method in [
            ({"uid": 2, "login": True}, "POST"),
            ({"uid": 1, "login": True, "tmp_login_id": ""}, "POST"),
            ({"uid": 1, "login": True, "tmp_login": True}, "POST"),
            ({"uid": 1, "login": True}, "GET"),
            ({"uid": 1, "login": False}, "POST"),
        ]:
            with self.subTest(session=session, method=method):
                self.flask.session = session
                self.flask.request.method = method
                for endpoint in ("compare_site_changes", "save_site_baseline"):
                    denied = getattr(self.controller, endpoint)({})
                    self.assertFalse(denied["status"], denied)
                    self.assertIn("authorization", denied["stage"])
        self.flask.session = {"uid": 1, "login": True}
        self.flask.request.method = "POST"
        value = self.controller.compare_site_changes({})
        self.assertTrue(value["status"], value)
        self.assertEqual(value["state"], "Baseline Missing")
        self.assertFalse(value["runtime_verified"])
        refused = self.controller.save_site_baseline({})
        self.assertFalse(refused["status"])
        self.assertEqual(refused["stage"], "website_baseline_save")
        self.assertFalse(Path(self.temp.name, BASELINE_FILE).exists())
        saved = self.controller.save_site_baseline({
            "expected_revision": "0", "expected_monitor_revision": "0",
            "expected_source_sha256": value["source_sha256"], "reviewed": "true"
        })
        self.assertTrue(saved["status"], saved)
        self.assertEqual(saved["baseline_revision"], 1)
        self.assertTrue(Path(self.temp.name, BASELINE_FILE).exists())

    def test_disabled_monitor_blocks_both_site_lifecycle_endpoints(self):
        from ach_customizer_state import set_enabled
        set_enabled("site_inventory", False, directory=self.temp.name, expected_revision=0)
        for endpoint in ("compare_site_changes", "save_site_baseline"):
            denied = getattr(self.controller, endpoint)({})
            self.assertFalse(denied["status"])
            self.assertIn("disabled", denied["msg"])
        self.assertFalse(Path(self.temp.name, BASELINE_FILE).exists())
