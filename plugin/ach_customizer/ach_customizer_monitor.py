"""Read-only aaPanel monitor primitives; no host configuration writes."""

from __future__ import annotations

import hashlib
import json
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
NATIVE_SITE_QUERY_BATCH = 100  # Paged query size, not a maximum website count.
MAX_NGINX_SITE_BYTES = 64 * 1024

# One policy for every accepted Nginx file, not one predicate per include type.
# The main PHP snippet is the sole exception: it must have exactly one
# separately validated literal Unix fastcgi_pass to the inspected [www] socket.
NGINX_UPSTREAM_DIRECTIVES = re.compile(
    r"\b(?:fastcgi_pass|proxy_pass|uwsgi_pass|scgi_pass|grpc_pass|memcached_pass)\b"
)


class MonitorInputError(ValueError):
    pass


PHP_DISCOVERY_SCHEMA_VERSION = 1
MAX_PHP_ROOT_ENTRIES = 128
MAX_PHP_VERSION_DIRECTORIES = 32


def discover_php_fpm_versions(config_root):
    """Bounded aaPanel PHP installation *file presence*, never runtime proof.

    Names are discovered from the trusted aaPanel PHP root, not user input.
    Open each directory relative to the pinned parent with O_NOFOLLOW;
    never execute a PHP binary, probe ports, reload services or read PHP config.
    """
    import os
    import stat

    response = {
        "schema": PHP_DISCOVERY_SCHEMA_VERSION,
        "state": "Needs Review",
        "versions": [],
        "read_only": True,
        "runtime_verified": False,
        "reason": "",
        "note": ("Observed aaPanel versioned files only. This does not prove installed "
                 "processes, effective pool configuration, or runtime compatibility. "
                 "PHP 8.5 has a separate guarded Manual Apply adapter; discovery "
                 "never authorizes a change or enables another adapter."),
    }
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    path = Path(config_root)
    if not path.is_absolute() or ".." in path.parts:
        raise MonitorInputError("Invalid aaPanel PHP installation root")
    def anchored_root():
        # Reopen the *original absolute pathname* for the final source check.
        # A pinned descriptor may otherwise survive a directory rename while
        # its original path now refers to a different PHP installation.
        fd = os.open("/", directory_flags)
        try:
            for name in path.parts[1:]:
                following = os.open(name, directory_flags, dir_fd=fd)
                os.close(fd)
                fd = following
            return fd
        except BaseException:
            os.close(fd)
            raise

    def identity(info):
        return tuple(getattr(info, key) for key in
                     ("st_dev", "st_ino", "st_mode", "st_nlink",
                      "st_size", "st_mtime_ns", "st_ctime_ns"))

    def file_present(ver, dirname, filename, *, executable=False):
        # The file is only stat'ed, never opened/executed. Capture both the
        # parent directory identity and final regular-file identity so an
        # atomic replacement cannot masquerade as the inspected source.
        try:
            sub = os.open(dirname, directory_flags, dir_fd=ver)
        except OSError:
            return False, None
        try:
            directory_identity = identity(os.fstat(sub))
            try:
                meta = os.stat(filename, dir_fd=sub, follow_symlinks=False)
            except OSError:
                return False, (directory_identity, None)
            found = (stat.S_ISREG(meta.st_mode) and meta.st_size > 0 and
                     (not executable or bool(meta.st_mode & 0o111)))
            return found, (directory_identity, identity(meta))
        finally:
            os.close(sub)

    def bounded_names(fd):
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(names) >= MAX_PHP_ROOT_ENTRIES:
                    raise MonitorInputError("Too many entries in aaPanel PHP installation root")
                names.append(entry.name)
        return sorted(names)

    try:
        root = anchored_root()
    except OSError:
        response["reason"] = "aaPanel PHP installation root missing or inaccessible"
        return response
    try:
        # Two bounded scans are compared; the second is rooted at the actual
        # current path, not the original, possibly detached descriptor.
        names = bounded_names(root)
        original_root_identity = identity(os.fstat(root))
        version_names = [name for name in names if re.fullmatch(r"[1-9][0-9]{1,2}", name)]
        observed = {}
        if len(version_names) > MAX_PHP_VERSION_DIRECTORIES:
            raise MonitorInputError("Too many PHP version directories for bounded discovery")
        for code in sorted(version_names, key=lambda x: (int(x[0]), int(x[1:]))):
            major, minor = int(code[0]), int(code[1:])
            version = {"code": code, "label": "PHP " + str(major) + "." + str(minor),
                       "state": "Needs Review", "binary_present": False,
                       "config_present": False, "preview_candidate": False,
                       "manual_apply_adapter": "none", "apply_eligible": False,
                       "reason": ""}
            response["versions"].append(version)
            try:
                ver = os.open(code, directory_flags, dir_fd=root)
            except OSError:
                observed[code] = None
                version["reason"] = "Versioned PHP directory is inaccessible or linked"
                continue
            try:
                ver_identity = identity(os.fstat(ver))
                binary, binary_identity = file_present(ver, "sbin", "php-fpm", executable=True)
                config, config_identity = file_present(ver, "etc", "php-fpm.conf")
                observed[code] = (ver_identity, binary_identity, config_identity)
                version["binary_present"] = binary
                version["config_present"] = config
                if (major, minor) < (8, 1):
                    version["state"] = "Unsupported"
                    version["reason"] = "Below the PHP 8.1+ inspection target"
                elif version["binary_present"] and version["config_present"]:
                    version["state"] = "File Preview Candidate"
                    version["preview_candidate"] = True
                    # This indicates only that an adapter exists in source;
                    # even PHP85 must pass a separate exact Prepare/approval.
                    if code in ("81", "85"):
                        version["manual_apply_adapter"] = "guarded_php" + code
                    version["reason"] = "Pool parser and runtime still require separate verification"
                else:
                    version["reason"] = "Native PHP-FPM binary or main config is missing or unsupported"
            finally:
                os.close(ver)
        # A directory rename, aaPanel update or site-level operation may
        # replace any ancestor, version folder, binary or config during the
        # scan. Never return those stale positive findings as current.
        try:
            current_root = anchored_root()
            try:
                if (identity(os.fstat(current_root)) != original_root_identity
                        or bounded_names(current_root) != names):
                    raise OSError("PHP installation root or entries changed")
                for code in version_names:
                    try:
                        current_ver = os.open(code, directory_flags, dir_fd=current_root)
                    except OSError:
                        if observed[code] is not None:
                            raise OSError("PHP installation directory changed")
                        continue
                    try:
                        binary, binary_identity = file_present(
                            current_ver, "sbin", "php-fpm", executable=True)
                        config, config_identity = file_present(
                            current_ver, "etc", "php-fpm.conf")
                        current = (identity(os.fstat(current_ver)),
                                   binary_identity, config_identity)
                        if observed[code] != current:
                            raise OSError("PHP installation file changed")
                    finally:
                        os.close(current_ver)
            finally:
                os.close(current_root)
        except OSError:
            response.update(
                state="Needs Review", versions=[],
                reason="aaPanel PHP source pathname or file changed during inspection; Refresh installed PHP"
            )
            return response
        if not response["versions"]:
            response["reason"] = "No versioned aaPanel PHP installation directories found"
        elif any(item["state"] != "File Preview Candidate" for item in response["versions"]):
            response["state"] = "Partial"
            response["reason"] = "Some PHP installations are incomplete or outside the inspection target"
        else:
            response["state"] = "Observed"
    finally:
        os.close(root)
    return response


