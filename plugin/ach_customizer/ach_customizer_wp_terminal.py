"""Opt-in, fail-closed native WP Toolkit terminal witness and manual Hosts review.

Only aaPanel 8.0.7's verified asynchronous single-site WP2 writer is supported.
The event-driven worker observes an *active* progress record and an absent
alias before it may report an exact, newly appended vendor record on failure.
It never automatically edits /etc/hosts: Linux write leases can be forcibly
broken even after a successful final check, making unattended truncation unsafe.
Current observations never create or restore a historical Hosts cleanup.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from uuid import uuid4

from ach_customizer_hosts import _hostname
from ach_customizer_hosts_manage import (
    HostsManageError, _locked_state, _new_file, _open_parent, _read_owned,
    _read_source, _sha,
)
from ach_customizer_state import DATA_DIR, _open_state_dir

PROGRESS = "/tmp/wp_aapanel_deploy.log"
LOCK = "/tmp/wp_aapanel_deploy.lock"
BATCH_LOCK = "/tmp/wp_batch_aapanel_deploy.lock"
HOSTS = "/etc/hosts"
NATIVE_SOURCE = "/www/server/panel/class_v2/one_key_wp_v2.py"
NATIVE_SITE_SOURCE = "/www/server/panel/class_v2/panel_site_v2.py"
# Verified aaPanel 8.0.7 source cohorts. Keep writer/lifecycle hashes paired:
# independently updated files cannot be mixed to authorize native mutation.
NATIVE_WRITER_SHA_PAIRS = frozenset({
    ("7578c279424f0b653c0f65ca2f22fbf0b86ce873673b05939e4b4b16c6713bf8",
     "b75a5a0b45c319df7eb49381363d3c3e90208157ebfd88de6f9b173d013d98fb"),
    ("baac86fed3328182e1c99c823e2bcc274c0e902f0db16a8fe2fc16fceb4874ce",
     "9696e3114a79587b78344bb2a661eac2555eb1227cf8da4c1ae8fa5b16283e92"),
})
NATIVE_META = "/www/server/panel/class/common.py"
# Advertise the loaded Python module's actual safety/diagnostic contract,
# not a fresh on-disk version which may hide stale aaPanel worker imports.
MANUAL_REVIEW_CONTRACT = "durable-manual-review-v3"
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
    if ((_sha(raw), _sha(handler)) not in NATIVE_WRITER_SHA_PAIRS
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
            "last_reason": "Disabled",
            "last_worker": {"state": "Not Observed", "stage": "idle",
                            "reason": "No native event evaluated", "operation_id": None}}


def _validate(row):
    default = _default()
    if (not isinstance(row, dict) or set(row) != set(default)
            or type(row["schema"]) is not int or row["schema"] != 1
            or type(row["revision"]) is not int or not 0 <= row["revision"] <= 2147483647
            or type(row["enabled"]) is not bool
            or type(row["enabled_ns"]) is not int or row["enabled_ns"] < 0
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


def _publish_manual_review_noreplace(fd, staging, canonical):
    """Atomically publish one already-fsynced inode with no overwrite.

    Linux renameat2(RENAME_NOREPLACE) moves the staging name rather than
    creating a second hard link. A SIGKILL at any point leaves either an
    ignored private stage or a readable canonical file with st_nlink=1.
    Never fall back to rename(2), which would replace evidence.
    """
    import ctypes
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise TerminalError("Atomic no-clobber manual-review publication unavailable") from exc
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                          ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(fd, os.fsencode(staging), fd, os.fsencode(canonical), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), canonical)


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
        # Write and fsync a unique private staging inode FIRST, then use
        # Linux atomic RENAME_NOREPLACE. No canonical truncation, overwrite,
        # or post-publish hard-link window (st_nlink must remain exactly 1).
        staging = "." + name + "." + uuid4().hex + ".tmp"
        try:
            _new_file(fd, staging, payload)
            try:
                _publish_manual_review_noreplace(fd, staging, name)
            except FileExistsError:
                previous = _read_manual_review(fd, operation)
                if (previous["event"]["target"] != row["event"]["target"]
                        or previous["event"]["detail"] != row["event"]["detail"]):
                    raise TerminalError("Conflicting native WP manual-review ownership")
            # Commit the newly published canonical directory entry before
            # the caller may advance the terminal token.
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
        # Never expose a private Hosts baseline or vendor progress payload.
        manual_rows, incomplete = _scan_manual_reviews(fd)
        latest = manual_rows[0] if manual_rows else None
        manual_review = ({
            "operation_id": latest["event"]["operation_id"],
            "domain": latest["event"]["target"],
            "activity_delivered": latest["delivered"],
        } if latest else None)
        return {key: value[key] for key in ("enabled", "revision", "last_reason", "last_worker")} | {
            "manual_review": manual_review,
            "manual_review_count": len(manual_rows),
            "manual_review_integrity": {
                "state": "Needs Review" if incomplete else "Complete",
                "incomplete_count": len(incomplete),
                "first_operation_id": incomplete[0] if incomplete else None,
            },
            "active_domain": value["active"]["domain"] if value["active"] else None,
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
    review_states = ("Needs Review", "Manual Review Required")
    if policy["last_worker"] != observed:
        policy["last_worker"] = observed
        if state in review_states:
            policy["last_reason"] = reason
        _save(fd, policy)
        if state == "Needs Review":
            try:
                from ach_customizer_activity import append_activity, record
                entry = record(
                    level="WARNING", module="lifecycle", action="wp_terminal_refused",
                    operation_id=operation or uuid4().hex,
                    stage=stage, outcome=state, target=domain,
                    detail=reason, recovery_id="")
                append_activity(data_dir, entry)
            except Exception:
                import logging
                logging.getLogger("ach_customizer").exception(
                    "Native WP operational refusal Activity persistence failed")
        # Manual Review Required has its own immutable evidence file. Generic
        # Activity is a recoverable projection, never the sole domain identity.
    return {"state": state, "changed": False,
            **({"reason": reason} if state in review_states else {})}


def _baseline_name(operation):
    return "ach_customizer.wp-terminal." + operation + ".before"


def _release_unused_baseline(fd, operation):
    """Clear the temporary read-only witness baseline after completion."""
    name = _baseline_name(operation)
    stored = _read_owned(fd, name, max_bytes=65536)
    if stored is None:
        return
    os.unlink(name, dir_fd=fd)
    os.fsync(fd)


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
                "reason": reason}


def _hostname_alias(line, domain):
    """Conservative: any pre-existing alias token prevents automatic deletion."""
    try:
        active = line.split(b"#", 1)[0].split()
        return domain.encode("ascii").lower() in (item.lower() for item in active[1:])
    except Exception:
        return True


def recheck_witness(*, data_dir=DATA_DIR, progress_path=PROGRESS):
    """Reconcile a current read-only witness after a confirmed native terminal.

    No old auto-Hosts cleanup journals are read, adopted or rewritten. Hosts
    remains untouched; the local baseline is only released after a matching
    terminal progress record has been independently inspected.
    """
    with _locked_state(data_dir) as fd:
        policy = _load(fd)
        active = policy["active"]
        if os.path.lexists(LOCK) or os.path.lexists(BATCH_LOCK):
            return {"state": "Active or Unknown", "changed": False}
        if active is None:
            return {"state": "No Witness", "changed": False}
        try:
            progress = _progress(progress_path)
        except (OSError, TerminalError):
            return {"state": "Needs Review", "changed": False}
        if (progress["status"] != 1 or progress["domain"] != active["domain"]
                or progress["ino"] != active["ino"] or progress["dev"] != active["dev"]
                or progress["mtime_ns"] <= active["started_ns"]):
            return {"state": "Active or Unknown", "changed": False}
        policy["active"] = None
        policy["last_token"] = progress["token"]
        policy["last_reason"] = "Native setup ended; witnessed Hosts source was never modified"
        _save(fd, policy)
        _release_unused_baseline(fd, active["operation"])
        return {"state": "No Repair Pending", "changed": False}


def abandon_witness(*, data_dir=DATA_DIR):
    """Operator-approved, no-Hosts-write witness discard after lost progress.

    First disable the policy; a missing progress record alone does not
    authorize discarding an active native WordPress setup witness.
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
        policy["active"] = None
        policy["last_reason"] = "Operator abandoned unverified stale WP witness; no Hosts edit"
        _save(fd, policy)
        _release_unused_baseline(fd, active["operation"])
        return {"state": "Witness Abandoned", "changed": False,
                "operation_id": active["operation"]}


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
