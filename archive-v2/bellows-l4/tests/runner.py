"""Compile once per fresh execution; require complete public-pin comparisons."""

import hashlib
import json
from pathlib import Path
import re

from execution import ROOT, ToolFailure
from harnesses import copy_bench, top_bench
from scenarios import write_cases


class Simulation:
    def __init__(self, execution, root=ROOT):
        self.execution = execution
        self.root = root
        self.models = {}
        self.records = []

    def compile(self, name, bench_text, *, simulator="verilator", parent=False,
                rtl_files=None):
        key = (name, simulator, parent, hashlib.sha256(bench_text.encode()).hexdigest())
        if key in self.models:
            return self.models[key]
        ex = self.execution
        bench = ex.directory / f"{name}-{simulator}.sv"
        bench.write_text(bench_text)
        rel = lambda path: Path(path).relative_to(self.root).as_posix()
        rtl = rtl_files if rtl_files is not None else sorted(
            rel(p) for p in (self.root / (
                "bellows_l3_reference/rtl" if parent else "rtl")).glob("*.sv"))
        if simulator == "icarus":
            binary = ex.directory / f"{name}.vvp"
            ex.run(["iverilog", "-g2012", "-Wall", "-s", "tb", "-o", rel(binary),
                    rel(bench), *rtl], f"{name}-compile", cwd=self.root)
        else:
            obj = ex.directory / f"{name}-obj"
            ex.run(["verilator", "--binary", "--timing", "-Wno-fatal", "-j", "2",
                    "--top-module", "tb", "--Mdir", rel(obj), "-o", "simulation",
                    rel(bench), *rtl], f"{name}-compile", cwd=self.root)
            binary = obj / "simulation"
        self.models[key] = binary
        return binary

    def execute(self, binary, name, args=(), *, simulator="verilator",
                expect_assertion=None):
        ex = self.execution
        argv = [binary.relative_to(self.root).as_posix(), *args]
        if simulator == "icarus":
            argv.insert(0, "vvp")
        try:
            text = ex.run(argv, name, cwd=self.root,
                          timeout=600 if simulator == "icarus" else 2700)
        except ToolFailure:
            command = ex.receipt["commands"][-1]
            text = (ROOT / command["stdout"]).read_text()
            text += (ROOT / command["stderr"]).read_text()
            assertion = re.search(r"ASSERT [^\n]+", text)
            if (expect_assertion is None or command["timed_out"] or
                    command["exit_code"] in (None, 0) or assertion is None or
                    expect_assertion not in assertion[0]):
                raise
            result = {"name": name, "detected": True,
                      "assertion": assertion[0], "exit_code": command["exit_code"],
                      "stdout": command["stdout"], "stderr": command["stderr"]}
            ex.receipt.setdefault("mutation_detections", []).append(result)
            ex.save()
            return result
        if expect_assertion is not None:
            raise AssertionError(f"mutant escaped unchanged assertion: {name}")
        return text

    def top(self, width, block, cases, *, depth=16, simulator="verilator",
            parent=False, generation=4, label="cases", expect_assertion=None):
        name = f"{'reference-' if parent else ''}g{generation}-w{width}-b{block}-sg{depth}-{simulator}"
        bench = top_bench(width, block, depth, parent=parent or generation == 3)
        binary = self.compile(name, bench, simulator=simulator, parent=parent)
        vectors = self.execution.directory / f"{name}-{label}.vectors.txt"
        records = write_cases(vectors, cases)
        self.execution.receipt.setdefault("case_vectors", {})[f"{name}-{label}"] = records
        self.execution.save()
        text = self.execute(binary, f"{name}-{label}",
                            [f"+vectors={vectors.relative_to(self.root).as_posix()}"],
                            simulator=simulator, expect_assertion=expect_assertion)
        if expect_assertion is not None:
            return text
        lines = [line for line in text.splitlines() if line.startswith("CASE ")]
        expected_bytes = sum(len(case.expected) for case in cases if case.error == 0)
        summary = re.search(r"SUMMARY TOP cases=(\d+) bytes=(\d+)", text)
        if (summary is None or int(summary[1]) != len(cases) or
                int(summary[2]) != expected_bytes or len(lines) != len(cases)):
            raise AssertionError(f"incomplete public scoreboard: {name}-{label}")
        observations = []
        for case, record, line in zip(cases, records, lines):
            values = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)}
            if (values["bytes"] != len(case.expected) or values["error"] != case.error or
                    values["channel"] != case.channel or values["codec"] != case.codec or
                    values["wide"] != case.wide or
                    values["checksum_mode"] != case.checksum_mode or values["cycles"] <= 0):
                raise AssertionError(f"unexpected case ledger: {case.name}: {line}")
            observations.append({**record, **values, "configuration": [block, depth, width],
                                 "simulator": simulator, "parent": parent,
                                 "generation": generation})
        self.records.extend(observations)
        self.execution.receipt["observations"] = self.records
        self.execution.save()
        return observations

    def copy(self, width, block=65536, simulator="verilator", expect_assertion=None):
        name = f"copy-{width}-{block}-{simulator}"
        binary = self.compile(name, copy_bench(width, block), simulator=simulator,
                              rtl_files=["rtl/bellows_l4_copy_engine.sv"])
        text = self.execute(binary, name, simulator=simulator,
                            expect_assertion=expect_assertion)
        if expect_assertion is not None:
            return text
        summary = re.search(r"SUMMARY COPY width=(\d+) block=(\d+) beats=(\d+) bytes=(\d+)",
                            text)
        if (not summary or tuple(map(int, summary.group(1, 2))) != (width, block) or
                int(summary[3]) == 0 or int(summary[4]) == 0):
            raise AssertionError("incomplete copy reference scoreboard")
        measurements = []
        for line in text.splitlines():
            if line.startswith("MEASURE COPY "):
                row = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)}
                row["bytes_per_cycle"] = row["bytes"]/row["cycles"]
                row["required_bytes_per_cycle"] = 0.99*width
                if row["bytes"] < 4096 or row["bytes_per_cycle"] < 0.99*width:
                    raise AssertionError(f"copy throughput: {row}")
                measurements.append(row)
        if block == 65536 and {row["offset"] for row in measurements} != {0, 1, 3, 7, 16}:
            raise AssertionError("missing literal/overlap throughput comparison")
        self.execution.receipt.setdefault("copy_results", []).append({
            "parameters": [block, width], "simulator": simulator,
            "beats": int(summary[3]), "bytes": int(summary[4]),
            "measurements": measurements})
        self.execution.save()
        return measurements

    def save_coverage(self):
        successful = [r for r in self.records if r["expected_error"] == 0]
        coverage = {
            "compared_transactions": len(self.records),
            "successful_transactions": len(successful),
            "negative_transactions": len(self.records)-len(successful),
            "compared_bytes": sum(r["output_bytes"] for r in successful),
            "codecs": sorted({r["codec"] for r in successful}),
            "channels": sorted({r["channel"] for r in successful}),
            "transports": sorted({r["wide"] for r in successful}),
            "checksums": sorted({r["checksum_mode"] for r in successful}),
            "seeds": sorted({r["seed"] for r in successful}),
        }
        path = self.execution.directory / "coverage.json"
        path.write_text(json.dumps(coverage, indent=2)+"\n")
        return coverage
