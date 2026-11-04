"""Explicit read-only loopback HTTP 404 evidence for one native aaPanel site.

The probe neither enables Apply/Restore nor claims to inspect the running
Nginx configuration. It checks one generated nonexistent URL with an aaPanel
database-bound HTTP/80 Host header; it does not resolve or contact that domain.
No redirects, cookies, arbitrary client URLs, TLS bypass, or service writes.
"""
from __future__ import annotations

import hashlib
import http.client
import re
from uuid import uuid4

from ach_customizer_status_inspect import (
    MAX_FILE_BYTES, VHOST_ROOT, inspect_site_files,
)
from ach_customizer_status_pages import StatusPageError

MAX_BODY_BYTES = MAX_FILE_BYTES
HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


class StatusProbeError(StatusPageError):
    pass


def _host(name):
    if (not isinstance(name, str) or len(name) > 253
            or len(name) < 3 or "." not in name
            or any(not HOST_LABEL.fullmatch(label) for label in name.split("."))):
        raise StatusProbeError("Native site hostname is not a supported literal HTTP Host")
    return name


def _source_identity(result):
    return (
        result.get("site_id"), result.get("site_key"),
        result.get("page_file_sha256"), result.get("page_file_bytes"),
        result.get("vhost_sha256"),
        result.get("extension_include_textual"),
        tuple(result.get("extensions_scanned", [])),
        tuple(result.get("error_page_sources", [])),
    )


def probe_site_404(site, *, locale, rendered_sha256, rendered_html=None,
                   vhost_root=VHOST_ROOT, port=80, connection_factory=None,
                   token_factory=None):
    """Return bounded response evidence for an explicit full-admin operation.

    Port and injected HTTP factory are internal test seams, not request inputs.
    This observes only HTTP/80 on loopback. It cannot attest HTTPS/443, worker
    generation, Cloudflare, routes for other URLs, or a safe Apply adapter.
    """
    if not isinstance(site, dict):
        raise StatusProbeError("Invalid native site")
    site_id = site.get("id")
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise StatusProbeError("Invalid native site ID")
    host = _host(site.get("name"))
    if str(site.get("status")) != "1":
        raise StatusProbeError("Native site is stopped; a 404 probe is unsupported")
    if (type(port) is not int or not 1 <= port <= 65535
            or not isinstance(rendered_sha256, str) or not SHA.fullmatch(rendered_sha256)):
        raise StatusProbeError("Invalid probe configuration or page identity")
    bindings = site.get("bound_domains")
    if (not isinstance(bindings, list) or
            not any(item == {"name": host, "port": 80} for item in bindings)):
        raise StatusProbeError("Native canonical website is not explicitly bound on HTTP/80")

    result = {
        "schema": 1, "site_id": site_id, "site_key": host,
        "template": "404", "locale": locale, "state": "Needs Review",
        "reason": "", "read_only": True, "apply_supported": False,
        "nginx_runtime_verified": False, "scope": "loopback_http_80",
        "http_status": None, "http_404_observed": False,
        "body_sha256": None, "body_bytes": None,
        "page_file_sha256": None, "rendered_sha256": rendered_sha256,
        "body_matches_file": False, "body_matches_render": False,
        "note": (
            "One explicit GET of a random nonexistent path on 127.0.0.1:80 "
            "with the native bound Host header. It is not proof of loaded "
            "Nginx routes, TLS/Cloudflare delivery, other URLs or safe Apply."
        ),
    }
    pre = inspect_site_files(
        site, locale=locale, template="404",
        rendered_sha256=rendered_sha256, rendered_html=rendered_html,
        vhost_root=vhost_root,
    )
    if (pre.get("page_file_state") not in ("Same bytes", "Different bytes")
            or pre.get("vhost_sha256") is None
            or pre.get("page_file_sha256") is None
            or not isinstance(pre.get("page_file_bytes"), int)
            or pre["page_file_bytes"] <= 0
            or pre.get("state") == "Unsupported"):
        result["reason"] = "Native page or VHost source cannot be safely inspected"
        return result

    # Use only an internal UUID, never user input for the probe URL. Both the
    # socket endpoint and the Host header are fixed by verified server data.
    token = token_factory() if token_factory else uuid4().hex
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise StatusProbeError("Invalid internal probe token")
    path = "/ach-status-probe-" + token
    factory = connection_factory or http.client.HTTPConnection
    connection = None
    try:
        connection = factory("127.0.0.1", port, timeout=3)
        connection.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host)
        connection.putheader("Accept", "text/html")
        connection.putheader("Accept-Encoding", "identity")
        connection.putheader("Cache-Control", "no-cache")
        connection.putheader("Connection", "close")
        connection.endheaders()
        response = connection.getresponse()
        code = response.status
        if type(code) is not int or not 100 <= code <= 599:
            raise StatusProbeError("Invalid local HTTP response status")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise StatusProbeError("Local HTTP response was compressed")
        declared = response.getheader("Content-Length")
        if declared is not None:
            if not re.fullmatch(r"[0-9]{1,7}", declared) or int(declared) > MAX_BODY_BYTES:
                raise StatusProbeError("Local HTTP response exceeds the bounded read limit")
        data = response.read(MAX_BODY_BYTES + 1)
        if len(data) > MAX_BODY_BYTES:
            raise StatusProbeError("Local HTTP response exceeded the bounded read limit")
        # Refuse truncated fixed-length responses; empty response is allowed
        # for mismatch diagnostics, never for positive proof.
        if declared is not None and len(data) != int(declared):
            raise StatusProbeError("Local HTTP response length is incomplete")
    except (OSError, TimeoutError, http.client.HTTPException, StatusProbeError) as exc:
        result["reason"] = ("Local HTTP/80 probe unavailable: " + str(exc))[:240]
        return result
    finally:
        if connection is not None:
            connection.close()

    post = inspect_site_files(
        site, locale=locale, template="404",
        rendered_sha256=rendered_sha256, rendered_html=rendered_html,
        vhost_root=vhost_root,
    )
    if (post.get("state") == "Unsupported" or
            pre.get("state") == "Needs Review" and pre.get("vhost_sha256") is None or
            _source_identity(pre) != _source_identity(post) or
            post.get("vhost_sha256") is None):
        result["reason"] = "Native source changed during HTTP probe; recheck before drawing conclusions"
        return result

    digest = hashlib.sha256(data).hexdigest()
    match_file = code == 404 and digest == pre["page_file_sha256"]
    match_render = match_file and digest == rendered_sha256
    result.update(
        state="HTTP Match" if match_file else "HTTP Mismatch",
        reason=(
            "Observed HTTP 404 with byte-identical site page" if match_file else
            "HTTP response does not prove the selected site file is served as 404"
        ),
        http_status=code, http_404_observed=(code == 404),
        body_sha256=digest, body_bytes=len(data),
        page_file_sha256=pre["page_file_sha256"],
        body_matches_file=match_file, body_matches_render=match_render,
    )
    return result
