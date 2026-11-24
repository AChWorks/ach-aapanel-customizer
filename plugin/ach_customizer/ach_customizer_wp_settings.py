"""Native selected-site WordPress debug and external WP-Cron management.

This is a manual, site-scoped operator workflow: explicit Apply -> Recheck ->
Restore, with no automatic changes when a website is discovered. Only one
unique, literal wp-config.php define is changed at a time. Existing foreign
settings, WP config macros/conditionals, and a cron task owned by somebody
else are never adopted. Recovery replaces only the exact owned line, not
unrelated administrator edits elsewhere in wp-config.php.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
from uuid import uuid4

from ach_customizer_cache_bridge import _docroot
from ach_customizer_cache_wordpress import _read_file, _replace_file, WP_BOOTSTRAP
from ach_customizer_status_extension import (
    _bounded_file, _directory, _owned_dir, _publish_complete, _write_exclusive,
)
from ach_customizer_state import DATA_DIR

SCHEMA = 1
CRON_DIR = "/etc/cron.d"
VHOST_ROOT = "/www/server/panel/vhost/nginx"
KEYS = {"debug": "WP_DEBUG", "cron": "DISABLE_WP_CRON"}
REGEX = re.compile(
    rb"(?m)^[ \t]*define\s*\(\s*(['\"])(WP_DEBUG|DISABLE_WP_CRON)\1\s*,"
    rb"\s*(true|false)\s*\)\s*;[ \t]*(?:(?://|#)[^\r\n]*)?(?:\r?\n|$)", re.I
)
MAX_RECORD = 4096
HASH = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
VERSION = re.compile(r"[1-9][0-9]{1,2}\Z")


class WPSettingsError(ValueError):
    def __init__(self, stage, message, recovery_id=None):
        super().__init__(message)
        self.stage = stage
        self.recovery_id = recovery_id if isinstance(recovery_id, str) and TOKEN.fullmatch(recovery_id) else None


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _name(site_id, kind):
    if type(site_id) is not int or not 0 < site_id < 2147483648 or kind not in KEYS:
        raise WPSettingsError("identity", "Invalid WordPress settings identity")
    return "ach_customizer.wp_settings." + str(site_id) + "." + kind + ".json"


def _task(site_id):
    return "ach-customizer-wp-cron-" + str(site_id)


def _read_record(fd, site, kind):
    data = _bounded_file(fd, _name(site["id"], kind), limit=MAX_RECORD, permissions=0o600)
    if data is None:
        return None
    try:
        row = json.loads(data)
        if not isinstance(row, dict):
            raise ValueError("Expected a JSON object")
        old = (base64.b64decode(row["original_line"], validate=True)
               if row.get("original_line") is not None else None)
    except (ValueError, UnicodeError, KeyError, TypeError, binascii.Error) as exc:
        raise WPSettingsError("recovery", "Saved WordPress policy record is unreadable") from exc
    if not isinstance(row, dict) or any(key not in row for key in (
            "operation_id", "php_version", "managed_line")):
        raise WPSettingsError("recovery", "Saved WordPress settings record is incomplete")
    if (not isinstance(row["operation_id"], str)
            or not isinstance(row["php_version"], str)
            or not isinstance(row["managed_line"], str)):
        raise WPSettingsError("recovery", "Saved WordPress settings identity is malformed")
    if (not isinstance(row, dict) or set(row) != {
                "schema", "kind", "site_id", "site_key", "root", "operation_id",
                "phase", "initial_sha256", "applied_sha256", "managed_line",
                "original_line", "php_version", "cron_task_sha256", "interval"
            } or type(row["schema"]) is not int or row["schema"] != SCHEMA
            or row["kind"] != kind or row["site_id"] != site["id"]
            or row["site_key"] != site["name"] or row["root"] != site["path"]
            or not TOKEN.fullmatch(row["operation_id"])
            or row["phase"] not in ("prepared", "applied", "restoring", "restored")
            or not all(isinstance(row[key], str) and HASH.fullmatch(row[key])
                       for key in ("initial_sha256", "applied_sha256"))
            or not isinstance(row["managed_line"], str)
            or "\n" not in row["managed_line"]
            or not VERSION.fullmatch(row["php_version"])
            or row["kind"] == "debug" and (row["cron_task_sha256"] is not None or row["interval"] is not None)
            or row["kind"] == "cron" and (not isinstance(row["cron_task_sha256"], str)
                    or not HASH.fullmatch(row["cron_task_sha256"])
                    or type(row["interval"]) is not int or not 1 <= row["interval"] <= 59)
            or old is not None and (len(old) > 1024 or b"\n" not in old)
            or _managed_value(row["managed_line"]) is None
            or _canonical_managed_line(row["kind"], row["operation_id"],
                                       _managed_value(row["managed_line"])) !=
               row["managed_line"].encode("ascii").replace(b"\r\n", b"\n")):
        raise WPSettingsError("recovery", "Saved WordPress settings record is invalid")
    return row, old


def _record_write(fd, site_id, kind, row):
    data = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_RECORD:
        raise WPSettingsError("recovery", "WordPress recovery record exceeds source budget")
    tmp = "." + _name(site_id, kind) + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, tmp, data, 0o600)
    os.replace(tmp, _name(site_id, kind), src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _canonical_managed_line(kind, op, value):
    return ("define( '" + KEYS[kind] + "', " + value +
            " ); // ACh Customizer " + op + "\n").encode("ascii")


def _managed_value(raw):
    match = re.fullmatch(r"define\( '(?:WP_DEBUG|DISABLE_WP_CRON)', (true|false) \);"
                         r" // ACh Customizer [0-9a-f]{32}\r?\n", raw)
    return match.group(1) if match else None


def _live_php_code(raw):
    """Mask PHP comments and quoted text while keeping original byte offsets.

    A conservative source check for one line-scoped setting, not a general
    PHP parser. Unfamiliar heredoc/nowdoc syntax needs manual review.
    """
    code = bytearray(raw)
    quoted = {}
    i = 0
    while i < len(raw):
        if raw.startswith(b"<<<", i):
            raise WPSettingsError(
                "compatibility", "WordPress config has complex PHP text; review the setting manually")
        if raw.startswith(b"/*", i):
            end = raw.find(b"*/", i + 2)
            if end < 0:
                raise WPSettingsError("compatibility", "WordPress PHP block comment is incomplete")
            end += 2
        elif raw.startswith(b"//", i) or raw[i] == 35:  # PHP # comment
            end = raw.find(b"\n", i)
            if end < 0:
                end = len(raw)
        elif raw[i] in (39, 34, 96):  # PHP quotes and backticks
            begin = i
            quote = raw[i]
            end = i + 1
            while end < len(raw) and raw[end] != quote:
                end += 2 if raw[end] == 92 else 1
            if end >= len(raw):
                raise WPSettingsError("compatibility", "WordPress PHP quoted text is incomplete")
            end += 1
            quoted[begin] = (end, raw[begin + 1:end - 1], quote)
        else:
            i += 1
            continue
        code[i:end] = b" " * (end - i)
        i = end
    return bytes(code), quoted


def _top_level_php(code, at):
    """Only use a direct PHP statement, never an inactive/conditional one."""
    prefix = code[:at]
    if (b"?>" in prefix
            or prefix.count(b"{") != prefix.count(b"}")
            or not prefix.rstrip().endswith((b"<?php", b";", b"}"))
            or re.search(rb"\b(?:if|elseif|while|for|foreach|switch)\s*\([^{}]*\)\s*:",
                         prefix, re.I)):
        raise WPSettingsError(
            "compatibility", "WordPress setting/bootstrap is conditional or not a direct PHP statement")


def _active_define_names(raw, code, quoted):
    """Inspect just the first argument of live PHP define() calls.

    A variable/computed first argument could define either managed constant;
    refuse the source rather than claim the setting is absent. Other define()
    values may be dynamic; their constant names must be literal.
    """
    names = []
    for call in re.finditer(rb"\bdefine\s*\(", code, re.I):
        at = call.end()
        while at < len(code) and code[at] in b" \t\r\n" and at not in quoted:
            at += 1
        literal = quoted.get(at)
        if (literal is None or literal[2] not in (39, 34)
                or b"\\" in literal[1] or literal[2] == 34 and b"$" in literal[1]):
            raise WPSettingsError(
                "compatibility", "WordPress config contains a dynamic define() name; review manually")
        end, name, _ = literal
        while end < len(code) and code[end] in b" \t\r\n":
            end += 1
        if end >= len(code) or code[end] != 44:  # comma after literal first argument
            raise WPSettingsError(
                "compatibility", "WordPress config contains an unsupported define() name; review manually")
        names.append((call.start(), name))
    return names


def _setting(raw, kind):
    name = KEYS[kind].encode("ascii")
    if not raw.lstrip().startswith(b"<?php"):
        raise WPSettingsError("compatibility", "WordPress config must start with PHP source")
    code, quoted = _live_php_code(raw)
    bootstrap = [
        match for match in WP_BOOTSTRAP.finditer(raw)
        if code[match.start() + len(match.group(0)) -
                len(match.group(0).lstrip(b" \t")):][:12] == b"require_once"
    ]
    if len(bootstrap) != 1:
        raise WPSettingsError("compatibility", "Unique active WordPress bootstrap not found")
    boot = bootstrap[0]
    _top_level_php(code, boot.start())

    # A pre-bootstrap PHP include can define either setting from another file.
    # Do not infer absence from wp-config.php alone or execute foreign PHP
    # during a read-only preview. The verified WordPress bootstrap follows
    # this prefix and is deliberately not an additional include.
    if re.search(rb"(?<![\w$])(?:require_once|require|include_once|include)\b",
                 code[:boot.start()], re.I):
        raise WPSettingsError(
            "compatibility", "WordPress config loads another PHP source before WordPress bootstrap; "
            "review the setting manually")

    # A PHP const statement may declare several constants separated by commas.
    # Check its active statement up to the semicolon, not only the first name;
    # comment and string contents have already been masked at fixed offsets.
    if re.search(rb"(?<![\w$])const\b[^;{}]*\b" + name + rb"\s*=(?!=|>)",
                 code, re.I):
        raise WPSettingsError(
            "compatibility", "WordPress " + KEYS[kind] +
            " uses a PHP const declaration; review manually")

    live = [at for at, value in _active_define_names(raw, code, quoted)
            if value.upper() == name]
    definitions = []
    for match in REGEX.finditer(raw):
        if match.group(2).upper() != name:
            continue
        at = match.start() + len(match.group(0)) - len(match.group(0).lstrip(b" \t"))
        if code[at:at + 6].lower() == b"define":
            definitions.append((at, match))
    # No reported absence if any active write uses an unsupported syntax.
    if len(live) != len(definitions) or len(live) > 1:
        raise WPSettingsError(
            "compatibility", "WordPress " + KEYS[kind] +
            " is duplicated, dynamic or not a single live literal definition")
    if not definitions:
        return None, None, boot.start()
    keyword_at, match = definitions[0]
    if (match.group(2) != name or
            live[0] != keyword_at or
            match.start() >= boot.start()):
        raise WPSettingsError(
            "compatibility", "WordPress " + KEYS[kind] +
            " definition is ambiguous, incorrectly cased or follows WordPress bootstrap")
    _top_level_php(code, keyword_at)
    return match, match.group(3).decode("ascii").lower(), boot.start()


def _propose(raw, kind, op, value):
    match, old_value, bootstrap_at = _setting(raw, kind)
    new_line = _canonical_managed_line(kind, op, value)
    if match is None:
        newline = b"\r\n" if b"\r\n" in raw else b"\n"
        inserted = new_line.replace(b"\n", newline)
        return raw[:bootstrap_at] + inserted + raw[bootstrap_at:], None, inserted
    before = match.group(0)
    if b"// ACh Customizer " in before:
        raise WPSettingsError("recovery", "A previous managed WordPress setting needs Recheck")
    # Edit the verified live span, not some identical inert text elsewhere.
    new_line = new_line.replace(b"\n", b"\r\n" if before.endswith(b"\r\n") else b"\n")
    return raw[:match.start()] + new_line + raw[match.end():], before, new_line


def _site_source(site, public, *, vhost_root):
    try:
        fd = _docroot(site, public)
    except (ValueError, OSError) as exc:
        raise WPSettingsError(
            "identity", "Native WordPress site root is shared, changed or inaccessible: "
            + str(exc)[:180]) from exc
    else:
        os.close(fd)
    root = site["path"]
    try:
        raw, _ = _read_file(root, "wp-config.php")
        settings, _ = _read_file(root, "wp-settings.php")
        cron, _ = _read_file(root, "wp-cron.php")
        vhost, _ = _read_file(vhost_root, site["name"] + ".conf")
    except (OSError, ValueError) as exc:
        raise WPSettingsError("source", "WordPress or native Nginx source unavailable: "
                              + type(exc).__name__) from exc
    if not raw.lstrip().startswith(b"<?php") or not settings.lstrip().startswith(b"<?php") or not cron.lstrip().startswith(b"<?php"):
        raise WPSettingsError("compatibility", "Verified WordPress PHP source files are required")
    from ach_customizer_monitor import (
        _active_nginx_text, _native_server_direct_include, MonitorInputError,
    )
    # Local WordPress operations need the site's native PHP CLI assignment,
    # not the entire Cache writer's source/peer admission predicate.
    try:
        active = _active_nginx_text(vhost.decode("utf-8"))
        candidates = re.findall(
            r"\binclude[ \t]+(enable-php-([^;\s]+)\.conf)[ \t]*;", active)
        if len(candidates) != 1:
            raise ValueError("No unique native PHP assignment")
        handler, assignment = candidates[0]
        match = re.fullmatch(r"([1-9][0-9]{1,2})(?:-wpfastcgi)?", assignment)
        if not match or not _native_server_direct_include(active, handler):
            raise ValueError("Unverified native PHP assignment or server scope")
        version = match.group(1)
    except (ValueError, UnicodeError, MonitorInputError) as exc:
        raise WPSettingsError("compatibility",
            "Unique server-scoped native PHP assignment is not available") from exc
    php = "/www/server/php/" + version + "/bin/php"
    if not os.path.isfile(php) or os.path.islink(php) or not os.access(php, os.X_OK):
        raise WPSettingsError("compatibility", "Selected site's native PHP CLI is unavailable")
    return raw, php, version


def _lint(raw, php, *, runner):
    try:
        proc = runner([php, "-l"], input=raw, capture_output=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WPSettingsError("syntax", "Cannot validate proposed WordPress PHP source") from exc
    if proc.returncode != 0:
        # Compiler messages can include original WP source snippets. Only
        # show the stage here, keeping detailed output in privileged QA.
        raise WPSettingsError("syntax", "Proposed wp-config.php failed native PHP syntax check")


def _cron_text(site, php, interval):
    # Cron treats % specially even inside shell quotes; reject not by an
    # arbitrary site allowlist but by encoding its special cron delimiter.
    root = site["path"]
    command = shlex.quote(php) + " -f " + shlex.quote(root + "/wp-cron.php")
    command = command.replace("%", r"\%")
    return (
        "# Managed by ACh aaPanel Customizer; use Restore before manual changes.\n"
        "*/" + str(interval) + " * * * * www " + command +
        " 2>&1 | /usr/bin/logger -t " + _task(site["id"]) + "\n"
    ).encode("utf8")


def _cron_ready(*, runner):
    if not os.path.isfile("/usr/bin/logger"):
        raise WPSettingsError("cron", "Required system logger is unavailable")
    try:
        result = runner(["systemctl", "is-active", "cron"], capture_output=True,
                        timeout=6, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WPSettingsError("cron", "Cannot inspect system cron scheduler") from exc
    if result.returncode != 0:
        raise WPSettingsError("cron", "System cron scheduler is not running")


def _reply(site, kind, state, digest, record, *, changed=False,
           reason="", runtime_verified=False, interval=None):
    return {
        "schema": SCHEMA, "site_id": site["id"], "site_key": site["name"],
        "kind": kind, "state": state, "source_sha256": digest,
        "recovery_id": record["operation_id"] if record else None,
        "changed": changed, "read_only": not changed,
        "runtime_verified": runtime_verified,
        "interval": interval,
        "reason": reason,
        "impact": "Selected WordPress wp-config.php setting only" + (
            " plus a root-owned site-specific /etc/cron.d scheduler" if kind == "cron" else ""),
    }


def manage(action, kind, site, public, *, desired=None, interval=None,
           expected_source=None, expected_recovery=None,
           data_fd, vhost_root=VHOST_ROOT, cron_dir=CRON_DIR,
           runner=None):
    """Caller owns primary-admin POST, selected-site snapshot, and state lock."""
    if action not in ("recheck", "apply", "restore") or kind not in KEYS:
        raise WPSettingsError("input", "Unsupported WordPress setting or action")
    if kind == "debug":
        if desired not in ("true", "false"):
            raise WPSettingsError("input", "Select an explicit WP_DEBUG value")
        if interval is not None:
            raise WPSettingsError("input", "Debug mode does not need a cron interval")
    else:
        if type(interval) is not int or not 1 <= interval <= 59 or desired != "true":
            raise WPSettingsError("input", "Choose a system cron interval of 1 to 59 minutes")
    run = runner or subprocess.run
    _owned_dir(data_fd)
    raw, php, version = _site_source(site, public, vhost_root=vhost_root)
    before_hash = _sha(raw)
    saved = _read_record(data_fd, site, kind)
    record, old = saved if saved else (None, None)
    cfd = None
    try:
        scheduled = None
        if kind == "cron":
            cfd = _directory(cron_dir)
            _owned_dir(cfd)
            scheduled = _bounded_file(cfd, _task(site["id"]), limit=4096, permissions=0o644)
        if action == "recheck":
            if not record:
                _, current_value, _ = _setting(raw, kind)
                if kind == "cron" and scheduled is not None:
                    state, reason = "Conflict", "Existing site Cron task is not owned by Customizer"
                elif current_value == desired:
                    state, reason = "Already Configured", "Current WordPress value already equals the selection"
                else:
                    state, reason = "Source Ready", ""
                return _reply(site, kind, state, before_hash, record,
                              reason=reason, interval=interval)
            managed = record["managed_line"].encode("ascii")
            matched, actual_value, _ = _setting(raw, kind)
            line = matched.group(0) if matched else None
            expected_task = (_cron_text(site, php, record["interval"])
                             if kind == "cron" else None)
            if record["phase"] == "restored":
                state = ("Restored" if managed not in raw and scheduled is None else "Drift")
            elif (record["phase"] == "applied" and line == managed and
                  (kind != "cron" or (scheduled is not None and
                   scheduled == expected_task and _sha(scheduled) == record["cron_task_sha256"]))):
                state = "Applied"
            else:
                state = "Recovery Required"
            return _reply(site, kind, state, before_hash, record,
                          interval=record["interval"],
                          reason="" if state in ("Applied", "Restored") else
                          "Managed WordPress source or scheduled task needs exact Restore/Recheck")
        if action == "apply":
            if record and record["phase"] != "restored" or kind == "cron" and scheduled is not None:
                raise WPSettingsError("recovery", "Existing WordPress setting or cron task needs recovery")
            if expected_source != before_hash:
                raise WPSettingsError("concurrency", "wp-config.php changed after Preview; Recheck")
            _, current, _ = _setting(raw, kind)
            if current == desired:
                raise WPSettingsError("input", "Setting already has the selected value; no Apply needed")
            operation_id = uuid4().hex
            proposed, original, managed = _propose(raw, kind, operation_id, desired)
            _lint(proposed, php, runner=run)
            cron_bytes = _cron_text(site, php, interval) if kind == "cron" else None
            if cron_bytes is not None:
                _cron_ready(runner=run)
            record = {
                "schema": SCHEMA, "kind": kind, "site_id": site["id"],
                "site_key": site["name"], "root": site["path"],
                "operation_id": operation_id, "phase": "prepared",
                "initial_sha256": before_hash, "applied_sha256": _sha(proposed),
                "managed_line": managed.decode("ascii"),
                "original_line": (base64.b64encode(original).decode("ascii")
                                  if original is not None else None),
                "php_version": version,
                "cron_task_sha256": _sha(cron_bytes) if cron_bytes is not None else None,
                "interval": interval,
            }
            _record_write(data_fd, site["id"], kind, record)
            try:
                if cron_bytes is not None:
                    _publish_complete(cfd, _task(site["id"]), cron_bytes, 0o644, operation_id)
                _replace_file(site["path"], "wp-config.php", raw, proposed)
                renewed, _, _ = _site_source(site, public, vhost_root=vhost_root)
                if renewed != proposed:
                    raise WPSettingsError("postcheck", "WordPress source did not commit exact proposal")
                record["phase"] = "applied"
                _record_write(data_fd, site["id"], kind, record)
            except Exception as exc:
                raise WPSettingsError("uncertain",
                        "WordPress source/scheduler Apply outcome uncertain; Recheck Recovery ID",
                        operation_id) from exc
            return _reply(site, kind, "Applied", _sha(proposed), record,
                          changed=True, interval=interval)
        if record is None or record["phase"] == "restored":
            raise WPSettingsError("recovery", "No saved WordPress setting to restore")
        if expected_recovery != record["operation_id"] or expected_source != before_hash:
            raise WPSettingsError("concurrency", "WordPress recovery selection changed; Recheck")
        managed = record["managed_line"].encode("ascii")
        installed = raw.count(managed) == 1
        if not installed:
            if record["phase"] == "prepared":
                # Before any source publication, original bytes must still match.
                if _sha(raw) != record["initial_sha256"]:
                    raise WPSettingsError("recovery", "Interrupted source no longer equals saved baseline")
            elif record["phase"] == "restoring":
                # A prior Restore may have committed wp-config.php and crashed
                # before retiring the cron task or advancing the journal. Do
                # not demand the removed managed line to exist again.
                observed_match, _, _ = _setting(raw, kind)
                observed = observed_match.group(0) if observed_match else None
                if old is None and observed is not None or (
                        old is not None and observed != old):
                    raise WPSettingsError(
                        "recovery", "Interrupted Restore source is not the saved original setting")
            else:
                raise WPSettingsError("recovery", "Exact managed wp-config.php setting is missing or changed")
        if kind == "cron" and scheduled is not None and _sha(scheduled) != record["cron_task_sha256"]:
            raise WPSettingsError("recovery", "Cron scheduler is modified or foreign")
        record["phase"] = "restoring"
        _record_write(data_fd, site["id"], kind, record)
        try:
            if installed:
                restored = raw.replace(managed, old or b"", 1)
                _lint(restored, php, runner=run)
                _replace_file(site["path"], "wp-config.php", raw, restored)
            else:
                restored = raw
            if kind == "cron" and scheduled is not None:
                if _bounded_file(cfd, _task(site["id"]), limit=4096, permissions=0o644) != scheduled:
                    raise WPSettingsError("concurrency", "Scheduled Cron task changed during Restore")
                os.unlink(_task(site["id"]), dir_fd=cfd)
                os.fsync(cfd)
            renewed, _, _ = _site_source(site, public, vhost_root=vhost_root)
            if renewed != restored:
                raise WPSettingsError("postcheck", "WordPress Restore did not restore the exact managed line")
            record["phase"] = "restored"
            _record_write(data_fd, site["id"], kind, record)
        except Exception as exc:
            raise WPSettingsError("uncertain",
                    "WordPress settings Restore uncertain; retain Recovery ID and Recheck",
                    record["operation_id"]) from exc
        return _reply(site, kind, "Restored", _sha(restored), record,
                      changed=True, interval=interval)
    finally:
        if cfd is not None:
            os.close(cfd)
