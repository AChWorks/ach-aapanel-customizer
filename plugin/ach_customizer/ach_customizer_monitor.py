"""Read-only aaPanel monitor primitives; no host configuration writes."""

from __future__ import annotations

import re
from pathlib import Path

POOL_KEYS = (
    "pm.max_children",
    "pm.start_servers",
    "pm.min_spare_servers",
    "pm.max_spare_servers",
    "pm.max_requests",
)
# These are native FPM process-manager directives, not policy fields.
# Unknown pm.* keys must not be silently mistaken for an omitted policy key.
PM_PASSTHROUGH_KEYS = frozenset((
    "pm.status_path",
    "pm.status_listen",
    "pm.process_idle_timeout",
    "pm.max_spawn_rate",
))
# Conservative INI key syntax: regular FPM directives and php/env array keys.
FPM_INI_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*(?:\[[A-Za-z0-9_./:-]+\])?")

CONFIG_FILES_LIMIT = 32
MAX_CONFIG_BYTES = 256 * 1024
MAX_DOMAIN_ROWS_PER_PAGE = 1000
MAX_DOMAIN_NAME_BYTES = 1024
MAX_DOMAIN_TEXT_BYTES_PER_PAGE = 256 * 1024
INVENTORY_SCHEMA_VERSION = 2
PHP_IMPACT_SCHEMA_VERSION = 1
PHP_IMPACT_SITE_LIMIT = 100
MAX_NGINX_SITE_BYTES = 64 * 1024


class MonitorInputError(ValueError):
    pass


def parse_page(value, *, maximum=100000):
    try:
        number = int(str(value))
    except (ValueError, TypeError):
        raise MonitorInputError("Page must be a positive integer") from None
    if not 1 <= number <= maximum:
        raise MonitorInputError("Page is outside the supported range")
    return number


def _bound_domains_for_sites(panel_public, sites):
    """Read recorded domain bindings in one bounded aaPanel domain-table query.

    aaPanel's native AddDomain/DelDomain can change HTTP domains without
    changing sites.name or its VHost filename. Never infer active domains
    from the canonical site key.
    """
    if not sites:
        return
    ids = [site["id"] for site in sites]
    if len(set(ids)) != len(ids):
        raise RuntimeError("aaPanel sites query returned duplicate site IDs")
    placeholders = ",".join("?" for _ in ids)
    result = (
        panel_public.M("domain")
        .where("pid IN (" + placeholders + ")", tuple(ids))
        .order("pid asc, id asc")
        .limit(f"0,{MAX_DOMAIN_ROWS_PER_PAGE + 1}")
        .field("id,pid,name,port")
        .select()
    )
    if not isinstance(result, list):
        raise RuntimeError("aaPanel domain query did not return a list")
    if len(result) > MAX_DOMAIN_ROWS_PER_PAGE:
        raise RuntimeError("Bound-domain inventory exceeded the read limit; use a smaller page size")
    bindings = {site_id: [] for site_id in ids}
    seen = set()
    seen_ids = set()
    total_name_bytes = 0
    for record in result:
        if not isinstance(record, dict):
            raise RuntimeError("aaPanel domain query returned an invalid row")
        try:
            raw_pid = str(record["pid"])
            raw_id = str(record["id"])
            if not re.fullmatch(r"[0-9]+", raw_pid) or not re.fullmatch(r"[0-9]+", raw_id):
                raise ValueError("invalid row identity")
            pid = int(raw_pid)
            row_id = int(raw_id)
            port_text = str(record["port"])
            if not re.fullmatch(r"[0-9]{1,5}", port_text):
                raise ValueError("invalid port")
            port = int(port_text)
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("aaPanel domain query returned an invalid site ID or port") from None
        domain = record.get("name")
        if row_id <= 0 or pid not in bindings or not 1 <= port <= 65535 or not isinstance(domain, str) or not domain.strip():
            raise RuntimeError("aaPanel domain query returned an invalid or out-of-page binding")
        try:
            name_bytes = len(domain.encode("utf-8"))
        except UnicodeEncodeError:
            raise RuntimeError("aaPanel domain query returned an invalid domain encoding") from None
        if name_bytes > MAX_DOMAIN_NAME_BYTES:
            raise RuntimeError("aaPanel domain name exceeds the read limit")
        total_name_bytes += name_bytes
        if total_name_bytes > MAX_DOMAIN_TEXT_BYTES_PER_PAGE:
            raise RuntimeError("Bound-domain inventory exceeds the response text limit; use a smaller page size")
        identity = (pid, domain, port)
        if identity in seen or row_id in seen_ids:
            raise RuntimeError("aaPanel domain query returned a duplicate binding")
        seen.add(identity)
        seen_ids.add(row_id)
        bindings[pid].append({"name": domain, "port": port})
    for site in sites:
        site["bound_domains"] = bindings[site["id"]]
        site["canonical_domain_bound"] = any(
            binding["name"] == site["name"] for binding in site["bound_domains"]
        )


