"""Native aaPanel plugin endpoints for Monitor and guarded manual PHP-FPM change.

Do NOT add a `_check` endpoint: aaPanel's dynamic plugin route bypasses the
ordinary inherited panel authentication boundary.
"""

import os
import sys
import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
_PANEL_CLASS_DIR = "/www/server/panel/class"
if os.path.isdir(_PANEL_CLASS_DIR) and _PANEL_CLASS_DIR not in sys.path:
    sys.path.append(_PANEL_CLASS_DIR)

from ach_customizer_activity import ActivityError, append_activity, configured_level, read_activity, record
from ach_customizer_monitor import (
    MonitorInputError, _bound_domains_for_sites,
    get_site_page, inspect_php_fpm_site_impact, preview_php_fpm,
)
from ach_customizer_hosts import (
    HostsInspectionError, inspect_local_hosts as inspect_hosts_file,
    native_site_snapshot,
)
from ach_customizer_fpm_apply import FpmApplyError
from ach_customizer_fpm_workflow import ManualFpmWorkflow
from ach_customizer_state import DATA_DIR, StateError, read_state, set_enabled
from ach_customizer_status_inspect import SUPPORTED_PAGES, inspect_site_files
from ach_customizer_status_pages import (
    DEFAULT_BRAND, BRAND_KEYS, PAGES, LOCALES, StatusPageError,
    read_preferences, render_page, select_brand, update_preferences, validate_brand,
    contrast_advisories,
)

# Worker-loaded constant: do not read fresh disk metadata at request time.
# In-place ZIP upgrades may leave old Python imports resident in aaPanel.
WORKER_SOURCE_VERSION = '0.1.115'

_STATE_DIR = DATA_DIR


