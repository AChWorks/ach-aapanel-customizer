"""Isolated PHP runtime process/socket evidence: no host service mutations."""
import hashlib
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / "plugin" / "ach_customizer"
sys.path.insert(0, str(PLUGIN))
import ach_customizer_php_runtime as runtime


class RuntimeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ach-fpm-runtime-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phps = self.root / "php"
        self.phps.mkdir()
        self.proc = self.root / "proc"
        self.proc.mkdir()
        (self.proc / "net").mkdir()
        self.sockpath = str(self.root / "php-test.sock")
        self.all_sockets = []
        self.addCleanup(lambda: [item.close() for item in self.all_sockets])
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.all_sockets.append(self.sock)
        self.sock.bind(self.sockpath)
        self.sock.listen(2)
        self.binary = self.create_php("81")
        self.inode = "912345"
        self.pid = "432"
        self.process(self.pid)
        self.unix(self.inode)

    def create_php(self, version):
        path = self.phps / version
        (path / "etc").mkdir(parents=True)
        (path / "sbin").mkdir()
        binary = path / "sbin" / "php-fpm"
        binary.write_bytes(b"\x7fELF" + b"fpm-test" * 6)
        binary.chmod(0o755)
        (path / "etc" / "php-fpm.conf").write_text(
            "[global]\n[www]\nlisten = " + self.sockpath + "\n"
        )
        return binary

    def process(self, pid, *, exe=None, title=None, inode=None, start="12345"):
        folder = self.proc / pid
        folder.mkdir(exist_ok=True)
        binary = folder / "exe"
        if binary.is_symlink():
            binary.unlink()
        binary.symlink_to(exe or self.binary)
        if title is None:
            title = "php-fpm: master process (" + str(
                self.phps / "81" / "etc" / "php-fpm.conf") + ")"
        (folder / "cmdline").write_bytes(title.encode() + b"\x00")
        # Field 22 of /proc/PID/stat is starttime, index 19 after '(comm)'.
        (folder / "stat").write_text(
            pid + " (php-fpm) S " + " ".join(["1"] * 18 + [start] + ["1"] * 8))
        fd = folder / "fd"
        fd.mkdir(exist_ok=True)
        for entry in fd.iterdir():
            entry.unlink()
        (fd / "7").symlink_to("socket:[" + (inode or self.inode) + "]")

    def unix(self, inode, *, path=None, flags="00010000"):
        (self.proc / "net" / "unix").write_text(
            "Num RefCount Protocol Flags Type St Inode Path\n"
            "0000000000000000: 00000003 00000000 " + flags +
            " 0001 01 " + inode + " " + (path or self.sockpath) + "\n")

    def inspect(self, version="81"):
        return runtime.inspect_php_fpm_runtime(
            str(self.phps), version, proc_root=str(self.proc))

    def deny(self, result):
        self.assertNotEqual(result["state"], "Observed", result)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["apply_eligible"])

    def test_exact_binary_master_config_kernel_socket_and_fd_observed(self):
        before = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        result = self.inspect()
        self.assertEqual(result["state"], "Observed", result)
        self.assertEqual(result["master_state"], "Matching Master")
        self.assertEqual(result["socket_state"], "Bound Listener")
        self.assertEqual(result["master_pid"], 432)
        self.assertEqual(result["socket_path"], self.sockpath)
        self.assertFalse(result["apply_eligible"])
        self.assertFalse(result["runtime_verified"])
        self.assertEqual(hashlib.sha256(self.binary.read_bytes()).hexdigest(), before)

    def test_other_versions_and_unknown_not_misclassified(self):
        self.create_php("85")
        r = self.inspect("85")
        self.deny(r)
        self.assertEqual(r["master_state"], "Not Observed")
        self.assertIn("does not prove service stopped", r["reason"])
        for v in ("80", "99"):
            self.deny(self.inspect(v))
        for invalid in ("", "bad", "../81", "8.1", None):
            with self.subTest(invalid=invalid), self.assertRaises(
                    runtime.RuntimeInspectError):
                self.inspect(invalid)

    def test_unknown_master_or_wrong_binary_rejected(self):
        self.process(self.pid, title="php-fpm: pool www")
        self.deny(self.inspect())
        self.process(self.pid, title="php-fpm: master process (/other/php.conf)")
        self.deny(self.inspect())
        self.process(self.pid, exe="/bin/true")
        self.deny(self.inspect())

    def test_missing_socket_or_unbound_listener_is_partial(self):
        self.sock.close()
        os.unlink(self.sockpath)
        r = self.inspect()
        self.deny(r)
        self.assertEqual(r["state"], "Partial")
        self.assertEqual(r["socket_state"], "Missing")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.all_sockets.append(self.sock)
        self.sock.bind(self.sockpath)
        self.unix(self.inode, path="/different.sock")
        r = self.inspect()
        self.deny(r)
        self.assertEqual(r["socket_state"], "Not Observed")

    def test_socket_and_process_fd_must_correspond(self):
        self.unix(self.inode, flags="00000000")
        self.deny(self.inspect())
        self.unix(self.inode)
        self.process(self.pid, inode="888888")
        r = self.inspect()
        self.deny(r)
        self.assertEqual(r["socket_state"], "Not Observed")

    def test_php85_independent_master_can_be_observed_without_write_capability(self):
        php85 = self.create_php("85")
        self.process(self.pid, exe=php85, title="php-fpm: master process (" +
                     str(self.phps / "85" / "etc" / "php-fpm.conf") + ")")
        r = self.inspect("85")
        self.assertEqual(r["state"], "Observed", r)
        self.assertFalse(r["apply_eligible"])
        self.assertFalse(r["runtime_verified"])

    def test_duplicated_kernel_listener_path_cannot_prove_single_ownership(self):
        table = self.proc / "net" / "unix"
        row = table.read_text().splitlines()[1]
        table.write_text(table.read_text() + row + "\n")
        r = self.inspect()
        self.deny(r)
        self.assertIn("ambiguous", r["reason"].lower())

    def test_procfs_net_unix_symlink_and_oversized_table_fail_closed(self):
        table = self.proc / "net" / "unix"
        table.unlink()
        table.symlink_to("/etc/hosts")
        self.deny(self.inspect())
        table.unlink()
        table.write_text("Num RefCount Protocol Flags Type St Inode Path\n" +
                         "x" * (runtime.MAX_UNIX_LIST + 1))
        r = self.inspect()
        self.deny(r)
        self.assertIn("oversized", r["reason"].lower())

    def test_binary_changed_during_observation_is_rejected(self):
        original = runtime._native_binary
        count = 0
        def drift(*args, **kwargs):
            nonlocal count
            count += 1
            identity = original(*args, **kwargs)
            return identity if count == 1 else (
                identity[0], identity[1] + 1, identity[2], identity[3])
        with patch.object(runtime, "_native_binary", side_effect=drift):
            r = self.inspect()
        self.deny(r)
        self.assertIn("changed", r["reason"].lower())

    def test_file_descriptor_overflow_must_not_infer_bound_master(self):
        folder = self.proc / self.pid / "fd"
        # The valid listener is present before hundreds of unrelated FDs.
        # Even if scandir yields the valid listener first, no positive result
        # may be returned before the complete bounded-list validation.
        self.assertEqual((folder / "7").readlink().as_posix(),
                         "socket:[" + self.inode + "]")
        for idx in range(runtime.MAX_MASTER_FDS + 1):
            (folder / str(1000 + idx)).symlink_to("pipe:[123]")
        r = self.inspect()
        self.deny(r)
        self.assertIn("too many file descriptors", r["reason"].lower())

    def test_multiple_masters_and_unsupported_includes_fail_closed(self):
        self.process("433")
        r = self.inspect()
        self.deny(r)
        self.assertIn("ambiguous", r["reason"].lower())
        (self.proc / "433" / "exe").unlink()
        (self.phps / "81" / "etc" / "php-fpm.conf").write_text(
            "[www]\nlisten = " + self.sockpath + "\ninclude = php-fpm.d/*.conf\n")
        r = self.inspect()
        self.deny(r)
        self.assertIn("included", r["reason"].lower())

    def test_symlinks_and_mid_probe_pid_reuse_block_success(self):
        self.sock.close()
        os.unlink(self.sockpath)
        Path(self.sockpath).symlink_to("/bin/true")
        self.deny(self.inspect())
        Path(self.sockpath).unlink()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.all_sockets.append(self.sock)
        self.sock.bind(self.sockpath)
        original = runtime._master_holds_listener
        seen = 0
        def change(*args, **kwargs):
            nonlocal seen
            answer = original(*args, **kwargs)
            seen += 1
            if seen == 1:
                self.process(self.pid, start="55555")
            return answer
        with patch.object(runtime, "_master_holds_listener", side_effect=change):
            r = self.inspect()
        self.deny(r)
        self.assertIn("changed", r["reason"])

    def test_extra_pools_duplicate_www_and_malformed_sources_never_observe(self):
        conf = self.phps / "81" / "etc" / "php-fpm.conf"
        baseline = conf.read_text()
        for extra in ("[other]\nlisten = /tmp/other.sock\n",
                      "[www]\nlisten = /tmp/other.sock\n",
                      "broken_without_equals\n", "[broken\n",
                      "include = pool.d/*.conf\n"):
            with self.subTest(extra=extra):
                conf.write_text(baseline + extra)
                got = self.inspect()
                self.deny(got)
                self.assertEqual(got["state"], "Needs Review")
                self.assertIsNone(got["master_pid"])
        conf.write_text(baseline)
        self.assertEqual(self.inspect()["state"], "Observed")

    def test_pid_reuse_cannot_keep_matching_master_on_early_partial_paths(self):
        # Exercise each early-return branch, not only the fully bound socket.
        for case in ("missing-socket", "missing-listener", "no-master-fd"):
            with self.subTest(case=case):
                if case == "missing-socket":
                    self.sock.close()
                    Path(self.sockpath).unlink()
                elif case == "missing-listener":
                    self.unix(self.inode, path="/different.sock")
                else:
                    self.unix(self.inode)
                    self.process(self.pid, inode="999999")
                original = runtime._process_start
                count = 0
                def reused(*args):
                    nonlocal count
                    count += 1
                    return original(*args) if count == 1 else "222222"
                with patch.object(runtime, "_process_start", side_effect=reused):
                    got = self.inspect()
                self.assertEqual(got["state"], "Needs Review", got)
                self.assertEqual(got["master_state"], "Needs Review")
                self.assertIsNone(got["master_pid"])
                self.assertIn("changed", got["reason"].lower())
                # Re-create a valid listener and master for the next case.
                if case == "missing-socket":
                    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.all_sockets.append(self.sock)
                    self.sock.bind(self.sockpath)
                    self.sock.listen(2)
                self.unix(self.inode)
                self.process(self.pid)

    def test_early_partial_revalidates_binary_title_and_fpm_source(self):
        self.unix(self.inode, path="/different.sock")
        original = runtime._master_title
        calls = 0
        def replaced_title(*args):
            nonlocal calls
            calls += 1
            return original(*args) if calls == 1 else False
        with patch.object(runtime, "_master_title", side_effect=replaced_title):
            result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["master_pid"])
        # A config modification after the initial master scan also revokes
        # the old PID association rather than returning Partial.
        conf = self.phps / "81" / "etc" / "php-fpm.conf"
        original = runtime._listening_inode
        def changed_config(*args):
            conf.write_text(conf.read_text() + "# regenerated\n")
            return None
        with patch.object(runtime, "_listening_inode", side_effect=changed_config):
            result = self.inspect()
        self.assertEqual(result["state"], "Needs Review")
        self.assertIsNone(result["master_pid"])

    def test_numeric_procfs_bound_blocks_untrusted_mass_listing(self):
        for i in range(runtime.MAX_PROCESSES):
            (self.proc / str(2000 + i)).mkdir()
        r = self.inspect()
        self.deny(r)
        self.assertIn("too many", r["reason"].lower())


if __name__ == "__main__":
    unittest.main()
