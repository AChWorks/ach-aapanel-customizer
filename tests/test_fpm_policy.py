"""Real file-backed, no-host-write tests for operator-saved PHP-FPM shared intent."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))

import ach_customizer_fpm_policy as policy
import ach_customizer_state as state
import ach_customizer_main as entrypoint


VALUES = {
    "pm.max_children": 20, "pm.start_servers": 5,
    "pm.min_spare_servers": 5, "pm.max_spare_servers": 10,
    "pm.max_requests": 300,
}


class FpmPolicyTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="ach-fpm-policy-")
        self.addCleanup(self.work.cleanup)
        root = Path(self.work.name)
        self.php_root = root / "php"
        self.etc = self.php_root / "85" / "etc"
        self.etc.mkdir(parents=True)
        self.conf = self.etc / "php-fpm.conf"
        self._write_pool()
        self.data = root / "data"
        self.data.mkdir(mode=0o700)
        self.original = self.conf.read_bytes()

    def _write_pool(self, max_children=20):
        self.conf.write_text(
            "[global]\n"
            "pid = /tmp/fpm-example.pid\n"
            "[www]\n"
            "pm = dynamic\n"
            f"pm.max_children = {max_children}\n"
            "pm.start_servers = 5\n"
            "pm.min_spare_servers = 5\n"
            "pm.max_spare_servers = 10\n"
            "pm.max_requests = 300\n"
        )
        self.conf.chmod(0o644)

    def _save(self, **overrides):
        _, token = policy.observe(str(self.php_root), "85", VALUES)
        inputs = {
            "directory": str(self.data), "expected_revision": 0,
            "expected_monitor_revision": 0,
            "expected_observation_sha256": token, "reviewed": "true",
        }
        inputs.update(overrides)
        return policy.save_policy(str(self.php_root), "85", VALUES, **inputs)

    def test_operator_saves_versioned_desired_values_without_touching_host_files(self):
        self.assertEqual(policy.read_policy(str(self.data))["profiles"], {})
        before = policy.get_policy("85", directory=str(self.data))
        self.assertFalse(before["saved"])
        self.assertEqual(before["policy_revision"], 0)
        preview, token = policy.observe(str(self.php_root), "85", VALUES)
        self.assertEqual(preview["state"], "File Match")
        self.assertRegex(token, r"^[a-f0-9]{64}$")
        saved = self._save()
        self.assertEqual(saved["state"], "Policy Saved")
        self.assertEqual(saved["policy_revision"], 1)
        self.assertFalse(saved["auto_enforce"])
        self.assertFalse(saved["runtime_verified"])
        self.assertEqual(self.original, self.conf.read_bytes())
        self.assertEqual((self.data / policy.POLICY_FILE).stat().st_mode & 0o777, 0o600)
        self.assertEqual(policy.get_policy("85", directory=str(self.data))["desired"], VALUES)
        same = self._save(expected_revision=1)
        self.assertEqual(same["state"], "Policy Unchanged")
        self.assertEqual(same["policy_revision"], 1)
        self.assertEqual(self.original, self.conf.read_bytes())
        self.assertFalse((self.data / state.STATE_FILE).exists())

    def test_external_aaPanel_pool_reset_is_visible_as_file_drift_to_saved_intent(self):
        self._save()
        self._write_pool(max_children=80)
        policy_read = policy.get_policy("85", directory=str(self.data))
        observed, token = policy.observe(str(self.php_root), "85", policy_read["desired"])
        self.assertEqual(observed["state"], "File Drift")
        self.assertEqual(observed["changes"], [
            {"setting":"pm.max_children", "desired":20, "actual":80}
        ])
        self.assertRegex(token, r"^[a-f0-9]{64}$")
        self.assertEqual(policy.read_policy(str(self.data))["profiles"]["85"], VALUES)
        # Merely checking drift never mutates the real FPM config or saved intent.
        self.assertIn(b"max_children = 80", self.conf.read_bytes())

    def test_stale_revision_monitor_toggle_and_source_change_fail_without_write(self):
        preview, token = policy.observe(str(self.php_root), "85", VALUES)
        self.assertEqual(preview["state"], "File Match")
        self._write_pool(max_children=80)
        with self.assertRaisesRegex(policy.FpmPolicyError, "changed since preview"):
            policy.save_policy(str(self.php_root), "85", VALUES, directory=str(self.data),
                               expected_revision=0, expected_monitor_revision=0,
                               expected_observation_sha256=token, reviewed=True)
        self.assertFalse((self.data / policy.POLICY_FILE).exists())
        self._write_pool()
        self._save()
        with self.assertRaisesRegex(policy.FpmPolicyError, "policy changed"):
            self._save(expected_revision=0)
        state.set_enabled("php_fpm_file_preview", False, directory=str(self.data),
                          expected_revision=0)
        with self.assertRaisesRegex(policy.FpmPolicyError, "disabled"):
            policy.get_policy("85", directory=str(self.data))
        with self.assertRaisesRegex(policy.FpmPolicyError, "disabled"):
            self._save(expected_revision=1, expected_monitor_revision=1)
        self.assertEqual(policy.read_policy(str(self.data))["revision"], 1)

    def test_malformed_source_and_profile_refused_safely(self):
        for version in ("", "85.0", "74", "8/5", 85, "8500"):
            with self.subTest(version=version):
                with self.assertRaises(policy.FpmPolicyError):
                    policy.get_policy(version, directory=str(self.data))
        with self.assertRaisesRegex(policy.FpmPolicyError, "Explicit"):
            self._save(reviewed=False)
        with self.assertRaisesRegex(policy.FpmPolicyError, "fingerprint"):
            self._save(expected_observation_sha256="bad")
        self.conf.unlink()
        self.conf.symlink_to("/etc/passwd")
        result, token = policy.observe(str(self.php_root), "85", VALUES)
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(token)
        with self.assertRaisesRegex(policy.FpmPolicyError, "since preview"):
            self._save(expected_observation_sha256="a"*64)
        self.conf.unlink()
        self._write_pool()
        path = self.data / policy.POLICY_FILE
        path.write_text('{"schema":1,"revision":1,"profiles":{"85":{"bogus":4}}}')
        path.chmod(0o600)
        with self.assertRaises(policy.FpmPolicyError):
            policy.get_policy("85", directory=str(self.data))
        path.write_text("{}")
        path.chmod(0o666)
        with self.assertRaisesRegex(policy.FpmPolicyError, "Untrusted"):
            policy.read_policy(str(self.data))

    def test_atomic_store_is_rooted_and_bounded_by_monitor_lock(self):
        self._save()
        monitor_before = state.read_state(str(self.data))
        _, token = policy.observe(str(self.php_root), "85", VALUES)
        updated = dict(VALUES)
        updated["pm.max_children"] = 30
        self.assertNotEqual(updated, VALUES)
        # The signed token is bound to the desired values, not only the file.
        with self.assertRaisesRegex(policy.FpmPolicyError, "changed since preview"):
            policy.save_policy(str(self.php_root), "85", updated, directory=str(self.data),
                               expected_revision=1, expected_monitor_revision=0,
                               expected_observation_sha256=token, reviewed=True)
        self.assertEqual(state.read_state(str(self.data)), monitor_before)
        self.assertEqual(policy.read_policy(str(self.data))["revision"], 1)


class FpmPolicyEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.TemporaryDirectory(prefix="ach-fpm-policy-endpoint-")
        self.addCleanup(self.store.cleanup)
        state_path = patch.object(entrypoint, "_STATE_DIR", self.store.name)
        state_path.start()
        self.addCleanup(state_path.stop)
        self.plugin = entrypoint.ach_customizer_main()
        self.flask = types.ModuleType("flask")
        self.flask.session = {"login":True, "uid":1}
        self.flask.request = types.SimpleNamespace(method="POST")
        self.flask.has_request_context = lambda:True
        self.context = patch.dict(sys.modules, {"flask":self.flask})
        self.context.start()
        self.addCleanup(self.context.stop)

    def test_admin_read_and_save_have_no_host_apply_and_use_staged_guard(self):
        read = self.plugin.fpm_policy_get({"php_version":"85"})
        self.assertTrue(read["status"], read)
        self.assertFalse(read["saved"])
        self.assertRegex(read["operation_id"], r"^[a-f0-9]{32}$")
        with patch.object(policy, "save_policy", return_value={
            "schema":1, "state":"Policy Saved", "policy_revision":1,
            "version":"85", "scope":"shared_service", "auto_enforce":False,
            "runtime_verified":False,
        }) as saved:
            response = self.plugin.fpm_policy_save({
                "php_version":"85",
                "max_children":"20", "start_servers":"5",
                "min_spare_servers":"5", "max_spare_servers":"10",
                "max_requests":"300", "expected_policy_revision":0,
                "expected_monitor_revision":0,
                "expected_observation_sha256":"b"*64, "reviewed":"true",
            })
            self.assertTrue(response["status"], response)
            args, kwargs = saved.call_args
            self.assertEqual(args[:2], ("/www/server/php", "85"))
            self.assertEqual(args[2], {k: str(v) for k,v in VALUES.items()})
            self.assertEqual(kwargs["directory"], self.store.name)
            self.assertEqual(kwargs["expected_observation_sha256"], "b"*64)
            self.assertTrue(response["auto_enforce"] is False)

    def _save_fixture_policy(self, version="85", revision=1):
        content = {"schema":1, "revision":revision, "profiles":{version: dict(VALUES)}}
        path = Path(self.store.name)/policy.POLICY_FILE
        path.write_text(json.dumps(content))
        path.chmod(0o600)

    def _recheck_file(self, state_value="File Drift", impact=None):
        if impact is None:
            impact = {
                "schema":1, "state":"File Mapping", "scope":"shared_service",
                "version":"85", "matched_sites":[{"id":3,"site_key":"wordpress.test"}],
                "unresolved_sites":[], "site_count":1, "other_php_sites_count":0,
                "dependency_sha256":"d"*64, "manual_apply_eligible":True,
                "reason":"", "note":"Native file-only scope",
            }
        changes = ([{"setting":"pm.max_children","desired":20,"actual":80}]
                   if state_value == "File Drift" else [])
        return {
            "status":True, "state":state_value, "version":"85", "scope":"shared_service",
            "changes":changes, "source":"/www/server/php/85/etc/php-fpm.conf",
            "fpm_observation_sha256":"f"*64, "fpm_saved_policy":
                policy.get_policy("85",directory=self.store.name),
            "shared_impact":impact, "note":"File/default preview only"
        }

    def test_recheck_no_policy_has_no_source_or_runtime_actions(self):
        with patch.object(self.plugin, "preview_php_fpm") as preview:
            value = self.plugin.fpm_policy_recheck({"php_version":"85",
                                                   "max_children":"999999"})
        self.assertTrue(value["status"], value)
        self.assertEqual(value["state"],"No Policy")
        self.assertFalse(value["saved"])
        self.assertEqual(value["changes"],[])
        self.assertFalse(value["auto_enforce"])
        self.assertFalse(value["runtime_verified"])
        self.assertFalse(value["apply_eligible"])
        preview.assert_not_called()

    def test_recheck_uses_saved_values_not_untrusted_browser_desired(self):
        self._save_fixture_policy()
        with patch.object(self.plugin, "preview_php_fpm",
                          return_value=self._recheck_file()) as preview:
            value=self.plugin.fpm_policy_recheck({
                "php_version":"85", "max_children":"999999",
                "start_servers":"999999", "approved_scope":"fake"
            })
        self.assertTrue(value["status"],value)
        self.assertEqual(value["state"],"File Drift")
        self.assertEqual(value["changes"][0]["actual"],80)
        self.assertEqual(value["desired"],VALUES)
        self.assertEqual(value["shared_impact"]["matched_sites"][0]["id"],3)
        self.assertFalse(value["auto_enforce"])
        self.assertFalse(value["apply_eligible"])
        self.assertFalse(value["runtime_verified"])
        assert_args=preview.call_args.args[0]
        self.assertEqual(assert_args["php_version"],"85")
        self.assertEqual(set(assert_args),
                         {"php_version","max_children","start_servers",
                          "min_spare_servers","max_spare_servers","max_requests"})
        self.assertEqual(assert_args["max_children"],20)
        self.assertEqual(assert_args["max_requests"],300)

    def test_recheck_match_is_distinct_from_effective_php_runtime_verification(self):
        self._save_fixture_policy()
        with patch.object(self.plugin, "preview_php_fpm",
                          return_value=self._recheck_file("File Match")):
            result=self.plugin.fpm_policy_recheck({"php_version":"85"})
        self.assertEqual(result["state"],"File Match")
        self.assertEqual(result["changes"],[])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["apply_eligible"])

    def test_recheck_invalid_source_and_midflight_policy_revision_do_not_infer_sites(self):
        self._save_fixture_policy()
        before=policy.get_policy("85",directory=self.store.name)
        after=dict(before,policy_revision=before["policy_revision"]+1)
        inspected = self._recheck_file()
        with patch.object(policy, "get_policy", side_effect=[before,after]), patch.object(
                self.plugin, "preview_php_fpm",
                return_value={**inspected, "fpm_saved_policy":before}) as preview:
            result=self.plugin.fpm_policy_recheck({"php_version":"85"})
        self.assertTrue(result["status"])
        self.assertEqual(result["state"],"Needs Review")
        self.assertIsNone(result["shared_impact"])
        self.assertEqual(result["changes"],[])
        preview.assert_called_once()
        with patch.object(self.plugin,"preview_php_fpm",return_value={
            **self._recheck_file(), "state":"Needs Review",
            "fpm_observation_sha256":None, "reason":"Untrusted pool source"
        }):
            fail=self.plugin.fpm_policy_recheck({"php_version":"85"})
        self.assertEqual(fail["state"],"Needs Review")
        self.assertIn("Untrusted",fail["reason"])
        self.assertIsNone(fail["shared_impact"])

    def test_recheck_unsupported_or_failed_preview_returns_actionable_stage(self):
        self._save_fixture_policy()
        with patch.object(self.plugin, "preview_php_fpm",return_value={
            "status":False,"stage":"php_fpm_file_preview", "msg":"Cannot read source"
        }):
            fail=self.plugin.fpm_policy_recheck({"php_version":"85"})
        self.assertFalse(fail["status"])
        self.assertEqual(fail["stage"],"fpm_policy_recheck")
        self.assertRegex(fail["operation_id"],r"^[a-f0-9]{32}$")
        for version in ("74","85/../bad"):
            invalid=self.plugin.fpm_policy_recheck({"php_version":version})
            self.assertFalse(invalid["status"])
            self.assertEqual(invalid["stage"],"fpm_policy_recheck")

    def test_corrupt_saved_policy_does_not_hide_file_preview(self):
        payload = {"php_version":"85", "max_children":"20", "start_servers":"5",
                   "min_spare_servers":"5", "max_spare_servers":"10",
                   "max_requests":"300"}
        preview = {"state":"File Drift", "scope":"shared_service", "version":"85",
                   "source":"/www/server/php/85/etc/php-fpm.conf",
                   "changes":[{"setting":"pm.max_children","actual":80,"desired":20}]}
        path = Path(self.store.name) / policy.POLICY_FILE
        path.write_text("UNTRUSTED")  # Deliberately malformed but owned test-only store.
        path.chmod(0o600)
        with patch.object(policy, "observe", return_value=(preview,"c"*64)), \
                patch.object(entrypoint,"inspect_php_fpm_site_impact",
                             return_value={"state":"Needs Review","schema":1,
                                           "scope":"shared_service","version":"85"}) as impact, \
                patch.dict(sys.modules,{"public":types.ModuleType("public")}):
            result=self.plugin.preview_php_fpm(payload)
        self.assertTrue(result["status"], result)
        self.assertEqual(result["state"],"File Drift")
        self.assertIsNone(result["fpm_saved_policy"])
        self.assertEqual(result["stage"],"fpm_policy_observation")
        self.assertIn("Operation ID",result["fpm_policy_reason"])
        self.assertEqual(result["changes"],preview["changes"])
        impact.assert_called_once()

    def test_full_admin_post_required_for_read_and_save(self):
        for actor, method, context in (
            ({"login":True,"uid":2},"POST",True),
            ({"login":True,"uid":1,"tmp_login":True},"POST",True),
            ({"login":True,"uid":1},"GET",True),
            ({"login":True,"uid":1},"POST",False),
        ):
            with self.subTest(actor=actor, method=method, context=context):
                self.flask.session = actor
                self.flask.request.method = method
                self.flask.has_request_context = lambda:context
                for name in ("fpm_policy_get", "fpm_policy_save", "fpm_policy_recheck"):
                    response = getattr(self.plugin, name)({"php_version":"85"})
                    self.assertFalse(response["status"])
                    self.assertEqual(response["stage"], "fpm_policy_authorization")
        self.assertFalse((Path(self.store.name)/policy.POLICY_FILE).exists())
