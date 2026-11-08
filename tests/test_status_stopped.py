"""Stopped-site 503: native SiteStop/Start string substitutions, CAS and recovery."""
import hashlib
import os
import re
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_status_stopped as subject
from ach_customizer_status_pages import DEFAULT_BRAND, render_page
from ach_customizer_state import _open_state_dir

sha = lambda b: hashlib.sha256(b).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-stopped-503-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vhosts = self.root / "native"
        self.state = self.root / "data"
        self.vhosts.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        self.site = {"id": 7, "name": "test-site.example", "path": "/www/wwwroot/test-site.example",
                     "status": "1", "bound_domains": [{"name": "test-site.example", "port": 80}]}
        self.conf = self.vhosts / (self.site["name"] + ".conf")
        self.original = (
            b"server\n{\n"
            b"    listen 80;\n"
            b"    listen 443 ssl;\n"
            b"    server_name test-site.example;\n"
            b"    root /www/wwwroot/test-site.example;\n"
            b"    include /www/server/panel/vhost/nginx/extension/test-site.example/*.conf;\n"
            b"    #SSL-START SSL related configuration\n"
            b"    location ~ \\.php$ { return 404; }\n"
            b"}\n"
        )
        self.conf.write_bytes(self.original)
        self.conf.chmod(0o600)
        self.fd = _open_state_dir(self.state)
        self.addCleanup(os.close, self.fd)
        self.html = render_page("en", "stopped")["html"]
        self.fail_reload = False
        self.fail_syntax_when_block = False
        self.nginx_calls = []
        self.active = self.original

    def runner(self, argv, **kw):
        self.nginx_calls.append(tuple(argv))
        if "-T" in argv:
            text = ("# configuration file /www/server/panel/vhost/nginx/" +
                    self.conf.name + ":\n").encode() + self.conf.read_bytes() + b"\n"
            return types.SimpleNamespace(returncode=0, stdout=text, stderr=b"")
        if "-t" in argv:
            return types.SimpleNamespace(returncode=(1 if self.fail_syntax_when_block and
                b"ACh stopped503 begin" in self.conf.read_bytes() else 0))
        if "-s" in argv and "reload" in argv:
            if self.fail_reload:
                return types.SimpleNamespace(returncode=1)
            self.active = self.conf.read_bytes()
            return types.SimpleNamespace(returncode=0)
        raise AssertionError(argv)

    def probe(self, site, *, stopped):
        if stopped:
            record = subject._record_load(self.fd, self.site)
            if record and b"# ACh stopped503 begin" in self.active:
                return 503, record["body_sha"], "text/html"
            return 200, sha(b"original stopped HTML"), "text/html"
        if b"root /www/server/stop;" in self.active:
            return 503, sha(b"unknown"), "text/plain"
        return 200, sha(b"running test site"), "text/html"

    def call(self, action="recheck", **kwargs):
        probe = kwargs.pop("probe", self.probe)
        return subject.manage_stopped(
            action, self.site, self.html, data_fd=self.fd,
            vhost_root=str(self.vhosts),
            nginx=self.root.as_posix()+"/nginx",
            nginx_conf=self.root.as_posix()+"/nginx.conf",
            runner=self.runner, probe=probe, **kwargs,
        )

    def apply(self):
        before = self.call()
        self.assertEqual(before["state"], "Source Ready")
        return self.call("apply", expected_vhost=before["vhost_sha256"],
                         expected_render=before["rendered_sha256"])

    def stop(self):
        self.site["status"] = "0"
        old = self.conf.read_bytes()
        new = old.replace(b"root /www/wwwroot/test-site.example",
                          b"root /www/server/stop").replace(b"include", b"#include")
        self.conf.write_bytes(new)
        self.active = new

    def start(self):
        self.site["status"] = "1"
        old = self.conf.read_bytes()
        new = old.replace(b"/www/server/stop", b"/www/wwwroot/test-site.example").replace(
            b"#include", b"include")
        self.conf.write_bytes(new)
        self.active = new


