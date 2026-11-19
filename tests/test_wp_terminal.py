"""Real filesystem tests for the constrained native WP failure witness."""
import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"plugin"/"ach_customizer"))
import ach_customizer_wp_terminal as worker


class TestNativeWpWitness(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ach-wp-native-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)
        self.orig = self.root / "orig"
        self.orig.mkdir(mode=0o700)
        self.hosts = self.orig / "hosts"
        self.before = b"127.0.0.1 localhost\n192.0.2.5 intentional.test\n"
        self.hosts.write_bytes(self.before)
        self.hosts.chmod(0o644)
        self.progress = self.root / "wp_aapanel_deploy.log"
        self.lock = self.root / "wp_aapanel_deploy.lock"
        self.batch = self.root / "wp_batch_aapanel_deploy.lock"
        self.native = self.root / "one_key_wp_v2.py"
        self.native.write_bytes(b"verified fixture native writer")
        self.native.chmod(0o644)
        self.site_handler = self.root / "panel_site_v2.py"
        self.site_handler.write_bytes(b"verified fixture progress lifecycle")
        self.site_handler.chmod(0o644)
        self.metadata = self.root / "common.py"
        self.metadata.write_bytes(b"g.version = '8.0.7'\n")
        self.metadata.chmod(0o644)
        sha = hashlib.sha256(self.native.read_bytes()).hexdigest()
        self.settings = patch.multiple(worker, NATIVE_SOURCE_SHA=sha,
                                       NATIVE_SITE_SOURCE=str(self.site_handler),
                                       NATIVE_SITE_SHA=hashlib.sha256(self.site_handler.read_bytes()).hexdigest(),
                                       NATIVE_META=str(self.metadata),
                                       LOCK=str(self.lock), BATCH_LOCK=str(self.batch))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        worker.set_enabled(True, data_dir=str(self.data))

    def progress_write(self, status=0, stages=(1,1,1,0), domain="failed.test"):
        data = dict(status=status, site_name=domain)
        for key, state in zip(("parameter_verification", "create_website",
                               "optional_configurations", "initialize_wp_website"),stages):
            data[key] = {"status":state, "error":"sensitive error not disclosed"}
        previous_ns = self.progress.stat().st_mtime_ns if self.progress.exists() else 0
        self.progress.write_text(json.dumps(data), encoding="utf-8")
        self.progress.chmod(0o644)
        if previous_ns and self.progress.stat().st_mtime_ns <= previous_ns:
            import os
            os.utime(self.progress, ns=(previous_ns+100_000_000,previous_ns+100_000_000))

    def tick(self):
        return worker.process_event(data_dir=str(self.data), hosts_path=str(self.hosts),
                                    progress_path=str(self.progress),native_source=str(self.native))

    def arm(self, domain="failed.test"):
        self.lock.write_text("123")
        self.progress_write(domain=domain)
        result=self.tick()
        self.initial_progress_ns=self.progress.stat().st_mtime_ns
        self.assertEqual(result["state"],"Witness Armed")
        return result

    def finish(self, stages=(1,1,1,-1), domain="failed.test"):
        self.lock.unlink(missing_ok=True)
        self.progress_write(status=1,stages=stages,domain=domain)
        # The native install has elapsed time between start and completion.
        completed_ns=max(self.progress.stat().st_mtime_ns, self.initial_progress_ns+100_000_000)
        import os
        os.utime(self.progress,ns=(completed_ns,completed_ns))
        return self.tick()

    def test_failed_terminal_exact_vendor_append_is_removed_once_and_restorable(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        result=self.finish()
        self.assertEqual(result["state"],"Alias Removed")
        self.assertTrue(result["changed"])
        self.assertEqual(self.hosts.read_bytes(),self.before)
        self.assertRegex(result["recovery_id"],r"^[0-9a-f]{32}$")
        self.assertEqual(self.tick()["state"],"No Witness")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["recoveries"],1)
        restored=worker.restore(result["recovery_id"],data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(restored["state"],"Restored")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")
        with self.assertRaises(worker.TerminalError):
            worker.restore(result["recovery_id"],data_dir=str(self.data),hosts_path=str(self.hosts))

    def test_successful_terminal_avoids_unnecessary_change(self):
        self.arm()
        result=self.finish(stages=(1,1,1,1))
        self.assertEqual(result["state"],"Success")
        self.assertFalse(result["changed"])
        self.assertEqual(self.hosts.read_bytes(),self.before)

    def test_without_preterminal_witness_never_edits_even_if_failure(self):
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        self.progress_write(status=1,stages=(1,1,1,-1))
        self.assertEqual(self.tick()["state"],"No Witness")
        self.assertIn(b"127.0.0.1 failed.test",self.hosts.read_bytes())

    def test_preexisting_intentional_hosts_alias_is_not_auto_removed(self):
        self.hosts.write_bytes(self.before+b"127.0.0.1 failed.test\n")
        self.lock.write_text("123")
        self.progress_write()
        self.assertEqual(self.tick()["state"],"Intentional Alias Possible")
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1))
        self.assertEqual(self.tick()["state"],"No Witness")

    def test_other_hosts_change_blocks_auto_and_restoration(self):
        self.arm()
        external=b"192.0.2.8 externally-changed.test\n"
        self.hosts.write_bytes(self.before+external+b"\n127.0.0.1 failed.test")
        result=self.finish()
        self.assertEqual(result["state"],"Needs Review")
        self.assertEqual(self.hosts.read_bytes(),self.before+external+b"\n127.0.0.1 failed.test")
        self.assertIsNone(worker.inspect(data_dir=str(self.data))["last_recovery"])

    def test_active_lock_prevents_completion_and_disable_is_immediate(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        self.progress_write(status=1, stages=(1,1,1,-1))
        self.assertEqual(self.tick()["state"],"Active or Unknown")
        worker.set_enabled(False,data_dir=str(self.data))
        self.lock.unlink()
        self.assertEqual(self.tick()["state"],"Disabled")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_batch_lifecycle_and_source_fingerprint_block(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1))
        self.batch.write_text("batch")
        self.assertEqual(self.tick()["state"],"Active or Unknown")
        self.batch.unlink()
        self.native.write_bytes(b"upgraded vendor source")
        self.assertEqual(self.tick()["state"],"Needs Review")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_progress_identity_domain_mismatch_blocks_and_untrusted_symlink_rejected(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1),domain="another.test")
        self.assertEqual(self.tick()["state"],"Active or Unknown")
        self.progress.unlink()
        self.progress.symlink_to(self.native)
        self.assertEqual(self.tick()["state"],"Needs Review")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def prepared_record(self):
        """Model a worker crash after durable pre-write journal creation."""
        with worker._locked_state(str(self.data)) as fd:
            policy=worker._load(fd)
            active=policy["active"]
            record={"schema":1,"operation":active["operation"],"domain":active["domain"],
                    "phase":"prepared", "before_sha":hashlib.sha256(
                        self.before+b"\n127.0.0.1 failed.test").hexdigest(),
                    "after_sha":hashlib.sha256(self.before).hexdigest(),
                    "backup":worker._baseline_name(active["operation"])}
            worker._save_recovery(fd,record)
            return active["operation"]

    def test_prepared_journal_blocks_automatic_retry_and_recheck_marks_not_applied(self):
        self.arm()
        operation=self.prepared_record()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1))
        self.assertEqual(self.tick()["state"],"Recovery Required")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")
        checked=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts),
                                       progress_path=str(self.progress))
        self.assertEqual(checked["state"],"not_applied")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery"],None)
        with self.assertRaises(worker.TerminalError):
            worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))

    def test_prepared_journal_can_be_reconciled_as_applied_then_restored(self):
        self.arm()
        operation=self.prepared_record()
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1))
        checked=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts),
                                       progress_path=str(self.progress))
        self.assertEqual(checked["state"],"applied")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery"],operation)
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery_state"],"applied")
        worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_emergency_disable_retains_active_witness_until_terminal_recheck(self):
        self.arm()
        worker.set_enabled(False,data_dir=str(self.data))
        with self.assertRaisesRegex(worker.TerminalError,"Unresolved native WP witness"):
            worker.set_enabled(True,data_dir=str(self.data))
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,1))
        result=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts),
                                       progress_path=str(self.progress))
        self.assertEqual(result["state"],"No Repair Pending")
        self.assertTrue(worker.set_enabled(True,data_dir=str(self.data))["enabled"])

    def test_uncertain_recovery_with_foreign_hosts_diff_refuses_recheck(self):
        self.arm()
        operation=self.prepared_record()
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1))
        edited=self.before+b"\n127.0.0.1 failed.test\n192.0.2.8 changed.test"
        self.hosts.write_bytes(edited)
        result=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts),
                                       progress_path=str(self.progress))
        self.assertEqual(result["state"],"Needs Review")
        self.assertEqual(self.hosts.read_bytes(),edited)
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery"],operation)

    def test_stale_witness_abandonment_requires_disable_and_no_locks_or_journal(self):
        self.arm()
        with self.assertRaisesRegex(worker.TerminalError,"Disable"):
            worker.abandon_witness(data_dir=str(self.data))
        worker.set_enabled(False,data_dir=str(self.data))
        with self.assertRaisesRegex(worker.TerminalError,"may still be active"):
            worker.abandon_witness(data_dir=str(self.data))
        self.lock.unlink()
        result=worker.abandon_witness(data_dir=str(self.data))
        self.assertEqual(result["state"],"Witness Abandoned")
        self.assertIsNone(worker.inspect(data_dir=str(self.data))["active_domain"])
        self.assertEqual(self.hosts.read_bytes(),self.before)
        self.assertTrue(worker.set_enabled(True,data_dir=str(self.data))["enabled"])

    def test_stale_progress_does_not_arm_a_new_witness(self):
        self.lock.write_text("123")
        self.progress_write()
        past=self.progress.stat().st_mtime_ns
        result=worker.process_event(data_dir=str(self.data),hosts_path=str(self.hosts),
            progress_path=str(self.progress),native_source=str(self.native),
            now_ns=past+worker.MAX_AGE_NS+1)
        self.assertEqual(result["state"],"Active or Unknown")
        self.assertIsNone(worker.inspect(data_dir=str(self.data))["active_domain"])

    def test_restore_rejects_new_native_wp_operation_even_after_previous_successful_cleanup(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        result=self.finish()
        self.lock.write_text("new native WP operation")
        with self.assertRaisesRegex(worker.TerminalError,"still be active"):
            worker.restore(result["recovery_id"],data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(self.hosts.read_bytes(),self.before)

    def test_prepared_recovery_cannot_be_abandoned_without_recheck(self):
        self.arm()
        worker.set_enabled(False,data_dir=str(self.data))
        self.prepared_record()
        self.lock.unlink()
        with self.assertRaisesRegex(worker.TerminalError,"Prepared"):
            worker.abandon_witness(data_dir=str(self.data))
        self.assertIsNotNone(worker.inspect(data_dir=str(self.data))["last_recovery"])

    def test_stale_foreign_change_rejects_restore(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        result=self.finish()
        self.hosts.write_bytes(self.before+b"# administrator edit\n")
        with self.assertRaisesRegex(worker.TerminalError,"changed since"):
            worker.restore(result["recovery_id"],data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(self.hosts.read_bytes(),self.before+b"# administrator edit\n")


if __name__ == '__main__':
    unittest.main()
