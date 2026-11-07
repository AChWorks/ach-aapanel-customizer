"""Native site-file 404/502 Apply/Recheck/Restore (no Nginx config write)."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_status_site_file as manager
from ach_customizer_status_extension import ExtensionError


class NativeSiteFileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="ach-site-file-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.vhost_root = self.root / "vhosts"
        self.vhost_root.mkdir()
        self.root_site = self.root / "www" / "demo.invalid"
        self.root_site.mkdir(parents=True)
        self.site = {
            "id": 7, "name": "demo.invalid", "path": str(self.root_site),
            "status": "1", "bound_domains": [{"name": "demo.invalid", "port": 80}]
        }
        self.vhost = self.vhost_root / "demo.invalid.conf"
        self.vhost.write_text(
            "server {\nlisten 80;\nserver_name demo.invalid;\n"
            "root " + str(self.root_site) + ";\n"
            "error_page 404 /404.html;\n"
            "error_page 502 /502.html;\n"
            "include enable-php-85.conf;\n}\n")
        self.files = {}
        for code in ("404", "502"):
            self.files[code] = self.root_site / (code + ".html")
            self.files[code].write_bytes(("original " + code).encode())
            self.files[code].chmod(0o644)
        self.state = self.root / "state"
        self.state.mkdir()
        self.fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.proposed = "<!doctype html><html>New Status</html>"
        self.original_vhost = self.vhost.read_bytes()
        self.commands = []
        self.broken_probe = False

    @staticmethod
    def sha(data):
        return hashlib.sha256(data).hexdigest()

    def runner(self, args, **_kwargs):
        self.commands.append(tuple(args))
        return SimpleNamespace(returncode=0)

    def probe(self, site, code, op):
        self.assertEqual(site["id"], 7)
        self.assertEqual(code, "404")
        self.assertIsNone(op)
        if self.broken_probe:
            return (500, self.sha(b"bad"), None)
        return (404, self.sha(self.files["404"].read_bytes()), None)

    def operate(self, action="recheck", *, code="404", **fields):
        current_sha = fields.get("expected_current")
        if current_sha is None:
            current_sha = (self.sha(self.files[code].read_bytes())
                           if self.files[code].exists() else "0" * 64)
        expected = {
            "expected_current": current_sha,
            "expected_vhost": self.sha(self.original_vhost),
            "expected_render": self.sha(self.proposed.encode()),
            "expected_recovery": None,
        }
        expected.update(fields)
        return manager.manage_site_file(
            action, self.site, code=code, html=self.proposed,
            data_fd=self.fd, vhost_root=str(self.vhost_root),
            runner=self.runner, probe=self.probe, **expected)

    def test_both_codes_apply_recheck_restore_exact_bytes_without_reload(self):
        original = {code: self.files[code].read_bytes() for code in ("404", "502")}
        before = self.vhost.read_bytes()
        for code in ("404", "502"):
            with self.subTest(code=code):
                unmanaged = self.operate(code=code)
                self.assertEqual(unmanaged["state"], "Unmanaged")
                self.assertIsNone(unmanaged["recovery_id"])
                applied = self.operate("apply", code=code)
                self.assertEqual(applied["state"], "Applied")
                self.assertEqual(applied["mode"], manager.MODE)
                self.assertTrue(applied["runtime_verified"] if code == "404"
                                else not applied["runtime_verified"])
                self.assertEqual(self.operate(code=code)["state"], "Applied")
                original_mode = self.files[code].stat().st_mode & 0o777
                self.assertEqual(original_mode, 0o644)
                self.assertEqual(self.files[code].read_bytes(), self.proposed.encode())
                restored = self.operate("restore", code=code,
                                    expected_recovery=applied["recovery_id"])
                self.assertEqual(restored["state"],
                                 "Restored" if code == "404" else "Source Restored")
                self.assertEqual(self.operate(code=code)["state"],
                                 "Restored" if code == "404" else "Source Restored")
                self.assertEqual(self.files[code].read_bytes(), original[code])
        self.assertEqual(self.vhost.read_bytes(), before)
        self.assertTrue(all("-t" in run for run in self.commands))
        self.assertFalse(any("reload" in run for run in self.commands))

    def test_exact_native_source_rejects_extension_and_unknown_directives(self):
        for modified in (
            self.original_vhost + b"include /www/server/panel/vhost/nginx/extension/demo.invalid/*.conf;\n",
            self.original_vhost.replace(b"error_page 404 /404.html;",
                                        b"error_page 404 /other.html;"),
            self.original_vhost.replace(b"root " + str(self.root_site).encode() + b";",
                                        b"root /tmp/foreign;"),
            self.original_vhost + b"location = /404.html { return 200; }\n",
        ):
            with self.subTest(source=modified[:60]):
                self.vhost.write_bytes(modified)
                with self.assertRaises(ExtensionError):
                    self.operate("apply")
                self.assertEqual(self.files["404"].read_bytes(), b"original 404")
                self.assertEqual(list(self.state.iterdir()), [])
        self.vhost.write_bytes(self.original_vhost)

    def test_journal_mode_contract_all_supported_modes_are_recoverable(self):
        """No allowed source mode may produce an unreadable recovery journal."""
        from ach_customizer_status_site_file import _supported_mode, _record_read

        path = self.files["502"]
        initial = path.read_bytes()
        original_uid, original_gid = path.stat().st_uid, path.stat().st_gid
        modes = [mode for mode in range(0o400, 0o756) if _supported_mode(mode)]
        self.assertIn(0o400, modes)
        self.assertIn(0o440, modes)
        self.assertIn(0o640, modes)
        self.assertIn(0o644, modes)
        self.assertIn(0o755, modes)
        self.assertGreater(len(modes), 40)
        for mode in modes:
            with self.subTest(mode=oct(mode)):
                path.chmod(mode)
                before = self.sha(initial)
                applied = self.operate("apply", code="502", expected_current=before)
                self.assertEqual(applied["state"], "Applied")
                recorded = _record_read(self.fd, self.site, "502")
                self.assertEqual(recorded["mode"], mode)
                self.assertEqual(recorded["before_sha"], before)
                self.assertEqual(recorded["op"], applied["recovery_id"])
                self.assertEqual(self.operate(code="502")["state"], "Applied")
                self.assertEqual(
                    (path.stat().st_uid, path.stat().st_gid, path.stat().st_mode & 0o7777),
                    (original_uid, original_gid, mode))
                restored = self.operate(
                    "restore", code="502", expected_recovery=applied["recovery_id"])
                self.assertEqual(restored["state"], "Source Restored")
                self.assertEqual(path.read_bytes(), initial)
                self.assertEqual(
                    (path.stat().st_uid, path.stat().st_gid, path.stat().st_mode & 0o7777),
                    (original_uid, original_gid, mode))
                self.assertEqual(self.operate(code="502")["state"], "Source Restored")
                # Every mode is an independent original native installation.
                # Clear only this disposable fixture's saved journal/backup,
                # never bypass drift protection inside the application.
                for artifact in self.state.iterdir():
                    self.assertTrue(artifact.name.startswith(
                        "ach_customizer.site_file."))
                    artifact.unlink()
        self.assertFalse(any("reload" in cmd for cmd in self.commands))

    def test_404_nondefault_safe_mode_keeps_http_proof_and_exact_restore(self):
        path = self.files["404"]
        path.chmod(0o440)
        before = path.read_bytes()
        applied = self.operate("apply")
        self.assertEqual(applied["state"], "Applied")
        self.assertTrue(applied["runtime_verified"])
        self.assertEqual(path.stat().st_mode & 0o7777, 0o440)
        self.assertEqual(self.operate()["state"], "Applied")
        restored = self.operate("restore", expected_recovery=applied["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertTrue(restored["runtime_verified"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mode & 0o7777, 0o440)

    def test_special_and_low_modes_rejected_before_journal_and_write(self):
        from ach_customizer_status_site_file import _supported_mode
        for code in ("404", "502"):
            path = self.files[code]
            initial = path.read_bytes()
            for mode in (0o4755, 0o2644, 0o200, 0o300):
                with self.subTest(code=code, mode=oct(mode)):
                    self.assertFalse(_supported_mode(mode))
                    path.chmod(mode)
                    try:
                        with self.assertRaises((ExtensionError, PermissionError)):
                            self.operate("apply", code=code,
                                         expected_current=self.sha(initial))
                    finally:
                        path.chmod(0o644)
                    self.assertEqual(path.read_bytes(), initial)
                    self.assertFalse(list(self.state.iterdir()))
        self.assertEqual(self.commands, [])

    def test_native_server_context_with_php_include_and_nested_locations(self):
        native = """# aaPanel native VHost, with misleading { } inside this comment
