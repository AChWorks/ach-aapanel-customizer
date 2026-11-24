"""Root-owned WordPress Bridge manifest lifecycle, in a nonprivileged fixture."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"))
from ach_customizer_cache_bridge import (
    MANIFEST_DIR, MANIFEST_NAME, MANIFEST_PREFIX, BridgeError,
    enable, disable, inspect,
)


class FakeSql:
    def __init__(self, site, peers=None):
        self.site = site
        self.peers = peers or []
    def M(self, name):
        assert name == "sites"
        return self
    def where(self, clause, args):
        assert clause == "path=?"
        self.root = args[0]
        return self
    def field(self, fields):
        assert fields == "id,name,path"
        return self
    def select(self):
        return [
            {k: entry[k] for k in ("id", "name", "path")}
            for entry in [self.site] + self.peers if entry["path"] == self.root
        ]


class CacheBridgeManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-native-bridge-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "www" / "acdomains" / "qa-wp.example"
        plugin = self.root / "wp-content/plugins/ach-aapanel-bridge"
        plugin.mkdir(parents=True)
        (self.root / "wp-config.php").write_text("<?php // test only")
        (plugin / "ach-aapanel-bridge.php").write_text("<?php // test only")
        self.site = {"id": 9, "name": "qa-wp.example", "path": str(self.root)}
        self.public = FakeSql(self.site)
        self.owner = os.geteuid()
        self.record = {
            "phase": "applied",
            "cache_directory": "/www/server/ach-customizer-fastcgi/site-9",
            "cache_generation": "a" * 32,
            "cache_identity": [12345, 67890],
            "op": "b" * 32,
        }

    def test_endpoint_inspect_without_native_lock_uses_real_manifest_contract(self):
        from ach_customizer_cache_manage import manage_cache
        state = Path(self.tmp.name) / "state"
        state.mkdir()
        actual_inspect = lambda site, public, record: inspect(
            site, public, record, owner_uid=self.owner)
        with patch("ach_customizer_cache_bridge.inspect",
                   side_effect=actual_inspect) as reader:
            def check(expected):
                result = manage_cache("bridge_inspect", self.site, self.public,
                                      data_dir=str(state))
                self.assertEqual(result["state"], expected)
                self.assertEqual(result["site_key"], self.site["name"])
                self.assertEqual(result["site_id"], self.site["id"])
                self.assertIsNone(result["recovery_id"])
                self.assertTrue(result["read_only"])
                self.assertFalse(result["runtime_verified"])
                self.assertFalse(result["purge_supported"])
                self.assertEqual(list(state.iterdir()), [])
            check("Not Provisioned")
            enable(self.site, self.public, self.record, owner_uid=self.owner)
            manifest = self.root / "wp-content" / MANIFEST_DIR / MANIFEST_NAME
            original = manifest.read_bytes()
            check("Stale — Disable Required")
            self.assertEqual(manifest.read_bytes(), original)
            data = json.loads(original[len(MANIFEST_PREFIX):])
            data["site_key"] = "foreign.example"
            manifest.write_bytes(MANIFEST_PREFIX + json.dumps(data).encode() + b"\n")
            check("Needs Review")
            manifest.write_bytes(original)
            manifest.chmod(0o666)
            check("Needs Review: WordPress Bridge manifest is not native-owned")
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(reader.call_count, 4)

    def test_endpoint_reinspects_if_first_writer_creates_lock_during_read(self):
        from ach_customizer_cache_manage import manage_cache
        from ach_customizer_state import LOCK_FILE
        state = Path(self.tmp.name) / "state"
        state.mkdir()
        lock = state / LOCK_FILE
        def appearing(site, public, record):
            if not lock.exists():
                lock.touch(mode=0o600)
                return "Not Provisioned"
            return "Stale — Disable Required"
        with patch("ach_customizer_cache_bridge.inspect", side_effect=appearing) as reader:
            result = manage_cache("bridge_inspect", self.site, self.public,
                                  data_dir=str(state))
        self.assertEqual(result["state"], "Stale — Disable Required")
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(list(state.iterdir()), [lock])
        self.assertEqual(lock.stat().st_size, 0)

    def test_enable_inspect_and_disable_exact_site(self):
        self.assertEqual(inspect(self.site, self.public, self.record,
                                 owner_uid=self.owner), "Not Provisioned")
        self.assertTrue(enable(self.site, self.public, self.record,
                               owner_uid=self.owner))
        self.assertFalse(enable(self.site, self.public, self.record,
                                owner_uid=self.owner))
        path = self.root / "wp-content" / MANIFEST_DIR / MANIFEST_NAME
        self.assertTrue(path.read_bytes().startswith(MANIFEST_PREFIX))
        data = json.loads(path.read_bytes()[len(MANIFEST_PREFIX):])
        self.assertEqual(data["site_id"], 9)
        self.assertEqual(data["cache_generation"], "a" * 32)
        self.assertEqual(inspect(self.site, self.public, self.record,
                                 owner_uid=self.owner), "Provisioned")
        self.assertTrue(disable(self.site, self.public, owner_uid=self.owner))
        self.assertFalse(path.exists())
        self.assertFalse(disable(self.site, self.public, owner_uid=self.owner))

    def test_native_manifest_round_trips_into_php_without_executing_metadata(self):
        if not shutil.which("php"):
            self.skipTest("PHP CLI missing")
        self.assertTrue(enable(self.site, self.public, self.record, owner_uid=self.owner))
        manifest = self.root / "wp-content" / MANIFEST_DIR / MANIFEST_NAME
        php_class = Path(__file__).resolve().parents[1] / (
            "wordpress/ach-aapanel-bridge/includes/class-cache-invalidation.php")
        php = r"""
        define('ABSPATH', $argv[1] . '/');
        define('WP_CONTENT_DIR', $argv[1] . '/wp-content');
        require $argv[2];
        $data = \AChWorks\AaPanelBridge\CacheInvalidation::manifest((int)$argv[3]);
        echo json_encode($data, JSON_THROW_ON_ERROR);
        """
        result = subprocess.run(["php", "-n", "-r", php,
                                 str(self.root), str(php_class), str(self.owner)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["site_id"], 9)
        self.assertEqual(parsed["site_key"], self.site["name"])
        self.assertEqual(parsed["cache_generation"], self.record["cache_generation"])
        inclusion = subprocess.run([
            "php", "-n", "-r",
            "define('ABSPATH', '/fixture/'); require $argv[1]; echo 'SAFE';",
            str(manifest)],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(inclusion.returncode, 0, inclusion.stderr)
        self.assertEqual(inclusion.stdout, "SAFE",
                         "Manifest must never emit JSON content if included as PHP")

    def test_generation_rotation_requires_explicit_disable(self):
        enable(self.site, self.public, self.record, owner_uid=self.owner)
        fresh = {**self.record, "cache_generation": "c" * 32}
        with self.assertRaisesRegex(BridgeError, "explicit Disable"):
            enable(self.site, self.public, fresh, owner_uid=self.owner)
        self.assertEqual(inspect(self.site, self.public, fresh,
                                 owner_uid=self.owner), "Needs Review")
        self.assertTrue(disable(self.site, self.public, owner_uid=self.owner))
        self.assertTrue(enable(self.site, self.public, fresh, owner_uid=self.owner))

    def test_untrusted_file_or_directory_mode_rejected(self):
        enable(self.site, self.public, self.record, owner_uid=self.owner)
        path = self.root / "wp-content" / MANIFEST_DIR / MANIFEST_NAME
        path.chmod(0o666)
        with self.assertRaisesRegex(BridgeError, "not native-owned"):
            disable(self.site, self.public, owner_uid=self.owner)
        self.assertTrue(path.exists())
        path.chmod(0o644)
        self.assertTrue(disable(self.site, self.public, owner_uid=self.owner))

    def test_shared_root_rejected_before_write(self):
        other = {"id": 10, "name": "other.example", "path": str(self.root)}
        with self.assertRaisesRegex(BridgeError, "shared"):
            enable(self.site, FakeSql(self.site, [other]), self.record, owner_uid=self.owner)
        self.assertFalse((self.root / "wp-content" / MANIFEST_DIR).exists())

    def test_no_foreign_manifest_deletion(self):
        enable(self.site, self.public, self.record, owner_uid=self.owner)
        path = self.root / "wp-content" / MANIFEST_DIR / MANIFEST_NAME
        data = json.loads(path.read_bytes()[len(MANIFEST_PREFIX):])
        data["site_key"] = "other.example"
        path.write_bytes(MANIFEST_PREFIX +
                         json.dumps(data, sort_keys=True, separators=(",", ":")).encode() +
                         b"\n")
        with self.assertRaisesRegex(BridgeError, "another site"):
            disable(self.site, self.public, owner_uid=self.owner)
        self.assertTrue(path.exists())

    def test_stale_restored_record_is_not_considered_provisioned(self):
        enable(self.site, self.public, self.record, owner_uid=self.owner)
        self.assertEqual(inspect(self.site, self.public,
            {**self.record, "phase": "restored"}, owner_uid=self.owner),
            "Stale — Disable Required")


if __name__ == "__main__":
    unittest.main()
