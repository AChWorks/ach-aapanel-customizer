"""Bounded native plugin file cleanup (never configuration or recovery).

Traverse from an owned directory descriptor, never following symlinks.
All failures fail closed: leave the destination in place.
"""

import contextlib
import hashlib
import re
import os
import stat

# The aaPanel paths are constants, not caller-controlled uninstall arguments.
_PANEL_COMPONENTS = ("www", "server", "panel")
_SOURCE_COMPONENTS = ("plugin", "ach_customizer")
_DEST_COMPONENTS = ("BTPanel", "static", "img", "soft_ico")
_SOURCE_NAME = "icon.png"
_DEST_NAME = "ico-ach_customizer.png"
_MAX_FILE_BYTES = 1024 * 1024
_RETIRED_SCANNER = "ach_customizer_abusive_scan.py"
# Exact source from the previous published native package (0.1.115).
_RETIRED_SCANNER_SHA256 = "63a80c46633686e588e59ed6b6ded9cfa3b6db2b51f4dcbfc7e90e8e71800bb9"
_RETIRED_BYTECODE = re.compile(r"ach_customizer_abusive_scan\.cpython-\d+(?:\.opt-\d+)?\.pyc\Z")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class UnsafeIconPath(Exception):
    """A path or owner is not the exact trustworthy aaPanel layout."""


def _owned_directory(fd, expected_uid, expected_device=None):
    entry = os.fstat(fd)
    if not stat.S_ISDIR(entry.st_mode) or entry.st_uid != expected_uid:
        raise UnsafeIconPath("directory identity/owner mismatch")
    if entry.st_mode & 0o022:
        raise UnsafeIconPath("directory is group/world writable")
    if expected_device is not None and entry.st_dev != expected_device:
        raise UnsafeIconPath("unexpected filesystem boundary")


def _open_directories(stack, parent_fd, components, uid, device=None):
    for component in components:
        if not component or component in (".", "..") or "/" in component:
            raise UnsafeIconPath("unsafe path component")
        fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        stack.callback(os.close, fd)
        _owned_directory(fd, uid, device)
        parent_fd = fd
    return parent_fd


def _open_owned_file(stack, parent_fd, filename, uid, device):
    fd = os.open(filename, _FILE_FLAGS, dir_fd=parent_fd)
    stack.callback(os.close, fd)
    entry = os.fstat(fd)
    if not stat.S_ISREG(entry.st_mode) or entry.st_uid != uid or entry.st_dev != device:
        raise UnsafeIconPath("not an owned regular file")
    if entry.st_nlink != 1 or entry.st_size > _MAX_FILE_BYTES:
        raise UnsafeIconPath("file link count/size is ambiguous")
    return fd, entry


def cleanup_owned_icon(*, trusted_root="/", panel_components=_PANEL_COMPONENTS,
                       expected_uid=0):
    """Return True only after unlinking our exact icon copy.

    trusted_root/panel_components/expected_uid are injection points for isolated
    regression tests. The on-host CLI below uses only constant production values.
    """
    try:
        with contextlib.ExitStack() as stack:
            root = os.open(trusted_root, _DIRECTORY_FLAGS)
            stack.callback(os.close, root)
            _owned_directory(root, expected_uid)

            panel = _open_directories(stack, root, panel_components, expected_uid)
            panel_device = os.fstat(panel).st_dev
            source_parent = _open_directories(
                stack, panel, _SOURCE_COMPONENTS, expected_uid, panel_device
            )
            destination_parent = _open_directories(
                stack, panel, _DEST_COMPONENTS, expected_uid, panel_device
            )
            source, source_stat = _open_owned_file(
                stack, source_parent, _SOURCE_NAME, expected_uid, panel_device
            )
            destination, destination_stat = _open_owned_file(
                stack, destination_parent, _DEST_NAME, expected_uid, panel_device
            )
            if source_stat.st_size != destination_stat.st_size:
                raise UnsafeIconPath("icon content mismatch")
            while True:
                first = os.read(source, 65536)
                second = os.read(destination, 65536)
                if first != second:
                    raise UnsafeIconPath("icon content mismatch")
                if not first:
                    break

            # Guard against a replacement between comparison and unlink. The
            # destination directory is pinned to a descriptor, not re-resolved.
            current = os.stat(
                _DEST_NAME, dir_fd=destination_parent, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_dev != destination_stat.st_dev
                or current.st_ino != destination_stat.st_ino
                or current.st_nlink != 1
                or current.st_uid != expected_uid
            ):
                raise UnsafeIconPath("icon was replaced before cleanup")
            os.unlink(_DEST_NAME, dir_fd=destination_parent)
        print("ACh aaPanel Customizer: verified owned icon copy removed")
        return True
    except (OSError, UnsafeIconPath) as exc:
        print("ACh aaPanel Customizer: icon copy preserved (" + str(exc) + ")")
        return False


