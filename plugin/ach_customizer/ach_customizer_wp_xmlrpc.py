"""Recoverable, site-local WordPress XML-RPC request switch.

A dedicated MU-plugin is a supported WordPress extension point. It denies
only requests where WordPress has set XMLRPC_REQUEST (before invoking XML-RPC
methods). The selected site's normal HTTP/80 response is used for runtime
proof; no Nginx, global firewall or WordPress database changes.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import stat
import time
from uuid import uuid4

from ach_customizer_cache_bridge import _docroot
from ach_customizer_cache_wordpress import _read_file
from ach_customizer_status_extension import (
    _bounded_file, _owned_dir, _write_exclusive, _publish_complete,
)
from ach_customizer_wp_settings import (
    WPSettingsError, _site_source, _lint, _sha,
)

SCHEMA = 1
FILE_NAME = "ach-customizer-xmlrpc.php"
MU_NAME = "mu-plugins"
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_RECORD = 2048
MAX_PLUGIN = 4096
O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _journal_name(site_id):
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise WPSettingsError("identity", "Invalid WordPress XML-RPC site identity")
    return "ach_customizer.wp_xmlrpc." + str(site_id) + ".json"


def _proof(op):
    return "ach-xmlrpc-" + hashlib.sha256(("ach-wp-xmlrpc:" + op).encode("ascii")).hexdigest()[:24]


def _plugin(op):
    nonce = _proof(op)
    return ("""<?php
/**
 * Plugin Name: ACh Customizer XML-RPC Gate
 * Description: Site-specific, administrator-controlled XML-RPC endpoint policy.
 */
if ( defined( 'XMLRPC_REQUEST' ) && XMLRPC_REQUEST ) {
    status_header( 403 );
    header( 'X-ACh-XMLRPC-Proof: %s' );
    header( 'Content-Type: text/plain; charset=utf-8' );
    exit( 'XML-RPC disabled by this website administrator.' );
}
""" % nonce).encode("ascii")


def _read_record(data_fd, site):
    raw = _bounded_file(data_fd, _journal_name(site["id"]),
                        limit=MAX_RECORD, permissions=0o600)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise WPSettingsError("recovery", "WordPress XML-RPC recovery journal unreadable") from exc
    fields = {"schema", "site_id", "site_key", "root", "op",
              "phase", "source_sha", "plugin_sha", "created_mu"}
    if (not isinstance(record, dict) or set(record) != fields
            or type(record["schema"]) is not int or record["schema"] != SCHEMA
            or type(record["site_id"]) is not int or record["site_id"] != site["id"]
            or record["site_key"] != site["name"]
            or type(record["site_id"]) is not int
            or record["root"] != site["path"]
            or not isinstance(record["op"], str) or not TOKEN.fullmatch(record["op"])
            or record["phase"] not in ("prepared", "applied", "restoring", "restored")
            or type(record["created_mu"]) is not bool
            or any(not isinstance(record[k], str) or not DIGEST.fullmatch(record[k])
                   for k in ("source_sha", "plugin_sha"))
            or _sha(_plugin(record["op"])) != record["plugin_sha"]):
        raise WPSettingsError("recovery", "WordPress XML-RPC journal identity or source changed")
    return record


def _write_record(fd, site_id, record):
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise WPSettingsError("recovery", "WordPress XML-RPC journal too large")
    temp = "." + _journal_name(site_id) + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, temp, payload, 0o600)
    os.replace(temp, _journal_name(site_id), src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _content_fd(site, public):
    root_fd = _docroot(site, public)
    try:
        content_fd = os.open("wp-content", O_DIR, dir_fd=root_fd)
    except OSError as exc:
        raise WPSettingsError("source", "Native WordPress wp-content is not a trusted directory") from exc
    finally:
        os.close(root_fd)
    st = os.fstat(content_fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o002
            or st.st_uid < 0):
        os.close(content_fd)
        raise WPSettingsError("source", "Unsafe WordPress wp-content ownership or mode")
    return content_fd, st


def _mu_fd(content_fd, owner, *, required=False):
    try:
        fd = os.open(MU_NAME, O_DIR, dir_fd=content_fd)
    except FileNotFoundError:
        if required:
            raise WPSettingsError("source", "Managed WordPress MU-plugin directory vanished")
        return None
    except OSError as exc:
        raise WPSettingsError("source", "Invalid or redirected WordPress MU-plugin directory") from exc
    st = os.fstat(fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o002
            or st.st_uid not in (0, owner.st_uid)):
        os.close(fd)
        raise WPSettingsError("source", "WordPress MU-plugin directory has unsafe ownership or mode")
    return fd


def _probe(site, *, port=80):
    """Real read-only verification of the selected WordPress XML-RPC endpoint."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    data = b'<?xml version="1.0"?><methodCall><methodName>system.listMethods</methodName><params/></methodCall>'
    try:
        conn.request("POST", "/xmlrpc.php", body=data, headers={
            "Host": site["name"], "Connection": "close",
            "Content-Type": "text/xml", "Cache-Control": "no-cache",
        })
        resp = conn.getresponse()
        status = resp.status
        proof = resp.getheader("X-ACh-XMLRPC-Proof")
        resp.read(256)
        resp.close()
        return status, proof
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise WPSettingsError("probe", "Local WordPress XML-RPC HTTP/80 probe failed: "
                              + type(exc).__name__) from exc
    finally:
        conn.close()


