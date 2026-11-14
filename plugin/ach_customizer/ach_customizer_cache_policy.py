"""Deterministic, side-effect-free per-site FastCGI cache policy generator.

This generator only renders reviewable Nginx fragments. The separate guarded
native Cache manager owns source checks, physical directories, approval,
reload and recovery; generating a reference never activates caching or
establishes WordPress/WooCommerce safety or Nginx Helper purge compatibility.
"""

import hashlib
import json
import re

class CachePolicyError(ValueError):
    pass


# A separate *physical* directory and keys zone for every managed site is
# required. Merely putting $host in a shared zone's key cannot isolate
# unlink_files/Purge All operating on the shared filesystem directory.
CACHE_ROOT = "/www/server/ach-customizer-fastcgi"
PHP_ADAPTERS = frozenset(("81", "85"))
# Source-pinned aaPanel server-scope HSTS only. Never infer or rewrite policy.
HSTS_DIRECTIVE = re.compile(
    r'add_header[ \t]+Strict-Transport-Security[ \t]+"max-age=[0-9]{1,10}'
    r'(?:; includeSubDomains)?(?:; preload)?"(?:[ \t]+always)?;'
)
NOTE = (
    "Reference config for isolated review only: not installed, not syntax-"
    "checked on this host, not loaded, not an Apply permission or purge API. "
    "A physical per-site directory requires separate ownership and alias "
    "checks before activation; Nginx Helper must not purge an old shared "
    "directory. Unknown plugin routes and actual WooCommerce sessions need "
    "native runtime acceptance."
)


