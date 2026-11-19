"""Operator-controlled systemd path+timer for a bounded native WP lifecycle.

Default installation creates no units. Enable/disable runs only through the
primary-admin aaPanel POST; the standalone uninstall path is best-effort and
never overwrites foreign units. No vendor files are patched.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import ach_customizer_wp_terminal as worker

UNIT_ROOT = Path("/etc/systemd/system")
UNIT = "ach-customizer-wp-terminal"
PANEL_PYTHON = "/www/server/panel/pyenv/bin/python3"
PLUGIN_WORKER = "/www/server/panel/plugin/ach_customizer/ach_customizer_wp_terminal.py"
PATH_CONTENT = """[Unit]
Description=ACh aaPanel Customizer native WordPress progress watcher

[Path]
PathChanged=/tmp/wp_aapanel_deploy.log
Unit=ach-customizer-wp-terminal.service

[Install]
WantedBy=multi-user.target
"""
TIMER_CONTENT = """[Unit]
Description=ACh aaPanel Customizer native WordPress terminal fallback

[Timer]
OnBootSec=30s
OnUnitInactiveSec=30s
Unit=ach-customizer-wp-terminal.service

[Install]
WantedBy=timers.target
"""
SERVICE_CONTENT = """[Unit]
Description=ACh aaPanel Customizer guarded native WordPress terminal reconciliation

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
PrivateTmp=no
ExecStart=/www/server/panel/pyenv/bin/python3 /www/server/panel/plugin/ach_customizer/ach_customizer_wp_terminal.py run
"""
UNITS = {"path": PATH_CONTENT, "timer": TIMER_CONTENT, "service": SERVICE_CONTENT}


class WatcherError(RuntimeError):
    pass


def _run(*argv):
    proc = subprocess.run(["systemctl", *argv], capture_output=True, text=True, timeout=20)
    if proc.returncode:
        raise WatcherError("Native WordPress watcher service action failed: " + argv[0])


def _trusted_unit(path, expected):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o644
                or info.st_size != len(expected.encode())):
            raise WatcherError("Untrusted native WordPress watcher unit")
        if os.read(fd, 8192) != expected.encode():
            raise WatcherError("Foreign native WordPress watcher unit; refusing overwrite")
        return True
    finally:
        os.close(fd)


def _ensure_units(root=UNIT_ROOT):
    if (not root.is_dir() or root.is_symlink() or root.stat().st_uid != os.geteuid()
            or root.stat().st_mode & 0o022):
        raise WatcherError("Unsupported systemd unit directory")
    for extension, content in UNITS.items():
        file = root / (UNIT + "." + extension)
        if _trusted_unit(file, content):
            continue
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(file, flags, 0o644)
        try:
            with os.fdopen(fd, "wb", closefd=False) as out:
                out.write(content.encode())
                out.flush()
            os.fchmod(fd, 0o644)
            os.fsync(fd)
        finally:
            os.close(fd)
    folder = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def _disable_services():
    # Explicit disable succeeds even if the unit has already been stopped.
    for extension in ("path", "timer"):
        _run("disable", "--now", UNIT + "." + extension)


def health(*, unit_root=UNIT_ROOT):
    """Read-only unit/source readiness; never infer real event timing."""
    try:
        worker._native_supported()
    except (OSError, worker.TerminalError):
        return {"watcher_ready": False, "watcher_status": "Unsupported native source",
                "watcher_source_verified": False}
    try:
        for ext in ("path", "timer", "service"):
            if not _trusted_unit(unit_root / (UNIT + "." + ext), UNITS[ext]):
                return {"watcher_ready": False, "watcher_status": "Watcher units not installed",
                        "watcher_source_verified": True}
        for ext in ("path", "timer"):
            proc = subprocess.run(["systemctl", "is-active", "--quiet", UNIT + "." + ext],
                                  capture_output=True, timeout=4)
            if proc.returncode:
                return {"watcher_ready": False, "watcher_status": "Watcher units inactive",
                        "watcher_source_verified": True}
        return {"watcher_ready": True, "watcher_status": "Units active; native event timing not yet certified",
                "watcher_source_verified": True}
    except (OSError, subprocess.TimeoutExpired, WatcherError):
        return {"watcher_ready": False, "watcher_status": "Watcher service state unverified",
                "watcher_source_verified": True}


def enable(*, data_dir=worker.DATA_DIR, unit_root=UNIT_ROOT):
    worker._native_supported()
    if not Path(PANEL_PYTHON).exists() or not Path(PLUGIN_WORKER).is_file():
        raise WatcherError("Native panel Python and deployed plugin worker are required")
    _ensure_units(unit_root)
    try:
        _run("daemon-reload")
        _run("enable", "--now", UNIT + ".path", UNIT + ".timer")
        _run("is-active", UNIT + ".path")
        _run("is-active", UNIT + ".timer")
        return worker.set_enabled(True, data_dir=data_dir)
    except Exception:
        # Even if activation reached systemd but readiness failed, clear the
        # persistent policy first and attempt unit deactivation. Never mask
        # either failure as an enabled, verified watcher.
        worker.set_enabled(False, data_dir=data_dir)
        try:
            _disable_services()
        except WatcherError:
            import logging
            logging.getLogger("ach_customizer").exception(
                "Native WP systemd activation cleanup unconfirmed")
        raise


def disable(*, data_dir=worker.DATA_DIR):
    # Policy is turned off before touching service manager; even if systemd is
    # inaccessible, an already-started worker will refuse to edit.
    result = worker.set_enabled(False, data_dir=data_dir)
    _disable_services()
    return result


def uninstall(*, data_dir=worker.DATA_DIR, unit_root=UNIT_ROOT):
    worker.set_enabled(False, data_dir=data_dir)
    _disable_services()
    for extension, content in UNITS.items():
        file = unit_root / (UNIT + "." + extension)
        if _trusted_unit(file, content):
            file.unlink()
    _run("daemon-reload")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["uninstall"]:
        print("Usage: ach_customizer_wp_watcher.py uninstall", file=sys.stderr)
        return 2
    try:
        uninstall()
        return 0
    except Exception as exc:
        print("ACh WP watcher cleanup needs review: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
