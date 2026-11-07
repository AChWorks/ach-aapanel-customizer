"""Conservative per-site 404 *file-only* transaction, not a Nginx route editor.

Only an already existing 0644 regular 404.html, with an actually observed
native VHost/HTTP 404 route, is eligible. The caller owns authorization, native
site/domain selection and a serialized Status Pages settings lock. All
recovery files live in the root-owned aaPanel state directory and survive ZIP
updates. Never change vendor VHosts, other sites, PHP, or Nginx services.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import stat
from uuid import uuid4

from ach_customizer_status_inspect import (
    _directory, _file_snapshot, inspect_site_files, MAX_FILE_BYTES, SHA256,
    READ_FLAGS, VHOST_ROOT,
)
from ach_customizer_status_probe import probe_site_404
from ach_customizer_status_routing import verify_configured_site_404, RouteGuardError
from ach_customizer_status_pages import StatusPageError

STATE_PREFIX = "ach_customizer.site404."
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_JOURNAL = 4096


class StatusManageError(StatusPageError):
    def __init__(self, stage, message, *, recovery_id=None):
        self.stage = stage
        self.recovery_id = (recovery_id if isinstance(recovery_id, str) and
                            re.fullmatch(r"[0-9a-f]{32}", recovery_id) else None)
        super().__init__(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _same_file_metadata(first, second):
    # Atime changes from our own reads are irrelevant; inode, owner,
    # permissions, size and content-related timestamps are not.
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_uid",
              "st_gid", "st_nlink", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(first, field) == getattr(second, field) for field in fields)


def _names(site_id):
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise StatusManageError("identity", "Invalid native website ID")
    prefix = STATE_PREFIX + str(site_id)
    return prefix + ".json", prefix + ".before"


def _regular(fd, *, limit=MAX_FILE_BYTES, mode=None):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            not 0 < info.st_size <= limit or
            (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
        raise StatusManageError("ownership", "Unsupported or unsafe status file")
    if os.listxattr(fd):
        raise StatusManageError("ownership", "File attributes require operator review")
    data = bytearray()
    while len(data) <= limit:
        part = os.read(fd, limit + 1 - len(data))
        if not part:
            break
        data.extend(part)
    after = os.fstat(fd)
    if (len(data) != info.st_size or any(
            getattr(info, k) != getattr(after, k)
            for k in ("st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_uid", "st_gid",
                      "st_dev", "st_ino", "st_nlink"))):
        raise StatusManageError("concurrency", "Status file changed during read")
    return bytes(data), info


def _read_data(data_fd, name, *, limit=MAX_FILE_BYTES):
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=data_fd)
    except FileNotFoundError:
        return None
    try:
        content, info = _regular(fd, limit=limit, mode=0o600)
        if info.st_uid != os.geteuid():
            raise StatusManageError("ownership", "Recovery evidence has the wrong owner")
        path = os.stat(name, dir_fd=data_fd, follow_symlinks=False)
        if (path.st_dev, path.st_ino) != (info.st_dev, info.st_ino):
            raise StatusManageError("concurrency", "Recovery evidence was rebound")
        return content
    finally:
        os.close(fd)


def _json_record(data_fd, site_id):
    journal, backup = _names(site_id)
    raw = _read_data(data_fd, journal, limit=MAX_JOURNAL)
    if raw is None:
        # Backups are durably persisted BEFORE their prepared journal. A
        # crash at that boundary cannot have initiated a site file write by
        # this manager, but must not be silently discarded or overwritten.
        # Return the bounded original bytes for exact-match reconciliation
        # under an entirely new, explicitly approved Apply preflight.
        return None, _read_data(data_fd, backup)
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise StatusManageError("recovery", "Unreadable site recovery journal") from exc
    expected = {"schema", "site_id", "site_key", "document_root", "before_sha256",
                "after_sha256", "phase", "operation_id", "source_vhost_sha256"}
    if (not isinstance(record, dict) or set(record) != expected or
            record["schema"] != 1 or record["site_id"] != site_id or
            record["phase"] not in ("prepared", "applied", "restored") or
            any(not isinstance(record[key], str) or not SHA256.fullmatch(record[key])
                for key in ("before_sha256", "after_sha256", "source_vhost_sha256")) or
            not isinstance(record["operation_id"], str) or
            not re.fullmatch(r"[0-9a-f]{32}", record["operation_id"]) or
            not isinstance(record["site_key"], str) or
            not isinstance(record["document_root"], str)):
        raise StatusManageError("recovery", "Invalid site recovery journal")
    original = _read_data(data_fd, backup)
    if original is None or _sha(original) != record["before_sha256"]:
        raise StatusManageError("recovery", "Site backup missing or checksum mismatch")
    return record, None


def _create_data(data_fd, name, content):
    fd = os.open(name, WRITE_FLAGS, 0o600, dir_fd=data_fd)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(data_fd)


def _rename_noreplace(directory_fd, temporary, permanent):
    """Linux atomic no-clobber rename; never overwrite existing recovery data.

    The supported aaPanel platform is Linux. If renameat2/RENAME_NOREPLACE is
    unavailable, reject Apply before touching the site rather than weaken
    the uniqueness guarantee to a racy existence check.
    """
    try:
        syscall = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "Atomic no-clobber publication unavailable") from exc
    syscall.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                        ctypes.c_char_p, ctypes.c_uint)
    syscall.restype = ctypes.c_int
    if syscall(directory_fd, temporary.encode("ascii"), directory_fd,
               permanent.encode("ascii"), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _save_original_backup(data_fd, permanent, original):
    """Durably publish complete original bytes, never a partial final file.

    Crashes before the atomic rename leave only a private ignored staging
    file. An interrupted directory fsync AFTER rename produces a complete
    potential orphan; Recheck must reconcile the actual final file.
    """
    temporary = "." + permanent + "." + uuid4().hex + ".tmp"
    published = False
    try:
        _create_data(data_fd, temporary, original)
        if _read_data(data_fd, temporary) != original:
            raise StatusManageError("backup", "Original backup verification failed")
        _rename_noreplace(data_fd, temporary, permanent)
        published = True
        os.fsync(data_fd)
    except OSError as exc:
        if published:
            raise StatusManageError(
                "backup_uncertain", "Original backup publication may have committed; "
                "Recheck the exact site before another Apply") from exc
        raise StatusManageError(
            "backup", "Original backup publication failed before site mutation; "
            "Recheck the exact site") from exc
    finally:
        if not published:
            try:
                os.unlink(temporary, dir_fd=data_fd)
            except FileNotFoundError:
                pass


def _save_journal(data_fd, site_id, record):
    journal, _backup = _names(site_id)
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_JOURNAL:
        raise StatusManageError("recovery", "Journal exceeds bounded size")
    temp = "." + journal + "." + uuid4().hex + ".tmp"
    done = False
    try:
        _create_data(data_fd, temp, payload)
        os.replace(temp, journal, src_dir_fd=data_fd, dst_dir_fd=data_fd)
        done = True
        os.fsync(data_fd)
    finally:
        if not done:
            try:
                os.unlink(temp, dir_fd=data_fd)
            except FileNotFoundError:
                pass


def _site_bytes(site, *, site_root_prefix=None):
    root = site.get("path")
    roots = (("/www/wwwroot/", "/www/acdomains/") if site_root_prefix is None
             else (site_root_prefix,))
    if (not isinstance(root, str) or not any(root.startswith(base) for base in roots)
            or len(root) > 1024):
        raise StatusManageError(
            "identity", "Only explicitly supported native website document roots are writable")
    fd = _directory(root)
    try:
        directory = os.fstat(fd)
        if (directory.st_mode & 0o022 or directory.st_uid != os.geteuid() or
                not stat.S_ISDIR(directory.st_mode)):
            raise StatusManageError("ownership", "Writable or non-directory document root")
        snapshot = _file_snapshot(fd, "404.html")
        if snapshot is None:
            raise StatusManageError("compatibility", "Existing native 404.html required; no new-file adapter")
        info = os.stat("404.html", dir_fd=fd, follow_symlinks=False)
        # A www-owned page is writable by an independent web process; a
        # matching hash is not an ownership protocol. Narrow Apply to files
        # owned by the plugin's effective root identity.
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o644 or
                info.st_uid != os.geteuid()):
            raise StatusManageError("ownership", "Native 404.html ownership/mode requires review")
        opened = os.open("404.html", READ_FLAGS, dir_fd=fd)
        try:
            content, read_info = _regular(opened, mode=0o644)
            if (_sha(content) != snapshot["sha256"] or
                    (read_info.st_dev, read_info.st_ino) != (info.st_dev, info.st_ino)):
                raise StatusManageError("concurrency", "404.html changed during preflight")
        finally:
            os.close(opened)
        return content, info, (directory.st_dev, directory.st_ino)
    finally:
        os.close(fd)


# Only this plugin may write into the staging directory (root:root 0700 in
# the native aaPanel process). Never expose displaced operator files as URLs.
STAGING_DIRECTORY = ".ach-customizer-staging"


def _exchange_site_with_stage(stage_fd, staged_name, site_fd):
    """Linux RENAME_EXCHANGE: the old pathname is retained, never discarded.

    os.replace() is not an atomic compare-and-swap. Exchange instead keeps
    the displaced inode accessible for post-swap identity validation. A
    non-cooperating root editor can still race us: on uncertainty retain the
    displaced file and refuse to claim success, rather than silently delete it.
    """
    try:
        syscall = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "Atomic exchange is unavailable") from exc
    syscall.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                        ctypes.c_char_p, ctypes.c_uint)
    syscall.restype = ctypes.c_int
    if syscall(stage_fd, staged_name.encode("ascii"), site_fd,
               b"404.html", 2) != 0:  # Linux RENAME_EXCHANGE
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _staging_directory(site_fd):
    root = os.fstat(site_fd)
    if root.st_uid != os.geteuid() or root.st_mode & 0o022:
        raise StatusManageError(
            "ownership", "Site document root must be exclusively writable by the plugin identity")
    created = False
    try:
        os.mkdir(STAGING_DIRECTORY, 0o700, dir_fd=site_fd)
        created = True
    except FileExistsError:
        pass
    # No symlinks, permissive pre-existing directories or foreign owners.
    descriptor = os.open(
        STAGING_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=site_fd)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o700 or
                info.st_dev != root.st_dev):
            raise StatusManageError("ownership", "Unsafe private site staging directory")
        if created:
            os.fsync(descriptor)
            os.fsync(site_fd)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _same_displaced_inode(displaced, original):
    # Linux rename updates ctime on the moved inode. Never compare ctime
    # across RENAME_EXCHANGE; identity, content, size, mtime, mode and owner
    # remain necessary. The file snapshot itself checks ctime for read races.
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_uid",
              "st_gid", "st_nlink", "st_mtime_ns")
    return all(getattr(displaced, name) == getattr(original, name)
               for name in fields)


def _staging_name(operation_id, phase):
    if (not isinstance(operation_id, str)
            or re.fullmatch(r"[0-9a-f]{32}", operation_id) is None
            or phase not in ("apply", "rollback", "restore")):
        raise StatusManageError("recovery", "Invalid site transaction staging identity")
    return ".site404." + operation_id + "." + phase + ".tmp"


def _staging_present(site, operation_id):
    # Called only for an existing validated journal. Never delete, silently
    # adopt or overwrite a crash-left displaced inode.
    site_fd = _directory(site["path"])
    try:
        try:
            stage_fd = os.open(STAGING_DIRECTORY,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=site_fd)
        except FileNotFoundError:
            return False
        try:
            s = os.fstat(stage_fd)
            if (s.st_uid != os.geteuid()
                    or stat.S_IMODE(s.st_mode) != 0o700):
                raise StatusManageError("ownership", "Recovery staging ownership changed")
            for phase in ("apply", "rollback", "restore"):
                try:
                    os.stat(_staging_name(operation_id, phase),
                            dir_fd=stage_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                else:
                    return True
            return False
        finally:
            os.close(stage_fd)
    finally:
        os.close(site_fd)


def _verified_apply_stage(site, record, current_sha):
    """Return a crash-left Apply stage only for two unambiguous swap states.

    An independent edit, another phase's staging file or changed directory
    identity needs explicit manual recovery, not an automatic overwrite.
    """
    site_fd = _directory(site["path"])
    stage_fd = None
    try:
        stage_fd = os.open(STAGING_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY
                           | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=site_fd)
        folder = os.fstat(stage_fd)
        if (folder.st_uid != os.geteuid()
                or stat.S_IMODE(folder.st_mode) != 0o700):
            raise StatusManageError("recovery", "Recovery staging directory became unsafe")
        for other in ("rollback", "restore"):
            if _file_snapshot(stage_fd, _staging_name(record["operation_id"], other)):
                raise StatusManageError("recovery", "Multiple swap phases require manual review")
        name = _staging_name(record["operation_id"], "apply")
        stage = _file_snapshot(stage_fd, name)
        if stage is None:
            raise StatusManageError("recovery", "Prepared Apply staging entry disappeared")
        metadata = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
        if (metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o644):
            raise StatusManageError("recovery", "Unexpected Apply staging ownership")
        pair = (current_sha, stage["sha256"])
        if pair not in (
                (record["before_sha256"], record["after_sha256"]),
                (record["after_sha256"], record["before_sha256"])):
            raise StatusManageError(
                "recovery", "Private staged bytes do not match a recoverable Apply exchange")
        return stage["sha256"]
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(site_fd)


def _retire_verified_apply_stage(site, record, originally_checked_sha):
    """Clean up after an explicit and independently verified Restore only."""
    site_fd = _directory(site["path"])
    stage_fd = None
    try:
        stage_fd = os.open(STAGING_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY
                           | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=site_fd)
        name = _staging_name(record["operation_id"], "apply")
        stage = _file_snapshot(stage_fd, name)
        if stage is None or stage["sha256"] != originally_checked_sha:
            raise StatusManageError("uncertain", "Private recovery file changed before retirement",
                                    recovery_id=record["operation_id"])
        if _file_snapshot(site_fd, "404.html")["sha256"] != record["before_sha256"]:
            raise StatusManageError("uncertain", "Restored page changed before staged-file cleanup",
                                    recovery_id=record["operation_id"])
        os.unlink(name, dir_fd=stage_fd)
        os.fsync(stage_fd)
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(site_fd)


def _replace_site(site, before, after, expected_info, expected_dir,
                  *, operation_id=None, phase="apply"):
    """Swap only the existing checked 404, retaining the displaced old inode.

    Atomic exchange allows us to detect a replacement by an independent
    editor *after* the last pre-swap check. If it is recoverable we exchange
    back without discarding the editor's inode. Ambiguity preserves private
    staged bytes and the previously durable recovery journal.
    """
    operation_id = operation_id or uuid4().hex
    stage_name = _staging_name(operation_id, phase)
    site_fd = _directory(site["path"])
    stage_fd = None
    staged = False
    exchanged = False
    exchange_attempted = False
    try:
        directory = os.fstat(site_fd)
        if ((directory.st_dev, directory.st_ino) != expected_dir or
                directory.st_mode & 0o022 or directory.st_uid != os.geteuid()):
            raise StatusManageError("concurrency", "Site root ownership or binding changed")
        current = _file_snapshot(site_fd, "404.html")
        state = os.stat("404.html", dir_fd=site_fd, follow_symlinks=False)
        if (current is None or current["sha256"] != _sha(before) or
                not _same_file_metadata(state, expected_info)):
            raise StatusManageError("concurrency", "Site 404 changed before staging")

        stage_fd = _staging_directory(site_fd)
        descriptor = os.open(stage_name, WRITE_FLAGS, 0o600, dir_fd=stage_fd)
        staged = True
        try:
            os.fchown(descriptor, state.st_uid, state.st_gid)
            os.fchmod(descriptor, 0o644)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(after)
                stream.flush()
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(stage_fd)
        current = _file_snapshot(site_fd, "404.html")
        latest = os.stat("404.html", dir_fd=site_fd, follow_symlinks=False)
        if (current is None or current["sha256"] != _sha(before) or
                not _same_file_metadata(latest, state)):
            raise StatusManageError("concurrency", "Site 404 changed before atomic exchange")
        bound = _directory(site["path"])
        try:
            rebound = os.fstat(bound)
            if (rebound.st_dev, rebound.st_ino) != expected_dir:
                raise StatusManageError("concurrency", "Site root rebound before exchange")
        finally:
            os.close(bound)

        exchange_attempted = True
        _exchange_site_with_stage(stage_fd, stage_name, site_fd)
        exchanged = True
        # A crash/fsync failure after exchange is uncertain. The old file
        # still exists in private staging and the journal was persisted.
        os.fsync(site_fd)
        os.fsync(stage_fd)
        displaced = _file_snapshot(stage_fd, stage_name)
        displaced_info = os.stat(stage_name, dir_fd=stage_fd, follow_symlinks=False)
        installed = _file_snapshot(site_fd, "404.html")
        installed_info = os.stat("404.html", dir_fd=site_fd, follow_symlinks=False)
        displaced_matches = (
            displaced is not None and displaced["sha256"] == _sha(before)
            and _same_displaced_inode(displaced_info, state))
        installed_matches = (
            installed is not None and installed["sha256"] == _sha(after)
            and installed_info.st_uid == state.st_uid
            and installed_info.st_gid == state.st_gid
            and stat.S_IMODE(installed_info.st_mode) == 0o644)
        if not displaced_matches or not installed_matches:
            # Exchange back only if the site still contains OUR staged inode;
            # if another actor replaced it too, do not overwrite their edit.
            can_reverse = installed_matches
            if can_reverse:
                _exchange_site_with_stage(stage_fd, stage_name, site_fd)
                os.fsync(site_fd)
                os.fsync(stage_fd)
                reversed_site = _file_snapshot(site_fd, "404.html")
                reversed_stage = _file_snapshot(stage_fd, stage_name)
                if (reversed_site is not None and displaced is not None
                        and reversed_site["sha256"] == displaced["sha256"]
                        and reversed_stage is not None
                        and reversed_stage["sha256"] == _sha(after)):
                    exchanged = False
                    exchange_attempted = False
                    os.unlink(stage_name, dir_fd=stage_fd)
                    staged = False
                    os.fsync(stage_fd)
                    raise StatusManageError(
                        "concurrency", "An independent site edit won the race; it was preserved")
            raise StatusManageError(
                "uncertain", "Site swap conflict; displaced file retained for recovery",
                recovery_id=operation_id)

        # The displaced inode has been verified against our durable original
        # backup; remove only this private, known-original staging entry.
        os.unlink(stage_name, dir_fd=stage_fd)
        staged = False
        os.fsync(stage_fd)
        rebound = _directory(site["path"])
        try:
            if ((os.fstat(rebound).st_dev, os.fstat(rebound).st_ino) !=
                    expected_dir):
                raise StatusManageError("uncertain", "Site root changed after atomic exchange",
                                        recovery_id=operation_id)
        finally:
            os.close(rebound)
    except Exception as exc:
        if exchange_attempted:
            # Including malformed/symlinked displaced entries and ambiguous
            # syscall results: never start an automatic rollback across an
            # unverified post-exchange state.
            if isinstance(exc, StatusManageError) and exc.stage == "uncertain":
                raise
            raise StatusManageError(
                "uncertain", "Site exchange is unconfirmed; private displaced entry retained",
                recovery_id=operation_id) from exc
        raise
    finally:
        if stage_fd is not None:
            if staged and not exchange_attempted:
                # Before exchange only: our own candidate bytes are disposable.
                try:
                    os.unlink(stage_name, dir_fd=stage_fd)
                except FileNotFoundError:
                    pass
            os.close(stage_fd)
        os.close(site_fd)


def _observed(site, locale, rendered_sha, rendered_html, vhost_root, probe):
    try:
        route = verify_configured_site_404(site, vhost_root=vhost_root)
    except (RouteGuardError, OSError, ValueError) as exc:
        raise StatusManageError("runtime", "Native configured 404 route is unproven: "
                                + str(exc)[:140]) from exc
    fn = probe or probe_site_404
    observed = fn(site, locale=locale, rendered_sha256=rendered_sha,
                  rendered_html=rendered_html, vhost_root=vhost_root)
    # A matching HTTP reply is not a stable Nginx source proof. Re-evaluate
    # the same bounded configured-source graph after the request and refuse
    # any source drift (the running worker generation is still not asserted).
    try:
        route_after = verify_configured_site_404(site, vhost_root=vhost_root)
    except (RouteGuardError, OSError, ValueError) as exc:
        raise StatusManageError("runtime", "Configured Nginx route changed during HTTP probe") from exc
    if (not isinstance(route.get("nginx_dump_sha256"), str) or
            not SHA256.fullmatch(route["nginx_dump_sha256"]) or
            route_after.get("nginx_dump_sha256") != route["nginx_dump_sha256"] or
            route_after.get("vhost_sha256") != route["vhost_sha256"]):
        raise StatusManageError("runtime", "Nginx configuration changed during HTTP verification")
    adoption = observed.get("adoption_preview")
    if (route.get("configured_static_http_80") is not True or
            route.get("loaded_workers_verified") is not False or
            route.get("vhost_sha256") != observed.get("adoption_preview", {}).get("vhost_sha256")):
        raise StatusManageError("runtime", "Current configured site source does not match HTTP evidence")
    if (observed.get("state") != "HTTP Match" or
            observed.get("http_status") != 404 or
            observed.get("body_matches_file") is not True or
            not isinstance(adoption, dict) or
            adoption.get("route_source_state") != "Native VHost" or
            adoption.get("current_sha256") != observed.get("body_sha256") or
            adoption.get("apply_supported") is not False):
        raise StatusManageError("runtime", "Current native 404 HTTP/file route unverified")
    return observed


def manage_site_404(action, site, *, locale, html, expected_current=None,
                    expected_vhost=None, expected_render=None, expected_recovery=None,
                    data_fd, vhost_root=VHOST_ROOT, probe=None, site_root_prefix=None):
    """Perform an explicit, stateful operation while caller holds preferences lock.

    Caller must independently enforce native admin POST/CSRF, current site,
    canonical HTTP/80 bindings, plugin selection, branding revision and
    explicit approval. No request controls filesystem paths or probe socket.
    """
    if action not in ("apply", "restore", "recheck"):
        raise StatusManageError("input", "Unsupported site 404 operation")
    if locale not in ("en", "fa") or not isinstance(html, str):
        raise StatusManageError("input", "Unsupported 404 locale/content")
    desired = html.encode("utf-8")
    if not 0 < len(desired) <= 32768:
        raise StatusManageError("input", "Rendered 404 page exceeds size limit")
    sha = _sha(desired)
    site_id = site.get("id")
    record, orphan_backup = _json_record(data_fd, site_id)
    if record and (record["site_key"] != site.get("name") or
                   record["document_root"] != site.get("path")):
        raise StatusManageError("identity", "Site ID was rebound; preserve recovery and review")
    content, info, directory = _site_bytes(site, site_root_prefix=site_root_prefix)
    current_sha = _sha(content)

    if action == "recheck":
        staged_recovery = bool(record and _staging_present(site, record["operation_id"]))
        if orphan_backup is not None:
            # File-only evidence. An orphan is never an actionable Restore:
            # there is no durable operation ID or accepted journal identity.
            # A fresh authenticated Apply can safely journal the exact saved
            # bytes only if its independent HTTP/VHost preflight still passes.
            state = "Orphan Backup" if orphan_backup == content else "Orphan Drift"
            return {"state": state, "changed": False, "site_id": site_id,
                    "page_file_sha256": current_sha, "rendered_sha256": sha,
                    "before_sha256": _sha(orphan_backup),
                    "after_sha256": None, "recovery_id": None,
                    "read_only": True, "mode": "native_existing_404_file"}
        state = ("Drift" if (
                     staged_recovery and
                     current_sha not in (record["before_sha256"], record["after_sha256"])
                 ) else
                 "Recovery Required" if staged_recovery else
                 "Unmanaged" if record is None else
                 "Recovery Required" if (
                     record["phase"] == "prepared" and current_sha in (
                         record["before_sha256"], record["after_sha256"])
                     or record["phase"] == "applied" and current_sha == record["before_sha256"]
                 ) else "Drift")
        if record and record["phase"] != "prepared" and not staged_recovery:
            goal = record["after_sha256"] if record["phase"] == "applied" else record["before_sha256"]
            if current_sha == goal:
                try:
                    observed = _observed(site, locale, sha, html, vhost_root, probe)
                    if (observed["body_sha256"] == goal and
                            observed["adoption_preview"].get("vhost_sha256") ==
                            record["source_vhost_sha256"]):
                        state = "Applied" if record["phase"] == "applied" else "Restored"
                except (StatusPageError, OSError):
                    state = "Needs Review"
        return {"state": state, "changed": False, "site_id": site_id,
                "page_file_sha256": current_sha,
                "rendered_sha256": sha,
                "before_sha256": record["before_sha256"] if record else None,
                "after_sha256": record["after_sha256"] if record else None,
                "recovery_id": record["operation_id"] if record else None,
                "read_only": True, "mode": "native_existing_404_file"}

    staged_recovery = bool(record and _staging_present(site, record["operation_id"]))
    if staged_recovery and action == "apply":
        raise StatusManageError(
            "recovery", "Unresolved private 404 swap artifact; Recheck/Restore required",
            recovery_id=record["operation_id"])

    if action == "apply":
        if (not isinstance(expected_current, str) or not SHA256.fullmatch(expected_current)
                or not isinstance(expected_vhost, str) or not SHA256.fullmatch(expected_vhost)
                or expected_current != current_sha or expected_render != sha):
            raise StatusManageError("concurrency", "Preview/current 404 hashes changed; refresh proof")
        observation = _observed(site, locale, sha, html, vhost_root, probe)
        if (observation["body_sha256"] != expected_current or
                observation["adoption_preview"].get("vhost_sha256") != expected_vhost):
            raise StatusManageError("concurrency", "Observed 404/VHost differs from approved preview")
        if orphan_backup is not None:
            if orphan_backup != content:
                raise StatusManageError(
                    "recovery", "Unjournaled site backup differs from current 404; "
                    "do not overwrite operator edits")
            if current_sha == sha:
                raise StatusManageError(
                    "recovery", "Proposed 404 already matches an unjournaled backup; "
                    "preserve backup and request manual recovery review")
        if record and record["phase"] != "restored":
            if (record["phase"] == "applied" and record["after_sha256"] == sha and
                    current_sha == sha and
                    record["source_vhost_sha256"] == expected_vhost):
                return {"state": "Already Applied", "changed": False, "site_id": site_id,
                        "page_file_sha256": sha, "recovery_id": record["operation_id"],
                        "read_only": False, "mode": "native_existing_404_file"}
            raise StatusManageError("recovery", "Existing 404 recovery must be resolved before new Apply")
        if current_sha == sha:
            return {"state": "Already Current", "changed": False, "site_id": site_id,
                    "page_file_sha256": sha, "recovery_id": None,
                    "read_only": False, "mode": "native_existing_404_file"}
        if record and record["before_sha256"] != current_sha:
            raise StatusManageError("recovery", "Restored baseline was changed; require manual adoption")
        refreshed = inspect_site_files(site, locale=locale, template="404",
                                       rendered_sha256=sha, rendered_html=html,
                                       vhost_root=vhost_root, source_fingerprint=True)
        if (refreshed.get("vhost_sha256") != expected_vhost or
                refreshed.get("route_source_state") != "Native VHost" or
                refreshed.get("page_file_sha256") != current_sha or
                not refreshed.get("_source_fingerprint")):
            raise StatusManageError("concurrency", "VHost or site file changed since HTTP preflight")
        latest_data, latest_info, latest_root = _site_bytes(
            site, site_root_prefix=site_root_prefix)
        if (latest_data != content or not _same_file_metadata(latest_info, info)
                or latest_root != directory):
            raise StatusManageError(
                "concurrency", "Site file metadata/ownership changed since HTTP preflight"
            )
        _, backup_name = _names(site_id)
        if record is None and orphan_backup is None:
            _save_original_backup(data_fd, backup_name, content)
        else:
            # A verified matching orphan is reused, not recreated. The next
            # step journals 'prepared' durably before touching the website.
            if _read_data(data_fd, backup_name) != content:
                raise StatusManageError("recovery", "Saved original bytes changed")
        transaction = {
            "schema": 1, "site_id": site_id,
            "site_key": site["name"], "document_root": site["path"],
            "before_sha256": current_sha, "after_sha256": sha,
            "phase": "prepared", "operation_id": uuid4().hex,
            "source_vhost_sha256": expected_vhost,
        }
        try:
            _save_journal(data_fd, site_id, transaction)
        except (OSError, StatusManageError) as exc:
            # No site mutation has happened. Publication of the prepared
            # journal may still be uncertain after its own directory fsync.
            raise StatusManageError(
                "journal_prepared", "Initial recovery journal not confirmed; "
                "website remains untouched; Recheck before another Apply") from exc
        try:
            _replace_site(site, content, desired, info, directory,
                          operation_id=transaction["operation_id"], phase="apply")
            verified = _observed(site, locale, sha, html, vhost_root, probe)
            if (verified["body_sha256"] != sha or
                    verified["adoption_preview"].get("vhost_sha256") != expected_vhost):
                raise StatusManageError("postcheck", "HTTP 404 body or VHost differs after Apply")
        except Exception as exc:
            # An uncertain exchange may still hold a displaced operator file.
            # Never launch automatic rollback across an unresolved stage.
            if (isinstance(exc, StatusManageError) and
                    exc.stage == "uncertain"):
                raise
            # A prepared journal is durable before any file mutation.
            # Re-read the path and restore ONLY exact original/applied bytes.
            # Uncertain external modifications are never overwritten blindly.
            try:
                actual, actual_info, actual_directory = _site_bytes(
                    site, site_root_prefix=site_root_prefix)
                if actual == desired:
                    _replace_site(site, desired, content, actual_info, actual_directory,
                                  operation_id=transaction["operation_id"], phase="rollback")
                elif actual != content:
                    raise StatusManageError("recovery", "Unexpected third-party 404 bytes")
                restored = _observed(site, locale, sha, html, vhost_root, probe)
                if (restored["body_sha256"] != current_sha or
                        restored["adoption_preview"].get("vhost_sha256") != expected_vhost):
                    raise StatusManageError("recovery", "Rollback HTTP/VHost verification failed")
                transaction["phase"] = "restored"
                _save_journal(data_fd, site_id, transaction)
            except Exception as recovery_exc:
                raise StatusManageError(
                    "uncertain", "404 Apply/rollback outcome uncertain; recovery journal preserved",
                    recovery_id=transaction["operation_id"]
                ) from recovery_exc
            raise StatusManageError(
                "recovered", "404 Apply failed; original site file and HTTP 404 verified restored"
            ) from exc
        transaction["phase"] = "applied"
        try:
            _save_journal(data_fd, site_id, transaction)
        except Exception as exc:
            # The live file was already changed and HTTP checked. Preserve
            # the prepared journal+backup rather than claiming success if
            # final journal persistence or its directory fsync failed.
            raise StatusManageError(
                "uncertain", "Site 404 changed but final recovery journal confirmation failed; recheck",
                recovery_id=transaction["operation_id"]
            ) from exc
        return {"state": "Applied", "changed": True, "site_id": site_id,
                "page_file_sha256": sha, "recovery_id": transaction["operation_id"],
                "read_only": False, "mode": "native_existing_404_file"}

    # Explicit Restore only when current bytes equal exactly our recorded
    # applied bytes; no overwriting operator edits or changed site IDs.
    if not record:
        raise StatusManageError("recovery", "No saved site 404 recovery exists")
    if (not isinstance(expected_recovery, str) or
            expected_recovery != record["operation_id"]):
        raise StatusManageError("concurrency", "Site recovery ID changed; recheck first")
    recovered_stage_sha = None
    if staged_recovery:
        recovered_stage_sha = _verified_apply_stage(site, record, current_sha)
    before = _read_data(data_fd, _names(site_id)[1])
    if current_sha not in (record["before_sha256"], record["after_sha256"]):
        raise StatusManageError("concurrency", "Site 404 no longer matches saved Apply; refuse overwrite")
    if record["phase"] == "restored":
        if recovered_stage_sha is not None:
            raise StatusManageError("recovery", "Restored journal has unexpected recovery staging")
        if current_sha != record["before_sha256"]:
            raise StatusManageError("recovery", "Restored baseline drifted; do not overwrite")
        verified = _observed(site, locale, sha, html, vhost_root, probe)
        if (verified["body_sha256"] != current_sha or
                verified["adoption_preview"].get("vhost_sha256") !=
                record["source_vhost_sha256"]):
            raise StatusManageError("runtime", "Restored 404 route changed; recheck required")
        return {"state": "Already Restored", "changed": False, "site_id": site_id,
                "page_file_sha256": current_sha, "recovery_id": record["operation_id"],
                "read_only": False, "mode": "native_existing_404_file"}
    # Repair an interrupted Restore if the exact original bytes are already
    # present and their HTTP 404 path still serves them.
    changed = current_sha == record["after_sha256"]
    if changed:
        observed_before = _observed(site, locale, sha, html, vhost_root, probe)
        if (observed_before["body_sha256"] != current_sha or
                observed_before["adoption_preview"].get("vhost_sha256") !=
                record["source_vhost_sha256"]):
            raise StatusManageError("runtime", "Pre-restore 404 route changed")
        _replace_site(site, content, before, info, directory,
                      operation_id=record["operation_id"], phase="restore")
    try:
        observed = _observed(site, locale, sha, html, vhost_root, probe)
        if (observed["body_sha256"] != record["before_sha256"] or
                observed["adoption_preview"].get("vhost_sha256") !=
                record["source_vhost_sha256"]):
            raise StatusManageError("postcheck", "Restored 404 HTTP/VHost mismatch")
    except Exception as exc:
        raise StatusManageError("postcheck", "404 Restore outcome unverified; retain recovery journal") from exc
    # The old inode from an interrupted Apply was retained in a private
    # folder. After verified Restore, discard it only if its exact bytes
    # still match the earlier read; otherwise preserve it as uncertain.
    if recovered_stage_sha is not None:
        _retire_verified_apply_stage(site, record, recovered_stage_sha)
    record["phase"] = "restored"
    _save_journal(data_fd, site_id, record)
    return {"state": "Restored", "changed": changed, "site_id": site_id,
            "page_file_sha256": record["before_sha256"],
            "recovery_id": record["operation_id"],
            "read_only": False, "mode": "native_existing_404_file"}