def get_site_page(panel_public, page=1, page_size=25):
    """Read aaPanel site IDs and actual bound domains; never write host state."""
    page = parse_page(page)
    size = parse_page(page_size, maximum=100)
    offset = (page - 1) * size
    result = (
        panel_public.M("sites")
        .order("id asc")
        .limit(f"{offset},{size + 1}")
        .field("id,name,path,status")
        .select()
    )
    if not isinstance(result, list):
        raise RuntimeError("aaPanel sites query did not return a list")
    sites = []
    for site in result[:size]:
        if not isinstance(site, dict):
            raise RuntimeError("aaPanel sites query returned an invalid row")
        try:
            site_id = int(site["id"])
        except (KeyError, ValueError, TypeError):
            raise RuntimeError("aaPanel sites query returned an invalid site ID") from None
        if site_id <= 0:
            raise RuntimeError("aaPanel sites query returned a non-positive site ID")
        name = site.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("aaPanel sites query returned an invalid site name")
        sites.append({
            "id": site_id,
            "name": name,
            "document_root": str(site.get("path") or ""),
            "panel_status": "" if site.get("status") is None else str(site["status"]),
            "application": "Unclassified",
            "classification": "Needs Review",
        })
    _bound_domains_for_sites(panel_public, sites)
    return {"inventory_schema": INVENTORY_SCHEMA_VERSION, "page": page, "page_size": size,
            "has_more": len(result) > size, "sites": sites}


def expected_pool_values(values):
    if not isinstance(values, dict):
        raise MonitorInputError("Expected pool values must be supplied as a mapping")
    result = {}
    for key in POOL_KEYS:
        value = values.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise MonitorInputError("Missing or invalid expected value: " + key)
        raw = str(value).strip()
        if not re.fullmatch(r"[0-9]{1,7}", raw):
            raise MonitorInputError("Expected value must be a nonnegative integer: " + key)
        number = int(raw)
        if number == 0 and key != "pm.max_requests":
            raise MonitorInputError("Value must be positive: " + key)
        result[key] = number
    if not (result["pm.min_spare_servers"] <= result["pm.start_servers"]
            <= result["pm.max_spare_servers"] <= result["pm.max_children"]):
        raise MonitorInputError("Expected FPM concurrency ordering is inconsistent")
    return result


