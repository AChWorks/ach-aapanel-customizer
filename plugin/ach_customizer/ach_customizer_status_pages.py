"""Offline ACh Status Pages v1: validated branding, deterministic preview, durable preferences.

This module intentionally NEVER installs pages or modifies any website, Nginx,
PHP-FPM, or aaPanel-owned template. It is a self-contained first Status Pages
render/preview slice; any future Apply must have a separately verified adapter.
"""
from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from ach_customizer_state import DATA_DIR, _open_state_dir

ASSETS_DIR = Path(__file__).parent / "status_pages"
LOCALES = ("en", "fa")
PAGES = ("403", "404", "429", "500", "502", "503", "504",
         "50x", "new-site", "stopped", "unbound")
BRAND_KEYS = ("brand_name", "tagline", "brand_url", "brand_label",
              "accent", "background", "foreground", "footer_enabled")
DEFAULT_BRAND = {
    "brand_name": "ACh",
    "tagline": "WEB SYSTEMS",
    "brand_url": "https://ach.li",
    "brand_label": "ach.li",
    "accent": "#008b92",
    "background": "#f4f2eb",
    "foreground": "#0b1718",
    "footer_enabled": True,
}
STATE_FILE = "ach_customizer.status_pages.json"
LOCK_FILE = "ach_customizer.status_pages.lock"
MAX_BYTES = 65536
MAX_SITES = 100
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
TOKEN_RE = re.compile(
    r"https://ach\.li|ach\.li|WEB SYSTEMS|ACh|ACH|#008b92|#f4f2eb|#0b1718"
    r"|#126b70|#235960|#215e61|#0b4143|Thoughtful systems for the web\.|زیرساخت و تجربه وب"
)


class StatusPageError(ValueError):
    pass


def _text(value, key, limit):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise StatusPageError("Invalid " + key + " length")
    if value.strip() != value or any(
            ord(c) < 32 or ord(c) == 127 or c in "\u202a\u202b\u202d\u202e\u202c\u2066\u2067\u2068\u2069"
            for c in value):
        raise StatusPageError("Unsafe " + key)
    return value


def _url(value):
    value = _text(value, "brand_url", 512)
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port  # Raises on malformed port.
    except ValueError as exc:
        raise StatusPageError("Invalid brand URL") from exc
    if (parsed.scheme not in ("https", "http") or not hostname
            or parsed.username is not None or parsed.password is not None
            or any(c.isspace() or ord(c) < 32 for c in value)
            or re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", value, re.I)
            or parsed.fragment or not value.startswith(parsed.scheme + "://")
            or any(x in value for x in ('"', "'", "<", ">", "\\"))):
        raise StatusPageError("Brand URL must be a safe HTTP(S) URL")
    if parsed.scheme == "http" and hostname not in ("localhost", "127.0.0.1", "::1"):
        raise StatusPageError("Non-local brand URLs require HTTPS")
    if not (hostname.encode("idna").decode("ascii") == hostname.lower() or hostname in ("::1",)):
        raise StatusPageError("Use a canonical ASCII/IDNA brand hostname")
    if port is not None and not 1 <= port <= 65535:
        raise StatusPageError("Invalid brand URL port")
    return value


def _rgb(color):
    return tuple(int(color[n:n+2], 16) / 255.0 for n in (1, 3, 5))


def _lightness(color):
    channels = _rgb(color)
    adjusted = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(a*b for a, b in zip(adjusted, (.2126, .7152, .0722)))


def _contrast(first, second):
    high, low = sorted((_lightness(first), _lightness(second)), reverse=True)
    return (high + .05) / (low + .05)


