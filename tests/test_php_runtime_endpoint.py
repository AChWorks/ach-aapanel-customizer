"""aaPanel PHP process-inspection endpoint authorization and operation evidence."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_main as backend
import ach_customizer_php_runtime as runtime
import ach_customizer_php_topology as topology


class NativePhpRuntimeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-runtime-endpoint-")
        self.addCleanup(self.tmp.cleanup)
        self.plugin = backend.ach_customizer_main()
        state = patch.object(backend, "_STATE_DIR", self.tmp.name)
        state.start()
        self.addCleanup(state.stop)

    @staticmethod
    def session(*, uid=1, method="POST", temp=False, context=True):
        flask = types.ModuleType("flask")
        flask.has_request_context = lambda: context
        flask.request = types.SimpleNamespace(method=method)
        flask.session = {"login": True, "uid": uid}
        if temp:
            flask.session["tmp_login_id"] = "temporary"
        return flask

    @staticmethod
    def observed():
        return {
            "schema": 1, "state": "Observed", "version": "81",
            "read_only": True, "runtime_verified": False, "apply_eligible": False,
            "master_state": "Matching Master", "socket_state": "Bound Listener",
            "master_pid": 432, "socket_path": "/tmp/php-cgi-81.sock",
            "reason": "", "note": runtime.NOTE,
        }

    def test_native_primary_admin_uses_fixed_root_and_no_client_paths(self):
        with patch.dict(sys.modules, {"flask": self.session()}), \
             patch.object(runtime, "inspect_php_fpm_runtime",
                          return_value=self.observed()) as probe:
            result = self.plugin.inspect_php_runtime({
                "php_version": "81", "root": "/etc",
                "proc_root": "/outside", "path": "/etc/shadow"})
        self.assertTrue(result["status"], result)
        self.assertEqual(result["master_pid"], 432)
        self.assertFalse(result["apply_eligible"])
        self.assertFalse(result["runtime_verified"])
        self.assertRegex(result["operation_id"], r"^[0-9a-f]{32}$")
        probe.assert_called_once_with("/www/server/php", "81")

    def test_runtime_and_site_file_map_are_independent_and_never_authorize_apply(self):
        expected = {
            "schema": 1, "state": "File Mapping", "version": "81",
            "scope": "shared_service", "read_only": True,
            "runtime_verified": False, "apply_eligible": False,
            "pool": "www", "config_path": "/www/server/php/81/etc/php-fpm.conf",
            "socket_path": "/tmp/php-cgi-81.sock", "site_count": 2,
            "matched_sites": [{"id": 3, "site_key": "one.test"}],
            "other_sites": [{"id": 4, "site_key": "two.test",
                             "version": "85", "socket_path": "/tmp/php-cgi-85.sock"}],
            "unresolved_sites": [], "source_sha256": "a" * 64,
            "reason": "", "note": topology.NOTE,
        }
        with patch.dict(sys.modules, {
                "flask": self.session(), "public": types.ModuleType("public")
        }), patch.object(runtime, "inspect_php_fpm_runtime",
                         return_value=self.observed()) as proc, \
             patch.object(topology, "inspect_php_fpm_site_topology",
                          return_value=expected) as files:
            result = self.plugin.inspect_php_runtime({
                "php_version": "81", "vhost_root": "/bad",
                "socket_path": "/tmp/attacker.sock", "site_id": "987"})
        self.assertTrue(result["status"], result)
        self.assertEqual(result["site_mapping"], expected)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["apply_eligible"])
        self.assertFalse(result["site_mapping"]["apply_eligible"])
        proc.assert_called_once_with("/www/server/php", "81")
        self.assertEqual(files.call_args.args[1:], ("/www/server/php", "81"))
        self.assertEqual(files.call_args.kwargs,
                         {"observed_runtime_socket": "/tmp/php-cgi-81.sock"})

    def test_process_missing_still_allows_read_only_file_map_without_runtime_claim(self):
        partial = self.observed()
        partial.update(state="Partial", socket_state="Not Observed",
                       reason="Socket listener not observed")
        with patch.dict(sys.modules, {
                "flask": self.session(), "public": types.ModuleType("public")
        }), patch.object(runtime, "inspect_php_fpm_runtime",
                         return_value=partial), \
             patch.object(topology, "inspect_php_fpm_site_topology") as mapper:
            mapper.return_value = {
                "state": "Partial", "read_only": True, "apply_eligible": False
            }
            result = self.plugin.inspect_php_runtime({"php_version": "81"})
        self.assertTrue(result["status"])
        self.assertEqual(result["state"], "Partial")
        self.assertIsNone(mapper.call_args.kwargs["observed_runtime_socket"])

    def test_secondary_temporary_get_and_missing_context_denied_before_scan(self):
        for context in (self.session(uid=2), self.session(method="GET"),
                        self.session(temp=True), self.session(context=False)):
            with self.subTest(context=context.session), \
                 patch.dict(sys.modules, {"flask": context}), \
                 patch.object(runtime, "inspect_php_fpm_runtime",
                              side_effect=AssertionError("unauthorized")) as reader:
                response = self.plugin.inspect_php_runtime({"php_version": "81"})
            self.assertFalse(response["status"])
            self.assertEqual(response["stage"], "php_runtime_authorization")
            reader.assert_not_called()

    def test_bounded_diagnostic_error_has_actionable_stage_and_operation(self):
        with patch.dict(sys.modules, {"flask": self.session()}), \
             patch.object(runtime, "inspect_php_fpm_runtime",
                          side_effect=runtime.RuntimeInspectError(
                              "PHP procfs process count exceeds safe read limit")):
            response = self.plugin.inspect_php_runtime({"php_version": "81"})
        self.assertFalse(response["status"])
        self.assertEqual(response["stage"], "php_runtime_inspection")
        self.assertIn("exceeds safe read limit", response["msg"])
        self.assertRegex(response["operation_id"], r"^[a-f0-9]{32}$")
        from ach_customizer_activity import read_activity
        entries = read_activity(self.tmp.name, module="php_fpm", limit=10)
        self.assertTrue(any(
            row["stage"] == "php_runtime_inspection" and
            row["module"] == "php_fpm" and row["level"] == "ERROR"
            for row in entries
        ), "PHP runtime failures belong to the PHP-FPM diagnostics module")

    def test_new_helper_missing_does_not_break_existing_endpoints(self):
        with patch.dict(sys.modules, {"flask": self.session(),
                                       "ach_customizer_php_runtime": None}):
            response = self.plugin.inspect_php_runtime({"php_version": "81"})
        self.assertFalse(response["status"])
        self.assertIn("restart aaPanel", response["msg"])
        preview = self.plugin.status_preview({
            "site_id": "", "template": "404", "locale": "en"
        })
        self.assertTrue(preview["status"])


if __name__ == "__main__":
    unittest.main()
