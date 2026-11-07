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


# Bounded filesystem-aware audit of other configured document roots.  A
# pathname comparison cannot identify symlinks or bind mounts.
MAX_EXTERNAL_ENTRIES = 2048
MAX_EXTERNAL_DIRECTORIES = 128
MAX_EXTERNAL_DEPTH = 12
MAX_EXTERNAL_ROOTS = 64
EXTERNAL_SCAN_DEADLINE = 2.5


def _external_path_consumer(config, document_root):
    roots = set()
    directives = list(re.finditer(
        r"(?m)(?<![A-Za-z0-9_])(root|alias)\s+([^;{}]+);", config))
    for match in directives:
        kind, path = match.group(1), match.group(2).strip()
        if not _canonical_path(path):
            raise RouteGuardError("Ambiguous or noncanonical other-site root/alias")
        if (path == document_root or path.startswith(document_root + "/")
                or document_root.startswith(path + "/")):
            raise RouteGuardError("Configured Nginx source shares a selected site path")
        if kind == "alias":
            raise RouteGuardError("Other-site alias requires a separate verified adapter")
        roots.add(path)
    raw = len(re.findall(r"(?m)(?<![A-Za-z0-9_])(?:root|alias)(?=\s)", config))
    if raw != len(directives):
        raise RouteGuardError("Other-site root/alias directive is not recognizable")
    server_count = len(re.findall(r"(?m)(?<![A-Za-z0-9_])server\s*\{", config))
    if server_count > 1 or (server_count == 1 and len(roots) != 1):
        raise RouteGuardError("Other Nginx server/root attribution is ambiguous")
    if re.search(
            r"(?m)(?<![A-Za-z0-9_])(?:location|proxy_pass|fastcgi_pass|"
            r"uwsgi_pass|scgi_pass|grpc_pass|try_files|rewrite|"
            r"perl|content_by_lua|access_by_lua|auth_request)(?=\s|\{)", config):
        raise RouteGuardError("Other-site dynamic routing requires an adapter")
    return roots


def _scan_external_root(path, selected_root, selected_file, digest, budget):
    """Reject unresolvable, aliased, or shared filesystem resources.

    Only a bounded tree without ANY symlinks can be proven separate here.
    No symlink directories are followed; each opened directory is checked
    against its pre-open inode. Source graph changes invalidate HTTP evidence.
    """
    def check_budget():
        if time.monotonic() > budget["deadline"]:
            raise RouteGuardError("Other-site filesystem inspection exceeded deadline")

    def walk(fd, relative, depth):
        check_budget()
        budget["directories"] += 1
        if budget["directories"] > MAX_EXTERNAL_DIRECTORIES or depth > MAX_EXTERNAL_DEPTH:
            raise RouteGuardError("Other-site filesystem graph exceeds inspection bounds")
        metadata = os.fstat(fd)
        # Every directory must exclude uncoordinated web/application writers.
        # Rechecking hashes does not prevent a writable directory introducing
        # a symlink between the final inspection and the file swap.
        if (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022):
            raise RouteGuardError("Other-site directory permits an independent writer")
        if (metadata.st_dev, metadata.st_ino) == selected_root:
            raise RouteGuardError("Other-site path resolves to selected document root")
        digest.update(repr((path, relative, metadata.st_dev, metadata.st_ino,
                            metadata.st_mode, metadata.st_ctime_ns)).encode())
        children = []
        with os.scandir(fd) as stream:
            for entry in stream:
                budget["entries"] += 1
                check_budget()
                if budget["entries"] > MAX_EXTERNAL_ENTRIES:
                    raise RouteGuardError("Other-site filesystem graph exceeds inspection bounds")
                children.append(entry.name)
        # Only the already-bounded names are sorted; never materialize an
        # unlimited directory iterator before checking the budget.
        for name in sorted(children):
            check_budget()
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            digest.update(repr((relative, name, info.st_dev, info.st_ino,
                                info.st_mode, info.st_size, info.st_mtime_ns,
                                info.st_ctime_ns)).encode())
            if stat.S_ISLNK(info.st_mode):
                raise RouteGuardError("Other-site symlink defeats exclusive 404 ownership")
            if (info.st_dev, info.st_ino) == selected_file:
                raise RouteGuardError("Other-site resource shares selected 404 inode")
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY
                                | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                try:
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise RouteGuardError("Other-site directory changed during scan")
                    walk(child, relative + "/" + name, depth + 1)
                finally:
                    os.close(child)
            elif not stat.S_ISREG(info.st_mode):
                raise RouteGuardError("Other-site filesystem contains an unsupported entry")

    try:
        fd = _directory(path)
        try:
            walk(fd, "", 0)
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        raise RouteGuardError("Other-site filesystem inspection was inconclusive") from exc


