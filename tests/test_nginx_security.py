"""Opt-in native aaPanel Nginx sensitive-file guard and recovery tests.

These tests model aaPanel's own per-site *.conf include ownership and real
worker generation transitions. Native HTTP proof is separately tested in the
isolated aaPanel VM; these tests never reload the host Nginx.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "plugin" / "ach_customizer"))
import ach_customizer_nginx_security as guard


class NativeSecurityTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="ach-native-security-")
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)
        self.vhost_root = self.root / "nginx"
        self.vhost_root.mkdir()
        self.ext = self.vhost_root / "extension" / "secure.invalid"
        self.ext.mkdir(parents=True)
        self.site_root = self.root / "www" / "acdomains" / "secure.invalid"
        self.site_root.mkdir(parents=True)
        self.site = {
            "id": 27, "name": "secure.invalid",
            "path": str(self.site_root), "status": "1",
            "bound_domains": [{"name": "secure.invalid", "port": 80}],
        }
        self.vhost = self.vhost_root / "secure.invalid.conf"
        self.vhost.write_text(
            "server {\nlisten 80;\nserver_name secure.invalid;\n"
            "root " + str(self.site_root) + ";\n"
            "error_page 404 /404.html;\nerror_page 502 /502.html;\n"
            "include " + str(self.ext) + "/*.conf;\n"
            "include enable-php-85.conf;\n}\n")
        self.nginx_conf = self.root / "nginx.conf"
        self.nginx_conf.write_text(
            "events {worker_connections 100;}\n"
            "http {include " + str(self.vhost_root) + "/*.conf;}\n")
        self.state = self.root / "state"
        self.state.mkdir()
        self.fd = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.foreign = self.root / "peer.invalid"
        self.foreign.write_bytes(b"Never change any unrelated site")
        self.commands = []
        self.active = False
        self.force_bad_syntax = False
        self.force_bad_proof = False

    @property
    def fragment(self):
        return self.ext / guard._file(self.site["id"])

    def runner(self, argv, **kw):
        self.commands.append(tuple(argv))
        if "-t" in argv and self.fragment.exists() and self.force_bad_syntax:
            return SimpleNamespace(returncode=1, stderr=b"intentional broken syntax")
        if "-s" in argv and "reload" in argv:
            self.active = self.fragment.exists()
        return SimpleNamespace(returncode=0, stderr=b"")

    def probe(self, site, op, kind):
        self.assertEqual(site["id"], 27)
        self.assertIn(kind, guard.PROOF_KINDS)
        if self.active and not self.force_bad_proof:
            return (403, op)
        return (404, None)

    def operate(self, action="preview", **kwargs):
        source = guard._sha(self.vhost.read_bytes())
        proposal = guard._proposal_sha()
        return guard.manage_guard(
            action, self.site, data_fd=self.fd,
            approved=kwargs.get("approved", True),
            expected_vhost=kwargs.get("source", source),
            expected_proposal=kwargs.get("proposal", proposal),
            expected_recovery=kwargs.get("recovery"),
            vhost_root=str(self.vhost_root),
            nginx_conf=str(self.nginx_conf), nginx="/test/nginx",
            runner=self.runner, probe=self.probe)

    def test_rule_names_and_proof_paths_are_fixed_and_site_path_independent(self):
        self.assertEqual(len(guard.PROOF_KINDS), 10)
        sample = guard._include("a" * 32).decode()
        self.assertEqual(sample.count("return 403 "), 3)
        self.assertEqual(sample.count("ACh-Guard-Proof-"), 3)
        self.assertIn("wp-content/uploads", guard._probe_path("a" * 32, "wp_uploaded_php"))
        self.assertIn("[.]htaccess", sample)
        self.assertNotIn("wwwroot", sample)
        self.assertNotIn(str(self.site_root), sample)
        self.assertNotIn(".well-known", sample)
        self.assertIn("if ($uri ~*", sample)
        self.assertNotIn("location ~", sample)
        with self.assertRaises(guard.GuardError):
            guard._probe_path("a" * 32, "http://evil.invalid/")

    def test_public_proof_never_exposes_durable_recovery_id(self):
        token = "b" * 32
        rule = guard._include(token).decode()
        self.assertNotIn(token, rule)
        self.assertIn(guard._public_proof(token), rule)
        for kind in guard.PROOF_KINDS:
            uri = guard._probe_path(token, kind)
            self.assertNotIn(token, uri, kind)
            self.assertTrue(uri.startswith("/"))
        with self.assertRaises(guard.GuardError):
            guard._public_proof("not-a-recovery-id")

    def test_preview_apply_recheck_restore_and_repeat_on_nondefault_root(self):
        root = self.site_root
        self.assertEqual(self.operate()["state"], "Unmanaged")
        self.assertFalse(list(self.state.iterdir()))
        self.assertFalse(list(self.ext.iterdir()))
        with self.assertRaisesRegex(guard.GuardError, "approval"):
            self.operate("apply", approved=False)
        with self.assertRaisesRegex(guard.GuardError, "changed"):
            self.operate("apply", source="1" * 64)
        applied = self.operate("apply")
        self.assertEqual(applied["state"], "Applied")
        self.assertTrue(applied["runtime_verified"])
        self.assertEqual(applied["site_root"], str(root))
        self.assertEqual(self.fragment.read_bytes(), guard._include(applied["recovery_id"]))
        self.assertEqual(self.operate("recheck")["state"], "Applied")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")
        with self.assertRaises(guard.GuardError):
            self.operate("restore", recovery="f" * 32)
        restored = self.operate("restore", recovery=applied["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(self.fragment.exists())
        self.assertEqual(self.operate("recheck")["state"], "Restored")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")
        second = self.operate("apply")
        self.assertNotEqual(second["recovery_id"], applied["recovery_id"])
        self.assertEqual(self.operate("restore", recovery=second["recovery_id"])["state"],
                         "Restored")
        self.assertEqual(len([c for c in self.commands if "reload" in c]), 4)

    def test_native_guard_does_not_require_a_404_status_route(self):
        # Pre-PHP defenses must not be coupled to Status Pages policy.
        text = self.vhost.read_text().replace("error_page 404 /404.html;\n", "")
        self.vhost.write_text(text)
        preview = self.operate("preview")
        self.assertEqual(preview["state"], "Unmanaged")
        applied = self.operate("apply", source=preview["vhost_sha256"])
        self.assertEqual(applied["state"], "Applied")
        self.assertEqual(self.operate("restore", recovery=applied["recovery_id"])["state"],
                         "Restored")

    def test_sibling_native_extension_change_invalidates_existing_preview(self):
        checked = self.operate("preview")
        foreign = self.ext / "other_module.conf"
        foreign.write_text("add_header X-Foreign-Module present;\n")
        foreign.chmod(0o600)
        updated = self.operate("preview")
        self.assertNotEqual(updated["vhost_sha256"], checked["vhost_sha256"])
        with self.assertRaisesRegex(guard.GuardError, "changed"):
            self.operate("apply", source=checked["vhost_sha256"])
        self.assertFalse(self.fragment.exists())
        self.assertFalse(list(self.state.iterdir()))
        applied = self.operate("apply", source=updated["vhost_sha256"])
        self.assertEqual(applied["state"], "Applied")
        self.assertEqual(self.operate("restore", recovery=applied["recovery_id"])["state"],
                         "Restored")
        self.assertEqual(foreign.read_text(), "add_header X-Foreign-Module present;\n")

    def test_untrusted_root_symlink_refuses_security_write(self):
        source = self.root / "symlinked-site"
        source.symlink_to(self.site_root, target_is_directory=True)
        self.site["path"] = str(source)
        self.vhost.write_text(self.vhost.read_text().replace(str(self.site_root), str(source)))
        with self.assertRaises(guard.GuardError):
            self.operate("apply")
        self.assertFalse(self.fragment.exists())
        self.assertFalse(list(self.state.iterdir()))

    def test_native_root_move_refuses_new_write_or_old_recovery(self):
        applied = self.operate("apply")
        self.site["path"] = str(self.root / "www" / "other-sites" / "secure.invalid")
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        with self.assertRaises(guard.ExtensionError):
            self.operate("restore", recovery=applied["recovery_id"])
        with self.assertRaises(guard.ExtensionError):
            self.operate("apply")
        self.assertTrue(self.fragment.exists())
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_changed_binding_and_generated_vhost_refuse_recovery(self):
        applied = self.operate("apply")
        self.site["bound_domains"].append({"name": "alias.invalid", "port": 80})
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        with self.assertRaises(guard.ExtensionError):
            self.operate("restore", recovery=applied["recovery_id"])
        self.site["bound_domains"].pop()
        self.vhost.write_text(self.vhost.read_text().replace(
            "root " + str(self.site_root), "root /tmp/another.invalid"))
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        with self.assertRaises(guard.ExtensionError):
            self.operate("apply")

    def test_foreign_and_symlink_fragment_never_overwritten(self):
        self.fragment.write_bytes(b"foreign Nginx rule")
        self.fragment.chmod(0o600)
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        with self.assertRaises(guard.GuardError):
            self.operate("apply")
        self.assertEqual(self.fragment.read_bytes(), b"foreign Nginx rule")
        self.fragment.unlink()
        self.fragment.symlink_to(self.foreign)
        with self.assertRaises(guard.ExtensionError):
            self.operate("preview")
        with self.assertRaises(guard.ExtensionError):
            self.operate("apply")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_shared_publication_error_preserves_prepared_guard_recovery(self):
        # The shared publisher raises ExtensionError (not GuardError). Simulate
        # uncertain durability after the no-clobber rename has already landed.
        import ach_customizer_status_extension as publisher
        original_rename = publisher._rename_noreplace

        def renamed_but_unconfirmed(fd, before, after):
            original_rename(fd, before, after)
            raise OSError(5, "simulated uncertain directory sync after rename")

        with patch.object(publisher, "_rename_noreplace",
                          side_effect=renamed_but_unconfirmed):
            with self.assertRaises(guard.GuardError) as captured:
                self.operate("apply")

        failure = captured.exception
        self.assertEqual(failure.stage, "uncertain")
        self.assertRegex(failure.recovery_id or "", r"^[0-9a-f]{32}$")
        self.assertIs(type(failure.__cause__), guard.ExtensionError)
        self.assertEqual(failure.__cause__.recovery_id, failure.recovery_id)
        self.assertNotIn("Status publication", str(failure))
        journal = json.loads(
            (self.state / guard._journal(self.site["id"])).read_text())
        self.assertEqual(journal["phase"], "prepared")
        self.assertEqual(journal["op"], failure.recovery_id)
        self.assertEqual(self.fragment.read_bytes(), guard._include(journal["op"]))
        self.assertFalse(self.active)
        self.assertEqual(self.operate("recheck")["state"], "Recovery Required")
        self.assertEqual(
            self.operate("restore", recovery=journal["op"])["state"], "Restored")
        self.assertFalse(self.fragment.exists())
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_syntax_failure_retains_recovery_without_nonspecific_reload(self):
        self.force_bad_syntax = True
        with self.assertRaises(guard.GuardError) as captured:
            self.operate("apply")
        self.assertEqual(captured.exception.stage, "recovered")
        op = captured.exception.recovery_id
        self.assertFalse(self.active)
        self.assertFalse(self.fragment.exists())
        self.assertTrue((self.ext / guard._retained(27, op)).exists())
        self.assertEqual(self.operate("recheck")["state"], "Recovery Required")
        self.force_bad_syntax = False
        self.assertEqual(self.operate("restore", recovery=op)["state"], "Restored")
        self.assertFalse((self.ext / guard._retained(27, op)).exists())

    def test_postcheck_failure_preserves_guard_and_requires_restore(self):
        self.force_bad_proof = True
        with self.assertRaises(guard.GuardError) as captured:
            self.operate("apply")
        self.assertEqual(captured.exception.stage, "uncertain")
        op = captured.exception.recovery_id
        self.assertTrue(self.fragment.exists())
        self.assertTrue(self.active)
        self.assertEqual(self.operate("recheck")["state"], "Recovery Required")
        self.force_bad_proof = False
        restored = self.operate("restore", recovery=op)
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(self.fragment.exists())
        self.assertFalse(self.active)

    def test_unsupported_root_shape_must_fail_before_writes(self):
        for invalid in ("/www/acdomains/../foreign", "/www//acdomains/site",
                        "relative/root", "/www/custom site"):
            with self.subTest(path=invalid):
                self.site["path"] = invalid
                with self.assertRaises(guard.GuardError):
                    self.operate("apply")
                self.assertFalse(self.fragment.exists())
                self.assertEqual(list(self.state.iterdir()), [])

    def test_failed_recovery_id_or_applied_record_does_not_permit_clobber(self):
        applied = self.operate("apply")
        self.assertEqual(self.operate("recheck")["state"], "Applied")
        with self.assertRaises(guard.GuardError):
            self.operate("apply")
        self.fragment.write_bytes(b"tampered by foreign source")
        with self.assertRaises(guard.GuardError):
            self.operate("restore", recovery=applied["recovery_id"])
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")


if __name__ == "__main__":
    unittest.main()
