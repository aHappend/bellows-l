"""Independent mandatory L1 entrypoint.

Reproduce from the project root with python3 tests/verify.py [--suite NAME].
Each selector performs its own work in a new evidence/l1-<hash>/ namespace.
Native timing, Quartus STA and hardware-bridge gates belong to the shared runtime.
"""

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from concurrent import concurrent_bench
from execution import Execution, ROOT, sources
from leaf_harnesses import ARBITRATION, TABLE, stream_bench, table_vectors
from reference import checksum, literal_block, lz4_decode, self_test
from runner import Simulation
from scenarios import (Case, codec_pair, descriptor_cases, entropy_cases, lz4_cases,
                       lz4_negative_cases, malformed_entropy_cases, performance_cases,
                       smoke_cases, write_cases)
from source_portability import inspect_sources
from structural import synthesize


SEEDS = (17, 89, 203)
GEOMETRIES = ((1, 1, 4), (1, 1, 8), (17, 3, 4), (17, 3, 8),
              (65536, 16, 4), (65536, 16, 8))


def compact_smoke(sim):
    for width in (4, 8):
        for block, depth in ((1, 1), (17, 3)):
            cases = smoke_cases(block)
            # SG fixtures requesting more descriptors have their own full-depth check.
            cases = [case for case in cases
                     if case.source_sizes is None or len(case.source_sizes) <= depth]
            if block == 1:
                cases += [Case("minimum-empty-BF16", b"", bytes(
                    b"BL4H\1\2\0\0"+bytes(12)+bytes(256)), codec=2, decompress=0),
                          Case("minimum-nonempty-BF16", b"\0\0", b"", codec=2,
                               decompress=0, error=8)]
            sim.top(width, block, cases, depth=depth, simulator="icarus", label="smoke")


def measure_performance(sim):
    parent = sim.top(8, 65536, performance_cases(parent=True), parent=True,
                     generation=3, label="performance")
    measurements = []
    for width in (4, 8):
        rows = sim.top(width, 65536, performance_cases(), label="performance")
        for index, (l3, l4) in enumerate(zip(parent, rows)):
            row = {"fixture": l4["name"], "width": width, "decoded_bytes": 32768,
                   "L3_cycles": l3["cycles"], "L4_cycles": l4["cycles"],
                   "speedup": l3["cycles"]/l4["cycles"],
                   "L3_bytes_per_cycle": 32768/l3["cycles"],
                   "L4_bytes_per_cycle": 32768/l4["cycles"],
                   "interval": "accepted command through accepted status, inclusive"}
            if index in (0, 3):
                row["required_speedup"] = float(width)
                if row["speedup"] < width:
                    raise AssertionError(f"integrated throughput requirement: {row}")
            measurements.append(row)
    sim.execution.receipt["performance"] = measurements
    sim.execution.save()


def exercise_concurrency(sim):
    for width in (4, 8):
        for phase in (None, 0, 1, 2, 3, 4, 5):
            name = f"concurrent-w{width}-reset{phase}"
            binary = sim.compile(name, concurrent_bench(width, reset_phase=phase))
            text = sim.execute(binary, name)
            summary = re.search(
                r"SUMMARY CONCURRENT width=(\d+) completions=(\d+) resets=(\d+) "
                r"reads=(\d+) writes=(\d+) bytes=(\d+) cycles=(\d+)", text)
            if (summary is None or int(summary[1]) != width or int(summary[2]) != 8 or
                    int(summary[3]) != int(phase is not None) or
                    min(map(int, summary.group(4, 5, 6, 7))) <= 0):
                raise AssertionError(f"incomplete concurrent scoreboard {name}")
            sim.execution.receipt.setdefault("concurrent_results", []).append({
                "width": width, "reset_phase": phase, "completions": 8,
                "read_requests": int(summary[4]), "write_requests": int(summary[5]),
                "compared_bytes": int(summary[6]), "cycles": int(summary[7]),
                "bytes_per_cycle": int(summary[6])/int(summary[7])})
            sim.execution.save()
    binary = sim.compile("arbitration", ARBITRATION,
                         rtl_files=["rtl/bellows_l4_scheduler.sv"])
    text = sim.execute(binary, "arbitration")
    if not re.search(r"SUMMARY ARBITRATION read=\d+ write=\d+ status=\d+ "
                     r"maximum_grant_gap=4", text):
        raise AssertionError("missing continuously-eligible four-grant comparisons")


