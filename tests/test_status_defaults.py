"""Real file/journal transactions for aaPanel new-site template sources."""
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
import ach_customizer_status_defaults as defaults
import ach_customizer_main as backend
from ach_customizer_status_pages import render_page
from ach_customizer_state import _open_state_dir


class NewSiteSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-default-source-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base / "native"
        self.data = self.base / "panel-data"
        self.src.mkdir(mode=0o700)
        self.data.mkdir(mode=0o700)
        self.originals = {}
        for template, name in defaults.TEMPLATES.items():
            raw = ("Native aaPanel default " + template).encode()
            path = self.src / name
            path.write_bytes(raw)
            path.chmod(0o600)
            self.originals[template] = raw
        self.fd = _open_state_dir(self.data)
        self.addCleanup(os.close, self.fd)

    def call(self, action, template="404", locale="en", **extra):
        rendered = render_page(locale, template)
        return defaults.manage_default(
            action, template, rendered["html"], data_fd=self.fd,
            source_root=self.src, **extra)

    def apply(self, template="404", locale="en"):
        before = self.call("recheck", template, locale)
        self.assertIn(before["state"], ("Source Ready", "Restored"), before)
        return self.call(
            "apply", template, locale,
            expected_current=before["current_sha256"],
            expected_render=before["rendered_sha256"])

    def test_apply_recheck_restore_reapply_all_sources_both_locales(self):
        for template in defaults.TEMPLATES:
            with self.subTest(template=template):
                path = self.src / defaults.TEMPLATES[template]
                for locale in ("fa", "en"):
                    applied = self.apply(template, locale)
                    self.assertEqual(applied["state"], "Applied")
                    self.assertFalse(applied["read_only"])
                    self.assertTrue(applied["changed"])
                    self.assertEqual(path.read_bytes(),
                                     render_page(locale, template)["html"].encode())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    current = self.call("recheck", template, locale)
                    self.assertEqual(current["state"], "Applied")
                    self.assertEqual(current["recovery_id"], applied["recovery_id"])
                    restored = self.call(
                        "restore", template, locale,
                        expected_recovery=current["recovery_id"])
                    self.assertEqual(restored["state"], "Restored")
                    self.assertTrue(restored["changed"])
                    self.assertEqual(path.read_bytes(), self.originals[template])
                    self.assertEqual(self.call("recheck", template)["state"], "Restored")

    def test_rejects_stale_approval_mismatched_render_and_wrong_recovery(self):
        read = self.call("recheck")
        with self.assertRaisesRegex(defaults.DefaultSourceError, "Recheck"):
            self.call("apply", expected_current="f"*64,
                      expected_render=read["rendered_sha256"])
        with self.assertRaisesRegex(defaults.DefaultSourceError, "preview changed"):
            self.call("apply", expected_current=read["current_sha256"],
                      expected_render="0"*64)
        self.assertEqual(list(self.data.iterdir()), [])
        applied = self.apply()
        with self.assertRaisesRegex(defaults.DefaultSourceError, "Recovery identity"):
            self.call("restore", expected_recovery="0"*32)
        already = self.call("apply", expected_current=applied["current_sha256"],
                            expected_render=applied["rendered_sha256"])
        self.assertEqual(already["state"], "Already Applied")
        self.assertFalse(already["changed"])
        self.assertEqual(self.call("recheck")["state"], "Applied")

    def test_rejects_source_drift_and_preserves_nonselected_templates(self):
        applied = self.apply("502")
        other = {t:(self.src / name).read_bytes() for t,name in defaults.TEMPLATES.items()
               if t!="502"}
        path=self.src/"502.html"
        path.write_bytes(b"Independent admin revision")
        self.assertEqual(self.call("recheck","502")["state"],"Drift")
        with self.assertRaisesRegex(defaults.DefaultSourceError,"drifted"):
            self.call("restore","502",expected_recovery=applied["recovery_id"])
        self.assertEqual(path.read_bytes(),b"Independent admin revision")
        self.assertEqual({t:(self.src / defaults.TEMPLATES[t]).read_bytes()
                         for t in other},other)
        path.write_bytes(render_page("en","502")["html"].encode())
        outcome=self.call("restore","502",expected_recovery=applied["recovery_id"])
        self.assertEqual(outcome["state"],"Restored")

    def test_missing_modified_backup_or_phase_is_not_silently_adopted(self):
        applied=self.apply()
        journal=self.data/defaults._journal_name("404")
        saved=json.loads(journal.read_text())
        backup=self.data/saved["backup"]
        backup.write_bytes(b"modified original")
        with self.assertRaisesRegex(defaults.DefaultSourceError,"backup"):
            self.call("recheck")
        backup.write_bytes(self.originals["404"])
        saved["template"]="502"
        journal.write_text(json.dumps(saved))
        with self.assertRaisesRegex(defaults.DefaultSourceError,"recovery identity"):
            self.call("recheck")
        saved["template"]="404"
        journal.write_text(json.dumps(saved))
        self.assertEqual(self.call("recheck")["state"],"Applied")
        self.call("restore",expected_recovery=applied["recovery_id"])

    def test_applied_journal_commit_failure_retains_recovery(self):
        original=defaults._record_write
        def broken(fd, template, record):
            if record["phase"]=="applied":
                raise OSError(5,"simulated post-publication journal loss")
            return original(fd,template,record)
        with patch.object(defaults,"_record_write",side_effect=broken):
            with self.assertRaises(defaults.DefaultSourceError) as ctx:
                self.apply()
        self.assertEqual(ctx.exception.stage,"uncertain")
        saved=self.call("recheck")
        self.assertEqual(saved["state"],"Recovery Required")
        self.assertEqual(saved["recovery_id"],ctx.exception.recovery_id)
        self.assertEqual(self.call("restore",expected_recovery=saved["recovery_id"])["state"],
                         "Restored")
        self.assertEqual((self.src/"404.html").read_bytes(),self.originals["404"])

    def test_failed_publish_keeps_prepared_journal_and_original_source(self):
        with patch.object(defaults,"_publish",side_effect=OSError(5,"disk fault")):
            with self.assertRaises(defaults.DefaultSourceError) as ctx:self.apply()
        self.assertEqual(ctx.exception.stage,"uncertain")
        self.assertEqual((self.src/"404.html").read_bytes(),self.originals["404"])
        state=self.call("recheck")
        self.assertEqual(state["state"],"Recovery Required")
        self.assertEqual(self.call("restore",expected_recovery=state["recovery_id"])["state"],
                         "Restored")
        self.assertEqual(self.call("recheck")["state"],"Restored")

    def test_restore_resumes_preexisting_identical_staging(self):
        applied = self.apply()
        stage = self.src / (".404.html." + applied["recovery_id"] + ".stage")
        stage.write_bytes(self.originals["404"])
        stage.chmod(0o600)
        restored = self.call("restore", expected_recovery=applied["recovery_id"])
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(stage.exists())
        self.assertEqual((self.src / "404.html").read_bytes(), self.originals["404"])

    def test_already_current_does_not_create_recovery_or_mutate_source(self):
        path = self.src / "404.html"
        data = render_page("en", "404")["html"].encode()
        path.write_bytes(data)
        before = path.stat()
        observed = self.call("recheck")
        self.assertEqual(observed["state"], "Already Current")
        result = self.call("apply", expected_current=observed["current_sha256"],
                           expected_render=observed["rendered_sha256"])
        self.assertEqual(result["state"], "Already Current")
        self.assertFalse(result["changed"])
        self.assertEqual(result["recovery_id"], None)
        self.assertEqual(list(self.data.iterdir()), [])
        self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))

    def test_symlinks_unsafe_modes_and_missing_files_refused(self):
        path=self.src/"404.html"
        target=self.base/"other"
        target.write_text("external")
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(Exception):self.call("recheck")
        path.unlink()
        path.write_text("native")
        path.chmod(0o666)
        with self.assertRaises(Exception):self.call("recheck")
        path.chmod(0o600)
        path.unlink()
        with self.assertRaises(defaults.DefaultSourceError):self.call("recheck")
        self.assertEqual(list(self.data.iterdir()),[])

    def test_mode_preserved_for_readable_native_source(self):
        path=self.src/"404.html"
        path.chmod(0o644)
        applied=self.apply()
        self.assertEqual(path.stat().st_mode & 0o777,0o644)
        self.call("restore",expected_recovery=applied["recovery_id"])
        self.assertEqual(path.stat().st_mode & 0o777,0o644)


