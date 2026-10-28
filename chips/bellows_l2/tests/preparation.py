#!/usr/bin/env python3
"""Retain one bounded advisory probe; never run the full admitted matrix here.

    python3 tests/preparation.py --subset targeted
    python3 tests/preparation.py --subset backend-focused
    python3 tests/preparation.py --subset output-focused
    python3 tests/preparation.py --subset ratio-focused --repair-of <receipt>
    python3 tests/preparation.py --audit-receipts <receipt> [<receipt> ...]
    python3 tests/preparation.py --audit-bundles evidence/l1 [<bundle> ...]
    python3 tests/preparation.py --audit-bundles evidence/l1 --source-diff
    python3 tests/preparation.py --inspect-hil-inputs
    python3 tests/preparation.py --inspect-hil-receipt evidence/retained-hil.json
    python3 tests/preparation.py --inspect-hil-inputs --hil-output evidence/native-board-hil-recovery-0120.json
    python3 tests/preparation.py --inspect-portable-inputs
    python3 tests/preparation.py --inspect-portable-inputs evidence/maintenance-root
    python3 tests/preparation.py --stage-portable-root evidence/fresh-portable/project

Repair links require predecessor metadata and both raw streams before launch.
This local check does not establish historical authenticity or authorize resumption.
The read-only audit writes JSON to stdout, creates no evidence, launches no children
and grants no acceptance credit. Missing history requires independent disposition;
an audit is not a replacement receipt or permission to resume paused verification.
Receipt-audit exit zero means metadata and logs are available, not that the
recorded commands passed. Each readable receipt separately reports its recorded
execution outcome; unknown or unsettled outcomes are never labeled successful.
Receipt audits also report source currency separately from historical execution:
a successful prerequisite from an older source set is not a current passing check.
Bundle audits separately report readability and binding to current declared inputs;
a readable historical bundle is not necessarily evidence for the current sources.
Optional --source-diff includes readable unified source changes from hash-checked
snapshots. It never rebases a receipt, excuses a changed binding or grants reuse.
The component inventory runs even when the top-level receipt is missing, so a
restoration request distinguishes an absent bundle from a partial restoration.
Present component files are fingerprinted and directory entries listed before
receipt validation. These observations identify restored material, not its
historical authenticity, completeness or authorization to resume verification.
New child receipts also bind the byte counts and hashes of both raw streams;
legacy receipts remain readable but are reported as lacking stream bindings.
Repair-predecessor audits validate any recorded stream bindings as well: a
present but truncated or changed log is not an available repair predecessor.
New bundle receipts bind all retained artifacts, not just sources and raw streams.
The audit checks their exact file inventory, sizes and hashes; legacy bundles
are explicitly reported as lacking these bindings. Neither kind of receipt
proves that files remain available after the audit's own process settles.
Artifact diagnostics distinguish missing, changed and unbound files, including
compiler intermediates. Classification never excludes files from the audit or
identifies the mechanism responsible for a missing file.
The HIL input inspection reads only fpga/board_hil.json, never invokes commands
from it, and never builds, programs or contacts hardware. Exit zero establishes
only that a nonempty command is configured without enabled native configuration
actions that build, copy RTL or flash hardware. It does not inspect the command's
own side effects or establish transport correctness,
programmed-image provenance, independent admission or hardware acceptance.
With --hil-output, also reject an occupied or non-project evidence destination.
This only inventories the admitted output contract; it never creates, removes
or renames that destination, and cannot authorize a different invocation.
Portable-input inspection compares readable declared files in a nominated
project-relative execution root with the current sources and checks both
mandatory portable destinations for occupation, including dangling symlinks.
It neither stages a root nor executes checks. A successful preflight establishes
only source identity and fresh destinations, not maintenance admission, tool
availability, functional results, hardware readiness or permission to resume.
Fresh-root staging copies only the current declared inputs, never historical
outputs or runtime metadata, and retains a source inventory and root mapping.
It refuses an occupied root and never launches checks or hardware commands.
The shared runtime must execute both unchanged mandatory commands in that actual
source root, in order; a launch-directory change without source copies is not
sufficient. Staging is preparation, not current portable or physical acceptance.
HIL receipt inspection diagnoses retained register-only runs without executing
hardware. A claimed native pass is reported separately from product acceptance.
Unrecognized output remains unestablished, never inferred to be byte comparisons.
This diagnostic does not define a new hardware transport or acceptance schema.
"""

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify import (CAPACITIES, DECLARED, ROOT, SEEDS, file_integrity, inputs,
                    json_write, validate_output)


