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
WP_CONSTANT_NAME = b"RT_WP_NGINX_HELPER_CACHE_PATH"
WP_BOOTSTRAP = re.compile(
    rb"(?m)^[ \t]*require_once[ \t]+ABSPATH[ \t]*\.[ \t]*"
    rb"['\"]wp-settings\.php['\"][ \t]*;[ \t]*(?:\r?\n|$)")
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
    // A source-text match is not proof of the value WordPress actually uses.
    // Refuse BEFORE activating plugins or enabling the vendor's Purge All.
    $expected = $input['expected_cache_path'] ?? null;
    if (!is_string($expected) || $expected === '' ||
        !is_string($present['constant']) || $present['constant'] !== $expected) {
        fwrite(STDERR, "Effective WordPress Nginx Helper Cache path is not the selected private site Cache\n");
        exit(15);
    }
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


def _php(site, php_version, command, *, previous=None, expected_cache_path=None):
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
            cwd=root, input=json.dumps({"action": command, "previous": previous,
                                        "expected_cache_path": expected_cache_path}),
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


def _constant_match(config, *, allow_absent=False, stage="recovery"):
    """Recognize exactly one unambiguous source definition, not a comment."""
    matches = list(WP_CONSTANT.finditer(config))
    if not matches and allow_absent and WP_CONSTANT_NAME not in config:
        return None
    # Another mention can be a dynamic/conditional definition that PHP
    # executes before the simple one. Never select only the regex match.
    if len(matches) != 1 or config.count(WP_CONSTANT_NAME) != 1:
        raise WordpressCacheError(
            stage, "Complex or repeated Nginx Helper cache constant needs review")
    # The anchored simple line can also occur verbatim in a PHP block comment.
    # Do not mistake that inert text for a live definition.
    if any(part.start() <= matches[0].start() < part.end()
           for part in re.finditer(rb"/\*.*?(?:\*/|\Z)", config, re.DOTALL)):
        raise WordpressCacheError(
            stage, "Nginx Helper cache constant occurs inside a PHP comment")
    return matches[0]


def _managed_constant_line(value, newline):
    return (b"define('RT_WP_NGINX_HELPER_CACHE_PATH', '" +
            value.encode("utf-8") + b"');" + newline)


def _is_managed_insert(config, cache, match=None):
    """A connector-inserted line must still be exact and bootstrap-adjacent."""
    match = match or _constant_match(config)
    anchors = list(WP_BOOTSTRAP.finditer(config))
    # Python's multiline $ matches before the LF; the regex consumes CR
    # but leaves the final LF outside the match in both newline styles.
    line = match.group(0) + b"\n"
    newline = b"\r\n" if line.endswith(b"\r\n") else b"\n"
    return (len(anchors) == 1 and match.end() + 1 == anchors[0].start()
            and config[match.end():match.end() + 1] == b"\n"
            and line == _managed_constant_line(cache, newline))


def _replace_wp_constant(config, value, *, managed_cache=None):
    """Set one simple Helper constant, or remove only our verified insert."""
    match = _constant_match(config, allow_absent=True, stage="compatibility")
    if match:
        if value is None:
            if managed_cache is None or not _is_managed_insert(config, managed_cache, match):
                raise WordpressCacheError(
                    "recovery", "Connector-managed WordPress Cache line changed; refusing removal")
            return config[:match.start()] + config[match.end() + 1:]
        return (config[:match.start(2)] + value.encode("utf-8") +
                config[match.end(2):])
    if value is None:
        return config
    anchors = list(WP_BOOTSTRAP.finditer(config))
    if len(anchors) != 1:
        raise WordpressCacheError(
            "compatibility", "Cannot locate the unique WordPress bootstrap in wp-config.php")
    position = anchors[0].start()
    newline = b"\r\n" if anchors[0].group(0).endswith(b"\r\n") else b"\n"
    return config[:position] + _managed_constant_line(value, newline) + config[position:]


