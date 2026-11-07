"""Guarded HTTP/80 unbound-domain Status Page for native aaPanel 8.0.7.

Adds an independent plugin-owned IPv4/IPv6 default_server and one static HTML
asset. Does not edit aaPanel-generated VHosts, vendor files or TLS routes.
All operations are behind the caller's primary-admin POST and state lock.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import subprocess
import time
from uuid import uuid4

from ach_customizer_status_inspect import _directory, VHOST_ROOT
from ach_customizer_status_extension import (
    ExtensionError, _bounded_file, _owned_dir, _write_exclusive,
    _publish_complete, _rename_noreplace, _nginx, NGINX, NGINX_CONF, MAX_HTML,
)
from ach_customizer_status_pages import StatusPageError

HTML_ROOT = "/www/server/nginx/html"
CONF_NAME = "00.ach_customizer_unbound.conf"
HTML_NAME = "_ach_customizer_unbound.html"
RECORD_NAME = "ach_customizer.status_unbound.json"
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
MAX_SOURCE_DUMP = 2 * 1024 * 1024
MAX_RECORD = 2048


class UnboundError(StatusPageError):
    def __init__(self, stage, message, recovery_id=None):
        self.stage = stage
        self.recovery_id = recovery_id if isinstance(recovery_id, str) and TOKEN.fullmatch(recovery_id) else None
        super().__init__(message)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _config(operation_id, html_root):
    # Nonce proves an actual newly loaded Nginx generation, not only a file.
    return ("""# ACh Customizer managed HTTP unbound route. Restore in plugin before manual edits.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ach-unbound-%s.invalid;
    root %s;
    add_header X-ACh-Status-Proof %s always;
    error_page 404 /%s;
    location / { return 404; }
    location = /%s { internal; }
}
""" % (operation_id, html_root, operation_id, HTML_NAME, HTML_NAME)).encode("ascii")


def _record_read(data_fd):
    raw = _bounded_file(data_fd, RECORD_NAME, limit=MAX_RECORD, permissions=0o600)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise UnboundError("recovery", "Unbound route recovery record is unreadable") from exc
    if (not isinstance(record, dict) or
            set(record) != {"schema", "operation_id", "phase", "source_sha256",
                            "rendered_sha256", "config_sha256", "before_v4", "before_v6"} or
            type(record["schema"]) is not int or record["schema"] != 1 or
            record["phase"] not in ("prepared", "applied", "restoring", "restored") or
            not isinstance(record["operation_id"], str) or
            not TOKEN.fullmatch(record["operation_id"]) or
            any(not isinstance(record[k], str) or not HASH.fullmatch(record[k])
                for k in ("source_sha256", "rendered_sha256", "config_sha256")) or
            any(type(record[k]) is not int or not 100 <= record[k] <= 599
                for k in ("before_v4", "before_v6"))):
        raise UnboundError("recovery", "Unbound route recovery identity is invalid")
    return record


def _record_write(data_fd, record):
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise UnboundError("recovery", "Unbound recovery record is oversized")
    name = "." + RECORD_NAME + "." + uuid4().hex + ".stage"
    _write_exclusive(data_fd, name, payload, 0o600)
    os.replace(name, RECORD_NAME, src_dir_fd=data_fd, dst_dir_fd=data_fd)
    os.fsync(data_fd)


def _http_port_80(listener):
    """Identify a listen address's port, not a coincidental IP component."""
    if listener.startswith("unix:"):
        return False
    if listener.startswith("["):
        end = listener.find("]")
        if end < 0:
            return False
        suffix = listener[end + 1:]
        if not suffix:
            return True  # IPv6 address without an explicit port defaults to 80.
        if not suffix.startswith(":"):
            return False
        port = suffix[1:]
    elif ":" in listener:
        port = listener.rsplit(":", 1)[1]
    else:
        port = listener if listener.isdecimal() else "80"
    return port.isdecimal() and int(port) == 80


