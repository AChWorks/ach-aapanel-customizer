"""Read-only aaPanel site record vs generated Nginx VHost comparison.

This checks the selected native site's root and host bindings against a stable
file snapshot. It does not inspect nginx -T, DNS, TLS, nested routing, or a
persistent desired policy, and never changes a file or service.
"""
from __future__ import annotations

import re
from pathlib import Path

from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _bounded_file_text,
    MAX_NGINX_SITE_BYTES,
)

SITE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
HOSTNAME = re.compile(r"(?:\*\.)?[A-Za-z0-9][A-Za-z0-9._-]{0,252}\Z")
ROOT = re.compile(r"/[A-Za-z0-9_./-]{1,2047}\Z")
NOTE = (
    "Comparison of registered aaPanel site/domain records with the generated "
    "Nginx VHost file only. It is not an active nginx -T, effective location, "
    "TLS/DNS, WordPress Toolkit ownership, runtime or desired-policy check. "
    "No website configuration, generated VHost, cache or service state "
    "was changed; this inspection may append a plugin Activity entry."
)


class VhostDriftError(MonitorInputError):
    pass


def _canonical_host(raw):
    if not isinstance(raw, str) or not HOSTNAME.fullmatch(raw):
        raise VhostDriftError("Unrecognized native website hostname")
    # Exactly one terminal DNS root dot is an accepted spelling variant;
    # multiple trailing dots are malformed and must never normalize to a match.
    if raw.endswith(".."):
        raise VhostDriftError("Noncanonical trailing dots in website hostname")
    name = (raw[:-1] if raw.endswith(".") else raw).lower()
    if name.startswith("*.") or ".." in name or "_" in name or any(
        not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
        for part in name.split(".")
    ):
        raise VhostDriftError("Wildcard or ambiguous website binding needs manual review")
    return name


def _server_statements(source):
    """Parse only simple server-level statements, rejecting syntax ambiguity.

    Nginx nested blocks are NOT treated as server statements. Unknown nested
    location/routing semantics mean this is only a file-level comparison.
    Braces inside quoted values are ignored; ambiguous escaping is refused.
    """
    text = _active_nginx_text(source)
    depth, statement, quote, escaped, server_count = 0, [], None, False, 0
    result = {"root": [], "server_name": [], "listen": []}
    nested_overrides = False
    for ch in text:
        if escaped:
            # An escaped metacharacter is literal, never a block delimiter.
            statement.extend(("\\", ch))
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote is not None:
            if ch == quote:
                quote = None
            statement.append(ch)
            continue
        if ch in "\"'":
            quote = ch
            statement.append(ch)
            continue
        if ch in "{};":
            part = "".join(statement).strip()
            statement.clear()
            if ch == "{":
                if depth == 0:
                    if part != "server":
                        raise VhostDriftError("Expected one native server block")
                    server_count += 1
                elif re.match(r"^(?:server_name|root|listen)(?:\s|$)", part):
                    raise VhostDriftError("Nested Nginx server settings need manual review")
                depth += 1
            elif ch == "}":
                if part or depth == 0:
                    raise VhostDriftError("Malformed Nginx VHost block")
                depth -= 1
            else:
                if not part or depth == 0:
                    raise VhostDriftError("Unscoped or malformed Nginx statement")
                fields = part.split()
                if not fields:
                    raise VhostDriftError("Malformed Nginx VHost statement")
                if fields[0] in result:
                    if depth != 1:
                        if fields[0] in ("root", "server_name"):
                            nested_overrides = True
                    else:
                        result[fields[0]].append(fields[1:])
            continue
        statement.append(ch)
    if quote or escaped or depth != 0 or "".join(statement).strip() or server_count != 1:
        raise VhostDriftError("Incomplete or multiple native Nginx server blocks")
    if nested_overrides:
        raise VhostDriftError("Nested root/server_name may override generated site metadata")
    return result


def _literal_document_root(path):
    """A literal absolute path with at most one terminal slash.

    Do not normalize traversal, doubled separators, or dot components into a
    File Match; this is a byte-source comparison, not filesystem resolution.
    """
    return (isinstance(path, str) and ROOT.fullmatch(path) is not None
            and "//" not in path
            and all(component not in (".", "..")
                    for component in path.split("/")[1:]))


def _same_native_document_root(native, generated):
    # Exactly one optional terminal slash; all other path bytes must agree.
    return native == generated or (
        generated.endswith("/") and generated[:-1] == native
    ) or (
        native.endswith("/") and native[:-1] == generated
    )


