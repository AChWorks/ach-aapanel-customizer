"""Read-only, version-anchored native PHP-FPM site/file attribution.

A native site has a *file-assigned* PHP version/socket only when the actual
aaPanel FPM main config, canonical Nginx snippet, VHost and safe includes agree.
Do not use these observations to authorize any shared-service Apply/Restore:
neither loaded Nginx configuration nor request routing is established here.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ach_customizer_monitor import (
    MonitorInputError, discover_php_fpm_versions,
    inspect_php_fpm_site_impact, _bounded_file_text, _single_www_listen,
    MAX_CONFIG_BYTES,
)
from ach_customizer_php_runtime import _validated_single_www_layout

VERSION = re.compile(r"[1-9][0-9]{1,2}\Z")
NOTE = (
    "Native site and PHP socket FILE attribution only, from two bounded "
    "source snapshots. Unknown site routes and uninstalled PHP versions "
    "make the impacted set incomplete. Not loaded Nginx routing, a live "
    "PHP request, runtime configuration, or authorization to Apply/Restore."
)


def _service_file_source(config_root, version):
    """Return a pinned single-pool FPM config/socket; reject extra pools/includes.

    The currently validated narrow native layout has one in-file [www] pool.
    This is NOT a parser for all PHP-FPM include/alternate-pool formats.
    """
    path = Path(config_root) / version / "etc" / "php-fpm.conf"
    text, fingerprint = _bounded_file_text(path, MAX_CONFIG_BYTES, with_fingerprint=True)
    _validated_single_www_layout(text)
    socket = _single_www_listen(str(path))
    if len(socket) > 200 or ".." in Path(socket).parts or "//" in socket:
        raise MonitorInputError("Unverifiable PHP-FPM Unix socket pathname")
    if _bounded_file_text(path, MAX_CONFIG_BYTES, with_fingerprint=True)[1] != fingerprint:
        raise MonitorInputError("PHP pool source changed during inspection")
    return str(path), socket, fingerprint


def inspect_php_fpm_site_topology(
    panel_public, config_root, version, *,
    vhost_root="/www/server/panel/vhost/nginx",
    nginx_conf_root="/www/server/nginx/conf",
    rewrite_root="/www/server/panel/vhost/rewrite",
    observed_runtime_socket=None,
):
    """Inspect installed PHP8.1+ service and all bounded native site assignments.

    Keeps older PHP85 Manual Apply impact/approval calls completely unchanged.
    Returned version/socket relationships are read-only, even when complete.
    """
    result = {
        "schema": 1, "state": "Needs Review", "version": version,
        "scope": "shared_service", "read_only": True,
        "runtime_verified": False, "apply_eligible": False,
        "pool": None, "config_path": None, "socket_path": None,
        "site_count": 0, "matched_sites": [], "other_sites": [],
        "unresolved_sites": [], "reason": "", "note": NOTE,
        "source_sha256": None,
    }
    try:
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise MonitorInputError("Unsupported version identifier")
        if (int(version[0]), int(version[1:])) < (8, 1):
            raise MonitorInputError("PHP 8.1+ is required for site topology")
        if panel_public.get_webserver() != "nginx" or str(
                panel_public.get_panel_version()).strip() != "8.0.7":
            raise MonitorInputError("Native Nginx site attribution requires verified aaPanel 8.0.7 layout")
        inventory = discover_php_fpm_versions(config_root)
        observed = {
            item["code"] for item in inventory["versions"] if item["preview_candidate"]
        }
        if version not in observed:
            raise MonitorInputError("Selected PHP version is not a complete native installed candidate")
        sources = {}

        def socket_for(code):
            if code not in observed:
                raise MonitorInputError("Other native site references an uninstalled PHP version")
            if code not in sources:
                sources[code] = _service_file_source(config_root, code)
            return sources[code][1]

        socket = socket_for(version)
        result.update(config_path=sources[version][0], socket_path=socket, pool="www")
        if observed_runtime_socket is not None and (
                not isinstance(observed_runtime_socket, str) or
                observed_runtime_socket != socket):
            raise MonitorInputError("Running master socket source and native file topology differ")

        kwargs = dict(
            vhost_root=vhost_root, nginx_conf_root=nginx_conf_root,
            rewrite_root=rewrite_root,
            other_socket_resolver=socket_for, include_other_sites=True,
        )
        # Two bounded, independent reads detect site creation, deletion,
        # regeneration, file edits, and include/pool replacement during scan.
        first = inspect_php_fpm_site_impact(
            panel_public, version, sources[version][0], **kwargs)
        if first["site_count"] == 0 and first["state"] != "File Mapping":
            raise MonitorInputError(first["reason"] or "Site mapping unavailable")
        second = inspect_php_fpm_site_impact(
            panel_public, version, sources[version][0], **kwargs)
        if first != second:
            raise MonitorInputError("Native website/PHP source changed during site mapping")
        for code, (path, original_socket, fingerprint) in sources.items():
            if (_bounded_file_text(path, MAX_CONFIG_BYTES, with_fingerprint=True)[1]
                    != fingerprint or _single_www_listen(path) != original_socket):
                raise MonitorInputError("Native PHP pool changed while mapping sites")
        current = discover_php_fpm_versions(config_root)
        if current != inventory:
            raise MonitorInputError("Installed PHP inventory changed during site mapping")

        complete = first["state"] == "File Mapping"
        # Tie the source digest to BOTH Nginx include/VHost evidence and all
        # actually referenced versioned FPM config sources. A later PHP
        # config edit must not leave the displayed identity unchanged.
        source = None
        if complete:
            source = hashlib.sha256(json.dumps({
                "nginx_dependencies": first["dependency_sha256"],
                "php_configs": {
                    code: value[2] for code, value in sorted(sources.items())
                },
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        result.update(
            state="File Mapping" if complete else "Partial",
            site_count=first["site_count"], matched_sites=first["matched_sites"],
            other_sites=first["other_sites"],
            unresolved_sites=first["unresolved_sites"],
            source_sha256=source,
            reason=first["reason"],
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, TypeError, AttributeError) as exc:
        # A PHP source or DB change invalidates the *whole* snapshot, not just
        # an arbitrary subset of site IDs. No partial success is asserted.
        result.update(state="Needs Review", site_count=0, matched_sites=[],
                      other_sites=[], unresolved_sites=[], source_sha256=None,
                      reason=str(exc)[:250])
    return result
