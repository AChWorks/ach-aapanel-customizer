"""Native authenticated aaPanel plugin endpoints for safe Monitor controls.

Do NOT add a `_check` endpoint: aaPanel's dynamic plugin route bypasses the
ordinary inherited panel authentication boundary.
"""

import os
import sys
from uuid import uuid4

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
_PANEL_CLASS_DIR = "/www/server/panel/class"
if os.path.isdir(_PANEL_CLASS_DIR) and _PANEL_CLASS_DIR not in sys.path:
    sys.path.append(_PANEL_CLASS_DIR)

from ach_customizer_monitor import MonitorInputError, get_site_page, preview_php_fpm
from ach_customizer_state import DATA_DIR, StateError, read_state, set_enabled

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
                "Read-only Monitor controls; no host configuration changes or background jobs."
                if active else
                "Monitoring is disabled. Websites and services keep running unchanged."
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
            return {"status": True, "operation_id": operation_id, **result}
        except Exception as exc:
            return self._fail("php_fpm_file_preview", exc, operation_id)