def _active_nginx_text(source):
    """Keep active Nginx text; strip only comments at argument boundaries.

    nginx's ngx_conf_read_token() treats '#' as a comment only when it
    begins a token, not inside quotes, unquoted arguments or escapes.
    Preserve quoted values and same-line directives for downstream
    conservative routing checks. Refuse incomplete lexical forms.
    The caller already bounds source bytes and validates file identity.
    """
    active = []
    token_start = True
    quote = None
    escaped = False
    in_comment = False
    after_quote = False
    variable = False

    for ch in source:
        if in_comment:
            if ch == "\n":
                active.append(ch)
                in_comment = False
                token_start = True
            continue
        if escaped:
            active.append(ch)
            escaped = False
            continue
        if ch == "\\":
            active.append(ch)
            escaped = True
            token_start = False
            variable = False
            continue
        if quote is not None:
            active.append(ch)
            if ch == quote:
                quote = None
                after_quote = True
            continue
        if after_quote:
            # Nginx requires a delimiter or ')' after a quoted argument.
            if ch not in " \t\r\n;{)":
                raise MonitorInputError("Ambiguous Nginx text after quoted argument")
            active.append(ch)
            token_start = True
            after_quote = False
            continue
        if token_start:
            if ch == "#":
                in_comment = True
                continue
            active.append(ch)
            if ch in " \t\r\n;{}":
                continue
            if ch in ("'", '"'):
                quote = ch
            if ch == "$":
                variable = True
            token_start = False
            continue

        active.append(ch)
        if ch in " \t\r\n;":
            token_start = True
            variable = False
        elif ch == "$":
            variable = True
        elif ch == "{" and not variable:
            token_start = True
        else:
            variable = False

    if quote is not None or escaped or after_quote:
        raise MonitorInputError("Unterminated or ambiguous Nginx argument")
    return "".join(active)