def legacy_streams(sim, simulator="verilator", compact=False):
    raw = [b"", b"a", b"abc", b"x"*17, bytes(range(256)), b"abcd"*128]
    if compact:
        raw = raw[:4]
    for parent in (False, True):
        for generation in (1, 2):
            cases = []
            for i, data in enumerate(raw):
                pair = codec_pair(data, 0, f"legacy-g{generation}-fixture{i}", stalls=1)
                cases += [pair[1]] if generation == 1 else pair
            name = f"legacy-{'reference' if parent else 'shipped'}-g{generation}-{simulator}"
            bench = stream_bench(generation, 17 if compact else 65536)
            binary = sim.compile(name, bench, simulator=simulator, parent=parent)
            vectors = sim.execution.directory / f"{name}.vectors.txt"
            records = write_cases(vectors, cases)
            text = sim.execute(binary, name,
                               [f"+vectors={sim.execution.relative(vectors)}"],
                               simulator=simulator)
            summary = re.search(r"SUMMARY LEGACY cases=(\d+) bytes=(\d+)", text)
            if (not summary or int(summary[1]) != len(cases) or
                    int(summary[2]) != sum(len(case.expected) for case in cases)):
                raise AssertionError(f"legacy comparison ledger incomplete: {name}")
            sim.execution.receipt.setdefault("legacy_results", []).append({
                "generation": generation, "parent": parent, "simulator": simulator,
                "cases": records, "compared_bytes": int(summary[2])})
            sim.execution.save()


def invalid_parameters(sim):
    from harnesses import top_bench
    for parameter, value in (("MAX_BLOCK_BYTES", 0), ("MAX_BLOCK_BYTES", 65537),
                             ("SG_DEPTH", 0), ("SG_DEPTH", 17),
                             ("COPY_BYTES", 0), ("COPY_BYTES", 1), ("COPY_BYTES", 16)):
        block, depth, width = 17, 3, 8
        if parameter == "MAX_BLOCK_BYTES":
            block = value
        elif parameter == "SG_DEPTH":
            depth = value
        else:
            width = value
        # No operation or vector file is needed: the diagnostic must execute.
        text = top_bench(width, block, depth)
        name = f"invalid-{parameter}-{value}"
        binary = sim.compile(name, text, simulator="icarus")
        try:
            sim.execute(binary, name, simulator="icarus")
        except Exception as exc:
            from execution import ToolFailure
            if not isinstance(exc, ToolFailure):
                raise
            command = sim.execution.receipt["commands"][-1]
            logs = "".join((ROOT / command[key]).read_text() for key in ("stdout", "stderr"))
            if (command["timed_out"] or command["exit_code"] in (None, 0) or
                    "PARAMETER ERROR" not in logs):
                raise
            sim.execution.receipt.setdefault("parameter_diagnostics", []).append({
                "parameter": parameter, "value": value,
                "compile_exit": 0, "diagnostic_exit": command["exit_code"],
                "stdout": command["stdout"], "stderr": command["stderr"]})
            sim.execution.save()
        else:
            raise AssertionError(f"illegal parameter accepted: {parameter}={value}")


