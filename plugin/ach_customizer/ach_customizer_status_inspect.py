"""Bounded read-only Status Pages site-file and Nginx-source inspection.

This is an operator diagnostic, NOT a verified effective Nginx routing parser
or a permit to Apply. No code path opens files for writing, runs nginx, or
mutates aaPanel. An include in a VHost may be regenerated or overridden.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import stat
import unicodedata

from ach_customizer_monitor import MonitorInputError, _active_nginx_text

VHOST_ROOT = "/www/server/panel/vhost/nginx"
SUPPORTED_PAGES = ("404", "502")
MAX_FILE_BYTES = 64 * 1024
MAX_EXTENSIONS = 32
# Diff is display-only, never an Apply patch. Bound both CPU and response size.
MAX_COMPARE_BYTES = 24 * 1024
MAX_COMPARE_LINES = 240
MAX_COMPARE_EXCERPT = 6144
MAX_COMPARE_DISPLAY_LINE = 360
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
# Used only for source-snapshot identity, never returned to panel clients.
_FILE_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns",
                "st_ctime_ns", "st_uid", "st_gid", "st_mode", "st_nlink")
_LONG_LINE_MARKER = " [long line clipped]"


class StatusInspectError(ValueError):
    pass


def _directory(path):
    """Anchor the entire path at root, rejecting symlinked ancestors."""
    if (not isinstance(path, str) or not 1 < len(path) <= 1024
            or not path.startswith("/") or "//" in path
            or "\x00" in path or path.endswith("/")):
        raise StatusInspectError("Unsupported directory path")
    components = path.split("/")[1:]
    if (len(components) > 40 or
            any(part in ("", ".", "..") for part in components)):
        raise StatusInspectError("Noncanonical directory path")
    fd = os.open("/", DIR_FLAGS)
    try:
        for component in components:
            next_fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _identity(stat_result):
    return tuple(getattr(stat_result, key) for key in _FILE_FIELDS)


def _remember_source(bindings, path, directory_fd, name, snapshot, names=None):
    """Remember the original absolute binding, not just an open directory FD."""
    directory = os.fstat(directory_fd)
    entry = {
        "path": path,
        "directory": (directory.st_dev, directory.st_ino),
        "name": name,
        "file": None if snapshot is None else snapshot["identity"],
        "names": names,
    }
    bindings.append(entry)


def _verify_source_bindings(bindings, missing_directories):
    """Re-resolve each original absolute path and reject detached source trees.

    This is a final best-effort *snapshot* check; no read-only inspection can
    guarantee a file remains unchanged after the check finishes.
    """
    for entry in bindings:
        descriptor = _directory(entry["path"])
        try:
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != entry["directory"]:
                raise StatusInspectError("Inspected directory binding changed")
            if entry["name"] is not None:
                try:
                    observed = os.stat(entry["name"], dir_fd=descriptor,
                                       follow_symlinks=False)
                except FileNotFoundError:
                    if entry["file"] is not None:
                        raise StatusInspectError("Inspected file disappeared")
                else:
                    if entry["file"] is None or _identity(observed) != entry["file"]:
                        raise StatusInspectError("Inspected file binding changed")
            if entry["names"] is not None:
                observed_names = sorted(name for name in os.listdir(descriptor)
                                        if name.endswith(".conf"))
                if observed_names != entry["names"]:
                    raise StatusInspectError("Site extension config list changed")
        finally:
            os.close(descriptor)
    for path in missing_directories:
        try:
            descriptor = _directory(path)
        except FileNotFoundError:
            continue
        else:
            os.close(descriptor)
            raise StatusInspectError("Previously missing extension directory appeared")


def _file_snapshot(directory_fd, name):
    """Return a stable regular-file byte snapshot; missing is distinct."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,255}", name):
        raise StatusInspectError("Unsafe file basename")
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                not 0 <= before.st_size <= MAX_FILE_BYTES):
            raise StatusInspectError("Unsafe or oversized inspected file")
        data = bytearray()
        while len(data) <= MAX_FILE_BYTES:
            piece = os.read(fd, MAX_FILE_BYTES + 1 - len(data))
            if not piece:
                break
            data.extend(piece)
        after = os.fstat(fd)
        fields = _FILE_FIELDS
        # fstat alone cannot prove that the pathname still names this inode:
        # aaPanel or an operator may atomically replace a site page/VHost
        # while the descriptor remains open. Recheck the exact basename
        # without following links; do not report the old bytes as current.
        try:
            pathname = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise StatusInspectError("File path changed during read-only inspection") from exc
        if (len(data) != before.st_size or
                any(getattr(before, k) != getattr(after, k) or
                    getattr(before, k) != getattr(pathname, k) for k in fields)):
            raise StatusInspectError("File changed during read-only inspection")
        return {"data": bytes(data), "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "identity": _identity(after)}
    finally:
        os.close(fd)


def _active(source):
    try:
        return _active_nginx_text(source.decode("utf-8"))
    except (UnicodeError, MonitorInputError) as exc:
        raise StatusInspectError("Ambiguous Nginx configuration text") from exc


def _has_directive(text, name):
    # This intentionally over-detects quoted references: false conflicts are
    # safe; claiming an absent routing directive when one exists is not.
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?=\s)", text) is not None