def _edits(site, original=None):
    root = site["path"]
    cache = CACHE_ROOT + "/site-" + str(site["id"])
    config, _ = _read_file(root, WORDPRESS_CONFIG)
    existing = _extract_constant(config, allow_absent=True)
    if existing is not None and existing not in (cache, "/www/server/fastcgi_cache"):
        raise WordpressCacheError("compatibility", "WordPress uses a custom Nginx Helper cache path; review before changing")
    config_after = _replace_wp_constant(config, cache)
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


def _native_generation(site, data_dir, current):
    """Resolve one verified native generation, not an arbitrary current Cache."""
    native = _read_managed(site, data_dir)
    expected_phase = current["state"].lower()
    if (native is None or native["site_key"] != site["name"]
            or native["op"] != current.get("recovery_id")
            or native["phase"] != expected_phase):
        raise WordpressCacheError(
            "recovery", "Native Cache journal and observed recovery identity differ",
            current.get("recovery_id"))
    return native["cache_generation"]


def _check_native_connection(site, record, current, data_dir):
    """Never transfer connector ownership to another independently Applied Cache."""
    if current["state"] not in ("Applied", "Restored"):
        raise WordpressCacheError(
            "recovery", "Native Cache is not in a verified managed state",
            record.get("recovery_id"))
    generation = _native_generation(site, data_dir, current)
    if (record.get("recovery_id") is None and
            record["phase"] == "initial" and
            record.get("cache_owned", True) and
            record.get("pending_generation") == generation and
            current["state"] == "Applied"):
        # Apply succeeded but the connector crashed before checkpointing its
        # recovery ID. The generation was persisted before Apply and the
        # native manager has independently verified this exact journal.
        record["recovery_id"] = current["recovery_id"]
        record["native_generation"] = generation
        record["phase"] = "cache_applied"
        _save(site, record, data_dir)
    elif (record.get("recovery_id") != current.get("recovery_id")
            or record.get("native_generation", generation) != generation):
        raise WordpressCacheError(
            "recovery", "Different native Cache generation; review the old WordPress connection before reconnecting",
            record.get("recovery_id"))
    if record.get("native_generation") is None:
        # Existing site-first journal can be bound only after its saved
        # recovery ID was matched, never from the current generation alone.
        record["native_generation"] = generation
        _save(site, record, data_dir)
    return generation


def _connected_ini(record, cache):
    original = record["ini_old"]
    target = cache + "/"
    return original if target in original.split(":") else original + ":" + target


def _source_values(site, record):
    """Check both source values before any mutation, allowing only exact states."""
    config, _ = _read_file(site["path"], WORDPRESS_CONFIG)
    ini, _ = _read_file(site["path"], USER_INI)
    cache = CACHE_ROOT + "/site-" + str(site["id"])
    old_config = record["wp_old"]
    old_ini = record["ini_old"]
    connected_ini = _connected_ini(record, cache)
    actual_config = _extract_constant(config, allow_absent=record["wp_old"] is None)
    actual_ini = _extract_basedir(ini)
    if old_config is None and actual_config == cache and not _is_managed_insert(config, cache):
        raise WordpressCacheError(
            "recovery", "Connector-managed WordPress Cache line changed; review before removal",
            record.get("recovery_id"))
    if actual_config not in (old_config, cache):
        raise WordpressCacheError(
            "recovery", "WordPress Cache constant is neither the saved original nor the managed site path",
            record.get("recovery_id"))
    if actual_ini not in (old_ini, connected_ini):
        raise WordpressCacheError(
            "recovery", "PHP open_basedir is neither the saved original nor the managed site path",
            record.get("recovery_id"))
    return config, ini, actual_config, actual_ini, cache, connected_ini


def _replace_value(raw, expression, value):
    matches = list(expression.finditer(raw))
    if len(matches) != 1:
        raise WordpressCacheError("recovery", "WordPress source setting is no longer unique")
    return raw[:matches[0].start(2)] + value.encode() + raw[matches[0].end(2):]