# The aaPanel-owned Nginx master is a different process from an independently
# invoked nginx -T. Corroborate its exact executable, startup arguments,
# listening socket, children and source-file age before allowing a file write.
# This is NOT a cryptographic attestation of the loaded worker config.
NATIVE_CONFIG = "/www/server/nginx/conf/nginx.conf"
NATIVE_PIDFILE = "/www/server/nginx/logs/nginx.pid"


def _proc_bytes(path, limit=65536):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise RouteGuardError("Native Nginx process observation is unavailable")
    return raw


def _pid_started_ns(pid, boot_ns, hz):
    raw = _proc_bytes("/proc/" + str(pid) + "/stat", 4096).decode("ascii")
    after = raw.rsplit(")", 1)[1].split()
    if len(after) < 20:
        raise RouteGuardError("Native Nginx process start identity is incomplete")
    return boot_ns + (int(after[19]) * 1000000000 // hz)


def _native_live_http80(files):
    try:
        parent = _directory(os.path.dirname(NATIVE_PIDFILE))
        try:
            pid_fd = os.open(os.path.basename(NATIVE_PIDFILE), READ_FLAGS, dir_fd=parent)
            try:
                pid_meta = os.fstat(pid_fd)
                pid_bytes = os.read(pid_fd, 32)
            finally:
                os.close(pid_fd)
        finally:
            os.close(parent)
        if (pid_meta.st_uid != 0 or pid_meta.st_mode & 0o022 or
                re.fullmatch(rb"[1-9][0-9]{0,6}\s*", pid_bytes) is None):
            raise RouteGuardError("Native Nginx PID file is untrusted")
        pid = int(pid_bytes)
        native_meta = os.stat(NATIVE_NGINX)
        master_meta = os.stat("/proc/" + str(pid) + "/exe")
        if ((native_meta.st_dev, native_meta.st_ino) !=
                (master_meta.st_dev, master_meta.st_ino)):
            raise RouteGuardError("Active Nginx master is not the configured native binary")
        status = _proc_bytes("/proc/" + str(pid) + "/status").decode("utf-8")
        if not re.search(r"(?m)^Uid:\s+0\s+0\s+0\s+0\s*$", status):
            raise RouteGuardError("Active Nginx master identity is not root")
        title = _proc_bytes("/proc/" + str(pid) + "/cmdline", 2048)
        title = title.split(b"\x00", 1)[0].decode("utf-8")
        expected = "nginx: master process " + NATIVE_NGINX + " -c " + NATIVE_CONFIG
        if title != expected:
            raise RouteGuardError("Active Nginx master invocation differs from inspected -T")
        children = _proc_bytes("/proc/" + str(pid) + "/task/" +
                               str(pid) + "/children", 4096).decode("ascii").split()
        if not children or len(children) > 64:
            raise RouteGuardError("Native Nginx worker set is unprovable")
        workers = []
        for child in children:
            if re.fullmatch(r"[1-9][0-9]{0,6}", child) is None:
                raise RouteGuardError("Native Nginx worker PID is invalid")
            child_title = _proc_bytes("/proc/" + child + "/cmdline", 2048)
            if child_title.split(b"\x00", 1)[0] != b"nginx: worker process":
                continue
            exe = os.stat("/proc/" + child + "/exe")
            if (exe.st_dev, exe.st_ino) != (native_meta.st_dev, native_meta.st_ino):
                raise RouteGuardError("Native worker executable differs from master")
            workers.append(int(child))
        if not workers:
            raise RouteGuardError("No active native HTTP Nginx worker was proven")

        # Accept exactly one IPv4 listener that can serve 127.0.0.1:80.
        # If another daemon/REUSEPORT listener could answer our probe, refuse.
        listeners = set()
        for line in _proc_bytes("/proc/net/tcp", 1048576).decode("ascii").splitlines()[1:]:
            fields = line.split()
            if (len(fields) > 9 and fields[3] == "0A"
                    and fields[1].endswith(":0050")
                    and fields[1].split(":")[0] in ("00000000", "0100007F")):
                listeners.add(fields[9])
        if len(listeners) != 1:
            raise RouteGuardError("Local HTTP/80 listener is missing or ambiguous")
        socket_inode = next(iter(listeners))
        if not any(os.readlink("/proc/" + str(pid) + "/fd/" + fd)
                   == "socket:[" + socket_inode + "]"
                   for fd in os.listdir("/proc/" + str(pid) + "/fd")):
            raise RouteGuardError("HTTP/80 listener does not belong to native Nginx")

        boot_line = next(line for line in
                         _proc_bytes("/proc/stat", 65536).decode("ascii").splitlines()
                         if line.startswith("btime "))
        boot_ns = int(boot_line.split()[1]) * 1000000000
        hz = os.sysconf("SC_CLK_TCK")
        worker_birth_ns = min(_pid_started_ns(worker, boot_ns, hz)
                              for worker in workers)
        source = hashlib.sha256()
        for path in sorted(files):
            folder = _directory(os.path.dirname(path))
            try:
                metadata = os.stat(os.path.basename(path), dir_fd=folder,
                                   follow_symlinks=False)
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                        or metadata.st_mode & 0o022
                        or max(metadata.st_mtime_ns, metadata.st_ctime_ns)
                           + 3000000000 >= worker_birth_ns):
                    raise RouteGuardError("Nginx source may postdate active worker generation")
                source.update(repr((path, metadata.st_dev, metadata.st_ino,
                                    metadata.st_size, metadata.st_ctime_ns,
                                    metadata.st_mtime_ns)).encode())
            finally:
                os.close(folder)
        source.update(repr((pid, sorted(workers), socket_inode,
                            worker_birth_ns)).encode())
        return {"native_http80_process_verified": True,
                "runtime_generation_sha256": source.hexdigest()}
    except RouteGuardError:
        raise
    except (OSError, ValueError, StopIteration, UnicodeError) as exc:
        raise RouteGuardError("Native serving Nginx provenance unproven: "
                              + type(exc).__name__) from exc


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
        [NATIVE_NGINX, "-T", "-c", NATIVE_CONFIG], stdin=subprocess.DEVNULL,
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