server
{
    listen 80;
    server_name demo.invalid;
    root __ROOT__;
    error_page 404 /404.html;
    error_page 502 /502.html;
    include enable-php-85.conf;
    include /www/server/panel/vhost/rewrite/demo.invalid.conf;
    add_header X-Safe "braces { } are data";
    location ~ \\.well-known{ allow all; }
    if ( $uri ~ "^/\\.well-known/.*\\.php$" ) { return 403; }
}
""".replace("__ROOT__", str(self.root_site))
        self.vhost.write_text(native)
        vhost_sha = self.sha(self.vhost.read_bytes())
        for code in ("404", "502"):
            with self.subTest(code=code):
                self.assertEqual(manager._source(self.site, code, str(self.vhost_root)),
                                 vhost_sha)
                applied = self.operate("apply", code=code, expected_vhost=vhost_sha)
                self.assertEqual(applied["state"], "Applied")
                self.assertEqual(self.operate(code=code)["state"], "Applied")
                restored = self.operate("restore", code=code,
                                        expected_recovery=applied["recovery_id"])
                self.assertEqual(restored["state"],
                                 "Restored" if code == "404" else "Source Restored")
        self.assertFalse(any("reload" in cmd for cmd in self.commands))

    def test_nested_only_error_page_never_authorizes_502_source_or_write(self):
        self.vhost.write_bytes(self.original_vhost.replace(
            b"error_page 502 /502.html;\n",
            b"location /special/ {\n error_page 502 /502.html;\n}\n"))
        with self.assertRaises(ExtensionError):
            manager._source(self.site, "502", str(self.vhost_root))
        from unittest.mock import patch
        with patch.object(manager, "VHOST_ROOT", str(self.vhost_root)):
            with self.assertRaises(ExtensionError):
                manager.preview_site_file_502(
                    self.site, locale="en",
                    rendered_sha256=self.sha(self.proposed.encode()),
                    rendered_html=self.proposed)
        with self.assertRaises(ExtensionError):
            self.operate("apply", code="502",
                         expected_vhost=self.sha(self.vhost.read_bytes()))
        self.assertEqual(self.files["502"].read_bytes(), b"original 502")
        self.assertEqual(self.commands, [])
        self.assertFalse(list(self.state.iterdir()))

    def test_nested_only_404_mapping_rejected_before_http_preflight(self):
        self.vhost.write_bytes(self.original_vhost.replace(
            b"error_page 404 /404.html;\n",
            b"location /private/ {\n error_page 404 /404.html;\n}\n"))
        with self.assertRaises(ExtensionError):
            self.operate("apply", code="404",
                         expected_vhost=self.sha(self.vhost.read_bytes()))
        self.assertEqual(self.commands, [])
        self.assertEqual(self.files["404"].read_bytes(), b"original 404")
        self.assertFalse(list(self.state.iterdir()))

    def test_nested_only_root_or_ambiguous_context_never_authorizes_502(self):
        before = self.original_vhost
        root_line = ("root " + str(self.root_site) + ";\n").encode()
        for modified in (
            before.replace(root_line, b"").replace(
                b"include enable-php-85.conf;\n",
                b"include enable-php-85.conf;\nlocation /special/ {\n " +
                root_line + b"}\n"),
            before.replace(b"error_page 502 /502.html;\n",
                           b"location /special/ { error_page 502 /502.html; }\n"),
            before.removesuffix(b"}\n"),
            before + b"server { root /tmp/foreign; }\n",
        ):
            with self.subTest(source=modified[:100]):
                self.vhost.write_bytes(modified)
                with self.assertRaises(ExtensionError):
                    self.operate("apply", code="502",
                                 expected_vhost=self.sha(modified))
                self.assertFalse(list(self.state.iterdir()))
                self.assertEqual(self.files["502"].read_bytes(), b"original 502")
        self.assertEqual(self.commands, [])

    def test_wrong_hashes_and_missing_file_never_mutate(self):
        for field in ("expected_current", "expected_vhost", "expected_render"):
            with self.subTest(field=field), self.assertRaises(ExtensionError):
                self.operate("apply", **{field: "0" * 64})
            self.assertEqual(list(self.state.iterdir()), [])
        self.files["404"].unlink()
        with self.assertRaises(ExtensionError):
            self.operate("recheck", code="404", expected_current="0" * 64)
        self.assertFalse(list(self.state.iterdir()))

    def test_drift_and_wrong_recovery_prevent_restore(self):
        applied = self.operate("apply")
        self.files["404"].write_bytes(b"manual edit")
        self.assertEqual(self.operate()["state"], "Drift")
        with self.assertRaises(ExtensionError):
            self.operate("restore", expected_recovery=applied["recovery_id"])
        self.files["404"].write_bytes(self.proposed.encode())
        with self.assertRaises(ExtensionError):
            self.operate("restore", expected_recovery="0" * 32)
        self.assertEqual(self.operate()["state"], "Applied")
        self.assertEqual(self.operate("restore", expected_recovery=applied["recovery_id"])["state"],
                         "Restored")

    def test_stopped_and_vhost_regeneration_keep_saved_recovery_only(self):
        applied = self.operate("apply")
        self.site["status"] = "0"
        suspended = self.operate()
        self.assertEqual(suspended["state"], "Suspended")
        self.assertEqual(suspended["recovery_id"], applied["recovery_id"])
        self.assertEqual(suspended["verification_scope"], "saved_journal_only")
        with self.assertRaises(ExtensionError):
            self.operate("restore", expected_recovery=applied["recovery_id"])
        self.site["status"] = "1"
        self.vhost.write_bytes(self.original_vhost + b"# native regeneration\n")
        drift = self.operate()
        self.assertEqual(drift["state"], "Needs Review")
        self.assertFalse(drift["runtime_verified"])
        self.assertEqual(drift["recovery_id"], applied["recovery_id"])
        with self.assertRaises(ExtensionError):
            self.operate("restore", expected_recovery=applied["recovery_id"])
        self.vhost.write_bytes(self.original_vhost)
        self.assertEqual(self.operate()["state"], "Applied")
        self.assertEqual(self.operate("restore", expected_recovery=applied["recovery_id"])["state"],
                         "Restored")

    def test_failed_http_postcheck_preserves_prepared_recovery_and_manual_restore(self):
        self.broken_probe = True
        with self.assertRaises(ExtensionError):
            self.operate("apply")
        self.assertEqual(self.files["404"].read_bytes(), b"original 404")
        self.assertEqual(list(self.state.iterdir()), [])
        self.broken_probe = False
        # Post-publish failure keeps a prepared journal and recoverable backup.
        calls = [0]
        def fail_after_file(site, code, op):
            calls[0] += 1
            if calls[0] > 1:
                return 500, self.sha(b"bad"), None
            return self.probe(site, code, op)
        with self.assertRaises(ExtensionError) as failure:
            manager.manage_site_file(
                "apply", self.site, code="404", html=self.proposed,
                expected_current=self.sha(b"original 404"),
                expected_vhost=self.sha(self.original_vhost),
                expected_render=self.sha(self.proposed.encode()),
                expected_recovery=None, data_fd=self.fd,
                vhost_root=str(self.vhost_root), runner=self.runner,
                probe=fail_after_file)
        op = failure.exception.recovery_id
        self.assertTrue(op)
        self.assertEqual(self.files["404"].read_bytes(), self.proposed.encode())
        self.assertEqual(self.operate()["state"], "Recovery Required")
        self.assertEqual(self.operate("restore", expected_recovery=op)["state"], "Restored")
        self.assertEqual(self.files["404"].read_bytes(), b"original 404")

    def test_prepared_staged_publish_can_restore_without_orphaned_stage(self):
        from unittest.mock import patch

        def interrupted(fd, site, filename, payload, old_bytes, uid, gid, mode, op):
            staged = self.root_site / ("." + filename + "." + op + ".stage")
            staged.write_bytes(payload)
            staged.chmod(mode)
            raise OSError("injected interruption before atomic publication")

        with patch.object(manager, "_publish", side_effect=interrupted):
            with self.assertRaises(ExtensionError) as failed:
                self.operate("apply")
        operation = failed.exception.recovery_id
        self.assertTrue(operation)
        staged = self.root_site / (".404.html." + operation + ".stage")
        self.assertTrue(staged.exists())
        self.assertEqual(self.files["404"].read_bytes(), b"original 404")
        self.assertEqual(self.operate()["state"], "Recovery Required")
        result = self.operate("restore", expected_recovery=operation)
        self.assertEqual(result["state"], "Restored")
        self.assertFalse(result["changed"])
        self.assertFalse(staged.exists())
        self.assertEqual(self.files["404"].read_bytes(), b"original 404")
        self.assertEqual(self.operate()["state"], "Restored")

    def test_symlink_and_world_writable_source_rejected(self):
        origin = self.files["404"].read_bytes()
        self.files["404"].unlink()
        link_target = self.root / "private-foreign"
        link_target.write_bytes(origin)
        self.files["404"].symlink_to(link_target)
        with self.assertRaises((ExtensionError, OSError)):
            self.operate("apply", expected_current=self.sha(origin))
        self.files["404"].unlink()
        self.files["404"].write_bytes(origin)
        self.files["404"].chmod(0o666)
        with self.assertRaises(ExtensionError):
            self.operate("apply", expected_current=self.sha(origin))
        self.files["404"].chmod(0o644)
        self.assertEqual(list(self.state.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
