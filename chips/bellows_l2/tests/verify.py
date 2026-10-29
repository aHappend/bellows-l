#!/usr/bin/env python3
"""Portable BELLOWS-L2 L1 verification.

Full admitted invocation (fresh destination required):
    python3 tests/verify.py --output evidence/l1

The bounded clean-directory reproduction invokes:
    python3 tests/verify.py --output result --subset reproduce

Requires Python, Icarus, Verilator, a C++ toolchain, make and Yosys.
Icarus executes compact startup/unit and clean-reproduction traffic; Verilator
executes the full behavioral matrix, decoder sweeps and disposable mutations.
Both backends use the same public-pin transactor, oracle and coverage checks.
Native timing/hardware gates and the
post-acceptance product report are independently owned by the shared runtime.

Executable requirement mapping:
* matrix_cases/compare: legal endpoints, seeds, grammar, exact fallback, frozen
  directed hash entries, extension/end boundaries, bytes, lengths, completion.
* bench: pre-edge transfers, bounded independent stalls, held final/status,
  active-reset X rejection, concurrent lanes, internal route with c_m_ready=0.
* hardware_decode_compressed: original raw bytes versus the actual parent
  decoder's recovery from every externally observed hardware-compressed block.
* unit_pipeline: synchronous two-port RAM, registered cascade and emitter.
* decoder_vectors: independent constructed blocks, history wrap, offset 65535,
  >64-KiB recovery, malformed prefixes, overflow and subsequent recovery.
* mutate/synthesis/clean_reproduction: three executing checker rejections,
  retained RAM/control/hierarchy/zero latches and a fresh declared-input copy.
* simulator_equivalence: compact duplex/round-trip/fallback traffic compared
  independently on both simulators, then exact public-trace agreement.
* occupied_destination: occupied directories/files, dangling output symlinks
  and symlinked or non-directory parents are rejected without changing them.
* preparation_regressions: synthetic retention, staging and HIL-diagnostic
  rejection tests; these establish harness behavior, not product acceptance.

The advisory --subset output-focused runs only output-path rejection checks
and tool-version queries; it establishes no RTL behavior or matrix coverage.
The advisory --subset harness-focused runs only the synthetic recovery-safety
regressions and tool-version queries; it never stages the actual project,
restores historical artifacts or exercises hardware.

Final receipts bind every retained artifact, including compared data and synthesis
outputs. Before publishing a final receipt, all artifact files and their directory
entries are fsynced and rechecked against the manifest. Synchronization errors
fail explicitly. Bundle paths and project-local ancestors are checked again for
symlink substitution after synchronization, before final content comparisons.
These bounded observations do not prevent concurrent filesystem replacement.
This improves crash durability, not protection against external
deletion; it cannot restore a missing bundle or authorize replay of a paused check.
Final stdout also identifies the receipt and results by size and SHA-256, with
source bindings and matrix outcomes. This diagnostic is not a replacement for
the raw bundle or proof of its availability after process settlement.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import random
import shutil
import signal
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench import generate
from oracle import (Case, Raw, Decoded, FormatError, decode, decoder_vectors,
                    literals, matrix_cases, unique_bytes)


ROOT = Path(__file__).resolve().parent.parent
CAPACITIES = (1, 5, 13, 257, 4096, 65536)
SEEDS = (1, 17, 89)
CHILD_TIMEOUT = 14400
DECLARED = ("rtl/*.sv", "bellows_l1_reference/rtl/*.sv", "tests/*.py",
            "design/SPEC.md", "design/ARCHITECTURE.md")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_integrity(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return dict(bytes=size, sha256=digest.hexdigest())


def json_write(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def persist_artifacts(output):
    """Synchronize a completed bundle before publishing its integrity bindings."""
    ancestors = [output, *(path for path in output.parents if path.is_relative_to(ROOT))]
    if any(path.is_symlink() for path in ancestors):
        raise AssertionError("Evidence artifacts must not depend on symlinks")
    paths = sorted(output.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise AssertionError("Evidence artifacts must not depend on symlinks")
    files = [path for path in paths if path.is_file()]
    artifacts = {}
    for path in files:
        binding = file_integrity(path)
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
        artifacts[relative(path)] = binding
    directories = [output, *(path for path in paths if path.is_dir())]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        sync_directory(directory)
    # Persist newly created ancestors as well, without touching unrelated files.
    for directory in output.resolve().parents:
        if not directory.is_relative_to(ROOT):
            break
        sync_directory(directory)
    final_paths = sorted(output.rglob("*"))
    if any(path.is_symlink() for path in [*ancestors, *final_paths]):
        raise AssertionError("Evidence artifacts must not depend on symlinks")
    if final_paths != paths:
        raise AssertionError("Evidence inventory changed during synchronization")
    for path in files:
        if file_integrity(path) != artifacts[relative(path)]:
            raise AssertionError(f"Evidence changed during synchronization: {relative(path)}")
    return artifacts


def inputs(root=ROOT):
    paths = sorted({p for pattern in DECLARED for p in root.glob(pattern)})
    for pattern in DECLARED:
        if not list(root.glob(pattern)):
            raise AssertionError(f"Unmatched declared input: {pattern}")
    return {p.relative_to(root).as_posix(): sha(p) for p in paths}


def relative(path):
    return (ROOT / path).resolve().relative_to(ROOT).as_posix()


def validate_output(output, root=ROOT):
    """Reject occupied or redirected paths before any evidence is created."""
    if output.is_absolute() or ".." in output.parts or not output.parts:
        raise ValueError("--output must be a nonempty project-relative path")
    if any(part in (".vulcan", ".git", ".tooling", "VULCAN") for part in output.parts):
        raise ValueError("runtime-owned output destination prohibited")
    destination = root / output
    if os.path.lexists(destination):
        raise ValueError(f"Refusing occupied output destination: {output.as_posix()}")
    for parent in destination.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f"Refusing symlinked output parent: {parent.relative_to(root)}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(
                f"Refusing non-directory output parent: {parent.relative_to(root)}")
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("Output destination resolves outside the project")


class Execution:
    """Append-only child receipts, exact streams, and source-bound snapshots."""

    def __init__(self, output):
        self.output = output
        self.source_hashes = inputs()
        self.started = now()
        self.children = []
        self.versions = {}
        self.results = []
        self.coverage = Counter()
        self.matrix_status = {(c, s): "not-executed" for c in CAPACITIES for s in SEEDS}
        self.sequence = 0
        snapshot = output / "source"
        for name, digest in self.source_hashes.items():
            dest = snapshot / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
            assert sha(dest) == digest

    def run(self, label, argv, cwd=ROOT, expected=(0,), extra_sources=()):
        self.sequence += 1
        directory = self.output / "commands" / f"{self.sequence:03d}-{label}"
        directory.mkdir(parents=True)
        record = dict(argv=[str(x) for x in argv], cwd=relative(cwd),
                      timeout_s=CHILD_TIMEOUT, start_time=now(),
                      source_sha256=self.source_hashes,
                      generated_source_sha256={relative(p): sha(p) for p in extra_sources},
                      tool_versions=dict(self.versions),
                      stdout=relative(directory / "stdout.log"),
                      stderr=relative(directory / "stderr.log"),
                      timed_out=False, exit_code=None)
        json_write(directory / "launch.json", record)
        monotonic = time.monotonic()
        with (directory / "stdout.log").open("xb") as stdout, (
                directory / "stderr.log").open("xb") as stderr:
            try:
                process = subprocess.Popen(record["argv"], cwd=cwd, stdout=stdout,
                                           stderr=stderr, start_new_session=True)
            except OSError as error:
                record["launch_error"] = f"{type(error).__name__}: {error}"
                stderr.write((record["launch_error"] + "\n").encode())
            else:
                try:
                    record["exit_code"] = process.wait(timeout=CHILD_TIMEOUT)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    record["exit_code"] = process.returncode
            for stream in (stdout, stderr):
                stream.flush()
                os.fsync(stream.fileno())
        record["stream_integrity"] = {
            channel: dict(bytes=(directory / f"{channel}.log").stat().st_size,
                          sha256=sha(directory / f"{channel}.log"))
            for channel in ("stdout", "stderr")
        }
        record["end_time"] = now()
        record["duration_s"] = time.monotonic() - monotonic
        record["source_unchanged"] = inputs() == self.source_hashes
        receipt = directory / "receipt.json"
        json_write(receipt, record)
        self.children.append(relative(receipt))
        if "launch_error" in record:
            raise AssertionError(f"Tool launch failed: {relative(receipt)}: {record['launch_error']}")
        if record["timed_out"]:
            raise AssertionError(f"Tool timeout, not a functional result: {relative(receipt)}")
        if not record["source_unchanged"]:
            raise AssertionError(f"Sources changed during execution: {relative(receipt)}")
        if record["exit_code"] not in expected:
            raise AssertionError(f"Unexpected exit {record['exit_code']}: {relative(receipt)}")
        return record, (directory / "stdout.log").read_text(), (
            directory / "stderr.log").read_text()

    def tools(self):
        for tool, option in (("python3", "--version"), ("iverilog", "-V"),
                             ("vvp", "-V"), ("verilator", "--version"),
                             ("c++", "--version"), ("make", "--version"),
                             ("yosys", "-V")):
            if shutil.which(tool) is None:
                raise AssertionError(f"Required dependency missing: {tool}; installation prohibited")
            record, stdout, stderr = self.run(f"version-{tool}", [tool, option])
            self.versions[tool] = (stdout + stderr).strip()
        json_write(self.output / "tool-versions.json", self.versions)

    def finish(self, outcome, error=None):
        json_write(self.output / "results.json",
                   dict(outcome=outcome, error=error, runs=self.results,
                        coverage=dict(self.coverage), mandatory_matrix=[
                            dict(capacity=c, seed=s, outcome=self.matrix_status[(c, s)])
                            for c in CAPACITIES for s in SEEDS]))
        artifacts = persist_artifacts(self.output)
        json_write(self.output / "receipt.json",
                   dict(kind="portable-verifier", start_time=self.started, end_time=now(),
                        cwd=".", argv=["python3", *sys.argv], source_sha256=self.source_hashes,
                        tool_versions=self.versions, children=self.children,
                        outcome=outcome, error=error,
                        artifact_integrity=artifacts,
                        results=relative(self.output / "results.json")))
        completion = dict(
            kind="portable-verifier-completion-diagnostic",
            outcome=outcome, error=error,
            source_sha256=self.source_hashes,
            receipt=dict(path=relative(self.output / "receipt.json"),
                         **file_integrity(self.output / "receipt.json")),
            results=dict(path=relative(self.output / "results.json"),
                         **file_integrity(self.output / "results.json")),
            child_receipts=len(self.children), bound_artifacts=len(artifacts),
            mandatory_matrix=[
                dict(capacity=c, seed=s, outcome=self.matrix_status[(c, s)])
                for c in CAPACITIES for s in SEEDS],
            raw_bundle_required=True, post_settlement_retention_verified=False)
        print(json.dumps(completion, sort_keys=True), flush=True)


def check_parent():
    for name in ("bellows_l1_top.sv", "bellows_l1_history.sv", "bellows_l1_output.sv"):
        assert (ROOT / "rtl" / name).read_bytes() == (
            ROOT / "bellows_l1_reference/rtl" / name).read_bytes(), f"Parent changed: {name}"


def source_contract(execution):
    for path in sorted((ROOT / "rtl").glob("*.sv")):
        source = re.sub(r"/\*.*?\*/|//[^\n]*", "", path.read_text(), flags=re.S)
        source = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)
        assert "/" not in source and "%" not in source, f"Division/remainder operator: {path.name}"
        processes = re.split(r"\balways\b", source)[1:]
        for process in processes:
            if not re.match(r"\s*@\s*\([^)]*\bposedge\b", process):
                continue
            nonblocking = bool(re.search(r"<=", process))
            blocking = bool(re.search(r"(?<![<>=!])=(?!=)", process))
            assert not (nonblocking and blocking), f"Mixed sequential assignments: {path.name}"
    execution.results.append(dict(kind="source-operator-and-assignment-contract", outcome="passed"))


def add_recoveries(cases):
    result = []
    for case in cases:
        result.append(case)
        if case.abort:
            result.append(Case(case.name + "-fresh-epoch",
                               [Raw("reset-recovery", b"Z", fallback=True)],
                               [Decoded("reset-recovery-decoder", literals(b"reset!"), b"reset!")]))
    return result


def save_expectations(directory, cases):
    records = []
    for index, case in enumerate(cases):
        records.append(dict(
            id=index, name=case.name, roundtrip=case.roundtrip, reset_abort=case.abort,
            raw=[dict(name=b.name, bytes=b.data.hex(), status=b.error, tags=b.tags,
                      exact_fallback=b.fallback, require_match=b.require_match,
                      ratio_below_one=b.ratio, segments=b.segments()) for b in case.raw],
            decoder=[dict(name=b.name, input=b.encoded.hex(), expected=b.expected.hex(),
                          status=b.error, tags=b.tags, segments=b.segments())
                     for b in case.decoder]))
    json_write(directory / "expectations.json", records)


COVERAGE_NAMES = ("c_input_stall", "d_input_stall", "c_output_stall", "d_output_stall",
                  "c_status_stall", "d_status_stall", "c_final_stall", "d_final_stall",
                  "concurrent", "coincident", "c_input_beats", "d_input_beats",
                  "c_output_beats", "d_output_beats", "c_status", "d_status",
                  "c_final", "d_final")


def parse_trace(path):
    output = defaultdict(lambda: defaultdict(list))
    statuses = defaultdict(lambda: defaultdict(list))
    finals = defaultdict(lambda: defaultdict(list))
    ingress = defaultdict(lambda: defaultdict(list))
    coverage, ended, aborted = {}, {}, {}
    done = 0
    for line in path.read_text().splitlines():
        fields = line.split()
        kind = fields[0]
        if kind == "DONE":
            done += 1
            continue
        index = int(fields[1])
        if kind == "STALL_C":
            assert len(fields) == 5
        elif kind in ("C", "D"):
            block, value, last = int(fields[2]), int(fields[3], 16), int(fields[4])
            assert last in (0, 1) and 0 <= value <= 255
            output[index][(kind, block)].append(value)
            finals[index][(kind, block)].append(last)
        elif kind in ("CS", "DS"):
            statuses[index][kind].append((int(fields[2]), int(fields[3])))
        elif kind in ("CI", "DI"):
            ingress[index][kind].append((int(fields[2]), int(fields[3])))
        elif kind == "COV":
            assert index not in coverage and len(fields[2:]) == len(COVERAGE_NAMES)
            coverage[index] = dict(zip(COVERAGE_NAMES, map(int, fields[2:])))
        elif kind == "END":
            assert index not in ended
            ended[index] = int(fields[2])
        elif kind == "ABORT":
            assert index not in aborted
            aborted[index] = (int(fields[2]), int(fields[3]))
        else:
            raise AssertionError(f"Unknown trace record: {line}")
    assert done == 1, "Missing or duplicate simulator completion"
    return output, statuses, finals, ingress, coverage, ended, aborted


def compare(directory, capacity, seed, cases, require_channels=True):
    output, statuses, finals, ingress, coverage, ended, aborted = parse_trace(
        directory / "trace.txt")
    assert set(ended) == set(range(len(cases))), "Missing/extra scenario"
    ledger, total_coverage = [], Counter()
    for index, case in enumerate(cases):
        cov = coverage[index]
        total_coverage.update(cov)
        if case.abort:
            assert index in aborted and cov["c_input_beats"] > 0
            if case.abort == "collect":
                assert not ingress[index]["CI"], "Collection reset must precede last acceptance"
            if case.abort == "match":
                assert len(ingress[index]["CI"]) == 1 and cov["c_output_beats"] == 0
            if case.abort == "emission":
                assert cov["c_output_beats"] > 0
            if case.abort == "stalled":
                assert cov["c_output_stall"] >= 3 and cov["c_output_beats"] == 0
            total_coverage["reset-" + case.abort] += 1
            continue
        assert statuses[index]["CS"] == list(enumerate(b.error for b in case.raw)), (
            case.name, "compression status association", statuses[index]["CS"])
        expected_d = ([Decoded(b.name, b"", b.data, b.error) for b in case.raw]
                      if case.roundtrip else case.decoder)
        assert statuses[index]["DS"] == list(enumerate(b.error for b in expected_d)), (
            case.name, "decoder status association", statuses[index]["DS"])
        assert len(ingress[index]["CI"]) == len(case.raw), "Raw block conservation"
        assert len(ingress[index]["DI"]) == (0 if case.roundtrip else len(case.decoder))
        assert cov["c_input_beats"] == sum(n for b in case.raw for n, _ in b.segments())
        assert cov["d_input_beats"] == (
            0 if case.roundtrip else sum(n for b in case.decoder for n, _ in b.segments()))
        allowed = {("C", i) for i in range(len(case.raw))}
        allowed |= {("D", i) for i in range(len(expected_d))}
        assert set(output[index]) <= allowed, "Unassociated or residual output"
        compressed_by_name = {}
        for block, raw in enumerate(case.raw):
            encoded = bytes(output[index][("C", block)])
            flags = finals[index][("C", block)]
            record = dict(capacity=capacity, seed=seed, scenario=case.name, block=raw.name,
                          raw_bytes=len(raw.data), status=raw.error,
                          raw_sha256=hashlib.sha256(raw.data).hexdigest(),
                          trace=relative(directory / "trace.txt"))
            if case.roundtrip or raw.error:
                assert not encoded and not flags, "Output on hidden/error compressor stream"
            else:
                assert flags == [0] * (len(encoded) - 1) + [1], "Compressed block final framing"
                assert len(encoded) <= 2 * capacity + 16, "Candidate storage bound"
                recovered, sequences = decode(encoded, strict=True)
                assert recovered == raw.data, f"COMPRESSED_BYTE_MISMATCH {raw.name}"
                reference_literal = literals(raw.data)
                assert len(encoded) <= len(reference_literal), "Fallback size invariant"
                if raw.fallback or len(encoded) == len(reference_literal):
                    assert encoded == reference_literal, f"EXACT_FALLBACK {raw.name}"
                    total_coverage["exact-fallback"] += 1
                matches = [r for r in sequences if not r["final"]]
                if raw.require_match:
                    assert matches, f"REAL_MATCH_REQUIRED {raw.name}"
                if len(raw.data) < 13:
                    assert not matches, "Short-block match forbidden"
                if raw.ratio:
                    assert raw.data and matches
                    assert len(encoded) < len(raw.data), (
                        f"COMPRESSION_RATIO {raw.name}: {len(encoded)}/{len(raw.data)} >= 1.0")
                    total_coverage[f"ratio-{capacity}-{raw.name}"] += 1
                if raw.name == "last-start-tail-five":
                    assert any(r["start"] == len(raw.data) - 12 and
                               r["start"] + r["length"] == len(raw.data) - 5 for r in matches)
                if raw.name == "four-byte-match":
                    assert any(r["length"] == 4 for r in matches)
                if raw.name.startswith("latest-entry-"):
                    assert [(r["start"], r["length"], r["offset"]) for r in matches] == [
                        (16, 8, 16), (32, 8, 16)], ("Latest old-entry lookup", matches)
                    if raw.name.endswith("after"):
                        assert encoded == compressed_by_name["latest-entry-before"], (
                            "Hash ownership crossed a block boundary")
                if raw.name.startswith("hardware-match-extension-"):
                    requested = int(raw.name.rsplit("-", 1)[1])
                    assert any(r["length"] == requested for r in matches), (
                        raw.name, matches)
                    if requested >= 19:
                        expected_ext = [255] * ((requested - 19) // 255) + [
                            (requested - 19) % 255]
                        assert any(r["match_extension"] == expected_ext for r in matches)
                record.update(encoded_bytes=len(encoded), matches=matches,
                              final_literals=sequences[-1]["literals"],
                              ratio=len(encoded) / len(raw.data) if raw.data else None,
                              recovered_sha256=hashlib.sha256(recovered).hexdigest())
                total_coverage["independent-compressed-blocks"] += 1
                total_coverage["compared-compressor-bytes"] += len(recovered)
                compressed_by_name[raw.name] = encoded
            for tag in raw.tags:
                if not raw.error and not case.roundtrip:
                    total_coverage[tag] += 1
            ledger.append(record)
        for block, expected in enumerate(expected_d):
            recovered = bytes(output[index][("D", block)])
            assert recovered == expected.expected, (
                f"DECOMPRESSED_BYTE_MISMATCH {case.name}/{expected.name}: "
                f"got {len(recovered)} bytes, expected {len(expected.expected)}")
            flags = finals[index][("D", block)]
            assert flags == ([0] * (len(recovered) - 1) + [1] if recovered else []), (
                expected.name, "decoded final framing")
            total_coverage["compared-decoder-bytes"] += len(recovered)
            total_coverage["decoder-completions"] += 1
            if not case.roundtrip and not expected.error:
                assert decode(expected.encoded)[0] == expected.expected
                total_coverage["independent-generated-blocks"] += 1
            if case.roundtrip:
                total_coverage["internal-roundtrip-blocks"] += 1
            for tag in expected.tags:
                total_coverage[tag] += 1
            ledger.append(dict(capacity=capacity, seed=seed, scenario=case.name,
                               block=expected.name, decoded_bytes=len(recovered),
                               status=expected.error,
                               expected_sha256=hashlib.sha256(expected.expected).hexdigest(),
                               recovered_sha256=hashlib.sha256(recovered).hexdigest(),
                               trace=relative(directory / "trace.txt")))
    if require_channels:
        for name in COVERAGE_NAMES[:8]:
            assert total_coverage[name] > 0, f"Unobserved public channel stall: {name}"
        assert total_coverage["concurrent"] > 0, "No simultaneous duplex activity"
    json_write(directory / "comparison.json", dict(
        outcome="passed", capacity=capacity, seed=seed, ledger=ledger,
        coverage=dict(total_coverage)))
    return ledger, total_coverage


def behavior(execution, label, capacity, seed, cases, rtl=None, require_channels=True,
             expected_sim_failure=None, simulator="verilator"):
    assert simulator in ("iverilog", "verilator"), f"Unknown simulator: {simulator}"
    matrix = label.startswith("matrix-")
    if matrix:
        execution.matrix_status[(capacity, seed)] = "running"
    directory = execution.output / label
    directory.mkdir()
    cases = add_recoveries(cases)
    save_expectations(directory, cases)
    bench, case_info = generate(directory, capacity, seed, cases)
    json_write(directory / "stimulus.json", case_info)
    sources = sorted((ROOT / "rtl").glob("*.sv")) if rtl is None else sorted(rtl.glob("*.sv"))
    generated = [bench] + sorted(directory.glob("*.hex"))
    if simulator == "iverilog":
        executable = directory / "sim.vvp"
        compile_argv = [
            "iverilog", "-g2012", "-Wall", "-s", "tb", "-o", relative(executable),
            *[relative(p) for p in sources], relative(bench)]
        simulate_argv = ["vvp", relative(executable)]
    else:
        executable = directory / "obj" / "sim"
        compile_argv = [
            "verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
            "-j", "2", "--top-module", "tb", "--Mdir", relative(executable.parent),
            "-o", "sim", *[relative(p) for p in sources], relative(bench)]
        simulate_argv = [relative(executable)]
    json_write(directory / "simulator.json", dict(
        simulator=simulator, compile_argv=compile_argv, simulate_argv=simulate_argv,
        four_state=simulator == "iverilog"))
    execution.run(label + "-compile",
                  compile_argv,
                  extra_sources=generated + sources)
    expected_exits = (0,)
    if expected_sim_failure:
        expected_exits = tuple(range(256))
        if simulator == "verilator":
            # Verilator implements $fatal with SIGABRT, not a positive exit.
            expected_exits += (-signal.SIGABRT,)
    record, stdout, stderr = execution.run(
        label + "-simulate", simulate_argv,
        expected=expected_exits,
        extra_sources=generated + sources)
    if expected_sim_failure:
        assert record["exit_code"] != 0, "Mutant did not fail"
        assert expected_sim_failure in stdout + stderr, (
            "Mutant failed for an unrelated reason", stdout, stderr)
        assert "CYCLE_PROGRESS_BOUND" not in stdout + stderr
        assert "STALL_C 0 0 " in (directory / "trace.txt").read_text(), (
            "Held-output mutation did not reach a publicly observed stall")
        return directory, None
    ledger, coverage = compare(directory, capacity, seed, cases, require_channels)
    execution.results.extend(ledger)
    execution.coverage.update(coverage)
    if matrix:
        execution.matrix_status[(capacity, seed)] = "passed"
    return directory, coverage


def hardware_decode_compressed(execution, label, capacity, seed, cases, directory,
                               simulator="verilator"):
    observed, _, _, _, _, _, _ = parse_trace(directory / "trace.txt")
    vectors = []
    for index, case in enumerate(add_recoveries(cases)):
        if case.abort or case.roundtrip:
            continue
        for block, raw in enumerate(case.raw):
            if not raw.error:
                encoded = bytes(observed[index][("C", block)])
                assert decode(encoded, strict=True)[0] == raw.data
                vectors.append(Decoded(f"{case.name}-{raw.name}", encoded, raw.data,
                                       tags=("hardware-compress-hardware-decompress",)))
    assert vectors
    result, coverage = behavior(execution, label, capacity, seed,
                                [Case("hardware-loopback", decoder=vectors)],
                                require_channels=False, simulator=simulator)
    for channel in ("d_input_stall", "d_output_stall", "d_final_stall", "d_status_stall"):
        assert coverage[channel] > 0, f"Loopback lacks {channel}"
    execution.results.append(dict(
        kind="hardware-compress-hardware-decompress", capacity=capacity, seed=seed,
        compressed_blocks=len(vectors), outcome="passed",
        source_trace=relative(directory / "trace.txt"),
        decoder_trace=relative(result / "trace.txt")))


def unit_pipeline(execution):
    """Public module ports prove synchronous storage and registered consumption."""
    directory = execution.output / "unit-pipeline"
    directory.mkdir()
    bench = directory / "tb.sv"
    bench.write_text(r"""module unit_tb;
