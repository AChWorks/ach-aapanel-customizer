"""Conservative per-site 404 *file-only* transaction, not a Nginx route editor.

Only an already existing 0644 regular 404.html, with an actually observed
native VHost/HTTP 404 route, is eligible. The caller owns authorization, native
site/domain selection and a serialized Status Pages settings lock. All
recovery files live in the root-owned aaPanel state directory and survive ZIP
updates. Never change vendor VHosts, other sites, PHP, or Nginx services.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import pwd
import stat
from uuid import uuid4

from ach_customizer_status_inspect import (
    _directory, _file_snapshot, inspect_site_files, MAX_FILE_BYTES, SHA256,
    READ_FLAGS, VHOST_ROOT,
)
from ach_customizer_status_probe import probe_site_404
from ach_customizer_status_pages import StatusPageError

STATE_PREFIX = "ach_customizer.site404."
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_JOURNAL = 4096


class StatusManageError(StatusPageError):
    def __init__(self, stage, message):
        self.stage = stage
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
        if (directory.st_mode & 0o022 or
                not stat.S_ISDIR(directory.st_mode)):
            raise StatusManageError("ownership", "Writable or non-directory document root")
        snapshot = _file_snapshot(fd, "404.html")
        if snapshot is None:
            raise StatusManageError("compatibility", "Existing native 404.html required; no new-file adapter")
        info = os.stat("404.html", dir_fd=fd, follow_symlinks=False)
        allowed_owners = {os.geteuid()}
        if os.geteuid() == 0:
            try:
                allowed_owners.add(pwd.getpwnam("www").pw_uid)
            except KeyError:
                pass
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o644 or
                info.st_uid not in allowed_owners):
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


def _replace_site(site, before, after, expected_info, expected_dir):
    """Atomic byte update with last-moment inode and source digest check."""
    fd = _directory(site["path"])
    temp = ".ach_customizer.404." + uuid4().hex + ".tmp"
    done = False
    try:
        directory = os.fstat(fd)
        if ((directory.st_dev, directory.st_ino) != expected_dir or
                directory.st_mode & 0o022):
            raise StatusManageError("concurrency", "Document root changed before 404 write")
        current = _file_snapshot(fd, "404.html")
        if (current is None or current["sha256"] != _sha(before)):
            raise StatusManageError("concurrency", "Original site 404 content changed")
        state = os.stat("404.html", dir_fd=fd, follow_symlinks=False)
        if not _same_file_metadata(state, expected_info):
            raise StatusManageError("concurrency", "Original site 404 metadata changed")
        descriptor = os.open(temp, WRITE_FLAGS, 0o600, dir_fd=fd)
        try:
            os.fchown(descriptor, state.st_uid, state.st_gid)
            os.fchmod(descriptor, 0o644)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(after)
                stream.flush()
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        current = _file_snapshot(fd, "404.html")
        latest = os.stat("404.html", dir_fd=fd, follow_symlinks=False)
        if (current is None or current["sha256"] != _sha(before) or
                not _same_file_metadata(latest, state)):
            raise StatusManageError("concurrency", "Site 404 changed before atomic replacement")
        bound = _directory(site["path"])
        try:
            rebound = os.fstat(bound)
            if (rebound.st_dev, rebound.st_ino) != expected_dir:
                raise StatusManageError("concurrency", "Site root path rebound before replacement")
        finally:
            os.close(bound)
        os.replace(temp, "404.html", src_dir_fd=fd, dst_dir_fd=fd)
        done = True
        os.fsync(fd)
        bound = _directory(site["path"])
        try:
            rebound = os.fstat(bound)
            if (rebound.st_dev, rebound.st_ino) != expected_dir:
                raise StatusManageError("uncertain", "Site root rebound after 404 replacement")
        finally:
            os.close(bound)
    finally:
        if not done:
            try:
                os.unlink(temp, dir_fd=fd)
            except FileNotFoundError:
                pass
        os.close(fd)


def _observed(site, locale, rendered_sha, rendered_html, vhost_root, probe):
    fn = probe or probe_site_404
    observed = fn(site, locale=locale, rendered_sha256=rendered_sha,
                  rendered_html=rendered_html, vhost_root=vhost_root)
    adoption = observed.get("adoption_preview")
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
        state = ("Unmanaged" if record is None else
                 "Recovery Required" if (
                     record["phase"] == "prepared" and current_sha in (
                         record["before_sha256"], record["after_sha256"])
                     or record["phase"] == "applied" and current_sha == record["before_sha256"]
                 ) else "Drift")
        if record and record["phase"] != "prepared":
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
                    current_sha == sha):
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
            _create_data(data_fd, backup_name, content)
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
        _save_journal(data_fd, site_id, transaction)
        try:
            _replace_site(site, content, desired, info, directory)
            verified = _observed(site, locale, sha, html, vhost_root, probe)
            if (verified["body_sha256"] != sha or
                    verified["adoption_preview"].get("vhost_sha256") != expected_vhost):
                raise StatusManageError("postcheck", "HTTP 404 body or VHost differs after Apply")
        except Exception as exc:
            # A prepared journal is durable before any file mutation.
            # Re-read the path and restore ONLY exact original/applied bytes.
            # Uncertain external modifications are never overwritten blindly.
            try:
                actual, actual_info, actual_directory = _site_bytes(
                    site, site_root_prefix=site_root_prefix)
                if actual == desired:
                    _replace_site(site, desired, content, actual_info, actual_directory)
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
                    "uncertain", "404 Apply/rollback outcome uncertain; recovery journal preserved"
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
                "uncertain", "Site 404 changed but final recovery journal confirmation failed; recheck"
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
    before = _read_data(data_fd, _names(site_id)[1])
    if current_sha not in (record["before_sha256"], record["after_sha256"]):
        raise StatusManageError("concurrency", "Site 404 no longer matches saved Apply; refuse overwrite")
    if record["phase"] == "restored":
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
        _replace_site(site, content, before, info, directory)
    try:
        observed = _observed(site, locale, sha, html, vhost_root, probe)
        if (observed["body_sha256"] != record["before_sha256"] or
                observed["adoption_preview"].get("vhost_sha256") !=
                record["source_vhost_sha256"]):
            raise StatusManageError("postcheck", "Restored 404 HTTP/VHost mismatch")
    except Exception as exc:
        raise StatusManageError("postcheck", "404 Restore outcome unverified; retain recovery journal") from exc
    record["phase"] = "restored"
    _save_journal(data_fd, site_id, record)
    return {"state": "Restored", "changed": changed, "site_id": site_id,
            "page_file_sha256": record["before_sha256"],
            "recovery_id": record["operation_id"],
            "read_only": False, "mode": "native_existing_404_file"}
