"""One-time, recoverable WordPress home/siteurl HTTP -> HTTPS correction.

The administrator explicitly triggers this selected-site database update. No
watcher, WP-CLI dependency, DNS, Nginx or certificate mutation. WordPress
itself performs the writes as the site's normal www user; a small journal
permits recovery after a partial update, without adopting foreign changes.
"""
from __future__ import annotations

import json
import os
import subprocess
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from ach_customizer_cache_wordpress import _read_file
from ach_customizer_status_extension import _bounded_file, _owned_dir, _write_exclusive
from ach_customizer_wp_settings import (
    WPSettingsError, _site_source, _sha, TOKEN,
)

SCHEMA = 1
KEYS = ("home", "siteurl")
PREFIX = "ACH_WP_URL_RESULT="
MAX_RECORD = 8192
PHP = r"""
$input = json_decode(stream_get_contents(STDIN), true);
if (!is_array($input) || !in_array($input['action'] ?? null, ['inspect', 'set'], true)) {
    fwrite(STDERR, "Invalid WordPress URL operation\n"); exit(10);
}
// Native site-user CLI, not an authenticated HTTP admin request.
$ach_url_phase = 'bootstrap';
$ach_url_finished = false;
register_shutdown_function(static function () use (&$ach_url_phase, &$ach_url_finished) {
    if (!$ach_url_finished) {
        fwrite(STDERR, "\nACH_WP_URL_PHASE=".$ach_url_phase."\n");
    }
});
require 'wp-load.php';
$ach_url_phase = 'inspect';
if (defined('WP_HOME') || defined('WP_SITEURL')) {
    fwrite(STDERR, "WordPress URL is controlled by WP_HOME/WP_SITEURL constants; update the source manually\n");
    exit(17);
}
if (!function_exists('is_multisite') || is_multisite()) {
    fwrite(STDERR, "WordPress multisite URL changes are not supported by this selected-site action\n");
    exit(11);
}
function ach_wp_urls_snapshot() {
    global $wpdb;
    $values = [];
    foreach (['home', 'siteurl'] as $key) {
        $query = $wpdb->prepare(
            "SELECT option_value FROM {$wpdb->options} WHERE option_name = %s LIMIT 1", $key
        );
        $stored = $wpdb->get_var($query);
        $effective = get_option($key, null);
        // WP_HOME/WP_SITEURL overrides, plugin filters, absent rows and
        // non-string options must not silently masquerade as a DB update.
        if (!is_string($stored) || !is_string($effective) || $stored !== $effective) {
            fwrite(STDERR, "WordPress URL value is overridden, filtered or missing: " . $key . "\n");
            exit(12);
        }
        $values[$key] = $stored;
    }
    return $values;
}
$values = ach_wp_urls_snapshot();
if ($input['action'] === 'set') {
    $ach_url_phase = 'set';
    $before = $input['before'] ?? null;
    $after = $input['after'] ?? null;
    if (!is_array($before) || !is_array($after) ||
        array_keys($before) !== ['home', 'siteurl'] ||
        array_keys($after) !== ['home', 'siteurl']) {
        fwrite(STDERR, "Malformed WordPress URL update\n"); exit(13);
    }
    foreach (['home', 'siteurl'] as $key) {
        if (!is_string($before[$key]) || !is_string($after[$key]) ||
            $values[$key] !== $before[$key]) {
            fwrite(STDERR, "WordPress " . $key . " changed before update\n"); exit(14);
        }
    }
    foreach (['home', 'siteurl'] as $key) {
        if ($before[$key] !== $after[$key] && !update_option($key, $after[$key])) {
            fwrite(STDERR, "WordPress failed to update " . $key . "\n"); exit(15);
        }
    }
    $values = ach_wp_urls_snapshot();
    if ($values !== $after) {
        fwrite(STDERR, "WordPress URL update did not persist exact target values\n"); exit(16);
    }
}
$ach_url_phase = 'encode';
echo "\nACH_WP_URL_RESULT=", json_encode($values, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR), "\n";
$ach_url_finished = true;
"""


def _name(site_id):
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise WPSettingsError("identity", "Invalid WordPress URL site identity")
    return "ach_customizer.wp_urls." + str(site_id) + ".json"


def _record_read(fd, site):
    raw = _bounded_file(fd, _name(site["id"]), limit=MAX_RECORD, permissions=0o600)
    if raw is None:
        return None
    try:
        row = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise WPSettingsError("recovery", "WordPress URL recovery journal is unreadable") from exc
    if (not isinstance(row, dict)
            or set(row) != {"schema", "site_id", "site_key", "root", "op",
                            "phase", "config_sha", "php_version", "original", "target"}
            or type(row["schema"]) is not int or row["schema"] != SCHEMA
            or row["site_id"] != site["id"] or row["site_key"] != site["name"]
            or row["root"] != site["path"]
            or not isinstance(row["op"], str) or not TOKEN.fullmatch(row["op"])
            or row["phase"] not in ("prepared", "applied", "restoring", "restored")
            or not isinstance(row["config_sha"], str) or len(row["config_sha"]) != 64
            or any(x not in "0123456789abcdef" for x in row["config_sha"])
            or not isinstance(row["php_version"], str) or not row["php_version"].isdigit()
            or not _valid_values(row["original"]) or not _valid_values(row["target"])):
        raise WPSettingsError("recovery", "Invalid WordPress URL recovery journal or selected site")
    return row


