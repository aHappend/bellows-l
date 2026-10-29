#!/usr/bin/env python3
"""Synthetic retention and HIL regressions, not product verification.

Run: python3 -B tests/test_preparation.py
No transport commands are executed and no hardware acceptance is established.
"""

import copy
from contextlib import chdir, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparation import (audit_artifacts, audit_bundle, audit_receipt, diagnose_hil_record,
                         inspect_hil_inputs, inspect_portable_inputs, main,
                         stage_portable_root)
from verify import file_integrity, json_write


class PortableRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("rtl/example.sv", "bellows_l1_reference/rtl/example.sv",
                     "tests/example.py", "design/SPEC.md", "design/ARCHITECTURE.md"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic declared input\n")
        self.outputs = (
            "evidence/l1",
            "evidence/l1-post-settlement-bundle-audit",
            "evidence/l1-post-settlement-bundle-audit-after-0621",
        )
        guard = patch("subprocess.Popen", side_effect=AssertionError(
            "Portable preflight and staging must not execute checks"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_preflight_accounts_for_every_admitted_output(self):
        report = inspect_portable_inputs(reference=self.root)
        self.assertTrue(report["portable_preflight_passed"], report["errors"])
        self.assertEqual([entry["path"] for entry in report["outputs"]],
                         list(self.outputs))
        self.assertTrue(all(entry["fresh"] for entry in report["outputs"]))
        self.assertFalse(report["authorizes_resumption"])

    def test_each_occupied_mandatory_output_is_preserved_and_rejected(self):
        for destination in self.outputs:
            with self.subTest(destination=destination):
                path = self.root / destination
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"historical output; preserve verbatim")
                report = inspect_portable_inputs(reference=self.root)
                self.assertFalse(report["portable_preflight_passed"])
                self.assertTrue(any("Refusing occupied output destination" in error
                                    for error in report["errors"]))
                self.assertEqual(path.read_bytes(), b"historical output; preserve verbatim")
                path.unlink()

    def test_non_directory_output_ancestor_is_preserved_and_rejected(self):
        ancestor = self.root / "evidence"
        ancestor.write_bytes(b"historical file; not an output directory")
        report = inspect_portable_inputs(reference=self.root)
        self.assertTrue(report["current_sources_match"])
        self.assertFalse(report["portable_preflight_passed"])
        self.assertEqual(len(report["outputs"]), len(self.outputs))
        self.assertEqual(
            sum("Refusing non-directory output parent" in error
                for error in report["errors"]), len(self.outputs))
        self.assertEqual(ancestor.read_bytes(),
                         b"historical file; not an output directory")

    def test_staging_retains_all_three_unchanged_commands_in_order(self):
        record = stage_portable_root("evidence/fresh/project", reference=self.root)
        expected = [["python3", "tests/verify.py", "--output", "evidence/l1"]]
        for destination in self.outputs[1:]:
            expected.append([
                "sh", "-c",
                f"mkdir {destination} && python3 tests/preparation.py "
                f"--audit-bundles evidence/l1 > {destination}/stdout.json 2> "
                f"{destination}/stderr.log"])
        self.assertEqual(record["mandatory_commands"], expected)
        self.assertTrue(record["preflight"]["portable_preflight_passed"])
        self.assertFalse(record["checks_executed"])
        self.assertFalse(record["hardware_executed"])
        self.assertFalse(record["acceptance_evidence"])
        for destination in self.outputs:
            self.assertFalse((self.root / "evidence/fresh/project" / destination).exists())

    def test_staging_synchronizes_sources_before_success_receipt(self):
        synchronized_files = set()
        real_fsync = os.fsync
        root = self.root / "evidence/durable/project"
        published = []

        def observe_fsync(descriptor):
            identity = os.fstat(descriptor)
            synchronized_files.add((identity.st_dev, identity.st_ino))
            real_fsync(descriptor)

        def publish_receipt(path, record):
            self.assertTrue(record["source_durability_completed"])
            for name in record["source_sha256"]:
                identity = (root / name).stat()
                self.assertIn((identity.st_dev, identity.st_ino), synchronized_files)
            for path_to_sync in (
                    root, *root.parents[:3], root / "rtl", root / "tests",
                    root / "design", root / "bellows_l1_reference",
                    root / "bellows_l1_reference/rtl",
                    root / "staging.stdout.log", root / "staging.stderr.log"):
                identity = path_to_sync.stat()
                self.assertIn((identity.st_dev, identity.st_ino), synchronized_files)
            published.append(path)
            json_write(path, record)

        with patch("preparation.os.fsync", side_effect=observe_fsync), patch(
                "preparation.json_write", side_effect=publish_receipt):
            record = stage_portable_root("evidence/durable/project", reference=self.root)
        self.assertEqual(published, [root / "staging-receipt.json"])
        for name in record["source_sha256"]:
            with self.subTest(source=name):
                identity = (root / name).stat()
                self.assertIn((identity.st_dev, identity.st_ino), synchronized_files)
        self.assertTrue(record["source_durability_completed"])
        self.assertEqual(record["source_files_synchronized"],
                         len(record["source_sha256"]))

    def test_staging_sync_failure_preserves_failed_receipt_without_success(self):
        real_fsync = os.fsync
        attempted = False

        def fail_first_sync(descriptor):
            nonlocal attempted
            if not attempted:
                attempted = True
                raise OSError("synthetic staged-source synchronization failure")
            real_fsync(descriptor)

        with patch("preparation.os.fsync", side_effect=fail_first_sync):
            with self.assertRaisesRegex(ValueError, "synchronization failure"):
                stage_portable_root("evidence/sync-failed/project", reference=self.root)
        root = self.root / "evidence/sync-failed/project"
        record = json.loads((root / "staging-receipt.json").read_text())
        self.assertEqual(record["exit_code"], 1)
        self.assertFalse(record["source_durability_completed"])
        self.assertFalse(record["checks_executed"])
        self.assertFalse(record["hardware_executed"])
        self.assertEqual((root / "staging.stdout.log").read_bytes(), b"")
        self.assertIn("synchronization failure",
                      (root / "staging.stderr.log").read_text())

    def test_staging_directory_sync_failure_is_not_a_successful_preflight(self):
        with patch("preparation.sync_directory", side_effect=OSError(
                "synthetic directory synchronization failure")):
            with self.assertRaisesRegex(ValueError, "directory synchronization failure"):
                stage_portable_root("evidence/directory-failed/project", reference=self.root)
        root = self.root / "evidence/directory-failed/project"
        record = json.loads((root / "staging-receipt.json").read_text())
        self.assertEqual(record["exit_code"], 1)
        self.assertEqual(record["source_files_synchronized"], 5)
        self.assertFalse(record["source_durability_completed"])
        self.assertNotIn("preflight", record)
        self.assertEqual((root / "staging.stdout.log").read_bytes(), b"")


class ArtifactRetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = Path("evidence/synthetic")
        self.base = self.root / self.bundle
        self.base.mkdir(parents=True)
        guard = patch("preparation.ROOT", self.root)
        guard.start()
        self.addCleanup(guard.stop)
        guard = patch("subprocess.Popen", side_effect=AssertionError(
            "Retention audits must not execute or regenerate artifacts"))
        guard.start()
        self.addCleanup(guard.stop)

    def artifact(self, name, payload=b"retained original bytes"):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path.relative_to(self.root).as_posix(), file_integrity(path)

    def test_complete_inventory_rechecks_every_bound_file(self):
        bindings = dict([self.artifact("stdout.log"), self.artifact("obj/model.o")])
        report = audit_artifacts(self.bundle, bindings)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["expected_files"], 2)
        self.assertEqual(report["checked_files"], 2)
        self.assertEqual(report["rechecked_files"], 2)
        self.assertTrue(report["inventory_stable"])

    def test_absent_bundle_routes_to_platform_without_authorizing_replay(self):
        with chdir(self.root):
            report = audit_bundle("evidence/absent")
        handoff = report["retention_handoff"]
        self.assertFalse(report["retained_files_readable"])
        self.assertEqual(handoff["prerequisite_owner"], "shared-runtime platform owner")
        self.assertEqual(handoff["artifact_availability"], "unestablished")
        self.assertIsNone(handoff["missing_bytes"])
        self.assertFalse(handoff["authorizes_staging"])
        self.assertFalse(handoff["authorizes_resumption"])
        self.assertFalse((self.root / "evidence/absent").exists())

    def test_bundle_handoff_preserves_loss_inventory_and_source_uncertainty(self):
        name, binding = self.artifact("obj/model.o")
        (self.root / name).unlink()
        receipt = self.base / "receipt.json"
        receipt.write_text(json.dumps(dict(
            kind="portable-verifier", artifact_integrity={name: binding})))
        before = receipt.read_bytes()
        with chdir(self.root):
            report = audit_bundle(self.bundle.as_posix())
        handoff = report["retention_handoff"]
        self.assertEqual(handoff["artifact_availability"], "incomplete_or_invalid")
        self.assertEqual(handoff["missing_artifact_bindings"], {name: binding})
        self.assertEqual(handoff["missing_bytes"], binding["bytes"])
        self.assertIsNone(handoff["current_sources_match"])
        self.assertFalse(handoff["platform_retention_remedy_established"])
        self.assertFalse(handoff["post_settlement_retention_established"])
        self.assertFalse(handoff["authorizes_resumption"])
        self.assertEqual(receipt.read_bytes(), before)
        self.assertFalse((self.root / name).exists())

    def test_complete_artifact_observation_does_not_certify_platform_remedy(self):
        name, binding = self.artifact("trace.log")
        (self.base / "receipt.json").write_text(json.dumps(dict(
            kind="portable-verifier", artifact_integrity={name: binding})))
        with chdir(self.root):
            report = audit_bundle(self.bundle.as_posix())
        handoff = report["retention_handoff"]
        self.assertEqual(handoff["artifact_availability"], "complete_at_observation")
        self.assertEqual(handoff["missing_bytes"], 0)
        self.assertFalse(handoff["platform_retention_remedy_established"])
        self.assertFalse(handoff["post_settlement_retention_established"])
        self.assertFalse(handoff["authorizes_staging"])
        self.assertFalse(handoff["authorizes_resumption"])
        self.assertFalse(report["retained_files_readable"])

    def test_missing_compiler_intermediates_are_not_exempted_or_regenerated(self):
        bindings = dict(self.artifact(f"obj/file-{index}.o") for index in range(299))
        for name in bindings:
            (self.root / name).unlink()
        report = audit_artifacts(self.bundle, bindings)
        self.assertEqual(report["expected_files"], 299)
        self.assertEqual(report["checked_files"], 0)
        self.assertEqual(set(report["missing_files"]), set(bindings))
        self.assertEqual(len(report["errors"]), 299)
        self.assertEqual(report["missing_artifact_bindings"], bindings)
        self.assertEqual(report["missing_bytes"],
                         sum(binding["bytes"] for binding in bindings.values()))
        self.assertEqual(report["missing_by_directory"], {
            "obj": dict(files=299, bytes=report["missing_bytes"])})
        self.assertEqual(list(self.base.rglob("*.o")), [])

    def test_missing_inventory_preserves_exact_bindings_across_directories(self):
        bindings = dict([
            self.artifact("matrix/obj/model.o", b"object"),
            self.artifact("matrix/obj/model.d", b""),
            self.artifact("reproduction/run.log", b"raw log")])
        retained, retained_binding = self.artifact("retained.log")
        for name in bindings:
            (self.root / name).unlink()
        report = audit_artifacts(self.bundle, {
            **bindings, retained: retained_binding})
        self.assertEqual(report["missing_artifact_bindings"], bindings)
        self.assertEqual(report["missing_bytes"], 13)
        self.assertEqual(report["missing_by_directory"], {
            "matrix/obj": dict(files=2, bytes=6),
            "reproduction": dict(files=1, bytes=7)})
        self.assertEqual(report["checked_files"], 1)
        self.assertTrue(report["errors"])

    def test_invalid_missing_binding_does_not_enter_recovery_inventory(self):
        name, binding = self.artifact("model.o")
        (self.root / name).unlink()
        for invalid in (dict(binding, bytes=True), dict(binding, sha256="invalid")):
            with self.subTest(binding=invalid):
                report = audit_artifacts(self.bundle, {name: invalid})
                self.assertTrue(report["errors"])
                self.assertEqual(report["missing_artifact_bindings"], {})
                self.assertEqual(report["missing_bytes"], 0)
                self.assertEqual(report["missing_by_directory"], {})

    def test_same_size_corruption_and_unbound_files_both_fail(self):
        name, binding = self.artifact("trace.log", b"original")
        (self.root / name).write_bytes(b"modified")
        extra, _ = self.artifact("unexpected.log")
        report = audit_artifacts(self.bundle, {name: binding})
        self.assertEqual(report["mismatched_files"], [name])
        self.assertEqual(report["unbound_files"], [extra])
        self.assertTrue(report["errors"])

    def test_disappearance_after_initial_hash_fails_recheck(self):
        name, binding = self.artifact("trace.log")

        def disappear_after_read(path):
            result = file_integrity(path)
            path.unlink()
            return result

        with patch("preparation.file_integrity", side_effect=disappear_after_read):
            report = audit_artifacts(self.bundle, {name: binding})
        self.assertEqual(report["checked_files"], 1)
        self.assertEqual(report["rechecked_files"], 0)
        self.assertFalse(report["inventory_stable"])
        self.assertEqual(report["missing_files"], [name])
        self.assertEqual(report["missing_artifact_bindings"], {name: binding})
        self.assertEqual(report["missing_bytes"], binding["bytes"])
        self.assertTrue(report["errors"])

    def test_same_bytes_symlink_substitution_is_not_retained_original(self):
        for directory_link in (False, True):
            with self.subTest(directory_link=directory_link):
                original = self.base / "original"
                original.mkdir(exist_ok=True)
                target = original / "trace.log"
                target.write_bytes(b"identical bytes")
                if directory_link:
                    link = self.base / "redirect"
                    link.symlink_to(original, target_is_directory=True)
                    name = (link / "trace.log").relative_to(self.root).as_posix()
                else:
                    link = self.base / "redirect.log"
                    link.symlink_to(target)
                    name = link.relative_to(self.root).as_posix()
                report = audit_artifacts(self.bundle, {
                    target.relative_to(self.root).as_posix(): file_integrity(target),
                    name: file_integrity(target)})
                self.assertTrue(any("symlink" in error.lower()
                                    for error in report["errors"]), report)
                self.assertEqual(target.read_bytes(), b"identical bytes")
                link.unlink()

    def test_bundle_directory_symlink_is_rejected(self):
        name, binding = self.artifact("trace.log")
        moved = self.root / "evidence/original"
        self.base.rename(moved)
        self.base.symlink_to(moved, target_is_directory=True)
        report = audit_artifacts(self.bundle, {name: binding})
        self.assertTrue(any("symlink" in error.lower()
                            for error in report["errors"]), report)

    def test_symlink_introduced_after_initial_hash_fails_recheck(self):
        name, binding = self.artifact("trace.log")
        target_name, target_binding = self.artifact("original.log")
        changed = False

        def redirect_after_read(path):
            nonlocal changed
            result = file_integrity(path)
            if path == self.root / name and not changed:
                path.unlink()
                path.symlink_to(self.root / target_name)
                changed = True
            return result

        with patch("preparation.file_integrity", side_effect=redirect_after_read):
            report = audit_artifacts(self.bundle, {
                name: binding, target_name: target_binding})
        self.assertTrue(changed)
        self.assertTrue(any("symlink" in error.lower()
                            for error in report["errors"]), report)


class ReceiptOutcomeTests(unittest.TestCase):
    def audit(self, **metadata):
        record = dict(argv=["synthetic-never-execute"], cwd=".",
                      exit_code=0, timed_out=False, source_sha256={},
                      tool_versions={}, stdout="evidence/synthetic/stdout.log",
                      stderr="evidence/synthetic/stderr.log")
        record.update(metadata)
        with patch("preparation.repair_receipt", return_value="synthetic-digest"), \
                patch("preparation.source_binding_errors", return_value=[]), \
                patch.object(Path, "read_bytes",
                             return_value=json.dumps(record).encode()), \
                patch("subprocess.Popen", side_effect=AssertionError(
                    "Receipt diagnosis must not launch commands")):
            return audit_receipt("evidence/synthetic/receipt.json")

    def test_false_valued_launch_errors_are_invalid_not_success(self):
        for value in ("", False, 0, [], {}):
            with self.subTest(launch_error=value):
                result = self.audit(launch_error=value)
                self.assertTrue(result["available"])
                self.assertEqual(result["recorded_execution"]["outcome"],
                                 "invalid-result")

    def test_nonempty_launch_error_is_failed_not_success(self):
        result = self.audit(launch_error="Synthetic executable unavailable")
        self.assertEqual(result["recorded_execution"]["outcome"], "launch-failed")

    def test_absent_or_null_launch_error_preserves_success(self):
        for metadata in ({}, dict(launch_error=None)):
            with self.subTest(metadata=metadata):
                result = self.audit(**metadata)
                self.assertEqual(result["recorded_execution"]["outcome"], "succeeded")

    def test_timeout_and_exit_outcomes_remain_distinct(self):
        for metadata, expected in (
                (dict(timed_out=True), "timed-out"),
                (dict(timed_out=0), "invalid-result"),
                (dict(exit_code=False), "invalid-result"),
                (dict(exit_code=None), "unsettled"),
                (dict(exit_code=1), "failed")):
            with self.subTest(metadata=metadata):
                result = self.audit(**metadata)
                self.assertEqual(result["recorded_execution"]["outcome"], expected)


class HilDiagnosticTests(unittest.TestCase):
    def setUp(self):
        guard = patch("subprocess.Popen", side_effect=AssertionError(
            "Read-only diagnostics must not launch hardware or other commands"))
        self.addCleanup(guard.stop)
        guard.start()
        self.record = dict(
            gate="board-hil", status="passed", deterministic_across_runs=True,
            runs=[dict(run_index=index, exit_code=0, passed=True,
                       stdout="Read register 57 (0x00000039): 178 (0x000000b2)\n",
                       stderr="") for index in (1, 2, 3)])

    def inspect_config(self, config, **kwargs):
        with patch.object(Path, "read_bytes",
                          return_value=json.dumps(config).encode()):
            return inspect_hil_inputs(**kwargs)

    def invoke_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["tests/preparation.py", *arguments]), \
                patch("preparation.os.chdir"), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = main()
        self.assertEqual(stderr.getvalue(), "")
        return code, json.loads(stdout.getvalue())

    def test_cli_missing_configuration_fails_without_executing_commands(self):
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError(
                "Synthetic missing fpga/board_hil.json")):
            code, result = self.invoke_cli("--inspect-hil-inputs")
        self.assertEqual(code, 1)
        self.assertFalse(result["product_command_configured"])
        self.assertFalse(result["authorizes_resumption"])
        self.assertTrue(result["errors"])

    def test_cli_configured_command_is_only_an_inventory_success(self):
        with patch.object(Path, "read_bytes", return_value=json.dumps(dict(
                remote_test_cmd="synthetic-never-execute")).encode()):
            code, result = self.invoke_cli("--inspect-hil-inputs")
        self.assertEqual(code, 0)
        self.assertTrue(result["product_command_configured"])
        self.assertFalse(result["hardware_executed"])
        self.assertFalse(result["acceptance_evidence"])
        self.assertFalse(result["authorizes_resumption"])

    def test_cli_invalid_configuration_reports_failure(self):
        for payload in (b"{", b"[]", b'{"remote_test_cmd": ""}'):
            with self.subTest(payload=payload), \
                    patch.object(Path, "read_bytes", return_value=payload):
                code, result = self.invoke_cli("--inspect-hil-inputs")
                self.assertEqual(code, 1)
                self.assertTrue(result["errors"])
                self.assertFalse(result["hardware_executed"])

    def test_cli_register_only_receipt_never_grants_acceptance(self):
        with patch.object(Path, "read_bytes",
                          return_value=json.dumps(self.record).encode()):
            code, result = self.invoke_cli(
                "--inspect-hil-receipt", "evidence/synthetic-hil.json")
        self.assertEqual(code, 0)
        self.assertEqual(result["register_only_runs"], 3)
        self.assertTrue(result["native_execution_diagnostic"][
            "three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])
        self.assertFalse(result["authorizes_resumption"])

    def test_cli_unknown_output_is_not_inferred_to_be_product_comparisons(self):
        record = copy.deepcopy(self.record)
        for run in record["runs"]:
            run["stdout"] = "PASS complete BELLOWS traffic\n"
        with patch.object(Path, "read_bytes",
                          return_value=json.dumps(record).encode()):
            code, result = self.invoke_cli(
                "--inspect-hil-receipt", "evidence/synthetic-hil.json")
        self.assertEqual(code, 0)
        self.assertEqual(result["register_only_runs"], 0)
        self.assertTrue(all(run["traffic_comparisons"] == "unestablished"
                            for run in result["runs"]))
        self.assertFalse(result["physical_acceptance_established"])

    def test_cli_missing_raw_receipt_stream_is_an_error(self):
        record = copy.deepcopy(self.record)
        del record["runs"][1]["stderr"]
        with patch.object(Path, "read_bytes",
                          return_value=json.dumps(record).encode()):
            code, result = self.invoke_cli(
                "--inspect-hil-receipt", "evidence/synthetic-hil.json")
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])
        self.assertFalse(result["physical_acceptance_established"])

    def test_missing_configuration_preserves_prerequisite_handoff(self):
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError(
                "Synthetic missing fpga/board_hil.json")):
            result = inspect_hil_inputs()
        self.assertFalse(result["product_command_configured"])
        self.assertTrue(result["errors"])
        handoff = result["coordinator_handoff"]
        self.assertEqual({item["name"] for item in handoff["required_inputs"]},
                         {"nondeploying_invocation", "stream_status_protocol",
                          "programmed_image_binding", "independent_admission"})
        for field in ("portable_rerun_resolves_gap", "designer_repair_justified",
                      "authorizes_adapter_implementation",
                      "authorizes_hardware_execution"):
            self.assertIs(handoff[field], False, field)

    def test_configured_command_is_not_permission_or_acceptance(self):
        result = self.inspect_config(dict(remote_test_cmd="synthetic-never-execute"))
        self.assertTrue(result["product_command_configured"])
        self.assertEqual(result["errors"], [])
        for field in ("acceptance_evidence", "authorizes_resumption",
                      "hardware_executed"):
            self.assertIs(result[field], False, field)
        self.assertTrue(result["unverified_requirements"])

    def test_build_copy_and_programming_configurations_are_rejected(self):
        for settings in (
                dict(bedrock_project_dir="synthetic"),
                dict(bedrock_project_dir="synthetic", remote_rpd_win_path="synthetic"),
                dict(sync_rtl_to_dir="synthetic"),
                dict(local_build_and_flash_cmd="synthetic-never-execute"),
                dict(force_flash=True)):
            with self.subTest(settings=settings):
                result = self.inspect_config(dict(
                    remote_test_cmd="synthetic-never-execute", **settings))
                self.assertTrue(result["configuration_actions"])
                self.assertTrue(result["errors"])
                self.assertFalse(result["hardware_executed"])

    def test_occupied_output_is_not_removed_or_reused(self):
        with patch("preparation.os.path.lexists", return_value=True):
            result = self.inspect_config(
                dict(remote_test_cmd="synthetic-never-execute"),
                output="evidence/synthetic-occupied.json")
        self.assertFalse(result["output_contract"]["fresh"])
        self.assertTrue(any("occupied" in error for error in result["errors"]))

    def test_output_beneath_file_or_dangling_symlink_is_not_fresh(self):
        for kind in ("file", "dangling-symlink"):
            with self.subTest(kind=kind):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    (root / "fpga").mkdir()
                    (root / "fpga/board_hil.json").write_text(json.dumps(dict(
                        remote_test_cmd="synthetic-never-execute")))
                    (root / "evidence").mkdir()
                    blocked = root / "evidence/blocked"
                    if kind == "file":
                        blocked.write_bytes(b"preserve")
                    else:
                        blocked.symlink_to("missing-target")
                    result = inspect_hil_inputs(
                        root=root, output="evidence/blocked/new/result.json")
                    self.assertFalse(result["output_contract"]["fresh"])
                    self.assertTrue(any("ancestor" in error
                                        for error in result["errors"]))
                    self.assertFalse(result["hardware_executed"])
                    self.assertTrue(blocked.is_symlink() if kind == "dangling-symlink"
                                    else blocked.read_bytes() == b"preserve")

    def test_output_beneath_missing_directories_is_only_preflight_fresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fpga").mkdir()
            (root / "fpga/board_hil.json").write_text(json.dumps(dict(
                remote_test_cmd="synthetic-never-execute")))
            result = inspect_hil_inputs(
                root=root, output="evidence/new/subdirectory/result.json")
            self.assertTrue(result["output_contract"]["fresh"])
            self.assertEqual(result["errors"], [])
            self.assertFalse((root / "evidence").exists())
            self.assertFalse(result["authorizes_resumption"])

    def test_redirected_or_runtime_owned_output_is_not_fresh(self):
        for kind in ("evidence-symlink", "nested-symlink", "runtime-owned"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "fpga").mkdir()
                (root / "fpga/board_hil.json").write_text(json.dumps(dict(
                    remote_test_cmd="synthetic-never-execute")))
                target = root / "preserve"
                target.mkdir()
                marker = target / "marker"
                marker.write_bytes(b"unchanged")
                if kind == "evidence-symlink":
                    (root / "evidence").symlink_to(target, target_is_directory=True)
                    output = "evidence/new.json"
                else:
                    (root / "evidence").mkdir()
                    if kind == "nested-symlink":
                        (root / "evidence/redirect").symlink_to(
                            target, target_is_directory=True)
                        output = "evidence/redirect/new.json"
                    else:
                        output = "evidence/.vulcan/new.json"
                result = inspect_hil_inputs(root=root, output=output)
                self.assertFalse(result["output_contract"]["fresh"])
                self.assertTrue(result["errors"])
                self.assertFalse(result["hardware_executed"])
                self.assertFalse(result["authorizes_resumption"])
                self.assertEqual(marker.read_bytes(), b"unchanged")
                self.assertEqual(list(target.iterdir()), [marker])
                self.assertFalse((root / output).exists())

    def test_three_native_successes_do_not_certify_product(self):
        result = diagnose_hil_record(self.record)
        self.assertTrue(result["three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])
        self.assertEqual(result["product_traffic_comparisons"], "unestablished")
        self.assertEqual(result["programmed_image_source_binding"], "unestablished")

    def test_failed_or_incomplete_runs_break_consecutive_sequence(self):
        for field, value in (("exit_code", 1), ("exit_code", False),
                             ("passed", False), ("stdout", None),
                             ("stderr", None)):
            with self.subTest(field=field, value=value):
                record = copy.deepcopy(self.record)
                record["runs"][1][field] = value
                result = diagnose_hil_record(record)
                self.assertEqual(result["longest_consecutive_native_successes"], 1)
                self.assertFalse(result["three_consecutive_native_successes"])

    def test_duplicate_invalid_and_gapped_indices_cannot_make_three(self):
        for index in (1, 5, True, 0, None):
            with self.subTest(index=index):
                record = copy.deepcopy(self.record)
                record["runs"][1]["run_index"] = index
                result = diagnose_hil_record(record)
                self.assertFalse(result["three_consecutive_native_successes"])
                self.assertFalse(result["physical_acceptance_established"])

    def test_recorded_token_failures_override_claimed_run_success(self):
        for field in ("missing_expected_tokens", "forbidden_tokens_found"):
            for value in (["synthetic-token"], None, "", False, {}):
                with self.subTest(field=field, value=value):
                    record = copy.deepcopy(self.record)
                    record["runs"][1][field] = value
                    result = diagnose_hil_record(record)
                    self.assertEqual(
                        result["longest_consecutive_native_successes"], 1)
                    self.assertFalse(result["three_consecutive_native_successes"])
                    self.assertTrue(any(field in error for error in result["errors"]))
                    self.assertFalse(result["physical_acceptance_established"])

    def test_empty_token_results_preserve_legacy_native_diagnostic(self):
        for run in self.record["runs"]:
            run["missing_expected_tokens"] = []
            run["forbidden_tokens_found"] = []
        result = diagnose_hil_record(self.record)
        self.assertTrue(result["three_consecutive_native_successes"])
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["physical_acceptance_established"])

    def test_cli_contradictory_token_result_fails_without_executing_commands(self):
        self.record["runs"][1]["forbidden_tokens_found"] = ["synthetic-token"]
        with patch.object(Path, "read_bytes",
                          return_value=json.dumps(self.record).encode()):
            code, result = self.invoke_cli(
                "--inspect-hil-receipt", "evidence/synthetic-hil.json")
        self.assertEqual(code, 1)
        self.assertTrue(result["errors"])
        self.assertFalse(result["native_execution_diagnostic"][
            "three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])
        self.assertFalse(result["hardware_executed"])

    def test_cli_failed_native_run_is_an_error_not_inventory_success(self):
        for field, value in (("exit_code", 1), ("exit_code", None),
                             ("exit_code", False), ("passed", False),
                             ("passed", None)):
            with self.subTest(field=field, value=value):
                record = copy.deepcopy(self.record)
                record["runs"][1][field] = value
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                diagnostic = result["native_execution_diagnostic"]
                self.assertTrue(any(field in error for error in diagnostic["errors"]))
                self.assertFalse(diagnostic["three_consecutive_native_successes"])
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["hardware_executed"])

    def test_cli_failed_aggregate_cannot_be_hidden_by_successful_runs(self):
        for field, value in (("status", "failed"), ("status", None),
                             ("status", True),
                             ("deterministic_across_runs", False),
                             ("deterministic_across_runs", None),
                             ("deterministic_across_runs", 1)):
            with self.subTest(field=field, value=value):
                record = copy.deepcopy(self.record)
                record[field] = value
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                self.assertTrue(any(field in error for error in result["errors"]))
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["authorizes_resumption"])
                self.assertFalse(result["hardware_executed"])

    def test_cli_requested_run_inventory_must_be_complete(self):
        for requested in (0, -1, True, None, "3", 2, 4):
            with self.subTest(requested=requested):
                record = copy.deepcopy(self.record)
                record["requested_runs"] = requested
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                self.assertTrue(any("requested_runs" in error
                                    for error in result["errors"]))
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["hardware_executed"])

    def test_requested_run_indices_cannot_be_shifted_or_reordered(self):
        for indices in ((2, 3, 4), (3, 2, 1), (1, 3, 2)):
            with self.subTest(indices=indices):
                record = copy.deepcopy(self.record)
                record["requested_runs"] = 3
                for run, index in zip(record["runs"], indices):
                    run["run_index"] = index
                result = diagnose_hil_record(record)
                self.assertTrue(any("requested_runs" in error
                                    for error in result["errors"]))
                self.assertFalse(result["physical_acceptance_established"])

    def test_complete_requested_inventory_remains_diagnostic_only(self):
        self.record["requested_runs"] = 3
        result = diagnose_hil_record(self.record)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])

    def test_inconsistent_receipt_cannot_report_successful_three_run_set(self):
        for field, value in (("requested_runs", 4), ("requested_runs", 2),
                             ("status", "failed"),
                             ("deterministic_across_runs", False)):
            with self.subTest(field=field, value=value):
                record = copy.deepcopy(self.record)
                record[field] = value
                result = diagnose_hil_record(record)
                self.assertEqual(result["longest_consecutive_native_successes"], 3)
                self.assertTrue(result["errors"])
                self.assertFalse(result["three_consecutive_native_successes"])
                self.assertFalse(result["physical_acceptance_established"])

    def test_failed_extra_run_cannot_be_hidden_by_successful_subsequence(self):
        record = copy.deepcopy(self.record)
        record["requested_runs"] = 4
        record["runs"].append(dict(
            run_index=4, exit_code=1, passed=False, stdout="", stderr="Synthetic failure"))
        result = diagnose_hil_record(record)
        self.assertEqual(result["longest_consecutive_native_successes"], 3)
        self.assertTrue(result["errors"])
        self.assertFalse(result["three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])

    def test_cli_timeout_cannot_be_hidden_by_successful_exit(self):
        for value in (True, None, 0, "false"):
            with self.subTest(timed_out=value):
                record = copy.deepcopy(self.record)
                record["runs"][1]["timed_out"] = value
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                diagnostic = result["native_execution_diagnostic"]
                self.assertTrue(any("timed_out" in error
                                    for error in diagnostic["errors"]))
                self.assertEqual(diagnostic["longest_consecutive_native_successes"], 1)
                self.assertFalse(diagnostic["three_consecutive_native_successes"])
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["hardware_executed"])

    def test_cli_launch_error_cannot_be_hidden_by_successful_exit(self):
        for value in ("Synthetic tool unavailable", "", False, 0, {}):
            with self.subTest(launch_error=value):
                record = copy.deepcopy(self.record)
                record["runs"][1]["launch_error"] = value
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                diagnostic = result["native_execution_diagnostic"]
                self.assertTrue(any("launch_error" in error
                                    for error in diagnostic["errors"]))
                self.assertEqual(diagnostic["longest_consecutive_native_successes"], 1)
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["hardware_executed"])

    def test_explicit_clean_execution_metadata_remains_diagnostic_only(self):
        for run in self.record["runs"]:
            run["timed_out"] = False
            run["launch_error"] = None
        result = diagnose_hil_record(self.record)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])

    def test_aggregate_execution_failure_cannot_be_hidden_by_clean_runs(self):
        for field, value in (("timed_out", True), ("timed_out", None),
                             ("timed_out", 0), ("timed_out", "false"),
                             ("launch_error", "Synthetic launch failure"),
                             ("launch_error", ""), ("launch_error", False),
                             ("launch_error", 0), ("launch_error", {})):
            with self.subTest(field=field, value=value):
                record = copy.deepcopy(self.record)
                record[field] = value
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                diagnostic = result["native_execution_diagnostic"]
                self.assertTrue(any(field in error for error in diagnostic["errors"]))
                self.assertEqual(diagnostic["longest_consecutive_native_successes"], 3)
                self.assertFalse(diagnostic["three_consecutive_native_successes"])
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["hardware_executed"])

    def test_clean_aggregate_execution_metadata_remains_diagnostic_only(self):
        self.record.update(timed_out=False, launch_error=None)
        result = diagnose_hil_record(self.record)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])

    def test_aggregate_exit_failure_cannot_be_hidden_by_clean_runs(self):
        for value in (1, -9, None, False, 0.0, "0"):
            with self.subTest(exit_code=value):
                record = copy.deepcopy(self.record)
                record["exit_code"] = value
                with patch.object(Path, "read_bytes",
                                  return_value=json.dumps(record).encode()):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt", "evidence/synthetic-hil.json")
                self.assertEqual(code, 1)
                diagnostic = result["native_execution_diagnostic"]
                self.assertTrue(any("aggregate HIL exit_code" in error
                                    for error in diagnostic["errors"]))
                self.assertEqual(diagnostic["longest_consecutive_native_successes"], 3)
                self.assertFalse(diagnostic["three_consecutive_native_successes"])
                self.assertFalse(result["physical_acceptance_established"])
                self.assertFalse(result["hardware_executed"])

    def test_clean_aggregate_exit_remains_diagnostic_only(self):
        self.record["exit_code"] = 0
        result = diagnose_hil_record(self.record)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["three_consecutive_native_successes"])
        self.assertFalse(result["physical_acceptance_established"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
