"""Native WordPress per-site manual debug and external Cron policy with Recovery."""
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

import ach_customizer_wp_settings as settings
REAL_SITE_SOURCE = settings._site_source
from ach_customizer_cache_wordpress import _read_file
from ach_customizer_state import _open_state_dir


class WPSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-wp-settings-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "site"
        self.root.mkdir()
        self.config = self.root / "wp-config.php"
        self.baseline = (
            b"<?php\n"
            b"define( 'WP_DEBUG', false );\n"
            b"define('DB_NAME','example');\n"
            b"require_once ABSPATH . 'wp-settings.php';\n"
        )
        self.config.write_bytes(self.baseline)
        self.config.chmod(0o640)
        self.vhost = self.base / "vhost"
        self.vhost.mkdir()
        self.cron = self.base / "cron.d"
        self.cron.mkdir(mode=0o700)
        self.data = self.base / "data"
        self.data.mkdir(mode=0o700)
        self.site = {"id": 9, "name": "example.test",
                     "path": str(self.root), "status": 1,
                     "bound_domains": [{"name": "example.test", "port": 80}]}
        self.public = object()
        self.fd = _open_state_dir(self.data)
        self.addCleanup(os.close, self.fd)
        self.patch = patch.object(settings, "_site_source", side_effect=self.source)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def source(self, site, public, *, vhost_root):
        self.assertIs(site, self.site)
        self.assertIs(public, self.public)
        current, _ = _read_file(str(self.root), "wp-config.php")
        return current, "/usr/bin/php", "85"

    def runner(self, command, **kw):
        if command[:2] == ["/usr/bin/php", "-l"]:
            assert b"<?php" in kw["input"]
            return types.SimpleNamespace(returncode=0)
        if command[:2] == ["systemctl", "is-active"]:
            return types.SimpleNamespace(returncode=0)
        raise AssertionError("unrecognized subprocess: " + repr(command))

    def call(self, action, kind, *, desired=None, interval=None, **kwargs):
        return settings.manage(action, kind, self.site, self.public,
            desired=desired, interval=interval,
            data_fd=self.fd, cron_dir=str(self.cron), vhost_root=str(self.vhost),
            runner=self.runner, **kwargs)

    def recheck(self, kind, value="true", interval=None):
        return self.call("recheck", kind, desired=value, interval=interval)

    def apply(self, kind, value="true", interval=None):
        info = self.recheck(kind, value, interval)
        self.assertEqual(info["state"], "Source Ready")
        return self.call("apply", kind, desired=value, interval=interval,
                         expected_source=info["source_sha256"])

    def restore(self, kind, value="true", interval=None):
        info = self.recheck(kind, value, interval)
        return self.call("restore", kind, desired=value, interval=interval,
                         expected_source=info["source_sha256"],
                         expected_recovery=info["recovery_id"])

    def test_native_assignment_supports_both_handlers_and_rejects_ambiguity(self):
        # Exercise the actual shared source reader, not the operation mock.
        for filename in ("wp-settings.php", "wp-cron.php"):
            (self.root / filename).write_text("<?php /* synthetic core */")
        vhost = self.vhost / "example.test.conf"
        with patch.object(settings, "_docroot", side_effect=lambda *a: os.open(self.root, os.O_RDONLY)), \
             patch.object(settings.os.path, "isfile", return_value=True), \
             patch.object(settings.os.path, "islink", return_value=False), \
             patch.object(settings.os, "access", return_value=True):
            for handler in ("enable-php-85.conf", "enable-php-85-wpfastcgi.conf", "enable-php-83.conf"):
                vhost.write_text("server {\n # include enable-php-81.conf;\n include " + handler + ";\n}\n")
                _, php, version = REAL_SITE_SOURCE(
                    self.site, self.public, vhost_root=str(self.vhost))
                self.assertEqual(php, "/www/server/php/" + version + "/bin/php")
                self.assertEqual(version, handler.split("-")[2].split(".")[0])
            for text in ("server { location /app { include enable-php-85.conf; } }",
                         "server { include enable-php-85.conf; include enable-php-81.conf; }",
                         "server { include enable-php-85-other.conf; }"):
                vhost.write_text(text)
                with self.assertRaisesRegex(settings.WPSettingsError, "assignment"):
                    REAL_SITE_SOURCE(self.site, self.public, vhost_root=str(self.vhost))

    def test_debug_apply_recheck_restore_exact_source_permissions(self):
        a = self.apply("debug")
        self.assertEqual(a["state"], "Applied")
        self.assertFalse(a["runtime_verified"])
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o640)
        self.assertIn(b"WP_DEBUG', true", self.config.read_bytes())
        self.assertIn(a["recovery_id"].encode(), self.config.read_bytes())
        self.assertEqual(self.recheck("debug")["state"], "Applied")
        restored = self.restore("debug")
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.baseline)
        self.assertEqual(self.recheck("debug")["state"], "Restored")

    def test_debug_absent_define_inserted_before_bootstrap_and_fully_removed(self):
        raw = self.baseline.replace(b"define( 'WP_DEBUG', false );\n", b"")
        self.config.write_bytes(raw)
        self.apply("debug", "false")
        changed = self.config.read_bytes()
        self.assertIn(b"WP_DEBUG', false", changed)
        self.assertLess(changed.index(b"WP_DEBUG"), changed.index(b"wp-settings.php"))
        self.restore("debug", "false")
        self.assertEqual(self.config.read_bytes(), raw)

    def test_debug_and_cron_independently_restore_one_line_without_clobbering_peer(self):
        self.apply("debug")
        self.apply("cron", interval=5)
        self.assertIn(b"DISABLE_WP_CRON', true", self.config.read_bytes())
        self.assertIn(b"WP_DEBUG', true", self.config.read_bytes())
        job = self.cron / settings._task(9)
        self.assertIn(b"*/5 * * * * www", job.read_bytes())
        self.assertEqual(job.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.recheck("cron", interval=5)["state"], "Applied")
        self.assertEqual(self.recheck("debug")["state"], "Applied")
        self.restore("debug")
        self.assertIn(b"DISABLE_WP_CRON', true", self.config.read_bytes())
        self.restore("cron", interval=5)
        self.assertEqual(self.config.read_bytes(), self.baseline)
        self.assertFalse(job.exists())

    def test_concurrent_unrelated_wp_config_edit_is_preserved_during_restore(self):
        self.apply("debug")
        with self.config.open("ab") as f:
            f.write(b"// Owner future unrelated setting\n")
        self.assertEqual(self.recheck("debug")["state"], "Applied")
        self.restore("debug")
        self.assertEqual(self.config.read_bytes(), self.baseline + b"// Owner future unrelated setting\n")

    def test_no_foreign_or_dynamic_define_is_ever_edited(self):
        examples = [
            b"<?php\ndefine( 'WP_DEBUG', getenv('DEBUG') );\nrequire_once ABSPATH . 'wp-settings.php';\n",
            b"<?php\ndefine( 'WP_DEBUG', false );\ndefine( 'WP_DEBUG', true );\nrequire_once ABSPATH . 'wp-settings.php';\n",
        ]
        for value in examples:
            with self.subTest(source=value):
                self.config.write_bytes(value)
                with self.assertRaises(settings.WPSettingsError):
                    self.recheck("debug")
                self.assertEqual(self.config.read_bytes(), value)
                self.assertFalse(list(self.data.iterdir()))

    def test_inert_comment_and_quoted_explanation_are_not_active_settings(self):
        for kind, constant in (("debug", b"WP_DEBUG"),
                               ("cron", b"DISABLE_WP_CRON")):
            source = (b"<?php\n/*\n" + b"define( '" + constant +
                      b"', false );\n*/\n"
                      b"$example = \"define( '" + constant + b"', false );\";\n"
                      b"require_once ABSPATH . 'wp-settings.php';\n")
            with self.subTest(kind=kind):
                self.config.write_bytes(source)
                interval = 5 if kind == "cron" else None
                self.assertEqual(self.recheck(kind, interval=interval)["state"], "Source Ready")
                self.assertEqual(self.apply(kind, interval=interval)["state"], "Applied")
                self.assertEqual(self.restore(kind, interval=interval)["state"], "Restored")
                self.assertEqual(self.config.read_bytes(), source)
                self.assertFalse(list(self.cron.iterdir()))

    def test_active_unrecognized_definitions_never_become_absent(self):
        for kind, constant in (("debug", b"WP_DEBUG"),
                               ("cron", b"DISABLE_WP_CRON")):
            forms = [
                b"const " + constant + b" = false;",
                b"const /* active */ " + constant + b" = false;",
                b"define( /* existing setting */ '" + constant + b"', false );",
                b"define( '" + constant + b"' /* inline */, false );",
                b"define( $constant_name, false );",  # key could be the requested setting
                b"define( 'WP_' . 'DEBUG', false );",  # dynamic target cannot be verified
                b'define( "WP_{$suffix}", false );',  # interpolated key is dynamic
            ]
            for definition in forms:
                source = (b"<?php\n" + definition +
                          b"\nrequire_once ABSPATH . 'wp-settings.php';\n")
                interval = 7 if kind == "cron" else None
                with self.subTest(kind=kind, definition=definition):
                    self.config.write_bytes(source)
                    with self.assertRaises(settings.WPSettingsError) as review:
                        self.recheck(kind, interval=interval)
                    self.assertEqual(review.exception.stage, "compatibility")
                    with self.assertRaises(settings.WPSettingsError) as attempted:
                        self.call("apply", kind, desired="true", interval=interval,
                                  expected_source=settings._sha(source))
                    self.assertEqual(attempted.exception.stage, "compatibility")
                    self.assertEqual(self.config.read_bytes(), source)
                    self.assertFalse(list(self.data.iterdir()))
                    self.assertFalse(list(self.cron.iterdir()))

    def test_multi_const_declarations_never_masquerade_as_absent(self):
        for kind, constant in (("debug", b"WP_DEBUG"),
                               ("cron", b"DISABLE_WP_CRON")):
            declarations = [
                b"const " + constant + b" = false;",
                b"const OTHER_SETTING = 1, " + constant + b" = false;",
                b"const OTHER_SETTING = 1,\n" + constant + b" = false;",
                b"const OTHER_SETTING = [1, 2], /* explanation */ " +
                constant + b" = false;",
                b"const OTHER_SETTING = 'a;b',\r\n /* active */\r\n" +
                constant + b" = false;",
                b"const /* comment */ OTHER_SETTING = 1, /* c */ " +
                constant + b" = false, NEXT_SETTING = 2;",
            ]
            for declaration in declarations:
                source = (b"<?php\r\n" + declaration + b"\r\n"
                          b"require_once ABSPATH . 'wp-settings.php';\r\n")
                interval = 9 if kind == "cron" else None
                with self.subTest(kind=kind, declaration=declaration):
                    self.config.write_bytes(source)
                    for action in ("recheck", "apply"):
                        with self.assertRaises(settings.WPSettingsError) as error:
                            self.call(action, kind, desired="true", interval=interval,
                                      **({"expected_source": settings._sha(source)}
                                         if action == "apply" else {}))
                        self.assertEqual(error.exception.stage, "compatibility")
                    self.assertEqual(self.config.read_bytes(), source)
                    self.assertFalse(list(self.data.iterdir()))
                    self.assertFalse(list(self.cron.iterdir()))

    def test_prebootstrap_included_php_is_not_an_absent_setting(self):
        for kind, constant in (("debug", b"WP_DEBUG"),
                               ("cron", b"DISABLE_WP_CRON")):
            # A real local PHP source exists; this is NOT merely a comment.
            included = (b"<?php\n"
                        b"define('" + constant + b"', false);\n")
            (self.root / "local-settings.php").write_bytes(included)
            for statement in (
                    b"require __DIR__ . '/local-settings.php';",
                    b"include __DIR__ . '/local-settings.php';",
                    b"require_once(__DIR__ . '/local-settings.php');",
                    b"include_once (__DIR__ . '/local-settings.php');"):
                for declared in (b"", b"define( '" + constant + b"', true );\n"):
                    source = (b"<?php\n" + declared + statement +
                              b"\nrequire_once ABSPATH . 'wp-settings.php';\n")
                    interval = 11 if kind == "cron" else None
                    with self.subTest(kind=kind, statement=statement, direct=bool(declared)):
                        self.config.write_bytes(source)
                        for action in ("recheck", "apply"):
                            with self.assertRaises(settings.WPSettingsError) as error:
                                self.call(action, kind, desired="true", interval=interval,
                                          **({"expected_source": settings._sha(source)}
                                             if action == "apply" else {}))
                            self.assertEqual(error.exception.stage, "compatibility")
                            self.assertIn("before WordPress bootstrap", str(error.exception))
                        self.assertEqual(self.config.read_bytes(), source)
                        self.assertFalse(list(self.data.iterdir()))
                        self.assertFalse(list(self.cron.iterdir()))

    def test_unrelated_const_and_inert_includes_do_not_block_normal_flow(self):
        for kind in ("debug", "cron"):
            source = (b"<?php\n"
                      b"const OTHER_SETTING = 'include require WP_DEBUG';\n"
                      b"$note = \"require_once __DIR__ . '/local-settings.php';\";\n"
                      b"/* include __DIR__ . '/other.php'; */\n"
                      b"// require __DIR__ . '/else.php';\n"
                      b"require_once ABSPATH . 'wp-settings.php';\n")
            with self.subTest(kind=kind):
                self.config.write_bytes(source)
                interval = 5 if kind == "cron" else None
                self.assertEqual(self.recheck(kind, interval=interval)["state"], "Source Ready")
                self.assertEqual(self.apply(kind, interval=interval)["state"], "Applied")
                self.assertEqual(self.recheck(kind, interval=interval)["state"], "Applied")
                self.assertEqual(self.restore(kind, interval=interval)["state"], "Restored")
                self.assertEqual(self.config.read_bytes(), source)
                self.assertFalse(list(self.cron.iterdir()))

    def test_conditionals_and_post_bootstrap_definitions_are_not_managed(self):
        cases = [
            b"<?php\nif (false) {\n  define( 'WP_DEBUG', false );\n}\n"
            b"require_once ABSPATH . 'wp-settings.php';\n",
            b"<?php\nif (false)\ndefine( 'WP_DEBUG', false );\n"
            b"require_once ABSPATH . 'wp-settings.php';\n",
            b"<?php\nif (false):\ndefine( 'WP_DEBUG', false );\nendif;\n"
            b"require_once ABSPATH . 'wp-settings.php';\n",
            b"<?php\nrequire_once ABSPATH . 'wp-settings.php';\n"
            b"define( 'WP_DEBUG', false );\n",
            b"<?php\ndefine( 'wp_debug', false );\n"
            b"require_once ABSPATH . 'wp-settings.php';\n",
        ]
        for source in cases:
            with self.subTest(source=source):
                self.config.write_bytes(source)
                with self.assertRaises(settings.WPSettingsError):
                    self.recheck("debug")
                self.assertEqual(self.config.read_bytes(), source)
                self.assertFalse(list(self.data.iterdir()))

    def test_only_live_bootstrap_and_literal_definition_are_edited(self):
        initial = (
            b"<?php\n/*\n"
            b"require_once ABSPATH . 'wp-settings.php';\n"
            b"*/\n"
            b"$comment_like = 'http://example.test/a/*b';\n"
            b"  define( 'WP_DEBUG', false );\n"
            b"require_once ABSPATH . 'wp-settings.php';\n"
        )
        self.config.write_bytes(initial)
        self.assertEqual(self.apply("debug")["state"], "Applied")
        changed = self.config.read_bytes()
        self.assertIn(b"$comment_like = 'http://example.test/a/*b';", changed)
        self.assertEqual(changed.count(b"require_once ABSPATH"), 2)
        self.assertIn(b"WP_DEBUG', true", changed)
        self.assertEqual(self.restore("debug")["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), initial)

    def test_commented_bootstrap_does_not_count_as_a_live_anchor(self):
        original = (
            b"<?php\n/*\nrequire_once ABSPATH . 'wp-settings.php';\n*/\n"
            b"require_once ABSPATH . 'wp-settings.php';\n"
        )
        self.config.write_bytes(original)
        self.apply("debug")
        self.restore("debug")
        self.assertEqual(self.config.read_bytes(), original)

    def test_crlf_literal_and_absent_setting_keep_exact_recovery(self):
        original = self.baseline.replace(b"\n", b"\r\n")
        self.config.write_bytes(original)
        self.apply("debug")
        self.assertIn(b"WP_DEBUG', true", self.config.read_bytes())
        self.restore("debug")
        self.assertEqual(self.config.read_bytes(), original)
        without = original.replace(b"define( 'WP_DEBUG', false );\r\n", b"")
        self.config.write_bytes(without)
        review = self.recheck("debug", "false")
        self.assertEqual(review["state"], "Restored")
        self.assertEqual(self.call("apply", "debug", desired="false",
                                   expected_source=review["source_sha256"])["state"],
                         "Applied")
        self.assertIn(b"WP_DEBUG', false", self.config.read_bytes())
        self.restore("debug", "false")
        self.assertEqual(self.config.read_bytes(), without)

    def test_complex_heredoc_requires_manual_review(self):
        source = (
            b"<?php\n$example = <<<MARKER\n"
            b"define( 'WP_DEBUG', false );\nMARKER;\n"
            b"require_once ABSPATH . 'wp-settings.php';\n"
        )
        self.config.write_bytes(source)
        with self.assertRaises(settings.WPSettingsError):
            self.recheck("debug")
        self.assertEqual(self.config.read_bytes(), source)
        self.assertFalse(list(self.data.iterdir()))

    def test_concurrent_source_change_rejects_stale_apply(self):
        info = self.recheck("debug")
        self.config.write_bytes(self.baseline + b"// other admin\n")
        with self.assertRaisesRegex(settings.WPSettingsError, "changed"):
            self.call("apply", "debug", desired="true",
                      expected_source=info["source_sha256"])
        self.assertFalse(list(self.data.iterdir()))

    def test_interrupted_cron_after_task_publication_can_restore(self):
        with patch.object(settings, "_replace_file", side_effect=OSError("simulated")):
            start = self.recheck("cron", interval=7)
            with self.assertRaises(settings.WPSettingsError) as err:
                self.call("apply", "cron", desired="true", interval=7,
                          expected_source=start["source_sha256"])
        self.assertEqual(err.exception.stage, "uncertain")
        self.assertEqual(self.config.read_bytes(), self.baseline)
        self.assertTrue((self.cron / settings._task(9)).exists())
        self.assertEqual(self.recheck("cron", interval=7)["state"], "Recovery Required")
        self.assertEqual(self.restore("cron", interval=7)["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.baseline)
        self.assertFalse((self.cron / settings._task(9)).exists())

    def test_existing_foreign_cron_job_refuses_ownership(self):
        foreign = self.cron / settings._task(9)
        foreign.write_text("# existing owner\n")
        foreign.chmod(0o644)
        self.assertEqual(self.recheck("cron", interval=5)["state"], "Conflict")
        with self.assertRaises(settings.WPSettingsError):
            self.call("apply", "cron", desired="true", interval=5,
                      expected_source=self.recheck("cron", interval=5)["source_sha256"])
        self.assertEqual(foreign.read_text(), "# existing owner\n")
        self.assertFalse(list(self.data.iterdir()))

    def test_source_drift_and_managed_line_edit_prevent_restore(self):
        applied = self.apply("debug")
        self.config.write_bytes(self.config.read_bytes().replace(b"WP_DEBUG', true", b"WP_DEBUG', false"))
        with self.assertRaises(settings.WPSettingsError):
            self.restore("debug")
        self.assertEqual(self.recheck("debug")["state"], "Recovery Required")
        self.assertTrue(applied["recovery_id"])

    def test_resume_interrupted_cron_restore_after_config_was_already_restored(self):
        self.apply("cron", interval=5)
        original_replacer = settings._replace_file
        did_replace = False
        def fail_after_exact_replace(*args, **kwargs):
            nonlocal did_replace
            result = original_replacer(*args, **kwargs)
            if not did_replace:
                did_replace = True
                raise OSError("simulated process interruption after committed config")
            return result
        with patch.object(settings, "_replace_file", side_effect=fail_after_exact_replace):
            with self.assertRaises(settings.WPSettingsError) as error:
                self.restore("cron", interval=5)
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertEqual(self.config.read_bytes(), self.baseline)
        self.assertTrue((self.cron / settings._task(9)).exists())
        self.assertEqual(self.recheck("cron", interval=5)["state"], "Recovery Required")
        recovered = self.restore("cron", interval=5)
        self.assertEqual(recovered["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.baseline)
        self.assertFalse((self.cron / settings._task(9)).exists())

    def test_resume_interrupted_debug_restore_with_unrelated_content_preserved(self):
        self.apply("debug")
        original_replacer = settings._replace_file
        with patch.object(settings, "_replace_file",
                          side_effect=lambda *args, **kwargs:
                          (original_replacer(*args, **kwargs), (_ for _ in ()).throw(
                           OSError("simulated post-rename fault")))):
            with self.assertRaises(settings.WPSettingsError):
                self.restore("debug")
        self.assertEqual(self.recheck("debug")["state"], "Recovery Required")
        with self.config.open("ab") as f:
            f.write(b"// distinct admin edit after prior Restore\n")
        self.assertEqual(self.restore("debug")["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.baseline +
                         b"// distinct admin edit after prior Restore\n")

    def test_invalid_restore_identity_blocks_modification(self):
        self.apply("debug")
        state = self.recheck("debug")
        with self.assertRaises(settings.WPSettingsError):
            self.call("restore", "debug", desired="true",
                      expected_source=state["source_sha256"],
                      expected_recovery="0" * 32)
        self.assertIn(b"WP_DEBUG', true", self.config.read_bytes())


class WPSettingsEndpointTests(unittest.TestCase):
    def setUp(self):
        import ach_customizer_main as backend
        self.backend = backend
        self.plugin = backend.ach_customizer_main()

    def test_admin_authorization_and_explicit_manual_action(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                self.backend, "_STATE_DIR", temp), patch.object(
                self.backend.ach_customizer_main, "_status_primary_admin_post",
                side_effect=PermissionError("No primary admin")):
            denied = self.plugin.wp_settings_manage({
                "settings_action": "recheck", "settings_kind": "debug",
                "desired": "true"
            })
            self.assertFalse(denied["status"])
            self.assertIn("authorization", denied["stage"])
        with tempfile.TemporaryDirectory() as temp, (
                patch.object(self.backend, "_STATE_DIR", temp)), (
                patch.object(self.backend.ach_customizer_main, "_status_primary_admin_post")), (
                patch.object(self.backend.ach_customizer_main, "_require_enabled")):
            denied = self.plugin.wp_settings_manage({
                "settings_action": "apply", "settings_kind": "debug",
                "desired": "true"
            })
            self.assertFalse(denied["status"])
            self.assertIn("authorize", denied["msg"])

    def test_authorized_request_is_site_scoped_and_returns_recovery_reference(self):
        from contextlib import nullcontext
        site = {"id": 7, "name": "wp.example.test",
                "path": "/www/wwwroot/wp.example.test", "status": 1,
                "bound_domains": [{"name": "wp.example.test", "port": 80}]}
        public = types.ModuleType("public")
        public.get_webserver = lambda: "nginx"
        result = {
            "schema": 1, "site_id": 7, "site_key": "wp.example.test",
            "kind": "debug", "state": "Applied", "changed": True,
            "source_sha256": "b" * 64, "recovery_id": "c" * 32,
        }
        with tempfile.TemporaryDirectory() as tmp, (
                patch.dict(sys.modules, {"public": public})), (
                patch.object(self.backend, "_STATE_DIR", tmp)), (
                patch.object(self.backend.ach_customizer_main, "_status_primary_admin_post")), (
                patch.object(self.backend.ach_customizer_main, "_require_enabled")), (
                patch.object(self.backend.ach_customizer_main, "_selected_native_website",
                             return_value=(public, site, lambda: dict(site)))), (
                patch("ach_customizer_cache_wordpress._site_lock",
                      return_value=nullcontext())), (
                patch.object(settings, "manage", return_value=result)) as managed:
            response=self.plugin.wp_settings_manage({
                "settings_action": "apply", "settings_kind": "debug",
                "desired": "true", "site_id": "7",
                "approved": "true", "expected_source_sha256": "a" * 64
            })
            self.assertTrue(response["status"], response)
            self.assertEqual(response["state"], "Applied")
            self.assertEqual(response["recovery_id"], "c" * 32)
            self.assertEqual(managed.call_args.args[:4],
                             ("apply", "debug", site, public))
            self.assertEqual(managed.call_args.kwargs["expected_source"], "a" * 64)
            self.assertEqual(managed.call_args.kwargs["interval"], None)


if __name__ == "__main__":
    unittest.main()
