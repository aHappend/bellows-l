#!/usr/bin/env python3
"""Portable BELLOWS-L1 verification, from the delivered root.

Prerequisites: python3, iverilog, vvp, yosys. No packages or hardware needed.
  python3 tests/verify.py --suite smoke
  python3 tests/verify.py --suite all
The default is all. All runs retain fresh evidence/l1/<id>/ directories.
--preparation selects advisory evidence/preparation/<id>/ instead; --repair-of
links a prior failed receipt without replacing it.

Requirement map:
* scenarios.py REQUIRED bins: each observed in all nine seed/traffic cells;
  >=32 independently encoded/decoded randomized blocks per cell.
* transactor.py: pre-edge byte/last/status comparisons, both clock edges,
  X/Z, reset epochs, stall stability, conservation, error drain readiness,
  three completion orderings, real overflow input, bounded no-boundary waits.
  Case/completion records are flushed to stdout and a separate ledger; both
  must be complete and agree. Missing records are never reconstructed.
* mutations(): real copied-source compile, positive control and behavioral
  rejection, not syntax errors, timeouts or absent artifacts.
* synthesis(): actual reachable netlist, latches, hierarchy, sequential cells
  and full synchronous history; not a timing or physical-operation claim.
* reproduction(): clean shipped-source smoke, without inherited Python paths.

Every child has a >=3600-second operational deadline. Simulation cycle bounds
are conservative functions of input/output bytes and explicitly bounded stalls,
not throughput targets. Source additions, removals or changed bytes at child
boundaries or finalization fail the run; retain sources unchanged throughout.
Native L1.5/L2/L3 gates and the post-acceptance product
PDF belong to the shared runtime, never to this portable L1 suite.
"""

import argparse
import difflib
import json
from pathlib import Path
import re
import shutil
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lz4_reference import arithmetic_boundaries
from retention import Run, clean_environment, digest, source_files, write_json
from scenarios import Case, REQUIRED, directed, good, randomized, smoke, pattern
from transactor import generate


ROOT = Path(__file__).resolve().parents[1]


def save_cases(run: Run, cases: list[Case], name: str) -> list[dict]:
    folder = run.path / "stimulus" / name
    folder.mkdir(parents=True, exist_ok=False)
    records = []
    for index, case in enumerate(cases):
        case.check()
        compressed = folder / f"{index:03d}.input.bin"
        expected = folder / f"{index:03d}.expected.bin"
        compressed.write_bytes(case.block)
        expected.write_bytes(case.expected)
        records.append({
            "name": case.name, "input": run.relative(compressed),
            "expected": run.relative(expected), "input_length": len(case.block),
            "output_length": len(case.expected), "error": case.error,
            "detection": case.detection, "special": case.special,
            "first_byte": case.block[0],
            "order": case.order, "tags": sorted(case.tags),
            "input_sha256": digest(compressed), "expected_sha256": digest(expected),
        })
    write_json(folder / "manifest.json", records)
    return records


def parse_ledger(text: str, case_count: int, name: str) -> tuple[list, dict]:
    summaries = []
    completions = []
    for line in text.splitlines():
        if line.startswith("CASE "):
            match = re.fullmatch(r"CASE (\d+) (PASS|ABORT) ((?:\w+=-?\d+ ?)+)", line)
            if match is None:
                raise AssertionError(f"{name}: malformed executed-case record")
            summaries.append(match.groups())
        elif line.startswith("SIMULATION_COMPLETE"):
            match = re.fullmatch(r"SIMULATION_COMPLETE ((?:\w+=-?\d+ ?)+)", line)
            if match is None:
                raise AssertionError(f"{name}: malformed completion record")
            completions.append(match.group(1))
    if len(summaries) != case_count or len(completions) != 1:
        raise AssertionError(f"{name}: incomplete executed-case ledger")
    if [int(record[0]) for record in summaries] != list(range(case_count)):
        raise AssertionError(f"{name}: missing/duplicated case identity")
    totals = {key: int(value) for key, value in re.findall(
        r"(\w+)=(-?\d+)", completions[0]
    )}
    if totals.get("cases") != case_count:
        raise AssertionError(f"{name}: completion case count mismatch")
    return summaries, totals


