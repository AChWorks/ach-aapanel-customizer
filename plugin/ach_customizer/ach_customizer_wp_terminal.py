"""Opt-in, fail-closed native WP Toolkit terminal witness and exact Hosts repair.

Only aaPanel 8.0.7's verified asynchronous single-site WP2 writer is supported.
The event-driven worker must observe an *active* progress record and an absent
alias before it will consider an exact, newly appended vendor record on failure.
No general-purpose /etc/hosts cleanup, foreign site recovery or polling exists.
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
    _read_source, _replace_source, _sha,
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
STATE_FILE = "ach_customizer.wp-terminal.json"
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
            "last_recovery": None, "last_reason": "Disabled", "recoveries": 0}


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
        return {key: value[key] for key in ("enabled", "revision", "last_reason", "recoveries")} | {
            "last_recovery": recovery_id,
            "active_domain": value["active"]["domain"] if value["active"] else None,
            "last_recovery_state": recovery_state,
            "scope": "failed_native_single_site_wp_toolkit", "auto_hosts": value["enabled"],
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
               "last_reason": "Armed for future native WP Toolkit events" if enabled else "Disabled"}
        _save(fd, row)
    return inspect(data_dir=data_dir)


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
            or row["phase"] not in ("prepared", "applied", "restored", "not_applied")
            or any(not isinstance(row[k], str) or not SHA.fullmatch(row[k]) for k in ("before_sha", "after_sha"))
            or _hostname(row["domain"]) != row["domain"]):
        raise TerminalError("Invalid WordPress recovery ownership")
    return row


def _source_payload(path):
    parent = _open_parent(path)
    try:
        return _read_source(parent)[0]
    finally:
        os.close(parent)


def process_event(*, data_dir=DATA_DIR, hosts_path=HOSTS, progress_path=PROGRESS,
                  native_source=NATIVE_SOURCE, now_ns=None):
    """Handle one filesystem notification. No automatic retries of uncertain edits."""
    now_ns = time.time_ns() if now_ns is None else now_ns
    with _locked_state(data_dir) as fd:
        policy = _load(fd)
        if not policy["enabled"]:
            return {"state": "Disabled", "changed": False}
        try:
            progress = _progress(progress_path)
        except (OSError, TerminalError) as exc:
            return {"state": "Needs Review", "changed": False, "reason": str(exc)}
        # A completed operation not seen while active is not an authorization.
        # Record its event ID read-only, avoiding repeated vendor-source scans.
        if progress["status"] == 1 and policy["active"] is None:
            if policy["last_token"] != progress["token"]:
                policy["last_token"] = progress["token"]
                policy["last_reason"] = "Native WP terminal without a preceding witness; no edit"
                _save(fd, policy)
            return {"state": "No Witness", "changed": False}
        try:
            _native_supported(native_source)
        except (OSError, TerminalError) as exc:
            return {"state": "Needs Review", "changed": False, "reason": str(exc)}
        if (os.path.lexists(BATCH_LOCK) or
                (progress["status"] == 1 and os.path.lexists(LOCK))):
            return {"state": "Active or Unknown", "changed": False}
        active = policy["active"]
        if progress["status"] == 0:
            if active is not None:
                return {"state": "Witness Active", "changed": False}
            if (not os.path.lexists(LOCK) or progress["mtime_ns"] + 1_000_000_000 < policy["enabled_ns"]
                    or abs(now_ns - progress["mtime_ns"]) > MAX_AGE_NS
                    or progress["steps"][3] not in (0, 2) or policy["recoveries"] >= MAX_RECOVERIES):
                return {"state": "Active or Unknown", "changed": False}
            baseline = _source_payload(hosts_path)
            domain = progress["domain"]
            # A mapping that existed before the task is never vendor-owned.
            if any(_hostname_alias(line, domain) for line in baseline.splitlines()):
                return {"state": "Intentional Alias Possible", "changed": False}
            operation = uuid4().hex
            _new_file(fd, _baseline_name(operation), baseline)
            os.fsync(fd)
            policy["active"] = {"operation": operation, "domain": domain,
                                "dev": progress["dev"], "ino": progress["ino"],
                                "started_ns": progress["mtime_ns"], "source_sha": _sha(baseline)}
            policy["last_reason"] = "Native WP setup observed before any local alias"
            _save(fd, policy)
            return {"state": "Witness Armed", "changed": False, "domain": domain}
        if active is None:
            return {"state": "No Witness", "changed": False}
        if (progress["domain"] != active["domain"] or progress["dev"] != active["dev"]
                or progress["ino"] != active["ino"] or progress["mtime_ns"] <= active["started_ns"]
                or abs(now_ns - progress["mtime_ns"]) > MAX_AGE_NS
                or progress["mtime_ns"] - active["started_ns"] > MAX_AGE_NS
                or os.path.lexists(LOCK)):
            return {"state": "Active or Unknown", "changed": False}
        if policy["last_token"] == progress["token"]:
            return {"state": "Already Observed", "changed": False}
        if progress["steps"] == [1, 1, 1, 1]:
            reason, state = "Native WP Toolkit succeeded; vendor owns its cleanup", "Success"
            changed = False
        elif progress["steps"] == [1, 1, 1, -1]:
            old = _read_owned(fd, _baseline_name(active["operation"]), required=True)
            if _sha(old) != active["source_sha"]:
                raise TerminalError("WordPress witness baseline checksum mismatch")
            marker = b"\n127.0.0.1 " + active["domain"].encode("ascii")
            if _read_owned(fd, _recovery_name(active["operation"]), max_bytes=4096) is not None:
                return {"state": "Recovery Required", "changed": False,
                        "recovery_id": active["operation"]}
            parent = _open_parent(hosts_path)
            try:
                current, meta = _read_source(parent)
                if current != old + marker:
                    reason, state, changed = "Hosts no longer matches the exact vendor append; no rewrite", "Needs Review", False
                else:
                    # Guard the terminal and effective policy again before the CAS.
                    if not _load(fd)["enabled"] or os.path.lexists(LOCK) or os.path.lexists(BATCH_LOCK):
                        return {"state": "Active or Unknown", "changed": False}
                    operation = active["operation"]
                    record = {"schema": 1, "operation": operation, "domain": active["domain"],
                              "phase": "prepared", "before_sha": _sha(current), "after_sha": _sha(old),
                              "backup": _baseline_name(operation)}
                    _save_recovery(fd, record)
                    _replace_source(parent, old, meta, expected_sha=_sha(current), recovery_id=operation)
                    record["phase"] = "applied"
                    _save_recovery(fd, record)
                    policy["last_recovery"] = operation
                    policy["recoveries"] += 1
                    reason, state, changed = "Exact failed native WP temporary alias removed", "Alias Removed", True
            finally:
                os.close(parent)
        else:
            reason, state, changed = "Native WP result is not an eligible terminal install", "Needs Review", False
        policy["active"] = None
        policy["last_token"] = progress["token"]
        policy["last_reason"] = reason
        _save(fd, policy)
        if not changed:
            _release_unused_baseline(fd, active["operation"])
        if changed or state == "Needs Review":
            try:
                from ach_customizer_activity import append_activity, record
                event = record(
                    level="WARNING", module="lifecycle", action="wp_terminal_auto",
                    operation_id=active["operation"], stage="native_wp_terminal",
                    outcome=state, target=active["domain"],
                    detail=reason, recovery_id=active["operation"] if changed else "")
                append_activity(data_dir, event)
            except Exception:
                # Recovery and source outcome are already persisted: an Activity
                # failure cannot justify a second edit or an automatic retry.
                import logging
                logging.getLogger("ach_customizer").exception("Native WP terminal Activity persistence failed")
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
        if record["phase"] != "prepared":
            return {"state": record["phase"], "changed": False, "recovery_id": recovery_id}
        baseline = _read_owned(fd, record["backup"], required=True)
        if _sha(baseline) != record["after_sha"]:
            raise TerminalError("Interrupted recovery backup is not trustworthy")
        current = _source_payload(hosts_path)
        if _sha(current) == record["after_sha"]:
            record["phase"] = "applied"
            policy["last_recovery"] = recovery_id
            policy["recoveries"] += 1
            reason = "Interrupted edit verified as applied; guarded Restore available"
            state = "applied"
        elif _sha(current) == record["before_sha"]:
            record["phase"] = "not_applied"
            reason = "Interrupted edit verified as not applied"
            state = "not_applied"
        else:
            return {"state": "Needs Review", "changed": False, "recovery_id": recovery_id,
                    "reason": "Hosts differs from both saved versions"}
        _save_recovery(fd, record)
        policy["active"] = None
        policy["last_reason"] = reason
        _save(fd, policy)
        return {"state": state, "changed": False, "recovery_id": recovery_id,
                "reason": reason}


def abandon_witness(*, data_dir=DATA_DIR):
    """Operator-approved, no-Hosts-write recovery after missed/replaced progress.

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
            return {"state": "No Witness", "changed": False}
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
            _replace_source(parent, restored, meta, expected_sha=_sha(current), recovery_id=operation)
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