def _textual_extension_include(text, key):
    expected = VHOST_ROOT + "/extension/" + key + "/*.conf"
    # A token-boundary textual reference, NOT proof that the directive is
    # inside the active server block or that Nginx loaded the fragment.
    return bool(re.search(
        r"(?:^|[;{}\n])\s*include\s+" + re.escape(expected) + r"\s*;",
        text, flags=re.MULTILINE
    ))


def _content_comparison(current, rendered_html, rendered_sha256, page_file):
    """Bounded site-file snapshot vs already rendered offline HTML.

    No operation writes a file, parses the existing HTML as executable markup
    or assumes the HTML is served by Nginx. Only a primary-admin endpoint may
    return the excerpt; callers must render it as plain text.
    """
    result = {
        "schema": 1, "state": "Unavailable", "excerpt": "",
        "truncated": False, "reason": "Content comparison was not requested",
        "old_lines": None, "new_lines": None,
    }
    if rendered_html is None:
        return result
    if not isinstance(rendered_html, str):
        raise StatusInspectError("Invalid rendered page content")
    proposed = rendered_html.encode("utf-8")
    if len(proposed) > 32768:
        raise StatusInspectError("Rendered page exceeds the offline preview limit")
    if hashlib.sha256(proposed).hexdigest() != rendered_sha256:
        raise StatusInspectError("Rendered page fingerprint does not match the content")
    if current is None:
        return {**result, "state": "New File",
                "reason": "No existing document-root page; the offline preview shows proposed content",
                "old_lines": 0, "new_lines": len(rendered_html.splitlines())}
    if current["sha256"] == rendered_sha256:
        return {**result, "state": "Identical",
                "reason": "The file snapshot and proposed preview are byte-identical",
                "old_lines": len(current["data"].splitlines()),
                "new_lines": len(rendered_html.splitlines())}
    if len(current["data"]) > MAX_COMPARE_BYTES or len(proposed) > MAX_COMPARE_BYTES:
        return {**result, "reason": "Content differs but exceeds the bounded text-diff limit"}
    try:
        old = current["data"].decode("utf-8")
    except UnicodeError:
        return {**result, "reason": "Existing site page is not valid UTF-8 text"}
    # Display integrity: C0/C1 controls, formatting/directional controls
    # (including LRM/RLM/ALM and isolates), Unicode line/paragraph separators
    # must not silently change how the human reviewer reads a line.
    # Ordinary CR/LF/TAB and Persian ZWNJ (U+200C) are intentional exceptions.
    for text in (old, rendered_html):
        if any((unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") and
                ch not in ("\t", "\n", "\r", "\u200c"))
               for ch in text):
            return {**result, "reason": "Control or directional formatting bytes prevent a safe text diff"}
    old_lines = old.splitlines(keepends=True)
    new_lines = rendered_html.splitlines(keepends=True)
    if len(old_lines) > MAX_COMPARE_LINES or len(new_lines) > MAX_COMPARE_LINES:
        return {**result, "reason": "Content differs but exceeds the bounded line-diff limit"}
    excerpt = []
    count = 0
    truncated = False
    for raw in difflib.unified_diff(
            old_lines, new_lines, fromfile="current " + page_file,
            tofile="proposed " + page_file, n=2, lineterm="\n"):
        line = raw.rstrip("\n").replace("\r", "\\r").replace("\t", "\\t")
        if len(line) > MAX_COMPARE_DISPLAY_LINE:
            line = line[:MAX_COMPARE_DISPLAY_LINE - len(_LONG_LINE_MARKER)] + _LONG_LINE_MARKER
            truncated = True
        # Enforce an actual UTF-8 response *byte* cap, not only a character
        # count: a page may contain multibyte Persian/Unicode characters.
        encoded_bytes = len(line.encode("utf-8")) + (1 if excerpt else 0)
        if count + encoded_bytes > MAX_COMPARE_EXCERPT:
            truncated = True
            break
        excerpt.append(line)
        count += encoded_bytes
    return {
        **result, "state": "Different", "excerpt": "\n".join(excerpt),
        "truncated": truncated,
        "reason": ("Bounded, display-only excerpt; it is not an Apply patch or proof of live routing"),
        "old_lines": len(old_lines), "new_lines": len(new_lines),
    }


