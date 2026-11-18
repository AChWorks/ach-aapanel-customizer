"""Explicit, recoverable removal of one site's unwanted local hosts alias.

Only authenticated aaPanel primary-admin endpoints may invoke writes. This
module accepts an exact native-site identity and an inspection fingerprint;
it never accepts a caller-chosen filesystem path in production. It cannot
identify which program wrote an alias or prove external DNS/Gateway behavior.
"""
from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import stat
from contextlib import contextmanager
from uuid import uuid4

from ach_customizer_hosts import (
    HOSTS_PATH, MAX_BYTES, MAX_LINES, MAX_ALIASES_PER_LINE,
    HostsInspectionError, _hostname, _site_domains, inspect_local_hosts,
    native_site_snapshot,
)
from ach_customizer_state import DATA_DIR, _open_state_dir

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OP = re.compile(r"[0-9a-f]{32}\Z")
_LOCK = "ach_customizer.hosts.lock"
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_NEW_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_STAT_KEYS = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink",
              "st_size", "st_mtime_ns", "st_ctime_ns")


class HostsManageError(HostsInspectionError):
    def __init__(self, message, recovery_id=None):
        super().__init__(message)
        self.recovery_id = recovery_id


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _site_fingerprint(site):
    try:
        return _sha(json.dumps(native_site_snapshot(site), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, KeyError) as exc:
        raise HostsManageError("Native website identity is incomplete") from exc


def _record_name(site_id):
    return "ach_customizer.hosts." + str(site_id) + ".json"


def _backup_name(site_id, operation):
    return "ach_customizer.hosts." + str(site_id) + "." + operation + ".backup"


def _same_identity(before, after):
    return all(getattr(before, key) == getattr(after, key) for key in _STAT_KEYS)


def _open_parent(source_path):
    """Fixed path in production. Optional fixture path is for isolated tests."""
    if (not isinstance(source_path, str) or not source_path.startswith("/")
            or len(source_path) > 1024 or "//" in source_path or "\x00" in source_path):
        raise HostsManageError("Invalid hosts file path")
    parts = source_path.split("/")[1:]
    if (len(parts) > 40 or len(parts) < 2 or parts[-1] != "hosts"
            or any(part in ("", ".", "..") for part in parts)):
        raise HostsManageError("Unsupported hosts file path")
    fd = os.open("/", _DIR_FLAGS)
    try:
        for name in parts[:-1]:
            next_fd = os.open(name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        root = os.fstat(fd)
        if (not stat.S_ISDIR(root.st_mode) or root.st_uid != os.geteuid()
                or root.st_mode & 0o022):
            raise HostsManageError("Hosts parent directory is not privately managed")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_source(parent):
    handle = os.open("hosts", _READ_FLAGS, dir_fd=parent)
    try:
        before = os.fstat(handle)
        mode = stat.S_IMODE(before.st_mode)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or before.st_mode & 0o022
                or before.st_mode & 0o7000 or not 0 < before.st_size <= MAX_BYTES):
            raise HostsManageError("Unsupported /etc/hosts source ownership or permissions")
        if os.listxattr(handle):
            # Replacing an inode without preserving its security labels/ACLs is unsafe.
            raise HostsManageError("Hosts file has extended attributes; use native OS management")
        payload = bytearray()
        while len(payload) <= MAX_BYTES:
            chunk = os.read(handle, MAX_BYTES + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(handle)
        pathname = os.stat("hosts", dir_fd=parent, follow_symlinks=False)
        if (len(payload) != before.st_size or not _same_identity(before, after)
                or not _same_identity(after, pathname)):
            raise HostsManageError("Hosts file changed during inspection; recheck")
        return bytes(payload), before
    finally:
        os.close(handle)


@contextmanager
def _locked_state(directory):
    fd = _open_state_dir(directory)
    lock_fd = None
    try:
        lock_fd = os.open(_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                          0o600, dir_fd=fd)
        info = os.fstat(lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise HostsManageError("Unsafe hosts remediation lock")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield fd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(fd)


def _read_owned(state_fd, name, *, required=False, max_bytes=MAX_BYTES):
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=state_fd)
    except FileNotFoundError:
        if required:
            raise HostsManageError("Saved hosts recovery material is missing") from None
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or not 0 < info.st_size <= max_bytes):
            raise HostsManageError("Untrusted hosts recovery material")
        payload = bytearray()
        while len(payload) <= max_bytes:
            chunk = os.read(fd, max_bytes + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != info.st_size:
            raise HostsManageError("Hosts recovery material changed during read")
        return bytes(payload)
    finally:
        os.close(fd)


def _record(state_fd, site):
    raw = _read_owned(state_fd, _record_name(site["id"]), max_bytes=4096)
    if raw is None:
        return None
    try:
        row = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise HostsManageError("Saved hosts recovery record is unreadable") from exc
    expected = {"schema", "site_id", "site_key", "site_snapshot_sha", "domain", "operation",
                "phase", "before_sha", "after_sha", "backup", "uid", "gid", "mode"}
    if (not isinstance(row, dict) or set(row) != expected or row["schema"] != 1
            or type(row["site_id"]) is not int or row["site_id"] != site["id"]
            or row["site_key"] != site["name"] or
            row["site_snapshot_sha"] != _site_fingerprint(site) or row["phase"] not in
            ("prepared", "applied", "restored")
            or not isinstance(row["operation"], str) or not _OP.fullmatch(row["operation"])
            or not isinstance(row["domain"], str)
            or any(not isinstance(row[key], str) or not _SHA.fullmatch(row[key])
                   for key in ("before_sha", "after_sha"))
            or row["backup"] != _backup_name(site["id"], row["operation"])
            or any(type(row[key]) is not int or row[key] < 0 for key in ("uid", "gid", "mode"))
            or row["mode"] > 0o777):
        raise HostsManageError("Invalid hosts recovery record or selected website identity")
    try:
        if _hostname(row["domain"]) != row["domain"]:
            raise HostsManageError("Invalid saved domain")
    except HostsInspectionError as exc:
        raise HostsManageError("Invalid saved hosts domain") from exc
    return row


def _archive_obsolete_record(state_fd, site, previous):
    """Retain a superseded, drifted recovery journal before another removal.

    The former backup is not deleted. Earlier full-file Restore must not be
    offered after an independent editor changed the source; the archive is
    forensic/recovery evidence, not a silent rollback candidate.
    """
    original = _read_owned(state_fd, _record_name(site["id"]), required=True,
                           max_bytes=4096)
    destination = ("ach_customizer.hosts." + str(site["id"]) + "." +
                   previous["operation"] + ".json")
    existing = _read_owned(state_fd, destination, max_bytes=4096)
    if existing is not None:
        if existing != original:
            raise HostsManageError("Conflicting previous hosts journal; inspect recovery")
        return
    _new_file(state_fd, destination, original)
    os.fsync(state_fd)


def _new_file(state_fd, name, payload):
    handle = os.open(name, _NEW_FLAGS, 0o600, dir_fd=state_fd)
    try:
        if os.fstat(handle).st_uid != os.geteuid():
            raise HostsManageError("Unsafe temporary hosts recovery owner")
        with os.fdopen(handle, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(handle)
    finally:
        os.close(handle)


def _save_record(fd, site, row):
    raw = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > 4096:
        raise HostsManageError("Hosts recovery metadata is too large")
    staging = "." + _record_name(site["id"]) + "." + uuid4().hex + ".tmp"
    _new_file(fd, staging, raw)
    try:
        os.replace(staging, _record_name(site["id"]),
                   src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(staging, dir_fd=fd)
        except FileNotFoundError:
            pass


def _loopback(ip):
    return ip.is_loopback or (isinstance(ip, ipaddress.IPv6Address) and
                              ip.ipv4_mapped is not None and ip.ipv4_mapped.is_loopback)


def _remove_domain_aliases(payload, domain):
    """Remove matching loopback aliases, retaining other tokens and comments."""
    try:
        payload.decode("utf-8", "strict")
    except UnicodeError as exc:
        raise HostsManageError("Hosts file text encoding is unsupported") from exc
    lines = payload.splitlines(keepends=True)
    if len(lines) > MAX_LINES:
        raise HostsManageError("Hosts file has too many lines")
    output, removed = [], 0
    for line in lines:
        active, marker, comment = line.partition(b"#")
        spans = list(re.finditer(rb"\S+", active))
        if not spans:
            output.append(line)
            continue
        if len(spans) < 2 or len(spans) > MAX_ALIASES_PER_LINE + 1:
            raise HostsManageError("Cannot safely edit malformed hosts line")
        try:
            ip = ipaddress.ip_address(spans[0].group().decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise HostsManageError("Cannot safely edit invalid hosts address") from exc
        if not _loopback(ip):
            output.append(line)
            continue
        indices = set()
        for i, item in enumerate(spans[1:], 1):
            try:
                if _hostname(item.group().decode("utf-8")) == domain:
                    indices.add(i)
            except (HostsInspectionError, UnicodeError):
                continue
        if not indices:
            output.append(line)
            continue
        removed += len(indices)
        if len(indices) == len(spans) - 1:
            # Removing every alias leaves no valid hosts mapping: preserve the
            # trailing comment as its own comment line when one exists.
            if marker:
                ending = b"\r\n" if line.endswith(b"\r\n") else (b"\n" if line.endswith(b"\n") else b"")
                output.append(b"#" + comment.rstrip(b"\r\n") + ending)
            continue
        # Preserve the exact bytes of all other tokens and comments.
        cursor, kept = 0, bytearray()
        for i, span in enumerate(spans):
            if i in indices:
                # Remove only the preceding separator + selected token.
                if i > 0:
                    if kept and kept[-1:] in (b" ", b"\t"):
                        while kept and kept[-1:] in (b" ", b"\t"):
                            kept.pop()
                cursor = span.end()
            else:
                kept.extend(active[cursor:span.end()])
                cursor = span.end()
        kept.extend(active[cursor:])
        output.append(bytes(kept) + (b"#" + comment if marker else b""))
    return b"".join(output), removed


def _replace_source(parent, payload, baseline, *, expected_sha, recovery_id):
    """Stage in the same directory, verify identity/hash, then atomic replace."""
    staged = ".ach_customizer.hosts." + recovery_id + ".stage"
    stage_fd = os.open(staged, _NEW_FLAGS, 0o600, dir_fd=parent)
    replaced = False
    try:
        with os.fdopen(stage_fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fchown(stage_fd, baseline.st_uid, baseline.st_gid)
        os.fchmod(stage_fd, stat.S_IMODE(baseline.st_mode))
        os.fsync(stage_fd)
        current, current_stat = _read_source(parent)
        if _sha(current) != expected_sha or not _same_identity(baseline, current_stat):
            raise HostsManageError("Hosts changed after review; refresh before modifying")
        try:
            os.replace(staged, "hosts", src_dir_fd=parent, dst_dir_fd=parent)
            replaced = True
            os.fsync(parent)
        except OSError as exc:
            raise HostsManageError("Hosts write outcome uncertain; inspect and recover", recovery_id) from exc
    finally:
        os.close(stage_fd)
        if not replaced:
            try:
                os.unlink(staged, dir_fd=parent)
            except FileNotFoundError:
                pass
    after, _ = _read_source(parent)
    if after != payload:
        raise HostsManageError("Hosts write outcome uncertain; inspect recovery", recovery_id)


def inspect_recovery(site, *, data_dir=DATA_DIR, source_path=HOSTS_PATH):
    """Read-only summary; no site/file mutation on inspection."""
    fd = _open_state_dir(data_dir)
    try:
        # Journal files are committed by atomic replace: observation never
        # creates or acquires a write lock or modifies persistent state.
        try:
            row = _record(fd, site)
        except HostsManageError:
            # An old/malformed/reassigned journal must not disable the
            # baseline read-only hosts diagnostic. It remains an explicit
            # recovery blocker, never evidence that removal is authorized.
            return {"state": "Needs Review", "recovery_id": None,
                    "domain": None}
    finally:
        os.close(fd)
    if row is None:
        return {"state": "None", "recovery_id": None, "domain": None}
    parent = _open_parent(source_path)
    try:
        current, _ = _read_source(parent)
    finally:
        os.close(parent)
    actual = _sha(current)
    state = row["phase"]
    if row["phase"] == "restored":
        state = "restored" if actual == row["before_sha"] else "Needs Review"
    else:
        state = ("Applied" if actual == row["after_sha"] else
                 "Not Applied" if actual == row["before_sha"] else "Needs Review")
    return {"state": state, "recovery_id": row["operation"], "domain": row["domain"]}


def remove_loopback_alias(*, site, domains, domain, expected_sha,
                          source_path=HOSTS_PATH, data_dir=DATA_DIR):
    names, _ = _site_domains(domains)
    if (not isinstance(domain, str) or domain not in names or
            domain in ("localhost", "ip6-localhost", "ip6-loopback") or
            not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha)):
        raise HostsManageError("Select a current exact website alias and refresh inspection")
    with _locked_state(data_dir) as state:
        existing = _record(state, site)
        parent = _open_parent(source_path)
        try:
            before, meta = _read_source(parent)
            if _sha(before) != expected_sha:
                raise HostsManageError("Hosts file changed after inspection; refresh")
            if existing is not None and existing["phase"] != "restored":
                if existing["after_sha"] == _sha(before):
                    raise HostsManageError(
                        "Restore the active hosts recovery before another edit",
                        existing["operation"])
                # An external tool changed the file since the old operation.
                # A fresh, explicitly reviewed edit may continue, but the old
                # whole-file Restore cannot be applied to this new source.
                backup = _read_owned(state, existing["backup"], required=True)
                if _sha(backup) != existing["before_sha"]:
                    raise HostsManageError("Previous hosts recovery backup is invalid")
            # The existing reader's site/domain checks apply to the same file
            # and reject malformed hosts entries, not just the selected one.
            snapshot = inspect_local_hosts(domains, source_path=source_path)
            if snapshot["hosts_sha256"] != expected_sha:
                raise HostsManageError("Hosts file changed during preflight")
            if not any(item["domain"] == domain and item["loopback"]
                       for item in snapshot["entries"]):
                raise HostsManageError("Selected alias has no current loopback mapping")
            after, removed = _remove_domain_aliases(before, domain)
            if removed == 0 or after == before or not after:
                raise HostsManageError("No eligible alias could be removed safely")
            op = uuid4().hex
            row = {
                "schema": 1, "site_id": site["id"], "site_key": site["name"],
                "site_snapshot_sha": _site_fingerprint(site),
                "domain": domain, "operation": op, "phase": "prepared",
                "before_sha": _sha(before), "after_sha": _sha(after),
                "backup": _backup_name(site["id"], op), "uid": meta.st_uid,
                "gid": meta.st_gid, "mode": stat.S_IMODE(meta.st_mode),
            }
            _new_file(state, row["backup"], before)
            os.fsync(state)
            if existing is not None and existing["phase"] != "restored":
                _archive_obsolete_record(state, site, existing)
            _save_record(state, site, row)
            _replace_source(parent, after, meta, expected_sha=_sha(before), recovery_id=op)
            row["phase"] = "applied"
            try:
                _save_record(state, site, row)
            except Exception as exc:
                raise HostsManageError("Hosts updated but journal completion is uncertain; inspect recovery", op) from exc
            # Removing the alias does not prove DNS, resolver or Gateway behavior.
            return {"state": "Alias Removed", "changed": True, "read_only": False,
                    "domain": domain, "removed_aliases": removed,
                    "hosts_sha256": _sha(after), "recovery_id": op,
                    "remote_dns_verified": False, "gateway_verified": False}
        finally:
            os.close(parent)


def restore_loopback_alias(*, site, expected_recovery_id,
                           source_path=HOSTS_PATH, data_dir=DATA_DIR):
    if not isinstance(expected_recovery_id, str) or not _OP.fullmatch(expected_recovery_id):
        raise HostsManageError("Select a saved hosts Recovery ID first")
    with _locked_state(data_dir) as state:
        row = _record(state, site)
        if row is None or row["operation"] != expected_recovery_id:
            raise HostsManageError("No matching saved hosts recovery exists")
        if row["phase"] == "restored":
            raise HostsManageError("Hosts aliases are already restored")
        backup = _read_owned(state, row["backup"], required=True)
        if _sha(backup) != row["before_sha"]:
            raise HostsManageError("Original hosts backup failed integrity verification")
        parent = _open_parent(source_path)
        try:
            current, meta = _read_source(parent)
            current_sha = _sha(current)
            if current_sha not in (row["after_sha"], row["before_sha"]):
                raise HostsManageError("Hosts changed since Apply; automatic Restore is unsafe",
                                       row["operation"])
            if (meta.st_uid, meta.st_gid, stat.S_IMODE(meta.st_mode)) != (
                    row["uid"], row["gid"], row["mode"]):
                raise HostsManageError("Hosts ownership/mode changed since Apply")
            changed = current_sha == row["after_sha"]
            if changed:
                _replace_source(parent, backup, meta, expected_sha=current_sha,
                                recovery_id=row["operation"])
            # A prepared operation that never reached the source is safely
            # reconciled without any redundant file write.
            row["phase"] = "restored"
            try:
                _save_record(state, site, row)
            except Exception as exc:
                raise HostsManageError("Hosts Restore committed but journal update is uncertain",
                                       row["operation"]) from exc
            return {"state": "Restored", "changed": changed, "read_only": False,
                    "domain": row["domain"], "hosts_sha256": row["before_sha"],
                    "recovery_id": row["operation"], "remote_dns_verified": False,
                    "gateway_verified": False}
        finally:
            os.close(parent)
