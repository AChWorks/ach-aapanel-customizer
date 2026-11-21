"""One-click native WordPress Cache + Nginx Helper connection.

The native aaPanel plugin owns Nginx and filesystem setup; WordPress owns its
plugin activation/options. No vendor/plugin core source is modified, no worker
is installed, and unrelated sites are never a purge target.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from ach_customizer_cache_manage import (
    CacheManageError, manage_cache, preview_cache_activation,
)
from ach_customizer_cache_policy import CACHE_ROOT
from ach_customizer_state import DATA_DIR, _open_state_dir

WORDPRESS_CONFIG = "wp-config.php"
USER_INI = ".user.ini"
FILE_PREFIX = "ach_customizer.nginx-helper."
HEX = re.compile(r"[0-9a-f]{32}\Z")
WP_CONSTANT = re.compile(
    rb"(?m)^([ \t]*define\([ \t]*['\"]RT_WP_NGINX_HELPER_CACHE_PATH['\"][ \t]*,"
    rb"[ \t]*['\"])([^'\"\r\n]+)(['\"][ \t]*\);[ \t]*\r?\n?)$")
BASEDIR = re.compile(rb"(?m)^(open_basedir=)([^\r\n]*)(\r?\n|$)")
# The site path and cache path are not user-supplied filesystem authorities.
PHP_BRIDGE = r'''
define('WP_ADMIN', true);
require 'wp-load.php';
require_once ABSPATH . 'wp-admin/includes/plugin.php';
$input = json_decode(stream_get_contents(STDIN), true);
if (!is_array($input) || !in_array($input['action'] ?? null,
        ['inspect','connect','suspend','restore'], true)) {
    fwrite(STDERR, "Invalid native WordPress integration command\n"); exit(10);
}
$helper = 'nginx-helper/nginx-helper.php';
$bridge = 'ach-aapanel-bridge/ach-aapanel-bridge.php';
foreach ([$helper, $bridge] as $plugin) {
    if (!is_file(WP_PLUGIN_DIR . '/' . $plugin)) {
        fwrite(STDERR, "Required WordPress plugin missing: ".$plugin."\n"); exit(11);
    }
}
$existing = get_site_option('rt_wp_nginx_helper_options', []);
if (!is_array($existing)) $existing = [];
$keys = ['cache_method','enable_purge','purge_method'];
$previous = [];
foreach ($keys as $key) {
    $previous[$key] = array_key_exists($key, $existing) ? $existing[$key] : null;
}
$present = [
    'nginx_helper' => is_plugin_active($helper),
    'bridge' => is_plugin_active($bridge),
    'options_present' => get_site_option('rt_wp_nginx_helper_options') !== false,
    'options' => $previous,
    'constant' => defined('RT_WP_NGINX_HELPER_CACHE_PATH')
        ? RT_WP_NGINX_HELPER_CACHE_PATH : null,
];
if ($input['action'] === 'connect') {
    foreach ([$helper,$bridge] as $plugin) {
        if (!is_plugin_active($plugin)) {
            $error = activate_plugin($plugin);
            if (is_wp_error($error)) {
                fwrite(STDERR, "WordPress activation failed for ".$plugin.": ".
                    $error->get_error_message()."\n"); exit(12);
            }
        }
    }
    $existing['cache_method'] = 'enable_fastcgi';
    $existing['purge_method'] = 'unlink_files';
    $existing['enable_purge'] = 1;
    update_site_option('rt_wp_nginx_helper_options', $existing);
}
if ($input['action'] === 'suspend') {
    $existing['enable_purge'] = 0;
    update_site_option('rt_wp_nginx_helper_options', $existing);
}
if ($input['action'] === 'restore') {
    $saved = $input['previous'] ?? null;
    if (!is_array($saved) || !is_array($saved['options'] ?? null)) exit(13);
    foreach ($keys as $key) {
        if (!array_key_exists($key, $saved['options'])) exit(14);
        if ($saved['options'][$key] === null) unset($existing[$key]);
        else $existing[$key] = $saved['options'][$key];
    }
    // Do not leave the vendor Purge All enabled after returning the WP
    // constant to aaPanel's shared cache root.
    $existing['enable_purge'] = 0;
    update_site_option('rt_wp_nginx_helper_options', $existing);
    foreach ([$bridge,$helper] as $plugin) {
        $was_active = ($plugin === $helper)
            ? ($saved['nginx_helper'] ?? true) : ($saved['bridge'] ?? true);
        if ($was_active === false && is_plugin_active($plugin)) {
            deactivate_plugins($plugin);
        }
    }
}
$result = [
    'active_helper' => is_plugin_active($helper),
    'active_bridge' => is_plugin_active($bridge),
    'options' => $input['action'] === 'inspect'
        ? $previous : array_intersect_key(get_site_option('rt_wp_nginx_helper_options', []),
                                          array_flip($keys)),
    'previous' => $present,
];
echo "ACH_WORDPRESS_CACHE_RESULT=", json_encode($result, JSON_UNESCAPED_SLASHES), "\n";
'''


class WordpressCacheError(RuntimeError):
    def __init__(self, stage, message, recovery_id=None):
        super().__init__(message)
        self.stage = stage
        self.recovery_id = recovery_id


def _php(site, php_version, command, *, previous=None):
    root = site["path"]
    binary = "/www/server/php/" + php_version + "/bin/php"
    if not Path(binary).is_file():
        raise WordpressCacheError("runtime", "Selected site's PHP CLI is unavailable")
    # Match the real aaPanel PHP-FPM/Cache writer, not document-root owner.
    owner = "www"
    try:
        result = subprocess.run(
            ["runuser", "-u", owner, "--", binary, "-d", "display_errors=stderr",
             "-r", PHP_BRIDGE],
            cwd=root, input=json.dumps({"action": command, "previous": previous}),
            text=True, capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WordpressCacheError("wordpress", "WordPress CLI setup unavailable: " +
                                  type(exc).__name__) from exc
    if result.returncode:
        # The names of missing plugins and WP errors are actionable; the
        # complete wp-config and DB credentials are never logged.
        message = (result.stderr or "").strip().splitlines()
        raise WordpressCacheError(
            "wordpress", "WordPress " + command + " failed: " +
            (message[-1][:350] if message else "PHP exit " + str(result.returncode)))
    try:
        lines = [line[len("ACH_WORDPRESS_CACHE_RESULT="):] for line in result.stdout.splitlines()
                 if line.startswith("ACH_WORDPRESS_CACHE_RESULT=")]
        data = json.loads(lines[-1]) if len(lines) == 1 else None
    except ValueError as exc:
        raise WordpressCacheError("wordpress", "WordPress did not return setup status") from exc
    if not isinstance(data, dict):
        raise WordpressCacheError("wordpress", "Unexpected WordPress setup response")
    return data


def _site_extension_line(site):
    from ach_customizer_cache_manage import VHOST_ROOT, SITE_KEY
    if not SITE_KEY.fullmatch(site["name"]):
        raise WordpressCacheError("identity", "Invalid native website key")
    return ("    include " + VHOST_ROOT + "/extension/" +
            site["name"] + "/*.conf;\n").encode()


def _bootstrap_site_extension(site):
    """Fill the specific native aaPanel new-site template gap, not its PHP core.

    Called ONLY after the native Cache adapter itself verified the exact
    missing-extension-only case. Native Nginx PHP/rewrites are preserved.
    """
    from ach_customizer_cache_manage import VHOST_ROOT, _missing_extension_inventory
    _missing_extension_inventory(site, VHOST_ROOT)
    raw, _ = _read_file(VHOST_ROOT, site["name"] + ".conf")
    line = _site_extension_line(site)
    if raw.count(line) == 1:
        return False
    # Place the include immediately after the native site's own root line,
    # exactly as aaPanel regenerates it. Inserting before PHP instead can
    # leave a Restored Cache journal with spurious drift on regeneration.
    root = re.compile(rb"(?m)^[ \t]*root[ \t]+" +
                      re.escape(site["path"].encode()) + rb";[ \t]*\r?\n")
    positions = list(root.finditer(raw))
    if len(positions) != 1:
        raise WordpressCacheError("compatibility",
            "Registered native WordPress VHost root line is not unique")
    # Do not add the extension when aaPanel has competing extension includes.
    if b"/extension/" in raw or raw.count(b"include enable-php-") != 1:
        raise WordpressCacheError("compatibility", "Native extension source requires review")
    extension_parent = Path(VHOST_ROOT) / "extension"
    if not extension_parent.is_dir() or extension_parent.is_symlink():
        raise WordpressCacheError("compatibility", "Native extension directory is unavailable")
    site_extension = extension_parent / site["name"]
    if site_extension.is_symlink():
        raise WordpressCacheError("compatibility", "Native site extension is redirected")
    if not site_extension.exists():
        site_extension.mkdir(mode=0o755)
    if not site_extension.is_dir():
        raise WordpressCacheError("compatibility", "Native site extension is not a directory")
    after = raw[:positions[0].end()] + line + raw[positions[0].end():]
    _replace_file(VHOST_ROOT, site["name"] + ".conf", raw, after)
    # The existing native Cache Apply validates Nginx -t and performs the
    # one necessary reload; no intermediate reload is needed here.
    return True


def _reload_php(version):
    """Refresh per-site .user.ini for the selected shared PHP-FPM service."""
    try:
        result = subprocess.run(
            ["systemctl", "reload", "php-fpm-" + version],
            capture_output=True, text=True, timeout=25, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WordpressCacheError(
            "php", "PHP-FPM reload failed after site configuration change") from exc
    if result.returncode:
        raise WordpressCacheError(
            "php", "PHP-FPM reload rejected; inspect the selected PHP service")


@contextmanager
def _site_lock(site, data_dir):
    """One scoped setup at a time; reuse the native Cache manager's own lock."""
    path = os.path.join(data_dir, FILE_PREFIX + str(site["id"]) + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o600):
            raise WordpressCacheError("ownership", "Untrusted WordPress setup lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WordpressCacheError(
                "concurrency", "Another WordPress Cache setup is in progress") from exc
        yield
    finally:
        os.close(fd)


