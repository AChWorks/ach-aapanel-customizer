"""Guarded, reversible manual PHP-FPM [www] policy for one verified aaPanel layout.

No entrypoint, scheduler or automatic enforcement is registered here. A trusted
full-administrator aaPanel endpoint must provide POST/CSRF/authorization,
operator confirmation and version/affected-site gates before calling apply().
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from ach_customizer_monitor import (
    POOL_KEYS, MonitorInputError, _parse_pool_text, expected_pool_values, preview_php_fpm,
)

MAX_BYTES = 256 * 1024
VERSION = "85"  # Existing PHP 8.5 default, retained for recovery compatibility.
SUPPORTED_VERSIONS = ("81", "85")  # Independently bounded native aaPanel adapters.
LOCK_TIMEOUT = 3.0
JOURNAL = "ach_customizer.fpm85.recovery.json"
SNAPSHOT = "ach_customizer.fpm85.recovery.before"
# Keep the original lock name as a shared lock for both versioned writers,
# including older resident PHP 8.5 workers during a panel-plugin ZIP upgrade.
LOCK = "ach_customizer.fpm85.recovery.lock"


def _recovery_names(version):
    if version not in SUPPORTED_VERSIONS:
        raise FpmApplyError("compatibility", "Unsupported PHP-FPM recovery version")
    return ("ach_customizer.fpm" + version + ".recovery.json",
            "ach_customizer.fpm" + version + ".recovery.before")


DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class FpmApplyError(RuntimeError):
    def __init__(self, stage, message):
        super().__init__(message)
        self.stage = stage


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _dir(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise FpmApplyError("ownership", "Expected a normal absolute directory")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            following = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = following
        st = os.fstat(fd)
        if st.st_uid != os.geteuid() or st.st_mode & 0o022:
            raise FpmApplyError("ownership", "Directory ownership or permissions are unsafe")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(fd_dir, name, *, max_bytes=MAX_BYTES, mode=None):
    fd = os.open(name, READ_FLAGS, dir_fd=fd_dir)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or st.st_mode & 0o022
                or (mode is not None and stat.S_IMODE(st.st_mode) != mode)
                or not 0 < st.st_size <= max_bytes):
            raise FpmApplyError("ownership", "Untrusted configuration or recovery file")
        # Atomic replacement preserves bytes, POSIX owner/group and mode,
        # but not arbitrary ACL/security xattrs. Refuse rather than lose them.
        try:
            attributes = os.listxattr(fd)
        except OSError as exc:
            raise FpmApplyError("ownership", "Cannot inspect file extended attributes") from exc
        if attributes:
            raise FpmApplyError("compatibility", "Extended file attributes are not supported by this adapter")
        chunks = bytearray()
        while len(chunks) <= max_bytes:
            item = os.read(fd, max_bytes + 1 - len(chunks))
            if not item:
                break
            chunks.extend(item)
        if not chunks or len(chunks) > max_bytes:
            raise FpmApplyError("ownership", "Configuration size changed unexpectedly")
        return bytes(chunks), st
    finally:
        os.close(fd)


def _write_new(fd_dir, name, data, *, mode):
    fd = os.open(name, CREATE_FLAGS, mode, dir_fd=fd_dir)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as f:
            f.write(data)
            f.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(fd_dir)


def _replace(fd_dir, target, data, st, *, prefix):
    current, actual_stat = _read(fd_dir, target)
    if (actual_stat.st_dev != st.st_dev or actual_stat.st_ino != st.st_ino) or _sha(current) != _sha(st.expected_bytes):
        raise FpmApplyError("conflict", "PHP-FPM file changed after the operator's preview")
    temporary = "." + prefix + "." + uuid4().hex + ".tmp"
    temp_fd = os.open(temporary, CREATE_FLAGS, stat.S_IMODE(st.st_mode), dir_fd=fd_dir)
    committed = False
    try:
        os.fchmod(temp_fd, stat.S_IMODE(st.st_mode))
        if os.geteuid() == 0:
            os.fchown(temp_fd, st.st_uid, st.st_gid)
        with os.fdopen(temp_fd, "wb", closefd=False) as f:
            f.write(data)
            f.flush()
        os.fsync(temp_fd)
        # A last identity and digest check detects external rewrites before
        # atomic replacement. External aaPanel writes do not honor our lock.
        newest, newest_stat = _read(fd_dir, target)
        if (newest_stat.st_dev != st.st_dev or newest_stat.st_ino != st.st_ino) or newest != st.expected_bytes:
            raise FpmApplyError("conflict", "PHP-FPM file was rewritten before mutation")
        os.replace(temporary, target, src_dir_fd=fd_dir, dst_dir_fd=fd_dir)
        committed = True
        os.fsync(fd_dir)
    finally:
        os.close(temp_fd)
        if not committed:
            try:
                os.unlink(temporary, dir_fd=fd_dir)
            except FileNotFoundError:
                pass


class _Expected:
    def __init__(self, st, expected_bytes):
        self.st_mode = st.st_mode
        self.st_uid = st.st_uid
        self.st_gid = st.st_gid
        self.st_ino = st.st_ino
        self.st_dev = st.st_dev
        self.expected_bytes = expected_bytes


def _plan_bytes(before, desired):
    if len(before) > MAX_BYTES or b"\x00" in before or b"\r" in before:
        raise FpmApplyError("compatibility", "Unsupported FPM configuration encoding/layout")
    try:
        lines = before.decode("utf-8").splitlines(keepends=True)
    except UnicodeError as exc:
        raise FpmApplyError("compatibility", "PHP-FPM configuration is not UTF-8") from exc
    section = None
    seen = set()
    last_directive = None
    output = []
    www_count = 0
    for raw in lines:
        trimmed = raw.strip()
        if trimmed.startswith("[") and trimmed.endswith("]"):
            section = trimmed[1:-1].strip()
            if section not in ("global", "www"):
                raise FpmApplyError("compatibility", "Only a direct [global] and [www] pool are supported")
            if section == "www":
                www_count += 1
            output.append(raw)
            continue
        if not trimmed or trimmed.startswith((";", "#")):
            output.append(raw)
            continue
        if "=" not in trimmed:
            raise FpmApplyError("compatibility", "Malformed PHP-FPM directive")
        key = trimmed.split("=", 1)[0].strip().lower()
        if key == "include":
            raise FpmApplyError("compatibility", "FPM includes require review before a manual write")
        if section == "www" and key in POOL_KEYS:
            if key in seen:
                raise FpmApplyError("compatibility", "Duplicate PHP-FPM setting")
            seen.add(key)
            # Replace only the numeric value, preserving comments and whitespace.
            matcher = re.fullmatch(r"(\s*[^=\n]+?\s*=\s*)([0-9]+)([ \t]*(?:[;#][^\n]*)?)(\n?)", raw)
            if not matcher:
                raise FpmApplyError("compatibility", "Unsupported PHP-FPM value layout")
            output.append(matcher.group(1) + str(desired[key]) + matcher.group(3) + matcher.group(4))
            last_directive = len(output)
        else:
            output.append(raw)
    if www_count != 1 or set(POOL_KEYS[:-1]) - seen:
        raise FpmApplyError("compatibility", "Exactly one direct dynamic [www] pool is required")
    if "pm.max_requests" not in seen and desired["pm.max_requests"] != 0:
        if last_directive is None:
            raise FpmApplyError("compatibility", "No insertion point in [www]")
        if not output[last_directive - 1].endswith("\n"):
            raise FpmApplyError("compatibility", "Unterminated FPM directive")
        output.insert(last_directive, "pm.max_requests = " + str(desired["pm.max_requests"]) + "\n")
    return "".join(output).encode("utf-8")



def require_native_runtime_paths(config_root, version, source=None):
    """PHP81 writer accepts only the exact runtime layout its hooks verify.

    A source-derived site file map alone can admit a different socket. Check
    the actual root-owned FPM config before Prepare and under the Apply lock.
    PHP85 is deliberately unchanged for existing recovery compatibility.
    """
    if version != "81":
        return
    if source is None:
        fd_dir = _dir(Path(config_root) / version / "etc")
        try:
            source, _ = _read(fd_dir, "php-fpm.conf")
        finally:
            os.close(fd_dir)
    if len(source) > MAX_BYTES or b"\x00" in source or b"\r" in source:
        raise FpmApplyError("compatibility", "Unsupported PHP 8.1 runtime source")
    try:
        content = source.decode("utf-8")
    except UnicodeError as exc:
        raise FpmApplyError("compatibility", "PHP 8.1 runtime source is not UTF-8") from exc
    expected = {
        ("global", "pid"): str(Path(config_root) / version / "var/run/php-fpm.pid"),
        ("www", "listen"): "/tmp/php-cgi-81.sock",
    }
    found = {key: [] for key in expected}
    section = None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line:
            continue
        key, value = (item.strip() for item in line.split("=", 1))
        field = (section, key.lower())
        if field in found:
            found[field].append(value)
    for field, expected_value in expected.items():
        if (len(found[field]) != 1 or not re.fullmatch(
                re.escape(expected_value) + r"(?:[ \t]+[;#][^\r\n]*)?",
                found[field][0])):
            raise FpmApplyError(
                "compatibility",
                "PHP 8.1 [global] pid and [www] socket must match the verified native service layout"
            )

def _plan(config_root, version, desired):
    if version not in SUPPORTED_VERSIONS:
        raise FpmApplyError("compatibility", "Only verified PHP 8.1 and PHP 8.5 pools support Manual Apply")
    desired = expected_pool_values(desired)
    folder = Path(config_root) / version / "etc"
    fd_dir = _dir(folder)
    try:
        before, st = _read(fd_dir, "php-fpm.conf")
        require_native_runtime_paths(config_root, version, before)
        preview = preview_php_fpm(config_root, version, desired)
        if (preview.get("state") not in ("File Match", "File Drift")
                or preview.get("source") != str(folder / "php-fpm.conf")):
            raise FpmApplyError("compatibility", "PHP-FPM layout is not eligible for manual Apply")
        after = _plan_bytes(before, desired)
        unchanged, same_stat = _read(fd_dir, "php-fpm.conf")
        if unchanged != before or (same_stat.st_dev != st.st_dev or same_stat.st_ino != st.st_ino):
            raise FpmApplyError("conflict", "PHP-FPM changed during preview")
        return {"version":version, "scope":"shared_service", "pool":"www",
                "before_sha256":_sha(before), "after_sha256":_sha(after),
                "changes":preview["changes"], "desired":desired,
                "source":str(folder / "php-fpm.conf"),
                "note":"File-only plan, not effective-runtime proof; all pool consumers may be affected."}, before, after, st
    finally:
        os.close(fd_dir)


def preview(config_root, version, desired):
    return _plan(config_root, version, desired)[0]


def _lock(state_dir):
    fd_dir = _dir(state_dir)
    try:
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd_dir)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600:
                raise FpmApplyError("ownership", "Unsafe manual Apply lock")
            deadline = time.monotonic() + LOCK_TIMEOUT
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise FpmApplyError("busy", "Another PHP-FPM operation is in progress")
                    time.sleep(.05)
            return fd_dir, fd
        except BaseException:
            os.close(fd)
            raise
    except BaseException:
        os.close(fd_dir)
        raise


def _read_journal(fd_dir, version=VERSION):
    journal, _ = _recovery_names(version)
    try:
        data, _ = _read(fd_dir, journal, max_bytes=4096, mode=0o600)
    except FileNotFoundError:
        return None
    try:
        record = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise FpmApplyError("recovery", "Unreadable PHP-FPM recovery journal") from exc
    required = {"schema", "operation_id", "version", "phase", "before_sha256", "after_sha256", "timestamp"}
    if not isinstance(record, dict) or set(record) != required or record["schema"] != 1 or record["version"] != version:
        raise FpmApplyError("recovery", "Unsupported PHP-FPM recovery journal")
    if (record["phase"] not in ("prepared", "applied", "uncertain")
            or not isinstance(record["operation_id"], str)
            or not re.fullmatch("[0-9a-f]{32}", record["operation_id"])
            or any(not isinstance(record[k], str) or not re.fullmatch("[0-9a-f]{64}", record[k]) for k in ("before_sha256", "after_sha256"))):
        raise FpmApplyError("recovery", "Invalid PHP-FPM recovery journal")
    return record


def _persist_journal(fd_dir, record):
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    journal, _ = _recovery_names(record["version"])
    temporary = ".ach_customizer.fpm" + record["version"] + ".journal." + uuid4().hex + ".tmp"
    try:
        _write_new(fd_dir, temporary, payload, mode=0o600)
        os.replace(temporary, journal, src_dir_fd=fd_dir, dst_dir_fd=fd_dir)
        os.fsync(fd_dir)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd_dir)
        except FileNotFoundError:
            pass


def _remove_recovery(fd_dir, version=VERSION):
    for name in _recovery_names(version):
        os.unlink(name, dir_fd=fd_dir)
    os.fsync(fd_dir)


def _check_callbacks(validate, activate, verify):
    if not all(callable(x) for x in (validate, activate, verify)):
        raise FpmApplyError("validation", "Explicit validation/reload/runtime verification are required")


def apply(config_root, state_dir, version, desired, *, expected_before, expected_after,
          validate, activate, verify, verify_restored):
    """Manual Apply after externally verified admin, CSRF, POST and approval gates."""
    _check_callbacks(validate, activate, verify)
    if not callable(verify_restored):
        raise FpmApplyError("validation", "Independent baseline runtime verification is required")
    journal, snapshot = _recovery_names(version)
    fd_state, lock_fd = _lock(state_dir)
    try:
        existing = _read_journal(fd_state, version)
        if existing is not None:
            raise FpmApplyError("recovery", "Complete or reconcile the previous PHP-FPM operation first")
        if os.path.lexists(Path(state_dir) / snapshot):
            raise FpmApplyError("recovery", "Unpaired recovery snapshot requires operator review")
        plan, before, after, original_stat = _plan(config_root, version, desired)
        if plan["before_sha256"] != expected_before or plan["after_sha256"] != expected_after:
            raise FpmApplyError("conflict", "PHP-FPM file or desired policy differs from preview")
        if before == after:
            return {"state":"No Change", "operation_id":None, **plan}
        operation_id = uuid4().hex
        config_fd = _dir(Path(config_root) / version / "etc")
        mutation_attempted = False
        record = {"schema":1, "operation_id":operation_id, "version":version, "phase":"prepared",
                  "before_sha256":plan["before_sha256"], "after_sha256":plan["after_sha256"],
                  "timestamp":int(time.time())}
        try:
            # Stage durable exact recovery bytes and journal before changing FPM.
            _write_new(fd_state, snapshot, before, mode=0o600)
            _persist_journal(fd_state, record)
            validate()
            mutation_attempted = True
            _replace(config_fd, "php-fpm.conf", after, _Expected(original_stat, before), prefix="ach_customizer")
            validate()
            activate()
            verify()
            written, _ = _read(config_fd, "php-fpm.conf")
            if written != after:
                raise FpmApplyError("verification", "PHP-FPM was rewritten by another operation")
            record["phase"] = "applied"
            _persist_journal(fd_state, record)
            return {"state":"Applied", "operation_id":operation_id, **plan}
        except Exception as exc:
            # A rename can succeed even when its final directory fsync fails.
            # Never assume a raised write means no file was replaced.
            try:
                current, st = _read(config_fd, "php-fpm.conf")
                if current == after and mutation_attempted:
                    _replace(config_fd, "php-fpm.conf", before, _Expected(st, after),
                             prefix="ach_customizer_recover")
                    validate()
                    activate()
                    verify_restored()
                elif current == before:
                    if mutation_attempted:
                        # Even if a failed rename left the old bytes, activation
                        # state may be uncertain: revalidate and reload baseline.
                        validate()
                        activate()
                        verify_restored()
                    elif (st.st_dev != original_stat.st_dev or st.st_ino != original_stat.st_ino):
                        raise FpmApplyError("conflict", "PHP-FPM ownership changed before Apply")
                else:
                    raise FpmApplyError("conflict", "Unknown external PHP-FPM rewrite prevents recovery")
                # Check the recovery artifacts we own before removing them.
                try:
                    saved_journal = _read_journal(fd_state, version)
                except FileNotFoundError:
                    saved_journal = None
                if saved_journal is not None and saved_journal["operation_id"] != operation_id:
                    raise FpmApplyError("recovery", "Unexpected recovery owner")
                try:
                    saved, _ = _read(fd_state, snapshot, mode=0o600)
                except FileNotFoundError:
                    saved = None
                if saved is not None and saved != before:
                    raise FpmApplyError("recovery", "Unexpected recovery snapshot")
                for name in (journal, snapshot):
                    if os.path.lexists(Path(state_dir) / name):
                        os.unlink(name, dir_fd=fd_state)
                os.fsync(fd_state)
            except Exception as recovery_error:
                record["phase"] = "uncertain"
                try:
                    if _read_journal(fd_state, version) is not None:
                        _persist_journal(fd_state, record)
                except Exception:
                    pass
                raise FpmApplyError(
                    "uncertain", "Apply failed and recovery is unverified: " + str(recovery_error)
                ) from exc
            raise FpmApplyError("apply", "Apply rejected and original file verified: " + str(exc)) from exc
        finally:
            os.close(config_fd)
    finally:
        os.close(lock_fd)
        os.close(fd_state)


def _recovery_pool_values(payload):
    """Read only five known numeric fields; never expose raw backup config."""
    try:
        text = payload.decode("utf-8")
        has_pool, values = _parse_pool_text(text)
    except (UnicodeError, MonitorInputError) as exc:
        raise FpmApplyError("recovery", "Unsupported saved PHP-FPM pool layout") from exc
    if not has_pool:
        raise FpmApplyError("recovery", "No supported [www] pool in recovery configuration")
    values = dict(values)
    values.setdefault("pm.max_requests", 0)
    if any(key not in values for key in POOL_KEYS):
        raise FpmApplyError("recovery", "Recovery configuration is missing required pool settings")
    return {key: values[key] for key in POOL_KEYS}


def recovery_status(config_root, state_dir, version):
    """Read-only visibility into the selected version's durable rollback boundary."""
    journal, snapshot = _recovery_names(version)
    # Recovery status is a pure read: unlike a write transaction, it must not
    # create a lock file just because a user opened the plugin UI.
    fd_state = _dir(state_dir)
    try:
        record = _read_journal(fd_state, version)
        if record is None:
            if os.path.lexists(Path(state_dir) / snapshot):
                raise FpmApplyError("recovery", "Unpaired PHP-FPM snapshot requires review")
            return {"state": "No Recovery", "version": version, "operation_id": None}
        snapshot, _ = _read(fd_state, snapshot, mode=0o600)
        if _sha(snapshot) != record["before_sha256"]:
            raise FpmApplyError("recovery", "Recovery snapshot checksum mismatch")
        fd_config = _dir(Path(config_root) / version / "etc")
        try:
            current, _ = _read(fd_config, "php-fpm.conf")
        finally:
            os.close(fd_config)
        # Concurrent Apply/rollback owns atomic journal replacement. A changed
        # journal means the read is stale; the next operation must recheck.
        if _read_journal(fd_state, version) != record:
            raise FpmApplyError("conflict", "PHP-FPM recovery changed while being inspected")
        digest = _sha(current)
        state = ("Applied" if digest == record["after_sha256"] else
                 "Already Baseline" if digest == record["before_sha256"] else
                 "Needs Review")
        baseline_values = observed_values = None
        restoration_changes = []
        if state in ("Applied", "Already Baseline"):
            baseline_values = _recovery_pool_values(snapshot)
            observed_values = _recovery_pool_values(current)
            restoration_changes = [
                {"setting": key, "current": observed_values[key],
                 "baseline": baseline_values[key]}
                for key in POOL_KEYS if observed_values[key] != baseline_values[key]
            ]
        return {"state": state, "version": version,
                "phase": record["phase"], "operation_id": record["operation_id"],
                "baseline_sha256": record["before_sha256"],
                "applied_sha256": record["after_sha256"],
                "observed_sha256": digest,
                "baseline_values": baseline_values,
                "observed_values": observed_values,
                "restoration_changes": restoration_changes,
                "safe_rollback_file_match": state in ("Applied", "Already Baseline")}
    finally:
        os.close(fd_state)


