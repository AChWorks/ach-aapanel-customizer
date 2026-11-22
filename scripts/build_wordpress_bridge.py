#!/usr/bin/env python3
"""Deterministic, independent WordPress companion ZIP; no release action."""
from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "wordpress" / "ach-aapanel-bridge"
ENTRY = "ach-aapanel-bridge.php"
SLUG = "ach-aapanel-bridge"
FILES = (
    ENTRY,
    "includes/class-nginx-helper-status.php",
    "includes/class-cache-invalidation.php",
    "includes/class-plugin.php",
    "readme.txt",
    "LICENSE",
)

# ZIP member timestamps depend on source bytes, not wall-clock time.
_EPOCH_1980 = 315532800
_DOS_SLOTS = 48 * 365 * 24 * 60 * 30


def _timestamp(payload: bytes) -> tuple[int, ...]:
    offset = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % _DOS_SLOTS
    stamp = datetime.fromtimestamp(_EPOCH_1980 + 2 * offset, timezone.utc)
    return stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second


def _header(source: str, field: str) -> str:
    match = re.search(r"(?m)^[ \t]*\*[ \t]*" + re.escape(field)
                      + r":[ \t]*([^\r\n]+?)\s*$", source[:2500])
    if not match:
        raise ValueError(f"Missing WordPress plugin header field: {field}")
    return match.group(1).strip()


def build(output: str | Path) -> dict[str, str]:
    # Capture every member before validating and opening the output: the
    # exact bytes checked below must be the bytes placed in the archive.
    payloads = {}
    for name in FILES:
        source = ROOT / name if name == "LICENSE" else PLUGIN / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or unsafe WordPress companion source: {name}")
        payloads[name] = source.read_bytes()
    header = payloads[ENTRY].decode("utf-8")
    if (_header(header, "Plugin Name") != "ACh aaPanel Bridge" or
            _header(header, "License") != "MPL-2.0" or
            _header(header, "License URI") != "https://www.mozilla.org/en-US/MPL/2.0/" or
            _header(header, "Text Domain") != SLUG or
            _header(header, "Update URI") !=
            "https://github.com/AChWorks/ach-aapanel-customizer/tree/main/wordpress/ach-aapanel-bridge"):
        raise ValueError("Unexpected WordPress companion identity")
    version = _header(header, "Version")
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}", version):
        raise ValueError("Unexpected independent WordPress plugin version")

    readme = payloads["readme.txt"].decode("utf-8")
    if not readme.startswith("=== ACh aaPanel Bridge ===\n"):
        raise ValueError("Unexpected WordPress readme.txt plugin identity")
    stable_tags = re.findall(r"(?m)^Stable tag:[ \t]*([^\r\n]+)$", readme)
    if len(stable_tags) != 1 or stable_tags[0].strip() != version:
        raise ValueError("WordPress readme.txt Stable tag does not match PHP plugin Version")
    if (len(re.findall(r"(?m)^License: MPL-2\.0$", readme)) != 1 or
            len(re.findall(r"(?m)^License URI: https://www\.mozilla\.org/en-US/MPL/2\.0/$",
                           readme)) != 1):
        raise ValueError("WordPress readme.txt MPL-2.0 license declaration is missing or inconsistent")
    destination = Path(output).resolve()
    if any(destination == (ROOT / name if name == "LICENSE" else PLUGIN / name).resolve()
           for name in FILES):
        raise ValueError("WordPress ZIP output must not overwrite a package source file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in payloads.items():
            metadata = ZipInfo(f"{SLUG}/{name}", _timestamp(payload))
            metadata.compress_type = ZIP_DEFLATED
            metadata.external_attr = 0o100644 << 16
            archive.writestr(metadata, payload, compress_type=ZIP_DEFLATED, compresslevel=9)
    return {
        "version": version,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "path": str(destination),
        "members": str(len(FILES)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "dist" / "ach-aapanel-bridge.zip"))
    result = build(parser.parse_args().output)
    print("Local unverified WordPress candidate:")
    for key, value in result.items():
        print(f"{key}: {value}")
