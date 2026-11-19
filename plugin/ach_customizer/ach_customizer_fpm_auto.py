"""Opt-in automatic shared PHP-FPM repair after verified native WP terminal events.

The saved desired PHP [www] policy is the operator's durable authority. This
worker runs outside an HTTP session only after a source-pinned native WP
terminal event, with all relevant aaPanel task locks gone. It must not mutate
hosts, vendor sources or services for unrelated configuration changes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

import ach_customizer_fpm_apply as recovery
import ach_customizer_fpm_policy as desired_policy
import ach_customizer_wp_terminal as native
from ach_customizer_fpm_workflow import ManualFpmWorkflow
from ach_customizer_state import (
    DATA_DIR, _exclusive_lock, _open_state_dir, _owned_file, _read_at, parse_revision,
)

NATIVE_FPM_SETTER = "/www/server/panel/class/config.py"
NATIVE_FPM_SETTER_SHA256 = "22f61688e0a41b6599f09d3addcea1b2dea9ce12f87ac9770a897aea32a6657d"
AUTO_FILE = "ach_customizer.fpm-auto.json"
MAX_AUTO_BYTES = 8192
MAX_AUTO_PROFILES = 2  # Current verified PHP 8.1/8.5 native mutation adapters.
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
TOKEN = re.compile(r"[a-f0-9]{64}\Z")


class FpmAutoError(RuntimeError):
    pass


def _digest(version, desired):
    payload = json.dumps({"version": version, "desired": desired},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _default():
    return {"schema": 1, "revision": 0, "profiles": {}}


def _validate(value):
    if (not isinstance(value, dict) or set(value) != {"schema", "revision", "profiles"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or type(value["revision"]) is not int or not 0 <= value["revision"] <= 2147483647
            or not isinstance(value["profiles"], dict)
            or len(value["profiles"]) > MAX_AUTO_PROFILES):
        raise FpmAutoError("Invalid FPM automatic repair state")
    for version, profile in value["profiles"].items():
        if (version not in recovery.SUPPORTED_VERSIONS
                or not isinstance(profile, dict)
                or set(profile) != {"enabled", "policy_sha256", "enabled_ns",
                                    "last_token", "last_state", "last_operation", "active"}
                or type(profile["enabled"]) is not bool
                or not isinstance(profile["policy_sha256"], str)
                or not DIGEST.fullmatch(profile["policy_sha256"])
                or type(profile["enabled_ns"]) is not int or profile["enabled_ns"] < 0
                or (profile["last_token"] is not None and
                    (not isinstance(profile["last_token"], str)
                     or not TOKEN.fullmatch(profile["last_token"])))
                or not isinstance(profile["last_state"], str) or len(profile["last_state"]) > 80
                or (profile["last_operation"] is not None and
                    (not isinstance(profile["last_operation"], str)
                     or not re.fullmatch("[0-9a-f]{32}", profile["last_operation"])))
                or (profile["active"] is not None and
                    (not isinstance(profile["active"], dict)
                     or set(profile["active"]) != {"dev", "ino", "started_ns",
                                                   "baseline_sha256", "domain",
                                                   "memory_mib", "baseline_max_requests"}
                     or type(profile["active"]["dev"]) is not int
                     or type(profile["active"]["ino"]) is not int
                     or type(profile["active"]["started_ns"]) is not int
                     or profile["active"]["started_ns"] < 0
                     or not isinstance(profile["active"]["baseline_sha256"], str)
                     or not DIGEST.fullmatch(profile["active"]["baseline_sha256"])
                     or not isinstance(profile["active"]["domain"], str)
                     or len(profile["active"]["domain"]) > 253
                     or type(profile["active"]["memory_mib"]) is not int
                     or profile["active"]["memory_mib"] < 1
                     or (profile["active"]["baseline_max_requests"] is not None
                         and (type(profile["active"]["baseline_max_requests"]) is not int
                              or profile["active"]["baseline_max_requests"] < 0))))):
            raise FpmAutoError("Invalid versioned automatic FPM policy")
    return value


def _read(fd_dir):
    try:
        fd = os.open(AUTO_FILE, READ_FLAGS, dir_fd=fd_dir)
    except FileNotFoundError:
        return _default()
    except OSError as exc:
        raise FpmAutoError("Unable to read automatic PHP policy") from exc
    try:
        info = _owned_file(fd, kind="FPM automatic policy")
        if not 0 < info.st_size <= MAX_AUTO_BYTES:
            raise FpmAutoError("Automatic PHP policy exceeds supported size")
        data = bytearray()
        while len(data) <= MAX_AUTO_BYTES:
            part = os.read(fd, MAX_AUTO_BYTES + 1 - len(data))
            if not part:
                break
            data.extend(part)
        if not data or len(data) > MAX_AUTO_BYTES:
            raise FpmAutoError("Invalid automatic PHP policy size")
        try:
            parsed = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise FpmAutoError("Unreadable automatic PHP policy") from exc
        return _validate(parsed)
    except OSError as exc:
        raise FpmAutoError("Automatic PHP policy read failed") from exc
    finally:
        os.close(fd)


def _save(fd_dir, value):
    data = (json.dumps(_validate(value), sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > MAX_AUTO_BYTES:
        raise FpmAutoError("Automatic PHP policy exceeds supported size")
    staging = ".ach_customizer.fpm-auto." + uuid4().hex + ".tmp"
    fd = os.open(staging, CREATE_FLAGS, 0o600, dir_fd=fd_dir)
    replaced = False
    try:
        _owned_file(fd, kind="temporary automatic PHP policy")
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(data)
            out.flush()
        os.fsync(fd)
        os.replace(staging, AUTO_FILE, src_dir_fd=fd_dir, dst_dir_fd=fd_dir)
        replaced = True
        try:
            os.fsync(fd_dir)
        except OSError as exc:
            raise FpmAutoError("Automatic FPM state commit uncertain; inspect before retry") from exc
    finally:
        os.close(fd)
        if not replaced:
            try:
                os.unlink(staging, dir_fd=fd_dir)
            except FileNotFoundError:
                pass


def _revoke_name(version):
    if version not in recovery.SUPPORTED_VERSIONS:
        raise FpmAutoError("Unsupported versioned PHP revocation")
    return "ach_customizer.fpm-auto-disable." + version + ".json"


def _read_revoke(fd_dir, version):
    name = _revoke_name(version)
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=fd_dir)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FpmAutoError("Unable to read pending automatic PHP revocation") from exc
    try:
        meta = _owned_file(fd, kind="FPM disable request")
        if not 0 < meta.st_size <= 512:
            raise FpmAutoError("Malformed automatic PHP disable request")
        blob = os.read(fd, 513)
        try:
            request = json.loads(blob.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise FpmAutoError("Unreadable automatic PHP disable request") from exc
        if (not isinstance(request, dict)
                or set(request) != {"schema", "version", "enabled_ns", "policy_sha256"}
                or request["schema"] != 1 or type(request["schema"]) is not int
                or request["version"] != version
                or type(request["enabled_ns"]) is not int or request["enabled_ns"] < 0
                or not isinstance(request["policy_sha256"], str)
                or not DIGEST.fullmatch(request["policy_sha256"])):
            raise FpmAutoError("Untrusted automatic PHP disable request")
        return request
    finally:
        os.close(fd)


def _publish_revoke(fd_dir, version, profile):
    """Durable, root-owned emergency intent without contending on Apply lock."""
    existing = _read_revoke(fd_dir, version)
    request = {"schema": 1, "version": version,
               "enabled_ns": profile["enabled_ns"],
               "policy_sha256": profile["policy_sha256"]}
    if existing is not None:
        if existing != request:
            raise FpmAutoError("An older or foreign PHP disable intent needs review")
        return existing
    name = _revoke_name(version)
    payload = (json.dumps(request, sort_keys=True, separators=(",", ":"))+"\n").encode("utf-8")
    staging = ".ach_customizer.fpm-auto-disable." + uuid4().hex + ".tmp"
    fd = os.open(staging, CREATE_FLAGS, 0o600, dir_fd=fd_dir)
    published = False
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(fd)
        try:
            # Reuse the existing tested Linux atomic-no-replace writer.
            # A crash cannot leave an unreadable partial canonical intent.
            native._publish_manual_review_noreplace(fd_dir, staging, name)
            published = True
        except FileExistsError:
            existing = _read_revoke(fd_dir, version)
            if existing != request:
                raise FpmAutoError("Concurrent PHP disable intent changed")
            return existing
        os.fsync(fd_dir)
    finally:
        os.close(fd)
        if not published:
            try:
                os.unlink(staging, dir_fd=fd_dir)
            except FileNotFoundError:
                pass
    return request


def _consume_revoke_locked(fd_dir, version):
    """Idempotently complete an emergency request while holding Monitor lock."""
    request = _read_revoke(fd_dir, version)
    if request is None:
        return False
    store = _read(fd_dir)
    profile = store["profiles"].get(version)
    if (profile is None or request["enabled_ns"] != profile["enabled_ns"]
            or request["policy_sha256"] != profile["policy_sha256"]):
        raise FpmAutoError("Pending PHP disable identity differs from current profile")
    if profile["enabled"]:
        updated = {**profile, "enabled": False, "active": None, "last_state": "Disabled"}
        _save(fd_dir, {**store, "revision": store["revision"]+1,
                       "profiles": {**store["profiles"], version: updated}})
    # Only after the persistent policy is fsynced may the durable request
    # be retired. Crash before unlink -> next worker completes idempotently.
    os.unlink(_revoke_name(version), dir_fd=fd_dir)
    os.fsync(fd_dir)
    return True


def resolve_disable(version, *, data_dir=DATA_DIR):
    fd = _open_state_dir(data_dir)
    try:
        try:
            lock = _exclusive_lock(fd)
        except Exception as exc:
            from ach_customizer_state import StateError
            if isinstance(exc, StateError) and "busy" in str(exc).lower():
                return inspect(version, data_dir=data_dir)
            raise
        try:
            _consume_revoke_locked(fd, version)
            return inspect(version, data_dir=data_dir)
        finally:
            os.close(lock)
    finally:
        os.close(fd)


def request_disable(version, *, data_dir=DATA_DIR, expected_auto_revision=None):
    """Durably revoke future authority even if host Apply exceeds lock timeout.

    Emergency Disable intentionally does not depend on a possibly stale UI
    revision: the requested target is the currently enabled PHP version.
    A truthful Pending Disable response requires no operator retry; the
    existing watcher timer/worker will complete after the active transaction.
    """
    if version not in recovery.SUPPORTED_VERSIONS:
        raise FpmAutoError("Unsupported PHP service for Emergency Disable")
    for _ in range(2):
        fd = _open_state_dir(data_dir)
        try:
            store = _read(fd)
            current = store["profiles"].get(version)
            if current and current["enabled"]:
                _publish_revoke(fd, version, current)
        finally:
            os.close(fd)
        result = resolve_disable(version, data_dir=data_dir)
        if not result["enabled"] or result["pending_disable"]:
            return result
        # Concurrent Enable committed after our first unlocked read. The
        # emergency request still targets the currently enabled version.
    raise FpmAutoError("Concurrent PHP enable prevented a confirmed Emergency Disable")


def inspect(version, *, data_dir=DATA_DIR):
    if version not in recovery.SUPPORTED_VERSIONS:
        raise FpmAutoError("Only verified PHP 8.1 and 8.5 have automated adapters")
    fd = _open_state_dir(data_dir)
    try:
        store = _read(fd)
        profile = store["profiles"].get(version)
        request = _read_revoke(fd, version)
        if request is not None and (profile is None or
                profile["enabled_ns"] != request["enabled_ns"] or
                profile["policy_sha256"] != request["policy_sha256"]):
            raise FpmAutoError("Pending PHP disable identity differs from current profile")
        # The policy-off fsync and canonical-request unlink are separate
        # durable commits. A crash between them leaves valid revocation
        # evidence that must remain Pending, even though enabled is false.
        pending = request is not None
        return {"version": version, "scope": "shared_service", "schema": 1,
                "state_revision": store["revision"],
                "enabled": bool(profile and profile["enabled"]),
                "pending_disable": pending,
                "saved_policy_sha256": profile["policy_sha256"] if profile else None,
                "last_state": ("Pending Disable" if pending else
                               profile["last_state"] if profile else "Disabled"),
                "last_operation": profile["last_operation"] if profile else None,
                "watch_scope": "verified_native_wp_terminal",
                "auto_hosts": False}
    finally:
        os.close(fd)


def any_enabled(*, data_dir=DATA_DIR):
    fd = _open_state_dir(data_dir)
    try:
        return any(profile["enabled"] for profile in _read(fd)["profiles"].values())
    finally:
        os.close(fd)


def any_pending_disable(*, data_dir=DATA_DIR):
    """Verify no valid revocation remains before stopping the owned retry timer.

    A prior unlink might have succeeded while its directory fsync failed.
    Durably confirm the current directory entries before reporting no work,
    and recheck canonical identities after that sync. Existing requests are
    never hidden by the disabled profile state.
    """
    if any(inspect(version, data_dir=data_dir)["pending_disable"]
           for version in recovery.SUPPORTED_VERSIONS):
        return True
    fd = _open_state_dir(data_dir)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            raise FpmAutoError("PHP-FPM revocation cleanup durability unverified") from exc
    finally:
        os.close(fd)
    return any(inspect(version, data_dir=data_dir)["pending_disable"]
               for version in recovery.SUPPORTED_VERSIONS)


def set_enabled(version, enabled, *, data_dir=DATA_DIR,
                expected_auto_revision, expected_policy_revision=None,
                expected_monitor_revision=None, expected_impact=None,
                reviewed=False, controller_factory=None):
    """Only a primary-admin endpoint should call this mutating helper.

    Caller must separately activate/disable the owned systemd watcher.
    Revalidation under the common Monitor lock binds saved operator intent
    and current native shared-service site attribution before enabling.
    """
    if version not in recovery.SUPPORTED_VERSIONS or type(enabled) is not bool:
        raise FpmAutoError("Invalid versioned automatic PHP control")
    if enabled:
        _verified_native_fpm_setter()
    if enabled and reviewed is not True:
        raise FpmAutoError("Explicit approval of automatic shared PHP service repair is required")
    revision = parse_revision(expected_auto_revision)
    policy_revision = (parse_revision(expected_policy_revision)
                       if enabled else None)
    monitor_revision = (parse_revision(expected_monitor_revision)
                        if enabled else None)
    if enabled and (not isinstance(expected_impact, str)
                    or not DIGEST.fullmatch(expected_impact)):
        raise FpmAutoError("Reviewed PHP shared-site mapping identity is required")
    fd = _open_state_dir(data_dir)
    try:
        lock = _exclusive_lock(fd)
        try:
            store = _read(fd)
            if store["revision"] != revision:
                raise FpmAutoError("Automatic PHP policy revision changed; inspect before retry")
            previous = store["profiles"].get(version)
            if enabled and _read_revoke(fd, version) is not None:
                raise FpmAutoError("Pending emergency revocation must finish before re-enable")
            if enabled:
                monitor = _read_at(fd)
                if not monitor["enabled"] or not monitor["modules"]["php_fpm_file_preview"]:
                    raise FpmAutoError("PHP-FPM Monitor must be enabled")
                policy = desired_policy._load(fd)
                if policy["revision"] != policy_revision or version not in policy["profiles"]:
                    raise FpmAutoError("Saved reviewed PHP policy changed; recheck")
                desired = policy["profiles"][version]
                factory = controller_factory or (
                    lambda: ManualFpmWorkflow(data_dir=data_dir))
                controller = factory()
                prepared = controller._prepare(_args(version, desired))
                if (monitor["revision"] != monitor_revision
                        or prepared["monitor_revision"] != monitor_revision
                        or prepared["impact_sha256"] != expected_impact):
                    raise FpmAutoError(
                        "Reviewed PHP shared-site mapping or Monitor changed; recheck before enabling")
                fingerprint = _digest(version, desired)
                if previous and previous["enabled"]:
                    if previous["policy_sha256"] != fingerprint:
                        raise FpmAutoError(
                            "Disable prior shared PHP auto profile before approving changed values")
                    return inspect(version, data_dir=data_dir)
                profile = {"enabled": True, "policy_sha256": fingerprint,
                           "enabled_ns": time.time_ns(), "last_token": None,
                           "last_state": "Armed", "last_operation": None,
                           "active": None}
            else:
                if not previous or not previous["enabled"]:
                    return inspect(version, data_dir=data_dir)
                profile = dict(previous)
                profile["enabled"] = False
                profile["last_state"] = "Disabled"
                profile["active"] = None
            updated = dict(store)
            updated["profiles"] = {**store["profiles"], version: profile}
            updated["revision"] += 1
            _save(fd, updated)
            if enabled and _read_revoke(fd, version) is not None:
                _consume_revoke_locked(fd, version)
                raise FpmAutoError("Concurrent Emergency Disable revoked the pending Enable")
            return {"version": version, "enabled": enabled,
                    "state_revision": updated["revision"],
                    "last_state": profile["last_state"],
                    "saved_policy_sha256": profile["policy_sha256"],
                    "watch_scope": "verified_native_wp_terminal",
                    "scope": "shared_service", "auto_hosts": False}
        finally:
            os.close(lock)
    finally:
        os.close(fd)


def _args(version, desired):
    return {"php_version": version, **{
        key.removeprefix("pm."): value for key, value in desired.items()}}


def _native_progress():
    native._native_supported()
    result = native._progress()
    if (result["mtime_ns"] > time.time_ns()
            or time.time_ns() - result["mtime_ns"] > native.MAX_AGE_NS
            or os.path.lexists(native.BATCH_LOCK)):
        return None
    return result


def _file_sha(config_root, version):
    """Validated descriptor-based current config read; not a source rewrite."""
    fd = recovery._dir(Path(config_root) / version / "etc")
    try:
        data, _ = recovery._read(fd, "php-fpm.conf")
        return recovery._sha(data)
    finally:
        os.close(fd)


def _native_opt_marker(config_root, version):
    """Validate the aaPanel v2 first-time optimization completion sidecar.

    Verified v2 one_key_wp.optimize_php() only invokes setFpmConfig when
    php-fpm.conf_record is absent, and creates this one-space sidecar after
    successful optimization. Never create/remove or infer it from generic FPM
    drift. A foreign/symlinked marker fails closed.
    """
    fd = recovery._dir(Path(config_root) / version / "etc")
    try:
        try:
            payload, st = recovery._read(fd, "php-fpm.conf_record", max_bytes=8)
        except FileNotFoundError:
            return None
        except (OSError, recovery.FpmApplyError) as exc:
            raise FpmAutoError("Untrusted native PHP optimization marker") from exc
        if payload != b" ":
            raise FpmAutoError("Unrecognized native PHP optimization marker")
        return st.st_mtime_ns
    finally:
        os.close(fd)


def _verified_native_fpm_setter():
    """Pin the exact native setFpmConfig implementation behind our output proof."""
    source, _ = native._trusted_file(NATIVE_FPM_SETTER, limit=262144)
    if recovery._sha(source) != NATIVE_FPM_SETTER_SHA256:
        raise FpmAutoError("aaPanel PHP-FPM setter source changed; automatic repair refused")


def _native_memory_mib():
    """Same physical-memory measure used by verified one_key_wp_v2.get_mem."""
    import psutil
    return int(psutil.virtual_memory().total / 1024 / 1024)


def _native_php_tuning(memory_mib):
    """The four concrete numeric values from verified optimize_php.php_fpm.

    config.config().setFpmConfig sets precisely these four pm.* values.
    It does not write pm.max_requests. Unknown RAM bands are not invented.
    """
    if type(memory_mib) is not int or memory_mib < 1:
        raise FpmAutoError("Invalid native aaPanel physical memory")
    bands = (
        (1024, (30, 5, 5, 20)),
        (2048, (50, 5, 5, 30)),
        (4098, (80, 10, 10, 30)),
        (8096, (120, 10, 10, 30)),
        (16192, (200, 15, 15, 50)),
        (32384, (300, 20, 20, 50)),
    )
    values = next((tuple_values for ceiling, tuple_values in bands
                   if memory_mib <= ceiling), (500, 20, 20, 50))
    return dict(zip(("pm.max_children", "pm.start_servers",
                     "pm.min_spare_servers", "pm.max_spare_servers"), values))


def _parsed_pool(config_bytes):
    try:
        has_pool, values = recovery._parse_pool_text(config_bytes.decode("utf-8"))
    except (UnicodeError, recovery.MonitorInputError) as exc:
        raise FpmAutoError("Native PHP pool bytes cannot be attributed safely") from exc
    if not has_pool:
        raise FpmAutoError("Native PHP [www] pool missing")
    return values


def _native_vendor_values(config_root, version, active):
    """Refuse independent edits to any optimizer-managed numeric setting.

    The vendor writes only the four sized values; a saved policy may also
    mention pm.max_requests, which the vendor does not modify. Require the
    originally witnessed value to be unchanged. Other untouched directives
    flow through the guarded current-source plan without being overwritten.
    """
    _verified_native_fpm_setter()
    if _native_memory_mib() != active["memory_mib"]:
        raise FpmAutoError("Native physical-memory tier changed during the WP task")
    fd = recovery._dir(Path(config_root) / version / "etc")
    try:
        current, _ = recovery._read(fd, "php-fpm.conf")
    finally:
        os.close(fd)
    values = _parsed_pool(current)
    expected = _native_php_tuning(active["memory_mib"])
    if any(values.get(key) != native_value for key, native_value in expected.items()):
        raise FpmAutoError(
            "PHP-FPM settings differ from the verified native optimizer output; "
            "possible independent administrator edit")
    if values.get("pm.max_requests") != active["baseline_max_requests"]:
        raise FpmAutoError(
            "PHP-FPM max_requests differs from the witnessed pre-native configuration")
    return recovery._sha(current)


def _completed_native_repair(fd_state, version, profile, progress, config_root, plan):
    """Reconcile a completed host transaction before retiring its terminal.

    A worker can die between the schema-2 applied fsync and the separate
    per-profile terminal acknowledgment. No second write or reload is needed
    when the journal proves that exact native event was already repaired.
    """
    record = recovery._read_journal(fd_state, version)
    if record is None:
        _, snapshot = recovery._recovery_names(version)
        try:
            os.stat(snapshot, dir_fd=fd_state, follow_symlinks=False)
        except FileNotFoundError:
            return None
        raise recovery.FpmApplyError("recovery", "Unpaired FPM recovery snapshot needs review")
    if record["phase"] != "applied":
        raise recovery.FpmApplyError("recovery", "Pending/uncertain FPM recovery needs review")
    # Even a previous unrelated applied record must have a real, intact
    # pre-image; do not retire a native terminal over broken recovery.
    _, snapshot = recovery._recovery_names(version)
    try:
        before, _ = recovery._read(fd_state, snapshot, mode=0o600)
    except FileNotFoundError as exc:
        raise recovery.FpmApplyError("recovery", "Missing automatic recovery pre-image") from exc
    if recovery._sha(before) != record["before_sha256"]:
        raise recovery.FpmApplyError("recovery", "Damaged automatic recovery snapshot")
    if record.get("event_token") != progress["token"]:
        return None
    if (record.get("schema") != 2 or record.get("owner") != "auto"
            or record.get("policy_sha256") != profile["policy_sha256"]):
        raise recovery.FpmApplyError("recovery", "Mismatched automatic recovery ownership")
    current = _file_sha(config_root, version)
    if (current != record["after_sha256"] or current != plan["after_sha256"]):
        raise recovery.FpmApplyError(
            "recovery", "Repaired native FPM source no longer matches committed recovery")
    return {"state": "Applied", "operation_id": record["operation_id"],
            "reconciled": True}


def run(*, data_dir=DATA_DIR, controller_factory=None, terminal_reader=None):
    """Repair only configuration drift attributable to a witnessed native task.

    A native progress start captures a trusted FPM file baseline. An exact
    later terminal identity/step can authorize reconciliation only when the
    source file changed during that witnessed window. Previous admin edits
    which predate the native task do not become an automatic write target.
    """
    revoked = False
    # Revocations are independent of native WP event availability and are
    # processed even when a path/timer wakeup has no current progress log.
    for candidate_version in recovery.SUPPORTED_VERSIONS:
        fd_revoke = _open_state_dir(data_dir)
        try:
            pending = _read_revoke(fd_revoke, candidate_version)
        finally:
            os.close(fd_revoke)
        if pending is not None:
            resolved = resolve_disable(candidate_version, data_dir=data_dir)
            revoked = revoked or not resolved["pending_disable"]
    fd = _open_state_dir(data_dir)
    try:
        if not any(profile["enabled"] for profile in _read(fd)["profiles"].values()):
            return {"state": ("Pending Disable" if any_pending_disable(data_dir=data_dir)
                              else "Disabled"),
                    "changed": False, "revocation_completed": revoked}
    finally:
        os.close(fd)

    reader = terminal_reader or _native_progress
    progress = reader()
    if progress is None:
        return {"state": "No verified native progress", "changed": False,
                "revocation_completed": revoked}
    outcomes = []
    for version in recovery.SUPPORTED_VERSIONS:
        fd = _open_state_dir(data_dir)
        try:
            lock = _exclusive_lock(fd)
            try:
                revoked = _consume_revoke_locked(fd, version) or revoked
                store = _read(fd)
                profile = store["profiles"].get(version)
                if not profile or not profile["enabled"]:
                    continue
                if progress["mtime_ns"] <= profile["enabled_ns"]:
                    continue
                if (progress["status"] == 0 and progress["steps"][3] in (0, 2)
                        and os.path.lexists(native.LOCK)):
                    if profile["active"] is not None:
                        # Do not replace a prior active witness with a new or
                        # ambiguous concurrent task; recovery is operator-owned.
                        continue
                    if reader() != progress:
                        continue
                    policy = desired_policy._load(fd)
                    desired = policy["profiles"].get(version)
                    if desired is None or _digest(version, desired) != profile["policy_sha256"]:
                        raise FpmAutoError("Saved PHP policy changed during native start")
                    factory = controller_factory or (
                        lambda: ManualFpmWorkflow(data_dir=data_dir))
                    controller = factory()
                    # Do not demand a stable site inventory while aaPanel is
                    # actively *creating* that site. The witness only reads
                    # a trustworthy service baseline; full site attribution,
                    # impact and runtime compatibility are revalidated at
                    # terminal immediately before any host mutation.
                    controller._environment(version)
                    controller._state()
                    _verified_native_fpm_setter()
                    # A pre-existing native v2 sidecar means this task will
                    # skip optimize_php entirely: do not infer FPM ownership.
                    if _native_opt_marker(controller.config_root, version) is not None:
                        continue
                    baseline = _file_sha(controller.config_root, version)
                    if (mem := _native_memory_mib()) < 1:
                        raise FpmAutoError("Invalid native physical memory")
                    fd_conf = recovery._dir(Path(controller.config_root)/version/"etc")
                    try:
                        before_bytes, _ = recovery._read(fd_conf, "php-fpm.conf")
                    finally:
                        os.close(fd_conf)
                    if recovery._sha(before_bytes) != baseline:
                        continue
                    original_max_requests = _parsed_pool(before_bytes).get("pm.max_requests")
                    # The source writer might have completed optimization
                    # between the initial marker absence and our baseline.
                    # Do not record a false pre-change snapshot in that case.
                    if (_native_opt_marker(controller.config_root, version) is not None
                            or reader() != progress):
                        continue
                    active = {"dev": progress["dev"], "ino": progress["ino"],
                              "domain": progress["domain"], "started_ns": progress["mtime_ns"],
                              "baseline_sha256": baseline,
                              "memory_mib": mem,
                              "baseline_max_requests": original_max_requests}
                    updated = {**profile, "active": active,
                               "last_state": "Witness Armed"}
                    _save(fd, {**store, "revision": store["revision"]+1,
                               "profiles": {**store["profiles"], version: updated}})
                    outcomes.append({"version": version, "state": "Witness Armed",
                                     "operation_id": None})
                    continue

                if (progress["status"] != 1 or progress["steps"] not in
                        ([1, 1, 1, 1], [1, 1, 1, -1])
                        or os.path.lexists(native.LOCK) or os.path.lexists(native.BATCH_LOCK)
                        or progress["token"] == profile["last_token"]):
                    continue
                active = profile["active"]
                if (active is None or active["dev"] != progress["dev"]
                        or active["ino"] != progress["ino"]
                        or active["domain"] != progress["domain"]
                        or progress["mtime_ns"] <= active["started_ns"]
                        or progress["mtime_ns"]-active["started_ns"] > native.MAX_AGE_NS):
                    continue
                if reader() != progress:
                    continue
                policy = desired_policy._load(fd)
                desired = policy["profiles"].get(version)
                if desired is None or _digest(version, desired) != profile["policy_sha256"]:
                    raise FpmAutoError("Saved PHP policy changed; disable/re-enable automatic repair")
                monitor = _read_at(fd)
                if not monitor["enabled"] or not monitor["modules"]["php_fpm_file_preview"]:
                    raise FpmAutoError("PHP-FPM Monitor disabled; automatic mutation refused")
                factory = controller_factory or (lambda: ManualFpmWorkflow(data_dir=data_dir))
                controller = factory()
                _verified_native_fpm_setter()
                marker_ns = _native_opt_marker(controller.config_root, version)
                if marker_ns is None:
                    # An optimizer may crash *after* touching the FPM file
                    # but before writing its completion sidecar. Do not
                    # classify that source change as "no optimization", or
                    # overwrite a file without trustworthy writer evidence.
                    if (_file_sha(controller.config_root, version) !=
                            active["baseline_sha256"]):
                        raise FpmAutoError(
                            "Native FPM changed without an optimization completion marker")
                    if reader() != progress:
                        continue
                    finished = {**profile, "last_token": progress["token"],
                                "last_state": "No Native FPM Optimization",
                                "last_operation": None, "active": None}
                    _save(fd, {**store, "revision": store["revision"] + 1,
                               "profiles": {**store["profiles"], version: finished}})
                    outcomes.append({"version": version,
                                     "state": "No Native FPM Optimization",
                                     "operation_id": None})
                    continue
                # The marker was verified absent when this exact native task
                # was witnessed. File modification timestamps may differ by
                # filesystem clock resolution/offset from progress timestamps;
                # ownership is the absence-to-valid-marker transition under
                # the pinned native writer contract, not nanosecond equality.
                prepared = controller._prepare(_args(version, desired))
                plan = prepared["plan"]
                # The witnessed native site must be a verified consumer of
                # THIS PHP shared pool. Another version/service can change
                # during the task without being owned by the WP installer.
                impact = prepared["shared_impact"]
                if not any(site["site_key"] == active["domain"]
                           for site in impact["matched_sites"]):
                    # No write, reload, recovery archive or token consumption:
                    # the unrelated PHP service belongs to another owner.
                    continue
                # Pre-existing drift is not attributable to this native run.
                # Likewise, an unrelated later source rewrite must not grant
                # authority when no source transition was observed.
                changed_since_start = (_file_sha(controller.config_root, version)
                                       != active["baseline_sha256"])
                if reader() != progress:
                    continue
                committed = _completed_native_repair(
                    fd, version, profile, progress, controller.config_root, plan)
                if committed is not None:
                    result = committed
                elif not changed_since_start:
                    result = {"state": "No Vendor FPM Change", "operation_id": None}
                else:
                    # The marker alone does not authorize an unrelated
                    # administrator edit after the optimizer finished.
                    if _native_vendor_values(controller.config_root, version, active) != plan["before_sha256"]:
                        raise FpmAutoError("Native optimizer evidence changed before preview")
                    # Match Manual Apply: the initial site attribution is
                    # observation only; re-evaluate current site identity and
                    # exact config plan immediately before the host write.
                    latest = controller._prepare(_args(version, desired))
                    if (latest["impact_sha256"] != prepared["impact_sha256"]
                            or latest["plan"] != plan
                            or not any(site["site_key"] == active["domain"]
                                       for site in latest["shared_impact"]["matched_sites"])
                            or reader() != progress):
                        raise recovery.FpmApplyError(
                            "fpm_conflict",
                            "Native PHP service or shared-site mapping changed before automatic repair")
                    validate, activate, verify = controller.hooks_factory(version, plan["desired"])
                    restored = dict(plan["desired"])
                    for change in plan["changes"]:
                        restored[change["setting"]] = change["actual"]
                    _, _, verify_restored = controller.hooks_factory(version, restored)
                    result = recovery.apply(
                        controller.config_root, controller.data_dir, version, desired,
                        expected_before=plan["before_sha256"],
                        expected_after=plan["after_sha256"], validate=validate,
                        activate=activate, verify=verify,
                        verify_restored=verify_restored,
                        auto_policy_sha256=profile["policy_sha256"],
                        auto_event_token=progress["token"],
                        auto_source_verify=lambda: (
                            _native_vendor_values(controller.config_root, version, active)
                            if _native_opt_marker(controller.config_root, version) is not None
                            and reader() == progress else None))
                updated = {**profile, "last_token": progress["token"],
                           "last_state": result["state"],
                           "last_operation": result["operation_id"],
                           "active": None}
                _save(fd, {**store, "revision": store["revision"] + 1,
                           "profiles": {**store["profiles"], version: updated}})
                outcomes.append({"version": version, "state": result["state"],
                                 "operation_id": result["operation_id"],
                                 "reconciled": result.get("reconciled", False)})
            except Exception as exc:
                # An error during a host Apply retains its original recovery
                # journal and does not consume or silently discard the witness.
                stage = exc.stage if isinstance(exc, recovery.FpmApplyError) else type(exc).__name__
                try:
                    store = _read(fd)
                    previous = store["profiles"].get(version)
                    if previous and previous["enabled"]:
                        if (previous["last_token"] == progress["token"]
                                and previous["last_operation"] is not None
                                and previous["last_state"] == "Applied"):
                            # The durable acknowledgment already landed; a
                            # later fsync/response exception must not erase
                            # truthful operation state and identity.
                            pass
                        else:
                            note = "Repair refused at " + str(stage)[:48]
                            _save(fd, {**store, "revision": store["revision"] + 1,
                                       "profiles": {**store["profiles"], version:
                                                    {**previous, "last_state": note}}})
                except Exception:
                    pass
                raise
            finally:
                # Requests arriving while validation/reload held this lock
                # are honored at the transaction boundary before another
                # terminal event can authorize a future write.
                try:
                    revoked = _consume_revoke_locked(fd, version) or revoked
                finally:
                    os.close(lock)
        finally:
            os.close(fd)
    return {"state": "Processed" if outcomes else "No new owned event",
            "changed": any(r["state"] == "Applied" and not r.get("reconciled", False)
                           for r in outcomes),
            "revocation_completed": revoked,
            "services": outcomes}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["run"]:
        print("Usage: ach_customizer_fpm_auto.py run", file=sys.stderr)
        return 2
    completed = False
    try:
        result = run()
        completed = True
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print("ACh automatic FPM repair refused: " + type(exc).__name__, file=sys.stderr)
        return 1
    finally:
        try:
            # A failed/unacknowledged revocation must keep its only owned
            # retry mechanism, including after an unlink-directory fsync
            # failure when the canonical path is temporarily absent.
            if completed and not any_enabled() and not any_pending_disable():
                import ach_customizer_fpm_watcher as watcher
                watcher._stop()
        except Exception as exc:
            print("ACh FPM watcher stop remains unconfirmed: " +
                  type(exc).__name__, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