def _setup_locked(site, public, *, data_dir):
    root = _site_root(site, public)
    record = _load(site, data_dir)
    cache_status = _native_record(site, public)

    if record is not None and record["phase"] == "restored":
        # Explicit Connect after a completed Disconnect is a NEW ownership
        # decision. A newly manual Applied generation belongs to its operator,
        # even when the previous connector created a different generation.
        if cache_status["state"] == "Restored":
            _check_native_connection(site, record, cache_status, data_dir)
        elif (cache_status["state"] == "Applied" and
              record.get("cache_owned", True) and
              cache_status["recovery_id"] == record["recovery_id"]):
            raise WordpressCacheError("recovery",
                "Restored WordPress journal conflicts with its still-Applied native Cache")
        record = None
    elif record is not None and cache_status["state"] == "Restored":
        raise WordpressCacheError("recovery",
            "WordPress setup was interrupted by native Cache Restore; Disconnect before connecting",
            record.get("recovery_id"))

    if record is not None and cache_status["state"] == "Applied":
        _check_native_connection(site, record, cache_status, data_dir)
    elif (record is not None and cache_status["state"] == "Unmanaged"
          and record["phase"] != "initial"):
        raise WordpressCacheError("recovery",
            "Native Cache disappeared while WordPress setup was in progress",
            record.get("recovery_id"))

    if cache_status["state"] in ("Unmanaged", "Restored"):
        from ach_customizer_cache_audit import inspect_site_fastcgi_cache
        native = inspect_site_fastcgi_cache(public, site["id"], site["name"])
        version = native.get("php_version")
        if version not in ("81", "85"):
            raise WordpressCacheError("compatibility",
                "Selected native WordPress PHP handler is incompatible with this Cache adapter")
    else:
        version = _active_php(site, data_dir)

    original_options = _php(site, version, "inspect")
    if record is None:
        patch = _edits(site)
        source_constant = _extract_constant(patch["wp_before"], allow_absent=True)
        effective_constant = original_options.get("previous", {}).get("constant")
        # An already-active Nginx Helper may define its own default path
        # while WordPress loads, even when wp-config.php has no definition.
        # Our managed definition will load first; the subsequent PHP
        # "connect" call must verify its effective site-owned path before
        # activating any plugins or enabling purging.
        if (effective_constant != source_constant and
                not (source_constant is None and original_options.get("active_helper"))):
            raise WordpressCacheError(
                "compatibility", "Effective WordPress Nginx Helper Cache path differs from its source")
        record = {
            "schema": 1, "site_id": site["id"], "site_key": site["name"],
            "wp_root": root, "php": version, "phase": "initial",
            "recovery_id": cache_status.get("recovery_id"),
            "native_generation": (
                _native_generation(site, data_dir, cache_status)
                if cache_status["state"] == "Applied" else None),
            "pending_generation": None,
            "wp_old": source_constant,
            "ini_old": _extract_basedir(patch["ini_before"]),
            "ini_immutable": patch["ini_immutable"],
            "cache_owned": cache_status["state"] != "Applied",
            "previous": original_options["previous"],
        }
        _save(site, record, data_dir)

    if cache_status["state"] in ("Unmanaged", "Restored"):
        try:
            plan = preview_cache_activation(
                site, public, cache_generation=record.get("pending_generation"))
        except CacheManageError as exc:
            if exc.reason_code != "native_extension_include_missing":
                raise
            _bootstrap_site_extension(site)
            plan = preview_cache_activation(
                site, public, cache_generation=record.get("pending_generation"))
        if (plan["native_handler"] not in ("stock", "wpfastcgi") or
                record["php"] != plan["php_version"]):
            raise WordpressCacheError(
                "compatibility", "Native PHP handler/source changed before WordPress Cache Apply")
        # Persist the exact proposed generation BEFORE the native Apply: an
        # interrupted success can be resumed without adopting arbitrary Cache.
        record["pending_generation"] = plan["cache_generation"]
        _save(site, record, data_dir)
        try:
            active = manage_cache(
                "apply", site, public, approved=True,
                expected_source=plan["source_sha256"],
                expected_proposal=plan["proposal_sha256"],
                cache_generation=plan["cache_generation"])
        except CacheManageError as exc:
            raise WordpressCacheError("cache", str(exc), exc.recovery_id) from exc
        generation = _native_generation(site, data_dir, active)
        if generation != record["pending_generation"]:
            raise WordpressCacheError("recovery",
                "Native Apply returned a different Cache generation", active.get("recovery_id"))
        record["recovery_id"] = active["recovery_id"]
        record["native_generation"] = generation
        record["phase"] = "cache_applied"
        _save(site, record, data_dir)

    active = _native_record(site, public)
    if active["state"] != "Applied" or not active["runtime_verified"]:
        raise WordpressCacheError("cache", "Native Cache Apply needs Recheck",
                                  active.get("recovery_id"))
    _check_native_connection(site, record, active, data_dir)
    if record["php"] != _active_php(site, data_dir):
        raise WordpressCacheError("cache",
            "Native PHP handler changed; recheck before WordPress integration")

    if record["phase"] in ("initial", "cache_applied", "configuring"):
        config, ini, actual_config, actual_ini, cache, connected_ini = _source_values(site, record)
        pending = record["phase"] == "configuring"
        if not pending:
            record["phase"] = "configuring"
            _save(site, record, data_dir)
        changed_config = _replace_file(
            root, WORDPRESS_CONFIG, config, _replace_wp_constant(config, cache))
        changed_ini = _replace_file(
            root, USER_INI, ini, _replace_value(ini, BASEDIR, connected_ini),
            immutable=record["ini_immutable"])
        # A failed reload may leave both files already changed on retry.
        # The saved "configuring" phase is proof that the FPM worker still
        # needs verification; the CLI subprocess alone is not proof.
        if (changed_config or changed_ini or
                pending and (record["wp_old"] != cache or record["ini_old"] != connected_ini)):
            _reload_php(record["php"])
        record["phase"] = "site_configured"
        _save(site, record, data_dir)
    elif record["phase"] not in ("site_configured", "connected"):
        raise WordpressCacheError("recovery", "Unknown WordPress setup checkpoint")

    _, _, actual_config, actual_ini, cache, connected_ini = _source_values(site, record)
    if actual_config != cache or actual_ini != connected_ini:
        raise WordpressCacheError("recovery",
            "WordPress site settings drifted after the PHP reload", record["recovery_id"])

    _php(site, record["php"], "connect", expected_cache_path=cache)
    manifest = manage_cache("bridge_enable", site, public,
                            approved=True, recovery_id=record["recovery_id"])
    if manifest["state"] != "Provisioned":
        raise WordpressCacheError("bridge", "Native Bridge manifest was not provisioned",
                                  record["recovery_id"])
    was_connected = record["phase"] == "connected"
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


