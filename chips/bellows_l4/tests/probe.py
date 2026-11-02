"""Bounded diagnostic entry; admitted delivery checks use verify.py."""

import argparse
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Execution, ROOT
from harnesses import copy_bench, top_bench
from reference import self_test
from scenarios import entropy_cases, performance_cases, smoke_cases, write_cases
from structural import synthesize


def authoring_probe(ex, focus):
    from runner import Simulation
    from scenarios import descriptor_cases, lz4_negative_cases, malformed_entropy_cases
    from verify import compact_smoke, invalid_parameters, legacy_streams
    sim = Simulation(ex)
    if focus == "reference":
        from scenarios import lz4_cases
        from verify import MUTATIONS
        counts = {"lz4": len(lz4_cases(17)), "malformed": len(malformed_entropy_cases())}
        for _, filename, old, _, _, _ in MUTATIONS:
            assert (ROOT / filename).read_text().count(old) == 1
        assert counts["malformed"] >= 100
        return counts
    if focus == "startup":
        compact_smoke(sim)
        invalid_parameters(sim)
        return sim.save_coverage()
    if focus == "legacy":
        legacy_streams(sim, simulator="icarus", compact=True)
        return ex.receipt["legacy_results"]
    if focus == "negative":
        cases = lz4_negative_cases(17)[:9]+descriptor_cases(17, 3)
        sim.top(8, 17, cases, depth=3, simulator="icarus", label="negative")
        return sim.save_coverage()
    if focus == "short-header":
        cases = [case for case in malformed_entropy_cases()
                 if "short-header" in case.name][:1]
        sim.top(8, 17, cases, simulator="icarus", label="short-header")
        return sim.save_coverage()
    if focus == "table":
        from leaf_harnesses import TABLE, table_vectors
        vectors = ex.directory / "table.vectors.txt"
        fixtures = table_vectors(vectors)
        binary = sim.compile("table", TABLE,
                             rtl_files=["rtl/bellows_l4_huffman_table.sv"])
        text = sim.execute(binary, "table", [f"+vectors={ex.relative(vectors)}"])
        assert "SUMMARY TABLE cases=12 " in text
        return {"fixtures": fixtures, "observations": text.splitlines()}
    if focus == "concurrent":
        from concurrent import concurrent_bench
        binary = sim.compile("concurrent", concurrent_bench(8))
        text = sim.execute(binary, "concurrent")
        assert "SUMMARY CONCURRENT width=8 completions=8 resets=0 " in text
        return text.splitlines()
    raise ValueError(focus)


def copy_probe(execution, width, block, simulator):
    name = f"copy-{width}-{block}-{simulator}"
    bench = execution.directory / f"{name}.sv"
    bench.write_text(copy_bench(width, block))
    rel = execution.relative
    rtl = "rtl/bellows_l4_copy_engine.sv"
    if simulator == "icarus":
        binary = execution.directory / f"{name}.vvp"
        execution.run(["iverilog", "-g2012", "-Wall", "-s", "tb",
                       "-o", rel(binary), rel(bench), rtl], f"{name}-compile")
        text = execution.run(["vvp", rel(binary)], name, timeout=600)
    else:
        obj = execution.directory / f"{name}-obj"
        execution.run(["verilator", "--binary", "--timing", "-Wno-fatal",
                       "--top-module", "tb", "--Mdir", rel(obj),
                       "-o", "simulation", rel(bench), rtl], f"{name}-compile")
        text = execution.run([rel(obj / "simulation")], name)
    if f"SUMMARY COPY width={width} block={block}" not in text:
        raise AssertionError("missing completed copy scoreboard")
    return text.strip().splitlines()


