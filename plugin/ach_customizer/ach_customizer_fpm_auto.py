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
                                                   "baseline_sha256", "domain"}
                     or type(profile["active"]["dev"]) is not int
                     or type(profile["active"]["ino"]) is not int
                     or type(profile["active"]["started_ns"]) is not int
                     or profile["active"]["started_ns"] < 0
                     or not isinstance(profile["active"]["baseline_sha256"], str)
                     or not DIGEST.fullmatch(profile["active"]["baseline_sha256"])
                     or not isinstance(profile["active"]["domain"], str)
                     or len(profile["active"]["domain"]) > 253))):
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


def inspect(version, *, data_dir=DATA_DIR):
    if version not in recovery.SUPPORTED_VERSIONS:
        raise FpmAutoError("Only verified PHP 8.1 and 8.5 have automated adapters")
    fd = _open_state_dir(data_dir)
    try:
        store = _read(fd)
        profile = store["profiles"].get(version)
        return {"version": version, "scope": "shared_service", "schema": 1,
                "state_revision": store["revision"],
                "enabled": bool(profile and profile["enabled"]),
                "saved_policy_sha256": profile["policy_sha256"] if profile else None,
                "last_state": profile["last_state"] if profile else "Disabled",
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


def set_enabled(version, enabled, *, data_dir=DATA_DIR,
                expected_auto_revision, expected_policy_revision=None,
                reviewed=False, controller_factory=None):
    """Only a primary-admin endpoint should call this mutating helper.

    Caller must separately activate/disable the owned systemd watcher.
    Revalidation under the common Monitor lock binds saved operator intent
    and current native shared-service site attribution before enabling.
    """
    if version not in recovery.SUPPORTED_VERSIONS or type(enabled) is not bool:
        raise FpmAutoError("Invalid versioned automatic PHP control")
    if enabled and reviewed is not True:
        raise FpmAutoError("Explicit approval of automatic shared PHP service repair is required")
    revision = parse_revision(expected_auto_revision)
    policy_revision = (parse_revision(expected_policy_revision)
                       if enabled else None)
    fd = _open_state_dir(data_dir)
    try:
        lock = _exclusive_lock(fd)
        try:
            store = _read(fd)
            if store["revision"] != revision:
                raise FpmAutoError("Automatic PHP policy revision changed; inspect before retry")
            previous = store["profiles"].get(version)
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
                controller._prepare(_args(version, desired))
                fingerprint = _digest(version, desired)
                if previous and previous["enabled"] and previous["policy_sha256"] == fingerprint:
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


def run(*, data_dir=DATA_DIR, controller_factory=None, terminal_reader=None):
    """Repair only configuration drift attributable to a witnessed native task.

    A native progress start captures a trusted FPM file baseline. An exact
    later terminal identity/step can authorize reconciliation only when the
    source file changed during that witnessed window. Previous admin edits
    which predate the native task do not become an automatic write target.
    """
    fd = _open_state_dir(data_dir)
    try:
        if not any(profile["enabled"] for profile in _read(fd)["profiles"].values()):
            return {"state": "Disabled", "changed": False}
    finally:
        os.close(fd)

    reader = terminal_reader or _native_progress
    progress = reader()
    if progress is None:
        return {"state": "No verified native progress", "changed": False}
    outcomes = []
    for version in recovery.SUPPORTED_VERSIONS:
        fd = _open_state_dir(data_dir)
        try:
            lock = _exclusive_lock(fd)
            try:
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
                    # A pre-existing native v2 sidecar means this task will
                    # skip optimize_php entirely: do not infer FPM ownership.
                    if _native_opt_marker(controller.config_root, version) is not None:
                        continue
                    baseline = _file_sha(controller.config_root, version)
                    # The source writer might have completed optimization
                    # between the initial marker absence and our baseline.
                    # Do not record a false pre-change snapshot in that case.
                    if (_native_opt_marker(controller.config_root, version) is not None
                            or reader() != progress):
                        continue
                    active = {"dev": progress["dev"], "ino": progress["ino"],
                              "domain": progress["domain"], "started_ns": progress["mtime_ns"],
                              "baseline_sha256": baseline}
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
                if not changed_since_start:
                    result = {"state": "No Vendor FPM Change", "operation_id": None}
                else:
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
                        auto_policy_sha256=profile["policy_sha256"])
                updated = {**profile, "last_token": progress["token"],
                           "last_state": result["state"],
                           "last_operation": result["operation_id"],
                           "active": None}
                _save(fd, {**store, "revision": store["revision"] + 1,
                           "profiles": {**store["profiles"], version: updated}})
                outcomes.append({"version": version, "state": result["state"],
                                 "operation_id": result["operation_id"]})
            except Exception as exc:
                # An error during a host Apply retains its original recovery
                # journal and does not consume or silently discard the witness.
                stage = exc.stage if isinstance(exc, recovery.FpmApplyError) else type(exc).__name__
                try:
                    store = _read(fd)
                    previous = store["profiles"].get(version)
                    if previous and previous["enabled"]:
                        note = "Repair refused at " + str(stage)[:48]
                        _save(fd, {**store, "revision": store["revision"] + 1,
                                   "profiles": {**store["profiles"], version:
                                                {**previous, "last_state": note}}})
                except Exception:
                    pass
                raise
            finally:
                os.close(lock)
        finally:
            os.close(fd)
    return {"state": "Processed" if outcomes else "No new owned event",
            "changed": any(r["state"] == "Applied" for r in outcomes),
            "services": outcomes}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["run"]:
        print("Usage: ach_customizer_fpm_auto.py run", file=sys.stderr)
        return 2
    try:
        result = run()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print("ACh automatic FPM repair refused: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
