"""Guarded native site-file 404/502 delivery when aaPanel has no extension include.

This adapter changes ONLY an explicitly selected site's existing 404.html or
502.html. The native VHost must already map that HTTP status to that filename.
It retains the original site-owned bytes, uid/gid/mode and a root-owned
recovery journal. No Nginx config is edited, and no service reload is needed.
404 is verified against real HTTP/80; 502 is source-only, not a fake HTTP 502.
"""
from __future__ import annotations

import json
import os
import re
import stat
from uuid import uuid4

from ach_customizer_status_inspect import _directory, _selected_error_page
from ach_customizer_status_extension import (
    CODES, DOMAIN, HASH, TOKEN, MAX_HTML, MAX_VHOST, ExtensionError,
    VHOST_ROOT, _bounded_file, _nginx, _owned_dir, _probe, _sha,
    _write_exclusive,
)

MAX_RECORD = 4096
MODE = "native_site_status_file"
NOTE_502 = "Site 502.html source verified; no live HTTP 502 was induced."
STAT_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns",
               "st_ctime_ns", "st_uid", "st_gid", "st_mode", "st_nlink")


def _record_name(site_id, code):
    return "ach_customizer.site_file." + str(site_id) + "." + code + ".json"


def _backup_name(site_id, code, op):
    return "ach_customizer.site_file." + str(site_id) + "." + code + "." + op + ".backup"


def _record_read(fd, site, code):
    raw = _bounded_file(fd, _record_name(site["id"], code),
                        limit=MAX_RECORD, permissions=0o600)
    if raw is None:
        return None
    try:
        entry = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ExtensionError("recovery", "Site-file recovery journal cannot be decoded") from exc
    required = {"schema", "site_id", "site_name", "site_root", "code",
                "op", "phase", "vhost_sha", "before_sha", "after_sha",
                "backup", "uid", "gid", "mode"}
    if (not isinstance(entry, dict) or set(entry) != required or
            type(entry["schema"]) is not int or entry["schema"] != 1 or
            type(entry["site_id"]) is not int or entry["site_id"] != site["id"] or
            entry["site_name"] != site["name"] or
            entry["site_root"] != site["path"] or entry["code"] != code or
            not isinstance(entry["op"], str) or not TOKEN.fullmatch(entry["op"]) or
            entry["phase"] not in ("prepared", "applied", "restored") or
            any(not isinstance(entry[key], str) or not HASH.fullmatch(entry[key])
                for key in ("vhost_sha", "before_sha", "after_sha")) or
            entry["backup"] != _backup_name(site["id"], code, entry["op"]) or
            any(type(entry[key]) is not int or entry[key] < 0
                for key in ("uid", "gid", "mode")) or
            not 0o400 <= entry["mode"] <= 0o755 or entry["mode"] & 0o022):
        raise ExtensionError("recovery", "Site-file journal identity or schema is invalid")
    return entry


