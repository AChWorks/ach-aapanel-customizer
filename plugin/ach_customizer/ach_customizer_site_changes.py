"""Bounded, read-only native site lifecycle comparison with explicit baseline storage.

Only aaPanel SQLite site/domain records are observed. No Nginx/PHP routing,
filesystem configuration, DNS or live request is inferred. Baseline is a
separately confirmed plugin-owned observation outside replaceable plugin code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from uuid import uuid4

from ach_customizer_monitor import get_site_page
from ach_customizer_state import _exclusive_lock, _open_state_dir, _owned_file

SCHEMA = 1
MAX_SITES = 100
MAX_BINDINGS_PER_SITE = 24
MAX_SITE_KEY_BYTES = 255
MAX_DOMAIN_BYTES = 255
MAX_PATH_BYTES = 2048
MAX_BASELINE_BYTES = 512 * 1024
MAX_REVISION = 2147483647
BASELINE_FILE = "ach_customizer.sites-baseline.json"
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
SHA_PATTERN = re.compile(r"[a-f0-9]{64}")


class SiteChangesError(ValueError):
    pass


def _text(value, label, maximum, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SiteChangesError("Invalid native " + label)
    if len(value.encode("utf-8")) > maximum:
        raise SiteChangesError("Native " + label + " exceeds the bounded size")
    return value


def _normalize(site):
    if not isinstance(site, dict) or type(site.get("id")) is not int or not 0 < site["id"] <= MAX_REVISION:
        raise SiteChangesError("Invalid native site ID")
    key = _text(site.get("name"), "site key", MAX_SITE_KEY_BYTES)
    root = _text(site.get("document_root"), "document root", MAX_PATH_BYTES, allow_empty=True)
    status = _text(site.get("panel_status"), "site status", 64, allow_empty=True)
    bindings = site.get("bound_domains")
    if not isinstance(bindings, list) or len(bindings) > MAX_BINDINGS_PER_SITE:
        raise SiteChangesError("Native site has too many or invalid domain bindings")
    domains = []
    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise SiteChangesError("Invalid native domain binding")
        domain = _text(binding.get("name"), "domain", MAX_DOMAIN_BYTES)
        port = binding.get("port")
        if type(port) is not int or not 1 <= port <= 65535:
            raise SiteChangesError("Invalid native domain port")
        if (domain, port) in seen:
            raise SiteChangesError("Duplicate native site domain binding")
        seen.add((domain, port))
        domains.append([domain, port])
    domains.sort(key=lambda item: (item[0], item[1]))
    return {"id": site["id"], "name": key, "document_root": root,
            "panel_status": status, "bound_domains": domains}


def _canonical(sites):
    return json.dumps(sites, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _digest(sites):
    return hashlib.sha256(_canonical(sites)).hexdigest()


def _validated_sites(sites):
    if not isinstance(sites, list) or len(sites) > MAX_SITES:
        raise SiteChangesError("Invalid saved site inventory")
    ids = set()
    previous = 0
    for site in sites:
        if not isinstance(site, dict) or set(site) != {
                "id", "name", "document_root", "panel_status", "bound_domains"}:
            raise SiteChangesError("Invalid saved site fields")
        identity = site.get("id")
        if type(identity) is not int or identity <= previous or identity in ids:
            raise SiteChangesError("Unsorted or duplicate site identities")
        ids.add(identity)
        previous = identity
        if _normalize({
            **site, "bound_domains": [
                {"name": entry[0], "port": entry[1]}
                for entry in site.get("bound_domains", [])
                if isinstance(entry, list) and len(entry) == 2
            ],
        }) != site:
            raise SiteChangesError("Noncanonical saved site inventory")
    if len(_canonical(sites)) > MAX_BASELINE_BYTES:
        raise SiteChangesError("Saved site inventory exceeds limit")
    return sites


def _scan(panel_public):
    """Two independent bounded native queries; require an identical snapshot."""
    def one():
        result = get_site_page(panel_public, page=1, page_size=MAX_SITES)
        if result.get("has_more") or len(result.get("sites", [])) > MAX_SITES:
            raise SiteChangesError("More than 100 native sites; baseline is unsupported")
        normalized = sorted((_normalize(item) for item in result["sites"]),
                            key=lambda item: item["id"])
        return _validated_sites(normalized)

    first = one()
    second = one()
    if first != second:
        raise SiteChangesError("Native site or binding records changed during inspection; compare again")
    return second, _digest(second)


def _load(directory_fd):
    try:
        fd = os.open(BASELINE_FILE, READ_FLAGS, dir_fd=directory_fd)
    except FileNotFoundError:
        return {"schema": SCHEMA, "revision": 0, "source_sha256": None, "sites": []}
    except OSError as exc:
        raise SiteChangesError("Native site baseline cannot be opened safely") from exc
    try:
        try:
            info = _owned_file(fd, kind="site baseline")
        except Exception as exc:
            raise SiteChangesError("Untrusted native site baseline") from exc
        if not 0 < info.st_size <= MAX_BASELINE_BYTES:
            raise SiteChangesError("Native site baseline exceeds size limit")
        payload = bytearray()
        while len(payload) <= MAX_BASELINE_BYTES:
            chunk = os.read(fd, MAX_BASELINE_BYTES + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if not payload or len(payload) > MAX_BASELINE_BYTES:
            raise SiteChangesError("Native site baseline is empty or oversized")
        try:
            baseline = json.loads(payload.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise SiteChangesError("Native site baseline is not valid JSON") from exc
        if not isinstance(baseline, dict) or set(baseline) != {
                "schema", "revision", "source_sha256", "sites"}:
            raise SiteChangesError("Unknown native site baseline schema")
        if type(baseline["schema"]) is not int or baseline["schema"] != SCHEMA or type(baseline["revision"]) is not int or not 1 <= baseline["revision"] <= MAX_REVISION:
            raise SiteChangesError("Unsupported native site baseline revision")
        _validated_sites(baseline["sites"])
        if not isinstance(baseline["source_sha256"], str) or not SHA_PATTERN.fullmatch(baseline["source_sha256"]):
            raise SiteChangesError("Invalid native site baseline digest")
        if baseline["source_sha256"] != _digest(baseline["sites"]):
            raise SiteChangesError("Native site baseline fingerprint does not match records")
        return baseline
    finally:
        os.close(fd)


def read_baseline(directory):
    dir_fd = _open_state_dir(directory)
    try:
        return _load(dir_fd)
    finally:
        os.close(dir_fd)


def _differences(before, current):
    old = {s["id"]: s for s in before}
    new = {s["id"]: s for s in current}
    changes = []
    for identity in sorted(set(old) | set(new)):
        previous = old.get(identity)
        updated = new.get(identity)
        if previous is None:
            changes.append({"id": identity, "kind": "Added", "fields": [],
                            "before": None, "after": updated})
        elif updated is None:
            changes.append({"id": identity, "kind": "Removed", "fields": [],
                            "before": previous, "after": None})
        elif previous != updated:
            keys = ("name", "document_root", "panel_status", "bound_domains")
            fields = [key for key in keys if previous[key] != updated[key]]
            changes.append({"id": identity, "kind": "Changed", "fields": fields,
                            "before": previous, "after": updated})
    return changes


def compare(panel_public, *, directory):
    baseline = read_baseline(directory)
    sites, digest = _scan(panel_public)
    changes = _differences(baseline["sites"], sites) if baseline["revision"] else []
    state = ("Baseline Missing" if not baseline["revision"] else
             "Changes Observed" if changes else "No Changes")
    return {
        "schema": SCHEMA, "state": state, "scope": "native_site_records",
        "read_only": True, "runtime_verified": False,
        "baseline_revision": baseline["revision"],
        "baseline_sha256": baseline["source_sha256"],
        "source_sha256": digest, "site_count": len(sites),
        "changes": changes,
        "note": ("aaPanel sites/domain database records only. "
                 "No effective Nginx routing, PHP pool, DNS, content or live runtime verification. "
                 "Site ID reuse with identical records is not detectable. "
                 "Saving a reviewed baseline changes only plugin-owned observation history."),
    }


def _write(directory_fd, state):
    payload = (json.dumps(state, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > MAX_BASELINE_BYTES:
        raise SiteChangesError("Native site baseline exceeds size limit")
    name = ".ach_customizer.sites." + uuid4().hex + ".tmp"
    fd = os.open(name, WRITE_FLAGS, 0o600, dir_fd=directory_fd)
    replaced = False
    try:
        _owned_file(fd, kind="temporary site baseline")
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
        os.fsync(fd)
        os.replace(name, BASELINE_FILE, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        replaced = True
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            raise SiteChangesError(
                "Site baseline commit uncertain; Compare again before recording another baseline"
            ) from exc
    finally:
        os.close(fd)
        if not replaced:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def save_reviewed_baseline(panel_public, *, directory, expected_revision,
                           expected_source_sha256, reviewed):
    if reviewed != "true" and reviewed is not True:
        raise SiteChangesError("Explicit review confirmation is required")
    if type(expected_revision) is not int and (
            not isinstance(expected_revision, str) or not re.fullmatch(r"0|[1-9][0-9]{0,9}", expected_revision)):
        raise SiteChangesError("Invalid expected site baseline revision")
    revision = int(expected_revision)
    if not 0 <= revision < MAX_REVISION:
        raise SiteChangesError("Expected site baseline revision is out of range")
    if not isinstance(expected_source_sha256, str) or not SHA_PATTERN.fullmatch(expected_source_sha256):
        raise SiteChangesError("Invalid expected site source fingerprint")
    # Scan before taking the persistent lock, then re-scan under the lock to
    # reject source drift during baseline recording. No host files are modified.
    sites, digest = _scan(panel_public)
    if digest != expected_source_sha256:
        raise SiteChangesError("Native sites changed since comparison; Compare again")
    directory_fd = _open_state_dir(directory)
    try:
        lock_fd = _exclusive_lock(directory_fd)
        try:
            current = _load(directory_fd)
            if current["revision"] != revision:
                raise SiteChangesError("Site baseline revision changed; Compare again")
            second, current_digest = _scan(panel_public)
            if second != sites or current_digest != digest:
                raise SiteChangesError("Native sites changed during baseline recording; Compare again")
            if current["source_sha256"] == digest:
                return {"schema": SCHEMA, "state": "Baseline Unchanged",
                        "baseline_revision": revision, "source_sha256": digest,
                        "changed": False}
            updated = {"schema": SCHEMA, "revision": revision + 1,
                       "source_sha256": digest, "sites": sites}
            _write(directory_fd, updated)
            return {"schema": SCHEMA, "state": "Baseline Saved",
                    "baseline_revision": revision + 1, "source_sha256": digest,
                    "changed": True}
        finally:
            os.close(lock_fd)
    finally:
        os.close(directory_fd)
