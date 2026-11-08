"""Isolated native extension 404/502 transaction tests; no real nginx reload."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_status_extension as extension


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-status-ext-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vhost_root = self.root / "nginx"
        self.vhost_root.mkdir()
        self.ext = self.vhost_root / "extension" / "demo.invalid"
        self.ext.mkdir(parents=True)
        self.public = self.root / "public"
        self.public.mkdir()
        self.site_root = self.root / "sites" / "demo.invalid"
        self.site_root.mkdir(parents=True)
        self.vhost = self.vhost_root / "demo.invalid.conf"
        self.vhost.write_text(
            "server {\nlisten 80;\nlisten 443 ssl;\n"
            "server_name demo.invalid;\n"
            "root " + str(self.site_root) + ";\n"
            "error_page 404 /404.html;\nerror_page 502 /502.html;\n"
            "include " + str(self.ext) + "/*.conf;\n}\n")
        self.nginx_conf = self.root / "nginx.conf"
        self.nginx_conf.write_text(
            "events { worker_connections 100; }\n"
            "http {\n include " + str(self.vhost_root) + "/*.conf;\n}\n")
        self.site = {"id": 7, "name": "demo.invalid", "path": str(self.site_root),
                     "status": "1",
                     "bound_domains": [{"name": "demo.invalid", "port": 80},
                                       {"name": "demo.invalid", "port": 443}]}
        self.state = self.root / "state"
        self.state.mkdir()
        self.data_fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.data_fd)
        self.code = "404"
        self.html = "<html><body>New page</body></html>"
        self.after = hashlib.sha256(self.html.encode()).hexdigest()
        self.before = hashlib.sha256(b"previous website 404").hexdigest()
        self.other = self.root / "other.test"
        self.other.write_bytes(b"Untouched non-target bytes")
        self.commands = []

    def runner(self, args, *, capture_output, timeout, check):
        self.commands.append(tuple(args))
        return SimpleNamespace(returncode=0, stderr=b"")

    def probe(self, site, code, operation):
        if operation is None:
            return (404, self.before, None)
        inc = self.ext / extension._include_name(site["id"], code)
        if inc.exists():
            return (extension._expected_status(code), self.after, operation)
        return (404, self.before, None)

    def run_manager(self, action="apply", **kw):
        return extension.manage_site_extension(
            action, self.site, code=kw.get("code", self.code),
            html=kw.get("html", self.html),
            expected_current=kw.get(
                "current", self.before if kw.get("code", self.code) == "404"
                else hashlib.sha256(b"").hexdigest()),
            expected_vhost=(kw["vhost"] if "vhost" in kw else hashlib.sha256(self.vhost.read_bytes()).hexdigest()),
            expected_render=kw.get("render", self.after),
            expected_recovery=kw.get("recovery"),
            data_fd=self.data_fd, vhost_root=str(self.vhost_root),
            public_root=str(self.public / ".pages"),
            nginx="/usr/sbin/nginx", nginx_conf=str(self.nginx_conf),
            runner=self.runner, probe=self.probe)

    def test_apply_recheck_restore_for_404_502_and_50x(self):
        for code in extension.CODES:
            with self.subTest(code=code):
                self.code = code
                self.assertEqual(self.run_manager("recheck")["state"], "Unmanaged")
                applied = self.run_manager()
                self.assertEqual(applied["state"], "Applied")
                self.assertEqual(self.run_manager("recheck")["state"], "Applied")
                content = (self.ext / extension._include_name(7, code)).read_text()
                self.assertIn("location = /" + ("502" if code == "50x" else code) + ".html", content)
                if code == "50x":
                    self.assertIn("error_page 500 503 504", content)
                    for status in extension.FIFTY_CODES:
                        self.assertIn(".__ach_customizer_proof_" + applied["recovery_id"] + "_" + status, content)
                self.assertIn("internal;", content)
                self.assertIn("allow 127.0.0.1;", content)
                self.assertNotIn(str(self.site_root) + "/" + code + ".html", content)
                self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")
                restored = self.run_manager("restore", recovery=applied["recovery_id"])
                expected_state = "Restored" if code == "404" else "Source Restored"
                self.assertEqual(restored["state"], expected_state)
                rechecked = self.run_manager("recheck")
                self.assertEqual(rechecked["state"], expected_state)
                self.assertEqual(rechecked["page_file_sha256"], rechecked["before_sha256"])
                if code in ("502", "50x"):
                    self.assertFalse(restored["runtime_verified"])
                    self.assertFalse(rechecked["runtime_verified"])
                    self.assertEqual(restored["verification_scope"], "source_and_nonce_only")
                    self.assertEqual(rechecked["verification_scope"], "source_and_nonce_only")
                else:
                    self.assertTrue(rechecked["runtime_verified"])
                self.assertFalse((self.ext / extension._include_name(7, code)).exists())
                self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")
        self.assertEqual(sum("reload" in cmd for cmd in self.commands), 6)

    def test_native_stop_start_retains_recovery_record(self):
        applied = self.run_manager()
        op = applied["recovery_id"]
        self.site["status"] = "0"
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("restore", recovery=op)
        stopped = self.run_manager("recheck")
        self.assertEqual(stopped["state"], "Suspended")
        self.assertEqual(stopped["recovery_id"], op)
        self.assertEqual(stopped["journal_phase"], "applied")
        self.assertEqual(stopped["verification_scope"], "saved_journal_only")
        self.assertFalse(stopped["runtime_verified"])
        self.assertFalse(stopped["changed"])
        self.site["status"] = "1"
        self.assertEqual(self.run_manager("recheck")["state"], "Applied")
        self.assertEqual(self.run_manager("restore", recovery=op)["state"], "Restored")

    def test_regenerated_vhost_keeps_inspectable_saved_recovery(self):
        applied = self.run_manager()
        original = self.vhost.read_bytes()
        self.vhost.write_bytes(original.replace(
            b"error_page 404 /404.html;", b"error_page 404 /changed.html;"))
        observed = self.run_manager("recheck")
        self.assertEqual(observed["state"], "Needs Review")
        self.assertEqual(observed["recovery_id"], applied["recovery_id"])
        self.assertEqual(observed["journal_phase"], "applied")
        self.assertEqual(observed["verification_scope"], "saved_journal_only")
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("restore", recovery=applied["recovery_id"])
        self.vhost.write_bytes(original)
        self.assertEqual(self.run_manager("recheck")["state"], "Applied")
        self.assertEqual(
            self.run_manager("restore", recovery=applied["recovery_id"])["state"], "Restored")

    def test_temporarily_missing_vhost_retains_saved_recovery_visibility(self):
        applied = self.run_manager()
        backup = self.vhost.read_bytes()
        old_vhost_sha = hashlib.sha256(backup).hexdigest()
        self.vhost.unlink()
        inspected = self.run_manager("recheck", vhost=old_vhost_sha)
        self.assertEqual(inspected["state"], "Needs Review")
        self.assertEqual(inspected["verification_scope"], "saved_journal_only")
        self.assertEqual(inspected["recovery_id"], applied["recovery_id"])
        with self.assertRaises((extension.ExtensionError, OSError)):
            self.run_manager("restore", recovery=applied["recovery_id"],
                             vhost=old_vhost_sha)
        self.vhost.write_bytes(backup)
        self.assertEqual(self.run_manager("recheck")["state"], "Applied")
        self.assertEqual(self.run_manager("restore", recovery=applied["recovery_id"])["state"], "Restored")

    def test_stopped_unmanaged_site_cannot_invent_recovery(self):
        self.site["status"] = "0"
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("recheck")
        self.assertEqual(list(self.state.iterdir()), [])

    def test_rejects_stale_hash_and_unknown_root_and_unsafe_owner(self):
        for options in ({"current": "0" * 64}, {"vhost": "0" * 64},
                        {"render": "0" * 64}):
            with self.subTest(options=options), self.assertRaises(extension.ExtensionError):
                self.run_manager(**options)
        self.assertFalse(list(self.state.iterdir()))
        self.ext.chmod(0o777)
        with self.assertRaises(extension.ExtensionError):
            self.run_manager()
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_independent_snippet_is_not_overwritten(self):
        path = self.ext / extension._include_name(7, "404")
        path.write_bytes(b"independent owner snippet")
        with self.assertRaises(extension.ExtensionError):
            self.run_manager()
        self.assertEqual(path.read_bytes(), b"independent owner snippet")
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_stale_502_preview_never_creates_journal(self):
        with self.assertRaises(extension.ExtensionError) as error:
            self.run_manager(code="502", current="0" * 64)
        self.assertEqual(error.exception.stage, "concurrency")
        self.assertFalse(list(self.state.iterdir()))

    def test_wrong_recovery_id_blocks_restore(self):
        applied = self.run_manager()
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("restore", recovery="f" * 32)
        self.assertEqual(self.run_manager("recheck")["state"], "Applied")
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_second_syntax_failure_retains_recovery_without_reload(self):
        calls = [0]
        def failed_second_syntax(args, **kwargs):
            self.commands.append(tuple(args))
            if "-t" in args:
                calls[0] += 1
                if calls[0] == 2:
                    return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)
        self.runner = failed_second_syntax
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "recovered")
        self.assertFalse(any("-s" in a for a in self.commands))
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        recovery = self.run_manager("recheck")["recovery_id"]
        self.assertTrue(recovery)
        self.assertEqual(self.run_manager("restore", recovery=recovery)["state"], "Restored")
        self.assertFalse((self.ext / extension._include_name(7, "404")).exists())
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_reload_failure_recheck_then_explicit_restore(self):
        attempted = [False]
        def failed_first_reload(args, **kwargs):
            self.commands.append(tuple(args))
            if "-s" in args and not attempted[0]:
                attempted[0] = True
                return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)
        self.runner = failed_first_reload
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertTrue(attempted[0])
        snapshot = self.run_manager("recheck")
        self.assertEqual(snapshot["state"], "Recovery Required")
        self.assertEqual(snapshot["recovery_id"], err.exception.recovery_id)
        out = self.run_manager("restore", recovery=snapshot["recovery_id"])
        self.assertEqual(out["state"], "Restored")
        self.assertEqual(self.run_manager("recheck")["state"], "Restored")
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_interrupted_restore_retries_only_with_approved_recovery(self):
        applied = self.run_manager()
        attempts = [0]
        def interrupted_restore_reload(args, **kwargs):
            self.commands.append(tuple(args))
            if "-s" in args:
                attempts[0] += 1
                if attempts[0] == 1:
                    return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)
        self.runner = interrupted_restore_reload
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager("restore", recovery=applied["recovery_id"])
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertFalse((self.ext / extension._include_name(7, "404")).exists())
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("restore", recovery="a" * 32)
        good = self.run_manager("restore", recovery=applied["recovery_id"])
        self.assertEqual(good["state"], "Restored")
        self.assertEqual(self.run_manager("recheck")["state"], "Restored")

    def test_cross_site_extension_sharing_is_rejected(self):
        another = self.vhost_root / "other.invalid.conf"
        another.write_text(
            "server {\nserver_name other.invalid;\n"
            "include " + str(self.ext) + "/*.conf;\n}\n")
        with self.assertRaises(extension.ExtensionError) as error:
            self.run_manager()
        self.assertEqual(error.exception.stage, "ownership")
        self.assertFalse(list(self.state.iterdir()))
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_site_source_root_mismatch_is_rejected(self):
        self.vhost.write_text(self.vhost.read_text().replace(
            "root " + str(self.site_root), "root " + str(self.other)))
        with self.assertRaises(extension.ExtensionError) as error:
            self.run_manager()
        self.assertEqual(error.exception.stage, "source")
        self.assertFalse(list(self.state.iterdir()))

    def test_retained_destination_cannot_be_overwritten(self):
        applied = self.run_manager()
        record = json.loads((self.state / extension._record_name(7, "404")).read_text())
        retained = self.ext / extension._retained_name(7, "404", applied["recovery_id"])
        retained.write_text("foreign entry")
        retained.chmod(0o600)
        with self.assertRaises(extension.ExtensionError) as error:
            self.run_manager("restore", recovery=applied["recovery_id"])
        self.assertEqual(error.exception.stage, "recovery")
        self.assertEqual(retained.read_text(), "foreign entry")
        self.assertTrue((self.ext / extension._include_name(7, "404")).exists())
        self.assertEqual(record["phase"], "applied")

    def test_indirect_selected_vhost_import_from_other_scope_fails_closed(self):
        # Even if the canonical VHost is reachable only once, importing it
        # inside another server is not the native top-level ownership path.
        other = self.vhost_root / "other.invalid.conf"
        other.write_text(
            "server {\nserver_name other.invalid;\n"
            "include " + str(self.vhost) + ";\n}\n")
        self.nginx_conf.write_text(
            "http { include " + str(other) + "; }\n")
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "ownership")
        self.assertFalse(list(self.state.iterdir()))

    def test_empty_native_rewrite_include_is_valid_source(self):
        rewrite = self.root / "empty-rewrite.conf"
        rewrite.write_bytes(b"")
        self.vhost.write_text(self.vhost.read_text().replace(
            "error_page 502 /502.html;\n",
            "error_page 502 /502.html;\ninclude " + str(rewrite) + ";\n"))
        applied = self.run_manager()
        self.assertEqual(applied["state"], "Applied")
        self.assertEqual(self.run_manager("restore",
                         recovery=applied["recovery_id"])["state"], "Restored")

    def test_partial_stage_fsync_failure_preserves_prepared_journal(self):
        from unittest.mock import patch
        original = extension.os.fsync
        injected = [False]
        def reject_stage(fd):
            try:
                name = os.readlink("/proc/self/fd/" + str(fd))
            except OSError:
                name = ""
            if ".conf." in name and name.endswith(".stage") and not injected[0]:
                injected[0] = True
                raise OSError(5, "simulated staged-file fsync failure")
            return original(fd)
        with patch.object(extension.os, "fsync", side_effect=reject_stage):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertTrue(injected[0])
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        self.assertFalse((self.ext / extension._include_name(7, "404")).exists())
        self.assertEqual(
            self.run_manager("restore", recovery=err.exception.recovery_id)["state"],
            "Restored")

    def test_concurrent_foreign_conf_before_publication_is_preserved(self):
        from unittest.mock import patch
        original = extension._rename_noreplace
        def competitor(fd, before, after):
            if after.endswith(".conf"):
                descriptor = os.open(
                    after, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600,
                    dir_fd=fd)
                try:
                    os.write(descriptor, b"foreign operator owned config")
                finally:
                    os.close(descriptor)
            return original(fd, before, after)
        with patch.object(extension, "_rename_noreplace", side_effect=competitor):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        candidate = self.ext / extension._include_name(7, "404")
        self.assertEqual(candidate.read_bytes(), b"foreign operator owned config")
        self.assertFalse(any("-s" in args for args in self.commands))
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("restore", recovery=err.exception.recovery_id)
        self.assertEqual(candidate.read_bytes(), b"foreign operator owned config")

    def test_502_old_nonce_remains_visible_after_restore_is_uncertain(self):
        from unittest.mock import patch
        applied = self.run_manager(code="502")
        original = self.probe
        def old_worker(site, code, operation):
            if code == "502" and operation is not None:
                return (502, self.after, operation)
            return original(site, code, operation)
        self.probe = old_worker
        counter = [0]
        def tick():
            counter[0] += 10
            return counter[0]
        with patch.object(extension.time, "monotonic", side_effect=tick):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager("restore", code="502",
                                 recovery=applied["recovery_id"])
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(err.exception.recovery_id, applied["recovery_id"])
        self.probe = original
        self.assertEqual(self.run_manager("restore", code="502",
                         recovery=applied["recovery_id"])["state"], "Source Restored")

    def test_502_uninspectable_symlink_cannot_be_treated_as_absent(self):
        untrusted = self.site_root / "502.html"
        untrusted.symlink_to(self.other)
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager(code="502")
        self.assertEqual(err.exception.stage, "source")
        self.assertFalse(list(self.state.iterdir()))
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_new_other_site_import_after_reload_is_not_positive_apply(self):
        another = self.vhost_root / "other.invalid.conf"
        original_runner = self.runner
        def inject_on_reload(args, **kwargs):
            if "-s" in args and "reload" in args:
                another.write_text(
                    "server {\nserver_name other.invalid;\n"
                    "include " + str(self.vhost_root / "extension") + "/*/*.conf;\n}\n")
            return original_runner(args, **kwargs)
        self.runner = inject_on_reload
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertTrue(err.exception.recovery_id)
        journal = json.loads(
            (self.state / extension._record_name(7, "404")).read_text())
        self.assertEqual(journal["phase"], "prepared")
        another.unlink()
        self.runner = original_runner
        self.assertEqual(self.run_manager("restore",
                         recovery=err.exception.recovery_id)["state"], "Restored")

    def test_broad_wildcard_import_into_non_target_is_rejected_before_write(self):
        other = self.vhost_root / "other.invalid.conf"
        other.write_text(
            "server {\nserver_name other.invalid;\n"
            "include " + str(self.vhost_root / "extension") + "/*/*.conf;\n}\n")
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "ownership")
        self.assertFalse(list(self.state.iterdir()))
        self.assertFalse(any("-s" in cmd for cmd in self.commands))

    def test_indirect_non_target_include_is_rejected_before_write(self):
        other = self.vhost_root / "other.invalid.conf"
        shared = self.root / "shared-routes.conf"
        shared.write_text(
            "include " + str(self.ext) + "/*.conf;\n")
        other.write_text(
            "server {\nserver_name other.invalid;\n"
            "include " + str(shared) + ";\n}\n")
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "ownership")
        self.assertFalse(list(self.state.iterdir()))

    def test_duplicate_selected_vhost_import_is_rejected(self):
        extra = self.vhost_root / "extra.invalid.conf"
        extra.write_text("include " + str(self.vhost) + ";\n")
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "ownership")
        self.assertFalse(list(self.state.iterdir()))

    def test_unproven_or_unreadable_nginx_include_graph_fails_closed(self):
        self.nginx_conf.write_text(
            "http {\n include " + str(self.vhost_root) + "/not-loaded/*.conf;\n}\n")
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager()
        self.assertEqual(err.exception.stage, "ownership")
        self.assertFalse(list(self.state.iterdir()))

    def test_partial_live_conf_write_is_inert_and_recoverable(self):
        from unittest.mock import patch
        original = extension._write_exclusive
        partial = []
        def fail_stage(fd, name, payload, mode):
            if ".conf." in name and name.endswith(".stage"):
                descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                     0o600, dir_fd=fd)
                try:
                    os.write(descriptor, payload[:13])
                finally:
                    os.close(descriptor)
                partial.append(name)
                raise OSError(5, "simulated partial staged write")
            return original(fd, name, payload, mode)
        with patch.object(extension, "_write_exclusive", side_effect=fail_stage):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertTrue(err.exception.recovery_id)
        self.assertEqual(len(partial), 1)
        self.assertFalse((self.ext / extension._include_name(7, "404")).exists())
        self.assertTrue((self.ext / partial[0]).exists())
        self.assertFalse(partial[0].endswith(".conf"))
        self.assertFalse(any("-s" in args for args in self.commands))
        snapshot = self.run_manager("recheck")
        self.assertEqual(snapshot["state"], "Recovery Required")
        self.assertEqual(snapshot["recovery_id"], err.exception.recovery_id)
        result = self.run_manager("restore", recovery=snapshot["recovery_id"])
        self.assertEqual(result["state"], "Restored")
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")

    def test_failed_asset_publication_is_inert_and_restorable(self):
        from unittest.mock import patch
        original = extension._write_exclusive
        def fail_asset(fd, name, payload, mode):
            if ".html." in name and name.endswith(".stage"):
                raise OSError(5, "simulated asset staging fsync failure")
            return original(fd, name, payload, mode)
        with patch.object(extension, "_write_exclusive", side_effect=fail_asset):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertFalse((self.ext / extension._include_name(7, "404")).exists())
        self.assertFalse(any("-s" in args for args in self.commands))
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        self.assertEqual(
            self.run_manager("restore", recovery=err.exception.recovery_id)["state"],
            "Restored")

    def test_lost_directory_fsync_after_atomic_conf_publication(self):
        from unittest.mock import patch
        original_fsync = extension.os.fsync
        target = self.ext.stat()
        calls = [0]
        def fail_after_rename(fd):
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
                calls[0] += 1
                if calls[0] == 2:
                    raise OSError(5, "simulated post-publication fsync loss")
            return original_fsync(fd)
        with patch.object(extension.os, "fsync", side_effect=fail_after_rename):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(calls[0], 2)
        self.assertTrue((self.ext / extension._include_name(7, "404")).exists())
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        self.assertEqual(
            self.run_manager("restore", recovery=err.exception.recovery_id)["state"],
            "Restored")

    def test_atomic_publish_ack_loss_does_not_retry_blindly(self):
        from unittest.mock import patch
        original = extension._rename_noreplace
        def lost_ack(fd, before, after):
            original(fd, before, after)
            if after.endswith(".conf"):
                raise OSError(5, "simulated lost rename acknowledgement")
        with patch.object(extension, "_rename_noreplace", side_effect=lost_ack):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertTrue((self.ext / extension._include_name(7, "404")).exists())
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        with self.assertRaises(extension.ExtensionError):
            self.run_manager()
        self.assertEqual(
            self.run_manager("restore", recovery=err.exception.recovery_id)["state"],
            "Restored")

    def test_final_apply_journal_failure_retains_real_recovery_identity(self):
        from unittest.mock import patch
        original = extension._record_save
        def failed_final(fd, site_id, code, record):
            if record["phase"] == "applied":
                raise OSError(5, "simulated final journal failure")
            return original(fd, site_id, code, record)
        with patch.object(extension, "_record_save", side_effect=failed_final):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        record = self.run_manager("recheck")
        self.assertEqual(record["state"], "Recovery Required")
        self.assertEqual(err.exception.recovery_id, record["recovery_id"])
        self.assertEqual(self.run_manager("restore", recovery=record["recovery_id"])["state"],
                         "Restored")

    def test_final_apply_journal_fsync_acknowledgement_loss(self):
        from unittest.mock import patch
        original = extension._record_save
        def stored_then_lost(fd, site_id, code, record):
            result = original(fd, site_id, code, record)
            if record["phase"] == "applied":
                raise OSError(5, "simulated commit acknowledgement loss")
            return result
        with patch.object(extension, "_record_save", side_effect=stored_then_lost):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager()
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(self.run_manager("recheck")["state"], "Applied")
        self.assertEqual(err.exception.recovery_id,
                         self.run_manager("recheck")["recovery_id"])
        self.assertEqual(self.run_manager("restore",
                         recovery=err.exception.recovery_id)["state"], "Restored")

    def test_final_restore_journal_failure_is_uncertain_and_resumable(self):
        from unittest.mock import patch
        applied = self.run_manager()
        original = extension._record_save
        def failed_final(fd, site_id, code, record):
            if record["phase"] == "restored":
                raise OSError(5, "simulated final restored journal loss")
            return original(fd, site_id, code, record)
        with patch.object(extension, "_record_save", side_effect=failed_final):
            with self.assertRaises(extension.ExtensionError) as err:
                self.run_manager("restore", recovery=applied["recovery_id"])
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(err.exception.recovery_id, applied["recovery_id"])
        self.assertEqual(self.run_manager("recheck")["state"], "Recovery Required")
        self.assertEqual(self.run_manager("restore",
                         recovery=applied["recovery_id"])["state"], "Restored")

    def test_502_restored_recheck_reports_existing_source_hash_not_applied_hash(self):
        existing = self.site_root / "502.html"
        previous = b"<html>original operator 502 source</html>"
        existing.write_bytes(previous)
        expected = hashlib.sha256(previous).hexdigest()
        applied = self.run_manager(code="502", current=expected)
        self.assertNotEqual(applied["page_file_sha256"], expected)
        restored = self.run_manager("restore", code="502",
                                    recovery=applied["recovery_id"])
        rechecked = self.run_manager("recheck", code="502")
        self.assertEqual(restored["state"], "Source Restored")
        self.assertEqual(rechecked["state"], "Source Restored")
        self.assertEqual(rechecked["page_file_sha256"], expected)
        self.assertEqual(rechecked["before_sha256"], expected)
        self.assertEqual(rechecked["after_sha256"], applied["page_file_sha256"])
        self.assertFalse(rechecked["runtime_verified"])
        self.assertEqual(rechecked["verification_scope"], "source_and_nonce_only")
        self.assertEqual(existing.read_bytes(), previous)

    def test_502_no_nonce_cannot_prove_previous_real_502(self):
        for wrong_status in (404, 200, 500):
            with self.subTest(wrong_status=wrong_status):
                applied = self.run_manager(code="502")
                base_probe = self.probe
                def after_no_status(site, code, operation):
                    active = (self.ext / extension._include_name(site["id"], code)).exists()
                    if code == "502" and operation is not None and not active:
                        return (wrong_status, hashlib.sha256(b"other status").hexdigest(), None)
                    return base_probe(site, code, operation)
                self.probe = after_no_status
                result = self.run_manager("restore", code="502",
                                          recovery=applied["recovery_id"])
                self.assertEqual(result["state"], "Source Restored")
                self.assertFalse(result["runtime_verified"])
                self.assertEqual(result["page_file_sha256"], hashlib.sha256(b"").hexdigest())
                rechecked = self.run_manager("recheck", code="502")
                self.assertEqual(rechecked["state"], "Source Restored")
                self.assertEqual(rechecked["page_file_sha256"],
                                 hashlib.sha256(b"").hexdigest())
                self.assertEqual(rechecked["page_file_sha256"],
                                 rechecked["before_sha256"])
                self.assertFalse(rechecked["runtime_verified"])
                self.assertEqual(rechecked["verification_scope"], "source_and_nonce_only")
                self.probe = base_probe

    def test_502_source_drift_rejects_full_restore_claim(self):
        applied = self.run_manager(code="502")
        original_502 = self.site_root / "502.html"
        original_502.write_bytes(b"independently edited existing 502 page")
        with self.assertRaises(extension.ExtensionError) as err:
            self.run_manager("restore", code="502", recovery=applied["recovery_id"])
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(self.run_manager("recheck", code="502")["state"],
                         "Recovery Required")
        original_502.unlink()
        self.assertEqual(self.run_manager("restore", code="502",
                         recovery=applied["recovery_id"])["state"], "Source Restored")

    def test_no_document_root_write(self):
        (self.site_root / "404.html").write_bytes(b"operator owned")
        self.run_manager()
        self.assertEqual((self.site_root / "404.html").read_bytes(), b"operator owned")
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")


    def test_50x_all_statuses_must_prove_same_body_and_nonce(self):
        op = "a" * 32
        observed = [(int(code), self.after, op) for code in extension.FIFTY_CODES]
        self.assertEqual(extension._assess_50x(observed, op), (500, self.after, op))
        for index in range(4):
            with self.subTest(status=extension.FIFTY_CODES[index]):
                partial = list(observed)
                partial[index] = (404, self.before, None)
                self.assertEqual(extension._assess_50x(partial, op), (0, None, op))
        self.assertEqual(extension._assess_50x([(404, self.before, None)] * 4, op),
                         (0, None, None))

    def test_50x_refuses_preexisting_native_500_503_504_routing(self):
        original = self.vhost.read_text()
        for mapping in ("error_page 500 /my500.html;", "error_page 500 503 /50x.html;",
                        "location = /api { error_page 504 /api504.html; }"):
            with self.subTest(mapping=mapping):
                self.vhost.write_text(original.replace("error_page 502 /502.html;",
                    "error_page 502 /502.html;\n" + mapping))
                with self.assertRaises(extension.ExtensionError):
                    self.run_manager(code="50x")
                self.assertFalse(list(self.state.iterdir()))
                self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")
        self.vhost.write_text(original)

    def test_50x_multiline_quoted_and_nested_mapping_conflicts_are_preflight_only(self):
        original = self.vhost.read_text()
        cases = (
            # Nginx recognizes newlines inside directive argument lists.
            "error_page 500\n    /operator-500.html;",
            "location /special/ {\n    error_page 503\n        /operator-503.html;\n}",
            "location /special/ { error_page 504\n    /operator-504.html; }",
            "error_page 503 # comment between Nginx directive tokens\n    /custom-503.html;",
            "add_header X-Note \"value#part\"; error_page 500 /operator-500.html;",
            "location /special/ { add_header X-Note 'a;#b';\n"
            "    error_page 503 504\n    /operator-multi.html; }",
        )
        for content in cases:
            with self.subTest(content=content):
                self.vhost.write_text(original.replace(
                    "error_page 502 /502.html;",
                    "error_page 502 /502.html;\n" + content))
                with self.assertRaises(extension.ExtensionError) as caught:
                    self.run_manager(code="50x")
                self.assertEqual(caught.exception.stage, "conflict")
                self.assertEqual(self.commands, [], "Must reject before Nginx syntax/reload")
                self.assertEqual(list(self.state.iterdir()), [], "No recovery journal")
                self.assertEqual(list(self.ext.iterdir()), [], "No extension publication")
                self.assertEqual(list(self.public.iterdir()), [], "No HTML publication")
        self.vhost.write_text(original)

    def test_50x_ignores_actual_comments_and_unrelated_quoted_text(self):
        original = self.vhost.read_text()
        harmless = (
            "# error_page 500 /comment-only.html;",
            "add_header X-Note 'text # error_page 503 /not-a-rule;';",
            "add_header X-Hint \"value#part\"; # error_page 504 /hidden.html;",
            "add_header X-Hint \"value\\\"#part\"; # error_page 500 /hidden.html;",
            "rewrite ^/special/$ /special.php?token=${request_uri} last;",
            "error_page 404 /404.html; # 500 503 504 in comment",
            "location /special/ { # error_page 500 /nested-comment.html;\n"
            "    add_header X-Note \"error_page 504;\"; }",
        )
        for content in harmless:
            with self.subTest(content=content):
                self.vhost.write_text(original.replace(
                    "error_page 502 /502.html;",
                    "error_page 502 /502.html;\n" + content))
                self.assertEqual(self.run_manager("recheck", code="50x")["state"], "Unmanaged")
                self.assertEqual(self.commands, [])
        self.vhost.write_text(original)
        applied = self.run_manager(code="50x")
        self.assertEqual(self.run_manager("recheck", code="50x")["state"], "Applied")
        self.assertEqual(self.run_manager("restore", code="50x",
                                          recovery=applied["recovery_id"])["state"],
                         "Source Restored")

    def test_50x_ambiguous_vhost_cannot_create_a_journal_or_reload(self):
        original = self.vhost.read_text()
        cases = (
            'add_header X-Note "unterminated quote;\nerror_page 500 /cannot-trust.html;',
            'location /special/ { error_page 503 /unfinished',
            'add_header X-Note valid; error_page 504',
            'add_header X-Bad "quoted\\',
        )
        for content in cases:
            with self.subTest(content=content):
                self.vhost.write_text(original.replace(
                    "error_page 502 /502.html;",
                    "error_page 502 /502.html;\n" + content))
                with self.assertRaises(extension.ExtensionError):
                    self.run_manager(code="50x")
                self.assertEqual(self.commands, [])
                self.assertEqual(list(self.state.iterdir()), [])
                self.assertEqual(list(self.ext.iterdir()), [])
                self.assertEqual(list(self.public.iterdir()), [])
        self.vhost.write_text(original)

    def test_50x_requires_native_502_mapping_and_uses_unmodified_site_file(self):
        current = self.vhost.read_text()
        self.vhost.write_text(current.replace("error_page 502 /502.html;", ""))
        with self.assertRaises(extension.ExtensionError):
            self.run_manager(code="50x")
        self.assertFalse(list(self.state.iterdir()))
        self.vhost.write_text(current)
        original = self.site_root / "502.html"
        original.write_bytes(b"real existing 502 file")
        source = hashlib.sha256(original.read_bytes()).hexdigest()
        self.assertEqual(self.run_manager("recheck", code="50x")["page_file_sha256"], source)
        applied = self.run_manager(code="50x", current=source)
        self.assertEqual(original.read_bytes(), b"real existing 502 file")
        self.assertTrue(applied["runtime_verified"])
        self.assertEqual(applied["verification_scope"], "http50x_body")
        checked = self.run_manager("recheck", code="50x")
        self.assertEqual(checked["state"], "Applied")
        self.assertTrue(checked["runtime_verified"])
        self.assertEqual(checked["verification_scope"], "http50x_body")
        restored = self.run_manager("restore", code="50x", recovery=applied["recovery_id"])
        self.assertEqual(restored["state"], "Source Restored")
        self.assertFalse(restored["runtime_verified"])
        self.assertEqual(original.read_bytes(), b"real existing 502 file")

    def test_502_and_50x_may_not_own_same_website_location_simultaneously(self):
        applied_502 = self.run_manager(code="502")
        with self.assertRaises(extension.ExtensionError) as error:
            self.run_manager(code="50x")
        self.assertEqual(error.exception.stage, "conflict")
        self.assertFalse((self.ext / extension._include_name(7, "50x")).exists())
        self.assertEqual(self.run_manager("restore", code="502",
                                         recovery=applied_502["recovery_id"])["state"],
                         "Source Restored")
        applied_50x = self.run_manager(code="50x")
        with self.assertRaises(extension.ExtensionError) as error:
            self.run_manager(code="502")
        self.assertEqual(error.exception.stage, "conflict")
        self.assertFalse((self.ext / extension._include_name(7, "502")).exists())
        self.assertEqual(self.run_manager("restore", code="50x",
                                         recovery=applied_50x["recovery_id"])["state"],
                         "Source Restored")

    def test_50x_preserves_saved_recovery_on_stopped_site(self):
        applied = self.run_manager(code="50x")
        self.site["status"] = "0"
        saved = self.run_manager("recheck", code="50x")
        self.assertEqual(saved["state"], "Suspended")
        self.assertEqual(saved["verification_scope"], "saved_journal_only")
        with self.assertRaises(extension.ExtensionError):
            self.run_manager("restore", code="50x", recovery=applied["recovery_id"])
        self.site["status"] = "1"
        self.assertEqual(self.run_manager("recheck", code="50x")["state"], "Applied")
        self.assertEqual(self.run_manager("restore", code="50x",
                                         recovery=applied["recovery_id"])["state"],
                         "Source Restored")


if __name__ == "__main__":
    unittest.main()