def validate_brand(value):
    if not isinstance(value, dict) or set(value) != set(BRAND_KEYS):
        raise StatusPageError("Branding fields do not match the supported schema")
    result = {
        "brand_name": _text(value["brand_name"], "brand_name", 80),
        "tagline": _text(value["tagline"], "tagline", 120),
        "brand_url": _url(value["brand_url"]),
        "brand_label": _text(value["brand_label"], "brand_label", 100),
    }
    for key in ("accent", "background", "foreground"):
        val = value[key]
        if not isinstance(val, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", val):
            raise StatusPageError("Invalid " + key + " color")
        result[key] = val.lower()
    if type(value["footer_enabled"]) is not bool:
        raise StatusPageError("Invalid footer attribution setting")
    result["footer_enabled"] = value["footer_enabled"]
    if _contrast(result["foreground"], result["background"]) < 4.5:
        raise StatusPageError("Foreground/background contrast is too low")
    # The accent is mainly decorative, but it must remain distinguishable.
    if _contrast(result["accent"], result["background"]) < 3.0:
        raise StatusPageError("Accent/background contrast is too low")
    return result


def _default_state():
    return {"schema": 1, "revision": 0, "global": DEFAULT_BRAND.copy(), "sites": {}}


def _validate_state(state):
    if not isinstance(state, dict) or set(state) != {"schema", "revision", "global", "sites"}:
        raise StatusPageError("Unsupported Status Pages preference schema")
    if type(state["schema"]) is not int or state["schema"] != 1:
        raise StatusPageError("Unsupported Status Pages state version")
    if type(state["revision"]) is not int or not 0 <= state["revision"] <= 2147483647:
        raise StatusPageError("Invalid Status Pages state revision")
    state["global"] = validate_brand(state["global"])
    sites = state["sites"]
    if not isinstance(sites, dict) or len(sites) > MAX_SITES:
        raise StatusPageError("Invalid Status Pages site preferences")
    for key, value in sites.items():
        if not re.fullmatch(r"[1-9][0-9]{0,9}", key) or int(key) > 2147483647:
            raise StatusPageError("Invalid Status Pages site identifier")
        sites[key] = validate_brand(value)
    return state


def _owned_file(fd):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise StatusPageError("Untrusted Status Pages settings file")
    return info


def _load_at(dir_fd):
    try:
        fd = os.open(STATE_FILE, READ_FLAGS, dir_fd=dir_fd)
    except FileNotFoundError:
        return _default_state()
    except OSError as exc:
        raise StatusPageError("Cannot safely open Status Pages settings") from exc
    try:
        info = _owned_file(fd)
        if not 0 < info.st_size <= MAX_BYTES:
            raise StatusPageError("Invalid Status Pages settings size")
        payload = os.read(fd, MAX_BYTES + 1)
        if not payload or len(payload) > MAX_BYTES:
            raise StatusPageError("Status Pages settings read exceeds limit")
        try:
            state = json.loads(payload.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise StatusPageError("Malformed Status Pages settings JSON") from exc
        return _validate_state(state)
    finally:
        os.close(fd)


def read_preferences(directory=DATA_DIR):
    fd = _open_state_dir(directory)
    try:
        return _load_at(fd)
    finally:
        os.close(fd)


def _take_lock(dir_fd):
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        _owned_file(fd)
        deadline = time.monotonic() + 3
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise StatusPageError("Status Pages settings are being updated")
                time.sleep(.05)
    except BaseException:
        os.close(fd)
        raise


def _write_at(dir_fd, state):
    payload = (json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_BYTES:
        raise StatusPageError("Status Pages settings are too large")
    name = ".ach_customizer.status_pages." + uuid4().hex + ".tmp"
    fd = os.open(name, CREATE_FLAGS, 0o600, dir_fd=dir_fd)
    committed = False
    try:
        _owned_file(fd)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(fd)
        os.replace(name, STATE_FILE, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        committed = True
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            raise StatusPageError("Preferences commit uncertain; reload before retry") from exc
    finally:
        os.close(fd)
        if not committed:
            try:
                os.unlink(name, dir_fd=dir_fd)
            except FileNotFoundError:
                pass


def update_preferences(*, scope, site_id, action, expected_revision, values=None, directory=DATA_DIR):
    if action not in ("save", "reset"):
        raise StatusPageError("Unsupported branding action")
    if scope not in ("global", "site"):
        raise StatusPageError("Unsupported branding scope")
    if scope == "site" and (type(site_id) is not int or not 1 <= site_id <= 2147483647):
        raise StatusPageError("Select a valid aaPanel site ID")
    if scope == "global" and site_id is not None:
        raise StatusPageError("Global branding must not include a site ID")
    if type(expected_revision) is not int or not 0 <= expected_revision <= 2147483647:
        raise StatusPageError("Expected branding revision is required")
    brand = validate_brand(values) if action == "save" else None
    directory_fd = _open_state_dir(directory)
    try:
        lock_fd = _take_lock(directory_fd)
        try:
            state = _load_at(directory_fd)
            if state["revision"] != expected_revision:
                raise StatusPageError("Branding was changed elsewhere; reload before saving")
            updated = json.loads(json.dumps(state))
            if scope == "global":
                updated["global"] = brand if brand is not None else DEFAULT_BRAND.copy()
            elif brand is None:
                updated["sites"].pop(str(site_id), None)
            else:
                updated["sites"][str(site_id)] = brand
            _validate_state(updated)
            if state == updated:
                return state, False
            if state["revision"] == 2147483647:
                raise StatusPageError("Branding revision exhausted")
            updated["revision"] += 1
            _write_at(directory_fd, updated)
            return updated, True
        finally:
            os.close(lock_fd)
    finally:
        os.close(directory_fd)


def select_brand(state, site_id=None):
    if site_id is not None and str(site_id) in state["sites"]:
        return state["sites"][str(site_id)].copy(), "Site override"
    return state["global"].copy(), "Global default"


def _asset(locale, page):
    if locale not in LOCALES or page not in PAGES:
        raise StatusPageError("Unknown Status Pages locale or template")
    # Resolve source through a no-follow path walk. Templates remain package-owned,
    # immutable snapshots; operator preferences live outside this directory.
    root = _open_state_dir(ASSETS_DIR)
    try:
        meta_fd = os.open("manifest.json", READ_FLAGS, dir_fd=root)
        try:
            info = os.fstat(meta_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != os.geteuid() or info.st_mode & 0o022 or
                    not 100 < info.st_size <= 4096):
                raise StatusPageError("Untrusted Status Pages manifest")
            manifest = json.loads(os.read(meta_fd, 4097).decode("utf-8"))
        finally:
            os.close(meta_fd)
        expected = {f"{loc}/{item}.html" for loc in LOCALES for item in PAGES}
        if (not isinstance(manifest, dict) or set(manifest) != {"schema", "reference_commit", "assets"}
                or manifest["schema"] != 1
                or manifest["reference_commit"] != "6c9412f3b220a563b64b82ce3d8ee65ff324fbbe"
                or not isinstance(manifest["assets"], dict)
                or set(manifest["assets"]) != expected):
            raise StatusPageError("Unexpected bundled Status Pages manifest")
        locale_dir = os.open(locale, DIRECTORY_FLAGS, dir_fd=root)
        try:
            fd = os.open(page + ".html", READ_FLAGS, dir_fd=locale_dir)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != os.geteuid() or info.st_mode & 0o022
                        or not 1000 <= info.st_size <= 25000):
                    raise StatusPageError("Untrusted bundled Status Page template")
                content = os.read(fd, 25001)
                if len(content) != info.st_size:
                    raise StatusPageError("Unexpected Status Page source size")
                digest = manifest["assets"].get(f"{locale}/{page}.html")
                if (not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)
                        or hashlib.sha256(content).hexdigest() != digest):
                    raise StatusPageError("Bundled Status Page source integrity mismatch")
                return content
            finally:
                os.close(fd)
        finally:
            os.close(locale_dir)
    finally:
        os.close(root)


def render_page(locale, page, brand=None):
    brand = validate_brand(brand or DEFAULT_BRAND)
    source = _asset(locale, page)
    source_hash = hashlib.sha256(source).hexdigest()
    # Preserve the exact owner-provided HTML bytes for defaults, no silent restyling.
    if brand == DEFAULT_BRAND:
        return {"html": source.decode("utf-8"), "source_sha256": source_hash,
                "rendered_sha256": source_hash, "changed": False}
    original = source.decode("utf-8")
    auxiliary = (brand["accent"] if _contrast(brand["accent"], brand["background"]) >= 4.5
                 else brand["foreground"])
    token_values = {
        "https://ach.li": html.escape(brand["brand_url"], quote=True),
        "ach.li": html.escape(brand["brand_label"], quote=True),
        "ACh": html.escape(brand["brand_name"], quote=True),
        "ACH": html.escape(brand["brand_name"], quote=True),
        "WEB SYSTEMS": html.escape(brand["tagline"], quote=True),
        "#008b92": brand["accent"],
        "#f4f2eb": brand["background"],
        "#0b1718": brand["foreground"],
        # Auxiliary accents derive from the chosen palette for non-default branding.
        "#126b70": auxiliary,
        "#235960": auxiliary,
        "#215e61": auxiliary,
        "#0b4143": brand["foreground"],
        "Thoughtful systems for the web.": html.escape(brand["tagline"], quote=True),
        "زیرساخت و تجربه وب": html.escape(brand["tagline"], quote=True),
    }
    text = TOKEN_RE.sub(lambda match: token_values[match.group()], original)
    if not brand["footer_enabled"]:
        text, count = re.subn(r'<footer class="bottom">.*?</footer>', "", text, count=1, flags=re.S)
        if count != 1:
            raise StatusPageError("Bundled footer structure changed")
    if len(text.encode("utf-8")) > 32768:
        raise StatusPageError("Rendered template exceeds size limit")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"html": text, "source_sha256": source_hash, "rendered_sha256": digest,
            "changed": source_hash != digest}
