"""Pure isolated filesystem tests; no host FPM or aaPanel service mutations."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin/ach_customizer"))
import ach_customizer_fpm_apply as manual
from ach_customizer_monitor import preview_php_fpm

DESIRED = {
    "pm.max_children": 20,
    "pm.start_servers": 5,
    "pm.min_spare_servers": 5,
    "pm.max_spare_servers": 10,
    "pm.max_requests": 300,
}
BASELINE = (b"[global]\n"
            b"pid = /tmp/fpm-test.pid\n\n"
            b"[www]\n"
            b"listen = /tmp/test-fpm.sock\n"
            b"user = www\n"
            b"group = www\n"
            b"pm = dynamic\n"
            b"pm.max_children = 50 ; leave this comment\n"
            b"pm.start_servers = 5\n"
            b"pm.min_spare_servers = 5\n"
            b"pm.max_spare_servers = 20\n"
            b"pm.status_path = /fpm-status\n")


class TestFpmManualApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_dir = self.root / "php" / "85" / "etc"
        self.data = self.root / "panel-data"
        self.config_dir.mkdir(parents=True)
        self.data.mkdir(mode=0o700)
        self.config = self.config_dir / "php-fpm.conf"
        self.config.write_bytes(BASELINE)
        self.config.chmod(0o644)
        self.events = []

    def plan(self):
        return manual.preview(self.root / "php", "85", DESIRED)

    def hooks(self):
        def validate():
            self.events.append("validate")
            if not self.config.exists():
                raise AssertionError("Configuration unexpectedly missing")
        def activate():
            self.events.append("activate")
        def verify():
            self.events.append("verify")
        return validate, activate, verify

    def apply(self, desired=None, hooks=None, plan=None, verify_restored=None):
        desired = DESIRED if desired is None else desired
        plan = self.plan() if plan is None else plan
        validate, activate, verify = hooks or self.hooks()
        return manual.apply(
            self.root / "php", self.data, "85", desired,
            expected_before=plan["before_sha256"],
            expected_after=plan["after_sha256"],
            validate=validate, activate=activate, verify=verify,
            verify_restored=verify_restored or self.hooks()[2],
        )

    def test_preview_is_read_only_and_version_scoped(self):
        before = self.config.read_bytes()
        plan = self.plan()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(plan["source"], str(self.config))
        self.assertEqual(plan["scope"], "shared_service")
        self.assertEqual([d["setting"] for d in plan["changes"]],
                         ["pm.max_children", "pm.max_spare_servers", "pm.max_requests"])
        with self.assertRaisesRegex(manual.FpmApplyError, "Only verified PHP"):
            manual.preview(self.root / "php", "84", DESIRED)
        self.assertEqual(list(self.data.iterdir()), [])

    def test_apply_and_rollback_restore_exact_bytes_and_permissions(self):
        plan = self.plan()
        result = self.apply(plan=plan)
        self.assertEqual(result["state"], "Applied")
        self.assertEqual(len(result["operation_id"]), 32)
        self.assertEqual(self.events, ["validate", "validate", "activate", "verify"])
        self.assertEqual(preview_php_fpm(self.root / "php", "85", DESIRED)["state"], "File Match")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.data / manual.SNAPSHOT).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.data / manual.JOURNAL).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.data / manual.SNAPSHOT).read_bytes(), BASELINE)
        recovered = manual.rollback(
            self.root / "php", self.data, "85", result["operation_id"],
            validate=self.hooks()[0], activate=self.hooks()[1], verify=self.hooks()[2],
            prewrite_check=lambda: None)
        self.assertEqual(recovered["state"], "Rolled Back")
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertFalse((self.data / manual.SNAPSHOT).exists())
        self.assertFalse((self.data / manual.JOURNAL).exists())

    def test_noop_requires_no_write_or_reload(self):
        self.config.write_bytes(BASELINE.replace(b"50 ;", b"20 ;").replace(b"= 20\n", b"= 10\n") + b"pm.max_requests = 300\n")
        plan = self.plan()
        self.assertEqual(plan["changes"], [])
        result = self.apply(plan=plan)
        self.assertEqual(result["state"], "No Change")
        self.assertEqual(self.events, [])
        self.assertFalse((self.data / manual.JOURNAL).exists())

    def test_stale_preview_rejected_before_backup(self):
        plan = self.plan()
        self.config.write_bytes(BASELINE + b"; panel modified\n")
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply(plan=plan)
        self.assertEqual(caught.exception.stage, "conflict")
        self.assertEqual(list(self.data.glob("*recovery*")), [self.data / manual.LOCK])
        self.assertEqual(self.config.read_bytes(), BASELINE + b"; panel modified\n")

    def test_incompatible_and_ambiguous_shapes_refuse(self):
        invalids = (
            BASELINE.replace(b"pm.max_children = 50", b"pm.max_children = 50\npm.max_children=80"),
            BASELINE + b"\n[another]\npm=dynamic\n",
            BASELINE + b"\ninclude=php-fpm.d/*.conf\n",
            BASELINE.replace(b"pm = dynamic", b"pm = static"),
            BASELINE.replace(b"pm.max_children = 50", b"pm.max_children"),
        )
        for invalid in invalids:
            with self.subTest(invalid=invalid[:32]):
                self.config.write_bytes(invalid)
                with self.assertRaises(manual.FpmApplyError):
                    self.plan()
        self.config.write_bytes(BASELINE)

    def test_unsafe_file_and_symlink_refused(self):
        self.config.unlink()
        target = self.config_dir / "elsewhere"
        target.write_bytes(BASELINE)
        self.config.symlink_to(target)
        with self.assertRaises((OSError, manual.FpmApplyError)):
            self.plan()
        self.config.unlink()
        os.link(target, self.config)
        with self.assertRaises(manual.FpmApplyError):
            self.plan()

    def test_validation_failure_after_write_restores_original(self):
        count = 0
        def validate():
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("simulated candidate test failure")
        def activate():
            self.events.append("reload")
        def verify():
            self.events.append("verify")
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply(hooks=(validate, activate, verify))
        self.assertEqual(caught.exception.stage, "apply")
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertFalse((self.data / manual.JOURNAL).exists())
        self.assertFalse((self.data / manual.SNAPSHOT).exists())
        self.assertEqual(count, 3)
        self.assertEqual(self.events, ["reload", "verify"])

    def test_forward_runtime_mismatch_requires_distinct_baseline_verification(self):
        expected=self.plan()["after_sha256"]
        calls=[]
        def forward_verify():
            calls.append("forward")
            self.assertEqual(manual._sha(self.config.read_bytes()), expected)
            raise ValueError("Simulated post-reload PHP failure")
        def baseline_verify():
            calls.append("restored")
            self.assertEqual(self.config.read_bytes(), BASELINE)
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply(hooks=(lambda: None, lambda: None, forward_verify),
                       verify_restored=baseline_verify)
        self.assertEqual(caught.exception.stage,"apply")
        self.assertEqual(calls,["forward","restored"])
        self.assertEqual(self.config.read_bytes(),BASELINE)
        self.assertFalse((self.data/manual.JOURNAL).exists())
        self.assertFalse((self.data/manual.SNAPSHOT).exists())

    def test_apply_rejects_missing_baseline_verifier_before_any_recovery_files(self):
        plan=self.plan()
        with self.assertRaises(manual.FpmApplyError) as caught:
            manual.apply(self.root/"php",self.data,"85",DESIRED,
                expected_before=plan["before_sha256"],
                expected_after=plan["after_sha256"],
                validate=lambda:None,activate=lambda:None,verify=lambda:None,
                verify_restored=None)
        self.assertEqual(caught.exception.stage,"validation")
        self.assertEqual(list(self.data.iterdir()),[])

    def test_crash_or_failed_recovery_is_not_silently_claimed(self):
        def fail_reload():
            raise RuntimeError("versioned service refused to reload")
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply(hooks=(lambda: None, fail_reload, lambda: None))
        self.assertEqual(caught.exception.stage, "uncertain")
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertTrue((self.data / manual.JOURNAL).exists())
        fd = manual._dir(self.data)
        try:
            record = manual._read_journal(fd)
        finally:
            os.close(fd)
        self.assertEqual(record["phase"], "uncertain")
        # The journal remains recoverable; a verified operator rollback clears it.
        done = manual.rollback(
            self.root / "php", self.data, "85", record["operation_id"],
            validate=lambda: None, activate=lambda: None, verify=lambda: None,
            prewrite_check=lambda: None)
        self.assertEqual(done["state"], "Rolled Back")
        self.assertFalse((self.data / manual.JOURNAL).exists())

    def test_rollback_prewrite_check_is_mandatory_and_refusal_preserves_journal(self):
        result = self.apply()
        applied = self.config.read_bytes()
        for check in (None, lambda: (_ for _ in ()).throw(
                manual.FpmApplyError("fpm_conflict", "site reassigned"))):
            with self.assertRaises(manual.FpmApplyError):
                manual.rollback(self.root / "php", self.data, "85", result["operation_id"],
                                validate=lambda: None, activate=lambda: None,
                                verify=lambda: None, prewrite_check=check)
            self.assertEqual(self.config.read_bytes(), applied)
            self.assertTrue((self.data / manual.JOURNAL).exists())
            self.assertTrue((self.data / manual.SNAPSHOT).exists())

    def test_recovery_status_reports_file_ownership_and_conflict(self):
        self.assertEqual(manual.recovery_status(self.root / "php", self.data, "85")["state"], "No Recovery")
        self.assertEqual(list(self.data.iterdir()), [], "read-only recovery status created a file")
        result = self.apply()
        status = manual.recovery_status(self.root / "php", self.data, "85")
        self.assertEqual(status["state"], "Applied")
        self.assertEqual(status["phase"], "applied")
        self.assertEqual(status["operation_id"], result["operation_id"])
        self.assertTrue(status["safe_rollback_file_match"])
        self.config.write_bytes(self.config.read_bytes() + b"; other writer\n")
        changed = manual.recovery_status(self.root / "php", self.data, "85")
        self.assertEqual(changed["state"], "Needs Review")
        self.assertFalse(changed["safe_rollback_file_match"])

    def test_unpaired_recovery_artifact_never_looks_empty(self):
        (self.data / manual.SNAPSHOT).write_bytes(BASELINE)
        (self.data / manual.SNAPSHOT).chmod(0o600)
        with self.assertRaises(manual.FpmApplyError) as caught:
            manual.recovery_status(self.root / "php", self.data, "85")
        self.assertEqual(caught.exception.stage, "recovery")

    def test_concurrent_external_mutation_blocks_rollback(self):
        result = self.apply()
        contents = self.config.read_bytes()
        self.config.write_bytes(contents + b"; external change\n")
        with self.assertRaises(manual.FpmApplyError) as caught:
            manual.rollback(self.root / "php", self.data, "85", result["operation_id"],
                            validate=lambda: None, activate=lambda: None, verify=lambda: None,
                            prewrite_check=lambda: None)
        self.assertEqual(caught.exception.stage, "conflict")
        self.assertTrue((self.data / manual.SNAPSHOT).is_file())
        self.assertEqual(self.config.read_bytes(), contents + b"; external change\n")
        with self.assertRaises(manual.FpmApplyError) as pending:
            self.apply()
        self.assertEqual(pending.exception.stage, "recovery")

    def test_preflight_failure_cleans_owned_snapshot_and_journal(self):
        def reject():
            raise ValueError("synthetic preflight syntax failure")
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply(hooks=(reject, lambda: None, lambda: None))
        self.assertEqual(caught.exception.stage, "apply")
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertFalse((self.data / manual.JOURNAL).exists())
        self.assertFalse((self.data / manual.SNAPSHOT).exists())

    def test_post_rename_exception_is_recovered_not_misclassified(self):
        real_replace = manual._replace
        count = 0
        def fail_after_commit(*args, **kwargs):
            nonlocal count
            count += 1
            result = real_replace(*args, **kwargs)
            if count == 1:
                raise OSError("simulated directory fsync failure after rename")
            return result
        with patch.object(manual, "_replace", side_effect=fail_after_commit):
            with self.assertRaises(manual.FpmApplyError) as caught:
                self.apply()
        self.assertEqual(caught.exception.stage, "apply")
        self.assertEqual(count, 2)
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertFalse((self.data / manual.JOURNAL).exists())
        self.assertFalse((self.data / manual.SNAPSHOT).exists())
        self.assertEqual(self.events, ["validate", "validate", "activate", "verify"])

    def test_corrupted_recovery_journal_fails_closed(self):
        (self.data / manual.JOURNAL).write_text('{"schema":1}', encoding="utf-8")
        (self.data / manual.JOURNAL).chmod(0o600)
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply()
        self.assertEqual(caught.exception.stage, "recovery")
        self.assertEqual(self.config.read_bytes(), BASELINE)

    def test_current_auto_journal_requires_exact_event_token(self):
        record = {
            "schema": 2, "operation_id": "a" * 32, "version": "85",
            "phase": "prepared", "before_sha256": "b" * 64,
            "after_sha256": "c" * 64, "timestamp": 1,
            "owner": "auto", "policy_sha256": "d" * 64,
            "event_token": "e" * 64,
        }
        fd = manual._dir(self.data)
        try:
            manual._persist_journal(fd, record)
            self.assertEqual(manual._read_journal(fd, "85"), record)
            # Old QA schema-2 without a witnessed event is not a current
            # automatic operation and cannot authorize recovery.
            previous = dict(record)
            previous.pop("event_token")
            manual._persist_journal(fd, previous)
            with self.assertRaises(manual.FpmApplyError) as err:
                manual._read_journal(fd, "85")
            self.assertEqual(err.exception.stage, "recovery")
        finally:
            os.close(fd)

    def test_extended_attributes_are_refused_before_modifying_config(self):
        if not hasattr(os, "setxattr"):
            self.skipTest("extended attributes unsupported")
        try:
            os.setxattr(self.config, "user.ach_test_only", b"fixture")
        except OSError:
            self.skipTest("test filesystem does not permit user extended attributes")
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.plan()
        self.assertEqual(caught.exception.stage, "compatibility")
        self.assertEqual(self.config.read_bytes(), BASELINE)

    def test_missing_checks_and_root_directory_violation_rejected(self):
        with self.assertRaises(manual.FpmApplyError):
            self.apply(hooks=(None, lambda: None, lambda: None))
        self.data.chmod(0o777)
        with self.assertRaises(manual.FpmApplyError) as caught:
            self.apply()
        self.assertEqual(caught.exception.stage, "ownership")
        self.assertEqual(self.config.read_bytes(), BASELINE)

    def test_foreign_operation_id_cannot_recover(self):
        result = self.apply()
        with self.assertRaises(manual.FpmApplyError):
            manual.rollback(self.root / "php", self.data, "85", "deadbeef" * 4,
                            validate=lambda: None, activate=lambda: None, verify=lambda: None,
                            prewrite_check=lambda: None)
        self.assertNotEqual(self.config.read_bytes(), BASELINE)
        self.assertTrue((self.data / manual.SNAPSHOT).is_file())


    def test_php81_and_php85_have_independent_recovery_and_cross_version_denial(self):
        php81 = self.root / "php" / "81" / "etc"
        php81.mkdir(parents=True)
        config81 = php81 / "php-fpm.conf"
        base81 = BASELINE.replace(b"/tmp/test-fpm.sock", b"/tmp/php-cgi-81.sock").replace(b"/tmp/fpm-test.pid", str(self.root / "php" / "81" / "var/run/php-fpm.pid").encode())
        config81.write_bytes(base81)
        config81.chmod(0o644)
        plan81 = manual.preview(self.root / "php", "81", DESIRED)
        self.assertEqual(plan81["version"], "81")
        changed81 = manual.apply(
            self.root / "php", self.data, "81", DESIRED,
            expected_before=plan81["before_sha256"],
            expected_after=plan81["after_sha256"],
            validate=lambda: None, activate=lambda: None,
            verify=lambda: self.assertEqual(
                preview_php_fpm(self.root / "php", "81", DESIRED)["state"], "File Match"),
            verify_restored=lambda: self.assertEqual(config81.read_bytes(), base81))
        self.assertEqual(changed81["state"], "Applied")
        self.assertFalse((self.data / manual.JOURNAL).exists())
        self.assertFalse((self.data / manual.SNAPSHOT).exists())
        journal81, snapshot81 = manual._recovery_names("81")
        self.assertEqual((self.data / snapshot81).read_bytes(), base81)
        self.assertEqual(manual.recovery_status(
            self.root / "php", self.data, "81")["state"], "Applied")
        self.assertEqual(manual.recovery_status(
            self.root / "php", self.data, "85")["state"], "No Recovery")

        changed85 = self.apply()
        self.assertTrue((self.data / manual.JOURNAL).is_file())
        self.assertTrue((self.data / journal81).is_file())
        with self.assertRaisesRegex(manual.FpmApplyError, "matching active"):
            manual.rollback(
                self.root / "php", self.data, "81", changed85["operation_id"],
                validate=lambda: None, activate=lambda: None, verify=lambda: None,
                prewrite_check=lambda: None)
        with self.assertRaisesRegex(manual.FpmApplyError, "matching active"):
            manual.rollback(
                self.root / "php", self.data, "85", changed81["operation_id"],
                validate=lambda: None, activate=lambda: None, verify=lambda: None,
                prewrite_check=lambda: None)

        manual.rollback(
            self.root / "php", self.data, "85", changed85["operation_id"],
            validate=lambda: None, activate=lambda: None, verify=lambda: None,
            prewrite_check=lambda: None)
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertEqual(manual.recovery_status(
            self.root / "php", self.data, "81")["state"], "Applied")
        manual.rollback(
            self.root / "php", self.data, "81", changed81["operation_id"],
            validate=lambda: None, activate=lambda: None,
            verify=lambda: self.assertEqual(config81.read_bytes(), base81),
            prewrite_check=lambda: None)
        self.assertEqual(config81.read_bytes(), base81)
        self.assertFalse((self.data / journal81).exists())
        self.assertFalse((self.data / snapshot81).exists())
        self.assertEqual(manual.recovery_status(
            self.root / "php", self.data, "85")["state"], "No Recovery")

    def test_php81_rejects_nonconventional_pid_or_socket_before_backup_or_reload(self):
        php81 = self.root / "php" / "81" / "etc"
        php81.mkdir(parents=True)
        source = php81 / "php-fpm.conf"
        standard = (BASELINE.replace(
            b"/tmp/test-fpm.sock", b"/tmp/php-cgi-81.sock"
        ).replace(
            b"/tmp/fpm-test.pid",
            str(self.root / "php" / "81" / "var/run/php-fpm.pid").encode()
        ))
        source.write_bytes(standard)
        source.chmod(0o644)
        approved = manual.preview(self.root / "php", "81", DESIRED)
        self.assertEqual(approved["version"], "81")
        for wrong in (
            standard.replace(b"/tmp/php-cgi-81.sock", b"/tmp/other-81.sock"),
            standard.replace(b"var/run/php-fpm.pid", b"var/run/custom.pid"),
            standard.replace(b"listen = /tmp/php-cgi-81.sock",
                             b"listen = /tmp/other-81.sock\nlisten = /tmp/php-cgi-81.sock"),
            standard.replace(b"pid = ", b"pid = /tmp/another.pid\npid = "),
            standard.replace(b"/tmp/php-cgi-81.sock", b"/tmp/other-81.sock # /tmp/php-cgi-81.sock"),
        ):
            with self.subTest(wrong=wrong[-80:]):
                source.write_bytes(wrong)
                with self.assertRaisesRegex(manual.FpmApplyError, "native service layout"):
                    manual.preview(self.root / "php", "81", DESIRED)
                with self.assertRaisesRegex(manual.FpmApplyError, "native service layout"):
                    manual.apply(
                        self.root / "php", self.data, "81", DESIRED,
                        expected_before=approved["before_sha256"],
                        expected_after=approved["after_sha256"],
                        validate=self.hooks()[0], activate=self.hooks()[1],
                        verify=self.hooks()[2],
                        verify_restored=self.hooks()[2],
                    )
                self.assertEqual(self.events, [], "Runtime hooks ran before layout compatibility")
                self.assertEqual(source.read_bytes(), wrong)
                journal, snapshot = manual._recovery_names("81")
                self.assertFalse((self.data / journal).exists())
                self.assertFalse((self.data / snapshot).exists())
        source.write_bytes(standard)
        self.assertEqual(manual.preview(self.root / "php", "81", DESIRED),
                         approved)

    def test_php81_conventional_runtime_paths_allow_native_comments_only(self):
        root = self.root / "php"
        standard = (
            b"[global]\n" +
            ("pid = " + str(root / "81/var/run/php-fpm.pid")).encode() +
            b" ; native service\n"
            b"[www]\nlisten = /tmp/php-cgi-81.sock # native socket\n"
        )
        manual.require_native_runtime_paths(root, "81", standard)
        invalid_sources = (
            standard.replace(b"pid = ", b"pid = /tmp/unrelated.pid\npid = ", 1),
            standard.replace(b"listen = ", b"listen = /tmp/other.sock\nlisten = ", 1),
        )
        for invalid in invalid_sources:
            with self.assertRaises(manual.FpmApplyError):
                manual.require_native_runtime_paths(root, "81", invalid)

    def test_php81_runtime_failure_restores_exact_original_and_does_not_touch_php85(self):
        php81 = self.root / "php" / "81" / "etc"
        php81.mkdir(parents=True)
        config81 = php81 / "php-fpm.conf"
        before = BASELINE.replace(b"/tmp/test-fpm.sock", b"/tmp/php-cgi-81.sock").replace(b"/tmp/fpm-test.pid", str(self.root / "php" / "81" / "var/run/php-fpm.pid").encode())
        config81.write_bytes(before)
        config81.chmod(0o644)
        plan = manual.preview(self.root / "php", "81", DESIRED)
        with self.assertRaises(manual.FpmApplyError) as ctx:
            manual.apply(
                self.root / "php", self.data, "81", DESIRED,
                expected_before=plan["before_sha256"],
                expected_after=plan["after_sha256"],
                validate=lambda: None, activate=lambda: None,
                verify=lambda: (_ for _ in ()).throw(RuntimeError("fault after reload")),
                verify_restored=lambda: self.assertEqual(config81.read_bytes(), before))
        self.assertEqual(ctx.exception.stage, "apply")
        self.assertEqual(config81.read_bytes(), before)
        self.assertEqual(self.config.read_bytes(), BASELINE)
        self.assertFalse(any(x.name.startswith("ach_customizer.fpm81.recovery")
                             for x in self.data.iterdir()))


if __name__ == "__main__":
    unittest.main()
