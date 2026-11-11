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

from ach_customizer_cache_policy import generate_reference, CACHE_ROOT
from ach_customizer_cache_audit import inspect_site_fastcgi_cache
from ach_customizer_monitor import (
    _active_nginx_text, _bounded_file_text, _native_extension_fingerprint,
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
    identity = record.get('cache_identity')
    valid_identity = (identity is None and record.get('phase') in ('prepared', 'restored') or
                      isinstance(identity, list) and len(identity) == 2 and
                      all(type(value) is int and value > 0 for value in identity))
    if (schema not in (1, 2) or set(record) != expected
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


def _site_sources(site, php, *, vhost_root=VHOST_ROOT, nginx_root=NGINX_ROOT):
    if (site.get('status') not in ('1',1) or not SITE_KEY.fullmatch(site['name'])
            or not any(binding.get('name') == site['name'] and binding.get('port') == 80
                       for binding in site.get('bound_domains', []))):
        raise CacheManageError('identity', 'A running registered HTTP/80 site with exact site hostname is required')
    vhost, sig = _read_source(vhost_root+'/'+site['name']+'.conf')
    main, _ = _read_source(nginx_root+'/nginx.conf')
    php_include, _ = _read_source(nginx_root+'/enable-php-'+php+'.conf')
    fastcgi, _ = _read_source(nginx_root+'/fastcgi.conf')
    pathinfo, _ = _read_source(nginx_root+'/pathinfo.conf')
    active = _active_nginx_text(vhost.decode())
    php_active = re.sub(r'\s+', ' ', _active_nginx_text(php_include.decode())).strip()
    stock = (r'location ~ [^/]\.php(/|$) { try_files $uri =404; '
             'fastcgi_pass unix:/tmp/php-cgi-'+php+'.sock; '
             'fastcgi_index index.php; include fastcgi.conf; '
             'include pathinfo.conf; }')
    if php_active != stock:
        raise CacheManageError('compatibility',
            'Native PHP handler has unverified routing or FastCGI parameters')
    params = _active_nginx_text(pathinfo.decode())
    if (any(not re.search(r'\bfastcgi_param\s+'+key+r'\s+'+value+r'\s*;', params)
            for key, value in (
                ('SCRIPT_FILENAME', r'\$document_root\$real_script_name'),
                ('SCRIPT_NAME', r'\$real_script_name'),
                ('PATH_INFO', r'\$path_info'))) or
            re.search(r'\b(?:include|add_header|fastcgi_pass)\s', params)):
        raise CacheManageError('compatibility',
            'Native PHP PATH_INFO parameters need manual compatibility review')
    # The managed location defines Cache diagnostics via add_header. On Nginx
    # 1.28 this suppresses inherited http/server-level response headers.
    # Only the bounded stock shape without site-level header overrides is safe.
    if re.search(r'\badd_header\s', active):
        raise CacheManageError('compatibility',
            'Selected VHost response headers cannot be inherited by Cache handler')
    ext = 'include '+vhost_root+'/extension/'+site['name']+'/*.conf;'
    php_line = 'include enable-php-'+php+'.conf;'
    # A native aaPanel PHP switch leaves the saved Cache extension pinned to
    # its original PHP handler. Explain the two independently observed versions
    # without treating the new include as approved or changing recovery gates.
    php_includes = re.findall(r'\binclude\s+enable-php-[^\s;]+\s*;', active)
    if (len(php_includes) == 1 and php in ('81', '85')
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
            'php_sha':_hash(php_include+b'\0'+fastcgi+b'\0'+pathinfo)}


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
    if (native['state'] != 'Source Observed'
            or native['zone_state'] != 'No Direct Directive'
            or native['php_version'] not in ('81','85')
            or native['unresolved_other_sites'] != 0
            or native['purge_directive_seen']):
        raise CacheManageError('compatibility',
            'Existing cache, unsupported native PHP/include, or unresolved peer site requires review')
    from ach_customizer_vhost_drift import inspect_vhost_drift
    drift = inspect_vhost_drift(public,site,vhost_root=vhost_root)
    if drift['state'] != 'File Match' or 80 not in drift['listen_ports']:
        raise CacheManageError('compatibility',
                               'Native VHost does not match the exact site/root/HTTP binding')
    sources=_site_sources(site,native['php_version'],
                          vhost_root=vhost_root,nginx_root=nginx_root)
    reference=generate_reference(site['id'],native['php_version'],
                                 cache_generation=cache_generation)
    return native,reference,sources


def _restored_generation_can_reapply(site, old, reference, *, vhost_root=VHOST_ROOT):
    """Allow another explicit Apply only with an exact, restored prior policy.

    Reuse the existing private site directory with the unchanged generator.
    Never silently adopt a directory or archived fragment from a different
    site or a different policy. Prior journals are archived, not discarded.
    """
    prior_reference = generate_reference(
        site['id'], old['php_version'],
        cache_generation=old['cache_generation'])
    if (old['phase'] != 'restored' or old['site_key'] != site['name'] or
            old['php_version'] != reference['php_version'] or
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
        if old is not None:
            _restored_generation_can_reapply(
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
                'cache_zone':reference['cache_zone'],
                'cache_directory':reference['cache_directory'],
                'impact':'One selected HTTP/80 VHost and Nginx service reload; '
                'requires exact browser approval and after-state recovery',
                'note':'No cache writes, reload, or purge in this read-only preview. '
                'Native WordPress/WooCommerce/Nginx Helper acceptance remains independent.'}
    finally:
        os.close(statefd)


def _fragments(site_id, php_version, cache_generation):
    reference=generate_reference(site_id,php_version,
                                 cache_generation=cache_generation)
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
    ref,_,extension_bytes=_fragments(site_id,record['php_version'],record['cache_generation'])
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
    ref,global_bytes,_=_fragments(site_id,record['php_version'],record['cache_generation'])
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
                           vhost_root=vhost_root, nginx_root=nginx_root)
    drift = [label for key, label in (
        ('vhost_sha', 'VHost/rewrite'), ('main_sha', 'main Nginx'),
        ('php_sha', 'PHP handler/parameters'))
        if source[key] != record[key]]
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
    _, global_bytes, extension_bytes = _fragments(record['site_id'], record['php_version'], record['cache_generation'])
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
                 runner=None, probe=None, cache_generation=None):
    """Serialized guarded per-site cache Apply/Recheck/Restore.

    Neither successful Nginx -t nor reload signaling by itself proves the
    target worker. A lost/ambiguous reload retains the journal and both source
    fragments for explicit reconciliation, never an automatic blind retry.
    """
    if action not in ('apply', 'restore', 'recheck'):
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
            lockfd = _exclusive_lock(statefd, create=(action != 'recheck'))
        except FileNotFoundError:
            if action != 'recheck':
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
            if action == 'apply':
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
                reference, global_bytes, ext_bytes = _fragments(site['id'], php, cache_generation)
                _nginx('-t', nginx=NGINX, conf=nginx_root+'/nginx.conf', runner=runner)
                initial = (probe or _probe)(site, marker=None)
                sources = _site_sources(site, php, vhost_root=vhost_root, nginx_root=nginx_root)
                record = {
                    'schema': 2, 'site_id': site['id'], 'site_key': site['name'],
                    'php_version': php, 'op': uuid4().hex, 'phase': 'prepared',
                    'cache_identity': None,
                    'cache_generation': cache_generation,
                    'source_sha': readiness['source_sha256'],
                    'proposal_sha': reference['proposal_sha256'],
                    'vhost_sha': sources['vhost_sha'], 'main_sha': sources['main_sha'],
                    'php_sha': sources['php_sha'],
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