def _source(nginx, nginx_conf, vhost_root, conf_name, runner=None):
    """Check *loaded* Nginx source and refuse another HTTP default owner.

    The normalized fingerprint excludes only this exact plugin-owned section.
    It is an approval dependency, not a general Nginx parser.
    """
    directory = _directory(os.path.dirname(nginx_conf))
    try:
        main = _bounded_file(directory, os.path.basename(nginx_conf), limit=131072)
    finally:
        os.close(directory)
    include = ("include " + vhost_root + "/*.conf;").encode()
    if not main or not re.search(rb"(?m)^[ \t]*" + re.escape(include) + rb"[ \t]*(?:#.*)?$", main):
        raise UnboundError("compatibility", "Native Nginx top-level VHost glob could not be verified")
    command = [nginx, "-T", "-c", nginx_conf]
    try:
        output = (runner or subprocess.run)(command, capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UnboundError("source", "Native loaded Nginx source unavailable") from exc
    if output.returncode != 0 or len(output.stdout) > MAX_SOURCE_DUMP:
        raise UnboundError("source", "Nginx loaded-source inspection failed or exceeds limit")
    try:
        source = output.stdout.decode("utf-8")
    except UnicodeError as exc:
        raise UnboundError("source", "Unsupported Nginx loaded-source encoding") from exc
    title = "# configuration file " + os.path.join(vhost_root, conf_name) + ":"
    sections = re.split(r"(?m)^(# configuration file [^\r\n]+:)\r?\n", source)
    kept = [sections[0]]
    owned_found = False
    for index in range(1, len(sections), 2):
        heading, data = sections[index], sections[index + 1]
        if heading == title:
            if owned_found:
                raise UnboundError("source", "Duplicate managed Nginx source section")
            owned_found = True
        else:
            kept.append(heading + "\n" + data)
    normalized = "".join(kept)
    # nginx -T has already validated the config. Recognize bounded listen
    # directives even in inline server blocks or with tab whitespace, while
    # ignoring comments and matching only the listener's actual port.
    uncommented = re.sub(r"(?m)#[^\r\n]*", "", normalized)
    for match in re.finditer(r"(?:(?<=^)|(?<=[;{}]))\s*listen\s+([^;{}]+);",
                             uncommented, re.MULTILINE):
        parts = match.group(1).split()
        if parts and "default_server" in parts[1:] and _http_port_80(parts[0]):
            raise UnboundError("conflict", "Another Nginx HTTP default_server already exists")
    return _sha(normalized.encode("utf-8")), owned_found


def _probe(ipv6=False):
    host = "ach-unbound-probe-" + uuid4().hex + ".invalid"
    conn = http.client.HTTPConnection("::1" if ipv6 else "127.0.0.1", 80, timeout=2.5)
    try:
        conn.request("GET", "/", headers={"Host": host,
                   "Accept-Encoding": "identity", "Cache-Control": "no-cache",
                   "Connection": "close"})
        response = conn.getresponse()
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise UnboundError("probe", "Unbound response was compressed")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > 128 * 1024):
            raise UnboundError("probe", "Unbound HTTP content length invalid")
        body = response.read(128 * 1024 + 1)
        if len(body) > 128 * 1024 or (length is not None and len(body) != int(length)):
            raise UnboundError("probe", "Unbound HTTP body incomplete or oversized")
        return response.status, _sha(body), response.getheader("X-ACh-Status-Proof")
    except (OSError, http.client.HTTPException, TimeoutError) as exc:
        raise UnboundError("probe", "Unbound loopback HTTP request unavailable") from exc
    finally:
        conn.close()


def _settled(operation_id, after_sha, *, present, before_v4=None, before_v6=None, probe=None):
    fn = probe or _probe
    for ipv6, previous in ((False, before_v4), (True, before_v6)):
        deadline = time.monotonic() + 8
        count = 0
        while True:
            status, body, nonce = fn(ipv6)
            if present:
                match = status == 404 and body == after_sha and nonce == operation_id
            else:
                # An unrelated named VHost can change the native fallback after
                # Apply. Restore removes only our route; it must not require an
                # old unrelated response status/body to remain unchanged.
                match = nonce != operation_id
            count = count + 1 if match else 0
            if count >= 3:
                break
            if time.monotonic() >= deadline:
                raise UnboundError("postcheck", "Nginx did not settle on expected HTTP route", operation_id)
            time.sleep(0.2)


def _retired(operation_id):
    return "." + CONF_NAME + "." + operation_id + ".retired"


