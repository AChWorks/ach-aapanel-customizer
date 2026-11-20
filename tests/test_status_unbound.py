"""Global HTTP/80 unbound route: bounded file ownership, live proof and recovery."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(ROOT))

import ach_customizer_status_unbound as subject
import ach_customizer_status_extension as publisher
import ach_customizer_main as backend
from ach_customizer_status_pages import render_page
from ach_customizer_state import _open_state_dir


class FakeNginx:
    def __init__(self, test):
        self.test = test
        self.running = False
        self.reloads = 0
        self.fail_test_when_present = False
        self.fail_reload = False
        self.fallback_v4 = 200
        self.fallback_v6 = 200

    def __call__(self, argv, **kwargs):
        if "-T" in argv:
            # Real nginx -T runs its syntax check first: malformed .conf in
            # the included glob makes both -T and -t fail before activation.
            if self.fail_test_when_present and self.test.config.exists():
                return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"native nginx syntax failure")
            prefix = f"# configuration file {self.test.nginx_conf}:\n"
            prefix += self.test.nginx_conf.read_text() + "\n"
            files = sorted(self.test.vhost.glob("*.conf"))
            for file in files:
                prefix += f"# configuration file {file}:\n" + file.read_text() + "\n"
            return types.SimpleNamespace(returncode=0, stdout=prefix.encode(), stderr=b"")
        if "-t" in argv:
            broken = self.fail_test_when_present and self.test.config.exists()
            return types.SimpleNamespace(returncode=1 if broken else 0)
        if "-s" in argv and "reload" in argv:
            if self.fail_reload:
                return types.SimpleNamespace(returncode=1)
            self.running = self.test.config.exists()
            self.reloads += 1
            return types.SimpleNamespace(returncode=0)
        raise AssertionError("Unexpected Nginx command: " + repr(argv))

    def probe(self, ipv6=False):
        if not self.running:
            return (self.fallback_v6 if ipv6 else self.fallback_v4, subject._sha(b"original-6" if ipv6 else b"original-4"), None)
        content = self.test.html.read_bytes()
        conf = self.test.config.read_bytes()
        proof = conf.split(b"X-ACh-Status-Proof ", 1)[1].split(b" ", 1)[0].strip()
        # nginx add_header ... always; returns original HTTP 404 semantics.
        return (404, subject._sha(content), proof.decode())


class UnboundRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-http-unbound-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vhost = self.base / "native"
        self.www = self.base / "html"
        self.data = self.base / "panel-data"
        self.native = self.base / "nginx"
        for p in (self.vhost, self.www, self.data, self.native):
            p.mkdir(mode=0o700)
        self.nginx_conf = self.native / "nginx.conf"
        self.nginx_conf.write_text("http {\n include " + str(self.vhost) + "/*.conf;\n}\n")
        self.nginx_conf.chmod(0o600)
        self.base_default = self.vhost / "0.default.conf"
        self.base_default.write_text("server { listen 80; listen [::]:80; server_name _; }\n")
        self.base_default.chmod(0o600)
        self.config = self.vhost / subject.CONF_NAME
        self.html = self.www / subject.HTML_NAME
        self.fd = _open_state_dir(self.data)
        self.addCleanup(os.close, self.fd)
        self.runner = FakeNginx(self)

    def call(self, action, locale="en", **extra):
        html = render_page(locale, "unbound")["html"]
        return subject.manage_unbound(
            action, html, data_fd=self.fd, vhost_root=str(self.vhost),
            html_root=str(self.www), nginx=str(self.base / "fake-nginx"),
            nginx_conf=str(self.nginx_conf), runner=self.runner,
            probe=self.runner.probe, **extra,
        )

    def read(self, locale="en"):
        return self.call("recheck", locale)

    def apply(self, locale="en"):
        a=self.read(locale)
        self.assertIn(a["state"], ("Source Ready","Restored"))
        return self.call(
            "apply", locale, expected_source=a["source_sha256"],
            expected_render=a["rendered_sha256"],
            expected_v4=a["before_ipv4_status"],
            expected_v6=a["before_ipv6_status"],
        )

    def restore(self, applied, locale="en"):
        a=self.read(locale)
        return self.call("restore", locale,
                         expected_source=a["source_sha256"],
                         expected_recovery=applied["recovery_id"])

    def test_apply_recheck_restore_both_locales_without_touching_native_default(self):
        original = self.base_default.read_bytes()
        for locale in ("en", "fa"):
            with self.subTest(locale=locale):
                before = self.read(locale)
                self.assertEqual(before["state"],"Source Ready" if locale=="en" else "Restored")
                self.assertFalse(before["runtime_verified"])
                self.assertEqual(self.runner.reloads, 0 if locale=="en" else 2)
                applied = self.apply(locale)
                self.assertEqual(applied["state"],"Applied")
                self.assertEqual(applied["runtime_verified"],True)
                self.assertEqual(self.runner.probe(False)[0],404)
                self.assertEqual(self.runner.probe(True)[0],404)
                self.assertEqual(self.config.stat().st_mode & 0o777,0o600)
                self.assertEqual(self.html.stat().st_mode & 0o777,0o644)
                self.assertEqual(self.read(locale)["state"],"Applied")
                result = self.restore(applied, locale)
                self.assertEqual(result["state"],"Restored")
                self.assertTrue(result["runtime_verified"])
                self.assertFalse(self.config.exists())
                self.assertFalse(self.html.exists())
                self.assertEqual(self.runner.probe(False)[0],200)
                self.assertEqual(self.runner.probe(True)[0],200)
                self.assertEqual(self.base_default.read_bytes(),original)
        self.assertEqual(self.runner.reloads,4)

    def test_ipv4_only_native_listener_does_not_require_or_create_ipv6(self):
        self.base_default.write_text("server { listen 80; server_name only4.invalid; }\n")
        original=self.base_default.read_bytes()
        checked=[]
        def only_ipv4(ipv6=False):
            checked.append(ipv6)
            if ipv6:
                raise AssertionError("IPv6 is not configured and must not be probed")
            return FakeNginx.probe(self.runner, False)
        with patch.object(self.runner, "probe", side_effect=only_ipv4):
            before=self.read()
            self.assertEqual((before["before_ipv4_status"], before["before_ipv6_status"]), (200,None))
            applied=self.apply()
            self.assertEqual(applied["state"],"Applied")
            self.assertIn(b"listen 80 default_server;",self.config.read_bytes())
            self.assertNotIn(b"[::]:80",self.config.read_bytes())
            self.assertEqual(self.read()["state"],"Applied")
            self.assertEqual(self.restore(applied)["state"],"Restored")
            self.assertIsNone(self.read()["before_ipv6_status"])
        self.assertTrue(checked)
        self.assertFalse(any(checked))
        self.assertEqual(self.base_default.read_bytes(),original)

    def test_ipv6_only_native_listener_does_not_require_or_create_ipv4(self):
        self.base_default.write_text("server { listen [::]:80; server_name only6.invalid; }\n")
        original=self.base_default.read_bytes()
        checked=[]
        def only_ipv6(ipv6=False):
            checked.append(ipv6)
            if not ipv6:
                raise AssertionError("IPv4 is not configured and must not be probed")
            return FakeNginx.probe(self.runner, True)
        with patch.object(self.runner, "probe", side_effect=only_ipv6):
            before=self.read()
            self.assertEqual((before["before_ipv4_status"], before["before_ipv6_status"]), (None,200))
            applied=self.apply()
            self.assertNotIn(b"listen 80 default_server;",self.config.read_bytes())
            self.assertIn(b"listen [::]:80 default_server;",self.config.read_bytes())
            self.assertEqual(self.read()["state"],"Applied")
            self.assertEqual(self.restore(applied)["state"],"Restored")
        self.assertTrue(checked)
        self.assertTrue(all(checked))
        self.assertEqual(self.base_default.read_bytes(),original)

    def test_absent_http_listener_is_incompatible_not_a_synthetic_success(self):
        self.base_default.write_text("server { listen 888; server_name unrelated.invalid; }\n")
        with self.assertRaises(subject.UnboundError) as error:
            self.read()
        self.assertEqual(error.exception.stage,"compatibility")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())
        self.assertEqual(list(self.data.iterdir()),[])

    def test_new_native_ipv6_listener_revokes_positive_applied_proof(self):
        self.base_default.write_text("server { listen 80; server_name only4.invalid; }\n")
        applied=self.apply()
        self.base_default.write_text("server { listen 80; listen [::]:80; server_name dual.invalid; }\n")
        current=self.read()
        self.assertEqual(current["state"],"Needs Review")
        self.assertFalse(current["runtime_verified"])
        self.assertEqual(self.restore(applied)["state"],"Restored")

    def test_address_specific_listener_never_expands_to_wildcard(self):
        for native in ("127.0.0.1:80", "192.0.2.5:80", "[::1]:80", "[2001:db8::5]:80"):
            with self.subTest(native=native):
                self.base_default.write_text("server { listen " + native + "; server_name limited.invalid; }\n")
                with self.assertRaises(subject.UnboundError) as error:
                    self.read()
                self.assertEqual(error.exception.stage,"compatibility")
                self.assertEqual(list(self.data.iterdir()),[])
                self.assertFalse(self.config.exists())

    def test_ipv6_dual_mode_socket_is_not_rebound_as_independent_listeners(self):
        self.base_default.write_text("server { listen [::]:80 ipv6only=off; server_name dual.invalid; }\n")
        with self.assertRaises(subject.UnboundError) as error:
            self.read()
        self.assertEqual(error.exception.stage,"compatibility")
        self.assertEqual(list(self.data.iterdir()),[])

    def _assert_restore_after_removed_family(self, original, updated, removed_ipv6):
        self.base_default.write_text(original)
        applied=self.apply()
        self.assertEqual(self.read()["state"], "Applied")
        self.base_default.write_text(updated)
        probes=[]
        def relocated_probe(ipv6=False):
            probes.append((ipv6, self.runner.running))
            if not self.runner.running and ipv6 == removed_ipv6:
                raise subject.UnboundProbeRefused("probe", "Confirmed loopback TCP refusal")
            return FakeNginx.probe(self.runner, ipv6)
        with patch.object(self.runner, "probe", side_effect=relocated_probe):
            changed=self.read()
            self.assertEqual(changed["state"], "Needs Review")
            self.assertFalse(changed["runtime_verified"])
            restored=self.restore(applied)
            self.assertEqual(restored["state"], "Restored")
            self.assertTrue(restored["runtime_verified"])
            self.assertEqual(self.read()["state"], "Restored")
        self.assertIn((removed_ipv6, False), probes)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())

    def test_dual_stack_to_ipv4_only_restore_confirms_removed_ipv6_refusal(self):
        self._assert_restore_after_removed_family(
            "server { listen 80; listen [::]:80; server_name old.invalid; }\n",
            "server { listen 80; server_name new.invalid; }\n", True)

    def test_ipv4_only_to_ipv6_only_restore_confirms_removed_ipv4_refusal(self):
        self._assert_restore_after_removed_family(
            "server { listen 80; server_name old.invalid; }\n",
            "server { listen [::]:80; server_name new.invalid; }\n", False)

    def test_old_listener_still_serving_managed_proof_cannot_claim_restored(self):
        applied=self.apply()
        self.base_default.write_text("server { listen 80; server_name only4.invalid; }\n")
        clock=[0.0]
        def old_worker(ipv6=False):
            if ipv6 and not self.runner.running:
                clock[0]=20.0
                return (404, applied["rendered_sha256"], applied["recovery_id"])
            return FakeNginx.probe(self.runner, ipv6)
        with patch.object(self.runner, "probe", side_effect=old_worker), \
             patch.object(subject.time, "monotonic", side_effect=lambda:clock[0]), \
             patch.object(subject.time, "sleep", return_value=None):
            self.assertEqual(self.read()["state"], "Needs Review")
            with self.assertRaises(subject.UnboundError) as error:
                self.restore(applied)
            self.assertEqual(error.exception.stage, "uncertain")
            self.assertEqual(error.exception.recovery_id, applied["recovery_id"])
        record=subject._record_read(self.fd)
        self.assertEqual(record["phase"],"restoring")
        self.assertTrue(self.html.exists(), "Retained recovery until old managed proof disappears")

    def test_timeout_for_removed_listener_is_not_a_confirmed_refusal(self):
        applied=self.apply()
        self.base_default.write_text("server { listen 80; server_name only4.invalid; }\n")
        def timed_out(ipv6=False):
            if ipv6 and not self.runner.running:
                raise subject.UnboundError("probe", "Simulated timeout (not ECONNREFUSED)")
            return FakeNginx.probe(self.runner, ipv6)
        with patch.object(self.runner, "probe", side_effect=timed_out):
            self.assertEqual(self.read()["state"], "Needs Review")
            with self.assertRaises(subject.UnboundError) as error:
                self.restore(applied)
            self.assertEqual(error.exception.stage,"uncertain")
        self.assertEqual(subject._record_read(self.fd)["phase"], "restoring")
        self.assertTrue(self.html.exists())

    def test_refused_current_listener_remains_unverified(self):
        applied=self.apply()
        def refused(ipv6=False):
            if ipv6 and not self.runner.running:
                raise subject.UnboundProbeRefused("probe", "TCP refused but native listener remains configured")
            return FakeNginx.probe(self.runner, ipv6)
        with patch.object(self.runner, "probe", side_effect=refused):
            with self.assertRaises(subject.UnboundError) as error:
                self.restore(applied)
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(subject._record_read(self.fd)["phase"], "restoring")

    def test_tcp_refusal_vs_timeout_have_different_probe_types(self):
        class BrokenConnection:
            def __init__(self, exc):
                self.exc=exc
            def request(self, *args, **kwargs):
                raise self.exc
            def close(self):
                pass
        for exc, expected in (
            (ConnectionRefusedError(111, "refused"), subject.UnboundProbeRefused),
            (TimeoutError("timed out"), subject.UnboundError),
        ):
            with self.subTest(exc=type(exc).__name__):
                with patch.object(subject.http.client, "HTTPConnection", return_value=BrokenConnection(exc)):
                    with self.assertRaises(expected) as error:
                        subject._probe(ipv6=True)
                    self.assertEqual(error.exception.stage, "probe")
                    self.assertIsInstance(error.exception, subject.UnboundProbeRefused if isinstance(exc, ConnectionRefusedError) else subject.UnboundError)
                    if isinstance(exc, TimeoutError):
                        self.assertNotIsInstance(error.exception, subject.UnboundProbeRefused)

    def test_read_only_recheck_creates_no_journal_or_static_files(self):
        result=self.read()
        self.assertEqual(result["state"],"Source Ready")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())
        self.assertEqual(list(self.data.iterdir()),[])

    def test_stale_approval_and_native_config_changes_refused_before_write(self):
        original=self.read()
        with self.assertRaises(subject.UnboundError):
            self.call("apply",expected_source="f"*64,
                      expected_render=original["rendered_sha256"],
                      expected_v4=200,expected_v6=200)
        self.base_default.write_text("server { listen 80; server_name changed.example; }\n")
        with self.assertRaises(subject.UnboundError):
            self.call("apply",expected_source=original["source_sha256"],
                      expected_render=original["rendered_sha256"],
                      expected_v4=200,expected_v6=200)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())

    def test_foreign_conflict_and_asset_not_overwritten(self):
        self.config.write_text("foreign config")
        self.config.chmod(0o600)
        self.assertEqual(self.read()["state"],"Conflict")
        self.assertEqual(self.config.read_text(),"foreign config")
        self.config.unlink()
        self.html.write_text("foreign HTML")
        self.html.chmod(0o644)
        self.assertEqual(self.read()["state"],"Conflict")
        self.assertEqual(self.html.read_text(),"foreign HTML")

    def test_symlink_or_foreign_mode_refused(self):
        target = self.base / "foreign"
        target.write_text("untouchable")
        self.html.symlink_to(target)
        with self.assertRaises(Exception):self.read()
        self.assertEqual(target.read_text(),"untouchable")
        self.html.unlink()
        self.html.write_text("public")
        self.html.chmod(0o666)
        with self.assertRaises(Exception):self.read()

    def test_applied_manual_asset_drift_blocks_restore(self):
        applied=self.apply()
        self.html.write_text("manual change")
        before=self.html.read_bytes()
        with self.assertRaises(subject.UnboundError):
            self.call("restore",expected_source=applied["source_sha256"],
                      expected_recovery=applied["recovery_id"])
        self.assertEqual(self.html.read_bytes(),before)
        self.assertTrue(self.config.exists())

    def test_interrupted_staging_never_publishes_incomplete_final_paths(self):
        # Exercise actual staged writes *after* stage inode creation and
        # rejected renames, for both the HTML asset and active Nginx config.
        original_site = self.base_default.read_bytes()
        for mode in ("partial_write", "pre_rename"):
            for final_name in (subject.HTML_NAME, subject.CONF_NAME):
                with self.subTest(mode=mode, final=final_name):
                    initial = self.read()
                    original_writer = publisher._write_exclusive
                    original_rename = publisher._rename_noreplace

                    def interrupted_writer(fd, name, payload, permissions):
                        if mode == "partial_write" and name.startswith("." + final_name + ".") and name.endswith(".stage"):
                            staged_fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                                permissions, dir_fd=fd)
                            try:
                                os.write(staged_fd, payload[:7])
                            finally:
                                os.close(staged_fd)
                            raise OSError(5, "simulated post-creation write failure")
                        return original_writer(fd, name, payload, permissions)

                    def interrupted_rename(fd, before, after):
                        if mode == "pre_rename" and after == final_name and before.endswith(".stage"):
                            raise OSError(5, "simulated pre-publication rename failure")
                        return original_rename(fd, before, after)

                    with patch.object(publisher, "_write_exclusive", side_effect=interrupted_writer), \
                         patch.object(publisher, "_rename_noreplace", side_effect=interrupted_rename):
                        with self.assertRaises(subject.UnboundError) as err:
                            self.call("apply", expected_source=initial["source_sha256"],
                                      expected_render=initial["rendered_sha256"],
                                      expected_v4=200, expected_v6=200)
                    self.assertEqual(err.exception.stage, "uncertain")
                    self.assertFalse(self.config.exists(), "No incomplete config in Nginx include glob")
                    self.assertEqual(len(list(self.vhost.glob("*.conf"))), 1)
                    self.assertEqual(self.base_default.read_bytes(), original_site)
                    if self.html.exists():
                        self.assertEqual(subject._sha(self.html.read_bytes()),
                                         initial["rendered_sha256"],
                                         "Published HTML is complete and hash-matched")
                    stage_root = self.vhost if final_name == subject.CONF_NAME else self.www
                    staged = stage_root / ("." + final_name + "." + err.exception.recovery_id + ".stage")
                    self.assertTrue(staged.is_file(), "Interrupted content remains only in an inactive stage")
                    self.assertEqual(self.runner([str(self.base / "fake-nginx"), "-t"]).returncode, 0)
                    state = self.read()
                    self.assertEqual(state["state"], "Recovery Required")
                    self.assertEqual(state["recovery_id"], err.exception.recovery_id)
                    restored = self.call("restore", expected_source=state["source_sha256"],
                                         expected_recovery=state["recovery_id"])
                    self.assertEqual(restored["state"], "Restored")
                    self.assertEqual(self.read()["state"], "Restored")
                    self.assertFalse(self.config.exists())
                    self.assertFalse(self.html.exists())
                    self.assertEqual(self.base_default.read_bytes(), original_site)

    def test_syntax_failure_after_publish_recovery_does_not_need_valid_preflight(self):
        initial=self.read()
        self.runner.fail_test_when_present=True
        with self.assertRaises(subject.UnboundError) as err:
            self.call("apply",expected_source=initial["source_sha256"],
                      expected_render=initial["rendered_sha256"],
                      expected_v4=200,expected_v6=200)
        self.assertEqual(err.exception.stage,"uncertain")
        state=self.read()
        self.assertEqual(state["state"],"Recovery Required")
        self.assertFalse(self.config.exists(), "Syntax-rejected config must not remain in the live Nginx glob")
        self.assertTrue((self.vhost/subject._retired(state["recovery_id"])).exists())
        restored=self.call("restore",expected_source=state["source_sha256"],
                           expected_recovery=state["recovery_id"])
        self.assertEqual(restored["state"],"Restored")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())

    def test_recovery_wrong_identity_denied_and_original_files_preserved(self):
        applied=self.apply()
        with self.assertRaises(subject.UnboundError):
            self.call("restore",expected_source=applied["source_sha256"],
                      expected_recovery="0"*32)
        self.assertTrue(self.config.exists())
        self.assertEqual(self.read()["state"],"Applied")


    def test_other_site_created_after_apply_does_not_block_recheck_or_restore(self):
        applied=self.apply()
        other=self.vhost/"another-new-site.conf"
        other.write_text("server { listen 80; server_name another-new-site.invalid; }\n")
        other.chmod(0o600)
        state=self.read()
        self.assertEqual(state["state"],"Applied")
        self.assertNotEqual(state["source_sha256"],applied["source_sha256"])
        saved=other.read_bytes()
        restored=self.restore(applied)
        self.assertEqual(restored["state"],"Restored")
        self.assertEqual(other.read_bytes(),saved)

    def test_restore_does_not_assume_unrelated_fallback_status_is_frozen(self):
        applied=self.apply()
        self.runner.fallback_v4=302
        self.runner.fallback_v6=503
        restored=self.restore(applied)
        self.assertEqual(restored["state"],"Restored")
        self.assertEqual(self.read()["before_ipv4_status"],302)
        self.assertEqual(self.read()["before_ipv6_status"],503)

    def test_foreign_http_defaultserver_conflict_fails_before_managed_write(self):
        foreign=self.vhost/"external-default.conf"
        foreign.write_text("server { \n listen 80 default_server;\n server_name external.invalid;\n}\n")
        foreign.chmod(0o600)
        with self.assertRaises(subject.UnboundError) as error:
            self.read()
        self.assertEqual(error.exception.stage,"conflict")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())

    def test_valid_http_default_syntax_variants_conflict_before_mutation(self):
        foreign = self.vhost / "foreign.conf"
        variants = (
            "server {\n listen 80 default_server;\n server_name collision.invalid;\n}\n",
            "server { listen 80 default_server; server_name collision.invalid; }\n",
            "server {\n listen\t80 default_server;\n}\n",
            "server {\n listen\n 80 default_server;\n}\n",
            "server { listen 0.0.0.0:80 default_server; }\n",
            "server { listen [::]:80 default_server; }\n",
            "server { listen 443; listen 80 default_server; }\n",
            "server { listen 443; listen [::]:80 default_server; }\n",
        )
        for content in variants:
            with self.subTest(content=content):
                foreign.write_text(content)
                foreign.chmod(0o600)
                with self.assertRaises(subject.UnboundError) as err:
                    self.read()
                self.assertEqual(err.exception.stage, "conflict")
                with self.assertRaises(subject.UnboundError) as err:
                    self.call("apply", expected_source="0" * 64,
                              expected_render="0" * 64, expected_v4=200, expected_v6=200)
                self.assertEqual(err.exception.stage, "conflict")
                self.assertEqual(list(self.data.iterdir()), [])
                self.assertFalse(self.config.exists())
                self.assertFalse(self.html.exists())
        foreign.unlink()

    def test_unrelated_address_components_and_https_defaults_not_http_conflicts(self):
        foreign = self.vhost / "foreign-https.conf"
        for content in (
            "server { listen 192.168.80.1:443 default_server; }\n",
            "server { listen [2001:db8:80::1]:443 default_server; }\n",
            "server { listen 0.0.0.0:8080 default_server; }\n",
            "# listen 80 default_server;\nserver { listen 443 default_server; }\n",
        ):
            with self.subTest(content=content):
                foreign.write_text(content)
                foreign.chmod(0o600)
                self.assertEqual(self.read()["state"], "Source Ready")
                self.assertEqual(list(self.data.iterdir()), [])
        foreign.unlink()

    def test_updated_config_template_does_not_block_existing_restore(self):
        applied=self.apply()
        old_generator=subject._config
        with patch.object(subject, "_config",
                          side_effect=lambda op, root, before: old_generator(op, root, before)+b"# revised generator\\n"):
            # Only the installed generator changed; the managed Nginx
            # bytes and their persistent approved SHA are still intact.
            state=self.read()
            self.assertEqual(state["state"],"Applied")
            restored=self.call("restore",expected_source=state["source_sha256"],
                               expected_recovery=state["recovery_id"])
            self.assertEqual(restored["state"],"Restored")
            self.assertEqual(self.read()["state"],"Restored")
            self.assertFalse(self.config.exists())
            self.assertFalse(self.html.exists())
            new=self.apply()
            self.assertEqual(new["state"],"Applied")
            self.restore(new)

    def test_failed_reload_preserves_recoverable_identity_for_explicit_restore(self):
        before=self.read()
        self.runner.fail_reload=True
        with self.assertRaises(subject.UnboundError) as err:
            self.call("apply",expected_source=before["source_sha256"],
                      expected_render=before["rendered_sha256"],
                      expected_v4=200,expected_v6=200)
        self.assertEqual(err.exception.stage,"uncertain")
        self.assertTrue(self.config.exists())
        current=self.read()
        self.assertEqual(current["state"],"Recovery Required")
        self.runner.fail_reload=False
        restored=self.call("restore",expected_source=current["source_sha256"],
                           expected_recovery=current["recovery_id"])
        self.assertEqual(restored["state"],"Restored")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())

class NativeUnboundEndpointTests(unittest.TestCase):
    def setUp(self):
        UnboundRouteTests.setUp(self)
        self.plugin=backend.ach_customizer_main()
        self.flask=types.ModuleType("flask")
        self.flask.session={"uid":1,"login":True}
        self.flask.has_request_context=lambda:True
        self.flask.request=types.SimpleNamespace(method="POST")
        self.public=types.ModuleType("public")
        self.public.get_webserver=lambda:"nginx"
        self.public.get_panel_version=lambda:"8.0.7"
        self.patchers=[
            patch.object(backend,"_STATE_DIR",str(self.data)),
            patch.dict(sys.modules,{"flask":self.flask,"public":self.public}),
            patch.object(subject,"manage_unbound",return_value={
                "schema":1,"mode":"native_http_unbound","state":"Source Ready",
                "source_sha256":"a"*64,"rendered_sha256":"b"*64,
                "recovery_id":None,"before_ipv4_status":200,"before_ipv6_status":200,
                "changed":False,"read_only":True,"runtime_verified":False,
                "impact":"Unknown HTTP Host on native HTTP/80 listeners only; no HTTPS or stopped-site change",
            }),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def endpoint(self,action="recheck",**overrides):
        payload={
            "scope":"global","site_id":"","template":"unbound","locale":"en",
            "unbound_action":action,"expected_revision":"0",
            "unbound_approval":action+"_global_http_unbound_reload",
        }
        payload.update(overrides)
        return self.plugin.status_unbound(payload)

    def test_primary_post_and_scope_authorization_unchanged(self):
        self.assertTrue(self.endpoint()["status"])
        for fields in ({"site_id":"4"},{"scope":"site"},{"template":"stopped"},
                       {"unbound_approval":""}):
            self.assertFalse(self.endpoint("apply",**fields)["status"])
        for session in ({"uid":2,"login":True},{"uid":1,"login":True,"tmp_login_id":"T"},
                        {"uid":1,"login":False}):
            self.flask.session=session
            result=self.endpoint("apply")
            self.assertFalse(result["status"])
            self.assertIn("authorization",result["stage"])
        self.flask.session={"uid":1,"login":True}
        self.flask.request.method="GET"
        self.assertFalse(self.endpoint()["status"])