def source_binding_errors(sources):
    """Compare historical bindings without changing the historical outcome."""
    if not isinstance(sources, dict) or not sources:
        return ["Missing or invalid source bindings"]
    try:
        current = inputs()
    except (OSError, AssertionError) as error:
        return [str(error)]
    errors = []
    for source in sorted(set(sources) | set(current)):
        if source not in sources:
            detail = "Current input absent from retained bindings"
        elif source not in current:
            detail = "Retained input absent from current declared inputs"
        elif sources[source] != current[source]:
            detail = "Current input differs from retained binding"
        else:
            continue
        errors.append(f"{detail}: {source}")
    return errors


def audit_artifacts(bundle, bindings):
    """Validate an optional manifest without repairing or creating any files."""
    report = dict(present=bindings is not None, checked_files=0, expected_files=0,
                  missing_files=[], mismatched_files=[], unbound_files=[], errors=[])
    if bindings is None:
        return report
    if not isinstance(bindings, dict) or not bindings:
        report["errors"].append("Invalid or empty artifact integrity manifest")
        return report
    report["expected_files"] = len(bindings)
    base = ROOT / bundle
    try:
        actual = {path.relative_to(ROOT).as_posix()
                  for path in base.rglob("*") if path.is_file()
                  and path != base / "receipt.json"}
        report["unbound_files"] = sorted(actual - set(bindings))
        for name in report["unbound_files"]:
            report["errors"].append(f"Unbound retained artifact: {name}")
    except OSError as error:
        report["errors"].append(f"Cannot inventory retained artifacts: {error}")
    for name, binding in bindings.items():
        try:
            if not isinstance(name, str) or not name:
                raise ValueError("Invalid artifact path")
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts
                    or not path.is_relative_to(bundle)
                    or not (ROOT / path).resolve().is_relative_to(base.resolve())
                    or path == bundle / "receipt.json"):
                raise ValueError(f"Artifact outside nominated bundle or self-bound: {name}")
            if (not isinstance(binding, dict)
                    or type(binding.get("bytes")) is not int
                    or binding["bytes"] < 0
                    or not isinstance(binding.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]) is None):
                raise ValueError(f"Invalid artifact integrity binding: {name}")
            if file_integrity(ROOT / path) != binding:
                report["mismatched_files"].append(name)
                raise ValueError(f"Artifact integrity mismatch: {name}")
            report["checked_files"] += 1
        except FileNotFoundError as error:
            report["missing_files"].append(name)
            report["errors"].append(str(error))
        except (OSError, ValueError) as error:
            report["errors"].append(str(error))
    return report