def inspect_site_files(site, *, locale, template, rendered_sha256,
                       rendered_html=None, vhost_root=VHOST_ROOT):
    """Compare a rendered 404/502 with native site files; never change them.

    Result is only a source/disk snapshot. Even when every file hash matches,
    effective Nginx routing and the live HTTP status are NOT verified.
    """
    if locale not in ("en", "fa") or template not in SUPPORTED_PAGES:
        raise StatusInspectError("Disk inspection supports site 404/502 only")
    if not isinstance(rendered_sha256, str) or not SHA256.fullmatch(rendered_sha256):
        raise StatusInspectError("Invalid rendered page fingerprint")
    if not isinstance(site, dict):
        raise StatusInspectError("Invalid native site record")
    try:
        site_id = int(site["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StatusInspectError("Invalid native site identifier") from exc
    if site_id <= 0 or site_id > 2147483647:
        raise StatusInspectError("Invalid native site identifier")
    key, document_root = site.get("name"), site.get("path")
    if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,253}", key)
            or not isinstance(document_root, str)):
        raise StatusInspectError("Unsupported native website key or document root")

    result = {
        "schema": 1, "site_id": site_id, "site_key": key,
        "template": template, "locale": locale, "state": "Needs Review",
        "reason": "", "read_only": True, "apply_supported": False,
        "nginx_runtime_verified": False, "rendered_sha256": rendered_sha256,
        "page_file": template + ".html", "page_file_state": "Uninspected",
        "page_file_sha256": None, "page_file_bytes": None,
        "comparison": {
            "schema": 1, "state": "Unavailable", "excerpt": "",
            "truncated": False, "reason": "Source inspection not completed",
            "old_lines": None, "new_lines": None,
        },
        "vhost_sha256": None, "extension_include_textual": False,
        "extensions_scanned": [], "error_page_sources": [],
        "note": ("Disk and textual VHost/extension snapshot only. An include may disappear "
                 "during aaPanel regeneration; neither loaded Nginx routes nor HTTP "
                 "response status are verified. Apply and Restore are disabled."),
    }
    bindings = []
    missing_directories = []
    try:
        directory_fd = _directory(document_root)
        try:
            site_page = _file_snapshot(directory_fd, template + ".html")
            _remember_source(bindings, document_root, directory_fd, template + ".html", site_page)
        finally:
            os.close(directory_fd)
        # A content diff is independent of whether Nginx actually routes to
        # this site file. Read-only and tied to the exact rendered SHA.
        result["comparison"] = _content_comparison(
            site_page, rendered_html, rendered_sha256, template + ".html")
        if site_page is None:
            result["page_file_state"] = "Absent"
        else:
            result["page_file_sha256"] = site_page["sha256"]
            result["page_file_bytes"] = site_page["bytes"]
            result["page_file_state"] = (
                "Same bytes" if site_page["sha256"] == rendered_sha256 else "Different bytes"
            )

        vhost_dir = _directory(vhost_root)
        try:
            vhost = _file_snapshot(vhost_dir, key + ".conf")
            _remember_source(bindings, vhost_root, vhost_dir, key + ".conf", vhost)
        finally:
            os.close(vhost_dir)
        if vhost is None:
            result.update(state="Unsupported", reason="Native website VHost file not found")
            _verify_source_bindings(bindings, missing_directories)
            return result
        result["vhost_sha256"] = vhost["sha256"]
        vhost_text = _active(vhost["data"])
        if _has_directive(vhost_text, "error_page"):
            result["error_page_sources"].append("site VHost")
        result["extension_include_textual"] = _textual_extension_include(vhost_text, key)

        extension_path = vhost_root + "/extension/" + key
        try:
            extension_fd = _directory(extension_path)
        except FileNotFoundError:
            missing_directories.append(extension_path)
            extension_fd = None
        if extension_fd is not None:
            try:
                names = sorted(
                    name for name in os.listdir(extension_fd) if name.endswith(".conf")
                )
                if len(names) > MAX_EXTENSIONS:
                    raise StatusInspectError("Too many site extension config fragments")
                _remember_source(bindings, extension_path, extension_fd, None, None, names=names)
                for name in names:
                    fragment = _file_snapshot(extension_fd, name)
                    if fragment is None:
                        raise StatusInspectError("Extension fragment disappeared during inspection")
                    _remember_source(bindings, extension_path, extension_fd, name, fragment)
                    text = _active(fragment["data"])
                    result["extensions_scanned"].append(name)
                    if _has_directive(text, "error_page"):
                        result["error_page_sources"].append("extension/" + name)
            finally:
                os.close(extension_fd)

        if result["error_page_sources"]:
            result["state"] = "Conflict"
            result["reason"] = "Existing error_page directives require owner and routing review"
        elif result["page_file_state"] == "Different bytes":
            result["state"] = "Conflict"
            result["reason"] = "Existing site page differs; do not overwrite manually owned content"
        elif not result["extension_include_textual"]:
            result["state"] = "Needs Review"
            result["reason"] = "No literal native site-extension include observed in this VHost"
        else:
            result["state"] = "File Match" if result["page_file_state"] == "Same bytes" else "Unmanaged"
            result["reason"] = (
                "Matching site page bytes, but HTTP serving is not verified" if result["state"] == "File Match"
                else "No site page file; a textual extension include exists, but its lifetime is unverified"
            )
        # Do not present an old descriptor's bytes after aaPanel has renamed
        # any original site/VHost path or modified the corresponding file.
        _verify_source_bindings(bindings, missing_directories)
    except (OSError, StatusInspectError) as exc:
        result["state"] = "Needs Review"
        result["reason"] = ("Read-only inspection incomplete: " + str(exc))[:240]
        # Suppress any proposed content diff on an uncertain filesystem read.
        result["comparison"] = {
            "schema": 1, "state": "Unavailable", "excerpt": "",
            "truncated": False, "reason": "Inspection incomplete; recheck before comparison",
            "old_lines": None, "new_lines": None,
        }
        result["vhost_sha256"] = None
        result["page_file_state"] = "Uninspected"
        result["page_file_sha256"] = None
        result["page_file_bytes"] = None
        result["extension_include_textual"] = False
        result["extensions_scanned"] = []
        result["error_page_sources"] = []
    return result