class NativeDefaultEndpointTests(unittest.TestCase):
    def setUp(self):
        NewSiteSourceTests.setUp(self)
        self.backend=backend.ach_customizer_main()
        self.public=types.ModuleType("public")
        self.public.get_webserver=lambda:"nginx"
        self.public.get_panel_version=lambda:"8.0.7"
        self.flask=types.ModuleType("flask")
        self.flask.session={"uid":1,"login":True}
        self.flask.has_request_context=lambda:True
        self.flask.request=types.SimpleNamespace(method="POST")
        ps=[patch.object(backend,"_STATE_DIR",str(self.data)),
            patch.object(defaults,"SOURCE_ROOT",str(self.src)),
            patch.dict(sys.modules,{"flask":self.flask,"public":self.public})]
        for p in ps:p.start();self.addCleanup(p.stop)

    def endpoint(self, action="recheck", template="404", **fields):
        args={"default_action":action,"scope":"global","site_id":"",
              "template":template,"locale":"en","expected_revision":"0",
              "default_approval":action+"_new_site_default_"+template}
        args.update(fields)
        return self.backend.status_defaults(args)

    def test_endpoint_real_apply_restore_activity_and_scope(self):
        first=self.endpoint()
        self.assertTrue(first["status"],first)
        self.assertEqual(first["state"],"Source Ready")
        assert first["scope"]=="global" and first["site_id"] is None
        applied=self.endpoint("apply",expected_current_sha256=first["current_sha256"],
                              expected_render_sha256=first["rendered_sha256"])
        self.assertTrue(applied["status"],applied)
        self.assertEqual(applied["state"],"Applied")
        rechecked=self.endpoint()
        self.assertTrue(rechecked["status"],rechecked)
        self.assertEqual(rechecked["state"],"Applied")
        restored=self.endpoint("restore",expected_recovery_id=rechecked["recovery_id"])
        self.assertTrue(restored["status"],restored)
        self.assertEqual(restored["state"],"Restored")
        self.assertEqual((self.src/"404.html").read_bytes(),self.originals["404"])
        from ach_customizer_activity import read_activity
        entries=read_activity(str(self.data))
        self.assertTrue(any(x["action"]=="status_default_apply" for x in entries))

    def test_endpoint_denies_unapproved_nonprimary_temporary_and_scope(self):
        before={name:(self.src/name).read_bytes() for name in defaults.TEMPLATES.values()}
        base=self.endpoint()
        for change in (
            {"scope":"site","site_id":"4"},
            {"default_approval":""},
            {"template":"403"},
            {"expected_revision":"9"},
        ):
            with self.subTest(change=change):
                response=self.endpoint("apply",
                    expected_current_sha256=base["current_sha256"],
                    expected_render_sha256=base["rendered_sha256"],**change)
                self.assertFalse(response["status"],response)
        for session in ({"uid":2,"login":True},{"uid":1,"login":True,"tmp_login_id":"qa"},
                        {"uid":1,"login":False}):
            self.flask.session=session
            response=self.endpoint("apply",expected_current_sha256=base["current_sha256"],
                                  expected_render_sha256=base["rendered_sha256"])
            self.assertFalse(response["status"],response)
            self.assertIn("authorization",response["stage"])
        self.flask.session={"uid":1,"login":True}
        self.flask.request.method="GET"
        self.assertFalse(self.endpoint()["status"])
        self.assertEqual({name:(self.src/name).read_bytes()
                         for name in defaults.TEMPLATES.values()},before)

if __name__=="__main__":
    unittest.main()
