"""Reusable bounded executions of independently generated public transactions."""

import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from l1_transport import top_testbench
from preparation import check_results, sha256


def compiler_versions(experiment):
    tools = experiment.receipt.setdefault("tools", {})
    for tool in ("g++", "make"):
        if tool not in tools:
            output = experiment.command("version-" + tool, [tool, "--version"])
            tools[tool] = output.splitlines()[0]


class Simulation:
    def __init__(self, experiment, geometry, libraries, simulator="verilator", parent=False,
                 source_directory=None):
        self.experiment = experiment
        self.geometry = geometry
        self.libraries = libraries
        self.simulator = simulator
        self.parent = parent
        self.source_directory = source_directory
        self.directory = experiment.directory / ("simulation-" + uuid4().hex[:8])
        self.directory.mkdir()
        self.template = None
        self.runs = []

    def run(self, name, cases, seed=17, dictionary=b"", roundtrip=False):
        e = self.experiment
        run = self.directory / (name + "-" + uuid4().hex[:8])
        run.mkdir()
        tb = top_testbench(cases, self.geometry, run, seed, dictionary)
        if self.parent:
            from l1_transport import INPUTS, OUTPUTS
            extras = {n for n in (*INPUTS, *OUTPUTS) if n.startswith("dict_")
                      or n == "cmd_dict_id"}
            for n in extras:
                tb = tb.replace(f".{n}({n}),\n", "").replace(f",\n.{n}({n})", "")
            tb = tb.replace("bellows_l5_top #", "bellows_l4_top #")
            tb = tb.replace(f", .DICT_BYTES({self.geometry[3]})", "")
            # Parent standalone modules intentionally retain their reset behavior.
            a, b = tb.index("task reset_outputs;"), tb.index("always @(negedge clk)")
            tb = tb[:a] + "task reset_outputs; begin end endtask\n" + tb[b:]
            tb = tb.replace('if(cmd_ready!==0) $fatal(1,"lane command admission remained open");', "")
        if self.template is None:
            self.template = tb
            (self.directory / "tb.sv").write_text(tb)
            source_directory = self.source_directory or e.directory / "source" / (
                "bellows_l4_reference/rtl" if self.parent else "rtl")
            import os
            sources = [os.path.relpath(p, self.directory) for p in sorted(source_directory.glob("*.sv"))]
            if not sources:
                raise AssertionError("no declared RTL source files")
            if self.simulator == "icarus":
                e.command("icarus-version-" + self.directory.name, ["iverilog", "-V"])
                e.command("compile-" + self.directory.name,
                          ["iverilog", "-g2012", "-Wall", "-s", "tb",
                           "-Ptb.CYCLE_LIMIT=500000", "-o", "sim.vvp", "tb.sv", *sources],
                          cwd=self.directory)
            else:
                compiler_versions(e)
                e.command("verilator-version-" + self.directory.name, ["verilator", "--version"])
                e.command("compile-" + self.directory.name,
                          ["verilator", "--binary", "--timing", "-Wno-fatal",
                           "--top-module", "tb", "-j", "2", "--Mdir", "compile-obj",
                           "tb.sv", *sources], cwd=self.directory)
            (self.directory / "transactor-sha256.txt").write_text(sha256(tb.encode()) + "\n")
        elif tb != self.template:
            raise AssertionError("vector change requires a different transactor geometry")
        argv = (["vvp", "../sim.vvp"] if self.simulator == "icarus"
                else ["../compile-obj/Vtb"])
        stdout = e.command("execute-" + run.name, argv,
                           timeout=600 if self.simulator == "icarus" else 2400, cwd=run)
        load_cost = re.findall(r"DICTIONARY_COLD_LOAD bytes=(\d+) cycles=(\d+)", stdout)
        dictionary_loads = [{"bytes": int(n), "cycles": int(c)} for n, c in load_cost]
        check_results(e, cases, self.libraries, dictionary, run)
        records = json.loads((run / "comparisons.json").read_text())
        self.runs.append({"name": name, "seed": seed, "cases": len(cases),
                          "directory": e.relative(run), "comparisons": records,
                          "dictionary_loads": dictionary_loads})
        (self.directory / "runs.json").write_text(json.dumps(self.runs, indent=2) + "\n")
        if roundtrip:
            from l1_transport import Case
            lines = (run / "results.txt").read_text().splitlines()
            decodes = [Case("roundtrip-" + c.name, bytes.fromhex(lines[2*i+1]),
                            codec=c.codec, decompress=1, mode=c.mode, wide=c.wide,
                            channel=c.channel, capacity=max(1, len(c.source)),
                            dictionary_id=c.dictionary_id, segments=c.segments)
                       for i, c in enumerate(cases)]
            recovered = self.run(name + "-roundtrip", decodes, seed, dictionary)
            output = (self.directory / recovered["directory_name"] / "results.txt").read_text().splitlines()
            for i, c in enumerate(cases):
                if bytes.fromhex(output[2*i+1]) != c.source:
                    raise AssertionError(f"{c.name}: complete RTL round-trip mismatch")
        return {"records": records, "directory_name": run.name, "directory": run,
                "dictionary_loads": dictionary_loads}

    def close(self):
        build = self.directory / "compile-obj"
        if build.is_dir():
            executable = build / "Vtb"
            if executable.is_file():
                shutil.copy2(executable, self.directory / "simulator")
            shutil.rmtree(build)


