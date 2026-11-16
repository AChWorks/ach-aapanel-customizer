"""Guarded, site-owned Nginx FastCGI cache management on aaPanel 8.0.7.

Only native primary-admin endpoint calls may invoke mutations. Keep journal and
per-site cache state outside the replaceable plugin; no vendor file is edited.
This adapter is intentionally limited to the proved Nginx/PHP 81/85 source
shape, and never changes/cleans the legacy shared WORDPRESS cache.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import pwd
import re
import stat
import time
from pathlib import Path
from uuid import uuid4

from ach_customizer_cache_policy import (
    generate_reference, CACHE_ROOT, HSTS_DIRECTIVE, WP_NATIVE_CANONICAL,
)
from ach_customizer_cache_audit import inspect_site_fastcgi_cache
from ach_customizer_monitor import (
    MonitorInputError, _active_nginx_text, _bounded_file_text,
    _native_extension_fingerprint, _native_unused_subdir,
    _native_server_direct_include,
    MAX_NGINX_SITE_BYTES,
)
from ach_customizer_state import DATA_DIR, _open_state_dir, _exclusive_lock
from ach_customizer_status_extension import (
    _bounded_file, _directory, _owned_dir, _publish_complete,
    _rename_noreplace, _nginx,
)
from ach_customizer_status_pages import StatusPageError

VHOST_ROOT = '/www/server/panel/vhost/nginx'
NGINX_ROOT = '/www/server/nginx/conf'
NGINX = '/www/server/nginx/sbin/nginx'
HEX = re.compile(r'[0-9a-f]{64}\Z')
TOKEN = re.compile(r'[0-9a-f]{32}\Z')
SITE_KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z')
GLOBAL_PREFIX = '0.ach_customizer_cache_'
EXTENSION_PREFIX = 'ach_customizer_cache_'
JOURNAL_PREFIX = 'ach_customizer.cache.'


class CacheManageError(StatusPageError):
    def __init__(self, stage, message, *, recovery_id=None, reason_code=None):
        super().__init__(message)
        self.stage = stage
        self.recovery_id = recovery_id if isinstance(recovery_id, str) and TOKEN.fullmatch(recovery_id) else None
        self.reason_code = (reason_code if reason_code == 'native_extension_include_missing'
                            else None)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _names(site_id):
    if type(site_id) is not int or not 1 <= site_id <= 2147483647:
        raise CacheManageError('identity', 'Invalid native site ID')
    return (GLOBAL_PREFIX + str(site_id) + '.conf',
            EXTENSION_PREFIX + str(site_id) + '.conf',
            JOURNAL_PREFIX + str(site_id) + '.json')


def _record_decode(raw, site_id):
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CacheManageError('recovery', 'Invalid persistent Cache recovery journal') from exc
    needed = {'schema', 'site_id', 'site_key', 'php_version', 'op', 'phase',
              'source_sha', 'proposal_sha', 'vhost_sha', 'main_sha', 'php_sha',
              'global_sha', 'extension_sha', 'cache_directory',
              'cache_generation', 'probe_status'}
    if not isinstance(record, dict):
        raise CacheManageError('recovery', 'Untrusted Cache journal')
    schema = record.get('schema')
    expected = needed | ({'cache_identity'} if schema == 2 else set())
    if schema == 2 and 'inherited_hsts' in record:
        expected.add('inherited_hsts')
    if schema == 2 and 'native_handler' in record:
        expected.add('native_handler')
    identity = record.get('cache_identity')
    valid_identity = (identity is None and record.get('phase') in ('prepared', 'restored') or
                      isinstance(identity, list) and len(identity) == 2 and
                      all(type(value) is int and value > 0 for value in identity))
    if (schema not in (1, 2) or set(record) != expected
            or ('native_handler' in record and record['native_handler'] != 'wpfastcgi')
            or ('inherited_hsts' in record and (
                type(record['inherited_hsts']) is not str or
                not HSTS_DIRECTIVE.fullmatch(record['inherited_hsts'])))
            or (schema == 2 and not valid_identity)
            or record['site_id'] != site_id
            or not isinstance(record['site_key'], str)
            or not SITE_KEY.fullmatch(record['site_key'])
            or record['php_version'] not in ('81','85')
            or not isinstance(record['op'], str) or not TOKEN.fullmatch(record['op'])
            or record['phase'] not in ('prepared','applied','restored')
            or any(not isinstance(record[x], str) or not HEX.fullmatch(record[x])
                   for x in ('source_sha','proposal_sha','vhost_sha','main_sha',
                             'php_sha','global_sha','extension_sha'))
            or record['cache_directory'] != CACHE_ROOT + '/site-' + str(site_id)
            or not isinstance(record['cache_generation'], str)
            or not TOKEN.fullmatch(record['cache_generation'])
            or type(record['probe_status']) is not int
            or not 100 <= record['probe_status'] <= 599):
        raise CacheManageError('recovery', 'Untrusted Cache journal; do not modify Nginx')
    return record


def _record_read(state_fd, site_id):
    raw = _bounded_file(state_fd, _names(site_id)[2], limit=8192,
                        permissions=0o600)
    return None if raw is None else _record_decode(raw, site_id)


def _generation_unused(state_fd, site_id, generation):
    """Read all retained activation journals; never trust only the latest one."""
    name = _names(site_id)[2]
    prefix = name + '.'
    suffix = '.restored'
    for entry in os.listdir(state_fd):
        if not (entry.startswith(prefix) and entry.endswith(suffix)):
            continue
        op = entry[len(prefix):-len(suffix)]
        if not TOKEN.fullmatch(op):
            raise CacheManageError('recovery', 'Unexpected Cache recovery archive name')
        raw = _bounded_file(state_fd, entry, limit=8192, permissions=0o600)
        if raw is None:
            raise CacheManageError('recovery', 'Cache recovery archive disappeared')
        old = _record_decode(raw, site_id)
        if old['op'] != op or old['phase'] != 'restored':
            raise CacheManageError('recovery', 'Cache archive identity is inconsistent')
        if old['cache_generation'] == generation:
            raise CacheManageError('recovery',
                'Cache generation was already activated and cannot be reused')


def _record_save(state_fd, record):
    payload = (json.dumps(record, sort_keys=True, separators=(',',':'))+'\n').encode()
    if len(payload) > 8192:
        raise CacheManageError('journal', 'Cache recovery record is oversized')
    name = _names(record['site_id'])[2]
    temp = name + '.' + uuid4().hex + '.stage'
    descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW |
                         os.O_CLOEXEC, 0o600, dir_fd=state_fd)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'wb', closefd=False) as out:
            out.write(payload)
            out.flush()
        os.fsync(descriptor)
        os.replace(temp, name, src_dir_fd=state_fd, dst_dir_fd=state_fd)
        os.fsync(state_fd)
    finally:
        os.close(descriptor)
        try:
            os.unlink(temp, dir_fd=state_fd)
        except FileNotFoundError:
            pass


def _read_source(path):
    source, signature = _bounded_file_text(Path(path), MAX_NGINX_SITE_BYTES,
                                           with_fingerprint=True)
    return source.encode('utf8'), signature


def _missing_extension_inventory(site, vhost_root):
    """Read the prospective wildcard target before suggesting its activation.

    Native aaPanel may create the Extension tree after site creation. An
    absent, verified site directory is compatible with refresh-first guidance;
    an existing directory is accepted only with bounded, anchored inspection
    of the native inert site_total.conf. No foreign routing is endorsed.
    """
    parent = Path(vhost_root) / 'extension'
    try:
        root_fd = _directory(vhost_root)
        try:
            _owned_dir(root_fd)
            try:
                source = os.stat('extension', dir_fd=root_fd,
                                 follow_symlinks=False)
            except FileNotFoundError:
                return  # No Extension parent yet on this native installation.
            if not stat.S_ISDIR(source.st_mode):
                raise ValueError('Native Extension parent is not a directory')
        finally:
            os.close(root_fd)

        parent_fd = _directory(str(parent))
        try:
            _owned_dir(parent_fd)
            if not os.fstat(parent_fd).st_mode & stat.S_IRUSR:
                raise ValueError('Native Extension parent is inaccessible')
            try:
                site_dir = os.stat(site['name'], dir_fd=parent_fd,
                                   follow_symlinks=False)
            except FileNotFoundError:
                return  # Native statistics has not created this site directory.
            if (not stat.S_ISDIR(site_dir.st_mode) or
                    not site_dir.st_mode & stat.S_IRUSR):
                raise ValueError('Native Extension directory is inaccessible')
        finally:
            os.close(parent_fd)

        _native_extension_fingerprint(
            parent / site['name'],
            site_id=site['id'], site_key=site['name'],
            allowed_conf_names=frozenset(('site_total.conf',)))
    except (OSError, ValueError, StatusPageError) as exc:
        raise CacheManageError(
            'compatibility',
            'Native site VHost is missing its Extension include, but the on-disk '
            'Extension directory is unverified. Inspect its ownership and '
            '*.conf contents before adding a wildcard include. '
            'No VHost or Cache change was made.') from exc


def _direct_server_scope_id(source, offset):
    """Lexically verify a statement is directly inside a single server block.

    Quoted and escaped braces are not Nginx block delimiters. This is a
    conservative source-scope check, not interpretation of arbitrary includes.
    """
    blocks = []
    start = 0
    quote = None
    escaped = False
    for pos, char in enumerate(source[:offset]):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "{":
            heading = source[start:pos].strip()
            blocks.append(pos if not blocks and heading == "server" else None)
            start = pos + 1
        elif char == "}":
            if not blocks:
                return None
            blocks.pop()
            start = pos + 1
        elif char == ";":
            start = pos + 1
    return (blocks[0] if quote is None and not escaped and len(blocks) == 1
            else None)


def _site_hsts_header(active_vhost, extension_line, php_line):
    """Copy one recognized native server HSTS, or refuse header inheritance.

    A managed PHP location declares X-ACh-Cache headers and thus suppresses
    inherited server add_header on Nginx 1.28. Never guess at unknown security
    headers or silently drop them.
    """
    entries = list(re.finditer(r"\badd_header(?=\s)", active_vhost))
    if not entries:
        return None
    if len(entries) != 1:
        raise CacheManageError(
            'compatibility', 'Selected VHost response headers need source-matched Cache review')
    entry = entries[0]
    match = HSTS_DIRECTIVE.match(active_vhost, entry.start())
    block = _direct_server_scope_id(active_vhost, entry.start())
    if (not match or block is None or
            block != _direct_server_scope_id(active_vhost, active_vhost.find(extension_line)) or
            block != _direct_server_scope_id(active_vhost, active_vhost.find(php_line))):
        raise CacheManageError(
            'compatibility', 'Selected VHost response headers cannot be safely inherited')
    return match.group(0)


def _site_sources(site, php, *, native_handler="stock",
                  vhost_root=VHOST_ROOT, nginx_root=NGINX_ROOT):
    if (site.get('status') not in ('1',1) or not SITE_KEY.fullmatch(site['name'])
            or not any(binding.get('name') == site['name'] and binding.get('port') == 80
                       for binding in site.get('bound_domains', []))):
        raise CacheManageError('identity', 'A running registered HTTP/80 site with exact site hostname is required')
    if native_handler not in ('stock', 'wpfastcgi'):
        raise CacheManageError('compatibility', 'Unknown native PHP handler')
    vhost, sig = _read_source(vhost_root+'/'+site['name']+'.conf')
    main, _ = _read_source(nginx_root+'/nginx.conf')
    php_suffix = '-wpfastcgi' if native_handler == 'wpfastcgi' else ''
    php_include, _ = _read_source(nginx_root+'/enable-php-'+php+php_suffix+'.conf')
    fastcgi, _ = _read_source(nginx_root+'/fastcgi.conf')
    pathinfo = (_read_source(nginx_root+'/pathinfo.conf')[0]
                if native_handler == 'stock' else b'')
    active = _active_nginx_text(vhost.decode())
    php_active = re.sub(r'\s+', ' ', _active_nginx_text(php_include.decode())).strip()
    stock = (r'location ~ [^/]\.php(/|$) { try_files $uri =404; '
             'fastcgi_pass unix:/tmp/php-cgi-'+php+'.sock; '
             'fastcgi_index index.php; include fastcgi.conf; '
             'include pathinfo.conf; }')
    if native_handler == 'wpfastcgi':
        # Both native 8.1 and 8.5 snippets were byte-source inspected on
        # aaPanel 8.0.7; only spacing and the PHP socket may differ.
        wp_expected = re.sub(r'\s+', ' ',
            WP_NATIVE_CANONICAL.replace('NATIVE_PHP', php)).strip()
        if php_active != wp_expected:
            raise CacheManageError('compatibility',
                'Native WordPress handler differs from known PHP/cache/header/purge source')
    elif php_active != stock:
        raise CacheManageError('compatibility',
            'Native PHP handler has unverified routing or FastCGI parameters')
    params = _active_nginx_text(pathinfo.decode())
    if native_handler == 'stock' and (any(not re.search(r'\bfastcgi_param\s+'+key+r'\s+'+value+r'\s*;', params)
            for key, value in (
                ('SCRIPT_FILENAME', r'\$document_root\$real_script_name'),
                ('SCRIPT_NAME', r'\$real_script_name'),
                ('PATH_INFO', r'\$path_info'))) or
            re.search(r'\b(?:include|add_header|fastcgi_pass)\s', params)):
        raise CacheManageError('compatibility',
            'Native PHP PATH_INFO parameters need manual compatibility review')
    # The managed location defines Cache diagnostics via add_header. On Nginx
    # 1.28 this suppresses inherited http/server-level response headers.
    # Preserve only the exact native server HSTS in a source-pinned journal.
    ext = 'include '+vhost_root+'/extension/'+site['name']+'/*.conf;'
    php_line = 'include enable-php-'+php+php_suffix+'.conf;'
    native_server_hsts = _site_hsts_header(active, ext, php_line)
    # Native WordPress PHP location already overrides server add_header;
    # its exact native PHP-level response headers are copied separately.
    inherited_hsts = native_server_hsts if native_handler == 'stock' else None
    # A native aaPanel PHP switch leaves the saved Cache extension pinned to
    # its original PHP handler. Explain the two independently observed versions
    # without treating the new include as approved or changing recovery gates.
    php_includes = re.findall(r'\binclude\s+enable-php-[^\s;]+\s*;', active)
    if (native_handler == 'stock' and len(php_includes) == 1 and php in ('81', '85')
            and active.count(ext) == 1 and
            php_includes[0] != php_line):
        alternate = re.fullmatch(r'include enable-php-(81|85)\.conf;',
                                 php_includes[0])
        if (alternate and alternate.group(1) != php):
            observed = alternate.group(1)
            raise CacheManageError(
                'compatibility',
                'Native site PHP include differs from saved Cache PHP %s.%s '
                '(observed PHP %s.%s); reconcile PHP in aaPanel and Recheck '
                'before Restore' %
                (php[0], php[1], observed[0], observed[1]))
    # Stock aaPanel 8.0.7 nginxAdd() creates new VHosts without the
    # per-site extension glob. Diagnose only that exact missing-include
    # condition, not a commented, competing, edited or mixed include. This
    # is operator guidance: never bootstrap a vendor-generated VHost here.
    if (active.count(ext) == 0 and ext not in vhost.decode()
            and len(php_includes) == 1 and php_includes[0] == php_line
            and not re.search(r'\binclude\s+[^;\n]*/extension/[^;\n]*;', active)
            and not re.search(r'\bfastcgi_cache(?:_purge)?\b', active)
            and not re.search(r'\blocation\s+~', active[:active.index(php_line)])):
        _missing_extension_inventory(site, vhost_root)
        raise CacheManageError(
            'compatibility',
            'Native aaPanel site VHost is missing the per-site extension include. '
            'Native site statistics may add it later; refresh the site Config and '
            'rerun Cache readiness before any manual edit. If still missing, use '
            'the latest native Config editor and recheck. No VHost/Cache change was made.',
            reason_code='native_extension_include_missing')
    native_subdir = 'include '+vhost_root+'/sub_dir/'+site['name']+'/*.conf;'
    subdir_refs = re.findall(r'\binclude\s+[^;\n]*/sub_dir/[^;\n]*;', active)
    if subdir_refs:
        if (subdir_refs != [native_subdir] or active.count(native_subdir) != 1
                or active.find(native_subdir) > active.find(ext)
                or not _native_server_direct_include(
                    active, native_subdir[len('include '):-1])):
            raise CacheManageError(
                'compatibility', 'Unverified native per-site subdirectory include')
        try:
            _native_unused_subdir(vhost_root, site['name'])
        except (OSError, MonitorInputError) as exc:
            raise CacheManageError(
                'compatibility', 'Native subdirectory routing needs review') from exc
    if (active.count(ext) != 1 or len(php_includes) != 1
            or php_includes[0] != php_line
            or active.index(ext) > active.index(php_line)
            or re.search(r'\bfastcgi_cache(?:_purge)?\b', active)
            or re.search(r'\blocation\s+~', active[:active.find(ext)])):
        raise CacheManageError('compatibility','Unsupported selected native VHost include order or cache source')
    from ach_customizer_cache_audit import _direct_http_scope_at
    include = 'include '+vhost_root+'/*.conf;'
    matches = list(re.finditer(re.escape(include), main.decode()))
    if len(matches) != 1 or not _direct_http_scope_at(main.decode(),matches[0].start()):
        raise CacheManageError('compatibility',
                               'Direct native http{} VHost include glob is unverified')
    active_main = _active_nginx_text(main.decode())
    if any(_direct_http_scope_at(active_main, item.start())
           for item in re.finditer(r'\badd_header\s', active_main)):
        raise CacheManageError('compatibility',
            'HTTP-level response headers cannot be inherited by Cache handler')
    rewrite_include = ('include '+str(Path(vhost_root).parent/'rewrite'/
                                      (site['name']+'.conf'))+';')
    rewrite = b''
    if rewrite_include in active:
        rewrite, _ = _read_source(str(Path(vhost_root).parent/'rewrite'/
                                      (site['name']+'.conf')))
        if re.search(r'\badd_header\s', _active_nginx_text(rewrite.decode())):
            raise CacheManageError('compatibility',
                'Native rewrite response headers need manual Cache review')
    return {'vhost_sha':_hash(vhost+b'\0'+rewrite), 'main_sha':_hash(main),
            'php_sha':_hash(php_include+b'\0'+fastcgi+b'\0'+pathinfo),
            'inherited_hsts': inherited_hsts, 'native_handler': native_handler}


def _path_owned(site_id, *, cache_root=CACHE_ROOT, allow_missing=False):
    """Reject symlink, mount/bind aliases and foreign per-site cache trees."""
    if cache_root != CACHE_ROOT:
        raise CacheManageError('ownership','Unknown cache root')
    root = Path(cache_root)
    # Check every existing component with O_NOFOLLOW, not Path.resolve() which
    # would silently follow an attacker-supplied directory alias.
    chain = Path('/')
    previous = None
    for part in root.parts[1:]:
        chain = chain / part
        try:
            fd = os.open(chain, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        except FileNotFoundError:
            if allow_missing and chain == root:
                return None
            raise CacheManageError('ownership','Cache parent is absent or unexpectedly aliased')
        info = os.fstat(fd)
        os.close(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            if chain == Path('/'):
                continue
            raise CacheManageError('ownership','Untrusted cache ancestor')
        previous = info
    sitepath = root / ('site-'+str(site_id))
    # st_dev/inode alone do not detect same-device bind mounts. Mountinfo
    # exposes such mounts even when os.path.ismount() returns False.
    # Never activate or use a managed tree with a mount nested inside it.
    try:
        with open('/proc/self/mountinfo', encoding='utf-8') as mountinfo:
            for line in mountinfo:
                fields = line.split()
                if len(fields) < 5:
                    raise CacheManageError('ownership', 'Malformed mount table')
                escaped = fields[4]
                mountpoint = re.sub(
                    r'\\([0-7]{3})',
                    lambda m: chr(int(m.group(1), 8)), escaped)
                if (mountpoint == str(root) or
                        mountpoint.startswith(str(root) + '/')):
                    raise CacheManageError('ownership',
                                           'Unexpected managed cache mount or bind alias')
    except (OSError, UnicodeError) as exc:
        raise CacheManageError('ownership',
                               'Cache physical-mount graph unavailable') from exc
    try:
        sitefd = os.open(sitepath, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise CacheManageError('ownership','Site-owned cache directory missing')
    try:
        info=os.fstat(sitefd)
        www=pwd.getpwnam('www')
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != www.pw_uid
                or info.st_gid != www.pw_gid or stat.S_IMODE(info.st_mode) != 0o750
                or os.path.ismount(sitepath) or info.st_dev != previous.st_dev):
            raise CacheManageError('ownership','Site-owned cache directory has changed')
        # Different site names are NOT sufficient: verify no inode aliases.
        for entry in root.iterdir():
            if not entry.name.startswith('site-') or entry == sitepath:
                continue
            peer = os.stat(entry, follow_symlinks=False)
            if (not stat.S_ISDIR(peer.st_mode) or peer.st_dev != info.st_dev
                    or (peer.st_dev,peer.st_ino) == (info.st_dev,info.st_ino)):
                raise CacheManageError('ownership','Cache roots may share a mount or physical identity')
        return (info.st_dev,info.st_ino)
    finally:
        os.close(sitefd)



def _cache_directory_identity_chain(path):
    """Pin every component of one native cache path without following symlinks.

    Identity chains detect both external bind mounts pointing at the selected
    directory and peer cache roots containing/contained in that directory.
    No peer path supplied by the browser is ever accepted here.
    """
    if (not isinstance(path, str) or not path.startswith('/') or
            path.startswith('//') or
            any(part in ('', '.', '..') for part in path.split('/')[1:])):
        raise CacheManageError('compatibility',
                               'Unverified registered Cache directory path')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    identities = []
    try:
        parent = os.fstat(fd)
        identities.append((parent.st_dev, parent.st_ino))
        for name in path.split('/')[1:]:
            next_fd = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            info = os.fstat(fd)
            identities.append((info.st_dev, info.st_ino))
        return tuple(identities)
    finally:
        os.close(fd)


def _cache_mount_target_identity(path):
    """No-follow identity of a mount target (directory OR regular Cache file)."""
    parent, name = path.rsplit('/', 1)
    if not parent or not name or name in ('.', '..'):
        raise CacheManageError('compatibility', 'Unverified peer Cache mount target')
    # Anchor the parent descriptor one component at a time: an intermediate
    # symlink cannot redirect this inspection outside the registered tree.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in parent.split('/')[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        target = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not (stat.S_ISDIR(target.st_mode) or stat.S_ISREG(target.st_mode)):
            raise CacheManageError('compatibility', 'Unverified peer Cache mount object')
        return (target.st_dev, target.st_ino)
    finally:
        os.close(fd)


def _cache_peer_mounts(selected_path, peer_directories):
    """Inspect Linux mountpoints within, at, or exclusively above peer roots.

    A bind mount can expose one selected-site Cache subtree through a peer
    root, descendant or exclusive ancestor. Do not reject unrelated mounts:
    compare their actual source object identities to selected Cache objects.
    Keep mount IDs to detect observed topology drift between passes.
    """
    nested = []
    try:
        with open('/proc/self/mountinfo', encoding='utf-8') as source:
            for line in source:
                fields = line.split()
                if len(fields) < 10 or '-' not in fields[6:]:
                    raise CacheManageError('compatibility',
                                           'Registered peer Cache mount table is malformed')
                path = re.sub(r'\\([0-7]{3})',
                              lambda m: chr(int(m.group(1), 8)), fields[4])
                for directory in peer_directories:
                    if (path == directory or path.startswith(directory + '/') or
                            (directory.startswith(path.rstrip('/') + '/') and
                             not selected_path.startswith(path.rstrip('/') + '/'))):
                        nested.append((directory, path, fields[0],
                                       _cache_mount_target_identity(path)))
    except (OSError, UnicodeError) as exc:
        raise CacheManageError('compatibility',
                               'Registered peer Cache mount table is unavailable') from exc
    return tuple(sorted(nested))


def _selected_cache_contains_mount_identity(selected_path, expected_identity,
                                            mount_identities):
    """Check actual selected Nginx objects only when a peer has nested mounts.

    Depth is the selected owned Nginx levels=1:2 layout; stream directory
    entries, keeping only the small set of suspicious mount-target identities.
    This also detects a bind mount of an individual selected cache file.
    """
    possible = set(mount_identities)
    if not possible:
        return False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = os.open(selected_path, flags)
    try:
        info = os.fstat(root_fd)
        if (info.st_dev, info.st_ino) != tuple(expected_identity):
            raise CacheManageError('concurrency',
                                   'Selected Cache root changed during peer inspection')
        if (info.st_dev, info.st_ino) in possible:
            return True
        # Actual Nginx levels=1:2 directories, no arbitrary recursion.
        # Foreign entries are validated by the normal two-pass file scanner.
        with os.scandir(root_fd) as first_entries:
            for first in first_entries:
                if not first.is_dir(follow_symlinks=False):
                    continue
                first_fd = os.open(first.name, flags, dir_fd=root_fd)
                try:
                    f = os.fstat(first_fd)
                    if (f.st_dev, f.st_ino) in possible:
                        return True
                    with os.scandir(first_fd) as second_entries:
                        for second in second_entries:
                            if not second.is_dir(follow_symlinks=False):
                                continue
                            second_fd = os.open(second.name, flags, dir_fd=first_fd)
                            try:
                                q = os.fstat(second_fd)
                                if (q.st_dev, q.st_ino) in possible:
                                    return True
                                with os.scandir(second_fd) as objects:
                                    for obj in objects:
                                        sig = obj.stat(follow_symlinks=False)
                                        if (sig.st_dev, sig.st_ino) in possible:
                                            return True
                            finally:
                                os.close(second_fd)
                finally:
                    os.close(first_fd)
        return False
    finally:
        os.close(root_fd)


def _cache_peer_symlink_targets(peer_directories, selected_device):
    """Read peer Nginx levels=1:2 symlinks without following unverified writes.

    Stream ordinary peer entries. Only a symlink (or objects reached below
    one) contributes physical identities: normal peer files are independent
    unless already covered by the mount table or a checked symlink.
    Following a peer symlink is read-only, relative to a pinned parent fd;
    the opened directory must have the previously observed target identity.
    No peer path is ever used for unlink.
    """
    links = []
    identities = set()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC

    def walk(parent_fd, peer, prefix, depth, linked_parent):
        with os.scandir(parent_fd) as entries:
            for entry in entries:
                # The ordinary peer Cache may contain many regular files.
                # Directory-entry type avoids a stat() for each non-link
                # leaf unless the parent was itself reached via a symlink.
                if depth == 2 and not linked_parent and not entry.is_symlink():
                    continue
                rel = prefix + entry.name
                raw = entry.stat(follow_symlinks=False)
                linked = stat.S_ISLNK(raw.st_mode)
                if linked:
                    resolved = entry.stat(follow_symlinks=True)
                    if (depth < 2 and not stat.S_ISDIR(resolved.st_mode) or
                            depth == 2 and not stat.S_ISREG(resolved.st_mode)):
                        raise CacheManageError(
                            'compatibility', 'Registered peer Cache symlink has unverified target')
                    links.append((peer, rel, raw.st_dev, raw.st_ino,
                                  raw.st_mtime_ns, resolved.st_dev, resolved.st_ino))
                elif depth < 2:
                    if not stat.S_ISDIR(raw.st_mode):
                        continue
                    resolved = raw
                else:
                    if not linked_parent:
                        continue  # Ordinary Cache files have no symlink exposure.
                    resolved = raw
                if (linked or linked_parent) and resolved.st_dev == selected_device:
                    identities.add((resolved.st_dev, resolved.st_ino))
                if depth == 2:
                    continue
                child = os.open(entry.name, flags | (0 if linked else os.O_NOFOLLOW),
                                dir_fd=parent_fd)
                try:
                    actual = os.fstat(child)
                    if (actual.st_dev, actual.st_ino) != (resolved.st_dev, resolved.st_ino):
                        raise CacheManageError(
                            'concurrency', 'Registered peer Cache object changed during scan')
                    walk(child, peer, rel + '/', depth + 1, linked_parent or linked)
                finally:
                    os.close(child)

    for peer in sorted(peer_directories):
        # Re-open each registered root by no-follow, directory-relative
        # components, rather than trusting a path with a replaced ancestor.
        fd = os.open('/', flags | os.O_NOFOLLOW)
        try:
            for name in peer.split('/')[1:]:
                child = os.open(name, flags | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            walk(fd, peer, '', 0, False)
        finally:
            os.close(fd)
    return tuple(sorted(links)), identities


def _verify_cache_peer_isolation(selected_path, expected_identity, peer_paths):
    """Prove relevant native peer cache trees are physically separate.

    A distinct canonical pathname is not enough: an external bind mount may
    name the selected inode, and a peer root may overlap its subtree.
    Rechecks around deletion detect observed topology changes; they cannot
    make arbitrary external mount changes atomic with Nginx traffic.
    """
    if not isinstance(peer_paths, list):
        raise CacheManageError('compatibility',
                               'Registered peer Cache directory inventory unavailable')
    if not peer_paths:
        return ()
    try:
        selected_chain = _cache_directory_identity_chain(selected_path)
        if selected_chain[-1] != tuple(expected_identity):
            raise CacheManageError('concurrency',
                                   'Selected Cache directory physical identity changed')
        verified = []
        seen = set()
        peer_directories = set()
        for peer in peer_paths:
            if (not isinstance(peer, dict) or set(peer) != {'id', 'directory'}
                    or type(peer['id']) is not int or peer['id'] < 1
                    or peer['id'] in seen):
                raise CacheManageError('compatibility',
                                       'Registered peer Cache identity is ambiguous')
            seen.add(peer['id'])
            # Missing global keys_zone paths are not proof of isolation.
            directory = peer['directory']
            peer_chain = _cache_directory_identity_chain(directory)
            if (selected_chain[-1] in peer_chain or
                    peer_chain[-1] in selected_chain):
                raise CacheManageError('compatibility',
                                       'Registered Cache directories physically overlap')
            verified.append((peer['id'], directory, peer_chain))
            peer_directories.add(directory)

        # Root identity alone misses an external bind of site/8 into
        # peer/8. Inspect actual mount destinations anywhere under the
        # registered peer roots, without rejecting unrelated mounted trees.
        nested = _cache_peer_mounts(selected_path, peer_directories)
        links, linked_objects = _cache_peer_symlink_targets(
            peer_directories, selected_chain[-1][0])
        candidates = ({identity for _, _, _, identity in nested
                       if identity[0] == selected_chain[-1][0]} | linked_objects)
        if (candidates.intersection(selected_chain) or
                _selected_cache_contains_mount_identity(
                    selected_path, expected_identity, candidates)):
            raise CacheManageError(
                'compatibility', 'Registered Cache subtrees physically overlap')
        return (tuple(verified), nested, links)
    except (OSError, UnicodeError) as exc:
        raise CacheManageError('compatibility',
                               'Registered peer Cache physical separation is unverified') from exc



def _scan_site_cache_files(site_id, expected_identity, *, remove=False):
    """Validate Nginx levels=1:2 objects inside ONE already-owned cache tree.

    No arbitrary recursive delete: foreign entries, links, mounts, hard links,
    changed inodes or unexpected layouts are not adopted as managed cache.
    Leave the Nginx-owned directories present so workers can continue writing.
    """
    identity = _path_owned(site_id)
    if identity != tuple(expected_identity):
        raise CacheManageError('ownership', 'Selected Cache directory identity changed')
    root_fd = os.open(CACHE_ROOT + '/site-' + str(site_id),
                      os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    www = pwd.getpwnam('www')
    count = 0

    def child_dir(parent_fd, name, expected_dev):
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(before.st_mode) or before.st_dev != expected_dev
                or before.st_uid != www.pw_uid or before.st_gid != www.pw_gid
                or stat.S_IMODE(before.st_mode) != 0o700):
            raise CacheManageError('ownership', 'Unexpected object inside site Cache tree')
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                     os.O_CLOEXEC, dir_fd=parent_fd)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            os.close(fd)
            raise CacheManageError('concurrency', 'Site Cache directory changed during scan')
        return fd

    try:
        top = os.fstat(root_fd)
        if (top.st_dev, top.st_ino) != identity:
            raise CacheManageError('concurrency', 'Selected Cache directory changed during scan')
        for first in sorted(os.listdir(root_fd)):
            if not re.fullmatch(r'[0-9a-f]', first):
                raise CacheManageError('ownership', 'Unexpected top-level site Cache object')
            first_fd = child_dir(root_fd, first, top.st_dev)
            try:
                for second in sorted(os.listdir(first_fd)):
                    if not re.fullmatch(r'[0-9a-f]{2}', second):
                        raise CacheManageError('ownership', 'Unexpected nested site Cache object')
                    second_fd = child_dir(first_fd, second, top.st_dev)
                    try:
                        for name in sorted(os.listdir(second_fd)):
                            if (not TOKEN.fullmatch(name) or name[-1] != first
                                    or name[-3:-1] != second):
                                raise CacheManageError('ownership', 'Unexpected site Cache filename')
                            before = os.stat(name, dir_fd=second_fd, follow_symlinks=False)
                            if (not stat.S_ISREG(before.st_mode) or before.st_dev != top.st_dev
                                    or before.st_uid != www.pw_uid or before.st_gid != www.pw_gid
                                    or stat.S_IMODE(before.st_mode) != 0o600
                                    or before.st_nlink != 1):
                                raise CacheManageError('ownership', 'Untrusted site Cache file')
                            if remove:
                                fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW |
                                             os.O_CLOEXEC, dir_fd=second_fd)
                                try:
                                    actual = os.fstat(fd)
                                    if (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
                                        raise CacheManageError('concurrency', 'Site Cache file changed during clear')
                                    current = os.stat(name, dir_fd=second_fd, follow_symlinks=False)
                                    if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                                        raise CacheManageError('concurrency', 'Site Cache filename changed during clear')
                                    os.unlink(name, dir_fd=second_fd)
                                finally:
                                    os.close(fd)
                            count += 1
                        if remove:
                            os.fsync(second_fd)
                    finally:
                        os.close(second_fd)
            finally:
                os.close(first_fd)
        if _path_owned(site_id) != identity:
            raise CacheManageError('concurrency', 'Site Cache ownership changed during clear')
        return count
    finally:
        os.close(root_fd)


# A deliberately narrow invalidation path for the site-owned Cache policy.
# Its key is $scheme$request_method$host$request_uri|<saved generation>.
# Nginx stores MD5(key) under levels=1:2. A verified Nginx KEY header is
# required; a matching filename alone is not proof of the cached response.
_CACHEABLE_URI = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@/-]{0,1023}\Z")


def _cache_url_path(value):
    if (type(value) is not str or not _CACHEABLE_URI.fullmatch(value)
            or '//' in value or re.search(r'(^|/)\.{1,2}(?:/|$)', value)):
        raise CacheManageError('input',
            'Cache URL must be a canonical path beginning with /; no query, '
            'fragment, encoded/ambiguous path or external URL is supported')
    return value


def _clear_site_cache_url(site_id, identity, site_key, generation, path):
    """Remove only exact current-generation HTTP(S) GET/HEAD cache objects.

    This is NOT a WordPress/Nginx Helper purge hook. It deliberately accepts
    only the selected site's primary Host and already-cacheable ASCII paths.
    Missing objects mean no cached entry; traffic can refill them immediately.
    """
    path = _cache_url_path(path)
    if not SITE_KEY.fullmatch(site_key) or not TOKEN.fullmatch(generation):
        raise CacheManageError('recovery', 'Unverified Cache key identity')
    if _path_owned(site_id) != tuple(identity):
        raise CacheManageError('ownership', 'Selected Cache directory identity changed')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = os.open(CACHE_ROOT + '/site-' + str(site_id), flags)
    www = pwd.getpwnam('www')
    removed = 0

    def directory(parent_fd, name, dev):
        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if (not stat.S_ISDIR(before.st_mode) or before.st_dev != dev
                or (before.st_uid, before.st_gid) != (www.pw_uid, www.pw_gid)
                or stat.S_IMODE(before.st_mode) != 0o700):
            raise CacheManageError('ownership', 'Untrusted Cache key directory')
        fd = os.open(name, flags, dir_fd=parent_fd)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            os.close(fd)
            raise CacheManageError('concurrency', 'Cache key directory changed')
        return fd

    try:
        top = os.fstat(root_fd)
        if (top.st_dev, top.st_ino) != tuple(identity):
            raise CacheManageError('concurrency', 'Selected Cache directory changed')
        for scheme in ('http', 'https'):
            for method in ('GET', 'HEAD'):
                key = (scheme + method + site_key.lower() + path + '|' + generation).encode('ascii')
                digest = hashlib.md5(key).hexdigest()  # Nginx disk key, not a security digest.
                first_fd = directory(root_fd, digest[-1], top.st_dev)
                if first_fd is None:
                    continue
                try:
                    second_fd = directory(first_fd, digest[-3:-1], top.st_dev)
                    if second_fd is None:
                        continue
                    try:
                        try:
                            before = os.stat(digest, dir_fd=second_fd, follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if (not stat.S_ISREG(before.st_mode) or
                                before.st_dev != top.st_dev or before.st_nlink != 1 or
                                (before.st_uid, before.st_gid) != (www.pw_uid, www.pw_gid) or
                                stat.S_IMODE(before.st_mode) != 0o600):
                            raise CacheManageError('ownership', 'Untrusted Cache key file')
                        fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW |
                                     os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=second_fd)
                        try:
                            actual = os.fstat(fd)
                            if (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
                                raise CacheManageError('concurrency', 'Cache key file changed')
                            header = os.read(fd, 4096)
                            marker = b'KEY: ' + key + b'\n'
                            # Native 1.28.x cache headers precede the KEY line;
                            # reject an unsupported object instead of guessing.
                            offset = header.find(marker)
                            if offset < 0 or offset > 1536:
                                raise CacheManageError('ownership',
                                                       'Cached object KEY header differs from the requested URL')
                            current = os.stat(digest, dir_fd=second_fd, follow_symlinks=False)
                            if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                                raise CacheManageError('concurrency', 'Cache key filename changed')
                            os.unlink(digest, dir_fd=second_fd)
                            removed += 1
                        finally:
                            os.close(fd)
                        os.fsync(second_fd)
                    finally:
                        os.close(second_fd)
                finally:
                    os.close(first_fd)
        if _path_owned(site_id) != tuple(identity):
            raise CacheManageError('concurrency', 'Selected Cache directory changed during URL clear')
        return removed
    finally:
        os.close(root_fd)


def _create_site_cache(site_id):
    parent = Path(CACHE_ROOT).parent
    parent_fd = _directory(str(parent))
    try:
        _owned_dir(parent_fd)
        try:
            os.mkdir(Path(CACHE_ROOT).name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    rootfd = _directory(CACHE_ROOT)
    try:
        _owned_dir(rootfd, 0o755)
        name='site-'+str(site_id)
        try:
            os.mkdir(name, mode=0o750, dir_fd=rootfd)
        except FileExistsError as exc:
            raise CacheManageError('ownership','Existing site cache directory must be reviewed before activation') from exc
        sitefd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=rootfd)
        try:
            www=pwd.getpwnam('www')
            os.fchown(sitefd,www.pw_uid,www.pw_gid)
            os.fchmod(sitefd,0o750)
            os.fsync(sitefd)
        finally:
            os.close(sitefd)
        os.fsync(rootfd)
    finally:
        os.close(rootfd)
    _path_owned(site_id)


def _cache_files(state_fd, site, *, vhost_root=VHOST_ROOT):
    global_name,ext_name,_=_names(site['id'])
    global_fd=_directory(vhost_root)
    try:
        extension_fd=_directory(vhost_root+'/extension/'+site['name'])
    except BaseException:
        os.close(global_fd)
        raise
    try:
        _owned_dir(global_fd)
        _owned_dir(extension_fd)
        return (global_fd,extension_fd,
                _bounded_file(global_fd,global_name,limit=4096,permissions=0o600),
                _bounded_file(extension_fd,ext_name,limit=8192,permissions=0o600))
    except BaseException:
        os.close(global_fd)
        os.close(extension_fd)
        raise


def _probe(site, *, marker=None):
    """Loopback PHP handler observation; never DNS, tokens or remote traffic."""
    if (not SITE_KEY.fullmatch(site['name']) or
            not any(x.get('name')==site['name'] and x.get('port')==80
                    for x in site.get('bound_domains',[]))):
        raise CacheManageError('probe','Native HTTP/80 identity is unavailable')
    conn=http.client.HTTPConnection('127.0.0.1',80,timeout=5)
    try:
        conn.request('HEAD','/index.php',headers={'Host':site['name'],
                     'Cache-Control':'no-store'})
        response=conn.getresponse()
        code=response.status
        observed=response.getheader('X-ACh-Cache-Site')
        upstream_cache=response.getheader('X-ACh-Cache')
        response.read(0)
        if not 200 <= code < 400:
            raise CacheManageError('probe','Registered PHP /index.php is not a healthy HTTP target')
        if marker is not None and (
                observed != str(marker) or
                upstream_cache not in ('BYPASS','MISS','HIT','EXPIRED','STALE','UPDATING','REVALIDATED')):
            # Nginx error pages can emit add_header ... always without
            # ever invoking the PHP upstream. Require FastCGI status too.
            raise CacheManageError('probe','Managed FastCGI upstream was not observed after reload')
        if marker is None and observed is not None:
            raise CacheManageError('probe','Unexpected cache handler before activation/after Restore')
        return code
    except (OSError,http.client.HTTPException) as exc:
        raise CacheManageError('probe','Registered local PHP handler request failed') from exc
    finally:
        conn.close()


def _await_php_route(site, *, marker, expected_status, probe=None):
    """Wait boundedly for a single reload's new workers; only read-only HEAD.

    Nginx -s reload acknowledges a signal, not new worker adoption. The
    last outcome is never converted into an extra reload or implicit Apply.
    """
    last = None
    for attempt in range(9):
        try:
            status = (probe or _probe)(site, marker=marker)
            if status == expected_status:
                return status
            last = CacheManageError('probe',
                'HTTP status differs from the pre-reload registered site')
        except Exception as exc:
            last = exc
        if attempt < 8:
            time.sleep(0.3)
    raise CacheManageError('probe',
        'Nginx route did not match its approved post-reload state') from last


def _compatibility(site, public, *, vhost_root=VHOST_ROOT, nginx_root=NGINX_ROOT,
                   cache_generation=None):
    native=inspect_site_fastcgi_cache(
        public, site['id'], site['name'],vhost_root=vhost_root,nginx_root=nginx_root,
        rewrite_root=str(Path(vhost_root).parent/'rewrite'))
    wp_source = (native['zone_state'] == 'Direct Zone'
                 and native['cache_zone'] == 'WORDPRESS'
                 and native['purge_directive_seen'])
    stock_source = (native['zone_state'] == 'No Direct Directive'
                    and not native['purge_directive_seen'])
    native_handler = 'wpfastcgi' if wp_source else 'stock'
    if (native['state'] != 'Source Observed'
            or not (stock_source or wp_source)
            or native['php_version'] not in ('81','85')
            or native['unresolved_other_sites'] != 0):
        raise CacheManageError('compatibility',
            'Existing cache, unsupported native PHP/include, or unresolved peer site requires review')
    from ach_customizer_vhost_drift import inspect_vhost_drift
    drift = inspect_vhost_drift(public,site,vhost_root=vhost_root)
    if drift['state'] != 'File Match' or 80 not in drift['listen_ports']:
        raise CacheManageError('compatibility',
                               'Native VHost does not match the exact site/root/HTTP binding')
    sources=_site_sources(site,native['php_version'],
                          native_handler=native_handler,
                          vhost_root=vhost_root,nginx_root=nginx_root)
    reference=generate_reference(site['id'],native['php_version'],
                                 cache_generation=cache_generation,
                                 inherited_hsts=sources['inherited_hsts'],
                                 native_handler=native_handler)
    return native,reference,sources


def _restored_generation_can_reapply(site, old, reference, *, vhost_root=VHOST_ROOT):
    """Allow another explicit Apply only with an exact, restored prior policy.

    Reuse the pinned site directory with a fresh generation. A fully restored
    schema-2 journal may precede an aaPanel site-key change or a supported
    stock-to-wpfastcgi source migration: its exact old fragments and physical
    identity must still match. No active/prepared recovery may be adopted.
    Prior journals are archived, not discarded.
    """
    prior_reference = generate_reference(
        site['id'], old['php_version'],
        cache_generation=old['cache_generation'],
        inherited_hsts=old.get('inherited_hsts'),
        native_handler=old.get('native_handler', 'stock'))
    prior_handler = old.get('native_handler', 'stock')
    current_handler = reference.get('native_handler', 'stock')
    changed_identity = old['site_key'] != site['name'] or prior_handler != current_handler
    if (old['phase'] != 'restored' or
            old['php_version'] != reference['php_version'] or
            (prior_handler != current_handler and
             (prior_handler, current_handler) != ('stock', 'wpfastcgi')) or
            (changed_identity and (old['schema'] != 2 or old['cache_identity'] is None)) or
            old['cache_generation'] == reference['cache_generation'] or
            old['proposal_sha'] != prior_reference['proposal_sha256']):
        raise CacheManageError('recovery',
            'Existing Cache generation cannot be reused without policy-specific recovery')
    global_name, ext_name, _ = _names(site['id'])
    expected_global, expected_ext = _expected_files(old)
    incomplete_setup = old['schema'] == 2 and old['cache_identity'] is None
    gfd, efd, g, e = _cache_files(None, site, vhost_root=vhost_root)
    try:
        previous_global = _bounded_file(gfd, global_name+'.'+old['op']+'.retained',
                                        limit=4096, permissions=0o600)
        previous_ext = _bounded_file(efd, ext_name+'.'+old['op']+'.retained',
                                     limit=8192, permissions=0o600)
        if (g is not None or e is not None or
                (previous_global,previous_ext) !=
                ((None,None) if incomplete_setup else (expected_global,expected_ext))):
            raise CacheManageError('recovery',
                'Previously restored Cache snippets are not byte-identical')
    finally:
        os.close(gfd)
        os.close(efd)
    if incomplete_setup:
        if _path_owned(site['id'], allow_missing=True) is not None:
            raise CacheManageError('ownership',
                'Incomplete Cache setup has an unexpected physical directory')
    elif old['schema'] == 2:
        _same_cache_identity(site['id'], old)
    elif _path_owned(site['id'], allow_missing=True) is None:
        # Historical unreleased journals did not store physical identities;
        # validate path ownership rather than silently adopting a missing tree.
        raise CacheManageError('ownership',
            'Prior managed Cache directory is missing, not safe to reuse')
    return changed_identity


def _archive_restored_record(statefd, record):
    name = _names(record['site_id'])[2]+'.'+record['op']+'.restored'
    payload = (json.dumps(record, sort_keys=True, separators=(',',':'))+'\n').encode()
    existing = _bounded_file(statefd, name, limit=8192, permissions=0o600)
    if existing is None:
        _publish_complete(statefd,name,payload,0o600,record['op'])
    elif existing != payload:
        raise CacheManageError('recovery',
            'Previous restored journal archive conflicts with saved recovery')


def preview_cache_activation(site,public,*,vhost_root=VHOST_ROOT,
                             nginx_root=NGINX_ROOT,data_dir=DATA_DIR,
                             cache_generation=None, probe=None):
    """Read-only approval preflight. This is NOT a runtime safety verdict."""
    if cache_generation is None:
        cache_generation = uuid4().hex
    if type(cache_generation) is not str or not TOKEN.fullmatch(cache_generation):
        raise CacheManageError('input','Invalid Cache approval generation')
    statefd=_open_state_dir(data_dir)
    try:
        old = _record_read(statefd,site['id'])
        _generation_unused(statefd, site['id'], cache_generation)
        if old is not None and old['cache_generation'] == cache_generation:
            raise CacheManageError('recovery',
                'Cache generation was already activated and cannot be reused')
        if old is not None and old['phase'] != 'restored':
            raise CacheManageError('recovery','Existing Cache record requires Recheck/Restore')
        native,reference,sources=_compatibility(
            site,public,vhost_root=vhost_root,nginx_root=nginx_root,
            cache_generation=cache_generation)
        restored_transition = False
        if old is not None:
            restored_transition = _restored_generation_can_reapply(
                site,old,reference,vhost_root=vhost_root)
        globfd,extensionfd,glob,extension=_cache_files(
            statefd,site,vhost_root=vhost_root)
        try:
            if glob is not None or extension is not None:
                raise CacheManageError('ownership','Native Cache filenames already exist')
        finally:
            os.close(globfd);os.close(extensionfd)
        if old is None and _path_owned(site['id'],allow_missing=True) is not None:
            raise CacheManageError('ownership','Existing Cache directory requires explicit recovery')
        # A static/404 site may have the same Nginx include shape but no
        # working PHP handler. Avoid presenting a plan that cannot pass the
        # mandatory Apply health check after operator consent.
        php_probe_status = (probe or _probe)(site, marker=None)
        return {'schema':1,'state':'Ready for Review','read_only':True,
                'php_probe_status':php_probe_status,
                'apply_supported':True,'runtime_verified':False,
                'site_id':site['id'],'site_key':site['name'],
                'source_sha256':native['source_sha256'],
                'proposal_sha256':reference['proposal_sha256'],
                'cache_generation':cache_generation,
                'php_version':native['php_version'],
                'native_handler': sources['native_handler'],
                'preserved_server_hsts': bool(sources['inherited_hsts']),
                'cache_zone':reference['cache_zone'],
                'cache_directory':reference['cache_directory'],
                'impact':'One selected HTTP/80 VHost and Nginx service reload; '
                'requires exact browser approval and after-state recovery',
                'note':('No writes/reload/purge in preview. Native wpfastcgi '
                        'response headers and PHP routing source-matched; '
                        'automatic Nginx Helper invalidation, live customer-session '
                        'privacy and Purge All remain unverified.'
                        if sources['native_handler'] == 'wpfastcgi' else
                        'No cache writes, reload, or purge in this read-only preview. '
                        'Native WordPress/WooCommerce/Nginx Helper acceptance remains independent.') +
                ((' Historical restored recovery %s belongs to site key %s (%s handler); '
                  'current site uses %s (%s handler). Exact retained fragments and '
                  'saved physical Cache identity matched, but application continuity '
                  'is NOT established. Approving Apply archives that recovery and '
                  'uses a new Cache generation without deleting older objects.' %
                  (old['op'], old['site_key'], old.get('native_handler', 'stock'),
                   site['name'], sources['native_handler']))
                 if restored_transition else '')}
    finally:
        os.close(statefd)


def _fragments(site_id, php_version, cache_generation, *, inherited_hsts=None,
               native_handler='stock'):
    reference=generate_reference(site_id,php_version,
                                 cache_generation=cache_generation,
                                 inherited_hsts=inherited_hsts,
                                 native_handler=native_handler)
    global_bytes=reference['global_http_fragment'].encode()
    extension_bytes=reference['site_server_fragment'].encode()
    return reference,global_bytes,extension_bytes


def verified_cache_extension(directory,site_id,site_key,name,text,*,state_dir=None):
    """Called by native Extension scanner; trust only exact owned journal/bytes."""
    if name != _names(site_id)[1] or Path(directory).name != site_key:
        raise CacheManageError('ownership','Unknown cache extension identity')
    statefd=_open_state_dir(state_dir or DATA_DIR)
    try:
        record=_record_read(statefd,site_id)
    finally:
        os.close(statefd)
    if (not record or record['site_key'] != site_key
            or record['phase'] not in ('prepared','applied')):
        raise CacheManageError('ownership','Cache extension lacks live recovery ownership')
    ref, _, extension_bytes = _fragments(
        site_id, record['php_version'], record['cache_generation'],
        inherited_hsts=record.get('inherited_hsts'),
        native_handler=record.get('native_handler', 'stock'))
    if (record['proposal_sha'] != ref['proposal_sha256']
            or record['extension_sha'] != _hash(extension_bytes)
            or text.encode() != extension_bytes):
        raise CacheManageError('ownership','Cache extension differs from owned generated source')
    fd=_directory(str(directory))
    try:
        _owned_dir(fd)
        if _bounded_file(fd,name,limit=8192,permissions=0o600) != extension_bytes:
            raise CacheManageError('ownership','Native Cache extension path was replaced')
    finally:
        os.close(fd)
    return record


def verified_cache_global(vhost_root, site_id, name, *, state_dir=None):
    if name != _names(site_id)[0]:
        raise CacheManageError('ownership','Unknown global Cache source name')
    statefd=_open_state_dir(state_dir or DATA_DIR)
    try:
        record=_record_read(statefd,site_id)
    finally:
        os.close(statefd)
    if not record or record['phase'] not in ('prepared','applied'):
        raise CacheManageError('ownership','Global Cache source lacks recovery ownership')
    ref, global_bytes, _ = _fragments(
        site_id, record['php_version'], record['cache_generation'],
        inherited_hsts=record.get('inherited_hsts'),
        native_handler=record.get('native_handler', 'stock'))
    fd=_directory(vhost_root)
    try:
        _owned_dir(fd)
        content=_bounded_file(fd,name,limit=4096,permissions=0o600)
    finally:
        os.close(fd)
    if (content != global_bytes or record['global_sha'] != _hash(global_bytes)
            or record['proposal_sha'] != ref['proposal_sha256']):
        raise CacheManageError('ownership','Global Cache source differs from owned generated source')
    return record

def _same_site_sources(site, record, *, vhost_root=VHOST_ROOT, nginx_root=NGINX_ROOT):
    source = _site_sources(site, record['php_version'],
                           native_handler=record.get('native_handler', 'stock'),
                           vhost_root=vhost_root, nginx_root=nginx_root)
    drift = [label for key, label in (
        ('vhost_sha', 'VHost/rewrite'), ('main_sha', 'main Nginx'),
        ('php_sha', 'PHP handler/parameters'))
        if source[key] != record[key]]
    if source['inherited_hsts'] != record.get('inherited_hsts'):
        drift.append('server HSTS')
    if drift:
        raise CacheManageError('concurrency',
            'Native Cache source changed since approval: ' + ', '.join(drift))


def _same_native_source_inventory(site, record, public, *,
                                  vhost_root=VHOST_ROOT, nginx_root=NGINX_ROOT,
                                  data_dir=DATA_DIR):
    """Guard the native extension glob in every recovery phase.

    The ordinary Apply/Restore lifecycle intentionally changes the managed
    fragment and directory metadata, so a blanket comparison with the saved
    full audit hash is invalid after publication. Still reject foreign routing
    from the included glob. Before any publication, the full original audit
    must also remain byte/fingerprint-identical to the approved snapshot.
    """
    try:
        _native_extension_fingerprint(
            Path(vhost_root) / 'extension' / site['name'],
            site_id=site['id'], site_key=site['name'],
            cache_state_dir=data_dir)
    except (OSError, ValueError) as exc:
        raise CacheManageError('concurrency',
            'Native Cache extension inventory changed or has unverified routing') from exc
    if record['schema'] == 2 and record['cache_identity'] is None:
        if public is None:
            raise CacheManageError('recovery',
                'Registered native website inventory is unavailable for empty Cache recovery')
        observed = inspect_site_fastcgi_cache(
            public, site['id'], site['name'], vhost_root=vhost_root,
            nginx_root=nginx_root,
            rewrite_root=str(Path(vhost_root).parent / 'rewrite'))
        if (observed.get('state') != 'Source Observed' or
                observed.get('source_sha256') != record['source_sha'] or
                observed.get('unresolved_other_sites') != 0):
            raise CacheManageError('concurrency',
                'Native Cache source inventory changed since prepared approval')


def _same_cache_identity(site_id, record):
    """The path is not enough: a valid-looking replacement inode is drift."""
    identity = _path_owned(site_id)
    if (not isinstance(identity, tuple) or len(identity) != 2 or
            record['schema'] != 2 or record['cache_identity'] != list(identity)):
        raise CacheManageError('ownership',
            'Saved Cache directory physical identity is missing or has changed')


def _safe_retire(fd, name, expected, operation):
    observed = _bounded_file(fd, name, limit=8192, permissions=0o600)
    retained = name + '.' + operation + '.retained'
    past = _bounded_file(fd, retained, limit=8192, permissions=0o600)
    if past is not None:
        if observed is not None or past != expected:
            raise CacheManageError('recovery', 'Retained Cache source differs from owned journal')
        return False
    if observed is None:
        return False
    if observed != expected:
        raise CacheManageError('ownership', 'Cache source was independently modified; do not overwrite')
    _rename_noreplace(fd, name, retained)
    os.fsync(fd)
    return True


def _expected_files(record):
    _, global_bytes, extension_bytes = _fragments(
        record['site_id'], record['php_version'], record['cache_generation'],
        inherited_hsts=record.get('inherited_hsts'),
        native_handler=record.get('native_handler', 'stock'))
    if (_hash(global_bytes) != record['global_sha'] or
            _hash(extension_bytes) != record['extension_sha']):
        raise CacheManageError('recovery', 'Generated Cache source no longer matches saved journal')
    return global_bytes, extension_bytes


def _empty_prepublication(site, record, *, vhost_root=VHOST_ROOT):
    """Read-only proof that a prepared operation never published Cache state.

    Only a schema-2 null identity can represent this crash window. Reuse the
    same exact-file/physical checks in Recheck and explicit no-op Restore.
    """
    if (record['schema'] != 2 or record['cache_identity'] is not None or
            record['phase'] not in ('prepared', 'restored')):
        raise CacheManageError('recovery', 'Not an empty prepublication Cache recovery')
    _expected_files(record)
    try:
        gfd, efd, g, e = _cache_files(None, site, vhost_root=vhost_root)
    except StatusPageError as exc:
        raise CacheManageError('ownership',
            'Untrusted Cache source during prepublication recovery') from exc
    try:
        if (g is not None or e is not None or
                _path_owned(site['id'], allow_missing=True) is not None):
            raise CacheManageError('recovery',
                'Incomplete Cache physical setup requires manual review')
    finally:
        os.close(gfd)
        os.close(efd)


def _cache_observation(site, record, public, *, vhost_root=VHOST_ROOT,
                       nginx_root=NGINX_ROOT, data_dir=DATA_DIR, probe=None):
    """Read-only full recovery identity, file and PHP observation."""
    state = 'Needs Review'
    reason = None
    recovery_scope = None
    gfd = efd = None
    try:
        _same_site_sources(site, record,
                           vhost_root=vhost_root, nginx_root=nginx_root)
        _same_native_source_inventory(
            site, record, public, vhost_root=vhost_root,
            nginx_root=nginx_root, data_dir=data_dir)
        if record['schema'] == 2 and record['cache_identity'] is None:
            # Before directory creation, there is no inode to compare. Prove
            # absence of BOTH managed files and the physical cache directory.
            _empty_prepublication(site, record, vhost_root=vhost_root)
            (probe or _probe)(site, marker=None)
            state = 'Recovery Required' if record['phase'] == 'prepared' else 'Restored'
            recovery_scope = 'prepublication'
        else:
            _same_cache_identity(site['id'], record)
            gfd, efd, g, e = _cache_files(None, site, vhost_root=vhost_root)
            gb, eb = _expected_files(record)
            if (g is not None and g != gb) or (e is not None and e != eb):
                raise CacheManageError('ownership',
                    'Managed Cache source differs from saved recovery')
            if record['phase'] == 'restored':
                if g is not None or e is not None:
                    raise CacheManageError('recovery',
                        'Restored Cache sources reappeared without an approved Apply')
                state = 'Restored'
            elif g == gb and e == eb:
                state = 'Recovery Required' if record['phase'] == 'prepared' else 'Applied'
            else:
                state = 'Recovery Required'
            if state in ('Applied', 'Restored'):
                result = (probe or _probe)(site, marker=site['id'] if state == 'Applied' else None)
                if record['phase'] == 'applied' and result != record['probe_status']:
                    raise CacheManageError('probe',
                        'PHP response status differs from saved recovery')
    except (StatusPageError, OSError, ValueError) as exc:
        state = 'Needs Review'
        recovery_scope = None
        reason = ('Recovery ownership/source verification: ' + str(exc))[:250]
    finally:
        if gfd is not None:
            os.close(gfd)
        if efd is not None:
            os.close(efd)
    response = {'schema': 1, 'state': state, 'read_only': True,
            'site_id': site['id'], 'site_key': site['name'],
            'recovery_id': record['op'], 'journal_phase': record['phase'],
            'runtime_verified': state in ('Applied', 'Restored') and recovery_scope is None,
            'purge_supported': False,
            'cache_directory': record['cache_directory'],
            'cache_zone': 'ACHFC_' + str(site['id']),
            'note': reason or (
                ('Cache never activated; explicit Restore can finalize the journal without reload.'
                 if record['phase'] == 'prepared' else
                 'Cache never activated; recovery journal already finalized without reload.')
                if recovery_scope == 'prepublication' else
                'File, physical directory and loopback PHP evidence only; '
                'real WP/Woo and Nginx Helper compatibility remains unverified.')}
    if recovery_scope is not None:
        response['recovery_scope'] = recovery_scope
    return response


def manage_cache(action, site, public=None, *, expected_source=None,
                 expected_proposal=None, recovery_id=None, approved=False,
                 data_dir=DATA_DIR, vhost_root=VHOST_ROOT, nginx_root=NGINX_ROOT,
                 runner=None, probe=None, cache_generation=None, cache_url_path=None):
    """Serialized guarded per-site cache and optional WordPress Bridge operations.

    Neither successful Nginx -t nor reload signaling by itself proves the
    target worker. A lost/ambiguous reload retains the journal and both source
    fragments for explicit reconciliation, never an automatic blind retry.
    """
    if action not in ('apply', 'restore', 'recheck', 'clear_files', 'clear_url',
                       'bridge_enable', 'bridge_disable', 'bridge_inspect'):
        raise CacheManageError('input', 'Unsupported Cache management operation')
    if (type(site.get('id')) is not int or
            not isinstance(site.get('name'), str) or
            not SITE_KEY.fullmatch(site['name'])):
        raise CacheManageError('identity', 'Unverified site identity')
    statefd = _open_state_dir(data_dir)
    try:
        try:
            # An Unmanaged Recheck must not create Monitor's shared lock file.
            # A managed operation already created that file under the writer lock.
            lockfd = _exclusive_lock(statefd, create=(action not in ('recheck', 'bridge_inspect')))
        except FileNotFoundError:
            if action not in ('recheck', 'bridge_inspect'):
                raise
            record = _record_read(statefd, site['id'])
            if record is not None:
                return {'schema': 1, 'state': 'Needs Review', 'read_only': True,
                        'site_id': site['id'], 'recovery_id': record['op'],
                        'runtime_verified': False, 'purge_supported': False,
                        'note': 'Existing recovery journal has no operation lock; manual review required.'}
            return {'schema': 1, 'state': 'Unmanaged', 'read_only': True,
                    'site_id': site['id'], 'recovery_id': None,
                    'runtime_verified': False, 'purge_supported': False}
        try:
            record = _record_read(statefd, site['id'])
            if action in ('bridge_enable', 'bridge_disable', 'bridge_inspect'):
                from ach_customizer_cache_bridge import (
                    BridgeError, enable as enable_bridge, disable as disable_bridge,
                    inspect as inspect_bridge,
                )
                if public is None:
                    raise CacheManageError('compatibility', 'Native site inventory required')
                if action == 'bridge_inspect':
                    try:
                        status = inspect_bridge(site, public, record)
                    except (BridgeError, OSError) as exc:
                        status = 'Needs Review: ' + str(exc)
                    return {'schema':1, 'state':status, 'read_only':True,
                            'site_id':site['id'], 'site_key':site['name'],
                            'recovery_id':record['op'] if record else None,
                            'runtime_verified':False, 'purge_supported':False,
                            'note':'WordPress-side registration, Nginx Helper options '
                                   'and live Nginx workers are not proven by this file check.'}
                if approved is not True:
                    raise CacheManageError('authorization',
                                           'Explicit WordPress Bridge approval required')
                if action == 'bridge_disable':
                    try:
                        changed = disable_bridge(site, public)
                    except (BridgeError, OSError) as exc:
                        raise CacheManageError('recovery',
                                               'Unable to disable site Bridge: ' + str(exc)) from exc
                    return {'schema':1, 'state':'Not Provisioned', 'changed':changed,
                            'site_id':site['id'], 'site_key':site['name'],
                            'read_only':False, 'runtime_verified':False,
                            'purge_supported':False,
                            'note':'Native site manifest removed; Nginx Helper options '
                                   'and any shared Purge All settings are unchanged.'}
                if (record is None or record['site_key'] != site['name']
                        or record['schema'] != 2 or record['phase'] != 'applied'
                        or record.get('native_handler') != 'wpfastcgi'
                        or recovery_id != record['op']):
                    raise CacheManageError('recovery',
                        'Verified Applied native WordPress Cache and matching recovery ID required')
                observed = _cache_observation(
                    site, record, public, vhost_root=vhost_root,
                    nginx_root=nginx_root, data_dir=data_dir, probe=probe)
                if observed.get('state') != 'Applied' or not observed.get('runtime_verified'):
                    raise CacheManageError('recovery',
                                           'Cache is not currently verified Applied')
                native = inspect_site_fastcgi_cache(
                    public, site['id'], site['name'], vhost_root=vhost_root,
                    nginx_root=nginx_root,
                    rewrite_root=str(Path(vhost_root).parent / 'rewrite'),
                    include_physical_peers=True)
                if (native.get('state') != 'Source Observed'
                        or native.get('zone_state') != 'Direct Zone'
                        or native.get('cache_zone') != 'ACHFC_' + str(site['id'])
                        or native.get('cache_directory') != record['cache_directory']
                        or native.get('unresolved_other_sites') != 0
                        or native.get('other_sites_same_directory')
                        or native.get('other_sites_same_zone')):
                    raise CacheManageError('compatibility',
                                           'Current site Cache isolation is unverified')
                peer_paths = native.get('physical_peer_cache_paths')
                identities = _verify_cache_peer_isolation(
                    record['cache_directory'], record['cache_identity'], peer_paths)
                try:
                    changed = enable_bridge(site, public, record)
                    if (_verify_cache_peer_isolation(
                            record['cache_directory'], record['cache_identity'],
                            peer_paths) != identities or
                        _cache_observation(site, record, public, vhost_root=vhost_root,
                            nginx_root=nginx_root, data_dir=data_dir,
                            probe=probe).get('state') != 'Applied'):
                        raise CacheManageError('uncertain',
                            'Bridge provisioned while Cache sources changed; Disable and Recheck')
                except (BridgeError, OSError) as exc:
                    raise CacheManageError('compatibility',
                        'WordPress Bridge provisioning refused: ' + str(exc)) from exc
                return {'schema':1, 'state':'Provisioned', 'changed':changed,
                        'site_id':site['id'], 'site_key':site['name'],
                        'recovery_id':record['op'], 'read_only':False,
                        'runtime_verified':False, 'purge_supported':False,
                        'note':'A native-owned site manifest is present; WordPress '
                               'Bridge activation, Nginx Helper unlink_files, real '
                               'worker state and vendor Purge All are NOT certified.'}

            if action == 'recheck':
                if record is None:
                    return {'schema': 1, 'state': 'Unmanaged', 'read_only': True,
                            'site_id': site['id'], 'recovery_id': None,
                            'runtime_verified': False, 'purge_supported': False}
                if record['site_key'] != site['name']:
                    return {'schema': 1, 'state': 'Needs Review', 'read_only': True,
                            'site_id': site['id'], 'recovery_id': record['op'],
                            'runtime_verified': False, 'purge_supported': False}
                return _cache_observation(site, record, public,
                                          vhost_root=vhost_root, nginx_root=nginx_root,
                                          data_dir=data_dir, probe=probe)

            if approved is not True:
                raise CacheManageError('authorization', 'Explicit current Cache approval required')
            if action in ('clear_files', 'clear_url'):
                if action == 'clear_url':
                    cache_url_path = _cache_url_path(cache_url_path)
                if (record is None or record['site_key'] != site['name']
                        or record['schema'] != 2 or record['phase'] != 'applied' or
                        recovery_id != record['op']):
                    raise CacheManageError('recovery',
                        'Fresh Applied Cache Recheck and matching recovery ID required')
                observed = _cache_observation(
                    site, record, public, vhost_root=vhost_root,
                    nginx_root=nginx_root, data_dir=data_dir, probe=probe)
                if observed['state'] != 'Applied' or not observed['runtime_verified']:
                    raise CacheManageError('recovery',
                        'Site Cache is not verified Applied; reconcile and Recheck')
                # The directory inode alone does not prove no other native
                # website now targets this tree. Check the complete registered
                # source inventory again, not only the saved Apply snapshot.
                if public is None:
                    raise CacheManageError('compatibility',
                        'Native website inventory required for site Cache file clear')
                native = inspect_site_fastcgi_cache(
                    public, site['id'], site['name'], vhost_root=vhost_root,
                    nginx_root=nginx_root,
                    rewrite_root=str(Path(vhost_root).parent / 'rewrite'),
                    include_physical_peers=True)
                if (native.get('state') != 'Source Observed' or
                        native.get('zone_state') != 'Direct Zone' or
                        native.get('cache_zone') != 'ACHFC_' + str(site['id']) or
                        native.get('cache_directory') != record['cache_directory'] or
                        native.get('unresolved_other_sites') != 0 or
                        native.get('other_sites_same_directory') or
                        native.get('other_sites_same_zone')):
                    raise CacheManageError('compatibility',
                        'Registered Cache source isolation requires fresh review')
                # Source-text path inequality does not exclude an external
                # bind-mount/symlink alias to this site's physical directory.
                # Verify all registered cache-using peers' pinned dev/inode
                # chains, then recheck before the first unlink.
                peer_paths = native.get('physical_peer_cache_paths')
                identities = _verify_cache_peer_isolation(
                    record['cache_directory'], record['cache_identity'], peer_paths)
                # Whole-tree Clear must inspect every object before deleting.
                # Single-URL clear checks only the exact MD5/key objects and
                # their parents; scanning the entire cache is unnecessary.
                if action == 'clear_files':
                    try:
                        _scan_site_cache_files(site['id'], record['cache_identity'])
                    except OSError as exc:
                        raise CacheManageError('ownership',
                            'Selected Cache files are not safely enumerable') from exc
                # Nginx may concurrently repopulate cache objects. An uncertain
                # unlink cannot be reported as a confirmed successful purge.
                try:
                    if _verify_cache_peer_isolation(
                            record['cache_directory'], record['cache_identity'],
                            peer_paths) != identities:
                        raise CacheManageError(
                            'concurrency', 'Registered Cache directory topology changed')
                    if action == 'clear_url':
                        removed = _clear_site_cache_url(
                            site['id'], record['cache_identity'], site['name'],
                            record['cache_generation'], cache_url_path)
                    else:
                        removed = _scan_site_cache_files(
                            site['id'], record['cache_identity'], remove=True)
                    if _verify_cache_peer_isolation(
                            record['cache_directory'], record['cache_identity'],
                            peer_paths) != identities:
                        raise CacheManageError(
                            'concurrency', 'Registered Cache directory topology changed')
                    if _cache_observation(
                            site, record, public, vhost_root=vhost_root,
                            nginx_root=nginx_root, data_dir=data_dir,
                            probe=probe)['state'] != 'Applied':
                        raise CacheManageError('concurrency',
                            'Site Cache route changed during file clear')
                except (OSError, CacheManageError) as exc:
                    raise CacheManageError('uncertain',
                        'Site Cache file removal not fully confirmed; Recheck before any retry',
                        recovery_id=record['op']) from exc
                return {'schema': 1, 'state': 'Applied', 'changed': removed > 0,
                        'site_id': site['id'], 'site_key': site['name'],
                        'recovery_id': record['op'], 'journal_phase': 'applied',
                        'runtime_verified': True, 'purge_supported': False,
                        'cache_files_removed': removed,
                        **({'cache_url_path': cache_url_path} if action == 'clear_url' else {}),
                        'note': ('Only exact current-generation GET/HEAD entries for the '
                                 'selected primary Host and URL were removed. Other Host '
                                 'aliases and queries are not covered. ' if action == 'clear_url' else
                                 'Only verified site-owned Cache files were unlinked. ') +
                                'No Nginx reload, shared WORDPRESS purge or Nginx Helper '
                                'operation. Concurrent traffic may repopulate the Cache; '
                                'recheck application behavior independently.'}

            if action == 'apply':
                from ach_customizer_cache_bridge import (
                    BridgeError, inspect as inspect_bridge,
                )
                try:
                    bridge_state = (inspect_bridge(site, public, record)
                                    if record is not None and
                                    record.get('native_handler') == 'wpfastcgi'
                                    else 'Not Provisioned')
                except (BridgeError, OSError) as exc:
                    raise CacheManageError('recovery',
                        'Review stale WordPress Bridge state before Cache Apply: ' + str(exc)) from exc
                if bridge_state != 'Not Provisioned':
                    raise CacheManageError('recovery',
                        'Disable previous WordPress Bridge mapping before a new Cache generation')
                if record is not None and record['phase'] != 'restored':
                    raise CacheManageError('recovery', 'Existing Cache journal must be reconciled')
                previous = record
                if public is None:
                    raise CacheManageError('compatibility', 'Native site database is required')
                if type(cache_generation) is not str or not TOKEN.fullmatch(cache_generation):
                    raise CacheManageError('input','Fresh Cache approval generation is required')
                readiness = preview_cache_activation(
                    site, public, vhost_root=vhost_root, nginx_root=nginx_root,
                    data_dir=data_dir, cache_generation=cache_generation, probe=probe)
                if (expected_source != readiness['source_sha256'] or
                        expected_proposal != readiness['proposal_sha256']):
                    raise CacheManageError('concurrency', 'Cache approval snapshot is stale')
                php = readiness['php_version']
                sources = _site_sources(
                    site, php, native_handler=readiness['native_handler'],
                    vhost_root=vhost_root, nginx_root=nginx_root)
                reference, global_bytes, ext_bytes = _fragments(
                    site['id'], php, cache_generation,
                    inherited_hsts=sources['inherited_hsts'],
                    native_handler=readiness['native_handler'])
                # The current source may have changed after Preview and
                # before these bytes were generated. Rebind exact consent
                # to the actual candidate, not only the earlier Preview.
                if reference['proposal_sha256'] != expected_proposal:
                    raise CacheManageError(
                        'concurrency', 'Native HSTS/Cache proposal changed after approval')
                _nginx('-t', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                initial = (probe or _probe)(site, marker=None)
                verified_sources = _site_sources(
                    site, php, native_handler=readiness['native_handler'],
                    vhost_root=vhost_root, nginx_root=nginx_root)
                if verified_sources != sources:
                    raise CacheManageError(
                        'concurrency', 'Native Cache source changed during Apply preflight')
                record = {
                    'schema': 2, 'site_id': site['id'], 'site_key': site['name'],
                    'php_version': php, 'op': uuid4().hex, 'phase': 'prepared',
                    **({'native_handler': 'wpfastcgi'}
                       if readiness['native_handler'] == 'wpfastcgi' else {}),
                    'cache_identity': None,
                    'cache_generation': cache_generation,
                    'source_sha': readiness['source_sha256'],
                    'proposal_sha': reference['proposal_sha256'],
                    'vhost_sha': sources['vhost_sha'], 'main_sha': sources['main_sha'],
                    'php_sha': sources['php_sha'],
                    **({'inherited_hsts': sources['inherited_hsts']}
                       if sources['inherited_hsts'] else {}),
                    'global_sha': _hash(global_bytes),
                    'extension_sha': _hash(ext_bytes),
                    'cache_directory': reference['cache_directory'],
                    'probe_status': initial,
                }
                if previous is not None:
                    # All re-Apply preconditions were rechecked under the
                    # single operation lock. Preserve previous recovery bytes
                    # before replacing the active journal with the new ID.
                    _archive_restored_record(statefd, previous)
                _record_save(statefd, record)
                try:
                    if previous is None or previous.get('cache_identity', 'legacy') is None:
                        _create_site_cache(site['id'])
                    identity = _path_owned(site['id'])
                    record['cache_identity'] = list(identity)
                    _record_save(statefd, record)
                    global_name, ext_name, _ = _names(site['id'])
                    gfd, efd, global_before, extension_before = _cache_files(
                        statefd, site, vhost_root=vhost_root)
                    try:
                        if global_before is not None or extension_before is not None:
                            raise CacheManageError('concurrency',
                                'Managed Cache filename appeared before publish')
                        _publish_complete(gfd, global_name, global_bytes, 0o600, record['op'])
                        _publish_complete(efd, ext_name, ext_bytes, 0o600, record['op'])
                    finally:
                        os.close(gfd)
                        os.close(efd)
                    _same_site_sources(site, record,
                                       vhost_root=vhost_root, nginx_root=nginx_root)
                    _same_cache_identity(site['id'], record)
                    observed = inspect_site_fastcgi_cache(
                        public, site['id'], site['name'], vhost_root=vhost_root,
                        nginx_root=nginx_root,
                        rewrite_root=str(Path(vhost_root).parent/'rewrite'))
                    if (observed['state'] != 'Source Observed' or
                            observed['zone_state'] != 'Direct Zone' or
                            observed['cache_zone'] != 'ACHFC_'+str(site['id']) or
                            observed['cache_directory'] != record['cache_directory'] or
                            observed['unresolved_other_sites']):
                        raise CacheManageError('concurrency',
                            'Post-publication Nginx Cache ownership is unverified')
                    _nginx('-t', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                except Exception as exc:
                    # The current operation did not signal Nginx reload.
                    # Never unlink files of unknown ownership to recover.
                    try:
                        gfd, efd, _, _ = _cache_files(statefd, site, vhost_root=vhost_root)
                        try:
                            _safe_retire(efd, _names(site['id'])[1], ext_bytes, record['op'])
                            _safe_retire(gfd, _names(site['id'])[0], global_bytes, record['op'])
                        finally:
                            os.close(gfd)
                            os.close(efd)
                        _nginx('-t', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                    except Exception as cleanup:
                        raise CacheManageError('uncertain',
                            'Cache preflight failed; retained sources need manual Recheck',
                            recovery_id=record['op']) from cleanup
                    raise CacheManageError('recovered',
                        'Cache activation was not signaled; Recheck saved recovery',
                        recovery_id=record['op']) from exc
                try:
                    _nginx('reload', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                    _await_php_route(
                        site, marker=site['id'], expected_status=initial, probe=probe)
                    _same_site_sources(site, record,
                                       vhost_root=vhost_root, nginx_root=nginx_root)
                    _same_cache_identity(site['id'], record)
                except Exception as exc:
                    raise CacheManageError('uncertain',
                        'Cache reload/worker observation unconfirmed; Recheck and Restore',
                        recovery_id=record['op']) from exc
                record['phase'] = 'applied'
                try:
                    _record_save(statefd, record)
                except Exception as exc:
                    raise CacheManageError('uncertain',
                        'Cache activated; final journal commit unconfirmed',
                        recovery_id=record['op']) from exc
                return {'schema': 1, 'state': 'Applied', 'changed': True,
                        'site_id': site['id'], 'site_key': site['name'],
                        'journal_phase': 'applied', 'recovery_id': record['op'],
                        'runtime_verified': True, 'purge_supported': False,
                        'cache_directory': record['cache_directory']}

            if (record is None or record['site_key'] != site['name'] or
                    recovery_id != record['op'] or
                    record['phase'] not in ('prepared', 'applied')):
                raise CacheManageError('recovery',
                    'Unknown, changed or already-restored Cache operation')
            _same_site_sources(site, record,
                               vhost_root=vhost_root, nginx_root=nginx_root)
            _same_native_source_inventory(
                site, record, public, vhost_root=vhost_root,
                nginx_root=nginx_root, data_dir=data_dir)
            if record['schema'] == 2 and record['cache_identity'] is None:
                # The same read-only physical proof used by Recheck permits
                # journal-only recovery; no Cache source or reload is touched.
                _empty_prepublication(site, record, vhost_root=vhost_root)
                (probe or _probe)(site, marker=None)
                record['phase'] = 'restored'
                _record_save(statefd, record)
                return {'schema': 1, 'state': 'Restored', 'changed': False,
                        'site_id': site['id'], 'site_key': site['name'],
                        'recovery_id': record['op'],
                        'journal_phase': 'restored',
                        'runtime_verified': False, 'purge_supported': False,
                        'recovery_scope': 'prepublication',
                        'note': 'Prepared Cache never activated; journal finalized without Nginx reload.'}
            _same_cache_identity(site['id'], record)
            # Revoke the opt-in WordPress URL mapper BEFORE this generation
            # ceases to be active. A failed Restore keeps its recovery journal
            # and source intact; Bridge can be explicitly re-enabled after
            # current Applied Recheck, never silently retained across Restore.
            from ach_customizer_cache_bridge import (
                BridgeError, disable as disable_bridge,
            )
            try:
                disable_bridge(site, public)
            except (BridgeError, OSError) as exc:
                raise CacheManageError('recovery',
                    'Cannot retire the WordPress Bridge manifest; '
                    'disable it before Cache Restore: ' + str(exc),
                    recovery_id=record['op']) from exc
            global_bytes, ext_bytes = _expected_files(record)
            gfd, efd, _, _ = _cache_files(statefd, site, vhost_root=vhost_root)
            try:
                _safe_retire(efd, _names(site['id'])[1], ext_bytes, record['op'])
                _safe_retire(gfd, _names(site['id'])[0], global_bytes, record['op'])
            finally:
                os.close(gfd)
                os.close(efd)
            try:
                _nginx('-t', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                _nginx('reload', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                _await_php_route(
                    site, marker=None, expected_status=record['probe_status'],
                    probe=probe)
                _same_site_sources(site, record,
                                   vhost_root=vhost_root, nginx_root=nginx_root)
            except Exception as exc:
                raise CacheManageError('uncertain',
                    'Cache Restore unconfirmed; retained files and journal preserved',
                    recovery_id=record['op']) from exc
            record['phase'] = 'restored'
            try:
                _record_save(statefd, record)
            except Exception as exc:
                raise CacheManageError('uncertain',
                    'Restore observed but journal finalization unconfirmed',
                    recovery_id=record['op']) from exc
            return {'schema': 1, 'state': 'Restored', 'changed': True,
                    'site_id': site['id'], 'site_key': site['name'],
                    'journal_phase': 'restored', 'recovery_id': record['op'],
                    'runtime_verified': True, 'purge_supported': False,
                    'note': 'Per-site cache bytes are retained. Shared WORDPRESS cache is untouched.'}
        finally:
            os.close(lockfd)
    finally:
        os.close(statefd)
