#!/usr/bin/env python3
"""Synthetic HIL diagnostic regressions, not physical product verification.

Run: python3 -B tests/test_preparation.py
No transport commands are executed and no hardware acceptance is established.
"""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparation import diagnose_hil_record, inspect_hil_inputs


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
