"""Bounded, root-owned, local JSONL activity history for the native aaPanel plugin.

Records contain explicitly allowlisted operational fields only. Never store
request bodies, Flask sessions, credentials, exception tracebacks or cookies.
Both appends and reads use descriptor-relative, no-follow file operations.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from datetime import datetime, timezone

LOG_NAME = "ach_customizer.activity.jsonl"
LOCK_NAME = "ach_customizer.activity.lock"
MAX_LOG_BYTES = 262144
MAX_RECORD_BYTES = 2048
MAX_RESULTS = 100
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
MODULES = {"monitor", "websites", "php_fpm", "status_pages", "diagnostics"}
_FIELDS = {"schema", "time_utc", "level", "module", "action", "stage",
           "outcome", "operation_id", "target", "error_class", "detail", "recovery_id"}
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC


class ActivityError(RuntimeError):
    """Activity history is unavailable or unsafe; never infer an operation failure."""


def configured_level():
    value = os.environ.get("ACH_CUSTOMIZER_ACTIVITY_LEVEL", "INFO").strip().upper()
    return value if value in LEVELS else "INFO"


def record(*, level, module, action, operation_id, stage, outcome,
           target="", error_class="", detail="", recovery_id=""):
    if level not in LEVELS or module not in MODULES:
        raise ActivityError("Invalid activity classification")
    if not isinstance(operation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", operation_id):
        raise ActivityError("Invalid activity operation identifier")
    fields = {
        "schema": 1,
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": level,
        "module": module,
        "action": str(action)[:48],
        "stage": str(stage)[:72],
        "outcome": str(outcome)[:40],
        "operation_id": operation_id,
        "target": str(target)[:120],
        "error_class": str(error_class)[:64],
        "detail": str(detail)[:240],
        "recovery_id": str(recovery_id)[:64],
    }
    for key, value in fields.items():
        if isinstance(value, str):
            # A field must never inject physical JSONL line breaks/control chars.
            fields[key] = "".join(ch if ord(ch) >= 32 else " " for ch in value)
    return fields


def _directory(directory):
    try:
        fd = os.open(directory, _DIR_FLAGS)
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            raise ActivityError("Unsafe activity directory ownership/permissions")
        return fd
    except OSError as exc:
        raise ActivityError("Cannot access activity directory") from exc


def _check_file(fd):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ActivityError("Unsafe activity file ownership/permissions")
    if info.st_size > MAX_LOG_BYTES:
        raise ActivityError("Activity file exceeds bounded size")
    return info.st_size


def _open_optional(fd_dir, name):
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=fd_dir)
    except FileNotFoundError:
        return None
    try:
        _check_file(fd)
    except Exception:
        os.close(fd)
        raise
    return fd


def _append_bytes(fd, data):
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise ActivityError("Activity append did not progress")
        view = view[count:]


def append_activity(directory, event):
    if (not isinstance(event, dict) or set(event) != _FIELDS
            or event.get("schema") != 1 or event.get("level") not in LEVELS
            or event.get("module") not in MODULES):
        raise ActivityError("Invalid activity record")
    if LEVELS[event["level"]] < LEVELS[configured_level()]:
        return True
    body = (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")
    if len(body) > MAX_RECORD_BYTES:
        raise ActivityError("Activity record too large")
    fd_dir = _directory(directory)
    try:
        fd_lock = os.open(LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                          0o600, dir_fd=fd_dir)
        try:
            _check_file(fd_lock)
            fcntl.flock(fd_lock, fcntl.LOCK_EX)
            fd = os.open(LOG_NAME, _WRITE_FLAGS, 0o600, dir_fd=fd_dir)
            try:
                size = _check_file(fd)
                if size + len(body) > MAX_LOG_BYTES:
                    old = _open_optional(fd_dir, LOG_NAME + ".1")
                    if old is not None:
                        os.close(old)
                    os.close(fd)
                    fd = None
                    os.replace(LOG_NAME, LOG_NAME + ".1",
                               src_dir_fd=fd_dir, dst_dir_fd=fd_dir)
                    fd = os.open(LOG_NAME, _WRITE_FLAGS | os.O_EXCL, 0o600, dir_fd=fd_dir)
                    _check_file(fd)
                    os.fsync(fd_dir)
                _append_bytes(fd, body)
                os.fsync(fd)
                # Persist a newly created directory entry as well as log bytes.
                os.fsync(fd_dir)
            finally:
                if fd is not None:
                    os.close(fd)
        finally:
            os.close(fd_lock)
    except (OSError, ActivityError) as exc:
        raise ActivityError("Activity persistence failed: " + type(exc).__name__) from exc
    finally:
        os.close(fd_dir)
    return True


def read_activity(directory, *, level="", module="", limit=50):
    if level and level not in LEVELS:
        raise ActivityError("Invalid severity filter")
    if module and module not in MODULES:
        raise ActivityError("Invalid module filter")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ActivityError("Invalid activity page size")
    fd_dir = _directory(directory)
    try:
        try:
            fd_lock = os.open(LOCK_NAME, _READ_FLAGS, dir_fd=fd_dir)
        except FileNotFoundError:
            # Reading a fresh install must not create any persistent state.
            for name in (LOG_NAME, LOG_NAME + ".1"):
                try:
                    os.stat(name, dir_fd=fd_dir, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise ActivityError("Activity history exists without its lock")
            return []
        try:
            _check_file(fd_lock)
            fcntl.flock(fd_lock, fcntl.LOCK_SH)
            items = []
            for filename in (LOG_NAME + ".1", LOG_NAME):
                fd = _open_optional(fd_dir, filename)
                if fd is None:
                    continue
                try:
                    data = bytearray()
                    while True:
                        part = os.read(fd, 32768)
                        if not part:
                            break
                        data.extend(part)
                        if len(data) > MAX_LOG_BYTES:
                            raise ActivityError("Activity read exceeded size limit")
                finally:
                    os.close(fd)
                for line in bytes(data).splitlines():
                    try:
                        item = json.loads(line)
                    except (ValueError, UnicodeDecodeError) as exc:
                        raise ActivityError("Unreadable activity history") from exc
                    if (not isinstance(item, dict) or set(item) != _FIELDS
                            or item.get("schema") != 1
                            or item.get("level") not in LEVELS
                            or item.get("module") not in MODULES):
                        raise ActivityError("Unsupported activity record")
                    if (level and item["level"] != level) or (module and item["module"] != module):
                        continue
                    items.append(item)
            return list(reversed(items[-limit:]))
        finally:
            os.close(fd_lock)
    finally:
        os.close(fd_dir)
