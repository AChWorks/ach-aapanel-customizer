"""Opt-in TLS/SNI rejection for unknown names on existing Nginx HTTPS sockets.

No listener, certificate, native VHost or HTTP/80 route is created/changed
unless an HTTPS socket already belongs to Nginx.  A new, plugin-owned
default_server on exactly those wildcard sockets rejects unknown SNI and
missing SNI before a certificate is sent. Named HTTPS sites keep their VHosts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import time
from uuid import uuid4

from ach_customizer_monitor import _active_nginx_text
from ach_customizer_status_extension import (
    ExtensionError, _bounded_file, _directory, _nginx, _owned_dir,
    _publish_complete, _rename_noreplace, _write_exclusive, NGINX, NGINX_CONF,
)
from ach_customizer_status_inspect import VHOST_ROOT

CONF_NAME = "00.ach_customizer_unknown_tls.conf"
RECORD_NAME = "ach_customizer.status_tls.json"
HASH = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
HOST = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?\Z")
MAX_RECORD = 3072
MAX_DUMP = 2 * 1024 * 1024
FAMILIES = ("ipv4", "ipv6")


class TLSError(ExtensionError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _config(op, families, protocols):
    blocks = []
    for family in FAMILIES:
        if family not in families:
            continue
        listener = "443" if family == "ipv4" else "[::]:443"
        proto = protocols.get(family)
        blocks.append(
            "server {\n"
            "    listen " + listener + " ssl default_server;\n"
            "    server_name ach-unknown-tls-" + op + ".invalid;\n"
            + ("    ssl_protocols " + proto + ";\n" if proto else "")
            + "    ssl_reject_handshake on;\n"
            "    return 421;\n"
            "}\n"
        )
    if not blocks:
        raise TLSError("compatibility", "No existing Nginx HTTPS listeners to protect")
    return ("# Plugin-owned TLS/SNI default; restore via Customizer, not by editing site VHosts.\n"
            + "".join(blocks)).encode("ascii")


def _journal_read(fd):
    raw = _bounded_file(fd, RECORD_NAME, limit=MAX_RECORD, permissions=0o600)
    if raw is None:
        return None
    try:
        row = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise TLSError("recovery", "TLS recovery journal cannot be decoded") from exc
    fields = {"schema", "operation_id", "phase", "source_sha256",
              "config_sha256", "families", "protocols", "witnesses"}
    if (not isinstance(row, dict) or set(row) != fields or row["schema"] != 1
            or type(row["schema"]) is not int
            or row["phase"] not in ("prepared", "applied", "restoring", "restored")
            or not isinstance(row["operation_id"], str)
            or not TOKEN.fullmatch(row["operation_id"])
            or not all(isinstance(row[k], str) and HASH.fullmatch(row[k])
                       for k in ("source_sha256", "config_sha256"))
            or not isinstance(row["families"], list) or not row["families"]
            or any(item not in FAMILIES for item in row["families"])
            or len(set(row["families"])) != len(row["families"])
            or not isinstance(row["protocols"], dict)
            or set(row["protocols"]) != set(row["families"])
            or any(v is not None and (not isinstance(v, str) or
                    not re.fullmatch(r"TLSv[0-9. ]+", v)) for v in row["protocols"].values())
            or not isinstance(row["witnesses"], dict)
            or set(row["witnesses"]) != set(row["families"])
            or any(not isinstance(v, str) or not HOST.fullmatch(v)
                   for v in row["witnesses"].values())
            or _sha(_config(row["operation_id"], row["families"], row["protocols"]))
               != row["config_sha256"]):
        raise TLSError("recovery", "Invalid or changed TLS recovery journal")
    return row


def _journal_write(fd, row):
    payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise TLSError("recovery", "TLS recovery journal exceeds source budget")
    temporary = "." + RECORD_NAME + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, temporary, payload, 0o600)
    os.replace(temporary, RECORD_NAME, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _source_sections(source):
    parts = re.split(r"(?m)^(# configuration file [^\r\n]+:)\r?\n", source)
    if len(parts) < 3 or len(parts) % 2 != 1:
        raise TLSError("source", "Nginx source dump has no reliable include boundaries")
    return [(parts[i][len("# configuration file "):-1], parts[i + 1])
            for i in range(1, len(parts), 2)]


def _server_directives(raw, *, stream=False):
    """Walk Nginx blocks and capture direct server directives only.

    Nginx -T is already syntax-checked, but quoted braces and nested
    location/if blocks must not be mistaken for a top-level listen.
    """
    text = _active_nginx_text(raw)
    stack, statement, quoted, escaped = [], [], None, False
    servers = []
    current = None
    for char in text:
        if escaped:
            statement.append(char)
            escaped = False
            continue
        if char == "\\":
            statement.append(char)
            escaped = True
            continue
        if quoted:
            statement.append(char)
            if char == quoted:
                quoted = None
            continue
        if char in ('"', "'"):
            statement.append(char)
            quoted = char
            continue
        if char == "{":
            entry = "".join(statement).strip().split()
            block = entry[0] if entry else ""
            if block == "server" and (not stack or stack[-1] in ("http", "stream")):
                current = {"stream": stream or "stream" in stack, "values": {}}
                servers.append(current)
            stack.append(block)
            statement = []
        elif char == "}":
            if stack:
                stack.pop()
            statement = []
            if not stack or stack[-1] in ("http", "stream"):
                current = None
        elif char == ";":
            if current is not None and stack and stack[-1] == "server":
                item = "".join(statement).strip().split(None, 1)
                if len(item) == 2 and item[0] in (
                        "listen", "server_name", "ssl_protocols"):
                    current["values"].setdefault(item[0], []).append(item[1].strip())
            statement = []
        else:
            statement.append(char)
    return servers


def _family(listener):
    parts = listener.split()
    if not parts:
        return None
    address = parts[0]
    if address.startswith("unix:"):
        return None
    if address.startswith("["):
        match = re.fullmatch(r"\[([^]]+)\](?::([0-9]+))?", address)
        if not match:
            return None
        port = int(match[2] or "80")
        family = "ipv6" if match[1] == "::" else "address-specific"
    elif ":" in address:
        host, port_string = address.rsplit(":", 1)
        if not port_string.isdigit():
            return None
        port = int(port_string)
        family = "ipv4" if host in ("*", "0.0.0.0") else "address-specific"
    elif address.isdigit():
        port = int(address)
        family = "ipv4"
    else:
        return None
    return family if port == 443 else None


def _loaded_source(*, nginx, nginx_conf, vhost_root, runner=None):
    directory = _directory(os.path.dirname(nginx_conf))
    try:
        main = _bounded_file(directory, os.path.basename(nginx_conf), limit=131072)
    finally:
        os.close(directory)
    include = ("include " + vhost_root + "/*.conf;").encode()
    if not main or not re.search(rb"(?m)^[ \t]*" + re.escape(include) + rb"[ \t]*(?:#.*)?$", main):
        raise TLSError("compatibility", "Native Nginx VHost include glob not verified")
    run = runner or subprocess.run
    try:
        response = run([nginx, "-T", "-c", nginx_conf],
                       capture_output=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TLSError("source", "Cannot inspect loaded Nginx TLS source") from exc
    if response.returncode != 0 or len(response.stdout) > MAX_DUMP:
        raise TLSError("source", "Nginx configuration dump invalid or exceeds read budget")
    try:
        sections = _source_sections(response.stdout.decode("utf-8"))
    except UnicodeError as exc:
        raise TLSError("source", "Nginx TLS source has invalid encoding") from exc
    owned_path = os.path.join(vhost_root, CONF_NAME)
    original, servers, found = [], [], False
    for filename, text in sections:
        if filename == owned_path:
            if found:
                raise TLSError("source", "TLS manager source included more than once")
            found = True
            continue
        original.append("# configuration file " + filename + ":\n" + text)
        servers.extend(_server_directives(text, stream=("/tcp/" in filename)))
    protocols, witnesses = {}, {}
    for server in servers:
        values = server["values"]
        for listener in values.get("listen", []):
            family = _family(listener)
            if family is None:
                continue
            parts = listener.split()
            if (server["stream"] or family == "address-specific"
                    or "ssl" not in parts[1:] or "quic" in parts[1:]
                    or "ipv6only=off" in parts[1:]
                    or "proxy_protocol" in parts[1:]):
                raise TLSError("compatibility",
                               "HTTPS/443 contains an address-specific, QUIC, stream or unsupported listen; no global default can be claimed")
            if "default_server" in parts[1:]:
                raise TLSError("conflict", "A foreign HTTPS/443 default_server already owns this socket")
            # A pre-existing default may have customized pre-SNI TLS
            # protocols. Preserve that first-server setting by family.
            if family not in protocols:
                proto = values.get("ssl_protocols", [])
                if len(proto) > 1:
                    raise TLSError("compatibility", "Ambiguous existing HTTPS protocol policy")
                selected = proto[0] if proto else None
                if selected and not re.fullmatch(r"TLSv[0-9.]+(?:\s+TLSv[0-9.]+)*", selected):
                    raise TLSError("compatibility", "Unsupported inherited TLS protocol policy")
                protocols[family] = selected
            if family not in witnesses:
                for expression in values.get("server_name", []):
                    names = expression.split()
                    host = next((value for value in names
                                 if HOST.fullmatch(value) and "." in value
                                 and not value.startswith((".", "*"))), None)
                    if host:
                        witnesses[family] = host
                        break
    return (_sha("".join(original).encode("utf-8")), found,
            protocols, witnesses)


def _tls_probe(family, name):
    """Probe real TLS on loopback; never disable TLS verification for users.

    This is a scoped diagnostic only: certificate identity is established by
    unchanged named-site source, not the relaxed loopback witness.
    """
    address = "::1" if family == "ipv6" else "127.0.0.1"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((address, 443), timeout=3) as conn:
            with context.wrap_socket(conn, server_hostname=name):
                return "accepted"
    except ssl.SSLError as exc:
        if "unrecognized name" in str(exc).lower():
            return "rejected"
        raise TLSError("probe", "TLS failed without the expected unknown-SNI alert: "
                       + str(exc)[:180]) from exc
    except ConnectionRefusedError:
        return "refused"
    except (OSError, TimeoutError) as exc:
        raise TLSError("probe", "Loopback HTTPS/443 is unavailable: " + str(exc)[:160]) from exc


def _probe_family(family, witness, *, rejection, absent=False, probe=None):
    """Verify the live workers, not merely the reload command's exit code.

    Nginx -s reload returns before all worker sockets settle. A first
    post-reload handshake can be routed to the previous worker generation.
    Require three consecutive correct fresh observations within a bounded
    settle window; never treat a single TLS alert, TCP refusal or timeout
    as successful Apply/Restore, and retain a diagnostic on expiration.
    """
    fn = probe or _tls_probe
    expected = "refused" if absent else "rejected" if rejection else "accepted"
    deadline = time.monotonic() + 10
    consecutive = 0
    last_reason = "No completed TLS observation"
    while True:
        unknown = "ach-unknown-" + uuid4().hex + ".invalid"
        try:
            got_unknown = fn(family, unknown)
            got_none = fn(family, None)
            got_known = None if absent else fn(family, witness)
            if (got_unknown == expected and got_none == expected
                    and (absent or got_known == "accepted")):
                consecutive += 1
                if consecutive >= 3:
                    return
                continue
            last_reason = (
                "unknown-SNI=" + str(got_unknown) +
                ", no-SNI=" + str(got_none) +
                (", named-SNI=" + str(got_known) if not absent else "")
            )
        except TLSError as exc:
            last_reason = exc.stage + ": " + str(exc)[:180]
        consecutive = 0
        if time.monotonic() >= deadline:
            raise TLSError("postcheck",
                           "TLS " + family + " workers did not settle within 10 seconds; " +
                           last_reason)
        time.sleep(0.2)


def _response(state, source, record, families, witnesses, *, changed=False,
              verified=False, reason="", read_only=True):
    return {
        "schema": 1, "mode": "native_unknown_tls_reject",
        "state": state, "source_sha256": source,
        "recovery_id": record["operation_id"] if record else None,
        "families": list(families), "witnesses": dict(witnesses),
        "changed": changed, "runtime_verified": verified,
        "reason": reason, "read_only": read_only,
        "impact": "Reject unknown/no-SNI on existing HTTPS/443 TCP wildcard sockets; preserve named HTTPS and HTTP/80",
    }


def manage_tls(action, *, data_fd, expected_source=None, expected_recovery=None,
               vhost_root=VHOST_ROOT, nginx=NGINX, nginx_conf=NGINX_CONF,
               runner=None, probe=None):
    if action not in ("recheck", "apply", "restore"):
        raise TLSError("input", "Unknown TLS rejection operation")
    _owned_dir(data_fd)
    vfd = _directory(vhost_root)
    try:
        _owned_dir(vfd)
        record = _journal_read(data_fd)
        conf = _bounded_file(vfd, CONF_NAME, limit=8192, permissions=0o600)
        retired_name = "." + CONF_NAME + "." + record["operation_id"] + ".retired" if record else None
        retired = (_bounded_file(vfd, retired_name, limit=8192, permissions=0o600)
                   if retired_name else None)
        source, present, protocols, witnesses = _loaded_source(
            nginx=nginx, nginx_conf=nginx_conf, vhost_root=vhost_root, runner=runner)
        families = list(protocols)
        if conf is not None and not present:
            raise TLSError("source", "Managed TLS file exists but is not loaded")
        if action == "recheck":
            if not record:
                state = ("Source Ready" if families and set(families) == set(witnesses)
                         and conf is None else
                         "Not Applicable" if not families and conf is None else "Conflict")
                reason = ("No existing Nginx HTTPS/443 wildcard listeners; no new socket will be opened"
                          if state == "Not Applicable" else
                          "Each existing HTTPS family needs a named HTTPS witness"
                          if state == "Conflict" else "")
                verified = False
            elif record["phase"] == "restored":
                state = ("Not Applicable" if not families and conf is None and retired is None
                         else "Restored" if conf is None and retired is None else "Drift")
                reason, verified = (
                    "No existing HTTPS/443 wildcard listener" if state == "Not Applicable" else ""
                ), False
            elif (record["phase"] == "applied" and conf is not None and present and
                  _sha(conf) == record["config_sha256"] and
                  set(record["families"]) == set(families)):
                try:
                    for family in record["families"]:
                        _probe_family(family, record["witnesses"][family],
                                      rejection=True, probe=probe)
                    verified, state, reason = True, "Applied", ""
                except TLSError as exc:
                    verified, state, reason = False, "Needs Review", str(exc)
            else:
                verified, state, reason = False, "Recovery Required", ""
            return _response(state, source, record, families, witnesses,
                             verified=verified, reason=reason)
        if action == "apply":
            if ((record and record["phase"] != "restored")
                    or conf is not None or retired is not None):
                raise TLSError("recovery", "Previous TLS policy must be Rechecked or Restored first")
            if not families or set(families) != set(witnesses):
                raise TLSError("compatibility", "Existing named HTTPS/443 wildcard socket is required")
            if expected_source != source:
                raise TLSError("concurrency", "Nginx TLS source changed since Recheck")
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            for family in families:
                _probe_family(family, witnesses[family], rejection=False, probe=probe)
            operation_id = uuid4().hex
            config = _config(operation_id, families, protocols)
            journal = {"schema": 1, "operation_id": operation_id, "phase": "prepared",
                       "source_sha256": source, "config_sha256": _sha(config),
                       "families": families, "protocols": protocols,
                       "witnesses": witnesses}
            _journal_write(data_fd, journal)
            try:
                _publish_complete(vfd, CONF_NAME, config, 0o600, operation_id)
                try:
                    _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
                except ExtensionError:
                    if _bounded_file(vfd, CONF_NAME, limit=8192, permissions=0o600) == config:
                        _rename_noreplace(vfd, CONF_NAME, retired_name or
                                          "." + CONF_NAME + "." + operation_id + ".retired")
                        os.fsync(vfd)
                    raise
                renewed = _loaded_source(nginx=nginx, nginx_conf=nginx_conf,
                                         vhost_root=vhost_root, runner=runner)
                if renewed != (source, True, protocols, witnesses):
                    raise TLSError("concurrency", "Nginx source changed during TLS Apply")
                _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
                for family in families:
                    _probe_family(family, witnesses[family], rejection=True, probe=probe)
                journal["phase"] = "applied"
                _journal_write(data_fd, journal)
            except Exception as exc:
                raise TLSError(
                    "uncertain",
                    "TLS Apply uncertain after " + str(getattr(exc, "stage", type(exc).__name__)) +
                    ": " + str(exc)[:190] + "; inspect saved Recovery ID before retry",
                    recovery_id=operation_id) from exc
            return _response("Applied", source, journal, families, witnesses,
                             changed=True, verified=True, read_only=False)

        if not record or record["phase"] == "restored":
            raise TLSError("recovery", "No TLS recovery journal to Restore")
        if expected_recovery != record["operation_id"] or expected_source != source:
            raise TLSError("concurrency", "TLS recovery selection changed; Recheck")
        if ((conf is not None and _sha(conf) != record["config_sha256"])
                or (retired is not None and _sha(retired) != record["config_sha256"])
                or (record["phase"] == "applied" and conf is None)):
            raise TLSError("recovery", "Exact managed TLS config is missing or modified")
        if conf is not None and retired is not None:
            raise TLSError("recovery", "Duplicate active and retired TLS configs; manual review needed")
        journal = dict(record, phase="restoring")
        _journal_write(data_fd, journal)
        try:
            if conf is not None:
                _rename_noreplace(vfd, CONF_NAME, retired_name)
                os.fsync(vfd)
            renewed = _loaded_source(nginx=nginx, nginx_conf=nginx_conf,
                                     vhost_root=vhost_root, runner=runner)
            if renewed[0] != source or renewed[1]:
                raise TLSError("concurrency", "Nginx TLS source changed during Restore")
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
            for family in record["families"]:
                _probe_family(family, record["witnesses"][family],
                              rejection=False, absent=family not in families, probe=probe)
            if _loaded_source(nginx=nginx, nginx_conf=nginx_conf,
                              vhost_root=vhost_root, runner=runner)[1]:
                raise TLSError("postcheck", "Managed TLS route still present after Restore")
            if conf is not None or retired is not None:
                retained = _bounded_file(vfd, retired_name, limit=8192, permissions=0o600)
                if retained is None or _sha(retained) != record["config_sha256"]:
                    raise TLSError("recovery", "Retired TLS config changed during Restore")
                os.unlink(retired_name, dir_fd=vfd)
                os.fsync(vfd)
            journal["phase"] = "restored"
            _journal_write(data_fd, journal)
        except Exception as exc:
            raise TLSError(
                "uncertain",
                "TLS Restore uncertain after " + str(getattr(exc, "stage", type(exc).__name__)) +
                ": " + str(exc)[:190] + "; retain Recovery ID and Recheck",
                recovery_id=record["operation_id"]) from exc
        return _response("Restored", source, journal, families, witnesses,
                         changed=True, verified=True, read_only=False)
    finally:
        os.close(vfd)
