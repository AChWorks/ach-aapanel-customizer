"""Opt-in, fail-closed native WP Toolkit terminal witness and manual Hosts review.

Only aaPanel 8.0.7's verified asynchronous single-site WP2 writer is supported.
The event-driven worker observes an *active* progress record and an absent
alias before it may report an exact, newly appended vendor record on failure.
It never automatically edits /etc/hosts: Linux write leases can be forcibly
broken even after a successful final check, making unattended truncation unsafe.
Older applied journals remain inspectable and explicitly restorable.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import sys
import time
from pathlib import Path
from uuid import uuid4

from ach_customizer_hosts import _hostname
from ach_customizer_hosts_manage import (
    HostsManageError, _locked_state, _new_file, _open_parent, _read_owned,
    _read_source, _same_identity, _sha,
)
from ach_customizer_state import DATA_DIR, _open_state_dir

PROGRESS = "/tmp/wp_aapanel_deploy.log"
LOCK = "/tmp/wp_aapanel_deploy.lock"
BATCH_LOCK = "/tmp/wp_batch_aapanel_deploy.lock"
HOSTS = "/etc/hosts"
NATIVE_SOURCE = "/www/server/panel/class_v2/one_key_wp_v2.py"
NATIVE_SOURCE_SHA = "7578c279424f0b653c0f65ca2f22fbf0b86ce873673b05939e4b4b16c6713bf8"
NATIVE_SITE_SOURCE = "/www/server/panel/class_v2/panel_site_v2.py"
NATIVE_SITE_SHA = "b75a5a0b45c319df7eb49381363d3c3e90208157ebfd88de6f9b173d013d98fb"
NATIVE_META = "/www/server/panel/class/common.py"
# Advertise the loaded Python module's actual safety/diagnostic contract,
# not a fresh on-disk version which may hide stale aaPanel worker imports.
MANUAL_REVIEW_CONTRACT = "durable-manual-review-v2"
STATE_FILE = "ach_customizer.wp-terminal.json"
MANUAL_REVIEW_PREFIX = "ach_customizer.wp-terminal."
MANUAL_REVIEW_SUFFIX = ".manual-review.json"
MANUAL_REVIEW_FILE = re.compile(
    r"ach_customizer\.wp-terminal\.([0-9a-f]{32})\.manual-review\.json\Z")
MANUAL_REVIEW_REASON = (
    "Exact native WP failed-install alias observed; Hosts unchanged; inspect Activity and remove manually")
MAX_MANUAL_REVIEW_BYTES = 2048
MAX_STATE_BYTES = 8192
MAX_PROGRESS_BYTES = 32768
MAX_AGE_NS = 15 * 60 * 1_000_000_000
MAX_RECOVERIES = 64
OP = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class TerminalError(RuntimeError):
    pass


def _trusted_file(path, *, limit, allow_tmp=False):
    """Read a root-owned, stable, non-symlink regular file without credentials."""
    if allow_tmp and not path.startswith("/tmp/"):
        raise TerminalError("Unexpected progress source")
    fd = os.open(path, FILE_FLAGS)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o022
                or not 0 < before.st_size <= limit):
            raise TerminalError("Untrusted native progress/source file")
        content = bytearray()
        while len(content) <= limit:
            part = os.read(fd, limit + 1 - len(content))
            if not part:
                break
            content.extend(part)
        after = os.fstat(fd)
        pathname = os.stat(path, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_uid", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(content) != before.st_size or any(
                getattr(before, key) != getattr(after, key)
                or getattr(before, key) != getattr(pathname, key) for key in fields):
            raise TerminalError("Native source changed during inspection")
        return bytes(content), before
    finally:
        os.close(fd)


def _native_supported(source=NATIVE_SOURCE):
    raw, _ = _trusted_file(source, limit=262144)
    handler, _ = _trusted_file(NATIVE_SITE_SOURCE, limit=1048576)
    panel, _ = _trusted_file(NATIVE_META, limit=65536)
    version = re.findall(rb"\bg\.version\s*=\s*'([0-9]+\.[0-9]+\.[0-9]+)'", panel)
    if (_sha(raw) != NATIVE_SOURCE_SHA or _sha(handler) != NATIVE_SITE_SHA
            or version != [b"8.0.7"]):
        raise TerminalError("Unverified native aaPanel 8.0.7 WP Toolkit writer or lifecycle; disable automatic reconciliation")


def _progress(path=PROGRESS):
    raw, meta = _trusted_file(path, limit=MAX_PROGRESS_BYTES, allow_tmp=True)
    try:
        row = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise TerminalError("Invalid native WordPress progress record") from exc
    if not isinstance(row, dict) or type(row.get("status")) is not int or row["status"] not in (0, 1):
        raise TerminalError("Unverified native WordPress progress status")
    if "Create_website" in row:  # Batch uses a separate lifecycle and shared log.
        raise TerminalError("Batch native WordPress progress is not supported")
    try:
        domain = _hostname(row["site_name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TerminalError("Native WordPress progress has no supported exact hostname") from exc
    if ("." not in domain or domain in ("localhost", "ip6-localhost", "ip6-loopback")
            or row["site_name"] != domain):
        raise TerminalError("Native WordPress progress hostname needs review")
    steps = ("parameter_verification", "create_website", "optional_configurations", "initialize_wp_website")
    status = []
    for step in steps:
        value = row.get(step)
        if not isinstance(value, dict) or type(value.get("status")) is not int or value["status"] not in (-1, 0, 1, 2):
            raise TerminalError("Malformed native WordPress step status")
        status.append(value["status"])
    return {"status": row["status"], "domain": domain, "steps": status,
            "dev": meta.st_dev, "ino": meta.st_ino, "mtime_ns": meta.st_mtime_ns,
            "token": hashlib.sha256(raw + str(meta.st_mtime_ns).encode()).hexdigest()}


def _default():
    return {"schema": 1, "revision": 0, "enabled": False,
            "enabled_ns": 0, "active": None, "last_token": None,
            "last_recovery": None, "last_reason": "Disabled", "recoveries": 0,
            "last_worker": {"state": "Not Observed", "stage": "idle",
                            "reason": "No native event evaluated", "operation_id": None}}


def _validate(row):
    default = _default()
    if (not isinstance(row, dict) or set(row) != set(default)
            or type(row["schema"]) is not int or row["schema"] != 1
            or type(row["revision"]) is not int or not 0 <= row["revision"] <= 2147483647
            or type(row["enabled"]) is not bool
            or type(row["enabled_ns"]) is not int or row["enabled_ns"] < 0
            or type(row["recoveries"]) is not int or not 0 <= row["recoveries"] <= MAX_RECOVERIES
            or not isinstance(row["last_reason"], str) or len(row["last_reason"]) > 240):
        raise TerminalError("Invalid native WordPress automation policy")
    worker = row["last_worker"]
    if (not isinstance(worker, dict) or set(worker) != {"state", "stage", "reason", "operation_id"}
            or not all(isinstance(worker[key], str) for key in ("state", "stage", "reason"))
            or len(worker["state"]) > 40 or len(worker["stage"]) > 64
            or len(worker["reason"]) > 240
            or (worker["operation_id"] is not None and
                (not isinstance(worker["operation_id"], str)
                 or not OP.fullmatch(worker["operation_id"])))):
        raise TerminalError("Invalid native WordPress operational outcome")
    if row["last_token"] is not None and (not isinstance(row["last_token"], str) or not SHA.fullmatch(row["last_token"])):
        raise TerminalError("Invalid native WordPress event token")
    if row["last_recovery"] is not None and (not isinstance(row["last_recovery"], str) or not OP.fullmatch(row["last_recovery"])):
        raise TerminalError("Invalid native WordPress recovery token")
    active = row["active"]
    if active is not None and (not isinstance(active, dict) or set(active) != {"operation", "domain", "dev", "ino", "started_ns", "source_sha"}
            or not isinstance(active["domain"], str) or _hostname(active["domain"]) != active["domain"]
            or not isinstance(active["operation"], str) or not OP.fullmatch(active["operation"])
            or not isinstance(active["source_sha"], str) or not SHA.fullmatch(active["source_sha"])
            or any(type(active[k]) is not int or active[k] < 0 for k in ("dev", "ino", "started_ns"))):
        raise TerminalError("Invalid active native WordPress witness")
    return row


def _load(state_fd):
    raw = _read_owned(state_fd, STATE_FILE, max_bytes=MAX_STATE_BYTES)
    if raw is None:
        return _default()
    try:
        return _validate(json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeError) as exc:
        raise TerminalError("Unreadable WordPress automation policy") from exc


def _save(state_fd, row):
    raw = (json.dumps(_validate(row), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_STATE_BYTES:
        raise TerminalError("WordPress automation policy too large")
    staging = "." + STATE_FILE + "." + uuid4().hex + ".tmp"
    _new_file(state_fd, staging, raw)
    try:
        os.replace(staging, STATE_FILE, src_dir_fd=state_fd, dst_dir_fd=state_fd)
        os.fsync(state_fd)
    finally:
        try:
            os.unlink(staging, dir_fd=state_fd)
        except FileNotFoundError:
            pass


def _manual_review_name(operation):
    if not isinstance(operation, str) or not OP.fullmatch(operation):
        raise TerminalError("Invalid manual-review operation ID")
    return MANUAL_REVIEW_PREFIX + operation + MANUAL_REVIEW_SUFFIX


def _read_manual_review(fd, operation):
    """Read one private, immutable-identity event and its delivery receipt."""
    payload = _read_owned(fd, _manual_review_name(operation), required=True,
                          max_bytes=MAX_MANUAL_REVIEW_BYTES)
    try:
        row = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise TerminalError("Unreadable native WP manual-review evidence") from exc
    event = row.get("event") if isinstance(row, dict) else None
    required_fields = {"schema", "time_utc", "level", "module", "action",
                       "stage", "outcome", "operation_id", "target",
                       "error_class", "detail", "recovery_id"}
    if (not isinstance(row, dict) or set(row) != {"schema", "created_ns", "delivered", "event"}
            or type(row["schema"]) is not int or row["schema"] != 1
            or type(row["created_ns"]) is not int or row["created_ns"] <= 0
            or type(row["delivered"]) is not bool or not isinstance(event, dict)
            or set(event) != required_fields
            or not all(isinstance(v, str) for k, v in event.items() if k != "schema")
            or type(event["schema"]) is not int or event["schema"] != 1
            or event["operation_id"] != operation
            or event["level"] != "WARNING" or event["module"] != "lifecycle"
            or event["action"] != "wp_terminal_manual_review"
            or event["stage"] != "native_terminal"
            or event["outcome"] != "Manual Review Required"
            or event["detail"] != MANUAL_REVIEW_REASON
            or event["error_class"] or event["recovery_id"]
            or len(event["time_utc"]) > 40
            or not event["time_utc"].endswith("+00:00")
            or _hostname(event["target"]) != event["target"]
            or "." not in event["target"]):
        raise TerminalError("Invalid native WP manual-review ownership or content")
    return row


def _scan_manual_reviews(fd):
    """Preserve usable evidence even if one older canonical record is damaged.

    Only the strictly validated, final canonical filename is authoritative.
    Leftover private staging files from a killed writer are never enumerated.
    An invalid canonical record is NOT deleted, hidden or auto-repaired;
    its Operation ID is surfaced for a separately reviewed OS-level recovery.
    """
    rows, incomplete = [], []
    for filename in os.listdir(fd):
        match = MANUAL_REVIEW_FILE.fullmatch(filename)
        if not match:
            continue
        operation = match.group(1)
        try:
            rows.append(_read_manual_review(fd, operation))
        except (OSError, HostsManageError, TerminalError, ValueError):
            incomplete.append(operation)
    return (sorted(rows, key=lambda row: (row["created_ns"], row["event"]["operation_id"]),
                   reverse=True), sorted(incomplete))


def _manual_review_rows(fd):
    return _scan_manual_reviews(fd)[0]


def _write_manual_review(fd, row, *, initial=False):
    operation = row["event"]["operation_id"]
    name = _manual_review_name(operation)
    payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_MANUAL_REVIEW_BYTES:
        raise TerminalError("Native WP manual-review evidence is too large")
    if initial:
        # Write and fsync a unique private staging inode FIRST, then
        # atomically publish by hard-linking it at the operation's canonical
        # name. link(2) is no-clobber (EEXIST) and does not expose partially
        # written bytes to readers; a killed writer leaves only an ignored
        # .tmp file. Never rename-replace an existing evidence record.
        staging = "." + name + "." + uuid4().hex + ".tmp"
        try:
            _new_file(fd, staging, payload)
            try:
                os.link(staging, name, src_dir_fd=fd, dst_dir_fd=fd,
                        follow_symlinks=False)
            except FileExistsError:
                previous = _read_manual_review(fd, operation)
                if (previous["event"]["target"] != row["event"]["target"]
                        or previous["event"]["detail"] != row["event"]["detail"]):
                    raise TerminalError("Conflicting native WP manual-review ownership")
            # Covers both the final link and any staging cleanup after it.
            os.fsync(fd)
        finally:
            try:
                os.unlink(staging, dir_fd=fd)
            except FileNotFoundError:
                pass
        return
    staging = "." + name + "." + uuid4().hex + ".tmp"
    _new_file(fd, staging, payload)
    try:
        os.replace(staging, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(staging, dir_fd=fd)
        except FileNotFoundError:
            pass


def _prepare_manual_review(fd, operation, domain):
    """Durable, single-operation source of truth BEFORE the terminal token save."""
    try:
        existing = _read_owned(fd, _manual_review_name(operation),
                               max_bytes=MAX_MANUAL_REVIEW_BYTES)
        row = _read_manual_review(fd, operation) if existing is not None else None
    except (OSError, HostsManageError, TerminalError, ValueError) as exc:
        raise TerminalError(
            "Incomplete canonical manual-review evidence for Operation ID "
            + operation + "; preserve and quarantine only after independent OS review"
        ) from exc
    if row is not None:
        if row["event"]["target"] != domain:
            raise TerminalError("Conflicting native WP manual-review domain")
        return row
    from ach_customizer_activity import record
    event = record(
        level="WARNING", module="lifecycle", action="wp_terminal_manual_review",
        operation_id=operation, stage="native_terminal", outcome="Manual Review Required",
        target=domain, detail=MANUAL_REVIEW_REASON)
    row = {"schema": 1, "created_ns": time.time_ns(), "delivered": False, "event": event}
    _write_manual_review(fd, row, initial=True)
    return _read_manual_review(fd, operation)


def _deliver_pending_manual_reviews(fd, data_dir):
    """Retry the durable outbox without ever replaying a Hosts operation.

    The logger checks both live and rotated Activity files under its own lock,
    so a crash after log fsync but before the receipt update is idempotent.
    The immutable event itself remains available even while delivery fails.
    """
    from ach_customizer_activity import append_activity
    for row in _manual_review_rows(fd):
        if row["delivered"]:
            continue
        try:
            persisted = append_activity(data_dir, row["event"], mandatory_manual_review=True)
            if persisted is not True:
                continue
            updated = dict(row)
            updated["delivered"] = True
            _write_manual_review(fd, updated)
        except Exception:
            # Never consume the source-of-truth outbox identity or terminal
            # token to mask an audit failure. A later invocation retries.
            continue


def manual_review_activity(*, data_dir=DATA_DIR, level="", module="",
                           with_integrity=False):
    """Privileged projection of usable events plus optional incomplete IDs."""
    fd = _open_state_dir(data_dir)
    try:
        rows, incomplete = _scan_manual_reviews(fd)
        events = [row["event"] for row in rows
                  if (not level or row["event"]["level"] == level)
                  and (not module or row["event"]["module"] == module)]
        return (events, incomplete) if with_integrity else events
    finally:
        os.close(fd)


def inspect(*, data_dir=DATA_DIR):
    fd = _open_state_dir(data_dir)
    try:
        value = _load(fd)
        # Do not expose raw baseline, vendor progress text or private paths.
        recovery_state = None
        recovery_id = value["last_recovery"]
        if value["active"] and _read_owned(fd, _recovery_name(value["active"]["operation"]), max_bytes=4096) is not None:
            recovery_id = value["active"]["operation"]
        if recovery_id:
            try:
                recovery_state = _read_recovery(fd, recovery_id)["phase"]
            except (TerminalError, HostsManageError):
                recovery_state = "Needs Review"
        manual_rows, incomplete = _scan_manual_reviews(fd)
        latest = manual_rows[0] if manual_rows else None
        manual_review = ({
            "operation_id": latest["event"]["operation_id"],
            "domain": latest["event"]["target"],
            "activity_delivered": latest["delivered"],
        } if latest else None)
        return {key: value[key] for key in ("enabled", "revision", "last_reason", "recoveries", "last_worker")} | {
            "manual_review": manual_review,
            "manual_review_count": len(manual_rows),
            "manual_review_integrity": {
                "state": "Needs Review" if incomplete else "Complete",
                "incomplete_count": len(incomplete),
                "first_operation_id": incomplete[0] if incomplete else None,
            },
            "last_recovery": recovery_id,
            "active_domain": value["active"]["domain"] if value["active"] else None,
            "last_recovery_state": recovery_state,
            "scope": "failed_native_single_site_wp_toolkit", "auto_hosts": False,
            "auto_fpm": False, "read_only": True}
    finally:
        os.close(fd)


def set_enabled(enabled, *, data_dir=DATA_DIR):
    if type(enabled) is not bool:
        raise TerminalError("Invalid WordPress automation enablement")
    with _locked_state(data_dir) as fd:
        row = _load(fd)
        if row["enabled"] == enabled:
            return inspect(data_dir=data_dir)
        if enabled and row["active"] is not None:
            raise TerminalError("Unresolved native WP witness; recheck recovery before re-enabling")
        row = {**row, "enabled": enabled, "revision": row["revision"] + 1,
               "enabled_ns": time.time_ns() if enabled else 0,
               "last_reason": "Armed for future native WP Toolkit events" if enabled else "Disabled",
               "last_worker": ({"state": "Not Observed", "stage": "idle",
                                "reason": "Awaiting native event", "operation_id": None}
                               if enabled else row["last_worker"])}
        _save(fd, row)
    return inspect(data_dir=data_dir)


def _worker_outcome(fd, policy, state, stage, reason, *, data_dir, operation=None, domain=""):
    """Persist one safe operational observation per changed outcome.

    No vendor error, file contents, URL or request body reaches state or
    Activity. Timer repeats with the same cause never create extra rows.
    """
    if operation is None and policy.get("active") is not None:
        operation = policy["active"]["operation"]
    observed = {"state": state, "stage": stage, "reason": reason,
                "operation_id": operation}
    review_states = ("Needs Review", "Recovery Required", "Manual Review Required")
    if policy["last_worker"] != observed:
        policy["last_worker"] = observed
        if state in review_states:
            policy["last_reason"] = reason
        _save(fd, policy)
        if state in ("Needs Review", "Recovery Required"):
            try:
                from ach_customizer_activity import append_activity, record
                durable_recovery = (operation if operation and
                    _read_owned(fd, _recovery_name(operation), max_bytes=4096) is not None else "")
                entry = record(
                    level="WARNING", module="lifecycle", action="wp_terminal_refused",
                    operation_id=operation or uuid4().hex,
                    stage=stage, outcome=state, target=domain,
                    detail=reason, recovery_id=durable_recovery)
                append_activity(data_dir, entry)
            except Exception:
                import logging
                logging.getLogger("ach_customizer").exception(
                    "Native WP operational refusal Activity persistence failed")
        # Manual Review Required has its own immutable evidence file. Generic
        # Activity is a recoverable projection, never the sole domain identity.
    return {"state": state, "changed": False,
            **({"reason": reason} if state in review_states else {}),
            **({"recovery_id": operation} if state == "Recovery Required" and operation and
                _read_owned(fd, _recovery_name(operation), max_bytes=4096) is not None else {})}


def _baseline_name(operation):
    return "ach_customizer.wp-terminal." + operation + ".before"


def _recovery_name(operation):
    return "ach_customizer.wp-terminal." + operation + ".recovery.json"


def _save_recovery(fd, record):
    name = _recovery_name(record["operation"])
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    staging = "." + name + "." + uuid4().hex + ".tmp"
    _new_file(fd, staging, raw)
    try:
        os.replace(staging, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(staging, dir_fd=fd)
        except FileNotFoundError:
            pass


def _release_unused_baseline(fd, operation):
    """Retain backups only for edits and unresolved prepared operations."""
    name = _baseline_name(operation)
    stored = _read_owned(fd, name, max_bytes=65536)
    if stored is None:
        return
    os.unlink(name, dir_fd=fd)
    os.fsync(fd)


def _read_recovery(fd, operation):
    if not isinstance(operation, str) or not OP.fullmatch(operation):
        raise TerminalError("Invalid WordPress recovery ID")
    raw = _read_owned(fd, _recovery_name(operation), required=True, max_bytes=4096)
    try:
        row = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise TerminalError("Unreadable WordPress recovery record") from exc
    if (not isinstance(row, dict) or set(row) != {"schema", "operation", "domain", "phase", "before_sha", "after_sha", "backup"}
            or row["schema"] != 1 or row["operation"] != operation
            or row["backup"] != _baseline_name(operation)
            or row["phase"] not in ("prepared", "applied", "restore_prepared", "restored", "not_applied")
            or any(not isinstance(row[k], str) or not SHA.fullmatch(row[k]) for k in ("before_sha", "after_sha"))
            or _hostname(row["domain"]) != row["domain"]):
        raise TerminalError("Invalid WordPress recovery ownership")
    return row


def _append_hosts_with_kernel_lease(parent, *, expected, desired, baseline, operation,
                                    prepare):
    """Append a *reviewed legacy Restore* suffix without overwriting other data.

    This is NEVER used for unattended removal. Even a successfully acquired
    Linux write lease can be forcibly broken after lease-break-time. The
    explicitly reviewed legacy Restore therefore uses O_APPEND + write(2),
    not pwrite at a stale offset: a competing append that wins before ours
    survives unchanged, followed by a Needs Review journal outcome.

    This does not assert exclusion of arbitrary third-party file writers or
    guarantee a successful Restore when external changes occur. No truncate,
    rename of Hosts or other destructive syscall is permitted here.
    """
    if (not isinstance(operation, str) or not OP.fullmatch(operation)
            or not isinstance(expected, bytes) or not isinstance(desired, bytes)
            or not desired.startswith(expected) or expected == desired):
        raise TerminalError("Only guarded append-only legacy Restore is available")
    flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    source = os.open("hosts", flags, dir_fd=parent)
    previous_signal = None
    breaking = False

    def lease_break(_signal, _frame):
        nonlocal breaking
        breaking = True

    try:
        previous_signal = signal.getsignal(signal.SIGIO)
        signal.signal(signal.SIGIO, lease_break)
        try:
            fcntl.fcntl(source, fcntl.F_SETLEASE, fcntl.F_WRLCK)
        except OSError as exc:
            raise TerminalError("Kernel write lease unavailable for legacy Restore; use manual review") from exc
        before = os.fstat(source)
        pathname = os.stat("hosts", dir_fd=parent, follow_symlinks=False)
        if (not _same_identity(baseline, before) or not _same_identity(before, pathname)
                or before.st_uid != os.geteuid() or before.st_nlink != 1
                or not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022
                or os.listxattr(source)):
            raise TerminalError("Hosts source changed or has unsupported metadata under write lease")
        if os.lseek(source, 0, os.SEEK_SET) != 0 or os.read(source, len(expected) + 1) != expected:
            raise TerminalError("Hosts source changed before guarded legacy Restore")
        if breaking or fcntl.fcntl(source, fcntl.F_GETLEASE) != fcntl.F_WRLCK:
            raise TerminalError("Hosts writer requested access during guarded legacy Restore")

        # The pre-append recovery phase is durable before touching Hosts.
        prepare()
        if (breaking or fcntl.fcntl(source, fcntl.F_GETLEASE) != fcntl.F_WRLCK
                or os.path.lexists(LOCK) or os.path.lexists(BATCH_LOCK)):
            raise TerminalError("Hosts lease changed or native task restarted; Recheck recovery")
        identity = os.stat("hosts", dir_fd=parent, follow_symlinks=False)
        if identity.st_ino != before.st_ino or identity.st_dev != before.st_dev:
            raise TerminalError("Hosts pathname changed; Recheck recovery")

        # Atomic EOF assignment by the kernel. Even if an uncoordinated writer
        # is admitted after forced lease expiration, never overwrite its bytes.
        suffix = desired[len(expected):]
        if os.write(source, suffix) != len(suffix):
            raise TerminalError("Partial legacy Restore append; Recheck recovery")
        os.fsync(source)
        after = os.fstat(source)
        if (after.st_size != len(desired) or os.lseek(source, 0, os.SEEK_SET) != 0
                or os.read(source, len(desired) + 1) != desired):
            raise TerminalError("Legacy Restore changed or source diverged; Recheck recovery")
        identity = os.stat("hosts", dir_fd=parent, follow_symlinks=False)
        if (identity.st_ino != after.st_ino or identity.st_dev != after.st_dev
                or breaking or fcntl.fcntl(source, fcntl.F_GETLEASE) != fcntl.F_WRLCK):
            raise TerminalError("Hosts changed during guarded legacy Restore; Recheck recovery")
    finally:
        # Closing our sole open-file description releases the lease even if
        # the kernel already forcibly revoked it. F_UNLCK can return EAGAIN
        # after such a break and must not conceal the actual write outcome.
        try:
            os.close(source)
        finally:
            if previous_signal is not None:
                signal.signal(signal.SIGIO, previous_signal)


def _source_payload(path):
    parent = _open_parent(path)
    try:
        return _read_source(parent)[0]
    finally:
        os.close(parent)


def process_event(*, data_dir=DATA_DIR, hosts_path=HOSTS, progress_path=PROGRESS,
                  native_source=NATIVE_SOURCE, now_ns=None):
    """Handle one native filesystem notification without editing Hosts."""
    now_ns = time.time_ns() if now_ns is None else now_ns
    with _locked_state(data_dir) as fd:
        # Recovery is independent of the native progress lifecycle and must
        # run before Disabled/Already Observed can short-circuit delivery.
        _deliver_pending_manual_reviews(fd, data_dir)
        policy = _load(fd)
        if not policy["enabled"]:
            return {"state": "Disabled", "changed": False}
        try:
            _native_supported(native_source)
        except (OSError, TerminalError):
            return _worker_outcome(
                fd, policy, "Needs Review", "native_source",
                "Pinned aaPanel WordPress source fingerprint/version mismatch or unreadable",
                data_dir=data_dir)
        try:
            progress = _progress(progress_path)
        except FileNotFoundError:
            return _worker_outcome(
                fd, policy, "Needs Review" if policy["active"] else "Idle",
                "native_progress", "Native progress missing while a witness remains" if policy["active"]
                else "No native WordPress operation observed", data_dir=data_dir)
        except (OSError, TerminalError):
            return _worker_outcome(
                fd, policy, "Needs Review", "native_progress",
                "Native WordPress progress unreadable or malformed; inspect vendor task",
                data_dir=data_dir)
        # A completed task without pre-terminal context is not a trustworthy detection.
        if progress["status"] == 1 and policy["active"] is None:
            if policy["last_token"] == progress["token"]:
                return {"state": "Already Observed", "changed": False}
            policy["last_token"] = progress["token"]
            policy["last_reason"] = "Native WP terminal without a preceding witness; no edit"
            _save(fd, policy)
            return _worker_outcome(
                fd, policy, "No Witness", "native_terminal",
                "Native terminal event was not witnessed before setup; no edit",
                data_dir=data_dir)
        if (os.path.lexists(BATCH_LOCK) or
                (progress["status"] == 1 and os.path.lexists(LOCK))):
            return _worker_outcome(
                fd, policy, "Active or Unknown", "native_locks",
                "Native WordPress or batch task still owns the progress lifecycle",
                data_dir=data_dir)
        active = policy["active"]
        if progress["status"] == 0:
            if active is not None:
                return _worker_outcome(
                    fd, policy, "Witness Active", "native_progress",
                    "Witnessed native WordPress setup is still in progress",
                    data_dir=data_dir, domain=active["domain"])
            if (not os.path.lexists(LOCK) or progress["mtime_ns"] + 1_000_000_000 < policy["enabled_ns"]
                    or abs(now_ns - progress["mtime_ns"]) > MAX_AGE_NS
                    or progress["steps"][3] not in (0, 2)):
                return _worker_outcome(
                    fd, policy, "Active or Unknown", "native_progress",
                    "Native task start, staleness, lock or lifetime guard not satisfied",
                    data_dir=data_dir)
            try:
                baseline = _source_payload(hosts_path)
            except (HostsManageError, OSError):
                return _worker_outcome(
                    fd, policy, "Needs Review", "hosts_baseline",
                    "Trusted Hosts source unavailable; no native WP witness armed",
                    data_dir=data_dir)
            domain = progress["domain"]
            # A mapping that existed before the task is never vendor-owned.
            if any(_hostname_alias(line, domain) for line in baseline.splitlines()):
                return _worker_outcome(
                    fd, policy, "Intentional Alias Possible", "hosts_baseline",
                    "A Hosts alias already exists before native WordPress setup; no edit",
                    data_dir=data_dir, domain=domain)
            operation = uuid4().hex
            _new_file(fd, _baseline_name(operation), baseline)
            os.fsync(fd)
            policy["active"] = {"operation": operation, "domain": domain,
                                "dev": progress["dev"], "ino": progress["ino"],
                                "started_ns": progress["mtime_ns"], "source_sha": _sha(baseline)}
            policy["last_reason"] = "Native WP setup observed before any local alias"
            _save(fd, policy)
            _worker_outcome(fd, policy, "Witness Armed", "native_progress",
                            "Alias-free native WordPress setup observed",
                            data_dir=data_dir, domain=domain)
            return {"state": "Witness Armed", "changed": False, "domain": domain}
        if active is None:
            return _worker_outcome(
                fd, policy, "No Witness", "native_progress",
                "No witnessed native WordPress operation; no edit", data_dir=data_dir)
        if (progress["domain"] != active["domain"] or progress["dev"] != active["dev"]
                or progress["ino"] != active["ino"] or progress["mtime_ns"] <= active["started_ns"]
                or abs(now_ns - progress["mtime_ns"]) > MAX_AGE_NS
                or progress["mtime_ns"] - active["started_ns"] > MAX_AGE_NS
                or os.path.lexists(LOCK)):
            return _worker_outcome(
                fd, policy, "Needs Review", "native_identity",
                "Native WordPress progress identity, timing or lock changed; no edit",
                data_dir=data_dir, domain=active["domain"])
        if policy["last_token"] == progress["token"]:
            return {"state": "Already Observed", "changed": False}
        if progress["steps"] == [1, 1, 1, 1]:
            reason, state = "Native WP Toolkit succeeded; vendor owns its cleanup", "Success"
            changed = False
        elif progress["steps"] == [1, 1, 1, -1]:
            try:
                old = _read_owned(fd, _baseline_name(active["operation"]), required=True)
            except (HostsManageError, OSError):
                return _worker_outcome(
                    fd, policy, "Needs Review", "witness_backup",
                    "Native WordPress witness backup unavailable; inspect manually",
                    data_dir=data_dir, domain=active["domain"])
            if _sha(old) != active["source_sha"]:
                return _worker_outcome(
                    fd, policy, "Needs Review", "witness_backup",
                    "Native WordPress witness backup fingerprint changed; inspect manually",
                    data_dir=data_dir, domain=active["domain"])
            if _read_owned(fd, _recovery_name(active["operation"]), max_bytes=4096) is not None:
                return _worker_outcome(
                    fd, policy, "Recovery Required", "recovery_journal",
                    "Prior native WP recovery journal exists; Recheck before another action",
                    data_dir=data_dir, domain=active["domain"])
            try:
                current = _source_payload(hosts_path)
            except (HostsManageError, OSError):
                return _worker_outcome(
                    fd, policy, "Needs Review", "hosts_observation",
                    "Trusted Hosts source unavailable; inspect manually",
                    data_dir=data_dir, domain=active["domain"])
            if current == old + b"\n127.0.0.1 " + active["domain"].encode("ascii"):
                # No linearizable conditional deletion syscall is available for
                # uncoordinated writers. A Linux write lease is time-bounded;
                # F_GETLEASE followed by ftruncate may erase a later append.
                # Preserve the entire file, record a safe manual-review result,
                # and retire this witnessed terminal token (no retry).
                reason, state, changed = (MANUAL_REVIEW_REASON, "Manual Review Required", False)
                # Durable mapping first: a crash or disk/log policy failure
                # after the terminal token is committed must never erase the
                # actionable domain and operation identity.
                _prepare_manual_review(fd, active["operation"], active["domain"])
            else:
                reason, state, changed = (
                    "Hosts differs from witnessed vendor append; no edit; inspect manually",
                    "Needs Review", False)
        else:
            reason, state, changed = "Native WP result is not an eligible terminal install", "Needs Review", False
        policy["active"] = None
        policy["last_token"] = progress["token"]
        policy["last_reason"] = reason
        # Commit terminal token AND the actionable last-worker state together.
        # A crash between two separate policy writes would otherwise leave an
        # Already Observed token without the manual-review Activity evidence.
        _worker_outcome(fd, policy, state, "native_terminal", reason,
                        data_dir=data_dir, operation=active["operation"], domain=active["domain"])
        if state == "Manual Review Required":
            _deliver_pending_manual_reviews(fd, data_dir)
        if not changed:
            _release_unused_baseline(fd, active["operation"])
        return {"state": state, "changed": changed, "domain": active["domain"],
                "recovery_id": policy["last_recovery"] if changed else None,
                "reason": reason}


def _hostname_alias(line, domain):
    """Conservative: any pre-existing alias token prevents automatic deletion."""
    try:
        active = line.split(b"#", 1)[0].split()
        return domain.encode("ascii").lower() in (item.lower() for item in active[1:])
    except Exception:
        return True


def recheck_recovery(*, data_dir=DATA_DIR, hosts_path=HOSTS, progress_path=PROGRESS):
    """Owner-requested evidence-only resolution of a crash-window journal.

    This NEVER edits /etc/hosts. It only reconciles a prepared journal when
    the current source matches exactly one of its two saved SHA-256 states.
    """
    with _locked_state(data_dir) as fd:
        policy = _load(fd)
        active = policy["active"]
        if os.path.lexists(LOCK) or os.path.lexists(BATCH_LOCK):
            return {"state": "Active or Unknown", "changed": False}
        recovery_id = active["operation"] if active else policy["last_recovery"]
        if not recovery_id:
            return {"state": "No Recovery", "changed": False}
        raw = _read_owned(fd, _recovery_name(recovery_id), max_bytes=4096)
        if raw is None:
            if not active:
                return {"state": "No Recovery", "changed": False}
            try:
                progress = _progress(progress_path)
            except (OSError, TerminalError):
                return {"state": "Needs Review", "changed": False}
            if (progress["status"] != 1 or progress["domain"] != active["domain"]
                    or progress["ino"] != active["ino"] or progress["dev"] != active["dev"]):
                return {"state": "Active or Unknown", "changed": False}
            policy["active"] = None
            policy["last_token"] = progress["token"]
            policy["last_reason"] = "Witness abandoned after a proven terminal operation without an edit"
            _save(fd, policy)
            _release_unused_baseline(fd, active["operation"])
            return {"state": "No Repair Pending", "changed": False}
        record = _read_recovery(fd, recovery_id)
        if active is not None and active["operation"] != recovery_id:
            return {"state": "Needs Review", "changed": False, "recovery_id": recovery_id,
                    "reason": "Another native WordPress witness is unresolved"}
        baseline = _read_owned(fd, record["backup"], required=True)
        appended = baseline + b"\n127.0.0.1 " + record["domain"].encode("ascii")
        if _sha(baseline) != record["after_sha"] or _sha(appended) != record["before_sha"]:
            raise TerminalError("Interrupted recovery source evidence is not trustworthy")
        current = _source_payload(hosts_path)
        current_hash = _sha(current)
        if current_hash not in (record["after_sha"], record["before_sha"]):
            return {"state": "Needs Review", "changed": False, "recovery_id": recovery_id,
                    "reason": "Hosts differs from both saved versions"}

        # An exact marker reappearing after a completed historical applied journal is
        # external activity, NOT evidence of an approved Restore. Only a
        # persisted restore_prepared intent can reconcile a crashed Restore.
        if record["phase"] == "applied" and current_hash == record["before_sha"]:
            return {"state": "Needs Review", "changed": False, "recovery_id": recovery_id,
                    "reason": "Exact native WP alias reappeared without a prepared Restore; investigate external writer"}

        # Phase and the actual source together establish a verified outcome.
        if record["phase"] in ("prepared", "not_applied"):
            state = "applied" if current_hash == record["after_sha"] else "not_applied"
        elif record["phase"] in ("applied", "restore_prepared", "restored"):
            state = "applied" if current_hash == record["after_sha"] else "restored"
        else:
            raise TerminalError("Unknown WordPress recovery phase")
        if record["phase"] == "not_applied" and state == "applied":
            return {"state": "Needs Review", "changed": False, "recovery_id": recovery_id,
                    "reason": "Hosts changed after a completed not-applied recovery"}
        if record["phase"] == "restored" and state == "applied":
            return {"state": "Needs Review", "changed": False, "recovery_id": recovery_id,
                    "reason": "Hosts changed after a completed Restore"}

        updated = dict(policy)
        updated["active"] = None
        if state in ("applied", "restored"):
            if updated["last_recovery"] != recovery_id:
                if updated["recoveries"] >= MAX_RECOVERIES:
                    return {"state": "Needs Review", "changed": False,
                            "recovery_id": recovery_id, "reason": "Recovery accounting needs review"}
                updated["recoveries"] += 1
            updated["last_recovery"] = recovery_id
        updated["last_reason"] = {
            "applied": "Verified native WP cleanup applied; Restore may be reviewed",
            "restored": "Verified native WP Restore completed",
            "not_applied": "Verified no native WP cleanup was applied",
        }[state]
        if record["phase"] != state:
            record["phase"] = state
            _save_recovery(fd, record)
        if policy != updated:
            _save(fd, updated)
        return {"state": state, "changed": False, "recovery_id": recovery_id,
                "reason": updated["last_reason"]}


def abandon_witness(*, data_dir=DATA_DIR):
    """Operator-approved, no-Hosts-write witness discard after lost progress.

    A prepared journal must be Rechecked instead. First disable the policy;
    no active native WP task may be assumed terminal from absent progress.
    """
    with _locked_state(data_dir) as fd:
        policy = _load(fd)
        if policy["enabled"]:
            raise TerminalError("Disable native WordPress automation before abandoning a witness")
        if os.path.lexists(LOCK) or os.path.lexists(BATCH_LOCK):
            raise TerminalError("Native WordPress operation may still be active")
        active = policy["active"]
        if active is None:
            return _worker_outcome(
                fd, policy, "No Witness", "native_progress",
                "No witnessed native WordPress operation; no edit", data_dir=data_dir)
        if _read_owned(fd, _recovery_name(active["operation"]), max_bytes=4096) is not None:
            raise TerminalError("Prepared native WordPress recovery exists; Recheck instead")
        policy["active"] = None
        policy["last_reason"] = "Operator abandoned unverified stale WP witness; no Hosts edit"
        _save(fd, policy)
        _release_unused_baseline(fd, active["operation"])
        return {"state": "Witness Abandoned", "changed": False,
                "operation_id": active["operation"]}


def restore(operation, *, data_dir=DATA_DIR, hosts_path=HOSTS):
    """Separate explicit admin-reviewed operation; no implicit rollback."""
    with _locked_state(data_dir) as fd:
        policy = _load(fd)
        if os.path.lexists(LOCK) or os.path.lexists(BATCH_LOCK):
            raise TerminalError("Native WordPress setup may still be active; Restore is unavailable")
        if policy["active"] is not None or policy["last_recovery"] != operation:
            raise TerminalError("Restore requires the newest saved recovery and no active setup")
        record = _read_recovery(fd, operation)
        if record["phase"] != "applied":
            raise TerminalError("No applied native WordPress Hosts recovery")
        backup = _read_owned(fd, record["backup"], required=True)
        if _sha(backup) != record["after_sha"]:
            raise TerminalError("Native WordPress recovery backup changed")
        parent = _open_parent(hosts_path)
        try:
            current, meta = _read_source(parent)
            if _sha(current) != record["after_sha"]:
                raise TerminalError("Hosts changed since automatic repair; do not overwrite")
            # Exact before bytes are the vendor-appended temporary alias.
            restored = backup + b"\n127.0.0.1 " + record["domain"].encode("ascii")
            if _sha(restored) != record["before_sha"]:
                raise TerminalError("Native WordPress recovery candidate differs")
            record["phase"] = "restore_prepared"
            _append_hosts_with_kernel_lease(
                parent, expected=current, desired=restored,
                baseline=meta, operation=operation,
                prepare=lambda: _save_recovery(fd, record))
            record["phase"] = "restored"
            _save_recovery(fd, record)
            policy["last_reason"] = "Operator restored the exact native WP Hosts source"
            _save(fd, policy)
            return {"state": "Restored", "changed": True, "recovery_id": operation}
        finally:
            os.close(parent)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["run"]:
        print("Usage: ach_customizer_wp_terminal.py run", file=sys.stderr)
        return 2
    try:
        result = process_event()
        # Suppress raw progress/error text: only fixed state/recovery identity.
        print("ACh WP terminal: " + result["state"] + (" recovery=" + result["recovery_id"] if result.get("recovery_id") else ""))
        return 0 if result["state"] not in ("Needs Review",) else 1
    except Exception as exc:
        print("ACh WP terminal needs review: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
