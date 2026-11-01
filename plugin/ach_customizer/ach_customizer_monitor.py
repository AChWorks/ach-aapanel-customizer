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


def get_site_page(panel_public, page=1, page_size=25):
    """Read aaPanel's sites table with a bounded, constant-field projection."""
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
    return {"page": page, "page_size": size, "has_more": len(result) > size, "sites": sites}


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
        if key == "include":
            # Include expansion is not implemented. Trust only the explicit root
            # include already preflighted above; nested includes need review.
            candidate = value.split(";", 1)[0].split("#", 1)[0].strip()
            if allowed_include is None or candidate != allowed_include:
                raise MonitorInputError("Unexpanded or unsupported PHP-FPM include")
            continue
        if section != "www":
            continue
        if key == "pm":
            if pool_mode is not None:
                raise MonitorInputError("Duplicate PHP-FPM pool mode")
            pool_mode = value.split(";", 1)[0].split("#", 1)[0].strip()
            continue
        if key not in POOL_KEYS:
            if key.startswith("pm.") and key not in PM_PASSTHROUGH_KEYS:
                raise MonitorInputError("Unsupported PHP-FPM process-manager setting: " + key)
            continue
        if key in pool:
            raise MonitorInputError("Duplicate setting inside [www]: " + key)
        value = value.split(";", 1)[0].split("#", 1)[0].strip()
        if not re.fullmatch(r"[0-9]{1,10}", value):
            raise MonitorInputError("Unsupported value inside [www]: " + key)
        pool[key] = int(value)
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
                if key == "include":
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
                + "File/default comparison only; running pool state and site-to-pool impact are not verified. No Apply is available.",
    }