def _inspect(site, vhost_root):
    site_key = site.get("name")
    if not isinstance(site_key, str) or not SITE_KEY.fullmatch(site_key):
        raise VhostDriftError("Unsupported native website VHost key")
    native_root = site.get("path")
    if not _literal_document_root(native_root):
        raise VhostDriftError("Native document root uses an unsupported path shape")
    bindings = site.get("bound_domains")
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 100:
        raise VhostDriftError("Native domain inventory is missing or too large")
    if any(not isinstance(row, dict) or type(row.get("port")) is not int or
           not 1 <= row["port"] <= 65535 for row in bindings):
        raise VhostDriftError("Malformed native domain or port binding")
    native_names = {_canonical_host(row.get("name")) for row in bindings}
    if len(native_names) > 100:
        raise VhostDriftError("Too many website hostnames")
    path = Path(vhost_root) / (site_key + ".conf")
    source, signature = _bounded_file_text(path, MAX_NGINX_SITE_BYTES,
                                            with_fingerprint=True)
    statements = _server_statements(source)
    if len(statements["root"]) != 1 or len(statements["root"][0]) != 1:
        raise VhostDriftError("A single generated Nginx document root is required")
    generated_root = statements["root"][0][0]
    if not _literal_document_root(generated_root):
        raise VhostDriftError("Generated Nginx document root is not a literal safe path")
    if len(statements["server_name"]) != 1 or not statements["server_name"][0]:
        raise VhostDriftError("A single generated server_name statement is required")
    generated_names = [_canonical_host(name) for name in statements["server_name"][0]]
    if len(set(generated_names)) != len(generated_names):
        raise VhostDriftError("Duplicate generated Nginx server_name entries")
    drift = []
    if not _same_native_document_root(native_root, generated_root):
        drift.append("DOCUMENT_ROOT_MISMATCH")
    if native_names - set(generated_names):
        drift.append("BOUND_HOST_MISSING_IN_VHOST")
    if set(generated_names) - native_names:
        drift.append("VHOST_HOST_NOT_IN_NATIVE_BINDINGS")
    ports = []
    for line in statements["listen"]:
        if not line or not re.fullmatch(r"(?:[0-9]{1,5}|(?:\[::\]|0\.0\.0\.0):[0-9]{1,5})", line[0]):
            raise VhostDriftError("Unsupported Nginx listen form; compare ports manually")
        ports.append(int(line[0].rsplit(":", 1)[-1]))
    if any(port < 1 or port > 65535 for port in ports):
        raise VhostDriftError("Invalid Nginx listen port")
    # Native domain.port does not necessarily represent every SSL listener:
    # exposing the two sets is useful, but they are NOT compared as drift.
    return {
        "vhost_sha256": signature,
        "native_root": native_root, "vhost_root": generated_root,
        "native_names": sorted(native_names),
        "vhost_names": sorted(generated_names),
        "listen_ports": sorted(set(ports)), "findings": drift,
    }


def inspect_vhost_drift(panel_public, site, *,
                        vhost_root="/www/server/panel/vhost/nginx"):
    """Two stable file reads; entrypoint verifies exact native DB identity."""
    response = {
        "schema": 1, "site_id": site.get("id"), "site_key": site.get("name"),
        "state": "Needs Review", "read_only": True,
        "runtime_verified": False, "fix_supported": False,
        "vhost_sha256": None, "native_root": None, "vhost_root": None,
        "native_names": [], "vhost_names": [], "listen_ports": [],
        "findings": [], "reason": "", "note": NOTE,
    }
    try:
        if (type(site.get("id")) is not int or not 1 <= site["id"] <= 2147483647 or
                panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != "8.0.7"):
            raise VhostDriftError("Only a selected aaPanel 8.0.7 Nginx website can be inspected")
        initial = _inspect(site, vhost_root)
        if initial != _inspect(site, vhost_root):
            raise VhostDriftError("Generated Nginx VHost changed during comparison")
        if (panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != "8.0.7"):
            raise VhostDriftError("Native panel version or web engine changed during inspection")
        response.update(initial)
        response["state"] = "File Drift" if initial["findings"] else "File Match"
    except (MonitorInputError, OSError, ValueError, TypeError, RuntimeError) as exc:
        response["reason"] = str(exc)[:250]
    return response
