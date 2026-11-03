"""Native aaPanel plugin endpoints for Monitor and guarded manual PHP-FPM change.

Do NOT add a `_check` endpoint: aaPanel's dynamic plugin route bypasses the
ordinary inherited panel authentication boundary.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
_PANEL_CLASS_DIR = "/www/server/panel/class"
if os.path.isdir(_PANEL_CLASS_DIR) and _PANEL_CLASS_DIR not in sys.path:
    sys.path.append(_PANEL_CLASS_DIR)

from ach_customizer_monitor import (
    MonitorInputError, get_site_page, inspect_php_fpm_site_impact, preview_php_fpm,
)
from ach_customizer_fpm_apply import FpmApplyError
from ach_customizer_fpm_workflow import ManualFpmWorkflow
from ach_customizer_state import DATA_DIR, StateError, read_state, set_enabled
from ach_customizer_status_pages import (
    DEFAULT_BRAND, BRAND_KEYS, PAGES, LOCALES, StatusPageError,
    read_preferences, render_page, select_brand, update_preferences, validate_brand,
)

_STATE_DIR = DATA_DIR


class ach_customizer_main:
    @staticmethod
    def _argument(args, key, default=None):
        if isinstance(args, dict):
            return args.get(key, default)
        return getattr(args, key, default)

    @staticmethod
    def _fail(stage, error, operation_id):
        return {"status": False, "stage": stage, "msg": str(error)[:300], "operation_id": operation_id}

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
            "overall_enabled": active,
            "modules_enabled": dict(state["modules"]),
            "modules": {
                name: "Monitor" if active and enabled else "Disabled"
                for name, enabled in state["modules"].items()
            },
            "overall_enable_control": "Plugin-owned Monitor switch only",
            "notice": (
                "Monitor controls are read-only; PHP 8.5 Manual Apply requires separate admin approval. No background enforcement."
                if active else
                "Monitor disabled; existing services stay running. Previously applied manual FPM changes require explicit recovery."
            ),
        }

    def get_overview(self, args):
        operation_id = uuid4().hex
        try:
            return self._overview(read_state(_STATE_DIR), operation_id)
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
            return {**self._overview(state, operation_id), "changed": changed}
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
            return {"status": True, "operation_id": operation_id, **result}
        except Exception as exc:
            return self._fail("website_discovery", exc, operation_id)

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
            result = preview_php_fpm("/www/server/php", version, desired)
            # Keep file/default drift available even when site ownership cannot
            # be attributed. This second bounded read never authorizes Apply.
            if result.get("state") in ("File Match", "File Drift") and result.get("source"):
                try:
                    import public

                    impact = inspect_php_fpm_site_impact(public, version, result["source"])
                except Exception as exc:
                    impact = {
                        "schema": 1, "state": "Needs Review", "scope": "shared_service",
                        "version": version, "matched_sites": [], "unresolved_sites": [],
                        "site_count": 0, "other_php_sites_count": 0,
                        "reason": ("Shared site attribution unavailable: " + str(exc))[:250],
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
            return {"status": True, "operation_id": operation_id,
                    **result, "shared_impact": impact}
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

    def status_preferences(self, args):
        """Read-only global and requested native-site branding; no file creation."""
        request_id = uuid4().hex
        try:
            site_id = self._status_site_id(args)
            state = read_preferences(_STATE_DIR)
            effective, source = select_brand(state, site_id)
            return {
                "status": True, "request_id": request_id, "schema": 1,
                "revision": state["revision"], "global": state["global"],
                "effective": effective, "source": source, "site_id": site_id,
                "templates": list(PAGES), "locales": list(LOCALES),
                "mode": "Preview only", "apply_supported": False,
            }
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
            return {
                "status": True, "request_id": request_id, "schema": 1,
                "revision": state["revision"], "site_id": site_id,
                "template": template, "locale": locale, "source": source,
                "mode": "Preview only", "apply_supported": False,
                **rendered,
            }
        except Exception as exc:
            return self._fail("status_preview", exc, request_id)

    def status_save(self, args):
        """Persist operator branding only; never apply to any website."""
        request_id = uuid4().hex
        try:
            self._status_primary_admin_post()
            scope = self._argument(args, "scope")
            site_id = self._status_site_id(args)
            action = self._argument(args, "action")
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
            return {
                "status": True, "request_id": request_id,
                "schema": 1, "revision": state["revision"],
                "changed": changed, "scope": scope, "site_id": site_id,
                "source": source, "effective": effective,
                "message": "Branding preferences saved; no site files or services changed",
            }
        except PermissionError as exc:
            return self._fail("status_authorization", exc, request_id)
        except Exception as exc:
            return self._fail("status_settings", exc, request_id)

    @staticmethod
    def _fpm_native_audit(action, response, request_id):
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
            "target": "PHP85-www-shared-service",
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
        except Exception:
            # Do not send arbitrary privileged exception details to a browser.
            response = self._fail("fpm_" + action, "Unexpected manual PHP-FPM error; no automatic retry", request_id)
        if action in ("apply", "rollback"):
            response["audit_logged"] = self._fpm_native_audit(action, response, request_id)
            if not response["audit_logged"]:
                response["audit_warning"] = "aaPanel activity-log persistence was not confirmed"
        return response

    def fpm_prepare(self, args):
        return self._fpm_action("prepare", args)

    def fpm_apply(self, args):
        return self._fpm_action("apply", args)

    def fpm_recovery(self, args):
        return self._fpm_action("recovery", args)

    def fpm_rollback(self, args):
        return self._fpm_action("rollback", args)
