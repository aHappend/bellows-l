"""Bounded diagnostic entry; admitted delivery checks use verify.py."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Execution, ROOT
from harnesses import copy_bench
from reference import self_test


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", choices=["copy"], default="copy")
    parser.add_argument("--simulator", choices=["icarus", "verilator"], default="icarus")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    ex = Execution(f"{args.probe}-diagnostic", preparation=True, repair_of=args.repair_of)
    try:
        self_test()
        ex.versions(["python3", "iverilog", "vvp"] if args.simulator == "icarus"
                    else ["python3", "verilator"])
        records = []
        for block in (1, 17, 65536):
            for width in (4, 8):
                records.extend(copy_probe(ex, width, block, args.simulator))
        ex.finish("passed", observations=records)
    except Exception as exc:
        ex.finish("failed", diagnostic=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
