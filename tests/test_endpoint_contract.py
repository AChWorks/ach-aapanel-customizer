"""Exercise the actual aaPanel-style entrypoint as a class, not only its helpers."""

import importlib.util
import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parent.parent / 'plugin' / 'ach_customizer'
SPEC = importlib.util.spec_from_file_location('ach_customizer_main', PLUGIN_DIR / 'ach_customizer_main.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MemorySiteQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.count = 0

    def order(self, key):
        assert key == 'id asc'
        return self

    def limit(self, expression):
        self.start, self.count = map(int, expression.split(','))
        return self

    def field(self, projection):
        assert projection == 'id,name,path,status'
        return self

    def select(self):
        return self.rows[self.start:self.start + self.count]


class MemoryDomainQuery:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.pids = ()

    def where(self, clause, values):
        assert clause == 'pid IN (' + ','.join('?' for _ in values) + ')'
        self.pids = values
        return self

    def order(self, key):
        assert key == 'pid asc, id asc'
        return self

    def limit(self, expression):
        assert expression == '0,257'
        return self

    def field(self, projection):
        assert projection == 'id,pid,name,port'
        return self

    def select(self):
        return [row for row in self.rows if row['pid'] in self.pids]


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.plugin = MODULE.ach_customizer_main()
        self.state_dir = tempfile.TemporaryDirectory(prefix="ach-endpoint-state-")
        self.addCleanup(self.state_dir.cleanup)
        state_path = patch.object(MODULE, "_STATE_DIR", self.state_dir.name)
        state_path.start()
        self.addCleanup(state_path.stop)

    def test_resident_overview_version_is_worker_loaded_not_new_manifest(self):
        # Patching the import-time version emulates an old panel worker with
        # new ZIP bytes already installed. The returned version must remain old.
        with patch.object(MODULE, 'WORKER_SOURCE_VERSION', '0.1.40'):
            response = self.plugin.get_overview({})
        self.assertTrue(response['status'], response)
        self.assertEqual(response['worker_source_version'], '0.1.40')
        self.assertNotIn('restart', response)
        self.assertFalse(response['enforcement'])

    def test_manual_fpm_methods_dispatch_once_and_preserve_durable_recovery_id(self):
        class Controller:
            calls = []
            def prepare(self, args):
                self.calls.append(("prepare", args))
                return {"plan":{"before_sha256":"a"*64}, "monitor_revision":4}
            def apply(self, args):
                self.calls.append(("apply", args))
                return {"state":"Applied", "operation_id":"b"*32}
            def recovery(self, args):
                self.calls.append(("recovery", args))
                return {"state":"Applied", "operation_id":"b"*32}
            def rollback(self, args):
                self.calls.append(("rollback", args))
                return {"state":"Rolled Back", "operation_id":"b"*32}
        controller = Controller()
        with patch.object(MODULE, "ManualFpmWorkflow", return_value=controller):
            for route, kind in (("fpm_prepare","prepare"), ("fpm_apply","apply"),
                                ("fpm_recovery","recovery"), ("fpm_rollback","rollback")):
                args = {"php_version":"85", "token":kind}
                result = getattr(self.plugin, route)(args)
                self.assertTrue(result["status"], result)
                self.assertRegex(result["request_id"], r"^[0-9a-f]{32}$")
                self.assertEqual(controller.calls[-1], (kind, args))
                if kind != "prepare":
                    self.assertEqual(result["operation_id"], "b"*32)
            self.assertEqual(len(controller.calls), 4)

    def test_native_audit_uses_bounded_structured_log_and_reports_outcome(self):
        from unittest.mock import Mock
        fake_public=types.ModuleType("public")
        fake_public.WriteLog=Mock(return_value=19)
        with patch.dict(sys.modules,{"public":fake_public}), patch.object(
                MODULE,"ManualFpmWorkflow") as factory:
            factory.return_value.apply.return_value={
                "state":"Applied","operation_id":"e"*32}
            applied=self.plugin.fpm_apply({"php_version":"85","secret":"do not log"})
            self.assertTrue(applied["status"])
            self.assertTrue(applied["audit_logged"])
            self.assertNotIn("audit_warning",applied)
            fake_public.WriteLog.assert_called_once()
            args,kwargs=fake_public.WriteLog.call_args
            self.assertEqual(args[0],"ACh Customizer")
            self.assertTrue(kwargs["not_web"])
            import json
            record=json.loads(args[1])
            self.assertEqual(record["action"],"fpm_apply")
            self.assertEqual(record["recovery_operation_id"],"e"*32)
            self.assertEqual(record["request_id"],applied["request_id"])
            self.assertNotIn("do not log",args[1])
            self.assertIn("timestamp_utc",record)
            fake_public.WriteLog.return_value=None
            failed_log=self.plugin.fpm_apply({})
            self.assertTrue(failed_log["status"],"Log failure must not hide an already applied operation")
            self.assertFalse(failed_log["audit_logged"])
            self.assertIn("audit_warning",failed_log)

    def test_status_site_choices_are_monitor_independent_but_primary_admin_only(self):
        """Branding selector works with monitoring OFF without relaxing get_sites."""
        import ach_customizer_state as state
        from unittest.mock import Mock
        state.set_enabled("overall", False, directory=self.state_dir.name,
                          expected_revision=0)
        native_state = (Path(self.state_dir.name) / state.STATE_FILE).read_bytes()
        fake_public = types.ModuleType("public")
        fake_flask = types.ModuleType("flask")
        fake_flask.session = {"login": True, "uid": 1}
        fake_flask.request = types.SimpleNamespace(method="POST")
        fake_flask.has_request_context = lambda: True
        payload = {"inventory_schema": 2, "page": 1, "page_size": 25,
                   "has_more": False, "sites": []}
        with patch.dict(sys.modules, {"public": fake_public, "flask": fake_flask}), patch.object(
                MODULE, "get_site_page", return_value=payload) as discovery:
            response = self.plugin.status_sites({"page": "1", "page_size": "25"})
            self.assertTrue(response["status"], response)
            self.assertEqual(response["purpose"], "status_site_selection")
            self.assertEqual(response["inventory_schema"], 2)
            discovery.assert_called_once_with(fake_public, "1", "25")
            self.assertFalse(self.plugin.get_sites({})["status"],
                             "Monitor website inventory should remain disabled")
            for session, method, context in (
                ({"login": True, "uid": 2}, "POST", True),
                ({"login": True, "uid": 1, "tmp_login_id": ""}, "POST", True),
                ({"login": True, "uid": 1, "tmp_login": True}, "POST", True),
                ({"login": True, "uid": 1}, "GET", True),
                ({"login": True, "uid": 1}, "POST", False),
            ):
                with self.subTest(session=session, method=method, context=context):
                    fake_flask.session = session
                    fake_flask.request.method = method
                    fake_flask.has_request_context = lambda: context
                    denied = self.plugin.status_sites({"page": "1"})
                    self.assertFalse(denied["status"])
                    self.assertEqual(denied["stage"], "status_sites_authorization")
            discovery.assert_called_once()
        self.assertEqual((Path(self.state_dir.name) / state.STATE_FILE).read_bytes(),
                         native_state, "Selection must not mutate Monitor settings")

    def test_status_site_choices_reject_invalid_native_page_instead_of_fabricating_sites(self):
        from ach_customizer_monitor import MonitorInputError
        fake_public = types.ModuleType("public")
        fake_flask = types.ModuleType("flask")
        fake_flask.session = {"login": True, "uid": 1}
        fake_flask.request = types.SimpleNamespace(method="POST")
        fake_flask.has_request_context = lambda: True
        with patch.dict(sys.modules, {"public": fake_public, "flask": fake_flask}), patch.object(
                MODULE, "get_site_page",
                side_effect=MonitorInputError("Invalid inventory page")):
            denied = self.plugin.status_sites({"page": "-4"})
        self.assertFalse(denied["status"])
        self.assertEqual(denied["stage"], "status_sites_read")
        self.assertNotIn("sites", denied)

    def test_manual_fpm_errors_fail_closed_and_report_stage(self):
        from ach_customizer_fpm_apply import FpmApplyError
        with patch.object(MODULE, "ManualFpmWorkflow") as factory:
            factory.return_value.apply.side_effect = FpmApplyError(
                "fpm_authorization", "Full primary aaPanel administrator POST is required")
            refused = self.plugin.fpm_apply({"approved_scope":"PHP85-www-shared-service"})
            self.assertFalse(refused["status"])
            self.assertEqual(refused["stage"], "fpm_authorization")
            self.assertIn("administrator", refused["msg"])
            factory.return_value.rollback.side_effect = RuntimeError("confidential internal stack")
            unknown = self.plugin.fpm_rollback({})
            self.assertFalse(unknown["status"])
            self.assertEqual(unknown["stage"], "fpm_rollback")
            self.assertNotIn("confidential", str(unknown))

    def test_nginx_guard_endpoint_does_not_expose_unauthorized_work(self):
        from unittest.mock import Mock
        guard = __import__("ach_customizer_nginx_security")
        fake_public = types.ModuleType("public")
        fake_public.get_webserver = lambda: "nginx"
        fake_public.get_panel_version = lambda: "8.0.7"
        flask_stub = types.ModuleType("flask")
        flask_stub.session = {"uid": 1, "login": True}
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        site = {"id": 9, "name": "alternate.invalid",
                "path": "/www/acdomains/alternate.invalid", "status": 1,
                "bound_domains": [{"name": "alternate.invalid", "port": 80}]}
        response = {"schema": 1, "site_id": 9, "site_key": site["name"],
                    "site_root": site["path"], "mode": "native_site_sensitive_paths",
                    "ruleset": "nested-sensitive-v2", "state": "Unmanaged",
                    "reason": "Native source checked", "read_only": True,
                    "changed": False, "runtime_verified": False,
                    "vhost_sha256": "a" * 64, "proposal_sha256": "b" * 64,
                    "recovery_id": None, "journal_phase": None,
                    "automatic_enforcement": False}
        with patch.dict(sys.modules, {"flask": flask_stub, "public": fake_public}), patch.object(
                self.plugin, "_selected_native_website", return_value=(
                    fake_public, site, lambda: site)) as selected, patch.object(
                guard, "manage_guard", return_value=response) as execute:
            for label, auth, method, context in (
                ("secondary", {"uid": 2, "login": True}, "POST", True),
                ("anonymous", {"uid": 1, "login": False}, "POST", True),
                ("temporary", {"uid": 1, "login": True, "tmp_login": True}, "POST", True),
                ("get", {"uid": 1, "login": True}, "GET", True),
                ("no-context", {"uid": 1, "login": True}, "POST", False),
            ):
                with self.subTest(label=label):
                    flask_stub.session = auth
                    flask_stub.request.method = method
                    flask_stub.has_request_context = lambda: context
                    denied = self.plugin.manage_nginx_protection(
                        {"guard_action": "apply", "approved": "true"})
                    self.assertFalse(denied["status"], denied)
                    self.assertEqual(denied["stage"], "nginx_guard_authorization")
                    selected.assert_not_called()
                    execute.assert_not_called()
            flask_stub.session = {"uid": 1, "login": True}
            flask_stub.request.method = "POST"
            flask_stub.has_request_context = lambda: True
            result = self.plugin.manage_nginx_protection({"guard_action": "preview"})
            self.assertTrue(result["status"], result)
            self.assertEqual(result["state"], "Unmanaged")
            self.assertTrue(result["read_only"])
            self.assertEqual(result["site_root"], site["path"])
            selected.assert_called_once()
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[:2], ("preview", site))
            self.assertFalse(execute.call_args.kwargs["approved"])

    def test_nginx_guard_failure_activity_uses_verified_target_and_typed_phase(self):
        from ach_customizer_activity import read_activity
        from ach_customizer_monitor import MonitorInputError
        from ach_customizer_nginx_security import GuardError, ExtensionError

        site = {"id": 9, "name": "paths85.aitest.gotohell.top",
                "path": "/www/acdomains/paths85.aitest.gotohell.top",
                "status": 1, "bound_domains": [
                    {"name": "paths85.aitest.gotohell.top", "port": 80}]}
        fake_public = types.ModuleType("public")
        fake_public.get_webserver = lambda: "nginx"
        fake_public.get_panel_version = lambda: "8.0.7"

        class SingleRoot:
            def where(self, *args):
                return self
            def field(self, *args):
                return self
            def limit(self, *args):
                return self
            def select(self):
                return [{"id": site["id"], "path": site["path"]}]

        fake_public.M = lambda name: SingleRoot()
        flask_stub = types.ModuleType("flask")
        flask_stub.session = {"uid": 1, "login": True}
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        import ach_customizer_nginx_security as manager

        with patch.dict(sys.modules, {"public": fake_public, "flask": flask_stub}), patch.object(
                self.plugin, "_selected_native_website",
                return_value=(fake_public, site, lambda: site)) as selected, patch.object(
                manager, "manage_guard") as managed:
            def assert_failure(action, error, target, phase, recovery=""):
                managed.side_effect = error
                response = self.plugin.manage_nginx_protection(
                    {"site_id": "999", "guard_action": action, "approved": "true"})
                self.assertFalse(response["status"], response)
                self.assertEqual(response["stage"], "nginx_guard_manage")
                self.assertRegex(response["operation_id"], r"^[0-9a-f]{32}$")
                self.assertEqual(response.get("recovery_id", ""), recovery)
                self.assertEqual(response.get("request_id", response["operation_id"]),
                                 response["operation_id"])
                activity = read_activity(self.state_dir.name, module="websites")[0]
                self.assertEqual(activity["action"], "nginx_guard_manage")
                self.assertEqual(activity["stage"], phase)
                self.assertEqual(activity["target"], target)
                self.assertEqual(activity["operation_id"], response["operation_id"])
                self.assertEqual(activity["recovery_id"], recovery)
                self.assertEqual(activity["outcome"], "failed")
                return response, activity

            # Before primary-admin authentication, even a supplied site ID
            # must not become a trusted attribution target.
            flask_stub.request.method = "GET"
            denied = self.plugin.manage_nginx_protection(
                {"site_id": "9", "guard_action": "apply"})
            self.assertEqual(denied["stage"], "nginx_guard_authorization")
            self.assertEqual(read_activity(self.state_dir.name)[0]["target"], "")
            selected.assert_not_called()
            managed.assert_not_called()
            flask_stub.request.method = "POST"

            # The identity lookup must complete before attribution is valid.
            selected.side_effect = MonitorInputError("Native site identity changed")
            early = self.plugin.manage_nginx_protection(
                {"site_id": "9", "guard_action": "preview"})
            self.assertEqual(early["stage"], "nginx_guard_manage")
            self.assertEqual(read_activity(self.state_dir.name)[0]["target"], "")
            selected.side_effect = None
            selected.return_value = (fake_public, site, lambda: site)

            assert_failure("preview",
                           GuardError("source", "Native selected VHost is absent"),
                           "9", "nginx_guard_source")
            # Shared Nginx helpers raise their own ExtensionError class.
            # These failures have typed stages but no owned recovery ID.
            for stage in ("source", "ownership", "concurrency"):
                assert_failure("preview",
                               ExtensionError(stage, "Native source cannot be trusted"),
                               "9", "nginx_guard_" + stage)
            assert_failure("apply",
                           ExtensionError("uncertain", "Raw helper exception",
                                          recovery_id="f" * 32),
                           "9", "nginx_guard_uncertain")
            for action in ("apply", "restore"):
                response, activity = assert_failure(
                    action, GuardError("uncertain",
                                       "Nginx security operation requires Recheck",
                                       recovery_id="d" * 32),
                    "9", "nginx_guard_uncertain", "d" * 32)
                self.assertEqual(activity["error_class"], "GuardError")
                self.assertNotEqual(response["operation_id"], response["recovery_id"])

            for action in ("preview", "recheck", "apply", "restore"):
                response, activity = assert_failure(
                    action, GuardError("unsupported_ruleset",
                                       "Unsupported native security recovery ruleset. "
                                       "Saved journal preserved; administrator investigation required.",
                                       recovery_id="d" * 32),
                    "9", "nginx_guard_unsupported_ruleset")
                self.assertEqual(response.get("reason_code"), "unsupported_guard_ruleset")
                self.assertIn("administrator investigation", response["msg"])
                self.assertNotIn("recovery_id", response)
                self.assertEqual(activity["recovery_id"], "")
                self.assertIn("administrator investigation", activity["detail"])
            # The generic helper or an arbitrary exception cannot advertise
            # this typed Guard-only diagnosis.
            response, _ = assert_failure("preview",
                                          ExtensionError("unsupported_ruleset", "Other helper"),
                                          "9", "nginx_guard_unsupported_ruleset")
            self.assertNotIn("reason_code", response)

            class Unexpected(RuntimeError):
                recovery_id = "e" * 32
                stage = "unsupported_ruleset"

            response, activity = assert_failure(
                "recheck", Unexpected("PRIVATE INTERNAL ERROR"),
                "9", "nginx_guard_manage")
            self.assertNotIn("PRIVATE", str(response))
            self.assertNotIn("PRIVATE", str(activity))
            self.assertEqual(activity["error_class"], "Unexpected")
            self.assertNotIn("reason_code", response)

    def test_nginx_guard_real_publisher_failure_retains_endpoint_recovery(self):
        # Exercise the actual shared publisher through the native endpoint,
        # not merely a mocked GuardError injected at the endpoint boundary.
        import json
        import ach_customizer_nginx_security as manager
        import ach_customizer_status_extension as publisher
        from ach_customizer_activity import read_activity

        with tempfile.TemporaryDirectory(prefix="ach-native-guard-endpoint-") as tmp:
            root = Path(tmp)
            vhosts = root / "nginx"
            ext = vhosts / "extension" / "endpoint.invalid"
            ext.mkdir(parents=True)
            document_root = root / "websites" / "endpoint.invalid"
            document_root.mkdir(parents=True)
            site = {
                "id": 9, "name": "endpoint.invalid",
                "path": str(document_root), "status": "1",
                "bound_domains": [{"name": "endpoint.invalid", "port": 80}],
            }
            (vhosts / "endpoint.invalid.conf").write_text(
                "server {\nlisten 80;\nserver_name endpoint.invalid;\n"
                "root " + str(document_root) + ";\n"
                "error_page 404 /404.html;\nerror_page 502 /502.html;\n"
                "include " + str(ext) + "/*.conf;\n"
                "include enable-php-85.conf;\n}\n")
            conf = root / "nginx.conf"
            conf.write_text(
                "events {worker_connections 100;}\n"
                "http {include " + str(vhosts) + "/*.conf;}\n")

            fake_public = types.ModuleType("public")
            fake_public.get_webserver = lambda: "nginx"
            fake_public.get_panel_version = lambda: "8.0.7"

            class OneSite:
                def where(self, *args):
                    return self
                def field(self, *args):
                    return self
                def limit(self, *args):
                    return self
                def select(self):
                    return [{"id": 9, "path": str(document_root)}]

            fake_public.M = lambda _: OneSite()
            flask_stub = types.ModuleType("flask")
            flask_stub.session = {"uid": 1, "login": True}
            flask_stub.request = types.SimpleNamespace(method="POST")
            flask_stub.has_request_context = lambda: True

            original_manage = manager.manage_guard
            original_rename = publisher._rename_noreplace

            def adapted_manage(action, selected, **kwargs):
                return original_manage(
                    action, selected, **kwargs,
                    vhost_root=str(vhosts), nginx_conf=str(conf),
                    nginx="/test/nginx",
                    runner=lambda *args, **kw: types.SimpleNamespace(
                        returncode=0, stderr=b""),
                    probe=lambda *args: (404, None))

            def renamed_but_unconfirmed(fd, before, after):
                original_rename(fd, before, after)
                raise OSError(5, "simulated uncertain extension sync")

            with patch.dict(sys.modules, {"public": fake_public, "flask": flask_stub}), patch.object(
                    self.plugin, "_selected_native_website", return_value=(
                        fake_public, site, lambda: site)), patch.object(
                    manager, "manage_guard", side_effect=adapted_manage):
                preview = self.plugin.manage_nginx_protection(
                    {"guard_action": "preview"})
                self.assertTrue(preview["status"], preview)
                with patch.object(publisher, "_rename_noreplace",
                                  side_effect=renamed_but_unconfirmed):
                    response = self.plugin.manage_nginx_protection({
                        "guard_action": "apply", "approved": "true",
                        "expected_vhost_sha256": preview["vhost_sha256"],
                        "expected_proposal_sha256": preview["proposal_sha256"],
                    })

                self.assertFalse(response["status"], response)
                self.assertEqual(response["stage"], "nginx_guard_manage")
                recovery = response.get("recovery_id")
                self.assertRegex(recovery or "", r"^[0-9a-f]{32}$")
                self.assertNotEqual(response["operation_id"], recovery)
                self.assertEqual(response["request_id"], response["operation_id"])
                activity = read_activity(self.state_dir.name, module="websites")[0]
                self.assertEqual(activity["target"], "9")
                self.assertEqual(activity["stage"], "nginx_guard_uncertain")
                self.assertEqual(activity["error_class"], "GuardError")
                self.assertEqual(activity["operation_id"], response["operation_id"])
                self.assertEqual(activity["recovery_id"], recovery)

                saved = json.loads(
                    (Path(self.state_dir.name) / manager._journal(9)).read_text())
                self.assertEqual(saved["phase"], "prepared")
                self.assertEqual(saved["op"], recovery)
                fragment = ext / manager._file(9)
                self.assertEqual(fragment.read_bytes(), manager._include(recovery))
                observed = self.plugin.manage_nginx_protection(
                    {"guard_action": "recheck"})
                self.assertTrue(observed["status"], observed)
                self.assertEqual(observed["state"], "Recovery Required")
                # Direct endpoint callers cannot bypass the reviewed
                # source precondition with only a valid Recovery ID.
                for stale_sha in (None, "f" * 64):
                    rejected = self.plugin.manage_nginx_protection({
                        "guard_action": "restore", "approved": "true",
                        "recovery_id": recovery,
                        **({"expected_vhost_sha256": stale_sha}
                           if stale_sha is not None else {}),
                    })
                    self.assertFalse(rejected["status"], rejected)
                    self.assertTrue(fragment.exists())
                restored = self.plugin.manage_nginx_protection({
                    "guard_action": "restore", "approved": "true",
                    "recovery_id": recovery,
                    "expected_vhost_sha256": observed["vhost_sha256"],
                })
                self.assertTrue(restored["status"], restored)
                self.assertEqual(restored["state"], "Restored")
                self.assertFalse(fragment.exists())

    def test_no_auth_bypassing_dynamic_check_or_mutation_entrypoint(self):
        self.assertNotIn('_check', vars(MODULE.ach_customizer_main))
        for name in vars(MODULE.ach_customizer_main):
            self.assertFalse(name.startswith(('apply_', 'reload_', 'restart_', 'update_')))
        response = self.plugin.get_overview({})
        self.assertTrue(response['status'])
        self.assertEqual(response['mode'], 'Monitor')
        self.assertIs(response['enforcement'], False)

    def test_primary_administrator_only_post_can_change_monitor_flags(self):
        flask_stub = types.ModuleType("flask")
        flask_stub.session = {"uid": 1, "login": True}
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        with patch.dict(sys.modules, {"flask": flask_stub}):
            response = self.plugin.set_control({"control": "overall", "enabled": "false", "expected_revision": "0"})
            self.assertTrue(response["status"], response)
            self.assertFalse(response["overall_enabled"])
            self.assertEqual(response["mode"], "Disabled")
            self.assertFalse(response["enforcement"])
            self.assertEqual(response["state_revision"], 1)
            self.assertTrue(response["changed"])
            self.assertEqual(self.plugin.get_overview({})["state_revision"], 1)
            duplicate = self.plugin.set_control({"control": "overall", "enabled": "false", "expected_revision": "1"})
            self.assertTrue(duplicate["status"])
            self.assertFalse(duplicate["changed"])
            self.assertEqual(duplicate["state_revision"], 1)
            flask_stub.session["uid"] = 2
            refused = self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})
            self.assertFalse(refused["status"])
            self.assertEqual(refused["stage"], "monitor_authorization")
            flask_stub.session["uid"] = 1
            flask_stub.request.method = "GET"
            refused = self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})
            self.assertEqual(refused["stage"], "monitor_authorization")
            flask_stub.request.method = "POST"
            flask_stub.session["login"] = False
            refused = self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})
            self.assertEqual(refused["stage"], "monitor_authorization")
            self.assertEqual(self.plugin.get_overview({})["state_revision"], 1)
            flask_stub.session["login"] = True
            flask_stub.has_request_context = lambda: False
            self.assertEqual(
                self.plugin.set_control({"control": "overall", "enabled": "true", "expected_revision": "1"})["stage"],
                "monitor_authorization",
            )


    def test_temporary_and_nonprimary_sessions_cannot_mutate_or_create_state(self):
        """Every rejected case must fail before entering the persistent writer."""
        import ach_customizer_state as state

        flask_stub = types.ModuleType("flask")
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        file = Path(self.state_dir.name) / state.STATE_FILE
        primary = {"login": True, "uid": 1}
        cases = (
            ("temporary_token_uid1", {**primary, "tmp_login": True}, "POST", True),
            ("temporary_truthy_marker", {**primary, "tmp_login": "yes"}, "POST", True),
            ("temporary_identity_id_empty", {**primary, "tmp_login_id": ""}, "POST", True),
            ("temporary_identity_id_zero", {**primary, "tmp_login_id": 0}, "POST", True),
            ("temporary_expiration_marker", {**primary, "tmp_login_expire": 0}, "POST", True),
            ("temporary_all_markers", {
                **primary, "tmp_login": True,
                "tmp_login_id": "18", "tmp_login_expire": 999999
            }, "POST", True),
            ("secondary_user", {"login": True, "uid": 2}, "POST", True),
            ("string_primary_id", {"login": True, "uid": "1"}, "POST", True),
            ("boolean_primary_id", {"login": True, "uid": True}, "POST", True),
            ("not_authenticated", {"login": False, "uid": 1}, "POST", True),
            ("get_instead_of_post", primary.copy(), "GET", True),
            ("no_flask_request_context", primary.copy(), "POST", False),
        )

        with patch.dict(sys.modules, {"flask": flask_stub}):
            for persisted in (False, True):
                if persisted:
                    state.set_enabled("overall", False,
                                      directory=self.state_dir.name,
                                      expected_revision=0)
                revision = 1 if persisted else 0
                original = file.read_bytes() if persisted else None
                for label, session, method, has_context in cases:
                    with self.subTest(persisted=persisted, case=label):
                        flask_stub.session = dict(session)
                        flask_stub.request.method = method
                        flask_stub.has_request_context = lambda: has_context
                        with patch.object(
                            MODULE, "set_enabled",
                            side_effect=AssertionError("Unauthorized state writer called"),
                        ) as writer:
                            response = self.plugin.set_control({
                                "control": "overall", "enabled": "true",
                                "expected_revision": str(revision),
                            })
                            writer.assert_not_called()
                        self.assertIs(response["status"], False)
                        self.assertEqual(response["stage"], "monitor_authorization")
                        self.assertTrue(response["operation_id"])
                        self.assertEqual(file.exists(), persisted)
                        if persisted:
                            self.assertEqual(file.read_bytes(), original)
                            self.assertEqual(state.read_state(self.state_dir.name)["revision"], revision)
                        else:
                            self.assertFalse(file.exists(), "Denied operation must not create Monitor state")
                            self.assertTrue(all(
                                child.name.startswith("ach_customizer.activity.")
                                for child in Path(self.state_dir.name).iterdir()))

    def test_optimistic_revision_rejection_through_authenticated_endpoint(self):
        flask_stub = types.ModuleType("flask")
        flask_stub.session = {"uid": 1, "login": True}
        flask_stub.request = types.SimpleNamespace(method="POST")
        flask_stub.has_request_context = lambda: True
        with patch.dict(sys.modules, {"flask": flask_stub}):
            first = self.plugin.set_control({
                "control": "overall", "enabled": "false", "expected_revision": "0"
            })
            self.assertTrue(first["status"], first)
            conflict = self.plugin.set_control({
                "control": "overall", "enabled": "true", "expected_revision": "0"
            })
            self.assertFalse(conflict["status"])
            self.assertEqual(conflict["stage"], "monitor_state_write")
            self.assertIn("revision changed", conflict["msg"])
            self.assertEqual(self.plugin.get_overview({})["state_revision"], 1)
            missing = self.plugin.set_control({
                "control": "overall", "enabled": "true"
            })
            self.assertFalse(missing["status"])
            self.assertIn("revision", missing["msg"])
            valid = self.plugin.set_control({
                "control": "overall", "enabled": "true", "expected_revision": "1"
            })
            self.assertTrue(valid["status"])
            self.assertEqual(valid["state_revision"], 2)

    def test_disabled_monitors_do_not_inspect_websites_or_shared_fpm(self):
        import ach_customizer_state as state

        state.set_enabled("site_inventory", False, directory=self.state_dir.name, expected_revision=0)
        with patch.object(MODULE, "get_site_page", side_effect=AssertionError("must not scan")) as sites_call:
            blocked = self.plugin.get_sites({})
            self.assertFalse(blocked["status"])
            self.assertIn("disabled", blocked["msg"])
            sites_call.assert_not_called()

        state.set_enabled("overall", False, directory=self.state_dir.name, expected_revision=1)
        with patch.object(MODULE, "preview_php_fpm", side_effect=AssertionError("must not inspect")) as fpm_call:
            blocked = self.plugin.preview_php_fpm({})
            self.assertFalse(blocked["status"])
            self.assertIn("disabled", blocked["msg"])
            fpm_call.assert_not_called()
        overview = self.plugin.get_overview({})
        self.assertFalse(overview["enforcement"])
        self.assertEqual(overview["modules"]["site_inventory"], "Disabled")
        self.assertEqual(overview["modules"]["php_fpm_file_preview"], "Disabled")

    def test_corrupted_monitor_state_is_visible_not_silently_reset(self):
        from pathlib import Path
        from ach_customizer_state import STATE_FILE
        file = Path(self.state_dir.name) / STATE_FILE
        file.write_text("{invalid")
        file.chmod(0o600)
        error = self.plugin.get_overview({})
        self.assertFalse(error["status"])
        self.assertEqual(error["stage"], "monitor_state_read")
        self.assertTrue(error["operation_id"])
        self.assertFalse(self.plugin.get_sites({})["status"])
        self.assertEqual(file.read_text(), "{invalid")

    def test_actual_entrypoint_can_query_sites_and_handles_error(self):
        query = MemorySiteQuery([
            {'id': 11, 'name': 'simple.test', 'path': '/test/simple', 'status': 1},
            {'id': 12, 'name': 'static.test', 'path': '/test/static', 'status': 0},
        ])
        panel = types.ModuleType('public')
        domains = MemoryDomainQuery([{'id': 1, 'pid': 11, 'name': 'simple.test', 'port': 80}])
        def database(table):
            assert table in ('sites', 'domain')
            return query if table == 'sites' else domains
        panel.M = database
        with patch.dict(sys.modules, {'public': panel}):
            ok = self.plugin.get_sites({'page': '1', 'page_size': '1'})
            self.assertTrue(ok['status'])
            self.assertEqual(ok['inventory_schema'], 2)
            self.assertEqual(ok['sites'][0]['name'], 'simple.test')
            self.assertTrue(ok['has_more'])
            err = self.plugin.get_sites({'page': '-1'})
            self.assertIs(err['status'], False)
            self.assertEqual(err['stage'], 'website_discovery')
            self.assertTrue(err['operation_id'])

    def test_ui_rejects_older_panel_backend_without_fabricating_empty_bindings(self):
        html = (PLUGIN_DIR / 'index.html').read_text(encoding='utf-8')
        self.assertIn('r.inventory_schema !== 2', html)
        self.assertIn('!Array.isArray(site.bound_domains)', html)
        self.assertIn('Inventory API mismatch:', html)
        self.assertNotIn('(site.bound_domains || [])', html)

    def test_inventory_tracks_added_renamed_and_removed_sites(self):
        query = MemorySiteQuery([{'id': 10, 'name': 'first.example', 'path': '/srv/one', 'status': 1}])
        panel = types.ModuleType('public')
        domains = MemoryDomainQuery([{'id': 1, 'pid': 10, 'name': 'first.example', 'port': 80}])
        panel.M = lambda table: query if table == 'sites' else domains if table == 'domain' else None
        with patch.dict(sys.modules, {'public': panel}):
            original = self.plugin.get_sites({})
            self.assertEqual([row['name'] for row in original['sites']], ['first.example'])
            query.rows.append({'id': 20, 'name': 'static.example', 'path': '/srv/static', 'status': 1})
            added = self.plugin.get_sites({})
            self.assertEqual([row['name'] for row in added['sites']], ['first.example', 'static.example'])
            query.rows[0]['name'] = 'renamed.example'
            renamed = self.plugin.get_sites({})
            self.assertEqual(renamed['sites'][0]['name'], 'renamed.example')
            self.assertFalse(renamed['sites'][0]['canonical_domain_bound'])
            self.assertEqual(renamed['sites'][0]['bound_domains'][0]['name'], 'first.example')
            query.rows.pop(0)
            removed = self.plugin.get_sites({})
            self.assertEqual([row['id'] for row in removed['sites']], [20])

    def test_php_fpm_file_drift_remains_visible_with_read_only_shared_site_mapping(self):
        payload = dict(php_version='85', max_children='50', start_servers='5',
                       min_spare_servers='5', max_spare_servers='20', max_requests='0')
        preview = {
            'state': 'File Drift', 'scope': 'shared_service', 'version': '85',
            'source': '/www/server/php/85/etc/php-fpm.conf',
            'changes': [{'setting': 'pm.max_children', 'actual': 80, 'desired': 50}],
        }
        impact = {
            'schema': 1, 'scope': 'shared_service', 'state': 'File Mapping', 'version': '85',
            'matched_sites': [{'id': 3, 'site_key': 'site-a.test'},
                              {'id': 6, 'site_key': 'site-b.test'}],
            'unresolved_sites': [], 'site_count': 2, 'other_php_sites_count': 0,
            'reason': '', 'note': 'File-only evidence.',
        }
        fake_public = types.ModuleType('public')
        with patch('ach_customizer_fpm_policy.observe', return_value=(preview, 'a'*64)), \
                patch('ach_customizer_fpm_policy.get_policy',
                      return_value={'saved':False, 'policy_revision':0}), \
                patch.object(MODULE, 'inspect_php_fpm_site_impact', return_value=impact) as mapping, \
                patch.dict(sys.modules, {'public': fake_public}):
            result = self.plugin.preview_php_fpm(payload)
        self.assertTrue(result['status'], result)
        self.assertEqual(result['state'], 'File Drift')
        self.assertEqual(result['changes'], preview['changes'])
        self.assertEqual(result['shared_impact'], impact)
        mapping.assert_called_once_with(fake_public, '85', preview['source'])

    def test_unsupported_php_file_layout_never_guesses_shared_site_scope(self):
        payload = dict(php_version='85', max_children='20', start_servers='5',
                       min_spare_servers='5', max_spare_servers='10', max_requests='300')
        with patch('ach_customizer_fpm_policy.observe', return_value=({
            'state': 'Needs Review', 'scope': 'shared_service', 'reason': 'Unknown layout',
        }, None)), patch('ach_customizer_fpm_policy.get_policy',
                     return_value={'saved': False, 'policy_revision': 0}), patch.object(MODULE, 'inspect_php_fpm_site_impact',
                         side_effect=AssertionError("unsafe inference")) as mapping:
            result = self.plugin.preview_php_fpm(payload)
        self.assertTrue(result['status'])
        self.assertEqual(result['state'], 'Needs Review')
        self.assertEqual(result['shared_impact']['state'], 'Needs Review')
        self.assertEqual(result['shared_impact']['matched_sites'], [])
        mapping.assert_not_called()

    def test_fpm_preview_is_read_only_and_reports_unsupported_layout(self):
        payload = dict(php_version='85', max_children='20', start_servers='5',
                       min_spare_servers='5', max_spare_servers='10', max_requests='300')
        with patch('ach_customizer_fpm_policy.observe', return_value=(
                {'state': 'Needs Review', 'scope': 'shared_service'}, None)) as call, \
                patch('ach_customizer_fpm_policy.get_policy',
                      return_value={'saved': False, 'policy_revision': 0}):
            result = self.plugin.preview_php_fpm(payload)
        self.assertTrue(result['status'])
        self.assertEqual(result['scope'], 'shared_service')
        self.assertTrue(result['operation_id'])
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0], '/www/server/php')
        broken = self.plugin.preview_php_fpm(dict(payload, php_version='../etc'))
        self.assertIs(broken['status'], False)
        self.assertEqual(broken['stage'], 'php_fpm_file_preview')


if __name__ == '__main__':
    unittest.main()
