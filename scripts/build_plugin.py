#!/usr/bin/env python3
"""Deterministic local aaPanel ZIP packager, not a release/publisher."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / 'plugin' / 'ach_customizer'
FILES = ('ach_customizer_main.py', 'ach_customizer_monitor.py', 'ach_customizer_cleanup.py', 'icon.png', 'index.html', 'info.json', 'install.sh')


def build(output):
    metadata = json.loads((PLUGIN / 'info.json').read_text(encoding='utf-8'))
    if metadata['name'] != 'ach_customizer' or not metadata['versions']:
        raise ValueError('Unexpected plugin manifest identity')
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            source = PLUGIN / name
            if source.is_symlink() or not source.is_file():
                raise ValueError('Missing or unsafe package file: ' + name)
            info = ZipInfo('ach_customizer/' + name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((0o100755 if name == 'install.sh' else 0o100644) << 16)
            archive.writestr(info, source.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
    sha = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f'Local unverified artifact: {output}\nSHA256: {sha}\nVersion: {metadata["versions"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'dist' / 'ach-customizer-dev.zip'))
    build(parser.parse_args().output)