def _parse_pool_file(file_path, allowed_include=None):
    if file_path.is_symlink() or not file_path.is_file():
        raise MonitorInputError("Non-regular or linked FPM configuration: " + str(file_path))
    if file_path.stat().st_size > MAX_CONFIG_BYTES:
        raise MonitorInputError("FPM configuration exceeds the read limit: " + str(file_path))
    text = file_path.read_text(encoding="utf-8")
    section = None
    seen_sections = set()
    pool = {}
    pool_mode = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            # The monitor only supports one canonical [www] pool. Reject case
            # variants rather than accidentally treating them as other pools.
            if section.lower() == "www" and section != "www":
                raise MonitorInputError("Noncanonical [www] pool section")
            if section in seen_sections and section == "www":
                raise MonitorInputError("Duplicate [www] pool section")
            seen_sections.add(section)
            continue
        # Without '=', a malformed directive (not a genuine omission) could
        # otherwise activate the implicit pm.max_requests=0 default.
        if "=" not in line:
            raise MonitorInputError("Malformed PHP-FPM directive on line " + str(line_number))
        key, value = (part.strip() for part in line.split("=", 1))
        if not FPM_INI_KEY.fullmatch(key):
            raise MonitorInputError("Unsupported PHP-FPM directive key on line " + str(line_number))
        # Ordinary PHP-FPM directive names are case-insensitive. Normalize
        # comparisons, but preserve the original key and array-key suffix.
        canonical_key = key.lower()
        if canonical_key == "include":
            # PHP-FPM special-cases lowercase "include" with a case-sensitive
            # comparison, unlike ordinary pool directives. Never expand an
            # unrecognized mixed-case variant as a valid include.
            if key != "include":
                raise MonitorInputError("Noncanonical PHP-FPM include directive")
            # Includes inside a pool inherit parser context. The independent
            # file parser cannot safely infer defaults across that boundary.
            if section == "www":
                raise MonitorInputError("include inside [www] pool needs review")
            # Trust only the explicit root include preflighted above; nested
            # or separately scoped includes require context-aware expansion.
            candidate = value.split(";", 1)[0].split("#", 1)[0].strip()
            if allowed_include is None or candidate != allowed_include:
                raise MonitorInputError("Unexpanded or unsupported PHP-FPM include")
            continue
        if section != "www":
            # Headerless include fragments may inherit an active pool from the
            # parent. Never skip process-manager values outside our explicit
            # [www] context and then infer pm.max_requests=0.
            if canonical_key == "pm" or canonical_key.startswith("pm."):
                raise MonitorInputError("Unscoped or unsupported PHP-FPM pool setting: " + key)
            continue
        if canonical_key == "pm":
            if pool_mode is not None:
                raise MonitorInputError("Duplicate PHP-FPM pool mode")
            pool_mode = value.split(";", 1)[0].split("#", 1)[0].strip()
            continue
        if canonical_key not in POOL_KEYS:
            if canonical_key.startswith("pm.") and canonical_key not in PM_PASSTHROUGH_KEYS:
                raise MonitorInputError("Unsupported PHP-FPM process-manager setting: " + key)
            continue
        if canonical_key in pool:
            raise MonitorInputError("Duplicate setting inside [www]: " + canonical_key)
        value = value.split(";", 1)[0].split("#", 1)[0].strip()
        if not re.fullmatch(r"[0-9]{1,10}", value):
            raise MonitorInputError("Unsupported value inside [www]: " + canonical_key)
        pool[canonical_key] = int(value)
    if "www" in seen_sections and pool_mode != "dynamic":
        raise MonitorInputError("Only an explicit dynamic [www] pool is supported")
    return "www" in seen_sections, pool


