#!/usr/bin/env python3
"""Retain one bounded advisory probe; never run the full admitted matrix here.

    python3 tests/preparation.py --subset targeted
    python3 tests/preparation.py --subset backend-focused
    python3 tests/preparation.py --subset output-focused
    python3 tests/preparation.py --subset harness-focused
    python3 tests/preparation.py --subset ratio-focused --repair-of <receipt>
    python3 tests/preparation.py --audit-receipts <receipt> [<receipt> ...]
    python3 tests/preparation.py --audit-receipts <receipt> --require-current-sources
    python3 tests/preparation.py --audit-bundles evidence/l1 [<bundle> ...]
    python3 tests/preparation.py --audit-bundles evidence/l1 --source-diff
    python3 tests/preparation.py --inspect-hil-inputs
    python3 tests/preparation.py --inspect-hil-receipt evidence/retained-hil.json
    python3 tests/preparation.py --inspect-hil-inputs --hil-output evidence/native-board-hil-recovery-0120.json
    python3 tests/preparation.py --inspect-portable-inputs
    python3 tests/preparation.py --inspect-portable-inputs evidence/maintenance-root
    python3 tests/preparation.py --inspect-portable-inputs evidence/maintenance-root --source-diff
    python3 tests/preparation.py --stage-portable-root evidence/fresh-portable/project

Repair links require predecessor metadata and both raw streams before launch.
This local check does not establish historical authenticity or authorize resumption.
The read-only audit writes JSON to stdout, creates no evidence, launches no children
and grants no acceptance credit. Missing history requires independent disposition;
an audit is not a replacement receipt or permission to resume paused verification.
Receipt-audit exit zero means metadata and logs are available, not that the
recorded commands passed. Each readable receipt separately reports its recorded
execution outcome; unknown or unsettled outcomes are never labeled successful.
When probe_exit_code is recorded, the enclosing probe outcome is reported
separately: a successful child does not hide a failed final source inventory.
Probe success requires a successful child and an explicitly unchanged inventory;
legacy receipts without a probe result do not acquire an invented one.
An optional launch_error must be null/absent for success, or a nonempty string
for a launch failure; false-valued malformed fields are invalid, not success.
Receipt audits also report source currency separately from historical execution:
a successful prerequisite from an older source set is not a current passing check.
With --require-current-sources, unavailable receipts or stale source bindings make
the receipt audit exit nonzero. The default remains an availability diagnostic.
Neither mode upgrades the recorded execution result or authorizes resumption.
Bundle audits separately report readability and binding to current declared inputs;
a readable historical bundle is not necessarily evidence for the current sources.
Current input bindings are rechecked after child inspection; a changed or unavailable
source inventory invalidates currency without relabeling historical files as lost.
An initially unavailable source inventory also leaves artifact and child inspection
running, retaining the loss inventory and platform handoff without source deltas.
Optional --source-diff includes readable unified source changes from hash-checked
snapshots. It never rebases a receipt, excuses a changed binding or grants reuse.
The component inventory runs even when the top-level receipt is missing, so a
restoration request distinguishes an absent bundle from a partial restoration.
Present component files are fingerprinted and directory entries listed before
receipt validation. These observations identify restored material, not its
historical authenticity, completeness or authorization to resume verification.
New child receipts also bind the byte counts and hashes of both raw streams;
legacy receipts remain readable but are reported as lacking stream bindings.
The outer bounded-probe receipt also binds both synchronized raw streams,
including failed children; changed logs cannot serve as repair predecessors.
Repair-predecessor audits validate any recorded stream bindings as well: a
present but truncated or changed log is not an available repair predecessor.
Predecessor receipts, streams and their project-local ancestors must not be
symlinks, including same-byte redirects and legacy streams without bindings.
Paths are checked before reading; this does not prevent concurrent replacement.
Bounded probes fail if their final declared-source inventory changes or becomes
unreadable, even when the child exits zero. The receipt preserves the child
exit_code separately from probe_exit_code and retains the source error in stderr.
New bundle receipts bind all retained artifacts, not just sources and raw streams.
The audit checks their exact file inventory, sizes and hashes; legacy bundles
are explicitly reported as lacking these bindings. Readable legacy metadata
is still inspected, but cannot make --audit-bundles succeed without an artifact
manifest. artifact_manifest_verified means a complete integrity observation,
not post-settlement retention, historical authenticity or permission to resume.
Neither kind of receipt
proves that files remain available after the audit's own process settles.
Artifact diagnostics distinguish missing, changed and unbound files, including
compiler intermediates. Classification never excludes files from the audit or
identifies the mechanism responsible for a missing file.
Missing artifacts include their validated original sizes and hashes, total byte
count and bundle-relative directory groups for an authentic-archive recovery
request. This inventory does not restore files or authorize regeneration.
Malformed child generated-source indexes fail explicitly without aborting the
remaining child inspection or the independent artifact-loss inventory.
Receipt-declared recovery archives are inspected without extraction: every member
must match the original manifest, with no duplicate, redirected or extra members.
Matching archived bytes identify a possible recovery source, not historical
authenticity, restored originals, a retention remedy or permission to resume.
Suffix groups compare validated manifest counts/bytes with missing counts/bytes
to expose selective loss, including compiler intermediates. Suffixes are descriptive,
not exemptions or evidence of which process removed a file.
Bundle diagnostics include a platform-owner handoff even if the receipt is
absent. It separates artifact availability, source currency and unestablished
post-settlement retention; a readable bundle never certifies a platform remedy.
Artifact audits repeat the inventory and re-read initially matching files before
returning; disappearance or mutation during the audit fails explicitly. This
bounded stability observation cannot establish persistence after process settlement.
The closing inventory follows the final content sweep as well, so additions,
removals and symlink substitutions during that sweep invalidate the observation.
The artifact sweep follows child, snapshot and current-source inspection, so
loss of an otherwise-unvisited synthesis artifact during those reads is detected.
The top-level receipt is separately re-read byte-for-byte before the audit returns;
its removal, replacement or symlink redirection invalidates the observation too.
Bundle, component, child-stream and snapshot paths are also checked for symlinks
before reading, rather than following a redirect and rejecting it only afterward.
Symlinked artifacts, directories and bundle ancestors are rejected, including
same-byte substitutions and redirects introduced between the two observations.
This matches the producer's no-symlink retention contract; it does not identify
the cause of historical artifact loss or authorize reconstructing missing files.
The HIL input inspection reads only fpga/board_hil.json, never invokes commands
from it, and never builds, programs or contacts hardware. Exit zero establishes
only a local inventory: symlinked configuration files or fpga directories are
rejected before reading, even if they redirect to identical bytes in the project.
This path preflight is not protection against concurrent filesystem replacement.
For a regular configuration, exit zero establishes
only that a nonempty command is configured without enabled native configuration
actions that build, copy RTL or flash hardware, including force_flash. It does not inspect the command's
own side effects or establish transport correctness,
programmed-image provenance, independent admission or hardware acceptance.
HIL receipt inspection fails for nonzero or invalid run exits, missing/false
run success, invalid raw streams and contradictory token checks. Failed or invalid
aggregate status and missing/non-true determinism also fail the diagnostic, even
when every individual run reports success. A readable
failed execution is not a successful native-execution diagnostic. Even three
consistent successful runs never establish product traffic or image provenance.
With --hil-output, also reject an occupied or non-project evidence destination.
An existing non-directory ancestor, including a dangling symlink, also makes
the destination unusable; inspection never removes it or creates directories.
The portable output guard also rejects symlinked parents and runtime-owned
path components, even when the evidence directory itself redirects elsewhere.
Existing non-directory parents also fail preflight for every affected output.
This only inventories the admitted output contract; it never creates, removes
or renames that destination, and cannot authorize a different invocation.
Portable-input inspection compares readable declared files in a nominated
project-relative execution root with the current sources and checks all three
mandatory portable destinations for occupation, including dangling symlinks.
Source identity uses direct byte comparisons; hashes are retained for provenance,
not used as a substitute for reading and comparing the copied contents.
Per-file comparisons identify the first differing byte, and both source inventories
are rechecked after all output-path inspections before reporting success, so changes
or source loss during output inspection fail explicitly.
Optional --source-diff adds readable staged-to-current source differences to those
same byte comparisons. It does not waive mismatches, occupied outputs or retention
prerequisites, and does not change or rebind either source tree.
Both current and staged source paths are checked for symlink redirection before
comparison and after the final inventories, including same-byte substitutions.
These bounded path observations do not prevent concurrent filesystem replacement.
All mandatory output destinations are reported even when source inspection fails;
an unavailable or rejected execution root never makes a destination look usable.
It neither stages a root nor executes checks. A successful preflight establishes
only source identity and fresh destinations, not maintenance admission, tool
availability, functional results, hardware readiness or permission to resume.
Fresh-root staging copies only the current declared inputs, never historical
outputs or runtime metadata, and retains a source inventory and root mapping.
It refuses an occupied root and never launches checks or hardware commands.
Copied files and their directory entries are synchronized before source preflight
and success recording; synchronization failures retain a failed staging receipt.
This crash-durability step does not establish a platform retention remedy or
protection against external deletion after the staging process settles.
The shared runtime must execute all three unchanged mandatory commands in that actual
source root, in order; a launch-directory change without source copies is not
sufficient. Staging is preparation, not current portable or physical acceptance.
HIL receipt inspection diagnoses retained register-only runs without executing
hardware. A claimed native pass is reported separately from product acceptance.
Receipt files and their ancestors must not be symlinks, even when they resolve
to identical bytes inside project evidence; rejected paths are not read.
This preflight does not protect against concurrent filesystem replacement.
Unrecognized output remains unestablished, never inferred to be byte comparisons.
The longest consecutive sequence counts only explicitly indexed, successful native
runs with complete raw streams and no contradictory recorded token failures.
Optional token-result fields, when present, must be empty lists; legacy receipts
without them remain diagnosable. Even three such runs establish no product traffic
or image provenance; the diagnostic never upgrades native outcomes to acceptance.
If requested_runs is recorded, it must be a positive integer matching the retained
run count and ordered indices 1..requested_runs. Missing or extra requested runs
cannot be hidden by a successful three-run subsequence. Legacy receipts without
the field remain diagnosable but do not establish completeness of a requested set.
The longest successful subsequence remains a historical count even when another
run or aggregate field fails. The three-run success flag requires an error-free
receipt as well as that count; it cannot conceal failures elsewhere in the set.
This diagnostic does not define a new hardware transport or acceptance schema.
Optional run execution metadata must not contradict a successful result: a
recorded timed_out must be exactly false and launch_error must be null. Absent
legacy fields remain diagnosable, not proof that timeout metadata was retained.
The same checks apply to optional aggregate execution metadata; clean individual
runs cannot conceal a timeout or launch failure of the enclosing execution.
An optional aggregate exit_code must be an integer zero, not a boolean or
coercible value. A failed, unsettled or malformed enclosing exit invalidates
the diagnostic even when all individual runs claim success.
HIL input inspection includes a Coordinator handoff for the shared-runtime
platform owner. Its requested protocol and image-provenance inputs are prerequisites
for independent admission, not a transport implementation or permission to run it.
Even a configured command leaves these obligations unverified. Missing physical
inputs must not trigger an unchanged portable rerun or a Designer repair request.
Run python3 -B tests/test_preparation.py for synthetic regressions of this safety
boundary. These tests never launch transport commands or certify hardware traffic.
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
import tarfile
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify import (CAPACITIES, DECLARED, ROOT, SEEDS, file_integrity, inputs,
                    json_write, sync_directory, validate_output)


PORTABLE_OUTPUTS = (
    "evidence/l1",
    "evidence/l1-post-settlement-bundle-audit",
    "evidence/l1-post-settlement-bundle-audit-after-0621",
)


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
                  rechecked_files=0, inventory_stable=False,
                  missing_files=[], missing_artifact_bindings={},
                  missing_bytes=0, missing_by_directory={},
                  artifacts_by_suffix={},
                  mismatched_files=[], unbound_files=[], errors=[])
    if bindings is None:
        return report
    if not isinstance(bindings, dict) or not bindings:
        report["errors"].append("Invalid or empty artifact integrity manifest")
        return report
    report["expected_files"] = len(bindings)
    base = ROOT / bundle
    initially_checked = []
    validated_bindings = {}
    actual = None

    def reject_symlinks(path):
        current = ROOT
        for part in path.relative_to(ROOT).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(
                    f"Symlink in retained artifact path: {current.relative_to(ROOT)}")

    def inventory():
        reject_symlinks(base)
        paths = list(base.rglob("*"))
        for path in paths:
            if path.is_symlink():
                raise ValueError(
                    f"Symlink in retained artifact inventory: {path.relative_to(ROOT)}")
        return {path.relative_to(ROOT).as_posix() for path in paths if path.is_file()
                and path != base / "receipt.json"}

    try:
        actual = inventory()
        report["unbound_files"] = sorted(actual - set(bindings))
        for name in report["unbound_files"]:
            report["errors"].append(f"Unbound retained artifact: {name}")
    except (OSError, ValueError) as error:
        report["errors"].append(f"Cannot inventory retained artifacts: {error}")
    for name, binding in bindings.items():
        try:
            if not isinstance(name, str) or not name:
                raise ValueError("Invalid artifact path")
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts
                    or not path.is_relative_to(bundle)
                    or path == bundle / "receipt.json"):
                raise ValueError(f"Artifact outside nominated bundle or self-bound: {name}")
            reject_symlinks(ROOT / path)
            if not (ROOT / path).resolve().is_relative_to(base.resolve()):
                raise ValueError(f"Artifact outside nominated bundle: {name}")
            if (not isinstance(binding, dict)
                    or type(binding.get("bytes")) is not int
                    or binding["bytes"] < 0
                    or not isinstance(binding.get("sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]) is None):
                raise ValueError(f"Invalid artifact integrity binding: {name}")
            validated_bindings[name] = dict(binding)
            suffix = Path(name).suffix
            group = report["artifacts_by_suffix"].setdefault(
                suffix, dict(expected_files=0, expected_bytes=0,
                             missing_files=0, missing_bytes=0))
            group["expected_files"] += 1
            group["expected_bytes"] += binding["bytes"]
            if file_integrity(ROOT / path) != binding:
                report["mismatched_files"].append(name)
                raise ValueError(f"Artifact integrity mismatch: {name}")
            report["checked_files"] += 1
            initially_checked.append(name)
        except FileNotFoundError as error:
            report["missing_files"].append(name)
            report["errors"].append(str(error))
        except (OSError, ValueError) as error:
            report["errors"].append(str(error))
    try:
        final_inventory = inventory()
        report["inventory_stable"] = actual is not None and final_inventory == actual
        if not report["inventory_stable"]:
            report["errors"].append("Artifact inventory changed during audit")
        for name in initially_checked:
            try:
                reject_symlinks(ROOT / name)
                if file_integrity(ROOT / name) != bindings[name]:
                    report["mismatched_files"].append(name)
                    raise ValueError(f"Artifact changed during audit: {name}")
                report["rechecked_files"] += 1
            except FileNotFoundError as error:
                report["missing_files"].append(name)
                report["errors"].append(f"Artifact disappeared during audit: {error}")
            except (OSError, ValueError) as error:
                report["errors"].append(str(error))
        closing_inventory = inventory()
        if closing_inventory != final_inventory:
            report["inventory_stable"] = False
            report["errors"].append("Artifact inventory changed during final content sweep")
            for name in sorted(closing_inventory - set(bindings)):
                if name not in report["unbound_files"]:
                    report["unbound_files"].append(name)
                    report["errors"].append(f"Unbound retained artifact: {name}")
            for name in initially_checked:
                if name not in closing_inventory and name not in report["missing_files"]:
                    report["missing_files"].append(name)
                    report["errors"].append(f"Artifact disappeared during final content sweep: {name}")
            report["unbound_files"].sort()
    except (OSError, ValueError) as error:
        report["inventory_stable"] = False
        report["errors"].append(f"Cannot re-inventory retained artifacts: {error}")
    for name in sorted(set(report["missing_files"])):
        binding = validated_bindings.get(name)
        if binding is None:
            continue
        report["missing_artifact_bindings"][name] = binding
        report["missing_bytes"] += binding["bytes"]
        group = report["artifacts_by_suffix"][Path(name).suffix]
        group["missing_files"] += 1
        group["missing_bytes"] += binding["bytes"]
        directory = Path(name).parent.relative_to(bundle).as_posix()
        group = report["missing_by_directory"].setdefault(
            directory, dict(files=0, bytes=0))
        group["files"] += 1
        group["bytes"] += binding["bytes"]
    return report


def audit_recovery_archive(bundle, receipt):
    """Compare a declared recovery copy without extracting or forgiving originals."""
    record = receipt.get("recovery_archive")
    report = dict(declared=record is not None, verified=False, checked_members=0,
                  original_files_required=True, authorizes_restoration=False,
                  platform_retention_remedy_established=False, errors=[])
    if record is None:
        return report
    try:
        archive = bundle / "retained-artifacts.tar.gz"
        if not isinstance(record, dict) or record.get("path") != archive.as_posix():
            raise ValueError("Recovery archive must be the nominated bundle's archive")
        for path in (ROOT / archive, *(ROOT / archive).parents):
            if path == ROOT:
                break
            if path.is_symlink():
                raise ValueError("Symlink in recovery archive path")
        bindings = receipt.get("artifact_integrity")
        if not isinstance(bindings, dict) or archive.as_posix() not in bindings:
            raise ValueError("Recovery archive lacks a historical integrity binding")
        before = file_integrity(ROOT / archive)
        if before != bindings[archive.as_posix()]:
            raise ValueError("Recovery archive integrity mismatch")
        expected = {}
        for name, binding in bindings.items():
            path = Path(name)
            if (path.is_absolute() or ".." in path.parts
                    or not path.is_relative_to(bundle)
                    or path == bundle / "receipt.json"):
                raise ValueError("Invalid original path in recovery archive manifest")
            if path != archive:
                if (not isinstance(binding, dict)
                        or type(binding.get("bytes")) is not int or binding["bytes"] < 0
                        or not isinstance(binding.get("sha256"), str)
                        or re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]) is None):
                    raise ValueError("Invalid original recovery archive binding")
                expected[path.relative_to(bundle).as_posix()] = binding
        if (type(record.get("members")) is not int
                or record["members"] != len(expected)):
            raise ValueError("Recovery archive recorded member count mismatch")
        seen = set()
        with tarfile.open(ROOT / archive, mode="r|gz") as retained:
            for member in retained:
                if (not member.isfile() or member.name not in expected
                        or member.name in seen):
                    raise ValueError(f"Unexpected or duplicate recovery member: {member.name}")
                binding = expected[member.name]
                if member.size != binding["bytes"]:
                    raise ValueError(f"Recovery member size mismatch: {member.name}")
                digest = hashlib.sha256()
                size = 0
                with retained.extractfile(member) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                if dict(bytes=size, sha256=digest.hexdigest()) != binding:
                    raise ValueError(f"Recovery member integrity mismatch: {member.name}")
                seen.add(member.name)
                report["checked_members"] += 1
        if seen != set(expected):
            raise ValueError("Recovery archive is missing original members")
        for path in (ROOT / archive, *(ROOT / archive).parents):
            if path == ROOT:
                break
            if path.is_symlink():
                raise ValueError("Symlink in recovery archive path")
        if file_integrity(ROOT / archive) != before:
            raise ValueError("Recovery archive changed during inspection")
        report["verified"] = True
    except (OSError, ValueError, TypeError, tarfile.TarError, EOFError) as error:
        report["errors"].append(str(error))
    return report


def audit_bundle(name, source_diff=False):
    """Inspect retained files only; availability never authorizes a rerun."""
    report = dict(path=name, errors=[], child_receipts=0, raw_streams=0,
                  snapshot_files=0, generated_sources=0, matrix_passed=0,
                  bound_raw_streams=0, unbound_raw_streams=0,
                  artifact_integrity_present=False, bound_artifacts=0,
                  receipt_stable=False,
                  current_source_inventory_stable=False,
                  current_sources_match=None, source_binding_errors=[],
                  components=[], missing_components=[],
                  matrix_required=len(CAPACITIES) * len(SEEDS))
    errors = report["errors"]
    receipt_path = None
    receipt_payload = None
    artifact_receipt = None
    current = None

    def local(value):
        if not isinstance(value, str) or not value:
            raise ValueError("Expected a nonempty project-relative path")
        path = Path(value)
        if (path.is_absolute() or ".." in path.parts
                or not path.parts or path.parts[0] != "evidence"):
            raise ValueError(f"Audit path must remain inside evidence/: {value}")
        current_path = ROOT
        for part in path.parts:
            current_path = current_path / part
            if current_path.is_symlink():
                raise ValueError(f"Symlink in bundle audit path: {current_path.relative_to(ROOT)}")
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
        receipt_path = bundle / "receipt.json"
        receipt_payload = receipt_path.read_bytes()
        receipt = json.loads(receipt_payload)
        if not isinstance(receipt, dict):
            raise ValueError(f"Not a JSON object: {receipt_path}")
        if receipt.get("kind") != "portable-verifier":
            raise ValueError(f"Not a portable-verifier bundle: {name}")
        artifact_receipt = receipt
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
        try:
            current = inputs()
        except (OSError, AssertionError) as error:
            report["source_binding_errors"].append(
                f"Cannot inventory current declared inputs: {error}")
            report["current_sources_match"] = False
        else:
            report["source_binding_errors"] = source_binding_errors(sources)
            report["current_sources_match"] = not report["source_binding_errors"]
        if source_diff and current is not None:
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
                if source_diff and current is not None:
                    append_delta(source, path.read_bytes(),
                                 (ROOT / source).read_bytes() if source in current else None)
            except (OSError, ValueError) as error:
                errors.append(str(error))
        if source_diff and current is not None:
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
                generated_sources = child["generated_source_sha256"]
                if not isinstance(generated_sources, dict):
                    raise ValueError("Invalid generated source index; expected an object")
                for generated, digest in generated_sources.items():
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
    if artifact_receipt is not None:
        archive = audit_recovery_archive(bundle, artifact_receipt)
        report["recovery_archive"] = archive
        errors.extend(archive["errors"])
        artifacts = audit_artifacts(bundle, artifact_receipt.get("artifact_integrity"))
        report["artifact_integrity"] = artifacts
        report["artifact_integrity_present"] = artifacts["present"]
        report["bound_artifacts"] = artifacts["checked_files"]
        errors.extend(artifacts["errors"])
    if receipt_payload is not None:
        try:
            for path in (receipt_path, *receipt_path.parents):
                if path.is_symlink():
                    raise ValueError(f"Symlink in bundle receipt path: {path}")
            if receipt_path.read_bytes() != receipt_payload:
                raise ValueError(f"Bundle receipt changed during audit: {receipt_path}")
            report["receipt_stable"] = True
        except (OSError, ValueError) as error:
            errors.append(f"Cannot recheck bundle receipt: {error}")
    if current is not None:
        try:
            report["current_source_inventory_stable"] = inputs() == current
            if not report["current_source_inventory_stable"]:
                report["source_binding_errors"].append(
                    "Current declared inputs changed during bundle audit")
        except (OSError, AssertionError) as error:
            report["source_binding_errors"].append(
                f"Cannot recheck current declared inputs: {error}")
        report["current_sources_match"] = (
            report["current_source_inventory_stable"]
            and not report["source_binding_errors"])
    report["retained_files_readable"] = not errors
    artifacts = report.get("artifact_integrity", {})
    report["artifact_manifest_errors"] = list(errors)
    if not artifacts.get("present"):
        report["artifact_manifest_errors"].append(
            "Missing artifact integrity manifest; readable metadata cannot "
            "establish complete retained artifacts")
    report["artifact_manifest_verified"] = not report["artifact_manifest_errors"]
    report["retention_handoff"] = dict(
        recipient="Coordinator",
        prerequisite_owner="shared-runtime platform owner",
        bundle=name,
        historical_manifest=f"{name}/receipt.json",
        artifact_availability=(
            "unestablished" if not artifacts.get("present") else
            "incomplete_or_invalid" if artifacts.get("errors") else
            "complete_at_observation"),
        missing_artifact_bindings=artifacts.get("missing_artifact_bindings", {}),
        missing_bytes=artifacts.get("missing_bytes"),
        artifacts_by_suffix=artifacts.get("artifacts_by_suffix", {}),
        recovery_archive=report.get("recovery_archive"),
        current_sources_match=report["current_sources_match"],
        platform_retention_remedy_established=False,
        post_settlement_retention_established=False,
        required_inputs=[
            "Authentic archive restoration, or a retained platform diagnosis and "
            "retention remedy before independently admitted fresh-root staging",
            "Adequate storage and direct-byte current-source preflight before execution",
            "Shared-runtime execution of all three unchanged mandatory portable "
            "commands in order from the admitted actual source root",
        ],
        prohibited_actions=[
            "Regenerate missing files into historical evidence",
            "Remove manifest entries or overwrite occupied outputs",
            "Treat source hashes, free storage or an in-process audit as a retention remedy",
        ],
        authorizes_staging=False,
        authorizes_resumption=False,
        establishes_physical_acceptance=False)
    return report


def repair_receipt(name):
    """Require retained predecessor metadata and streams, not just a filename."""
    def reject_symlinks(path):
        current = ROOT
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(
                    f"Symlink in repair predecessor path: {current.relative_to(ROOT)}")

    prior = Path(name)
    if prior.is_absolute() or ".." in prior.parts:
        raise ValueError("--repair-of must name a project-relative receipt")
    reject_symlinks(prior)
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
        if stream.is_absolute() or ".." in stream.parts:
            raise ValueError(f"Non-project {channel} path in repair predecessor {name}")
        reject_symlinks(stream)
        if not stream.resolve().is_relative_to(ROOT):
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
    elif record.get("launch_error") is not None:
        launch_error = record["launch_error"]
        outcome = ("launch-failed" if isinstance(launch_error, str)
                   and launch_error.strip() else "invalid-result")
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
    if "probe_exit_code" in record:
        probe_code = record["probe_exit_code"]
        if probe_code is None:
            probe_outcome = "unsettled"
        elif type(probe_code) is not int:
            probe_outcome = "invalid-result"
        elif probe_code != 0:
            probe_outcome = "failed"
        elif outcome != "succeeded" or record.get("source_unchanged") is not True:
            probe_outcome = "invalid-result"
        else:
            probe_outcome = "succeeded"
        report["recorded_probe"] = dict(
            exit_code=probe_code, outcome=probe_outcome,
            source_unchanged=record.get("source_unchanged"),
            source_inventory_error=record.get("source_inventory_error"))
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
            if os.path.lexists(root / destination):
                raise ValueError(
                    "HIL output is occupied; preserve it and request independently "
                    "reviewed replanning, not an unchanged retry")
            for ancestor in destination.parents:
                if (os.path.lexists(root / ancestor)
                        and not (root / ancestor).is_dir()):
                    raise ValueError(
                        f"HIL output ancestor is not a directory: {ancestor}")
            validate_output(destination, root=root)
            contract["fresh"] = True
        except (OSError, ValueError) as error:
            report["errors"].append(str(error))
    try:
        for component in (root / "fpga", path):
            if component.is_symlink():
                raise ValueError(
                    "Symlink in HIL configuration path: "
                    f"{component.relative_to(root)}")
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
        if config.get("force_flash"):
            report["configuration_actions"].append("force_flash")
        if report["configuration_actions"]:
            report["errors"].append(
                "Configured native HIL actions conflict with the no-deployment "
                "work order: " + ", ".join(report["configuration_actions"]))
    except (OSError, ValueError) as error:
        report["errors"].append(f"Cannot establish product-command input: {error}")
    report["unverified_requirements"] = [
        "Supported physical BELLOWS traffic transport",
        "Documented stream/status protocol for compression, decompression, duplex and internal round-trip",
        "Readable programmed-image binding to accepted sources",
        "Fresh shared-runtime prerequisite evidence",
        "Independent admission of adapter ownership, invocation and fresh outputs",
        "Three consecutive byte-exact physical compression, decompression, simultaneous-duplex and internal-round-trip passes",
    ]
    report["coordinator_handoff"] = dict(
        recipient="Coordinator",
        prerequisite_owner="shared-runtime platform owner",
        required_inputs=[
            dict(name="nondeploying_invocation",
                 request="Supported product-traffic argv, working directory and "
                         "prerequisites; no build, programming or RTL-copy actions"),
            dict(name="stream_status_protocol",
                 request="Document ingress/egress byte and block framing, empty-block "
                         "keep, ready/valid stalls, completion/error association and "
                         "mode selection for both lanes and internal round-trip"),
            dict(name="programmed_image_binding",
                 request="Readable provenance connecting the currently programmed "
                         "image, its build inputs and the delivered RTL; register "
                         "responsiveness or an unassociated source hash is insufficient"),
            dict(name="independent_admission",
                 request="Independently admit configuration, adapter ownership, "
                         "invocation and fresh evidence outputs before implementation "
                         "or physical execution"),
        ],
        required_physical_result="Three consecutive deterministic passes comparing "
                                 "complete bytes and block/status associations for "
                                 "compression, decompression, concurrent duplex and "
                                 "internal round-trip",
        portable_rerun_resolves_gap=False,
        designer_repair_justified=False,
        authorizes_adapter_implementation=False,
        authorizes_hardware_execution=False)
    return report


def diagnose_hil_record(record):
    """Separate native execution consistency from unestablished product evidence."""
    if not isinstance(record, dict) or record.get("gate") != "board-hil":
        raise ValueError("Expected a native board-hil receipt object")
    runs = record.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Missing retained HIL runs")
    consecutive = longest = 0
    previous = None
    indices = set()
    errors = []
    if record.get("status") != "passed":
        errors.append("Failed or invalid aggregate HIL status")
    if record.get("deterministic_across_runs") is not True:
        errors.append("Failed or invalid aggregate HIL deterministic_across_runs")
    for field, valid in (
            ("exit_code", "exit_code" not in record
             or (type(record["exit_code"]) is int and record["exit_code"] == 0)),
            ("timed_out", "timed_out" not in record or record["timed_out"] is False),
            ("launch_error", record.get("launch_error") is None)):
        if not valid:
            errors.append(f"Failed or invalid aggregate HIL {field}")
    if "requested_runs" in record:
        requested = record["requested_runs"]
        if type(requested) is not int or requested <= 0:
            errors.append("Failed or invalid aggregate HIL requested_runs")
        elif requested != len(runs):
            errors.append("Retained HIL run count differs from requested_runs")
        elif any(not isinstance(run, dict)
                 or type(run.get("run_index")) is not int
                 or run["run_index"] != ordinal
                 for ordinal, run in enumerate(runs, 1)):
            errors.append("Retained HIL run indices do not cover requested_runs in order")
    for ordinal, run in enumerate(runs, 1):
        if not isinstance(run, dict):
            errors.append(f"Invalid HIL run {ordinal}")
            consecutive = 0
            previous = None
            continue
        index = run.get("run_index")
        indexed = type(index) is int and index > 0 and index not in indices
        if not indexed:
            errors.append(f"Invalid or duplicate HIL run index at ordinal {ordinal}")
        else:
            indices.add(index)
        token_checks_clean = True
        for field in ("missing_expected_tokens", "forbidden_tokens_found"):
            if field in run and (
                    not isinstance(run[field], list) or run[field]):
                errors.append(
                    f"Failed or invalid {field} for HIL run at ordinal {ordinal}")
                token_checks_clean = False
        execution_clean = True
        for field, valid in (
                ("timed_out", "timed_out" not in run or run["timed_out"] is False),
                ("launch_error", run.get("launch_error") is None)):
            if not valid:
                errors.append(
                    f"Failed or invalid {field} for HIL run at ordinal {ordinal}")
                execution_clean = False
        for field, valid in (
                ("exit_code", type(run.get("exit_code")) is int
                 and run["exit_code"] == 0),
                ("passed", run.get("passed") is True),
                ("stdout", isinstance(run.get("stdout"), str)),
                ("stderr", isinstance(run.get("stderr"), str))):
            if not valid:
                errors.append(
                    f"Failed or invalid {field} for HIL run at ordinal {ordinal}")
                execution_clean = False
        succeeded = indexed and token_checks_clean and execution_clean
        if succeeded:
            consecutive = consecutive + 1 if previous == index - 1 else 1
            longest = max(longest, consecutive)
            previous = index
        else:
            consecutive = 0
            previous = None
    return dict(
        recorded_run_count=len(runs),
        longest_consecutive_native_successes=longest,
        three_consecutive_native_successes=longest >= 3 and not errors,
        recorded_deterministic_across_runs=record.get("deterministic_across_runs"),
        product_traffic_comparisons="unestablished",
        programmed_image_source_binding="unestablished",
        physical_acceptance_established=False,
        errors=errors)


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
        for candidate in (ROOT / path, *(ROOT / path).parents):
            if candidate == ROOT:
                break
            if candidate.is_symlink():
                raise ValueError("HIL receipt must not depend on symlinks")
        payload = (ROOT / path).read_bytes()
        report["receipt_integrity"] = dict(
            bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        record = json.loads(payload)
        report["native_execution_diagnostic"] = diagnose_hil_record(record)
        report["errors"].extend(report["native_execution_diagnostic"]["errors"])
        report["recorded_status"] = record.get("status")
        runs = record.get("runs")
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


def inspect_portable_inputs(name=".", reference=ROOT, source_diff=False):
    """Check a maintenance-staged root without copying inputs or running checks."""
    report = dict(kind="read-only-portable-input-inventory",
                  acceptance_evidence=False, authorizes_resumption=False,
                  root_mapping=dict(source_root=".", execution_root=str(name)),
                  current_sources_match=False, portable_preflight_passed=False,
                  source_comparison="direct-bytes", source_files_compared=0,
                  source_comparisons=[], source_inventory_stable=False,
                  source_sha256={}, outputs=[], errors=[])
    errors = report["errors"]
    inspection_root = None
    current = staged = None

    def reject_source_redirects(root):
        paths = {path for pattern in DECLARED for path in root.glob(pattern)}
        for path in paths:
            if any(candidate.is_symlink() for candidate in (path, *path.parents)
                   if candidate != reference and candidate.is_relative_to(reference)):
                raise ValueError(
                    f"Declared source depends on a symlink: {path.relative_to(reference)}")

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
        inspection_root = root
        reject_source_redirects(reference)
        reject_source_redirects(root)
        current = inputs(reference)
        staged = inputs(root)
        report["source_sha256"] = staged
        for source in sorted(set(current) | set(staged)):
            if source not in staged:
                errors.append(f"Missing declared source: {source}")
            elif source not in current:
                errors.append(f"Unexpected declared source: {source}")
            else:
                report["source_files_compared"] += 1
                original = (reference / source).read_bytes()
                copied = (root / source).read_bytes()
                equal = original == copied
                first_difference = None
                if not equal:
                    first_difference = next(
                        (index for index, (left, right) in enumerate(zip(original, copied))
                         if left != right), min(len(original), len(copied)))
                report["source_comparisons"].append(dict(
                    path=source, direct_bytes_equal=equal,
                    current_bytes=len(original), staged_bytes=len(copied),
                    first_differing_byte=first_difference))
                if source_diff and not equal:
                    report["source_comparisons"][-1]["unified_diff"] = "".join(
                        difflib.unified_diff(
                            copied.decode("utf-8").splitlines(keepends=True),
                            original.decode("utf-8").splitlines(keepends=True),
                            fromfile=f"staged/{source}", tofile=f"current/{source}"))
                if (hashlib.sha256(original).hexdigest() != current[source]
                        or hashlib.sha256(copied).hexdigest() != staged[source]):
                    errors.append(f"Declared source changed during comparison: {source}")
                if not equal:
                    errors.append(f"Declared source differs from current input: {source}")
        report["current_sources_match"] = not errors
    except (OSError, ValueError, AssertionError) as error:
        errors.append(str(error))
    for destination in PORTABLE_OUTPUTS:
        output = dict(path=destination, fresh=False, usable=False)
        report["outputs"].append(output)
        if inspection_root is None:
            output["error"] = "Execution root unavailable or rejected"
            continue
        try:
            output["fresh"] = not os.path.lexists(inspection_root / destination)
            validate_output(Path(destination), root=inspection_root)
            output["usable"] = True
        except (OSError, ValueError) as error:
            output["error"] = str(error)
            errors.append(f"Mandatory output rejected; preserve it: {error}")
    if current is not None and staged is not None:
        try:
            current_unchanged = inputs(reference) == current
            staged_unchanged = inputs(root) == staged
            reject_source_redirects(reference)
            reject_source_redirects(root)
            if not current_unchanged or not staged_unchanged:
                raise ValueError("Declared source inventory changed during inspection")
            report["source_inventory_stable"] = True
        except (OSError, ValueError, AssertionError) as error:
            report["current_sources_match"] = False
            errors.append(f"Final declared-source inspection failed: {error}")
    report["portable_preflight_passed"] = not errors
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
        source_files_synchronized=0, source_directories_synchronized=0,
        source_durability_completed=False,
        mandatory_commands=[
            ["python3", "tests/verify.py", "--output", "evidence/l1"],
            *[["sh", "-c",
               f"mkdir {destination} && python3 tests/preparation.py "
               f"--audit-bundles evidence/l1 > {destination}/stdout.json 2> "
               f"{destination}/stderr.log"]
              for destination in PORTABLE_OUTPUTS[1:]],
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
                handle.flush()
                os.fsync(handle.fileno())
            record["source_files_synchronized"] += 1
        directories = {root}
        for name in sources:
            for directory in (root / name).parents:
                if directory == root:
                    break
                directories.add(directory)
        for directory in sorted(directories, key=lambda path: len(path.parts),
                                reverse=True):
            sync_directory(directory)
            record["source_directories_synchronized"] += 1
        for directory in root.parents:
            sync_directory(directory)
            record["source_directories_synchronized"] += 1
            if directory == reference:
                break
        record["source_durability_completed"] = True
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
            handle.flush()
            os.fsync(handle.fileno())
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
                                 "backend-focused", "output-focused", "harness-focused"))
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
                        help="include readable changes with bundle or portable-input inspection")
    parser.add_argument("--require-current-sources", action="store_true",
                        help="fail receipt inventory when any declared source binding is stale")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    if args.require_current_sources and not args.audit_receipts:
        parser.error("--require-current-sources applies only to --audit-receipts")
    if args.hil_output is not None and not args.inspect_hil_inputs:
        parser.error("--hil-output applies only to --inspect-hil-inputs")
    if (args.source_diff and not args.audit_bundles
            and args.inspect_portable_inputs is None):
        parser.error("--source-diff requires --audit-bundles or --inspect-portable-inputs")
    os.chdir(ROOT)
    if args.inspect_hil_receipt is not None:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        report = inspect_hil_receipt(args.inspect_hil_receipt)
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        # Exit zero means consistent native run records, not physical acceptance.
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
        report = inspect_portable_inputs(
            args.inspect_portable_inputs, source_diff=args.source_diff)
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
        manifests = all(record["artifact_manifest_verified"] for record in records)
        json.dump(dict(kind="read-only-bundle-inventory",
                       acceptance_evidence=False, acceptance_credit=0,
                       authorizes_resumption=False, retained_files_readable=readable,
                       artifact_manifest_verified=manifests,
                       current_sources_match=current,
                       bundles=records), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if readable and current and manifests else 1
    if args.audit_receipts:
        if args.repair_of:
            parser.error("--repair-of applies only to --subset")
        records = [audit_receipt(name) for name in args.audit_receipts]
        complete = all(record["available"] for record in records)
        current = all(record.get("current_sources_match") is True for record in records)
        json.dump(dict(kind="read-only-receipt-inventory",
                       acceptance_evidence=False, acceptance_credit=0,
                       authorizes_resumption=False, complete=complete,
                       current_sources_match=current,
                       current_sources_required=args.require_current_sources,
                       receipts=records), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if complete and (current or not args.require_current_sources) else 1
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
        record["source_unchanged"] = False
        try:
            record["source_unchanged"] = inputs() == record["source_sha256"]
        except (OSError, AssertionError) as error:
            record["source_inventory_error"] = (
                f"Final source inventory unavailable: {type(error).__name__}: {error}")
        else:
            if not record["source_unchanged"]:
                record["source_inventory_error"] = "Declared sources changed during probe"
        if not record["source_unchanged"]:
            stderr.write((record["source_inventory_error"] + "\n").encode())
        record["probe_exit_code"] = (
            1 if record["timed_out"] or "launch_error" in record
            or not record["source_unchanged"] else record["exit_code"])
        for stream in (stdout, stderr):
            stream.flush()
            os.fsync(stream.fileno())
    record["stream_integrity"] = {
        channel: file_integrity(out / f"{channel}.log")
        for channel in ("stdout", "stderr")
    }
    record["end_time"] = datetime.now(timezone.utc).isoformat()
    record["duration_s"] = time.monotonic() - start
    versions = out / "result/tool-versions.json"
    record["tool_versions"] = json.loads(versions.read_text()) if versions.exists() else {}
    record["child_receipt"] = (out / "result/receipt.json").as_posix()
    json_write(out / "receipt.json", record)
    print((out / "receipt.json").as_posix())
    print((out / "stdout.log").read_text(), end="")
    print((out / "stderr.log").read_text(), end="", file=sys.stderr)
    return record["probe_exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())