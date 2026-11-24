"""One-click WordPress connection regression: no repeated path edits."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"))
import ach_customizer_cache_wordpress as wp


class WordpressConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-wp-connect-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.site_dir = self.root / "wordpress"
        self.site_dir.mkdir()
        self.site = {"id": 7, "name": "wp.example.test", "path": str(self.site_dir)}
        self.cache = wp.CACHE_ROOT + "/site-7"
        self.config = self.site_dir / "wp-config.php"
        self.original_config = (
            "<?php\n"
            "define( 'DB_PASSWORD', 'leave-this-alone' );\n"
            "define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n"
            "require_once ABSPATH . 'wp-settings.php';\n"
        ).encode()
        self.config.write_bytes(self.original_config)
        self.ini = self.site_dir / ".user.ini"
        self.original_ini = ("open_basedir=" + str(self.site_dir) + "/:/tmp/\n").encode()
        self.ini.write_bytes(self.original_ini)
        self.previous = {"nginx_helper": False, "bridge": False,
                         "options_present": False,
                         "options": {"enable_purge": None, "cache_method": None,
                                     "purge_method": None}}
        # Persisted WP_Role entries: None=absent, False=explicit deny, True=grant.
        # The role_has_cap filter may independently override the effective view.
        self.admin_caps_stored = {"Nginx Helper | Config": None,
                                  "Nginx Helper | Purge cache": None}
        self.admin_caps_filter = {}
        self.fail_role_persistence = False
        self.fail_role_write_after = None
        self.connected = False
        self.native_restored = False
        self.native_id = "f" * 32
        self.native_generation = "c" * 32
        self.wp_active = False
        self.options = {"enable_purge": 0, "cache_method": "enable_fastcgi",
                        "purge_method": "unlink_files"}
        self.runtime_override = None
        self.events = []

    def fake_cache(self, action, site, *args, **kwargs):
        self.events.append(("cache", action))
        if action == "recheck":
            state = ("Applied" if self.connected else
                     "Restored" if self.native_restored else "Unmanaged")
            return {"state": state, "site_id": 7, "site_key": self.site["name"],
                    "runtime_verified": state != "Unmanaged",
                    "recovery_id": self.native_id if state != "Unmanaged" else None}
        if action == "apply":
            self.connected = True
            self.native_restored = False
            return {"state": "Applied", "recovery_id": self.native_id}
        if action == "bridge_enable":
            return {"state": "Provisioned"}
        if action == "restore":
            self.connected = False
            self.native_restored = True
            return {"state": "Restored"}
        raise AssertionError(action)

    def fake_php(self, site, version, command, **kwargs):
        self.events.append(("php", command))
        effective = (self.runtime_override if self.runtime_override is not None else
                     wp._extract_constant(self.config.read_bytes(), allow_absent=True))
        role_view = dict(self.admin_caps_stored)
        filtered_view = {key: bool(self.admin_caps_filter.get(key, stored))
                         for key, stored in role_view.items()}
        previous = dict(self.previous, constant=effective,
                        admin_caps_stored=role_view, admin_caps_effective=filtered_view)
        if command == "inspect":
            return {"previous": previous,
                    "active_helper": self.wp_active, "active_bridge": self.wp_active,
                    "options": dict(self.options)}
        if command == "connect":
            if kwargs.get("expected_cache_path") != effective:
                raise wp.WordpressCacheError(
                    "wordpress", "Effective WordPress Nginx Helper Cache path differs")
            self.wp_active = True
            for key in self.admin_caps_stored:
                if self.admin_caps_stored[key] is not True:
                    if not self.fail_role_persistence:
                        self.admin_caps_stored[key] = True
                    if self.fail_role_write_after == key:
                        self.fail_role_write_after = None
                        raise RuntimeError("injected interrupted persisted capability write")
                if self.admin_caps_filter.get(key, True) is False:
                    raise wp.WordpressCacheError("wordpress", "WordPress capability filter denies grant")
            self.options.update({"cache_method": "enable_fastcgi",
                                 "purge_method": "unlink_files",
                                 "enable_purge": 1})
        if command == "suspend":
            self.options["enable_purge"] = 0
        if command == "restore":
            self.wp_active = bool(self.previous["nginx_helper"] and
                                  self.previous["bridge"])
            old = kwargs.get("previous", {}).get("admin_caps_stored", {})
            for key, baseline in old.items():
                if self.admin_caps_stored[key] != baseline and not self.fail_role_persistence:
                    self.admin_caps_stored[key] = baseline
                if self.fail_role_write_after == key:
                    self.fail_role_write_after = None
                    raise RuntimeError("injected interrupted persisted capability restore")
            self.options["enable_purge"] = 0
        return {"previous": previous,
                "active_helper": self.wp_active, "active_bridge": self.wp_active,
                "options": dict(self.options)}

    def native_journal(self, site, data_dir):
        return {"op": self.native_id, "cache_generation": self.native_generation,
                "site_key": self.site["name"], "phase":
                ("applied" if self.connected else "restored" if self.native_restored else "prepared")}

    def start(self):
        patches = [
            patch.object(wp, "_site_root", return_value=str(self.site_dir)),
            patch.object(wp, "_native_record", side_effect=lambda *a: self.fake_cache("recheck", self.site)),
            patch.object(wp, "_read_managed", side_effect=self.native_journal),
            patch.object(wp, "preview_cache_activation",
                         return_value={"native_handler": "wpfastcgi", "php_version": "85",
                                       "source_sha256": "a" * 64,
                                       "proposal_sha256": "b" * 64,
                                       "cache_generation": "c" * 32}),
            patch("ach_customizer_cache_audit.inspect_site_fastcgi_cache",
                  return_value={"php_version": "85"}),
            patch.object(wp, "_php", side_effect=self.fake_php),
            patch.object(wp, "manage_cache", side_effect=self.fake_cache),
            patch.object(wp, "_immutable", return_value=False),
            patch.object(wp, "_reload_php"),
            patch.object(wp, "_active_php", return_value="85"),
            patch("ach_customizer_cache_bridge.disable"),
            patch("ach_customizer_cache_bridge.inspect", return_value="Provisioned"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_single_click_configures_both_files_and_bridge_and_no_second_edits(self):
        self.start()
        first = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(first["state"], "Connected")
        self.assertIn(self.cache.encode(), self.config.read_bytes())
        self.assertIn((self.cache + "/").encode(), self.ini.read_bytes())
        self.assertIn(b"leave-this-alone", self.config.read_bytes())
        saved = (self.config.read_bytes(), self.ini.read_bytes())
        second = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(second["state"], "Connected")
        self.assertFalse(second["changed"])
        self.assertEqual((self.config.read_bytes(), self.ini.read_bytes()), saved)
        self.assertEqual(sum(e == ("cache", "apply") for e in self.events), 1)
        self.assertEqual(sum(e == ("cache", "bridge_enable") for e in self.events), 2)
        record = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertEqual(record["phase"], "connected")
        self.assertEqual(record["recovery_id"], "f" * 32)
        self.assertEqual(record["native_generation"], "c" * 32)
        self.assertEqual(record["previous"]["admin_caps_stored"],
                         {"Nginx Helper | Config": None,
                          "Nginx Helper | Purge cache": None})
        self.assertEqual(set(self.admin_caps_stored.values()), {True})

    def test_existing_vendor_admin_capabilities_survive_disconnect(self):
        self.admin_caps_stored["Nginx Helper | Config"] = True
        self.admin_caps_stored["Nginx Helper | Purge cache"] = False
        self.start()
        self.setup_once()
        self.assertTrue(all(self.admin_caps_stored.values()))
        result = wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(result["state"], "Restored")
        self.assertEqual(self.admin_caps_stored,
                         {"Nginx Helper | Config": True,
                          "Nginx Helper | Purge cache": False})

    def test_missing_purge_capability_detected_and_repaired_without_cache_reapply(self):
        self.start()
        self.setup_once()
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")
        self.admin_caps_stored["Nginx Helper | Purge cache"] = False
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Needs Review")
        applied = sum(x == ("cache", "apply") for x in self.events)
        second = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(second["state"], "Connected")
        self.assertFalse(second["changed"])
        self.assertTrue(all(self.admin_caps_stored.values()))
        self.assertEqual(sum(x == ("cache", "apply") for x in self.events), applied)
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(set(self.admin_caps_stored.values()), {None})

    def test_current_journal_missing_stored_role_baseline_is_rejected_without_edits(self):
        self.start()
        self.setup_once()
        path = self.root / "ach_customizer.nginx-helper.7.json"
        saved = json.loads(path.read_text())
        saved["previous"].pop("admin_caps_stored")
        saved["previous"]["admin_caps"] = {
            "Nginx Helper | Config": False, "Nginx Helper | Purge cache": False}
        path.write_text(json.dumps(saved))
        before_events = list(self.events)
        with self.assertRaisesRegex(
                wp.WordpressCacheError, "persisted administrator role baseline"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        with self.assertRaisesRegex(
                wp.WordpressCacheError, "persisted administrator role baseline"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.events, before_events)
        self.assertEqual(set(self.admin_caps_stored.values()), {True})

    def test_filtered_true_without_stored_grant_restores_exact_absence(self):
        self.admin_caps_filter = {"Nginx Helper | Config": True,
                                  "Nginx Helper | Purge cache": True}
        self.start()
        self.setup_once()
        journal = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertEqual(set(journal["previous"]["admin_caps_stored"].values()), {None})
        self.assertEqual(set(self.admin_caps_stored.values()), {True})
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(set(self.admin_caps_stored.values()), {None})
        self.assertEqual(set(self.admin_caps_filter.values()), {True},
                         "Unrelated WordPress capability filters must not be changed")

    def test_filtered_false_does_not_erase_preexisting_stored_true(self):
        self.admin_caps_stored["Nginx Helper | Config"] = True
        self.admin_caps_filter["Nginx Helper | Config"] = False
        self.start()
        with self.assertRaisesRegex(wp.WordpressCacheError, "capability filter"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertTrue(self.admin_caps_stored["Nginx Helper | Config"])
        journal = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertIs(journal["previous"]["admin_caps_stored"]["Nginx Helper | Config"], True)
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertTrue(self.admin_caps_stored["Nginx Helper | Config"])
        self.assertIsNone(self.admin_caps_stored["Nginx Helper | Purge cache"])

    def test_role_storage_failure_cannot_be_reported_connected_and_can_retry(self):
        self.start()
        self.fail_role_persistence = True
        with self.assertRaisesRegex(wp.WordpressCacheError, "not persisted and usable"):
            self.setup_once()
        self.assertEqual(set(self.admin_caps_stored.values()), {None})
        journal_file = self.root / "ach_customizer.nginx-helper.7.json"
        journal = json.loads(journal_file.read_text())
        self.assertEqual(journal["phase"], "site_configured")
        self.assertEqual(set(journal["previous"]["admin_caps_stored"].values()), {None})
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Needs Review")
        self.fail_role_persistence = False
        self.setup_once()
        self.assertEqual(set(self.admin_caps_stored.values()), {True})
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(set(self.admin_caps_stored.values()), {None})

    def test_interrupted_connect_after_first_role_write_preserves_baseline(self):
        self.start()
        self.fail_role_write_after = "Nginx Helper | Config"
        with self.assertRaisesRegex(RuntimeError, "interrupted persisted capability write"):
            self.setup_once()
        self.assertIs(self.admin_caps_stored["Nginx Helper | Config"], True)
        self.assertIsNone(self.admin_caps_stored["Nginx Helper | Purge cache"])
        journal_file = self.root / "ach_customizer.nginx-helper.7.json"
        original = json.loads(journal_file.read_text())["previous"]["admin_caps_stored"]
        self.assertEqual(set(original.values()), {None})
        self.setup_once()
        self.assertEqual(set(self.admin_caps_stored.values()), {True})
        self.assertEqual(json.loads(journal_file.read_text())["previous"]["admin_caps_stored"],
                         original)
        wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(set(self.admin_caps_stored.values()), {None})

    def test_interrupted_restore_after_first_role_write_is_idempotent(self):
        self.start()
        self.setup_once()
        self.fail_role_write_after = "Nginx Helper | Config"
        with self.assertRaisesRegex(RuntimeError, "interrupted persisted capability restore"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertIsNone(self.admin_caps_stored["Nginx Helper | Config"])
        self.assertIs(self.admin_caps_stored["Nginx Helper | Purge cache"], True)
        journal_file = self.root / "ach_customizer.nginx-helper.7.json"
        self.assertEqual(json.loads(journal_file.read_text())["phase"], "restore_reloaded")
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(set(self.admin_caps_stored.values()), {None})
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["changed"],
                         False)

    def test_failed_restored_role_write_retries_without_false_success(self):
        self.start()
        self.setup_once()
        self.fail_role_persistence = True
        with self.assertRaisesRegex(wp.WordpressCacheError, "durably restored"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        j = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertEqual(j["phase"], "restore_reloaded")
        self.assertEqual(set(self.admin_caps_stored.values()), {True})
        self.fail_role_persistence = False
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(set(self.admin_caps_stored.values()), {None})

    def test_one_click_disconnect_restores_original_lines_without_extra_steps(self):
        self.start()
        wp.setup(self.site, object(), data_dir=str(self.root))
        reply = wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(reply["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertEqual(set(self.admin_caps_stored.values()), {None})
        self.assertIn(("php", "suspend"), self.events)
        self.assertIn(("php", "restore"), self.events)
        self.assertIn(("cache", "restore"), self.events)
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["changed"], False)
        with patch.object(wp, "manage_cache", return_value={
                "state": "Restored", "recovery_id": "f" * 32,
                "runtime_verified": True}):
            self.assertEqual(
                wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                "Not Connected")

    def test_preexisting_native_cache_is_not_rolled_back_by_disconnect(self):
        # A site may already have a manually Applied native Cache before
        # WordPress Helper was installed. One-click owns only WP integration.
        self.connected = True
        self.start()
        first = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(first["state"], "Connected")
        journal = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertFalse(journal["cache_owned"])
        self.assertNotIn(("cache", "apply"), self.events)
        outcome = wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(outcome["state"], "Restored")
        self.assertTrue(self.connected, "Existing native Cache must remain Applied")
        self.assertNotIn(("cache", "restore"), self.events)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Not Connected")
        # The site can reconnect without reparing or reapplying the
        # previous native Cache generation or re-editing its owner file.
        again = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(again["state"], "Connected")
        self.assertTrue(self.connected)
        self.assertNotIn(("cache", "restore"), self.events)

    def test_partial_disconnect_retries_from_each_exact_checkpoint(self):
        for failed_step in ("config", "ini", "reload", "wp_options",
                            "native_restore", "post_native_restore"):
            with self.subTest(step=failed_step):
                # Use a fresh fixture per stage to avoid cross-case state.
                case = WordpressConnectionTests("runTest")
                case.setUp()
                case.start()
                self.addCleanup(case.doCleanups)
                peer = case.root / "peer-cache"
                peer.write_bytes(b"peer-cache-unrelated-to-selected-site")
                case.setup_once()
                original_edit = wp._replace_file
                original_php = wp._php
                original_cache = wp.manage_cache
                original_save = wp._save
                injected = [False]
                def editing(*args, **kwargs):
                    value = original_edit(*args, **kwargs)
                    if not injected[0] and (failed_step == "config" and args[1] == wp.WORDPRESS_CONFIG
                                             or failed_step == "ini" and args[1] == wp.USER_INI):
                        injected[0] = True
                        raise RuntimeError("injected post-edit checkpoint")
                    return value
                def php_step(*args, **kwargs):
                    if failed_step == "wp_options" and args[2] == "restore" and not injected[0]:
                        injected[0] = True
                        raise RuntimeError("injected WordPress option restore")
                    return original_php(*args, **kwargs)
                def cache_step(*args, **kwargs):
                    if failed_step == "native_restore" and args[0] == "restore" and not injected[0]:
                        injected[0] = True
                        raise RuntimeError("injected native Cache restore")
                    return original_cache(*args, **kwargs)
                def saving(*args, **kwargs):
                    if (failed_step == "post_native_restore" and
                            args[1]["phase"] == "restored" and not injected[0]):
                        injected[0] = True
                        raise RuntimeError("injected final journal write")
                    return original_save(*args, **kwargs)
                with patch.object(wp, "_replace_file", side_effect=editing), \
                     patch.object(wp, "_php", side_effect=php_step), \
                     patch.object(wp, "manage_cache", side_effect=cache_step), \
                     patch.object(wp, "_save", side_effect=saving):
                    if failed_step == "reload":
                        with patch.object(wp, "_reload_php", side_effect=RuntimeError("injected PHP reload")):
                            with self.assertRaisesRegex(RuntimeError, "injected"):
                                wp.restore(case.site, object(), data_dir=str(case.root))
                        injected[0] = True
                    else:
                        with self.assertRaisesRegex(RuntimeError, "injected"):
                            wp.restore(case.site, object(), data_dir=str(case.root))
                self.assertTrue(injected[0])
                outcome = wp.restore(case.site, object(), data_dir=str(case.root))
                self.assertEqual(outcome["state"], "Restored")
                self.assertEqual(case.config.read_bytes(), case.original_config)
                self.assertEqual(case.ini.read_bytes(), case.original_ini)
                self.assertEqual(peer.read_bytes(), b"peer-cache-unrelated-to-selected-site")
                journal = json.loads((case.root / "ach_customizer.nginx-helper.7.json").read_text())
                self.assertEqual(journal["phase"], "restored")
                self.assertEqual(journal["recovery_id"], case.native_id)
                self.assertFalse(case.connected)

    def setup_once(self):
        result = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(result["state"], "Connected")

    def test_setup_can_retry_after_file_write_and_reload_interruptions(self):
        for failure in ("post_config", "post_ini", "reload"):
            with self.subTest(failure=failure):
                case = WordpressConnectionTests("runTest")
                case.setUp()
                case.start()
                self.addCleanup(case.doCleanups)
                original_edit = wp._replace_file
                failed = [False]
                def editor(*args, **kwargs):
                    changed = original_edit(*args, **kwargs)
                    if (changed and not failed[0] and
                            ((failure == "post_config" and args[1] == wp.WORDPRESS_CONFIG)
                             or (failure == "post_ini" and args[1] == wp.USER_INI))):
                        failed[0] = True
                        raise RuntimeError("injected source edit")
                    return changed
                with patch.object(wp, "_replace_file", side_effect=editor):
                    if failure == "reload":
                        with patch.object(wp, "_reload_php", side_effect=RuntimeError("injected reload")):
                            with self.assertRaisesRegex(RuntimeError, "injected"):
                                wp.setup(case.site, object(), data_dir=str(case.root))
                    else:
                        with self.assertRaisesRegex(RuntimeError, "injected"):
                            wp.setup(case.site, object(), data_dir=str(case.root))
                outcome = wp.setup(case.site, object(), data_dir=str(case.root))
                self.assertEqual(outcome["state"], "Connected")
                self.assertEqual(wp._extract_constant(case.config.read_bytes()), case.cache)
                self.assertIn((case.cache + "/").encode(), case.ini.read_bytes())

    def test_wpconfig_only_change_still_reloads_selected_php_fpm(self):
        self.original_ini = ("open_basedir=" + str(self.site_dir) +
                             "/:/tmp/:" + self.cache + "/\n").encode()
        self.ini.write_bytes(self.original_ini)
        self.start()
        with patch.object(wp, "_reload_php") as reload:
            self.setup_once()
            reload.assert_called_once_with("85")
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertEqual(wp._extract_constant(self.config.read_bytes()), self.cache)

    def test_disconnect_before_native_apply_reports_not_connected(self):
        self.start()
        with patch.object(wp, "preview_cache_activation",
                          side_effect=wp.CacheManageError("compatibility", "preview refused")):
            with self.assertRaises(wp.CacheManageError):
                wp.setup(self.site, object(), data_dir=str(self.root))
        result = wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(result["state"], "Restored")
        self.assertFalse(self.connected)
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Not Connected")
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)

    def test_check_reports_partial_native_recovery_without_a_write(self):
        self.start()
        self.setup_once()
        journal = self.root / "ach_customizer.nginx-helper.7.json"
        before = (journal.read_bytes(), self.config.read_bytes(), self.ini.read_bytes())
        for state in ("Recovery Required", "Needs Review"):
            with self.subTest(state=state), \
                 patch.object(wp, "manage_cache", return_value={
                     "state": state, "recovery_id": "f" * 32,
                     "runtime_verified": False, "note": "Saved source requires review"
                 }) as native, patch.object(wp, "_php") as php, \
                 patch.object(wp, "_save") as save:
                result = wp.inspect(self.site, object(), data_dir=str(self.root))
                self.assertEqual(result["state"], "Needs Review")
                self.assertTrue(result["read_only"])
                self.assertEqual(result["recovery_id"], "f" * 32)
                self.assertIn(state, result["note"])
                self.assertIn("Apply & restore", result["note"])
                self.assertIn("Saved source requires review", result["note"])
                self.assertEqual(native.call_args.args[0], "recheck")
                native.assert_called_once()
                php.assert_not_called()
                save.assert_not_called()
                self.assertEqual((journal.read_bytes(), self.config.read_bytes(),
                                  self.ini.read_bytes()), before)

    def test_inspect_detects_only_cache_method_drift(self):
        self.start()
        self.setup_once()
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"], "Connected")
        self.options["cache_method"] = "disable_cache"
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"], "Needs Review")
        self.options["cache_method"] = "enable_fastcgi"
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"], "Connected")

    def test_cannot_adopt_stale_native_cache_generation_as_connector_owned(self):
        self.start()
        self.setup_once()
        before = (self.root / "ach_customizer.nginx-helper.7.json").read_bytes()
        self.native_id = "b" * 32
        self.native_generation = "d" * 32
        with self.assertRaisesRegex(wp.WordpressCacheError, "Different native Cache generation"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        with self.assertRaisesRegex(wp.WordpressCacheError, "Different native Cache generation"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual((self.root / "ach_customizer.nginx-helper.7.json").read_bytes(), before)
        self.assertNotIn(("cache", "restore"), self.events)

    def test_intentional_connect_after_completed_restore_does_not_own_new_manual_cache(self):
        self.start()
        self.setup_once()
        wp.restore(self.site, object(), data_dir=str(self.root))
        self.native_id = "b" * 32
        self.native_generation = "d" * 32
        self.connected, self.native_restored = True, False
        outcome = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(outcome["state"], "Connected")
        record = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertFalse(record["cache_owned"])
        self.assertEqual(record["recovery_id"], "b" * 32)
        self.assertEqual(record["native_generation"], "d" * 32)
        wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertTrue(self.connected, "Native B must be retained after WordPress disconnect")

    def test_native_generation_drift_with_unchanged_recovery_id_is_rejected(self):
        self.start()
        self.setup_once()
        self.native_generation = "d" * 32
        self.assertEqual(
            wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
            "Needs Review")
        with self.assertRaisesRegex(wp.WordpressCacheError, "Different native Cache generation"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        with self.assertRaisesRegex(wp.WordpressCacheError, "Different native Cache generation"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertTrue(self.connected)

    def test_wpconfig_only_pending_reload_retries_after_uncertain_worker_signal(self):
        self.original_ini = ("open_basedir=" + str(self.site_dir) +
                             "/:/tmp/:" + self.cache + "/\n").encode()
        self.ini.write_bytes(self.original_ini)
        self.start()
        with patch.object(wp, "_reload_php", side_effect=RuntimeError("FPM reload uncertain")):
            with self.assertRaisesRegex(RuntimeError, "FPM reload uncertain"):
                wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(wp._extract_constant(self.config.read_bytes()), self.cache)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        before = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertEqual(before["phase"], "configuring")
        with patch.object(wp, "_reload_php") as reload:
            outcome = wp.setup(self.site, object(), data_dir=str(self.root))
            reload.assert_called_once_with("85")
        self.assertEqual(outcome["state"], "Connected")

    def test_foreign_config_during_disconnected_recovery_is_rejected(self):
        self.start()
        self.setup_once()
        self.config.write_bytes(self.config.read_bytes().replace(
            self.cache.encode(), b"/opt/operator-owned-custom-cache"))
        before = self.config.read_bytes()
        with self.assertRaisesRegex(wp.WordpressCacheError, "neither the saved original"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue(self.connected)

    def test_interrupted_native_apply_reconciles_only_saved_pending_generation(self):
        self.start()
        saved = wp._save
        raised = [False]
        def interrupted(site, record, data_dir):
            if (record["phase"] == "cache_applied" and not raised[0]):
                raised[0] = True
                raise RuntimeError("simulated lost post-Apply checkpoint")
            return saved(site, record, data_dir)
        with patch.object(wp, "_save", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "checkpoint"):
                wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertTrue(self.connected)
        state = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertIsNone(state["recovery_id"])
        self.assertEqual(state["pending_generation"], self.native_generation)
        outcome = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(outcome["state"], "Connected")
        self.assertEqual(self.events.count(("cache", "apply")), 1)

    def test_missing_helper_fails_before_any_cache_write(self):
        self.start()
        with patch.object(wp, "_php", side_effect=wp.WordpressCacheError(
                "wordpress", "Required WordPress plugin missing: nginx-helper")):
            with self.assertRaisesRegex(wp.WordpressCacheError, "plugin missing"):
                wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertFalse((self.root / "ach_customizer.nginx-helper.7.json").exists())

    def test_pristine_native_wordpress_without_constant_is_one_click_and_reversible(self):
        # Native aaPanel OneClick WordPress does not preinstall the Helper path.
        self.original_config = self.original_config.replace(
            b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n",
            b"")
        self.config.write_bytes(self.original_config)
        self.start()
        first = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(first["state"], "Connected")
        self.assertEqual(wp._extract_constant(self.config.read_bytes()), self.cache)
        self.assertEqual(self.config.read_bytes().count(wp.WP_CONSTANT_NAME), 1)
        self.assertLess(self.config.read_bytes().find(wp.WP_CONSTANT_NAME),
                        self.config.read_bytes().find(b"require_once ABSPATH"))
        connected = self.config.read_bytes()
        second = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertFalse(second["changed"])
        self.assertEqual(self.config.read_bytes(), connected)
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")
        record = json.loads((self.root / "ach_customizer.nginx-helper.7.json").read_text())
        self.assertIsNone(record["wp_old"])
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)
        self.assertNotIn(wp.WP_CONSTANT_NAME, self.config.read_bytes())
        self.assertEqual(wp.setup(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)

    def test_active_helper_runtime_default_without_source_override_is_reversible(self):
        # Installed Nginx Helper may define a filtered vendor fallback after
        # WordPress loads; wp-config.php itself has no explicit Cache path.
        self.original_config = self.original_config.replace(
            b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n",
            b"")
        self.config.write_bytes(self.original_config)
        self.previous["nginx_helper"] = True
        self.previous["bridge"] = True
        self.wp_active = True
        self.start()

        def vendor_default_php(site, version, command, **kwargs):
            source = wp._extract_constant(self.config.read_bytes(), allow_absent=True)
            self.runtime_override = "/var/run/nginx-cache" if source is None else None
            return self.fake_php(site, version, command, **kwargs)

        with patch.object(wp, "_php", side_effect=vendor_default_php):
            connected = wp.setup(self.site, object(), data_dir=str(self.root))
            self.assertEqual(connected["state"], "Connected")
            self.assertEqual(wp._extract_constant(self.config.read_bytes()), self.cache)
            self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                             "Connected")
            restored = wp.restore(self.site, object(), data_dir=str(self.root))
            self.assertEqual(restored["state"], "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(self.ini.read_bytes(), self.original_ini)

    def test_one_click_supports_stock_native_php_handler(self):
        # A fresh aaPanel WordPress site can retain enable-php-85.conf.
        self.start()
        with patch.object(wp, "preview_cache_activation", return_value={
                "native_handler": "stock", "php_version": "85",
                "source_sha256": "a" * 64, "proposal_sha256": "b" * 64,
                "cache_generation": "c" * 32}):
            result = wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(result["state"], "Connected")
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)

    def test_pristine_native_wordpress_source_edit_can_resume_and_restore(self):
        self.original_config = self.original_config.replace(
            b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n",
            b"")
        self.config.write_bytes(self.original_config)
        self.start()
        real_edit = wp._replace_file
        already = [False]
        def interrupt(*args, **kwargs):
            changed = real_edit(*args, **kwargs)
            if changed and args[1] == wp.WORDPRESS_CONFIG and not already[0]:
                already[0] = True
                raise RuntimeError("simulated interruption after wp-config edit")
            return changed
        with patch.object(wp, "_replace_file", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes().count(wp.WP_CONSTANT_NAME), 1)
        self.assertEqual(wp.setup(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")
        self.assertEqual(self.config.read_bytes().count(wp.WP_CONSTANT_NAME), 1)
        self.assertEqual(wp.restore(self.site, object(), data_dir=str(self.root))["state"],
                         "Restored")
        self.assertEqual(self.config.read_bytes(), self.original_config)

    def test_native_wordpress_bootstrap_and_malformed_constant_fail_without_change(self):
        original = self.config.read_bytes()
        scenarios = [
            b"<?php\ndefine('DB_PASSWORD', 'secret');\n",
            b"<?php\ndefine('RT_WP_NGINX_HELPER_CACHE_PATH', getenv('PATH'));\n"
            b"require_once ABSPATH . 'wp-settings.php';\n",
            original.replace(b"require_once ABSPATH",
                             b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\nrequire_once ABSPATH")
        ]
        for contents in scenarios:
            with self.subTest(contents=contents[:45]):
                self.config.write_bytes(contents)
                with patch.object(wp, "_immutable", return_value=False):
                    with self.assertRaises(wp.WordpressCacheError):
                        wp._edits(self.site)
                self.assertEqual(self.config.read_bytes(), contents)

    def test_native_wordpress_crlf_bootstrap_roundtrip(self):
        config = b"<?php\r\ndefine('DB_PASSWORD', 'unchanged');\r\nrequire_once ABSPATH . 'wp-settings.php';\r\n"
        target = wp._replace_wp_constant(config, self.cache)
        self.assertIn(b"');\r\nrequire_once", target)
        self.assertEqual(wp._replace_wp_constant(target, None, managed_cache=self.cache), config)

    def test_dynamic_and_literal_constant_are_rejected_before_any_cache_apply(self):
        dynamic = (b"define(\n  'RT_WP_NGINX_HELPER_CACHE_PATH',\n"
                   b"  '/www/server/' . 'fastcgi_cache'\n);\n")
        original = self.original_config
        self.config.write_bytes(original.replace(
            b"require_once ABSPATH", dynamic + b"require_once ABSPATH"))
        self.start()
        with self.assertRaisesRegex(wp.WordpressCacheError, "Complex or repeated"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertFalse(self.connected)
        self.assertFalse(self.wp_active)
        self.assertEqual(self.options["enable_purge"], 0)

    def test_literal_definition_in_php_multiline_comment_is_not_live(self):
        self.config.write_bytes(
            b"<?php\n/*\n"
            b"define('RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache');\n"
            b"*/\nrequire_once ABSPATH . 'wp-settings.php';\n")
        with patch.object(wp, "_immutable", return_value=False):
            with self.assertRaisesRegex(wp.WordpressCacheError, "inside a PHP comment"):
                wp._edits(self.site)

    def test_runtime_source_mismatch_is_refused_before_native_cache_apply(self):
        self.runtime_override = "/www/server/elsewhere"
        self.start()
        with self.assertRaisesRegex(wp.WordpressCacheError, "differs from its source"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertNotIn(("cache", "apply"), self.events)
        self.assertFalse(self.wp_active)
        self.assertEqual(self.options["enable_purge"], 0)

    def test_active_helper_never_overrides_explicit_mismatched_source(self):
        self.previous["nginx_helper"] = True
        self.wp_active = True
        self.runtime_override = "/var/run/nginx-cache"
        self.start()
        with self.assertRaisesRegex(wp.WordpressCacheError, "differs from its source"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertNotIn(("cache", "apply"), self.events)

    def test_missing_helper_cannot_claim_dynamic_runtime_default(self):
        self.original_config = self.original_config.replace(
            b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n",
            b"")
        self.config.write_bytes(self.original_config)
        self.runtime_override = "/var/run/nginx-cache"
        self.start()
        with self.assertRaisesRegex(wp.WordpressCacheError, "differs from its source"):
            wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertNotIn(("cache", "apply"), self.events)

    def test_runtime_path_changes_after_reload_cannot_enable_vendor_purge(self):
        self.start()
        def wrong_runtime(_version):
            self.runtime_override = "/www/server/fastcgi_cache"
        with patch.object(wp, "_reload_php", side_effect=wrong_runtime):
            with self.assertRaisesRegex(wp.WordpressCacheError, "Effective WordPress"):
                wp.setup(self.site, object(), data_dir=str(self.root))
        self.assertTrue(self.connected)
        self.assertFalse(self.wp_active)
        self.assertEqual(self.options["enable_purge"], 0)
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Needs Review")
        self.runtime_override = None
        self.assertEqual(wp.setup(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")

    def test_connected_inspection_requires_effective_runtime_cache_path(self):
        self.start()
        self.setup_once()
        self.runtime_override = "/www/server/fastcgi_cache"
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Needs Review")
        self.runtime_override = None
        self.assertEqual(wp.inspect(self.site, object(), data_dir=str(self.root))["state"],
                         "Connected")

    def test_pristine_disconnect_never_removes_operator_reformatted_definition(self):
        self.original_config = self.original_config.replace(
            b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache' );\n",
            b"")
        self.config.write_bytes(self.original_config)
        self.start()
        self.setup_once()
        self.config.write_bytes(self.config.read_bytes().replace(
            b"define('RT_WP_NGINX_HELPER_CACHE_PATH', '",
            b"define( 'RT_WP_NGINX_HELPER_CACHE_PATH', '"))
        changed = self.config.read_bytes()
        with self.assertRaisesRegex(wp.WordpressCacheError, "Connector-managed"):
            wp.restore(self.site, object(), data_dir=str(self.root))
        self.assertEqual(self.config.read_bytes(), changed)
        self.assertEqual(self.options["enable_purge"], 1)

    @unittest.skipUnless(shutil.which("php"), "PHP CLI unavailable")
    def test_embedded_php_refuses_wrong_runtime_cache_before_vendor_actions(self):
        # Exercise the real embedded PHP guard with a tiny isolated WP fixture,
        # not a mocked Python check or a live WordPress/database installation.
        root = self.site_dir
        (root / "wp-admin" / "includes").mkdir(parents=True)
        (root / "wp-admin" / "includes" / "plugin.php").write_text("<?php\n")
        for plugin in ("nginx-helper/nginx-helper.php",
                       "ach-aapanel-bridge/ach-aapanel-bridge.php"):
            path = root / "wp-content" / "plugins" / plugin
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<?php\n")
        (root / "wp-load.php").write_text("""<?php