def lz4_suite(ex):
    sim = Simulation(ex)
    compact_smoke(sim)
    legacy_streams(sim, simulator="icarus", compact=True)
    legacy_streams(sim)
    for width in (4, 8):
        sim.copy(width, 1, "icarus")
        sim.copy(width, 17, "icarus")
        sim.copy(width)
        for seed in SEEDS:
            cases = lz4_cases(seed)
            sim.top(width, 65536, cases, label=f"seed{seed}")
        sim.top(width, 65536, lz4_negative_cases()+descriptor_cases(), label="negative-sg")
        for block, depth in ((1, 1), (17, 3)):
            sim.top(width, block, smoke_cases(block)[:8]+descriptor_cases(block, depth),
                    depth=depth, label="boundary")
        # Exact independently generated compressor bytes on preserved L3 and
        # integrated L4 interfaces supplement the stream compatibility checks.
        cases = []
        for i, raw in enumerate((b"", b"a", b"abc"*128, bytes(range(256))*4)):
            cases += codec_pair(raw, 0, f"parent-compressor{i}", wide=0,
                                channel=i & 3)
        sim.top(width, 65536, cases, generation=3, parent=True, label="compatibility")
        sim.top(width, 65536, cases, generation=3, label="compatibility")
        sim.top(width, 65536, cases, label="compatibility")
        legacy_negative = [replace(case, wide=0) for case in lz4_negative_cases()[:9]]
        sim.top(width, 65536, legacy_negative, generation=3, parent=True,
                label="malformed-compatibility")
        sim.top(width, 65536, legacy_negative, generation=3,
                label="malformed-compatibility")
        sim.top(width, 65536, legacy_negative, label="malformed-compatibility")
        for mode in (0, 1, 2):
            raw = bytes((i*37) & 255 for i in range(65536))
            sim.top(width, 65536, codec_pair(raw, 0, f"maximum-lz4-checksum{mode}",
                                           checksum_mode=mode), label=f"max-checksum{mode}")
    invalid_parameters(sim)
    measure_performance(sim)
    exercise_concurrency(sim)
    coverage = sim.save_coverage()
    for width in (4, 8):
        for seed in SEEDS:
            random_rows = [r for r in sim.records if r["name"].startswith(
                f"random-seed{seed}-") and r["configuration"][2] == width]
            if len(random_rows) < 64 or any(r["expected_error"] for r in random_rows):
                raise AssertionError(f"missing successful 64-block sweep width={width} seed={seed}")
    return coverage


def entropy_suite(ex):
    sim = Simulation(ex)
    for width in (4, 8):
        sim.top(width, 17, [case for case in smoke_cases(17) if case.codec],
                simulator="icarus", label="entropy-smoke")
        for seed in SEEDS:
            cases = entropy_cases(seed, maximum=seed == 17)
            rows = sim.top(width, 65536, cases, label=f"entropy-seed{seed}")
            for codec, threshold in ((1, 0.50), (2, 0.70), (3, 0.35)):
                row = next(r for r in rows if r["name"] ==
                           f"compressibility-mode{codec}-encode")
                ratio = row["output_bytes"]/row["input_bytes"]
                if ratio > threshold:
                    raise AssertionError(f"actual complete-frame compression mode{codec}: {ratio}")
                ex.receipt.setdefault("compression_results", []).append({
                    "width": width, "seed": seed, "codec": codec,
                    "frame_bytes": row["output_bytes"], "raw_bytes": row["input_bytes"],
                    "ratio": ratio, "maximum_ratio": threshold,
                    "cycles": row["cycles"], "raw_bytes_per_cycle":
                    row["input_bytes"]/row["cycles"]})
            ex.save()
        sim.top(width, 65536, malformed_entropy_cases(), label="malformed-entropy")
    vectors = ex.directory / "table.vectors.txt"
    records = table_vectors(vectors)
    binary = sim.compile("canonical-table", TABLE,
                         rtl_files=["rtl/bellows_l4_huffman_table.sv"])
    text = sim.execute(binary, "canonical-table",
                       [f"+vectors={ex.relative(vectors)}"])
    summary = re.search(r"SUMMARY TABLE cases=(\d+) lookups=(\d+)", text)
    if not summary or int(summary[1]) != len(records) or int(summary[2]) < 1000:
        raise AssertionError("canonical/fallback public lookup comparisons incomplete")
    ex.receipt["table_results"] = {"fixtures": records, "lookups": int(summary[2])}
    ex.save()
    coverage = sim.save_coverage()
    if set(coverage["codecs"]) != {0, 1, 2, 3, 4}:
        raise AssertionError("maximum-length all-codec comparisons missing")
    for width in (4, 8):
        for seed in SEEDS:
            rows = [r for r in sim.records if r["name"].startswith(f"seed{seed}-mode")
                    and r["configuration"][2] == width]
            if len(rows) < 128:
                raise AssertionError("entropy randomized encode/decode sweep incomplete")
    return coverage