class StopTests(Fixture):
    def test_full_prepare_stop_start_restore_preserves_native_bytes(self):
        result = self.apply()
        self.assertEqual(result["state"], "Armed")
        self.assertFalse(result["runtime_verified"])
        self.assertNotEqual(self.conf.read_bytes(), self.original)
        self.assertEqual(self.call()["state"], "Armed")
        self.stop()
        self.assertEqual(self.call()["state"], "Applied")
        self.assertTrue(self.call()["runtime_verified"])
        self.assertEqual(self.probe(self.site, stopped=True)[0], 503)
        self.start()
        self.assertEqual(self.call()["state"], "Armed")
        self.assertEqual(self.conf.read_bytes().replace(
            subject._managed(self.site, self.html, result["recovery_id"])[0], b""), self.original)
        latest = self.call()
        recovered = self.call("restore", expected_recovery=result["recovery_id"],
                              expected_vhost=latest["vhost_sha256"])
        self.assertEqual(recovered["state"], "Restored")
        self.assertTrue(recovered["runtime_verified"])
        self.assertEqual(self.conf.read_bytes(), self.original)
        self.assertEqual(self.call()["state"], "Restored")
        self.assertEqual(len(list(self.state.glob("*.backup"))), 0)

    def test_stopped_restore_removes_only_owned_block(self):
        result = self.apply()
        self.stop()
        before = self.conf.read_bytes()
        restored = self.call("restore", expected_vhost=sha(before),
                              expected_recovery=result["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.conf.read_bytes(),
                         self.original.replace(b"root /www/wwwroot/test-site.example",
                                               b"root /www/server/stop").replace(
                                                   b"include", b"#include"))
        self.start()
        self.assertEqual(self.conf.read_bytes(), self.original)

    def test_preflight_refuses_stopped_or_wrong_identity_and_stale_hash(self):
        current = self.call()
        with self.assertRaisesRegex(subject.ExtensionError, "changed"):
            self.call("apply", expected_vhost="0"*64,
                      expected_render=current["rendered_sha256"])
        with self.assertRaisesRegex(subject.ExtensionError, "branding"):
            self.call("apply", expected_vhost=current["vhost_sha256"],
                      expected_render="1"*64)
        self.site["status"] = "0"
        with self.assertRaises(subject.ExtensionError):
            self.call("apply", expected_vhost=current["vhost_sha256"],
                      expected_render=current["rendered_sha256"])
        self.assertEqual(self.conf.read_bytes(), self.original)

    def test_foreign_owned_marker_without_journal_is_denied(self):
        self.conf.write_bytes(self.original.replace(
            subject.MARKER, b"    # ACh stopped503 begin " + b"0"*32 +
            b"\n" + subject.MARKER))
        with self.assertRaises(subject.ExtensionError):
            self.call()

    def test_reapply_after_restore_denies_foreign_stopped_rule(self):
        first = self.apply()
        self.call("restore", expected_vhost=sha(self.conf.read_bytes()),
                  expected_recovery=first["recovery_id"])
        unknown = self.original.replace(
            subject.MARKER,
            b"    # ACh stopped503 begin " + b"9"*32 + b"\n" + subject.MARKER)
        self.conf.write_bytes(unknown)
        state = self.call()
        self.assertEqual(state["state"], "Conflict")
        with self.assertRaises(subject.ExtensionError) as caught:
            self.call("apply", expected_vhost=state["vhost_sha256"],
                      expected_render=state["rendered_sha256"])
        self.assertEqual(caught.exception.stage, "conflict")
        self.assertEqual(self.conf.read_bytes(), unknown)

    def test_manual_edit_inside_owned_block_is_never_removed(self):
        result = self.apply()
        self.conf.write_bytes(self.conf.read_bytes().replace(
            b"    # ACh stopped503 end", b"    # ACh stopped503 edited"))
        self.assertEqual(self.call()["state"], "Recovery Required")
        with self.assertRaises(subject.ExtensionError):
            self.call("restore", expected_vhost=sha(self.conf.read_bytes()),
                      expected_recovery=result["recovery_id"])

    def test_manual_edit_outside_owned_block_is_preserved_on_restore(self):
        result = self.apply()
        self.conf.write_bytes(self.conf.read_bytes() + b"# external comment\n")
        latest = self.call()
        self.assertIn(latest["state"], ("Armed", "Needs Review"))
        restored = self.call("restore", expected_vhost=latest["vhost_sha256"],
                             expected_recovery=result["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.conf.read_bytes(), self.original + b"# external comment\n")

    def test_stopped_verified_http503_with_outside_block_drift_keeps_guarded_restore(self):
        armed = self.apply()
        self.stop()
        foreign = b"# independent native operator comment outside managed block\n"
        self.conf.write_bytes(self.conf.read_bytes() + foreign)
        self.active = self.conf.read_bytes()
        response = self.probe(self.site, stopped=True)
        self.assertEqual(response[0], 503)
        record = subject._record_load(self.fd, self.site)
        self.assertEqual(response[1], record["body_sha"])
        self.assertEqual(response[2], "text/html")
        recheck = self.call()
        self.assertEqual(recheck["state"], "Needs Review")
        self.assertFalse(recheck["runtime_verified"],
                         "Verified body alone cannot approve drifted native source")
        self.assertEqual(recheck["proof_kind"], "none")
        self.assertEqual(recheck["recovery_id"], armed["recovery_id"])
        self.assertEqual(recheck["vhost_sha256"], sha(self.conf.read_bytes()))
        self.assertEqual(recheck["served_sha256"], record["body_sha"])
        restored = self.call("restore", expected_vhost=recheck["vhost_sha256"],
                             expected_recovery=armed["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(restored["proof_kind"], "native_http200")
        self.assertEqual(restored["recovery_id"], armed["recovery_id"])
        expected_stopped = (
            self.original.replace(b"root /www/wwwroot/test-site.example",
                                  b"root /www/server/stop")
            .replace(b"include", b"#include") + foreign
        )
        self.assertEqual(self.conf.read_bytes(), expected_stopped)
        self.start()
        self.assertEqual(self.conf.read_bytes(), self.original + foreign)
        self.assertEqual(self.call()["state"], "Restored")
        self.assertEqual(len(list(self.state.glob("*.backup"))), 0)

    def test_reload_failure_retains_recovery_before_retry(self):
        before = self.call()
        self.fail_reload = True
        with self.assertRaisesRegex(subject.ExtensionError, "uncertain") as caught:
            self.call("apply", expected_vhost=before["vhost_sha256"],
                      expected_render=before["rendered_sha256"])
        self.assertEqual(len(caught.exception.recovery_id), 32)
        self.assertEqual(self.call()["state"], "Recovery Required")
        self.fail_reload = False
        recovery = self.call("restore", expected_vhost=sha(self.conf.read_bytes()),
                            expected_recovery=caught.exception.recovery_id)
        self.assertEqual(recovery["state"], "Restored")
        self.assertEqual(self.conf.read_bytes(), self.original)

    def test_symlink_native_vhost_and_unsafe_mode_denied(self):
        self.conf.unlink()
        foreign = self.root / "foreign"
        foreign.write_bytes(self.original)
        self.conf.symlink_to(foreign)
        with self.assertRaises(Exception): self.call()
        self.assertEqual(foreign.read_bytes(), self.original)
        self.conf.unlink()
        self.conf.write_bytes(self.original)
        self.conf.chmod(0o666)
        with self.assertRaises(Exception): self.call()

    def test_syntax_rejection_reverts_exact_original_native_vhost(self):
        before = self.call()
        self.fail_syntax_when_block = True
        with self.assertRaises(subject.ExtensionError) as error:
            self.call("apply", expected_vhost=before["vhost_sha256"],
                      expected_render=before["rendered_sha256"])
        self.assertEqual(error.exception.stage, "syntax")
        self.assertEqual(self.conf.read_bytes(), self.original)
        restored = self.call()
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(restored["recovery_id"], error.exception.recovery_id)

    def test_prepared_journal_with_no_published_block_restores_without_overwrite(self):
        before = self.call()
        with patch.object(subject, "_publish", side_effect=OSError("staged but not published")):
            with self.assertRaises(subject.ExtensionError) as err:
                self.call("apply", expected_vhost=before["vhost_sha256"],
                          expected_render=before["rendered_sha256"])
        self.assertEqual(err.exception.stage,"uncertain")
        self.assertEqual(self.conf.read_bytes(),self.original)
        stored=self.call()
        self.assertEqual(stored["state"],"Recovery Required")
        recovered=self.call("restore",expected_vhost=stored["vhost_sha256"],
                            expected_recovery=stored["recovery_id"])
        self.assertEqual(recovered["state"],"Restored")
        self.assertFalse(recovered["changed"])
        self.assertEqual(self.conf.read_bytes(),self.original)
        self.assertEqual(self.call()["state"],"Restored")

    def test_restoring_journal_with_removed_block_recovers_without_source_write(self):
        applied=self.apply()
        state=self.call()
        original_write=subject._record_save
        def interrupt(fd,site,entry):
            if entry["phase"]=="restored":
                raise OSError("simulated failed final journal save")
            return original_write(fd,site,entry)
        with patch.object(subject,"_record_save",side_effect=interrupt):
            with self.assertRaises(subject.ExtensionError) as error:
                self.call("restore",expected_vhost=state["vhost_sha256"],
                          expected_recovery=applied["recovery_id"])
        self.assertEqual(error.exception.stage,"uncertain")
        self.assertEqual(self.conf.read_bytes(),self.original)
        pending=self.call()
        self.assertEqual(pending["state"],"Recovery Required")
        restored=self.call("restore",expected_vhost=pending["vhost_sha256"],
                           expected_recovery=applied["recovery_id"])
        self.assertEqual(restored["state"],"Restored")
        self.assertFalse(restored["changed"])
        self.assertTrue(restored["runtime_verified"])
        self.assertEqual(self.conf.read_bytes(),self.original)

    def test_request_host_identity_is_raw_host_not_server_default_fallback(self):
        self.site["bound_domains"].append({"name": "alias.test-site.example", "port": 8080})
        regex = subject._request_host_pattern(self.site)
        for authority in ("test-site.example", "TEST-SITE.EXAMPLE",
                          "test-site.example.", "test-site.example:80",
                          "test-site.example:443", "alias.test-site.example",
                          "alias.test-site.example:8080"):
            self.assertIsNotNone(re.fullmatch(regex, authority, re.I), authority)
        for authority in ("", "unknown.example", "unknown.test-site.example",
                          "test-site.example.evil.invalid",
                          "test-site.example:9000", "other.alias.test-site.example",
                          "test-site.example:80.evil", "127.0.0.1"):
            self.assertIsNone(re.fullmatch(regex, authority, re.I), authority)
        block, _ = subject._managed(self.site, self.html, "b"*32)
        self.assertIn(b'set $achstopgate "$http_host@$document_root";', block)
        self.assertIn(b"if ($achstopgate ~*", block)
        self.assertNotIn(b"$host@", block)
        self.assertNotIn(b"ach_stop_match_", block)
        self.assertIn(b"@/www/server/st[o]p$", block)

    def test_unsafe_or_unbound_host_names_deny_arming(self):
        for bindings in (
            [{"name": "other.example", "port": 80}],
            [{"name": "*.test-site.example", "port": 80}],
            [{"name": "test-site.example", "port": True}],
            [{"name": "test-site.example", "port": 65536}],
            None,
        ):
            with self.subTest(bindings=bindings):
                self.site["bound_domains"] = bindings
                with self.assertRaises(subject.ExtensionError):
                    subject._managed(self.site, self.html, "b"*32)

    def test_apply_late_native_writer_preserves_prepared_recovery(self):
        before = self.call()
        changed = b"# NATIVE OPERATOR CHANGE AFTER RELOAD\n"
        def late_mutation(site, *, stopped):
            self.conf.write_bytes(self.conf.read_bytes() + changed)
            return self.probe(site, stopped=stopped)
        with self.assertRaises(subject.ExtensionError) as caught:
            self.call("apply", expected_vhost=before["vhost_sha256"],
                      expected_render=before["rendered_sha256"], probe=late_mutation)
        self.assertEqual(caught.exception.stage, "uncertain")
        self.assertIsNotNone(caught.exception.recovery_id)
        record = subject._record_load(self.fd, self.site)
        self.assertEqual(record["phase"], "prepared")
        self.assertEqual(record["op"], caught.exception.recovery_id)
        self.assertTrue(self.conf.read_bytes().endswith(changed))
        self.assertEqual(self.call()["state"], "Recovery Required")

    def test_restore_late_native_writer_preserves_restoring_recovery(self):
        applied = self.apply()
        previous = self.call()
        changed = b"# NATIVE OPERATOR CHANGE DURING RESTORE\n"
        def late_mutation(site, *, stopped):
            self.conf.write_bytes(self.conf.read_bytes() + changed)
            return self.probe(site, stopped=stopped)
        with self.assertRaises(subject.ExtensionError) as caught:
            self.call("restore", expected_vhost=previous["vhost_sha256"],
                      expected_recovery=applied["recovery_id"], probe=late_mutation)
        self.assertEqual(caught.exception.stage, "uncertain")
        record = subject._record_load(self.fd, self.site)
        self.assertEqual(record["phase"], "restoring")
        self.assertEqual(record["op"], applied["recovery_id"])
        self.assertTrue(self.conf.read_bytes().endswith(changed))
        self.assertNotIn(b"ACh stopped503 begin", self.conf.read_bytes())
        self.assertEqual(self.call()["state"], "Recovery Required")

    def test_response_proof_kind_is_bound_to_actual_state_and_observation(self):
        armed = self.apply()
        self.assertEqual(armed["proof_kind"], "source_only")
        self.assertEqual(self.call()["proof_kind"], "source_only")
        self.stop()
        actual = self.call()
        self.assertEqual(actual["state"], "Applied")
        self.assertEqual(actual["proof_kind"], "stopped_http503")
        self.assertTrue(actual["runtime_verified"])
        stopped = self.call("restore", expected_vhost=actual["vhost_sha256"],
                            expected_recovery=armed["recovery_id"])
        self.assertEqual(stopped["proof_kind"], "native_http200")
        self.assertEqual(self.call()["proof_kind"], "source_only")

    def test_running_probe_ignores_large_wordpress_html_body(self):
        class FakeResponse:
            status = 404
            def getheader(self, key, default=None):
                return "text/html" if key == "Content-Type" else "identity"
            def read(self, size):
                raise AssertionError("Running-site response body should not be read")
        class FakeConn:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return FakeResponse()
            def close(self): pass
        with patch.object(subject.http.client, "HTTPConnection", FakeConn):
            self.assertEqual(subject._probe(self.site, stopped=False),
                             (404, None, "text/html"))

    def test_native_stop_html_restore_checks_status_not_large_builtin_body(self):
        class FakeResponse:
            status = 200
            def getheader(self, key, default=None):
                return "text/html" if key == "Content-Type" else "identity"
            def read(self, size):
                raise AssertionError("Native stop HTML can exceed the ACh template bound")
        class FakeConn:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return FakeResponse()
            def close(self): pass
        with patch.object(subject.http.client, "HTTPConnection", FakeConn):
            self.assertEqual(subject._probe(self.site, stopped=True),
                             (200, None, "text/html"))

    def test_native_503_source_partition_en_fa_and_unsafe_brand(self):
        for locale in ("en", "fa"):
            for danger in (False, True):
                with self.subTest(locale=locale, danger=danger):
                    brand = dict(DEFAULT_BRAND)
                    if danger:
                        brand["brand_name"] = "One $5 include /www/server/stop"
                    content = render_page(locale, "stopped", brand)["html"]
                    block, served_sha = subject._managed(self.site, content, "a"*32)
                    self.assertNotIn(b"include", block)
                    self.assertNotIn(b"/www/server/stop", block)
                    self.assertNotIn(self.site["path"].encode(), block)
                    self.assertLess(len(block), subject.MAX_VHOST // 2)
                    self.assertRegex(served_sha, r"\A[0-9a-f]{64}\Z")


if __name__ == "__main__":
    unittest.main()
