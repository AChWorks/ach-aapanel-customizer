"""Opt-in, per-site WordPress Bridge manifest for guarded Cache URL mapping.

A root-owned, non-executable metadata record is installed ONLY after explicit
native operator approval and a freshly verified Applied Cache generation.
WordPress Bridge can read it but cannot modify it as the PHP worker.

This does not activate Nginx Helper, change any WordPress option, certify
Nginx workers or enable vendor Purge All.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

MANIFEST_DIR = "ach-customizer-bridge"
MANIFEST_NAME = "cache.php"
MANIFEST_PREFIX = b"<?php defined('ABSPATH') || exit; __halt_compiler(); ?>\n"
PHP_PLUGIN = ("plugins", "ach-aapanel-bridge", "ach-aapanel-bridge.php")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
DNS_HOST = re.compile(r"[a-z0-9][a-z0-9.-]{0,253}\Z")


class BridgeError(ValueError):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage


def _dirfd(fd, name):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    return os.open(name, flags, dir_fd=fd)


def _regular(fd, name, owner_uid, mode=0o644):
    try:
        item = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(item.st_mode) or item.st_nlink != 1
            or item.st_uid != owner_uid or stat.S_IMODE(item.st_mode) != mode):
        raise BridgeError("ownership", "WordPress Bridge manifest is not native-owned")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    filefd = os.open(name, flags, dir_fd=fd)
    try:
        if (os.fstat(filefd).st_ino, os.fstat(filefd).st_dev) != (item.st_ino, item.st_dev):
            raise BridgeError("concurrency", "WordPress Bridge manifest changed during read")
        data = os.read(filefd, 4097)
    finally:
        os.close(filefd)
    if len(data) > 4096:
        raise BridgeError("ownership", "Untrusted oversized WordPress Bridge manifest")
    return data


def _docroot(site, public):
    path = site.get("path")
    if (not isinstance(path, str) or not path.startswith("/")
            or path == "/" or "//" in path
            or any(part in (".", "..") for part in path.split("/"))
            or os.path.realpath(path) != path):
        raise BridgeError("identity", "Native WordPress document root is not canonical")
    rows = public.M("sites").where("path=?", (path,)).field("id,name,path").select()
    if (not isinstance(rows, list) or len(rows) != 1
            or str(rows[0].get("id")) != str(site["id"])
            or rows[0].get("name") != site["name"]
            or rows[0].get("path") != path):
        raise BridgeError("identity", "Native WordPress document root is shared or changed")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        current = os.stat(path, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise BridgeError("concurrency", "Native WordPress root changed during inspection")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _contentfd(site, public, *, require_plugin=False):
    rootfd = _docroot(site, public)
    try:
        wpfd = _dirfd(rootfd, "wp-content")
        try:
            config = os.stat("wp-config.php", dir_fd=rootfd, follow_symlinks=False)
            if not stat.S_ISREG(config.st_mode):
                raise BridgeError("compatibility", "Unverified WordPress root")
            # A checked-in Bridge plugin is necessary, activation still
            # belongs to WordPress and is not inferred from source presence.
            if require_plugin:
                try:
                    pluginsfd = _dirfd(wpfd, PHP_PLUGIN[0])
                    try:
                        bridgefd = _dirfd(pluginsfd, PHP_PLUGIN[1])
                        try:
                            entry = os.stat(PHP_PLUGIN[2], dir_fd=bridgefd, follow_symlinks=False)
                            if not stat.S_ISREG(entry.st_mode):
                                raise BridgeError("compatibility", "WordPress Bridge plugin is missing")
                        finally:
                            os.close(bridgefd)
                    finally:
                        os.close(pluginsfd)
                except FileNotFoundError as exc:
                    raise BridgeError("compatibility", "WordPress Bridge plugin is not installed") from exc
            return wpfd
        except BaseException:
            os.close(wpfd)
            raise
    finally:
        os.close(rootfd)


def _manifestfd(wpfd, *, create, owner_uid):
    created = False
    try:
        fd = _dirfd(wpfd, MANIFEST_DIR)
    except FileNotFoundError:
        if not create:
            return None
        os.mkdir(MANIFEST_DIR, 0o700, dir_fd=wpfd)
        os.fsync(wpfd)
        fd = _dirfd(wpfd, MANIFEST_DIR)
        created = True
    try:
        if created:
            os.fchmod(fd, 0o755)
            os.fsync(fd)
        obj = os.fstat(fd)
        if obj.st_uid != owner_uid or stat.S_IMODE(obj.st_mode) != 0o755:
            raise BridgeError("ownership", "Untrusted WordPress Bridge directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _decode(data):
    if not data.startswith(MANIFEST_PREFIX):
        raise BridgeError("ownership", "Unexpected WordPress Bridge manifest format")
    try:
        obj = json.loads(data[len(MANIFEST_PREFIX):])
    except (ValueError, UnicodeDecodeError) as exc:
        raise BridgeError("ownership", "Unparseable WordPress Bridge manifest") from exc
    if (type(obj) is not dict or set(obj) != {
            "schema", "site_id", "site_key", "wp_root", "cache_directory",
            "cache_generation", "cache_identity", "recovery_id"
        } or obj["schema"] != 1 or type(obj["site_id"]) is not int
            or obj["site_id"] < 1 or obj["site_id"] > 2147483647
            or type(obj["site_key"]) is not str
            or not DNS_HOST.fullmatch(obj["site_key"])
            or type(obj["wp_root"]) is not str
            or type(obj["cache_generation"]) is not str
            or not HEX32.fullmatch(obj["cache_generation"])
            or type(obj["recovery_id"]) is not str
            or not HEX32.fullmatch(obj["recovery_id"])
            or type(obj["cache_identity"]) is not list
            or len(obj["cache_identity"]) != 2
            or any(type(n) is not int or n <= 0 for n in obj["cache_identity"])
            or obj["cache_directory"] !=
                "/www/server/ach-customizer-fastcgi/site-" + str(obj["site_id"])):
        raise BridgeError("ownership", "Invalid WordPress Bridge manifest identity")
    return obj


def _data(site, record):
    host = site["name"].lower()
    if (not DNS_HOST.fullmatch(host) or host != site["name"]
            or not isinstance(site.get("path"), str)):
        raise BridgeError("identity", "Unverified canonical WordPress Host")
    data = {
        "schema": 1, "site_id": site["id"], "site_key": host,
        "wp_root": site["path"], "cache_directory": record["cache_directory"],
        "cache_generation": record["cache_generation"],
        "cache_identity": record["cache_identity"], "recovery_id": record["op"],
    }
    return _decode(MANIFEST_PREFIX + json.dumps(
        data, separators=(",", ":"), sort_keys=True).encode() + b"\n")


def _read(wpfd, owner_uid):
    fd = _manifestfd(wpfd, create=False, owner_uid=owner_uid)
    if fd is None:
        return None
    try:
        raw = _regular(fd, MANIFEST_NAME, owner_uid)
        return _decode(raw) if raw is not None else None
    finally:
        os.close(fd)


def inspect(site, public, record=None, *, owner_uid=0):
    if not os.path.lexists(Path(site.get("path", "/no-root")) / "wp-content" / MANIFEST_DIR):
        return "Not Provisioned"
    wpfd = _contentfd(site, public)
    try:
        data = _read(wpfd, owner_uid)
        if data is None:
            return "Not Provisioned"
        if (data["site_id"] != site["id"] or data["site_key"] != site["name"]
                or data["wp_root"] != site["path"]):
            return "Needs Review"
        if record is None or record.get("phase") != "applied":
            return "Stale — Disable Required"
        return "Provisioned" if data == _data(site, record) else "Needs Review"
    finally:
        os.close(wpfd)


def enable(site, public, record, *, owner_uid=0):
    expected = _data(site, record)
    wpfd = _contentfd(site, public, require_plugin=True)
    try:
        fd = _manifestfd(wpfd, create=True, owner_uid=owner_uid)
        try:
            existing = _regular(fd, MANIFEST_NAME, owner_uid)
            raw = MANIFEST_PREFIX + json.dumps(
                expected, separators=(",", ":"), sort_keys=True).encode() + b"\n"
            if existing is not None:
                if existing != raw:
                    raise BridgeError("recovery", "Existing Bridge manifest requires explicit Disable")
                return False
            tmp = "." + MANIFEST_NAME + "." + uuid4().hex + ".stage"
            filefd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             os.O_NOFOLLOW | os.O_CLOEXEC, 0o644, dir_fd=fd)
            try:
                os.fchmod(filefd, 0o644)
                with os.fdopen(filefd, "wb", closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                os.fsync(filefd)
                os.link(tmp, MANIFEST_NAME, src_dir_fd=fd, dst_dir_fd=fd,
                        follow_symlinks=False)
                os.fsync(fd)
            finally:
                os.close(filefd)
                try:
                    os.unlink(tmp, dir_fd=fd)
                except FileNotFoundError:
                    pass
            return True
        finally:
            os.close(fd)
    finally:
        os.close(wpfd)


def disable(site, public, *, owner_uid=0):
    """Remove only an exact native-owned, same-site manifest; never foreign files."""
    if not os.path.lexists(Path(site.get("path", "/no-root")) / "wp-content" / MANIFEST_DIR):
        return False
    wpfd = _contentfd(site, public)
    try:
        fd = _manifestfd(wpfd, create=False, owner_uid=owner_uid)
        if fd is None:
            return False
        try:
            raw = _regular(fd, MANIFEST_NAME, owner_uid)
            if raw is None:
                return False
            data = _decode(raw)
            if (data["site_id"] != site["id"] or
                    data["site_key"] != site["name"] or
                    data["wp_root"] != site["path"]):
                raise BridgeError("ownership", "Bridge manifest belongs to another site")
            if _regular(fd, MANIFEST_NAME, owner_uid) != raw:
                raise BridgeError("concurrency", "Bridge manifest changed during Disable")
            os.unlink(MANIFEST_NAME, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.rmdir(MANIFEST_DIR, dir_fd=wpfd)
            os.fsync(wpfd)
        except OSError:
            # Preserve a populated directory for ownership investigation.
            pass
        return True
    finally:
        os.close(wpfd)