reg clk=0, rst_n=0;
always #5 clk=~clk;
reg we=0, manual=1, ae=0, be=0;
reg [15:0] wa=0, aa=0, ba=0;
reg [7:0] wd=0;
wire [7:0] ad, bd;
wire le;
wire [15:0] la;
reg sv=0, br=0;
wire sr,bv,done;
wire [7:0] byte_data;
reg [7:0] cascade;
integer comparisons=0, transfers=0, n;
reg [7:0] held;
bellows_l2_literal_buffer #(.MAX_BLOCK_BYTES(5)) storage (
 .clk(clk),.rst_n(rst_n),.write_en(we),.write_addr(wa),.write_data(wd),
 .a_en(manual ? ae : le),.a_addr(manual ? aa : la),.a_data(ad),
 .b_en(be),.b_addr(ba),.b_data(bd));
bellows_l2_emitter encoder (
 .clk(clk),.rst_n(rst_n),.seq_valid(sv),.seq_ready(sr),
 .literal_start(17'd0),.literal_length(17'd1),.match_length(17'd0),
 .match_offset(16'd0),.final_sequence(1'b1),
 .literal_en(le),.literal_addr(la),.literal_data(ad),
 .byte_data(byte_data),.byte_valid(bv),.byte_ready(br),.done(done));
always @(posedge clk) cascade<=ad;
always @(posedge clk) if(!rst_n && {sr,bv,byte_data,done,le} !== 12'b0)
 $fatal(1,"UNIT_RESET_ACTIVE");
always @(negedge clk) if(!rst_n && {sr,bv,byte_data,done,le} !== 12'b0)
 $fatal(1,"UNIT_RESET_NEGATIVE_EDGE");
initial begin
 #0;
 if({sr,bv,byte_data,done,le} !== 12'b0) $fatal(1,"UNIT_RESET_TIME_ZERO");
 repeat(3) @(negedge clk);
 #1; rst_n=1;
 @(negedge clk); we=1; wa=0; wd=8'h41;
 @(negedge clk); wa=1; wd=8'hb6;
 @(negedge clk); we=0; ae=1; be=1; aa=0; ba=1;
 @(posedge clk); #1;
 if(ad!==8'h41 || bd!==8'hb6) $fatal(1,"SYNC_READ_PORTS");
 comparisons=comparisons+2;
 @(negedge clk); aa=1; ba=0;
 #1;
 if(ad!==8'h41 || bd!==8'hb6) $fatal(1,"COMBINATIONAL_RAM_READ");
 comparisons=comparisons+2;
 @(posedge clk); #1;
 if(ad!==8'hb6 || bd!==8'h41 || cascade!==8'h41)
  $fatal(1,"TWO_REGISTER_STAGE_LATENCY");
 comparisons=comparisons+3;
 @(negedge clk); ae=0; be=0;
 @(posedge clk); #1;
 if(cascade!==8'hb6) $fatal(1,"REGISTERED_RESPONSE_CONSUMPTION");
 comparisons=comparisons+1;
 @(negedge clk); manual=0; sv=1;
 if(sr!==1) $fatal(1,"EMITTER_IDLE_READY");
 @(posedge clk); #1;
 if(bv!==0) $fatal(1,"EMITTER_INPUT_FORWARDING");
 comparisons=comparisons+1;
 @(negedge clk); sv=0;
 @(posedge clk); #1;
 if(bv!==1 || byte_data!==8'h10) $fatal(1,"EMITTER_REGISTERED_TOKEN");
 comparisons=comparisons+1;
 held=byte_data;
 repeat(5) begin
  @(posedge clk); #1;
  if(bv!==1 || byte_data!==held) $fatal(1,"EMITTER_HELD_TOKEN");
  comparisons=comparisons+1;
 end
 @(negedge clk); br=1;
 begin : consume
  for(n=0;n<100;n=n+1) begin
   @(posedge clk);
   if(bv && br) begin
    if(transfers==0 && byte_data!==8'h10) $fatal(1,"EMITTER_TOKEN_BYTES");
    if(transfers==1 && byte_data!==8'h41) $fatal(1,"EMITTER_LITERAL_BYTES");
    if(transfers>1) $fatal(1,"EXTRA_EMITTER_BYTE");
    comparisons=comparisons+1; transfers=transfers+1;
   end
   if(done) disable consume;
  end
  $fatal(1,"UNIT_PROGRESS_BOUND");
 end
 if(transfers!=2 || comparisons!=17) $fatal(1,"UNIT_COMPARISON_COUNTS");
 $display("UNIT_RESULT comparisons=%0d transfers=%0d",comparisons,transfers);
 $finish;
end
endmodule
""")
    executable = directory / "sim.vvp"
    execution.run("unit-pipeline-compile",
                  ["iverilog", "-g2012", "-Wall", "-s", "unit_tb", "-o",
                   relative(executable), "rtl/bellows_l2_literal_buffer.sv",
                   "rtl/bellows_l2_emitter.sv", relative(bench)], extra_sources=[bench])
    record, stdout, stderr = execution.run(
        "unit-pipeline-simulate", ["vvp", relative(executable)], extra_sources=[bench])
    assert re.search(r"^UNIT_RESULT comparisons=17 transfers=2$", stdout, re.M), (
        "Missing checked unit quantities", stdout)
    execution.results.append(dict(kind="registered-public-module-pipeline",
                                  outcome="passed", comparisons=17, transferred_bytes=2,
                                  receipt=execution.children[-1]))
    execution.coverage["two-registered-stage-public-comparisons"] += 17


def synthesis(execution, label, capacity):
    directory = execution.output / label
    directory.mkdir()
    netlist = directory / "netlist.json"
    sources = sorted((ROOT / "rtl").glob("*.sv"))
    script = directory / "synthesis.ys"
    script.write_text(
        "read_verilog -sv " + " ".join(relative(p) for p in sources) + "\n"
        f"hierarchy -check -top bellows_l2_top -chparam MAX_BLOCK_BYTES {capacity}\n"
        "proc\nmemory_collect\nopt\nmemory_dff\nopt\nwreduce\nopt\n"
        "check -assert\nstat\n"
        f"write_json {relative(netlist)}\n")
    record, stdout, stderr = execution.run(
        label, ["yosys", "-Q", "-T", "-s", relative(script)], extra_sources=[script])
    data = json.loads(netlist.read_text())
    names = {}
    cells = Counter()
    memories = []
    state = Counter()
    for key, module in data["modules"].items():
        name = module.get("attributes", {}).get("hdlname", key).split()[0].lstrip("\\")
        names[name] = module
        for cell in module["cells"].values():
            kind = cell["type"]
            cells[kind] += 1
            if "dff" in kind.lower():
                state[name] += 1
            assert "latch" not in kind.lower(), f"Synthesized latch: {name}/{kind}"
            assert kind not in ("$div", "$mod", "$divfloor", "$modfloor"), (
                f"Combinational division/remainder: {kind}")
            if kind.startswith("$mem"):
                memories.append(dict(module=name, type=kind, parameters=cell["parameters"]))
    expected = {"bellows_l2_top", "bellows_l2_compressor", "bellows_l2_hash_match",
                "bellows_l2_literal_buffer", "bellows_l2_emitter", "bellows_l1_top",
                "bellows_l1_history", "bellows_l1_output"}
    assert set(names) == expected, ("Missing/extra synthesized hierarchy", set(names))
    for name in expected - {"bellows_l2_top", "bellows_l2_literal_buffer", "bellows_l1_history"}:
        assert state[name] > 0, f"Missing synthesizable sequential control: {name}"
    memory_owners = {m["module"] for m in memories}
    assert memory_owners >= {"bellows_l2_compressor", "bellows_l2_hash_match",
                             "bellows_l2_literal_buffer", "bellows_l1_history"}
    bits = Counter()
    for memory in memories:
        params = memory["parameters"]
        width, size = int(params["WIDTH"], 2), int(params["SIZE"], 2)
        bits[memory["module"]] += width * size
        reads = int(params["RD_PORTS"], 2)
        assert reads > 0 and int(params["RD_CLK_ENABLE"], 2) == (1 << reads) - 1, (
            "Asynchronously addressed memory", memory["module"])
    assert bits["bellows_l1_history"] == 65536 * 8
    assert bits["bellows_l2_literal_buffer"] == capacity * 8
    assert bits["bellows_l2_compressor"] == (2 * capacity + 16) * 8
    assert bits["bellows_l2_hash_match"] == 256 * 16
    for name in ("bellows_l2_top", "bellows_l2_compressor", "bellows_l1_top"):
        children = [c for c in names[name]["cells"].values() if not c["type"].startswith("$")]
        assert children and all(c["connections"] for c in children), f"Hierarchy wiring: {name}"
    result = dict(kind="yosys-coarse-synthesis", capacity=capacity, outcome="passed",
                  module_names=sorted(names), cells=dict(cells), memory_bits=dict(bits),
                  state_cells=dict(state), latch_cells=0, division_remainder_cells=0,
                  receipt=execution.children[-1], netlist=relative(netlist))
    json_write(directory / "structure.json", result)
    execution.results.append(result)
    execution.coverage["real-yosys-synthesis"] += 1


def illegal_parameters(execution):
    directory = execution.output / "illegal-parameters"
    directory.mkdir()
    sources = [relative(p) for p in sorted((ROOT / "rtl").glob("*.sv"))]
    for capacity in (0, 65537):
        executable = directory / f"bad-{capacity}.vvp"
        record, stdout, stderr = execution.run(
            f"illegal-{capacity}-compile",
            ["iverilog", "-g2012", "-Wall", "-s", "bellows_l2_top",
             f"-Pbellows_l2_top.MAX_BLOCK_BYTES={capacity}", "-o", relative(executable),
             *sources], expected=tuple(range(256)))
        if record["exit_code"] == 0:
            record, stdout, stderr = execution.run(
                f"illegal-{capacity}-diagnostic", ["vvp", relative(executable)],
                expected=tuple(range(256)))
            assert record["exit_code"] != 0 and "PARAMETER ERROR" in stdout + stderr
        else:
            assert stdout + stderr, "Silent illegal-parameter rejection"
        execution.results.append(dict(kind="illegal-parameter", capacity=capacity,
                                      outcome="rejected", receipt=execution.children[-1]))


def mutate(execution):
    variants = [
        ("offset", "bellows_l2_emitter.sv",
         "presented_data <= offset[7:0];",
         "presented_data <= offset[7:0] ^ 8'd1;", "ZERO_OFFSET"),
        ("trailing", "bellows_l2_hash_match.sv",
         "extension_limit = size - 17'd5;",
         "extension_limit = size - 17'd4;", "TRAILING_FIVE_LITERALS"),
        ("held-output", "bellows_l2_compressor.sv",
         "OUTPUT_HOLD: begin",
         "OUTPUT_HOLD: begin\n"
         "                    if (presented_valid && !m_ready)\n"
         "                        presented_data <= presented_data ^ 8'd1;",
         "HELD_C_OUTPUT"),
    ]
    for name, filename, before, after, expected in variants:
        directory = execution.output / f"mutant-{name}-sources"
        directory.mkdir()
        for source in sorted((ROOT / "rtl").glob("*.sv")):
            text = source.read_text()
            if source.name == filename:
                assert text.count(before) == 1, f"Mutation site changed: {filename}"
                text = text.replace(before, after)
            (directory / source.name).write_text(text)
        case = Case("mutant-feature", [Raw("offset-one-match", b"A" * 257,
                                        require_match=True)])
        if name == "held-output":
            run, _ = behavior(execution, f"mutant-{name}", 257, 1, [case], rtl=directory,
                              require_channels=False, expected_sim_failure=expected)
            failure = expected
        else:
            try:
                behavior(execution, f"mutant-{name}", 257, 1, [case], rtl=directory,
                         require_channels=False)
            except FormatError as error:
                failure = str(error)
                assert failure == expected, f"Wrong mutant rejection: {failure}"
                run = execution.output / f"mutant-{name}"
                trace = (run / "trace.txt").read_text()
                assert "CS 0 0 0" in trace and "DONE" in trace
            else:
                raise AssertionError(f"Unsensed synthesizable defect: {name}")
        result = dict(kind="defect-sensitivity", mutation=name, outcome="expected-rejection",
                      failure=failure, compile_receipt=execution.children[-2],
                      simulation_receipt=execution.children[-1], sources=relative(directory),
                      evidence=relative(run))
        json_write(run / "mutation-rejection.json", result)
        execution.results.append(result)
        execution.coverage[f"mutant-{name}"] += 1
    check_parent()


def clean_reproduction(execution):
    directory = execution.output / "reproduction" / "project"
    directory.mkdir(parents=True)
    for name, digest in execution.source_hashes.items():
        dest = directory / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
        assert sha(dest) == digest
    assert inputs(directory) == execution.source_hashes
    execution.run("clean-reproduction",
                  ["python3", "tests/verify.py", "--output", "result", "--subset", "reproduce"],
                  cwd=directory, extra_sources=[directory / name
                                                for name in execution.source_hashes])
    result = json.loads((directory / "result/results.json").read_text())
    assert result["outcome"] == "passed"
    assert result["coverage"]["internal-roundtrip-blocks"] > 0
    assert result["coverage"]["exact-fallback"] > 0
    assert result["coverage"]["concurrent"] > 0
    assert result["coverage"]["real-yosys-synthesis"] == 1
    execution.results.append(dict(kind="bounded-clean-reproduction", outcome="passed",
                                  receipt=execution.children[-1],
                                  result=relative(directory / "result/results.json")))


def occupied_destination(execution):
    directory = execution.output / "occupied"
    directory.mkdir()
    marker = directory / "sentinel.txt"
    marker.write_text("Retain occupied destination verbatim.\n")
    digest = sha(marker)
    record, stdout, stderr = execution.run(
        "occupied-output-rejection", ["python3", "tests/verify.py", "--output",
                                     relative(directory), "--subset", "reproduce"],
        expected=(1,))
    assert "occupied output destination" in stderr
    assert list(directory.iterdir()) == [marker] and sha(marker) == digest
    record, stdout, stderr = execution.run(
        "occupied-file-rejection", ["python3", "tests/verify.py", "--output",
                                    relative(marker), "--subset", "reproduce"],
        expected=(1,))
    assert "occupied output destination" in stderr and sha(marker) == digest
    missing = directory / "must-not-be-created"
    link = directory / "dangling"
    link.symlink_to(missing.name)
    parent_link = directory / "parent-link"
    parent_link.symlink_to(".", target_is_directory=True)
    for label, destination, diagnostic in (
            ("dangling-output", link, "occupied output destination"),
            ("symlink-parent", parent_link / missing.name, "symlinked output parent")):
        record, stdout, stderr = execution.run(
            f"{label}-rejection", ["python3", "tests/verify.py", "--output",
                                   destination.relative_to(ROOT).as_posix(),
                                   "--subset", "reproduce"], expected=(1,))
        assert diagnostic in stderr, f"Wrong rejection reason: {stderr}"
        assert not os.path.lexists(missing), "Rejected output created its target"
        assert link.is_symlink() and os.readlink(link) == missing.name
        assert parent_link.is_symlink() and os.readlink(parent_link) == "."
        assert sha(marker) == digest
    link.unlink()
    parent_link.unlink()
    assert list(directory.iterdir()) == [marker] and sha(marker) == digest
    execution.results.append(dict(
        kind="output-destination-rejections", outcome="passed",
        compared_cases=["occupied-directory", "occupied-file",
                        "dangling-symlink", "symlinked-parent"],
        sentinel_sha256=digest, rejected_targets_created=0))


def simulator_equivalence(execution):
    cases = matrix_cases(257, 89, targeted=True)
    traces = []
    for simulator in ("iverilog", "verilator"):
        directory, coverage = behavior(
            execution, f"backend-{simulator}", 257, 89, cases, simulator=simulator)
        for feature in ("concurrent", "internal-roundtrip-blocks", "exact-fallback"):
            assert coverage[feature] > 0, f"Backend smoke lacks {feature}"
        traces.append(directory / "trace.txt")
    assert traces[0].read_bytes() == traces[1].read_bytes(), (
        "Compact Icarus/Verilator public traces differ")
    execution.results.append(dict(
        kind="compact-simulator-equivalence", outcome="passed",
        traces=[relative(path) for path in traces],
        trace_integrity=file_integrity(traces[0])))


def preparation_regressions(execution):
    record, _, _ = execution.run(
        "preparation-regressions",
        ["python3", "-B", "tests/test_preparation.py"])
    execution.results.append(dict(
        kind="synthetic-recovery-safety-regressions", outcome="passed",
        exit_code=record["exit_code"], receipt=execution.children[-1],
        product_coverage=False, establishes_platform_retention_remedy=False,
        establishes_physical_acceptance=False))


def full(execution):
    preparation_regressions(execution)
    unit_pipeline(execution)
    simulator_equivalence(execution)
    for capacity in CAPACITIES:
        for seed in SEEDS:
            execution.matrix_status[(capacity, seed)] = "running"
            cases = matrix_cases(capacity, seed)
            directory, _ = behavior(execution, f"matrix-{capacity}-seed-{seed}",
                                    capacity, seed, cases)
            execution.matrix_status[(capacity, seed)] = "running"
            hardware_decode_compressed(execution, f"loopback-{capacity}-seed-{seed}",
                                       capacity, seed, cases, directory)
            execution.matrix_status[(capacity, seed)] = "passed"
    behavior(execution, "decoder-length-overflows", 13, 89,
             [Case("length-overflows", decoder=decoder_vectors(overflow=True))],
             require_channels=False)
    for capacity in CAPACITIES:
        synthesis(execution, f"synthesis-{capacity}", capacity)
    illegal_parameters(execution)
    mutate(execution)
    clean_reproduction(execution)
    occupied_destination(execution)
    required = ("hash-collision", "offset-one", "match-four", "last-match-start",
                "five-trailing", "literal-extension", "match-extension",
                "offset-65535", "history-wrap", "output-over-65536",
                "malformed", "post-error-recovery", "length-overflow",
                "reset-collect", "reset-match", "reset-emission", "reset-stalled",
                "latest-hash-entry", "hash-clearing",
                "internal-roundtrip-blocks", "independent-compressed-blocks",
                "independent-generated-blocks", "hardware-compress-hardware-decompress",
                "two-registered-stage-public-comparisons")
    for name in required:
        assert execution.coverage[name] > 0, f"Missing mandatory coverage: {name}"
    for capacity in (4096, 65536):
        for name in ("A", "ABCD", "byte-ramp"):
            assert execution.coverage[f"ratio-{capacity}-ratio-{name}"] == len(SEEDS)
    assert all(value == "passed" for value in execution.matrix_status.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--subset", choices=("all", "reproduce", "ratio-focused", "targeted",
                                            "boundary-focused", "extreme-focused",
                                            "final-focused", "overflow-focused",
                                            "backend-focused", "output-focused",
                                            "harness-focused"),
                        default="all")
    args = parser.parse_args()
    os.chdir(ROOT)
    output = args.output
    try:
        validate_output(output)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    output.mkdir(parents=True)
    execution = Execution(ROOT / output)
    try:
        execution.tools()
        check_parent()
        source_contract(execution)
        if args.subset == "all":
            full(execution)
        elif args.subset == "output-focused":
            occupied_destination(execution)
        elif args.subset == "harness-focused":
            preparation_regressions(execution)
        elif args.subset == "backend-focused":
            unit_pipeline(execution)
            simulator_equivalence(execution)
        elif args.subset == "ratio-focused":
            pattern = bytes(range(256))
            behavior(execution, "ratio-ramp-4096", 4096, 1,
                     [Case("ratio-ramp", [Raw("ratio-byte-ramp", pattern * 16,
                                            require_match=True, ratio=True)])],
                     require_channels=False)
        elif args.subset in ("boundary-focused", "final-focused"):
            unit_pipeline(execution)
            for capacity in (1, 13, 257):
                cases = matrix_cases(capacity, 17)
                directory, _ = behavior(execution, f"boundary-{capacity}", capacity, 17, cases)
                hardware_decode_compressed(execution, f"boundary-loopback-{capacity}",
                                           capacity, 17, cases, directory)
            for capacity in (1, 13):
                synthesis(execution, f"synthesis-{capacity}", capacity)
            if args.subset == "final-focused":
                synthesis(execution, "synthesis-257", 257)
                illegal_parameters(execution)
                mutate(execution)
                clean_reproduction(execution)
                occupied_destination(execution)
        elif args.subset == "overflow-focused":
            behavior(execution, "decoder-length-overflows", 13, 89,
                     [Case("length-overflows", decoder=decoder_vectors(overflow=True))],
                     require_channels=False)
        elif args.subset == "extreme-focused":
            capacity = 65536
            raw = [Raw("max-fallback", unique_bytes(capacity, random.Random(89)),
                       fallback=True)]
            for pattern, name in ((b"A", "A"), (b"ABCD", "ABCD"),
                                  (bytes(range(256)), "byte-ramp")):
                raw.append(Raw(f"ratio-{name}", (pattern * capacity)[:capacity],
                               require_match=True, ratio=True))
            behavior(execution, "extreme-65536", capacity, 89,
                     [Case("large-duplex", raw, decoder_vectors(large=True)),
                      Case("large-internal-route", [Raw("max-route", b"A" * capacity)],
                           roundtrip=True)])
            synthesis(execution, "synthesis-65536", capacity)
        else:
            unit_pipeline(execution)
            cases = matrix_cases(257, 89, targeted=True)
            simulator = "iverilog" if args.subset == "reproduce" else "verilator"
            directory, _ = behavior(execution, "targeted-257", 257, 89, cases,
                                    simulator=simulator)
            hardware_decode_compressed(execution, "targeted-loopback-257",
                                       257, 89, cases, directory, simulator=simulator)
            synthesis(execution, "synthesis-257", 257)
            if args.subset == "targeted":
                illegal_parameters(execution)
                mutate(execution)
        execution.finish("passed")
        print(f"Portable verification passed: {output.as_posix()}/results.json")
        return 0
    except Exception as error:
        detail = f"{type(error).__name__}: {error}"
        for key, value in execution.matrix_status.items():
            if value == "running":
                execution.matrix_status[key] = "failed"
        (execution.output / "failure.log").write_text(traceback.format_exc())
        execution.finish("failed", detail)
        print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
