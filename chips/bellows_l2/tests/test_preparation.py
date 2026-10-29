#!/usr/bin/env python3
"""Synthetic retention and HIL regressions, not product verification.

Run: python3 -B tests/test_preparation.py
No transport commands are executed and no hardware acceptance is established.
Producer-to-auditor checks distinguish successful synchronization from later loss;
they do not diagnose the mechanism or establish a platform retention remedy.
"""

import copy
from contextlib import chdir, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify as verifier
from preparation import (audit_artifacts, audit_bundle, audit_receipt, diagnose_hil_record,
                         inspect_hil_inputs, inspect_portable_inputs, main,
                         repair_receipt, stage_portable_root)
from verify import (archive_artifacts, file_integrity, inputs, json_write,
                    persist_artifacts, sync_directory)


class ArtifactProducerTests(unittest.TestCase):
    def test_finalization_failure_is_not_retried_over_occupied_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with chdir(root), patch("verify.ROOT", root), patch(
                    "verify.Execution") as execution, patch(
                    "verify.check_parent"), patch("verify.source_contract"), patch(
                    "verify.preparation_regressions"), patch(
                    "sys.argv", ["verify.py", "--output", "result",
                                 "--subset", "harness-focused"]):
                execution.return_value.finish.side_effect = OSError(
                    "synthetic retention failure")
                with self.assertRaisesRegex(OSError, "synthetic retention failure"):
                    verifier.main()
                execution.return_value.finish.assert_called_once_with("passed")
                self.assertFalse((root / "result/failure.log").exists())

    def test_archive_preserves_bytes_but_never_excuses_missing_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evidence/bundle"
            original = output / "obj/model.o"
            original.parent.mkdir(parents=True)
            payload = b"synthetic compiler intermediate\0" * 17
            original.write_bytes(payload)
            with patch("verify.ROOT", root), patch("preparation.ROOT", root):
                record = archive_artifacts(output)
                archive = root / record["path"]
                archive_bytes = archive.read_bytes()
                bindings = persist_artifacts(output)
                self.assertEqual(record["members"], 1)
                self.assertTrue(record["original_files_required"])
                self.assertFalse(record["post_settlement_retention_verified"])
                with self.assertRaises(FileExistsError):
                    archive_artifacts(output)
                self.assertEqual(archive.read_bytes(), archive_bytes)
                original.unlink()
                report = audit_artifacts(Path("evidence/bundle"), bindings)
                self.assertTrue(report["errors"])
                self.assertEqual(report["missing_files"],
                                 ["evidence/bundle/obj/model.o"])
                with tarfile.open(archive, "r:gz") as retained:
                    self.assertEqual(retained.getnames(), ["obj/model.o"])
                    with retained.extractfile("obj/model.o") as handle:
                        self.assertEqual(handle.read(), payload)
                self.assertFalse(original.exists())

    def test_archive_rejects_symlinked_artifacts_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evidence/bundle"
            output.mkdir(parents=True)
            original = output / "data.bin"
            original.write_bytes(b"synthetic bytes")
            (output / "redirect.bin").symlink_to(original)
            with patch("verify.ROOT", root):
                with self.assertRaisesRegex(AssertionError, "symlink"):
                    archive_artifacts(output)
            self.assertFalse((output / "retained-artifacts.tar.gz").exists())

    def test_archive_rejects_original_mutation_and_retains_failed_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evidence/bundle"
            output.mkdir(parents=True)
            original = output / "data.bin"
            original.write_bytes(b"original bytes")
            add = tarfile.TarFile.add

            def mutate_after_copy(retained, path, **kwargs):
                add(retained, path, **kwargs)
                path.write_bytes(b"modified bytes")

            with patch("verify.ROOT", root), patch.object(
                    tarfile.TarFile, "add", new=mutate_after_copy):
                with self.assertRaisesRegex(AssertionError, "Original evidence changed"):
                    archive_artifacts(output)
            self.assertEqual(original.read_bytes(), b"modified bytes")
            with tarfile.open(output / "retained-artifacts.tar.gz", "r:gz") as retained:
                with retained.extractfile("data.bin") as handle:
                    self.assertEqual(handle.read(), b"original bytes")

    def test_archive_rejects_member_byte_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evidence/bundle"
            output.mkdir(parents=True)
            original = output / "data.bin"
            original.write_bytes(b"original bytes")
            with patch("verify.ROOT", root), patch.object(
                    tarfile.TarFile, "extractfile",
                    return_value=io.BytesIO(b"corrupted bytes")):
                with self.assertRaisesRegex(AssertionError, "archive byte mismatch"):
                    archive_artifacts(output)
            self.assertTrue((output / "retained-artifacts.tar.gz").is_file())
            self.assertEqual(original.read_bytes(), b"original bytes")

    def test_same_byte_symlink_substitution_during_synchronization_is_rejected(self):
        for replacement in ("file", "bundle", "ancestor"):
            with self.subTest(replacement=replacement), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "evidence/bundle"
                output.mkdir(parents=True)
                artifact = output / "data.bin"
                artifact.write_bytes(b"synthetic retained bytes")
                peer = output / "peer.bin"
                peer.write_bytes(artifact.read_bytes())
                substituted = False

                def synchronize(path):
                    nonlocal substituted
                    sync_directory(path)
                    if path == output and not substituted:
                        substituted = True
                        if replacement == "file":
                            artifact.unlink()
                            artifact.symlink_to(peer)
                        elif replacement == "bundle":
                            original = root / "original-bundle"
                            output.rename(original)
                            output.symlink_to(original, target_is_directory=True)
                        else:
                            original = root / "original-evidence"
                            output.parent.rename(original)
                            output.parent.symlink_to(original, target_is_directory=True)

                with patch("verify.ROOT", root), patch(
                        "verify.sync_directory", side_effect=synchronize):
                    with self.assertRaisesRegex(AssertionError, "symlink"):
                        persist_artifacts(output)
                self.assertTrue(substituted)
                self.assertEqual(artifact.read_bytes(), b"synthetic retained bytes")

    def test_regular_bundle_is_synchronized_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evidence/bundle"
            output.mkdir(parents=True)
            artifact = output / "data.bin"
            artifact.write_bytes(b"synthetic retained bytes")
            with patch("verify.ROOT", root):
                bindings = persist_artifacts(output)
            self.assertEqual(bindings, {
                "evidence/bundle/data.bin": file_integrity(artifact)})

    def test_loss_after_successful_synchronization_is_rejected_without_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = Path("evidence/bundle")
            output = root / bundle
            artifacts = {
                "obj/model.o": b"synthetic compiler intermediate",
                "stdout.log": b"synthetic successful execution\n",
                "synthesis/netlist.json": b"synthetic synthesis artifact\n",
            }
            for name, payload in artifacts.items():
                path = output / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            with patch("verify.ROOT", root), patch("preparation.ROOT", root), \
                    patch("subprocess.Popen", side_effect=AssertionError(
                        "A retention audit must not regenerate missing artifacts")):
                bindings = persist_artifacts(output)
                receipt = output / "receipt.json"
                json_write(receipt, dict(exit_code=0, artifact_integrity=bindings))
                original = receipt.read_bytes()
                before = audit_artifacts(bundle, bindings)
                self.assertEqual(before["errors"], [])
                self.assertEqual(before["rechecked_files"], len(artifacts))

                missing = output / "obj/model.o"
                missing.unlink()
                after = audit_artifacts(bundle, bindings)

            name = missing.relative_to(root).as_posix()
            self.assertTrue(after["errors"])
            self.assertEqual(after["missing_files"], [name])
            self.assertEqual(after["missing_artifact_bindings"], {
                name: bindings[name]})
            self.assertEqual(after["missing_bytes"], len(artifacts["obj/model.o"]))
            self.assertEqual(after["rechecked_files"], len(artifacts) - 1)
            self.assertEqual(receipt.read_bytes(), original)
            self.assertEqual(json.loads(original)["exit_code"], 0)
            self.assertFalse(missing.exists())
            for retained in ("stdout.log", "synthesis/netlist.json"):
                self.assertEqual((output / retained).read_bytes(), artifacts[retained])


