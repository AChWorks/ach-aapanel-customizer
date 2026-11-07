"""Conservative *configured-source* guard for a simple aaPanel HTTP/80 404.

The ordinary site's Nginx VHost and a bounded nginx -T dump must agree.
This intentionally supports only one literal, non-TLS, non-rewriting static
server. The dump describes the current *disk* configuration, not the loaded
workers. A separate bounded HTTP/80 response probe remains mandatory.

Do not broaden support through string search alone: nested locations, includes,
TLS, alias, shared roots and different server layouts require a reviewed adapter.
"""
from __future__ import annotations

import hashlib
import os
import re
import select
import stat
import subprocess
import time

from ach_customizer_status_inspect import (
    _directory, _file_snapshot, READ_FLAGS, VHOST_ROOT,
)

NATIVE_NGINX = "/www/server/nginx/sbin/nginx"
MAX_DUMP_BYTES = 4 * 1024 * 1024
DUMP_DEADLINE = 5.0
HEADER = re.compile(r"(?m)^# configuration file (/[^:\r\n]+):[ \t]*$")
NAME = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,252})\Z")
PATH = re.compile(r"/[a-zA-Z0-9/_.-]{1,1023}\Z")


class RouteGuardError(ValueError):
    pass


def _canonical_path(value):
    return (isinstance(value, str) and PATH.fullmatch(value) is not None
            and not value.endswith("/") and "//" not in value
            and all(p not in ("", ".", "..") for p in value.split("/")[1:]))


def _external_path_consumer(config, document_root):
    # Reject unprovable dynamic/quoted/relative roots and shared parent paths.
    # Exact text inequality is insufficient when aliases or path traversal
    # reach the same document root. This is intentionally a narrow gate.
    for m in re.finditer(r"(?m)(?<![A-Za-z0-9_])(?:root|alias)\s+([^;{}]+);",
                         config):
        path = m.group(1).strip()
        if not _canonical_path(path):
            raise RouteGuardError("Ambiguous or noncanonical other-site root/alias")
        if (path == document_root or path.startswith(document_root + "/")
                or document_root.startswith(path + "/")):
            raise RouteGuardError("Configured Nginx source shares a selected site path")
    # A malformed/unterminated root or alias must not evade the matcher.
    raw = len(re.findall(r"(?m)(?<![A-Za-z0-9_])(?:root|alias)(?=\s)", config))
    parsed = len(list(re.finditer(
        r"(?m)(?<![A-Za-z0-9_])(?:root|alias)\s+([^;{}]+);", config)))
    if raw != parsed:
        raise RouteGuardError("Other-site root/alias directive is not recognizable")


def _capture_nginx_t():
    """Run only the installed, checked native executable; no shell or reload.

    Limit output while streaming, never materialize arbitrary configuration
    data into an unbounded subprocess.run(capture_output=True). Never log or
    return the potentially sensitive full Nginx configuration to panel users.
    """
    parent = os.path.dirname(NATIVE_NGINX)
    directory = _directory(parent)
    try:
        parent_info = os.fstat(directory)
        if parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
            raise RouteGuardError("Native nginx executable directory is untrusted")
        fd = os.open(os.path.basename(NATIVE_NGINX),
                     READ_FLAGS, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                    info.st_mode & 0o022 or not info.st_mode & 0o111):
                raise RouteGuardError("Native nginx executable ownership is untrusted")
        finally:
            os.close(fd)
    finally:
        os.close(directory)

    process = subprocess.Popen(
        [NATIVE_NGINX, "-T"], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        close_fds=True,
    )
    output = bytearray()
    deadline = time.monotonic() + DUMP_DEADLINE
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RouteGuardError("Nginx configuration inspection timed out")
            readable, _, _ = select.select([process.stdout], [], [], remaining)
            if not readable:
                raise RouteGuardError("Nginx configuration inspection timed out")
            part = os.read(process.stdout.fileno(),
                           min(65536, MAX_DUMP_BYTES + 1 - len(output)))
            if not part:
                break
            output.extend(part)
            if len(output) > MAX_DUMP_BYTES:
                raise RouteGuardError("Nginx configuration dump exceeds bounded limit")
        try:
            status = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise RouteGuardError("Nginx config process exceeded bounded deadline") from exc
        if status != 0:
            raise RouteGuardError("Native nginx -T failed; no site Apply permitted")
        try:
            return output.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RouteGuardError("Nginx configuration dump is not UTF-8") from exc
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        process.stdout.close()


