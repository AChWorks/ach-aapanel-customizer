"""Opt-in, site-specific Nginx pre-PHP sensitive-path protection for aaPanel 8.0.7.

Native site identity, VHost, and exclusive extension inclusion are re-read on
every operation. The only managed config is one exact site-owned *.conf file.
No vendor Nginx templates, WordPress files or peer-site config are edited.
A root-owned journal survives interrupted publication/reload and permits a
separate explicit recovery. An HTTP 403 + generated nonce proves that the
active Nginx worker actually selected each fixed defensive location.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import time
from uuid import uuid4

from ach_customizer_status_inspect import _directory, VHOST_ROOT
from ach_customizer_status_site_file import _server_directives
from ach_customizer_status_extension import (
    DOMAIN, HASH, NGINX, NGINX_CONF, TOKEN, ExtensionError,
    _bounded_file, _nginx, _owned_dir, _publish_complete,
    _rename_noreplace, _include_graph_guard, _write_exclusive,
)

MODE = "native_site_sensitive_paths"
SCHEMA = 1
MAX_JOURNAL = 4096
MAX_INCLUDE = 8192
PROOF_BODY = "ACh-Guard-Proof-"
# Pre-stable current policy only; QA installations are reset between builds.
RULESET = "site-sensitive-files-v1"
RULESET_XMLRPC = "site-sensitive-files-xmlrpc-v1"
RULESETS = (RULESET, RULESET_XMLRPC)
PROOF_KINDS = (
    "root_env", "nested_env", "wp_env", "nested_htaccess",
    "backup_dir", "wp_backup_dir", "uploaded_php", "wp_uploaded_php",
    "media_php", "tmp_php", "debug_log", "error_log",
    "db_dump", "config_backup",
)
XMLRPC_PROOF_KINDS = PROOF_KINDS + ("xmlrpc",)
# Path syntax is verified against the current aaPanel native record, never
# reconstructed from a name, URL, browser-selected path or global site root.
ROOT = re.compile(r"/[a-zA-Z0-9/_.-]{1,1023}\Z")


class GuardError(ExtensionError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _file(site_id):
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise GuardError("identity", "Invalid native site ID")
    return "ach_customizer_sensitive_" + str(site_id) + ".conf"


def _journal(site_id):
    _file(site_id)
    return "ach_customizer.nginx_security." + str(site_id) + ".json"


def _retained(site_id, op):
    if not isinstance(op, str) or not TOKEN.fullmatch(op):
        raise GuardError("identity", "Invalid security recovery identity")
    return "ach_customizer_sensitive_" + str(site_id) + "." + op + ".retained"


def _site_identity(site):
    if (not isinstance(site, dict) or type(site.get("id")) is not int
            or not isinstance(site.get("name"), str)
            or not DOMAIN.fullmatch(site["name"])
            or not isinstance(site.get("path"), str)
            or not ROOT.fullmatch(site["path"])
            or "//" in site["path"] or ".." in site["path"].split("/")):
        raise GuardError("identity", "Unsupported native site root or identity")
    bindings = site.get("bound_domains")
    if not isinstance(bindings, list):
        raise GuardError("identity", "Invalid native domain binding inventory")
    clean = []
    for binding in bindings:
        if (not isinstance(binding, dict) or
                not isinstance(binding.get("name"), str) or
                not DOMAIN.fullmatch(binding["name"]) or
                type(binding.get("port")) is not int or
                not 1 <= binding["port"] <= 65535):
            raise GuardError("identity", "Invalid native site domain binding")
        clean.append((binding["name"], binding["port"]))
    if len(set(clean)) != len(clean):
        raise GuardError("identity", "Duplicate native site domain binding")
    return _sha(json.dumps(sorted(clean), separators=(",", ":")).encode("ascii"))


def _public_proof(op):
    """Nonsecret verification marker; never expose the recovery ID in HTTP.

    Native request paths and denied responses can appear in web access logs.
    An irreversible digest keeps the root-owned journal ID out of those logs.
    """
    if not isinstance(op, str) or not TOKEN.fullmatch(op):
        raise GuardError("identity", "Invalid security proof generation")
    return PROOF_BODY + hashlib.sha256(("site-guard-v1:" + op).encode("ascii")).hexdigest()[:32]


def _include(op, ruleset=RULESET):
    if not isinstance(op, str) or not TOKEN.fullmatch(op):
        raise GuardError("identity", "Invalid Nginx guard generation")
    if ruleset not in RULESETS:
        raise GuardError("input", "Unsupported Nginx security rule selection")
    # Server-rewrite if+return blocks execute before Nginx location selection.
    # They cannot be bypassed by an existing ^~ /wp-content/uploads/ prefix,
    # whereas regex locations alone would lose to a matching ^~ location.
    # Only fixed, reviewed regexes enter the native source; quoted Nginx
    # expressions use character classes instead of ambiguous backslash escapes.
    proof = _public_proof(op)
    patterns = (
        "(^|/)(?:[.]env(?:[.][^/]+)?|[.]htaccess|[.]user[.]ini|[.]git|[.]svn)(?:/|$)",
        "(^|/)(?:backups?|db-backup|db_dumps?)(?:/|$)",
        "(^|/)(?:uploads|media|tmp)/[^?#]*[.](?:php[0-9]?|phtml|phar)(?:/|$)",
    )
    # High-confidence sensitive *files*, not all archives or logs.
    # Existing Nginx autoindex-off already prevents ordinary directory listing.
    patterns += (
        "(^|/)(?:(?:debug|error|access|php_errors)[.]log(?:[.][0-9]+|[.]gz)?"
        "|error_log(?:[.][0-9]+|[.]gz)?"
        "|wp-config[.]php(?:[.](?:bak|backup|old|orig|save)|~)"
        "|[^/]+[.](?:sql|sqlite|sqlite3|db)(?:[.]gz)?"
        "|[^/]+[.](?:bak|backup))(?:/|$)",
    )
    if ruleset == RULESET_XMLRPC:
        # Server rewrite phase executes before php's ^~ or regex location
        # dispatch. $uri omits the query string; all methods are rejected.
        patterns += ("^/xmlrpc[.]php$",)
    parts = [
        "# Managed by ACh aaPanel Customizer; do not edit manually.",
        "# Scoped pre-PHP defense. Rule set: " + ruleset,
    ]
    for pattern in patterns:
        parts.extend((
            'if ($uri ~* "' + pattern + '") {',
            '    return 403 "' + proof + '";',
            "}",
        ))
    result = ("\n".join(parts) + "\n").encode("ascii")
    if len(result) > MAX_INCLUDE:
        raise GuardError("publication", "Generated security rule exceeds limit")
    return result


def _proposal_sha(ruleset=RULESET):
    # Deterministic approval binds the rule semantics and selected XML-RPC
    # option, independent of the per-activation nonce.
    return _sha(_include("0" * 32, ruleset))


def _read_journal(data_fd, site_id):
    raw = _bounded_file(data_fd, _journal(site_id),
                        limit=MAX_JOURNAL, permissions=0o600)
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise GuardError("recovery", "Security recovery journal is unreadable") from exc
    fields = {"schema", "site_id", "site_key", "site_root", "bindings_sha",
              "ruleset", "op", "phase", "vhost_sha", "include_sha"}
    if (not isinstance(record, dict) or set(record) != fields
            or type(record["schema"]) is not int or record["schema"] != SCHEMA
            or type(record["site_id"]) is not int or record["site_id"] != site_id
            or not isinstance(record["site_key"], str)
            or not DOMAIN.fullmatch(record["site_key"])
            or not isinstance(record["site_root"], str)
            or not ROOT.fullmatch(record["site_root"])
            or "//" in record["site_root"] or ".." in record["site_root"].split("/")
            or not isinstance(record["op"], str) or not TOKEN.fullmatch(record["op"])
            or record["phase"] not in ("prepared", "applied", "restored")
            or any(not isinstance(record[k], str) or not HASH.fullmatch(record[k])
                   for k in ("bindings_sha", "vhost_sha", "include_sha"))):
        raise GuardError("recovery", "Invalid or altered native security recovery journal")
    if not isinstance(record["ruleset"], str):
        raise GuardError("recovery", "Invalid or altered native security recovery journal")
    if record["ruleset"] not in RULESETS:
        # An older/unrecognized rule family cannot be verified by the current
        # generator. Preserve the journal and refuse all writes; incompatibility
        # alone does not establish tampering.
        raise GuardError("unsupported_ruleset",
                         "Unsupported native security recovery ruleset. Saved journal "
                         + _journal(site_id) + " preserved. This version cannot verify "
                         "or restore it; a server administrator must investigate the "
                         "original rule and journal separately before further changes.")
    if _sha(_include(record["op"], record["ruleset"])) != record["include_sha"]:
        raise GuardError("recovery", "Invalid or altered native security recovery journal")
    return record


def _save_journal(data_fd, record):
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if not 0 < len(raw) <= MAX_JOURNAL:
        raise GuardError("recovery", "Security journal exceeds supported size")
    target = _journal(record["site_id"])
    temp = "." + target + "." + uuid4().hex + ".stage"
    created = False
    try:
        _write_exclusive(data_fd, temp, raw, 0o600)
        created = True
        os.replace(temp, target, src_dir_fd=data_fd, dst_dir_fd=data_fd)
        created = False
        os.fsync(data_fd)
    finally:
        if created:
            os.unlink(temp, dir_fd=data_fd)


def _probe_path(op, kind):
    if kind not in XMLRPC_PROOF_KINDS or not TOKEN.fullmatch(op):
        raise GuardError("input", "Unsupported security probe")
    # Use actual high-risk native path prefixes. Prefixing everything with
    # one synthetic top-level folder would MISS a more-specific Nginx ^~
    # location on /wp-content/uploads/ or /backups/.
    suffix = ".__ach_customizer_security_" + _public_proof(op).rsplit("-", 1)[-1]
    return {
        "root_env": "/.env" + suffix,
        "nested_env": "/sub/.env" + suffix,
        "wp_env": "/wp-content/.env" + suffix,
        "nested_htaccess": "/wp-content/uploads/.htaccess",
        "backup_dir": "/backups/" + suffix + "/proof.sql",
        "wp_backup_dir": "/wp-content/backups/" + suffix + "/proof.sql",
        "uploaded_php": "/uploads/" + suffix + "/proof.php",
        "wp_uploaded_php": "/wp-content/uploads/" + suffix + "/proof.php",
        "media_php": "/media/" + suffix + "/proof.phtml",
        "tmp_php": "/tmp/" + suffix + "/proof.php",
        "debug_log": "/wp-content/uploads/debug.log",
        "error_log": "/site/logs/error_log",
        "db_dump": "/site/db-backup-copy.sql.gz",
        "config_backup": "/wp-config.php.bak",
        "xmlrpc": "/xmlrpc.php",
    }[kind]


def _probe(site, op, kind, *, port=80):
    if (not isinstance(site, dict) or not isinstance(site.get("name"), str)
            or not DOMAIN.fullmatch(site["name"])):
        raise GuardError("identity", "Unsupported native HTTP Host")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.5)
    try:
        conn.request("GET", _probe_path(op, kind), headers={
            "Host": site["name"], "Connection": "close",
            "Accept-Encoding": "identity", "Cache-Control": "no-cache",
        })
        response = conn.getresponse()
        code = response.status
        content_encoding = response.getheader("Content-Encoding", "identity")
        if content_encoding.lower() != "identity":
            raise GuardError("probe", "Nginx security response was compressed")
        body = response.read(4097)
        response.close()
        # Status alone does not prove the server-rewrite guard ran:
        # aaPanel may also return native 403/404 on a missing path.
        # The random per-generation body ties this observation to the
        # precise managed source without adding a global response header.
        nonce = op if body == _public_proof(op).encode("ascii") else None
        return code, nonce
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise GuardError("probe", "Local Nginx HTTP/80 verification unavailable") from exc
    finally:
        conn.close()


def _verified(site, op, *, present, probe=None, ruleset=RULESET):
    if ruleset not in RULESETS:
        raise GuardError("recovery", "Unknown managed Nginx security rule set")
    fn = probe or _probe
    kinds = XMLRPC_PROOF_KINDS if ruleset == RULESET_XMLRPC else PROOF_KINDS
    deadline = time.monotonic() + 9
    consecutive = 0
    while True:
        results = [fn(site, op, kind) for kind in kinds]
        valid = (all(code == 403 and header == op for code, header in results)
                 if present else all(header != op for _, header in results))
        consecutive = consecutive + 1 if valid else 0
        if consecutive >= 3:
            return True
        if time.monotonic() >= deadline:
            raise GuardError(
                "postcheck", "Serving Nginx workers did not confirm the "
                + ("new guard" if present else "removed guard") + " on all protected paths")
        time.sleep(0.2)


def _source_safe(site, *, vhost_root, nginx_conf):
    """Native VHost security preflight independent of Status Pages mapping.

    A selected sensitive-path policy must work even when the native /404.html
    error_page is absent. The selected VHost and its other *.conf includes
    form the optimistic preflight source identity.
    """
    if (site.get("status") not in (1, "1")
            or {"name": site["name"], "port": 80} not in site["bound_domains"]):
        raise GuardError("identity", "Native site must have active HTTP/80 binding")
    name = site["name"]
    root = site["path"].rstrip("/")
    if os.path.realpath(root) != root or not os.path.isdir(root):
        raise GuardError("identity", "Native document root is absent or redirected")
    if (not isinstance(vhost_root, str) or not vhost_root.startswith("/")
            or os.path.realpath(vhost_root) != vhost_root):
        raise GuardError("source", "Native Nginx VHost root is not canonical")
    vhost_fd = _directory(vhost_root)
    try:
        _owned_dir(vhost_fd)
        raw = _bounded_file(vhost_fd, name + ".conf")
    finally:
        os.close(vhost_fd)
    if raw is None:
        raise GuardError("source", "Native selected-site Nginx VHost is absent")
    try:
        directives = _server_directives(raw.decode("utf8"))
    except (UnicodeError, ExtensionError) as exc:
        raise GuardError("source", "Native Nginx site source cannot be safely inspected") from exc
    def values(command):
        return [d[len(command) + 1:] for d in directives if d.startswith(command + " ")]
    includes = values("include")
    roots = values("root")
    server_names = values("server_name")
    expected_glob = vhost_root + "/extension/" + name + "/*.conf"
    if roots != [root] or len(server_names) != 1:
        raise GuardError("source", "Native root or server identity is unproven")
    if includes.count(expected_glob) != 1:
        if expected_glob not in includes:
            raise GuardError(
                "source", "New native VHost has no selected-site extension include. "
                "Add exactly one server-level include for " + expected_glob +
                " and its root-owned directory using the site's aaPanel Config, then Recheck")
        raise GuardError("source", "Native site extension include is duplicated or unproven")
    observed_names = server_names[0].split()
    native_domains = {binding["name"] for binding in site["bound_domains"]}
    if (not observed_names or name not in observed_names
            or len(set(observed_names)) != len(observed_names)
            or any(item not in native_domains for item in observed_names)):
        raise GuardError("source", "Generated VHost names do not match native bindings")
    _include_graph_guard(site, "404", vhost_root, nginx_conf)
    vhost_fd = _directory(vhost_root)
    try:
        _owned_dir(vhost_fd)
        # Check every parked native VHost, not just the first N filenames.
        # Stream directory entries so large installations do not accumulate
        # an unrelated peer-name inventory.
        with os.scandir(vhost_fd) as entries:
            for entry in entries:
                other = entry.name
                if (other == name + ".conf" or not other.endswith(".conf")
                        or not DOMAIN.fullmatch(other[:-5])):
                    continue
                peer = _bounded_file(vhost_fd, other)
                if peer is not None and expected_glob.encode() in peer:
                    raise GuardError("ownership", "Another native Nginx server imports this site's extension")
    finally:
        os.close(vhost_fd)
    ext_path = vhost_root + "/extension/" + name
    ext_fd = _directory(ext_path)
    try:
        _owned_dir(ext_fd)
        files = sorted(item for item in os.listdir(ext_fd) if item.endswith(".conf"))
        digest = hashlib.sha256(raw)
        for filename in files:
            if filename == _file(site["id"]):
                continue
            if len(filename) > 240 or "/" in filename or "\x00" in filename:
                raise GuardError("source", "Untrusted native extension filename")
            fragment = _bounded_file(ext_fd, filename, limit=64 * 1024)
            if fragment is None:
                raise GuardError("concurrency", "Native Nginx extension disappeared")
            digest.update(filename.encode("utf8") + b"\0" + hashlib.sha256(fragment).digest())
        return digest.hexdigest(), ext_path
    finally:
        os.close(ext_fd)


def _report(site, *, state, source_sha=None, journal=None, changed=False,
            runtime_verified=False, reason="", read_only=True, ruleset=RULESET):
    effective = (journal["ruleset"] if journal and
                 journal["phase"] in ("prepared", "applied") else ruleset)
    return {
        "schema": SCHEMA, "site_id": site["id"], "site_key": site["name"],
        "site_root": site["path"], "mode": MODE, "ruleset": effective,
        "block_xmlrpc": effective == RULESET_XMLRPC,
        "state": state, "reason": reason, "read_only": read_only,
        "changed": changed, "runtime_verified": runtime_verified,
        "vhost_sha256": source_sha, "proposal_sha256": _proposal_sha(effective),
        "recovery_id": journal["op"] if journal else None,
        "journal_phase": journal["phase"] if journal else None,
        "automatic_enforcement": False,
    }


def manage_guard(action, site, *, data_fd, approved=False,
                 expected_vhost=None, expected_proposal=None,
                 expected_recovery=None, vhost_root=VHOST_ROOT,
                 nginx=NGINX, nginx_conf=NGINX_CONF, runner=None,
                 probe=None, block_xmlrpc=False):
    """Manage under caller's full-primary-admin, current-site state lock.

    Caller must validate the selected native site before and after this
    function. Preview/Recheck never publishes or reloads configuration.
    """
    if action not in ("preview", "apply", "recheck", "restore") or type(block_xmlrpc) is not bool:
        raise GuardError("input", "Unsupported native Nginx protection action/option")
    selected_ruleset = RULESET_XMLRPC if block_xmlrpc else RULESET
    bindings_sha = _site_identity(site)
    _owned_dir(data_fd)
    record = _read_journal(data_fd, site["id"])
    if action in ("apply", "restore") and approved is not True:
        raise GuardError("approval", "Explicit selected-site Nginx reload approval required")

    if site.get("status") not in ("1", 1):
        if action in ("apply", "restore"):
            raise GuardError("identity", "Stopped native website cannot change Nginx policy")
        return _report(site, state="Suspended" if record else "Needs Review",
                       journal=record, reason="Native website is stopped; inspect saved recovery",
                       ruleset=selected_ruleset)
    try:
        source_sha, extension_dir = _source_safe(
            site, vhost_root=vhost_root, nginx_conf=nginx_conf)
    except (ExtensionError, OSError):
        if action in ("apply", "restore") or record is None:
            raise
        return _report(site, state="Needs Review", journal=record,
                       reason="Native VHost/include source changed; existing recovery retained",
                       ruleset=selected_ruleset)

    extension_fd = _directory(extension_dir)
    try:
        _owned_dir(extension_fd)
        filename = _file(site["id"])
        current = _bounded_file(extension_fd, filename,
                                limit=MAX_INCLUDE, permissions=0o600)
        changed_source = bool(record and (
            record["site_key"] != site["name"] or
            record["site_root"] != site["path"] or
            record["bindings_sha"] != bindings_sha or
            record["vhost_sha"] != source_sha))
        # A fully restored record no longer owns a live source; permit a
        # fresh operator-reviewed Apply after native regeneration.
        restored_no_include = bool(
            record and record["phase"] == "restored" and current is None)
        # Inspect the same live/retained ownership state for every active
        # journal, not only when the native VHost happened to change.
        retained = None
        live_owned = retained_owned = False
        if record and record["phase"] in ("prepared", "applied"):
            retained = _bounded_file(
                extension_fd, _retained(site["id"], record["op"]),
                limit=MAX_INCLUDE, permissions=0o600)
            live_owned = (current is not None and retained is None
                          and _sha(current) == record["include_sha"])
            retained_owned = (current is None and retained is not None
                              and _sha(retained) == record["include_sha"])

        # Same-site/root native source drift may permit only an explicit
        # retirement of the one exact owned rule. It never approves the
        # new source or silently reapplies protection.
        drift_restore_ready = bool(
            changed_source and record["phase"] in ("prepared", "applied")
            and record["site_key"] == site["name"]
            and record["site_root"] == site["path"]
            and record["vhost_sha"] != source_sha
            and (live_owned or retained_owned))
        if changed_source and not (restored_no_include or drift_restore_ready):
            if action in ("apply", "restore"):
                raise GuardError(
                    "identity", "Native site/VHost changed; preserved security recovery requires review")
            return _report(site, state="Needs Review", source_sha=source_sha,
                           journal=record, reason="Site identity, root, bindings or native source drifted",
                           ruleset=selected_ruleset)

        if action in ("preview", "recheck") and drift_restore_ready:
            report = _report(
                site, state="Recovery Required", source_sha=source_sha,
                journal=record, ruleset=selected_ruleset,
                reason="Native VHost source changed while this exact owned guard remains; "
                       "explicitly Restore its Recovery ID before a fresh Preview/Apply")
            if record["phase"] == "applied":
                # Frontend validates the exact scope before exposing Restore;
                # unverified drift must never be displayed as healthy Applied.
                report["recovery_scope"] = "native_source_drift"
            return report

        if action in ("preview", "recheck"):
            if record is None:
                state = "Unmanaged" if current is None else "Needs Review"
            elif record["phase"] == "prepared":
                # The durable journal may precede publication, or one exact
                # live/retained fragment may survive interrupted publication.
                state = ("Recovery Required" if (
                    live_owned or retained_owned or
                    (current is None and retained is None)) else "Needs Review")
            elif record["phase"] == "restored":
                state = "Restored" if current is None else "Needs Review"
                if current is None:
                    try:
                        _verified(site, record["op"], present=False, probe=probe,
                                  ruleset=record["ruleset"])
                    except (GuardError, OSError):
                        state = "Needs Review"
            elif record["phase"] == "applied" and retained_owned:
                state = "Recovery Required"
            elif record["phase"] == "applied" and live_owned:
                try:
                    _verified(site, record["op"], present=True, probe=probe,
                              ruleset=record["ruleset"])
                    state = "Applied"
                except (GuardError, OSError):
                    state = "Needs Review"
            else:
                state = "Needs Review"
            reason = {
                "Unmanaged": "Native VHost is eligible; no managed security policy is active",
                "Restored": "Previous managed rule has been retired and nonce is absent",
                "Applied": "All selected pre-location Nginx probes served HTTP 403 with the active proof",
                "Recovery Required": "An interrupted Apply/Restore needs explicit inspected recovery",
                "Needs Review": "Foreign/stale source, mismatch or unavailable runtime proof",
            }.get(state, "Native site not eligible")
            if state == "Recovery Required" and record["phase"] == "applied":
                reason = ("Interrupted Restore retained the exact owned Guard file; "
                          "explicitly Restore the saved Recovery ID")
            report = _report(site, state=state, source_sha=source_sha,
                             journal=record, runtime_verified=state in ("Applied", "Restored"),
                             reason=reason, ruleset=selected_ruleset)
            if state == "Recovery Required" and record["phase"] == "applied":
                report["recovery_scope"] = "interrupted_restore"
            return report

        # Bind Restore to the exact inspected source, not merely the
        # original journal SHA or the selected native site snapshot.
        if action == "restore" and (
                not isinstance(expected_vhost, str)
                or not HASH.fullmatch(expected_vhost)
                or expected_vhost != source_sha):
            raise GuardError(
                "concurrency", "Native Nginx source changed or Recheck evidence is missing; "
                "Recheck this site before Restore")

        # Neither a successful Nginx -t nor HTTP proof makes a write safe
        # if the generated native source is not still the reviewed source.
        _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)

        if action == "apply":
            if current is not None or record and record["phase"] != "restored":
                raise GuardError("concurrency", "Existing native security rule is foreign or needs recovery")
            if (expected_vhost != source_sha or
                    expected_proposal != _proposal_sha(selected_ruleset)):
                raise GuardError("concurrency", "Selected security plan or VHost changed since Preview")
            if record:
                _verified(site, record["op"], present=False, probe=probe,
                          ruleset=record["ruleset"])
            op = uuid4().hex
            include_bytes = _include(op, selected_ruleset)
            created = {
                "schema": SCHEMA, "site_id": site["id"], "site_key": site["name"],
                "site_root": site["path"], "bindings_sha": bindings_sha,
                "ruleset": selected_ruleset, "op": op, "phase": "prepared",
                "vhost_sha": source_sha, "include_sha": _sha(include_bytes),
            }
            _save_journal(data_fd, created)
            try:
                _publish_complete(extension_fd, filename, include_bytes, 0o600, op)
            except ExtensionError as exc:
                # The shared publisher raises ExtensionError, not GuardError.
                # Only this owned, post-journal publication boundary may
                # promote the locally generated durable recovery identity.
                raise GuardError(
                    "uncertain", "Nginx security publication unconfirmed; "
                    "Recheck saved Recovery ID before another action",
                    recovery_id=op,
                ) from exc
            # If syntax fails, retire the file before a reload; keep journal
            # and retained asset for explicit Recheck/Restore.
            try:
                if _source_safe(site, vhost_root=vhost_root,
                                nginx_conf=nginx_conf)[0] != source_sha:
                    raise GuardError("concurrency", "Native VHost changed before activation")
                _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            except Exception as exc:
                try:
                    _rename_noreplace(extension_fd, filename, _retained(site["id"], op))
                    os.fsync(extension_fd)
                    _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
                except Exception as cleanup:
                    raise GuardError(
                        "uncertain", "Security syntax failure could not be retired; Recheck recovery",
                        recovery_id=op) from cleanup
                raise GuardError(
                    "recovered", "Security syntax check failed without reloading Nginx; Recheck recovery",
                    recovery_id=op) from exc
            try:
                _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
                _verified(site, op, present=True, probe=probe,
                          ruleset=selected_ruleset)
                if _source_safe(site, vhost_root=vhost_root,
                                nginx_conf=nginx_conf)[0] != source_sha:
                    raise GuardError("concurrency", "Native include source changed during guard activation")
            except Exception as exc:
                raise GuardError(
                    "uncertain", "Nginx guard activation unconfirmed; Recheck saved Recovery ID",
                    recovery_id=op) from exc
            created["phase"] = "applied"
            try:
                _save_journal(data_fd, created)
            except Exception as exc:
                raise GuardError(
                    "uncertain", "Security live but final recovery journal unconfirmed; Recheck",
                    recovery_id=op) from exc
            return _report(site, state="Applied", source_sha=source_sha,
                           journal=created, changed=True, runtime_verified=True,
                           reason="All selected pre-location probes verified on live Nginx",
                           read_only=False, ruleset=selected_ruleset)

        if (not record or expected_recovery != record["op"] or
                record["phase"] not in ("prepared", "applied")):
            raise GuardError("recovery", "Unknown or retired Nginx security Recovery ID")
        retired_name = _retained(site["id"], record["op"])
        retained_bytes = _bounded_file(extension_fd, retired_name,
                                       limit=MAX_INCLUDE, permissions=0o600)
        # Native aaPanel writers do not share our lock. Validate both the
        # reviewed VHost/sibling sources and the exact Guard filenames again
        # after the initial syntax test, before any rename or service reload.
        if _source_safe(site, vhost_root=vhost_root,
                        nginx_conf=nginx_conf)[0] != expected_vhost:
            raise GuardError(
                "concurrency", "Native Nginx source changed after Recheck; "
                "Recheck this site before Restore")
        live_now = _bounded_file(extension_fd, filename,
                                 limit=MAX_INCLUDE, permissions=0o600)
        retained_now = _bounded_file(extension_fd, retired_name,
                                     limit=MAX_INCLUDE, permissions=0o600)
        if live_now != current or retained_now != retained_bytes:
            raise GuardError(
                "concurrency", "Managed Nginx Guard changed during Restore; "
                "Recheck file ownership before retrying")
        if current is None:
            if retained_bytes is not None and _sha(retained_bytes) != record["include_sha"]:
                raise GuardError("recovery", "Retained security config has changed")
            if retained_bytes is None and record["phase"] != "prepared":
                raise GuardError("recovery", "Applied security config missing without owned retained file")
        elif _sha(current) != record["include_sha"] or retained_bytes is not None:
            raise GuardError("recovery", "Managed security config altered or ambiguous")

        expected_retired = current if current is not None else retained_bytes
        retired_here = False
        moved_identity = None
        if current is not None:
            try:
                original_stat = os.stat(filename, dir_fd=extension_fd,
                                        follow_symlinks=False)
                moved_identity = (original_stat.st_dev, original_stat.st_ino)
                _rename_noreplace(extension_fd, filename, retired_name)
                retired_here = True
                os.fsync(extension_fd)
            except Exception as exc:
                # A rename or directory-sync failure may already have moved
                # the exact file. Keep its journal and Recovery ID intact.
                raise GuardError(
                    "uncertain", "Guard retirement could not be confirmed; "
                    "Recheck saved Recovery ID before another action",
                    recovery_id=record["op"]) from exc

        def confirm_retirement():
            # The managed Guard is intentionally absent from the VHost SHA.
            # A separate byte-exact check must therefore cover this file,
            # including replacement immediately around renameat2.
            live = _bounded_file(extension_fd, filename,
                                 limit=MAX_INCLUDE, permissions=0o600)
            retired = _bounded_file(extension_fd, retired_name,
                                    limit=MAX_INCLUDE, permissions=0o600)
            if live is not None or retired != expected_retired:
                raise GuardError("concurrency", "Guard file changed after retirement")
            if retired_here:
                info = os.stat(retired_name, dir_fd=extension_fd,
                               follow_symlinks=False)
                if (info.st_dev, info.st_ino) != moved_identity:
                    raise GuardError("concurrency", "Guard file identity changed at retirement")

        def check_before_reload():
            try:
                confirm_retirement()
            except (ExtensionError, OSError) as exc:
                if retired_here:
                    try:
                        # A rollback reintroduces a *.conf included by Nginx.
                        # Inode identity and trusted metadata alone cannot
                        # authorize that: the SAME inode may have been edited
                        # in place after retirement. Only the original exact
                        # journal-owned bytes may be made live again.
                        rollback_bytes = _bounded_file(
                            extension_fd, retired_name,
                            limit=MAX_INCLUDE, permissions=0o600)
                        if (rollback_bytes is None
                                or rollback_bytes != expected_retired
                                or _sha(rollback_bytes) != record["include_sha"]):
                            raise GuardError(
                                "concurrency", "Retired Guard content changed; "
                                "cannot safely restore original filename")
                        rollback_stat = os.stat(
                            retired_name, dir_fd=extension_fd, follow_symlinks=False)
                        if (rollback_stat.st_dev, rollback_stat.st_ino) != moved_identity:
                            raise GuardError(
                                "concurrency", "Retired Guard inode replaced; "
                                "cannot safely restore original filename")
                        # Never replace a concurrently created live entry.
                        _rename_noreplace(extension_fd, retired_name, filename)
                        os.fsync(extension_fd)
                    except Exception as rollback:
                        raise GuardError(
                            "uncertain", "Unverified Guard retirement and safe "
                            "pathname recovery unavailable; inspect both files "
                            "using the saved Recovery ID (no Nginx reload)",
                            recovery_id=record["op"]) from rollback
                raise GuardError(
                    "concurrency", "Guard ownership changed during retirement; "
                    "no Nginx reload was attempted. Recheck saved Recovery ID",
                    recovery_id=record["op"]) from exc

        # Check immediately after rename, then again after the FINAL syntax
        # test. A successful nginx -t alone cannot approve a later VHost
        # edit or a modified retained Guard.
        check_before_reload()
        try:
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
        except Exception as exc:
            raise GuardError(
                "uncertain", "Final Nginx syntax check failed after Guard retirement; "
                "no reload was attempted. Recheck saved Recovery ID",
                recovery_id=record["op"]) from exc
        check_before_reload()
        try:
            final_source_sha = _source_safe(
                site, vhost_root=vhost_root, nginx_conf=nginx_conf)[0]
        except (ExtensionError, OSError) as exc:
            raise GuardError(
                "uncertain", "Native Nginx source became unreadable after Guard retirement; "
                "no reload was attempted. Recheck saved Recovery ID",
                recovery_id=record["op"]) from exc
        if final_source_sha != expected_vhost:
            raise GuardError(
                "uncertain", "Native source changed during final Nginx syntax check; "
                "no reload was attempted. Recheck saved Recovery ID",
                recovery_id=record["op"])
        try:
            _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
            _verified(site, record["op"], present=False, probe=probe,
                      ruleset=record["ruleset"])
            if _source_safe(site, vhost_root=vhost_root,
                            nginx_conf=nginx_conf)[0] != source_sha:
                raise GuardError("concurrency", "Native source drifted during security Restore")
            confirm_retirement()
        except Exception as exc:
            raise GuardError(
                "uncertain", "Security Restore unconfirmed; inspect saved recovery before retrying",
                recovery_id=record["op"]) from exc
        record["phase"] = "restored"
        try:
            _save_journal(data_fd, record)
        except Exception as exc:
            raise GuardError(
                "uncertain", "Security Restore completed; journal update unconfirmed",
                recovery_id=record["op"]) from exc
        if retained_bytes is not None or current is not None:
            try:
                # No longer included; journal contains exact immutable rule
                # identity. Cleanup never removes an unknown extension.
                if _bounded_file(extension_fd, retired_name,
                                 limit=MAX_INCLUDE, permissions=0o600) == _include(
                                     record["op"], record["ruleset"]):
                    os.unlink(retired_name, dir_fd=extension_fd)
                    os.fsync(extension_fd)
            except OSError:
                pass
        return _report(site, state="Restored", source_sha=source_sha,
                       journal=record, changed=True, runtime_verified=True,
                       read_only=False, reason="Managed guard removed; no old nonce served")
    finally:
        os.close(extension_fd)
