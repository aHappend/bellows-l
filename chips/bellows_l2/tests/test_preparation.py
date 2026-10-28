#!/usr/bin/env python3
"""Synthetic HIL diagnostic regressions, not physical product verification.

Run: python3 -B tests/test_preparation.py
No transport commands are executed and no hardware acceptance is established.
"""

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparation import diagnose_hil_record, inspect_hil_inputs, main


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
