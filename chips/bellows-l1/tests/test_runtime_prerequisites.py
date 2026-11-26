"""Offline regression for one-shot dispatch through the installed Vulcan Runtime."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from vulcan_agent import __version__, engineering, native_scope, process, runtime
from vulcan_agent.project import InputError, matches


CHECK = "offline_child"
STEP = f"check:{CHECK}"
CHECK_TIMEOUT = 15


def write_fixture(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class PrerequisiteAdmissionTest(unittest.TestCase):
    def new_fixture(self):
        scratch = tempfile.TemporaryDirectory(prefix="vulcan-prerequisites-", dir="/tmp")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.home = self.root / ".vulcan" / "engineering"
        self.home.mkdir(parents=True)
        self.marker = self.root / "launches.txt"
        self.order = {
            "schema": 1,
            "domain": "digital_circuit",
            "profile": "verification",
            "mode": "verify",
            "objective": "Offline prerequisite dispatch fixture",
            "role_limits": {"timeout_s": 30, "max_output_bytes": 4096},
        }
        write_fixture(self.root / "vulcan-workflow.json", self.order)
        self.workflow = engineering.Workflow(self.root, self.order)
        (self.root / "child.py").write_text(
            "with open('launches.txt', 'a', encoding='utf-8') as marker:\n"
            "    marker.write('child\\n')\n",
            encoding="utf-8",
        )

    def reviewer_fixture(self, name, operation, **context):
        folder = self.home / name
        folder.mkdir()
        write_fixture(folder / "request.json", {
            "role": "reviewer", "operation": operation, "project": str(self.root),
            "journal_folder": folder.relative_to(self.root).as_posix(),
            "context": {"config": self.order, **context},
        })
        write_fixture(folder / "response.json", {"status": "passed", "decision": {"status": "done"}})
        write_fixture(folder / "result.json", {
            "status": "passed", "exit_code": 0, "process_scope_settled": True,
        })
        return folder

    def opening(self, name, *, scope_timeout, run=None):
        requirements = ["Observe the offline marker"]
        if run is not None:
            requirements.append("Check one-shot prerequisite dispatch")
        plan = {
            "roadmap": ["Run the offline marker child."],
            "spec": "Append one marker per launch.",
            "reason": "Exercise reviewed dispatch without using a product or platform.",
            "design_inputs": [],
            "verification_inputs": ["child.py"],
            "checks": [{
                "id": CHECK, "argv": [sys.executable, "-B", "child.py"],
                "inputs": ["child.py"], "outputs": [],
                "timeout_s": CHECK_TIMEOUT, "max_output_bytes": 4096,
            }],
            "verification": {"packages": [{
                "id": "rtl_functional", "basis": "risk_selected", "requirements": requirements,
                "parameters": {}, "check_ids": [CHECK],
            }]},
            "native_scope": {"after": {CHECK: []}, "timeout_s": scope_timeout},
        }
        contract = engineering.validate_plan(plan, self.order, root=self.root)
        if run is None:
            run = runtime.Run.open(self.root, self.home, contract, new=True)
        else:
            self.assertTrue(run.sync_checks_with_plan(contract))
        review = self.reviewer_fixture(name, "plan", plan=plan)
        state = self.workflow.state
        state.update(phase="prerequisites", plan=plan, run=run.folder.name)
        state["plans"].append(plan)
        state.setdefault("admitted_plan_reviews", []).append({"reviewer_call": review.name, "run": run.folder.name})
        self.workflow.save()
        native_scope.bind(run, review)
        return run

    def assert_launches(self, run, count):
        self.assertEqual(self.marker.read_text().splitlines(), ["child"] * count)
        self.assertEqual([attempt["step"] for attempt in run.state["attempts"]], [STEP] * count)

    def retired_child(self, run):
        attempt = run.latest(STEP)
        self.assertEqual(attempt["status"], "passed")
        self.assertEqual(attempt["exit_code"], 0)
        self.assertIs(attempt["process_scope_settled"], True)
        receipt = process.require_settled_scope(run.attempt_dir(attempt))
        self.assertTrue(receipt["command"]["pid"])
        self.assertEqual(receipt["scope"]["remaining"], [])
        return receipt

    def test_run_prerequisites_one_shot_admission(self):
        for case, scope_timeout in (("completed", 60), ("refused", CHECK_TIMEOUT)):
            with self.subTest(case=case):
                self.new_fixture()
                run = self.opening(f"plan-before-{case}", scope_timeout=60)
                self.assertTrue(run.run_checks(run.config["checks"]))
                self.assert_launches(run, 1)
                self.retired_child(run)
                self.assertTrue(run.current_check(run.config["checks"][0]))
                previous = run.latest(STEP)
                prior_result = run.attempt_dir(previous) / "result.json"
                prior_sha = file_sha256(prior_result)

                run = self.opening(f"plan-after-{case}", scope_timeout=scope_timeout, run=run)
                check, = run.config["checks"]
                self.assertTrue(matches(self.root, check["inputs"], run.attempt_dir(previous) / "inputs"))
                self.assertNotEqual(run.check_contract_sha256(check), previous["check_contract_sha256"])
                self.assertFalse(run.current_check(check))
                with self.assertRaisesRegex(InputError, "unused opening scope"):
                    run.run_checks([check])
                self.assert_launches(run, 1)

                review = self.reviewer_fixture(
                    f"approval-{case}", "recovery",
                    proposed_recovery={
                        "action": "checks", "reason": "Run only the revised offline check.",
                        "prerequisite_checks": [CHECK],
                    },
                    prerequisite_dispatch=run.prerequisite_context([CHECK]),
                )
                run.authorize_prerequisites([CHECK], review)
                run = runtime.Run.open(self.root, self.home, run.config, run_id=run.folder.name)
                self.assertEqual(run.state["prerequisite_dispatches"][-1]["status"], "pending")
                if case == "completed":
                    self.assertTrue(run.run_prerequisites())
                    scope = self.retired_child(run)
                    refusal = None
                    self.assert_launches(run, 2)
                else:
                    with self.assertRaisesRegex(InputError, "remaining opening scope budget") as error:
                        run.run_prerequisites()
                    scope = None
                    refusal = str(error.exception)
                    self.assert_launches(run, 1)

                dispatched = len(run.state["attempts"])
                loaded = runtime.Run.open(self.root, self.home, run.config, run_id=run.folder.name)
                settlement = loaded.state["prerequisite_dispatches"][-1]["status"]
                self.assertEqual(settlement, "completed" if case == "completed" else "failed")
                if case == "completed":
                    self.assertTrue(loaded.run_prerequisites())
                    self.assert_launches(loaded, 2)
                else:
                    with self.assertRaisesRegex(InputError, "consumed"):
                        loaded.run_prerequisites()
                    self.assert_launches(loaded, 1)
                with self.assertRaisesRegex(InputError, "consumed"):
                    loaded.authorize_prerequisites([CHECK], review)
                self.assertEqual(file_sha256(prior_result), prior_sha)
                print(json.dumps({
                    "case": case, "settlement": settlement, "new_launches": dispatched - 1,
                    "replay_launches": len(loaded.state["attempts"]) - dispatched,
                    "admitted_child_process_scope": scope, "refusal": refusal,
                }), flush=True)


if __name__ == "__main__":
    print(json.dumps({
        "runtime_version": __version__,
        "runtime_modules": {module.__name__: {"path": module.__file__, "sha256": file_sha256(module.__file__)}
                            for module in (engineering, native_scope, process, runtime)},
        "source_sha256": file_sha256(__file__),
    }), flush=True)
    unittest.main(verbosity=2)
