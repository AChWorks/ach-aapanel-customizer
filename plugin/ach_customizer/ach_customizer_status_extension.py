"""Native aaPanel-owned Nginx extension error pages (404, 502 and generic 50x).

No document-root file is modified. A site-specific, root-owned include routes
the existing error_page URI to an immutable, plugin-owned HTML asset.
Generic 50x adds only Nginx-served 500/503/504 mappings while retaining the
native /502.html route. It does NOT intercept application-generated responses. The
operator explicitly authorizes one Nginx configuration reload; an independent
loopback error response must prove the selected site, status, content and
operation nonce. Every ambiguous activation retains recovery evidence.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import http.client
import json
import os
import re
import stat
import subprocess
import time
from uuid import uuid4

from ach_customizer_status_inspect import _directory, VHOST_ROOT, READ_FLAGS, StatusInspectError
from ach_customizer_status_pages import StatusPageError
from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _native_unused_subdir,
    _native_server_direct_include,
)
from ach_customizer_status_probe import _DeadlineSocket, _remaining

NGINX = "/www/server/nginx/sbin/nginx"
NGINX_CONF = "/www/server/nginx/conf/nginx.conf"
PUBLIC_ROOT = "/www/server/nginx/.ach-customizer-status"
CODES = ("404", "502", "50x")
FIFTY_CODES = ("500", "502", "503", "504")


def _expected_status(code):
    return 500 if code == "50x" else int(code)
DOMAIN = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,252})\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
MAX_HTML = 64 * 1024
MAX_RECORD = 4096
MAX_VHOST = 128 * 1024
MAX_PROBE = 128 * 1024


class ExtensionError(StatusPageError):
    def __init__(self, stage, reason, *, recovery_id=None):
        self.stage = stage
        self.recovery_id = recovery_id if isinstance(recovery_id, str) and TOKEN.fullmatch(recovery_id) else None
        super().__init__(reason)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _owned_dir(fd, mode=None):
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o022 or
            (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
        raise ExtensionError("ownership", "Site extension directory has untrusted permissions")
    return info


def _bounded_file(fd, name, *, limit=MAX_VHOST, permissions=None,
                  allow_empty=False):
    try:
        descriptor = os.open(name, READ_FLAGS, dir_fd=fd)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or before.st_mode & 0o022
                or (permissions is not None and stat.S_IMODE(before.st_mode) != permissions)
                or before.st_size < (0 if allow_empty else 1)
                or before.st_size > limit
                or os.listxattr(descriptor)):
            raise ExtensionError("ownership", "Untrusted file in managed native source")
        payload = os.read(descriptor, limit + 1)
        after = os.fstat(descriptor)
        if (len(payload) != before.st_size
                or any(getattr(before, k) != getattr(after, k)
                       for k in ("st_ino", "st_dev", "st_mtime_ns", "st_ctime_ns",
                                 "st_mode", "st_uid", "st_gid", "st_size"))):
            raise ExtensionError("concurrency", "Native file changed during bounded read")
        return payload
    finally:
        os.close(descriptor)


def _write_exclusive(fd, name, payload, mode):
    descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=fd)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(fd)


def _rename_noreplace(fd, before, after):
    """Atomically retire an extension file without overwriting a foreign entry."""
    try:
        call = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise ExtensionError("compatibility", "Linux no-clobber rename is unavailable") from exc
    call.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                     ctypes.c_char_p, ctypes.c_uint)
    call.restype = ctypes.c_int
    if call(fd, before.encode("ascii"), fd, after.encode("ascii"), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))



def _publish_complete(fd, name, payload, mode, op):
    """Stage, hash-check and atomically publish an owned file without clobber.

    The unique nonmatching .stage filename is NEVER a live Nginx *.conf.
    If write, fsync, rename or directory sync fails, retain the prepared
    journal and stage for an explicitly supervised reconciliation.
    """
    staging = "." + name + "." + op + ".stage"
    try:
        _write_exclusive(fd, staging, payload, mode)
        staged = _bounded_file(fd, staging, limit=max(MAX_HTML, len(payload)),
                               permissions=mode)
        if staged != payload:
            raise ExtensionError("publication", "Staged status content differs from proposal")
        _rename_noreplace(fd, staging, name)
        os.fsync(fd)
    except Exception as exc:
        raise ExtensionError(
            "uncertain",
            "Status publication not confirmed; Recheck before a new Apply or Restore",
            recovery_id=op,
        ) from exc


def _record_name(site_id, code):
    if type(site_id) is not int or not 1 <= site_id <= 2147483647 or code not in CODES:
        raise ExtensionError("identity", "Unsupported native status target")
    return "ach_customizer.status." + str(site_id) + "." + code + ".json"


def _record_load(fd, site_id, code):
    raw = _bounded_file(fd, _record_name(site_id, code), limit=MAX_RECORD, permissions=0o600)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ExtensionError("recovery", "Status extension recovery journal unreadable") from exc
    required = {"schema", "site_id", "site_name", "code", "op", "phase",
                "vhost_sha", "before_sha", "after_sha", "include_sha", "asset_path"}
    if (not isinstance(data, dict) or set(data) != required or
            data["schema"] != 1 or data["site_id"] != site_id or
            data["code"] != code or not isinstance(data["site_name"], str) or
            not DOMAIN.fullmatch(data["site_name"]) or
            not isinstance(data["op"], str) or not TOKEN.fullmatch(data["op"]) or
            data["phase"] not in ("prepared", "applied", "restored") or
            any(not isinstance(data[key], str) or not HASH.fullmatch(data[key])
                for key in ("vhost_sha", "before_sha", "after_sha", "include_sha")) or
            not isinstance(data["asset_path"], str) or
            not re.fullmatch(r"/[a-zA-Z0-9/_.-]{1,1023}", data["asset_path"])):
        raise ExtensionError("recovery", "Invalid native status journal")
    return data


def _record_save(fd, site_id, code, record):
    payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise ExtensionError("recovery", "Status journal exceeds limit")
    temporary = "." + _record_name(site_id, code) + "." + uuid4().hex
    created = False
    try:
        _write_exclusive(fd, temporary, payload, 0o600)
        created = True
        os.replace(temporary, _record_name(site_id, code),
                   src_dir_fd=fd, dst_dir_fd=fd)
        created = False
        os.fsync(fd)
    finally:
        if created:
            os.unlink(temporary, dir_fd=fd)



def _include_graph_guard(site, code, vhost_root, nginx_conf):
    """Bounded native include-ownership proof, not a general Nginx parser.

    Follow file-scope include edges from the actual primary nginx.conf.
    The proposed snippet may be reached ONLY from its own native VHost's
    exact, server-scoped extension/*.conf edge. Unknown graph/indirection,
    nonliteral source or multi-consumer graph fails closed before any write.
    """
    import glob
    import fnmatch

    site_conf = os.path.join(vhost_root, site["name"] + ".conf")
    exact_mask = vhost_root + "/extension/" + site["name"] + "/*.conf"
    proposed = vhost_root + "/extension/" + site["name"] + "/" + _include_name(site["id"], code)
    conf_dir = os.path.dirname(nginx_conf)
    if (not os.path.isabs(nginx_conf) or not os.path.isabs(vhost_root)
            or ".." in nginx_conf.split("/") or ".." in vhost_root.split("/")):
        raise ExtensionError("source", "Native Nginx include root is not canonical")

    def matches(pattern, path):
        lhs, rhs = pattern.split("/"), path.split("/")
        return len(lhs) == len(rhs) and all(
            fnmatch.fnmatchcase(item, pattern_part)
            for item, pattern_part in zip(rhs, lhs)
        )

    scanned = 0
    imported = 0
    selected_vhost_count = 0
    visiting = set()
    total_bytes = 0

    def walk(path, depth):
        nonlocal scanned, imported, selected_vhost_count, total_bytes
        if depth > 12 or scanned >= 128 or path in visiting:
            raise ExtensionError("source", "Native Nginx include graph is cyclic or too large")
        if (not os.path.isabs(path) or ".." in path.split("/")
                or os.path.realpath(path) != path):
            raise ExtensionError("source", "Nginx include graph has an unresolved source path")
        directory = _directory(os.path.dirname(path))
        try:
            _owned_dir(directory)
            raw = _bounded_file(directory, os.path.basename(path), limit=MAX_VHOST,
                                allow_empty=True)
        finally:
            os.close(directory)
        if raw is None:
            raise ExtensionError("source", "Nginx include graph source disappeared")
        scanned += 1
        total_bytes += len(raw)
        if total_bytes > 2 * 1024 * 1024:
            raise ExtensionError("source", "Nginx include graph exceeds bounded read limit")
        if path == site_conf:
            selected_vhost_count += 1
        try:
            active = _active_nginx_text(raw.decode("utf8", "replace"))
        except MonitorInputError as exc:
            raise ExtensionError("source", "Ambiguous native Nginx include syntax") from exc
        expressions = re.findall(
            r"(?<![A-Za-z0-9_])include\s+([^\s;{}]{1,512})\s*;", active
        )
        if len(expressions) != len(re.findall(r"\binclude\s+", active)):
            raise ExtensionError("source", "Unrecognized Nginx include syntax")
        visiting.add(path)
        try:
            for expression in expressions:
                mask = (expression if expression.startswith("/") else
                        conf_dir + "/" + expression)
                if (os.path.normpath(mask) != mask or
                        ".." in mask.split("/") or "//" in mask or
                        "**" in mask or len(mask) > 1024):
                    raise ExtensionError("source", "Unverifiable Nginx include mask")
                if any(char in mask for char in "*?["):
                    # This is the supported aaPanel include-ownership
                    # contract. No unknown wildcard can import a future
                    # plugin-owned filename through an alias/symlink or a
                    # broader mask before that file even exists.
                    if path == nginx_conf:
                        allowed = (vhost_root + "/*.conf",
                                   vhost_root + "/tcp/*.conf")
                    elif (path.startswith(vhost_root + "/") and
                          path.endswith(".conf") and
                          "/" not in path[len(vhost_root) + 1:]):
                        native_key = path.rsplit("/", 1)[-1][:-5]
                        allowed = (
                            vhost_root + "/extension/" + native_key + "/*.conf",
                            vhost_root + "/sub_dir/" + native_key + "/*.conf",
                        )
                    else:
                        allowed = ()
                    if mask not in allowed:
                        raise ExtensionError(
                            "ownership", "Unsupported native Nginx wildcard include")
                    if "/sub_dir/" in mask:
                        # Only a direct server-level native include is a
                        # recognized regeneration source. The same pathname
                        # nested in a location does not establish ownership.
                        if not _native_server_direct_include(active, mask):
                            raise ExtensionError(
                                "ownership", "Native subdirectory include is not server-scoped")
                        try:
                            _native_unused_subdir(vhost_root, native_key)
                        except (OSError, MonitorInputError) as exc:
                            raise ExtensionError(
                                "ownership", "Native per-site subdirectory routes need review") from exc
                        # Scan a fresh glob too; an unexpected concurrent
                        # creation cannot become an accepted route.
                        if glob.glob(mask):
                            raise ExtensionError(
                                "ownership", "Native per-site subdirectory routes need review")
                        continue
                    parent = os.path.dirname(mask)
                    if os.path.realpath(parent) != parent or not os.path.isdir(parent):
                        raise ExtensionError(
                            "ownership", "Unsupported native Nginx wildcard include")
                if matches(mask, proposed):
                    if path != site_conf or mask != exact_mask:
                        raise ExtensionError(
                            "ownership", "A second Nginx source can import the selected extension")
                    imported += 1
                candidates = glob.glob(mask)
                if len(candidates) > 128:
                    raise ExtensionError("source", "Nginx include wildcard is too broad")
                for child in sorted(candidates):
                    if (child == site_conf and
                            (path != nginx_conf or mask != vhost_root + "/*.conf")):
                        raise ExtensionError(
                            "ownership", "Selected native VHost is imported from an ambiguous scope")
                    if not os.path.isfile(child) or os.path.islink(child):
                        raise ExtensionError("source", "Untrusted or nonregular Nginx included source")
                    walk(child, depth + 1)
        finally:
            visiting.remove(path)

    walk(nginx_conf, 0)
    if imported != 1 or selected_vhost_count != 1:
        raise ExtensionError(
            "ownership", "Exclusive native server include source could not be established")


def _reject_50x_vhost_mappings(source):
    """Recognize error_page statements in the bounded selected native VHost.

    Nginx treats newlines as argument whitespace and # as a comment only
    outside quoted/escaped tokens. Scan all contexts, including locations;
    this is deliberately a statement recognizer, NOT an effective-config
    parser or a rewrite of the native VHost.
    """
    if "\x00" in source or len(source) > MAX_VHOST:
        raise ExtensionError("source", "Uninspectable native Nginx 50x source")
    tokens = []
    word = []
    quote = None
    escaped = False
    comment = False
    in_variable = False
    dollar = False
    depth = 0

    def finish_word():
        if word:
            tokens.append("".join(word))
            word.clear()

    def check_statement():
        if not tokens or tokens[0] != "error_page":
            return
        # The final argument is a URI or named location; an optional =code
        # may precede it. Status code arguments must be literal integers.
        if len(tokens) < 3:
            raise ExtensionError("source", "Unclassifiable native Nginx error_page")
        codes = tokens[1:-1]
        if any(code in ("500", "503", "504") for code in codes):
            raise ExtensionError("conflict", "Selected site already owns a 500/503/504 error mapping")
        if any(not re.fullmatch(r"[0-9]{3}|=[0-9]{3}|=", code) for code in codes):
            raise ExtensionError("source", "Unclassifiable native Nginx error_page")

    for char in source:
        if comment:
            if char == "\n":
                comment = False
            continue
        if escaped:
            # Nginx unescapes only these characters; unknown escapes retain
            # the backslash, so they cannot masquerade as numeric statuses.
            word.append({"t": "\t", "r": "\r", "n": "\n"}.get(char,
                        char if char in ("'", '"', "\\") else "\\" + char))
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
            continue
        if char in ("'", '"') and not word:
            quote = char
            continue
        if char == "#" and not word:
            comment = True
            continue
        if char in " \t\r\n":
            finish_word()
            dollar = False
            continue
        if in_variable:
            word.append(char)
            if char == "}":
                in_variable = False
            continue
        if char == "{" and dollar:
            in_variable = True
            word.append(char)
            dollar = False
            continue
        dollar = char == "$"
        if char in ";{}":
            finish_word()
            if char == ";":
                check_statement()
            elif char == "{":
                if tokens and tokens[0] == "error_page":
                    raise ExtensionError("source", "Unterminated native Nginx error_page")
                depth += 1
            else:
                if tokens or depth == 0:
                    raise ExtensionError("source", "Ambiguous native Nginx 50x context")
                depth -= 1
            tokens.clear()
            continue
        word.append(char)
    if quote or escaped or in_variable or depth or tokens or word:
        raise ExtensionError("source", "Incomplete or ambiguous native Nginx 50x source")


def _source(site, code, vhost_root, nginx_conf=NGINX_CONF):
    name = site.get("name")
    if (not isinstance(name, str) or not DOMAIN.fullmatch(name)
            or code not in CODES or site.get("status") not in ("1", 1)
            or type(site.get("id")) is not int):
        raise ExtensionError("identity", "Selected native website is unsupported")
    if {"name": name, "port": 80} not in site.get("bound_domains", []):
        raise ExtensionError("identity", "Native site must be bound on HTTP/80")
    directory = _directory(vhost_root)
    try:
        _owned_dir(directory)
        source = _bounded_file(directory, name + ".conf")
    finally:
        os.close(directory)
    if source is None:
        raise ExtensionError("source", "Native site configuration absent")
    text = source.decode("utf8", "replace")
    expected_include = vhost_root + "/extension/" + name + "/*.conf"
    def exact(expr):
        return len(re.findall(expr, text, re.M)) == 1
    document_root = site.get("path")
    if (len(re.findall(r"(?m)^\s*server\s*\{", text)) != 1 or
            len(re.findall(r"(?m)^\s*server_name\s+", text)) != 1 or
            not isinstance(document_root, str) or
            not re.fullmatch(r"/[a-zA-Z0-9/_.-]{1,1023}", document_root) or
            ".." in document_root.split("/") or "//" in document_root or
            not exact(r"^\s*root\s+" + re.escape(document_root.rstrip("/")) + r"/?\s*;") or
            not exact(r"^\s*server_name\s+" + re.escape(name) + r"\s*;") or
            not exact(r"^\s*error_page\s+" + ("502" if code == "50x" else code) +
                      r"\s+/" + ("502" if code == "50x" else code) + r"\.html\s*;") or
            not exact(r"^\s*include\s+" + re.escape(expected_include) + r"\s*;")):
        raise ExtensionError("source", "Native site root, error-page or extension binding is unproven")
    if code == "50x":
        # Guard all selected native VHost error_page contexts before any
        # journal, asset, include publication or shared Nginx reload.
        _reject_50x_vhost_mappings(text)
    if not _native_server_direct_include(text, expected_include):
        raise ExtensionError("source", "Status extension must be included at server scope")
    # Before preparing any owned content, prove the selected server is
    # the only reachable consumer in the bounded effective native include graph.
    _include_graph_guard(site, code, vhost_root, nginx_conf)
    # Also fail on parked native VHost sources which could become active later.
    directory = _directory(vhost_root)
    try:
        entries = []
        with os.scandir(directory) as stream:
            for entry in stream:
                if len(entries) >= 128:
                    raise ExtensionError("source", "Too many native VHosts for bounded isolation")
                entries.append(entry.name)
        for filename in entries:
            if (filename == name + ".conf" or not filename.endswith(".conf")
                    or not DOMAIN.fullmatch(filename[:-5])):
                continue
            data = _bounded_file(directory, filename)
            if data is not None and expected_include.encode() in data:
                raise ExtensionError("ownership", "Another Nginx VHost shares this extension include")
    finally:
        os.close(directory)
    ext_path = vhost_root + "/extension/" + name
    ext = _directory(ext_path)
    try:
        _owned_dir(ext)
    finally:
        os.close(ext)
    return _sha(source), ext_path


def _include_name(site_id, code):
    return "ach_customizer_" + str(site_id) + "_" + code + ".conf"


def _retained_name(site_id, code, op):
    return "ach_customizer_" + str(site_id) + "_" + code + "." + op + ".retained"


def _asset_path(public_root, site_id, code, after_sha):
    return public_root + "/" + str(site_id) + "/" + code + "-" + after_sha + ".html"


def _include(code, asset_path, op):
    # ACh-managed paths are intentionally independent of site files and
    # only affect Nginx-served errors for the explicitly selected VHost.
    if not TOKEN.fullmatch(op) or not HASH.fullmatch(asset_path.rsplit("-", 1)[-1][:-5]):
        raise ExtensionError("input", "Invalid plugin asset identity")
    if code == "50x":
        # Native aaPanel already maps 502 -> /502.html. Do not duplicate that
        # status mapping: provide its exact URI and add only missing 50x codes.
        route = "/.__ach_customizer_50x_" + op + ".html"
        output = [
            "error_page 500 503 504 " + route + ";",
            "location = " + route + " {",
            "    internal;",
            "    alias " + asset_path + ";",
            "    default_type text/html;",
            "    add_header X-ACh-Status-Proof " + op + " always;",
            "}",
            "location = /502.html {",
            "    internal;",
            "    alias " + asset_path + ";",
            "    default_type text/html;",
            "    add_header X-ACh-Status-Proof " + op + " always;",
            "}",
        ]
        for status in FIFTY_CODES:
            output.extend((
                "location = /.__ach_customizer_proof_" + op + "_" + status + " {",
                "    allow 127.0.0.1;",
                "    deny all;",
                "    try_files /.__ach_customizer_never_exists_" + op + " =" + status + ";",
                "}",
            ))
        return ("\n".join(output) + "\n").encode("ascii")
    probe_path = "/.__ach_customizer_proof_" + op
    return (
        "location = /" + code + ".html {\n"
        "    internal;\n"
        "    alias " + asset_path + ";\n"
        "    default_type text/html;\n"
        "    add_header X-ACh-Status-Proof " + op + " always;\n"
        "}\n"
        "location = " + probe_path + " {\n"
        "    allow 127.0.0.1;\n"
        "    deny all;\n"
        "    try_files /.__ach_customizer_never_exists_" + op + " =" + code + ";\n"
        "}\n"
    ).encode("ascii")


def _public_dirs(public_root, site_id):
    parent = os.path.dirname(public_root)
    pfd = _directory(parent)
    try:
        _owned_dir(pfd)
        created = False
        try:
            os.mkdir(os.path.basename(public_root), 0o700, dir_fd=pfd)
            created = True
        except FileExistsError:
            pass
        root = os.open(os.path.basename(public_root),
                       os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                       dir_fd=pfd)
        if created:
            os.fchmod(root, 0o755)
            os.fsync(root)
            os.fsync(pfd)
    finally:
        os.close(pfd)
    try:
        _owned_dir(root, 0o755)
        created_site = False
        try:
            os.mkdir(str(site_id), 0o700, dir_fd=root)
            created_site = True
        except FileExistsError:
            pass
        site_fd = os.open(str(site_id), os.O_RDONLY | os.O_DIRECTORY
                          | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
        try:
            if created_site:
                os.fchmod(site_fd, 0o755)
                os.fsync(site_fd)
                os.fsync(root)
            _owned_dir(site_fd, 0o755)
            return site_fd
        except Exception:
            os.close(site_fd)
            raise
    finally:
        os.close(root)


def _nginx(action, *, nginx=NGINX, conf=NGINX_CONF, runner=None):
    if action not in ("-t", "reload"):
        raise ExtensionError("input", "Unsupported Nginx operation")
    args = [nginx, "-t", "-c", conf] if action == "-t" else [nginx, "-s", "reload", "-c", conf]
    run = runner or subprocess.run
    try:
        outcome = run(args, capture_output=True, timeout=8, check=False)
        if outcome.returncode != 0:
            raise ExtensionError("syntax" if action == "-t" else "activation",
                                 "Native Nginx " + action + " failed; recovery required")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExtensionError("activation", "Native Nginx operation unavailable") from exc


def _assess_50x(observations, op):
    if (len(observations) == len(FIFTY_CODES) and
            all(result[0] == int(status) and result[2] == op
                for result, status in zip(observations, FIFTY_CODES)) and
            len({result[1] for result in observations}) == 1):
        return (500, observations[0][1], op)
    # Never claim an old generation has vanished if even one code retains it.
    return (0, None, op if any(result[2] == op for result in observations) else None)


def _probe(site, code, op, *, port=80, proof_status=None):
    # The multi-status probe proves *each* native Nginx error status, body,
    # and generation nonce through independent fresh HTTP requests.
    if code == "50x":
        if op is None:
            return _probe(site, "502", None, port=port)
        observations = [
            _probe(site, status, op, port=port, proof_status=status)
            for status in FIFTY_CODES
        ]
        return _assess_50x(observations, op)
    host = site["name"]
    if not DOMAIN.fullmatch(host) or (op is not None and not TOKEN.fullmatch(op)):
        raise ExtensionError("identity", "Invalid internal status probe identity")
    path = ("/.__ach_customizer_proof_" + op +
            ("_" + proof_status if proof_status else "") if op else
            "/.__ach_customizer_probe_" + uuid4().hex + ".css")
    deadline = time.monotonic() + 2.5
    conn = None
    response = None
    raw_socket = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=_remaining(deadline))
        conn.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host)
        conn.putheader("Accept-Encoding", "identity")
        conn.putheader("Cache-Control", "no-cache")
        conn.putheader("Connection", "close")
        conn.connect()
        raw_socket = conn.sock
        raw_socket.settimeout(_remaining(deadline))
        conn.endheaders()
        raw_socket.setblocking(False)
        conn.sock = _DeadlineSocket(raw_socket, deadline)
        response = conn.getresponse()
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ExtensionError("probe", "Native status body was compressed")
        declared = response.getheader("Content-Length")
        if declared is not None and (not declared.isdecimal()
                                     or int(declared) > MAX_PROBE):
            raise ExtensionError("probe", "Native status body length exceeds limit")
        payload = response.read(MAX_PROBE + 1)
        if len(payload) > MAX_PROBE or (declared is not None and
                                       len(payload) != int(declared)):
            raise ExtensionError("probe", "Native status body exceeds limit or is truncated")
        _remaining(deadline)
        return response.status, _sha(payload), response.getheader("X-ACh-Status-Proof")
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ExtensionError("probe", "Native loopback HTTP probe unavailable") from exc
    finally:
        if response is not None:
            response.close()
        if conn is not None:
            conn.close()
        if raw_socket is not None:
            raw_socket.close()


def _verified(site, code, op, sha, *, probe=None):
    fn = probe or _probe
    deadline = time.monotonic() + 8
    consecutive = 0
    while True:
        result = fn(site, code, op)
        if result == (_expected_status(code), sha, op):
            consecutive += 1
            if consecutive >= 3:
                return result
        else:
            consecutive = 0
        if time.monotonic() >= deadline:
            raise ExtensionError("postcheck", "Serving Nginx did not consistently confirm status, file and operation nonce")
        time.sleep(0.2)


def _verified_absent(site, code, op, baseline_sha, *, probe=None):
    # A successful nginx -s reload only signals the master. During a
    # graceful reload, old workers can still serve a previous generation.
    # Require three distinct fresh HTTP connections without the former
    # plugin nonce before calling Restore complete.
    fn = probe or _probe
    deadline = time.monotonic() + 8
    consecutive = 0
    while True:
        _status, _sha_body, observed_proof = fn(site, code, op)
        valid = observed_proof != op
        if valid and code == "404":
            old_status, old_sha, old_proof = fn(site, code, None)
            valid = old_status == 404 and old_sha == baseline_sha and old_proof != op
        consecutive = consecutive + 1 if valid else 0
        if consecutive >= 3:
            return
        if time.monotonic() >= deadline:
            raise ExtensionError("postcheck", "Previous status generation remains observable after Restore")
        time.sleep(0.2)


def preview_site_502(site, *, locale, rendered_sha256, rendered_html,
                     vhost_root=VHOST_ROOT, template="502"):
    """Read-only native 502 source preview; NOT a synthetic live 502 claim.

    The subsequently authorized Apply must prove an actual 502 response with
    the chosen immutable HTML and a fresh operation nonce before success.
    """
    from ach_customizer_status_inspect import inspect_site_files
    if template not in ("502", "50x"):
        raise ExtensionError("input", "Unsupported Nginx source preview")
    source_sha, _ = _source(site, template, vhost_root)
    inspected = inspect_site_files(
        site, locale=locale, template="502",
        rendered_sha256=rendered_sha256, rendered_html=rendered_html,
        vhost_root=vhost_root, source_fingerprint=True)
    current = inspected.get("page_file_sha256")
    if inspected.get("page_file_state") == "Absent":
        current = _sha(b"")
        note = "Site 502.html is absent. No previous HTTP 502 response was induced."
    elif (inspected.get("page_file_state") in ("Same bytes", "Different bytes")
          and isinstance(current, str) and HASH.fullmatch(current)):
        note = "Existing site 502.html is read-only. No live 502 response was induced."
    else:
        raise ExtensionError(
            "source", "Site 502.html is uninspectable; source-only approval is unsafe")
    if template == "50x":
        note += " Generic 50x uses this 502 source as its Restore baseline; no 500/503/504 was induced."
    return {
        "schema": 1, "site_id": site["id"], "site_key": site["name"],
        "template": template, "locale": locale,
        "state": "Source Ready", "reason": ("Native 50x source is eligible for guarded Nginx error routing"
             if template == "50x" else "Native 502 extension source is eligible for explicit guarded activation"),
        "read_only": True, "apply_supported": False,
        "nginx_runtime_verified": False, "scope": "native_vhost_source_only",
        "http_status": None, "http_404_observed": False, "body_sha256": None,
        "body_bytes": None, "page_file_sha256": current,
        "rendered_sha256": rendered_sha256, "body_matches_file": False,
        "body_matches_render": False, "note": note,
        "adoption_preview": {
            "schema": 1, "state": "Source Ready",
            "route_source_state": "Native VHost",
            "current_sha256": current, "proposed_sha256": rendered_sha256,
            "vhost_sha256": source_sha,
            "requires_adoption": False, "requires_backup": False,
            "ownership_verified": False, "recovery_verified": False,
            "apply_supported": False,
            "reason": "Explicit plugin-owned extension and global Nginx reload approval required",
        },
    }


def preview_site_50x(site, *, locale, rendered_sha256, rendered_html,
                     vhost_root=VHOST_ROOT):
    """Source-only preflight; real Nginx 50x proof follows explicit Apply."""
    return preview_site_502(
        site, locale=locale, rendered_sha256=rendered_sha256,
        rendered_html=rendered_html, vhost_root=vhost_root, template="50x")


def _previous_502_source(site, vhost_root, html):
    """Source fingerprint only: never infer a preexisting live HTTP 502."""
    from ach_customizer_status_inspect import inspect_site_files
    inspected = inspect_site_files(
        site, locale="en", template="502", rendered_sha256=_sha(html.encode("utf8")),
        rendered_html=html, vhost_root=vhost_root, source_fingerprint=True,
    )
    current = inspected.get("page_file_sha256")
    if inspected.get("page_file_state") == "Absent":
        return _sha(b"")
    if (inspected.get("page_file_state") in ("Same bytes", "Different bytes")
            and isinstance(current, str) and HASH.fullmatch(current)):
        return current
    raise ExtensionError("source", "Previous site 502.html could not be inspected safely")


def _saved_recovery_unavailable(site, code, html_bytes, data_fd, *, stopped):
    """Read an exact saved operation when native routing cannot be verified.

    The journal is evidence, NOT a current page SHA or Nginx permission.
    No VHost, service or plugin-owned extension is altered or reloaded.
    """
    record = _record_load(data_fd, site["id"], code)
    if record is None:
        raise ExtensionError("recovery", "No saved status operation; native site source is unavailable")
    if record["site_name"] != site["name"]:
        raise ExtensionError("identity", "Saved operation belongs to a different native site")
    return {
        "state": "Suspended" if stopped else "Needs Review",
        "changed": False, "site_id": site["id"],
        "page_file_sha256": (record["before_sha"] if record["phase"] == "restored"
                             else record["after_sha"]),
        "rendered_sha256": _sha(html_bytes),
        "before_sha256": record["before_sha"],
        "after_sha256": record["after_sha"],
        "recovery_id": record["op"],
        "journal_phase": record["phase"],
        "read_only": True, "mode": "native_status_extension",
        "runtime_verified": False, "verification_scope": "saved_journal_only",
        "note": ("Native website is stopped; the saved recovery is visible, "
                 "but the service and current status page are NOT verified. "
                 "Start the site, refresh the site inventory, and Recheck before Restore."
                 if stopped else
                 "Native status VHost/source changed; the saved recovery remains "
                 "visible, but the current status page is NOT verified. "
                 "Reconcile source and Recheck before Restore."),
    }


def manage_site_extension(action, site, *, code, html, expected_current,
                          expected_vhost, expected_render, expected_recovery,
                          data_fd, vhost_root=VHOST_ROOT, public_root=PUBLIC_ROOT,
                          nginx=NGINX, nginx_conf=NGINX_CONF,
                          runner=None, probe=None):
    """Status Pages operation under caller's existing primary-admin state lock.

    Only an explicit, checked manual Apply/Restore performs a global Nginx
    reload. No browser parameter supplies a path, process, port or command.
    """
    if action not in ("apply", "restore", "recheck") or code not in CODES:
        raise ExtensionError("input", "Unsupported Status Pages operation")
    html_bytes = html.encode("utf8")
    if not 0 < len(html_bytes) <= MAX_HTML:
        raise ExtensionError("input", "Rendered HTML exceeds bounded size")
    _owned_dir(data_fd)
    # A native Stop may rewrite the VHost and comment its extension includes.
    # Preserve read-only recovery access without weakening Apply/Restore.
    if action == "recheck" and site.get("status") in ("0", 0):
        return _saved_recovery_unavailable(
            site, code, html_bytes, data_fd, stopped=True)
    try:
        source_sha, ext_path = _source(site, code, vhost_root, nginx_conf)
    except (ExtensionError, OSError, StatusInspectError):
        if action != "recheck":
            raise
        return _saved_recovery_unavailable(
            site, code, html_bytes, data_fd, stopped=False)
    site_id = site["id"]
    include_name = _include_name(site_id, code)
    ext_fd = _directory(ext_path)
    try:
        _owned_dir(ext_fd)
        record = _record_load(data_fd, site_id, code)
        current_config = _bounded_file(ext_fd, include_name, limit=8192, permissions=0o600)
        if record and (record["site_name"] != site["name"]
                       or record["vhost_sha"] != source_sha):
            if (action == "recheck" and record["site_name"] == site["name"]):
                return _saved_recovery_unavailable(
                    site, code, html_bytes, data_fd, stopped=False)
            raise ExtensionError("identity", "Site or VHost changed; retain recovery for review")
        expected_sha = _sha(html_bytes)
        if action == "recheck":
            state = ("Unmanaged" if record is None and current_config is None else
                     "Needs Review" if record is None else
                     "Recovery Required" if record["phase"] == "prepared" else
                     "Drift")
            if record and record["phase"] == "applied":
                if current_config is None:
                    retained = _bounded_file(ext_fd,
                        _retained_name(site_id, code, record["op"]),
                        limit=8192, permissions=0o600)
                    if retained is not None and _sha(retained) == record["include_sha"]:
                        state = "Recovery Required"
                elif _sha(current_config) == record["include_sha"]:
                    try:
                        if (probe or _probe)(site, code, record["op"]) == (
                                _expected_status(code), record["after_sha"], record["op"]):
                            state = "Applied"
                    except (ExtensionError, OSError):
                        state = "Needs Review"
            if record and record["phase"] == "restored" and current_config is None:
                try:
                    status, body, proof = (probe or _probe)(site, code, record["op"])
                    source_ok = (code == "404" or
                                 _previous_502_source(site, vhost_root, html) ==
                                 record["before_sha"])
                    old_404 = code != "404" or (
                        status == 404 and body == record["before_sha"])
                    state = ("Restored" if code == "404" else "Source Restored") if (
                        proof != record["op"] and source_ok and old_404) else "Needs Review"
                except (ExtensionError, OSError, StatusPageError):
                    state = "Needs Review"
            if record is None and current_config is None:
                if code == "50x":
                    current_sha = _previous_502_source(site, vhost_root, html)
                else:
                    try:
                        _status, current_sha, _proof = (probe or _probe)(site, code, None)
                    except (ExtensionError, OSError):
                        current_sha = expected_sha
            else:
                current_sha = (record["before_sha"] if record and
                               state in ("Restored", "Source Restored")
                               else record["after_sha"] if record else expected_sha)
            return {"state": state, "changed": False, "site_id": site_id,
                    "page_file_sha256": current_sha,
                    "rendered_sha256": expected_sha,
                    "before_sha256": record["before_sha"] if record else None,
                    "after_sha256": record["after_sha"] if record else None,
                    "recovery_id": record["op"] if record else None,
                    "read_only": True, "mode": "native_status_extension",
                    "verification_scope": ("http50x_body" if code == "50x" and state == "Applied"
                                           else "source_and_nonce_only" if code != "404"
                                           else "http404_body"),
                    "runtime_verified": state == "Applied" if code == "50x" else state == "Restored" and code == "404"}

        # A syntax error in an unrelated Nginx VHost must never be turned
        # into an authorization to change this site; no change on failure.
        _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
        if action == "apply" and code in ("502", "50x"):
            # Both modes own /502.html; only one may be active on a site.
            other = "502" if code == "50x" else "50x"
            competing = _bounded_file(
                ext_fd, _include_name(site_id, other), limit=8192, permissions=0o600)
            if competing is not None:
                raise ExtensionError("conflict", "Another active status mode owns native /502.html")
        if action == "apply":
            if (current_config is not None or record and record["phase"] != "restored"):
                raise ExtensionError("concurrency", "Existing status extension is managed or requires recovery")
            if (expected_vhost != source_sha or expected_render != expected_sha
                    or not isinstance(expected_current, str) or not HASH.fullmatch(expected_current)):
                raise ExtensionError("concurrency", "Approved current/source/render evidence changed")
            prior_status, prior_sha, _prior_proof = (probe or _probe)(site, code, None)
            if code == "404" and (prior_status != 404 or prior_sha != expected_current):
                raise ExtensionError("concurrency", "Live existing HTTP 404 differs from approval")
            if code in ("502", "50x"):
                if _previous_502_source(site, vhost_root, html) != expected_current:
                    raise ExtensionError(
                        "concurrency", "Existing 502 file differs from approved source preview")
            op = uuid4().hex
            asset_path = _asset_path(public_root, site_id, code, expected_sha)
            include_bytes = _include(code, asset_path, op)
            record = {
                "schema": 1, "site_id": site_id, "site_name": site["name"],
                "code": code, "op": op, "phase": "prepared",
                "vhost_sha": source_sha,
                "before_sha": (prior_sha if code == "404" else expected_current),
                "after_sha": expected_sha, "include_sha": _sha(include_bytes),
                "asset_path": asset_path,
            }
            _record_save(data_fd, site_id, code, record)
            asset_dir = _public_dirs(public_root, site_id)
            try:
                asset_name = os.path.basename(asset_path)
                prior = _bounded_file(asset_dir, asset_name, limit=MAX_HTML, permissions=0o644)
                if prior is not None and prior != html_bytes:
                    raise ExtensionError("ownership", "Published status asset has changed")
                if prior is None:
                    _publish_complete(asset_dir, asset_name, html_bytes, 0o644, op)
            finally:
                os.close(asset_dir)
            # Publish only a complete, hash-verified .conf. Incomplete
            # writes remain as inert .stage files outside the native mask.
            _publish_complete(ext_fd, include_name, include_bytes, 0o600, op)
            # Validate syntax before attempting any daemon reload. If new
            # syntax cannot load, retire this plugin-owned snippet without
            # deleting its inode; the Nginx service was never signaled.
            try:
                if _source(site, code, vhost_root, nginx_conf)[0] != source_sha:
                    raise ExtensionError("concurrency", "Native site changed before activation")
                _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            except Exception as exc:
                try:
                    _rename_noreplace(ext_fd, include_name,
                                      _retained_name(site_id, code, op))
                    os.fsync(ext_fd)
                    _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
                except Exception as cleanup_exc:
                    raise ExtensionError("uncertain",
                                         "Syntax preflight failed; retained include needs recovery",
                                         recovery_id=op) from cleanup_exc
                raise ExtensionError("recovered",
                                     "Extension syntax preflight failed before any service reload",
                                     recovery_id=op) from exc
            try:
                _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
                _verified(site, code, op, expected_sha, probe=probe)
                # The selected-site response alone cannot prove that a
                # concurrent Nginx config edit did not add a second consumer.
                if _source(site, code, vhost_root, nginx_conf)[0] != source_sha:
                    raise ExtensionError(
                        "concurrency", "Native Nginx include graph changed after activation")
            except Exception as exc:
                # The configuration may already have activated. Preserve it
                # and the prepared journal: never blindly retry a reload.
                raise ExtensionError("uncertain",
                                     "Activation unconfirmed; Recheck exact recovery before Restore",
                                     recovery_id=op) from exc
            record["phase"] = "applied"
            try:
                _record_save(data_fd, site_id, code, record)
            except Exception as exc:
                raise ExtensionError(
                    "uncertain",
                    "Nginx Apply completed but final recovery journal is unconfirmed; Recheck",
                    recovery_id=op,
                ) from exc
            return {"state": "Applied", "changed": True, "site_id": site_id,
                    "page_file_sha256": expected_sha, "recovery_id": op,
                    "read_only": False, "mode": "native_status_extension",
                    "runtime_verified": code == "50x",
                    "verification_scope": "http50x_body" if code == "50x" else
                                          "http404_body" if code == "404" else
                                          "source_and_nonce_only"}

        if (record is None or expected_recovery != record["op"] or
                record["phase"] not in ("applied", "prepared")):
            raise ExtensionError("recovery", "Unknown or unapproved status recovery identity")
        retained = _retained_name(site_id, code, record["op"])
        retained_bytes = _bounded_file(ext_fd, retained, limit=8192, permissions=0o600)
        if current_config is None:
            if retained_bytes is None:
                if record["phase"] != "prepared":
                    raise ExtensionError("recovery", "Missing or altered retained status include")
                # A prepared publication may have failed BEFORE creation of
                # the active .conf (e.g. staged write/fsync failure). There
                # is no managed pathname to move. The explicit Restore
                # still reloads and checks that the operation nonce is gone.
            elif _sha(retained_bytes) != record["include_sha"]:
                raise ExtensionError("recovery", "Missing or altered retained status include")
            # This also covers syntax-failed Apply, interrupted Restore and
            # an unacknowledged but successful reload.
        else:
            if (_sha(current_config) != record["include_sha"]
                    or retained_bytes is not None):
                raise ExtensionError("recovery", "Status extension was independently modified")
            if record["phase"] == "applied":
                observed = (probe or _probe)(site, code, record["op"])
                if observed != (_expected_status(code), record["after_sha"], record["op"]):
                    raise ExtensionError("concurrency", "Applied route no longer matches journal")
            _rename_noreplace(ext_fd, include_name, retained)
            os.fsync(ext_fd)
        try:
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            # Even when the file was removed during an earlier interrupted
            # Restore, a fresh explicit action may reconcile its live state.
            _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
            _verified_absent(site, code, record["op"], record["before_sha"],
                             probe=probe)
            if (_source(site, code, vhost_root, nginx_conf)[0] != record["vhost_sha"]
                    or (code in ("502", "50x") and
                        _previous_502_source(site, vhost_root, html) !=
                        record["before_sha"])):
                raise ExtensionError(
                    "concurrency", "Native 502 file or Nginx source drifted during Restore")
        except Exception as exc:
            raise ExtensionError("uncertain", "Restore not confirmed; retained include and journal preserved",
                                 recovery_id=record["op"]) from exc
        record["phase"] = "restored"
        try:
            _record_save(data_fd, site_id, code, record)
        except Exception as exc:
            raise ExtensionError(
                "uncertain",
                "Nginx Restore completed but final recovery journal is unconfirmed; Recheck",
                recovery_id=record["op"],
            ) from exc
        return {"state": ("Restored" if code == "404" else "Source Restored"),
                "changed": True, "site_id": site_id,
                "page_file_sha256": record["before_sha"], "recovery_id": record["op"],
                "read_only": False, "mode": "native_status_extension",
                "runtime_verified": code == "404",
                "verification_scope": ("http404_body" if code == "404"
                                       else "source_and_nonce_only")}
    finally:
        os.close(ext_fd)
