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
            # Emulate Nginx's actual -T file-section structure and glob order.
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
        self.base_default.write_text("server { listen 80; server_name _; }\n")
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

    def test_partial_apply_prepared_with_no_files_is_restorable(self):
        initial = self.read()
        original_writer = subject._write_exclusive
        def broken(directory,name,payload,mode):
            if name==subject.HTML_NAME:raise OSError(5,"controlled early write failure")
            return original_writer(directory,name,payload,mode)
        with patch.object(subject,"_write_exclusive",side_effect=broken):
            with self.assertRaises(subject.UnboundError) as err:
                self.call("apply",expected_source=initial["source_sha256"],
                          expected_render=initial["rendered_sha256"],
                          expected_v4=200,expected_v6=200)
        self.assertEqual(err.exception.stage,"uncertain")
        state=self.read()
        self.assertEqual(state["state"],"Recovery Required")
        self.assertIsNotNone(state["recovery_id"])
        returned=self.call("restore",expected_source=state["source_sha256"],
                           expected_recovery=state["recovery_id"])
        self.assertEqual(returned["state"],"Restored")
        self.assertFalse(self.config.exists())
        self.assertFalse(self.html.exists())

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
                "impact":"Unknown HTTP Host on port 80 (IPv4/IPv6) only; no HTTPS or stopped-site change",
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