def audit_bundle(name, source_diff=False):
    """Inspect retained files only; availability never authorizes a rerun."""
    report = dict(path=name, errors=[], child_receipts=0, raw_streams=0,
                  snapshot_files=0, generated_sources=0, matrix_passed=0,
                  bound_raw_streams=0, unbound_raw_streams=0,
                  artifact_integrity_present=False, bound_artifacts=0,
                  current_sources_match=None, source_binding_errors=[],
                  components=[], missing_components=[],
                  matrix_required=len(CAPACITIES) * len(SEEDS))
    errors = report["errors"]

    def local(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Expected a nonempty project-relative path")
        path = Path(value)
        if (path.is_absolute() or ".." in path.parts
                or not path.resolve().is_relative_to(ROOT / "evidence")):
            raise ValueError(f"Audit path must remain inside evidence/: {value}")
        return path

    def read_record(path):
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError(f"Not a JSON object: {path}")
        return value

    def check_file(path, digest=None):
        payload = path.read_bytes()
        if digest is not None and hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError(f"Hash mismatch: {path}")

    try:
        bundle = local(name)
        for suffix, kind in (("", "directory"), ("receipt.json", "file"),
                             ("results.json", "file"), ("source", "directory"),
                             ("commands", "directory")):
            path = local((bundle / suffix).as_posix())
            present = path.is_file() if kind == "file" else path.is_dir()
            component = dict(path=path.as_posix(), kind=kind, present=present)
            report["components"].append(component)
            if present:
                try:
                    if kind == "directory":
                        component["entries"] = sorted(child.name for child in path.iterdir())
                        component["empty"] = not component["entries"]
                        if component["empty"]:
                            errors.append(f"Empty required directory: {path}")
                    else:
                        payload = path.read_bytes()
                        component["bytes"] = len(payload)
                        component["sha256"] = hashlib.sha256(payload).hexdigest()
                except OSError as error:
                    errors.append(f"Cannot inventory component {path}: {error}")
            if not present:
                report["missing_components"].append(path.as_posix())
                errors.append(f"Missing required {kind}: {path}")
        receipt = read_record(bundle / "receipt.json")
        if receipt.get("kind") != "portable-verifier":
            raise ValueError(f"Not a portable-verifier bundle: {name}")
        artifacts = audit_artifacts(bundle, receipt.get("artifact_integrity"))
        report["artifact_integrity"] = artifacts
        report["artifact_integrity_present"] = artifacts["present"]
        report["bound_artifacts"] = artifacts["checked_files"]
        errors.extend(artifacts["errors"])
        results_path = local(receipt["results"])
        if results_path != bundle / "results.json":
            raise ValueError(f"Results outside nominated bundle: {results_path}")
        results = read_record(results_path)
        report["recorded_outcome"] = results.get("outcome")
        expected = {(c, s) for c in CAPACITIES for s in SEEDS}
        matrix = results["mandatory_matrix"]
        keys = [(row["capacity"], row["seed"]) for row in matrix]
        if len(keys) != len(expected) or set(keys) != expected:
            errors.append("Mandatory matrix has missing, duplicate or unexpected entries")
        report["matrix_passed"] = sum(row["outcome"] == "passed" for row in matrix)
        report["matrix_incomplete"] = [row for row in matrix if row["outcome"] != "passed"]
        sources = receipt["source_sha256"]
        if not isinstance(sources, dict) or not sources:
            raise ValueError("Missing source snapshot bindings")
        report["source_binding_errors"] = source_binding_errors(sources)
        report["current_sources_match"] = not report["source_binding_errors"]
        current = inputs()
        if source_diff:
            report["source_deltas"] = []

        def append_delta(source, before, after):
            if before == after:
                return
            report["source_deltas"].append(dict(
                path=source,
                change="added" if before is None else
                       "removed" if after is None else "modified",
                unified_diff="".join(difflib.unified_diff(
                    (before or b"").decode("utf-8").splitlines(keepends=True),
                    (after or b"").decode("utf-8").splitlines(keepends=True),
                    fromfile=f"retained/{source}" if before is not None else "/dev/null",
                    tofile=f"current/{source}" if after is not None else "/dev/null"))))

        for source, digest in sources.items():
            path = local((bundle / "source" / source).as_posix())
            try:
                check_file(path, digest)
                report["snapshot_files"] += 1
                if source_diff:
                    append_delta(source, path.read_bytes(),
                                 (ROOT / source).read_bytes() if source in current else None)
            except (OSError, ValueError) as error:
                errors.append(str(error))
        if source_diff:
            for source in sorted(set(current) - set(sources)):
                try:
                    append_delta(source, None, (ROOT / source).read_bytes())
                except (OSError, ValueError) as error:
                    errors.append(str(error))
        children = receipt["children"]
        if not isinstance(children, list) or not children:
            raise ValueError("Missing child receipt index")
        for child_name in children:
            try:
                child_path = local(child_name)
                if not child_path.is_relative_to(bundle / "commands"):
                    raise ValueError(f"Child outside nominated commands: {child_name}")
                child = read_record(child_path)
                if child["source_sha256"] != sources:
                    raise ValueError(f"Inconsistent source bindings: {child_name}")
                if child["exit_code"] is None or child["timed_out"]:
                    errors.append(f"Unsettled or timed-out child: {child_name}")
                report["child_receipts"] += 1
                for channel in ("stdout", "stderr"):
                    stream = local(child[channel])
                    if stream.parent != child_path.parent:
                        raise ValueError(f"Stream outside child directory: {stream}")
                    check_file(stream)
                    report["raw_streams"] += 1
                    if "stream_integrity" in child:
                        binding = child["stream_integrity"][channel]
                        check_file(stream, binding["sha256"])
                        if stream.stat().st_size != binding["bytes"]:
                            raise ValueError(f"Raw stream size mismatch: {stream}")
                        report["bound_raw_streams"] += 1
                    else:
                        report["unbound_raw_streams"] += 1
                for generated, digest in child["generated_source_sha256"].items():
                    if generated in sources:
                        if digest != sources[generated]:
                            raise ValueError(f"Inconsistent input binding: {generated}")
                        path = local((bundle / "source" / generated).as_posix())
                    else:
                        path = local(generated)
                    check_file(path, digest)
                    report["generated_sources"] += 1
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(f"{child_name}: {error}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(str(error))
    report["retained_files_readable"] = not errors
    return report


def repair_receipt(name):
    """Require retained predecessor metadata and streams, not just a filename."""
    prior = Path(name)
    if prior.is_absolute() or ".." in prior.parts:
        raise ValueError("--repair-of must name a project-relative receipt")
    if not prior.resolve().is_relative_to(ROOT):
        raise ValueError("--repair-of must remain inside this project")
    try:
        payload = prior.read_bytes()
        record = json.loads(payload)
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read repair predecessor {name}: {error}") from error
    if not isinstance(record, dict):
        raise ValueError(f"Repair predecessor is not a receipt object: {name}")
    required = ("argv", "cwd", "source_sha256", "tool_versions",
                "start_time", "end_time", "timed_out", "exit_code", "stdout", "stderr")
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError(f"Incomplete repair predecessor {name}: missing {', '.join(missing)}")
    for channel in ("stdout", "stderr"):
        value = record[channel]
        if not isinstance(value, str) or not value:
            raise ValueError(f"Invalid {channel} path in repair predecessor {name}")
        stream = Path(value)
        if (stream.is_absolute() or ".." in stream.parts
                or not stream.resolve().is_relative_to(ROOT)):
            raise ValueError(f"Non-project {channel} path in repair predecessor {name}")
        if not stream.is_file():
            raise ValueError(f"Repair predecessor raw stream missing: {stream.as_posix()}")
        if "stream_integrity" in record:
            integrity = record["stream_integrity"]
            binding = integrity.get(channel) if isinstance(integrity, dict) else None
            if (not isinstance(binding, dict)
                    or type(binding.get("bytes")) is not int
                    or binding["bytes"] < 0
                    or not isinstance(binding.get("sha256"), str)
                    or len(binding["sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in binding["sha256"])):
                raise ValueError(f"Invalid {channel} integrity binding in repair predecessor {name}")
            try:
                data = stream.read_bytes()
            except OSError as error:
                raise ValueError(
                    f"Cannot read repair predecessor raw stream {stream.as_posix()}: {error}"
                ) from error
            if (len(data) != binding["bytes"]
                    or hashlib.sha256(data).hexdigest() != binding["sha256"]):
                raise ValueError(
                    f"Repair predecessor raw stream integrity mismatch: {stream.as_posix()}"
                )
    return hashlib.sha256(payload).hexdigest()


def audit_receipt(name):
    """Keep retained-log availability distinct from the recorded tool result."""
    report = dict(path=name)
    try:
        report["receipt_sha256"] = repair_receipt(name)
        record = json.loads((ROOT / name).read_bytes())
    except (OSError, ValueError) as error:
        report.update(available=False, error=str(error))
        return report
    code = record["exit_code"]
    timed_out = record["timed_out"]
    if timed_out is True:
        outcome = "timed-out"
    elif timed_out is not False or (code is not None and type(code) is not int):
        outcome = "invalid-result"
    elif record.get("launch_error"):
        outcome = "launch-failed"
    elif code is None:
        outcome = "unsettled"
    elif code == 0:
        outcome = "succeeded"
    else:
        outcome = "failed"
    report.update(available=True, recorded_execution=dict(
        argv=record["argv"], cwd=record["cwd"], exit_code=code,
        timed_out=timed_out, outcome=outcome,
        source_unchanged=record.get("source_unchanged"),
        tool_versions=record["tool_versions"],
        stdout=record["stdout"], stderr=record["stderr"]))
    source_errors = source_binding_errors(record["source_sha256"])
    report["current_sources_match"] = not source_errors
    report["source_binding_errors"] = source_errors
    return report


def inspect_hil_inputs(root=ROOT, output=None):
    """Inventory the supported product-command input without executing it."""
    path = root / "fpga/board_hil.json"
    report = dict(kind="read-only-hil-input-inventory",
                  path="fpga/board_hil.json", acceptance_evidence=False,
                  authorizes_resumption=False, hardware_executed=False,
                  product_command_configured=False,
                  configuration_actions=[], errors=[])
    if output is not None:
        destination = Path(output)
        contract = dict(path=str(output), fresh=False)
        report["output_contract"] = contract
        try:
            if (destination.is_absolute() or ".." in destination.parts
                    or not destination.is_relative_to("evidence")
                    or destination == Path("evidence")
                    or not (root / destination).resolve().is_relative_to(
                        (root / "evidence").resolve())):
                raise ValueError("HIL output must be a project-relative path inside evidence/")
            # A dangling symlink is occupied too; do not follow it or replace it.
            if os.path.lexists(root / destination):
                raise ValueError(
                    "HIL output is occupied; preserve it and request independently "
                    "reviewed replanning, not an unchanged retry")
            contract["fresh"] = True
        except (OSError, ValueError) as error:
            report["errors"].append(str(error))
    try:
        payload = path.read_bytes()
        report["configuration_integrity"] = dict(
            bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        config = json.loads(payload)
        if not isinstance(config, dict):
            raise ValueError("Board HIL configuration must be a JSON object")
        command = config.get("remote_test_cmd")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Missing nonempty remote_test_cmd")
        report["product_command_configured"] = True
        report["deployment_fields_present"] = sorted(
            key for key in ("bedrock_project_dir", "remote_rpd_win_path",
                            "sync_rtl_to_dir", "local_build_and_flash_cmd",
                            "force_flash") if config.get(key))
        if config.get("bedrock_project_dir"):
            report["configuration_actions"].append("bedrock_build")
            if config.get("remote_rpd_win_path"):
                report["configuration_actions"].append("transfer_and_flash")
        else:
            if config.get("sync_rtl_to_dir"):
                report["configuration_actions"].append("copy_rtl")
            if config.get("local_build_and_flash_cmd"):
                report["configuration_actions"].append("local_build_and_flash")
        if report["configuration_actions"]:
            report["errors"].append(
                "Configured native HIL actions conflict with the no-deployment "
                "work order: " + ", ".join(report["configuration_actions"]))
    except (OSError, ValueError) as error:
        report["errors"].append(f"Cannot establish product-command input: {error}")
    report["unverified_requirements"] = [
        "Supported physical BELLOWS traffic transport",
        "Readable programmed-image binding to accepted sources",
        "Fresh shared-runtime prerequisite evidence",
        "Independent admission of adapter ownership, invocation and fresh outputs",
        "Three consecutive byte-exact physical compression, decompression, simultaneous-duplex and internal-round-trip passes",
    ]
    return report


def inspect_hil_receipt(name):
    """Identify a known insufficient HIL result, never certify unknown traffic."""
    report = dict(kind="read-only-hil-receipt-diagnostic",
                  path=name, acceptance_evidence=False,
                  authorizes_resumption=False, hardware_executed=False,
                  physical_acceptance_established=False,
                  recorded_status=None, runs=[], errors=[])
    try:
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts
                or not path.is_relative_to("evidence")
                or not (ROOT / path).resolve().is_relative_to(
                    (ROOT / "evidence").resolve())):
            raise ValueError("HIL receipt must remain inside project evidence/")
        payload = (ROOT / path).read_bytes()
        report["receipt_integrity"] = dict(
            bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        record = json.loads(payload)
        if not isinstance(record, dict) or record.get("gate") != "board-hil":
            raise ValueError("Expected a native board-hil receipt object")
        report["recorded_status"] = record.get("status")
        runs = record.get("runs")
        if not isinstance(runs, list) or not runs:
            raise ValueError("Missing retained HIL runs")
        for index, run in enumerate(runs, 1):
            if not isinstance(run, dict):
                raise ValueError(f"Invalid HIL run {index}")
            stdout = run.get("stdout")
            stderr = run.get("stderr")
            if not isinstance(stdout, str) or not isinstance(stderr, str):
                raise ValueError(f"Missing raw HIL streams for run {index}")
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            register_reads = sum(bool(re.fullmatch(
                r"Read register \d+ \(0x[0-9a-fA-F]+\): \d+ \(0x[0-9a-fA-F]+\)",
                line)) for line in lines)
            register_only = register_reads > 0 and all(
                re.fullmatch(
                    r"Read register \d+ \(0x[0-9a-fA-F]+\): \d+ \(0x[0-9a-fA-F]+\)",
                    line)
                or re.fullmatch(r"FPGA diagnostics total time: [0-9.]+ seconds", line)
                for line in lines)
            report["runs"].append(dict(
                ordinal=index, recorded_index=run.get("run_index"),
                exit_code=run.get("exit_code"), recorded_passed=run.get("passed"),
                register_reads=register_reads, register_only=register_only,
                stdout_bytes=len(stdout.encode()), stderr_bytes=len(stderr.encode()),
                traffic_comparisons="unestablished"))
        report["register_only_runs"] = sum(
            run["register_only"] for run in report["runs"])
        report["diagnosis"] = (
            "Register responsiveness is not BELLOWS traffic verification"
            if report["register_only_runs"] else
            "Retained output requires independent product-traffic review")
    except (OSError, ValueError) as error:
        report["errors"].append(str(error))
    return report


def inspect_portable_inputs(name=".", reference=ROOT):
    """Check a maintenance-staged root without copying inputs or running checks."""
    report = dict(kind="read-only-portable-input-inventory",
                  acceptance_evidence=False, authorizes_resumption=False,
                  root_mapping=dict(source_root=".", execution_root=str(name)),
                  current_sources_match=False, portable_preflight_passed=False,
                  source_sha256={}, outputs=[], errors=[])
    errors = report["errors"]
    try:
        relative_root = Path(name)
        if (relative_root.is_absolute() or ".." in relative_root.parts
                or any(part in (".vulcan", ".git", ".tooling", "VULCAN")
                       for part in relative_root.parts)):
            raise ValueError("Execution root must be a non-runtime project-relative directory")
        root = reference / relative_root
        if not root.resolve().is_relative_to(reference.resolve()):
            raise ValueError("Execution root resolves outside the project")
        if not root.is_dir():
            raise ValueError("Execution root is not an existing readable directory")
        current = inputs(reference)
        paths = {path for pattern in DECLARED for path in root.glob(pattern)}
        for path in paths:
            if any(candidate.is_symlink() for candidate in (path, *path.parents)
                   if candidate != reference and candidate.is_relative_to(reference)):
                raise ValueError(
                    f"Declared source depends on a symlink: {path.relative_to(root)}")
        staged = inputs(root)
        report["source_sha256"] = staged
        for source in sorted(set(current) | set(staged)):
            if source not in staged:
                errors.append(f"Missing declared source: {source}")
            elif source not in current:
                errors.append(f"Unexpected declared source: {source}")
            elif current[source] != staged[source]:
                errors.append(f"Declared source differs from current input: {source}")
        report["current_sources_match"] = not errors
        for destination in ("evidence/l1", "evidence/l1-post-settlement-bundle-audit"):
            path = root / destination
            occupied = os.path.lexists(path)
            output = dict(path=destination, fresh=not occupied)
            report["outputs"].append(output)
            try:
                validate_output(Path(destination), root=root)
            except ValueError as error:
                errors.append(f"Mandatory output rejected; preserve it: {error}")
        report["portable_preflight_passed"] = not errors
    except (OSError, ValueError, AssertionError) as error:
        errors.append(str(error))
    return report


def stage_portable_root(name, reference=ROOT):
    """Create an append-only declared-input copy for shared-runtime execution."""
    relative_root = Path(name)
    if (relative_root.is_absolute() or ".." in relative_root.parts
            or not relative_root.is_relative_to("evidence")
            or relative_root == Path("evidence")
            or any(part in (".vulcan", ".git", ".tooling", "VULCAN")
                   for part in relative_root.parts)):
        raise ValueError("Staging root must be a non-runtime path inside evidence/")
    root = reference / relative_root
    if not root.resolve().is_relative_to(reference.resolve()):
        raise ValueError("Staging root resolves outside the project")
    for candidate in (root, *root.parents):
        if candidate == reference:
            break
        if candidate.is_symlink():
            raise ValueError("Staging root must not depend on symlinks")
    if os.path.lexists(root):
        raise ValueError("Occupied staging root; preserve it and select a fresh root")
    sources = inputs(reference)
    for name in sources:
        source = reference / name
        for candidate in (source, *source.parents):
            if candidate == reference:
                break
            if candidate.is_symlink():
                raise ValueError(f"Declared source depends on a symlink: {name}")
    root.mkdir(parents=True, exist_ok=False)
    record = dict(
        kind="declared-input-root-staging", acceptance_evidence=False,
        argv=["python3", "tests/preparation.py", "--stage-portable-root",
              relative_root.as_posix()],
        cwd=".", root_mapping=dict(source_root=".",
                                  execution_root=relative_root.as_posix()),
        source_sha256=sources, staged_source_sha256={},
        start_time=datetime.now(timezone.utc).isoformat(),
        tool_versions={"python3": sys.version}, timeout_s=None,
        timed_out=False, exit_code=None, children=[],
        checks_executed=False, hardware_executed=False,
        mandatory_commands=[
            ["python3", "tests/verify.py", "--output", "evidence/l1"],
            ["sh", "-c", "mkdir evidence/l1-post-settlement-bundle-audit && "
             "python3 tests/preparation.py --audit-bundles evidence/l1 > "
             "evidence/l1-post-settlement-bundle-audit/stdout.json 2> "
             "evidence/l1-post-settlement-bundle-audit/stderr.log"],
        ],
        stdout=(relative_root / "staging.stdout.log").as_posix(),
        stderr=(relative_root / "staging.stderr.log").as_posix(),
    )
    error = None
    try:
        for name, digest in sources.items():
            payload = (reference / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f"Source changed before copy: {name}")
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(payload)
        record["staged_source_sha256"] = inputs(root)
        if record["staged_source_sha256"] != sources or inputs(reference) != sources:
            raise ValueError("Sources changed during staging")
        record["preflight"] = inspect_portable_inputs(
            relative_root.as_posix(), reference=reference)
        if not record["preflight"]["portable_preflight_passed"]:
            raise ValueError("Staged portable-input preflight failed")
        record["exit_code"] = 0
    except (OSError, ValueError, AssertionError) as failure:
        error = f"{type(failure).__name__}: {failure}"
        record.update(exit_code=1, error=error)
    record["end_time"] = datetime.now(timezone.utc).isoformat()
    for channel, text in (("stdout", "Declared inputs staged; no checks executed.\n"
                          if error is None else ""),
                          ("stderr", error + "\n" if error else "")):
        path = root / f"staging.{channel}.log"
        with path.open("x") as handle:
            handle.write(text)
    record["stream_integrity"] = {
        channel: file_integrity(root / f"staging.{channel}.log")
        for channel in ("stdout", "stderr")
    }
    json_write(root / "staging-receipt.json", record)
    if error is not None:
        raise ValueError(
            f"{error}; retained {relative_root.as_posix()}/staging-receipt.json")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--subset",
                        choices=("targeted", "ratio-focused", "reproduce", "boundary-focused",
                                 "extreme-focused", "final-focused", "overflow-focused",
                                 "backend-focused", "output-focused"))
    operation.add_argument("--audit-receipts", nargs="+", metavar="RECEIPT")
    operation.add_argument("--audit-bundles", nargs="+", metavar="BUNDLE")
    operation.add_argument("--inspect-hil-inputs", action="store_true")
    operation.add_argument("--inspect-hil-receipt", metavar="PROJECT_RELATIVE_RECEIPT")
    operation.add_argument("--inspect-portable-inputs", nargs="?", const=".",
                           metavar="PROJECT_RELATIVE_ROOT")
    operation.add_argument("--stage-portable-root", metavar="PROJECT_RELATIVE_ROOT")
    parser.add_argument("--hil-output", metavar="PROJECT_RELATIVE_PATH",
                        help="read-only fresh-output inspection with --inspect-hil-inputs")
    parser.add_argument("--source-diff", action="store_true",
                        help="include readable snapshot changes with --audit-bundles")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    if args.hil_output is not None and not args.inspect_hil_inputs:
        parser.error("--hil-output applies only to --inspect-hil-inputs")
    if args.source_diff and not args.audit_bundles:
        parser.error("--source-diff applies only to --audit-bundles")
    os.chdir(ROOT)
    if args.inspect_hil_receipt is not None:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        report = inspect_hil_receipt(args.inspect_hil_receipt)
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        # Exit zero means the diagnostic is readable, not physical acceptance.
        return 0 if not report["errors"] else 1
    if args.stage_portable_root is not None:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        try:
            report = stage_portable_root(args.stage_portable_root)
        except (OSError, ValueError, AssertionError) as error:
            parser.exit(1, f"{error}\n")
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.inspect_portable_inputs is not None:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        report = inspect_portable_inputs(args.inspect_portable_inputs)
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if report["portable_preflight_passed"] else 1
    if args.inspect_hil_inputs:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        report = inspect_hil_inputs(output=args.hil_output)
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if report["product_command_configured"] and not report["errors"] else 1
    if args.audit_bundles:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        records = [audit_bundle(name, source_diff=args.source_diff) for name in args.audit_bundles]
        readable = all(record["retained_files_readable"] for record in records)
        current = all(record["current_sources_match"] is True for record in records)
        json.dump(dict(kind="read-only-bundle-inventory",
                       acceptance_evidence=False, acceptance_credit=0,
                       authorizes_resumption=False, retained_files_readable=readable,
                       current_sources_match=current,
                       bundles=records), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if readable and current else 1
    if args.audit_receipts:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        records = [audit_receipt(name) for name in args.audit_receipts]
        complete = all(record["available"] for record in records)
        json.dump(dict(kind="read-only-receipt-inventory",
                       acceptance_evidence=False, acceptance_credit=0,
                       authorizes_resumption=False, complete=complete,
                       receipts=records), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if complete else 1
    prior_digest = None
    if args.repair_of:
        try:
            prior_digest = repair_receipt(args.repair_of)
        except ValueError as error:
            parser.error(str(error))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path("evidence/preparation") / f"verifier-{args.subset}-{stamp}-{uuid.uuid4().hex[:8]}"
    out.mkdir(parents=True)
    argv = ["python3", "tests/verify.py", "--output", (out / "result").as_posix(),
            "--subset", args.subset]
    record = dict(kind="bounded-verifier-preparation", acceptance_evidence=False,
                  argv=argv, cwd=".", timeout_s=18000, start_time=datetime.now(
                      timezone.utc).isoformat(), source_sha256=inputs(),
                  stdout=(out / "stdout.log").as_posix(),
                  stderr=(out / "stderr.log").as_posix(),
                  timed_out=False, exit_code=None, repair_of=args.repair_of)
    if args.repair_of:
        record["repair_of_sha256"] = prior_digest
    json_write(out / "launch.json", record)
    start = time.monotonic()
    with (out / "stdout.log").open("xb") as stdout, (out / "stderr.log").open("xb") as stderr:
        try:
            process = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
        except OSError as error:
            record["launch_error"] = f"{type(error).__name__}: {error}"
            stderr.write((record["launch_error"] + "\n").encode())
        else:
            try:
                record["exit_code"] = process.wait(timeout=18000)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                record["exit_code"] = process.returncode
    record["end_time"] = datetime.now(timezone.utc).isoformat()
    record["duration_s"] = time.monotonic() - start
    record["source_unchanged"] = inputs() == record["source_sha256"]
    versions = out / "result/tool-versions.json"
    record["tool_versions"] = json.loads(versions.read_text()) if versions.exists() else {}
    record["child_receipt"] = (out / "result/receipt.json").as_posix()
    json_write(out / "receipt.json", record)
    print((out / "receipt.json").as_posix())
    print((out / "stdout.log").read_text(), end="")
    print((out / "stderr.log").read_text(), end="", file=sys.stderr)
    return 1 if record["timed_out"] or "launch_error" in record else record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