def preview_php_fpm(config_root, version, expected):
    """Inspect only versioned, conventional FPM files; never change or reload them."""
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]{2,3}", version):
        raise MonitorInputError("Invalid PHP version identifier")
    desired = expected_pool_values(expected)
    version_dir = Path(config_root) / version
    etc_dir = version_dir / "etc"
    if version_dir.is_symlink() or etc_dir.is_symlink() or not etc_dir.is_dir():
        return {"state": "Needs Review", "reason": "PHP-FPM directory was not found or is linked", "scope": "shared_service", "version": version}
    main_conf = etc_dir / "php-fpm.conf"
    if not main_conf.exists() or main_conf.is_symlink() or not main_conf.is_file():
        return {"state": "Needs Review", "reason": "Main PHP-FPM configuration is missing or linked", "scope": "shared_service", "version": version}
    try:
        if main_conf.stat().st_size > MAX_CONFIG_BYTES:
            raise MonitorInputError("Main PHP-FPM configuration exceeds the read limit")
        include_values = []
        for line in main_conf.read_text(encoding="utf-8").splitlines():
            line = line.split(";", 1)[0].split("#", 1)[0].strip()
            if "=" in line:
                key, value = (x.strip() for x in line.split("=", 1))
                if key.lower() == "include":
                    # Reject variants before selecting files to inspect: they
                    # are not recognized as includes by PHP-FPM itself.
                    if key != "include":
                        raise MonitorInputError("Noncanonical PHP-FPM include directive")
                    include_values.append(value)
        if len(include_values) > 1:
            raise MonitorInputError("Multiple PHP-FPM include directives need review")
        known_includes = ("php-fpm.d/*.conf", str(etc_dir / "php-fpm.d" / "*.conf"))
        if include_values and include_values[0] not in known_includes:
            raise MonitorInputError("PHP-FPM uses an unsupported include pattern")
    except (MonitorInputError, OSError, UnicodeError) as exc:
        return {"state": "Needs Review", "reason": str(exc)[:300], "scope": "shared_service", "version": version}
    paths = [main_conf]
    includes_dir = etc_dir / "php-fpm.d"
    if includes_dir.is_symlink():
        return {"state": "Needs Review", "reason": "PHP-FPM include directory is linked", "scope": "shared_service", "version": version}
    if includes_dir.exists() and include_values:
        if not includes_dir.is_dir():
            return {"state": "Needs Review", "reason": "Unexpected PHP-FPM include directory type", "scope": "shared_service", "version": version}
        include_files = sorted(includes_dir.glob("*.conf"))
        if len(include_files) > CONFIG_FILES_LIMIT:
            return {"state": "Needs Review", "reason": "Too many PHP-FPM files for bounded discovery", "scope": "shared_service", "version": version}
        paths.extend(include_files)
    found = []
    try:
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            has_pool, actual = _parse_pool_file(
                path, allowed_include=include_values[0] if path == main_conf and include_values else None
            )
            if has_pool:
                found.append((str(path), actual))
    except (MonitorInputError, OSError, UnicodeError) as exc:
        return {"state": "Needs Review", "reason": str(exc)[:300], "scope": "shared_service", "version": version}
    if len(found) != 1:
        return {"state": "Needs Review", "reason": "Exactly one explicit [www] pool is required; found " + str(len(found)), "scope": "shared_service", "version": version}
    source, actual = found[0]
    # PHP-FPM documents pm.max_requests=0 when the directive is omitted.
    # aaPanel's native php-fpm.conf template omits it entirely. Do not
    # fabricate defaults for the other, mandatory dynamic-pool settings.
    implicit_defaults = []
    if "pm.max_requests" not in actual:
        actual["pm.max_requests"] = 0
        implicit_defaults.append({"setting": "pm.max_requests", "value": 0, "origin": "PHP-FPM default"})
    missing = [key for key in POOL_KEYS if key not in actual]
    if missing:
        return {"state": "Needs Review", "reason": "Missing explicit settings: " + ", ".join(missing), "scope": "shared_service", "version": version, "source": source}
    diff = [{"setting": key, "desired": desired[key], "actual": actual[key]}
            for key in POOL_KEYS if desired[key] != actual[key]]
    return {
        "state": "File Drift" if diff else "File Match",
        "scope": "shared_service",
        "version": version,
        "pool": "www",
        "source": source,
        "changes": diff,
        "implicit_defaults": implicit_defaults,
        "note": ("pm.max_requests=0 is the documented PHP-FPM default, not an explicit file value. "
                 if implicit_defaults else "")
                + "File/default comparison only; running pool state is not verified. Shared-site file attribution is separately classified and is not an Apply authorization.",
    }


