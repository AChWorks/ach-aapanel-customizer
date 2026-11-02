"""Persistent, plugin-owned Monitor controls outside replaceable aaPanel plugin code.

No website/service configuration changes are made here. Reads never create a
state file. Writes are authenticated by the plugin entrypoint, serialized,
validated and committed by an atomic replacement of one root-owned file.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import time
from pathlib import Path
from uuid import uuid4

DATA_DIR = "/www/server/panel/data"
STATE_FILE = "ach_customizer.state.json"
LOCK_FILE = "ach_customizer.state.lock"
SCHEMA_VERSION = 1
MODULES = ("site_inventory", "php_fpm_file_preview")
MAX_STATE_BYTES = 4096
LOCK_TIMEOUT_SECONDS = 3.0

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class StateError(RuntimeError):
    """Missing state is valid; malformed, untrusted or inaccessible state is not."""


def _default_state():
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "enabled": True,
        "modules": {name: True for name in MODULES},
    }


def _validated(state):
    if not isinstance(state, dict) or set(state) != {
        "schema_version", "revision", "enabled", "modules"
    }:
        raise StateError("Unsupported or malformed Monitor state")
    if type(state["schema_version"]) is not int or state["schema_version"] != SCHEMA_VERSION:
        raise StateError("Unsupported Monitor state version")
    if type(state["revision"]) is not int or not 0 <= state["revision"] <= 2147483647:
        raise StateError("Invalid Monitor state revision")
    if type(state["enabled"]) is not bool:
        raise StateError("Invalid overall Monitor state")
    modules = state["modules"]
    if not isinstance(modules, dict) or set(modules) != set(MODULES):
        raise StateError("Invalid Monitor module state")
    if any(type(modules[name]) is not bool for name in MODULES):
        raise StateError("Invalid Monitor module switch")
    return state


def _owned_file(fd, *, kind):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
        raise StateError("Untrusted Monitor " + kind + " file")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise StateError("Insecure Monitor " + kind + " permissions")
    return info


def _open_state_dir(path):
    """Open every ancestor without following symlinks, returning anchored fd."""
    path = Path(path)
    if not path.is_absolute() or any(part in (".", "..") for part in path.parts):
        raise StateError("Monitor state directory must be an absolute normal path")
    fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        for segment in path.parts[1:]:
            next_fd = os.open(segment, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise StateError("Untrusted Monitor state directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_at(directory_fd):
    try:
        fd = os.open(STATE_FILE, _READ_FLAGS, dir_fd=directory_fd)
    except FileNotFoundError:
        return _default_state()
    except OSError as exc:
        raise StateError("Cannot safely open Monitor state") from exc
    try:
        info = _owned_file(fd, kind="state")
        if not 0 < info.st_size <= MAX_STATE_BYTES:
            raise StateError("Monitor state exceeds the supported size")
        data = bytearray()
        while len(data) <= MAX_STATE_BYTES:
            chunk = os.read(fd, MAX_STATE_BYTES + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if not data or len(data) > MAX_STATE_BYTES:
            raise StateError("Monitor state is empty or oversized")
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise StateError("Monitor state is not valid JSON") from exc
        return _validated(parsed)
    finally:
        os.close(fd)


def read_state(directory=DATA_DIR):
    directory_fd = _open_state_dir(directory)
    try:
        return _read_at(directory_fd)
    finally:
        os.close(directory_fd)


def _exclusive_lock(directory_fd):
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=directory_fd)
    try:
        _owned_file(fd, kind="lock")
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise StateError("Monitor state update is busy")
                time.sleep(0.05)
    except BaseException:
        os.close(fd)
        raise


def _atomic_write(directory_fd, state):
    payload = (json.dumps(state, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_STATE_BYTES:
        raise StateError("Monitor state exceeds the supported size")
    temporary = ".ach_customizer.state." + uuid4().hex + ".tmp"
    temp_fd = os.open(temporary, _WRITE_FLAGS, 0o600, dir_fd=directory_fd)
    replaced = False
    try:
        _owned_file(temp_fd, kind="temporary state")
        with os.fdopen(temp_fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(temp_fd)
        os.replace(temporary, STATE_FILE,
                   src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        replaced = True
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            # The rename may have committed: a retry must first re-read state.
            raise StateError("Monitor state commit is uncertain; inspect current revision") from exc
    finally:
        os.close(temp_fd)
        if not replaced:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def parse_enabled(value):
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise StateError("Enabled value must be true or false")


def parse_revision(value):
    """Strict optimistic concurrency token from the current Monitor overview."""
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
        number = int(value)
    else:
        raise StateError("Expected Monitor state revision is required")
    if not 0 <= number <= 2147483647:
        raise StateError("Expected Monitor state revision is outside the supported range")
    return number


def set_enabled(control, enabled, *, expected_revision, directory=DATA_DIR):
    """Persist a Monitor flag only against the exact revision the operator saw."""
    if control != "overall" and control not in MODULES:
        raise StateError("Unknown Monitor control")
    enabled = parse_enabled(enabled)
    expected_revision = parse_revision(expected_revision)
    directory_fd = _open_state_dir(directory)
    try:
        lock_fd = _exclusive_lock(directory_fd)
        try:
            state = _read_at(directory_fd)
            if state["revision"] != expected_revision:
                raise StateError("Monitor state revision changed; reopen Overview before retrying")
            if control == "overall":
                old = state["enabled"]
            else:
                old = state["modules"][control]
            if old == enabled:
                return state, False
            if state["revision"] >= 2147483647:
                raise StateError("Monitor state revision exhausted")
            updated = {
                "schema_version": SCHEMA_VERSION,
                "revision": state["revision"] + 1,
                "enabled": state["enabled"] if control != "overall" else enabled,
                "modules": dict(state["modules"]),
            }
            if control != "overall":
                updated["modules"][control] = enabled
            _atomic_write(directory_fd, _validated(updated))
            return updated, True
        finally:
            os.close(lock_fd)
    finally:
        os.close(directory_fd)
