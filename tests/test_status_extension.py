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
            return (int(code), self.after, operation)
        return (404, self.before, None)

    def run_manager(self, action="apply", **kw):
        return extension.manage_site_extension(
            action, self.site, code=kw.get("code", self.code),
            html=kw.get("html", self.html),
            expected_current=kw.get(
                "current", self.before if kw.get("code", self.code) == "404"
                else hashlib.sha256(b"").hexdigest()),
            expected_vhost=kw.get("vhost", hashlib.sha256(self.vhost.read_bytes()).hexdigest()),
            expected_render=kw.get("render", self.after),
            expected_recovery=kw.get("recovery"),
            data_fd=self.data_fd, vhost_root=str(self.vhost_root),
            public_root=str(self.public / ".pages"),
            nginx="/usr/sbin/nginx", nginx_conf="/tmp/test-nginx.conf",
            runner=self.runner, probe=self.probe)

    def test_apply_recheck_restore_for_404_and_502(self):
        for code in extension.CODES:
            with self.subTest(code=code):
                self.code = code
                self.assertEqual(self.run_manager("recheck")["state"], "Unmanaged")
                applied = self.run_manager()
                self.assertEqual(applied["state"], "Applied")
                self.assertEqual(self.run_manager("recheck")["state"], "Applied")
                content = (self.ext / extension._include_name(7, code)).read_text()
                self.assertIn("location = /" + code + ".html", content)
                self.assertIn("internal;", content)
                self.assertIn("allow 127.0.0.1;", content)
                self.assertNotIn(str(self.site_root) + "/" + code + ".html", content)
                self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")
                restored = self.run_manager("restore", recovery=applied["recovery_id"])
                self.assertEqual(restored["state"], "Restored")
                self.assertEqual(self.run_manager("recheck")["state"], "Restored")
                self.assertFalse((self.ext / extension._include_name(7, code)).exists())
                self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")
        self.assertEqual(sum("reload" in cmd for cmd in self.commands), 4)

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

    def test_no_document_root_write(self):
        (self.site_root / "404.html").write_bytes(b"operator owned")
        self.run_manager()
        self.assertEqual((self.site_root / "404.html").read_bytes(), b"operator owned")
        self.assertEqual(self.other.read_bytes(), b"Untouched non-target bytes")


if __name__ == "__main__":
    unittest.main()
