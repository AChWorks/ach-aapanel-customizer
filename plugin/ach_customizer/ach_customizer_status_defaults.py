"""Guarded aaPanel *new-site source* defaults; not a live Nginx error route.

aaPanel 8.0.7 copies defaultDoc.html, 404.html and 502.html into newly
created document roots. Changing these files never edits existing websites.
Original bytes and permissions are retained outside the replaceable plugin.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from uuid import uuid4

from ach_customizer_status_inspect import _directory
from ach_customizer_status_extension import _bounded_file, _owned_dir, _write_exclusive
from ach_customizer_status_pages import StatusPageError

SOURCE_ROOT = "/www/server/panel/data"
TEMPLATES = {"new-site": "defaultDoc.html", "404": "404.html", "502": "502.html"}
MAX_SOURCE = 64 * 1024
MAX_RECORD = 2048
HASH = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[0-9a-f]{32}\Z")


class DefaultSourceError(StatusPageError):
    def __init__(self, stage, message, recovery_id=None):
        self.stage = stage
        self.recovery_id = recovery_id if (isinstance(recovery_id, str) and
                                            ID.fullmatch(recovery_id)) else None
        super().__init__(message)


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _journal_name(template):
    return "ach_customizer.status_default." + template + ".json"


def _backup_name(template, operation_id):
    return "ach_customizer.status_default." + template + "." + operation_id + ".backup"


def _open_source(directory):
    fd = _directory(str(directory))
    try:
        _owned_dir(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _source(fd, filename):
    payload = _bounded_file(fd, filename, limit=MAX_SOURCE)
    if payload is None:
        raise DefaultSourceError("source", "Native aaPanel new-site default is missing")
    info = os.stat(filename, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
        raise DefaultSourceError("ownership", "Native new-site source has untrusted ownership")
    return payload, stat.S_IMODE(info.st_mode)


def _record_read(data_fd, template):
    payload = _bounded_file(data_fd, _journal_name(template),
                            limit=MAX_RECORD, permissions=0o600)
    if payload is None:
        return None
    try:
        record = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise DefaultSourceError("recovery", "Saved new-site default recovery record is invalid") from exc
    if (not isinstance(record, dict) or
            set(record) != {"schema", "template", "operation_id", "phase",
                            "before_sha256", "after_sha256", "backup", "before_mode"} or
            type(record["schema"]) is not int or record["schema"] != 1 or
            record["template"] != template or
            record["phase"] not in ("prepared", "applied", "restored") or
            not isinstance(record["operation_id"], str) or
            not ID.fullmatch(record["operation_id"]) or
            any(not isinstance(record[name], str) or not HASH.fullmatch(record[name])
                for name in ("before_sha256", "after_sha256")) or
            record["backup"] != _backup_name(template, record["operation_id"]) or
            type(record["before_mode"]) is not int or
            not 0 < record["before_mode"] <= 0o777 or
            record["before_mode"] & 0o022):
        raise DefaultSourceError("recovery", "Saved new-site default recovery identity is invalid")
    return record


def _record_write(fd, template, record):
    payload = (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise DefaultSourceError("recovery", "New-site default recovery record is too large")
    tmp = "." + _journal_name(template) + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, tmp, payload, 0o600)
    os.replace(tmp, _journal_name(template), src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _backup(data_fd, record):
    raw = _bounded_file(data_fd, record["backup"], limit=MAX_SOURCE, permissions=0o600)
    if raw is None or _sha(raw) != record["before_sha256"]:
        raise DefaultSourceError("recovery", "Verified original new-site source backup is unavailable",
                                 record["operation_id"])
    return raw


def _publish(source_fd, source_name, payload, mode, op, source_expected, source_root):
    """Atomically publish complete bytes; never a partially copied template."""
    stage = "." + source_name + "." + op + ".stage"
    prior_stage = _bounded_file(source_fd, stage, limit=MAX_SOURCE)
    if prior_stage is None:
        _write_exclusive(source_fd, stage, payload, mode)
    elif prior_stage != payload:
        raise DefaultSourceError("publication", "Existing staged source is not the saved render", op)
    staged = _bounded_file(source_fd, stage, limit=MAX_SOURCE)
    staged_mode = stat.S_IMODE(os.stat(stage, dir_fd=source_fd, follow_symlinks=False).st_mode)
    if staged != payload or staged_mode != mode:
        raise DefaultSourceError("publication", "Staged default differs from selected render", op)
    # The aaPanel template directory must still be at the original pathname.
    renewed = _open_source(source_root)
    try:
        if (os.fstat(renewed).st_dev, os.fstat(renewed).st_ino) != (
                os.fstat(source_fd).st_dev, os.fstat(source_fd).st_ino):
            raise DefaultSourceError("concurrency", "Native aaPanel default directory changed", op)
        current, current_mode = _source(renewed, source_name)
        if current != source_expected or current_mode != mode:
            raise DefaultSourceError("concurrency", "Native aaPanel default changed; recheck", op)
        os.replace(stage, source_name, src_dir_fd=source_fd, dst_dir_fd=source_fd)
        os.fsync(source_fd)
    finally:
        os.close(renewed)
    actual, actual_mode = _source(source_fd, source_name)
    if actual != payload or actual_mode != mode:
        raise DefaultSourceError("uncertain", "New-site default publication unconfirmed; recheck", op)


def manage_default(action, template, html, *,
                   data_fd, expected_current=None, expected_render=None,
                   expected_recovery=None, source_root=None):
    """Recheck, Apply or Restore exactly one aaPanel new-site template source.

    Caller holds the shared Status Pages settings lock and authorizes mutation.
    New site creation will copy these bytes; existing sites are never changed.
    """
    if action not in ("recheck", "apply", "restore") or template not in TEMPLATES:
        raise DefaultSourceError("identity", "Unsupported new-site default operation")
    if not isinstance(html, str):
        raise DefaultSourceError("render", "Selected status render is invalid")
    payload = html.encode("utf-8")
    if not 0 < len(payload) <= MAX_SOURCE:
        raise DefaultSourceError("render", "Selected HTML exceeds native template size")
    target = TEMPLATES[template]
    proposed_sha = _sha(payload)
    source_root = SOURCE_ROOT if source_root is None else source_root
    source_fd = _open_source(source_root)
    try:
        current, mode = _source(source_fd, target)
        current_sha = _sha(current)
        record = _record_read(data_fd, template)
        if record is not None and record["phase"] != "restored":
            _backup(data_fd, record)
        if action == "recheck":
            if record is None:
                state = "Already Current" if current_sha == proposed_sha else "Source Ready"
            elif record["phase"] == "restored":
                state = "Restored" if current_sha == record["before_sha256"] else "Drift"
            elif current_sha not in (record["before_sha256"], record["after_sha256"]):
                state = "Drift"
            elif record["phase"] == "prepared":
                state = "Recovery Required"
            else:
                state = "Applied" if current_sha == record["after_sha256"] else "Recovery Required"
            return _response(state, template, target, current_sha, proposed_sha,
                             record, False, True)

        if action == "apply":
            if not isinstance(expected_current, str) or expected_current != current_sha:
                raise DefaultSourceError("concurrency", "Native source changed; Recheck before Apply")
            if expected_render != proposed_sha:
                raise DefaultSourceError("render", "Selected Status Pages preview changed")
            if record is not None and record["phase"] in ("prepared", "applied"):
                if record["phase"] == "applied" and current_sha == record["after_sha256"] \
                        and proposed_sha == current_sha:
                    return _response("Already Applied", template, target, current_sha,
                                     proposed_sha, record, False, False)
                raise DefaultSourceError("recovery", "Restore previous managed default before a new Apply",
                                         record["operation_id"])
            if current_sha == proposed_sha:
                return _response("Already Current", template, target, current_sha,
                                 proposed_sha, None, False, False)
            previous_backup = None
            if record is not None:
                if current_sha != record["before_sha256"]:
                    raise DefaultSourceError("concurrency", "Previously restored default has drifted")
                old = _bounded_file(data_fd, record["backup"], limit=MAX_SOURCE,
                                    permissions=0o600)
                if old is not None and _sha(old) != record["before_sha256"]:
                    raise DefaultSourceError("recovery", "Previous backup has changed")
                # Never retire the previous recovery evidence before the
                # replacement operation has been committed successfully.
                previous_backup = record["backup"] if old is not None else None
            op = uuid4().hex
            record = {"schema": 1, "template": template, "operation_id": op,
                      "phase": "prepared", "before_sha256": current_sha,
                      "after_sha256": proposed_sha,
                      "backup": _backup_name(template, op), "before_mode": mode}
            try:
                _write_exclusive(data_fd, record["backup"], current, 0o600)
                _record_write(data_fd, template, record)
                _publish(source_fd, target, payload, mode, op, current, source_root)
                record["phase"] = "applied"
                _record_write(data_fd, template, record)
            except Exception as exc:
                raise DefaultSourceError(
                    "uncertain", "New-site default Apply unconfirmed; Recheck recovery before retry",
                    op) from exc
            if previous_backup is not None:
                try:
                    os.unlink(previous_backup, dir_fd=data_fd)
                    os.fsync(data_fd)
                except OSError:
                    # Cleanup is not part of an already confirmed Apply.
                    # Keeping an obsolete, safely named backup is preferable
                    # to reporting a false write failure and blind retries.
                    pass
            return _response("Applied", template, target, proposed_sha, proposed_sha,
                             record, True, False)

        if record is None or record["phase"] == "restored":
            raise DefaultSourceError("recovery", "No active managed default to Restore")
        if expected_recovery != record["operation_id"]:
            raise DefaultSourceError("concurrency", "Recovery identity changed; Recheck first")
        if current_sha not in (record["before_sha256"], record["after_sha256"]):
            raise DefaultSourceError("concurrency", "Native source drifted; no overwrite permitted",
                                     record["operation_id"])
        prior = _backup(data_fd, record)
        if mode != record["before_mode"]:
            raise DefaultSourceError("concurrency", "Native source permissions changed; no overwrite",
                                     record["operation_id"])
        changed = current_sha != record["before_sha256"]
        try:
            if changed:
                _publish(source_fd, target, prior, mode, record["operation_id"],
                         current, source_root)
            record["phase"] = "restored"
            _record_write(data_fd, template, record)
        except Exception as exc:
            raise DefaultSourceError(
                "uncertain", "New-site default Restore unconfirmed; Recheck recovery before retry",
                record["operation_id"]) from exc
        return _response("Restored", template, target, _sha(prior), proposed_sha,
                         record, changed, False)
    finally:
        os.close(source_fd)


def _response(state, template, filename, current_sha, selected_sha, record, changed, read_only):
    return {
        "schema": 1, "mode": "native_new_site_sources", "state": state,
        "template": template, "source_file": filename,
        "current_sha256": current_sha, "rendered_sha256": selected_sha,
        "before_sha256": record["before_sha256"] if record else None,
        "after_sha256": record["after_sha256"] if record else None,
        "recovery_id": record["operation_id"] if record else None,
        "changed": changed, "read_only": read_only, "runtime_verified": False,
        "impact": "New sites only; does not change existing sites or live Nginx routing",
    }