def _record_write(fd, site, code, entry):
    payload = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise ExtensionError("recovery", "Site-file recovery journal exceeds limit")
    staging = "." + _record_name(site["id"], code) + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, staging, payload, 0o600)
    os.replace(staging, _record_name(site["id"], code),
               src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _source(site, code, vhost_root):
    """Conservative *existing* native aaPanel server-scope file mapping."""
    name = site.get("name")
    root = site.get("path")
    if (type(site.get("id")) is not int or code not in CODES
            or not isinstance(name, str) or not DOMAIN.fullmatch(name)
            or site.get("status") not in ("1", 1)
            or {"name": name, "port": 80} not in site.get("bound_domains", [])
            or not isinstance(root, str)
            or not re.fullmatch(r"/[a-zA-Z0-9/_.-]{1,1023}", root)
            or "//" in root or ".." in root.split("/")):
        raise ExtensionError("identity", "Unsupported or stopped native site-file target")
    fd = _directory(vhost_root)
    try:
        _owned_dir(fd)
        raw = _bounded_file(fd, name + ".conf", limit=MAX_VHOST)
    finally:
        os.close(fd)
    if raw is None:
        raise ExtensionError("source", "Native website VHost is missing")
    value = raw.decode("utf-8", "replace")
    active = "\n".join(line.split("#", 1)[0] for line in value.splitlines())
    # Native file mode is deliberately unavailable when the VHost has an
    # extension include, a second selected error-page route, or a local
    # location that can shadow the standard page URI.
    if (len(re.findall(r"(?m)^\s*server\s*\{", active)) != 1
            or len(re.findall(r"(?m)^\s*server_name\s+", active)) != 1
            or len(re.findall(r"(?m)^\s*root\s+", active)) != 1
            or len(re.findall(r"(?m)^\s*root\s+" + re.escape(root) + r"\s*;", active)) != 1
            or len(re.findall(r"(?m)^\s*server_name\s+" + re.escape(name) + r"\s*;", active)) != 1
            or _selected_error_page(active, code) != "native"
            or re.search(r"\binclude\s+[^;]*?/extension/", active)
            or re.search(r"\blocation\s*=\s*/" + code + r"\.html\b", active)):
        raise ExtensionError(
            "source", "Exact native site-file error route is not eligible; "
                      "an extension/custom rule or incompatible VHost may be active")
    return _sha(raw)


def _site_dir(site):
    fd = _directory(site["path"])
    try:
        st = os.fstat(fd)
        if (not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o022
                or st.st_uid < 0 or st.st_gid < 0):
            raise ExtensionError("ownership", "Native website root permissions are incompatible")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(fd, filename):
    from ach_customizer_status_inspect import READ_FLAGS
    try:
        handle = os.open(filename, READ_FLAGS, dir_fd=fd)
    except FileNotFoundError as exc:
        raise ExtensionError("source", "Native site has no existing status HTML file") from exc
    try:
        before = os.fstat(handle)
        parent = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                before.st_uid not in (parent.st_uid, 0) or
                before.st_mode & 0o022 or not 0 < before.st_size <= MAX_HTML or
                os.listxattr(handle)):
            raise ExtensionError("ownership", "Selected site status file is not an exclusive, safe regular file")
        raw = os.read(handle, MAX_HTML + 1)
        after = os.fstat(handle)
        path_stat = os.stat(filename, dir_fd=fd, follow_symlinks=False)
        if (len(raw) != before.st_size or
                any(getattr(before, key) != getattr(after, key) or
                    getattr(before, key) != getattr(path_stat, key)
                    for key in STAT_FIELDS)):
            raise ExtensionError("concurrency", "Native site status file changed during read")
        return raw, before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)
    finally:
        os.close(handle)


def _backup(fd, record):
    raw = _bounded_file(fd, record["backup"], limit=MAX_HTML, permissions=0o600)
    if raw is None or _sha(raw) != record["before_sha"]:
        raise ExtensionError("recovery", "Verified original site status file backup is unavailable")
    return raw


