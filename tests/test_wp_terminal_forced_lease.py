"""Opt-in extended Linux lease-break regression (~45 seconds on Debian QA).

Run explicitly with:
  AAC_WP_FORCE_LEASE_QA=1 python3 -B -m unittest discover -s tests -p test_wp_terminal_forced_lease.py -v

Never touches /etc/hosts or installed aaPanel state. A child is SIGSTOP'ed
after the legacy Restore final guard; a separate writer blocks on the lease
until the real kernel forces its expiration. The resumed Restore must leave
the complete foreign append intact and return Needs Review. New unattended
WP terminal observations cannot invoke this append-only helper at all.
"""
import hashlib
import os
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_wp_terminal as worker


@unittest.skipUnless(os.environ.get("AAC_WP_FORCE_LEASE_QA") == "1",
                     "Run only in an explicitly approved isolated extended QA")
class ForcedLeaseBreakRegression(unittest.TestCase):
    def test_real_forced_lease_break_does_not_overwrite_foreign_hosts_append(self):
        lease_timeout = int(Path("/proc/sys/fs/lease-break-time").read_text().strip())
        self.assertGreaterEqual(lease_timeout, 1)
        self.assertLessEqual(lease_timeout, 55, "Use a bounded isolated host for this test")
        with tempfile.TemporaryDirectory(prefix="aac-wp-real-lease-") as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir(mode=0o700)
            parent = root / "source"
            parent.mkdir(mode=0o700)
            hosts = parent / "hosts"
            baseline = b"127.0.0.1 localhost\n192.0.2.9 retained-before.test\n"
            hosts.write_bytes(baseline)
            hosts.chmod(0o644)
            op = uuid4().hex
            domain = "failed.test"
            marker = b"\n127.0.0.1 " + domain.encode("ascii")
            foreign = b"192.0.2.55 retained-after-forced-break.test\n"
            with worker._locked_state(str(state)) as fd:
                worker._new_file(fd, worker._baseline_name(op), baseline)
                rec = {"schema": 1, "operation": op, "domain": domain,
                       "phase": "applied", "before_sha": hashlib.sha256(baseline + marker).hexdigest(),
                       "after_sha": hashlib.sha256(baseline).hexdigest(),
                       "backup": worker._baseline_name(op)}
                worker._save_recovery(fd, rec)
                policy = worker._default()
                policy["last_recovery"] = op
                policy["recoveries"] = 1
                worker._save(fd, policy)

            # Child only ever calls explicit operator-reviewed, append-only
            # *historical* Restore, not autonomous failed-WP alias deletion.
            child_code = r"""
import os, signal, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import ach_customizer_wp_terminal as w
root=Path(sys.argv[2])
w.LOCK=str(root/'native.lock')
w.BATCH_LOCK=str(root/'batch.lock')
original=os.write
suffix=b'\n127.0.0.1 failed.test'
def suspended_append(fd,data):
    if data==suffix:
        print('AFTER_FINAL_GUARD', flush=True)
        os.kill(os.getpid(), signal.SIGSTOP)
    return original(fd,data)
os.write=suspended_append
try:
    w.restore(sys.argv[3], data_dir=str(root/'state'),
              hosts_path=str(root/'source'/'hosts'))
    print('UNEXPECTED_LEGACY_RESTORE_SUCCESS',flush=True)
    sys.exit(4)
except w.TerminalError as exc:
    print('NEEDS_RECHECK '+str(exc),flush=True)
"""
            competitor_code = r"""
import os,sys
f=os.open(sys.argv[1],os.O_WRONLY|os.O_APPEND)
try:
    amount=os.write(f,bytes.fromhex(sys.argv[2]))
    assert amount==len(bytes.fromhex(sys.argv[2]))
    os.fsync(f)
finally:
    os.close(f)
print('FOREIGN_APPEND_ADMITTED')
"""
            child = subprocess.Popen(
                [sys.executable, "-B", "-c", child_code, str(PLUGIN), tmp, op],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            competitor = None
            try:
                readable, _, _ = select.select([child.stdout], [], [], 10)
                self.assertTrue(readable, "Legacy Restore child did not reach final guard")
                self.assertEqual(child.stdout.readline().strip(), "AFTER_FINAL_GUARD")
                self.assertIsNone(child.poll())
                competitor = subprocess.Popen(
                    [sys.executable, "-B", "-c", competitor_code, str(hosts), foreign.hex()],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                out, err = competitor.communicate(timeout=lease_timeout + 22)
                self.assertEqual(competitor.returncode, 0, err)
                self.assertIn("FOREIGN_APPEND_ADMITTED", out)
                self.assertIsNone(child.poll(), "Holder must still be SIGSTOP'ed")
                # After real forced lease expiration, previously blocked O_APPEND
                # has completed. The paused holder now resumes, appending at EOF
                # rather than overwriting those exact foreign bytes.
                os.kill(child.pid, signal.SIGCONT)
                tail, err = child.communicate(timeout=8)
                self.assertEqual(child.returncode, 0, err + tail)
                self.assertIn("NEEDS_RECHECK", tail)
                self.assertEqual(hosts.read_bytes(), baseline + foreign + marker)
                checked = worker.recheck_recovery(
                    data_dir=str(state), hosts_path=str(hosts))
                self.assertEqual(checked["state"], "Needs Review")
                self.assertEqual(worker.inspect(data_dir=str(state))["last_recovery"], op)
                with worker._locked_state(str(state)) as fd:
                    self.assertEqual(worker._read_recovery(fd, op)["phase"], "restore_prepared")
            finally:
                if competitor and competitor.poll() is None:
                    competitor.kill()
                    competitor.communicate(timeout=5)
                if child.poll() is None:
                    try:
                        os.kill(child.pid, signal.SIGCONT)
                    except ProcessLookupError:
                        pass
                    child.kill()
                    child.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