def _settled(site, record, *, present, probe=None):
    fn = probe or _probe
    expected_proof = _proof(record["op"])
    deadline = time.monotonic() + 8
    consecutive = 0
    while True:
        status, proof = fn(site)
        good = (status == 403 and proof == expected_proof
                if present else proof != expected_proof)
        consecutive = consecutive + 1 if good else 0
        if consecutive >= 3:
            return
        if time.monotonic() >= deadline:
            raise WPSettingsError(
                "postcheck", "WordPress did not confirm the " +
                ("active XML-RPC block" if present else "retired XML-RPC policy")
                + " in live HTTP responses")
        time.sleep(0.2)


def _source(site, public):
    if site.get("status") not in ("1", 1) or not {
            "name":site["name"], "port":80} in site["bound_domains"]:
        raise WPSettingsError("identity", "XML-RPC policy requires an active native WordPress HTTP/80 site")
    raw, php, version = _site_source(
        site, public, vhost_root="/www/server/panel/vhost/nginx")
    xmlrpc, _ = _read_file(site["path"], "xmlrpc.php")
    if (not xmlrpc.lstrip().startswith(b"<?php")
            or b"XMLRPC_REQUEST" not in xmlrpc
            or b"wp-load.php" not in xmlrpc):
        raise WPSettingsError("compatibility", "Native WordPress XML-RPC bootstrap is unsupported")
    return _sha(raw + b"\x00" + xmlrpc + b"\x00" + version.encode("ascii")), php


def _reply(site, state, source_sha, record, *, changed=False,
           runtime_verified=False, reason=""):
    return {
        "schema": SCHEMA, "site_id": site["id"], "site_key": site["name"],
        "kind": "xmlrpc", "state": state, "source_sha256": source_sha,
        "recovery_id": record["op"] if record else None, "changed": changed,
        "read_only": not changed, "runtime_verified": runtime_verified,
        "interval": None, "reason": reason,
        "impact": "Selected WordPress XML-RPC endpoint only; site-owned must-use plugin, no Nginx reload",
    }