def _publish(fd, site, filename, payload, old_bytes, uid, gid, mode, op):
    """Stage and atomically publish one complete native site-owned file."""
    staged_name = "." + filename + "." + op + ".stage"
    staging = os.open(staged_name, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                      | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
    try:
        with os.fdopen(staging, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        if (os.fstat(staging).st_uid != uid or
                os.fstat(staging).st_gid != gid):
            os.fchown(staging, uid, gid)
        os.fchmod(staging, mode)
        os.fsync(staging)
    finally:
        os.close(staging)
    # Re-resolve absolute source and inode before touching the live path.
    confirmed = _site_dir(site)
    try:
        if ((os.fstat(confirmed).st_dev, os.fstat(confirmed).st_ino) !=
                (os.fstat(fd).st_dev, os.fstat(fd).st_ino)):
            raise ExtensionError("concurrency", "Native website root was rebound")
        now, now_uid, now_gid, now_mode = _file(confirmed, filename)
        if (now != old_bytes or (now_uid, now_gid, now_mode) != (uid, gid, mode)):
            raise ExtensionError("concurrency", "Native status file changed before publication")
        stage, _, _, _ = _file(confirmed, staged_name)
        if stage != payload:
            raise ExtensionError("publication", "Staged site status content differs from selected render")
        os.replace(staged_name, filename, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(confirmed)
    now, now_uid, now_gid, now_mode = _file(fd, filename)
    if now != payload or (now_uid, now_gid, now_mode) != (uid, gid, mode):
        raise ExtensionError("uncertain", "Site status publication unconfirmed; Recheck recovery")


def _response(state, site, code, current_sha, render_sha, record,
              *, changed=False, read_only=True, verified=False):
    result = {
        "state": state, "changed": changed, "site_id": site["id"],
        "page_file_sha256": current_sha, "rendered_sha256": render_sha,
        "before_sha256": record["before_sha"] if record else None,
        "after_sha256": record["after_sha"] if record else None,
        "recovery_id": record["op"] if record else None,
        "read_only": read_only, "mode": MODE,
        "runtime_verified": bool(verified) if code == "404" else False,
        "verification_scope": "http404_body" if code == "404" else "source_only",
    }
    return result


def _saved_only(site, code, payload, data_fd, *, stopped):
    rec = _record_read(data_fd, site, code)
    if rec is None:
        raise ExtensionError("recovery", "No previous site-file recovery is saved")
    return {
        **_response("Suspended" if stopped else "Needs Review", site, code,
                    rec["before_sha"] if rec["phase"] == "restored"
                    else rec["after_sha"], _sha(payload), rec),
        "runtime_verified": False, "verification_scope": "saved_journal_only",
        "journal_phase": rec["phase"],
        "note": ("Native site is stopped; the saved file recovery cannot prove current HTTP."
                 if stopped else "Native site source changed; reconcile and Recheck before Restore."),
    }


def _site_probe(site, code, expected, probe):
    if code == "502":
        return False
    result = (probe or _probe)(site, "404", None)
    if result != (404, expected, None):
        raise ExtensionError("probe", "Selected-site HTTP 404 does not match native file SHA-256")
    return True


def preview_site_file_502(site, *, locale, rendered_sha256, rendered_html):
    """Explicit read-only 502 source proof; no artificial 502 HTTP traffic."""
    vhost_sha = _source(site, "502", VHOST_ROOT)
    fd = _site_dir(site)
    try:
        raw, _, _, _ = _file(fd, "502.html")
    finally:
        os.close(fd)
    current = _sha(raw)
    return {
        "schema": 1, "site_id": site["id"], "site_key": site["name"],
        "template": "502", "locale": locale, "state": "Source Ready",
        "reason": "Existing native site 502.html and exact VHost source are ready for backup",
        "read_only": True, "apply_supported": False,
        "nginx_runtime_verified": False, "scope": "native_vhost_source_only",
        "http_status": None, "http_404_observed": False,
        "body_sha256": None, "body_bytes": None,
        "page_file_sha256": current, "rendered_sha256": rendered_sha256,
        "body_matches_file": False, "body_matches_render": False,
        "note": NOTE_502,
        "adoption_preview": {
            "schema": 1, "state": "Source Ready",
            "route_source_state": "Native VHost", "current_sha256": current,
            "proposed_sha256": rendered_sha256, "vhost_sha256": vhost_sha,
            "requires_adoption": True, "requires_backup": True,
            "ownership_verified": False, "recovery_verified": False,
            "apply_supported": False,
            "reason": "A full-primary-admin manual adoption and recoverable backup are required",
        },
    }


def manage_site_file(action, site, *, code, html, expected_current,
                     expected_vhost, expected_render, expected_recovery, data_fd,
                     vhost_root=VHOST_ROOT, nginx=None, nginx_conf=None,
                     runner=None, probe=None):
    if action not in ("apply", "restore", "recheck") or code not in CODES:
        raise ExtensionError("input", "Unsupported native site status file action")
    payload = html.encode("utf-8")
    if not 0 < len(payload) <= MAX_HTML:
        raise ExtensionError("input", "Selected rendered HTML exceeds site-file size limit")
    _owned_dir(data_fd)
    if action == "recheck" and site.get("status") in (0, "0"):
        return _saved_only(site, code, payload, data_fd, stopped=True)
    try:
        current_vhost = _source(site, code, vhost_root)
    except (ExtensionError, OSError):
        if action != "recheck":
            raise
        return _saved_only(site, code, payload, data_fd, stopped=False)

    fd = _site_dir(site)
    try:
        file_name = code + ".html"
        current, uid, gid, mode = _file(fd, file_name)
        digest, render_sha = _sha(current), _sha(payload)
        rec = _record_read(data_fd, site, code)
        if rec and rec["vhost_sha"] != current_vhost:
            if action == "recheck":
                return _saved_only(site, code, payload, data_fd, stopped=False)
            raise ExtensionError("identity", "Native VHost changed; keep saved recovery")
        if rec and (uid, gid, mode) != (rec["uid"], rec["gid"], rec["mode"]):
            raise ExtensionError("ownership", "Original site status file ownership changed")
        if rec and rec["phase"] != "restored":
            _backup(data_fd, rec)

        if action == "recheck":
            if rec is None:
                state = "Unmanaged"
            elif rec["phase"] == "restored":
                state = (("Restored" if code == "404" else "Source Restored")
                         if digest == rec["before_sha"] else "Drift")
            elif digest not in (rec["before_sha"], rec["after_sha"]):
                state = "Drift"
            elif rec["phase"] == "prepared":
                state = "Recovery Required"
            else:
                state = "Applied" if digest == rec["after_sha"] else "Recovery Required"
            verified = False
            if code == "404" and state in ("Applied", "Restored"):
                try:
                    verified = _site_probe(site, code, digest, probe)
                except ExtensionError:
                    state = "Needs Review"
            return _response(state, site, code, digest, render_sha, rec,
                             verified=verified)

        if action == "apply":
            if (expected_vhost != current_vhost or expected_current != digest
                    or expected_render != render_sha):
                raise ExtensionError("concurrency", "Selected native status source changed since preview")
            if rec and rec["phase"] != "restored":
                raise ExtensionError("recovery", "Site status file has an unfinished saved operation",
                                     recovery_id=rec["op"])
            if rec and digest != rec["before_sha"]:
                raise ExtensionError("concurrency", "Previously restored file has drifted")
            if digest == render_sha:
                return _response("Already Current", site, code, digest, render_sha, None,
                                 changed=False, read_only=False)
            _site_probe(site, code, digest, probe)
            _nginx("-t", nginx=nginx or "/www/server/nginx/sbin/nginx",
                   conf=nginx_conf or "/www/server/nginx/conf/nginx.conf", runner=runner)
            op = uuid4().hex
            entry = {
                "schema": 1, "site_id": site["id"], "site_name": site["name"],
                "site_root": site["path"], "code": code, "op": op,
                "phase": "prepared", "vhost_sha": current_vhost,
                "before_sha": digest, "after_sha": render_sha,
                "backup": _backup_name(site["id"], code, op),
                "uid": uid, "gid": gid, "mode": mode,
            }
            previous = rec
            try:
                _write_exclusive(data_fd, entry["backup"], current, 0o600)
                _record_write(data_fd, site, code, entry)
                _publish(fd, site, file_name, payload, current, uid, gid, mode, op)
                _site_probe(site, code, render_sha, probe)
                if _source(site, code, vhost_root) != current_vhost:
                    raise ExtensionError("concurrency", "Native VHost changed during site-file Apply")
                entry["phase"] = "applied"
                _record_write(data_fd, site, code, entry)
            except Exception as exc:
                raise ExtensionError(
                    "uncertain", "Native site-file Apply unconfirmed; Recheck saved recovery",
                    recovery_id=op) from exc
            if previous:
                try:
                    os.unlink(previous["backup"], dir_fd=data_fd)
                    os.fsync(data_fd)
                except OSError:
                    pass
            return _response("Applied", site, code, render_sha, render_sha,
                             entry, changed=True, read_only=False, verified=code == "404")

        if not rec or expected_recovery != rec["op"] or rec["phase"] == "restored":
            raise ExtensionError("recovery", "Unknown or already retired native site-file recovery")
        before = _backup(data_fd, rec)
        if digest not in (rec["before_sha"], rec["after_sha"]):
            raise ExtensionError("concurrency", "Native site status file has independent edits")
        if rec["phase"] == "applied" and digest != rec["after_sha"]:
            raise ExtensionError("concurrency", "Applied native site status source no longer matches recovery")
        if code == "404":
            _site_probe(site, code, digest, probe)
        changed = digest != rec["before_sha"]
        try:
            if changed:
                _publish(fd, site, file_name, before, current, uid, gid, mode, rec["op"])
            _site_probe(site, code, rec["before_sha"], probe)
            if _source(site, code, vhost_root) != current_vhost:
                raise ExtensionError("concurrency", "Native VHost changed during site-file Restore")
            rec["phase"] = "restored"
            _record_write(data_fd, site, code, rec)
        except Exception as exc:
            raise ExtensionError(
                "uncertain", "Native site-file Restore unconfirmed; Recheck saved recovery",
                recovery_id=rec["op"]) from exc
        # A prepared Apply may have failed with an inert staged native file
        # before any replacement. Retire it only after original bytes and
        # recovery phase are durably restored; never follow an untrusted path.
        stage = "." + file_name + "." + rec["op"] + ".stage"
        try:
            staged, stage_uid, stage_gid, stage_mode = _file(fd, stage)
        except FileNotFoundError:
            pass
        except ExtensionError:
            pass  # Preserve unexpected artifacts for explicit operator inspection.
        else:
            if (_sha(staged) == rec["after_sha"] and
                    (stage_uid, stage_gid, stage_mode) == (uid, gid, mode)):
                try:
                    os.unlink(stage, dir_fd=fd)
                    os.fsync(fd)
                except OSError:
                    pass
        return _response("Restored" if code == "404" else "Source Restored",
                         site, code, rec["before_sha"], render_sha, rec,
                         changed=changed, read_only=False, verified=code == "404")
    finally:
        os.close(fd)
