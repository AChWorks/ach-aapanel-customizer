"""Read-only Nginx Helper file-presence evidence for a native aaPanel website.

Do not bootstrap WordPress, read wp-config.php/DB options, execute third-party
plugin code, or infer whether an installed plugin is active. An inspected
filesystem path is taken only from the revalidated native aaPanel site record.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_MAX_PLUGIN_BYTES = 32768
_VERSION = re.compile(r"(?m)^[ \t]*\*[ \t]*Version:[ \t]*([0-9]+\.[0-9]+(?:\.[0-9]+){0,2})[ \t]*\r?$")
_NAME = re.compile(r"(?m)^[ \t]*\*[ \t]*Plugin Name:[ \t]*Nginx Helper[ \t]*\r?$")
_IDENT = ("st_dev", "st_ino", "st_mode", "st_size", "st_uid", "st_gid",
          "st_nlink", "st_mtime_ns", "st_ctime_ns")


class HelperInspectionError(ValueError):
    pass


def _identity(meta):
    return tuple(getattr(meta, field) for field in _IDENT)


def _directory(parent, component):
    return os.open(component, _DIR_FLAGS, dir_fd=parent)


def _descend(parent, *parts):
    current = os.dup(parent)
    try:
        for part in parts:
            following = _directory(current, part)
            os.close(current)
            current = following
        return current
    except BaseException:
        os.close(current)
        raise


def _regular(directory, name, *, read=False):
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                not 0 < before.st_size <= _MAX_PLUGIN_BYTES):
            raise HelperInspectionError("Unverified WordPress/plugin file type or size")
        if read:
            raw = bytearray()
            while len(raw) <= _MAX_PLUGIN_BYTES:
                chunk = os.read(fd, _MAX_PLUGIN_BYTES + 1 - len(raw))
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) > _MAX_PLUGIN_BYTES:
                raise HelperInspectionError("Oversized Nginx Helper source")
            value = bytes(raw)
        else:
            value = b""
        after = os.fstat(fd)
        if _identity(before) != _identity(after):
            raise HelperInspectionError("WordPress/plugin file changed during inspection")
        return (_identity(after), hashlib.sha256(value).hexdigest(), value)
    finally:
        os.close(fd)


def _scan(root):
    base = os.open("/", _DIR_FLAGS)
    try:
        current = _descend(base, *root.parts[1:])
    finally:
        os.close(base)
    try:
        root_identity = _identity(os.fstat(current))
        try:
            wp = _descend(current, "wp-includes")
        except FileNotFoundError:
            return "Not Observed", None, root_identity, None
        try:
            core = _regular(wp, "version.php")
        finally:
            os.close(wp)
        if core is None:
            return "Not Observed", None, root_identity, None
        try:
            directory = _descend(current, "wp-content", "plugins", "nginx-helper")
        except FileNotFoundError:
            return "Not Installed", None, root_identity, core[:2]
        try:
            source = _regular(directory, "nginx-helper.php", read=True)
        finally:
            os.close(directory)
        if source is None:
            raise HelperInspectionError("Incomplete Nginx Helper plugin source")
        body = source[2].decode("utf-8")
        version = _VERSION.search(body[:4096])
        if not _NAME.search(body[:4096]) or version is None:
            raise HelperInspectionError("Unrecognized Nginx Helper plugin metadata")
        # Reopen the native site root by its *original path* to detect a moved
        # or rebound document root, not just changes to pinned descriptors.
        fresh = os.open("/", _DIR_FLAGS)
        try:
            check = _descend(fresh, *root.parts[1:])
        finally:
            os.close(fresh)
        try:
            if _identity(os.fstat(check)) != root_identity:
                raise HelperInspectionError("Native document root changed during inspection")
        finally:
            os.close(check)
        return "Installed", version.group(1), root_identity, (core[:2], source[:2])
    finally:
        os.close(current)


def inspect_nginx_helper_files(site_root):
    """Two-pass file-only diagnosis; no WordPress activation/config claims."""
    result = {
        "schema": 1, "state": "Needs Review", "version": None,
        "active_verified": False, "purge_method_verified": False,
        "cache_path_verified": False, "purge_safe_verified": False,
        "reason": "", "note": "",
    }
    if (not isinstance(site_root, str) or len(site_root) > 1024 or
            not site_root.startswith("/") or "//" in site_root or
            site_root.endswith("/") or ".." in Path(site_root).parts or
            str(Path(site_root)) != site_root):
        result["reason"] = "Unverified native document root"
        result["note"] = "No WordPress/Nginx Helper files trusted."
        return result
    root = Path(site_root)
    try:
        first = _scan(root)
        if first != _scan(root):
            raise HelperInspectionError("WordPress/Nginx Helper source changed during inspection")
        state, version, _, _ = first
    except (OSError, UnicodeError, ValueError):
        result["reason"] = "Native WordPress/plugin files unavailable, redirected or changing"
        result["note"] = "Inspect the native document root and plugin layout manually."
        return result
    result.update(state=state, version=version)
    if state == "Not Observed":
        result["note"] = (
            "No root-level WordPress core marker observed; subdirectory installs "
            "and application type are not established.")
    elif state == "Not Installed":
        result["note"] = (
            "No standard Nginx Helper plugin folder observed under this WordPress root. "
            "Must-use or alternate plugins and runtime activation are not inspected.")
    elif version == "2.4.1":
        result["note"] = (
            "Installed source v2.4.1 only; activation, purge method and effective "
            "RT_WP_NGINX_HELPER_CACHE_PATH are UNKNOWN. unlink_files per-URL hashes "
            "omit Customizer's cache generation; get_request needs a separately "
            "verified purge route. Ordinary Purge All recursively deletes the "
            "configured directory even with get_request. NO safe purge inferred.")
    else:
        result["note"] = (
            "Installed source only; activation, effective path and purge method "
            "are UNKNOWN. This version's purge implementation is not verified. "
            "NO safe per-site Purge All or URL invalidation inferred.")
    return result