def ledger_regression() -> dict:
    rows = [f"CASE {i} PASS in=1 out=0 error=0" for i in range(300)]
    completion = (
        "SIMULATION_COMPLETE cases=300 completed=300 aborted=0 statuses=300 "
        "simultaneous=0 back_to_back=299 cycles=10000"
    )
    text = "\n".join([*rows, completion]) + "\n"
    summaries, totals = parse_ledger(text, 300, "positive-control")
    if len(text) <= 8192 or len(summaries) != 300 or totals["statuses"] != 300:
        raise AssertionError("ledger parser positive control did not execute")
    fixtures = {
        "partial-record": text.replace(rows[57], "CASE 57 PASS in="),
        "missing-records": "\n".join([*rows[:58], *rows[85:], completion]),
        "duplicate-case": text.replace(rows[58], rows[57]),
        "missing-completion": "\n".join(rows),
        "duplicate-completion": text + completion + "\n",
        "wrong-case-total": text.replace("cases=300", "cases=299"),
        "buffer-sized-loss": text[:8192] + text[12288:],
    }
    for name, fixture in fixtures.items():
        try:
            parse_ledger(fixture, 300, name)
        except AssertionError:
            continue
        raise AssertionError(f"ledger parser accepted {name}")
    return {"positive_cases": 300, "positive_bytes": len(text),
            "rejected_corruptions": sorted(fixtures)}


def simulation(run: Run, records: list[dict], name: str, seed: int = 17,
               mode: int = 0, rtl: list[Path] | None = None,
               rejection: bool = False) -> dict:
    folder = run.path / name
    folder.mkdir(parents=True, exist_ok=False)
    tb = folder / "tb.sv"
    ledger = folder / "case-ledger.log"
    tb.write_text(generate(records, seed, mode, run.relative(ledger)), encoding="ascii")
    sources = sorted(ROOT.glob("rtl/*.sv")) if rtl is None else rtl
    executable = folder / "simulation.vvp"
    run.command(
        ["iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
         run.relative(executable), *[run.relative(p) for p in sources],
         run.relative(tb)], name + "/compile",
    )
    result = run.command(["vvp", run.relative(executable)], name + "/execute",
                         require_success=not rejection)
    log = (ROOT / result["stdout"]).read_text(encoding="utf-8")
    if rejection:
        # Only the byte/last/status scoreboard is acceptable mutant detection.
        if (result["timed_out"] or result["exit_status"] in (None, 0)
                or not re.search(r"MISMATCH .* (byte got=|last position mismatch|status got=)", log)):
            raise AssertionError(f"{name}: no actual targeted byte/status mismatch")
        mismatch = next(line for line in log.splitlines() if "MISMATCH" in line)
        return {"rejected": True, "first_mismatch": mismatch,
                "receipt": run.relative(folder / "execute/receipt.json")}
    summaries, totals = parse_ledger(log, len(records), name + "/stdout")
    if parse_ledger(ledger.read_text(encoding="ascii"), len(records),
                    name + "/case-ledger") != (summaries, totals):
        raise AssertionError(f"{name}: stdout and separate ledger disagree")
    normal = sum(not record["special"] for record in records)
    if (totals.get("completed") != normal or totals.get("statuses") != normal
            or totals.get("aborted") != len(records) - normal):
        raise AssertionError("completion/reset-epoch conservation")
    if len(records) > 1 and totals.get("back_to_back", 0) == 0:
        raise AssertionError("no immediate next-block transfer observed")
    observed = set()
    ledger = []
    for index, (number, outcome, fields) in enumerate(summaries):
        record = records[index]
        if int(number) != index:
            raise AssertionError("missing/duplicated case identity")
        counts = dict((key, int(value)) for key, value in re.findall(r"(\w+)=(-?\d+)", fields))
        if counts.get("in") != record["input_length"]:
            raise AssertionError("unobserved compressed input")
        if record["special"]:
            if outcome != "ABORT":
                raise AssertionError("reset/wait did not execute")
        else:
            if outcome != "PASS" or counts.get("out") != record["output_length"]:
                raise AssertionError("incomplete output comparison")
            if counts.get("error") != record["error"]:
                raise AssertionError("incorrect status ledger")
            if record["output_length"] and counts.get("comparisons", 0) == 0:
                raise AssertionError("zero byte comparisons")
        observed.update(record["tags"])
        ledger.append({"name": record["name"], "outcome": outcome,
                       "observed": counts, "tags": record["tags"]})
    result_summary = {
        "seed": seed, "traffic": ("ready", "random", "burst")[mode],
        "case_count": len(records), "observed_bins": sorted(observed),
        "random_valid_blocks": sum("random" in r["tags"] for r in records),
        "ledger": ledger, "receipt": run.relative(folder / "execute/receipt.json"),
        "raw_case_ledger": run.relative(folder / "case-ledger.log"),
        "observed_totals": totals,
    }
    write_json(folder / "results.json", result_summary)
    return result_summary


