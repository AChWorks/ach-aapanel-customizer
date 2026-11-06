"""Bounded read-only Linux PHP-FPM master/listener observation.

A positive result means that a specific native PHP binary appears as one
master process with the exact main configuration path and has an open fd for
the bound Unix listening socket. This is NOT PHP request acceptance, an
effective pool-setting probe, shared-impact authorization or Apply eligibility.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from ach_customizer_monitor import (
    MonitorInputError, discover_php_fpm_versions, _bounded_file_text,
    _single_www_listen, MAX_CONFIG_BYTES,
)

MAX_PROCESSES = 4096
MAX_MASTER_MATCHES = 8
MAX_MASTER_FDS = 256
MAX_PROC_CMD = 4096
MAX_PROC_STAT = 8192
MAX_UNIX_LIST = 256 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
VERSION = re.compile(r"[1-9][0-9]{1,2}\Z")
NOTE = (
    "Read-only point-in-time Linux procfs and Unix-listener observation. "
    "Does not prove PHP requests, effective pool settings, Nginx routing, "
    "site impact, or authorize any PHP-FPM Apply/Restore."
)


class RuntimeInspectError(MonitorInputError):
    pass


def _open_directory(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeInspectError("Noncanonical runtime source pathname")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            following = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = following
        return fd
    except BaseException:
        os.close(fd)
        raise


def _native_binary(path):
    parent = _open_directory(Path(path).parent)
    try:
        fd = os.open(Path(path).name, FILE_FLAGS, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_size <= 0 or not info.st_mode & 0o111 or
                    info.st_mode & 0o022):
                raise RuntimeInspectError("Native PHP-FPM binary ownership/mode needs review")
            bound = os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False)
            if (bound.st_dev, bound.st_ino, bound.st_mtime_ns) != (
                    info.st_dev, info.st_ino, info.st_mtime_ns):
                raise RuntimeInspectError("PHP-FPM binary pathname changed")
            return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _bounded_proc_file(path, limit):
    fd = os.open(path, FILE_FLAGS)
    try:
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, limit + 1 - len(data))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > limit:
            raise RuntimeInspectError("Oversized Linux process evidence")
        return bytes(data)
    finally:
        os.close(fd)


def _process_start(proc_root, pid):
    raw = _bounded_proc_file(Path(proc_root) / pid / "stat", MAX_PROC_STAT)
    # /proc/<pid>/stat field 2 (comm) can contain nested whitespace/")".
    suffix = raw.decode("ascii", "strict").rsplit(") ", 1)
    if len(suffix) != 2 or not suffix[0].startswith(pid + " ("):
        raise RuntimeInspectError("Unsupported Linux process identity")
    fields = suffix[1].split()
    if len(fields) < 20 or not fields[19].isdigit():
        raise RuntimeInspectError("Incomplete Linux process start identity")
    return fields[19]


def _master_title(proc_root, pid, config_path):
    raw = _bounded_proc_file(Path(proc_root) / pid / "cmdline", MAX_PROC_CMD)
    if not raw:
        return False
    # FPM rewrites its process title. No generic substring matching, no
    # command-line disclosure or fabricated config association.
    title = raw.split(b"\x00", 1)[0].decode("utf-8", "strict")
    return title == "php-fpm: master process (" + config_path + ")"


def _exe_matches(proc_root, pid, expected):
    info = os.stat(Path(proc_root) / pid / "exe")
    return (info.st_dev, info.st_ino) == expected[:2]


def _find_masters(proc_root, expected, config_path):
    fd = _open_directory(proc_root)
    try:
        pids = []
        with os.scandir(fd) as entries:
            for entry in entries:
                name = entry.name
                if not name.isascii() or not name.isdecimal():
                    continue
                if len(pids) >= MAX_PROCESSES:
                    raise RuntimeInspectError("Too many Linux PIDs to inspect reliably")
                pids.append(name)
        matches = []
        denied = False
        for pid in sorted(pids, key=int):
            try:
                start = _process_start(proc_root, pid)
                if _exe_matches(proc_root, pid, expected) and _master_title(
                        proc_root, pid, config_path):
                    matches.append((pid, start))
                    if len(matches) > MAX_MASTER_MATCHES:
                        raise RuntimeInspectError("Ambiguous PHP-FPM master process count")
            except (FileNotFoundError, ProcessLookupError):
                continue  # Process exited between procfs directory and inspection.
            except PermissionError:
                denied = True
            except (UnicodeError, ValueError, RuntimeInspectError, OSError):
                # A process we cannot inspect prevents a negative identity
                # claim. Known-matching masters still require later checks.
                denied = True
        return matches, denied
    finally:
        os.close(fd)


def _socket_identity(path):
    file_path = Path(path)
    parent = _open_directory(file_path.parent)
    try:
        info = os.stat(file_path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISSOCK(info.st_mode) or info.st_nlink != 1:
            raise RuntimeInspectError("FPM listen path is not a native Unix socket")
        return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid
    finally:
        os.close(parent)


def _listening_inode(proc_root, socket_path):
    """Use kernel /proc/net/unix LISTEN inode, not filesystem socket inode."""
    raw = _bounded_proc_file(Path(proc_root) / "net" / "unix", MAX_UNIX_LIST)
    lines = raw.decode("utf-8", "strict").splitlines()
    if not lines or not lines[0].startswith("Num "):
        raise RuntimeInspectError("Unsupported Linux Unix-socket table")
    matches = []
    for line in lines[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) != 8 or fields[7] != socket_path:
            continue
        if not fields[6].isdigit():
            raise RuntimeInspectError("Malformed kernel Unix-socket inode")
        if fields[4] != "0001" or int(fields[3], 16) & 0x10000 == 0:
            raise RuntimeInspectError("Named Unix socket is not a listening stream")
        matches.append(fields[6])
        if len(matches) > 1:
            raise RuntimeInspectError("Ambiguous native Unix listening socket")
    return matches[0] if matches else None


def _master_holds_listener(proc_root, pid, inode):
    fd = _open_directory(Path(proc_root) / pid / "fd")
    try:
        count = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                if count >= MAX_MASTER_FDS:
                    raise RuntimeInspectError("Master has too many file descriptors for bounded inspection")
                count += 1
                if not entry.name.isdecimal():
                    continue
                try:
                    link = os.readlink(entry.name, dir_fd=fd)
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if link == "socket:[" + inode + "]":
                    return True
        return False
    finally:
        os.close(fd)


def inspect_php_fpm_runtime(config_root, version, *, proc_root="/proc"):
    """Observe exactly one native master+listener without running any program.

    Unknown or unreadable procfs, multiple masters, included pool layouts,
    mismatched binaries or socket changes fail closed as Needs Review.
    """
    result = {
        "schema": 1, "version": version, "state": "Needs Review",
        "read_only": True, "runtime_verified": False, "apply_eligible": False,
        "master_state": "Needs Review", "socket_state": "Needs Review",
        "master_pid": None, "socket_path": None,
        "reason": "", "note": NOTE,
    }
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise RuntimeInspectError("Select a valid discovered PHP version")
    major, minor = int(version[0]), int(version[1:])
    if (major, minor) < (8, 1):
        result["reason"] = "Only PHP 8.1+ is supported for this runtime inspection"
        return result
    if not Path(config_root).is_absolute() or ".." in Path(config_root).parts:
        raise RuntimeInspectError("Noncanonical aaPanel PHP root")
    binary = str(Path(config_root) / version / "sbin" / "php-fpm")
    conf = str(Path(config_root) / version / "etc" / "php-fpm.conf")
    try:
        discovered = discover_php_fpm_versions(config_root)
        eligible = [item for item in discovered["versions"]
                    if item["code"] == version and item["preview_candidate"]]
        if not eligible:
            result["reason"] = "Selected version is not a stable, complete native PHP file candidate"
            return result
        original_binary = _native_binary(binary)
        config_text, config_sig = _bounded_file_text(
            Path(conf), MAX_CONFIG_BYTES, with_fingerprint=True)
        # Ambiguous included pools are not modeled as a matching live config.
        if any(
                re.match(r"(?i)^include\s*=", line.split(";", 1)[0].split("#", 1)[0].strip())
                for line in config_text.splitlines()):
            result["reason"] = "Included/multiple PHP pools require a separate native runtime adapter"
            return result
        socket_path = _single_www_listen(conf)
        if len(socket_path) > 200:
            raise RuntimeInspectError("Oversized PHP-FPM Unix socket path")
        result["socket_path"] = socket_path
        matches, denied = _find_masters(proc_root, original_binary, conf)
        if len(matches) != 1 or denied:
            result["master_state"] = "Not Observed" if not matches and not denied else "Needs Review"
            result["reason"] = (
                "No matching PHP-FPM master process observed; this does not prove service stopped"
                if not matches and not denied else
                "Master process identity is ambiguous or Linux procfs is inaccessible"
            )
            return result
        pid, start = matches[0]
        result["master_state"] = "Matching Master"
        result["master_pid"] = int(pid)
        try:
            original_socket = _socket_identity(socket_path)
        except FileNotFoundError:
            result["state"] = "Partial"
            result["socket_state"] = "Missing"
            result["reason"] = "Matching PHP master exists but its Unix socket path is missing"
            return result
        inode = _listening_inode(proc_root, socket_path)
        if inode is None:
            result["state"] = "Partial"
            result["socket_state"] = "Not Observed"
            result["reason"] = "PHP socket pathname exists but no matching kernel listener was observed"
            return result
        if not _master_holds_listener(proc_root, pid, inode):
            result["state"] = "Partial"
            result["socket_state"] = "Not Observed"
            result["reason"] = "The matching PHP master did not own the observed Unix listener"
            return result
        # Pin point-in-time associations again after traversing procfs:
        # detect binary/config/socket drift or recycled PIDs before reporting.
        if (_native_binary(binary) != original_binary or
                _bounded_file_text(Path(conf), MAX_CONFIG_BYTES, with_fingerprint=True)[1]
                != config_sig or
                _single_www_listen(conf) != socket_path or
                _socket_identity(socket_path) != original_socket or
                _process_start(proc_root, pid) != start or
                not _exe_matches(proc_root, pid, original_binary) or
                not _master_title(proc_root, pid, conf) or
                _listening_inode(proc_root, socket_path) != inode or
                not _master_holds_listener(proc_root, pid, inode)):
            raise RuntimeInspectError("PHP process, configuration or socket changed during observation")
        result.update(
            state="Observed", socket_state="Bound Listener", reason="",
        )
    except (MonitorInputError, RuntimeInspectError, OSError, UnicodeError, ValueError) as exc:
        # The runtime subset may be incomplete or inaccessible. Never claim
        # the PHP service is down or that another version can be modified.
        result.update(state="Needs Review", master_state="Needs Review",
                      socket_state="Needs Review", master_pid=None,
                      reason=str(exc)[:250])
    return result