def _native_server_direct_include(source, include_path):
    """Require one literal include directly inside one native server block.

    This is a small Nginx lexical scope check, not a general config parser.
    Ignore quoted/escaped braces as delimiters and strip only real comments
    via the existing Nginx argument lexer. Refuse ambiguous block structure,
    duplicate includes, and includes nested in locations/if blocks.
    """
    active = _active_nginx_text(source)
    stack = []
    part = []
    quote = None
    escaped = False
    in_variable = False
    variable_chars = 0
    dollar = False
    matches = 0
    servers = 0
    exact = re.compile(r"include[ \t]+" + re.escape(include_path) + r"\Z")
    for ch in active:
        if escaped:
            part.extend(("\\", ch))
            escaped = False
            dollar = False
            continue
        if ch == "\\":
            escaped = True
            dollar = False
            continue
        if quote is not None:
            part.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            part.append(ch)
            quote = ch
            dollar = False
            continue
        if in_variable:
            # Nginx ${name} expands a variable, not an Nginx block. Only
            # a complete, literal ASCII variable name may consume braces.
            if ch == "}":
                if variable_chars == 0:
                    return False
                in_variable = False
            elif ch.isascii() and (ch.isalnum() or ch == "_"):
                variable_chars += 1
            else:
                return False
            part.append(ch)
            continue
        if ch == "{" and dollar:
            in_variable = True
            variable_chars = 0
            dollar = False
            part.append(ch)
            continue
        if ch in "{};":
            dollar = False
            statement = "".join(part).strip()
            part.clear()
            if ch == "{":
                if not statement:
                    return False
                if not stack:
                    if statement != "server":
                        return False
                    servers += 1
                    stack.append("server")
                else:
                    stack.append("nested")
            elif ch == "}":
                if statement or not stack:
                    return False
                stack.pop()
            else:
                if not statement or not stack:
                    return False
                if exact.fullmatch(statement):
                    if stack != ["server"]:
                        return False
                    matches += 1
            continue
        part.append(ch)
        dollar = ch == "$"
    return (not quote and not escaped and not in_variable and not stack and
            not "".join(part).strip() and servers == 1 and matches == 1)


def _unsupported_nginx_upstream(active_text, *, allow_fastcgi=False):
    """Reject unsupported upstream directives consistently in every dependency."""
    return any(
        name != "fastcgi_pass" or not allow_fastcgi
        for name in NGINX_UPSTREAM_DIRECTIVES.findall(active_text)
    )


def parse_page(value, *, maximum=100000):
    try:
        number = int(str(value))
    except (ValueError, TypeError):
        raise MonitorInputError("Page must be a positive integer") from None
    if not 1 <= number <= maximum:
        raise MonitorInputError("Page is outside the supported range")
    return number


def iter_native_site_rows(panel_public, *, batch_size=NATIVE_SITE_QUERY_BATCH):
    """Iterate a complete ordered native site ID/name table, in bounded pages.

    Page size bounds each query, not the number of supported websites.
    Repeated/out-of-order rows are rejected so a changed database cannot
    silently turn an incomplete inventory into a trusted shared-site map.
    """
    offset, previous = 0, 0
    while True:
        rows = (panel_public.M("sites")
                .order("id asc")
                .limit(f"{offset},{batch_size + 1}")
                .field("id,name")
                .select())
        if not isinstance(rows, list) or len(rows) > batch_size + 1:
            raise MonitorInputError("Native website page unavailable or malformed")
        for row in rows[:batch_size]:
            if not isinstance(row, dict) or not re.fullmatch(r"[0-9]+", str(row.get("id", ""))):
                raise MonitorInputError("Invalid native website identity")
            identity = int(row["id"])
            if identity <= previous or identity > 2147483647:
                raise MonitorInputError("Native website pagination changed or repeated an ID")
            previous = identity
            yield row
        if len(rows) <= batch_size:
            return
        offset += batch_size