MUTATIONS = (
    ("small-offset-overlap", "rtl/bellows_l4_copy_engine.sv",
     "1: seed_lane=0;", "1: seed_lane=lane;", "copy", "COPY DATA"),
    ("wide-tail-lanes", "rtl/bellows_l4_copy_engine.sv",
     ": 8'd0;", ": 8'hff;", "copy", "COPY DATA"),
    ("channel-ownership", "rtl/bellows_l4_sg_dma.sv",
     "w_rd_req_valid ? read_channel : 2'd0;",
     "w_rd_req_valid ? (read_channel ^ 2'd1) : 2'd0;", "ownership", "TOP READ OWNERSHIP"),
    ("canonical-bit-order", "rtl/bellows_l4_entropy.sv",
     "packed_byte[7-pack_fill]<=code_bits[15];",
     "packed_byte[7-pack_fill]<=code_bits[0];", "canonical", "TOP BYTE"),
    ("BF16-residual", "rtl/bellows_l4_entropy.sv",
     "{s_data[7],low_byte[6:0]} : s_data;",
     "{1'b0,low_byte[6:0]} : s_data;",
     "BF16", "TOP BYTE"),
    ("checksum-polynomial", "rtl/bellows_l3_checksum.sv",
     "32'hedb88320", "32'hedb88321", "checksum", "TOP BYTE"),
)


def mutation_case(kind):
    if kind == "ownership":
        return [Case("mutation-channel-ownership", literal_block(b"channel2-data"),
                     b"channel2-data", channel=2)]
    if kind == "canonical":
        return codec_pair(b"abacabad"*8, 1, "mutation-canonical")[:1]
    if kind == "BF16":
        return codec_pair(b"\x81\xbf\xff\xff\x7f\x80", 2, "mutation-BF16")[:1]
    if kind == "checksum":
        return codec_pair(b"123456789", 0, "mutation-CRC", checksum_mode=2)[:1]
    raise ValueError(kind)