class ach_customizer_main:
    @staticmethod
    def _argument(args, key, default=None):
        if isinstance(args, dict):
            return args.get(key, default)
        return getattr(args, key, default)

    @staticmethod
    def _activity_result(response, module, action, *, target="", error=None,
                         level="INFO", allow_error_detail=True, trusted_detail=None,
                         activity_stage=None):
        """Best-effort plugin diagnostics, independent of operation success."""
        correlation = response.get("request_id", response.get("operation_id"))
        try:
            failed = response.get("status") is not True
            # Log a useful controlled error, but never dump arbitrary exception
            # representations, request objects or authentication material.
            controlled = (PermissionError, StateError, StatusPageError,
                          MonitorInputError, FpmApplyError, HostsInspectionError,
                          ActivityError)
            detail = (
                str(error) if allow_error_detail and isinstance(error, controlled)
                else trusted_detail if allow_error_detail and isinstance(trusted_detail, str)
                else ""
            )
            impact = response.get("shared_impact")
            needs_review = (not failed and
                            (response.get("state") == "Needs Review" or
                             isinstance(impact, dict) and impact.get("state") == "Needs Review"))
            severity = "ERROR" if failed else "WARNING" if needs_review else level
            outcome = ("failed" if failed else "Needs Review" if needs_review else
                       response.get("state", "success"))
            # FPM's operation_id is a durable recovery identity. The Status
            # Pages manager uses a separate recovery_id; its operation_id is
            # only the request correlation, NEVER the recovery journal ID.
            cache_recovery = (module == "websites" and
                              action in ("manage_cache_policy", "cache_manage",
                                         "manage_nginx_protection", "nginx_guard_manage",
                                         "manage_abusive_scan", "abusive_scan_manage",
                                         "wp_settings_manage", "wp_settings_uncertain",
                                         "manage_wordpress_cache", "wordpress_cache_setup",
                                         "wordpress_cache_inspect", "wordpress_cache_restore",
                                         "wordpress_cache_request", "wordpress_cache_authorization"))
            hosts_recovery = (module == "websites" and
                              action in ("manage_local_hosts", "hosts_management"))
            recovery = (response.get("recovery_id")
                        if module == "status_pages" or cache_recovery or hosts_recovery else
                        response.get("operation_id"))
            if (not response.get("request_id") or not isinstance(recovery, str)
                    or re.fullmatch(r"[0-9a-f]{32}", recovery) is None):
                recovery = ""
            entry = record(
                level=severity, module=module,
                action=action, operation_id=correlation,
                stage=activity_stage or response.get("stage", "complete"),
                outcome=outcome,
                target=target, error_class=type(error).__name__ if error else "",
                detail=detail,
                recovery_id=recovery if (not failed or module == "status_pages" or
                                           cache_recovery or hosts_recovery) else "",
            )
            persisted = append_activity(_STATE_DIR, entry)
            # None means below verbosity threshold, NOT a persistence failure.
            response["activity_logged"] = True if persisted else None
        except Exception:
            response["activity_logged"] = False
            response["activity_warning"] = "Plugin activity-log persistence was not confirmed"
            logging.getLogger("ach_customizer").exception(
                "Plugin activity-log write failed: %s %s %s", module, action, correlation)
        return response

    @staticmethod
    def _fail(stage, error, operation_id, *, diagnostic_error=None, target="",
              activity_stage=None):
        # Ordinary controlled validation/auth failures remain actionable.
        # Do not expose arbitrary DB/filesystem/internal exception text to
        # browsers: retain the precise exception class in private Activity.
        controlled = (PermissionError, StateError, StatusPageError,
                      MonitorInputError, FpmApplyError, HostsInspectionError,
                      ActivityError)
        wordpress_detail = False
        if stage.startswith("wordpress_cache_"):
            try:
                from ach_customizer_cache_wordpress import WordpressCacheError
                controlled += (WordpressCacheError,)
                wordpress_detail = isinstance(error, (WordpressCacheError, StatusPageError))
            except ImportError:
                pass
        if stage == "abusive_scan_manage":
            # This scanner is intentionally operator-controlled. Report
            # its typed dependency/ownership/validation failures rather than
            # hiding actionable causes behind a generic plugin error.
            try:
                from ach_customizer_abusive_scan import AbuseError
                controlled += (AbuseError,)
            except ImportError:
                pass
        typed_domain_detail = isinstance(error, str) and diagnostic_error is not None
        if isinstance(error, controlled) or typed_domain_detail:
            message = str(error)[:300]
        else:
            message = "Unexpected plugin error; inspect Activity using Operation ID"
        response = {"status": False, "stage": stage,
                    "msg": message, "operation_id": operation_id}
        # A narrow read-only diagnosis for aaPanel's fresh-site VHost shape.
        # No Cache mutation/recovery endpoint accepts this as authorization.
        if (stage == "cache_activation_preview" and
                getattr(error, "reason_code", None) == "native_extension_include_missing"):
            response["reason_code"] = "native_extension_include_missing"
        actual_recovery = getattr(error, "recovery_id", None)
        # Only a trusted Hosts or Nginx Guard writer may supply durable
        # recovery identity. Never promote an arbitrary exception's or
        # caller-provided recovery_id into the audit trail.
        trusted_hosts_recovery = True
        if stage == "hosts_management":
            try:
                from ach_customizer_hosts_manage import HostsManageError
                trusted_hosts_recovery = isinstance(error, HostsManageError)
            except ImportError:
                trusted_hosts_recovery = False
        if stage == "nginx_guard_manage":
            try:
                from ach_customizer_nginx_security import GuardError
                trusted_hosts_recovery = isinstance(error, GuardError)
                if trusted_hosts_recovery and error.stage == "unsupported_ruleset":
                    # A diagnostic only: the retained record is not verified
                    # recovery evidence and provides no Restore authorization.
                    response["reason_code"] = "unsupported_guard_ruleset"
                    actual_recovery = None
            except ImportError:
                trusted_hosts_recovery = False
        if stage == "abusive_scan_manage":
            try:
                from ach_customizer_abusive_scan import AbuseError
                trusted_hosts_recovery = isinstance(error, AbuseError)
            except ImportError:
                trusted_hosts_recovery = False
        if stage.startswith("wordpress_cache_"):
            trusted_hosts_recovery = wordpress_detail
        if (trusted_hosts_recovery and isinstance(actual_recovery, str) and
                re.fullmatch(r"[0-9a-f]{32}", actual_recovery)):
            response["recovery_id"] = actual_recovery
            response["request_id"] = operation_id
        module = ("php_fpm" if stage.startswith(("fpm_", "php_fpm_", "php_versions_", "php_runtime_")) else
                  "status_pages" if stage.startswith("status_") else
                  "websites" if stage.startswith(("website_", "hosts_", "cache_", "nginx_guard_", "abusive_scan_", "wordpress_cache_", "wp_settings_")) else
                  "lifecycle" if stage.startswith("wp_terminal_") else
                  "diagnostics" if stage.startswith("activity_") else "monitor")
        return ach_customizer_main._activity_result(
            response, module, stage, target=target,
            error=diagnostic_error if diagnostic_error is not None else error,
            # This text was explicitly reviewed at the typed endpoint boundary;
            # keep its original exception class and the actionable Activity cause.
            trusted_detail=message if typed_domain_detail or wordpress_detail else None,
            activity_stage=activity_stage)

    def get_activity(self, args):
        """Native full-primary-admin-only diagnostics. No arbitrary paths."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            level = self._argument(args, "level", "")
            module = self._argument(args, "module", "")
            try:
                limit = int(self._argument(args, "limit", 50))
            except (TypeError, ValueError) as exc:
                raise ActivityError("Invalid activity page size") from exc
            # Manual-review evidence is an immutable plugin-owned Activity
            # source, not an optional JSONL message. This primary-admin-only
            # projection keeps actionable identities visible during JSONL
            # persistence failures, ERROR verbosity and log rotation.
            import ach_customizer_wp_terminal as terminal
            stale_helper = getattr(terminal, "MANUAL_REVIEW_CONTRACT", None) != "durable-manual-review-v3"
            from ach_customizer_activity import MAX_RESULTS
            if (type(limit) is not int or not 1 <= limit <= MAX_RESULTS
                    or level not in ("", "DEBUG", "INFO", "WARNING", "ERROR")
                    or module not in ("", "monitor", "websites", "php_fpm",
                                      "status_pages", "diagnostics", "lifecycle")):
                raise ActivityError("Invalid activity filters or page size")
            # Preserve unrelated Activity when aaPanel has retained an old
            # helper import after ZIP upgrade. Do not claim to have read the
            # private WP outbox until an operator-approved panel reload.
            durable_manual, incomplete = (([], []) if stale_helper else
                terminal.manual_review_activity(
                    data_dir=_STATE_DIR, level=level, module=module,
                    with_integrity=True))
            log_warning = ("Resident WP helper stale; durable manual-review evidence "
                           "unavailable until an approved panel reload" if stale_helper else None)
            if incomplete:
                warning = ("Incomplete private native WP manual-review evidence for "
                           + str(len(incomplete)) + " operation(s); first Operation ID: "
                           + incomplete[0] + ". Preserve files for independent OS review.")
                log_warning = (log_warning + " " + warning) if log_warning else warning
            try:
                generic = read_activity(
                    _STATE_DIR, level=level, module=module, limit=MAX_RESULTS)
            except ActivityError:
                if not durable_manual and not incomplete:
                    raise
                # Do not hide valid reports or the precise incomplete Outbox
                # operation identity merely because rolling JSONL is damaged.
                generic = []
                warning = ("General Activity log unavailable; "
                           + ("durable WordPress manual-review evidence shown" if durable_manual
                              else "incomplete manual-review evidence metadata shown"))
                log_warning = (log_warning + " " + warning) if log_warning else warning
            seen = set()
            entries = []
            for event in durable_manual + generic:
                key = (event["action"], event["operation_id"])
                if key in seen and event["action"] == "wp_terminal_manual_review":
                    continue
                seen.add(key)
                entries.append(event)
            entries.sort(key=lambda item: (item["time_utc"], item["operation_id"]), reverse=True)
            return {"status": True, "request_id": request_id, "schema": 1,
                    "entries": entries[:limit], "configured_level": configured_level(),
                    "retention_max_bytes": 524288, "read_only": True,
                    **({"activity_warning": log_warning} if log_warning else {})}
        except PermissionError as exc:
            return self._fail("activity_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("activity_read", exc, request_id)

    @staticmethod
    def _overview(state, operation_id):
        active = state["enabled"]
        return {
            "status": True,
            "operation_id": operation_id,
            "mode": "Monitor" if active else "Disabled",
            "enforcement": False,
            "state_schema": state["schema_version"],
            "state_revision": state["revision"],
            "worker_source_version": WORKER_SOURCE_VERSION,
            "overall_enabled": active,
            "modules_enabled": dict(state["modules"]),
            "modules": {
                name: "Monitor" if active and enabled else "Disabled"
                for name, enabled in state["modules"].items()
            },
            "overall_enable_control": "Plugin-owned Monitor switch only",
            "notice": (
                "Monitor switches do not directly change services or enable automatic repair. Disabling Overall Monitor or a relevant module blocks related workflows; disabling Overall Monitor or PHP-FPM preview also blocks opted-in PHP-FPM repair. Manual Apply and auto-repair Enable remain separate explicit actions."
                if active else
                "Monitor disabled: existing services keep running, but related inspections/manual workflows and already opted-in PHP-FPM automatic repair cannot run. Previously applied manual FPM changes require explicit recovery."
            ),
        }

    def get_overview(self, args):
        operation_id = uuid4().hex
        try:
            response = self._overview(read_state(_STATE_DIR), operation_id)
            return self._activity_result(response, "monitor", "get_overview", level="DEBUG")
        except Exception as exc:
            return self._fail("monitor_state_read", exc, operation_id)

    def set_control(self, args):
        """Update only plugin-owned settings; never enable host enforcement.

        Native aaPanel authentication is inherited for this regular /plugin
        action. A second explicit server-side gate rejects non-admin sessions.
        """
        operation_id = uuid4().hex
        try:
            from flask import has_request_context, request, session

            # aaPanel can mark a temporary-token login as login=True and
            # uid=1. These sessions must never persist operator preferences.
            # Check the independent temporary identity markers even when a
            # token/session passes aaPanel's native authentication and CSRF.
            if (not has_request_context() or request.method != "POST"
                    or session.get("login") is not True
                    or type(session.get("uid")) is not int
                    or session["uid"] != 1
                    or bool(session.get("tmp_login"))
                    or "tmp_login_id" in session
                    or "tmp_login_expire" in session):
                raise PermissionError("Full primary aaPanel administrator session and POST are required")
            control = self._argument(args, "control")
            enabled = self._argument(args, "enabled")
            state, changed = set_enabled(
                control, enabled,
                expected_revision=self._argument(args, "expected_revision"),
                directory=_STATE_DIR,
            )
            response = {**self._overview(state, operation_id), "changed": changed}
            return self._activity_result(response, "monitor", "set_control", target=str(control))
        except PermissionError as exc:
            return self._fail("monitor_authorization", exc, operation_id)
        except Exception as exc:
            return self._fail("monitor_state_write", exc, operation_id)

    @staticmethod
    def _require_enabled(module):
        state = read_state(_STATE_DIR)
        if not state["enabled"]:
            raise StateError("Monitor is disabled by its operator")
        if not state["modules"][module]:
            raise StateError("Monitor module is disabled: " + module)

    def get_sites(self, args):
        operation_id = uuid4().hex
        try:
            self._require_enabled("site_inventory")
            import public

            result = get_site_page(
                public,
                self._argument(args, "page", 1),
                self._argument(args, "page_size", 25),
            )
            response = {"status": True, "operation_id": operation_id, **result}
            return self._activity_result(response, "websites", "get_sites",
                                         target="page:" + str(result["page"]), level="DEBUG")
        except Exception as exc:
            return self._fail("website_discovery", exc, operation_id)

    def compare_site_changes(self, args):
        """Full-primary-admin Monitor-only native site/binding comparison."""
        request_id = uuid4().hex
        site_error_type = None
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            # Resolve the new optional helper lazily: a stale in-memory aaPanel
            # module must not break unrelated installed plugin actions.
            try:
                from ach_customizer_site_changes import compare, SiteChangesError
                site_error_type = SiteChangesError
            except ImportError as exc:
                raise MonitorInputError(
                    "Site-change helper is outdated after plugin update; "
                    "restart the panel service during maintenance and reopen the plugin"
                ) from exc
            import public
            result = compare(public, directory=_STATE_DIR)
            response = {"status": True, "operation_id": request_id, **result}
            return self._activity_result(
                response, "websites", "compare_site_changes",
                target="native-sites", level="DEBUG")
        except PermissionError as exc:
            return self._fail("website_changes_authorization", exc, request_id)
        except Exception as exc:
            if site_error_type is not None and isinstance(exc, site_error_type):
                return self._fail("website_changes_compare", str(exc), request_id,
                                  diagnostic_error=exc)
            return self._fail("website_changes_compare", exc, request_id)

    def save_site_baseline(self, args):
        """Explicit reviewed baseline revision; never writes a site or service."""
        request_id = uuid4().hex
        site_error_type = None
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_site_changes import save_reviewed_baseline, SiteChangesError
                site_error_type = SiteChangesError
            except ImportError as exc:
                raise MonitorInputError(
                    "Site-change helper is outdated after plugin update; "
                    "restart the panel service during maintenance and reopen the plugin"
                ) from exc
            import public
            result = save_reviewed_baseline(
                public, directory=_STATE_DIR,
                expected_revision=self._argument(args, "expected_revision"),
                expected_monitor_revision=self._argument(args, "expected_monitor_revision"),
                expected_source_sha256=self._argument(args, "expected_source_sha256"),
                reviewed=self._argument(args, "reviewed"),
            )
            response = {"status": True, "operation_id": request_id, **result}
            return self._activity_result(
                response, "websites", "save_site_baseline", target="native-sites")
        except PermissionError as exc:
            return self._fail("website_baseline_authorization", exc, request_id)
        except Exception as exc:
            if site_error_type is not None and isinstance(exc, site_error_type):
                return self._fail("website_baseline_save", str(exc), request_id,
                                  diagnostic_error=exc)
            return self._fail("website_baseline_save", exc, request_id)

    def save_selected_site_baseline(self, args):
        """Review and record only the selected native site's observed DB state."""
        request_id = uuid4().hex
        site_error_type = None
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_site_changes import (
                    save_reviewed_selected_site_baseline, SiteChangesError)
                site_error_type = SiteChangesError
            except ImportError as exc:
                raise MonitorInputError(
                    "Site baseline helper is outdated after plugin update; "
                    "reopen aaPanel after verifying resident Python worker"
                ) from exc
            public, selected, current_site = self._selected_native_website(args)
            result = save_reviewed_selected_site_baseline(
                public, directory=_STATE_DIR,
                selected_site=selected, current_site=current_site,
                expected_revision=self._argument(args, "expected_revision"),
                expected_monitor_revision=self._argument(
                    args, "expected_monitor_revision"),
                expected_source_sha256=self._argument(
                    args, "expected_source_sha256"),
                reviewed=self._argument(args, "reviewed"),
            )
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "save_selected_site_baseline",
                target=str(selected["id"]))
        except PermissionError as exc:
            return self._fail("website_selected_baseline_authorization",
                              exc, request_id)
        except Exception as exc:
            if site_error_type is not None and isinstance(exc, site_error_type):
                return self._fail("website_selected_baseline_save", str(exc), request_id,
                                  diagnostic_error=exc)
            return self._fail("website_selected_baseline_save", exc, request_id)

    def inspect_site_reconciliation(self, args):
        """Primary-admin, selected-site onboarding and drift/recovery summary.

        Observational composition only; all manual module Apply/Restore
        endpoints independently enforce their own fresh source/approval gates.
        """
        request_id = uuid4().hex
        reconciliation_errors = ()
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_site_reconcile import (
                    inspect_selected_site, ReconciliationError)
                from ach_customizer_site_changes import SiteChangesError
                reconciliation_errors = (ReconciliationError, SiteChangesError)
            except ImportError as exc:
                raise MonitorInputError(
                    "Site reconciliation helper is outdated after plugin update; "
                    "inspect installed files and resident panel worker before retrying"
                ) from exc
            public, before, current_site = self._selected_native_website(args)
            result = inspect_selected_site(
                public, before, current_site=current_site, directory=_STATE_DIR)
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "inspect_site_reconciliation", target=str(before["id"]),
                level="WARNING" if result["state"] == "Needs Review" else "INFO")
        except PermissionError as exc:
            return self._fail("website_reconciliation_authorization", exc, request_id)
        except Exception as exc:
            if reconciliation_errors and isinstance(exc, reconciliation_errors):
                return self._fail("website_reconciliation_read", str(exc), request_id,
                                  diagnostic_error=exc)
            return self._fail("website_reconciliation_read", exc, request_id)

    def get_php_versions(self, args):
        """Primary-admin-only, read-only installed PHP file discovery."""
        operation_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            # aaPanel may retain an older monitor helper in the panel process
            # after an in-place ZIP update. Resolve this new symbol only after
            # authorization so stale code cannot break unrelated endpoints.
            try:
                from ach_customizer_monitor import discover_php_fpm_versions
            except ImportError as exc:
                raise MonitorInputError(
                    "PHP discovery module is outdated after plugin update. "
                    "Restart aaPanel panel service (not server), reopen the "
                    "plugin and Refresh installed PHP."
                ) from exc
            result = discover_php_fpm_versions("/www/server/php")
            response = {"status": True, "operation_id": operation_id, **result}
            return self._activity_result(
                response, "php_fpm", "get_php_versions",
                target="native-php", level="WARNING" if result["state"] == "Partial" else "DEBUG")
        except PermissionError as exc:
            return self._fail("php_versions_authorization", exc, operation_id)
        except Exception as exc:
            return self._fail("php_versions_discovery", exc, operation_id)

    def inspect_php_runtime(self, args):
        """Read-only selected-version master/socket evidence; never Apply."""
        operation_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            version = self._argument(args, "php_version")
            # Lazy import prevents stale aaPanel module caches from taking
            # down existing PHP discovery/Monitor/Status Pages endpoints.
            try:
                from ach_customizer_php_runtime import inspect_php_fpm_runtime
            except ImportError as exc:
                raise MonitorInputError(
                    "PHP runtime inspector not loaded after plugin update; "
                    "restart aaPanel panel service, reopen and Refresh installed PHP"
                ) from exc
            result = inspect_php_fpm_runtime("/www/server/php", version)
            # This is a second, independent read-only file attribution. An
            # old/stale native ZIP worker must keep the existing process
            # inspection usable, but must NOT claim site-map success.
            try:
                import public
                from ach_customizer_php_topology import inspect_php_fpm_site_topology
                topology = inspect_php_fpm_site_topology(
                    public, "/www/server/php", version,
                    observed_runtime_socket=(
                        result["socket_path"] if result["state"] == "Observed" else None
                    ),
                )
            except (ImportError, RuntimeError, TypeError, AttributeError) as exc:
                topology = {
                    "schema": 1, "state": "Needs Review", "version": version,
                    "scope": "shared_service", "read_only": True,
                    "runtime_verified": False, "apply_eligible": False,
                    "pool": None, "config_path": None, "socket_path": None,
                    "site_count": 0, "matched_sites": [], "other_sites": [],
                    "unresolved_sites": [], "source_sha256": None,
                    "reason": "Native PHP site-topology adapter unavailable or incompatible",
                    "note": (
                        "No site-to-service impact boundary established. Restart panel "
                        "after plugin update; reload native website inventory."
                    ),
                }
            result["site_mapping"] = topology
            response = {"status": True, "operation_id": operation_id, **result}
            return self._activity_result(
                response, "php_fpm", "inspect_php_runtime",
                target=str(version)[:16],
                level="DEBUG" if result["state"] == "Observed" and
                topology["state"] == "File Mapping" else "WARNING"
            )
        except PermissionError as exc:
            return self._fail("php_runtime_authorization", exc, operation_id)
        except Exception as exc:
            return self._fail("php_runtime_inspection", exc, operation_id)

    def inspect_local_hosts(self, args):
        """Full-admin-only, read-only origin-local /etc/hosts diagnosis.

        Native site identity and real domain bindings are rechecked before
        returning; no client path/domain is trusted, and no correction exists.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            # aaPanel can keep the previous Hosts module in the panel Python
            # process after an in-place plugin import. A newer helper must
            # never make unrelated Monitor/Website endpoints fail at import.
            try:
                from ach_customizer_hosts import native_site_snapshot
            except ImportError as exc:
                raise HostsInspectionError(
                    "Hosts diagnostic module is outdated after plugin update. "
                    "Restart aaPanel panel service (not server), reopen this plugin "
                    "and refresh website inventory before inspecting."
                ) from exc
            # The browser-selected site key is a precondition, never a lookup
            # source. Refuse stale/reassigned aaPanel IDs before reading hosts.
            expected_site_key = self._argument(args, "expected_site_key")
            expected_snapshot = self._argument(args, "expected_site_snapshot")
            if (not isinstance(expected_site_key, str) or not expected_site_key
                    or len(expected_site_key) > 255 or
                    not isinstance(expected_snapshot, str) or
                    not expected_snapshot):
                raise HostsInspectionError("Refresh the native website inventory before inspection")
            try:
                selected_identity = json.loads(expected_snapshot)
            except (ValueError, TypeError):
                raise HostsInspectionError(
                    "Invalid selected website inventory snapshot; refresh inventory") from None
            if (not isinstance(selected_identity, list) or len(selected_identity) != 5 or
                    type(selected_identity[0]) is not int or
                    not isinstance(selected_identity[1], str) or
                    not isinstance(selected_identity[2], str) or
                    not isinstance(selected_identity[3], str) or
                    not isinstance(selected_identity[4], list) or
                    any(not isinstance(pair, list) or len(pair) != 2 or
                        not isinstance(pair[0], str) or
                        type(pair[1]) is not int
                        for pair in selected_identity[4])):
                raise HostsInspectionError("Invalid selected website snapshot; refresh inventory")
            site_id = self._status_site_id(args)
            if site_id is None:
                raise HostsInspectionError("Choose an existing native aaPanel site ID")
            import public
            def current_site():
                record = public.M("sites").where("id=?", (site_id,)).field(
                    "id,name,path,status").find()
                if (not isinstance(record, dict) or type(record.get("id")) not in
                        (int, str) or str(record["id"]) != str(site_id)
                        or not isinstance(record.get("name"), str)
                        or not record["name"]):
                    raise HostsInspectionError("Native site identity changed")
                site = {"id": site_id, "name": record["name"],
                        "path": record.get("path"), "status": record.get("status")}
                _bound_domains_for_sites(public, [site])
                return site
            before = current_site()
            if (before["name"] != expected_site_key or
                    native_site_snapshot(before) != selected_identity):
                raise HostsInspectionError(
                    "Selected website identity or bound domains changed; refresh native inventory")
            names = [item["name"] for item in before["bound_domains"]]
            result = inspect_hosts_file(names)
            # Recovery is bound to the same site and the current origin file.
            # A read-only diagnostic never acknowledges an unverified write.
            from ach_customizer_hosts_manage import inspect_recovery
            result["hosts_recovery"] = inspect_recovery(
                before, data_dir=_STATE_DIR)
            if current_site() != before:
                raise HostsInspectionError("Native site or bound domains changed; recheck")
            return self._activity_result(
                {"status": True, "request_id": request_id,
                 "site_id": site_id, "site_key": before["name"], **result},
                "websites", "inspect_local_hosts", target=str(site_id))
        except PermissionError as exc:
            return self._fail("hosts_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("hosts_inspection", exc, request_id)

    def inspect_hosts_aliases(self, args):
        """List origin-local loopback names with no native-site prerequisite."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            from ach_customizer_hosts_manage import inspect_available_aliases
            result = inspect_available_aliases()
            return self._activity_result(
                {"status": True, "schema": 1, "request_id": request_id, **result},
                "websites", "inspect_hosts_aliases", level="DEBUG")
        except PermissionError as exc:
            return self._fail("hosts_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("hosts_inspection", exc, request_id)

    def remove_hosts_alias(self, args):
        """One explicit administrator action; read current Hosts at click time."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            from ach_customizer_hosts_manage import remove_available_alias
            result = remove_available_alias(domain=self._argument(args, "domain"),
                                            data_dir=_STATE_DIR)
            return self._activity_result(
                {"status": True, "schema": 1, "request_id": request_id, **result},
                "websites", "remove_hosts_alias", target=result["domain"],
                level="WARNING")
        except PermissionError as exc:
            return self._fail("hosts_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("hosts_management", exc, request_id)

    def manage_local_hosts(self, args):
        """Opt-in exact domain/hosts remediation with recoverable original bytes.

        A successful source edit does not prove external DNS, another host's
        resolver, nor that WordPress Toolkit will not recreate the entry.
        """
        request_id = uuid4().hex
        trusted_site_id = ""
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            action = self._argument(args, "hosts_action")
            if action not in ("remove", "restore") or self._argument(args, "reviewed") != "true":
                raise HostsInspectionError("Review and explicitly approve the selected hosts operation")
            from ach_customizer_hosts_manage import (
                HostsManageError, remove_loopback_alias, restore_loopback_alias,
            )
            _, before, current_site = self._selected_native_website(args)
            if current_site() != before:
                raise HostsManageError("Native site changed before hosts operation")
            trusted_site_id = str(before["id"])
            names = [item["name"] for item in before["bound_domains"]]
            if action == "remove":
                result = remove_loopback_alias(
                    site=before, domains=names,
                    domain=self._argument(args, "domain"),
                    expected_sha=self._argument(args, "expected_hosts_sha256"),
                    data_dir=_STATE_DIR)
            else:
                result = restore_loopback_alias(
                    site=before,
                    expected_recovery_id=self._argument(args, "recovery_id"),
                    data_dir=_STATE_DIR)
            if current_site() != before:
                raise HostsManageError(
                    "Native site identity changed during hosts write; inspect recovery",
                    result["recovery_id"])
            return self._activity_result(
                {"status": True, "request_id": request_id, "schema": 1,
                 "site_id": before["id"], "site_key": before["name"], **result},
                "websites", "manage_local_hosts", target=str(before["id"]))
        except PermissionError as exc:
            return self._fail("hosts_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("hosts_management", exc, request_id,
                              target=trusted_site_id)

    def wp_terminal_manage(self, args):
        """Primary-admin control of read-only WP failure observation.

        The witness only observes native setup and records a diagnostic;
        it never repairs Hosts or PHP-FPM.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            action = self._argument(args, "terminal_action")
            import ach_customizer_wp_terminal as terminal
            if (action != "disable" and
                    getattr(terminal, "MANUAL_REVIEW_CONTRACT", None) != "durable-manual-review-v3"):
                response = self._fail(
                    "wp_terminal_management", MonitorInputError(
                        "Resident native WP helper is stale. Emergency disable remains available; "
                        "a controlled aaPanel reload requires operator approval."), request_id)
                response["reason_code"] = "resident_wp_helper_stale"
                return response
            inspect = terminal.inspect
            recheck_witness, abandon_witness = terminal.recheck_witness, terminal.abandon_witness
            if action == "inspect":
                result = inspect(data_dir=_STATE_DIR)
                level = "DEBUG"
            elif action == "enable":
                if self._argument(args, "reviewed") != "true":
                    raise MonitorInputError("Explicit native WP read-only witness approval is required")
                import public
                if public.get_panel_version() != "8.0.7" or public.get_webserver() != "nginx":
                    raise MonitorInputError("Native WP witness is verified only for aaPanel 8.0.7 Nginx")
                from ach_customizer_wp_watcher import enable
                result = enable(data_dir=_STATE_DIR)
                level = "WARNING"
            elif action == "disable":
                from ach_customizer_wp_watcher import disable
                result = disable(data_dir=_STATE_DIR)
                level = "WARNING"
            elif action == "recheck":
                result = recheck_witness(data_dir=_STATE_DIR)
                level = "INFO" if result["state"] not in ("Needs Review", "Active or Unknown") else "WARNING"
            elif action == "abandon":
                if self._argument(args, "reviewed") != "true":
                    raise MonitorInputError("Explicit stale WP witness abandonment approval is required")
                result = abandon_witness(data_dir=_STATE_DIR)
                level = "WARNING"
            else:
                raise MonitorInputError("Unsupported native WordPress terminal operation")
            if action in ("inspect", "enable", "disable"):
                from ach_customizer_wp_watcher import health
                result = {**result, **health()}
            return self._activity_result(
                {"status": True, "schema": 1, "request_id": request_id, **result},
                "lifecycle", "wp_terminal_" + action, level=level)
        except PermissionError as exc:
            return self._fail("wp_terminal_authorization", exc, request_id)
        except Exception as exc:
            # Only our own exception messages are suitable for the native UI.
            from ach_customizer_wp_terminal import TerminalError
            from ach_customizer_wp_watcher import WatcherError
            if isinstance(exc, (TerminalError, WatcherError)):
                return self._fail("wp_terminal_management", str(exc), request_id,
                                  diagnostic_error=exc)
            return self._fail("wp_terminal_management", exc, request_id)

    def _selected_native_website(self, args):
        """Revalidate a browser site snapshot using aaPanel's own site IDs.

        Called only AFTER each invoking endpoint checks full-admin POST and
        Monitor access. Return a fresh-reader so the caller can reject native
        site changes during the selected read-only inspection. Request paths,
        hostnames and ports are never filesystem lookup authorities.
        """
        expected_key = self._argument(args, "expected_site_key")
        expected_snapshot = self._argument(args, "expected_site_snapshot")
        if (not isinstance(expected_key, str) or not expected_key or
                len(expected_key) > 255 or
                not isinstance(expected_snapshot, str) or
                not expected_snapshot):
            raise MonitorInputError("Refresh the selected native website inventory")
        try:
            selected = json.loads(expected_snapshot)
        except (TypeError, ValueError):
            raise MonitorInputError("Invalid native website snapshot; refresh inventory") from None
        if (not isinstance(selected, list) or len(selected) != 5 or
                type(selected[0]) is not int or not isinstance(selected[1], str) or
                not isinstance(selected[2], str) or not isinstance(selected[3], str) or
                not isinstance(selected[4], list) or
                any(not isinstance(item, list) or len(item) != 2 or
                        not isinstance(item[0], str) or type(item[1]) is not int
                        for item in selected[4])):
            raise MonitorInputError("Invalid native website snapshot; refresh inventory")
        site_id = self._status_site_id(args)
        if site_id is None:
            raise MonitorInputError("Choose a native aaPanel website")
        import public

        def current_site():
            record = public.M("sites").where("id=?", (site_id,)).field(
                "id,name,path,status").find()
            if (not isinstance(record, dict) or type(record.get("id")) not in
                    (int, str) or str(record["id"]) != str(site_id) or
                    not isinstance(record.get("name"), str) or not record["name"]):
                raise MonitorInputError("Native site identity changed")
            site = {"id": site_id, "name": record["name"],
                    "path": record.get("path"), "status": record.get("status")}
            _bound_domains_for_sites(public, [site])
            return site

        before = current_site()
        if (before["name"] != expected_key or
                native_site_snapshot(before) != selected):
            raise MonitorInputError(
                "Native site/root/bindings changed; refresh website inventory")
        return public, before, current_site

    def manage_nginx_protection(self, args):
        """Primary-admin native per-site pre-PHP sensitive-path protection.

        A separate opt-in policy has no implicit auto-enforcement. Even
        Recheck revalidates the current native site and include graph;
        Apply/Restore additionally require an explicit site confirmation.
        """
        request_id = uuid4().hex
        action = self._argument(args, "guard_action")
        trusted_site_id = ""
        guard_stage_error_type = None
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            if action not in ("preview", "apply", "recheck", "restore"):
                raise MonitorInputError("Unsupported Nginx security operation")
            import public
            if (public.get_webserver() != "nginx" or
                    str(public.get_panel_version()).strip() != "8.0.7"):
                raise MonitorInputError("Nginx security adapter requires aaPanel 8.0.7 Nginx")
            from ach_customizer_nginx_security import (
                manage_guard, GuardError, ExtensionError,
            )
            guard_stage_error_type = ExtensionError
            from ach_customizer_state import _open_state_dir
            from ach_customizer_status_pages import _take_lock
            public, before, current_site = self._selected_native_website(args)
            # Only a fully revalidated native site becomes an Activity target.
            # Browser-provided IDs are never trusted for failed pre-selection.
            trusted_site_id = str(before["id"])
            approved = self._argument(args, "approved") == "true"
            xmlrpc_choice = self._argument(args, "guard_block_xmlrpc", "false")
            if xmlrpc_choice not in ("true", "false"):
                raise MonitorInputError("Choose an explicit XML-RPC Nginx guard option")
            # A globally shared native document root cannot justify an
            # isolated per-site protection claim. Reject before any write.
            if action in ("apply", "restore"):
                same_roots = public.M("sites").where("path=?", (before["path"],)).field(
                    "id,path").limit("0,2").select()
                if (not isinstance(same_roots, list) or len(same_roots) != 1 or
                        type(same_roots[0].get("id")) is not int or
                        same_roots[0]["id"] != before["id"] or
                        same_roots[0].get("path") != before["path"]):
                    raise MonitorInputError(
                        "Shared or unverified native site root; Nginx protection refused")
            fd = _open_state_dir(_STATE_DIR)
            try:
                lock_fd = _take_lock(fd)
                try:
                    if current_site() != before:
                        raise MonitorInputError("Native website changed before Nginx protection")
                    result = manage_guard(
                        action, before, data_fd=fd, approved=approved,
                        expected_vhost=self._argument(args, "expected_vhost_sha256"),
                        expected_proposal=self._argument(args, "expected_proposal_sha256"),
                        expected_recovery=self._argument(args, "recovery_id"),
                        block_xmlrpc=xmlrpc_choice == "true",
                    )
                    if current_site() != before:
                        raise GuardError(
                            "uncertain", "Native site changed during security operation; "
                            "reinspect saved recovery before another action",
                            recovery_id=result.get("recovery_id"))
                finally:
                    os.close(lock_fd)
            finally:
                os.close(fd)
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "manage_nginx_protection", target=str(before["id"]),
                level="WARNING" if result["state"] in
                    ("Needs Review", "Recovery Required", "Suspended") else "INFO")
        except PermissionError as exc:
            return self._fail("nginx_guard_authorization", exc, request_id,
                              target=trusted_site_id)
        except Exception as exc:
            # Both GuardError and the inherited native helper ExtensionError
            # have trusted typed stages. Only GuardError may supply an owned
            # Recovery ID at _fail; an arbitrary exception cannot inject one.
            phase = (getattr(exc, "stage", None)
                     if guard_stage_error_type and
                     isinstance(exc, guard_stage_error_type) else None)
            typed_stage = ("nginx_guard_" + phase
                           if isinstance(phase, str) and
                           re.fullmatch(r"[a-z][a-z_]{0,31}", phase) else None)
            return self._fail("nginx_guard_manage", exc, request_id,
                              target=trusted_site_id, activity_stage=typed_stage)

    def manage_abusive_scan(self, args):
        """Explicit per-site log monitoring, origin-wide firewall ban/recovery.

        Fail2ban is a host dependency. Selected site ownership, persisted
        recovery, exact log source and shared-service side effects remain
        visible; the endpoint never installs packages or edits vendor files.
        """
        request_id = uuid4().hex
        action = self._argument(args, "scan_action")
        trusted_site_id = ""
        try:
            self._status_primary_admin_post()
            if action in ("orphan_list", "orphan_restore"):
                # Recovery must remain available after deleting the website,
                # including when the Monitor has been disabled. Never accept
                # a claimed orphan status supplied by the browser.
                from ach_customizer_abusive_scan import manage_orphans, AbuseError
                from ach_customizer_state import _open_state_dir
                from ach_customizer_status_pages import _take_lock
                import public

                def native_site_absent(site_id):
                    result = public.M("sites").where("id=?", (site_id,)).count()
                    if type(result) is not int or result < 0:
                        raise AbuseError("identity", "Native site absence lookup failed")
                    return result == 0

                raw_site = self._argument(args, "orphan_site_id")
                site_id = None
                if action == "orphan_restore":
                    if not isinstance(raw_site, str) or not re.fullmatch(
                            r"[1-9][0-9]{0,9}", raw_site):
                        raise AbuseError("input", "Select a recorded native scanner site ID")
                    site_id = int(raw_site)
                data_fd = _open_state_dir(_STATE_DIR)
                try:
                    lock = _take_lock(data_fd)
                    try:
                        result = manage_orphans(
                            action, data_fd=data_fd,
                            native_site_absent=native_site_absent,
                            site_id=site_id,
                            recovery_id=self._argument(args, "recovery_id"),
                            approved=self._argument(args, "approved") == "true")
                    finally:
                        os.close(lock)
                finally:
                    os.close(data_fd)
                trusted_site_id = (str(result["site_id"])
                                   if action == "orphan_restore" else "")
                return self._activity_result(
                    {"status": True, "request_id": request_id, **result},
                    "websites", "manage_abusive_scan", target=trusted_site_id,
                    level="WARNING" if result["state"] == "Recovery Required" else "INFO")
            self._require_enabled("site_inventory")
            if action not in ("preview", "apply", "recheck", "restore"):
                raise MonitorInputError("Unsupported Fail2ban scanner action")
            from ach_customizer_abusive_scan import manage, AbuseError
            from ach_customizer_nginx_security import manage_guard
            from ach_customizer_state import _open_state_dir
            from ach_customizer_status_pages import _take_lock

            public, site, current_site = self._selected_native_website(args)
            trusted_site_id = str(site["id"])
            data_fd = _open_state_dir(_STATE_DIR)
            try:
                lock = _take_lock(data_fd)
                try:
                    if current_site() != site:
                        raise MonitorInputError("Native site changed during Fail2ban readiness")
                    if action == "apply":
                        # Only the verified Nginx server-level sensitive-path
                        # guard can claim pre-PHP blocking for this site.
                        guard = manage_guard("recheck", site, data_fd=data_fd)
                        if guard["state"] != "Applied" or not guard["runtime_verified"]:
                            raise AbuseError("dependency",
                                "Enable and verify this site's Nginx sensitive-path guard first")
                    result = manage(
                        action, site, data_fd=data_fd,
                        approved=self._argument(args, "approved") == "true",
                        params={name: self._argument(args, name)
                                for name in ("maxretry", "findtime", "bantime")
                                if self._argument(args, name) is not None},
                        expected_plan=self._argument(args, "expected_plan_sha256"),
                        recovery_id=self._argument(args, "recovery_id"),
                    )
                    if current_site() != site:
                        raise AbuseError("uncertain",
                            "Native site changed; recheck exact Fail2ban recovery",
                            recovery_id=result.get("recovery_id"))
                finally:
                    os.close(lock)
            finally:
                os.close(data_fd)
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "manage_abusive_scan", target=trusted_site_id,
                level="WARNING" if result["state"] in
                    ("Needs Review", "Recovery Required", "Dependency Missing") else "INFO")
        except PermissionError as exc:
            return self._fail("abusive_scan_authorization", exc, request_id,
                              target=trusted_site_id)
        except Exception as exc:
            from ach_customizer_abusive_scan import AbuseError
            kind = getattr(exc, "stage", None) if isinstance(exc, AbuseError) else None
            typed = ("abusive_scan_" + kind if isinstance(kind, str) and
                     re.fullmatch(r"[a-z][a-z_]{0,31}", kind) else None)
            return self._fail("abusive_scan_manage", exc, request_id,
                              target=trusted_site_id, activity_stage=typed)

    def inspect_native_vhost(self, args):
        """Primary-admin-only file-level Nginx vs native site record drift.

        Select by native ID and independently verify the browser's recorded
        site, root, status and bound-domain precondition before AND after.
        No browser-supplied path or hostname becomes an inspection target.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_vhost_drift import inspect_vhost_drift
            except ImportError as exc:
                raise MonitorInputError(
                    "VHost inspector not loaded after plugin update; restart the "
                    "aaPanel panel service and refresh the website inventory"
                ) from exc
            public, before, current_site = self._selected_native_website(args)
            site_id = before["id"]
            result = inspect_vhost_drift(public, before)
            if current_site() != before:
                raise MonitorInputError(
                    "Native site/root/bindings changed during VHost comparison; recheck")
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "inspect_native_vhost", target=str(site_id),
                level="DEBUG" if result["state"] == "File Match" else "WARNING")
        except PermissionError as exc:
            return self._fail("website_vhost_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("website_vhost_inspection", exc, request_id)

    def inspect_nginx_candidate(self, args):
        """On-demand prospective Nginx -T + local HTTP/80 observation.

        This action NEVER signals a reload and never treats candidate file
        inclusion or a HEAD status as proof of the worker's loaded policy.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_nginx_observation import observe_nginx_site
            except ImportError as exc:
                raise MonitorInputError(
                    "Nginx observer not loaded after plugin update; restart "
                    "aaPanel panel service and refresh website inventory"
                ) from exc
            public, before, current_site = self._selected_native_website(args)
            result = observe_nginx_site(public, before)
            if current_site() != before:
                raise MonitorInputError(
                    "Native website/root/bindings changed during Nginx observation; recheck")
            problem = result["reason"] or result["origin_http"].get("reason", "")
            issue = MonitorInputError(problem) if problem else None
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "inspect_nginx_candidate", target=str(before["id"]),
                error=issue,
                level="DEBUG" if result["state"] == "Candidate Included"
                    and result["origin_http"]["state"] != "Unavailable"
                    else "WARNING")
        except PermissionError as exc:
            return self._fail("website_nginx_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("website_nginx_observation", exc, request_id)

    def inspect_fastcgi_cache(self, args):
        """Full-primary-admin, read-only native FastCGI source audit.

        The selected site and bound domain snapshot are comparison-only.
        Neither request-supplied filesystem paths nor suggested domains can
        determine which site/VHost is inspected. No cache mutation or purge.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_cache_audit import inspect_site_fastcgi_cache
            except ImportError as exc:
                raise MonitorInputError(
                    "Cache inspector not loaded after plugin update; restart "
                    "aaPanel panel service and refresh the native site inventory"
                ) from exc
            public, before, current_site = self._selected_native_website(args)
            site_id = before["id"]
            result = inspect_site_fastcgi_cache(public, site_id, before["name"])
            from ach_customizer_cache_helper import inspect_nginx_helper_files
            helper = inspect_nginx_helper_files(before["path"])
            if current_site() != before:
                raise MonitorInputError(
                    "Native site or bound domains changed during cache inspection")
            response = {
                "status": True, "request_id": request_id, **result,
                "nginx_helper": helper,
            }
            return self._activity_result(
                response, "websites", "inspect_fastcgi_cache",
                target=str(site_id),
                level="WARNING" if result["state"] != "Source Observed"
                    or result["findings"] or helper["state"] in ("Installed", "Needs Review")
                    else "DEBUG",
            )
        except PermissionError as exc:
            return self._fail("cache_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("cache_inspection", exc, request_id)

    def probe_private_cache(self, args):
        """Full-admin synthetic cache-bypass observations on local HTTP(S).

        Never accept a browser-supplied URL, header or cache path. This is
        separate from source inspection, real-session tests and Purge All.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            from ach_customizer_cache_audit import inspect_site_fastcgi_cache
            from ach_customizer_cache_runtime import probe_private_cache
            profile = args.get("probe_profile", "wordpress")
            if type(profile) is not str or profile not in ("wordpress", "woocommerce_default"):
                raise MonitorInputError("Unsupported fixed Cache diagnostic profile")
            public, before, current_site = self._selected_native_website(args)
            audited = inspect_site_fastcgi_cache(
                public, before["id"], before["name"])
            result = probe_private_cache(before, audited, profile=profile)
            if current_site() != before:
                raise MonitorInputError(
                    "Native website/root/bindings changed during Cache runtime probe")
            # A positive loopback response cannot be assigned to a changed
            # source snapshot. Never upgrade a stale file audit to success.
            if result["state"] == "Observed BYPASS":
                after = inspect_site_fastcgi_cache(
                    public, before["id"], before["name"])
                if (after.get("state") != "Source Observed" or
                        after.get("source_sha256") != audited.get("source_sha256") or
                        after.get("managed_cache_handler") != audited.get("managed_cache_handler")):
                    result["state"] = "Needs Review"
                    result["private_probe_bypass_observed"] = False
                    if "default_guest_bypass_observed" in result:
                        result["default_guest_bypass_observed"] = False
                    result["reason"] = "Native Cache source changed during runtime observation"
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "probe_private_cache", target=str(before["id"]),
                level="DEBUG" if result["state"] == "Observed BYPASS" else "WARNING")
        except PermissionError as exc:
            return self._fail("cache_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("cache_runtime_probe", exc, request_id)

    def preview_cache_safety(self, args):
        """Reference-only per-site cache layout; no site, service or cache write.

        Only an explicitly selected current native site with an unambiguous
        *direct* cache zone gets reference fragments. An existing zone and
        source signatures do not prove that the active workers use it, or
        that the replacement snippet can be safely installed.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            try:
                from ach_customizer_cache_audit import inspect_site_fastcgi_cache
                from ach_customizer_cache_policy import generate_reference
            except ImportError as exc:
                raise MonitorInputError(
                    "Cache reference helper is outdated after plugin update; restart "
                    "the aaPanel panel service and refresh native website inventory"
                ) from exc
            public, before, current_site = self._selected_native_website(args)
            observed = inspect_site_fastcgi_cache(
                public, before["id"], before["name"])
            if current_site() != before:
                raise MonitorInputError(
                    "Native website/root/bindings changed during cache proposal")
            baseline = {
                "schema": 1, "site_id": before["id"],
                "site_key": before["name"], "read_only": True,
                "installed": False, "runtime_verified": False,
                "safe_verified": False, "apply_supported": False,
                "purge_supported": False, "cache_zone": None,
                "cache_directory": None, "proposal_sha256": None,
                "global_http_fragment": "", "site_server_fragment": "",
                "php_version": None,
                "source_sha256": observed.get("source_sha256"),
            }
            if (observed.get("state") != "Source Observed"
                    or observed.get("zone_state") != "Direct Zone"
                    or observed.get("php_version") not in ("81", "85")):
                reason = (
                    "Selected site requires a verified PHP 8.1/8.5 native "
                    "FastCGI-cache source before a reference is available"
                )
                reply = {"status": True, "request_id": request_id,
                         **baseline, "state": "Needs Review",
                         "reason": reason,
                         "note": "No policy generated, installed or enabled."}
            else:
                plan = generate_reference(
                    before["id"], observed["php_version"])
                reply = {"status": True, "request_id": request_id,
                         "site_key": before["name"],
                         "source_sha256": observed["source_sha256"],
                         **plan, "reason": ""}
            return self._activity_result(
                reply, "websites", "preview_cache_safety",
                target=str(before["id"]), level="WARNING")
        except PermissionError as exc:
            return self._fail("cache_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("cache_reference_preview", exc, request_id)

    def preview_cache_activation(self, args):
        """Explicit per-site Cache Apply preflight; no host or cache mutations."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            from ach_customizer_cache_manage import preview_cache_activation
            public, before, current_site = self._selected_native_website(args)
            result = preview_cache_activation(before, public)
            if current_site() != before:
                raise MonitorInputError("Native website changed during Cache activation preflight")
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "preview_cache_activation",
                target=str(before["id"]), level="WARNING")
        except PermissionError as exc:
            return self._fail("cache_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("cache_activation_preview", exc, request_id)

    def manage_cache_policy(self, args):
        """Primary-admin manual Cache Apply/Recheck/Restore; never implicit Purge."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            # aaPanel reserves the POST 'action' key for its own plugin router.
            # A body 'action' would override query action=a before this handler.
            action = self._argument(args, "cache_action")
            from ach_customizer_cache_manage import manage_cache
            if action not in ("apply", "recheck", "restore", "clear_files", "clear_url",
                              "bridge_enable", "bridge_disable", "bridge_inspect"):
                raise MonitorInputError("Unsupported Cache operation")
            public, before, current_site = self._selected_native_website(args)
            result = manage_cache(
                action, before, public,
                expected_source=self._argument(args, "expected_source_sha256"),
                expected_proposal=self._argument(args, "expected_proposal_sha256"),
                cache_generation=self._argument(args, "cache_generation"),
                recovery_id=self._argument(args, "recovery_id"),
                approved=self._argument(args, "approved") == "true",
                cache_url_path=self._argument(args, "cache_url_path") if action == "clear_url" else None,
            )
            if current_site() != before:
                # The operation could already have committed. Preserve its
                # recovery identity and report uncertainty, never auto-retry.
                from ach_customizer_cache_manage import CacheManageError
                raise CacheManageError("uncertain",
                    "Native site changed during Cache operation; Recheck before next action",
                    recovery_id=result.get("recovery_id"))
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "manage_cache_policy", target=str(before["id"]),
                level="WARNING")
        except PermissionError as exc:
            return self._fail("cache_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("cache_manage", exc, request_id)

    def manage_wordpress_cache(self, args):
        """One primary-admin site click connects official Nginx Helper.

        This is a coordinated site setup, not a second cache purger.
        """
        request_id = uuid4().hex
        action = ""
        target = ""
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            action = self._argument(args, "wordpress_cache_action")
            if action not in ("inspect", "setup", "restore"):
                raise MonitorInputError("Unsupported WordPress Cache setup action")
            if action != "inspect" and self._argument(args, "approved") != "true":
                raise MonitorInputError("Select Connect or Disconnect for this site")
            from ach_customizer_cache_wordpress import inspect, setup, restore
            public, before, current_site = self._selected_native_website(args)
            target = str(before["id"])
            result = {"inspect": inspect, "setup": setup, "restore": restore}[action](
                before, public)
            if current_site() != before:
                from ach_customizer_cache_wordpress import WordpressCacheError
                raise WordpressCacheError(
                    "concurrency", "Native WordPress site identity changed; Recheck before retry",
                    result.get("recovery_id"))
            return self._activity_result(
                {"status": True, "request_id": request_id, **result},
                "websites", "manage_wordpress_cache", target=str(before["id"]),
                level="WARNING" if result["state"] == "Needs Review" else "INFO")
        except PermissionError as exc:
            return self._fail("wordpress_cache_authorization", exc, request_id)
        except Exception as exc:
            from ach_customizer_cache_wordpress import WordpressCacheError
            from ach_customizer_cache_manage import CacheManageError
            phase = exc.stage if isinstance(exc, (WordpressCacheError, CacheManageError)) else "unexpected"
            stage = ("wordpress_cache_" + action
                     if action in ("inspect", "setup", "restore")
                     else "wordpress_cache_request")
            return self._fail(stage, exc, request_id, target=target,
                              activity_stage=(action + ":" + phase) if action in ("inspect", "setup", "restore") else phase)

    def wp_settings_manage(self, args):
        """One selected WordPress site's debug or system scheduler policy."""
        request_id = uuid4().hex
        action = self._argument(args, "settings_action")
        target = ""
        try:
            self._status_primary_admin_post()
            self._require_enabled("site_inventory")
            if action not in ("recheck", "apply", "restore"):
                raise MonitorInputError("Unsupported WordPress settings action")
            if action != "recheck" and self._argument(args, "approved") != "true":
                raise MonitorInputError("Click Apply or Restore to authorize this exact website change")
            import public
            if public.get_webserver() != "nginx":
                raise MonitorInputError("WordPress settings adapter requires native Nginx site attribution")
            from ach_customizer_cache_wordpress import _site_lock
            from ach_customizer_wp_settings import manage, WPSettingsError
            from ach_customizer_state import _open_state_dir
            from ach_customizer_status_pages import _take_lock
            kind = self._argument(args, "settings_kind")
            desired = self._argument(args, "desired")
            raw_interval = self._argument(args, "interval")
            if kind == "cron":
                if (not isinstance(raw_interval, str) or
                        not re.fullmatch(r"[1-9][0-9]?", raw_interval)):
                    raise MonitorInputError("Select a valid system Cron minute step")
                interval = int(raw_interval)
            elif kind == "debug":
                interval = None
            elif kind == "xmlrpc":
                interval = None
                if desired != "block":
                    raise MonitorInputError("Select Block XML-RPC for this site")
            elif kind == "https":
                interval = None
                if desired != "https":
                    raise MonitorInputError("Select HTTPS URLs for this site")
            else:
                raise MonitorInputError("Unsupported WordPress setting")
            public, before, current_site = self._selected_native_website(args)
            target = str(before["id"])
            fd = _open_state_dir(_STATE_DIR)
            try:
                # Match the established WordPress Cache lock order: first
                # selected-site, then the shared settings/recovery lock.
                # Inverting the order can deadlock Cache setup/Restore.
                with _site_lock(before, _STATE_DIR):
                    lock = _take_lock(fd)
                    try:
                        if current_site() != before:
                            raise WPSettingsError("concurrency", "Native site changed before WordPress settings action")
                        if kind == "xmlrpc":
                            from ach_customizer_wp_xmlrpc import manage_xmlrpc
                            result = manage_xmlrpc(
                                action, before, public, data_fd=fd,
                                expected_source=self._argument(args, "expected_source_sha256"),
                                expected_recovery=self._argument(args, "expected_recovery_id"),
                            )
                        elif kind == "https":
                            from ach_customizer_wp_urls import manage_urls
                            result = manage_urls(
                                action, before, public, data_fd=fd,
                                expected_source=self._argument(args, "expected_source_sha256"),
                                expected_recovery=self._argument(args, "expected_recovery_id"),
                            )
                        else:
                            result = manage(
                                action, kind, before, public,
                                desired=desired, interval=interval, data_fd=fd,
                                expected_source=self._argument(args, "expected_source_sha256"),
                                expected_recovery=self._argument(args, "expected_recovery_id"),
                            )
                        if current_site() != before:
                            raise WPSettingsError(
                                "uncertain", "Native site identity changed during WordPress settings action",
                                result.get("recovery_id"))
                    finally:
                        os.close(lock)
            finally:
                os.close(fd)
            return self._activity_result(
                {"status": True, "request_id": request_id,
                 "settings_action": action, **result},
                "websites", "wp_settings_manage", target=target,
                level="WARNING" if result["state"] in (
                    "Recovery Required", "Drift", "Conflict") else "INFO",
            )
        except PermissionError as exc:
            return self._fail("wp_settings_authorization", exc, request_id, target=target)
        except MonitorInputError as exc:
            return self._fail("wp_settings_preflight", exc, request_id, target=target)
        except Exception as exc:
            from ach_customizer_wp_settings import WPSettingsError
            if isinstance(exc, WPSettingsError):
                response = self._fail("wp_settings_" + exc.stage,
                                      str(exc), request_id,
                                      diagnostic_error=exc, target=target)
                if exc.stage in ("uncertain", "recovery"):
                    response["recovery_required"] = True
                return response
            return self._fail("wp_settings_unexpected", exc, request_id, target=target)

    def fpm_policy_get(self, args):
        """Read operator-saved shared PHP intent, not a live/runtime verdict."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("php_fpm_file_preview")
            from ach_customizer_fpm_policy import get_policy
            version = self._argument(args, "php_version")
            result = get_policy(version, directory=_STATE_DIR)
            return self._activity_result(
                {"status": True, "operation_id": request_id, **result},
                "php_fpm", "fpm_policy_get", target=str(version), level="DEBUG")
        except PermissionError as exc:
            return self._fail("fpm_policy_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("fpm_policy_read", exc, request_id)

    def fpm_policy_recheck(self, args):
        """Compare saved service intent with fresh native file and site evidence.

        A recheck is not an Apply preview, a host mutation, or a runtime verdict.
        Never accept desired values from the caller on this route.
        """
        request_id = uuid4().hex
        version = self._argument(args, "php_version")
        try:
            self._status_primary_admin_post()
            self._require_enabled("php_fpm_file_preview")
            from ach_customizer_fpm_policy import get_policy
            before = get_policy(version, directory=_STATE_DIR)
            baseline = {
                "status": True, "schema": 1, "operation_id": request_id,
                "version": version, "policy_revision": before["policy_revision"],
                "monitor_revision": before["monitor_revision"],
                "saved": before["saved"], "desired": before["desired"],
                "read_only": True, "runtime_verified": False, "auto_enforce": False,
                "apply_eligible": False, "scope": "shared_service", "pool": "www",
                "changes": [], "shared_impact": None,
                "note": "Desired values compared against PHP files/defaults only; no host action.",
            }
            if not before["saved"]:
                return self._activity_result(
                    {**baseline, "state": "No Policy",
                     "reason": "No reviewed PHP-FPM desired policy is saved for this version."},
                    "php_fpm", "fpm_policy_recheck", target=str(version), level="INFO")

            # The existing Preview is the only owner of site-file attribution.
            # Compose its bounded observation, not a second ad-hoc parser.
            desired_args = {"php_version": version}
            for key, value in before["desired"].items():
                desired_args[key.removeprefix("pm.")] = value
            inspected = self.preview_php_fpm(desired_args)
            if inspected.get("status") is not True:
                raise MonitorInputError(
                    "Native PHP-FPM source inspection failed; see Activity and retry")
            after = get_policy(version, directory=_STATE_DIR)
            if before != after or inspected.get("fpm_saved_policy") != before:
                return self._activity_result(
                    {**baseline, "state": "Needs Review",
                     "reason": "Saved policy or Monitor changed during inspection; recheck again."},
                    "php_fpm", "fpm_policy_recheck", target=str(version), level="WARNING")
            if (inspected.get("state") not in ("File Match", "File Drift")
                    or not isinstance(inspected.get("fpm_observation_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}",
                                        inspected["fpm_observation_sha256"])):
                return self._activity_result(
                    {**baseline, "state": "Needs Review",
                     "reason": inspected.get("fpm_policy_reason") or
                     inspected.get("reason") or
                     "Native PHP source needs review; saved policy was not changed."},
                    "php_fpm", "fpm_policy_recheck", target=str(version), level="WARNING")
            impact = inspected["shared_impact"]
            # Reuse the guarded Manual Apply identity contract. Never issue
            # an Enable approval token for an unresolved native site map.
            impact_hash = None
            if (isinstance(impact, dict) and impact.get("state") == "File Mapping"
                    and impact.get("manual_apply_eligible") is True):
                from ach_customizer_fpm_workflow import ManualFpmWorkflow
                _, impact_hash = ManualFpmWorkflow()._impact(
                    None, {"version": version}, observed=impact)
            response = {
                **baseline, "state": inspected["state"], "reason": inspected.get("reason") or "",
                "changes": inspected["changes"], "shared_impact": impact,
                "impact_sha256": impact_hash,
                "source": inspected["source"],
                "source_observation_sha256": inspected["fpm_observation_sha256"],
                "note": ("Point-in-time desired-versus-file comparison only. "
                         "Shared site-file attribution is separately classified. "
                         "To restore, load the saved values then independently Preview, "
                         "Prepare, approve and Apply the guarded PHP 8.1/8.5 service."),
            }
            return self._activity_result(
                response, "php_fpm", "fpm_policy_recheck", target=str(version),
                level="INFO" if inspected["state"] == "File Drift" else "DEBUG")
        except PermissionError as exc:
            return self._fail("fpm_policy_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("fpm_policy_recheck", exc, request_id)

    def fpm_policy_save(self, args):
        """Store reviewed Monitor-only desired values; never touch PHP service."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            self._require_enabled("php_fpm_file_preview")
            from ach_customizer_fpm_policy import save_policy
            version = self._argument(args, "php_version")
            desired = {
                "pm.max_children": self._argument(args, "max_children"),
                "pm.start_servers": self._argument(args, "start_servers"),
                "pm.min_spare_servers": self._argument(args, "min_spare_servers"),
                "pm.max_spare_servers": self._argument(args, "max_spare_servers"),
                "pm.max_requests": self._argument(args, "max_requests"),
            }
            result = save_policy(
                "/www/server/php", version, desired, directory=_STATE_DIR,
                expected_revision=self._argument(args, "expected_policy_revision"),
                expected_monitor_revision=self._argument(args, "expected_monitor_revision"),
                expected_observation_sha256=self._argument(args, "expected_observation_sha256"),
                reviewed=self._argument(args, "reviewed"),
            )
            return self._activity_result(
                {"status": True, "operation_id": request_id, **result},
                "php_fpm", "fpm_policy_save", target=str(version))
        except PermissionError as exc:
            return self._fail("fpm_policy_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("fpm_policy_save", exc, request_id)

    def fpm_auto_manage(self, args):
        """Primary-admin-only auto repair of a previously reviewed PHP policy.

        Enablement is scoped to a saved desired [www] service profile.
        A root systemd worker owns later native post-terminal corrections;
        this HTTP method never directly mutates PHP configuration.
        """
        request_id = uuid4().hex
        action = self._argument(args, "auto_action", "inspect")
        version = self._argument(args, "php_version")
        try:
            self._status_primary_admin_post()
        except PermissionError as exc:
            return self._fail("fpm_auto_authorization", exc, request_id)
        try:
            from ach_customizer_fpm_auto import inspect
            import ach_customizer_fpm_watcher as watcher
            if action == "inspect":
                result = inspect(version, data_dir=_STATE_DIR)
            elif action == "enable":
                self._require_enabled("php_fpm_file_preview")
                if getattr(watcher, "ARMING_CONTRACT_VERSION", 0) != 2:
                    raise watcher.FpmWatcherError(
                        "Resident FPM watcher helper is stale after ZIP import; "
                        "do not enable until a separately approved panel-only reload")
                result = watcher.enable(
                    version, data_dir=_STATE_DIR,
                    expected_auto_revision=self._argument(args, "expected_auto_revision"),
                    expected_policy_revision=self._argument(args, "expected_policy_revision"),
                    expected_monitor_revision=self._argument(args, "expected_monitor_revision"),
                    expected_impact=self._argument(args, "expected_impact"),
                    reviewed=self._argument(args, "reviewed") == "true",
                )
            elif action == "disable":
                result = watcher.disable(
                    version, data_dir=_STATE_DIR,
                    expected_auto_revision=self._argument(args, "expected_auto_revision"),
                )
            else:
                raise MonitorInputError("Unsupported automatic PHP service action")
            result = {**result, **watcher.health()}
            if (action == "inspect"
                    and getattr(watcher, "ARMING_CONTRACT_VERSION", 0) != 2):
                result = {**result, "watcher_ready": False,
                          "watcher_status": ("Resident FPM watcher helper is stale; "
                                             "separately authorize a panel-only reload")}
            return self._activity_result(
                {"status": True, "schema": 1, "request_id": request_id, **result},
                "php_fpm", "fpm_auto_" + action,
                target=str(version), level="WARNING" if action != "inspect" else "DEBUG")
        except Exception as exc:
            from ach_customizer_fpm_auto import FpmAutoError
            from ach_customizer_fpm_watcher import FpmWatcherError
            if isinstance(exc, (FpmAutoError, FpmWatcherError, MonitorInputError)):
                return self._fail("fpm_auto_management", str(exc), request_id,
                                  diagnostic_error=exc)
            return self._fail("fpm_auto_management", exc, request_id)

    def preview_php_fpm(self, args):
        operation_id = uuid4().hex
        try:
            self._require_enabled("php_fpm_file_preview")
            version = self._argument(args, "php_version")
            desired = {
                "pm.max_children": self._argument(args, "max_children"),
                "pm.start_servers": self._argument(args, "start_servers"),
                "pm.min_spare_servers": self._argument(args, "min_spare_servers"),
                "pm.max_spare_servers": self._argument(args, "max_spare_servers"),
                "pm.max_requests": self._argument(args, "max_requests"),
            }
            from ach_customizer_fpm_policy import observe, get_policy
            policy_error = None
            try:
                result, evidence_sha256 = observe("/www/server/php", version, desired)
            except (MonitorInputError, OSError) as exc:
                # A strict policy-fingerprint failure must not erase the older
                # bounded file preview or accidentally permit saving policy.
                result = preview_php_fpm("/www/server/php", version, desired)
                evidence_sha256 = None
                policy_error = exc
            try:
                saved_policy = get_policy(version, directory=_STATE_DIR)
            except (StateError, MonitorInputError, OSError) as exc:
                # An unreadable/malformed policy store is a visible degraded
                # subfeature, not grounds to hide usable source drift.
                saved_policy = None
                if policy_error is None:
                    policy_error = exc
            # Keep file/default drift available even when site ownership cannot
            # be attributed. This second bounded read never authorizes Apply.
            impact_error = None
            if result.get("state") in ("File Match", "File Drift") and result.get("source"):
                try:
                    import public

                    impact = inspect_php_fpm_site_impact(public, version, result["source"])
                except Exception as exc:
                    impact_error = exc
                    impact = {
                        "schema": 1, "state": "Needs Review", "scope": "shared_service",
                        "version": version, "matched_sites": [], "unresolved_sites": [],
                        "site_count": 0, "other_php_sites_count": 0,
                        "reason": "Shared site attribution failed; review Activity for operation " + operation_id,
                        "note": "Read-only file attribution failed; no affected sites were inferred.",
                    }
            else:
                impact = {
                    "schema": 1, "state": "Needs Review", "scope": "shared_service",
                    "version": version, "matched_sites": [], "unresolved_sites": [],
                    "site_count": 0, "other_php_sites_count": 0,
                    "reason": "PHP-FPM file layout needs review before mapping websites",
                    "note": "No site-to-pool inference was attempted.",
                }
            response = {"status": True, "operation_id": operation_id,
                        **result, "shared_impact": impact,
                        "fpm_observation_sha256": evidence_sha256,
                        "fpm_saved_policy": saved_policy}
            if policy_error is not None:
                response["fpm_policy_reason"] = (
                    "Saved policy/source fingerprint unavailable; use Operation ID "
                    + operation_id + " in Activity. Existing source preview is read-only; "
                    "no policy save is authorized.")
            if impact_error is not None:
                response["stage"] = "php_fpm_site_impact"
            elif policy_error is not None:
                response["stage"] = "fpm_policy_observation"
            return self._activity_result(
                response, "php_fpm", "preview_php_fpm", target=str(version),
                error=impact_error or policy_error, level="WARNING" if policy_error else "INFO",
                allow_error_detail=False)
        except Exception as exc:
            return self._fail("php_fpm_file_preview", exc, operation_id)

    @staticmethod
    def _status_site_id(args):
        value = ach_customizer_main._argument(args, "site_id", "")
        if value in (None, ""):
            return None
        if type(value) is int:
            number = value
        elif isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10 and str(int(value)) == value:
            number = int(value)
        else:
            raise StatusPageError("Invalid aaPanel site ID")
        if not 1 <= number <= 2147483647:
            raise StatusPageError("Invalid aaPanel site ID")
        import public
        site = public.M("sites").where("id=?", (number,)).field("id,name,path,status").find()
        if not isinstance(site, dict) or int(site.get("id", 0)) != number or not site.get("name"):
            raise StatusPageError("Website not found in native aaPanel inventory")
        return number

    @staticmethod
    def _status_values(args):
        values = {key: ach_customizer_main._argument(args, key) for key in BRAND_KEYS}
        if values["footer_enabled"] == "true":
            values["footer_enabled"] = True
        elif values["footer_enabled"] == "false":
            values["footer_enabled"] = False
        return validate_brand(values)

    @staticmethod
    def _status_primary_admin_post():
        from flask import has_request_context, request, session
        if (not has_request_context() or request.method != "POST"
                or session.get("login") is not True
                or type(session.get("uid")) is not int or session["uid"] != 1
                or bool(session.get("tmp_login"))
                or "tmp_login_id" in session or "tmp_login_expire" in session):
            raise PermissionError("Full primary aaPanel administrator POST is required")

    def status_sites(self, args):
        """Admin-only bounded native site choices, independent of Monitor.

        Monitor disabling must not prevent choosing a real site for separately
        authorized Status Pages previews, inspections or branding preferences.
        Uses the same validated native discovery contract as get_sites, but
        never changes the Monitor state or host configuration.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            import public
            result = get_site_page(
                public,
                self._argument(args, "page", 1),
                self._argument(args, "page_size", 25),
            )
            response = {"status": True, "request_id": request_id,
                        "purpose": "status_site_selection", **result}
            return self._activity_result(
                response, "status_pages", "status_sites",
                target="page:" + str(result["page"]), level="DEBUG")
        except PermissionError as exc:
            return self._fail("status_sites_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("status_sites_read", exc, request_id)

    def status_preferences(self, args):
        """Read-only global and requested native-site branding; no file creation."""
        request_id = uuid4().hex
        try:
            site_id = self._status_site_id(args)
            state = read_preferences(_STATE_DIR)
            effective, source = select_brand(state, site_id)
            response = {
                "status": True, "request_id": request_id, "schema": 1,
                "revision": state["revision"], "global": state["global"],
                "effective": effective, "source": source, "site_id": site_id,
                "templates": list(PAGES), "locales": list(LOCALES),
                "mode": "Preview only", "apply_supported": False,
                "advisories": contrast_advisories(effective),
            }
            return self._activity_result(
                response, "status_pages", "status_preferences",
                target="site:" + str(site_id) if site_id else "global", level="DEBUG")
        except Exception as exc:
            return self._fail("status_preferences", exc, request_id)

    def status_preview(self, args):
        """Safe offline HTML preview; never touches a website or a service."""
        request_id = uuid4().hex
        try:
            site_id = self._status_site_id(args)
            template = self._argument(args, "template")
            locale = self._argument(args, "locale")
            state = read_preferences(_STATE_DIR)
            effective, source = select_brand(state, site_id)
            if self._argument(args, "brand_name") is not None:
                effective = self._status_values(args)
                source = "Unsaved preview"
            rendered = render_page(locale, template, effective)
            response = {
                "status": True, "request_id": request_id, "schema": 1,
                "revision": state["revision"], "site_id": site_id,
                "template": template, "locale": locale, "source": source,
                "mode": "Preview only", "apply_supported": False,
                **rendered,
            }
            return self._activity_result(
                response, "status_pages", "status_preview",
                target="site:" + str(site_id) if site_id else "global", level="DEBUG")
        except Exception as exc:
            return self._fail("status_preview", exc, request_id)

    def status_inspect(self, args):
        """Admin-only read-only file/source comparison for a single native site.

        No Nginx -T/HTTP/Apply or recovery promises are made. Do not expose
        filesystem diagnostics to lesser/temporary aaPanel identities.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            site_id = self._status_site_id(args)
            if site_id is None:
                raise StatusPageError("Select an existing native website")
            template = self._argument(args, "template")
            locale = self._argument(args, "locale")
            if template not in SUPPORTED_PAGES or locale not in LOCALES:
                raise StatusPageError("Site inspection supports only English/Persian 404/502")
            state = read_preferences(_STATE_DIR)
            effective, source = select_brand(state, site_id)
            if self._argument(args, "brand_name") is not None:
                effective = self._status_values(args)
                source = "Unsaved comparison"
            rendered = render_page(locale, template, effective)

            import public
            def native_record():
                return public.M("sites").where("id=?", (site_id,)).field(
                    "id,name,path,status").find()
            before = native_record()
            if not isinstance(before, dict) or int(before.get("id", 0)) != site_id:
                raise StatusPageError("Native site changed before inspection")
            inspected = inspect_site_files(
                before, template=template, locale=locale,
                rendered_sha256=rendered["rendered_sha256"],
                rendered_html=rendered["html"],
            )
            if native_record() != before:
                raise StatusPageError("Native site changed during inspection; recheck")
            response = {
                "status": True, "request_id": request_id, "revision": state["revision"],
                "selection_source": source, **inspected,
            }
            return self._activity_result(response, "status_pages", "status_inspect", target="site:" + str(site_id))
        except PermissionError as exc:
            return self._fail("status_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("status_inspect", exc, request_id)

    @staticmethod
    def _status_probe_selection(args, site_id):
        """Strict client-snapshot precondition; never a destination authority."""
        expected_key = ach_customizer_main._argument(args, "expected_site_key")
        serialized = ach_customizer_main._argument(args, "expected_site_snapshot")
        refresh = "Selected website may have changed; refresh native website inventory"
        if (not isinstance(expected_key, str) or not expected_key
                or len(expected_key) > 255 or
                not isinstance(serialized, str) or
                not serialized):
            raise StatusPageError(refresh)
        try:
            identity = json.loads(serialized)
        except (ValueError, TypeError):
            raise StatusPageError(refresh) from None
        if (not isinstance(identity, list) or len(identity) != 5 or
                type(identity[0]) is not int or identity[0] != site_id or
                not isinstance(identity[1], str) or identity[1] != expected_key or
                not isinstance(identity[2], str) or
                not isinstance(identity[3], str) or
                not isinstance(identity[4], list) or
                any(not isinstance(pair, list) or len(pair) != 2 or
                    not isinstance(pair[0], str) or
                    type(pair[1]) is not int or
                    not 1 <= pair[1] <= 65535
                    for pair in identity[4])):
            raise StatusPageError(refresh)
        return expected_key, identity, serialized

    def status_probe(self, args):
        """Primary-admin-triggered localhost HTTP/80 404 probe for a bound site.

        Deliberately not automatic or a generic host/proxy request feature.
        HTTP evidence cannot grant Apply/Restore eligibility.
        """
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            # During in-place native ZIP updates, a stale/missing new helper
            # must not prevent unrelated plugin endpoints from importing.
            try:
                from ach_customizer_status_probe import probe_site_404
            except ImportError as exc:
                raise StatusPageError(
                    "Status probe helper is outdated after plugin update. Restart "
                    "aaPanel panel service, reopen the plugin, and recheck."
                ) from exc
            try:
                site_id = self._status_site_id(args)
            except StatusPageError as exc:
                raise StatusPageError(
                    "Selected website is unavailable; refresh native website inventory"
                ) from exc
            if site_id is None:
                raise StatusPageError("Select an existing native website for an HTTP 404 probe")
            expected_key, expected_identity, serialized = self._status_probe_selection(args, site_id)
            template = self._argument(args, "template")
            delivery = self._argument(args, "site_delivery", "extension")
            if delivery not in ("extension", "file"):
                raise StatusPageError("Unsupported site status delivery mode")
            if template == "50x" and delivery != "extension":
                raise StatusPageError("Generic 50x requires the native Nginx extension mode")
            if (template not in ("404", "502", "50x") or
                    self._argument(args, "locale") not in LOCALES):
                raise StatusPageError("Select an English/Persian site 404 or 502")
            import public
            if public.get_webserver() != "nginx":
                raise StatusPageError("Only native Nginx HTTP/80 can be probed")
            def native_record():
                site = public.M("sites").where("id=?", (site_id,)).field(
                    "id,name,path,status").find()
                if (not isinstance(site, dict) or
                        type(site.get("id")) is not int or site["id"] != site_id):
                    raise StatusPageError("Native site identity changed during HTTP probe")
                # Read the exact native bound-domain set on both sides of the
                # request. Do not infer website routing from the site name.
                _bound_domains_for_sites(public, [site])
                return site

            before = native_record()
            if (before["name"] != expected_key or
                    native_site_snapshot(before) != expected_identity):
                raise StatusPageError(
                    "Selected website identity or domains changed; refresh native website inventory")
            preferences = read_preferences(_STATE_DIR)
            effective, source = select_brand(preferences, site_id)
            if self._argument(args, "brand_name") is not None:
                effective = self._status_values(args)
                source = "Unsaved probe selection"
            rendered = render_page(self._argument(args, "locale"), template, effective)
            if template == "404":
                observed = probe_site_404(
                    before, delivery=delivery, locale=self._argument(args, "locale"),
                    rendered_sha256=rendered["rendered_sha256"],
                    rendered_html=rendered["html"],
                )
            else:
                if delivery == "file":
                    from ach_customizer_status_site_file import preview_site_file_502
                    preview = preview_site_file_502
                else:
                    from ach_customizer_status_extension import preview_site_502, preview_site_50x
                    preview = preview_site_50x if template == "50x" else preview_site_502
                observed = preview(
                    before, locale=self._argument(args, "locale"),
                    rendered_sha256=rendered["rendered_sha256"],
                    rendered_html=rendered["html"],
                )
            if (native_record() != before or public.get_webserver() != "nginx"
                    or read_preferences(_STATE_DIR) != preferences):
                raise StatusPageError(
                    "Native website, branding or Nginx service changed during HTTP probe"
                )
            response = {
                "status": True, "request_id": request_id,
                "revision": preferences["revision"], "selection_source": source,
                "verified_site_snapshot": serialized,
                **observed,
            }
            return self._activity_result(
                response, "status_pages", "status_probe",
                target="site:" + str(site_id),
                level="INFO" if observed["state"] in ("HTTP Match", "Source Ready") else "WARNING",
            )
        except PermissionError as exc:
            return self._fail("status_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("status_probe", exc, request_id)

    def status_manage(self, args):
        """Guarded 404/502 extension or existing native site-file management.

        Extension mode retains its separately approved shared Nginx reload.
        File mode changes only the selected, preexisting site status HTML;
        no vendor VHost edit or service reload is performed.
        """
        request_id = uuid4().hex
        site_id = None
        action = self._argument(args, "site_action")
        try:
            self._status_primary_admin_post()
            if action not in ("apply", "restore", "recheck"):
                raise StatusPageError("Unsupported status file operation")
            if self._argument(args, "scope") != "site":
                raise StatusPageError("Only explicitly selected website scope supports status extensions")
            site_id = self._status_site_id(args)
            code = self._argument(args, "template")
            if site_id is None or code not in ("404", "502", "50x"):
                raise StatusPageError("Select a website and a supported 404/502/50x template")
            locale = self._argument(args, "locale")
            if locale not in LOCALES:
                raise StatusPageError("Unsupported Status Pages locale")
            delivery = self._argument(args, "site_delivery", "extension")
            if delivery not in ("extension", "file"):
                raise StatusPageError("Unsupported site status delivery mode")
            if code == "50x" and delivery != "extension":
                raise StatusPageError("Generic 50x requires the native Nginx extension mode")
            suffix = "_reload" if delivery == "extension" else "_site_file"
            if action == "apply" and self._argument(args, "site_approval") != (
                    "apply_exact_site_" + code + suffix):
                raise StatusPageError("Explicit site-specific status Apply approval required")
            if action == "restore" and self._argument(args, "site_approval") != (
                    "restore_exact_site_" + code + suffix):
                raise StatusPageError("Explicit site-specific saved recovery Restore approval required")
            expected_key, expected_identity, serialized = self._status_probe_selection(args, site_id)
            from ach_customizer_state import _open_state_dir, parse_revision
            from ach_customizer_status_pages import _load_at, _take_lock
            try:
                from ach_customizer_status_extension import manage_site_extension, ExtensionError
            except ImportError as exc:
                raise StatusPageError(
                    "Status extension manager not loaded after plugin update; restart panel and reopen"
                ) from exc
            if delivery == "file":
                try:
                    from ach_customizer_status_site_file import manage_site_file
                except ImportError as exc:
                    raise StatusPageError(
                        "Native site-file adapter not loaded; restart panel and recheck"
                    ) from exc
                manage = manage_site_file
            else:
                manage = manage_site_extension
            import public
            if public.get_webserver() != "nginx" or str(public.get_panel_version()).strip() != "8.0.7":
                raise StatusPageError("Native status extension adapter requires aaPanel 8.0.7 Nginx")

            def native_record():
                record = public.M("sites").where("id=?", (site_id,)).field(
                    "id,name,path,status").find()
                if (not isinstance(record, dict) or
                        type(record.get("id")) is not int or record["id"] != site_id):
                    raise StatusPageError("Native website changed; refresh selection")
                _bound_domains_for_sites(public, [record])
                return record

            before = native_record()
            if (before.get("name") != expected_key or
                    native_site_snapshot(before) != expected_identity):
                raise StatusPageError("Website identity/domains changed; reload site inventory")

            def unique_native_root():
                # A path shared by two native websites is not an isolated
                # status-page target. Confirm under a bounded native SQL read,
                # not from browser-provided inventory or VHost filename.
                rows = public.M("sites").where(
                    "path=?", (before["path"],)
                ).field("id,path").limit("0,2").select()
                if (not isinstance(rows, list) or len(rows) != 1 or
                        not isinstance(rows[0], dict) or
                        type(rows[0].get("id")) is not int or
                        rows[0]["id"] != site_id or
                        rows[0].get("path") != before["path"]):
                    raise StatusPageError(
                        "Native document root is shared or could not be proven exclusive; "
                        "site 404 write is unsafe"
                    )

            if action != "recheck":
                unique_native_root()
            # Stopped websites may still need their saved recovery ID.
            # Only a read-only Recheck is allowed; neither write path may
            # bypass the native running-site and current-route contract.
            if str(before.get("status")) != "1" and action != "recheck":
                raise StatusPageError("Selected website is stopped; only recovery Recheck is available")

            state_fd = _open_state_dir(_STATE_DIR)
            try:
                lock_fd = _take_lock(state_fd)
                try:
                    state = _load_at(state_fd)
                    revision = parse_revision(self._argument(args, "expected_revision"))
                    if state["revision"] != revision:
                        raise StatusPageError("Branding revision changed; recheck selected website")
                    effective, _source = select_brand(state, site_id)
                    if self._argument(args, "brand_name") is not None:
                        effective = self._status_values(args)
                    rendered = render_page(locale, code, effective)
                    if native_record() != before:
                        raise StatusPageError("Native website changed during 404 preflight")
                    if action != "recheck":
                        unique_native_root()
                    result = manage(
                        action, before, code=code, html=rendered["html"],
                        expected_current=self._argument(args, "expected_page_sha256"),
                        expected_vhost=self._argument(args, "expected_vhost_sha256"),
                        expected_render=self._argument(args, "expected_render_sha256"),
                        expected_recovery=self._argument(args, "expected_recovery_id"),
                        data_fd=state_fd,
                    )
                    try:
                        if action != "recheck":
                            unique_native_root()
                        if (native_record() != before or
                                public.get_webserver() != "nginx" or
                                str(public.get_panel_version()).strip() != "8.0.7"):
                            raise StatusPageError(
                                "Native site or webserver changed during 404 operation"
                            )
                    except StatusPageError as exc:
                        raise ExtensionError(
                            "uncertain",
                            "Native target changed; inspect saved status recovery before retrying",
                            recovery_id=result.get("recovery_id"),
                        ) from exc
                    response = {
                        "status": True, "request_id": request_id,
                        "operation_id": request_id, "schema": 1,
                        "site_action": action, "revision": revision,
                        "verified_site_snapshot": serialized,
                        "locale": locale, "template": code,
                        **result,
                    }
                finally:
                    os.close(lock_fd)
            finally:
                os.close(state_fd)
            return self._activity_result(
                response, "status_pages", "status_" + action,
                target="site:" + str(site_id),
                level="WARNING" if result["state"] in (
                    "Drift", "Recovery Required", "Needs Review", "Suspended",
                    "Orphan Backup", "Orphan Drift"
                ) else "INFO",
            )
        except PermissionError as exc:
            return self._fail("status_manage_authorization", exc, request_id)
        except StatusPageError as exc:
            step = getattr(exc, "stage", "preflight")
            cause = exc.__cause__
            if cause is not None:
                # Private operational diagnosis retains stage and errno while
                # avoiding arbitrary filesystem paths, bytes or credentials.
                logging.getLogger("ach_customizer").warning(
                    "Native Status extension failure: stage=%s request_id=%s "
                    "cause_class=%s errno=%s", step, request_id,
                    type(cause).__name__, getattr(cause, "errno", None))
            response = self._fail("status_manage_" + str(step), exc, request_id)
            if step in ("uncertain", "postcheck", "recovery"):
                response["recovery_required"] = True
            return response
        except Exception as exc:
            return self._fail("status_manage_unexpected", exc, request_id)

    def status_stopped(self, args):
        """Opt-in native SiteStop/Start HTTP503 rule with exact VHost recovery.

        This is deliberately separate from per-site extension status management:
        aaPanel disables server-scope includes when stopping a website.
        """
        request_id = uuid4().hex
        action = self._argument(args, "stopped_action")
        try:
            self._status_primary_admin_post()
            if (self._argument(args, "scope") != "site" or
                    self._argument(args, "template") != "stopped" or
                    action not in ("recheck", "apply", "restore")):
                raise StatusPageError("Choose a native website and stopped-site template")
            site_id = self._status_site_id(args)
            if site_id is None:
                raise StatusPageError("Select a validated native website")
            locale = self._argument(args, "locale")
            if locale not in LOCALES:
                raise StatusPageError("Select a supported stopped-site locale")
            if (action != "recheck" and self._argument(args, "stopped_approval") !=
                    action + "_exact_native_stopped503_reload"):
                raise StatusPageError("Explicit website-scoped stopped-site Nginx approval required")
            expected_key, expected_identity, serialized = self._status_probe_selection(
                args, site_id)
            from ach_customizer_state import _open_state_dir, parse_revision
            from ach_customizer_status_pages import _load_at, _take_lock
            from ach_customizer_status_stopped import manage_stopped
            from ach_customizer_status_extension import ExtensionError
            import public

            def compatible():
                return (public.get_webserver() == "nginx" and
                        str(public.get_panel_version()).strip() == "8.0.7")
            if not compatible():
                raise StatusPageError("Stopped-site adapter requires native aaPanel 8.0.7 Nginx")

            def native_record():
                record = public.M("sites").where("id=?", (site_id,)).field(
                    "id,name,path,status").find()
                if (not isinstance(record, dict) or
                        type(record.get("id")) is not int or record["id"] != site_id):
                    raise StatusPageError("Native website changed; refresh inventory")
                _bound_domains_for_sites(public, [record])
                return record

            before = native_record()
            if (before.get("name") != expected_key or
                    native_site_snapshot(before) != expected_identity):
                raise StatusPageError("Selected website changed; refresh native inventory")

            def unique_root():
                rows = public.M("sites").where("path=?", (before["path"],)).field(
                    "id,path").limit("0,2").select()
                if (not isinstance(rows, list) or len(rows) != 1 or
                        type(rows[0].get("id")) is not int or
                        rows[0]["id"] != site_id or rows[0].get("path") != before["path"]):
                    raise StatusPageError("Native document root is shared or unverified")

            if action == "apply" and str(before.get("status")) != "1":
                raise StatusPageError("Site must be running before arming HTTP 503; use Recheck")
            if action != "recheck":
                unique_root()
            fd = _open_state_dir(_STATE_DIR)
            try:
                lock = _take_lock(fd)
                try:
                    state = _load_at(fd)
                    revision = parse_revision(self._argument(args, "expected_revision"))
                    if revision != state["revision"]:
                        raise StatusPageError("Branding revision changed; Recheck")
                    effective, _ = select_brand(state, site_id)
                    if self._argument(args, "brand_name") is not None:
                        effective = self._status_values(args)
                    rendered = render_page(locale, "stopped", effective)
                    if native_record() != before or not compatible():
                        raise StatusPageError("Native site or webserver changed during preflight")
                    if action != "recheck":
                        unique_root()
                    result = manage_stopped(
                        action, before, rendered["html"], data_fd=fd,
                        expected_vhost=self._argument(args, "expected_vhost_sha256"),
                        expected_render=self._argument(args, "expected_render_sha256"),
                        expected_recovery=self._argument(args, "expected_recovery_id"),
                    )
                    try:
                        if action != "recheck":
                            unique_root()
                        if native_record() != before or not compatible():
                            raise StatusPageError("Native site/webserver changed during operation")
                    except StatusPageError as exc:
                        raise ExtensionError("uncertain", "Stopped-site outcome is uncertain; Recheck saved recovery",
                                             recovery_id=result.get("recovery_id")) from exc
                    response = {
                        "status": True, "request_id": request_id, "operation_id": request_id,
                        "stopped_action": action, "scope": "site", "template": "stopped",
                        "locale": locale, "revision": revision,
                        "verified_site_snapshot": serialized, **result,
                    }
                finally:
                    os.close(lock)
            finally:
                os.close(fd)
            return self._activity_result(
                response, "status_pages", "status_stopped_" + action,
                target="site:" + str(site_id),
                level="WARNING" if result["state"] in (
                    "Recovery Required", "Needs Review", "Conflict") else "INFO")
        except PermissionError as exc:
            return self._fail("status_stopped_authorization", exc, request_id)
        except StatusPageError as exc:
            step = str(getattr(exc, "stage", "preflight"))
            response = self._fail("status_stopped_" + step, exc, request_id)
            if step in ("uncertain", "postcheck", "recovery"):
                response["recovery_required"] = True
            return response
        except Exception as exc:
            return self._fail("status_stopped_unexpected", exc, request_id)

    def status_defaults(self, args):
        """Explicit global *new-site source* 404/502/defaultDoc management.

        Does not edit a running website, generated VHost or Nginx route.
        aaPanel copies the installed sources only for newly created sites.
        """
        request_id = uuid4().hex
        action = self._argument(args, "default_action")
        template = self._argument(args, "template")
        try:
            self._status_primary_admin_post()
            from ach_customizer_status_defaults import (
                DefaultSourceError, TEMPLATES, manage_default,
            )
            from ach_customizer_state import _open_state_dir, parse_revision
            from ach_customizer_status_pages import _load_at, _take_lock
            if (self._argument(args, "scope") != "global" or
                    self._argument(args, "site_id") not in (None, "")):
                raise StatusPageError("New-site defaults require global scope, not a website")
            if action not in ("recheck", "apply", "restore") or template not in TEMPLATES:
                raise StatusPageError("Select new-site, 404 or 502 default source")
            locale = self._argument(args, "locale")
            if locale not in LOCALES:
                raise StatusPageError("Unsupported new-site default language")
            if action != "recheck" and self._argument(args, "default_approval") != (
                    action + "_new_site_default_" + template):
                raise StatusPageError("Explicit selected new-site default approval required")
            import public
            def compatible():
                return (public.get_webserver() == "nginx" and
                        str(public.get_panel_version()).strip() == "8.0.7")
            if not compatible():
                raise StatusPageError("Native default source adapter requires aaPanel 8.0.7 Nginx")
            data_fd = _open_state_dir(_STATE_DIR)
            try:
                lock = _take_lock(data_fd)
                try:
                    state = _load_at(data_fd)
                    revision = parse_revision(self._argument(args, "expected_revision"))
                    if revision != state["revision"]:
                        raise StatusPageError("Global branding revision changed; Recheck first")
                    effective, _ = select_brand(state)
                    if self._argument(args, "brand_name") is not None:
                        effective = self._status_values(args)
                    rendered = render_page(locale, template, effective)
                    result = manage_default(
                        action, template, rendered["html"], data_fd=data_fd,
                        expected_current=self._argument(args, "expected_current_sha256"),
                        expected_render=self._argument(args, "expected_render_sha256"),
                        expected_recovery=self._argument(args, "expected_recovery_id"),
                    )
                    if not compatible():
                        raise DefaultSourceError(
                            "uncertain", "Panel version changed; Recheck managed default source",
                            result.get("recovery_id"))
                finally:
                    os.close(lock)
            finally:
                os.close(data_fd)
            response = {
                "status": True, "request_id": request_id, "operation_id": request_id,
                "default_action": action, "scope": "global",
                "site_id": None, "locale": locale, "revision": revision,
                **result,
            }
            return self._activity_result(
                response, "status_pages", "status_default_" + action,
                target="new-site-default:" + template,
                level="WARNING" if result["state"] in ("Drift", "Recovery Required")
                else "INFO",
            )
        except PermissionError as exc:
            return self._fail("status_default_authorization", exc, request_id)
        except StatusPageError as exc:
            return self._fail(
                "status_default_" + str(getattr(exc, "stage", "preflight")),
                exc, request_id)
        except Exception as exc:
            return self._fail("status_default_unexpected", exc, request_id)

    def status_unbound(self, args):
        """Explicit global HTTP/80 unbound Nginx route (never TLS or site stop)."""
        request_id = uuid4().hex
        action = self._argument(args, "unbound_action")
        try:
            self._status_primary_admin_post()
            if (self._argument(args, "scope") != "global" or
                    self._argument(args, "site_id") not in (None, "") or
                    self._argument(args, "template") != "unbound" or
                    action not in ("recheck", "apply", "restore")):
                raise StatusPageError("Select global/unbound and Recheck, Apply or Restore")
            locale = self._argument(args, "locale")
            if locale not in LOCALES:
                raise StatusPageError("Unsupported unbound page language")
            if (action != "recheck" and
                    self._argument(args, "unbound_approval") !=
                    action + "_global_http_unbound_reload"):
                raise StatusPageError("Explicit global HTTP/80 Nginx reload approval required")
            import public
            def compatible():
                return (public.get_webserver() == "nginx" and
                        str(public.get_panel_version()).strip() == "8.0.7")
            if not compatible():
                raise StatusPageError("HTTP unbound manager requires aaPanel 8.0.7 Nginx")
            from ach_customizer_state import _open_state_dir, parse_revision
            from ach_customizer_status_pages import _load_at, _take_lock
            try:
                from ach_customizer_status_unbound import manage_unbound, UnboundError
            except ImportError as exc:
                raise StatusPageError(
                    "Unbound status manager was not loaded after update; restart the panel"
                ) from exc

            def status_arg(name):
                value = self._argument(args, name)
                return int(value) if (isinstance(value, str) and
                                      re.fullmatch(r"[1-5][0-9]{2}", value)) else None

            fd = _open_state_dir(_STATE_DIR)
            try:
                lock = _take_lock(fd)
                try:
                    state = _load_at(fd)
                    revision = parse_revision(self._argument(args, "expected_revision"))
                    if revision != state["revision"]:
                        raise StatusPageError("Global branding revision changed; Recheck")
                    effective, _ = select_brand(state)
                    if self._argument(args, "brand_name") is not None:
                        effective = self._status_values(args)
                    rendered = render_page(locale, "unbound", effective)
                    result = manage_unbound(
                        action, rendered["html"], data_fd=fd,
                        expected_source=self._argument(args, "expected_source_sha256"),
                        expected_render=self._argument(args, "expected_render_sha256"),
                        expected_recovery=self._argument(args, "expected_recovery_id"),
                        expected_v4=status_arg("expected_ipv4_status"),
                        expected_v6=status_arg("expected_ipv6_status"),
                    )
                    if not compatible():
                        raise UnboundError(
                            "uncertain", "aaPanel/Nginx changed during HTTP unbound management",
                            result.get("recovery_id"),
                        )
                finally:
                    os.close(lock)
            finally:
                os.close(fd)
            response = {
                "status": True, "request_id": request_id,
                "operation_id": request_id, "unbound_action": action,
                "scope": "global", "site_id": None, "template": "unbound",
                "locale": locale, "revision": revision, **result,
            }
            return self._activity_result(
                response, "status_pages", "status_unbound_" + action,
                target="global-http:80", level="WARNING" if result["state"] in (
                    "Conflict", "Drift", "Needs Review", "Recovery Required"
                ) else "INFO",
            )
        except PermissionError as exc:
            return self._fail("status_unbound_authorization", exc, request_id)
        except StatusPageError as exc:
            stage = getattr(exc, "stage", "preflight")
            response = self._fail("status_unbound_" + str(stage), exc, request_id)
            if stage in ("uncertain", "postcheck", "recovery"):
                response["recovery_required"] = True
            return response
        except Exception as exc:
            return self._fail("status_unbound_unexpected", exc, request_id)

    def status_tls(self, args):
        """Opt-in unknown-SNI TLS rejection on existing HTTPS/443 sockets only."""
        request_id = uuid4().hex
        action = self._argument(args, "tls_action")
        try:
            self._status_primary_admin_post()
            if (self._argument(args, "scope") != "global" or
                    self._argument(args, "site_id") not in (None, "") or
                    self._argument(args, "template") != "unbound" or
                    action not in ("recheck", "apply", "restore")):
                raise StatusPageError("Select global/unbound for TLS/SNI management")
            if (action != "recheck" and
                    self._argument(args, "tls_approval") !=
                    action + "_global_tls_reject_reload"):
                raise StatusPageError("Explicit TLS/SNI Nginx reload approval required")
            import public
            if public.get_webserver() != "nginx":
                raise StatusPageError("TLS/SNI rejection requires native Nginx")
            from ach_customizer_state import _open_state_dir
            from ach_customizer_status_pages import _take_lock
            from ach_customizer_status_tls import manage_tls, TLSError

            fd = _open_state_dir(_STATE_DIR)
            try:
                lock = _take_lock(fd)
                try:
                    result = manage_tls(
                        action, data_fd=fd,
                        expected_source=self._argument(args, "expected_source_sha256"),
                        expected_recovery=self._argument(args, "expected_recovery_id"),
                    )
                    if public.get_webserver() != "nginx":
                        raise TLSError(
                            "uncertain", "aaPanel web server changed during TLS management",
                            recovery_id=result.get("recovery_id"),
                        )
                finally:
                    os.close(lock)
            finally:
                os.close(fd)
            response = {
                "status": True, "request_id": request_id,
                "operation_id": request_id, "tls_action": action,
                "scope": "global", "site_id": None, "template": "unbound",
                **result,
            }
            return self._activity_result(
                response, "status_pages", "status_tls_" + action,
                target="unknown-sni-https:443",
                level="WARNING" if result["state"] in (
                    "Conflict", "Drift", "Needs Review", "Recovery Required"
                ) else "INFO",
            )
        except PermissionError as exc:
            return self._fail("status_tls_authorization", exc, request_id)
        except StatusPageError as exc:
            stage = getattr(exc, "stage", "preflight")
            response = self._fail("status_tls_" + str(stage), exc, request_id)
            if stage in ("uncertain", "postcheck", "recovery"):
                response["recovery_required"] = True
            return response
        except Exception as exc:
            return self._fail("status_tls_unexpected", exc, request_id)

    def status_save(self, args):
        """Persist operator branding only; never apply to any website."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            scope = self._argument(args, "scope")
            site_id = self._status_site_id(args)
            action = self._argument(args, "branding_action")
            if (scope == "site") != (site_id is not None):
                raise StatusPageError("Selected scope and website do not match")
            from ach_customizer_state import parse_revision
            revision = parse_revision(self._argument(args, "expected_revision"))
            values = self._status_values(args) if action == "save" else None
            state, changed = update_preferences(
                scope=scope, site_id=site_id, action=action,
                expected_revision=revision, values=values, directory=_STATE_DIR,
            )
            effective, source = select_brand(state, site_id)
            response = {
                "status": True, "request_id": request_id,
                "schema": 1, "revision": state["revision"],
                "changed": changed, "scope": scope, "site_id": site_id,
                "source": source, "effective": effective,
                "advisories": contrast_advisories(effective),
                "message": (
                    "Branding preferences reset for this scope; no site files or services changed"
                    if action == "reset" else
                    "Branding preferences saved; no site files or services changed"
                ),
            }
            audit_action = "status_reset" if action == "reset" else "status_save"
            return self._activity_result(response, "status_pages", audit_action, target=("site:" + str(site_id)) if site_id else "global")
        except PermissionError as exc:
            return self._fail("status_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("status_settings", exc, request_id)

    @staticmethod
    def _fpm_native_audit(action, response, request_id, version):
        """Best-effort native aaPanel activity log with explicit delivery status.

        aaPanel 8.0.7 `public.WriteLog` returns the SQLite log row ID or None.
        Logging MUST NOT turn a successfully applied host change into a
        reported failure, or hide an uncertain mutating outcome. Avoid
        request payloads, passwords, sessions and exception tracebacks.
        """
        record = {
            "schema": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": "primary_admin_action_or_rejected_attempt",
            "action": "fpm_" + action,
            "target": ("PHP" + version + "-www-shared-service"
                       if version in ("81", "85") else "PHP-unknown-shared-service"),
            "request_id": request_id,
            "success": response["status"] is True,
            "result": response.get("state") if response["status"] else response.get("stage"),
            "recovery_operation_id": response.get("operation_id") if response["status"] else None,
        }
        try:
            import public
            outcome = public.WriteLog("ACh Customizer", json.dumps(record, sort_keys=True), not_web=True)
            if outcome is not None and outcome is not False:
                return True
            logging.getLogger("ach_customizer").warning(
                "Native PHP-FPM audit persistence returned no row: %s %s",
                record["action"], request_id)
        except (ImportError, AttributeError) as exc:
            logging.getLogger("ach_customizer").warning(
                "Native PHP-FPM audit unavailable: %s %s (%s)",
                record["action"], request_id, type(exc).__name__)
        except Exception:
            logging.getLogger("ach_customizer").exception(
                "Native PHP-FPM audit failed: %s %s", record["action"], request_id)
        return False

    def _fpm_action(self, action, args):
        """Regular native plugin POST action; the workflow rechecks full-admin auth."""
        request_id = uuid4().hex
        try:
            result = getattr(ManualFpmWorkflow(), action)(args)
            # A successful Apply's operation_id is the durable recovery ID;
            # request_id is a separate one-request diagnostic identifier.
            response = {"status": True, "request_id": request_id, **result}
        except FpmApplyError as exc:
            response = self._fail(exc.stage, exc, request_id)
        except Exception as exc:
            # Keep the real type for authorized troubleshooting without exposing
            # privileged exception content to the browser or activity history.
            response = self._fail(
                "fpm_" + action, "Unexpected manual PHP-FPM error; no automatic retry",
                request_id, diagnostic_error=exc)
        if action in ("apply", "rollback"):
            response["audit_logged"] = self._fpm_native_audit(
                action, response, request_id, self._argument(args, "php_version"))
            if not response["audit_logged"]:
                response["audit_warning"] = "aaPanel activity-log persistence was not confirmed"
        if response["status"] is True:
            version = self._argument(args, "php_version")
            target = "PHP" + version + "-www-shared-service" if version in ("81", "85") else "PHP-unknown-shared-service"
            self._activity_result(response, "php_fpm", "fpm_" + action, target=target)
        return response

    def fpm_prepare(self, args):
        return self._fpm_action("prepare", args)

    def fpm_apply(self, args):
        return self._fpm_action("apply", args)

    def fpm_recovery(self, args):
        return self._fpm_action("recovery", args)

    def fpm_rollback(self, args):
        return self._fpm_action("rollback", args)
