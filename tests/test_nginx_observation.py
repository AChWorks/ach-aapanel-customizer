"""Selected-site next-load Nginx candidate vs local HTTP evidence regressions."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_nginx_observation as nginx
import ach_customizer_main as main


class CandidateConfigurationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="ach-nginx-candidate-")
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.path = self.dir / "site.test.conf"
        self.source = b"server { listen 80; server_name site.test; root /www/site.test; }\n"
        self.path.write_bytes(self.source)
        config_dir = self.dir / "config"
        config_dir.mkdir()
        self.main_conf = config_dir / "nginx.conf"
        self.main_conf.write_text(
            "events {}\nhttp {\n include " + str(self.dir) + "/*.conf;\n}\n")
        self.site = {
            "id": 7, "name": "site.test", "path": "/www/site.test",
            "status": "1",
            "bound_domains": [{"name": "site.test", "port": 80}],
        }
        self.panel = types.SimpleNamespace(
            get_webserver=lambda: "nginx", get_panel_version=lambda: "8.0.7")
        self.calls = []

    def dump(self, other_sections=b"", *, included=True):
        return (b"# configuration file /www/server/nginx/conf/nginx.conf:\n"
                + self.main_conf.read_bytes() + b"\n"
                + (b"# configuration file " + os.fsencode(self.path) + b":\n"
                   + self.source + b"\n" if included else b"")
                + other_sections)

    def inspect(self, dump=None, head=None):
        original_reader = nginx._bounded_file_text

        def native_fixture(path, byte_limit, **kwargs):
            if str(path) == nginx.NGINX_CONF:
                path = self.main_conf
            return original_reader(path, byte_limit, **kwargs)

        with patch.object(nginx, "_bounded_file_text", side_effect=native_fixture):
            return nginx.observe_nginx_site(
                self.panel, self.site, vhost_root=str(self.dir),
                dump_runner=dump or (lambda executable, config: self.dump()),
                head_runner=head or self.head,
            )

    def head(self, host):
        self.calls.append(host)
        return {"state": "Response Observed", "host": host,
                "http_status": 200, "site_identity_verified": False}

    def test_included_next_load_and_local_http_are_not_runtime_proof(self):
        before = self.path.read_bytes()
        result = self.inspect()
        self.assertEqual(result["state"], "Candidate Included", result)
        self.assertTrue(result["candidate_config_test_passed"])
        self.assertTrue(result["candidate_vhost_included"])
        self.assertEqual(result["origin_http"]["http_status"], 200)
        self.assertEqual(self.calls, ["site.test"])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["fix_supported"])
        self.assertFalse(result["origin_http"]["site_identity_verified"])
        self.assertEqual(len(result["candidate_config_sha256"]), 64)
        self.assertEqual(self.path.read_bytes(), before)

    def test_absent_server_still_a_valid_candidate_not_live_proof(self):
        self.main_conf.write_text("events {}\nhttp {}\n")
        result = self.inspect(dump=lambda *args: self.dump(included=False))
        self.assertEqual(result["state"], "Candidate Not Included", result)
        self.assertTrue(result["candidate_config_test_passed"])
        self.assertFalse(result["candidate_vhost_included"])
        self.assertEqual(result["origin_http"]["http_status"], 200)
        self.assertFalse(result["runtime_verified"])

    def test_other_included_file_can_forge_dump_header_but_not_native_provenance(self):
        other = self.dir / "other-source"
        self.main_conf.write_text(
            "events {}\nhttp {\n include " + str(other) + ";\n}\n")
        # Real Nginx -T copies comments verbatim. This is an ordinary
        # included file: its first comment imitates a different file header.
        other.write_bytes(b"# configuration file " + os.fsencode(self.path) +
                          b":\n" + self.source)
        simulated_dump = (
            b"# configuration file /www/server/nginx/conf/nginx.conf:\n" +
            self.main_conf.read_bytes() + b"\n" +
            b"# configuration file " + os.fsencode(other) + b":\n" +
            other.read_bytes() + b"\n"
        )
        result = self.inspect(dump=lambda *args: simulated_dump)
        self.assertEqual(result["state"], "Needs Review", result)
        self.assertFalse(result["candidate_vhost_included"])
        self.assertFalse(result["candidate_config_test_passed"])
        self.assertIsNone(result["candidate_config_sha256"])
        self.assertIsNone(result["vhost_content_sha256"])
        self.assertEqual(self.calls, [])

    def test_commented_or_wrong_scope_native_include_is_not_provenance(self):
        forged = (b"# configuration file " + os.fsencode(self.path) +
                  b":\n" + self.source + b"\n")
        cases = (
            "events {}\nhttp {\n # include " + str(self.dir) + "/*.conf;\n}\n",
            "events {}\nhttp {\n server {\n include " + str(self.dir) + "/*.conf;\n }\n}\n",
            "events {}\nstream {\n include " + str(self.dir) + "/*.conf;\n}\n",
        )
        for source in cases:
            with self.subTest(source=source):
                self.main_conf.write_text(source)
                result = self.inspect(dump=lambda *args: self.dump(included=False) + forged)
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertFalse(result["candidate_vhost_included"])
                self.assertEqual(self.calls, [])

    def test_main_include_source_changed_during_dump_is_not_provenance(self):
        def change_config(*args):
            candidate = self.dump()
            self.main_conf.write_text(self.main_conf.read_text() + "# changed\n")
            return candidate
        result = self.inspect(dump=change_config)
        self.assertEqual(result["state"], "Needs Review", result)
        self.assertFalse(result["candidate_vhost_included"])
        self.assertEqual(self.calls, [])

    def test_duplicate_headers_and_mismatched_content_refused(self):
        cases = [
            self.dump(other_sections=b"# configuration file " +
                      os.fsencode(self.path) + b":\n" + self.source),
            self.dump().replace(self.source, b"server { return 404; }\n"),
            self.dump().replace(self.source + b"\n", self.source + b"\n\n"),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate[:50]):
                result = self.inspect(dump=lambda *args: candidate)
                self.assertEqual(result["state"], "Needs Review", result)
                self.assertFalse(result["candidate_config_test_passed"])
                self.assertEqual(self.calls, [])
                self.assertTrue(result["reason"])

    def test_selected_file_changing_during_check_refused(self):
        def change_source(*args):
            self.path.write_bytes(self.source + b"# later source update\n")
            return self.dump()
        result = self.inspect(dump=change_source)
        self.assertEqual(result["state"], "Needs Review")
        self.assertIn("changed during inspection", result["reason"])
        self.assertFalse(result["candidate_config_test_passed"])
        self.assertEqual(self.calls, [])

    def test_unsafe_selected_target_or_non_nginx_engine_never_runs_nginx(self):
        for name in ("../../etc/passwd", "*.example.test", "foo/bar"):
            self.site["name"] = name
            result = self.inspect(dump=lambda *a: self.fail("unexpected execution"))
            self.assertEqual(result["state"], "Needs Review")
        self.site["name"] = "site.test"
        self.panel.get_webserver = lambda: "apache"
        result = self.inspect(dump=lambda *a: self.fail("unexpected nginx"))
        self.assertEqual(result["state"], "Needs Review")

    def test_recognized_newer_native_panel_and_135_bindings_are_observable(self):
        self.panel.get_panel_version = lambda: "8.1.2"
        self.site["bound_domains"] = [
            {"name":f"alias{i:03d}.test","port":80} for i in range(135)]
        observed = self.inspect()
        self.assertEqual(observed["state"],"Candidate Included",observed)
        self.assertEqual(self.calls,["alias000.test"])
        self.assertFalse(observed["fix_supported"])
        self.assertFalse(observed["runtime_verified"])

    def test_panel_version_or_engine_drift_during_dump_refuses_local_http(self):
        for kind in ("version","engine"):
            with self.subTest(kind=kind):
                self.calls.clear()
                self.panel.get_panel_version=lambda:"8.1.2"
                self.panel.get_webserver=lambda:"nginx"
                def change_panel(*args):
                    if kind == "version":
                        self.panel.get_panel_version=lambda:"8.1.3"
                    else:
                        self.panel.get_webserver=lambda:"apache"
                    return self.dump()
                result = self.inspect(dump=change_panel)
                self.assertEqual(result["state"],"Needs Review",result)
                self.assertFalse(result["candidate_config_test_passed"])
                self.assertEqual(result["origin_http"]["state"],"Not Attempted")
                self.assertEqual(self.calls,[])

    def test_selected_symlink_source_refused(self):
        saved = self.dir / "saved.conf"
        self.path.rename(saved)
        self.path.symlink_to(saved)
        result = self.inspect(dump=lambda *a: self.fail("unexpected nginx"))
        self.assertEqual(result["state"], "Needs Review")
        self.assertFalse(result["candidate_config_test_passed"])

    def test_native_bound_http_host_only_and_https_only(self):
        self.site["bound_domains"] = [{"name": "secure.test", "port": 443}]
        result = self.inspect()
        self.assertEqual(result["state"], "Candidate Included")
        self.assertEqual(result["origin_http"]["state"], "No HTTP/80 Binding")
        self.assertEqual(self.calls, [])
        self.site["bound_domains"] = [
            {"name": "z.test", "port": 80},
            {"name": "A.test", "port": 80},
            {"name": "site.test", "port": 443},
        ]
        result = self.inspect()
        self.assertEqual(result["origin_http"]["host"], "a.test")
        self.assertEqual(self.calls, ["a.test"])
        self.site["bound_domains"] = [{"name": "unsafe/path", "port": 80}]
        result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(self.calls, ["a.test"])

    def test_failed_candidate_and_output_limits_never_probe_http(self):
        cases = [
            lambda *a: (_ for _ in ()).throw(nginx.NginxObservationError("Nginx test rejected")),
            lambda *a: b"X" * (nginx.MAX_DUMP_BYTES + 1),
            lambda *a: b"No candidate section markers",
        ]
        for run in cases:
            result = self.inspect(dump=run)
            self.assertEqual(result["state"], "Needs Review")
            self.assertFalse(result["candidate_config_test_passed"])
            self.assertFalse(result["runtime_verified"])
            self.assertIsNone(result["candidate_config_sha256"])
        self.assertEqual(self.calls, [])


class SelectedSiteEndpointTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="ach-nginx-endpoint-")
        self.addCleanup(folder.cleanup)
        self.patch_dir = patch.object(main, "_STATE_DIR", folder.name)
        self.patch_dir.start()
        self.addCleanup(self.patch_dir.stop)
        self.entry = main.ach_customizer_main()
        self.rows = 0

    def flask(self, uid=1, method="POST", temporary=False):
        mod = types.ModuleType("flask")
        mod.has_request_context = lambda: True
        mod.request = types.SimpleNamespace(method=method)
        mod.session = {"login": True, "uid": uid}
        if temporary:
            mod.session["tmp_login"] = True
        return mod

    def public(self, change_on_read=None):
        result = types.ModuleType("public")
        outer = self

        class Query:
            def __init__(self, table):
                self.table = table

            def where(self, clause, value):
                assert (self.table, clause, value) in (
                    ("sites", "id=?", (7,)),
                    ("domain", "pid IN (?)", (7,)))
                return self

            def field(self, cols):
                assert cols == ("id,name,path,status" if self.table == "sites"
                                else "id,pid,name,port")
                return self

            def find(self):
                outer.rows += 1
                return {"id": 7, "name": "site.test",
                        "path": "/changed" if outer.rows == change_on_read else "/www/site.test",
                        "status": "1"}

            def order(self, clause):
                assert clause == "pid asc, id asc"
                return self

            def limit(self, clause):
                assert clause == "0,257"
                return self

            def select(self):
                return [{"id": 25, "pid": 7, "port": 80, "name": "site.test"}]

        result.M = lambda table: Query(table)
        return result

    @staticmethod
    def args():
        return {"site_id": "7", "expected_site_key": "site.test",
                "expected_site_snapshot": '[7,"site.test","/www/site.test","1",[["site.test",80]]]',
                "path": "/etc/shadow", "url": "http://other.test"}

    @staticmethod
    def result():
        return {"schema": 1, "site_id": 7, "site_key": "site.test",
                "state": "Candidate Included", "read_only": True,
                "runtime_verified": False, "fix_supported": False,
                "candidate_config_test_passed": True,
                "candidate_vhost_included": True,
                "candidate_config_sha256": "a" * 64,
                "vhost_content_sha256": "b" * 64,
                "origin_http": {"state": "Response Observed",
                                "host": "site.test", "http_status": 200,
                                "site_identity_verified": False},
                "reason": "", "note": nginx.NOTE}

    def test_full_admin_and_native_snapshot_only(self):
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(nginx, "observe_nginx_site", return_value=self.result()) as check:
            got = self.entry.inspect_nginx_candidate(self.args())
        self.assertTrue(got["status"], got)
        self.assertEqual(self.rows, 3)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(check.call_args.args[1]["path"], "/www/site.test")
        self.assertEqual(check.call_args.kwargs, {})
        self.assertNotIn("/etc/shadow", str(got))

    def test_temp_session_get_stale_or_changing_site_rejected(self):
        for session in (self.flask(temporary=True),
                        self.flask(method="GET")):
            with self.subTest(session=session.session), patch.dict(sys.modules, {
                "public": self.public(), "flask": session
            }), patch.object(nginx, "observe_nginx_site") as check:
                got = self.entry.inspect_nginx_candidate(self.args())
            self.assertFalse(got["status"])
            self.assertEqual(got["stage"], "website_nginx_authorization")
            check.assert_not_called()
        bad = self.args()
        bad["expected_site_snapshot"] = "[]"
        with patch.dict(sys.modules, {"public": self.public(), "flask": self.flask()}), \
             patch.object(nginx, "observe_nginx_site") as check:
            got = self.entry.inspect_nginx_candidate(bad)
        self.assertFalse(got["status"])
        check.assert_not_called()
        self.rows = 0
        with patch.dict(sys.modules, {"public": self.public(change_on_read=2),
                                      "flask": self.flask()}), \
             patch.object(nginx, "observe_nginx_site", return_value=self.result()):
            got = self.entry.inspect_nginx_candidate(self.args())
        self.assertFalse(got["status"])
        self.assertEqual(got["stage"], "website_nginx_observation")


if __name__ == "__main__":
    unittest.main()