def manage_xmlrpc(action, site, public, *, data_fd,
                  expected_source=None, expected_recovery=None,
                  runner=None, probe=None):
    if action not in ("recheck", "apply", "restore"):
        raise WPSettingsError("input", "Unsupported XML-RPC policy action")
    _owned_dir(data_fd)
    source, php = _source(site, public)
    record = _read_record(data_fd, site)
    cfd, owner = _content_fd(site, public)
    mfd = None
    try:
        mfd = _mu_fd(cfd, owner)
        existing = (_bounded_file(mfd, FILE_NAME, limit=MAX_PLUGIN, permissions=0o644)
                    if mfd is not None else None)
        if action == "recheck":
            if record is None:
                if existing is not None:
                    state, reason = "Conflict", "Foreign WordPress XML-RPC plugin source exists"
                else:
                    baseline = (probe or _probe)(site)
                    state = "Source Ready" if baseline[0] in (200, 405) and baseline[1] is None else "Conflict"
                    reason = "" if state == "Source Ready" else "XML-RPC endpoint is already blocked, redirected or incompatible"
            elif record["phase"] == "restored":
                state, reason = ("Restored", "") if existing is None else ("Drift", "Restored plugin file reappeared")
            elif record["phase"] == "applied" and existing is not None and _sha(existing) == record["plugin_sha"]:
                try:
                    _settled(site, record, present=True, probe=probe)
                    state, reason = "Applied", ""
                except WPSettingsError as exc:
                    state, reason = "Needs Review", str(exc)
            else:
                state, reason = "Recovery Required", "Interrupted or edited XML-RPC policy needs exact Recovery ID"
            return _reply(site, state, source, record,
                          runtime_verified=state=="Applied", reason=reason)
        if action == "apply":
            if expected_source != source:
                raise WPSettingsError("concurrency", "WordPress XML-RPC source changed; Recheck")
            if (existing is not None or record and record["phase"] != "restored"):
                raise WPSettingsError("recovery", "Existing XML-RPC plugin or recovery needs review")
            baseline = (probe or _probe)(site)
            if baseline[0] not in (200, 405) or baseline[1] is not None:
                raise WPSettingsError("compatibility", "Existing XML-RPC endpoint is already blocked or redirected")
            op = uuid4().hex
            payload = _plugin(op)
            _lint(payload, php, runner=runner or __import__("subprocess").run)
            row = {
                "schema": SCHEMA, "site_id":site["id"],
                "site_key":site["name"], "root":site["path"],
                "op":op, "phase":"prepared", "source_sha":source,
                "plugin_sha":_sha(payload), "created_mu":mfd is None,
            }
            _write_record(data_fd, site["id"], row)
            try:
                if mfd is None:
                    os.mkdir(MU_NAME, 0o755, dir_fd=cfd)
                    os.chown(MU_NAME, owner.st_uid, owner.st_gid, dir_fd=cfd, follow_symlinks=False)
                    os.fsync(cfd)
                    mfd = _mu_fd(cfd, owner, required=True)
                _publish_complete(mfd, FILE_NAME, payload, 0o644, op)
                if _source(site, public)[0] != source:
                    raise WPSettingsError("concurrency", "WordPress native source changed after plugin publication")
                _settled(site, row, present=True, probe=probe)
                row["phase"] = "applied"
                _write_record(data_fd, site["id"], row)
            except Exception as exc:
                raise WPSettingsError(
                    "uncertain", "WordPress XML-RPC Apply uncertain at " +
                    str(getattr(exc, "stage", type(exc).__name__)) + ": " + str(exc)[:140] +
                    "; Recheck saved Recovery ID", op) from exc
            return _reply(site, "Applied", source, row, changed=True, runtime_verified=True)
        if not record or record["phase"] == "restored":
            raise WPSettingsError("recovery", "No saved WordPress XML-RPC policy to restore")
        if expected_source != source or expected_recovery != record["op"]:
            raise WPSettingsError("concurrency", "Selected WordPress XML-RPC source or Recovery ID changed")
        if existing is not None and _sha(existing) != record["plugin_sha"]:
            raise WPSettingsError("recovery", "Managed XML-RPC file has changed; refusing foreign deletion")
        if existing is None and record["phase"] == "applied":
            raise WPSettingsError("recovery", "Applied XML-RPC plugin disappeared; manual review required")
        row = {**record, "phase": "restoring"}
        _write_record(data_fd, site["id"], row)
        try:
            if existing is not None:
                check = _bounded_file(mfd, FILE_NAME, limit=MAX_PLUGIN, permissions=0o644)
                if check != existing:
                    raise WPSettingsError("concurrency", "Managed XML-RPC plugin changed during Restore")
                os.unlink(FILE_NAME, dir_fd=mfd)
                os.fsync(mfd)
            _settled(site, row, present=False, probe=probe)
            if record["created_mu"] and mfd is not None and not os.listdir(mfd):
                os.rmdir(MU_NAME, dir_fd=cfd)
                os.fsync(cfd)
            row["phase"] = "restored"
            _write_record(data_fd, site["id"], row)
        except Exception as exc:
            raise WPSettingsError(
                "uncertain", "WordPress XML-RPC Restore uncertain at " +
                str(getattr(exc, "stage", type(exc).__name__)) + ": " + str(exc)[:140] +
                "; retain Recovery ID", record["op"]) from exc
        return _reply(site, "Restored", source, row, changed=True, runtime_verified=True)
    finally:
        if mfd is not None:
            os.close(mfd)
        os.close(cfd)