def mutations(run: Run) -> list[dict]:
    top_path = ROOT / "rtl/bellows_l1_top.sv"
    original = top_path.read_text(encoding="ascii")
    definitions = [
        (
            "offset-endianness",
            "wire [15:0] assembled_offset = {s_data, match_offset[7:0]};",
            "wire [15:0] assembled_offset = {match_offset[7:0], s_data};",
            good("palindromic-offset-control", [(pattern(257), 257, 4)], b"!"),
            good("offset-256-target", [(pattern(256), 256, 4)], b"!"),
        ),
        (
            "match-minimum-four", "+ 32'd4;",
            "+ (s_data[3:0] == 4'd15 ? 32'd4 : 32'd0);",
            good("extended-match-control", [(b"X", 1, 20)], b"!"),
            good("four-byte-match-target", [(b"X", 1, 4)], b"!"),
        ),
        (
            "stale-overlap",
            "wire [15:0] read_address = write_pointer - match_offset;",
            """reg [15:0] frozen_match_start;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) frozen_match_start <= 16'd0;
        else if (state == ST_OFFSET_HIGH && input_transfer)
            frozen_match_start <= write_pointer;
    end
    wire [15:0] normal_source = write_pointer - match_offset;
    wire [15:0] read_address = normal_source >= frozen_match_start
        ? frozen_match_start - 16'd2 : normal_source;""",
            good("nonoverlap-control", [(pattern(257), 257, 4)], b"!"),
            good("overlap-one-target", [(b"AB", 1, 70)], b"!"),
        ),
    ]
    results = []
    original_hashes = {p.name: digest(p) for p in ROOT.glob("rtl/*.sv")}
    for name, before, after, control, target in definitions:
        if original.count(before) != 1:
            raise AssertionError(f"{name}: ambiguous/absent mutation anchor")
        folder = run.path / "mutants" / name
        folder.mkdir(parents=True, exist_ok=False)
        rtl = []
        for source in sorted(ROOT.glob("rtl/*.sv")):
            destination = folder / source.name
            if source == top_path:
                destination.write_text(original.replace(before, after), encoding="ascii")
            else:
                shutil.copyfile(source, destination)
            rtl.append(destination)
        edit = {
            "before": before, "after": after, "original_sha256": digest(top_path),
            "mutant_sha256": digest(folder / top_path.name),
            "meaning": (
                "Dependent overlap reads select an older known pre-match byte, "
                "not the freshly committed byte; target AB/offset1 must repeat B."
                if name == "stale-overlap" else name
            ),
        }
        write_json(folder / "edit.json", edit)
        (folder / "change.diff").write_text("".join(difflib.unified_diff(
            original.splitlines(True),
            (folder / top_path.name).read_text().splitlines(True),
            fromfile="original/bellows_l1_top.sv", tofile="mutant/bellows_l1_top.sv",
        )), encoding="ascii")
        control_records = save_cases(run, [control], "control-" + name)
        target_records = save_cases(run, [target], "target-" + name)
        simulation(run, control_records, "mutants/" + name + "/positive-control", rtl=rtl)
        # Establish the target's sensitivity against unchanged real RTL first.
        simulation(run, target_records, "mutants/" + name + "/original-target")
        rejection = simulation(run, target_records,
                               "mutants/" + name + "/negative-target",
                               rtl=rtl, rejection=True)
        results.append({"mutant": name, "positive_control": "passed",
                        "original_target": "passed", **rejection})
    if original_hashes != {p.name: digest(p) for p in ROOT.glob("rtl/*.sv")}:
        raise AssertionError("mutation changed production sources")
    return results


def integer_parameter(value: str) -> int:
    return int(value, 2)