def _bounded_file_text(path, byte_limit):
    """Read one regular config without following its final symlink."""
    import os
    import stat

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > byte_limit:
            raise MonitorInputError("Unsupported or oversized configuration file")
        content = bytearray()
        while len(content) <= byte_limit:
            chunk = os.read(fd, byte_limit + 1 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > byte_limit:
            raise MonitorInputError("Configuration file exceeds the read limit")
        return content.decode("utf-8")
    finally:
        os.close(fd)


def _single_www_listen(pool_source):
    """Extract only a literal, unique Unix listen of the already parsed pool."""
    text = _bounded_file_text(pool_source, MAX_CONFIG_BYTES)
    section = None
    addresses = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "www" or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        if key.lower() == "listen":
            addresses.append(value.split(";", 1)[0].split("#", 1)[0].strip())
    if len(addresses) != 1 or not re.fullmatch(r"/[A-Za-z0-9_./-]+\.sock", addresses[0]):
        raise MonitorInputError("A single literal Unix socket in [www] is required")
    return addresses[0]


def _native_nginx_php_version(vhost_text):
    """Identify only the conventional direct aaPanel PHP include, not full routing."""
    includes = re.findall(
        r"(?m)^[ \t]*include[ \t]+([^;\s]+)[ \t]*;[ \t]*(?:\#[^\n]*)?$",
        vhost_text,
    )
    php_includes = [value for value in includes if "enable-php-" in value]
    if len(php_includes) != 1 or re.search(r"(?m)^[ \t]*fastcgi_pass\b", vhost_text):
        raise MonitorInputError("No unique conventional PHP include in the site VHost")
    match = re.fullmatch(r"enable-php-([0-9]{2,3})\.conf", php_includes[0])
    if not match:
        raise MonitorInputError("The PHP include requires review")
    return match.group(1)


def inspect_php_fpm_site_impact(panel_public, version, pool_source, *,
                                vhost_root="/www/server/panel/vhost/nginx",
                                nginx_conf_root="/www/server/nginx/conf"):
    """Bounded, read-only **file attribution**, never an effective-runtime claim.

    One shared PHP-FPM service can serve multiple native sites. Nginx
    extension overlays, indirect includes, alternative FastCGI layouts,
    concurrent regeneration and mixed web engines cannot be inferred from
    a VHost's direct include alone; refuse such ownership claims.
    """
    result = {
        "schema": PHP_IMPACT_SCHEMA_VERSION,
        "state": "Needs Review",
        "scope": "shared_service",
        "version": version,
        "matched_sites": [],
        "unresolved_sites": [],
        "site_count": 0,
        "other_php_sites_count": 0,
        "reason": "",
        "note": ("Conventional Nginx VHost/PHP include and [www] Unix-socket FILE attribution only; "
                 "not proof of effective routing, PHP worker state, or a complete impact boundary for Apply."),
    }
    try:
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]{2,3}", version):
            raise MonitorInputError("Invalid PHP version for shared impact")
        vhost_dir = Path(vhost_root)
        nginx_dir = Path(nginx_conf_root)
        if vhost_dir.is_symlink() or nginx_dir.is_symlink():
            raise MonitorInputError("Linked Nginx configuration directory")
        socket = _single_www_listen(pool_source)
        php_include = _bounded_file_text(
            nginx_dir / ("enable-php-" + version + ".conf"), MAX_NGINX_SITE_BYTES
        )
        fastcgi = re.findall(
            r"(?m)^[ \t]*fastcgi_pass[ \t]+unix:([^;\s]+)[ \t]*;",
            php_include,
        )
        if len(fastcgi) != 1 or fastcgi[0] != socket:
            raise MonitorInputError("Nginx PHP include is not mapped to the inspected [www] socket")
        # Native DB is the authority for website IDs. Refuse partial sets:
        # missing later pages would create an unsafe shared-resource claim.
        rows = (
            panel_public.M("sites")
            .order("id asc")
            .limit("0," + str(PHP_IMPACT_SITE_LIMIT + 1))
            .field("id,name")
            .select()
        )
        if not isinstance(rows, list):
            raise MonitorInputError("aaPanel website inventory is unavailable")
        if len(rows) > PHP_IMPACT_SITE_LIMIT:
            raise MonitorInputError("Website count exceeds bounded shared-pool attribution")
        seen = set()
        for site in rows:
            if not isinstance(site, dict) or not re.fullmatch(r"[0-9]+", str(site.get("id", ""))):
                raise MonitorInputError("Unexpected website identity")
            site_id = int(site["id"])
            if site_id <= 0 or site_id in seen:
                raise MonitorInputError("Duplicate or invalid website ID")
            seen.add(site_id)
            name = site.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 255:
                raise MonitorInputError("Invalid native website key")
            result["site_count"] += 1
            site_key = {"id": site_id, "site_key": name}
            # Website identity comes from SQLite, never from an arbitrary path
            # supplied by an HTTP client. Unknown naming is Needs Review.
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                result["unresolved_sites"].append({**site_key, "reason": "Unsupported VHost filename"})
                continue
            try:
                vhost = _bounded_file_text(
                    vhost_dir / (name + ".conf"), MAX_NGINX_SITE_BYTES
                )
                assigned = _native_nginx_php_version(vhost)
            except (OSError, UnicodeError, MonitorInputError):
                result["unresolved_sites"].append({**site_key, "reason": "VHost PHP assignment needs review"})
                continue
            if assigned == version:
                result["matched_sites"].append(site_key)
            else:
                result["other_php_sites_count"] += 1
        if result["unresolved_sites"]:
            result["reason"] = "Some website assignments are ambiguous; shared impact is incomplete"
        else:
            result["state"] = "File Mapping"
    except (OSError, UnicodeError, MonitorInputError, ValueError) as exc:
        # A global DB/schema/socket error invalidates *all* partial matches.
        # Only per-site unsupported VHosts keep already proven file links.
        result.update(matched_sites=[], unresolved_sites=[], site_count=0,
                      other_php_sites_count=0, reason=str(exc)[:250])
    return result
