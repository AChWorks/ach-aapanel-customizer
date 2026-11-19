"""Real filesystem tests for the constrained native WP failure witness."""
import fcntl
import hashlib
import os
import errno
import subprocess
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

    def legacy_applied(self):
        """A previous release's recovery, not a fresh unattended edit."""
        self.arm()
        operation = self.prepared_record()
        with worker._locked_state(str(self.data)) as fd:
            rec = worker._read_recovery(fd, operation)
            rec["phase"] = "applied"
            worker._save_recovery(fd, rec)
            policy = worker._load(fd)
            policy["active"] = None
            policy["last_recovery"] = operation
            policy["recoveries"] = 1
            policy["last_reason"] = "Historical native WP cleanup applied"
            worker._save(fd, policy)
        self.lock.unlink()
        self.hosts.write_bytes(self.before)
        return operation

    def test_failed_terminal_exact_vendor_append_is_observed_but_never_removed(self):
        self.arm()
        marker = b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(self.before + marker)
        with patch.object(worker.os, "ftruncate", side_effect=AssertionError("UNSAFE AUTO TRUNCATE")):
            result = self.finish()
        self.assertEqual(result["state"], "Manual Review Required")
        self.assertFalse(result["changed"])
        self.assertIn("remove manually", result["reason"])
        self.assertIsNone(result["recovery_id"])
        self.assertEqual(self.hosts.read_bytes(), self.before + marker)
        self.assertEqual(self.tick()["state"], "Already Observed")
        inspection = worker.inspect(data_dir=str(self.data))
        self.assertTrue(inspection["enabled"])
        self.assertFalse(inspection["auto_hosts"])
        self.assertEqual(inspection["last_worker"]["state"], "Manual Review Required")
        self.assertIsNone(inspection["last_recovery"])
        self.assertEqual(inspection["recoveries"], 0)
        from ach_customizer_activity import LOG_NAME
        entries = [json.loads(x) for x in (self.data / LOG_NAME).read_text().splitlines()]
        matches = [x for x in entries if x["action"] == "wp_terminal_manual_review"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["target"], "failed.test")
        for _ in range(3):
            self.assertEqual(self.tick()["state"], "Already Observed")
        self.assertEqual((self.data / LOG_NAME).read_text().count('"wp_terminal_manual_review"'),1)
        self.assertEqual(self.hosts.read_bytes(), self.before + marker)

    def test_uncoordinated_foreign_append_after_witness_read_survives(self):
        self.arm()
        marker = b"\n127.0.0.1 failed.test"
        foreign = b"\n192.0.2.55 foreign-after-check.test"
        self.hosts.write_bytes(self.before + marker)
        original = worker._source_payload
        def concurrent_append(path):
            snap = original(path)
            with open(self.hosts, "ab") as handle:
                handle.write(foreign)
                handle.flush()
                os.fsync(handle.fileno())
            return snap
        with (patch.object(worker, "_source_payload", side_effect=concurrent_append),
              patch.object(worker.os, "ftruncate", side_effect=AssertionError("UNSAFE AUTO TRUNCATE"))):
            result = self.finish()
        self.assertEqual(result["state"], "Manual Review Required")
        self.assertFalse(result["changed"])
        self.assertEqual(self.hosts.read_bytes(), self.before + marker + foreign)
        self.assertIsNone(worker.inspect(data_dir=str(self.data))["last_recovery"])
        self.assertEqual(self.tick()["state"], "Already Observed")

    def test_observed_manual_review_is_not_a_systemd_worker_failure(self):
        import contextlib
        import io
        output=io.StringIO()
        with patch.object(worker, "process_event", return_value={
                "state": "Manual Review Required", "changed": False}), \
                contextlib.redirect_stdout(output):
            self.assertEqual(worker.main(["run"]), 0)
        self.assertIn("Manual Review Required",output.getvalue())

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
        self.assertEqual(self.tick()["state"],"Needs Review")
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
        operation=self.legacy_applied()
        self.lock.write_text("new native WP operation")
        with self.assertRaisesRegex(worker.TerminalError,"still be active"):
            worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(self.hosts.read_bytes(),self.before)

    def test_prepared_recovery_cannot_be_abandoned_without_recheck(self):
        self.arm()
        worker.set_enabled(False,data_dir=str(self.data))
        self.prepared_record()
        self.lock.unlink()
        with self.assertRaisesRegex(worker.TerminalError,"Prepared"):
            worker.abandon_witness(data_dir=str(self.data))
        self.assertIsNotNone(worker.inspect(data_dir=str(self.data))["last_recovery"])

    def test_crash_after_applied_journal_before_policy_save_rechecks_idempotently(self):
        self.arm()
        op=self.prepared_record()
        with worker._locked_state(str(self.data)) as fd:
            record=worker._read_recovery(fd,op)
            record["phase"]="applied"
            worker._save_recovery(fd,record)
        self.lock.unlink()
        self.progress_write(status=1,stages=(1,1,1,-1))
        self.assertEqual(self.tick()["state"],"Recovery Required")
        first=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(first["state"],"applied")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["recoveries"],1)
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery"],op)
        second=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(second["state"],"applied")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["recoveries"],1)
        restored=worker.restore(op,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(restored["state"],"Restored")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_crash_after_restore_write_before_journal_persist_rechecks_idempotently(self):
        operation=self.legacy_applied()
        with worker._locked_state(str(self.data)) as fd:
            record=worker._read_recovery(fd,operation)
            record["phase"]="restore_prepared"
            worker._save_recovery(fd,record)
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        outcome=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(outcome["state"],"restored")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery_state"],"restored")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["last_recovery"],operation)
        self.assertEqual(worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))["state"],"restored")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["recoveries"],1)
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")
        with self.assertRaises(worker.TerminalError):
            worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))

    def test_unattended_worker_never_attempts_any_kernel_write_lease_or_mutation(self):
        self.arm()
        marker=b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(self.before+marker)
        held=os.open(self.hosts,os.O_RDWR)
        actual_fcntl=fcntl.fcntl
        def probe(fd, command, arg=0):
            if command == fcntl.F_SETLEASE:
                raise AssertionError("Unattended writer attempted an unsafe lease")
            return actual_fcntl(fd,command,arg)
        try:
            with patch.object(worker.fcntl,"fcntl",side_effect=probe):
                result=self.finish()
        finally:
            os.close(held)
        self.assertEqual(result["state"],"Manual Review Required")
        self.assertFalse(result["changed"])
        self.assertEqual(self.hosts.read_bytes(),self.before+marker)

    def test_unsupported_kernel_lease_fails_closed_for_reviewed_legacy_restore(self):
        operation=self.legacy_applied()
        original=fcntl.fcntl
        def unsupported(fd,command,arg=0):
            if command==fcntl.F_SETLEASE and arg==fcntl.F_WRLCK:
                raise OSError(errno.EINVAL,"unsupported")
            return original(fd,command,arg)
        with patch.object(worker.fcntl,'fcntl',side_effect=unsupported):
            with self.assertRaisesRegex(worker.TerminalError,"lease unavailable"):
                worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(self.hosts.read_bytes(),self.before)
        with worker._locked_state(str(self.data)) as fd:
            self.assertEqual(worker._read_recovery(fd,operation)["phase"],"applied")

    def test_final_window_rename_preserves_foreign_path_in_reviewed_restore(self):
        operation=self.legacy_applied()
        outsider=self.orig/"external"
        foreign=self.before+b"192.0.2.55 added-by-other-writer.test\n"
        outsider.write_bytes(foreign);outsider.chmod(0o644)
        actual=os.write
        actions=[]
        def race(fd,data):
            if data==b"\n127.0.0.1 failed.test":
                os.replace(outsider,self.hosts)
                actions.append("renamed")
            return actual(fd,data)
        with patch.object(worker.os,"write",side_effect=race):
            with self.assertRaisesRegex(worker.TerminalError,"changed during guarded legacy Restore"):
                worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(actions,["renamed"])
        self.assertEqual(self.hosts.read_bytes(),foreign)
        self.assertEqual(worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))["state"],"Needs Review")
        with worker._locked_state(str(self.data)) as fd:
            self.assertEqual(worker._read_recovery(fd,operation)["phase"],"restore_prepared")

    def test_forced_lease_expiration_interleaving_preserves_foreign_append(self):
        """Simulate kernel-forced lease removal *after* the last guard."""
        operation=self.legacy_applied()
        foreign=b"\n192.0.2.55 foreign-after-lease.test\n"
        actual=os.write
        attempted=[]
        def expired_lease(fd,data):
            if data==b"\n127.0.0.1 failed.test":
                # This is the same late interleaving as a forced kernel break;
                # the independent writer can now acquire a new write FD.
                fcntl.fcntl(fd,fcntl.F_SETLEASE,fcntl.F_UNLCK)
                code=("import os,sys; f=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND);"
                      "os.write(f,bytes.fromhex(sys.argv[2]));os.close(f)")
                result=subprocess.run([sys.executable,'-c',code,str(self.hosts),foreign.hex()],
                                      capture_output=True,text=True,timeout=3)
                attempted.append(result.returncode)
                self.assertEqual(result.returncode,0,result.stderr)
            return actual(fd,data)
        with patch.object(worker.os,"write",side_effect=expired_lease):
            with self.assertRaisesRegex(worker.TerminalError,"source diverged"):
                worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(attempted,[0])
        self.assertEqual(self.hosts.read_bytes(),self.before+foreign+b"\n127.0.0.1 failed.test")
        self.assertEqual(worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))["state"],"Needs Review")
        with worker._locked_state(str(self.data)) as fd:
            self.assertEqual(worker._read_recovery(fd,operation)["phase"],"restore_prepared")

    def test_vendor_source_refusal_is_persisted_and_activity_deduplicated(self):
        self.arm()
        self.native.write_bytes(b"new vendor writer")
        first=self.tick()
        self.assertEqual(first["state"],"Needs Review")
        status=worker.inspect(data_dir=str(self.data))
        self.assertTrue(status["enabled"])
        self.assertEqual(status["last_worker"]["state"],"Needs Review")
        self.assertEqual(status["last_worker"]["stage"],"native_source")
        self.assertIn("fingerprint",status["last_worker"]["reason"])
        self.assertIn("fingerprint",status["last_reason"])
        from ach_customizer_activity import LOG_NAME
        log=self.data/LOG_NAME
        records=[json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual(len([x for x in records if x["action"]=="wp_terminal_refused"]),1)
        for _ in range(4):
            self.assertEqual(self.tick()["state"],"Needs Review")
        self.assertEqual(log.read_text().count('"wp_terminal_refused"'),1)
        self.assertEqual(self.hosts.read_bytes(),self.before)

    def test_untrusted_progress_never_leaks_secrets_to_policy_or_activity(self):
        self.arm()
        self.progress.write_text('{"status":"secret-token-abc","admin_password":"secret-token-abc"}')
        self.progress.chmod(0o644)
        response=self.tick()
        self.assertEqual(response["state"],"Needs Review")
        status=worker.inspect(data_dir=str(self.data))
        self.assertEqual(status["last_worker"]["stage"],"native_progress")
        self.assertNotIn("secret-token-abc",json.dumps(status))
        for file in self.data.iterdir():
            if file.suffix in (".json", ".jsonl"):
                self.assertNotIn("secret-token-abc",file.read_text())

    def test_unattended_worker_never_blocks_foreign_writer_or_truncates(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        foreign=b"\n192.0.2.55 external.test"
        original=worker._source_payload
        def observe_and_append(path):
            sample=original(path)
            code=("import os,sys; f=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND);"
                  "os.write(f,bytes.fromhex(sys.argv[2]));os.close(f)")
            result=subprocess.run([sys.executable,'-c',code,str(self.hosts),foreign.hex()],
                                  capture_output=True,text=True,timeout=3)
            self.assertEqual(result.returncode,0,result.stderr)
            return sample
        with (patch.object(worker,"_source_payload",side_effect=observe_and_append),
              patch.object(worker.os,"ftruncate",side_effect=AssertionError("UNSAFE TRUNCATE"))):
            result=self.finish()
        self.assertEqual(result["state"],"Manual Review Required")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test"+foreign)

    def test_applied_journal_external_exact_marker_reappend_is_not_restore(self):
        operation=self.legacy_applied()
        # Verify the ordinary already-applied state before external activity.
        self.assertEqual(worker.recheck_recovery(
            data_dir=str(self.data),hosts_path=str(self.hosts))["state"],"applied")
        original_policy=worker.inspect(data_dir=str(self.data))
        self.assertEqual(original_policy["last_recovery_state"],"applied")
        # A separate writer recreates precisely the former vendor marker.
        externally_reappended=self.before+b"\n127.0.0.1 failed.test"
        with open(self.hosts,"ab") as writer:
            writer.write(externally_reappended[len(self.before):])
        first=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(first["state"],"Needs Review")
        self.assertIn("without a prepared Restore",first["reason"])
        second=worker.recheck_recovery(data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(second["state"],"Needs Review")
        self.assertEqual(self.hosts.read_bytes(),externally_reappended)
        state=worker.inspect(data_dir=str(self.data))
        self.assertEqual(state["last_recovery"],operation)
        self.assertEqual(state["last_recovery_state"],"applied")
        self.assertEqual(state["recoveries"],original_policy["recoveries"])
        with worker._locked_state(str(self.data)) as fd:
            self.assertEqual(worker._read_recovery(fd,operation)["phase"],"applied")

    def test_stale_foreign_change_rejects_restore(self):
        operation=self.legacy_applied()
        self.hosts.write_bytes(self.before+b"# administrator edit\n")
        with self.assertRaisesRegex(worker.TerminalError,"changed since"):
            worker.restore(operation,data_dir=str(self.data),hosts_path=str(self.hosts))
        self.assertEqual(self.hosts.read_bytes(),self.before+b"# administrator edit\n")


if __name__ == '__main__':
    unittest.main()