def _extract_constant(content, *, allow_absent=False):
    match = _constant_match(content, allow_absent=allow_absent)
    return match.group(2).decode("utf-8") if match else None


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
    if (journal["phase"] == "connected" and runtime["state"] == "Applied"
            and runtime["runtime_verified"]
            and runtime.get("recovery_id") == journal.get("recovery_id")
            and _native_generation(site, data_dir, runtime) ==
                journal.get("native_generation")):
        conf, _ = _read_file(site["path"], WORDPRESS_CONFIG)
        ini, _ = _read_file(site["path"], USER_INI)
        cache = CACHE_ROOT + "/site-" + str(site["id"])
        if (_extract_constant(conf) == cache
                and (journal["wp_old"] is not None or _is_managed_insert(conf, cache))
                and cache + "/" in _extract_basedir(ini).split(":")):
            status = _php(site, journal["php"], "inspect")
            from ach_customizer_cache_bridge import inspect as bridge_inspect
            if (status.get("previous", {}).get("constant") == cache
                    and status["active_helper"] and status["active_bridge"] and
                    status["options"].get("cache_method") == "enable_fastcgi" and
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
    # If setup never reached a Cache Apply, nothing changed on the WP side.
    if current["state"] == "Unmanaged" and record["phase"] == "initial":
        _, _, actual_config, actual_ini, _, _ = _source_values(site, record)
        if actual_config != record["wp_old"] or actual_ini != record["ini_old"]:
            raise WordpressCacheError(
                "recovery", "WordPress source changed before the initial native Apply")
        record["phase"] = "restored"
        _save(site, record, data_dir)
        return {"schema": 1, "state": "Restored",
                "site_id": site["id"], "site_key": site["name"], "changed": True}
    if current["state"] not in ("Applied", "Restored"):
        raise WordpressCacheError("recovery",
            "Native Cache needs independent Recheck before Disconnect",
            record.get("recovery_id"))
    _check_native_connection(site, record, current, data_dir)
    config, ini, actual_config, actual_ini, cache, connected_ini = _source_values(site, record)
    if record["phase"] in ("restore_reloaded", "restore_wordpress") and (
            actual_config != record["wp_old"] or actual_ini != record["ini_old"]):
        raise WordpressCacheError("recovery",
            "WordPress files changed after the saved PHP Restore checkpoint",
            record["recovery_id"])

    if record["phase"] not in ("restoring", "restore_reloaded", "restore_wordpress"):
        record["phase"] = "restoring"
        _save(site, record, data_dir)

    if record["phase"] == "restoring":
        _php(site, record["php"], "suspend")
        from ach_customizer_cache_bridge import disable as bridge_disable
        bridge_disable(site, public)
        # Each file may be connected OR already restored by a prior attempt.
        # The exact two allowed values were checked before the first write.
        changed_config = _replace_file(
            site["path"], WORDPRESS_CONFIG, config,
            _replace_wp_constant(config, record["wp_old"], managed_cache=cache))
        changed_ini = _replace_file(
            site["path"], USER_INI, ini,
            _replace_value(ini, BASEDIR, record["ini_old"]),
            immutable=record["ini_immutable"])
        # This phase remains "restoring" if reload is uncertain or fails.
        # A retry then reloads only after revalidating the saved source values.
        if (changed_config or changed_ini or record["wp_old"] != cache
                or record["ini_old"] != connected_ini):
            _reload_php(record["php"])
        record["phase"] = "restore_reloaded"
        _save(site, record, data_dir)

    if record["phase"] == "restore_reloaded":
        _, _, actual_config, actual_ini, _, _ = _source_values(site, record)
        if actual_config != record["wp_old"] or actual_ini != record["ini_old"]:
            raise WordpressCacheError("recovery", "WordPress Restore source changed")
        _php(site, record["php"], "restore", previous=record["previous"])
        record["phase"] = "restore_wordpress"
        _save(site, record, data_dir)

    # Verify the shared directory cannot be used by Nginx Helper Purge All
    # before completing or replaying native Cache Restore.
    _, _, actual_config, actual_ini, _, _ = _source_values(site, record)
    if actual_config != record["wp_old"] or actual_ini != record["ini_old"]:
        raise WordpressCacheError("recovery", "WordPress Restore source verification failed")
    status = _php(site, record["php"], "inspect")
    if status["options"].get("enable_purge") not in (None, False, 0):
        raise WordpressCacheError("recovery", "Nginx Helper Purge All remains enabled")

    if current["state"] == "Applied" and record.get("cache_owned", True):
        result = manage_cache("restore", site, public, approved=True,
                              recovery_id=record["recovery_id"])
        if result["state"] != "Restored":
            raise WordpressCacheError("recovery", "Native Cache Restore requires review",
                                      record["recovery_id"])
    # An independently managed Cache is not ours to restore; and an already
    # Restored generation is only finalized, never signaled twice.
    record["phase"] = "restored"
    _save(site, record, data_dir)
    return {"schema": 1, "state": "Restored", "site_id": site["id"],
            "site_key": site["name"], "changed": True,
            "recovery_id": record["recovery_id"],
            "note": ("Existing operator-owned native Cache was retained."
                     if not record.get("cache_owned", True) else
                     "Site-specific WordPress, PHP access and native Cache settings restored.")}
