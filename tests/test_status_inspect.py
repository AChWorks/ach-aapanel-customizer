"""Read-only site-file/Nginx source comparison and protected native endpoint."""
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PACKAGE))
import ach_customizer_status_inspect as inspection
import ach_customizer_main as backend
from ach_customizer_status_pages import render_page

SHA = "a" * 64


class SiteSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vhosts = self.root / "vhost" / "nginx"
        self.vhosts.mkdir(parents=True)
        self.document_root = self.root / "websites" / "demo.test"
        self.document_root.mkdir(parents=True)
        self.key = "demo.test"
        self.site = dict(id=7, name=self.key, path=str(self.document_root), status="1")
        self.vhost = self.vhosts / (self.key + ".conf")
        self.set_vhost()
        patcher = patch.object(inspection, "VHOST_ROOT", str(self.vhosts))
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_vhost(self, extra=""):
        self.vhost.write_text(
            "server {\n  listen 80;\n  server_name demo.test;\n" +
            "  include " + str(self.vhosts) + "/extension/demo.test/*.conf;\n" +
            extra + "\n}\n", encoding="utf-8")

    def scan(self, page="404", locale="en", digest=SHA, rendered_html=None):
        return inspection.inspect_site_files(
            self.site, locale=locale, template=page,
            rendered_sha256=digest, rendered_html=rendered_html,
            vhost_root=str(self.vhosts))

    def test_missing_document_page_and_textual_include_never_claim_runtime(self):
        before = self.vhost.read_bytes()
        r = self.scan()
        self.assertEqual(r["state"], "Unmanaged")
        self.assertEqual(r["page_file_state"], "Absent")
        self.assertTrue(r["extension_include_textual"])
        self.assertFalse(r["nginx_runtime_verified"])
        self.assertFalse(r["apply_supported"])
        self.assertTrue(r["read_only"])
        self.assertEqual(r["vhost_sha256"], hashlib.sha256(before).hexdigest())
        self.assertFalse((self.document_root / "404.html").exists())
        self.assertEqual(self.vhost.read_bytes(), before)

    def test_match_is_only_content_match_and_never_installed_claim(self):
        file = self.document_root / "404.html"
        content = b"<html>known local 404</html>"
        file.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        result = self.scan(digest=digest)
        self.assertEqual(result["state"], "File Match")
        self.assertEqual(result["page_file_state"], "Same bytes")
        self.assertEqual(result["page_file_bytes"], len(content))
        self.assertFalse(result["nginx_runtime_verified"])
        self.assertIn("not verified", result["reason"])
        self.assertEqual(file.read_bytes(), content)
        changed = self.scan(digest=SHA)
        self.assertEqual(changed["state"], "Conflict")
        self.assertEqual(changed["page_file_state"], "Different bytes")
        self.assertEqual(file.read_bytes(), content)

    def test_vhost_and_extension_error_page_conflict_without_reading_external_contents(self):
        self.set_vhost("  error_page 404 /old-404.html;")
        r = self.scan()
        self.assertEqual(r["state"], "Conflict")
        self.assertEqual(r["error_page_sources"], ["site VHost"])
        self.set_vhost()
        extension = self.vhosts / "extension" / self.key
        extension.mkdir(parents=True)
        (extension / "site_total.conf").write_text("location /x { return 200; }\n")
        (extension / "operator.conf").write_text("error_page 502 /custom.html;\n")
        r = self.scan(page="502")
        self.assertEqual(r["state"], "Conflict")
        self.assertEqual(r["error_page_sources"], ["extension/operator.conf"])
        self.assertEqual(r["extensions_scanned"], ["operator.conf", "site_total.conf"])
        self.assertFalse(r["nginx_runtime_verified"])

    def test_comment_does_not_imply_extension_or_error_page(self):
        self.vhost.write_text(
            "server {\n# include " + str(self.vhosts) +
            "/extension/demo.test/*.conf;\n# error_page 404 /legacy.html;\n}\n")
        r = self.scan()
        self.assertEqual(r["state"], "Needs Review")
        self.assertFalse(r["extension_include_textual"])
        self.assertEqual(r["error_page_sources"], [])

    def test_missing_vhost_is_unsupported_not_success(self):
        self.vhost.unlink()
        r = self.scan()
        self.assertEqual(r["state"], "Unsupported")
        self.assertIsNone(r["vhost_sha256"])
        self.assertFalse(r["nginx_runtime_verified"])

    def test_symlinked_files_and_ancestors_fail_closed(self):
        external = self.root / "other"
        external.write_text("not a site file")
        (self.document_root / "404.html").symlink_to(external)
        r = self.scan()
        self.assertEqual(r["state"], "Needs Review")
        self.assertIsNone(r["vhost_sha256"])
        (self.document_root / "404.html").unlink()
        linked_path = self.root / "alias"
        linked_path.symlink_to(self.document_root, target_is_directory=True)
        self.site["path"] = str(linked_path)
        r = self.scan()
        self.assertEqual(r["state"], "Needs Review")
        self.assertIsNone(r["page_file_sha256"])

    def test_linked_extension_fragment_and_oversized_vhost_are_uncertain(self):
        folder = self.vhosts / "extension" / self.key
        folder.mkdir(parents=True)
        (folder / "untrusted.conf").symlink_to(self.vhost)
        self.assertEqual(self.scan()["state"], "Needs Review")
        (folder / "untrusted.conf").unlink()
        self.vhost.write_text("x" * (inspection.MAX_FILE_BYTES + 1))
        r = self.scan()
        self.assertEqual(r["state"], "Needs Review")
        self.assertIsNone(r["vhost_sha256"])

    def test_extension_count_is_bounded_and_no_partial_positive_claims(self):
        folder = self.vhosts / "extension" / self.key
        folder.mkdir(parents=True)
        for i in range(inspection.MAX_EXTENSIONS + 1):
            (folder / f"fragment-{i:02d}.conf").write_text("listen 80;")
        r = self.scan()
        self.assertEqual(r["state"], "Needs Review")
        self.assertEqual(r["extensions_scanned"], [])
        self.assertIsNone(r["vhost_sha256"])

    def test_invalid_input_prevents_arbitrary_paths_or_pages(self):
        for item in ("../../etc/shadow", "bad/x", "x"*256, ""):
            self.site["name"] = item
            with self.assertRaises(inspection.StatusInspectError):
                self.scan()
        self.site["name"] = self.key
        for item in ("404/../../etc", "new-site", "503"):
            with self.assertRaises(inspection.StatusInspectError):
                self.scan(page=item)
        with self.assertRaises(inspection.StatusInspectError):
            self.scan(digest="not-sha")
        self.site["path"] = "/tmp/../etc"
        self.assertEqual(self.scan()["state"], "Needs Review")

    def test_a_separate_site_and_unrelated_content_are_preserved(self):
        other_root = self.root / "websites" / "other.test"
        other_root.mkdir()
        other_file = other_root / "404.html"
        other_file.write_bytes(b"owner-defined page")
        digest = hashlib.sha256(other_file.read_bytes()).hexdigest()
        r = self.scan()
        self.assertEqual(r["site_id"], 7)
        self.assertEqual(r["page_file_state"], "Absent")
        self.assertEqual(hashlib.sha256(other_file.read_bytes()).hexdigest(), digest)

    def test_rendered_bundle_sha_can_be_compared_to_disk(self):
        rendered = render_page("fa", "404")
        (self.document_root / "404.html").write_text(rendered["html"], encoding="utf-8")
        r = self.scan(page="404", locale="fa", digest=rendered["rendered_sha256"])
        self.assertEqual(r["page_file_state"], "Same bytes")
        self.assertEqual(r["rendered_sha256"], rendered["source_sha256"])
        self.assertFalse(r["nginx_runtime_verified"])


    def test_new_file_readonly_comparison_preserves_document_root(self):
        preview = render_page("en", "404")
        result = self.scan(digest=preview["rendered_sha256"],
                           rendered_html=preview["html"])
        comparison = result["comparison"]
        self.assertEqual(comparison["state"], "New File")
        self.assertEqual(comparison["old_lines"], 0)
        self.assertGreater(comparison["new_lines"], 40)
        self.assertEqual(comparison["excerpt"], "")
        self.assertFalse(comparison["truncated"])
        self.assertEqual(result["page_file_state"], "Absent")
        self.assertFalse((self.document_root / "404.html").exists())
        self.assertFalse(result["apply_supported"])

    def test_identical_preview_bytes_have_no_false_change(self):
        preview = render_page("fa", "502")
        target = self.document_root / "502.html"
        target.write_bytes(preview["html"].encode("utf-8"))
        before = target.read_bytes()
        result = self.scan(page="502", locale="fa",
                           digest=preview["rendered_sha256"],
                           rendered_html=preview["html"])
        self.assertEqual(result["comparison"]["state"], "Identical")
        self.assertEqual(result["comparison"]["excerpt"], "")
        self.assertEqual(result["comparison"]["old_lines"],
                         result["comparison"]["new_lines"])
        self.assertEqual(target.read_bytes(), before)

    def test_different_html_yields_bounded_plain_text_excerpt(self):
        current = (b"<!doctype html>\n<html><body>\n"
                   b"<script>alert('existing')</script>\n</body></html>\n")
        target = self.document_root / "404.html"
        target.write_bytes(current)
        proposed = '<!doctype html>\n<html><body>\n<p>Safe preview</p>\n</body></html>\n'
        digest = hashlib.sha256(proposed.encode("utf-8")).hexdigest()
        result = self.scan(digest=digest, rendered_html=proposed)
        comp = result["comparison"]
        self.assertEqual(comp["state"], "Different")
        self.assertFalse(comp["truncated"])
        self.assertIn("--- current 404.html", comp["excerpt"])
        self.assertIn("+++ proposed 404.html", comp["excerpt"])
        self.assertIn("<script>alert('existing')</script>", comp["excerpt"])
        self.assertIn("<p>Safe preview</p>", comp["excerpt"])
        self.assertLessEqual(len(comp["excerpt"]), inspection.MAX_COMPARE_EXCERPT)
        self.assertEqual(target.read_bytes(), current)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["nginx_runtime_verified"])

    def test_untrusted_or_huge_current_content_does_not_produce_diff(self):
        proposed = "<html>candidate</html>\n"
        digest = hashlib.sha256(proposed.encode()).hexdigest()
        target = self.document_root / "404.html"
        for contents, expected in [
            (b"\x00MALFORMED", "Control"),
            (b"\xff\xfe", "UTF-8"),
            (b"q" * (inspection.MAX_COMPARE_BYTES + 1), "text-diff limit"),
            (b"row\n" * (inspection.MAX_COMPARE_LINES + 1), "line-diff limit"),
            ("\u202epretend safe".encode("utf-8"), "Control"),
        ]:
            with self.subTest(contents=contents[:20]):
                target.write_bytes(contents)
                result = self.scan(digest=digest, rendered_html=proposed)
                self.assertEqual(result["comparison"]["state"], "Unavailable")
                self.assertEqual(result["comparison"]["excerpt"], "")
                self.assertIn(expected, result["comparison"]["reason"])
                self.assertEqual(target.read_bytes(), contents)
                self.assertFalse(result["apply_supported"])

    def test_large_changed_html_diff_is_clipped_and_marked_display_only(self):
        current = "<html>\n" + "".join(f"<p>{i} OLD</p>\n" for i in range(220)) + "</html>\n"
        proposed = "<html>\n" + "".join(f"<p>{i} NEW</p>\n" for i in range(220)) + "</html>\n"
        self.assertLess(len(current.encode()), inspection.MAX_COMPARE_BYTES)
        (self.document_root / "404.html").write_text(current, encoding="utf-8")
        digest = hashlib.sha256(proposed.encode()).hexdigest()
        compared = self.scan(digest=digest, rendered_html=proposed)["comparison"]
        self.assertEqual(compared["state"], "Different")
        self.assertTrue(compared["truncated"])
        self.assertLessEqual(len(compared["excerpt"]), inspection.MAX_COMPARE_EXCERPT)
        self.assertIn("display-only", compared["reason"])
        self.assertEqual(compared["old_lines"], 222)
        self.assertEqual(compared["new_lines"], 222)

    def test_multibyte_persian_text_cannot_exceed_the_actual_response_byte_cap(self):
        old = "<html>\n" + "".join("<p>" + "قدیمی" * 8 + "</p>\n" for _ in range(140)) + "</html>\n"
        new = "<html>\n" + "".join("<p>" + "جدید" * 10 + "</p>\n" for _ in range(140)) + "</html>\n"
        self.assertLess(len(old.encode()), inspection.MAX_COMPARE_BYTES)
        self.assertLess(len(new.encode()), inspection.MAX_COMPARE_BYTES)
        (self.document_root / "404.html").write_bytes(old.encode("utf-8"))
        result = self.scan(digest=hashlib.sha256(new.encode()).hexdigest(),
                           rendered_html=new)
        comparison = result["comparison"]
        self.assertEqual(comparison["state"], "Different")
        self.assertTrue(comparison["truncated"])
        self.assertLessEqual(len(comparison["excerpt"].encode("utf-8")),
                             inspection.MAX_COMPARE_EXCERPT)
        self.assertIn("--- current 404.html", comparison["excerpt"])

    def test_changed_filename_binding_refuses_stale_file_excerpt(self):
        # Independent proof of the pathname check, even when a valid open FD
        # and both fstat reads appear unchanged.
        current = self.document_root / "404.html"
        different = self.document_root / "replacement.html"
        current.write_text("<html>old site markup</html>")
        different.write_text("<html>replacement</html>")
        proposed = "<html>proposed</html>\n"
        real_stat = os.stat

        def changed_path(path, *args, **kwargs):
            if path == "404.html" and kwargs.get("dir_fd") is not None:
                self.assertFalse(kwargs.get("follow_symlinks", True))
                return real_stat(different)
            return real_stat(path, *args, **kwargs)

        with patch.object(inspection.os, "stat", side_effect=changed_path):
            result = self.scan(digest=hashlib.sha256(proposed.encode()).hexdigest(),
                               rendered_html=proposed)
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(result["comparison"]["state"], "Unavailable")
        self.assertEqual(result["comparison"]["excerpt"], "")
        self.assertIsNone(result["page_file_sha256"])
        self.assertIn("changed", result["reason"])
        self.assertEqual(current.read_text(), "<html>old site markup</html>")

    def test_oversized_internal_render_never_bypasses_preview_size_contract(self):
        proposed = "<html>" + ("x" * 32768) + "</html>"
        result = self.scan(digest=hashlib.sha256(proposed.encode()).hexdigest(),
                           rendered_html=proposed)
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(result["comparison"]["state"], "Unavailable")
        self.assertIn("offline preview limit", result["reason"])

    def test_mismatched_rendered_digest_never_produces_successful_comparison(self):
        (self.document_root / "404.html").write_text("an owner page")
        result = self.scan(digest=SHA, rendered_html="<html>not this sha</html>")
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(result["comparison"]["state"], "Unavailable")
        self.assertIn("fingerprint", result["reason"])

    def test_symlinked_site_page_never_exposes_an_excerpt(self):
        target = self.root / "elsewhere"
        target.write_text("<html>private content</html>")
        (self.document_root / "404.html").symlink_to(target)
        html = "<html>proposed</html>"
        result = self.scan(digest=hashlib.sha256(html.encode()).hexdigest(),
                           rendered_html=html)
        self.assertEqual(result["state"], "Needs Review")
        self.assertEqual(result["comparison"]["state"], "Unavailable")
        self.assertNotIn("private content", str(result))


class NativeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plugin = backend.ach_customizer_main()
        self.data = Path(self.tmp.name)
        self.record = dict(id=7, name="demo.test", path=str(self.data), status="1")
        self.calls = 0
        patcher = patch.object(backend, "_STATE_DIR", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_public(self, mutate_on_third=False):
        stub = types.ModuleType("public")
        container = self
        class Query:
            def where(self, *args):
                return self
            def field(self, *args):
                return self
            def find(self):
                container.calls += 1
                if mutate_on_third and container.calls == 3:
                    return dict(container.record, path="/moved/other")
                return dict(container.record)
        stub.M = lambda table: Query() if table == "sites" else None
        return stub

    def fake_flask(self, uid=1, method="POST", temp=False):
        stub = types.ModuleType("flask")
        stub.has_request_context = lambda: True
        stub.request = types.SimpleNamespace(method=method)
        stub.session = dict(login=True, uid=uid)
        if temp:
            stub.session["tmp_login"] = True
        return stub

    def test_readonly_inspect_denies_guest_and_temporary_sessions_before_file_access(self):
        for flask in (self.fake_flask(uid=2), self.fake_flask(temp=True),
                      self.fake_flask(method="GET")):
            with patch.dict(sys.modules, {"public": self.fake_public(),
                                          "flask": flask}):
                with patch.object(backend, "inspect_site_files", side_effect=AssertionError("must not read")):
                    result = self.plugin.status_inspect({"site_id": "7", "template": "404", "locale": "en"})
            self.assertFalse(result["status"])
            self.assertEqual(result["stage"], "status_authorization")
        self.assertEqual(self.calls, 0)
        self.assertFalse((self.data / "ach_customizer.status_pages.json").exists())

    def test_primary_admin_inspect_binds_site_identity_and_never_changes_state(self):
        before = dict(self.record)
        response = {"schema": 1, "site_id": 7, "state": "Unmanaged",
                    "read_only": True, "apply_supported": False, "nginx_runtime_verified": False}
        with patch.dict(sys.modules, {"public": self.fake_public(), "flask": self.fake_flask()}):
            with patch.object(backend, "inspect_site_files", return_value=response) as spy:
                r = self.plugin.status_inspect({"site_id": "7", "template": "502", "locale": "fa"})
        self.assertTrue(r["status"], r)
        self.assertEqual(r["revision"], 0)
        self.assertEqual(r["selection_source"], "Global default")
        self.assertEqual(r["site_id"], 7)
        self.assertEqual(spy.call_args.kwargs["template"], "502")
        self.assertEqual(spy.call_args.kwargs["locale"], "fa")
        rendered = render_page("fa", "502")
        self.assertEqual(spy.call_args.kwargs["rendered_html"], rendered["html"])
        self.assertEqual(spy.call_args.kwargs["rendered_sha256"], rendered["rendered_sha256"])
        self.assertEqual(spy.call_args.args[0], before)
        self.assertEqual(self.calls, 3, "Site rechecked after source inspection")
        self.assertFalse((self.data / "ach_customizer.status_pages.json").exists())

    def test_site_change_during_inspection_fails_closed(self):
        with patch.dict(sys.modules, {"public": self.fake_public(mutate_on_third=True),
                                      "flask": self.fake_flask()}):
            with patch.object(backend, "inspect_site_files", return_value={"schema":1}) as spy:
                r = self.plugin.status_inspect({"site_id":"7","template":"404","locale":"en"})
        self.assertFalse(r["status"])
        self.assertEqual(r["stage"], "status_inspect")
        self.assertIn("changed during", r["msg"])
        self.assertEqual(spy.call_count, 1)

    def test_invalid_template_or_site_rejected_before_disk_scan(self):
        with patch.dict(sys.modules, {"public":self.fake_public(), "flask":self.fake_flask()}):
            with patch.object(backend, "inspect_site_files", side_effect=AssertionError("not reached")) as inspector:
                r = self.plugin.status_inspect({"site_id":"7","template":"unbound","locale":"en"})
                s = self.plugin.status_inspect({"site_id":"7/evil","template":"404","locale":"en"})
                inspector.assert_not_called()
        self.assertEqual(r["stage"], "status_inspect")
        self.assertIn("only English/Persian 404/502", r["msg"])
        self.assertEqual(s["stage"], "status_inspect")


if __name__ == "__main__":
    unittest.main()
