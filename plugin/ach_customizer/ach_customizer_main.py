"""aaPanel legacy authenticated plug-in endpoint: monitor-only initial foundation.

Do not implement `_check`: according to aaPanel's official demo, declaring it
opts the plug-in into separate dynamic routing that does not inherit panel auth.
"""

import os
import sys
from uuid import uuid4

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)
# Match the documented aaPanel module lookup without changing its process cwd.
_PANEL_CLASS_DIR = "/www/server/panel/class"
if os.path.isdir(_PANEL_CLASS_DIR) and _PANEL_CLASS_DIR not in sys.path:
    sys.path.append(_PANEL_CLASS_DIR)

from ach_customizer_monitor import MonitorInputError, get_site_page, preview_php_fpm


class ach_customizer_main:
    @staticmethod
    def _argument(args, key, default=None):
        if isinstance(args, dict):
            return args.get(key, default)
        return getattr(args, key, default)

    @staticmethod
    def _fail(stage, error, operation_id):
        return {"status": False, "stage": stage, "msg": str(error)[:300], "operation_id": operation_id}

    def get_overview(self, args):
        return {
            "status": True,
            "mode": "Monitor",
            "enforcement": False,
            "overall_enable_control": "Pending native lifecycle acceptance",
            "modules": {"site_inventory": "Monitor", "php_fpm_file_preview": "Monitor"},
            "notice": "Read-only development candidate. No host configuration changes or background jobs.",
        }

    def get_sites(self, args):
        operation_id = uuid4().hex
        try:
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
