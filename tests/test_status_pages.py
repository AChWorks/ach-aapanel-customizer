"""Source-pinned, offline white-label Status Pages preview and preference tests."""
import hashlib
import importlib.util
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
from ach_customizer_status_pages import (
    ASSETS_DIR, BRAND_KEYS, DEFAULT_BRAND, LOCALES, PAGES, STATE_FILE,
    StatusPageError, _contrast, _semantic_palette, read_preferences, render_page,
    select_brand, update_preferences, validate_brand,
)

SPEC = importlib.util.spec_from_file_location("status_endpoint", PLUGIN / "ach_customizer_main.py")
API = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)


def customized(name, domain="example.test", **extra):
    values = dict(DEFAULT_BRAND, brand_name=name, tagline="HELP TEAM",
                  brand_url="https://" + domain, brand_label=domain,
                  accent="#0060a0", footer_enabled=False)
    values.update(extra)
    return values


class RenderTests(unittest.TestCase):
    def test_all_22_original_assets_retain_exact_reference_sha256(self):
        manifest = json.loads((ASSETS_DIR / "manifest.json").read_text())
        self.assertEqual(manifest["reference_commit"],
                         "6c9412f3b220a563b64b82ce3d8ee65ff324fbbe")
        self.assertEqual(len(manifest["assets"]), 22)
        self.assertEqual(set(manifest["assets"]), {
            f"{locale}/{page}.html" for locale in LOCALES for page in PAGES
        })
        for path, digest in manifest["assets"].items():
            raw = (ASSETS_DIR / path).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
            lang, filename = path.split("/")
            preview = render_page(lang, filename[:-5])
            self.assertEqual(preview["html"].encode("utf-8"), raw)
            self.assertEqual(preview["rendered_sha256"], digest)
            self.assertFalse(preview["changed"])
            self.assertIn(f'lang="{lang}"', preview["html"])
            self.assertIn('dir="rtl"' if lang == "fa" else 'dir="ltr"',
                          preview["html"])
            self.assertNotIn("<script", preview["html"].lower())
            self.assertNotIn("<link", preview["html"].lower())

    def test_white_label_both_locales_no_residual_forced_marketing(self):
        for lang in LOCALES:
            for page in PAGES:
                preview = render_page(lang, page, customized("Acme & <HQ>"))
                content = preview["html"]
                self.assertTrue(preview["changed"])
                self.assertNotIn("ACh", content)
                self.assertNotIn("ACH /", content)
                self.assertNotIn("ach.li", content)
                self.assertIn("Acme &amp; &lt;HQ&gt;", content)
                self.assertIn("https://example.test", content)
                self.assertIn("#0060a0", content)
                self.assertIn('class="brand-sub">HELP TEAM', content)
                self.assertNotIn('<footer class="bottom">', content)
                if page == "404":
                    self.assertIn('class="button" href="/"', content)
                self.assertEqual(len(preview["rendered_sha256"]), 64)

    def test_other_brand_in_footer_when_enabled_and_404_home_stays_local(self):
        brand = customized("Example", "brand.example", footer_enabled=True)
        for lang in LOCALES:
            page = render_page(lang, "404", brand)["html"]
            self.assertIn('href="/"', page)
            self.assertIn('href="https://brand.example"', page)
            self.assertIn('brand.example &nearr;', page)
            self.assertNotIn("ach.li", page)

    def test_required_01_light_and_dark_custom_semantic_palette_on_every_page(self):
        # Exact contrast failure from independent review: old renderer
        # accepted white button text on a white button and dark low-contrast
        # fixed secondary labels over black.
        themes = (
            customized("Dark Verified", accent="#ffff00",
                       background="#000000", foreground="#ffffff",
                       footer_enabled=True),
            customized("Light Verified", accent="#125b9b",
                       background="#ffffff", foreground="#181818",
                       footer_enabled=True),
            customized("Dark Navy", accent="#f0c940",
                       background="#101820", foreground="#e4f5f0",
                       footer_enabled=True),
            customized("Low Accent", accent="#00969c",
                       background="#f4f2eb", foreground="#0b1718",
                       footer_enabled=True),
        )
        expected = {
            "muted", "link", "line", "button_bg", "button_text", "button_hover",
            "visual_a", "visual_b", "visual_ink", "grid", "halo",
        }
        for theme in themes:
            resolved = validate_brand(theme)
            palette = _semantic_palette(resolved)
            self.assertEqual(set(palette), expected)
            self.assertGreaterEqual(_contrast(theme["foreground"], theme["background"]), 4.5)
            self.assertGreaterEqual(_contrast(theme["accent"], theme["background"]), 3.0)
            for element in ("muted", "link"):
                self.assertGreaterEqual(
                    _contrast(palette[element], theme["background"]), 4.5,
                    (theme["brand_name"], element))
            self.assertGreaterEqual(_contrast(palette["line"], theme["background"]), 3.0)
            for button in ("button_bg", "button_hover"):
                self.assertGreaterEqual(
                    _contrast(palette[button], palette["button_text"]), 4.5,
                    (theme["brand_name"], button))
            for surface in ("visual_a", "visual_b"):
                self.assertGreaterEqual(
                    _contrast(palette[surface], palette["visual_ink"]), 4.5,
                    (theme["brand_name"], surface))
            self.assertGreaterEqual(_contrast(theme["accent"], theme["background"]), 3.0)
            for locale in LOCALES:
                for name in PAGES:
                    with self.subTest(theme=theme["brand_name"], locale=locale, page=name):
                        rendered = render_page(locale, name, theme)
                        self.assertTrue(rendered["changed"])
                        self.assertIn("Derived accessible semantic colors", rendered["html"])
                        self.assertIn("--ach-link:" + palette["link"], rendered["html"])
                        self.assertIn("--ach-button-text:" + palette["button_text"], rendered["html"])
                        self.assertIn("--ach-button-hover:" + palette["button_hover"], rendered["html"])
                        self.assertIn("--ach-visual-a:" + palette["visual_a"], rendered["html"])
                        self.assertIn(".button:hover{background:var(--ach-button-hover)", rendered["html"])
                        self.assertIn(".visual-top,.visual-bottom,.orbit-mark{color:var(--ach-visual-ink)",
                                      rendered["html"])
                        self.assertIn(".eyebrow,.secondary,.bottom a{color:var(--ach-link)",
                                      rendered["html"])
                        self.assertIn(".button:focus-visible{outline-color:var(--accent)", rendered["html"])
                        self.assertIn(f'lang="{locale}"', rendered["html"])
                        self.assertIn('dir="rtl"' if locale == "fa" else 'dir="ltr"',
                                      rendered["html"])
                        self.assertEqual(
                            rendered["rendered_sha256"],
                            hashlib.sha256(rendered["html"].encode("utf-8")).hexdigest())
                        self.assertNotIn("<script", rendered["html"].lower())
                        self.assertNotIn("https://ach.li", rendered["html"])
                        self.assertNotIn("ACh", rendered["html"])

    def test_required_01_reviewer_exact_dark_failure_is_corrected(self):
        theme = customized("Example", "example.test", accent="#ffff00",
                           background="#000000", foreground="#ffffff",
                           footer_enabled=True)
        palette = _semantic_palette(validate_brand(theme))
        self.assertNotEqual(palette["button_bg"], palette["button_text"])
        self.assertEqual(palette["button_bg"], "#ffffff")
        self.assertEqual(palette["button_text"], "#000000")
        self.assertGreaterEqual(_contrast(palette["muted"], "#000000"), 4.5)
        self.assertGreaterEqual(_contrast(palette["link"], "#000000"), 4.5)
        for locale in LOCALES:
            response = render_page(locale, "404", theme)
            self.assertEqual(response["source_sha256"],
                             hashlib.sha256((ASSETS_DIR / locale / "404.html").read_bytes()).hexdigest())
            self.assertNotEqual(response["source_sha256"], response["rendered_sha256"])
            self.assertIn('href="/"', response["html"])
            self.assertIn("color:var(--ach-button-text)", response["html"])
            self.assertIn("--ach-button-text:#000000", response["html"])
            self.assertIn("--ach-link:#ffff00", response["html"])

    def test_required_01_random_valid_palettes_keep_semantic_contrast(self):
        import random

        rng = random.Random(190311)
        accepted = 0
        for _ in range(2500):
            fg, bg, accent = (
                f"#{rng.randrange(1 << 24):06x}" for _ in range(3)
            )
            if _contrast(fg, bg) < 4.5 or _contrast(accent, bg) < 3.0:
                continue
            brand = validate_brand(dict(DEFAULT_BRAND, foreground=fg,
                                        background=bg, accent=accent))
            colors = _semantic_palette(brand)
            for name in ("muted", "link"):
                self.assertGreaterEqual(_contrast(colors[name], bg), 4.5)
            for name in ("button_bg", "button_hover"):
                self.assertGreaterEqual(_contrast(colors[name], colors["button_text"]), 4.5)
            for name in ("visual_a", "visual_b"):
                self.assertGreaterEqual(_contrast(colors[name], colors["visual_ink"]), 4.5)
            accepted += 1
        self.assertGreaterEqual(accepted, 100)

    def test_required_01_effective_palette_changes_digest_without_editing_source(self):
        original = (ASSETS_DIR / "en" / "404.html").read_bytes()
        first = customized("Acme", accent="#125b9b",
                           background="#ffffff", foreground="#181818")
        second = dict(first, accent="#004488")
        a = render_page("en", "404", first)
        b = render_page("en", "404", second)
        self.assertNotEqual(a["rendered_sha256"], b["rendered_sha256"])
        self.assertEqual(a["source_sha256"], b["source_sha256"])
        self.assertEqual(hashlib.sha256(original).hexdigest(), a["source_sha256"])
        self.assertEqual((ASSETS_DIR / "en" / "404.html").read_bytes(), original)

    def test_reject_invalid_page_and_unsafe_brand_inputs(self):
        for lang, page in (("../", "404"), ("en", "../404"), ("fr", "404"),
                           ("en", "404.html"), ("en", "404/../../")):
            with self.assertRaises(StatusPageError):
                render_page(lang, page)
        for url in ("javascript:alert(1)", "data:text/html,x", "http://evil.test",
                    "https://a.test/path\r\nX:test", "https://a.test/%0D%0Aevil",
                    "https://x.test/?q=\"onmouseover=", "https://user@host.test",
                    "https://host.test:99999/"):
            with self.subTest(url=url), self.assertRaises(StatusPageError):
                validate_brand(customized("E", brand_url=url))
        for color in ("red", "#fff", "#ff0';evil", "#1234567"):
            with self.subTest(color=color), self.assertRaises(StatusPageError):
                validate_brand(customized("E", accent=color))
        for name in ("a\r\nb", "a\u202eb"):
            with self.assertRaises(StatusPageError):
                validate_brand(customized(name))
        with self.assertRaises(StatusPageError):
            validate_brand(customized("E", foreground="#ffffff", background="#ffffff"))
        with self.assertRaises(StatusPageError):
            validate_brand(customized("E", accent="#009da4"))

    def test_escaping_does_not_inject_html_markup_attributes_or_scripts(self):
        custom = customized('"><script>alert(1)</script>&"')
        result = render_page("en", "404", custom)["html"]
        self.assertNotIn('<script>alert(1)</script>', result)
        self.assertNotIn('"><script', result)
        self.assertIn('&lt;script&gt;', result)
        self.assertIn('&quot;', result)

    def test_missing_or_symlinked_bundled_asset_is_rejected(self):
        import ach_customizer_status_pages as mod
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "en").mkdir()
            (directory / "en" / "404.html").symlink_to(ASSETS_DIR / "en" / "404.html")
            with patch.object(mod, "ASSETS_DIR", directory), self.assertRaises(OSError):
                render_page("en", "404")


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-status-pages-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def change(self, scope, site_id, revision, values=None, action="save"):
        return update_preferences(scope=scope, site_id=site_id, action=action,
                                  values=values, expected_revision=revision,
                                  directory=self.dir)

    def test_default_reads_never_create_state_file(self):
        defaults = read_preferences(self.dir)
        self.assertEqual(defaults["global"], DEFAULT_BRAND)
        self.assertEqual(defaults["revision"], 0)
        self.assertEqual(defaults["sites"], {})
        self.assertFalse((self.dir / STATE_FILE).exists())

    def test_global_and_two_site_overrides_are_independent(self):
        g1 = customized("Global", "global.test")
        g2 = customized("New Global", "new-global.test")
        s1 = customized("Site One", "site-one.test")
        s2 = customized("Site Two", "site-two.test")
        first, changed = self.change("global", None, 0, g1)
        self.assertTrue(changed)
        self.assertEqual(first["revision"], 1)
        with self.assertRaises(StatusPageError):
            self.change("global", None, 0, g2)
        first, changed = self.change("site", 7, 1, s1)
        second, changed = self.change("site", 8, 2, s2)
        self.assertEqual(second["revision"], 3)
        updated, changed = self.change("global", None, 3, g2)
        self.assertEqual(select_brand(updated, 7)[0]["brand_name"], "Site One")
        self.assertEqual(select_brand(updated, 8)[0]["brand_name"], "Site Two")
        self.assertEqual(select_brand(updated, 9)[0]["brand_name"], "New Global")
        updated, changed = self.change("site", 7, 4, action="reset")
        self.assertTrue(changed)
        self.assertEqual(select_brand(updated, 7)[1], "Global default")
        self.assertEqual(select_brand(updated, 8)[0]["brand_name"], "Site Two")
        _, changed = self.change("site", 7, 5, action="reset")
        self.assertFalse(changed, "Idempotent reset must not increase revision")
        again = read_preferences(self.dir)
        self.assertEqual(again["revision"], 5)
        stat_info = (self.dir / STATE_FILE).stat()
        self.assertEqual(stat_info.st_mode & 0o777, 0o600)
        self.assertEqual(stat_info.st_uid, os.geteuid())

    def test_state_file_symlink_and_malformed_values_fail_closed(self):
        path = self.dir / STATE_FILE
        other = self.dir / "unowned"
        other.write_text("no")
        path.symlink_to(other)
        with self.assertRaises(StatusPageError):
            read_preferences(self.dir)
        path.unlink()
        path.write_text("{}")
        path.chmod(0o600)
        with self.assertRaises(StatusPageError):
            read_preferences(self.dir)
        self.assertEqual(path.read_text(), "{}")

    def test_unsupported_scope_and_extra_keys_are_rejected_without_write(self):
        for scope, site in (("other", None), ("global", 7), ("site", None)):
            with self.subTest(scope=scope, site=site), self.assertRaises(StatusPageError):
                self.change(scope, site, 0, DEFAULT_BRAND)
        with self.assertRaises(StatusPageError):
            self.change("global", None, 0, dict(DEFAULT_BRAND, html="<script>"))
        self.assertFalse((self.dir / STATE_FILE).exists())


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-status-entry-")
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(API, "_STATE_DIR", self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.plugin = API.ach_customizer_main()

    def _native_public(self, accepted=(7, 8)):
        obj = types.ModuleType("public")
        class Query:
            def where(self, clause, values):
                assert clause == "id=?"
                self.ident = values[0]
                return self
            def field(self, names):
                assert names == "id,name,path,status"
                return self
            def find(self):
                if self.ident not in accepted:
                    return {}
                return {"id":self.ident,"name":f"site-{self.ident}.test",
                        "path":f"/www/wwwroot/site-{self.ident}.test","status":"1"}
        obj.M = lambda table: Query() if table == "sites" else None
        return obj

    def test_preview_and_native_site_lookup_are_read_only(self):
        with patch.dict(sys.modules, {"public":self._native_public()}):
            default = self.plugin.status_preview({"locale":"fa","template":"404"})
            self.assertTrue(default["status"], default)
            self.assertFalse(default["apply_supported"])
            self.assertTrue(default["html"].startswith("<!doctype html>"))
            self.assertFalse((Path(self.tmp.name) / STATE_FILE).exists())
            good = self.plugin.status_preferences({"site_id":"7"})
            self.assertTrue(good["status"], good)
            self.assertEqual(good["site_id"], 7)
            # A customized dark palette is previewed through the deployed
            # native endpoint without a preference or website mutation.
            custom = dict(customized("Example", "example.test", accent="#ffff00",
                                     background="#000000", foreground="#ffffff",
                                     footer_enabled=True),
                          site_id="7", locale="fa", template="404")
            dark = self.plugin.status_preview(custom)
            self.assertTrue(dark["status"], dark)
            self.assertFalse(dark["apply_supported"])
            self.assertEqual(dark["source"], "Unsaved preview")
            self.assertIn("--ach-button-text:#000000", dark["html"])
            self.assertIn("--ach-link:#ffff00", dark["html"])
            self.assertNotEqual(dark["rendered_sha256"], dark["source_sha256"])
            self.assertFalse((Path(self.tmp.name) / STATE_FILE).exists())
            bad = self.plugin.status_preferences({"site_id":"999"})
            self.assertFalse(bad["status"])
            self.assertEqual(bad["stage"], "status_preferences")
            bad2 = self.plugin.status_preview({"site_id":"../", "locale":"en","template":"404"})
            self.assertFalse(bad2["status"])

    def test_save_requires_full_primary_admin_post_and_stale_revision_rejected(self):
        fake_flask = types.ModuleType("flask")
        fake_flask.session = {}
        fake_flask.has_request_context = lambda: fake_flask.request is not None
        fake_flask.request = None
        payload = dict(customized("Acme"), scope="global", site_id="",
                       branding_action="save",expected_revision="0",footer_enabled="false")
        with patch.dict(sys.modules, {"public":self._native_public()}):
            with patch.dict(sys.modules, {"flask":fake_flask}):
                self.assertEqual(self.plugin.status_save(payload)["stage"],"status_authorization")
                for method,logged,uid,temp in (("GET",True,1,False),("POST",True,2,False),
                                               ("POST",True,1,True),("POST",False,1,False)):
                    fake_flask.request = types.SimpleNamespace(method=method)
                    fake_flask.session = dict(login=logged,uid=uid,tmp_login=temp)
                    r=self.plugin.status_save(payload)
                    self.assertFalse(r["status"])
                    self.assertEqual(r["stage"],"status_authorization")
                self.assertFalse((Path(self.tmp.name)/STATE_FILE).exists())
                fake_flask.request = types.SimpleNamespace(method="POST")
                fake_flask.session = dict(login=True,uid=1)
                # Native aaPanel merges request.form AFTER request.args. Its
                # routing field `action=a` must never be replaced by `action=save`.
                missing_branding_action = dict(payload, action="save")
                missing_branding_action.pop("branding_action")
                self.assertEqual(self.plugin.status_save(missing_branding_action)["stage"],
                                 "status_settings")
                first=self.plugin.status_save(payload)
                self.assertTrue(first["status"],first)
                self.assertEqual(first["revision"],1)
                self.assertTrue(first["changed"])
                self.assertEqual(self.plugin.status_save(payload)["stage"],"status_settings")
                reread=self.plugin.status_preferences({})
                self.assertEqual(reread["effective"]["brand_name"],"Acme")
            self.assertEqual(read_preferences(self.tmp.name)["revision"],1)

    def test_branding_save_and_reset_have_distinct_activity_actions(self):
        from ach_customizer_activity import read_activity
        flask = types.ModuleType("flask")
        flask.request = types.SimpleNamespace(method="POST")
        flask.session = dict(login=True, uid=1)
        flask.has_request_context = lambda: True
        payload = dict(customized("QA Brand"), scope="global", site_id="",
                       branding_action="save", expected_revision="0")
        with patch.dict(sys.modules, {"public": self._native_public(),
                                      "flask": flask}):
            saved = self.plugin.status_save(payload)
            self.assertTrue(saved["status"], saved)
            self.assertEqual(saved["revision"], 1)
            reset = self.plugin.status_save(dict(payload, branding_action="reset",
                                                 expected_revision="1"))
            self.assertTrue(reset["status"], reset)
            self.assertEqual(reset["revision"], 2)
            self.assertIn("reset", reset["message"].lower())
        actions = [row["action"] for row in read_activity(self.tmp.name, module="status_pages")]
        self.assertEqual(actions[:2], ["status_reset", "status_save"])
        self.assertEqual(read_preferences(self.tmp.name)["revision"], 2)



if __name__ == "__main__":
    unittest.main()
