"""Operator-reviewed shared PHP-FPM intent; Monitor only, never a host change.

The policy belongs to a versioned shared [www] service, not to a website.
A saved policy is not an Apply/Restore approval or an effective runtime proof.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from ach_customizer_monitor import (
    MAX_CONFIG_BYTES, MonitorInputError, POOL_KEYS, _bounded_file_text,
    expected_pool_values, preview_php_fpm,
)
from ach_customizer_state import (
    _exclusive_lock, _open_state_dir, _owned_file, _read_at, parse_revision,
    read_state,
)

POLICY_FILE = "ach_customizer.fpm-policy.json"
SCHEMA = 1
MAX_BYTES = 128 * 1024  # Bounded storage resource, not PHP-version count.
MAX_REVISION = 2147483647
VERSION_PATTERN = re.compile(r"[1-9][0-9]{1,2}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class FpmPolicyError(MonitorInputError):
    pass


def _version(value):
    if not isinstance(value, str) or not VERSION_PATTERN.fullmatch(value):
        raise FpmPolicyError("Select a native PHP version")
    return value


def _values(value):
    if (not isinstance(value, dict) or set(value) != set(POOL_KEYS) or
            any(type(v) is not int for v in value.values())):
        raise FpmPolicyError("Malformed saved PHP-FPM shared policy values")
    normalized = expected_pool_values(value)
    if normalized != value:
        raise FpmPolicyError("Noncanonical PHP-FPM shared policy values")
    return normalized


def _checked(data):
    if (not isinstance(data, dict) or set(data) != {"schema", "revision", "profiles"}
            or type(data["schema"]) is not int or data["schema"] != SCHEMA
            or type(data["revision"]) is not int or not 0 <= data["revision"] <= MAX_REVISION
            or not isinstance(data["profiles"], dict)):
        raise FpmPolicyError("Malformed or unsupported PHP-FPM policy store")
    for version, values in data["profiles"].items():
        _version(version)
        _values(values)
    return data


def _load(directory_fd):
    try:
        fd = os.open(POLICY_FILE, READ_FLAGS, dir_fd=directory_fd)
    except FileNotFoundError:
        return {"schema": SCHEMA, "revision": 0, "profiles": {}}
    except OSError as exc:
        raise FpmPolicyError("Unable to open saved PHP-FPM policy safely") from exc
    try:
        try:
            meta = _owned_file(fd, kind="FPM policy")
        except Exception as exc:
            raise FpmPolicyError("Untrusted PHP-FPM policy file") from exc
        if not 0 < meta.st_size <= MAX_BYTES:
            raise FpmPolicyError("PHP-FPM policy exceeds the supported size")
        payload = bytearray()
        while len(payload) <= MAX_BYTES:
            piece = os.read(fd, MAX_BYTES + 1 - len(payload))
            if not piece:
                break
            payload.extend(piece)
        if not payload or len(payload) > MAX_BYTES:
            raise FpmPolicyError("PHP-FPM policy is empty or oversized")
        try:
            return _checked(json.loads(payload.decode("utf-8")))
        except (ValueError, UnicodeError, TypeError) as exc:
            raise FpmPolicyError("Saved PHP-FPM policy is not valid canonical JSON") from exc
    finally:
        os.close(fd)


def read_policy(directory):
    fd = _open_state_dir(directory)
    try:
        return _load(fd)
    finally:
        os.close(fd)


def _monitor(state):
    if not state["enabled"] or not state["modules"]["php_fpm_file_preview"]:
        raise FpmPolicyError("PHP-FPM Monitor is disabled; enable it before policy review")


def get_policy(version, *, directory):
    version = _version(version)
    before = read_state(directory)
    _monitor(before)
    policy = read_policy(directory)
    after = read_state(directory)
    _monitor(after)
    if after != before:
        raise FpmPolicyError("Monitor changed during PHP policy inspection; retry")
    values = policy["profiles"].get(version)
    return {
        "schema": SCHEMA, "version": version, "policy_revision": policy["revision"],
        "monitor_revision": after["revision"], "saved": values is not None,
        "desired": dict(values) if values is not None else None,
        "read_only": True, "runtime_verified": False, "auto_enforce": False,
        "scope": "shared_service", "pool": "www",
        "note": ("Operator-reviewed desired values only; compare against a fresh native "
                 "PHP-FPM file preview. No runtime verification or automatic enforcement."),
    }


def observe(config_root, version, desired):
    """Produce a bounded evidence token for a particular desired-vs-file preview.

    Both native main and selected pool source must be unchanged across repeated
    preview/parses; the token binds all input values and both source fingerprints.
    """
    version = _version(version)
    values = expected_pool_values(desired)
    first = preview_php_fpm(config_root, version, values)
    if first["state"] not in ("File Match", "File Drift"):
        return first, None
    root = Path(config_root) / version / "etc"
    main = root / "php-fpm.conf"
    source = Path(first["source"])
    if source != main and source.parent != root / "php-fpm.d":
        raise FpmPolicyError("Unexpected PHP-FPM policy source path")
    main_before = _bounded_file_text(main, MAX_CONFIG_BYTES, with_fingerprint=True)[1]
    pool_before = _bounded_file_text(source, MAX_CONFIG_BYTES, with_fingerprint=True)[1]
    second = preview_php_fpm(config_root, version, values)
    main_after = _bounded_file_text(main, MAX_CONFIG_BYTES, with_fingerprint=True)[1]
    pool_after = _bounded_file_text(source, MAX_CONFIG_BYTES, with_fingerprint=True)[1]
    if first != second or main_before != main_after or pool_before != pool_after:
        raise FpmPolicyError("PHP-FPM files changed during policy preview; inspect again")
    token = hashlib.sha256(json.dumps({
        "version": version, "desired": values, "preview": second,
        "main_source": main_after, "pool_source": pool_after,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return second, token


def _write(directory_fd, policy):
    payload = (json.dumps(_checked(policy), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise FpmPolicyError("PHP-FPM policy exceeds the supported size")
    temporary = ".ach_customizer.fpm-policy." + uuid4().hex + ".tmp"
    fd = os.open(temporary, WRITE_FLAGS, 0o600, dir_fd=directory_fd)
    replaced = False
    try:
        _owned_file(fd, kind="temporary FPM policy")
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(fd)
        os.replace(temporary, POLICY_FILE, src_dir_fd=directory_fd,
                   dst_dir_fd=directory_fd)
        replaced = True
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            raise FpmPolicyError(
                "PHP-FPM policy commit may have succeeded; read the saved revision before retrying"
            ) from exc
    finally:
        os.close(fd)
        if not replaced:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def save_policy(config_root, version, desired, *, directory, expected_revision,
                expected_monitor_revision, expected_observation_sha256, reviewed):
    """Persist desired intent only after fresh operator-reviewed file evidence."""
    version = _version(version)
    values = expected_pool_values(desired)
    revision = parse_revision(expected_revision)
    monitor_revision = parse_revision(expected_monitor_revision)
    if not (reviewed is True or reviewed == "true"):
        raise FpmPolicyError("Explicit shared PHP policy review confirmation is required")
    if (not isinstance(expected_observation_sha256, str) or
            not SHA_PATTERN.fullmatch(expected_observation_sha256)):
        raise FpmPolicyError("A fresh PHP-FPM preview fingerprint is required")
    preflight, digest = observe(config_root, version, values)
    if digest is None or digest != expected_observation_sha256:
        raise FpmPolicyError("PHP-FPM source or form changed since preview; inspect again")
    directory_fd = _open_state_dir(directory)
    try:
        lock_fd = _exclusive_lock(directory_fd)
        try:
            monitor = _read_at(directory_fd)
            _monitor(monitor)
            if monitor["revision"] != monitor_revision:
                raise FpmPolicyError("Monitor changed since policy preview; inspect again")
            current = _load(directory_fd)
            if current["revision"] != revision:
                raise FpmPolicyError("Saved PHP policy changed; reload and inspect again")
            postflight, current_digest = observe(config_root, version, values)
            if postflight != preflight or current_digest != digest:
                raise FpmPolicyError("PHP-FPM source changed while saving policy")
            if current["profiles"].get(version) == values:
                state, changed = "Policy Unchanged", False
            else:
                if current["revision"] >= MAX_REVISION:
                    raise FpmPolicyError("PHP-FPM policy revision exhausted")
                profiles = dict(current["profiles"])
                profiles[version] = values
                updated = {"schema": SCHEMA, "revision": revision + 1,
                           "profiles": profiles}
                _write(directory_fd, updated)
                revision += 1
                state, changed = "Policy Saved", True
            return {
                "schema": SCHEMA, "state": state, "version": version,
                "policy_revision": revision, "monitor_revision": monitor_revision,
                "desired": values, "changed": changed, "scope": "shared_service",
                "auto_enforce": False, "runtime_verified": False,
                "note": ("Plugin-owned desired values saved only. PHP configuration and "
                         "running service remain unchanged. Use a new preview to detect drift."),
            }
        finally:
            os.close(lock_fd)
    finally:
        os.close(directory_fd)
