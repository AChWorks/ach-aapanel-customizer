"""Bounded native aaPanel FastCGI-cache SOURCE audit; not a cache safety verdict.

Inspect only native registered site VHosts, versioned PHP include snippets, and
direct cache-path declarations in nginx.conf. Nginx's effective inheritance,
map variables, active workers, live response headers, and WordPress purge tools
are not proven. Absolutely no cache purge, host/config write or HTTP request.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _bounded_file_text,
    _native_nginx_php_version, _native_extension_fingerprint,
    _unsupported_nginx_upstream, MAX_NGINX_SITE_BYTES,
    PHP_IMPACT_SITE_LIMIT,
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
    "may also purge shared cache files outside Nginx configuration."
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


def _site_source(site_key, vhost_root, nginx_root, rewrite_root):
    if not isinstance(site_key, str) or not SITE_KEY.fullmatch(site_key):
        raise CacheAuditError("Unsupported native website VHost key")
    vhost_path = Path(vhost_root) / (site_key + ".conf")
    vhost, vhost_sig = _text_and_signature(vhost_path)
    rewrite = Path(rewrite_root) / (site_key + ".conf")
    extension = Path(vhost_root) / "extension" / site_key
    version, snippet, has_rewrite, has_extension = _native_nginx_php_version(
        vhost, native_rewrite=str(rewrite),
        native_extension=str(extension / "*.conf"),
    )
    # Pure static / no-PHP sites are returned as unverified cache consumers;
    # inherited HTTP/server cache directives are not modelled here.
    if version == "00":
        raise CacheAuditError("No supported native FastCGI PHP site include")
    snippet_source, snippet_sig = _text_and_signature(Path(nginx_root) / snippet)
    sources = [vhost, snippet_source]
    fingerprints = [("vhost", site_key, vhost_sig),
                    ("php-snippet", snippet, snippet_sig)]
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
        sig = _native_extension_fingerprint(extension)
        fingerprints.append(("extension", site_key, sig))
    return _merge_directives(*sources), fingerprints, version


def _native_sites(panel_public):
    rows = (panel_public.M("sites").order("id asc")
            .limit("0," + str(PHP_IMPACT_SITE_LIMIT + 1))
            .field("id,name").select())
    if not isinstance(rows, list) or len(rows) > PHP_IMPACT_SITE_LIMIT:
        raise CacheAuditError("Native website list unavailable or exceeds 100 sites")
    sites = []
    seen = set()
    for row in rows:
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


def _global_zones(source):
    parsed = _statements(source)
    names = []
    for declaration in parsed["fastcgi_cache_path"]:
        zones = re.findall(r"(?<!\S)keys_zone=([A-Za-z_][A-Za-z0-9_]*):[0-9]+[kKmMgG](?=\s|$)",
                           declaration)
        if len(zones) != 1 or not ZONE.fullmatch(zones[0]) or zones[0] in names:
            raise CacheAuditError("Ambiguous Nginx FastCGI cache-path zone declaration")
        names.append(zones[0])
    return names


def _analyze_selected(directives, zone_state, zone, global_zones, peers):
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
        else:
            key = directives["fastcgi_cache_key"][0]
            if not re.search(r"\$(?:host|http_host|server_name)(?![A-Za-z0-9_])", key):
                add("HOST_PARTITION_NOT_OBSERVED")
        if zone not in global_zones:
            add("ZONE_DECLARATION_NOT_IN_MAIN_FILE")
        if peers:
            add("SHARED_ZONE_REFERENCES")
    recognized_headers = {
        "set-cookie": "Set-Cookie", "cache-control": "Cache-Control",
        "expires": "Expires", "vary": "Vary",
        "x-accel-expires": "X-Accel-Expires",
    }
    ignored = {
        recognized_headers[field.lower()] for entry in directives["fastcgi_ignore_headers"]
        for field in _argument_tokens(entry) if field.lower() in recognized_headers
    }
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
                               rewrite_root="/www/server/panel/vhost/rewrite"):
    """Read registered native site text twice, reporting bounded clues only."""
    result = {
        "schema": 1, "state": "Needs Review", "site_id": site_id,
        "site_key": site_key, "read_only": True,
        "runtime_verified": False, "cache_safe_verified": False,
        "purge_supported": False, "fix_supported": False,
        "zone_state": "Needs Review", "cache_zone": None,
        "global_zone_directly_declared": False,
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
        if (panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != "8.0.7"):
            raise CacheAuditError("Only verified aaPanel 8.0.7 Nginx source layout can be inspected")

        def scan():
            sites = _native_sites(panel_public)
            if (site_id, site_key) not in sites:
                raise CacheAuditError("Selected native site identity has changed")
            global_text, global_sig = _text_and_signature(
                Path(nginx_root) / "nginx.conf")
            global_zones = _global_zones(global_text)
            selected_directives, selected_files, _ = _site_source(
                site_key, vhost_root, nginx_root, rewrite_root)
            zone_state, zone = _cache_zone(selected_directives)
            peers = []
            unresolved = 0
            fingerprints = [("nginx.conf", "global", global_sig)] + selected_files
            for ident, key in sites:
                if ident == site_id:
                    continue
                try:
                    peer_directives, files, _ = _site_source(
                        key, vhost_root, nginx_root, rewrite_root)
                    _, peer_zone = _cache_zone(peer_directives)
                except (CacheAuditError, MonitorInputError, OSError, UnicodeError, ValueError):
                    unresolved += 1
                    continue
                fingerprints.extend(files)
                if zone is not None and peer_zone == zone:
                    peers.append({"id": ident, "site_key": key})
            return (sites, global_zones, selected_directives, zone_state,
                    zone, peers, unresolved, fingerprints)

        first = scan()
        if first != scan():
            raise CacheAuditError("Nginx/native website sources changed during cache audit")
        if (panel_public.get_webserver() != "nginx" or
                str(panel_public.get_panel_version()).strip() != "8.0.7"):
            raise CacheAuditError("Native web engine or panel version changed during audit")
        sites, globals_, directives, zone_state, zone, peers, unresolved, fingerprints = first
        findings, ignored = _analyze_selected(directives, zone_state, zone, globals_, peers)
        host_seen = any(re.search(
            r"\$(?:host|http_host|server_name)(?![A-Za-z0-9_])", value)
            for value in directives["fastcgi_cache_key"])
        source_sha = hashlib.sha256(json.dumps(
            {"sites": sites, "source": fingerprints}, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        result.update(
            state="Partial" if unresolved else "Source Observed",
            zone_state=zone_state, cache_zone=zone,
            global_zone_directly_declared=zone is not None and zone in globals_,
            bypass_directive_seen=bool(directives["fastcgi_cache_bypass"]),
            no_cache_directive_seen=bool(directives["fastcgi_no_cache"]),
            host_key_variable_seen=bool(host_seen),
            purge_directive_seen=bool(directives["fastcgi_cache_purge"]),
            ignore_headers=ignored, findings=findings,
            other_sites_same_zone=peers, unresolved_other_sites=unresolved,
            inspected_sites=len(sites), source_sha256=source_sha,
            reason=("Some native websites have uninspected cache source; "
                    "shared-zone use may be incomplete" if unresolved else ""),
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, TypeError) as exc:
        result["reason"] = str(exc)[:250]
    return result
