"""Bounded native aaPanel FastCGI-cache SOURCE audit; not a cache safety verdict.

Inspect only native registered site VHosts, versioned PHP include snippets, and
direct cache-path declarations in nginx.conf. Nginx's effective inheritance,
map variables, active workers, live response headers, and WordPress purge tools
are not proven. Absolutely no cache purge, host/config write or HTTP request.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path

from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _bounded_file_text,
    _native_nginx_php_version, _native_extension_fingerprint,
    _native_unused_subdir, _native_server_direct_include, _native_local_route_dependencies,
    _unsupported_nginx_upstream, MAX_NGINX_SITE_BYTES,
    iter_native_site_rows,
)

SITE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
ZONE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
DIRECTIVES = (
    "fastcgi_cache", "fastcgi_cache_key", "fastcgi_cache_bypass",
    "fastcgi_no_cache", "fastcgi_ignore_headers", "fastcgi_cache_methods",
    "fastcgi_cache_purge", "fastcgi_cache_path", "fastcgi_cache_valid",
)
NAMES = re.compile(
    # Recognize unmodelled FastCGI cache controls too. A path containing
    # "fastcgi_cache" is not a directive: require a statement boundary.
    r"(?m)(?:^|[;{}])[ \t]*(fastcgi_cache(?:_[A-Za-z_]+)?|"
    r"fastcgi_no_cache|fastcgi_ignore_headers)(?=\s)"
)
ARG_TOKEN = re.compile(r"""[^\s'"\\;{}]+|"[^"\\]*"|'[^'\\]*'""")
LINES = re.compile(
    r"(?m)^[ \t]*(" + "|".join(DIRECTIVES) +
    r")[ \t]+([^;{}\r\n]{1,1024});[ \t]*(?=\r?$)"
)
MAX_FINDINGS = 12
NOTE = (
    "Read-only Nginx file-text clues, not a loaded/effective cache policy. "
    "No proof of private-data caching, user isolation, runtime request "
    "bypass, safe purge scope, or a working cache. The aaPanel Nginx Helper "
    "may also purge shared cache files outside Nginx configuration. "
    "A host token in a cache key does not isolate filesystem-based Purge All."
)


class CacheAuditError(MonitorInputError):
    pass


def _text_and_signature(path):
    source, signature = _bounded_file_text(
        Path(path), MAX_NGINX_SITE_BYTES, with_fingerprint=True)
    return _active_nginx_text(source), signature


def _statements(text):
    """Fail closed on inline, unknown or ambiguous cache statements."""
    found = NAMES.findall(text)
    if any(name not in DIRECTIVES for name in found):
        raise CacheAuditError("Unsupported Nginx FastCGI-cache control requires review")
    rows = LINES.findall(text)
    if len(rows) != len(found):
        raise CacheAuditError("Unsupported/inline Nginx FastCGI-cache statement")
    output = {name: [] for name in DIRECTIVES}
    for name, arguments in rows:
        value = arguments.strip()
        if not value or len(value) > 1024:
            raise CacheAuditError("Malformed Nginx FastCGI-cache directive")
        output[name].append(value)
    return output


def _argument_tokens(arguments):
    """Recognize simple Nginx quoted/unquoted tokens, not arbitrary escapes.

    Escapes and concatenated quote fragments have context-specific Nginx
    semantics; rejecting them is safer than dropping a security-relevant flag.
    """
    result = []
    end = 0
    for match in ARG_TOKEN.finditer(arguments):
        gap = arguments[end:match.start()]
        if gap.strip() or (result and not gap):
            raise CacheAuditError("Ambiguous Nginx FastCGI argument quoting")
        token = match.group()
        if token.startswith(('"', "'")):
            token = token[1:-1]
        if not token or any(char.isspace() for char in token):
            raise CacheAuditError("Unsupported compound Nginx FastCGI argument")
        result.append(token)
        end = match.end()
    if arguments[end:].strip() or not result:
        raise CacheAuditError("Ambiguous Nginx FastCGI argument quoting")
    return result


def _merge_directives(*sources):
    result = {name: [] for name in DIRECTIVES}
    for source in sources:
        parsed = _statements(source)
        for name in DIRECTIVES:
            result[name].extend(parsed[name])
    return result


def _site_source(site_id, site_key, vhost_root, nginx_root, rewrite_root, *, peer=False):
    if not isinstance(site_key, str) or not SITE_KEY.fullmatch(site_key):
        raise CacheAuditError("Unsupported native website VHost key")
    vhost_path = Path(vhost_root) / (site_key + ".conf")
    vhost, vhost_sig = _text_and_signature(vhost_path)
    rewrite = Path(rewrite_root) / (site_key + ".conf")
    extension = Path(vhost_root) / "extension" / site_key
    version, snippet, has_rewrite, has_extension, has_subdir, well_known = _native_nginx_php_version(
        vhost, native_rewrite=str(rewrite),
        native_extension=str(extension / "*.conf"),
        native_subdir=str(Path(vhost_root) / "sub_dir" / site_key / "*.conf"),
        native_well_known=str(Path(vhost_root) / "well-known" / (site_key + ".conf")),
    )
    # Cache Clear's all-site source graph must include native subdirectory
    # routing, even on a peer site, before asserting cache file isolation.
    extra_files = ([("native-unused-subdir", site_key,
                     _native_unused_subdir(vhost_root, site_key))]
                   if has_subdir else [])
    if well_known:
        extra_files.append(("native-ssl-well-known", site_key, well_known))
    snippet_source, snippet_sig = _text_and_signature(Path(nginx_root) / snippet)
    if version == "00":
        # Inert native Static sites must not block an unrelated PHP site's
        # cache audit, but only classify them after reading their real files.
        static_handler = snippet_source.strip()
        if static_handler and not re.fullmatch(
            r"location\s+~\s+\\\.php\$\s*\{\s*return\s+404;\s*\}",
            static_handler,
        ):
            raise CacheAuditError("Static PHP include has unverified routing")
        if any(_statements(vhost).values()):
            raise CacheAuditError("Static VHost has FastCGI-cache controls")
        fingerprints = [
            ("vhost", site_key, vhost_sig),
            ("static-snippet", snippet, snippet_sig),
        ] + extra_files
        if has_rewrite:
            text, sig = _text_and_signature(rewrite)
            if text.strip():
                raise CacheAuditError("Static site rewrite has unverified routing")
            fingerprints.append(("rewrite", site_key, sig))
        if has_extension:
            sig = _native_extension_fingerprint(
                extension, site_id=site_id, site_key=site_key)
            # A site switched from PHP to Static after Cache Apply may still
            # have an active site-owned PHP handler in its extension.
            owned_cache = extension / ("ach_customizer_cache_%d.conf" % site_id)
            if owned_cache.exists() or owned_cache.is_symlink():
                raise CacheAuditError("Static site retains a managed cache handler")
            fingerprints.append(("extension", site_key, sig))
        return _merge_directives(vhost, snippet_source), fingerprints, "00", None
    sources = [vhost, snippet_source]
    managed_wp = False
    managed_cache_handler = None
    managed_php_source = None
    fingerprints = ([("vhost", site_key, vhost_sig),
                     ("php-snippet", snippet, snippet_sig)] + extra_files)
    nested = re.findall(
        r"(?m)^[ \t]*include[ \t]+([^;{}\r\n]+);[ \t]*(?=\r?$)",
        snippet_source,
    )
    tokens = re.findall(
        r"(?m)(?:^|[;{}])[ \t]*include(?=\s)", snippet_source,
    )
    # FastCGI parameter snippets are the only native nested includes that
    # are understood. Read/fingerprint their actual content as well; a
    # second-level include or routing directive must never be silently
    # classified as a harmless PHP parameters source.
    if (len(nested) != len(tokens) or len(nested) > 2 or
            len(set(nested)) != len(nested) or
            any(part not in ("fastcgi.conf", "pathinfo.conf") for part in nested)):
        raise CacheAuditError("PHP snippet has uninspected FastCGI nested includes")
    for part in nested:
        params, params_sig = _text_and_signature(Path(nginx_root) / part)
        if (re.search(r"\b(?:include|location)\b", params)
                or _unsupported_nginx_upstream(params)):
            raise CacheAuditError("FastCGI parameter include has unresolved routing")
        sources.append(params)
        fingerprints.append(("fastcgi-parameters", part, params_sig))
    if has_rewrite:
        text, sig = _text_and_signature(rewrite)
        if re.search(r"\binclude\b", text) or _unsupported_nginx_upstream(text):
            raise CacheAuditError("Native rewrite contains unresolved routing/include")
        sources.append(text)
        fingerprints.append(("rewrite", site_key, sig))
    if has_extension:
        # A selected writer remains strict; an independently registered
        # peer may have a fully inspected, Cache-irrelevant application route.
        owned = extension / ("ach_customizer_cache_%d.conf" % site_id)
        inspect_foreign = None
        if (peer and not owned.exists() and not owned.is_symlink()
                and _native_server_direct_include(vhost, str(extension / "*.conf"))):
            inspect_foreign = lambda active: _native_local_route_dependencies(active, nginx_root)
        sig = _native_extension_fingerprint(
            extension, site_id=site_id, site_key=site_key,
            inspect_foreign=inspect_foreign)
        fingerprints.append(("extension", site_key, sig))
        # The native scanner verified the exact journal-owned Cache source.
        # Audit its real directives too: otherwise a successfully activated
        # site would appear uncached just because its PHP handler is in the
        # extension glob rather than the original versioned PHP include.
        managed_name = "ach_customizer_cache_%d.conf" % site_id
        managed_path = extension / managed_name
        if managed_path.exists() or managed_path.is_symlink():
            managed_raw, managed_sig = _bounded_file_text(
                managed_path, MAX_NGINX_SITE_BYTES, with_fingerprint=True)
            from ach_customizer_cache_manage import verified_cache_extension
            record = verified_cache_extension(
                extension, site_id, site_key, managed_name, managed_raw)
            managed_wp = record.get('native_handler') == 'wpfastcgi'
            # Only a fully Applied, journal/byte-verified owned policy can
            # authorize the managed runtime header diagnostic. A prepared
            # recovery remains source-observable but is not probe-ready.
            managed_cache_handler = (record.get('native_handler', 'stock')
                                     if record.get('phase') == 'applied' else 'pending')
            managed_php_source = _active_nginx_text(managed_raw)
            sources.append(managed_php_source)
            fingerprints.append(("managed-cache-extension", managed_name, managed_sig))
    combined = _merge_directives(*sources)
    if managed_wp:
        from ach_customizer_cache_policy import WP_NATIVE_CANONICAL
        expected = re.sub(r'\s+', ' ',
            WP_NATIVE_CANONICAL.replace('NATIVE_PHP', version)).strip()
        if (version not in ('81', '85') or
                re.sub(r'\s+', ' ', _active_nginx_text(snippet_source)).strip() != expected):
            raise CacheAuditError('Managed WP override native PHP source changed')
        active_vhost = _active_nginx_text(vhost)
        native_ext = str(extension / '*.conf')
        extension_line = 'include ' + native_ext + ';'
        php_line = 'include enable-php-' + version + '-wpfastcgi.conf;'
        if (active_vhost.count(extension_line) != 1 or
                active_vhost.count(php_line) != 1 or
                active_vhost.index(extension_line) > active_vhost.index(php_line) or
                re.search(r'\blocation\s+~',
                    active_vhost[:active_vhost.index(extension_line)]) or
                not _native_server_direct_include(active_vhost, native_ext)):
            raise CacheAuditError('Managed WP Cache location precedence unverified')
        # The owned extension is included before native wpfastcgi. Nginx uses
        # the first matching regex PHP location, so the legacy WORDPRESS PHP
        # handler is shadowed; its distinct /purge location is still active.
        # Count only source-verified managed PHP cache directives for effective
        # zone/path and physical peer-isolation checks, but retain /purge as a
        # diagnostic. Without a journal-authorized extension, report both as
        # ambiguous rather than claiming override or safe Cache Clear.
        effective = _merge_directives(vhost, managed_php_source)
        for directive in DIRECTIVES:
            if directive != 'fastcgi_cache_purge':
                combined[directive] = effective[directive]
    return combined, fingerprints, version, managed_cache_handler


def _native_sites(panel_public):
    sites = []
    seen = set()
    for row in iter_native_site_rows(panel_public):
        if not isinstance(row, dict) or not re.fullmatch("[0-9]+", str(row.get("id", ""))):
            raise CacheAuditError("Invalid native site list")
        identity = int(row["id"])
        if identity < 1 or identity > 2147483647 or identity in seen:
            raise CacheAuditError("Duplicate or invalid native website ID")
        if not isinstance(row.get("name"), str) or len(row["name"]) > 255:
            raise CacheAuditError("Malformed native website key")
        sites.append((identity, row["name"]))
        seen.add(identity)
    return sites


def _cache_zone(directives):
    cache = directives["fastcgi_cache"]
    if not cache:
        return "No Direct Directive", None
    if len(cache) != 1:
        raise CacheAuditError("Multiple FastCGI cache directives require Nginx scope inspection")
    if cache[0] == "off":
        return "Direct Off", None
    if not ZONE.fullmatch(cache[0]):
        raise CacheAuditError("Variable/nonliteral cache zone requires Nginx scope inspection")
    return "Direct Zone", cache[0]


def _direct_http_scope_at(source, offset):
    """Recognize only direct http { ... } membership for one include.

    Braces inside quoted Nginx arguments/escaped tokens are not block
    delimiters. This only tracks lexical scope; it does not evaluate the
    complete Nginx configuration or arbitrary include expansion.
    """
    blocks = []
    start = 0
    quote = None
    escaped = False
    for position, char in enumerate(source[:offset]):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "{":
            heading = source[start:position].strip()
            blocks.append("http" if not blocks and heading == "http" else "other")
            start = position + 1
        elif char == "}":
            if not blocks:
                return False
            blocks.pop()
            start = position + 1
        elif char == ";":
            start = position + 1
    return quote is None and not escaped and blocks == ["http"]


# A deliberately narrow contract for the aaPanel 8.0.7 global cache file:
# every active statement must match one of these complete single-line forms.
GLOBAL_CACHE_STATEMENT = re.compile(
    r"(?m)^[ \t]*(fastcgi_cache_key|fastcgi_cache_path|"
    r"fastcgi_cache_use_stale|fastcgi_ignore_headers)[ \t]+"
    r"([^;{}\r\n]{1,1024});[ \t]*(?=\r?$)"
)
SUPPORTED_STALE_OPTIONS = frozenset({
    "off", "error", "timeout", "invalid_header", "updating",
    "http_500", "http_503", "http_403", "http_404", "http_429",
})


def _known_global_statements(source):
    """Reject every unmodelled active directive, including nested includes."""
    matched = list(GLOBAL_CACHE_STATEMENT.finditer(source))
    if GLOBAL_CACHE_STATEMENT.sub("", source).strip():
        raise CacheAuditError("Uninspected directive in aaPanel global cache file")
    parsed = {name: [] for name in DIRECTIVES}
    for match in matched:
        name, arguments = match.group(1), match.group(2).strip()
        tokens = _argument_tokens(arguments)
        if name == "fastcgi_cache_use_stale":
            if (len(tokens) != len(set(tokens))
                    or any(option not in SUPPORTED_STALE_OPTIONS for option in tokens)
                    or ("off" in tokens and len(tokens) != 1)):
                raise CacheAuditError("Unsupported global fastcgi_cache_use_stale option")
        else:
            parsed[name].append(arguments)
    return parsed


def _known_global_cache(nginx_root, vhost_root):
    """Inspect direct main directives and aaPanel's one known top-level cache include.

    Unlike Nginx -T, this is a bounded *source* observation, never a claim
    about loaded workers, full inheritance or arbitrary included files.
    """
    main_source, main_sig = _text_and_signature(Path(nginx_root) / "nginx.conf")
    main = _statements(main_source)
    sources = [("nginx.conf", "main", main_sig)]
    cache_file = Path(vhost_root) / "0.fastcgi_cache.conf"
    extra = None
    if cache_file.exists() or cache_file.is_symlink():
        marker = re.compile(
            r"(?m)^[ \t]*include[ \t]+" +
            re.escape(str(Path(vhost_root))) +
            r"/\*\.conf[ \t]*;[ \t]*(?=\r?$)"
        )
        matches = list(marker.finditer(main_source))
        if (len(matches) != 1 or
                not _direct_http_scope_at(main_source, matches[0].start())):
            raise CacheAuditError(
                "aaPanel global FastCGI cache file has unverified Nginx include HTTP scope"
            )
        cache_text, cache_sig = _text_and_signature(cache_file)
        extra = _known_global_statements(cache_text)
        sources.append(("aaPanel-cache-global", cache_file.name, cache_sig))
    # Accept only the EXACT journal-owned global Cache fragments in the
    # native aaPanel VHost http{} glob; a forged file or a deleted journal
    # must never be treated as a trusted alternate cache zone.
    managed = []
    try:
        entries = list(Path(vhost_root).iterdir())
    except OSError as exc:
        raise CacheAuditError("Cannot enumerate native Nginx global sources") from exc
    for entry in entries:
        if (not entry.name.startswith("0.ach_customizer_cache_")
                or not entry.name.endswith(".conf")):
            continue
        match = re.fullmatch(r"0\.ach_customizer_cache_([1-9][0-9]*)\.conf", entry.name)
        if match is None or len(match.group(1)) > 10:
            raise CacheAuditError("Unknown ACh global Cache source requires review")
        site_id = int(match.group(1))
        try:
            from ach_customizer_cache_manage import verified_cache_global
            from ach_customizer_cache_policy import generate_reference
            journal = verified_cache_global(str(vhost_root), site_id, entry.name)
            reference = generate_reference(site_id, journal["php_version"])
            managed.append(("ACh managed", {
                "fastcgi_cache_path": [line[len("fastcgi_cache_path "):-1]
                    for line in reference["global_http_fragment"].splitlines()
                    if line.startswith("fastcgi_cache_path ")],
                "fastcgi_cache": [], "fastcgi_ignore_headers": [],
                "fastcgi_cache_key": [],
            }))
            _, signature = _text_and_signature(entry)
            sources.append(("ACh-cache-global", entry.name, signature))
        except (OSError, ValueError, TypeError) as exc:
            raise CacheAuditError("Unverified ACh global Cache source") from exc
    # Keep the actual source owner for every declared zone. Two cache zones
    # with one filesystem path are NOT two isolated purge domains.
    paths = {}
    direct = set()
    ignored = set()
    cache_keys = []
    for owner, parsed in [("main", main), ("aaPanel include", extra), *managed]:
        if parsed is None:
            continue
        if parsed["fastcgi_cache"]:
            raise CacheAuditError("Unexpected global fastcgi_cache setting requires review")
        for declaration in parsed["fastcgi_cache_path"]:
            tokens = _argument_tokens(declaration)
            names = re.findall(
                r"(?<!\S)keys_zone=([A-Za-z_][A-Za-z0-9_]*):[0-9]+[kKmMgG](?=\s|$)",
                declaration,
            )
            if (len(names) != 1 or not ZONE.fullmatch(names[0])
                    or names[0] in paths or not tokens or
                    not re.fullmatch(r"/[A-Za-z0-9_./-]{1,240}", tokens[0])
                    or "//" in tokens[0]
                    or posixpath.normpath(tokens[0]) != tokens[0]):
                # Refuse /./, trailing /, /../, and duplicate separators:
                # they cannot create a false "no peer" from equivalent text.
                raise CacheAuditError("Ambiguous global FastCGI cache zone or directory")
            paths[names[0]] = (tokens[0], owner)
            if owner == "main":
                direct.add(names[0])
        for entry in parsed["fastcgi_ignore_headers"]:
            ignored.update(
                name for field in _argument_tokens(entry)
                for name in ("Cache-Control", "Expires", "Set-Cookie", "Vary", "X-Accel-Expires")
                if field.lower() == name.lower()
            )
        cache_keys.extend(parsed["fastcgi_cache_key"])
    if len(cache_keys) > 1:
        raise CacheAuditError("Multiple global FastCGI cache-key sources require review")
    return {
        "paths": paths, "direct_zones": direct,
        "ignored": sorted(ignored), "global_key": cache_keys[0] if cache_keys else None,
        "include_observed": extra is not None, "signatures": sources,
    }


def _analyze_selected(directives, zone_state, zone, globals_, peers, directory_peers):
    findings = []
    def add(name):
        if name not in findings and len(findings) < MAX_FINDINGS:
            findings.append(name)

    active = zone_state == "Direct Zone"
    # A source-only scan cannot infer Nginx location/server precedence.
    # Even two literal keys with identical values may apply at different
    # scopes; never combine them into one favorable host-partition signal.
    if len(directives["fastcgi_cache_key"]) > 1:
        raise CacheAuditError("Multiple FastCGI cache-key scopes require review")
    if active:
        if not directives["fastcgi_cache_bypass"]:
            add("NO_DIRECT_CACHE_BYPASS")
        if not directives["fastcgi_no_cache"]:
            add("NO_DIRECT_CACHE_WRITE_GUARD")
        if not directives["fastcgi_cache_key"]:
            add("KEY_NOT_DIRECTLY_OBSERVED")
        key = (directives["fastcgi_cache_key"][0]
               if directives["fastcgi_cache_key"] else globals_["global_key"])
        if not key or not re.search(r"\$(?:host|http_host|server_name)(?![A-Za-z0-9_])", key):
            add("HOST_PARTITION_NOT_OBSERVED")
        if zone not in globals_["paths"]:
            add("ZONE_DECLARATION_NOT_IN_MAIN_FILE")
        if peers:
            add("SHARED_ZONE_REFERENCES")
        if directory_peers:
            add("SHARED_CACHE_DIRECTORY_PURGE_RISK")
        if globals_["ignored"]:
            add("GLOBAL_RESPONSE_CACHE_HEADER_IGNORED")
    recognized_headers = {
        "set-cookie": "Set-Cookie", "cache-control": "Cache-Control",
        "expires": "Expires", "vary": "Vary",
        "x-accel-expires": "X-Accel-Expires",
    }
    direct_ignored = {
        recognized_headers[field.lower()] for entry in directives["fastcgi_ignore_headers"]
        for field in _argument_tokens(entry) if field.lower() in recognized_headers
    }
    # Lower-level directives may override inheritance. Both remain warnings
    # rather than an assertion about Nginx's effective/loaded value.
    ignored = direct_ignored | (set(globals_["ignored"]) if active else set())
    methods = [_argument_tokens(entry) for entry in directives["fastcgi_cache_methods"]]
    if active and ignored:
        add("RESPONSE_CACHE_HEADER_IGNORED")
    if active and any(token.upper() == "POST" for entry in methods for token in entry):
        add("NON_GET_CACHE_METHOD")
    if directives["fastcgi_cache_purge"]:
        add("PURGE_DIRECTIVE_OBSERVED")
    # Presence of both guards or a host variable does NOT establish that
    # the expressions actually protect private sessions, users or routes.
    if active:
        add("PRIVATE_ROUTE_RUNTIME_TEST_REQUIRED")
    return findings, sorted(ignored)


def inspect_site_fastcgi_cache(panel_public, site_id, site_key, *,
                               vhost_root="/www/server/panel/vhost/nginx",
                               nginx_root="/www/server/nginx/conf",
                               rewrite_root="/www/server/panel/vhost/rewrite",
                               include_physical_peers=False):
    """Read registered native site text twice, reporting bounded clues only.

    The optional peer-directory inventory is internal to guarded Cache Clear:
    it exposes the native zone-to-path mapping for filesystem verification,
    without making source-only purge_scope a destructive authorization.
    """
    result = {
        "schema": 1, "state": "Needs Review", "site_id": site_id,
        "site_key": site_key, "read_only": True,
        "runtime_verified": False, "cache_safe_verified": False,
        "purge_supported": False, "fix_supported": False,
        "zone_state": "Needs Review", "cache_zone": None,
        "php_version": None, "managed_cache_handler": None,
        "global_zone_directly_declared": False,
        "aaPanel_global_include_observed": False,
        "global_ignore_headers": [], "cache_directory": None,
        "other_sites_same_directory": [], "purge_scope": "Unknown",
        "bypass_directive_seen": False, "no_cache_directive_seen": False,
        "host_key_variable_seen": False, "purge_directive_seen": False,
        "ignore_headers": [], "findings": [],
        "other_sites_same_zone": [], "unresolved_other_sites": 0,
        "inspected_sites": 0, "source_sha256": None,
        "reason": "", "note": NOTE,
    }
    try:
        if (type(site_id) is not int or not 1 <= site_id <= 2147483647 or
                not isinstance(site_key, str) or not SITE_KEY.fullmatch(site_key)):
            raise CacheAuditError("Invalid selected native site")
        if panel_public.get_webserver() != "nginx":
            raise CacheAuditError("Native Nginx webserver is required for source audit")
        panel_version = str(panel_public.get_panel_version()).strip()

        def scan():
            sites = _native_sites(panel_public)
            if (site_id, site_key) not in sites:
                raise CacheAuditError("Selected native site identity has changed")
            globals_ = _known_global_cache(nginx_root, vhost_root)
            selected_directives, selected_files, version, managed_handler = _site_source(
                site_id, site_key, vhost_root, nginx_root, rewrite_root)
            zone_state, zone = _cache_zone(selected_directives)
            peers = []
            directory_peers = []
            different_directory_peer = False
            physical_peer_paths = []
            unresolved = 0
            first_unresolved = ""
            selected_directory = (
                globals_["paths"].get(zone, (None, None))[0]
                if zone is not None else None
            )
            fingerprints = globals_["signatures"] + selected_files
            for ident, key in sites:
                if ident == site_id:
                    continue
                try:
                    peer_directives, files, _, _ = _site_source(
                        ident, key, vhost_root, nginx_root, rewrite_root, peer=True)
                    _, peer_zone = _cache_zone(peer_directives)
                except (CacheAuditError, MonitorInputError, OSError, UnicodeError, ValueError) as exc:
                    unresolved += 1
                    if not first_unresolved:
                        detail = str(exc) if isinstance(exc, MonitorInputError) else type(exc).__name__
                        first_unresolved = key + ": " + detail
                    continue
                fingerprints.extend(files)
                if zone is not None and peer_zone == zone:
                    peers.append({"id": ident, "site_key": key})
                peer_directory = (globals_["paths"].get(peer_zone, (None, None))[0]
                                  if peer_zone is not None else None)
                if peer_zone is not None:
                    # A referenced but undeclared zone also needs resolution
                    # before a filesystem-deleting operation can be approved.
                    physical_peer_paths.append((ident, peer_directory))
                if selected_directory is not None and peer_directory is not None:
                    if peer_directory == selected_directory:
                        directory_peers.append({"id": ident, "site_key": key})
                    else:
                        # Distinct canonical strings may still alias via symlinks
                        # or mounts. Source-only diagnostics cannot certify that
                        # they are separate physical directories.
                        different_directory_peer = True
            return (sites, globals_, selected_directives, version, managed_handler, zone_state,
                    zone, peers, directory_peers, different_directory_peer,
                    physical_peer_paths, unresolved, fingerprints, first_unresolved)

        first = scan()
        if first != scan():
            raise CacheAuditError("Nginx/native website sources changed during cache audit")
        if (panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != panel_version):
            raise CacheAuditError("Native web engine or panel version changed during audit")
        (sites, globals_, directives, php_version, managed_handler, zone_state, zone, peers,
         directory_peers, different_directory_peer, physical_peer_paths,
         unresolved, fingerprints, first_unresolved) = first
        findings, ignored = _analyze_selected(
            directives, zone_state, zone, globals_, peers, directory_peers)
        observed_key = (directives["fastcgi_cache_key"][0]
                        if directives["fastcgi_cache_key"] else globals_["global_key"])
        host_seen = bool(observed_key and re.search(
            r"\$(?:host|http_host|server_name)(?![A-Za-z0-9_])", observed_key))
        selected_directory = (globals_["paths"].get(zone, (None, None))[0]
                              if zone is not None else None)
        source_sha = hashlib.sha256(json.dumps(
            {"sites": sites, "source": fingerprints}, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        if include_physical_peers is True:
            # Not part of the regular public source-audit response. All peer
            # paths come from the same twice-verified native inventory.
            result["physical_peer_cache_paths"] = [
                {"id": ident, "directory": path}
                for ident, path in physical_peer_paths
            ]
        result.update(
            state="Partial" if unresolved else "Source Observed",
            zone_state=zone_state, cache_zone=zone, php_version=php_version,
            managed_cache_handler=managed_handler,
            global_zone_directly_declared=zone is not None and
                zone in globals_["direct_zones"],
            aaPanel_global_include_observed=globals_["include_observed"],
            global_ignore_headers=globals_["ignored"],
            cache_directory=selected_directory,
            other_sites_same_directory=directory_peers,
            purge_scope=("Shared Registered Directory" if directory_peers else
                         "No Registered Directory Peer" if selected_directory and
                             not unresolved and not different_directory_peer
                         else "Unknown"),
            bypass_directive_seen=bool(directives["fastcgi_cache_bypass"]),
            no_cache_directive_seen=bool(directives["fastcgi_no_cache"]),
            host_key_variable_seen=bool(host_seen),
            purge_directive_seen=bool(directives["fastcgi_cache_purge"]),
            ignore_headers=ignored, findings=findings,
            other_sites_same_zone=peers, unresolved_other_sites=unresolved,
            inspected_sites=len(sites), source_sha256=source_sha,
            reason=(("Peer Cache source incomplete (%d); %s" % (unresolved, first_unresolved))[:250]
                    if unresolved else ""),
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, TypeError) as exc:
        result["reason"] = str(exc)[:250]
    return result
