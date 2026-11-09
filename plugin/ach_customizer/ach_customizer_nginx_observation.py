"""On-demand Nginx *candidate configuration* and origin HTTP/80 observations.

nginx -T reads the configuration that would be used on a future load. It does
NOT inspect the config held by existing workers. A loopback HTTP HEAD observes
a response, but cannot identify which server/location produced it. These are
independent, deliberately non-authorizing read-only observations.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import re
import selectors
import subprocess
import time
from pathlib import Path

from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _bounded_file_text,
    MAX_NGINX_SITE_BYTES,
)
from ach_customizer_cache_audit import _direct_http_scope_at
from ach_customizer_vhost_drift import SITE_KEY, _canonical_host

NGINX_BIN = "/www/server/nginx/sbin/nginx"
NGINX_CONF = "/www/server/nginx/conf/nginx.conf"
VHOST_DIR = "/www/server/panel/vhost/nginx"
MAX_DUMP_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 32 * 1024
TIMEOUT = 8
SECTION = re.compile(rb"(?m)^# configuration file (/[^:\r\n]+):[ \t]*\r?$")
NOTE = (
    "Nginx -T syntax/include evidence describes files that a NEW load would "
    "read, not the running worker configuration. A localhost HEAD observes "
    "only the HTTP/80 response for the selected native Host, not that a "
    "particular VHost, PHP pool, cache policy or identity served it. "
    "No reload, purge, configuration edit, redirect follow or remote request."
)


class NginxObservationError(MonitorInputError):
    pass


def _run_bounded_dump(executable, config, *, deadline=TIMEOUT):
    """Drain both pipes with a hard byte/time limit; never emit config text.

    No shell and no Nginx -s reload. Calling -T can check referenced files,
    but it does not signal or reconfigure an already running master.
    """
    process = subprocess.Popen(
        [str(executable), "-T", "-c", str(config)], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
    )
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
    started = time.monotonic()
    try:
        selector.register(process.stdout, selectors.EVENT_READ, "out")
        selector.register(process.stderr, selectors.EVENT_READ, "err")
        while selector.get_map():
            if time.monotonic() - started > deadline:
                raise NginxObservationError("Nginx candidate test exceeded the 8-second deadline")
            for key, _ in selector.select(timeout=0.2):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = stdout if key.data == "out" else stderr
                buffer.extend(chunk)
                if len(stdout) > MAX_DUMP_BYTES or len(stderr) > MAX_STDERR_BYTES:
                    raise NginxObservationError(
                        "Nginx candidate output exceeded bounded inspection capacity")
        remaining = deadline - (time.monotonic() - started)
        if remaining <= 0:
            raise NginxObservationError("Nginx candidate test exceeded the deadline")
        process.wait(timeout=remaining)
        if process.returncode != 0:
            # Only a small diagnostic excerpt from stderr, never the dumped
            # configuration or unchecked stdout, reaches the admin UI.
            diagnostic = stderr.decode("utf-8", "replace").strip()
            diagnostic = re.sub(r"[\r\n\t]+", " ", diagnostic)[:250]
            raise NginxObservationError(
                "Nginx candidate config test failed (exit " +
                str(process.returncode) + "): " +
                (diagnostic or "Inspect Nginx error logs"))
        return bytes(stdout)
    except subprocess.TimeoutExpired as exc:
        raise NginxObservationError("Nginx candidate test exceeded the deadline") from exc
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def _native_http_include(main_source, vhost_root):
    """Verify the aaPanel native VHost glob in the actual main HTTP source.

    Nginx -T section markers are plain text: comments inside other included
    files can forge them. A dump match is not include provenance by itself.
    """
    active = _active_nginx_text(main_source)
    pattern = re.compile(
        r"(?m)^[ \t]*include[ \t]+" + re.escape(str(Path(vhost_root))) +
        r"/\*\.conf[ \t]*;[ \t]*(?=\r?$)"
    )
    if not any(_direct_http_scope_at(active, match.start())
               for match in pattern.finditer(active)):
        raise NginxObservationError(
            "Selected VHost has no verified direct native HTTP include source")


def _candidate_site_section(dump, expected_path, source):
    """Compare literal Nginx -T sections; this alone is not provenance.

    -T expands includes but cannot attest active workers or server precedence.
    Nginx may deduplicate dumped filenames; a section count does not prove
    the number of include operations. Compare complete body/framing strictly.
    """
    markers = list(SECTION.finditer(dump))
    if not markers or len(markers) > 512:
        raise NginxObservationError("Nginx candidate sections missing or exceed supported inventory")
    expected = os.fsencode(str(expected_path))
    matches = []
    for pos, marker in enumerate(markers):
        if marker.group(1) != expected:
            continue
        next_start = markers[pos + 1].start() if pos + 1 < len(markers) else len(dump)
        # Nginx 1.28.3 -T emits a leading LF after its section header and
        # one trailing LF after the source bytes. Compare the exact framing
        # rather than stripping arbitrary newlines: otherwise a changed
        # source tail could masquerade as identical.
        body = dump[marker.end():next_start]
        matches.append(body)
    if not matches:
        return "Not Included", False
    if len(matches) != 1:
        raise NginxObservationError("Selected native VHost appears in multiple Nginx candidate sections")
    if matches[0] != b"\n" + source + b"\n":
        raise NginxObservationError(
            "Selected VHost section in Nginx candidate differs from stable disk file")
    return "Included", True


def _local_head(host, *, connection_factory=http.client.HTTPConnection):
    try:
        connection = connection_factory("127.0.0.1", 80, timeout=3)
        try:
            connection.putrequest("HEAD", "/", skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host)
            connection.endheaders()
            result = connection.getresponse()
            if type(result.status) is not int or not 100 <= result.status <= 599:
                raise NginxObservationError("Invalid local HTTP/80 response status")
            return {"state": "Response Observed", "host": host,
                    "http_status": result.status, "site_identity_verified": False}
        finally:
            connection.close()
    except (OSError, http.client.HTTPException, TimeoutError) as exc:
        return {"state": "Unavailable", "host": host, "http_status": None,
                "site_identity_verified": False,
                "reason": "localhost HTTP/80 HEAD unavailable (" + type(exc).__name__ + ")"}


def observe_nginx_site(panel_public, site, *, vhost_root=VHOST_DIR,
                       nginx_bin=NGINX_BIN, nginx_conf=NGINX_CONF,
                       dump_runner=_run_bounded_dump, head_runner=_local_head):
    """Correlate selected native site with prospective config and live HEAD.

    Caller supplies a separately verified native DB snapshot and rechecks it
    after return. No browser-controlled paths, ports, URLs or headers.
    """
    response = {
        "schema": 1, "site_id": site.get("id"), "site_key": site.get("name"),
        "state": "Needs Review", "read_only": True,
        "runtime_verified": False, "fix_supported": False,
        "candidate_config_test_passed": False,
        "candidate_vhost_included": False,
        "candidate_config_sha256": None,
        "vhost_content_sha256": None,
        "origin_http": {"state": "Not Attempted", "host": None,
                        "http_status": None, "site_identity_verified": False},
        "reason": "", "note": NOTE,
    }
    try:
        if (type(site.get("id")) is not int or not 1 <= site["id"] <= 2147483647 or
                not isinstance(site.get("name"), str) or
                not SITE_KEY.fullmatch(site["name"]) or
                panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != "8.0.7"):
            raise NginxObservationError("Only selected aaPanel 8.0.7 Nginx sites are supported")
        if str(nginx_bin) != NGINX_BIN or str(nginx_conf) != NGINX_CONF:
            raise NginxObservationError("Unrecognized native Nginx binary or config")
        # Test helper may override vhost_root, but not a real endpoint caller.
        path = Path(vhost_root) / (site["name"] + ".conf")
        source, signature = _bounded_file_text(path, MAX_NGINX_SITE_BYTES,
                                                 with_fingerprint=True)
        main_source, main_signature = _bounded_file_text(
            Path(nginx_conf), MAX_NGINX_SITE_BYTES, with_fingerprint=True)
        raw = source.encode("utf-8")
        dump = dump_runner(nginx_bin, nginx_conf)
        if not isinstance(dump, bytes) or len(dump) > MAX_DUMP_BYTES:
            raise NginxObservationError("Nginx candidate output is oversized or malformed")
        included_state, included = _candidate_site_section(dump, path, raw)
        if included:
            # A forged section header in another file is not proof that this
            # native VHost was opened by the successful config test.
            _native_http_include(main_source, vhost_root)
        # Check both independent include source and selected VHost for drift.
        if (main_signature != _bounded_file_text(
                Path(nginx_conf), MAX_NGINX_SITE_BYTES,
                with_fingerprint=True)[1] or
                signature != _bounded_file_text(path, MAX_NGINX_SITE_BYTES,
                                                 with_fingerprint=True)[1] or
                panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != "8.0.7"):
            raise NginxObservationError("Nginx or native VHost source changed during inspection")
        response.update({
            "state": "Candidate Included" if included else "Candidate Not Included",
            "candidate_config_test_passed": True,
            "candidate_vhost_included": included,
            "candidate_config_sha256": hashlib.sha256(dump).hexdigest(),
            "vhost_content_sha256": hashlib.sha256(raw).hexdigest(),
        })
        # Active HTTP/80 is a distinct, optional observation of native names.
        # Only a valid literal native HTTP/80 binding can supply Host.
        bindings = site.get("bound_domains")
        if not isinstance(bindings, list) or len(bindings) > 100:
            raise NginxObservationError("Native Host bindings unavailable for HTTP observation")
        hosts = sorted({
            _canonical_host(row["name"])
            for row in bindings
            if isinstance(row, dict) and type(row.get("port")) is int and
            row["port"] == 80
        })
        if hosts:
            response["origin_http"] = head_runner(hosts[0])
        else:
            response["origin_http"]["state"] = "No HTTP/80 Binding"
    except (MonitorInputError, OSError, ValueError, TypeError,
            RuntimeError, subprocess.SubprocessError) as exc:
        response["state"] = "Needs Review"
        response["candidate_config_test_passed"] = False
        response["candidate_vhost_included"] = False
        response["candidate_config_sha256"] = None
        response["vhost_content_sha256"] = None
        response["origin_http"] = {"state": "Not Attempted", "host": None,
                                   "http_status": None, "site_identity_verified": False}
        response["reason"] = str(exc)[:350]
    return response
