"""Bounded local HTTP/80 HEAD observations for native WP and default Woo routes.

No real credentials, bodies, redirects, caller-provided URLs, purge or
configuration writes. These headers are not a session or VHost certification.
A defective cache policy may warm an anonymous public entry.
"""
from __future__ import annotations

import http.client
import re
from pathlib import Path

from ach_customizer_cache_policy import CACHE_ROOT
from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _bounded_file_text,
    _native_server_direct_include, MAX_NGINX_SITE_BYTES,
)

_SITE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_PATHS = (("/", "home"), ("/wp-json/", "rest"))
_SCENARIOS = ("authorization", "cookie")
# Common default WooCommerce paths only. A store can change the page slugs;
# never claim discovery or comprehensive privacy coverage from these paths.
_WOO_GUEST_PATHS = (
    ("/cart/", "cart"),
    ("/checkout/", "checkout"),
    ("/my-account/", "account"),
    ("/wp-json/wc/store/v1/cart/", "store-cart"),
    ("/wp-json/wc/store/v1/checkout/", "store-checkout"),
)
_EXPECTED = frozenset(("BYPASS", "HIT", "MISS", "EXPIRED", "STALE", "UPDATING", "REVALIDATED"))


def probe_private_cache(site, source_audit, *, vhost_root="/www/server/panel/vhost/nginx",
                        connection_factory=None, profile="wordpress"):
    """Observe only a registered native site on literal loopback port 80.

    Request headers cannot contain real user credentials. A positive result
    reports native X-Cache or journal-owned X-ACh-Cache headers for four
    fixed HEAD requests; not production HTTPS or real-session privacy.
    WooCommerce mode adds five anonymous *default* route observations.
    """
    if profile not in ("wordpress", "woocommerce_default") or type(profile) is not str:
        raise MonitorInputError("Unsupported fixed Cache diagnostic profile")
    woo = profile == "woocommerce_default"
    name = site.get("name")
    identity = site.get("id")
    result = {
        "schema": 2 if woo else 1, "state": "Unavailable", "site_id": identity,
        "site_key": name, "read_only": True,
        "cache_safe_verified": False, "purge_supported": False,
        "runtime_verified": False, "private_probe_bypass_observed": False,
        "request_method": "HEAD", "origin": "127.0.0.1:80",
        "probes": [], "reason": "",
        "note": ("Local HTTP/80 HEAD default WooCommerce route headers only. "
                 "Page slugs can be customized; no Woo installation, actual GET, "
                 "guest/session privacy, HTTPS edge, responding VHost or safe "
                 "Purge All has been independently verified." if woo else
                 "Synthetic local HTTP/80 HEAD header observations only. "
                 "They do not prove real authenticated sessions, WooCommerce "
                 "anonymous cart/checkout, responding VHost, running HTTPS "
                 "edge, or safe Purge All."),
    }
    if woo:
        result["profile"] = "woocommerce_default"
        result["default_guest_bypass_observed"] = False
    if (type(identity) is not int or not 1 <= identity <= 2147483647
            or not isinstance(name, str) or not _SITE.fullmatch(name)
            or site.get("status") not in (1, "1")
            or not any(domain.get("name") == name and domain.get("port") == 80
                       for domain in site.get("bound_domains", []))):
        raise MonitorInputError("Select a running native HTTP/80 website before probing")
    if (source_audit.get("site_id") != identity or
            source_audit.get("site_key") != name or
            source_audit.get("state") != "Source Observed" or
            source_audit.get("zone_state") != "Direct Zone" or
            source_audit.get("php_version") not in ("81", "85")):
        result["state"] = "Needs Review"
        result["reason"] = "Native FastCGI source audit is incomplete or unsupported"
        return result
    version = source_audit["php_version"]
    path = Path(vhost_root) / (name + ".conf")
    try:
        text, _ = _bounded_file_text(path, MAX_NGINX_SITE_BYTES, with_fingerprint=True)
        active = _active_nginx_text(text)
    except (OSError, UnicodeError, ValueError, MonitorInputError):
        result["state"] = "Needs Review"
        result["reason"] = "Selected native VHost source is not readable or stable"
        return result
    managed = source_audit.get("managed_cache_handler")
    if managed not in (None, "stock", "wpfastcgi"):
        result["state"] = "Needs Review"
        result["reason"] = "Unrecognized managed Cache source identity"
        return result
    if managed is None:
        include = "include enable-php-" + version + "-wpfastcgi.conf;"
        if (len(re.findall(r"\binclude\s+enable-php-[^\s;]+;", active)) != 1 or
                active.count(include) != 1):
            result["state"] = "Unsupported"
            result["reason"] = "Selected site has neither a native wpfastcgi handler nor an applied managed Cache"
            return result
    else:
        # The audit already read the exact owned Extension twice, verifying
        # its bytes against the persistent *applied* Cache recovery journal.
        # Reconcile the selected native VHost's PHP and include precedence;
        # a stock PHP site must never be accepted from a zone name alone.
        expected_zone = "ACHFC_" + str(identity)
        expected_directory = CACHE_ROOT + "/site-" + str(identity)
        native_php = "include enable-php-" + version + (
            "-wpfastcgi" if managed == "wpfastcgi" else "") + ".conf;"
        extension = str(Path(vhost_root) / "extension" / name / "*.conf")
        extension_line = "include " + extension + ";"
        if (source_audit.get("cache_zone") != expected_zone or
                source_audit.get("cache_directory") != expected_directory or
                len(re.findall(r"\binclude\s+enable-php-[^\s;]+;", active)) != 1 or
                active.count(native_php) != 1 or active.count(extension_line) != 1 or
                active.index(extension_line) > active.index(native_php) or
                re.search(r"\blocation\s+~", active[:active.index(extension_line)]) or
                not _native_server_direct_include(active, extension)):
            result["state"] = "Needs Review"
            result["reason"] = "Applied site-owned Cache source or PHP routing changed"
            return result

    connection_factory = connection_factory or (
        lambda: http.client.HTTPConnection("127.0.0.1", 80, timeout=4))
    requests = [
        (path, label, scenario) for path, label in _PATHS
        for scenario in _SCENARIOS
    ]
    if woo:
        requests.extend((path, label, "anonymous") for path, label in _WOO_GUEST_PATHS)
    for path, label, scenario in requests:
        headers = {"Host": name}
        if scenario == "authorization":
            headers["Authorization"] = "Bearer ach-customizer-invalid-synthetic-probe"
        elif scenario == "cookie":
            headers["Cookie"] = "ach_customizer_probe=synthetic"
        try:
            conn = connection_factory()
        except (OSError, http.client.HTTPException):
            result["reason"] = "Origin-local HTTP connection failed"
            break
        try:
            conn.request("HEAD", path, headers=headers)
            reply = conn.getresponse()
            status = reply.status
            if managed is None:
                raw_cache = reply.getheader("X-Cache", "")
            else:
                # Both headers must identify the exact managed selected-site
                # handler. Neither header authenticates a real user/VHost.
                marker = reply.getheader("X-ACh-Cache-Site", "")
                raw_cache = (reply.getheader("X-ACh-Cache", "")
                             if marker == str(identity) else "")
            reply.read(0)
        except (OSError, http.client.HTTPException):
            result["reason"] = "Origin-local HTTP request failed"
            break
        finally:
            conn.close()
        if managed is None:
            match = re.fullmatch(
                r"(BYPASS|HIT|MISS|EXPIRED|STALE|UPDATING|REVALIDATED) From " +
                re.escape(name), raw_cache or "")
            cache = match.group(1) if match else "Not Observed"
        else:
            cache = raw_cache if raw_cache in _EXPECTED else "Not Observed"
        result["probes"].append({
            "path": path, "route": label, "scenario": scenario,
            "http_status": status, "cache": cache,
        })
    if (len(result["probes"]) == len(requests) and
            all(p["http_status"] == 200 and p["cache"] == "BYPASS"
                for p in result["probes"])):
        result["state"] = "Observed BYPASS"
        result["private_probe_bypass_observed"] = True
        if woo:
            result["default_guest_bypass_observed"] = True
    elif any(p["cache"] in _EXPECTED and p["cache"] != "BYPASS"
             and p["http_status"] == 200 for p in result["probes"]):
        result["state"] = "Needs Review"
        result["reason"] = ("A default anonymous WooCommerce path may be cached"
                            if woo and any(p["scenario"] == "anonymous" and
                                           p["http_status"] == 200 and
                                           p["cache"] in _EXPECTED and
                                           p["cache"] != "BYPASS"
                                           for p in result["probes"])
                            else "A synthetic identity-bearing request did not bypass cache")
    else:
        result["state"] = "Unavailable"
        if not result["reason"]:
            result["reason"] = ("Default WooCommerce route did not return HTTP 200 "
                                "with expected cache headers; check customized slugs"
                                if woo else
                                "No complete successful native PHP cache-header observation")
    return result
