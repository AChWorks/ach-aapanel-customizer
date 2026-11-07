"""Native-aaPanel-only manual shared PHP-FPM flow; never auto-enforce.

aaPanel's ordinary authenticated plugin route provides native CSRF checks;
each privileged method independently enforces a full primary-admin POST.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import ach_customizer_fpm_apply as recovery
from ach_customizer_state import (
    DATA_DIR, parse_revision, read_state, _open_state_dir, _exclusive_lock,
)

CONFIG_ROOT = "/www/server/php"
SUPPORTED_PANEL = "8.0.7"
APPROVAL_SCOPE = "PHP85-www-shared-service"  # Existing PHP85 approval contract.


def _approval_scope(version):
    if version not in recovery.SUPPORTED_VERSIONS:
        raise recovery.FpmApplyError("fpm_compatibility", "Unsupported PHP-FPM manual adapter")
    return "PHP" + version + "-www-shared-service"


def _arg(args, key, default=None):
    if isinstance(args, dict):
        return args.get(key, default)
    return getattr(args, key, default)


def _full_primary_admin_post():
    from flask import has_request_context, request, session
    if (not has_request_context() or request.method != "POST"
            or session.get("login") is not True
            or type(session.get("uid")) is not int or session["uid"] != 1
            or bool(session.get("tmp_login"))
            or "tmp_login_id" in session or "tmp_login_expire" in session):
        raise recovery.FpmApplyError(
            "fpm_authorization", "Full primary aaPanel administrator POST is required"
        )


def _run(argv, *, timeout):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise recovery.FpmApplyError(
            "fpm_runtime", "Versioned PHP-FPM operation failed: " + Path(argv[0]).name
        )
    return (proc.stdout + proc.stderr)[-24000:]


def _live_values(dump):
    values = {}
    for name in recovery.POOL_KEYS:
        matches = re.findall(r"\b" + re.escape(name) + r"\s*=\s*(\d+)(?=\s|$)", dump)
        if len(matches) != 1:
            raise recovery.FpmApplyError("fpm_runtime", "Cannot verify PHP-FPM setting " + name)
        values[name] = int(matches[0])
    return values


def _default_runtime_hooks(config_root, version, desired=None):
    if version not in recovery.SUPPORTED_VERSIONS or str(config_root) != CONFIG_ROOT:
        raise recovery.FpmApplyError("fpm_compatibility", "Unsupported PHP-FPM service target")
    binary = Path(CONFIG_ROOT) / version / "sbin/php-fpm"
    service = Path("/etc/init.d/php-fpm-" + version)
    pidfile = Path(CONFIG_ROOT) / version / "var/run/php-fpm.pid"
    socket = Path("/tmp/php-cgi-" + version + ".sock")
    if (not binary.is_file() or binary.is_symlink() or not service.is_file()
            or service.is_symlink() or binary.stat().st_uid != 0
            or service.stat().st_uid != 0 or binary.stat().st_mode & 0o022
            or service.stat().st_mode & 0o022):
        raise recovery.FpmApplyError("fpm_compatibility", "Unsupported FPM binary/service ownership")
    # The same exact source-to-hook contract applies before Apply, and again
    # before invoking recovery hooks; neither may trust an unrelated socket.
    recovery.require_native_runtime_paths(config_root, version)
    expected = recovery.expected_pool_values(desired) if desired is not None else None

    def validate():
        _run([str(binary), "-t"], timeout=15)

    def activate():
        _run([str(service), "reload"], timeout=30)

    def verify():
        dump = _run([str(binary), "-tt"], timeout=15)
        values = _live_values(dump)
        if expected is not None and values != expected:
            raise recovery.FpmApplyError("fpm_runtime", "Reloaded FPM policy differs from desired settings")
        if pidfile.is_symlink() or not pidfile.is_file():
            raise recovery.FpmApplyError("fpm_runtime", "PHP-FPM master PID is unavailable")
        pid_text = pidfile.read_text().strip()
        if not re.fullmatch("[0-9]{1,10}", pid_text) or int(pid_text) <= 1:
            raise recovery.FpmApplyError("fpm_runtime", "Invalid PHP-FPM master PID")
        pid = int(pid_text)
        os.kill(pid, 0)
        if not socket.exists() or not stat.S_ISSOCK(socket.lstat().st_mode):
            raise recovery.FpmApplyError("fpm_runtime", "PHP-FPM Unix socket is missing")
    return validate, activate, verify


class ManualFpmWorkflow:
    def __init__(self, *, public=None, impact_lookup=None, config_root=CONFIG_ROOT,
                 data_dir=DATA_DIR, state_reader=None, hooks_factory=None):
        self.public = public
        self.impact_lookup = impact_lookup
        self.config_root = config_root
        self.data_dir = data_dir
        self.state_reader = state_reader or (lambda: read_state(self.data_dir))
        self.hooks_factory = hooks_factory or (lambda version, desired: _default_runtime_hooks(
            self.config_root, version, desired))

    def _environment(self, version):
        if version not in recovery.SUPPORTED_VERSIONS:
            raise recovery.FpmApplyError("fpm_compatibility", "Only PHP 8.1 and 8.5 have verified manual adapters")
        panel = self.public
        if panel is None:
            import public
            panel = public
        if panel.get_panel_version() != SUPPORTED_PANEL or panel.get_webserver() != "nginx":
            raise recovery.FpmApplyError(
                "fpm_compatibility", "Manual Apply requires verified aaPanel 8.0.7 + Nginx"
            )
        return panel

    def _state(self):
        state = self.state_reader()
        if not state["enabled"] or not state["modules"]["php_fpm_file_preview"]:
            raise recovery.FpmApplyError("fpm_monitor", "PHP-FPM Monitor must be enabled for Apply")
        return state

    def _desired(self, args):
        return {
            "pm.max_children":_arg(args,"max_children"),
            "pm.start_servers":_arg(args,"start_servers"),
            "pm.min_spare_servers":_arg(args,"min_spare_servers"),
            "pm.max_spare_servers":_arg(args,"max_spare_servers"),
            "pm.max_requests":_arg(args,"max_requests"),
        }

    def _lookup_impact(self, panel, plan):
        lookup = self.impact_lookup
        if lookup is None:
            try:
                from ach_customizer_monitor import inspect_php_fpm_site_impact
            except ImportError as exc:
                raise recovery.FpmApplyError(
                    "fpm_compatibility", "Site-to-pool attribution adapter is not installed"
                ) from exc
            lookup = inspect_php_fpm_site_impact
        return lookup(panel, plan["version"], plan["source"])

    def _impact(self, panel, plan, *, observed=None):
        impact = observed if observed is not None else self._lookup_impact(panel, plan)
        if (not isinstance(impact, dict) or impact.get("state") != "File Mapping"
                or impact.get("manual_apply_eligible") is not True
                or impact.get("schema") != 1 or impact.get("version") != plan["version"]
                or impact.get("scope") != "shared_service"
                or impact.get("unresolved_sites") != []
                or not isinstance(impact.get("matched_sites"), list)
                or not impact["matched_sites"]
                or type(impact.get("site_count")) is not int
                or not 1 <= impact["site_count"] <= 100
                or not 1 <= len(impact["matched_sites"]) <= impact["site_count"]
                or type(impact.get("other_php_sites_count")) is not int
                or impact["other_php_sites_count"] < 0
                or impact["site_count"] != (
                    len(impact["matched_sites"]) + impact["other_php_sites_count"])
                or not isinstance(impact.get("dependency_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", impact["dependency_sha256"])):
            raise recovery.FpmApplyError("fpm_impact", "Native shared-pool site attribution needs review")
        ids = set()
        for item in impact["matched_sites"]:
            if (not isinstance(item, dict) or type(item.get("id")) is not int
                    or item["id"] <= 0 or item["id"] in ids
                    or not isinstance(item.get("site_key"), str)
                    or not 1 <= len(item["site_key"]) <= 255
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", item["site_key"])):
                raise recovery.FpmApplyError("fpm_impact", "Invalid shared-pool site identity")
            ids.add(item["id"])
        identity = {
            "version":plan["version"], "site_count":impact["site_count"],
            "manual_apply_eligible": impact["manual_apply_eligible"],
            "matched_sites":impact["matched_sites"],
            "other_php_sites_count":impact.get("other_php_sites_count"),
            "dependency_sha256":impact["dependency_sha256"],
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":")).encode("utf-8")).hexdigest()
        return impact, digest

    def _prepare(self, args):
        version = _arg(args, "php_version")
        panel = self._environment(version)
        state = self._state()
        plan = recovery.preview(self.config_root, version, self._desired(args))
        impact, digest = self._impact(panel, plan)
        return {"plan":plan, "shared_impact":impact, "impact_sha256":digest,
                "monitor_revision":state["revision"],
                "approval_scope":_approval_scope(version),
                "warning":"Changes the PHP " + version + " www shared pool; all consumers may be affected, including non-aaPanel applications."}

    def prepare(self, args):
        _full_primary_admin_post()
        return self._prepare(args)

    def apply(self, args):
        _full_primary_admin_post()
        version = _arg(args, "php_version")
        if _arg(args, "approved_scope") != _approval_scope(version):
            raise recovery.FpmApplyError("fpm_approval", "Explicit shared-service approval is required")
        current = self._prepare(args)
        plan = current["plan"]
        if (parse_revision(_arg(args, "expected_revision")) != current["monitor_revision"]
                or _arg(args, "expected_before") != plan["before_sha256"]
                or _arg(args, "expected_after") != plan["after_sha256"]
                or _arg(args, "expected_impact") != current["impact_sha256"]):
            raise recovery.FpmApplyError("fpm_conflict", "Manual Apply preview is stale")
        validate, activate, verify = self.hooks_factory(version, plan["desired"])
        # Recovery verifies the ORIGINAL pool values, never the candidate's
        # values. A failed forward verification must not make a successful
        # baseline restoration look uncertain merely because it reverted.
        restored_values = dict(plan["desired"])
        for change in plan["changes"]:
            restored_values[change["setting"]] = change["actual"]
        _, _, verify_restored = self.hooks_factory(version, restored_values)
        # Serialize against persistent Monitor toggle writes: approval must
        # still match a current enabled revision while the host operation runs.
        state_fd = _open_state_dir(self.data_dir)
        try:
            state_lock = _exclusive_lock(state_fd)
            try:
                latest = self._state()
                if latest["revision"] != current["monitor_revision"]:
                    raise recovery.FpmApplyError("fpm_conflict", "Monitor state changed before Apply")
                # The initial site-file mapping is only an observation. Verify
                # it once more immediately before the guarded file mutation.
                # External aaPanel updates do not honor our plugin lock, so
                # this remains a bounded best-effort precondition, not a
                # transactional site inventory or full traffic guarantee.
                _, impact_now = self._impact(self._environment(version), plan)
                if impact_now != current["impact_sha256"]:
                    raise recovery.FpmApplyError("fpm_conflict", "Shared PHP-FPM site mapping changed before Apply")
                result = recovery.apply(
                    self.config_root, self.data_dir, version, plan["desired"],
                    expected_before=plan["before_sha256"], expected_after=plan["after_sha256"],
                    validate=validate, activate=activate, verify=verify,
                    verify_restored=verify_restored)
            finally:
                os.close(state_lock)
        finally:
            os.close(state_fd)
        return {**result, "shared_impact":current["shared_impact"],
                "note":"Native FPM syntax/reload and service health checked; not proof of all client traffic."}

    def _recovery_details(self, panel, version):
        """One read-only current recovery decision, independent of Monitor mode."""
        status = recovery.recovery_status(self.config_root, self.data_dir, version)
        if not status.get("operation_id"):
            return status
        manual = ("Automatic restoration is unavailable. Recovery records remain intact. "
                  "Reinstall the plugin or use an authorized supervised recovery "
                  "procedure after inspecting current sites, FPM bytes and service health.")
        plan = {"version": version, "source": str(Path(self.config_root) / version / "etc/php-fpm.conf")}
        # Keep the saved operation visible even if a later aaPanel/source
        # change makes automatic restoration unsafe.
        try:
            recovery.require_native_runtime_paths(self.config_root, version)
        except recovery.FpmApplyError as exc:
            return {**status, "safe_rollback_file_match": False,
                    "impact_reason": str(exc), "shared_impact": None,
                    "manual_recovery": manual}
        try:
            observed = self._lookup_impact(panel, plan)
        except Exception:
            return {**status, "safe_rollback_file_match": False,
                    "impact_reason": "Current site routing cannot be inspected",
                    "shared_impact": None, "manual_recovery": manual}
        try:
            impact, digest = self._impact(panel, plan, observed=observed)
        except recovery.FpmApplyError as exc:
            return {**status, "safe_rollback_file_match": False,
                    "impact_reason": str(exc), "shared_impact": observed,
                    "manual_recovery": manual}
        result = {**status, "shared_impact": impact, "impact_sha256": digest}
        if not status["safe_rollback_file_match"]:
            return {**result, "manual_recovery": manual}
        decision = {
            "operation_id": status["operation_id"],
            "baseline_sha256": status["baseline_sha256"],
            "applied_sha256": status["applied_sha256"],
            "observed_sha256": status["observed_sha256"],
            "restoration_changes": status["restoration_changes"],
            "impact_sha256": digest,
        }
        result["recovery_decision_sha256"] = hashlib.sha256(
            json.dumps(decision, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result["warning"] = (
            "Restoring PHP " + version + " [www] reloads one shared service for the currently "
            "listed sites and possibly undiscovered consumers. File mapping does "
            "not establish full effective routing or universal site health."
        )
        return result

    def recovery(self, args):
        _full_primary_admin_post()
        version = _arg(args, "php_version", recovery.VERSION)
        panel = self._environment(version)
        return self._recovery_details(panel, version)

    def rollback(self, args):
        _full_primary_admin_post()
        version = _arg(args, "php_version", recovery.VERSION)
        panel = self._environment(version)
        if _arg(args, "approved_scope") != _approval_scope(version):
            raise recovery.FpmApplyError("fpm_approval", "Explicit shared-service recovery approval is required")
        operation_id = _arg(args, "operation_id")
        if not isinstance(operation_id, str) or not re.fullmatch("[0-9a-f]{32}", operation_id):
            raise recovery.FpmApplyError("fpm_recovery", "A valid saved operation ID is required")
        current = self._recovery_details(panel, version)
        expected_decision = _arg(args, "expected_recovery")
        expected_impact = _arg(args, "expected_impact")
        if (current.get("operation_id") != operation_id
                or current.get("safe_rollback_file_match") is not True
                or not isinstance(expected_decision, str)
                or not re.fullmatch("[0-9a-f]{64}", expected_decision)
                or expected_decision != current.get("recovery_decision_sha256")
                or expected_impact != current.get("impact_sha256")):
            raise recovery.FpmApplyError(
                "fpm_conflict", "Recovery decision or affected websites changed; inspect and approve again"
            )
        validate, activate, verify = self.hooks_factory(version, None)

        def prewrite_check():
            recovery.require_native_runtime_paths(self.config_root, version)
            latest = self._recovery_details(self._environment(version), version)
            if (latest.get("safe_rollback_file_match") is not True
                    or latest.get("recovery_decision_sha256") != expected_decision
                    or latest.get("impact_sha256") != expected_impact):
                raise recovery.FpmApplyError(
                    "fpm_conflict", "Shared-site impact or recovery file changed before Rollback"
                )

        restored = recovery.rollback(
            self.config_root, self.data_dir, version, operation_id,
            validate=validate, activate=activate, verify=verify,
            prewrite_check=prewrite_check)
        return {**restored, "version": version, "shared_impact": current["shared_impact"],
                "note": "Baseline bytes restored and FPM syntax/reload checks completed."}
