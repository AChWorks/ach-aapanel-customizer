"""Opt-in native aaPanel Nginx sensitive-file guard and recovery tests.

These tests model aaPanel's own per-site *.conf include ownership and real
worker generation transitions. Native HTTP proof is separately tested in the
isolated aaPanel VM; these tests never reload the host Nginx.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
        self.assertIn(kind, guard.XMLRPC_PROOF_KINDS)
        if self.active and not self.force_bad_proof:
            return (403, op)
        return (404, None)

    def operate(self, action="preview", **kwargs):
        source = guard._sha(self.vhost.read_bytes())
        variant = (guard.RULESET_XMLRPC if kwargs.get("xmlrpc", False) else guard.RULESET)
        proposal = guard._proposal_sha(variant)
        return guard.manage_guard(
            action, self.site, data_fd=self.fd,
            approved=kwargs.get("approved", True),
            expected_vhost=kwargs.get("source", source),
            expected_proposal=kwargs.get("proposal", proposal),
            expected_recovery=kwargs.get("recovery"),
            vhost_root=str(self.vhost_root),
            nginx_conf=str(self.nginx_conf), nginx="/test/nginx",
            runner=self.runner, probe=self.probe,
            block_xmlrpc=kwargs.get("xmlrpc", False))

    def test_rule_names_and_proof_paths_are_fixed_and_site_path_independent(self):
        self.assertEqual(len(guard.PROOF_KINDS), 14)
        sample = guard._include("a" * 32).decode()
        self.assertEqual(sample.count("return 403 "), 4)
        self.assertEqual(sample.count("ACh-Guard-Proof-"), 4)
        self.assertIn("wp-content/uploads", guard._probe_path("a" * 32, "wp_uploaded_php"))
        self.assertIn("[.]htaccess", sample)
        self.assertNotIn("wwwroot", sample)
        self.assertNotIn(str(self.site_root), sample)
        self.assertNotIn(".well-known", sample)
        self.assertIn("if ($uri ~*", sample)
        self.assertNotIn("location ~", sample)
        with self.assertRaises(guard.GuardError):
            guard._probe_path("a" * 32, "http://evil.invalid/")

    def test_simple_file_protection_avoids_redundant_directory_listing_rules(self):
        source = guard._include("f" * 32).decode()
        patterns = re.findall(r'if \(\$uri ~\* "([^"]+)"\)', source)
        self.assertEqual(len(patterns), 4)
        self.assertNotIn("autoindex", source)
        self.assertNotIn("location ", source)
        # URL matching is against Nginx's normalized $uri, at any site root.
        sensitive = (
            "/debug.log", "/wp-content/debug.log", "/wp-content/uploads/debug.log",
            "/logs/error_log", "/logs/error_log.1", "/error.log",
            "/backup.sql", "/dir/data.sql.gz", "/dir/sqlite-store.sqlite3",
            "/wp-config.php.bak", "/wp-config.php.old", "/wp-config.php~",
            "/assets/tooling.bak", "/assets/tooling.backup",
            "/path/backups/archive.zip", "/nested/.env.local",
            "/wp-content/uploads/test.PHP",
        )
        ordinary = (
            "/", "/wp-content/uploads/", "/wp-content/plugins/",
            "/wp-content/uploads/photo.jpg", "/uploads/public-report.zip",
            "/public.txt", "/index.html", "/assets/app.js",
            "/assets/public.log", "/images/backup-banner.jpg",
            "/.well-known/acme-challenge/random-token", "/oauth/callback",
            "/wp-json/api", "/docs/README.pdf",
        )
        for path in sensitive:
            with self.subTest(denied=path):
                self.assertTrue(any(re.search(pattern, path, re.I) for pattern in patterns),
                                path)
        for path in ordinary:
            with self.subTest(allowed=path):
                self.assertFalse(any(re.search(pattern, path, re.I) for pattern in patterns),
                                 path)

    def test_opt_in_nginx_xmlrpc_stays_in_one_owned_guard_and_restores(self):
        default = self.operate("preview")
        opted = self.operate("preview", xmlrpc=True)
        self.assertEqual(default["ruleset"], guard.RULESET)
        self.assertEqual(opted["ruleset"], guard.RULESET_XMLRPC)
        self.assertTrue(opted["block_xmlrpc"])
        self.assertNotEqual(default["proposal_sha256"], opted["proposal_sha256"])
        self.assertNotIn("xmlrpc", guard._include("f" * 32).decode())
        self.assertIn("^/xmlrpc[.]php$", guard._include(
            "f" * 32, guard.RULESET_XMLRPC).decode())
        self.assertIn("return 403", guard._include("f" * 32, guard.RULESET_XMLRPC).decode())
        self.assertNotIn(".well-known", guard._include("f" * 32, guard.RULESET_XMLRPC).decode())
        with self.assertRaisesRegex(guard.GuardError, "changed"):
            self.operate("apply", xmlrpc=True, proposal=default["proposal_sha256"])
        result = self.operate("apply", xmlrpc=True)
        self.assertEqual(result["state"], "Applied")
        self.assertTrue(result["block_xmlrpc"])
        self.assertEqual(self.operate("recheck")["ruleset"], guard.RULESET_XMLRPC)
        self.assertEqual(self.operate("recheck")["state"], "Applied")
        self.assertEqual(self.fragment.read_bytes(),
                         guard._include(result["recovery_id"], guard.RULESET_XMLRPC))
        self.assertEqual(self.operate("restore", recovery=result["recovery_id"])["state"],
                         "Restored")
        self.assertFalse(self.fragment.exists())
        # Both current options use one selected-site journal and Restore.
        old = self.operate("apply")
        self.assertEqual(self.operate("recheck")["ruleset"], guard.RULESET)
        self.assertEqual(self.operate("restore", recovery=old["recovery_id"])["state"],
                         "Restored")

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

    def test_native_new_site_missing_extension_reports_manual_prerequisite(self):
        original = self.vhost.read_text()
        self.vhost.write_text(original.replace(
            "include " + str(self.ext) + "/*.conf;\n", ""))
        with self.assertRaisesRegex(
                guard.GuardError, "New native VHost has no selected-site extension include"):
            guard._source_safe(self.site, vhost_root=str(self.vhost_root),
                               nginx_conf=str(self.nginx_conf))
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertFalse(self.fragment.exists())

    def test_manual_reapply_after_restored_source_was_regenerated(self):
        first = self.operate("apply")
        self.operate("restore", recovery=first["recovery_id"])
        self.vhost.write_text(self.vhost.read_text().replace(
            "include enable-php-85.conf;",
            "add_header X-Owner-Setting yes;\ninclude enable-php-85.conf;"))
        review = self.operate("preview")
        self.assertEqual(review["state"], "Restored")
        self.assertNotEqual(review["vhost_sha256"], first["vhost_sha256"])
        applied = self.operate("apply", source=review["vhost_sha256"])
        self.assertEqual(applied["state"], "Applied")
        self.assertNotEqual(applied["recovery_id"], first["recovery_id"])
        self.assertEqual(self.operate("restore", recovery=applied["recovery_id"])["state"],
                         "Restored")

    def _large_native_inventory(self, *, extension_comment_bytes=0):
        """Complete native inventory, including >1 MiB of valid sources."""
        for number in range(136):
            name = f"peer-{number:03d}.invalid"
            (self.vhost_root / (name + ".conf")).write_text(
                f"server {{\nlisten 80;\nserver_name {name};\n}}\n")
        for number in range(40):
            (self.ext / f"foreign_{number:03d}.conf").write_text(
                f"add_header X-Peer-{number} yes;\n"
                + ("# " + "x" * extension_comment_bytes + "\n"
                   if extension_comment_bytes else ""))
        self.site["bound_domains"].extend(
            {"name": f"alias-{number:03d}.invalid", "port": 80}
            for number in range(140))

    def test_complete_large_native_inventory_applies_and_restores_without_touching_peers(self):
        self._large_native_inventory(extension_comment_bytes=30_000)
        self.assertEqual(len(self.site["bound_domains"]), 141)
        self.assertGreater(sum(p.stat().st_size for p in self.ext.glob("*.conf")),
                           1024 * 1024)
        peer = self.vhost_root / "peer-135.invalid.conf"
        foreign = self.ext / "foreign_039.conf"
        peer_bytes = peer.read_bytes()
        preview = self.operate("preview")
        self.assertEqual(preview["state"], "Unmanaged")
        # The final source must participate in the precondition, not silently
        # disappear when the 33rd extension or 129th peer is discovered.
        foreign.write_text("add_header X-Peer-39 changed;\n")
        with self.assertRaisesRegex(guard.GuardError, "changed"):
            self.operate("apply", source=preview["vhost_sha256"])
        self.assertFalse(self.fragment.exists())
        latest = self.operate("preview")
        self.assertNotEqual(latest["vhost_sha256"], preview["vhost_sha256"])
        applied = self.operate("apply", source=latest["vhost_sha256"])
        self.assertEqual(applied["state"], "Applied")
        reviewed = self.operate("recheck")
        self.assertEqual(reviewed["state"], "Applied")
        self.assertEqual(self.operate("restore", recovery=applied["recovery_id"],
                                      source=reviewed["vhost_sha256"])["state"], "Restored")
        self.assertEqual(peer.read_bytes(), peer_bytes)
        self.assertEqual(foreign.read_text(), "add_header X-Peer-39 changed;\n")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")
        self.assertEqual(len([c for c in self.commands if "reload" in c]), 2)

    def test_large_inventory_still_rejects_ownership_conflict_in_last_peer(self):
        self._large_native_inventory()
        peer = self.vhost_root / "peer-135.invalid.conf"
        peer.write_text(
            "server {\nserver_name peer-135.invalid;\n"
            f"include {self.ext}/*.conf;\n}}\n")
        with self.assertRaises(guard.ExtensionError) as blocked:
            self.operate("apply")
        self.assertEqual(blocked.exception.stage, "ownership")
        self.assertFalse(self.fragment.exists())
        self.assertFalse(list(self.state.iterdir()))
        self.assertFalse(self.commands)

        peer.write_text("server { server_name peer-135.invalid; }\n")
        self.site["bound_domains"].append(
            {"name": "alias-139.invalid", "port": 80})
        with self.assertRaisesRegex(guard.GuardError, "Duplicate"):
            self.operate("apply")
        self.assertFalse(self.fragment.exists())
        self.assertFalse(self.commands)

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
        reviewed = self.operate("recheck")
        self.assertEqual(reviewed["state"], "Applied")
        self.assertEqual(self.operate("restore", recovery=applied["recovery_id"],
                                      source=reviewed["vhost_sha256"])["state"], "Restored")
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

    def test_live_native_domain_change_can_restore_exact_owned_guard_without_undo(self):
        applied = self.operate("apply")
        original = self.vhost.read_text()
        self.site["bound_domains"].append({"name": "alias.invalid", "port": 80})
        changed = original.replace(
            "server_name secure.invalid;", "server_name secure.invalid alias.invalid;")
        self.vhost.write_text(changed)
        self.assertNotEqual(guard._sha(changed.encode()), applied["vhost_sha256"])
        review = self.operate("recheck")
        self.assertEqual(review["state"], "Recovery Required")
        self.assertEqual(review["journal_phase"], "applied")
        self.assertFalse(review["runtime_verified"])
        self.assertEqual(review["recovery_id"], applied["recovery_id"])
        self.assertTrue(self.fragment.exists())
        with self.assertRaises(guard.GuardError):
            self.operate("apply")
        restored = self.operate("restore", recovery=review["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(self.fragment.exists())
        self.assertEqual(self.vhost.read_text(), changed)
        self.assertEqual(self.operate("preview")["state"], "Restored")
        reinstalled = self.operate("apply")
        self.assertEqual(reinstalled["state"], "Applied")
        self.assertEqual(self.operate("restore", recovery=reinstalled["recovery_id"])[
            "state"], "Restored")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_stale_drift_restore_fails_before_mutation_or_reload(self):
        applied = self.operate("apply")
        self.vhost.write_text(self.vhost.read_text().replace(
            "server_name secure.invalid;",
            "server_name secure.invalid;\n# aaPanel edit B"))
        review_b = self.operate("recheck")
        self.assertEqual(review_b["state"], "Recovery Required")
        self.assertEqual(review_b["recovery_scope"], "native_source_drift")

        # A second valid native VHost change must invalidate B's approval,
        # even though site identity, root and the owned Guard remain exact.
        self.vhost.write_text(self.vhost.read_text() + "# aaPanel edit C\n")
        source_c = self.vhost.read_bytes()
        before = list(self.commands)
        with self.assertRaises(guard.GuardError) as stale:
            self.operate("restore", recovery=applied["recovery_id"],
                         source=review_b["vhost_sha256"])
        self.assertEqual(stale.exception.stage, "concurrency")
        self.assertIn("Recheck", str(stale.exception))
        self.assertEqual(self.commands, before)
        self.assertTrue(self.fragment.exists())
        self.assertEqual(self.vhost.read_bytes(), source_c)
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

        review_c = self.operate("recheck")
        self.assertNotEqual(review_c["vhost_sha256"], review_b["vhost_sha256"])
        sibling = self.ext / "unrelated_module.conf"
        sibling.write_text("add_header X-Unrelated yes;\n")
        sibling.chmod(0o600)
        prior_commands = list(self.commands)
        with self.assertRaises(guard.GuardError) as stale_sibling:
            self.operate("restore", recovery=applied["recovery_id"],
                         source=review_c["vhost_sha256"])
        self.assertEqual(stale_sibling.exception.stage, "concurrency")
        self.assertEqual(self.commands, prior_commands)
        self.assertTrue(self.fragment.exists())
        self.assertEqual(sibling.read_text(), "add_header X-Unrelated yes;\n")

        # Even direct callers must supply reviewed source evidence, not
        # merely the durable Recovery ID and a current site snapshot.
        with self.assertRaises(guard.GuardError) as missing:
            self.operate("restore", recovery=applied["recovery_id"],
                         source=None)
        self.assertEqual(missing.exception.stage, "concurrency")
        self.assertEqual(self.commands, prior_commands)

        review_d = self.operate("recheck")
        self.assertEqual(review_d["state"], "Recovery Required")
        self.assertNotEqual(review_d["vhost_sha256"], review_c["vhost_sha256"])
        restored = self.operate("restore", recovery=applied["recovery_id"],
                                source=review_d["vhost_sha256"])
        self.assertEqual(restored["state"], "Restored")
        self.assertTrue(restored["runtime_verified"])
        self.assertFalse(self.fragment.exists())
        self.assertFalse(self.active)
        self.assertEqual(self.vhost.read_bytes(), source_c)
        self.assertEqual(sibling.read_text(), "add_header X-Unrelated yes;\n")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")
        self.assertEqual(len([c for c in self.commands if "reload" in c]), 2)

    def test_restore_rechecks_source_after_syntax_check_before_retirement(self):
        applied = self.operate("apply")
        reviewed = self.operate("recheck")
        self.assertEqual(reviewed["state"], "Applied")
        sibling = self.ext / "new_native_extension.conf"
        original_runner = self.runner
        changed = False

        def native_writer_during_syntax(argv, **kw):
            nonlocal changed
            if "-t" in argv and not changed:
                changed = True
                sibling.write_text("add_header X-New-Site-State observed;\n")
                sibling.chmod(0o600)
            return original_runner(argv, **kw)

        self.runner = native_writer_during_syntax
        try:
            with self.assertRaises(guard.GuardError) as interrupted:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=reviewed["vhost_sha256"])
        finally:
            self.runner = original_runner
        self.assertTrue(changed)
        self.assertEqual(interrupted.exception.stage, "concurrency")
        self.assertTrue(self.fragment.exists(), "No owned-file rename on late drift")
        self.assertEqual(len([c for c in self.commands if "reload" in c]), 1)
        self.assertEqual(sibling.read_text(),
                         "add_header X-New-Site-State observed;\n")

        fresh = self.operate("recheck")
        self.assertEqual(fresh["state"], "Recovery Required")
        self.assertEqual(fresh["recovery_scope"], "native_source_drift")
        self.assertNotEqual(fresh["vhost_sha256"], reviewed["vhost_sha256"])
        self.assertEqual(self.operate(
            "restore", recovery=fresh["recovery_id"],
            source=fresh["vhost_sha256"])["state"], "Restored")
        self.assertEqual(sibling.read_text(),
                         "add_header X-New-Site-State observed;\n")
        self.assertEqual(self.foreign.read_bytes(),
                         b"Never change any unrelated site")

    def test_source_edit_during_final_syntax_never_reloads_unreviewed_source(self):
        for change in ("vhost", "sibling"):
            with self.subTest(change=change):
                applied = self.operate("apply")
                checked = self.operate("recheck")
                retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
                vhost_before = self.vhost.read_bytes()
                sibling = self.ext / "late_sibling.conf"
                syntax_calls = 0
                previous_runner = self.runner

                def edit_during_second_check(argv, **kw):
                    nonlocal syntax_calls
                    if "-t" in argv:
                        syntax_calls += 1
                        if syntax_calls == 2:
                            if change == "vhost":
                                self.vhost.write_bytes(
                                    self.vhost.read_bytes() + b"# Valid concurrent VHost edit\n")
                            else:
                                sibling.write_bytes(b"add_header X-External yes;\n")
                                sibling.chmod(0o600)
                    return previous_runner(argv, **kw)

                reloads_before = len([x for x in self.commands if "reload" in x])
                self.runner = edit_during_second_check
                try:
                    with self.assertRaises(guard.GuardError) as error:
                        self.operate("restore", recovery=applied["recovery_id"],
                                     source=checked["vhost_sha256"])
                finally:
                    self.runner = previous_runner
                self.assertEqual(syntax_calls, 2)
                self.assertEqual(error.exception.stage, "uncertain")
                self.assertEqual(error.exception.recovery_id, applied["recovery_id"])
                self.assertIn("no reload", str(error.exception))
                self.assertEqual(len([x for x in self.commands if "reload" in x]),
                                 reloads_before)
                self.assertFalse(self.fragment.exists())
                self.assertEqual(retained.read_bytes(), guard._include(applied["recovery_id"]))
                journal = json.loads((self.state / guard._journal(self.site["id"])).read_text())
                self.assertEqual(journal["phase"], "applied")
                self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")
                self.assertEqual(self.vhost.read_bytes(), vhost_before +
                                 (b"# Valid concurrent VHost edit\n" if change == "vhost" else b""))
                if change == "sibling":
                    self.assertEqual(sibling.read_bytes(), b"add_header X-External yes;\n")

                fresh = self.operate("recheck")
                self.assertEqual(fresh["state"], "Recovery Required")
                self.assertEqual(fresh["recovery_scope"], "native_source_drift")
                self.assertNotEqual(fresh["vhost_sha256"], checked["vhost_sha256"])
                self.assertEqual(self.operate(
                    "restore", recovery=fresh["recovery_id"],
                    source=fresh["vhost_sha256"])["state"], "Restored")
                self.assertFalse(retained.exists())
                if sibling.exists():
                    sibling.unlink()

    def test_first_syntax_foreign_live_edit_is_refused_without_rename(self):
        applied = self.operate("apply")
        checked = self.operate("recheck")
        foreign = b"add_header X-Foreign-Valid yes;\n"
        previous_runner = self.runner
        written = False

        def edit_during_first_check(argv, **kw):
            nonlocal written
            if "-t" in argv and not written:
                written = True
                self.fragment.write_bytes(foreign)
            return previous_runner(argv, **kw)

        reloads = len([x for x in self.commands if "reload" in x])
        self.runner = edit_during_first_check
        try:
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        finally:
            self.runner = previous_runner
        self.assertTrue(written)
        self.assertEqual(error.exception.stage, "concurrency")
        self.assertEqual(self.fragment.read_bytes(), foreign)
        self.assertFalse((self.ext / guard._retained(
            self.site["id"], applied["recovery_id"])).exists())
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads)
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")

    def _assert_foreign_guard_swap_is_rolled_back(self, timing):
        applied = self.operate("apply")
        checked = self.operate("recheck")
        original_rename = guard._rename_noreplace
        foreign = ("add_header X-Foreign-%s yes;\n" % timing).encode()
        triggered = False

        def edit_during_rename(fd, before, after):
            nonlocal triggered
            if before == guard._file(self.site["id"]) and not triggered:
                triggered = True
                if timing == "before":
                    self.fragment.write_bytes(foreign)
                original_rename(fd, before, after)
                if timing == "after":
                    (self.ext / after).write_bytes(foreign)
                return
            return original_rename(fd, before, after)

        reloads = len([x for x in self.commands if "reload" in x])
        with patch.object(guard, "_rename_noreplace", side_effect=edit_during_rename):
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        self.assertTrue(triggered)
        self.assertEqual(error.exception.stage, "concurrency")
        self.assertEqual(self.fragment.read_bytes(), foreign)
        self.assertFalse((self.ext / guard._retained(
            self.site["id"], applied["recovery_id"])).exists())
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads)
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_foreign_guard_swapped_before_rename_rolls_back_without_reload(self):
        self._assert_foreign_guard_swap_is_rolled_back("before")

    def test_foreign_guard_swapped_after_rename_rolls_back_without_reload(self):
        self._assert_foreign_guard_swap_is_rolled_back("after")

    def test_retained_guard_changed_during_final_syntax_does_not_reload(self):
        applied = self.operate("apply")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        self.fragment.rename(retained)
        checked = self.operate("recheck")
        self.assertEqual(checked["state"], "Recovery Required")
        previous_runner = self.runner
        syntax_checks = 0
        foreign = b"add_header X-Foreign-Retained yes;\n"

        def change_during_final_syntax(argv, **kw):
            nonlocal syntax_checks
            if "-t" in argv:
                syntax_checks += 1
                if syntax_checks == 2:
                    retained.write_bytes(foreign)
            return previous_runner(argv, **kw)

        reloads = len([x for x in self.commands if "reload" in x])
        self.runner = change_during_final_syntax
        try:
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        finally:
            self.runner = previous_runner
        self.assertEqual(syntax_checks, 2)
        self.assertEqual(error.exception.stage, "concurrency")
        self.assertEqual(retained.read_bytes(), foreign)
        self.assertFalse(self.fragment.exists())
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads)
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")

    def test_replacement_inode_is_not_moved_back_to_live_guard_path(self):
        applied = self.operate("apply")
        checked = self.operate("recheck")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        original_rename = guard._rename_noreplace
        replaced = False

        def replace_inode_after_rename(fd, before, after):
            nonlocal replaced
            original_rename(fd, before, after)
            if before == guard._file(self.site["id"]) and not replaced:
                replaced = True
                original = retained.read_bytes()
                retained.unlink()
                retained.write_bytes(original)
                retained.chmod(0o600)

        reloads = len([x for x in self.commands if "reload" in x])
        with patch.object(guard, "_rename_noreplace", side_effect=replace_inode_after_rename):
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        self.assertTrue(replaced)
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(error.exception.recovery_id, applied["recovery_id"])
        self.assertFalse(self.fragment.exists())
        self.assertEqual(retained.read_bytes(), guard._include(applied["recovery_id"]))
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads)
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")
        self.assertEqual(self.operate("recheck")["state"], "Recovery Required")

    def test_occupied_guard_name_preserves_foreign_file_and_recovery_journal(self):
        applied = self.operate("apply")
        checked = self.operate("recheck")
        foreign = b"add_header X-Foreign-Collision yes;\n"
        previous_rename = guard._rename_noreplace
        injected = False

        def concurrent_name_collision(fd, before, after):
            nonlocal injected
            previous_rename(fd, before, after)
            if before == guard._file(self.site["id"]) and not injected:
                injected = True
                self.fragment.write_bytes(foreign)
                self.fragment.chmod(0o600)

        reloads = len([x for x in self.commands if "reload" in x])
        with patch.object(guard, "_rename_noreplace", side_effect=concurrent_name_collision):
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        self.assertTrue(injected)
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(error.exception.recovery_id, applied["recovery_id"])
        self.assertEqual(self.fragment.read_bytes(), foreign)
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        self.assertEqual(retained.read_bytes(), guard._include(applied["recovery_id"]))
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads)
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_retired_symlink_is_never_reintroduced_into_live_nginx_include(self):
        applied = self.operate("apply")
        checked = self.operate("recheck")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        previous_rename = guard._rename_noreplace
        replaced = False

        def symlink_after_retirement(fd, before, after):
            nonlocal replaced
            previous_rename(fd, before, after)
            if before == guard._file(self.site["id"]) and not replaced:
                replaced = True
                retained.unlink()
                retained.symlink_to(self.foreign)

        reloads = len([x for x in self.commands if "reload" in x])
        with patch.object(guard, "_rename_noreplace", side_effect=symlink_after_retirement):
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        self.assertTrue(replaced)
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(error.exception.recovery_id, applied["recovery_id"])
        self.assertFalse(self.fragment.exists())
        self.assertTrue(retained.is_symlink())
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads)
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")

    def test_post_reload_retained_change_cannot_commit_false_restored(self):
        applied = self.operate("apply")
        checked = self.operate("recheck")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        previous_runner = self.runner
        foreign = b"add_header X-External-After-Reload yes;\n"
        edited = False

        def change_after_reload(argv, **kw):
            nonlocal edited
            result = previous_runner(argv, **kw)
            if "-s" in argv and "reload" in argv and not edited:
                edited = True
                retained.write_bytes(foreign)
            return result

        reloads = len([x for x in self.commands if "reload" in x])
        self.runner = change_after_reload
        try:
            with self.assertRaises(guard.GuardError) as error:
                self.operate("restore", recovery=applied["recovery_id"],
                             source=checked["vhost_sha256"])
        finally:
            self.runner = previous_runner
        self.assertTrue(edited)
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(error.exception.recovery_id, applied["recovery_id"])
        self.assertEqual(retained.read_bytes(), foreign)
        self.assertFalse(self.fragment.exists())
        self.assertEqual(len([x for x in self.commands if "reload" in x]), reloads + 1)
        self.assertEqual(json.loads((self.state / guard._journal(
            self.site["id"])).read_text())["phase"], "applied")
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_interrupted_restore_exact_retained_with_unchanged_vhost(self):
        applied = self.operate("apply")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        original_source = self.vhost.read_bytes()
        self.fragment.rename(retained)
        checked = self.operate("recheck")
        self.assertEqual(checked["state"], "Recovery Required")
        self.assertEqual(checked["journal_phase"], "applied")
        self.assertEqual(checked["recovery_scope"], "interrupted_restore")
        self.assertFalse(checked["runtime_verified"])
        self.assertEqual(checked["recovery_id"], applied["recovery_id"])
        restored = self.operate("restore", recovery=checked["recovery_id"],
                                source=checked["vhost_sha256"])
        self.assertEqual(restored["state"], "Restored")
        self.assertTrue(restored["runtime_verified"])
        self.assertFalse(self.fragment.exists())
        self.assertFalse(retained.exists())
        self.assertFalse(self.active)
        self.assertEqual(self.vhost.read_bytes(), original_source)
        saved = json.loads((self.state / guard._journal(self.site["id"])).read_text())
        self.assertEqual(saved["phase"], "restored")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_applied_guard_live_retained_ownership_matrix_with_and_without_drift(self):
        applied = self.operate("apply")
        owned = self.fragment.read_bytes()
        original = self.vhost.read_text()
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        cases = {
            "live_exact": ("Applied", "Recovery Required"),
            "retained_exact": ("Recovery Required", "Recovery Required"),
            "duplicated_exact": ("Needs Review", "Needs Review"),
            "live_altered": ("Needs Review", "Needs Review"),
            "retained_altered": ("Needs Review", "Needs Review"),
            "both_altered": ("Needs Review", "Needs Review"),
            "missing": ("Needs Review", "Needs Review"),
        }
        for drift in (False, True):
            self.vhost.write_text(original + ("# aaPanel changed VHost\n" if drift else ""))
            for kind, states in cases.items():
                with self.subTest(source_drift=drift, ownership=kind):
                    for path in (self.fragment, retained):
                        if path.exists():
                            path.unlink()
                    if kind in ("live_exact", "duplicated_exact"):
                        self.fragment.write_bytes(owned)
                        self.fragment.chmod(0o600)
                    elif kind in ("live_altered", "both_altered"):
                        self.fragment.write_bytes(b"foreign live\n")
                        self.fragment.chmod(0o600)
                    if kind in ("retained_exact", "duplicated_exact"):
                        retained.write_bytes(owned)
                        retained.chmod(0o600)
                    elif kind in ("retained_altered", "both_altered"):
                        retained.write_bytes(b"foreign retained\n")
                        retained.chmod(0o600)
                    checked = self.operate("recheck")
                    expected = states[int(drift)]
                    self.assertEqual(checked["state"], expected)
                    self.assertEqual(checked["runtime_verified"], expected == "Applied")
                    if expected == "Recovery Required":
                        scope = ("native_source_drift" if drift
                                 else "interrupted_restore")
                        self.assertEqual(checked["recovery_scope"], scope)
                    if expected == "Needs Review":
                        before = list(self.commands)
                        before_files = {
                            path: path.read_bytes() if path.exists() else None
                            for path in (self.fragment, retained)}
                        with self.assertRaises(guard.GuardError):
                            self.operate("restore", recovery=applied["recovery_id"],
                                         source=checked["vhost_sha256"])
                        self.assertEqual(
                            len([c for c in self.commands if "reload" in c]),
                            len([c for c in before if "reload" in c]))
                        for path, content in before_files.items():
                            self.assertEqual(
                                path.read_bytes() if path.exists() else None, content)
                    self.assertEqual(self.foreign.read_bytes(),
                                     b"Never change any unrelated site")

    def test_drift_during_interrupted_restore_recovers_retired_exact_rule(self):
        applied = self.operate("apply")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        self.fragment.rename(retained)
        self.site["bound_domains"].append({"name": "alias.invalid", "port": 80})
        self.vhost.write_text(self.vhost.read_text().replace(
            "server_name secure.invalid;", "server_name secure.invalid alias.invalid;"))
        review = self.operate("recheck")
        self.assertEqual(review["state"], "Recovery Required")
        self.assertEqual(review["recovery_scope"], "native_source_drift")
        self.assertEqual(self.operate("restore", recovery=applied["recovery_id"])[
            "state"], "Restored")
        self.assertFalse(self.fragment.exists())
        self.assertFalse(retained.exists())
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

    def test_drift_with_ambiguous_live_and_retired_copies_refuses_restore(self):
        applied = self.operate("apply")
        retained = self.ext / guard._retained(self.site["id"], applied["recovery_id"])
        retained.write_bytes(self.fragment.read_bytes())
        retained.chmod(0o600)
        self.vhost.write_text(self.vhost.read_text().replace(
            "server_name secure.invalid;", "server_name secure.invalid;\n# native edit"))
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        with self.assertRaises(guard.GuardError):
            self.operate("restore", recovery=applied["recovery_id"])
        self.assertTrue(self.fragment.exists())
        self.assertTrue(retained.exists())

    def test_live_native_source_drift_refuses_tampered_guard_recovery(self):
        applied = self.operate("apply")
        self.site["bound_domains"].append({"name": "alias.invalid", "port": 80})
        self.vhost.write_text(self.vhost.read_text().replace(
            "server_name secure.invalid;", "server_name secure.invalid alias.invalid;"))
        self.fragment.write_bytes(b"foreign changed rule\n")
        self.assertEqual(self.operate("recheck")["state"], "Needs Review")
        with self.assertRaises(guard.GuardError):
            self.operate("restore", recovery=applied["recovery_id"])
        self.assertEqual(self.fragment.read_bytes(), b"foreign changed rule\n")
        self.assertEqual(self.foreign.read_bytes(), b"Never change any unrelated site")

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
