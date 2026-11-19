"""Operator-enabled source-pinned FPM auto repair systemd lifecycle.

No new timer/path/service is registered during normal plugin install.
The separate service allows PHP-FPM auto repair without enabling the
read-only WordPress Hosts witness or modifying aaPanel vendor files.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import ach_customizer_fpm_auto as worker
import ach_customizer_wp_terminal as native
from ach_customizer_state import DATA_DIR

UNIT_ROOT = Path("/etc/systemd/system")
UNIT = "ach-customizer-fpm-auto"
PANEL_PYTHON = "/www/server/panel/pyenv/bin/python3"
PLUGIN_WORKER = "/www/server/panel/plugin/ach_customizer/ach_customizer_fpm_auto.py"
PATH_CONTENT = """[Unit]
Description=ACh aaPanel Customizer native WordPress FPM repair event path

[Path]
PathChanged=/tmp/wp_aapanel_deploy.log
Unit=ach-customizer-fpm-auto.service

[Install]
WantedBy=multi-user.target
"""
TIMER_CONTENT = """[Unit]
Description=ACh aaPanel Customizer terminal PHP-FPM repair fallback

[Timer]
OnBootSec=30s
OnUnitInactiveSec=30s
Unit=ach-customizer-fpm-auto.service

[Install]
WantedBy=timers.target
"""
SERVICE_CONTENT = """[Unit]
Description=ACh aaPanel Customizer verified native WordPress PHP-FPM repair

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
PrivateTmp=no
ExecStart=/www/server/panel/pyenv/bin/python3 /www/server/panel/plugin/ach_customizer/ach_customizer_fpm_auto.py run
"""
UNITS = {"path": PATH_CONTENT, "timer": TIMER_CONTENT, "service": SERVICE_CONTENT}


class FpmWatcherError(RuntimeError):
    pass


def _run(*argv):
    proc = subprocess.run(["systemctl", *argv], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise FpmWatcherError("PHP-FPM repair systemd action failed: " + argv[0])


def _trusted(path, expected):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o644
                or info.st_size != len(expected.encode())):
            raise FpmWatcherError("Untrusted PHP-FPM repair watcher unit")
        if os.read(fd, 8192) != expected.encode():
            raise FpmWatcherError("Foreign PHP-FPM repair watcher unit")
        return True
    finally:
        os.close(fd)


def _ensure_units(root=UNIT_ROOT):
    if (not root.is_dir() or root.is_symlink() or root.stat().st_uid != os.geteuid()
            or root.stat().st_mode & 0o022):
        raise FpmWatcherError("Unsupported systemd unit directory")
    for ext, content in UNITS.items():
        path = root / (UNIT + "." + ext)
        if _trusted(path, content):
            continue
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(content.encode())
                stream.flush()
            os.fchmod(fd, 0o644)
            os.fsync(fd)
        finally:
            os.close(fd)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stop():
    # Emergency Disable must still work on a never-activated or already
    # removed watcher. Do not attempt to manage foreign systemd units.
    for ext in ("path", "timer"):
        if _trusted(UNIT_ROOT / (UNIT + "." + ext), UNITS[ext]):
            _run("disable", "--now", UNIT + "." + ext)


def health(*, unit_root=UNIT_ROOT):
    try:
        native._native_supported()
        for ext, data in UNITS.items():
            if not _trusted(unit_root / (UNIT + "." + ext), data):
                return {"watcher_ready": False, "watcher_status": "FPM repair units absent"}
        for ext in ("path", "timer"):
            result = subprocess.run(["systemctl", "is-active", "--quiet", UNIT + "." + ext],
                                    capture_output=True, timeout=5)
            if result.returncode:
                return {"watcher_ready": False, "watcher_status": "FPM repair watcher inactive"}
        return {"watcher_ready": True, "watcher_status": "FPM repair watcher active"}
    except Exception:
        return {"watcher_ready": False, "watcher_status": "FPM repair watcher unavailable"}


def enable(version, *, data_dir=DATA_DIR, expected_auto_revision,
           expected_policy_revision, expected_monitor_revision,
           expected_impact, reviewed):
    native._native_supported()
    if not Path(PANEL_PYTHON).is_file() or not Path(PLUGIN_WORKER).is_file():
        raise FpmWatcherError("Native panel Python and installed auto repair helper are required")
    existing = worker.any_enabled(data_dir=data_dir)
    _ensure_units()
    try:
        _run("daemon-reload")
        _run("enable", "--now", UNIT + ".path", UNIT + ".timer")
        _run("is-active", UNIT + ".path")
        _run("is-active", UNIT + ".timer")
        return worker.set_enabled(version, True, data_dir=data_dir,
                                  expected_auto_revision=expected_auto_revision,
                                  expected_policy_revision=expected_policy_revision,
                                  expected_monitor_revision=expected_monitor_revision,
                                  expected_impact=expected_impact,
                                  reviewed=reviewed)
    except Exception:
        if not existing and not worker.any_enabled(data_dir=data_dir):
            try:
                _stop()
            except FpmWatcherError:
                import logging
                logging.getLogger("ach_customizer").exception(
                    "FPM auto repair watcher cleanup failed")
        raise


def disable(version, *, data_dir=DATA_DIR, expected_auto_revision):
    # Persist an independent revocation before waiting on the shared lock.
    # A host reload can hold that lock beyond the normal 3-second timeout.
    # The owned timer/worker drains an acknowledged Pending Disable without
    # a second operator click; never stop the timer before consumption.
    result = worker.request_disable(
        version, data_dir=data_dir, expected_auto_revision=expected_auto_revision)
    if result["pending_disable"]:
        try:
            # An externally deactivated path/timer must not strand a durable
            # revocation after a long-running transaction. Re-arm only the
            # trusted retry timer until the worker commits policy-off.
            _ensure_units()
            _run("daemon-reload")
            _run("enable", "--now", UNIT + ".timer")
            _run("start", "--no-block", UNIT + ".service")
            return {**result, "wakeup_ready": True}
        except FpmWatcherError:
            import logging
            logging.getLogger("ach_customizer").exception(
                "Durable PHP-FPM disable pending; retry timer/wakeup unavailable")
            return {**result, "wakeup_ready": False}
    if (not worker.any_enabled(data_dir=data_dir)
            and not worker.any_pending_disable(data_dir=data_dir)):
        _stop()
    return result


def uninstall(*, data_dir=DATA_DIR, unit_root=UNIT_ROOT):
    # Enforce policy-off before removing units or plugin source.
    for version in worker.recovery.SUPPORTED_VERSIONS:
        status = worker.inspect(version, data_dir=data_dir)
        if status["enabled"] or status["pending_disable"]:
            status = worker.request_disable(
                version, data_dir=data_dir,
                expected_auto_revision=status["state_revision"])
            if status["enabled"] or status["pending_disable"]:
                raise FpmWatcherError(
                    "PHP-FPM automatic disable pending; preserve installed worker until complete")
    if (worker.any_enabled(data_dir=data_dir)
            or worker.any_pending_disable(data_dir=data_dir)):
        raise FpmWatcherError(
            "PHP-FPM automatic safe-stop is incomplete; preserve the owned retry worker")
    _stop()
    for ext, content in UNITS.items():
        path = unit_root / (UNIT + "." + ext)
        if _trusted(path, content):
            path.unlink()
    _run("daemon-reload")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["uninstall"]:
        print("Usage: ach_customizer_fpm_watcher.py uninstall", file=sys.stderr)
        return 2
    try:
        uninstall()
        return 0
    except Exception as exc:
        print("ACh FPM repair watcher cleanup needs review: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
