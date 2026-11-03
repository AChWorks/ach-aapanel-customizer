"""Safe install/uninstall event bridge for aaPanel's native plugin lifecycle hook.

This source file is replaceable by aaPanel; activity data is not. The native
CLI uses fixed paths and allowlisted event names, never user-provided targets.
Activity persistence failure is reported but must not change lifecycle effects.
"""
from __future__ import annotations

import sys
from uuid import uuid4

from ach_customizer_activity import append_activity, record
from ach_customizer_state import DATA_DIR

# action, stage, outcome, severity, error classification
_EVENTS = {
    "install_registered": ("install", "install_hook", "registered", "INFO", ""),
    "uninstall_icon_removed": ("uninstall", "icon_cleanup", "removed", "INFO", ""),
    "uninstall_icon_preserved": (
        "uninstall", "icon_cleanup", "preserved", "WARNING", "IconCleanupFailed"),
    "uninstall_cleanup_unavailable": (
        "uninstall", "icon_cleanup", "unavailable", "WARNING", "IconCleanupUnavailable"),
}


def record_lifecycle(event, *, directory=DATA_DIR):
    """Append one canonical native-hook event; fail closed on unknown names."""
    if event not in _EVENTS:
        raise ValueError("Unsupported lifecycle event")
    action, stage, outcome, level, error_class = _EVENTS[event]
    entry = record(
        level=level, module="lifecycle", action=action, stage=stage,
        outcome=outcome, operation_id=uuid4().hex, target="ach_customizer",
        error_class=error_class,
        detail="Plugin source may be replaced; persistent state and recovery are retained"
        if action == "uninstall" else "Native plugin install hook returned",
    )
    return entry, append_activity(directory, entry)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in _EVENTS:
        print("ACh Customizer: invalid lifecycle event argument", file=sys.stderr)
        return 2
    try:
        event, persisted = record_lifecycle(args[0])
    except Exception as exc:
        # Do not echo arbitrary privileged exception details or state paths.
        print("ACh Customizer: lifecycle Activity persistence unconfirmed (" +
              type(exc).__name__ + ")", file=sys.stderr)
        return 1
    if persisted is None:
        print("ACh Customizer: lifecycle Activity skipped by configured level")
    else:
        print("ACh Customizer: lifecycle Activity recorded: " + event["operation_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