// Model the enabled login-URL protection observed on an actual site:
// a fake admin HTTP context exits before the connector can inspect.
if (defined('WP_ADMIN') && WP_ADMIN) exit(0);
if (defined('WP_CLI') && WP_CLI) exit(91);
define('ABSPATH', __DIR__ . '/');
define('WP_PLUGIN_DIR', __DIR__ . '/wp-content/plugins');
define('RT_WP_NGINX_HELPER_CACHE_PATH', '/www/server/fastcgi_cache');
function get_site_option($key, $default = false) { return $default; }
class TestAdminRole {
    public $capabilities = [];
    public function has_cap($cap) { return (bool)($this->capabilities[$cap] ?? false); }
    public function add_cap($cap, $grant=true) {
        $this->capabilities[$cap] = $grant;
        file_put_contents(__DIR__ . '/vendor-actions', 'cap:' . $cap . "\n", FILE_APPEND);
    }
    public function remove_cap($cap) { unset($this->capabilities[$cap]); }
}
function get_role($role) {
    if ($role !== 'administrator') return null;
    static $admin = null;
    return $admin ??= new TestAdminRole();
}
function is_plugin_active($plugin) { return false; }
function is_wp_error($error) { return false; }
function activate_plugin($plugin) {
    file_put_contents(__DIR__ . '/vendor-actions', 'activate:' . $plugin . "\\n", FILE_APPEND);
    return null;
}
function update_site_option($key, $value) {
    file_put_contents(__DIR__ . '/vendor-actions', 'update', FILE_APPEND);
}
""")
        result = subprocess.run(
            [shutil.which("php"), "-r", wp.PHP_BRIDGE], cwd=root,
            input=json.dumps({"action": "connect", "expected_cache_path": self.cache}),
            capture_output=True, text=True, check=False, timeout=15)
        # Prove the prior incorrect bootstrap really terminates this fixture.
        old = subprocess.run([shutil.which("php"), "-r", "define('WP_ADMIN', true);" + wp.PHP_BRIDGE],
                             cwd=root, input=json.dumps({"action":"inspect"}),
                             capture_output=True, text=True, timeout=15)
        self.assertEqual(old.returncode, 0)
        self.assertNotIn("ACH_WORDPRESS_CACHE_RESULT=", old.stdout)
        self.assertIn('"phase":"bootstrap"', old.stderr)
        self.assertEqual(result.returncode, 15, result.stderr)
        self.assertIn("Effective WordPress", result.stderr)
        self.assertFalse((root / "vendor-actions").exists())
        result = subprocess.run(
            [shutil.which("php"), "-r", wp.PHP_BRIDGE], cwd=root,
            input=json.dumps({"action": "connect",
                              "expected_cache_path": "/www/server/fastcgi_cache"}),
            capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("activate:nginx-helper", (root / "vendor-actions").read_text())
        self.assertIn("update", (root / "vendor-actions").read_text())

    @unittest.skipUnless(shutil.which("php"), "PHP CLI unavailable")
    def test_php_reports_safe_early_exit_and_fatal_bootstrap_diagnostics(self):
        real_run = subprocess.run
        def native_run(args, **kwargs):
            return real_run([shutil.which("php"), *args[5:]], **kwargs)
        # Exercise the real Python parser and PHP shutdown reporter. Replace
        # only the production runuser/bin path with this test's actual PHP.
        with patch.object(wp.Path, "is_file", return_value=True), \
             patch.object(wp.subprocess, "run", side_effect=native_run):
            (self.site_dir / "wp-load.php").write_text(
                '<?php echo "private-output"; exit(0);')
            with self.assertRaisesRegex(wp.WordpressCacheError, "bootstrap: Missing result marker .*PHP exit 0") as early:
                wp._php(self.site, "85", "inspect")
            self.assertNotIn("private-output", str(early.exception))
            (self.site_dir / "wp-load.php").write_text(
                '<?php trigger_error("private-secret", E_USER_ERROR);')
            with self.assertRaisesRegex(wp.WordpressCacheError, "bootstrap:.*fatal type 256 at wp-load.php:1") as fatal:
                wp._php(self.site, "85", "inspect")
            self.assertNotIn("private-secret", str(fatal.exception))

    def test_custom_cache_path_must_not_be_overwritten(self):
        self.config.write_bytes(self.original_config.replace(
            b"/www/server/fastcgi_cache", b"/home/operator/custom-cache"))
        with patch.object(wp, "_immutable", return_value=False):
            with self.assertRaisesRegex(wp.WordpressCacheError, "custom"):
                wp._edits(self.site)
        self.assertIn(b"/home/operator/custom-cache", self.config.read_bytes())

    def test_atomic_editor_preserves_unrelated_settings(self):
        before, _ = wp._read_file(str(self.site_dir), "wp-config.php")
        after = before.replace(b"/www/server/fastcgi_cache", self.cache.encode())
        wp._replace_file(str(self.site_dir), "wp-config.php", before, after)
        self.assertIn(b"DB_PASSWORD", self.config.read_bytes())
        self.assertEqual(self.config.read_bytes(), after)
        with self.assertRaisesRegex(wp.WordpressCacheError, "modified"):
            wp._replace_file(str(self.site_dir), "wp-config.php", before, b"bad")

    def test_symlink_is_not_a_site_config(self):
        self.ini.unlink()
        self.ini.symlink_to(self.config)
        with self.assertRaises(OSError):
            wp._read_file(str(self.site_dir), ".user.ini")

    def test_bootstrap_only_adds_native_extension_before_php_block(self):
        vhost = self.root / "vhosts"
        vhost.mkdir()
        (vhost / "extension").mkdir()
        original = (b"server\n{\n    listen 80;\n    server_name wp.example.test;\n" +
                    ("    root " + str(self.site_dir) + ";\n").encode() +
                    b"    #PHP-INFO-START  PHP configuration\n"
                    b"    include enable-php-85-wpfastcgi.conf;\n"
                    b"    #PHP-INFO-END\n}\n")
        path = vhost / "wp.example.test.conf"
        path.write_bytes(original)
        with patch("ach_customizer_cache_manage.VHOST_ROOT", str(vhost)), \
             patch("ach_customizer_cache_manage._missing_extension_inventory"):
            self.assertTrue(wp._bootstrap_site_extension(self.site))
            self.assertTrue((vhost / "extension" / "wp.example.test").is_dir())
            line = b"    include " + str(vhost / "extension" / "wp.example.test" / "*.conf").encode() + b";\n"
            self.assertEqual(path.read_bytes().count(line), 1)
            self.assertEqual(path.read_bytes().replace(line, b"", 1), original)
            self.assertLess(path.read_bytes().find(b"root "), path.read_bytes().find(line))
            self.assertLess(path.read_bytes().find(line), path.read_bytes().find(b"#PHP-INFO-START"))

if __name__ == "__main__":
    unittest.main()
