#!/usr/bin/env python3
"""Deterministic local aaPanel ZIP packager, not a release/publisher."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / 'plugin' / 'ach_customizer'
CORE_FILES = ('ach_customizer_main.py', 'ach_customizer_activity.py', 'ach_customizer_lifecycle.py', 'ach_customizer_monitor.py', 'ach_customizer_state.py', 'ach_customizer_cleanup.py', 'ach_customizer_fpm_apply.py', 'ach_customizer_fpm_workflow.py', 'ach_customizer_status_pages.py', 'ach_customizer_status_inspect.py', 'ach_customizer_status_probe.py', 'ach_customizer_hosts.py', 'ach_customizer_cache_audit.py', 'icon.png', 'index.html', 'info.json', 'install.sh')
PAGE_VARIANTS = ('403', '404', '429', '500', '502', '503', '504', '50x', 'new-site', 'stopped', 'unbound')
FILES = CORE_FILES + ('status_pages/manifest.json',) + tuple(
    f'status_pages/{locale}/{page}.html'
    for locale in ('en', 'fa') for page in PAGE_VARIANTS
)

# aaPanel extracts ZIP member mtimes onto installed Python source files.
# A constant date can cause Python's size+mtime bytecode cache to execute an
# obsolete same-size module after a native plugin ZIP upgrade. Keep builds
# deterministic, but derive the member timestamp from source content instead.
# The 1980..2027 two-second ZIP DOS-time space is large enough to make
# accidental hash-to-timestamp collisions extremely unlikely; timestamps are
# fingerprints, not build or modification chronology.
_SECONDS_EPOCH_1980 = 315532800
_DOS_TWO_SECOND_SLOTS = 48 * 365 * 24 * 60 * 30


def _content_timestamp(payload):
    digest = hashlib.sha256(payload).digest()
    offset = int.from_bytes(digest[:8], 'big') % _DOS_TWO_SECOND_SLOTS
    dt = datetime.fromtimestamp(_SECONDS_EPOCH_1980 + 2 * offset, tz=timezone.utc)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)



def build(output):
    metadata = json.loads((PLUGIN / 'info.json').read_text(encoding='utf-8'))
    if metadata['name'] != 'ach_customizer' or not metadata['versions']:
        raise ValueError('Unexpected plugin manifest identity')
    # Refuse any accidentally edited/missing bundled source before packaging.
    manifest = json.loads((PLUGIN / 'status_pages' / 'manifest.json').read_text())
    if manifest.get('schema') != 1 or set(manifest.get('assets', {})) != {
            f'{locale}/{page}.html'
            for locale in ('en', 'fa') for page in PAGE_VARIANTS}:
        raise ValueError('Unexpected status page asset inventory')
    for rel, digest in manifest['assets'].items():
        source = PLUGIN / 'status_pages' / rel
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Bundled Status Page hash mismatch: ' + rel)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            source = PLUGIN / name
            if source.is_symlink() or not source.is_file():
                raise ValueError('Missing or unsafe package file: ' + name)
            payload = source.read_bytes()
            info = ZipInfo('ach_customizer/' + name, _content_timestamp(payload))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((0o100755 if name == 'install.sh' else 0o100644) << 16)
            archive.writestr(info, payload, compress_type=ZIP_DEFLATED, compresslevel=9)
    sha = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f'Local unverified artifact: {output}\nSHA256: {sha}\nVersion: {metadata["versions"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'dist' / 'ach-customizer-dev.zip'))
    build(parser.parse_args().output)