def _sections(dump):
    if (not isinstance(dump, str) or not 0 < len(dump.encode("utf-8")) <= MAX_DUMP_BYTES
            or "\x00" in dump):
        raise RouteGuardError("Missing, oversized or malformed Nginx config dump")
    headers = list(HEADER.finditer(dump))
    if not 1 <= len(headers) <= 128 or dump[:headers[0].start()].strip():
        raise RouteGuardError("Nginx configuration file boundaries are not recognized")
    files = {}
    for i, header in enumerate(headers):
        path = header.group(1)
        if (not _canonical_path(path) or path in files):
            raise RouteGuardError("Ambiguous Nginx dump path/duplicate file")
        end = headers[i+1].start() if i+1 < len(headers) else len(dump)
        files[path] = dump[header.end():end].strip("\r\n")
    return files


def _simple_server(text, site_key, root):
    # No includes/locations/rewrites/variables, even if they currently return
    # a matching HTTP body. Do not write a speculative generic Nginx parser.
    if ("'" in text or '"' in text or "$" in text or
            "\\" in text or "{" not in text or "}" not in text):
        raise RouteGuardError("Nonliteral site route requires a native adapter")
    text = re.sub(r"(?m)#[^\r\n]*$", "", text)
    match = re.fullmatch(r"\s*server\s*\{([^{}]*)\}\s*", text, re.DOTALL)
    if match is None:
        raise RouteGuardError("Nested or multiple Nginx server/location blocks unsupported")
    statements = match.group(1).split(";")
    if statements[-1].strip():
        raise RouteGuardError("Incomplete Nginx source directive")
    directives = [value.strip() for value in statements[:-1]]
    if any(not item or "\n" in item.strip().replace("\n", " ", 0) for item in directives):
        raise RouteGuardError("Unsupported multiline Nginx directive")
    required = {
        "listen 80": 0,
        "server_name " + site_key: 0,
        "root " + root: 0,
        "error_page 404 /404.html": 0,
    }
    optional = {"index index.html", "index index.htm index.html", "access_log off"}
    for item in directives:
        normalized = " ".join(item.split())
        if normalized in required:
            required[normalized] += 1
        elif normalized not in optional:
            raise RouteGuardError("Unsupported server directive or routing override")
    if any(number != 1 for number in required.values()):
        raise RouteGuardError("Native site must have one exact 80/host/root/404 rule")


def verify_configured_site_404(site, *, vhost_root=VHOST_ROOT, capture=None):
    """Fail-closed eligibility for simple HTTP-only configured Nginx sources.

    Even success does NOT prove loaded worker configuration or absence of
    concurrent root edits. It must be paired with current loopback HTTP
    probing and inode-preserving guarded file transactions.
    """
    if not isinstance(site, dict):
        raise RouteGuardError("Invalid native site")
    name, root = site.get("name"), site.get("path")
    if (not isinstance(name, str) or not NAME.fullmatch(name) or
            not _canonical_path(root) or
            site.get("status") not in ("1", 1) or
            site.get("bound_domains") != [{"name": name, "port": 80}]):
        raise RouteGuardError("Only one literal enabled HTTP/80 site is supported")
    if not _canonical_path(vhost_root):
        raise RouteGuardError("Unsupported Nginx source directory")
    file_path = vhost_root + "/" + name + ".conf"
    directory = _directory(vhost_root)
    try:
        original = _file_snapshot(directory, name + ".conf")
        source_meta = os.stat(name + ".conf", dir_fd=directory, follow_symlinks=False)
        if (original is None or source_meta.st_uid != os.geteuid()
                or source_meta.st_mode & 0o022):
            raise RouteGuardError("Native site VHost source not exclusively owned")
    finally:
        os.close(directory)
    dump = (capture or _capture_nginx_t)()
    files = _sections(dump)
    contents = files.get(file_path)
    if contents is None or contents != original["data"].decode("utf-8").strip("\r\n"):
        raise RouteGuardError("Site VHost missing from nginx -T or changed since inspection")
    _simple_server(contents, name, root)
    for path, content in files.items():
        if path == file_path:
            continue
        uncommented = re.sub(r"(?m)#[^\r\n]*$", "", content)
        # A separate named VHost or alias/root consumer invalidates exclusivity
        # even if one HTTP/80 probe happens to match.
        if re.search(r"(?m)(?<![A-Za-z0-9_])server_name\s+[^;]*\b"
                     + re.escape(name) + r"\b", uncommented):
            raise RouteGuardError("Another Nginx source binds the selected host")
        _external_path_consumer(uncommented, root)
    directory = _directory(vhost_root)
    try:
        after = _file_snapshot(directory, name + ".conf")
        if (after is None or after["sha256"] != original["sha256"]
                or after["identity"] != original["identity"]):
            raise RouteGuardError("Native Nginx source changed during route inspection")
    finally:
        os.close(directory)
    return {
        "configured_static_http_80": True,
        "nginx_dump_sha256": hashlib.sha256(dump.encode("utf-8")).hexdigest(),
        "vhost_sha256": original["sha256"],
        "loaded_workers_verified": False,
        "https_verified": False,
    }