def defects_suite(ex):
    baseline = Simulation(ex)
    results = []
    for name, filename, old, new, kind, assertion in MUTATIONS:
        # The exact unchanged functional case executes against unmodified RTL
        # before this mutation is compiled, in the same invocation.
        if kind == "copy":
            baseline.copy(8)
        else:
            baseline.top(8, 65536, mutation_case(kind), label=f"baseline-{name}")
        root = ex.directory / f"mutant-{name}-{uuid.uuid4().hex[:8]}"
        root.mkdir(exist_ok=False)
        for folder in ("rtl", "tests", "design", "bellows_l3_reference/rtl"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        for path in sources():
            target = root / path.relative_to(ROOT)
            shutil.copyfile(path, target)
        path = root / filename
        original = path.read_text()
        if original.count(old) != 1:
            raise AssertionError(f"mutation anchor is not unique: {name}: {original.count(old)}")
        mutated = original.replace(old, new)
        path.write_text(mutated)
        patch = ex.directory / f"{name}.patch"
        import difflib
        patch.write_text("".join(difflib.unified_diff(
            original.splitlines(True), mutated.splitlines(True),
            fromfile=filename, tofile=filename)))
        # The copied executable uses the unchanged oracle and generated bench.
        # A dedicated Execution whose directory is inside the disposable root
        # avoids compiler absolute paths and binds all mutated input sources.
        child = root / "tests/mutation_driver.py"
        child.write_text(
            "import sys\nfrom pathlib import Path\n"
            "sys.path.insert(0,str(Path(__file__).resolve().parent))\n"
            "from execution import Execution\nfrom runner import Simulation\n"
            "from verify import mutation_case\n"
            "ex=Execution('l1-mutation')\n"
            "try:\n"
            " sim=Simulation(ex)\n"
            + (" result=sim.copy(8,expect_assertion=" + repr(assertion) + ")\n"
               if kind == "copy" else
               " result=sim.top(8,65536,mutation_case("+repr(kind)+"),"
               "label='mutated',expect_assertion="+repr(assertion)+")\n")
            + " ex.finish('passed',detection=result)\n"
            "except Exception as exc:\n"
            " ex.finish('failed',diagnostic=f'{type(exc).__name__}: {exc}')\n"
            " raise\n")
        inventory = {p.relative_to(root).as_posix():
                     hashlib.sha256(p.read_bytes()).hexdigest() for p in sources(root)}
        text = ex.run(["python3", "tests/mutation_driver.py"], f"mutation-{name}", cwd=root)
        lines = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        result = lines[-1] if lines else {}
        detection = result.get("detection", {})
        if (result.get("outcome") != "passed" or detection.get("detected") is not True or
                assertion not in detection.get("assertion", "")):
            raise AssertionError(f"mutation lacks intended compiled assertion rejection: {name}")
        results.append({"name": name, "source_hashes": inventory,
                        "patch": ex.relative(patch), "workspace": ex.relative(root),
                        "child_receipt": ex.relative(root / result["receipt"]),
                        "assertion": detection["assertion"]})
        ex.receipt["defect_sensitivity"] = results
        ex.save()
    if len(results) < 6:
        raise AssertionError("six independently compiled functional defects required")
    return {"compiled_mutants": len(results), "reference_assertion_rejections": len(results)}


def synthesis_suite(ex):
    rows = [synthesize(ex, *geometry) for geometry in GEOMETRIES]
    if len(rows) != len(GEOMETRIES):
        raise AssertionError("synthesis configuration matrix incomplete")
    return {"synthesized_configurations": len(rows)}


def portability_suite(ex):
    issues = inspect_sources(ROOT)
    if issues:
        raise AssertionError(f"shipped source portability violations: {issues}")
    directory = ROOT / "evidence" / f"portable-{uuid.uuid4().hex[:16]}"
    directory.mkdir(parents=True, exist_ok=False)
    bindings = {}
    for path in sources():
        relative = path.relative_to(ROOT)
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        bindings[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    ex.receipt["portable_workspace"] = ex.relative(directory)
    ex.receipt["portable_source_hashes"] = bindings
    ex.save()
    # Both compact simulations and synthesis regenerate exclusively inside
    # the clean copied source tree; no original evidence or binaries are read.
    receipts = []
    for probe in ("top", "synthesis", "source-portability"):
        text = ex.run(["python3", "tests/probe.py", "--probe", probe],
                      f"portable-{probe}", cwd=directory)
        lines = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
        result = lines[-1] if lines else {}
        if result.get("outcome") != "passed":
            raise AssertionError(f"clean reproduction failed {probe}")
        receipt = directory / result["receipt"]
        if not receipt.is_file():
            raise AssertionError("clean reproduction missing execution receipt")
        receipts.append(ex.relative(receipt))
    ex.receipt["portable_receipts"] = receipts
    ex.save()
    return {"clean_reproduction_receipts": receipts, "copied_sources": len(bindings)}


SUITES = {"lz4": lz4_suite, "entropy": entropy_suite, "defects": defects_suite,
          "synthesis": synthesis_suite, "portability": portability_suite}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(SUITES))
    args = parser.parse_args()
    ex = Execution("l1")
    try:
        self_test()
        selected = (args.suite,) if args.suite else tuple(SUITES)
        tools = {"python3"}
        for suite in selected:
            tools.update({"yosys"} if suite == "synthesis" else (
                {"iverilog", "vvp", "yosys"} if suite == "portability" else
                {"verilator"} if suite == "defects" else {"iverilog", "vvp", "verilator"}))
        ex.versions(sorted(tools))
        results = {}
        for suite in selected:
            print(f"running independent {suite} verification", flush=True)
            results[suite] = SUITES[suite](ex)
        ex.finish("passed", suites=results)
        return 0
    except Exception as exc:
        ex.finish("failed", diagnostic=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    sys.exit(main())