def verify_configured_site_404(site, *, vhost_root=VHOST_ROOT, capture=None,
                               runtime=None):
    """Corroborate a narrow static HTTP route against the live native process.

    Source age, executable, worker lineage and listener identity narrow the
    disk-to-runtime gap but cannot attest worker configuration byte-for-byte.
    HTTP proof and collision-safe file recovery remain independently required.
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
    try:
        selected_fd = _directory(root)
        try:
            selected_stat = os.fstat(selected_fd)
            page_stat = os.stat("404.html", dir_fd=selected_fd,
                                follow_symlinks=False)
            if not stat.S_ISREG(page_stat.st_mode) or page_stat.st_nlink != 1:
                raise RouteGuardError("Selected page inode is not exclusively owned")
            selected_root = (selected_stat.st_dev, selected_stat.st_ino)
            selected_file = (page_stat.st_dev, page_stat.st_ino)
        finally:
            os.close(selected_fd)
    except OSError as exc:
        raise RouteGuardError("Selected document root/page cannot be verified") from exc
    other_roots = set()
    for path, content in files.items():
        if path == file_path:
            continue
        uncommented = re.sub(r"(?m)#[^\r\n]*$", "", content)
        # A separate named VHost or alias/root consumer invalidates exclusivity
        # even if one HTTP/80 probe happens to match.
        if re.search(r"(?m)(?<![A-Za-z0-9_])server_name\s+[^;]*\b"
                     + re.escape(name) + r"\b", uncommented):
            raise RouteGuardError("Another Nginx source binds the selected host")
        other_roots.update(_external_path_consumer(uncommented, root))
    if len(other_roots) > MAX_EXTERNAL_ROOTS:
        raise RouteGuardError("Too many other-site roots for safe ownership inspection")
    graph = hashlib.sha256()
    budget = {"entries": 0, "directories": 0,
              "deadline": time.monotonic() + EXTERNAL_SCAN_DEADLINE}
    for other_root in sorted(other_roots):
        _scan_external_root(other_root, selected_root, selected_file, graph, budget)
    observed_runtime = (runtime or _native_live_http80)(files)
    if (not isinstance(observed_runtime, dict) or
            observed_runtime.get("native_http80_process_verified") is not True or
            not isinstance(observed_runtime.get("runtime_generation_sha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}",
                             observed_runtime["runtime_generation_sha256"])):
        raise RouteGuardError("Live native HTTP/80 daemon provenance was not verified")
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
        "external_graph_sha256": graph.hexdigest(),
        "runtime_generation_sha256": observed_runtime["runtime_generation_sha256"],
        "native_http80_process_verified": True,
        "vhost_sha256": original["sha256"],
        "loaded_workers_verified": False,
        "https_verified": False,
    }