def _bound_domains_for_sites(panel_public, sites, *, strict_native=False):
    """Read recorded domain bindings using bounded native query pages.

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
    # Page *domain rows*, not the number of websites or their bindings.
    # Each bounded query stays within the source-reader byte budget, while
    # a site with many valid aliases remains observable.
    batch_size = min(MAX_DOMAIN_ROWS_PER_PAGE,
                     MAX_DOMAIN_TEXT_BYTES_PER_PAGE // MAX_DOMAIN_NAME_BYTES)
    bindings = {site_id: [] for site_id in ids}
    native_ids = {site_id: [] for site_id in ids} if strict_native else None
    seen = set()
    seen_ids = set()
    offset = 0
    last_order = None
    while True:
        result = (
            panel_public.M("domain")
            .where("pid IN (" + placeholders + ")", tuple(ids))
            .order("pid asc, id asc")
            .limit(f"{offset},{batch_size + 1}")
            .field("id,pid,name,port")
            .select()
        )
        if not isinstance(result, list):
            raise RuntimeError("aaPanel domain query did not return a list")
        if len(result) > batch_size + 1:
            raise RuntimeError("aaPanel domain query ignored its bounded page")
        total_name_bytes = 0
        for record in result[:batch_size]:
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
            order = (pid, row_id)
            if last_order is not None and order <= last_order:
                raise RuntimeError("aaPanel domain query changed order during pagination")
            last_order = order
            try:
                name_bytes = len(domain.encode("utf-8"))
            except UnicodeEncodeError:
                raise RuntimeError("aaPanel domain query returned an invalid domain encoding") from None
            if name_bytes > MAX_DOMAIN_NAME_BYTES:
                raise RuntimeError("aaPanel domain name exceeds the read limit")
            total_name_bytes += name_bytes
            if total_name_bytes > MAX_DOMAIN_TEXT_BYTES_PER_PAGE:
                raise RuntimeError("Bound-domain response page exceeds the byte budget")
            identity = (pid, domain, port)
            if identity in seen or row_id in seen_ids:
                raise RuntimeError("aaPanel domain query returned a duplicate binding")
            seen.add(identity)
            seen_ids.add(row_id)
            bindings[pid].append({"name": domain, "port": port})
            if strict_native:
                native_ids[pid].append(row_id)
        if len(result) <= batch_size:
            break
        offset += batch_size
    for site in sites:
        site["bound_domains"] = bindings[site["id"]]
        if strict_native:
            site["_native_domain_row_ids"] = native_ids[site["id"]]
        site["canonical_domain_bound"] = any(
            binding["name"] == site["name"] for binding in site["bound_domains"]
        )


def get_site_page(panel_public, page=1, page_size=25, *, strict_native=False):
    """Read native site/domain records; strict mode validates raw lifecycle data.

    Ordinary Website UI calls retain their existing tolerant presentation
    behavior. A saved lifecycle baseline must never consume coerced omissions.
    """
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
        if strict_native:
            raw_id = site.get("id")
            if (type(raw_id) is int and 1 <= raw_id <= 2147483647):
                pass
            elif (isinstance(raw_id, str) and
                  re.fullmatch(r"[1-9][0-9]{0,9}", raw_id) and
                  int(raw_id) <= 2147483647):
                pass
            else:
                raise RuntimeError("Malformed native site identity for lifecycle baseline")
            if (not isinstance(site.get("path"), str) or
                    not site["path"].strip() or
                    len(site["path"].encode("utf-8")) > 2048):
                raise RuntimeError("Missing or malformed native document root")
            raw_status = site.get("status")
            if (type(raw_status) is int and 0 <= raw_status <= 2147483647):
                pass
            elif (isinstance(raw_status, str) and raw_status.strip() and
                  len(raw_status.encode("utf-8")) <= 64):
                pass
            else:
                raise RuntimeError("Missing or malformed native site status")
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
    _bound_domains_for_sites(panel_public, sites, strict_native=strict_native)
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
    return _parse_pool_text(file_path.read_text(encoding="utf-8"), allowed_include)


def _parse_pool_text(text, allowed_include=None):
    """Apply the same conservative pool parser to trusted recovery bytes."""
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


def _bounded_file_text(path, byte_limit, *, with_fingerprint=False):
    """Read one regular config without following its final symlink."""
    import os
    import stat

    # Anchor every path component with O_NOFOLLOW, not just the leaf file.
    # Otherwise a symlinked ancestor can redirect an apparently trusted
    # Nginx include to a different tree between discovery and inspection.
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise MonitorInputError("Noncanonical Nginx configuration path")
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open("/", dir_flags)
    try:
        for component in path.parts[1:-1]:
            following = os.open(component, dir_flags, dir_fd=directory)
            os.close(directory)
            directory = following
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                     os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or not 0 <= meta.st_size <= byte_limit
                or meta.st_nlink != 1 or meta.st_uid != os.geteuid()
                or meta.st_mode & 0o022):
            raise MonitorInputError("Unsafe or oversized Nginx configuration file")
        before = meta
        content = bytearray()
        while len(content) <= byte_limit:
            chunk = os.read(fd, byte_limit + 1 - len(content))
            if not chunk:
                break
            content.extend(chunk)
        if len(content) > byte_limit:
            raise MonitorInputError("Configuration file exceeds the read limit")
        after = os.fstat(fd)
        tracked = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns",
                   "st_uid", "st_gid", "st_mode", "st_nlink")
        if any(getattr(before, key) != getattr(after, key) for key in tracked):
            raise MonitorInputError("Nginx configuration changed during inspection")
        decoded = content.decode("utf-8")
        if not with_fingerprint:
            return decoded
        identity = {key: getattr(after, key) for key in tracked}
        identity["sha256"] = hashlib.sha256(content).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return decoded, fingerprint
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


def _verified_native_php_include(nginx_dir, name, socket):
    """Bind one known aaPanel PHP snippet and its literal FastCGI parameters.

    The wpfastcgi snippet has additional cache controls and a purge location;
    they do not constitute another PHP upstream. Neither shape may introduce
    a second upstream, a nested routing include, or a different pool socket.
    """
    if not re.fullmatch(r"enable-php-[0-9]{2,3}(?:-wpfastcgi)?\.conf", name):
        raise MonitorInputError("Unsupported native PHP snippet")
    php_include, php_signature = _bounded_file_text(
        nginx_dir / name, MAX_NGINX_SITE_BYTES, with_fingerprint=True,
    )
    active = _active_nginx_text(php_include)
    nested = re.findall(
        r"(?m)^[ \t]*include[ \t]+([^;\s]+)[ \t]*;[ \t]*$", active
    )
    if (len(nested) != len(re.findall(r"\binclude\b", active))
            or len(set(nested)) != len(nested)
            or any(part not in ("fastcgi.conf", "pathinfo.conf") for part in nested)):
        raise MonitorInputError("Unverified Nginx PHP nested include needs review")
    if _unsupported_nginx_upstream(active, allow_fastcgi=True):
        raise MonitorInputError("Unsupported Nginx PHP upstream routing needs review")
    destinations = re.findall(
        r"(?m)^[ \t]*fastcgi_pass[ \t]+unix:([^;\s]+)[ \t]*;[ \t]*$", active
    )
    if (len(re.findall(r"\bfastcgi_pass\b", active)) != 1
            or destinations != [socket]):
        raise MonitorInputError(
            "Nginx PHP include has ambiguous FastCGI destinations or is not mapped to the [www] socket"
        )
    dependencies = [{"kind": "php_include", "name": name, "signature": php_signature}]
    for part in nested:
        content, signature = _bounded_file_text(
            nginx_dir / part, MAX_NGINX_SITE_BYTES, with_fingerprint=True,
        )
        params = _active_nginx_text(content)
        if (re.search(r"\b(?:include|location)\b", params)
                or _unsupported_nginx_upstream(params)):
            raise MonitorInputError("Unsafe Nginx FastCGI parameter include needs review")
        dependencies.append({"kind": "php_params", "name": part, "signature": signature})
    return dependencies


def _verified_owned_status_extension(directory, site_id, site_key, name, text):
    """Accept only the exact status writer's owned Nginx source and journal.

    A managed location is not a generic permission for routing directives.
    Reuse the status writer's canonical generator, on-disk file ownership and
    durable recovery record, including a prepared-but-published operation.
    """
    import os

    from ach_customizer_state import DATA_DIR, StateError, _open_state_dir
    from ach_customizer_status_extension import (
        ExtensionError, PUBLIC_ROOT, _asset_path, _bounded_file,
        _directory, _include, _owned_dir, _record_load,
    )

    code = name.rsplit("_", 1)[-1][:-5]
    if (type(site_id) is not int or not 1 <= site_id <= 2147483647
            or Path(directory).name != site_key or code not in ("404", "502")
            or name != "ach_customizer_" + str(site_id) + "_" + code + ".conf"):
        raise MonitorInputError("Native Status Pages extension identity needs review")
    try:
        state_fd = _open_state_dir(DATA_DIR)
        try:
            record = _record_load(state_fd, site_id, code)
        finally:
            os.close(state_fd)
        if (not record or record["site_name"] != site_key
                or record["phase"] not in ("prepared", "applied")
                or record["asset_path"] != _asset_path(
                    PUBLIC_ROOT, site_id, code, record["after_sha"])):
            raise MonitorInputError("Native Status Pages recovery ownership needs review")
        expected = _include(code, record["asset_path"], record["op"])
        if (record["include_sha"] != hashlib.sha256(expected).hexdigest()
                or text.encode("utf-8") != expected):
            raise MonitorInputError("Native Status Pages extension content needs review")
        extension_fd = _directory(str(directory))
        try:
            _owned_dir(extension_fd)
            if _bounded_file(extension_fd, name, permissions=0o600) != expected:
                raise MonitorInputError("Native Status Pages file identity needs review")
        finally:
            os.close(extension_fd)
    except (ExtensionError, StateError) as exc:
        raise MonitorInputError("Native Status Pages ownership needs review") from exc
    # Its verified operation and source are part of the shared-impact digest.
    # A concurrent journal or file change also invalidates the next scan.
    return record


def _native_unused_subdir(vhost_root, site_key):
    """Verify an optional native aaPanel sub_dir/<site>/*.conf is inactive.

    aaPanel 8.0.7 regeneration adds this wildcard independently of the
    existing per-site Extension include. An absent directory is valid for
    a wildcard, but any *.conf inside it can introduce application routes
    that these adapters have not proven safe. Never follow a directory alias;
    a present tree is checked twice by the existing bounded source scanner.
    """
    import os

    root = Path(vhost_root)
    if (not isinstance(site_key, str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", site_key) or
            not root.is_absolute() or ".." in root.parts or
            str(root) != os.path.normpath(str(root))):
        raise MonitorInputError("Unsupported native subdirectory source identity")
    directory = root / "sub_dir" / site_key
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for index, part in enumerate(directory.parts[1:]):
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if index < len(root.parts) - 1:
                    raise MonitorInputError("Native Nginx source root is missing")
                return None
            os.close(fd)
            fd = child
    except OSError as exc:
        raise MonitorInputError("Native subdirectory source is not a trusted directory") from exc
    finally:
        os.close(fd)

    # No .conf is accepted here, even when it looks inert: this directory
    # is a separate aaPanel routing extension point, not the site_total log.
    return _native_extension_fingerprint(directory, allowed_conf_names=frozenset())


def _native_extension_fingerprint(directory, *, site_id=None, site_key=None,
                                  allowed_conf_names=None, cache_state_dir=None):
    """Read a single native per-site '*.conf' glob without following links.

    Accept inert native logging overlays or the exact verified, plugin-owned
    Status Pages 404/502 source. All other routing remains unresolved. Two
    anchored snapshots include file identities, bytes and recovery ownership.
    The digest is rechecked before an approved FPM Apply/Rollback.
    A scoped caller may restrict the exact live .conf filenames without
    weakening the existing FPM scanner's default accepted sources.
    """
    import os
    import stat

    directory = Path(directory)
    if not directory.is_absolute() or ".." in directory.parts:
        raise MonitorInputError("Noncanonical native extension path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    identities = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                  "st_mtime_ns", "st_ctime_ns", "st_nlink")

    def snapshot():
        fd = os.open("/", flags)
        try:
            for component in directory.parts[1:]:
                following = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = following
            before = os.fstat(fd)
            if (not stat.S_ISDIR(before.st_mode) or before.st_uid != os.geteuid()
                    or before.st_mode & 0o022):
                raise MonitorInputError("Unsafe native extension directory")
            # Count every entry, including non-.conf files, and stop before
            # collecting or sorting an unbounded directory listing.
            with os.scandir(fd) as iterator:
                entries = []
                for entry in iterator:
                    if len(entries) >= CONFIG_FILES_LIMIT:
                        raise MonitorInputError(
                            "Native extension directory exceeds bounded inventory"
                        )
                    entries.append(entry.name)
            entries.sort()
            files = []
            for name in entries:
                if not name.endswith(".conf"):
                    continue
                if allowed_conf_names is not None and name not in allowed_conf_names:
                    raise MonitorInputError("Unexpected native extension source for this operation")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.conf", name):
                    raise MonitorInputError("Unsupported native extension filename")
                text, signature = _bounded_file_text(
                    directory / name, MAX_NGINX_SITE_BYTES, with_fingerprint=True,
                )
                if re.fullmatch(r"ach_customizer_cache_[1-9][0-9]*\.conf", name):
                    # Exactly one site-owned Cache routing source is allowed,
                    # only with its independently persisted prepared/applied
                    # journal and byte-identical generated content. Never
                    # relax the inert-extension rule for foreign routes.
                    from ach_customizer_cache_manage import verified_cache_extension
                    if name != "ach_customizer_cache_" + str(site_id) + ".conf":
                        raise MonitorInputError("Another site's Cache extension requires review")
                    try:
                        journal = verified_cache_extension(
                            directory, site_id, site_key, name, text,
                            state_dir=cache_state_dir)
                    except (ValueError, OSError) as exc:
                        raise MonitorInputError("Native Cache extension ownership needs review") from exc
                    files.append({"name": name, "signature": signature,
                                  "cache_journal": journal})
                elif name.startswith("ach_customizer_"):
                    journal = _verified_owned_status_extension(
                        directory, site_id, site_key, name, text)
                    files.append({"name": name, "signature": signature,
                                  "status_journal": journal})
                else:
                    active = _active_nginx_text(text)
                    for line in active.splitlines():
                        if (line.strip() and not re.fullmatch(
                                r"[ \t]*(?:access_log|error_log)[ \t]+[^;{}\r\n]+;[ \t]*", line)):
                            raise MonitorInputError("Native extension has unverified routing or directives")
                    files.append({"name": name, "signature": signature})
            after = os.fstat(fd)
            if any(getattr(before, field) != getattr(after, field) for field in identities):
                raise MonitorInputError("Native extension changed during inspection")
            # An open directory can remain valid after its pathname was
            # rebound. Reopen the complete path and verify the live identity.
            check_fd = os.open("/", flags)
            try:
                for component in directory.parts[1:]:
                    next_fd = os.open(component, flags, dir_fd=check_fd)
                    os.close(check_fd)
                    check_fd = next_fd
                rebound = os.fstat(check_fd)
                if any(getattr(after, field) != getattr(rebound, field) for field in identities):
                    raise MonitorInputError("Native extension directory path was rebound")
            finally:
                os.close(check_fd)
            identity = {key: getattr(after, key) for key in identities}
            return {"directory": identity, "entries": entries, "files": files}
        finally:
            os.close(fd)

    original = snapshot()
    if original != snapshot():
        raise MonitorInputError("Native extension entries changed during inspection")
    return hashlib.sha256(json.dumps(
        original, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _native_nginx_php_version(vhost_text, *, native_rewrite=None,
                              native_extension=None, native_subdir=None):
    """Accept exact aaPanel PHP/rewrite/extension and optional unused sub_dir."""
    active = _active_nginx_text(vhost_text)
    includes = re.findall(
        r"(?m)^[ \t]*include[ \t]+([^;\s]+)[ \t]*;[ \t]*$", active,
    )
    if (len(includes) != len(re.findall(r"\binclude\b", active))
            or len(set(includes)) != len(includes)
            or _unsupported_nginx_upstream(active)):
        raise MonitorInputError("Unverified Nginx include or upstream routing needs review")
    php = [(match.group(1), name) for name in includes
           if (match := re.fullmatch(
               r"enable-php-([0-9]{2,3})(?:-wpfastcgi)?\.conf", name))]
    if len(php) != 1:
        raise MonitorInputError("No unique native Nginx PHP include")
    extras = [name for name in includes if name != php[0][1]]
    if (len(extras) > 3 or any(
            name not in (native_rewrite, native_extension, native_subdir)
            or name is None for name in extras)):
        raise MonitorInputError("Additional or unverified Nginx include/routing needs review")
    if native_subdir in extras and native_subdir is not None:
        if not _native_server_direct_include(active, native_subdir):
            raise MonitorInputError("Native subdirectory include is not server-scoped")
    return (php[0][0], php[0][1], native_rewrite in extras,
            native_extension in extras, native_subdir in extras)


def inspect_php_fpm_site_impact(panel_public, version, pool_source, *,
                                vhost_root="/www/server/panel/vhost/nginx",
                                nginx_conf_root="/www/server/nginx/conf",
                                rewrite_root="/www/server/panel/vhost/rewrite",
                                other_socket_resolver=None, include_other_sites=False):
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
        # A complete, verified native site/socket inventory can support the
        # separate, explicitly approved PHP 8.5 shared-service manual writer.
        # File attribution never authorizes an action by itself.
        "manual_apply_eligible": False,
        "site_count": 0,
        "other_php_sites_count": 0,
        **({"other_sites": []} if include_other_sites else {}),
        "reason": "",
        "note": ("Verified native Nginx VHost/PHP includes, inert or owned Status Pages site extensions and [www] Unix-socket FILE attribution only; "
                 "not proof of effective routing, PHP worker state, or a complete impact boundary for Apply."),
    }
    try:
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]{2,3}", version):
            raise MonitorInputError("Invalid PHP version for shared impact")
        vhost_dir = Path(vhost_root)
        nginx_dir = Path(nginx_conf_root)
        rewrite_dir = Path(rewrite_root)
        if vhost_dir.is_symlink() or nginx_dir.is_symlink() or rewrite_dir.is_symlink():
            raise MonitorInputError("Linked Nginx configuration directory")
        socket = _single_www_listen(pool_source)
        native_standard = "enable-php-" + version + ".conf"
        dependencies = _verified_native_php_include(nginx_dir, native_standard, socket)
        checked_snippets = {native_standard}
        # Native DB is the authority for website IDs. Refuse partial sets:
        # missing later pages would create an unsafe shared-resource claim.
        seen = set()
        for site in iter_native_site_rows(panel_public):
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
                vhost, vhost_signature = _bounded_file_text(
                    vhost_dir / (name + ".conf"), MAX_NGINX_SITE_BYTES,
                    with_fingerprint=True,
                )
                rewrite = rewrite_dir / (name + ".conf")
                extension = vhost_dir / "extension" / name
                assigned, php_name, has_rewrite, has_extension, has_subdir = _native_nginx_php_version(
                    vhost, native_rewrite=str(rewrite),
                    native_extension=str(extension / "*.conf"),
                    native_subdir=str(vhost_dir / "sub_dir" / name / "*.conf"),
                )
                if has_subdir:
                    dependencies.append({
                        "kind": "native_unused_subdir", "id": site_id,
                        "signature": _native_unused_subdir(vhost_dir, name),
                    })
                if has_rewrite:
                    rewrite_text, rewrite_signature = _bounded_file_text(
                        rewrite, MAX_NGINX_SITE_BYTES, with_fingerprint=True
                    )
                    rewrite_active = _active_nginx_text(rewrite_text)
                    if (re.search(r"\binclude\b", rewrite_active)
                            or _unsupported_nginx_upstream(rewrite_active)):
                        raise MonitorInputError("Unverified Nginx rewrite routing needs review")
                    dependencies.append({"kind": "native_rewrite", "id": site_id,
                                         "signature": rewrite_signature})
                if has_extension:
                    dependencies.append({"kind": "native_extension", "id": site_id,
                                         "signature": _native_extension_fingerprint(
                                             extension, site_id=site_id, site_key=name)})
                if php_name not in checked_snippets:
                    if assigned == "00":
                        if php_name != "enable-php-00.conf":
                            raise MonitorInputError("Unsupported no-PHP Nginx include")
                        disabled, signature = _bounded_file_text(
                            nginx_dir / php_name, MAX_NGINX_SITE_BYTES, with_fingerprint=True
                        )
                        disabled_active = _active_nginx_text(disabled)
                        if (re.search(r"\binclude\b", disabled_active)
                                or NGINX_UPSTREAM_DIRECTIVES.search(disabled_active)):
                            raise MonitorInputError("No-PHP include contains unverified upstream routing")
                        dependencies.append({"kind": "no_php_include", "name": php_name,
                                             "signature": signature})
                    else:
                        # A filename alone is not proof that an 'other PHP'
                        # website cannot also feed the inspected shared pool.
                        # Validate its actual literal native socket as well.
                        expected_socket = socket if assigned == version else (
                            other_socket_resolver(assigned) if other_socket_resolver else
                            "/tmp/php-cgi-" + assigned + ".sock"
                        )
                        if assigned != version and expected_socket == socket:
                            raise MonitorInputError("Another PHP snippet shares this pool socket")
                        dependencies.extend(_verified_native_php_include(
                            nginx_dir, php_name, expected_socket
                        ))
                    checked_snippets.add(php_name)
                dependencies.append({"kind": "vhost", "id": site_id,
                                     "signature": vhost_signature})
            except (OSError, UnicodeError, MonitorInputError):
                result["unresolved_sites"].append({**site_key, "reason": "VHost PHP assignment needs review"})
                continue
            if assigned == version:
                result["matched_sites"].append(site_key)
            else:
                result["other_php_sites_count"] += 1
                if include_other_sites:
                    result["other_sites"].append({
                        **site_key, "version": assigned,
                        "socket_path": None if assigned == "00" else (
                            other_socket_resolver(assigned) if other_socket_resolver else
                            "/tmp/php-cgi-" + assigned + ".sock"
                        ),
                    })
        if result["unresolved_sites"]:
            result["reason"] = "Some website assignments are ambiguous; shared impact is incomplete"
        else:
            # Bind every accepted site VHost and the shared PHP include's
            # bytes+identity to the Apply/Rollback impact precondition.
            result["dependency_sha256"] = hashlib.sha256(json.dumps(
                dependencies, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest()
            result["state"] = "File Mapping"
            # Both native forms are checked: extension/*.conf contains inert logging
            # or an exact owned Status Pages snippet; wpfastcgi has the selected
            # [www] Unix socket with no hidden upstream. Do not reject ordinary
            # aaPanel sites merely for using these validated native features.
            # Only two natively scoped PHP 8.1/8.5 adapters exist. A positive
            # source mapping is necessary, not a replacement for Apply review.
            result["manual_apply_eligible"] = (version in ("81", "85") and bool(result["matched_sites"]))
    except (OSError, UnicodeError, MonitorInputError, ValueError) as exc:
        # A global DB/schema/socket error invalidates *all* partial matches.
        # Only per-site unsupported VHosts keep already proven file links.
        result.update(matched_sites=[], unresolved_sites=[], site_count=0,
                      other_php_sites_count=0, reason=str(exc)[:250])
        if include_other_sites:
            result["other_sites"] = []
    return result