def rollback(config_root, state_dir, version, operation_id, *,
             validate, activate, verify, prewrite_check):
    """Restore after the trusted caller's fresh shared-impact authorization."""
    _check_callbacks(validate, activate, verify)
    if not callable(prewrite_check):
        raise FpmApplyError("validation", "Fresh pre-write Rollback impact verification is required")
    journal, snapshot = _recovery_names(version)
    fd_state, lock_fd = _lock(state_dir)
    try:
        record = _read_journal(fd_state, version)
        if record is None or record["operation_id"] != operation_id:
            raise FpmApplyError("recovery", "No matching active PHP-FPM recovery operation")
        before, _ = _read(fd_state, snapshot, mode=0o600)
        if _sha(before) != record["before_sha256"]:
            raise FpmApplyError("recovery", "Recovery backup checksum mismatch")
        fd_config = _dir(Path(config_root) / version / "etc")
        try:
            current, st = _read(fd_config, "php-fpm.conf")
            if _sha(current) != record["after_sha256"] and current != before:
                raise FpmApplyError("conflict", "PHP-FPM was modified since Apply; refusing overwrite")
            # Run the current-site/approved-decision check while holding the
            # recovery lock, as near as possible to the configuration replace.
            # Site writers outside this plugin still do not share its lock.
            prewrite_check()
            newest, latest_stat = _read(fd_config, "php-fpm.conf")
            if (newest != current or latest_stat.st_dev != st.st_dev
                    or latest_stat.st_ino != st.st_ino):
                raise FpmApplyError("conflict", "PHP-FPM changed during the Rollback impact recheck")
            if current != before:
                _replace(fd_config, "php-fpm.conf", before, _Expected(st, current), prefix="ach_customizer_rollback")
            try:
                validate()
                activate()
                verify()
            except Exception as exc:
                record["phase"] = "uncertain"
                _persist_journal(fd_state, record)
                raise FpmApplyError("uncertain", "Rollback runtime verification failed: " + str(exc)) from exc
            _remove_recovery(fd_state, version)
            return {"state":"Rolled Back", "operation_id":operation_id,
                    "restored_sha256":record["before_sha256"]}
        finally:
            os.close(fd_config)
    finally:
        os.close(lock_fd)
        os.close(fd_state)