def retire_scanner_source(*, trusted_root="/", panel_components=_PANEL_COMPONENTS,
                          expected_uid=0, expected_sha256=_RETIRED_SCANNER_SHA256):
    """Remove only the verified previous package's inert source and bytecode.

    aaPanel's native ZIP importer overlays files instead of deleting removed
    members. No recovery journal, Fail2ban file, service or native site is
    changed by this one-time source retirement.
    """
    try:
        with contextlib.ExitStack() as stack:
            root = os.open(trusted_root, _DIRECTORY_FLAGS)
            stack.callback(os.close, root)
            _owned_directory(root, expected_uid)
            panel = _open_directories(stack, root, panel_components, expected_uid)
            device = os.fstat(panel).st_dev
            parent = _open_directories(
                stack, panel, _SOURCE_COMPONENTS, expected_uid, device)
            try:
                source, entry = _open_owned_file(
                    stack, parent, _RETIRED_SCANNER, expected_uid, device)
            except FileNotFoundError:
                return True
            if hashlib.sha256(os.read(source, _MAX_FILE_BYTES + 1)).hexdigest() != expected_sha256:
                raise UnsafeIconPath("retired source is not the previous packaged file")
            candidates = []
            try:
                cache = _open_directories(stack, parent, ("__pycache__",),
                                          expected_uid, device)
            except FileNotFoundError:
                pass
            else:
                for name in os.listdir(cache):
                    if _RETIRED_BYTECODE.fullmatch(name):
                        _, saved = _open_owned_file(
                            stack, cache, name, expected_uid, device)
                        candidates.append((cache, name, saved))
            candidates.append((parent, _RETIRED_SCANNER, entry))
            # Check all identities before deleting any of these exact files.
            for directory, name, saved in candidates:
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if any(getattr(current, field) != getattr(saved, field) for field in
                       ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink",
                        "st_size", "st_mtime_ns", "st_ctime_ns")):
                    raise UnsafeIconPath("retired file changed before cleanup")
            for directory, name, _ in candidates:
                os.unlink(name, dir_fd=directory)
        print("ACh aaPanel Customizer: retired scanner source and bytecode removed")
        return True
    except (OSError, UnsafeIconPath) as exc:
        print("ACh aaPanel Customizer: retired scanner source preserved (" + str(exc) + ")")
        return False


if __name__ == "__main__":
    # The shell records whether verified icon cleanup succeeded. Preserve
    # legacy nonfatal uninstall semantics in install.sh, not a false exit 0.
    if os.geteuid() != 0:
        print("ACh aaPanel Customizer: icon copy preserved (requires root)")
        raise SystemExit(1)
    import sys
    if sys.argv[1:] == ["retire-scanner-source"]:
        raise SystemExit(0 if retire_scanner_source() else 1)
    if sys.argv[1:]:
        raise SystemExit(2)
    raise SystemExit(0 if cleanup_owned_icon() else 1)