def custom_simulation(experiment, name, generator, cases, geometry, libraries,
                      seed=17, dictionary=b"", simulator="verilator", concurrent=False):
    """Run a dedicated protocol/leaf transactor with retained raw results."""
    import os
    directory = experiment.directory / (name + "-" + uuid4().hex[:8])
    directory.mkdir()
    tb = generator(cases, geometry, directory, seed, dictionary)
    (directory / "tb.sv").write_text(tb)
    sources = [os.path.relpath(p, directory)
               for p in sorted((experiment.directory / "source/rtl").glob("*.sv"))]
    try:
        if simulator == "icarus":
            experiment.command(name + "-version", ["iverilog", "-V"])
            experiment.command(name + "-compile",
                               ["iverilog", "-g2012", "-Wall", "-s", "tb",
                                "-Ptb.CYCLE_LIMIT=500000", "-o", "sim.vvp", "tb.sv", *sources],
                               cwd=directory)
            experiment.command(name + "-simulation", ["vvp", "sim.vvp"], timeout=600, cwd=directory)
        else:
            compiler_versions(experiment)
            experiment.command(name + "-version", ["verilator", "--version"])
            experiment.command(name + "-compile",
                               ["verilator", "--binary", "--timing", "-Wno-fatal",
                                "--top-module", "tb", "-j", "2", "--Mdir", "compile-obj",
                                "tb.sv", *sources], cwd=directory)
            experiment.command(name + "-simulation", ["./compile-obj/Vtb"], cwd=directory)
        if cases:
            if concurrent:
                path = directory / "results.txt"
                lines = path.read_text().splitlines()
                if len(lines) != 8:
                    raise AssertionError("concurrent completion conservation")
                ordered = {}
                for i in range(0, 8, 2):
                    key = int(lines[i].split()[1])
                    if key in ordered:
                        raise AssertionError("duplicate concurrent completion")
                    ordered[key] = lines[i:i+2]
                shutil.copy2(path, directory / "results-arrival-order.txt")
                path.write_text("\n".join(line for k in range(4) for line in ordered[k]) + "\n")
            check_results(experiment, cases, libraries, dictionary, directory)
        return directory
    finally:
        build = directory / "compile-obj"
        if build.is_dir():
            if (build / "Vtb").is_file():
                shutil.copy2(build / "Vtb", directory / "simulator")
            shutil.rmtree(build)