def _site_root(site, public):
    from ach_customizer_cache_bridge import _docroot
    fd = _docroot(site, public)
    os.close(fd)
    root = site["path"]
    if os.path.realpath(root) != root:
        raise WordpressCacheError("identity", "WordPress document root is not canonical")
    return root


def _read_file(root, name):
    path = os.path.join(root, name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        identity = os.fstat(fd)
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
            raise WordpressCacheError("ownership", "Site configuration file is not regular")
        contents = os.read(fd, 1024 * 1024 + 1)
        if len(contents) > 1024 * 1024:
            raise WordpressCacheError("compatibility", "Site configuration file is oversized")
        if os.stat(path, follow_symlinks=False).st_ino != identity.st_ino:
            raise WordpressCacheError("concurrency", "Site configuration changed during inspection")
        return contents, identity
    finally:
        os.close(fd)


def _replace_file(root, name, before, after, *, immutable=False):
    """Atomic exact-source replacement of only a registered WordPress file."""
    if before == after:
        return False
    current, meta = _read_file(root, name)
    if current != before:
        if current == after:
            return False
        raise WordpressCacheError("concurrency", name + " was modified; recheck before setup")
    path = os.path.join(root, name)
    if immutable:
        subprocess.run(["chattr", "-i", path], capture_output=True, check=True)
    temporary = os.path.join(root, "." + name + ".achcache-" + uuid4().hex)
    staged = False
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchown(fd, meta.st_uid, meta.st_gid)
            os.fchmod(fd, stat.S_IMODE(meta.st_mode))
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(after)
                stream.flush()
            os.fsync(fd)
        finally:
            os.close(fd)
        verified, _ = _read_file(root, name)
        if verified != before:
            raise WordpressCacheError("concurrency", name + " changed before replacement")
        os.replace(temporary, path)
        staged = True
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if not staged:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        if immutable:
            subprocess.run(["chattr", "+i", path], capture_output=True, check=True)
    return True


def _immutable(path):
    try:
        flags = subprocess.run(["lsattr", "-d", path], text=True,
                               capture_output=True, timeout=5, check=True).stdout.split()[0]
    except (OSError, subprocess.SubprocessError, IndexError) as exc:
        raise WordpressCacheError("filesystem", "Cannot inspect site's immutable PHP file") from exc
    return "i" in flags


def _edits(site, original=None):
    root = site["path"]
    cache = CACHE_ROOT + "/site-" + str(site["id"])
    config, _ = _read_file(root, WORDPRESS_CONFIG)
    matches = list(WP_CONSTANT.finditer(config))
    if len(matches) != 1:
        raise WordpressCacheError("compatibility", "Expected one simple Nginx Helper cache-path constant in wp-config.php")
    existing = matches[0].group(2).decode("utf-8")
    if existing not in (cache, "/www/server/fastcgi_cache"):
        raise WordpressCacheError("compatibility", "WordPress uses a custom Nginx Helper cache path; review before changing")
    config_after = (config[:matches[0].start(2)] + cache.encode() +
                    config[matches[0].end(2):])
    ini, _ = _read_file(root, USER_INI)
    base = list(BASEDIR.finditer(ini))
    if len(base) != 1:
        raise WordpressCacheError("compatibility", "Expected one open_basedir in the site's .user.ini")
    raw = base[0].group(2).decode("utf-8")
    segments = raw.split(":")
    if any(not part for part in segments):
        raise WordpressCacheError("compatibility", "Malformed per-site PHP open_basedir")
    target = cache + "/"
    ini_after = (ini if target in segments else
                 ini[:base[0].start(2)] + (raw + ":" + target).encode() +
                 ini[base[0].end(2):])
    return {"wp_before": config, "wp_after": config_after,
            "ini_before": ini, "ini_after": ini_after,
            "ini_immutable": _immutable(os.path.join(root, USER_INI))}


def _journal_name(site):
    return FILE_PREFIX + str(site["id"]) + ".json"


def _load(site, data_dir):
    path = os.path.join(data_dir, _journal_name(site))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o600:
            raise WordpressCacheError("recovery", "Untrusted WordPress Cache setup journal")
        record = json.loads(os.read(fd, 16384))
        if (not isinstance(record, dict) or record.get("schema") != 1
                or record.get("site_id") != site["id"]
                or record.get("site_key") != site["name"]
                or record.get("wp_root") != site["path"]):
            raise WordpressCacheError("recovery", "WordPress Cache setup journal belongs to another site identity")
        return record
    finally:
        os.close(fd)


def _save(site, record, data_dir):
    path = os.path.join(data_dir, _journal_name(site))
    staged = path + "." + uuid4().hex + ".tmp"
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "w", closefd=False) as output:
            json.dump(record, output, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(staged, path)
    directory = os.open(data_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _native_record(site, public):
    current = manage_cache("recheck", site, public)
    if current["state"] not in ("Applied", "Unmanaged", "Restored"):
        raise WordpressCacheError("cache", "Native Cache recovery needs review before WordPress setup",
                                  current.get("recovery_id"))
    return current


def setup(site, public, *, data_dir=DATA_DIR):
    """One operator click; successive calls finish prior partial stages."""
    with _site_lock(site, data_dir):
        return _setup_locked(site, public, data_dir=data_dir)


def _setup_locked(site, public, *, data_dir):
    root = _site_root(site, public)
    record = _load(site, data_dir)
    cache_status = _native_record(site, public)
    was_connected = bool(record and record["phase"] == "connected"
                         and cache_status["state"] == "Applied")
    if record is not None and record["phase"] == "restored":
        # Both a fully restored native Cache and a Cache that predates this
        # connector can be connected again without removing foreign state.
        if (cache_status["state"] == "Restored" or
                cache_status["state"] == "Applied" and not record.get("cache_owned", True)):
            record = None
        else:
            raise WordpressCacheError("recovery",
                "Native Cache recovery differs from the previous WordPress connection")
    elif cache_status["state"] == "Restored" and record is not None:
        raise WordpressCacheError("recovery",
            "Complete the previous WordPress setup recovery before reconnecting")
    if cache_status["state"] in ("Unmanaged", "Restored"):
        from ach_customizer_cache_audit import inspect_site_fastcgi_cache
        native = inspect_site_fastcgi_cache(public, site["id"], site["name"])
        version = native.get("php_version")
        if version not in ("81", "85"):
            raise WordpressCacheError("compatibility", "This site's PHP handler is not supported by the installed Cache adapter")
    else:
        version = _active_php(site, data_dir)
    # Check installed WordPress plugins and PHP first, before any Nginx edit.
    original_options = _php(site, version, "inspect")
    if record is None:
        patch = _edits(site)
        record = {
            "schema": 1, "site_id": site["id"], "site_key": site["name"],
            "wp_root": root, "php": version, "phase": "initial",
            "recovery_id": cache_status.get("recovery_id"),
            "wp_old": _extract_constant(patch["wp_before"]),
            "ini_old": _extract_basedir(patch["ini_before"]),
            "ini_immutable": patch["ini_immutable"],
            "cache_owned": cache_status["state"] != "Applied",
            "previous": original_options["previous"],
        }
        _save(site, record, data_dir)
    if cache_status["state"] in ("Unmanaged", "Restored"):
        try:
            plan = preview_cache_activation(site, public)
        except CacheManageError as exc:
            if exc.reason_code != "native_extension_include_missing":
                raise
            # Keep the standard native site extension include even after
            # a disconnect: deleting it strands aaPanel's Cache recovery in
            # Needs Review and causes another manual configuration step.
            _bootstrap_site_extension(site)
            plan = preview_cache_activation(site, public)
        if plan["native_handler"] != "wpfastcgi":
            raise WordpressCacheError("compatibility", "Select an installed native WordPress website")
        try:
            active = manage_cache(
                "apply", site, public, approved=True,
                expected_source=plan["source_sha256"],
                expected_proposal=plan["proposal_sha256"],
                cache_generation=plan["cache_generation"])
            record["recovery_id"] = active["recovery_id"]
            record["phase"] = "cache_applied"
            _save(site, record, data_dir)
        except CacheManageError as exc:
            raise WordpressCacheError("cache", str(exc), exc.recovery_id) from exc
    active = _native_record(site, public)
    if active["state"] != "Applied" or not active["runtime_verified"]:
        raise WordpressCacheError("cache", "Native Cache Apply needs Recheck",
                                  active.get("recovery_id"))
    record["recovery_id"] = active["recovery_id"]
    if record["php"] != _active_php(site, data_dir):
        raise WordpressCacheError("cache", "Native PHP handler changed; recheck before WordPress integration")
    patch = _edits(site)
    if record["phase"] in ("initial", "cache_applied", "site_configured"):
        # The original line snippets are persisted before either file edit.
        _replace_file(root, WORDPRESS_CONFIG, patch["wp_before"], patch["wp_after"])
        ini_changed = _replace_file(root, USER_INI, patch["ini_before"], patch["ini_after"],
                                    immutable=record["ini_immutable"])
        if ini_changed:
            _reload_php(record["php"])
        record["phase"] = "site_configured"
        _save(site, record, data_dir)
    else:
        if _extract_constant(patch["wp_before"]) != CACHE_ROOT + "/site-" + str(site["id"]):
            raise WordpressCacheError("recovery", "WordPress cache path changed since connection")
        if CACHE_ROOT + "/site-" + str(site["id"]) + "/" not in _extract_basedir(patch["ini_before"]).split(":"):
            raise WordpressCacheError("recovery", "PHP access to Cache directory has changed")
    _php(site, record["php"], "connect")
    manifest = manage_cache("bridge_enable", site, public,
                            approved=True, recovery_id=record["recovery_id"])
    if manifest["state"] != "Provisioned":
        raise WordpressCacheError("bridge", "Native Bridge manifest was not provisioned",
                                  record["recovery_id"])
    record["phase"] = "connected"
    _save(site, record, data_dir)
    return {"schema": 1, "state": "Connected", "site_id": site["id"],
            "site_key": site["name"], "recovery_id": record["recovery_id"],
            "changed": not was_connected, "runtime_verified": active["runtime_verified"],
            "note": "Nginx Helper per-page and site-wide purging are configured for the owned site Cache."}


def _active_php(site, data_dir):
    from ach_customizer_cache_manage import _record_read
    fd = _open_state_dir(data_dir)
    try:
        record = _record_read(fd, site["id"])
    finally:
        os.close(fd)
    if record is None or record["phase"] != "applied" or record["site_key"] != site["name"]:
        raise WordpressCacheError("cache", "Native site Cache is not Applied")
    return record["php_version"]


def _extract_constant(content):
    matches = list(WP_CONSTANT.finditer(content))
    if len(matches) != 1:
        raise WordpressCacheError("recovery", "WordPress cache-path constant changed")
    return matches[0].group(2).decode("utf-8")


def _extract_basedir(content):
    matches = list(BASEDIR.finditer(content))
    if len(matches) != 1:
        raise WordpressCacheError("recovery", "PHP open_basedir definition changed")
    return matches[0].group(2).decode("utf-8")


def inspect(site, public, *, data_dir=DATA_DIR):
    _site_root(site, public)
    journal = _load(site, data_dir)
    if journal is None:
        return {"schema": 1, "state": "Not Connected", "site_id": site["id"],
                "site_key": site["name"], "read_only": True}
    runtime = _native_record(site, public)
    if journal["phase"] == "restored" and (
            runtime["state"] == "Restored" or
            runtime["state"] == "Applied" and not journal.get("cache_owned", True)):
        return {"schema": 1, "state": "Not Connected",
                "site_id": site["id"], "site_key": site["name"],
                "read_only": True, "recovery_id": journal["recovery_id"],
                "note": "WordPress Cache connection restored to its previous state."}
    state = "Needs Review"
    if journal["phase"] == "connected" and runtime["state"] == "Applied" and runtime["runtime_verified"]:
        conf, _ = _read_file(site["path"], WORDPRESS_CONFIG)
        ini, _ = _read_file(site["path"], USER_INI)
        cache = CACHE_ROOT + "/site-" + str(site["id"])
        if _extract_constant(conf) == cache and cache + "/" in _extract_basedir(ini).split(":"):
            status = _php(site, journal["php"], "inspect")
            from ach_customizer_cache_bridge import inspect as bridge_inspect
            if (status["active_helper"] and status["active_bridge"] and
                    status["options"].get("enable_purge") == 1 and
                    status["options"].get("purge_method") == "unlink_files" and
                    bridge_inspect(site, public, _read_managed(site, data_dir)) == "Provisioned"):
                state = "Connected"
    return {"schema": 1, "state": state, "site_id": site["id"],
            "site_key": site["name"], "read_only": True,
            "recovery_id": journal["recovery_id"],
            "note": ("Configured; normal WordPress content changes need no repeat setup."
                     if state == "Connected" else
                     "Connection is incomplete or source drifted; repeat one-click setup or inspect recovery.")}


def _read_managed(site, data_dir):
    from ach_customizer_cache_manage import _record_read
    fd = _open_state_dir(data_dir)
    try:
        return _record_read(fd, site["id"])
    finally:
        os.close(fd)


def restore(site, public, *, data_dir=DATA_DIR):
    with _site_lock(site, data_dir):
        return _restore_locked(site, public, data_dir=data_dir)


def _restore_locked(site, public, *, data_dir):
    _site_root(site, public)
    record = _load(site, data_dir)
    if record is None or record["phase"] == "restored":
        return {"schema": 1, "state": "Not Connected",
                "site_id": site["id"], "site_key": site["name"], "changed": False}
    current = _native_record(site, public)
    if current["state"] == "Unmanaged" and record["phase"] == "initial":
        record["phase"] = "restored"
        _save(site, record, data_dir)
        return {"schema": 1, "state": "Restored",
                "site_id": site["id"], "site_key": site["name"], "changed": True}
    if current["state"] == "Restored" and current["recovery_id"] == record["recovery_id"]:
        # A previous disconnect already finished native Cache Restore, but
        # the final native VHost/journal checkpoint may have been interrupted.
        config, _ = _read_file(site["path"], WORDPRESS_CONFIG)
        ini, _ = _read_file(site["path"], USER_INI)
        if (_extract_constant(config) != record["wp_old"]
                or _extract_basedir(ini) != record["ini_old"]):
            raise WordpressCacheError("recovery",
                "WordPress configuration was not restored; inspect the site before recovery")
        status = _php(site, record["php"], "inspect")
        if status["options"].get("enable_purge") not in (None, False, 0):
            raise WordpressCacheError("recovery", "Nginx Helper Purge All remains enabled")
        record["phase"] = "restored"
        _save(site, record, data_dir)
        return {"schema": 1, "state": "Restored",
                "site_id": site["id"], "site_key": site["name"], "changed": True}
    if current["state"] != "Applied" or current["recovery_id"] != record["recovery_id"]:
        raise WordpressCacheError("recovery", "Cache identity changed; inspect saved recovery before disconnect")
    _php(site, record["php"], "suspend")
    from ach_customizer_cache_bridge import disable as bridge_disable
    bridge_disable(site, public)
    cache = CACHE_ROOT + "/site-" + str(site["id"])
    for name, key, old, replacement in (
        (WORDPRESS_CONFIG, "wp_old", record["wp_old"], cache),
        (USER_INI, "ini_old", record["ini_old"],
         _extract_basedir(_read_file(site["path"], USER_INI)[0])),
    ):
        raw, _ = _read_file(site["path"], name)
        if name == WORDPRESS_CONFIG:
            expression = WP_CONSTANT
        else:
            expression = BASEDIR
        matches = list(expression.finditer(raw))
        if len(matches) != 1:
            raise WordpressCacheError("recovery", name + " is no longer source-matched")
        before_value = matches[0].group(2)
        if name == WORDPRESS_CONFIG:
            if before_value.decode() != cache:
                raise WordpressCacheError("recovery", "WordPress cache-path changed")
            new_value = old
        else:
            values = before_value.decode().split(":")
            target = cache + "/"
            old_values = record["ini_old"].split(":")
            if target not in values:
                raise WordpressCacheError("recovery", "Site PHP access path changed")
            if target not in old_values:
                values.remove(target)
            new_value = ":".join(values)
        changed = (raw[:matches[0].start(2)] + new_value.encode() +
                   raw[matches[0].end(2):])
        _replace_file(site["path"], name, raw, changed,
                      immutable=(name == USER_INI and record["ini_immutable"]))
    _reload_php(record["php"])
    _php(site, record["php"], "restore", previous=record["previous"])
    if record.get("cache_owned", True):
        result = manage_cache("restore", site, public, approved=True,
                              recovery_id=record["recovery_id"])
        if result["state"] != "Restored":
            raise WordpressCacheError("recovery", "Native Cache Restore requires review")
    # A Cache already Applied before this one-click setup is not ours to
    # Restore. Its native generation and site-owned Nginx files remain intact.
    record["phase"] = "restored"
    _save(site, record, data_dir)
    return {"schema": 1, "state": "Restored", "site_id": site["id"],
            "site_key": site["name"], "changed": True,
            "recovery_id": record["recovery_id"],
            "note": ("Site-owned native Cache was retained because it existed before Connect."
                     if not record.get("cache_owned", True) else
                     "Site-specific WordPress, PHP access and native Cache settings restored.")}