def synthesis(run: Run) -> dict:
    folder = run.path / "synthesis"
    folder.mkdir(exist_ok=False)
    script = folder / "synth.ys"
    netlist = folder / "netlist.json"
    rtl = " ".join(p.relative_to(ROOT).as_posix() for p in sorted(ROOT.glob("rtl/*.sv")))
    script.write_text(
        f"read_verilog -sv {rtl}\n"
        "hierarchy -check -top bellows_l1_top\n"
        "proc\nopt\nfsm\nopt\nwreduce\npeepopt\nopt_clean\n"
        "memory_dff\nmemory_collect\nopt\n"
        "check -assert\nstat\n"
        f"write_json {run.relative(netlist)}\n", encoding="ascii",
    )
    receipt = run.command(["yosys", "-Q", "-T", "-s", run.relative(script)],
                          "synthesis/execute")
    modules = json.loads(netlist.read_text())["modules"]
    visited = set()
    sequential = []
    memory = []
    unresolved = []
    latches = []
    arithmetic = []

    def inspect(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        module = modules[name]
        if int(str(module.get("attributes", {}).get("blackbox", "0")), 2):
            raise AssertionError(f"blackbox module {name}")
        for cname, cell in module.get("cells", {}).items():
            kind = cell["type"]
            identity = f"{name}/{cname}"
            if "latch" in kind.lower():
                latches.append(identity)
            if kind in ("$div", "$mod", "$divfloor", "$modfloor"):
                arithmetic.append(identity)
            if kind in modules:
                inspect(kind)
            elif not kind.startswith("$"):
                unresolved.append(identity)
            elif "dff" in kind.lower():
                sequential.append(identity)
            if kind == "$mem_v2":
                params = cell["parameters"]
                if (integer_parameter(params["SIZE"]) == 65536
                        and integer_parameter(params["WIDTH"]) == 8):
                    memory.append({"cell": identity, "parameters": params,
                                   "connections": cell["connections"]})
    inspect("bellows_l1_top")
    if latches or unresolved or arithmetic or not sequential or len(memory) != 1:
        raise AssertionError(
            f"netlist check: latches={latches} unresolved={unresolved} "
            f"div/mod={arithmetic} sequential={len(sequential)} memories={len(memory)}"
        )
    if not {"bellows_l1_history", "bellows_l1_output"} <= visited:
        raise AssertionError("required reachable literal hierarchy missing")
    registered = integer_parameter(memory[0]["parameters"]["RD_CLK_ENABLE"]) != 0
    if not registered:
        # Some Yosys versions keep the enabled async-reset read FF external.
        # Trace every memory output bit to an actual reachable clocked FF D pin.
        module_name = memory[0]["cell"].split("/", 1)[0]
        rd_bits = set(memory[0]["connections"]["RD_DATA"])
        registered_bits = set()
        for cell in modules[module_name]["cells"].values():
            if "dff" in cell["type"].lower():
                registered_bits.update(rd_bits.intersection(cell["connections"].get("D", [])))
        if registered_bits != rd_bits or len(rd_bits) != 8:
            raise AssertionError("history read not registered in actual netlist")
    result = {
        "reachable_modules": sorted(visited), "latch_cells": latches,
        "unresolved_cells": unresolved, "div_mod_cells": arithmetic,
        "sequential_cells": sequential, "history": memory,
        "registered_read": True, "receipt": run.relative(folder / "execute/receipt.json"),
        "netlist": run.relative(netlist),
    }
    write_json(folder / "results.json", result)
    return {"registered_read": True, "history_shape": [65536, 8],
            "latches": 0, "unresolved": 0, "sequential_cells": len(sequential),
            "receipt": run.relative(folder / "execute/receipt.json")}


def source_audit(run: Run) -> dict:
    # Audit only deliverable inputs, never runtime-owned metadata or transcripts.
    bad = []
    patterns = (
        r"/(?:home|data|root|Users|tmp)/[A-Za-z0-9_.-]+/",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"(?i)(?:jtag[_ -]?cable|pcie[_ -]?bdf)\s*=\s*['\"][^'\"]+",
    )
    for path in source_files(ROOT):
        text = path.read_text(encoding="utf-8")
        for expression in patterns:
            if re.search(expression, text):
                bad.append(path.relative_to(ROOT).as_posix())
    if bad:
        raise AssertionError("nonportable/private shipped source: " + ", ".join(bad))
    result = {"audited_files": [p.relative_to(ROOT).as_posix() for p in source_files(ROOT)],
              "private_paths_credentials_device_ids": 0}
    write_json(run.path / "source-audit.json", result)
    return result


def reproduction(run: Run) -> dict:
    folder = run.path / "clean-reproduction"
    folder.mkdir(exist_ok=False)
    hashes = {}
    for source in source_files(ROOT):
        relative = source.relative_to(ROOT)
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative.as_posix()] = digest(target)
    write_json(run.path / "clean-reproduction-inputs.json", hashes)
    receipt = run.command(
        ["python3", "tests/verify.py", "--suite", "smoke"],
        "clean-reproduction-execute", cwd=folder, env=clean_environment(),
    )
    child = list((folder / "evidence/l1").glob("*/results.json"))
    if len(child) != 1:
        raise AssertionError("clean smoke evidence absent or ambiguous")
    result = json.loads(child[0].read_text())
    if result.get("outcome") != "passed" or result["simulation"]["case_count"] < 5:
        raise AssertionError("clean smoke did not compare recovery and reuse")
    return {"receipt": run.relative(run.path / "clean-reproduction-execute/receipt.json"),
            "child_results": run.relative(child[0]), "outcome": "passed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("all", "smoke", "diagnostic"), default="all")
    parser.add_argument("--preparation", action="store_true")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    run = Run(ROOT, preparation=args.preparation, repair_of=args.repair_of)
    run.record["argv"] = ["python3", "tests/verify.py", *sys.argv[1:]]
    try:
        run.versions()
        results = {"suite": args.suite, "arithmetic": arithmetic_boundaries(),
                   "ledger_regression": ledger_regression()}
        results["audit"] = source_audit(run)
        if args.suite == "smoke":
            records = save_cases(run, smoke(), "smoke")
            results["simulation"] = simulation(run, records, "smoke", mode=2)
        elif args.suite == "diagnostic":
            if not args.preparation:
                raise ValueError("diagnostic is advisory and requires --preparation")
            records = save_cases(run, directed(include_overflow=False), "directed")
            results["simulations"] = [
                simulation(run, records, "directed-ready", mode=0),
                simulation(run, records, "directed-burst", mode=2),
                simulation(
                    run, records + save_cases(run, randomized(17), "random-17"),
                    "directed-random", mode=1,
                ),
            ]
            repeated = save_cases(run, smoke() * 32, "ledger-boundary")
            results["ledger_boundary"] = simulation(
                run, repeated, "ledger-boundary", seed=2026, mode=2,
            )
            results["mutations"] = mutations(run)
            results["synthesis"] = synthesis(run)
            results["reproduction"] = reproduction(run)
        else:
            records = save_cases(run, directed(), "directed")
            results["matrix"] = []
            for seed in (17, 89, 2026):
                random_records = save_cases(run, randomized(seed), f"random-{seed}")
                for mode in range(3):
                    summary = simulation(run, records + random_records,
                                         f"matrix/seed-{seed}-mode-{mode}", seed, mode)
                    missing = REQUIRED - set(summary["observed_bins"])
                    if missing or summary["random_valid_blocks"] < 32:
                        raise AssertionError(f"coverage gap seed={seed} mode={mode}: {sorted(missing)}")
                    results["matrix"].append(summary)
            results["mutations"] = mutations(run)
            results["synthesis"] = synthesis(run)
            results["reproduction"] = reproduction(run)
        run.assert_sources_unchanged()
        results["outcome"] = "passed"
        results["source_sha256"] = run.record["source_sha256"]
        write_json(run.path / "results.json", results)
        message = f"L1 {args.suite} passed; retained {run.relative(run.path / 'receipt.json')}"
        run.finish(0, stdout=message + "\n")
        print(message)
        return 0
    except (AssertionError, OSError, RuntimeError, ValueError) as error:
        message = f"L1 FAILED: {error}; retained {run.relative(run.path / 'receipt.json')}"
        diagnostic = traceback.format_exc() + message + "\n"
        run.finish(1, str(error), stderr=diagnostic)
        print(diagnostic, end="", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
