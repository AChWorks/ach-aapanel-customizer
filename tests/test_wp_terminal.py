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


class TestNativeWpSourceAttestation(unittest.TestCase):
    def test_verified_eight_zero_seven_source_pairs_only(self):
        expected = {
            ("7578c279424f0b653c0f65ca2f22fbf0b86ce873673b05939e4b4b16c6713bf8",
             "b75a5a0b45c319df7eb49381363d3c3e90208157ebfd88de6f9b173d013d98fb"),
            ("baac86fed3328182e1c99c823e2bcc274c0e902f0db16a8fe2fc16fceb4874ce",
             "9696e3114a79587b78344bb2a661eac2555eb1227cf8da4c1ae8fa5b16283e92"),
        }
        self.assertEqual(worker.NATIVE_WRITER_SHA_PAIRS, expected)

        def verify(writer_sha, site_sha, version=b"8.0.7"):
            sources = {
                worker.NATIVE_SOURCE: b"writer",
                worker.NATIVE_SITE_SOURCE: b"site",
                worker.NATIVE_META: b"g.version = '" + version + b"'",
            }
            def read(path, **_kwargs):
                return sources[path], None
            def digest(content):
                return {b"writer": writer_sha, b"site": site_sha}[content]
            with patch.object(worker, "_trusted_file", side_effect=read), patch.object(
                    worker, "_sha", side_effect=digest):
                worker._native_supported()

        for writer_sha, site_sha in expected:
            with self.subTest(cohort=writer_sha[:12]):
                verify(writer_sha, site_sha)
                with self.assertRaisesRegex(worker.TerminalError, "Unverified native"):
                    verify(writer_sha, site_sha, version=b"8.0.8")
        old, updated = sorted(expected)
        for writer_sha, site_sha in ((old[0], updated[1]), (updated[0], old[1])):
            with self.subTest(mixed=(writer_sha[:12], site_sha[:12])):
                with self.assertRaisesRegex(worker.TerminalError, "Unverified native"):
                    verify(writer_sha, site_sha)
        with self.assertRaisesRegex(worker.TerminalError, "Unverified native"):
            verify("0" * 64, updated[1])


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
        self.settings = patch.multiple(
            worker,
            NATIVE_WRITER_SHA_PAIRS=frozenset({(
                sha, hashlib.sha256(self.site_handler.read_bytes()).hexdigest())}),
            NATIVE_SITE_SOURCE=str(self.site_handler),
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

    def test_recovery_counter_is_not_limited_to_64_events(self):
        from ach_customizer_wp_terminal import _default, _validate
        record = _default()
        record["recoveries"] = 135
        self.assertEqual(_validate(record)["recoveries"], 135)

    def test_exact_long_domain_survives_private_outbox_activity_and_crash(self):
        from ach_customizer_activity import read_activity
        import ach_customizer_main as api
        domain=".".join(("a"*50,"b"*50,"c"*50,"d"*7))
        self.assertEqual(len(domain),160)
        self.arm(domain=domain)
        marker=b"\n127.0.0.1 "+domain.encode("ascii")
        self.hosts.write_bytes(self.before+marker)
        real=worker._worker_outcome
        def interruption(fd,policy,state,stage,reason,**kwargs):
            if state=="Manual Review Required":
                raise SystemExit("injected crash after complete Outbox publication")
            return real(fd,policy,state,stage,reason,**kwargs)
        with patch.object(worker,"_worker_outcome",side_effect=interruption):
            with self.assertRaisesRegex(SystemExit,"injected crash"):
                self.finish(domain=domain)
        first=worker.inspect(data_dir=str(self.data))
        op=first["manual_review"]["operation_id"]
        self.assertEqual(first["active_domain"],domain)
        self.assertEqual(first["manual_review"]["domain"],domain)
        self.assertEqual(len(first["manual_review"]["domain"]),160)
        self.assertEqual(first["recoveries"],0)
        self.assertEqual(self.tick()["state"],"Manual Review Required")
        current=worker.inspect(data_dir=str(self.data))
        self.assertEqual(current["manual_review"]["operation_id"],op)
        self.assertEqual(current["manual_review"]["domain"],domain)
        self.assertEqual(current["manual_review_count"],1)
        self.assertEqual(current["recoveries"],0)
        self.assertIsNone(current["last_recovery"])
        with worker._locked_state(str(self.data)) as fd:
            private=worker._read_manual_review(fd,op)
        self.assertEqual(private["event"]["target"],domain)
        logs=[e for e in read_activity(str(self.data)) if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(logs),1)
        self.assertEqual(logs[0]["target"],domain)
        with patch.object(api,"_STATE_DIR",str(self.data)), patch.object(
                api.ach_customizer_main,"_status_primary_admin_post",return_value=None):
            feed=api.ach_customizer_main().get_activity({"module":"lifecycle"})
        self.assertTrue(feed["status"],feed)
        matches=[e for e in feed["entries"] if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]["target"],domain)
        self.assertEqual(self.hosts.read_bytes(),self.before+marker)

    def test_interrupted_initial_staging_write_is_never_canonical(self):
        from ach_customizer_activity import read_activity
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        with worker._locked_state(str(self.data)) as fd:
            op=worker._load(fd)["active"]["operation"]
        original=worker._new_file
        def fail_partial(fd,name,content):
            if name.startswith("."+worker._manual_review_name(op)+".") and name.endswith(".tmp"):
                handle=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                try:
                    os.write(handle,content[:15])
                finally:
                    os.close(handle)
                raise OSError(errno.ENOSPC,"injected partial write")
            return original(fd,name,content)
        with patch.object(worker,"_new_file",side_effect=fail_partial):
            with self.assertRaises(OSError):
                self.finish()
        canonical=self.data/worker._manual_review_name(op)
        self.assertFalse(canonical.exists())
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review_count"],0)
        with worker._locked_state(str(self.data)) as fd:
            policy=worker._load(fd)
        self.assertEqual(policy["active"]["operation"],op)
        self.assertIsNone(policy["last_token"])
        self.assertEqual(self.tick()["state"],"Manual Review Required")
        record=worker.inspect(data_dir=str(self.data))["manual_review"]
        self.assertEqual(record["operation_id"],op)
        self.assertEqual(record["domain"],"failed.test")
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_crash_leftover_incomplete_staging_is_ignored_and_original_operation_reused(self):
        self.arm()
        with worker._locked_state(str(self.data)) as fd:
            op=worker._load(fd)["active"]["operation"]
        orphan=self.data/("."+worker._manual_review_name(op)+".crashed.tmp")
        orphan.write_bytes(b"\x00partial previous process")
        orphan.chmod(0o600)
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review_count"],0)
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review_integrity"]["state"],"Complete")
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        self.assertEqual(self.finish()["state"],"Manual Review Required")
        row=worker.inspect(data_dir=str(self.data))
        self.assertEqual(row["manual_review"]["operation_id"],op)
        self.assertTrue(orphan.exists(),"An unreviewed orphan stage is not auto-deleted")
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_atomic_rename_publication_failure_preserves_witness_without_canonical_record(self):
        self.arm()
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 failed.test")
        with worker._locked_state(str(self.data)) as fd:
            op=worker._load(fd)["active"]["operation"]
        with patch.object(worker,"_publish_manual_review_noreplace",
                          side_effect=OSError(errno.EIO,"injected atomic rename failure")):
            with self.assertRaises(OSError):
                self.finish()
        self.assertFalse((self.data/worker._manual_review_name(op)).exists())
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review_count"],0)
        self.assertEqual(self.tick()["state"],"Manual Review Required")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review"]["operation_id"],op)
        self.assertEqual(worker.inspect(data_dir=str(self.data))["recoveries"],0)
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 failed.test")

    def test_incomplete_canonical_is_preserved_reported_and_operator_recoverable(self):
        import ach_customizer_main as api
        from ach_customizer_activity import read_activity
        self.arm(domain="first.test")
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 first.test")
        self.assertEqual(self.finish(domain="first.test")["state"],"Manual Review Required")
        first=worker.inspect(data_dir=str(self.data))["manual_review"]["operation_id"]
        self.arm(domain="second.test")
        with worker._locked_state(str(self.data)) as fd:
            second=worker._load(fd)["active"]["operation"]
        broken=self.data/worker._manual_review_name(second)
        broken.write_bytes(b"\x00partial canonical bytes")
        broken.chmod(0o600)
        state=worker.inspect(data_dir=str(self.data))
        self.assertEqual(state["manual_review_count"],1)
        self.assertEqual(state["manual_review"]["operation_id"],first)
        self.assertEqual(state["manual_review_integrity"],
                         {"state":"Needs Review","incomplete_count":1,"first_operation_id":second})
        with patch.object(api,"_STATE_DIR",str(self.data)), patch.object(
                api.ach_customizer_main,"_status_primary_admin_post",return_value=None):
            report=api.ach_customizer_main().get_activity({"module":"lifecycle"})
        self.assertTrue(report["status"],report)
        self.assertIn(second,report["activity_warning"])
        self.assertEqual(len([e for e in report["entries"] if e["action"]=="wp_terminal_manual_review"]),1)
        self.hosts.write_bytes(self.before+b"\n127.0.0.1 first.test"+b"\n127.0.0.1 second.test")
        with self.assertRaisesRegex(worker.TerminalError,second):
            self.finish(domain="second.test")
        self.assertEqual(broken.read_bytes(),b"\x00partial canonical bytes")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["active_domain"],"second.test")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["recoveries"],0)
        # Simulate a separately reviewed *OS operator* quarantine of this exact
        # malformed file: the worker itself never deletes or overwrites it.
        quarantined=self.data/(broken.name+".quarantined")
        broken.rename(quarantined)
        self.assertEqual(self.tick()["state"],"Manual Review Required")
        reports=worker.manual_review_activity(data_dir=str(self.data))
        self.assertEqual({e["target"] for e in reports},{"first.test","second.test"})
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),2)
        self.assertTrue(quarantined.exists())
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review_integrity"]["state"],"Complete")
        self.assertIsNone(worker.inspect(data_dir=str(self.data))["last_recovery"])
        self.assertEqual(self.hosts.read_bytes(),self.before+b"\n127.0.0.1 first.test"+
                         b"\n127.0.0.1 second.test")

    def test_directory_fsync_failure_after_atomic_rename_is_recoverable(self):
        self.arm()
        marker=b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(self.before+marker)
        with worker._locked_state(str(self.data)) as fd:
            op=worker._load(fd)["active"]["operation"]
        original=worker.os.fsync
        seen=[False]
        def fail_post_link(fd):
            if (not seen[0] and os.fstat(fd).st_mode & 0o170000 == 0o040000 and
                    (self.data/worker._manual_review_name(op)).exists()):
                seen[0]=True
                raise OSError(errno.EIO,"injected directory fsync failure after link")
            return original(fd)
        with patch.object(worker.os,"fsync",side_effect=fail_post_link):
            with self.assertRaises(OSError):
                self.finish()
        self.assertTrue(seen[0])
        with worker._locked_state(str(self.data)) as fd:
            first=worker._read_manual_review(fd,op)
            self.assertEqual(worker._load(fd)["active"]["operation"],op)
        self.assertEqual(first["event"]["target"],"failed.test")
        self.assertEqual(self.tick()["state"],"Manual Review Required")
        with worker._locked_state(str(self.data)) as fd:
            self.assertEqual(worker._read_manual_review(fd,op)["event"],first["event"])
        from ach_customizer_activity import read_activity
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.hosts.read_bytes(),self.before+marker)

    def test_sigkill_after_atomic_publication_recovers_single_link_canonical(self):
        """A real child process exit cannot execute Python finally cleanup."""
        from ach_customizer_activity import read_activity
        self.arm()
        marker=b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(self.before+marker)
        with worker._locked_state(str(self.data)) as fd:
            operation=worker._load(fd)["active"]["operation"]
        pid=os.fork()
        if pid == 0:
            real=worker._publish_manual_review_noreplace
            def die_after_publish(*args):
                real(*args)
                os._exit(77)
            try:
                with patch.object(worker,"_publish_manual_review_noreplace",
                                  side_effect=die_after_publish):
                    self.finish()
            except BaseException:
                os._exit(88)
            os._exit(89)
        _,status=os.waitpid(pid,0)
        self.assertEqual(os.waitstatus_to_exitcode(status),77)
        canonical=self.data/worker._manual_review_name(operation)
        self.assertTrue(canonical.is_file())
        self.assertEqual(canonical.stat().st_nlink,1,
            "A crash must not leave a linked private stage that blocks safe reads")
        self.assertFalse(list(self.data.glob("."+canonical.name+".*.tmp")))
        state=worker.inspect(data_dir=str(self.data))
        self.assertEqual(state["manual_review"]["operation_id"],operation)
        self.assertEqual(state["manual_review_integrity"]["state"],"Complete")
        self.assertEqual(self.tick()["state"],"Manual Review Required")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["manual_review_count"],1)
        self.assertEqual(len([r for r in read_activity(str(self.data))
                              if r["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.hosts.read_bytes(),self.before+marker)

    def test_only_corrupt_canonical_and_broken_general_log_report_precise_metadata(self):
        import ach_customizer_main as api
        from ach_customizer_activity import LOG_NAME
        self.arm()
        with worker._locked_state(str(self.data)) as fd:
            operation=worker._load(fd)["active"]["operation"]
        canonical=self.data/worker._manual_review_name(operation)
        canonical.write_bytes(b"partial")
        canonical.chmod(0o600)
        log=self.data/LOG_NAME
        log.write_text("invalid JSONL\n")
        log.chmod(0o600)
        with patch.object(api,"_STATE_DIR",str(self.data)),patch.object(
                api.ach_customizer_main,"_status_primary_admin_post",return_value=None):
            response=api.ach_customizer_main().get_activity({"module":"lifecycle"})
        self.assertTrue(response["status"],response)
        self.assertEqual(response["entries"],[])
        self.assertIn(operation,response["activity_warning"])
        self.assertIn("General Activity log unavailable",response["activity_warning"])
        self.assertEqual(canonical.read_bytes(),b"partial")
        self.assertEqual(worker.inspect(data_dir=str(self.data))["active_domain"],"failed.test")
        self.assertEqual(self.hosts.read_bytes(),self.before)

    def test_existing_valid_canonical_record_cannot_be_clobbered(self):
        from ach_customizer_activity import read_activity
        self.arm()
        with worker._locked_state(str(self.data)) as fd:
            op=worker._load(fd)["active"]["operation"]
            original=worker._prepare_manual_review(fd,op,"failed.test")
            attempted={**original,"event":{**original["event"],"time_utc":"2026-01-01T00:00:00+00:00"}}
            worker._write_manual_review(fd,attempted,initial=True)
            unchanged=worker._read_manual_review(fd,op)
            self.assertEqual(unchanged,original)
            forged={**original,"event":{**original["event"],"target":"another.test"}}
            with self.assertRaises(worker.TerminalError):
                worker._write_manual_review(fd,forged,initial=True)
            self.assertEqual(worker._read_manual_review(fd,op),original)

    def test_manual_review_outbox_recovers_after_activity_disk_failure(self):
        from ach_customizer_activity import ActivityError, LOG_NAME, append_activity, read_activity
        from ach_customizer_main import ach_customizer_main
        import ach_customizer_main as api
        self.arm()
        exact=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(exact)
        original=append_activity
        def fail_manual(directory,event,**kwargs):
            if kwargs.get("mandatory_manual_review"):
                raise ActivityError("injected Activity disk failure")
            return original(directory,event,**kwargs)
        with patch("ach_customizer_activity.append_activity",side_effect=fail_manual):
            result=self.finish()
            self.assertEqual(result["state"],"Manual Review Required")
            saved=worker.inspect(data_dir=str(self.data))
            self.assertEqual(saved["manual_review_count"],1)
            manual=saved["manual_review"]
            self.assertEqual(manual["domain"],"failed.test")
            self.assertRegex(manual["operation_id"],r"^[0-9a-f]{32}$")
            self.assertIs(manual["activity_delivered"],False)
            # Even if JSONL delivery is broken, an authorized Activity read
            # projects the durable event exactly once.
            with patch.object(api,"_STATE_DIR",str(self.data)), patch.object(
                    api.ach_customizer_main,"_status_primary_admin_post",return_value=None):
                dashboard=ach_customizer_main().get_activity({"module":"lifecycle"})
            self.assertTrue(dashboard["status"],dashboard)
            matches=[e for e in dashboard["entries"]
                     if e["action"]=="wp_terminal_manual_review"]
            self.assertEqual(len(matches),1)
            self.assertEqual(matches[0]["target"],"failed.test")
        # The terminal token was already persisted. Recovery must NOT replay
        # Hosts edits or fabricate a new operation/recovery journal.
        second=self.tick()
        self.assertEqual(second["state"],"Already Observed")
        current=worker.inspect(data_dir=str(self.data))
        self.assertEqual(current["manual_review_count"],1)
        self.assertEqual(current["manual_review"]["operation_id"],manual["operation_id"])
        self.assertIs(current["manual_review"]["activity_delivered"],True)
        self.assertEqual(current["recoveries"],0)
        self.assertIsNone(current["last_recovery"])
        logs=read_activity(str(self.data),module="lifecycle")
        self.assertEqual(len([e for e in logs if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.hosts.read_bytes(),exact)
        self.assertEqual((self.data/LOG_NAME).read_text().count('"wp_terminal_manual_review"'),1)

    def test_manual_review_crash_after_token_commit_before_activity(self):
        self.arm()
        exact=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(exact)
        real=worker._deliver_pending_manual_reviews
        def crash_after_policy(fd,data_dir):
            policy=worker._load(fd)
            if policy["last_token"] is not None:
                raise SystemExit("crash after terminal token before Activity")
            return real(fd,data_dir)
        with patch.object(worker,"_deliver_pending_manual_reviews",side_effect=crash_after_policy):
            with self.assertRaisesRegex(SystemExit,"before Activity"):
                self.finish()
        evidence=worker.inspect(data_dir=str(self.data))
        self.assertIsNone(evidence["active_domain"])
        self.assertEqual(evidence["manual_review"]["domain"],"failed.test")
        self.assertIs(evidence["manual_review"]["activity_delivered"],False)
        self.assertEqual(self.hosts.read_bytes(),exact)
        self.assertEqual(self.tick()["state"],"Already Observed")
        self.assertIs(worker.inspect(data_dir=str(self.data))["manual_review"]["activity_delivered"],True)
        from ach_customizer_activity import read_activity
        events=[e for e in read_activity(str(self.data)) if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(events),1)

    def test_manual_review_crash_after_activity_fsync_before_delivery_receipt(self):
        self.arm()
        exact=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(exact)
        real=worker._write_manual_review
        def stop_before_receipt(fd,row,*,initial=False):
            if not initial and row["delivered"]:
                raise SystemExit("crash after Activity fsync")
            return real(fd,row,initial=initial)
        with patch.object(worker,"_write_manual_review",side_effect=stop_before_receipt):
            with self.assertRaisesRegex(SystemExit,"after Activity fsync"):
                self.finish()
        evidence=worker.inspect(data_dir=str(self.data))
        self.assertIs(evidence["manual_review"]["activity_delivered"],False)
        from ach_customizer_activity import read_activity, LOG_NAME
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.tick()["state"],"Already Observed")
        self.assertIs(worker.inspect(data_dir=str(self.data))["manual_review"]["activity_delivered"],True)
        self.assertEqual((self.data/LOG_NAME).read_text().count('"wp_terminal_manual_review"'),1)
        self.assertEqual(self.hosts.read_bytes(),exact)

    def test_manual_review_crash_after_durable_outbox_before_policy_commit(self):
        self.arm()
        exact=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(exact)
        original=worker._worker_outcome
        def crash_before_policy(fd,policy,state,stage,reason,**kwargs):
            if state=="Manual Review Required":
                raise SystemExit("simulated crash before terminal policy commit")
            return original(fd,policy,state,stage,reason,**kwargs)
        with patch.object(worker,"_worker_outcome",side_effect=crash_before_policy):
            with self.assertRaisesRegex(SystemExit,"before terminal"):
                self.finish()
        pending=worker.inspect(data_dir=str(self.data))
        self.assertIsNotNone(pending["active_domain"])
        self.assertEqual(pending["manual_review_count"],1)
        first_op=pending["manual_review"]["operation_id"]
        # A restarted worker may deliver the existing outbox first. Repeated
        # native terminal observation must not create a second event.
        result=self.tick()
        self.assertEqual(result["state"],"Manual Review Required")
        latest=worker.inspect(data_dir=str(self.data))
        self.assertEqual(latest["manual_review_count"],1)
        self.assertEqual(latest["manual_review"]["operation_id"],first_op)
        self.assertIsNone(latest["active_domain"])
        self.assertIs(latest["manual_review"]["activity_delivered"],True)
        from ach_customizer_activity import read_activity
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.hosts.read_bytes(),exact)

    def test_disabled_worker_can_replay_pending_manual_review_without_restarting_watcher(self):
        from ach_customizer_activity import ActivityError, read_activity
        self.arm()
        exact=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(exact)
        with patch("ach_customizer_activity.append_activity",
                   side_effect=ActivityError("disk unavailable")):
            self.assertEqual(self.finish()["state"],"Manual Review Required")
        worker.set_enabled(False,data_dir=str(self.data))
        self.assertEqual(self.tick()["state"],"Disabled")
        state=worker.inspect(data_dir=str(self.data))
        self.assertFalse(state["enabled"])
        self.assertTrue(state["manual_review"]["activity_delivered"])
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(self.hosts.read_bytes(),exact)

    def test_rotated_activity_does_not_discard_private_manual_review_identity(self):
        from ach_customizer_activity import MAX_LOG_BYTES, append_activity, read_activity
        self.arm()
        exact=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(exact)
        self.assertEqual(self.finish()["state"],"Manual Review Required")
        first_op=worker.inspect(data_dir=str(self.data))["manual_review"]["operation_id"]
        # Force enough ordinary rows to rotate both JSONL generations.
        from ach_customizer_activity import record
        with patch("ach_customizer_activity.MAX_LOG_BYTES",4096):
            for i in range(1,50):
                append_activity(str(self.data),record(
                    level="ERROR",module="lifecycle",action="other",
                    stage="fixture",outcome="Observed",operation_id=f"{i:032x}",
                    detail="x"*150))
        raw=read_activity(str(self.data),module="lifecycle")
        self.assertFalse(any(e["action"]=="wp_terminal_manual_review" for e in raw))
        import ach_customizer_main as api
        with patch.object(api,"_STATE_DIR",str(self.data)), patch.object(
                api.ach_customizer_main,"_status_primary_admin_post",return_value=None):
            result=api.ach_customizer_main().get_activity({"module":"lifecycle","limit":100})
        self.assertTrue(result["status"],result)
        canonical=[e for e in result["entries"] if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(canonical),1)
        self.assertEqual(canonical[0]["target"],"failed.test")
        self.assertEqual(canonical[0]["operation_id"],first_op)
        self.assertEqual(self.hosts.read_bytes(),exact)

    def test_manual_review_bypasses_error_verbosity_but_other_warnings_do_not(self):
        from ach_customizer_activity import read_activity
        self.arm()
        marker=b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(self.before+marker)
        with patch.dict(os.environ,{"ACH_CUSTOMIZER_ACTIVITY_LEVEL":"ERROR"}):
            response=self.finish()
            self.assertEqual(response["state"],"Manual Review Required")
            rows=[e for e in read_activity(str(self.data)) if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["level"],"WARNING")
        self.assertEqual(rows[0]["target"],"failed.test")
        self.assertIs(worker.inspect(data_dir=str(self.data))["manual_review"]["activity_delivered"],True)
        self.assertEqual(self.hosts.read_bytes(),self.before+marker)

    def test_multiple_manual_review_domains_persist_after_later_worker_state(self):
        from ach_customizer_activity import read_activity
        self.arm(domain="failed.test")
        first=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(first)
        self.assertEqual(self.finish()["state"],"Manual Review Required")
        op1=worker.inspect(data_dir=str(self.data))["manual_review"]["operation_id"]
        # A second independent failed installation must not erase the first.
        self.arm(domain="second.test")
        second=first+b"\n127.0.0.1 second.test"
        self.hosts.write_bytes(second)
        self.assertEqual(self.finish(domain="second.test")["state"],"Manual Review Required")
        status=worker.inspect(data_dir=str(self.data))
        self.assertEqual(status["manual_review_count"],2)
        self.assertNotEqual(status["manual_review"]["operation_id"],op1)
        self.assertEqual(status["manual_review"]["domain"],"second.test")
        # Even after new timer observations replace last_worker, the durable
        # domain-to-operation mappings survive and Activity is deduplicated.
        self.assertEqual(self.tick()["state"],"Already Observed")
        records=[e for e in worker.manual_review_activity(data_dir=str(self.data))
                 if e["action"]=="wp_terminal_manual_review"]
        self.assertEqual(len(records),2)
        self.assertEqual({e["target"] for e in records},{"failed.test","second.test"})
        self.assertEqual(len([e for e in read_activity(str(self.data))
                              if e["action"]=="wp_terminal_manual_review"]),2)
        self.assertEqual(self.hosts.read_bytes(),second)
        self.assertEqual(status["recoveries"],0)

    def test_activity_log_corruption_retains_privileged_manual_view(self):
        import ach_customizer_main as api
        from ach_customizer_activity import LOG_NAME
        self.arm()
        original=self.before+b"\n127.0.0.1 failed.test"
        self.hosts.write_bytes(original)
        self.assertEqual(self.finish()["state"],"Manual Review Required")
        (self.data/LOG_NAME).write_text("corrupt general log\n")
        (self.data/LOG_NAME).chmod(0o600)
        with patch.object(api,"_STATE_DIR",str(self.data)), patch.object(
                api.ach_customizer_main,"_status_primary_admin_post",return_value=None):
            reply=api.ach_customizer_main().get_activity({})
        self.assertTrue(reply["status"],reply)
        self.assertIn("General Activity log unavailable",reply["activity_warning"])
        self.assertEqual(len([e for e in reply["entries"]
                              if e["action"]=="wp_terminal_manual_review"]),1)
        self.assertEqual(reply["entries"][0]["target"],"failed.test")
        self.assertEqual(self.hosts.read_bytes(),original)

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