def generate_reference(site_id, php_version, *, cache_root=CACHE_ROOT,
                       cache_generation=None, inherited_hsts=None):
    """Render reviewable http/server fragments with no side effects.

    Only a caller that has independently established a native website, PHP
    include and full administrator privilege should expose the result. The
    overridable root is solely for isolated tests, never a browser argument.
    """
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise CachePolicyError("Invalid native website ID")
    if type(php_version) is not str or php_version not in PHP_ADAPTERS:
        raise CachePolicyError("PHP adapter has no verified FastCGI cache reference")
    if (type(cache_root) is not str or
            not re.fullmatch(r"/[A-Za-z0-9_./-]{2,220}", cache_root) or
            re.search(r"//|/\./|/\.\./|/$", cache_root) or
            cache_root.endswith(("/.", "/.."))):
        raise CachePolicyError("Cache reference root must be a canonical absolute path")

    if cache_generation is not None and (
            type(cache_generation) is not str or
            not re.fullmatch(r"[0-9a-f]{32}", cache_generation)):
        raise CachePolicyError("Invalid cache generation")
    if inherited_hsts is not None and (
            type(inherited_hsts) is not str or
            not HSTS_DIRECTIVE.fullmatch(inherited_hsts)):
        raise CachePolicyError("Unverified native HSTS response header")
    zone = "ACHFC_%d" % site_id
    var = "achfc_%d" % site_id
    directory = "%s/site-%d" % (cache_root, site_id)
    # These maps are site-unique, so multiple independent site references do
    # not redefine an Nginx variable in the common http context.
    http_fragment = (
        "# ach-customizer isolated cache reference site %d (not installed)\n" % site_id
        + "fastcgi_cache_path %s levels=1:2 keys_zone=%s:10m inactive=60m max_size=256m use_temp_path=off;\n" % (directory, zone)
        + "map $upstream_http_cache_control $%s_private_response {\n" % var
        + "    default 0;\n"
        + "    ~*(?:^|[,[:space:]])(?:private|no-cache|no-store|(?:s-)?max-age[[:space:]]*=[[:space:]]*0)(?:$|[,[:space:]]) 1;\n"
        + "}\n"
        + "map $upstream_http_x_accel_expires $%s_expired_response {\n" % var
        + "    default 0;\n"
        + "    ~^[[:space:]]*0[[:space:]]*$ 1;\n"
        + "}\n"
    )
    # Nginx server-level rewrite `set`/`if` is a practical baseline for the
    # conventional aaPanel PHP location. Do not put these guards in an earlier
    # extension include while the native WP snippet resets `$skip_cache` later.
    server_fragment = (
        "# ach-customizer independent PHP handler reference site %d (not installed)\n" % site_id
        + "set $%s_skip 0;\n" % var
        + "if ($request_method !~ ^(GET|HEAD)$) { set $%s_skip 1; }\n" % var
        + "if ($http_authorization != \"\") { set $%s_skip 1; }\n" % var
        + "if ($http_cookie != \"\") { set $%s_skip 1; }\n" % var
        + "if ($args != \"\") { set $%s_skip 1; }\n" % var
        + "if ($http_cache_control ~* \"(?:no-cache|no-store)\") { set $%s_skip 1; }\n" % var
        + "if ($request_uri ~* \"^/(?:wp-admin(?:/|$)|wp-login\\.php(?:/|$)|xmlrpc\\.php(?:/|$)|wp-cron\\.php(?:/|$)|wp-json(?:/|$)|wc-api(?:/|$)|wc-ajax(?:/|$)|(?:cart|checkout|my-account|order-pay|order-received|api|webhook)(?:/|$))\") { set $%s_skip 1; }\n" % var
        # Keep the original-URI route guard (internal redirects can change
        # $uri), but skip all encoded/noncanonical original paths as well.
        # Nginx location routing decodes %XX, compresses adjacent slashes and
        # resolves /./ and /../. These alternate forms must not evade a
        # private-route guard. Query-string hits are already bypassed.
        + r'if ($request_uri ~ "(?:%%|//|/\.\.?(?:/|$))") { set $%s_skip 1; }' % var + "\n"
        + "location ~ [^/]\\.php(/|$) {\n"
        + "    try_files $uri =404;\n"
        + "    fastcgi_pass unix:/tmp/php-cgi-%s.sock;\n" % php_version
        + "    fastcgi_index index.php;\n"
        + "    include fastcgi.conf;\n"
        + "    include pathinfo.conf;\n"
        + "    fastcgi_cache %s;\n" % zone
        # A fresh per-Apply cache key namespace prevents a later Reapply
        # from serving stale objects left by a completed Restore. Keep the
        # physical site-owned tree for forensic recovery and safe retention.
        + '    fastcgi_cache_key "$scheme$request_method$host$request_uri%s";\n' %
          (("|" + cache_generation) if cache_generation is not None else "")
        + "    fastcgi_cache_valid 200 10m;\n"
        # aaPanel 8.0.7 can inherit 'fastcgi_ignore_headers Cache-Control
        # Expires Set-Cookie'. At this location, override that list with only
        # Set-Cookie: normal Nginx caching honors upstream Cache-Control and
        # Expires again, while $upstream_http_set_cookie in fastcgi_no_cache
        # still rejects *every* Set-Cookie response for storage.
        + "    fastcgi_ignore_headers Set-Cookie;\n"
        + "    fastcgi_cache_bypass $%s_skip;\n" % var
        + "    fastcgi_no_cache $%s_skip $upstream_http_set_cookie $upstream_http_vary $upstream_http_www_authenticate $%s_private_response $%s_expired_response;\n" % (var, var, var)
        + "    add_header X-ACh-Cache $upstream_cache_status always;\n"
        + "    add_header X-ACh-Cache-Site %d always;\n" % site_id
        + (("    " + inherited_hsts + "\n") if inherited_hsts else "")
        + "}\n"
    )
    digest = hashlib.sha256(json.dumps(
        [site_id, php_version, http_fragment, server_fragment],
        separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return {
        "schema": 1, "site_id": site_id, "php_version": php_version,
        "state": "Reference Only", "read_only": True,
        "installed": False, "runtime_verified": False,
        "safe_verified": False, "apply_supported": False,
        "purge_supported": False, "cache_directory": directory,
        "cache_zone": zone, "cache_generation": cache_generation,
        "global_http_fragment": http_fragment,
        "site_server_fragment": server_fragment,
        "proposal_sha256": digest, "note": NOTE,
    }