class PreparationStreamTests(unittest.TestCase):
    def test_probe_rejects_changed_or_unreadable_final_source_inventory(self):
        for final_inventory in (
                {"tests/example.py": "1" * 64},
                OSError("synthetic source inventory unavailable")):
            with self.subTest(final_inventory=final_inventory), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                initial = {"tests/example.py": "0" * 64}

                def launch(argv, **kwargs):
                    kwargs["stdout"].write(b"synthetic successful child\n")
                    process = unittest.mock.Mock()
                    process.wait.return_value = 0
                    return process

                with chdir(root), patch("preparation.ROOT", root), patch(
                        "preparation.inputs", side_effect=[initial, final_inventory]), patch(
                        "preparation.subprocess.Popen", side_effect=launch), patch(
                        "sys.argv", ["preparation.py", "--subset", "harness-focused"]), \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(), 1)
                    receipts = list(root.glob("evidence/preparation/*/receipt.json"))
                    self.assertEqual(len(receipts), 1)
                    record = json.loads(receipts[0].read_bytes())
                    self.assertEqual(record["exit_code"], 0)
                    self.assertFalse(record["source_unchanged"])
                    self.assertEqual(record["probe_exit_code"], 1)
                    self.assertIn("source", record["source_inventory_error"].lower())
                    self.assertIn("source", (root / record["stderr"]).read_text().lower())
                    for channel in ("stdout", "stderr"):
                        self.assertEqual(record["stream_integrity"][channel],
                                         file_integrity(root / record[channel]))

    def test_probe_binds_both_raw_streams_and_rejects_later_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_bindings = {"tests/example.py": "0" * 64}

            def launch(argv, **kwargs):
                kwargs["stdout"].write(b"synthetic child stdout\n")
                kwargs["stderr"].write(b"synthetic child stderr\n")
                process = unittest.mock.Mock()
                process.wait.return_value = 0
                return process

            with chdir(root), patch("preparation.ROOT", root), patch(
                    "preparation.inputs", return_value=source_bindings), patch(
                    "preparation.subprocess.Popen", side_effect=launch), patch(
                    "sys.argv", ["preparation.py", "--subset", "harness-focused"]), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(), 0)
                receipts = list(root.glob("evidence/preparation/*/receipt.json"))
                self.assertEqual(len(receipts), 1)
                receipt = receipts[0]
                record = json.loads(receipt.read_bytes())
                self.assertEqual(record["exit_code"], 0)
                self.assertEqual(record["probe_exit_code"], 0)
                self.assertTrue(record["source_unchanged"])
                for channel in ("stdout", "stderr"):
                    stream = root / record[channel]
                    self.assertIn("stream_integrity", record)
                    self.assertEqual(record["stream_integrity"][channel],
                                     file_integrity(stream))
                name = receipt.relative_to(root).as_posix()
                repair_receipt(name)
                (root / record["stdout"]).write_bytes(b"truncated")
                with self.assertRaisesRegex(ValueError, "stream integrity mismatch"):
                    repair_receipt(name)


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

    def test_readable_source_deltas_do_not_waive_mismatches_or_occupied_outputs(self):
        staged = self.root / "evidence/fresh/project"
        stage_portable_root("evidence/fresh/project", reference=self.root)
        source = self.root / "tests/example.py"
        source.write_bytes(b"synthetic revised verification source\n")
        for destination in self.outputs:
            path = staged / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"preserve historical evidence")
        before = {path: path.read_bytes() for path in self.root.rglob("*")
                  if path.is_file()}

        report = inspect_portable_inputs(
            "evidence/fresh/project", reference=self.root, source_diff=True)

        self.assertFalse(report["portable_preflight_passed"])
        self.assertFalse(report["current_sources_match"])
        self.assertTrue(report["source_inventory_stable"])
        self.assertFalse(report["authorizes_resumption"])
        self.assertEqual(report["source_files_compared"], 5)
        differences = [row for row in report["source_comparisons"]
                       if not row["direct_bytes_equal"]]
        self.assertEqual(len(differences), 1)
        self.assertEqual(differences[0]["path"], "tests/example.py")
        self.assertIn("--- staged/tests/example.py\n", differences[0]["unified_diff"])
        self.assertIn("+++ current/tests/example.py\n", differences[0]["unified_diff"])
        self.assertIn("-synthetic declared input\n", differences[0]["unified_diff"])
        self.assertIn("+synthetic revised verification source\n",
                      differences[0]["unified_diff"])
        self.assertTrue(all(not row["fresh"] and not row["usable"]
                            for row in report["outputs"]))
        self.assertEqual(before, {path: path.read_bytes()
                                  for path in self.root.rglob("*") if path.is_file()})

    def test_source_deltas_are_opt_in_and_cli_preserves_failure_exit(self):
        stage_portable_root("evidence/fresh/project", reference=self.root)
        (self.root / "tests/example.py").write_bytes(b"changed input\n")
        report = inspect_portable_inputs("evidence/fresh/project", reference=self.root)
        self.assertTrue(all("unified_diff" not in row
                            for row in report["source_comparisons"]))
        output = io.StringIO()
        with patch("preparation.ROOT", self.root), patch(
                "sys.argv", ["preparation.py", "--inspect-portable-inputs",
                             "evidence/fresh/project", "--source-diff"]), patch(
                "preparation.inspect_portable_inputs", return_value=report) as inspect, \
                chdir(self.root), redirect_stdout(output):
            self.assertEqual(main(), 1)
        inspect.assert_called_once_with("evidence/fresh/project", source_diff=True)
        self.assertFalse(json.loads(output.getvalue())["current_sources_match"])

    def test_preflight_rejects_same_byte_current_source_redirect(self):
        stage_portable_root("evidence/fresh/project", reference=self.root)
        source = self.root / "rtl/example.sv"
        original = self.root / "original.sv"
        source.rename(original)
        source.symlink_to(original)
        report = inspect_portable_inputs("evidence/fresh/project", reference=self.root)
        self.assertFalse(report["portable_preflight_passed"], report)
        self.assertFalse(report["current_sources_match"])
        self.assertTrue(any("symlink" in error for error in report["errors"]))
        self.assertEqual(source.read_bytes(), original.read_bytes())
        self.assertTrue(source.is_symlink())
        self.assertEqual(len(report["outputs"]), len(self.outputs))

    def test_preflight_rechecks_both_source_trees_for_same_byte_redirects(self):
        stage_portable_root("evidence/fresh/project", reference=self.root)
        for side in ("current", "staged"):
            with self.subTest(side=side):
                root = (self.root if side == "current" else
                        self.root / "evidence/fresh/project")
                source = root / "rtl/example.sv"
                original = root / "original.sv"
                calls = 0

                def inventory(path):
                    nonlocal calls
                    result = inputs(path)
                    calls += 1
                    if calls == 4:
                        source.rename(original)
                        source.symlink_to(original)
                    return result

                with patch("preparation.inputs", side_effect=inventory):
                    report = inspect_portable_inputs(
                        "evidence/fresh/project", reference=self.root)
                self.assertEqual(calls, 4)
                self.assertFalse(report["portable_preflight_passed"], report)
                self.assertFalse(report["current_sources_match"])
                self.assertTrue(any("symlink" in error for error in report["errors"]))
                self.assertEqual(source.read_bytes(), original.read_bytes())
                source.unlink()
                original.rename(source)

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

    def test_missing_execution_root_reports_no_usable_outputs(self):
        report = inspect_portable_inputs("evidence/absent/project", reference=self.root)
        self.assertFalse(report["portable_preflight_passed"])
        self.assertFalse(report["current_sources_match"])
        self.assertEqual([entry["path"] for entry in report["outputs"]],
                         list(self.outputs))
        self.assertTrue(all(not entry["fresh"] and not entry["usable"]
                            for entry in report["outputs"]))
        self.assertFalse((self.root / "evidence").exists())

    def test_source_inventory_failure_does_not_hide_occupied_outputs(self):
        source = self.root / "rtl/example.sv"
        source.unlink()
        for destination in self.outputs:
            path = self.root / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"preserve historical evidence")
        report = inspect_portable_inputs(reference=self.root)
        self.assertFalse(report["portable_preflight_passed"])
        self.assertFalse(report["current_sources_match"])
        self.assertTrue(any("Unmatched declared input" in error
                            for error in report["errors"]))
        self.assertEqual([entry["path"] for entry in report["outputs"]],
                         list(self.outputs))
        for entry in report["outputs"]:
            self.assertFalse(entry["fresh"])
            self.assertFalse(entry["usable"])
            self.assertIn("Refusing occupied output destination", entry["error"])
            self.assertEqual((self.root / entry["path"]).read_bytes(),
                             b"preserve historical evidence")

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

    def complete_bundle(self):
        source = b"synthetic RTL\n"
        _, source_binding = self.artifact("source/rtl/example.sv", source)
        sources = {"rtl/example.sv": source_binding["sha256"]}
        child_name, _ = self.artifact("commands/001/receipt.json", json.dumps(dict(
            source_sha256=sources, exit_code=0, timed_out=False,
            stdout=f"{self.bundle}/commands/001/stdout.log",
            stderr=f"{self.bundle}/commands/001/stderr.log",
            generated_source_sha256={})).encode())
        self.artifact("commands/001/stdout.log", b"synthetic output\n")
        self.artifact("commands/001/stderr.log", b"")
        self.artifact("synthesis/netlist.json", b"synthetic retained netlist\n")
        self.artifact("results.json", json.dumps(dict(
            outcome="passed", mandatory_matrix=[
                dict(capacity=capacity, seed=seed, outcome="passed")
                for capacity in (1, 5, 13, 257, 4096, 65536)
                for seed in (1, 17, 89)])).encode())
        artifacts = {path.relative_to(self.root).as_posix(): file_integrity(path)
                     for path in self.base.rglob("*") if path.is_file()}
        receipt = self.base / "receipt.json"
        receipt.write_text(json.dumps(dict(
            kind="portable-verifier", results=f"{self.bundle}/results.json",
            source_sha256=sources, children=[child_name],
            artifact_integrity=artifacts)))
        return receipt, sources

    def test_unchanged_complete_receipt_remains_readable(self):
        receipt, sources = self.complete_bundle()
        original = receipt.read_bytes()
        with chdir(self.root), patch("preparation.inputs", return_value=sources):
            report = audit_bundle(self.bundle.as_posix())
        self.assertTrue(report["retained_files_readable"], report["errors"])
        self.assertTrue(report["artifact_manifest_verified"],
                        report["artifact_manifest_errors"])
        self.assertTrue(report["receipt_stable"])
        self.assertEqual(receipt.read_bytes(), original)

    def test_readable_legacy_bundle_without_manifest_cannot_pass_retention_check(self):
        receipt, sources = self.complete_bundle()
        original_record = json.loads(receipt.read_bytes())
        for missing in ("absent", "null"):
            with self.subTest(manifest=missing):
                record = copy.deepcopy(original_record)
                if missing == "absent":
                    del record["artifact_integrity"]
                else:
                    record["artifact_integrity"] = None
                receipt.write_text(json.dumps(record))
                original = receipt.read_bytes()
                stdout, stderr = io.StringIO(), io.StringIO()
                with chdir(self.root), patch("preparation.inputs", return_value=sources), \
                        patch("sys.argv", ["preparation.py", "--audit-bundles",
                                           self.bundle.as_posix()]), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = main()
                report = json.loads(stdout.getvalue())
                self.assertEqual(exit_code, 1)
                self.assertTrue(report["retained_files_readable"])
                self.assertTrue(report["current_sources_match"])
                self.assertFalse(report["artifact_manifest_verified"])
                bundle = report["bundles"][0]
                self.assertFalse(bundle["artifact_manifest_verified"])
                self.assertTrue(any("Missing artifact integrity manifest" in error
                                    for error in bundle["artifact_manifest_errors"]))
                self.assertEqual(bundle["recorded_outcome"], "passed")
                self.assertEqual(bundle["matrix_passed"], 18)
                self.assertEqual(bundle["child_receipts"], 1)
                self.assertEqual(bundle["raw_streams"], 2)
                self.assertFalse(report["authorizes_resumption"])
                self.assertEqual(stderr.getvalue(), "")
                self.assertEqual(receipt.read_bytes(), original)

    def test_artifact_loss_during_child_inspection_is_rejected(self):
        for change in ("missing", "changed", "unbound"):
            with self.subTest(change=change):
                self.bundle = Path("evidence") / f"synthetic-{change}"
                self.base = self.root / self.bundle
                self.base.mkdir()
                receipt, sources = self.complete_bundle()
                original = receipt.read_bytes()
                target = self.base / "synthesis/netlist.json"
                child = self.base / "commands/001/receipt.json"
                read_bytes = Path.read_bytes
                affected = False

                def change_during_child_read(path):
                    nonlocal affected
                    payload = read_bytes(path)
                    if path.absolute() == child and not affected:
                        affected = True
                        if change == "missing":
                            target.unlink()
                        elif change == "changed":
                            target.write_bytes(b"changed after initial inventory\n")
                        else:
                            (target.parent / "unexpected.json").write_bytes(b"unbound\n")
                    return payload

                with chdir(self.root), patch("preparation.inputs", return_value=sources), \
                        patch.object(Path, "read_bytes", change_during_child_read):
                    report = audit_bundle(self.bundle.as_posix())
                self.assertTrue(affected)
                self.assertFalse(report["retained_files_readable"], report["errors"])
                artifacts = report["artifact_integrity"]
                field = {"missing": "missing_files", "changed": "mismatched_files",
                         "unbound": "unbound_files"}[change]
                expected = (target.parent / "unexpected.json"
                            if change == "unbound" else target)
                self.assertIn(expected.relative_to(self.root).as_posix(), artifacts[field])
                self.assertEqual(receipt.read_bytes(), original)
                self.assertFalse(report["retention_handoff"]["authorizes_resumption"])
                unexpected = target.parent / "unexpected.json"
                if unexpected.exists():
                    unexpected.unlink()

    def test_source_change_during_bundle_audit_rejects_current_acceptance(self):
        receipt, sources = self.complete_bundle()
        original = receipt.read_bytes()
        changed = {"rtl/example.sv": "0" * 64}
        with chdir(self.root), patch(
                "preparation.inputs", side_effect=[sources, sources, changed]):
            report = audit_bundle(self.bundle.as_posix())
        self.assertTrue(report["retained_files_readable"], report["errors"])
        self.assertFalse(report["current_sources_match"])
        self.assertFalse(report["current_source_inventory_stable"])
        self.assertIn("Current declared inputs changed during bundle audit",
                      report["source_binding_errors"])
        self.assertFalse(report["retention_handoff"]["current_sources_match"])
        self.assertEqual(receipt.read_bytes(), original)

    def test_source_disappearance_during_bundle_audit_is_not_historical_loss(self):
        receipt, sources = self.complete_bundle()
        original = receipt.read_bytes()
        with chdir(self.root), patch(
                "preparation.inputs", side_effect=[
                    sources, sources, OSError("synthetic current source disappeared")]):
            report = audit_bundle(self.bundle.as_posix())
        self.assertTrue(report["retained_files_readable"], report["errors"])
        self.assertFalse(report["current_sources_match"])
        self.assertFalse(report["current_source_inventory_stable"])
        self.assertTrue(any("synthetic current source disappeared" in error
                            for error in report["source_binding_errors"]))
        self.assertEqual(receipt.read_bytes(), original)

    def test_initial_source_inventory_failure_preserves_retention_diagnostics(self):
        receipt, _ = self.complete_bundle()
        original = receipt.read_bytes()
        artifact = self.base / "synthesis/netlist.json"
        artifact.unlink()
        for error in (AssertionError("Unmatched declared input: rtl/*.sv"),
                      PermissionError("synthetic current source access denied")):
            with self.subTest(error=type(error).__name__):
                with chdir(self.root), patch("preparation.inputs", side_effect=error):
                    report = audit_bundle(self.bundle.as_posix(), source_diff=True)
                self.assertFalse(report["current_sources_match"])
                self.assertFalse(report["current_source_inventory_stable"])
                self.assertTrue(any(str(error) in message
                                    for message in report["source_binding_errors"]))
                self.assertFalse(report["retained_files_readable"])
                self.assertEqual(report["child_receipts"], 1)
                self.assertEqual(report["raw_streams"], 2)
                name = artifact.relative_to(self.root).as_posix()
                self.assertIn(name, report["artifact_integrity"]["missing_files"])
                self.assertIn(name, report["retention_handoff"]["missing_artifact_bindings"])
                self.assertFalse(report["retention_handoff"]["authorizes_resumption"])
                self.assertNotIn("source_deltas", report)
                self.assertFalse(artifact.exists())
                self.assertEqual(receipt.read_bytes(), original)

    def test_initial_source_failure_does_not_relabel_readable_history_as_lost(self):
        receipt, _ = self.complete_bundle()
        original = receipt.read_bytes()
        with chdir(self.root), patch(
                "preparation.inputs", side_effect=AssertionError("Unmatched declared input")):
            report = audit_bundle(self.bundle.as_posix(), source_diff=True)
        self.assertTrue(report["retained_files_readable"], report["errors"])
        self.assertFalse(report["current_sources_match"])
        self.assertFalse(report["current_source_inventory_stable"])
        self.assertTrue(report["source_binding_errors"])
        self.assertEqual(report["artifact_integrity"]["missing_files"], [])
        self.assertEqual(report["child_receipts"], 1)
        self.assertEqual(report["raw_streams"], 2)
        self.assertTrue(report["receipt_stable"])
        self.assertFalse(report["retention_handoff"]["authorizes_resumption"])
        self.assertNotIn("source_deltas", report)
        self.assertEqual(receipt.read_bytes(), original)

    def test_receipt_must_remain_identical_through_artifact_audit(self):
        receipt, sources = self.complete_bundle()
        original = receipt.read_bytes()

        def replace_receipt(*args, **kwargs):
            report = audit_artifacts(*args, **kwargs)
            changed = json.loads(original)
            changed["artifact_integrity"] = {}
            receipt.write_text(json.dumps(changed))
            return report

        with chdir(self.root), patch("preparation.inputs", return_value=sources), \
                patch("preparation.audit_artifacts", side_effect=replace_receipt):
            report = audit_bundle(self.bundle.as_posix())
        self.assertFalse(report["retained_files_readable"])
        self.assertFalse(report["receipt_stable"])
        self.assertTrue(any("receipt changed during audit" in error.lower()
                            for error in report["errors"]), report["errors"])
        self.assertNotEqual(receipt.read_bytes(), original)

    def test_receipt_disappearance_during_audit_is_explicit_failure(self):
        receipt, sources = self.complete_bundle()

        def remove_receipt(*args, **kwargs):
            report = audit_artifacts(*args, **kwargs)
            receipt.unlink()
            return report

        with chdir(self.root), patch("preparation.inputs", return_value=sources), \
                patch("preparation.audit_artifacts", side_effect=remove_receipt):
            report = audit_bundle(self.bundle.as_posix())
        self.assertFalse(report["retained_files_readable"])
        self.assertFalse(report["receipt_stable"])
        self.assertTrue(any("cannot recheck bundle receipt" in error.lower()
                            for error in report["errors"]), report["errors"])
        self.assertFalse(receipt.exists())

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

    def test_passing_matrix_cannot_hide_partial_synthesis_retention_loss(self):
        receipt, sources = self.complete_bundle()
        bindings = dict(self.artifact(f"matrix/obj/file-{index}.o")
                        for index in range(299))
        retained_synthesis = {}
        for capacity in (1, 5, 13, 257, 4096, 65536):
            artifacts = dict(self.artifact(
                f"synthesis-{capacity}/{name}", b"synthetic synthesis artifact\n")
                for name in ("synthesis.ys", "netlist.json", "structure.json"))
            if capacity == 257:
                retained_synthesis.update(artifacts)
            else:
                bindings.update(artifacts)
        record = json.loads(receipt.read_bytes())
        record["artifact_integrity"].update(bindings)
        record["artifact_integrity"].update(retained_synthesis)
        receipt.write_text(json.dumps(record))
        original = receipt.read_bytes()
        for name in bindings:
            (self.root / name).unlink()

        stdout, stderr = io.StringIO(), io.StringIO()
        with chdir(self.root), patch("preparation.inputs", return_value=sources), \
                patch("sys.argv", ["preparation.py", "--audit-bundles",
                                   self.bundle.as_posix()]), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main()

        report = json.loads(stdout.getvalue())
        bundle = report["bundles"][0]
        inventory = bundle["artifact_integrity"]
        self.assertEqual(exit_code, 1)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(bundle["recorded_outcome"], "passed")
        self.assertEqual(bundle["matrix_passed"], 18)
        self.assertTrue(report["current_sources_match"])
        self.assertFalse(report["retained_files_readable"])
        self.assertEqual(len(inventory["missing_files"]), 314)
        self.assertEqual(inventory["missing_artifact_bindings"], bindings)
        self.assertEqual(inventory["missing_bytes"],
                         sum(binding["bytes"] for binding in bindings.values()))
        self.assertEqual(inventory["rechecked_files"],
                         inventory["expected_files"] - 314)
        self.assertFalse(bundle["retention_handoff"]["authorizes_staging"])
        self.assertFalse(report["authorizes_resumption"])
        self.assertEqual(receipt.read_bytes(), original)
        for name, binding in retained_synthesis.items():
            self.assertEqual(file_integrity(self.root / name), binding)
        self.assertTrue(all(not (self.root / name).exists() for name in bindings))

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
                self.assertEqual(report["artifacts_by_suffix"], {})

    def test_suffix_inventory_distinguishes_selective_loss_without_exemptions(self):
        missing = dict([
            self.artifact("first/obj/model.o", b"object"),
            self.artifact("second/obj/model.o", b"other object"),
            self.artifact("first/obj/model.d", b""),
            self.artifact("first/obj/model.gch", b"precompiled header")])
        retained = dict([
            self.artifact("third/obj/model.o", b"kept"),
            self.artifact("raw/output.log", b"raw"),
            self.artifact("raw/no_suffix", b"")])
        for name in missing:
            (self.root / name).unlink()
        report = audit_artifacts(self.bundle, {**missing, **retained})
        self.assertEqual(report["artifacts_by_suffix"], {
            ".o": dict(expected_files=3, expected_bytes=22,
                       missing_files=2, missing_bytes=18),
            ".d": dict(expected_files=1, expected_bytes=0,
                       missing_files=1, missing_bytes=0),
            ".gch": dict(expected_files=1, expected_bytes=18,
                         missing_files=1, missing_bytes=18),
            ".log": dict(expected_files=1, expected_bytes=3,
                         missing_files=0, missing_bytes=0),
            "": dict(expected_files=1, expected_bytes=0,
                     missing_files=0, missing_bytes=0)})
        self.assertEqual(report["missing_artifact_bindings"], missing)
        self.assertEqual(report["checked_files"], len(retained))
        self.assertEqual(len(report["errors"]), len(missing))
        self.assertTrue(all(not (self.root / name).exists() for name in missing))
        for name, binding in retained.items():
            self.assertEqual(file_integrity(self.root / name), binding)

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
        self.assertEqual(report["artifacts_by_suffix"][".log"], dict(
            expected_files=1, expected_bytes=binding["bytes"],
            missing_files=1, missing_bytes=binding["bytes"]))
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

    def test_bundle_audit_rejects_redirects_before_reading_them(self):
        for component in ("bundle", "receipt.json", "results.json",
                          "commands/001/stdout.log", "source/rtl/example.sv"):
            with self.subTest(component=component):
                receipt, sources = self.complete_bundle()
                path = self.base if component == "bundle" else self.base / component
                target = self.root / "evidence/redirect-target"
                path.rename(target)
                path.symlink_to(target, target_is_directory=target.is_dir())
                original_read = Path.read_bytes
                redirected_reads = []

                def read_without_redirect(candidate):
                    absolute = candidate if candidate.is_absolute() else self.root / candidate
                    if absolute == path or path in absolute.parents:
                        redirected_reads.append(candidate)
                        raise AssertionError(f"Read redirected audit path: {candidate}")
                    return original_read(candidate)

                try:
                    with chdir(self.root), patch("preparation.inputs",
                                                return_value=sources), \
                            patch.object(Path, "read_bytes", read_without_redirect):
                        report = audit_bundle(self.bundle.as_posix())
                    self.assertFalse(report["retained_files_readable"])
                    self.assertTrue(any("symlink" in error.lower()
                                        for error in report["errors"]), report)
                    self.assertEqual(redirected_reads, [])
                    self.assertFalse(report["retention_handoff"]["authorizes_resumption"])
                finally:
                    path.unlink()
                    target.rename(path)

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

    def test_receipt_symlinks_are_rejected_before_reading(self):
        for component in ("receipt", "directory"):
            with self.subTest(component=component), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                evidence = root / "evidence"
                evidence.mkdir()
                original = evidence / "original.json"
                payload = json.dumps(self.record).encode()
                original.write_bytes(payload)
                if component == "receipt":
                    receipt = evidence / "redirect.json"
                    receipt.symlink_to(original.name)
                else:
                    redirect = evidence / "redirect"
                    redirect.symlink_to(".", target_is_directory=True)
                    receipt = redirect / original.name
                with patch("preparation.ROOT", root), patch.object(
                        Path, "read_bytes", side_effect=AssertionError(
                            "Redirected HIL evidence must not be read")):
                    code, result = self.invoke_cli(
                        "--inspect-hil-receipt",
                        receipt.relative_to(root).as_posix())
                self.assertEqual(code, 1)
                self.assertTrue(any("symlink" in error for error in result["errors"]))
                self.assertFalse(result["physical_acceptance_established"])
                self.assertEqual(original.read_bytes(), payload)

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

    def test_hil_configuration_symlinks_are_rejected_before_reading(self):
        for kind in ("file", "directory", "dangling-file", "dangling-directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "synthetic-target"
                target.mkdir()
                config = target / "board_hil.json"
                config.write_text(json.dumps(dict(
                    remote_test_cmd="synthetic-never-execute")))
                if "directory" in kind:
                    link = root / "fpga"
                    link.symlink_to(
                        root / "missing" if kind.startswith("dangling") else target,
                        target_is_directory=True)
                else:
                    (root / "fpga").mkdir()
                    link = root / "fpga/board_hil.json"
                    link.symlink_to(
                        root / "missing" if kind.startswith("dangling") else config)
                original = config.read_bytes()
                with patch.object(Path, "read_bytes", side_effect=AssertionError(
                        "A symlinked HIL configuration must not be read")):
                    result = inspect_hil_inputs(root=root)
                self.assertFalse(result["product_command_configured"])
                self.assertTrue(any("Symlink in HIL configuration path" in error
                                    for error in result["errors"]))
                self.assertNotIn("configuration_integrity", result)
                self.assertFalse(result["hardware_executed"])
                self.assertFalse(result["authorizes_resumption"])
                self.assertTrue(link.is_symlink())
                self.assertEqual(config.read_bytes(), original)
                self.assertTrue(result["coordinator_handoff"]["required_inputs"])

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
