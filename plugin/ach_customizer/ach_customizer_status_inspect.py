"""Bounded read-only Status Pages site-file and Nginx-source inspection.

This is an operator diagnostic, NOT a verified effective Nginx routing parser
or a permit to Apply. No code path opens files for writing, runs nginx, or
mutates aaPanel. An include in a VHost may be regenerated or overridden.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat

from ach_customizer_monitor import MonitorInputError, _active_nginx_text

VHOST_ROOT = "/www/server/panel/vhost/nginx"
SUPPORTED_PAGES = ("404", "502")
MAX_FILE_BYTES = 64 * 1024
MAX_EXTENSIONS = 32
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns",
                  "st_ctime_ns", "st_uid", "st_gid", "st_mode", "st_nlink")
        if (len(data) != before.st_size or
                any(getattr(before, k) != getattr(after, k) for k in fields)):
            raise StatusInspectError("File changed during read-only inspection")
        return {"data": bytes(data), "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data)}
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


def inspect_site_files(site, *, locale, template, rendered_sha256,
                       vhost_root=VHOST_ROOT):
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
        "vhost_sha256": None, "extension_include_textual": False,
        "extensions_scanned": [], "error_page_sources": [],
        "note": ("Disk and textual VHost/extension snapshot only. An include may disappear "
                 "during aaPanel regeneration; neither loaded Nginx routes nor HTTP "
                 "response status are verified. Apply and Restore are disabled."),
    }
    try:
        directory_fd = _directory(document_root)
        try:
            site_page = _file_snapshot(directory_fd, template + ".html")
        finally:
            os.close(directory_fd)
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
        finally:
            os.close(vhost_dir)
        if vhost is None:
            result.update(state="Unsupported", reason="Native website VHost file not found")
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
            extension_fd = None
        if extension_fd is not None:
            try:
                names = sorted(
                    name for name in os.listdir(extension_fd) if name.endswith(".conf")
                )
                if len(names) > MAX_EXTENSIONS:
                    raise StatusInspectError("Too many site extension config fragments")
                for name in names:
                    fragment = _file_snapshot(extension_fd, name)
                    if fragment is None:
                        raise StatusInspectError("Extension fragment disappeared during inspection")
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
    except (OSError, StatusInspectError) as exc:
        result["state"] = "Needs Review"
        result["reason"] = ("Read-only inspection incomplete: " + str(exc))[:240]
        # Suppress partial positive matches on an uncertain filesystem read.
        result["vhost_sha256"] = None
        result["extensions_scanned"] = []
        result["error_page_sources"] = []
    return result