def _response(state, record, source_sha, rendered_sha, before, *, changed=False,
              read_only=True, runtime_verified=False):
    return {
        "schema": 1, "mode": "native_http_unbound", "state": state,
        "source_sha256": source_sha, "rendered_sha256": rendered_sha,
        "recovery_id": record["operation_id"] if record else None,
        "before_ipv4_status": before[0], "before_ipv6_status": before[1],
        "changed": changed, "read_only": read_only,
        "runtime_verified": runtime_verified,
        "impact": "Unknown HTTP Host on port 80 (IPv4/IPv6) only; no HTTPS or stopped-site change",
    }


def manage_unbound(action, html, *, data_fd,
                   expected_source=None, expected_render=None,
                   expected_recovery=None, expected_v4=None, expected_v6=None,
                   vhost_root=VHOST_ROOT, html_root=HTML_ROOT,
                   nginx=NGINX, nginx_conf=NGINX_CONF, runner=None, probe=None):
    if action not in ("recheck", "apply", "restore") or not isinstance(html, str):
        raise UnboundError("input", "Unsupported global HTTP unbound operation")
    html_bytes = html.encode("utf-8")
    if not 0 < len(html_bytes) <= MAX_HTML:
        raise UnboundError("render", "Unbound HTML is oversized")
    rendered_sha = _sha(html_bytes)
    _owned_dir(data_fd)
    vfd = _directory(vhost_root)
    hfd = _directory(html_root)
    try:
        _owned_dir(vfd)
        _owned_dir(hfd)
        record = _record_read(data_fd)
        conf = _bounded_file(vfd, CONF_NAME, limit=8192, permissions=0o600)
        asset = _bounded_file(hfd, HTML_NAME, limit=MAX_HTML, permissions=0o644)
        retired = (_bounded_file(vfd, _retired(record["operation_id"]),
                    limit=8192, permissions=0o600) if record else None)
        source_sha, loaded = _source(nginx, nginx_conf, vhost_root, CONF_NAME, runner)
        if conf is not None and not loaded:
            raise UnboundError("source", "Managed-looking Nginx file is not loaded")
        if action == "recheck":
            if not record:
                state = "Source Ready" if conf is None and asset is None else "Conflict"
                verified = False
                before = ((probe or _probe)(False)[0], (probe or _probe)(True)[0]) if state == "Source Ready" else (None, None)
            else:
                before = (record["before_v4"], record["before_v6"])
                if record["phase"] == "restored":
                    state = "Restored" if conf is None and retired is None and asset is None else "Drift"
                    verified = False
                    if state == "Restored":
                        # Fresh native baselines after unrelated site changes.
                        before = ((probe or _probe)(False)[0], (probe or _probe)(True)[0])
                elif record["phase"] != "applied":
                    state, verified = "Recovery Required", False
                elif (conf is not None and loaded and
                      _sha(conf) == record["config_sha256"] and
                      asset is not None and _sha(asset) == record["rendered_sha256"]):
                    result = (probe or _probe)(False), (probe or _probe)(True)
                    verified = all(item == (404, record["rendered_sha256"], record["operation_id"])
                                   for item in result)
                    state = "Applied" if verified else "Needs Review"
                else:
                    state, verified = "Recovery Required", False
            return _response(state, record, source_sha, rendered_sha, before,
                             runtime_verified=verified)
        if action == "apply":
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            if ((record and record["phase"] != "restored") or conf is not None
                    or asset is not None or retired is not None):
                raise UnboundError("recovery", "Existing/unconfirmed managed unbound route; Recheck first")
            if (expected_source != source_sha or expected_render != rendered_sha or
                    type(expected_v4) is not int or type(expected_v6) is not int or
                    not 100 <= expected_v4 <= 599 or not 100 <= expected_v6 <= 599):
                raise UnboundError("concurrency", "Unbound routing approval is stale; Recheck")
            observed = ((probe or _probe)(False)[0], (probe or _probe)(True)[0])
            if observed != (expected_v4, expected_v6):
                raise UnboundError("concurrency", "Original unbound HTTP response changed; Recheck")
            operation_id = uuid4().hex
            config = _config(operation_id, html_root)
            journal = {
                "schema": 1, "operation_id": operation_id, "phase": "prepared",
                "source_sha256": source_sha, "rendered_sha256": rendered_sha,
                "config_sha256": _sha(config), "before_v4": observed[0],
                "before_v6": observed[1],
            }
            _record_write(data_fd, journal)
            try:
                # The staged names never enter the active *.conf glob.
                # Publish complete bytes atomically (asset before config).
                _publish_complete(hfd, HTML_NAME, html_bytes, 0o644, operation_id)
                _publish_complete(vfd, CONF_NAME, config, 0o600, operation_id)
                try:
                    # nginx -T also performs syntax validation. Test before
                    # inspecting loaded source so a rejected new .conf can
                    # be detached and the normal Restore path stays usable.
                    _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
                except ExtensionError as syntax:
                    if syntax.stage == "syntax" and _bounded_file(
                            vfd, CONF_NAME, limit=8192, permissions=0o600) == config:
                        _rename_noreplace(vfd, CONF_NAME, _retired(operation_id))
                        os.fsync(vfd)
                    raise
                renewed, present = _source(nginx, nginx_conf, vhost_root, CONF_NAME, runner)
                if renewed != source_sha or not present:
                    raise UnboundError("concurrency", "Nginx routing source changed during Apply", operation_id)
                _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
                _settled(operation_id, rendered_sha, present=True, probe=probe)
                if _source(nginx, nginx_conf, vhost_root, CONF_NAME, runner) != (source_sha, True):
                    raise UnboundError("concurrency", "Nginx source drift after Apply", operation_id)
                journal["phase"] = "applied"
                _record_write(data_fd, journal)
            except Exception as exc:
                raise UnboundError("uncertain",
                                   "HTTP unbound Apply is uncertain; Recheck recovery before retrying",
                                   operation_id) from exc
            return _response("Applied", journal, source_sha, rendered_sha, observed,
                             changed=True, read_only=False, runtime_verified=True)

        if not record or record["phase"] == "restored":
            raise UnboundError("recovery", "No managed unbound route to restore")
        operation_id = record["operation_id"]
        if expected_recovery != operation_id or expected_source != source_sha:
            raise UnboundError("concurrency", "Saved unbound routing recovery changed; Recheck")
        if ((asset is None and record["phase"] == "applied") or
                (asset is not None and _sha(asset) != record["rendered_sha256"]) or
                (conf is not None and _sha(conf) != record["config_sha256"]) or
                (retired is not None and _sha(retired) != record["config_sha256"])):
            raise UnboundError("recovery", "Managed asset or configuration no longer matches recovery")
        if conf is None and retired is None and record["phase"] == "applied":
            raise UnboundError("recovery", "Applied route is missing; retain recovery evidence")
        if conf is not None and retired is not None:
            raise UnboundError("recovery", "Duplicate managed routing source; manual review required")
        journal = dict(record, phase="restoring")
        _record_write(data_fd, journal)
        try:
            if conf is not None:
                _rename_noreplace(vfd, CONF_NAME, _retired(operation_id))
                os.fsync(vfd)
            renewed, loaded_now = _source(nginx, nginx_conf, vhost_root, CONF_NAME, runner)
            if renewed != source_sha or loaded_now:
                raise UnboundError("concurrency", "Another Nginx source changed during Restore", operation_id)
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
            _settled(operation_id, record["rendered_sha256"], present=False,
                     before_v4=record["before_v4"], before_v6=record["before_v6"], probe=probe)
            if _source(nginx, nginx_conf, vhost_root, CONF_NAME, runner) != (source_sha, False):
                raise UnboundError("concurrency", "Nginx source changed after Restore", operation_id)
            if retired is not None or conf is not None:
                retained = _bounded_file(
                    vfd, _retired(operation_id), limit=8192, permissions=0o600)
                if retained is None or _sha(retained) != record["config_sha256"]:
                    raise UnboundError("recovery", "Retained managed route changed", operation_id)
                os.unlink(_retired(operation_id), dir_fd=vfd)
                os.fsync(vfd)
            if asset is not None:
                if _bounded_file(hfd, HTML_NAME, limit=MAX_HTML, permissions=0o644) != asset:
                    raise UnboundError("recovery", "Managed static asset changed", operation_id)
                os.unlink(HTML_NAME, dir_fd=hfd)
                os.fsync(hfd)
            journal["phase"] = "restored"
            _record_write(data_fd, journal)
        except Exception as exc:
            raise UnboundError("uncertain",
                               "HTTP unbound Restore is uncertain; Recheck saved recovery",
                               operation_id) from exc
        return _response("Restored", journal, source_sha, rendered_sha,
                         (record["before_v4"], record["before_v6"]),
                         changed=True, read_only=False, runtime_verified=True)
    finally:
        os.close(hfd)
        os.close(vfd)
