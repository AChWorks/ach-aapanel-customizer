"""Cross-module native-source contract: managed Status Pages must not block PHP FPM.

Temporary aaPanel-shaped files and journals, with no host Nginx or PHP writes.
The accepted status snippets are produced by the real Status Pages generator.
"""
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(ROOT))

import ach_customizer_cache_audit as cache
import ach_customizer_fpm_workflow as workflow
import ach_customizer_monitor as monitor
import ach_customizer_status_extension as status


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SitesQuery:
    def __init__(self, rows):
        self.rows = rows

    def order(self, value):
        assert value == "id asc"
        return self

    def limit(self, value):
        assert value == "0,101"
        return self

    def field(self, value):
        assert value == "id,name"
        return self

    def select(self):
        return list(self.rows)


class Panel:
    def __init__(self, rows):
        self.rows = rows

    def M(self, name):
        assert name == "sites"
        return SitesQuery(self.rows)

    def get_webserver(self):
        return "nginx"

    def get_panel_version(self):
        return "8.0.7"


class OwnedStatusInteropTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ach-status-php-interop-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vhosts = self.root / "vhosts"
        self.nginx = self.root / "nginx"
        self.rewrites = self.root / "rewrite"
        self.data = self.root / "data"
        self.php_root = self.root / "php"
        self.pool = self.php_root / "85" / "etc" / "php-fpm.conf"
        for path in (self.vhosts, self.nginx, self.rewrites, self.data,
                     self.pool.parent):
            path.mkdir(parents=True)
        self.pool.write_text(
            "[global]\n[www]\npm = dynamic\n"
            "listen = /tmp/php-cgi-85.sock\n"
            "pm.max_children = 50\npm.start_servers = 5\n"
            "pm.min_spare_servers = 5\npm.max_spare_servers = 20\n",
            encoding="utf-8")
        (self.nginx / "nginx.conf").write_text(
            "http {\nfastcgi_cache_path /tmp/ach-cache "
            "levels=1:2 keys_zone=WORDPRESS:100m inactive=60m;\n}\n")
        (self.nginx / "fastcgi.conf").write_text(
            "fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;\n")
        (self.nginx / "enable-php-85.conf").write_text(
            "location ~ \\.php$ {\n"
            " fastcgi_pass unix:/tmp/php-cgi-85.sock;\n"
            " include fastcgi.conf;\n}\n")
        (self.nginx / "enable-php-85-wpfastcgi.conf").write_text(
            "location ~ \\.php$ {\n"
            " fastcgi_pass unix:/tmp/php-cgi-85.sock;\n"
            " include fastcgi.conf;\n"
            " fastcgi_cache WORDPRESS;\n"
            " fastcgi_cache_key \"$scheme$request_method$host$request_uri\";\n"
            " fastcgi_cache_bypass $skip_cache $http_authorization;\n"
            " fastcgi_no_cache $skip_cache $http_authorization;\n}\n")
        (self.nginx / "enable-php-00.conf").write_text(
            "location ~ \\.php$ { return 404; }\n")
        self.rows = [
            {"id": 3, "name": "wp-a.test"},
            {"id": 6, "name": "wp-b.test"},
            {"id": 7, "name": "static.test"},
        ]
        self.panel = Panel(self.rows)
        for item in self.rows:
            site_id, name = item["id"], item["name"]
            ext = self.vhosts / "extension" / name
            ext.mkdir(parents=True)
            (ext / "site_total.conf").write_text("access_log off;\n")
            php = ("enable-php-00.conf" if site_id == 7 else
                   "enable-php-85-wpfastcgi.conf" if site_id == 6 else
                   "enable-php-85.conf")
            (self.vhosts / (name + ".conf")).write_text(
                "server {\n server_name " + name + ";\n"
                " include " + php + ";\n"
                " include " + str(ext) + "/*.conf;\n}\n")
        patcher = patch("ach_customizer_state.DATA_DIR", str(self.data))
        patcher.start()
        self.addCleanup(patcher.stop)

    def impact(self):
        return monitor.inspect_php_fpm_site_impact(
            self.panel, "85", self.pool, vhost_root=self.vhosts,
            nginx_conf_root=self.nginx, rewrite_root=self.rewrites)

    def audit(self):
        return cache.inspect_site_fastcgi_cache(
            self.panel, 3, "wp-a.test",
            vhost_root=str(self.vhosts), nginx_root=str(self.nginx),
            rewrite_root=str(self.rewrites))

    def owned(self, site_id=3, code="404", *, phase="applied"):
        name = next(item["name"] for item in self.rows if item["id"] == site_id)
        op = ("%032x" % (site_id * 1000 + int(code)))
        after = sha(("rendered " + code).encode())
        asset = status._asset_path(status.PUBLIC_ROOT, site_id, code, after)
        source = status._include(code, asset, op)
        path = self.vhosts / "extension" / name / status._include_name(site_id, code)
        path.write_bytes(source)
        path.chmod(0o600)
        record = {
            "schema": 1, "site_id": site_id, "site_name": name,
            "code": code, "op": op, "phase": phase,
            "vhost_sha": sha((self.vhosts / (name + ".conf")).read_bytes()),
            "before_sha": sha(b"previous source"),
            "after_sha": after,
            "include_sha": sha(source),
            "asset_path": asset,
        }
        journal = self.data / status._record_name(site_id, code)
        journal.write_text(json.dumps(record, sort_keys=True) + "\n")
        journal.chmod(0o600)
        return path, journal, record, source

    @staticmethod
    def update_journal(journal, record):
        journal.write_text(json.dumps(record, sort_keys=True) + "\n")
        journal.chmod(0o600)

    def test_native_inert_and_owned_404_502_on_both_sites_are_eligible(self):
        baseline = self.impact()
        self.assertEqual(baseline["state"], "File Mapping", baseline)
        self.assertTrue(baseline["manual_apply_eligible"])
        self.owned(3, "404")
        after_404 = self.impact()
        self.assertEqual(after_404["state"], "File Mapping", after_404)
        self.assertTrue(after_404["manual_apply_eligible"])
        self.assertNotEqual(after_404["dependency_sha256"], baseline["dependency_sha256"])
        self.owned(6, "502")
        after_other = self.impact()
        self.assertEqual(after_other["state"], "File Mapping", after_other)
        self.assertTrue(after_other["manual_apply_eligible"])
        self.assertEqual([x["id"] for x in after_other["matched_sites"]], [3, 6])
        self.assertEqual(after_other["other_php_sites_count"], 1)
        self.assertNotEqual(after_404["dependency_sha256"], after_other["dependency_sha256"])

    def test_prepared_owned_source_is_attributable_without_recovery_dependency(self):
        self.owned(6, "502", phase="prepared")
        result = self.impact()
        self.assertEqual(result["state"], "File Mapping", result)
        self.assertTrue(result["manual_apply_eligible"])

    def test_unknown_changed_and_extra_upstream_remain_unresolved(self):
        path, journal, record, source = self.owned()
        for content in (
            source + b"include /tmp/foreign.conf;\n",
            source + b"fastcgi_pass unix:/tmp/other.sock;\n",
            source.replace(b"location = /404.html", b"location = /index.php"),
            b"access_log off;\n",
        ):
            with self.subTest(content=content[:50]):
                path.write_bytes(content)
                self.assertEqual(self.impact()["state"], "Needs Review")
        path.write_bytes(source)
        self.assertEqual(self.impact()["state"], "File Mapping")
        # A second, independently authored routing file remains a rejection.
        (path.parent / "foreign.conf").write_text(
            "location /hidden { proxy_pass http://elsewhere; }\n")
        self.assertEqual(self.impact()["state"], "Needs Review")
        (path.parent / "foreign.conf").unlink()
        self.assertEqual(self.impact()["state"], "File Mapping")

    def test_owned_identity_journal_and_file_permissions_are_required(self):
        path, journal, record, source = self.owned()
        journal.unlink()
        self.assertEqual(self.impact()["state"], "Needs Review")
        self.update_journal(journal, record)
        for change in (
            {"site_name": "another.test"},
            {"asset_path": "/tmp/forged/" + record["asset_path"].split("/")[-1]},
            {"include_sha": "f" * 64},
            {"phase": "restored"},
        ):
            with self.subTest(change=change):
                self.update_journal(journal, {**record, **change})
                self.assertEqual(self.impact()["state"], "Needs Review")
        self.update_journal(journal, record)
        path.chmod(0o644)
        self.assertEqual(self.impact()["state"], "Needs Review")
        path.chmod(0o600)
        self.assertEqual(self.impact()["state"], "File Mapping")
        path.unlink()
        path.symlink_to(self.pool)
        self.assertEqual(self.impact()["state"], "Needs Review")

    def test_file_and_journal_dependency_drift_invalidate_stale_approval(self):
        path, journal, record, source = self.owned()
        first = self.impact()
        self.update_journal(journal, {**record, "phase": "prepared"})
        second = self.impact()
        self.assertEqual(second["state"], "File Mapping")
        self.assertNotEqual(first["dependency_sha256"], second["dependency_sha256"])
        self.update_journal(journal, record)
        path.unlink()
        path.write_bytes(source)
        path.chmod(0o600)
        third = self.impact()
        self.assertEqual(third["state"], "File Mapping")
        self.assertNotEqual(first["dependency_sha256"], third["dependency_sha256"])
        self.pool.write_text(self.pool.read_text().replace(
            "/tmp/php-cgi-85.sock", "/tmp/different.sock"))
        self.assertEqual(self.impact()["state"], "Needs Review")

    def test_healthy_selected_and_peer_cache_audit_with_owned_status(self):
        initial = self.audit()
        self.assertEqual(initial["state"], "Partial", initial)
        self.assertEqual(initial["unresolved_other_sites"], 1)  # static site
        self.owned(3, "404")
        self.owned(6, "502")
        healthy = self.audit()
        self.assertEqual(healthy["state"], "Partial", healthy)  # static is unsupported
        self.assertEqual(healthy["unresolved_other_sites"], 1)
        self.assertNotEqual(healthy["source_sha256"], initial["source_sha256"])
        self.assertEqual(healthy["zone_state"], initial["zone_state"])
        path = self.vhosts / "extension" / "wp-b.test" / "ach_customizer_6_502.conf"
        path.write_bytes(path.read_bytes() + b"proxy_pass http://elsewhere;\n")
        damaged = self.audit()
        self.assertEqual(damaged["state"], "Partial")
        self.assertEqual(damaged["unresolved_other_sites"], 2)

    def test_apply_then_owned_status_then_fresh_explicit_fpm_rollback(self):
        import ach_customizer_fpm_apply as core
        original = self.pool.read_bytes()
        hooks = lambda _v, _d: (lambda: None, lambda: None, lambda: None)
        control = workflow.ManualFpmWorkflow(
            public=self.panel, config_root=self.php_root, data_dir=self.data,
            state_reader=lambda: {
                "revision": 0, "enabled": True,
                "modules": {"php_fpm_file_preview": True}},
            impact_lookup=lambda panel, version, source: self.impact(),
            hooks_factory=hooks)
        flask = types.ModuleType("flask")
        flask.session = {"uid": 1, "login": True}
        flask.request = types.SimpleNamespace(method="POST")
        flask.has_request_context = lambda: True
        arguments = {
            "php_version": "85", "max_children": "80", "start_servers": "10",
            "min_spare_servers": "10", "max_spare_servers": "30",
            "max_requests": "1000"}
        with patch.dict(sys.modules, {"flask": flask}):
            preview = control.prepare(arguments)
            apply_args = {
                **arguments, "approved_scope": workflow.APPROVAL_SCOPE,
                "expected_revision": str(preview["monitor_revision"]),
                "expected_before": preview["plan"]["before_sha256"],
                "expected_after": preview["plan"]["after_sha256"],
                "expected_impact": preview["impact_sha256"]}
            applied = control.apply(apply_args)
            self.assertEqual(applied["state"], "Applied")
            self.owned(6, "502")
            prior = control.recovery({"php_version": "85"})
            self.assertTrue(prior["safe_rollback_file_match"])
            self.assertTrue(prior.get("recovery_decision_sha256"), prior)
            # A later source change invalidates the old approval, not recovery itself.
            path, _, _, _ = self.owned(3, "404")
            fresh = control.recovery({"php_version": "85"})
            self.assertNotEqual(prior["impact_sha256"], fresh["impact_sha256"])
            path.write_bytes(path.read_bytes() + b"include /tmp/foreign;\n")
            damaged = control.recovery({"php_version": "85"})
            self.assertIsNone(damaged.get("recovery_decision_sha256"))
            self.assertEqual(damaged["shared_impact"]["state"], "Needs Review")
            path.write_bytes(status._include(
                "404", self.owned_asset(3, "404"), self.owned_op(3, "404")))
            # The caller must inspect and approve the new exact recovery decision.
            recovered = control.recovery({"php_version": "85"})
            self.assertTrue(recovered.get("recovery_decision_sha256"), recovered)
            rolled = control.rollback({
                "php_version": "85", "approved_scope": workflow.APPROVAL_SCOPE,
                "operation_id": applied["operation_id"],
                "expected_recovery": recovered["recovery_decision_sha256"],
                "expected_impact": recovered["impact_sha256"]})
            self.assertEqual(rolled["state"], "Rolled Back")
            self.assertEqual(self.pool.read_bytes(), original)
            self.assertEqual(core.recovery_status(self.php_root, self.data, "85")["state"],
                             "No Recovery")

    def owned_asset(self, site_id, code):
        record = json.loads((self.data / status._record_name(site_id, code)).read_text())
        return record["asset_path"]

    def owned_op(self, site_id, code):
        record = json.loads((self.data / status._record_name(site_id, code)).read_text())
        return record["op"]


if __name__ == "__main__":
    unittest.main()
