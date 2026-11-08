"""Guarded, opt-in native aaPanel stopped-site HTTP 503, without vendor hooks.

aaPanel 8.0.7 SiteStop comments every 'include' in its VHost, and SiteStart
rewrites literal /www/server/stop. A small inline, server-scope conditional
survives both transitions. The exact operator-approved HTML is assembled from
bounded Nginx set variables to avoid the Nginx 4KiB config-token limit.

Only the selected native VHost changes. A saved original, exact managed block
and journal allow scoped Restore without overwriting unrelated later edits.
No automatic enforcement, arbitrary Nginx target or TLS-default interception.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import time
from uuid import uuid4

from ach_customizer_status_inspect import _directory
from ach_customizer_status_extension import (
    DOMAIN, HASH, TOKEN, MAX_VHOST, VHOST_ROOT, NGINX, NGINX_CONF,
    ExtensionError, _bounded_file, _owned_dir, _sha, _write_exclusive, _nginx,
)
from ach_customizer_status_site_file import _server_directives

RECORD_PREFIX = "ach_customizer.stopped503."
STOP_ROOT = "/www/server/stop"
MAX_RECORD = 4096
MAX_RENDER = 32768
MAX_NGINX_DUMP = 2 * 1024 * 1024
SEPARATOR = b"    # ACh stopped503 "
MARKER = b"    #SSL-START"
ROOT_RE = re.compile(r"/[A-Za-z0-9_./-]{1,1023}\Z")
NOTE = ("Uses a selected native VHost server-scope conditional; aaPanel "
        "SiteStop/Start changes the native root but does not disable this hook. "
        "Shared Nginx syntax/reload required; HTTPS fallback is unchanged.")


def _valid_site(site, *, allow_stopped=True):
    if (not isinstance(site, dict) or type(site.get("id")) is not int or
            not 1 <= site["id"] <= 2147483647 or
            not isinstance(site.get("name"), str) or
            not DOMAIN.fullmatch(site["name"]) or
            not isinstance(site.get("path"), str) or
            not ROOT_RE.fullmatch(site["path"]) or
            "//" in site["path"] or ".." in site["path"].split("/") or
            site["path"] == STOP_ROOT or
            str(site.get("status")) not in (("0", "1") if allow_stopped else ("1",)) or
            {"name": site["name"], "port": 80} not in site.get("bound_domains", [])):
        raise ExtensionError("identity", "Selected aaPanel HTTP/80 site is not a supported native Stop target")


def _name(site):
    return site["name"] + ".conf"


def _journal_name(site):
    return RECORD_PREFIX + str(site["id"]) + ".json"


def _backup_name(site, op):
    return RECORD_PREFIX + str(site["id"]) + "." + op + ".backup"


def _native_source(site, raw, *, allow_managed=False):
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ExtensionError("source", "Native Nginx VHost is not UTF-8") from exc
    direct = _server_directives(text)
    root = STOP_ROOT if str(site["status"]) == "0" else site["path"]
    if (direct.count("server_name " + site["name"]) != 1 or
            sum(d.startswith("server_name ") for d in direct) != 1 or
            direct.count("root " + root) != 1 or
            sum(d.startswith("root ") for d in direct) != 1 or
            not any(d == "listen 80" for d in direct) or
            raw.count(MARKER) != 1 or
            text.count("\nserver\n") > 1):
        raise ExtensionError("source", "Native VHost root, Host or server scope is not verified")
    if not allow_managed and (SEPARATOR in raw or b"ach_stop_" in raw):
        raise ExtensionError("conflict", "Existing stopped-site rule has no verified recovery ownership")
    return root


def _record_load(data_fd, site):
    raw = _bounded_file(data_fd, _journal_name(site), limit=MAX_RECORD,
                        permissions=0o600)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ExtensionError("recovery", "Stopped-site recovery record unreadable") from exc
    keys = {"schema", "site_id", "site_name", "site_root", "op", "phase",
            "before_sha", "after_sha", "block_sha", "render_sha", "body_sha", "backup"}
    if (not isinstance(value, dict) or set(value) != keys or
            type(value["schema"]) is not int or value["schema"] != 1 or
            value["site_id"] != site["id"] or value["site_name"] != site["name"] or
            value["site_root"] != site["path"] or
            not isinstance(value["op"], str) or not TOKEN.fullmatch(value["op"]) or
            value["phase"] not in ("prepared", "applied", "restoring", "restored") or
            any(not isinstance(value[k], str) or not HASH.fullmatch(value[k])
                for k in ("before_sha", "after_sha", "block_sha", "render_sha", "body_sha")) or
            value["backup"] != _backup_name(site, value["op"])):
        raise ExtensionError("recovery", "Stopped-site recovery identity invalid")
    return value


def _record_save(fd, site, entry):
    payload = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_RECORD:
        raise ExtensionError("recovery", "Stopped-site journal too large")
    name = "." + _journal_name(site) + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, name, payload, 0o600)
    os.replace(name, _journal_name(site), src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def _backed(fd, site, record):
    raw = _bounded_file(fd, record["backup"], limit=MAX_VHOST, permissions=0o600)
    if raw is None or _sha(raw) != record["before_sha"]:
        raise ExtensionError("recovery", "Original native VHost recovery backup invalid")
    return raw


def _split_safe(html, site):
    """Keep aaPanel's raw SiteStop/SiteStart substitutions out of managed data.

    Nginx 'set' expressions expand $, so represent that character as an
    equivalent HTML entity. Other substring-sensitive words can be split
    across distinct variables without changing the response bytes.
    """
    if not isinstance(html, str) or not 0 < len(html.encode("utf-8")) <= MAX_RENDER:
        raise ExtensionError("render", "Invalid or oversized stopped-site HTML")
    served = html.replace("$", "&#36;")
    parts = []
    unsafe = ("include", "#include", STOP_ROOT, site["path"])
    pending = served
    while pending:
        stop = min(len(pending), 700)
        # Force a split *inside* any reserved token within the next segment.
        for word in unsafe:
            start = pending.find(word)
            if 0 <= start < stop:
                stop = min(stop, max(1, start + max(1, len(word) // 2)))
        parts.append(pending[:stop])
        pending = pending[stop:]
        if len(parts) > 160:
            raise ExtensionError("render", "Stopped-site HTML exceeds Nginx inline capacity")
    if any(word in part for word in unsafe for part in parts):
        raise ExtensionError("render", "Cannot safely partition native Stop HTML")
    return served, parts


def _request_host_pattern(site):
    """Anchor the *raw* request Host to native domain rows, never $host.

    Nginx $host falls back to server_name when the request omits Host; this
    would authorize unknown/default-server traffic. The raw $http_host stays
    empty for such requests. Include normal 80/443 authority ports and any
    explicitly recorded site-bound ports, without accepting other hostnames.
    """
    domains = site.get("bound_domains")
    if not isinstance(domains, list) or not domains:
        raise ExtensionError("identity", "Native website Host bindings unavailable")
    names = set()
    ports = {80, 443}
    for binding in domains:
        if not isinstance(binding, dict):
            raise ExtensionError("identity", "Invalid native website Host binding")
        name, port = binding.get("name"), binding.get("port")
        if (not isinstance(name, str) or not DOMAIN.fullmatch(name) or
                type(port) is not int or not 1 <= port <= 65535):
            raise ExtensionError("identity", "Invalid native website Host binding")
        names.add(name.lower())
        ports.add(port)
    if site["name"].lower() not in names:
        raise ExtensionError("identity", "Canonical website Host is not bound to this site")
    patterns = "|".join(re.escape(name) for name in sorted(names))
    allowed_ports = "|".join(str(port) for port in sorted(ports))
    return r"^(?:" + patterns + r")\.?(?::(?:" + allowed_ports + r"))?$"


def _managed(site, html, op):
    if not TOKEN.fullmatch(op):
        raise ExtensionError("input", "Invalid stop operation")
    served, parts = _split_safe(html, site)
    prefix = "ach_stop_" + op + "_"
    lines = ["    # ACh stopped503 begin " + op]
    for index, part in enumerate(parts):
        # Nginx quoted directive arguments preserve UTF-8, escaped quotes and
        # physical linebreaks; each token stays below the 4KiB lexer limit.
        value = part.replace("\\", "\\\\").replace('"', '\\"')
        lines.append('    set $' + prefix + str(index) + ' "' + value + '";')
    value = "".join("$" + prefix + str(i) for i in range(len(parts)))
    allowed_host = _request_host_pattern(site)
    # A raw server-scope return inherits aaPanel's application/octet-stream
    # default, making real browsers download the HTML. Rewrite to an internal
    # exact location with its OWN text/html MIME while preserving HTTP503.
    # The negative lookahead excludes the internal target to prevent loops.
    basename = ".__ach_stop_doc_" + op + ".html"
    route = "/" + basename
    # Combine the *raw* HTTP authority and current native root in a single
    # short Nginx variable. An @ separator cannot occur in a valid bound
    # hostname. Avoid nested ifs and long per-operation variable identifiers
    # (native Nginx variables_hash_bucket_size remains unchanged).
    guarded_host_and_root = _request_host_pattern(site)[:-1] + r"@/www/server/st[o]p$"
    lines.extend((
        '    set $achstopgate "$http_host@$document_root";',
        '    if ($achstopgate ~* "' + guarded_host_and_root + '") {',
        '        rewrite ^/(?!\\.' + basename[1:-5] + '\\.html$) ' + route + ' last;',
        '    }',
        '    location = ' + route + ' {',
        '        internal;',
        '        default_type text/html;',
        '        return 503 "' + value + '";',
        '    }',
        "    # ACh stopped503 end " + op,
        "",
    ))
    block = "\n".join(lines).encode("utf-8")
    if any(t in block for t in (b"/www/server/stop", b"include", site["path"].encode())):
        raise ExtensionError("render", "Native SiteStop may rewrite managed source")
    if len(block) > MAX_VHOST // 2:
        raise ExtensionError("render", "Stopped-site Nginx inline fragment too large")
    return block, _sha(served.encode("utf-8"))


def _block_bounds(raw, op):
    start = ("    # ACh stopped503 begin " + op + "\n").encode()
    end = ("    # ACh stopped503 end " + op + "\n").encode()
    if raw.count(start) != 1 or raw.count(end) != 1:
        raise ExtensionError("recovery", "Managed stopped-site block is missing or duplicated")
    i = raw.index(start)
    j = raw.index(end, i + len(start)) + len(end)
    return i, j


def _loaded(site, raw, *, nginx=NGINX, conf=NGINX_CONF, runner=None):
    runner = runner or subprocess.run
    try:
        result = runner([nginx, "-T", "-c", conf],
                        capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExtensionError("source", "Nginx loaded-site source unavailable") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_NGINX_DUMP:
        raise ExtensionError("source", "Nginx loaded-site source invalid or oversized")
    title = ("# configuration file " + VHOST_ROOT + "/" + _name(site) + ":\n").encode()
    chunks = result.stdout.split(title)
    if len(chunks) != 2:
        raise ExtensionError("source", "Native VHost is not loaded exactly once")
    body = chunks[1].split(b"\n# configuration file ", 1)[0]
    if body.rstrip() != raw.rstrip():
        raise ExtensionError("source", "Loaded Nginx VHost differs from native file")
    return True


def _probe(site, *, stopped):
    conn = http.client.HTTPConnection("127.0.0.1", 80, timeout=3.5)
    try:
        # The native aaPanel stop root serves its index at "/" with HTTP200
        # after Restore, but returns 404 for arbitrary missing paths. Probe
        # exactly that public stop document across both states.
        path = "/" if stopped else "/.__ach_stop_probe_" + uuid4().hex
        conn.request("GET", path,
                     headers={"Host": site["name"], "Accept-Encoding": "identity",
                              "Cache-Control": "no-cache", "Connection": "close"})
        result = conn.getresponse()
        content_type = result.getheader("Content-Type", "")
        # Running WordPress pages and the aaPanel native /stop/index.html
        # (about 58 KiB) can be larger than the bounded ACh template. Only
        # our STOPPED HTTP503 proof needs full bytes; native Restore HTTP200
        # must verify its status without reading arbitrary large native HTML.
        if not stopped or result.status != 503:
            return result.status, None, content_type
        if result.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ExtensionError("postcheck", "Stopped-site response is compressed")
        payload = result.read(MAX_RENDER + 1)
        if len(payload) > MAX_RENDER:
            raise ExtensionError("postcheck", "Stopped-site response body too large")
        return result.status, _sha(payload), content_type
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise ExtensionError("probe", "Selected native site HTTP/80 probe unavailable") from exc
    finally:
        conn.close()


def _settle(site, code, body_sha=None, *, probe=None, stopped=None):
    deadline = time.monotonic() + 10
    stable = 0
    while True:
        observed = (probe or _probe)(site, stopped=(code == 503 if stopped is None else stopped))
        match = (observed[0] == code and (body_sha is None or observed[1] == body_sha) and
                 (code != 503 or observed[2].split(";", 1)[0].strip().lower() == "text/html"))
        stable = stable + 1 if match else 0
        if stable >= 3:
            return observed
        if time.monotonic() >= deadline:
            raise ExtensionError("postcheck", "Native stopped-site response did not settle")
        time.sleep(0.25)


def _publish(fd, name, before, after, op):
    if _bounded_file(fd, name, limit=MAX_VHOST, permissions=0o600) != before:
        raise ExtensionError("concurrency", "Native VHost changed before publication")
    stage = "." + name + "." + op + "." + uuid4().hex + ".stage"
    _write_exclusive(fd, stage, after, 0o600)
    if _bounded_file(fd, name, limit=MAX_VHOST, permissions=0o600) != before:
        raise ExtensionError("concurrency", "Native VHost changed during publication")
    os.replace(stage, name, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)
    if _bounded_file(fd, name, limit=MAX_VHOST, permissions=0o600) != after:
        raise ExtensionError("uncertain", "Published VHost identity not verified", recovery_id=op)


def _verify_after_reload(fd, site, expected, *, nginx, conf, runner):
    """Do not finalize a journal phase against a changed native VHost.

    The disk bytes and current Nginx -T source must both match *after* the
    reload and runtime probe. This does not assert that every old worker
    generation has already exited.
    """
    actual = _bounded_file(fd, _name(site), limit=MAX_VHOST, permissions=0o600)
    if actual != expected:
        raise ExtensionError("concurrency", "Native VHost changed after Nginx reload")
    _loaded(site, expected, nginx=nginx, conf=conf, runner=runner)
    if _bounded_file(fd, _name(site), limit=MAX_VHOST, permissions=0o600) != expected:
        raise ExtensionError("concurrency", "Native VHost changed during final Nginx inspection")


def _response(site, record, sha, source_html, body_sha, state, *,
              read_only=True, changed=False, runtime_verified=False):
    return {"schema": 1, "mode": "native_stopped_http503",
            "state": state, "site_id": site["id"], "site_key": site["name"],
            "site_status": str(site["status"]), "vhost_sha256": sha,
            "rendered_sha256": _sha(source_html.encode("utf-8")),
            "served_sha256": body_sha, "recovery_id": record["op"] if record else None,
            "read_only": read_only, "changed": changed,
            "runtime_verified": runtime_verified,
            "proof_kind": (
                "stopped_http503" if state == "Applied" and runtime_verified else
                "native_http200" if state == "Restored" and runtime_verified
                and str(site["status"]) == "0" else
                "running_non503" if state == "Restored" and runtime_verified else
                "source_only" if state in ("Source Ready", "Armed", "Restored")
                else "none"
            ),
            "impact": NOTE}


def manage_stopped(action, site, html, *, data_fd, expected_vhost=None,
                   expected_render=None, expected_recovery=None,
                   vhost_root=VHOST_ROOT, nginx=NGINX, nginx_conf=NGINX_CONF,
                   runner=None, probe=None):
    if action not in ("recheck", "apply", "restore"):
        raise ExtensionError("input", "Unsupported stopped-site action")
    _valid_site(site, allow_stopped=True)
    _owned_dir(data_fd)
    fd = _directory(vhost_root)
    try:
        _owned_dir(fd)
        before = _bounded_file(fd, _name(site), limit=MAX_VHOST, permissions=0o600)
        if before is None:
            raise ExtensionError("source", "Native website VHost unavailable")
        record = _record_load(data_fd, site)
        _native_source(site, before, allow_managed=record is not None)
        current_sha = _sha(before)
        if record and record["phase"] != "restored":
            _backed(data_fd, site, record)
        if action == "recheck":
            if record is None:
                _loaded(site, before, nginx=nginx, conf=nginx_conf, runner=runner)
                state, verified = "Source Ready", False
                body_sha = _managed(site, html, "a"*32)[1]
            elif record["phase"] == "restored":
                # A restored journal is not proof that a later native/manual
                # change has not reintroduced a similarly named rule.
                # A foreign rule after a completed Restore has no owned
                # active recovery to remove. Report a non-actionable Conflict
                # rather than inviting a Restore that must fail.
                state = "Conflict" if (SEPARATOR in before or b"ach_stop_" in before) else "Restored"
                verified = False
                body_sha = record["body_sha"]
            elif record["phase"] != "applied":
                state, verified = "Recovery Required", False
                body_sha = record["body_sha"]
            else:
                try:
                    i, j = _block_bounds(before, record["op"])
                    owned = before[i:j]
                    if _sha(owned) != record["block_sha"]:
                        raise ExtensionError("recovery", "Stopped-site managed block changed")
                    _loaded(site, before, nginx=nginx, conf=nginx_conf, runner=runner)
                    original = _backed(data_fd, site, record)
                    expected_running = original.replace(MARKER, owned + MARKER, 1)
                    # The only supported native lifecycle transformation is
                    # aaPanel 8.0.7's exact root replacement and include
                    # commenting. Unrelated changes must be shown to Owner.
                    expected = (expected_running.replace(site["path"].encode(), STOP_ROOT.encode())
                                .replace(b"include", b"#include") if str(site["status"]) == "0"
                                else expected_running)
                    drift = before != expected
                    if str(site["status"]) == "0":
                        observed = (probe or _probe)(site, stopped=True)
                        route_matches = (observed[0] == 503 and
                                         observed[1] == record["body_sha"] and
                                         observed[2].split(";", 1)[0].strip().lower() == "text/html")
                        # A matching HTTP response alone does not prove the
                        # managed source is unchanged. Keep Needs Review and
                        # its Recovery ID, without claiming verified delivery.
                        verified = route_matches and not drift
                        state = "Applied" if verified else "Needs Review"
                    else:
                        verified, state = False, "Needs Review" if drift else "Armed"
                except ExtensionError:
                    verified, state = False, "Recovery Required"
                body_sha = record["body_sha"]
            return _response(site, record, current_sha, html, body_sha, state,
                             runtime_verified=verified)

        if expected_vhost != current_sha:
            raise ExtensionError("concurrency", "Native VHost changed; Recheck before writing")
        if action == "apply":
            _valid_site(site, allow_stopped=False)
            if record and record["phase"] != "restored":
                raise ExtensionError("recovery", "Previous stopped-site operation needs Restore")
            # The retained Restored journal is not ownership of a later
            # operator/foreign rule. Never layer a second managed 503 block
            # on top of an unrecognized one.
            if SEPARATOR in before or b"ach_stop_" in before:
                raise ExtensionError("conflict", "Existing stopped-site rule is not approved for replacement")
            if expected_render != _sha(html.encode("utf-8")):
                raise ExtensionError("concurrency", "Stopped-site branding changed since Recheck")
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            _loaded(site, before, nginx=nginx, conf=nginx_conf, runner=runner)
            operation = uuid4().hex
            block, body_sha = _managed(site, html, operation)
            new = before.replace(MARKER, block + MARKER, 1)
            if len(new) > MAX_VHOST:
                raise ExtensionError("render", "Managed native VHost exceeds size bound")
            entry = {"schema": 1, "site_id": site["id"], "site_name": site["name"],
                     "site_root": site["path"], "op": operation, "phase": "prepared",
                     "before_sha": current_sha, "after_sha": _sha(new),
                     "block_sha": _sha(block), "render_sha": expected_render,
                     "body_sha": body_sha, "backup": _backup_name(site, operation)}
            _write_exclusive(data_fd, entry["backup"], before, 0o600)
            _record_save(data_fd, site, entry)
            try:
                _publish(fd, _name(site), before, new, operation)
                _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
                _loaded(site, new, nginx=nginx, conf=nginx_conf, runner=runner)
                _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
                # The rule is dormant while running; check the ordinary HTTP
                # route remains reachable without making a fake 503 claim.
                observed = (probe or _probe)(site, stopped=False)
                if observed[0] == 503:
                    raise ExtensionError("postcheck", "Running website unexpectedly returns HTTP503")
                _verify_after_reload(fd, site, new, nginx=nginx,
                                     conf=nginx_conf, runner=runner)
                entry["phase"] = "applied"
                _record_save(data_fd, site, entry)
            except Exception as exc:
                # A syntax-rejected owned file must never be left as the next
                # Nginx reload candidate when its bytes are still exclusively
                # ours. Revert only this exact candidate; never overwrite a
                # concurrent operator edit or silently drop saved recovery.
                if (isinstance(exc, ExtensionError) and exc.stage == "syntax" and
                        _bounded_file(fd, _name(site), limit=MAX_VHOST, permissions=0o600) == new):
                    try:
                        _publish(fd, _name(site), new, before, operation)
                        _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
                        _loaded(site, before, nginx=nginx, conf=nginx_conf, runner=runner)
                        entry["phase"] = "restored"
                        _record_save(data_fd, site, entry)
                    except Exception as rollback_exc:
                        raise ExtensionError("uncertain", "Rejected Nginx source rollback uncertain; Recheck recovery",
                                             recovery_id=operation) from rollback_exc
                    raise ExtensionError("syntax", "Nginx rejected stopped-site rule; original native source restored",
                                         recovery_id=operation) from exc
                raise ExtensionError("uncertain",
                                     "Stopped-site Apply uncertain; Recheck recovery before retrying",
                                     recovery_id=operation) from exc
            return _response(site, entry, _sha(new), html, body_sha, "Armed",
                             changed=True, read_only=False, runtime_verified=False)

        if not record or record["phase"] == "restored":
            raise ExtensionError("recovery", "No saved stopped-site rule to Restore")
        op = record["op"]
        if expected_recovery != op:
            raise ExtensionError("concurrency", "Stopped-site recovery identity changed")
        saved = _backed(data_fd, site, record)
        without_rule = (saved if str(site["status"]) == "1" else
                        saved.replace(site["path"].encode(), STOP_ROOT.encode())
                             .replace(b"include", b"#include"))
        # A failed publication or an interrupted Restore can leave the
        # journal prepared/restoring after the exact managed block has
        # disappeared. Reconcile only if the full native source equals the
        # verified saved baseline for this native SiteStop/Start state.
        block_present = SEPARATOR in before
        if block_present:
            i, j = _block_bounds(before, op)
            if _sha(before[i:j]) != record["block_sha"]:
                raise ExtensionError("recovery", "Managed stopped-site block changed; manual review")
            original = before[:i] + before[j:]
        elif before == without_rule:
            original = before
        else:
            raise ExtensionError("recovery", "Managed block absent and native VHost differs from recovery")
        _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
        _loaded(site, before, nginx=nginx, conf=nginx_conf, runner=runner)
        entry = dict(record, phase="restoring")
        _record_save(data_fd, site, entry)
        try:
            if block_present:
                _publish(fd, _name(site), before, original, op)
            _nginx("-t", nginx=nginx, conf=nginx_conf, runner=runner)
            _loaded(site, original, nginx=nginx, conf=nginx_conf, runner=runner)
            _nginx("reload", nginx=nginx, conf=nginx_conf, runner=runner)
            if str(site["status"]) == "0":
                # Native aaPanel stop serves its original page with HTTP200.
                _settle(site, 200, probe=probe, stopped=True)
            else:
                if (probe or _probe)(site, stopped=False)[0] == 503:
                    raise ExtensionError("postcheck", "Restored running site returns HTTP503")
            _verify_after_reload(fd, site, original, nginx=nginx,
                                 conf=nginx_conf, runner=runner)
            entry["phase"] = "restored"
            _record_save(data_fd, site, entry)
            # Backup is not needed after a verified Restore; keep the journal.
            retained = _bounded_file(data_fd, entry["backup"], limit=MAX_VHOST,
                                     permissions=0o600)
            if retained is not None and _sha(retained) == record["before_sha"]:
                os.unlink(entry["backup"], dir_fd=data_fd)
                os.fsync(data_fd)
        except Exception as exc:
            raise ExtensionError("uncertain",
                                 "Stopped-site Restore uncertain; inspect saved recovery",
                                 recovery_id=op) from exc
        return _response(site, entry, _sha(original), html, record["body_sha"],
                         "Restored", changed=block_present, read_only=False,
                         runtime_verified=True)
    finally:
        os.close(fd)
