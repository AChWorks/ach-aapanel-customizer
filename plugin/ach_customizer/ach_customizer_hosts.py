"""Read-only host-local /etc/hosts diagnostics for native aaPanel website domains.

A matching loopback alias is an *origin-local source observation*, not proof
of broken public DNS or remote Gateway reachability. Never modify /etc/hosts,
invoke a resolver, or infer another machine's DNS behavior.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import stat

HOSTS_PATH = "/etc/hosts"
MAX_BYTES = 65536
MAX_LINES = 2048
MAX_DOMAINS = 100
MAX_MATCHES = 100
MAX_ALIASES_PER_LINE = 128
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class HostsInspectionError(ValueError):
    pass


def _hostname(value):
    if not isinstance(value, str) or not value or len(value) > 253 or value.strip() != value:
        raise HostsInspectionError("Invalid website hostname")
    if value.startswith("*."):
        raise HostsInspectionError("Wildcard website hostnames cannot be resolved as exact /etc/hosts aliases")
    if any(ord(c) < 33 or c in "/\\#:@" for c in value):
        raise HostsInspectionError("Unsafe hostname")
    try:
        normalized = (value[:-1] if value.endswith(".") else value).encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HostsInspectionError("Invalid IDNA website hostname") from exc
    labels = normalized.split(".")
    if not 1 <= len(normalized) <= 253 or any(
        not 1 <= len(label) <= 63 or
        not re.fullmatch("[a-z0-9-]+", label) or
        label[0] == "-" or label[-1] == "-"
        for label in labels
    ):
        raise HostsInspectionError("Noncanonical website hostname")
    return normalized


def _site_domains(domains):
    if not isinstance(domains, list) or not 1 <= len(domains) <= MAX_DOMAINS:
        raise HostsInspectionError("Bounded native website domain inventory is required")
    resolved, unsupported = [], []
    for entry in domains:
        if not isinstance(entry, str):
            raise HostsInspectionError("Invalid native website domain")
        if entry.startswith("*."):
            canonical_wildcard = "*." + _hostname(entry[2:])
            if canonical_wildcard not in unsupported:
                unsupported.append(canonical_wildcard)
            continue
        canonical = _hostname(entry)
        if canonical not in resolved:
            resolved.append(canonical)
    if not resolved:
        raise HostsInspectionError("No exact bound website hostname to inspect")
    return resolved, unsupported


def native_site_snapshot(site):
    """Canonical comparison-only snapshot of the selected native inventory.

    The browser sees the same fields through get_site_page; only native
    database reads determine which hostnames will actually be inspected.
    Sorting makes the precondition independent of database row ordering.
    """
    bindings = site["bound_domains"]
    return [
        site["id"], site["name"], str(site.get("path") or ""),
        "" if site.get("status") is None else str(site["status"]),
        sorted(([item["name"], item["port"]] for item in bindings),
               key=lambda item: (item[0], item[1])),
    ]


def _file_bytes(path):
    """Descriptor-anchored, stable small-file read. Fixture path only in tests."""
    if (not isinstance(path, str) or not path.startswith("/")
            or len(path) > 1024 or "//" in path or "\x00" in path):
        raise HostsInspectionError("Invalid hosts path")
    parts = path.split("/")[1:]
    if len(parts) > 40 or any(x in ("", ".", "..") for x in parts):
        raise HostsInspectionError("Unsafe hosts path")
    if not parts or parts[-1] != "hosts":
        raise HostsInspectionError("Inspection is restricted to a hosts file")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        source = os.open(parts[-1], FILE_FLAGS, dir_fd=fd)
        try:
            before = os.fstat(source)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != os.geteuid()
                    or (before.st_mode & 0o022) or not 0 < before.st_size <= MAX_BYTES):
                raise HostsInspectionError("Unsafe /etc/hosts source file identity")
            data = bytearray()
            while len(data) <= MAX_BYTES:
                chunk = os.read(source, MAX_BYTES + 1 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            after = os.fstat(source)
            fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode",
                      "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
            if len(data) != before.st_size or any(
                getattr(before, k) != getattr(after, k) for k in fields
            ):
                raise HostsInspectionError("Hosts file changed during inspection")
            # fstat() alone misses rename(2) replacing the pathname while
            # our descriptor still points to the now-superseded old inode.
            # Recheck the *fixed* final basename relative to the same pinned
            # parent. Never follow a replacement symlink or open a new file.
            try:
                pathname = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            except OSError as exc:
                raise HostsInspectionError("Hosts source changed; retry inspection") from exc
            if (not stat.S_ISREG(pathname.st_mode) or any(
                getattr(after, k) != getattr(pathname, k) for k in fields
            )):
                raise HostsInspectionError("Hosts source changed; retry inspection")
            return bytes(data)
        finally:
            os.close(source)
    finally:
        os.close(fd)


def inspect_local_hosts(domains, *, source_path=HOSTS_PATH):
    """Return only native-site matching aliases; never expose entire hosts."""
    names, skipped = _site_domains(domains)
    payload = _file_bytes(source_path)
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise HostsInspectionError("Hosts file has unsupported text encoding") from exc
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise HostsInspectionError("Hosts file has too many lines")

    matches = []
    selected = set(names)
    for line_number, raw in enumerate(lines, 1):
        active = raw.partition("#")[0].strip()
        if not active:
            continue
        tokens = active.split()
        if len(tokens) < 2 or len(tokens) > MAX_ALIASES_PER_LINE + 1:
            raise HostsInspectionError("Invalid hosts entry shape at line " + str(line_number))
        try:
            address = ipaddress.ip_address(tokens[0])
        except ValueError as exc:
            raise HostsInspectionError("Invalid IP address in hosts file at line " + str(line_number)) from exc
        is_loopback = address.is_loopback or bool(
            isinstance(address, ipaddress.IPv6Address) and
            address.ipv4_mapped is not None and address.ipv4_mapped.is_loopback
        )
        seen_line = set()
        for alias in tokens[1:]:
            try:
                canonical = _hostname(alias)
            except HostsInspectionError:
                # Unrelated aliases can be OS-specific; they never establish
                # a match to a validated native website name.
                continue
            if canonical not in selected or canonical in seen_line:
                continue
            seen_line.add(canonical)
            if len(matches) >= MAX_MATCHES:
                raise HostsInspectionError("Too many local hosts entries for selected site")
            matches.append({
                "domain": canonical, "address": str(address),
                "line": line_number, "loopback": bool(is_loopback),
            })
    matched_loopback = any(item["loopback"] for item in matches)
    state = ("Local Loopback Entry" if matched_loopback
             else "Needs Review" if skipped
             else "No Local Loopback Entry")
    reason = (
        "An exact website hostname has an explicit origin-local loopback entry"
        if matched_loopback else
        "Some wildcard bindings cannot be checked as exact hosts aliases"
        if skipped else
        "No explicit loopback entry found for these exact bound hostnames"
    )
    return {
        "schema": 1, "state": state, "reason": reason,
        "domains": names, "uninspected_wildcards": skipped,
        "entries": matches, "hosts_sha256": hashlib.sha256(payload).hexdigest(),
        "read_only": True, "remote_dns_verified": False,
        "resolver_verified": False, "gateway_verified": False, "fix_supported": False,
        "note": ("Snapshot of /etc/hosts text on the aaPanel origin only. "
                 "This does not determine OS resolver precedence, public DNS, "
                 "proxy behavior, another host/Gateway's resolution or connectivity. "
                 "Loopback aliases may be intentional. Separate reviewed manual removal is "
                 "available only with the current file and native website identity."),
    }
