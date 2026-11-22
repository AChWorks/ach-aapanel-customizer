"""Unknown-SNI TLS policy: source ownership, real-probe contract and recovery."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(ROOT))

import ach_customizer_status_tls as subject
import ach_customizer_main as backend
from ach_customizer_state import _open_state_dir


class FakeNginx:
    def __init__(self, fixture):
        self.fixture = fixture
        self.running = False
        self.reloads = 0
        self.fail_config = False
        self.fail_reload = False

    def __call__(self, argv, **kwargs):
        if "-T" in argv:
            if self.fail_config and self.fixture.managed.exists():
                return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"syntax problem")
            text = "# configuration file " + str(self.fixture.nginx_conf) + ":\n"
            text += self.fixture.nginx_conf.read_text() + "\n"
            for file in sorted(self.fixture.vhost.glob("*.conf")):
                text += "# configuration file " + str(file) + ":\n" + file.read_text() + "\n"
            return types.SimpleNamespace(returncode=0, stdout=text.encode(), stderr=b"")
        if "-t" in argv:
            return types.SimpleNamespace(
                returncode=int(self.fail_config and self.fixture.managed.exists()))
        if "-s" in argv and "reload" in argv:
            if self.fail_reload:
                return types.SimpleNamespace(returncode=1)
            self.running = self.fixture.managed.exists()
            self.reloads += 1
            return types.SimpleNamespace(returncode=0)
        raise AssertionError("Unexpected Nginx command: " + repr(argv))

    def probe(self, family, name):
        # A managed default can still serve an address family after the
        # native site has been deleted; deleting it during Restore removes
        # that socket entirely, which must be reported as TCP refused.
        native = self.fixture.named.read_text()
        family_present = "listen 443 " in native if family == "ipv4" else "listen [::]:443 " in native
        if not family_present and not self.running:
            return "refused"
        if (name is None or name.startswith("ach-unknown-")) and self.running:
            return "rejected"
        return "accepted"


class TlsPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-tls-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vhost = self.base / "vhosts"
        self.confroot = self.base / "nginx"
        self.data = self.base / "data"
        for path in (self.vhost, self.confroot, self.data):
            path.mkdir(mode=0o700)
        self.nginx_conf = self.confroot / "nginx.conf"
        self.nginx_conf.write_text(
            "http {\ninclude " + str(self.vhost) + "/*.conf;\n}\n")
        self.nginx_conf.chmod(0o600)
        self.named = self.vhost / "site.conf"
        self.named.write_text(
            "server { listen 443 ssl; listen [::]:443 ssl; "
            "server_name example.test; ssl_certificate /tmp/abc.pem; }\n")
        self.named.chmod(0o600)
        self.managed = self.vhost / subject.CONF_NAME
        self.fd = _open_state_dir(self.data)
        self.addCleanup(os.close, self.fd)
        self.runner = FakeNginx(self)

    def call(self, action, **kwargs):
        return subject.manage_tls(action, data_fd=self.fd,
                                  vhost_root=str(self.vhost),
                                  nginx=str(self.base / "fake-nginx"),
                                  nginx_conf=str(self.nginx_conf),
                                  runner=self.runner,
                                  probe=self.runner.probe, **kwargs)

    def recheck(self):
        return self.call("recheck")

    def apply(self):
        first = self.recheck()
        self.assertIn(first["state"], ("Source Ready", "Restored"))
        return self.call("apply", expected_source=first["source_sha256"])

    def restore(self):
        current = self.recheck()
        return self.call("restore", expected_source=current["source_sha256"],
                         expected_recovery=current["recovery_id"])

    def test_apply_recheck_restore_preserves_native_https_source_and_other_files(self):
        original = self.named.read_bytes()
        initial = self.recheck()
        self.assertEqual(initial["state"], "Source Ready")
        self.assertEqual(set(initial["families"]), {"ipv4", "ipv6"})
        self.assertEqual(initial["witnesses"]["ipv4"], "example.test")
        self.assertEqual(self.runner.reloads, 0)
        applied = self.apply()
        self.assertEqual(applied["state"], "Applied")
        self.assertTrue(applied["runtime_verified"])
        self.assertEqual(self.managed.stat().st_mode & 0o777, 0o600)
        self.assertIn(b"ssl_reject_handshake on;", self.managed.read_bytes())
        self.assertEqual(self.named.read_bytes(), original)
        self.assertEqual(self.runner.reloads, 1)
        self.assertEqual(self.recheck()["state"], "Applied")
        restored = self.restore()
        self.assertEqual(restored["state"], "Restored")
        self.assertTrue(restored["runtime_verified"])
        self.assertEqual(self.runner.reloads, 2)
        self.assertFalse(self.managed.exists())
        self.assertEqual(self.named.read_bytes(), original)
        self.assertEqual(self.recheck()["state"], "Restored")

    def test_reload_worker_generation_race_has_bounded_settle_and_exact_recovery(self):
        original = self.runner.probe
        lag = {"apply": 2, "restore": 2}
        def delayed(family, name):
            if name is not None and name.startswith("ach-unknown-"):
                if self.runner.reloads == 1 and lag["apply"]:
                    lag["apply"] -= 1
                    return "accepted"  # old worker has not switched yet
                if self.runner.reloads == 2 and lag["restore"]:
                    lag["restore"] -= 1
                    return "rejected"  # old managed worker still draining
            return original(family, name)
        self.runner.probe = delayed
        applied = self.apply()
        self.assertEqual(applied["state"], "Applied")
        self.assertEqual(lag["apply"], 0)
        self.assertEqual(self.recheck()["state"], "Applied")
        restored = self.restore()
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(lag["restore"], 0)
        self.assertFalse(self.managed.exists())

    def test_no_https_listener_does_not_open_a_new_port(self):
        self.named.write_text("server { listen 80; server_name example.test; }")
        state = self.recheck()
        self.assertEqual(state["state"], "Not Applicable")
        self.assertEqual(state["families"], [])
        with self.assertRaises(subject.TLSError):
            self.call("apply", expected_source=state["source_sha256"])
        self.assertFalse(self.managed.exists())
        self.assertEqual(list(self.data.iterdir()), [])

    def test_foreign_https_default_or_address_specific_listener_refused(self):
        variants = (
            "server { listen 443 ssl default_server; server_name example.test; }",
            "server { listen 127.0.0.1:443 ssl; server_name example.test; }",
            "server { listen 443 quic; server_name example.test; }",
            "server { listen 443 ssl ipv6only=off; server_name example.test; }",
            "stream { server { listen 443; proxy_pass 127.0.0.1:8071; } }",
        )
        for item in variants:
            with self.subTest(item=item):
                self.named.write_text(item)
                with self.assertRaises(subject.TLSError):
                    self.recheck()
                self.assertFalse(self.managed.exists())
        self.assertFalse(list(self.data.iterdir()))

    def test_source_drift_invalidates_approval_without_moving_native_files(self):
        ready = self.recheck()
        self.named.write_text(self.named.read_text() + "# native changed\n")
        with self.assertRaisesRegex(subject.TLSError, "changed"):
            self.call("apply", expected_source=ready["source_sha256"])
        self.assertFalse(self.managed.exists())
        self.assertFalse(list(self.data.iterdir()))

    def test_interrupted_reload_remains_recoverable_from_original_id(self):
        baseline = self.recheck()
        self.runner.fail_reload = True
        with self.assertRaises(subject.TLSError) as err:
            self.call("apply", expected_source=baseline["source_sha256"])
        self.assertEqual(err.exception.stage, "uncertain")
        operation_id = err.exception.recovery_id
        self.assertRegex(operation_id, r"^[a-f0-9]{32}$")
        self.assertEqual(self.recheck()["state"], "Recovery Required")
        self.runner.fail_reload = False
        restored = self.restore()
        self.assertEqual(restored["state"], "Restored")
        self.assertEqual(restored["recovery_id"], operation_id)
        self.assertEqual(self.recheck()["state"], "Restored")

    def test_syntax_failure_detaches_incomplete_live_config(self):
        first = self.recheck()
        self.runner.fail_config = True
        with self.assertRaises(subject.TLSError) as error:
            self.call("apply", expected_source=first["source_sha256"])
        self.assertEqual(error.exception.stage, "uncertain")
        self.assertFalse(self.managed.exists())
        self.assertEqual(self.recheck()["state"], "Recovery Required")
        self.runner.fail_config = False
        self.assertEqual(self.restore()["state"], "Restored")

    def test_exact_recovery_identity_and_modified_config_protected(self):
        applied = self.apply()
        state = self.recheck()
        with self.assertRaises(subject.TLSError):
            self.call("restore", expected_source=state["source_sha256"],
                      expected_recovery="0" * 32)
        self.managed.write_text(self.managed.read_text() + "# foreign edit\n")
        with self.assertRaises(subject.TLSError):
            self.restore()
        self.assertTrue(self.managed.exists())
        self.assertEqual(state["recovery_id"], applied["recovery_id"])

    def test_restore_after_named_https_site_removed_checks_confirmed_socket_absence(self):
        self.apply()
        self.named.write_text("server { listen 80; server_name example.test; }")
        self.assertEqual(self.recheck()["state"], "Recovery Required")
        restored = self.restore()
        self.assertEqual(restored["state"], "Restored")
        self.assertFalse(self.managed.exists())
        self.assertEqual(self.recheck()["state"], "Not Applicable")

    def test_exact_protocols_copied_from_implicit_default_without_rewriting_sites(self):
        self.named.write_text(
            "server { listen 443 ssl; server_name example.test; "
            "ssl_protocols TLSv1.2 TLSv1.3; }")
        applied = self.apply()
        self.assertIn(b"ssl_protocols TLSv1.2 TLSv1.3;", self.managed.read_bytes())
        self.assertEqual(applied["families"], ["ipv4"])


class EndpointAuthorizationTests(unittest.TestCase):
    def test_primary_admin_post_and_explicit_global_approval(self):
        p = backend.ach_customizer_main()
        public = types.ModuleType("public")
        public.get_webserver = lambda: "nginx"
        with tempfile.TemporaryDirectory() as local, patch.object(
                backend, "_STATE_DIR", local), patch.dict(
                sys.modules, {"public": public}):
            with patch.object(backend.ach_customizer_main, "_status_primary_admin_post",
                              side_effect=PermissionError("no primary admin")):
                rejected = p.status_tls({"tls_action": "recheck",
                                         "scope": "global", "template": "unbound"})
                self.assertFalse(rejected["status"])
                self.assertIn("authorization", rejected["stage"])
            with patch.object(backend.ach_customizer_main, "_status_primary_admin_post"):
                rejected = p.status_tls({"tls_action": "apply",
                                         "scope": "global", "template": "unbound"})
                self.assertFalse(rejected["status"])
                self.assertIn("approval", rejected["msg"].lower())
                rejected = p.status_tls({"tls_action": "recheck",
                                         "scope": "site", "template": "unbound"})
                self.assertFalse(rejected["status"])


if __name__ == "__main__":
    unittest.main()