def _record_save(fd, site_id, row):
    payload = (json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise WPSettingsError("recovery", "WordPress URL journal exceeds supported URL size")
    temporary = "." + _name(site_id) + "." + uuid4().hex + ".stage"
    created = False
    try:
        _write_exclusive(fd, temporary, payload, 0o600)
        created = True
        os.replace(temporary, _name(site_id), src_dir_fd=fd, dst_dir_fd=fd)
        created = False
        os.fsync(fd)
    finally:
        if created:
            os.unlink(temporary, dir_fd=fd)


def _valid_values(values):
    return (isinstance(values, dict) and list(values) == list(KEYS)
            and all(isinstance(values[key], str) for key in KEYS))


def _php(site, php, command, *, before=None, after=None, runner=None):
    run = runner or subprocess.run
    try:
        result = run(
            ["runuser", "-u", "www", "--", php, "-d", "display_errors=stderr", "-r", PHP],
            cwd=site["path"],
            input=json.dumps({"action": command, "before": before, "after": after}),
            text=True, capture_output=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WPSettingsError("wordpress", "WordPress URL PHP operation unavailable: "
                              + type(exc).__name__) from exc
    lines = [line[len(PREFIX):] for line in result.stdout.splitlines()
             if line.startswith(PREFIX)]
    data = None
    if len(lines) == 1:
        try:
            data = json.loads(lines[0])
        except (ValueError, UnicodeError):
            pass
    if result.returncode or not _valid_values(data):
        phases = [line[len("ACH_WP_URL_PHASE="):]
                  for line in (result.stderr or "").splitlines()
                  if line.startswith("ACH_WP_URL_PHASE=")]
        phase = (phases[0] if len(phases) == 1 and phases[0] in
                 ("bootstrap", "inspect", "set", "encode") else "unknown phase")
        reasons = {
            10: "Invalid WordPress URL operation",
            11: "WordPress multisite URL changes are not supported",
            12: "WordPress URL value is overridden, filtered or missing",
            13: "Malformed WordPress URL update",
            14: "WordPress URL changed before update",
            15: "WordPress failed to update URL",
            16: "WordPress URL update did not persist exact target values",
            17: "WordPress URL controlled by WP_HOME/WP_SITEURL constants",
        }
        reason = reasons.get(result.returncode, "Missing result marker" if not lines
                             else "Incomplete or invalid result")
        raise WPSettingsError("wordpress", f"WordPress {command} failed during {phase}: "
                              f"{reason} (PHP exit {result.returncode})")

    return data


def _source(site, public):
    raw, php, version = _site_source(
        site, public, vhost_root="/www/server/panel/vhost/nginx")
    try:
        bootstrap, _ = _read_file(site["path"], "wp-load.php")
    except (OSError, ValueError) as exc:
        raise WPSettingsError("source", "Selected native website is missing WordPress bootstrap") from exc
    if not bootstrap.lstrip().startswith(b"<?php"):
        raise WPSettingsError("compatibility", "Selected site has an incompatible WordPress bootstrap")
    return _sha(raw), php, version


def _https(value, site):
    try:
        url = urlsplit(value)
        port = url.port
    except (TypeError, ValueError) as exc:
        raise WPSettingsError("compatibility", "WordPress URL is not a valid HTTP/HTTPS address") from exc
    names = {site["name"].lower()}
    names.update(binding["name"].lower() for binding in site["bound_domains"])
    if (url.scheme not in ("http", "https") or not url.hostname
            or url.hostname.lower() not in names
            or url.username is not None or url.password is not None
            or url.query or url.fragment or any(x in value for x in "\r\n\0")
            or url.path and not url.path.startswith("/")):
        raise WPSettingsError(
            "compatibility", "WordPress URL is outside selected site's native host bindings "
            "or has an unsupported scheme/credential/query; change it manually in WordPress")
    if url.scheme == "https":
        return value
    netloc = url.netloc
    if port == 80:
        netloc = netloc.rsplit(":", 1)[0]
    return urlunsplit(("https", netloc, url.path, "", ""))


def _desired(values, site):
    return {key: _https(values[key], site) for key in KEYS}


def _digest(config_sha, php_version, site, values):
    return _sha(json.dumps([
        site["id"], site["name"], site["path"],
        sorted((b["name"], b["port"]) for b in site["bound_domains"]),
        config_sha, php_version, values,
    ], separators=(",", ":"), sort_keys=True).encode())


def _reply(site, state, source, record, *, changed=False, reason="",
           runtime_verified=False, current=None, target=None):
    return {
        "schema": SCHEMA, "site_id": site["id"], "site_key": site["name"],
        "kind": "https", "state": state, "source_sha256": source,
        "recovery_id": record["op"] if record else None,
        "changed": changed, "read_only": not changed,
        "runtime_verified": runtime_verified, "interval": None, "reason": reason,
        "impact": "Selected WordPress home/siteurl database options only; "
                  "converts HTTP to HTTPS, no DNS/Nginx/certificate changes",
        "urls_before": current, "urls_target": target,
    }


def manage_urls(action, site, public, *, data_fd,
                expected_source=None, expected_recovery=None, runner=None):
    """Caller owns primary-admin auth, site lock, state lock and native identity."""
    if action not in ("recheck", "apply", "restore"):
        raise WPSettingsError("input", "Unsupported WordPress URL action")
    _owned_dir(data_fd)
    config_sha, php, version = _source(site, public)
    record = _record_read(data_fd, site)
    current = _php(site, php, "inspect", runner=runner)
    source = _digest(config_sha, version, site, current)
    # URL ownership is the database option pair, not a particular unrelated
    # wp-config.php line or PHP binary version. A Debug/Cron change or native
    # PHP upgrade must not make this independent URL Restore impossible.
    # Recheck still binds every request to the *current* WordPress source,
    # selected native site and effective, unfiltered database values.
    if action == "recheck":
        if record is None:
            desired = _desired(current, site)
            state = "Already Configured" if desired == current else "Source Ready"
            reason = "" if state == "Source Ready" else "WordPress URLs already use HTTPS"
        elif record["phase"] == "restored":
            desired = _desired(current, site)
            if current == record["original"]:
                state, reason = "Restored", ""
            else:
                state = "Source Ready" if desired != current else "Already Configured"
                reason = ("Previous URL correction was restored; inspect current "
                          "WordPress URLs before a new one-time change")
        elif record["phase"] == "applied" and current == record["target"]:
            state, reason, desired = "Applied", "", record["target"]
        else:
            state, reason, desired = ("Recovery Required",
                "Prepared, interrupted or changed URL options need exact Restore",
                record["target"])
        return _reply(site, state, source, record, current=current, target=desired,
                      reason=reason, runtime_verified=state in ("Applied", "Restored"))
    if expected_source != source:
        raise WPSettingsError("concurrency", "WordPress URLs changed after Recheck; inspect again")
    if action == "apply":
        if record and record["phase"] != "restored":
            raise WPSettingsError("recovery", "A previous WordPress URL operation needs Restore first",
                                  record["op"])
        target = _desired(current, site)
        if target == current:
            raise WPSettingsError("input", "WordPress URLs are already HTTPS; no Apply needed")
        row = {
            "schema": SCHEMA, "site_id": site["id"], "site_key": site["name"],
            "root": site["path"], "op": uuid4().hex, "phase": "prepared",
            "config_sha": config_sha, "php_version": version,
            "original": current, "target": target,
        }
        _record_save(data_fd, site["id"], row)
        try:
            _php(site, php, "set", before=current, after=target, runner=runner)
            confirmed = _php(site, php, "inspect", runner=runner)
            if confirmed != target:
                raise WPSettingsError("postcheck", "WordPress did not retain HTTPS URL options")
            row["phase"] = "applied"
            _record_save(data_fd, site["id"], row)
        except Exception as exc:
            raise WPSettingsError(
                "uncertain", "WordPress HTTPS update may be partial: " +
                str(exc)[:180] + "; Recheck then Restore the saved Recovery ID",
                row["op"]) from exc
        return _reply(site, "Applied", _digest(config_sha, version, site, target),
                      row, changed=True, runtime_verified=True,
                      current=current, target=target)
    if not record or record["phase"] == "restored":
        raise WPSettingsError("recovery", "No active WordPress HTTPS update to Restore")
    if expected_recovery != record["op"]:
        raise WPSettingsError("concurrency", "WordPress URL Recovery ID changed; Recheck")
    if any(current[key] not in (record["original"][key], record["target"][key])
           for key in KEYS):
        raise WPSettingsError(
            "recovery", "WordPress URL options changed independently; do not overwrite "
            "an administrator's new values", record["op"])
    row = {**record, "phase": "restoring"}
    _record_save(data_fd, site["id"], row)
    try:
        _php(site, php, "set", before=current, after=record["original"], runner=runner)
        confirmed = _php(site, php, "inspect", runner=runner)
        if confirmed != record["original"]:
            raise WPSettingsError("postcheck", "WordPress URL restore did not persist")
        row["phase"] = "restored"
        _record_save(data_fd, site["id"], row)
    except Exception as exc:
        raise WPSettingsError(
            "uncertain", "WordPress URL Restore uncertain: " + str(exc)[:180] +
            "; retain the saved Recovery ID and Recheck", record["op"]) from exc
    return _reply(site, "Restored",
                  _digest(config_sha, version, site, record["original"]),
                  row, changed=True, runtime_verified=True,
                  current=current, target=record["original"])