def top_probe(execution, width, block, simulator, cases=None, parent=False):
    name = f"{'parent' if parent else 'top'}-{width}-{block}-{simulator}"
    bench = execution.directory / f"{name}.sv"
    bench.write_text(top_bench(width, block, parent=parent))
    vectors = execution.directory / f"{name}.vectors.txt"
    selected = smoke_cases(block) if cases is None else cases
    records = write_cases(vectors, selected)
    execution.receipt.setdefault("case_vectors", {})[name] = records
    execution.save()
    rel = execution.relative
    rtl = sorted(p.relative_to(ROOT).as_posix() for p in (
        ROOT / ("bellows_l3_reference/rtl" if parent else "rtl")).glob("*.sv"))
    if simulator == "icarus":
        binary = execution.directory / f"{name}.vvp"
        execution.run(["iverilog", "-g2012", "-Wall", "-s", "tb",
                       "-o", rel(binary), rel(bench), *rtl], f"{name}-compile")
        text = execution.run(["vvp", rel(binary), f"+vectors={rel(vectors)}"],
                             name, timeout=600)
    else:
        obj = execution.directory / f"{name}-obj"
        execution.run(["verilator", "--binary", "--timing", "-Wno-fatal",
                       "--top-module", "tb", "--Mdir", rel(obj),
                       "-o", "simulation", rel(bench), *rtl], f"{name}-compile")
        text = execution.run([rel(obj / "simulation"), f"+vectors={rel(vectors)}"], name)
    case_lines = [line for line in text.splitlines() if line.startswith("CASE ")]
    if len(case_lines) != len(selected) or f"SUMMARY TOP cases={len(selected)} " not in text:
        raise AssertionError("incomplete top-level comparison ledger")
    return case_lines


def performance_probe(execution):
    parent_lines = top_probe(execution, 8, 65536, "verilator",
                             performance_cases(parent=True), parent=True)
    parent_cycles = [int(re.search(r"cycles=(\d+)", line)[1]) for line in parent_lines]
    measurements = []
    for width in (4, 8):
        lines = top_probe(execution, width, 65536, "verilator", performance_cases())
        cycles = [int(re.search(r"cycles=(\d+)", line)[1]) for line in lines]
        for i, (l3, l4) in enumerate(zip(parent_cycles, cycles)):
            measurements.append({"fixture": performance_cases()[i].name, "width": width,
                                 "decoded_bytes": 32768, "L3_cycles": l3, "L4_cycles": l4,
                                 "speedup": l3 / l4, "L4_bytes_per_cycle": 32768 / l4})
        execution.receipt["performance"] = measurements
        execution.save()
        for i in (0, 3):
            if parent_cycles[i] < width * cycles[i]:
                raise AssertionError(f"integrated speedup {performance_cases()[i].name}: "
                                     f"L3={parent_cycles[i]} L4={cycles[i]} "
                                     f"ratio={parent_cycles[i]/cycles[i]:.6f} "
                                     f"required={width}.0")
    return measurements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", choices=["copy", "top", "performance", "entropy", "synthesis",
                                          "source-portability", "authoring"],
                        default="copy")
    parser.add_argument("--focus", choices=["reference", "startup", "legacy", "negative",
                                          "short-header", "table", "concurrent"],
                        default="reference")
    parser.add_argument("--simulator", choices=["icarus", "verilator"], default="icarus")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    ex = Execution(f"{args.probe}-diagnostic", preparation=True, repair_of=args.repair_of)
    try:
        self_test()
        simulator = "verilator" if args.probe in ("performance", "entropy") else args.simulator
        tools = ["python3", "iverilog", "vvp", "verilator"] if args.probe == "authoring" else (
            ["python3"] if args.probe == "source-portability" else (
            ["python3", "yosys"] if args.probe == "synthesis" else (
            ["python3", "iverilog", "vvp"] if simulator == "icarus"
            else ["python3", "verilator"])))
        ex.versions(tools)
        records = []
        if args.probe == "authoring":
            records = authoring_probe(ex, args.focus)
        elif args.probe == "source-portability":
            records = ex.run(["python3", "tests/source_portability.py"], "source-portability")
        elif args.probe == "synthesis":
            records = [synthesize(ex, 1, 1, 4)]
        elif args.probe == "performance":
            records = performance_probe(ex)
        elif args.probe == "entropy":
            cases = entropy_cases(17)
            records = top_probe(ex, 8, 65536, simulator, cases=cases[:40])
        else:
            for block in ((1, 17, 65536) if args.probe == "copy" else (17,)):
                for width in (4, 8):
                    probe = copy_probe if args.probe == "copy" else top_probe
                    records.extend(probe(ex, width, block, simulator))
        ex.finish("passed", observations=records)
    except Exception as exc:
        ex.finish("failed", diagnostic=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
