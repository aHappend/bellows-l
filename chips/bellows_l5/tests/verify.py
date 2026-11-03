"""Portable BELLOWS-L5 L1 verification.

Prerequisites: Python 3.10+, Icarus, Verilator 5.x with a compatible C++
compiler and make, Yosys, and shared libzstd/liblz4/libxxhash (including
ZSTD_DCtx_loadDictionary_advanced). Run admitted commands from the project root.
Native timing and hardware gates are owned and recorded by the shared runtime.
The low-32-bit XXH64 content checksum detects corruption, not authentication;
valid semantic-equivalent mutations are recorded explicitly.
"""

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
import traceback
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l1_fse import table_testbench
from l1_dictionary import dictionary_testbench
from l1_matrix import (SEEDS, boundaries, codec_matrix, constant_tables, dictionary_edges, errors,
                      malformed_tables, sequence_boundaries)
from l1_oracle import Libraries, frame, rle_sequence_frame
from l1_protocol import concurrent_testbench, lifecycle_testbench
from l1_runner import Simulation, custom_simulation
from l1_synthesis import synthesis
from l1_transport import Case
from preparation import (CONFIGURATIONS, ROOT, Experiment, cases_for, corruption_cases,
                         dictionary_cases, interop_cases, legacy_cases, sha256)


def libraries_for(experiment):
    libraries = Libraries()
    experiment.receipt["libraries"] = libraries.versions()
    rng = random.Random(2026)
    for length in (0, 1, 2, 3, 7, 8, 15, 16, 17, 31, 32, 33, 255, 256, 4096, 65536):
        libraries.check_hash(rng.randbytes(length))
    return libraries


def leaf(experiment, simulator):
    custom_simulation(experiment, "fse-" + simulator,
                      lambda c, g, d, s, b: table_testbench(d), [], (3, 3, 8, 7),
                      None, simulator=simulator)


def protocol(experiment, geometry, libraries, seed=17, simulator="verilator"):
    dictionary = bytes(range(min(geometry[3], 7)))
    raw = b"ab"[:geometry[0]]
    cases = [Case("concurrent-" + str(i), raw, codec=(0, 1, 5, 6)[i],
                  channel=i, wide=i & 1, capacity=1024,
                  dictionary_id=0x12345678 if i == 3 else 0) for i in range(4)]
    custom_simulation(experiment, "concurrent-" + str(seed), concurrent_testbench,
                      cases, geometry, libraries, seed, dictionary, concurrent=True)
    custom_simulation(experiment, "lifecycle-" + str(seed),
                      lambda c, g, d, s, b: lifecycle_testbench(g, d),
                      [Case("recovery", b"x", capacity=64)], geometry, libraries,
                      simulator=simulator)
    custom_simulation(experiment, "dictionary-views-" + str(seed),
                      lambda c, g, d, s, b: dictionary_testbench(d, g[3]),
                      [], geometry, libraries, simulator=simulator)


def parameters(experiment):
    """Illegal values must elaborate before their explicit runtime diagnostic."""
    directory = experiment.directory / ("parameters-" + uuid4().hex[:8])
    directory.mkdir()
    sources = [os.path.relpath(p, directory)
               for p in sorted((experiment.directory / "source/rtl").glob("*.sv"))]
    fields = ("MAX_BLOCK_BYTES", "SG_DEPTH", "COPY_BYTES", "DICT_BYTES")
    values = ((0, 65537), (0, 17), (1, 16), (0, 16385))
    records = []
    for index, illegal in enumerate(values):
        for value in illegal:
            geometry = [3, 3, 8, 7]
            geometry[index] = value
            name = f"illegal-{fields[index]}-{value}"
            tb = "module tb;\nreg clk=0,rst_n=0;\nalways #5 clk=~clk;\n"
            tb += "bellows_l5_top #(" + ",".join(
                f".{key}({v})" for key, v in zip(fields, geometry)) + ") dut(.clk(clk),.rst_n(rst_n));\n"
            tb += 'initial begin #20; $fatal(1,"missing parameter diagnostic"); end\nendmodule\n'
            (directory / (name + ".sv")).write_text(tb)
            experiment.command(name + "-compile",
                               ["iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
                                name + ".vvp", name + ".sv", *sources], cwd=directory)
            output = experiment.command(name + "-diagnostic", ["vvp", name + ".vvp"],
                                        timeout=600, cwd=directory, expect_failure=True)
            if "PARAMETER ERROR" not in output:
                raise AssertionError(f"{name}: illegal geometry failed without required diagnostic")
            records.append({"parameter": fields[index], "value": value,
                            "elaborated": True, "explicit_diagnostic": True})
    # The additional required maximum geometry with COPY_BYTES=4.
    experiment.command("copy4-elaboration",
                       ["iverilog", "-g2012", "-Wall", "-s", "bellows_l5_top",
                        "-Pbellows_l5_top.COPY_BYTES=4", "-o", "copy4.vvp", *sources],
                       cwd=directory)
    (directory / "parameter-comparisons.json").write_text(json.dumps(records, indent=2) + "\n")


def dictionary_gain(experiment, simulation, seed):
    dictionary, cases, manifest = dictionary_cases(seed)
    run = simulation.run("gain-" + str(seed), cases, seed, dictionary, roundtrip=True)
    lines = (run["directory"] / "results.txt").read_text().splitlines()
    baseline_total = candidate_total = 0
    for i, record in enumerate(manifest):
        baseline = bytes.fromhex(lines[4*i+1])
        candidate = bytes.fromhex(lines[4*i+3])
        observed = run["records"][2*i+1]
        if not observed["dictionary_matches"] or not observed["fse_transitions"]:
            raise AssertionError("gain fixture did not execute dictionary references and FSE")
        if 4*len(candidate) > 3*len(baseline):
            raise AssertionError(f"dictionary gain seed={seed} page={record['page_bytes']}")
        record.update(candidate_bytes=len(candidate), baseline_bytes=len(baseline),
                      dictionary_matches=observed["dictionary_matches"],
                      fse_transitions=observed["fse_transitions"])
        baseline_total += len(baseline)
        candidate_total += len(candidate)
    if 2*candidate_total > baseline_total:
        raise AssertionError("dictionary aggregate exceeds 50% baseline")
    result = {"seed": seed, "generator": dictionary_cases.__doc__,
              "dictionary_sha256": sha256(dictionary), "cases": manifest,
              "baseline_bytes": baseline_total, "candidate_bytes": candidate_total,
              "cold_load_bytes": len(dictionary), "cold_load_transactions": run["dictionary_loads"],
              "pinned_logical_storage_bytes": len(dictionary),
              "physical_byte_views": 4, "physical_byte_image_bytes": 4*len(dictionary)}
    (run["directory"] / "gain.json").write_text(json.dumps(result, indent=2) + "\n")
    return result, dictionary, cases, run


def page_corruption(experiment, simulation, seed, dictionary, cases, run):
    lines = (run["directory"] / "results.txt").read_text().splitlines()
    generator = random.Random(seed ^ 0xC077)
    corrupt = []
    manifest = []
    from l1_zstd import FrameError, decode_frame
    for page in range(3):
        original = bytes.fromhex(lines[4*page+3])
        raw = cases[2*page+1].source
        bits = generator.sample(range(len(original)*8), 64)
        for bit in bits:
            changed = bytearray(original)
            changed[bit//8] ^= 1 << (bit%8)
            changed = bytes(changed)
            try:
                model = decode_frame(changed, dictionary).data
            except FrameError:
                model = None
            try:
                library = simulation.libraries.decompress_zstd(changed, len(raw), dictionary)
            except ValueError:
                library = None
            if model is not None and library is not None and model != library:
                raise AssertionError("page corruption oracles disagree")
            accepted = model is not None and library is not None
            manifest.append({"page_bytes": len(raw), "bit": bit,
                             "input_sha256": sha256(changed), "parser_accepts": model is not None,
                             "libzstd_accepts": library is not None,
                             "semantically_equivalent": accepted and model == raw})
            corrupt.append(Case(f"page{len(raw)}-bit{bit}", changed, codec=6,
                                decompress=1, capacity=len(raw), wide=1,
                                dictionary_id=0x12345678, error=0 if accepted else -1))
    observed = simulation.run("page-corruption", corrupt, seed, dictionary)
    (observed["directory"] / "corruption.json").write_text(json.dumps(manifest, indent=2) + "\n")


def behavior(experiment, configuration):
    libraries = libraries_for(experiment)
    geometry = CONFIGURATIONS[configuration]
    simulation = Simulation(experiment, geometry, libraries)
    parent = Simulation(experiment, geometry, libraries, parent=True)
    ledger = []
    try:
        for seed in SEEDS:
            dictionary = random.Random(seed).randbytes(min(geometry[3], 1024))
            matrix = codec_matrix(geometry, seed, dictionary)
            simulation.run("codec-matrix-" + str(seed), matrix, seed, dictionary)
            simulation.run("dictionary-edges-" + str(seed),
                           dictionary_edges(geometry, dictionary, libraries), seed, dictionary)
            negative = errors(geometry, dictionary)
            simulation.run("errors-" + str(seed), negative, seed, dictionary)
            legacy_negative = [c for c in negative if c.codec < 5 or c.codec == 7]
            old_negative = parent.run("parent-errors-" + str(seed), legacy_negative, seed)
            new_negative = simulation.run("legacy-errors-" + str(seed), legacy_negative, seed)
            if (old_negative["directory"] / "results.txt").read_bytes() != (
                    new_negative["directory"] / "results.txt").read_bytes():
                raise AssertionError("legacy negative behavior differs from immutable parent")
            boundary_cases = boundaries(geometry, seed)
            if seed != SEEDS[0]:
                boundary_cases = [c for c in boundary_cases if len(c.source) <= 257]
            simulation.run("boundaries-" + str(seed), boundary_cases, seed,
                           dictionary, roundtrip=True)
            legacy = legacy_cases(geometry, include_max=seed == SEEDS[0])
            new = simulation.run("legacy-" + str(seed), legacy, seed)
            old = parent.run("parent-legacy-" + str(seed), legacy, seed)
            if (new["directory"] / "results.txt").read_bytes() != (
                    old["directory"] / "results.txt").read_bytes():
                raise AssertionError("delivered legacy behavior differs from immutable parent")
            ledger.append({"seed": seed, "codec_matrix": len(matrix),
                           "negative_cases": len(negative), "parent_differential": len(legacy)})
        simulation.run("missing-dictionary-and-recovery",
                       [Case("absent-dictionary", b"x", codec=6, dictionary_id=0x12345678,
                             error=13, pre_dma=True),
                        Case("codec5-after-absent", b"x")])
        if geometry[0] >= 16:
            external = sequence_boundaries(geometry, libraries)
            simulation.run("rfc-length-offset-boundaries", external)
        if configuration == "default":
            parameters(experiment)
            leaf(experiment, "verilator")
            for pinned in (False, True):
                dictionary = (bytes.fromhex("37a430ec") +
                              random.Random(2026).randbytes(1020)) if pinned else b""
                simulation.run("interop-" + str(pinned), interop_cases(libraries, dictionary),
                               dictionary=dictionary)
                simulation.run("malformed-tables-" + str(pinned),
                               malformed_tables(libraries, dictionary), dictionary=dictionary)
                simulation.run("constant-tables-" + str(pinned),
                               constant_tables(libraries, dictionary), dictionary=dictionary)
                corrupt, manifest = corruption_cases(libraries, dictionary)
                run = simulation.run("short-corruption-" + str(pinned), corrupt,
                                     dictionary=dictionary)
                (run["directory"] / "corruption.json").write_text(
                    json.dumps(manifest, indent=2) + "\n")
            gain = []
            for seed in SEEDS:
                result, dictionary, cases, run = dictionary_gain(experiment, simulation, seed)
                gain.append(result)
                if seed == 2026:
                    page_corruption(experiment, simulation, seed, dictionary, cases, run)
            total_baseline = sum(r["baseline_bytes"] for r in gain)
            total_candidate = sum(r["candidate_bytes"] for r in gain)
            if total_candidate * 2 > total_baseline or sum(len(r["cases"]) for r in gain) != 9:
                raise AssertionError("nine-case aggregate dictionary threshold not met")
            (experiment.directory / "gain-summary.json").write_text(json.dumps(
                {"seeds": gain, "candidate_bytes": total_candidate,
                 "baseline_bytes": total_baseline}, indent=2) + "\n")
        protocol(experiment, geometry, libraries)
        if configuration in ("singleton", "nonpower"):
            smoke(experiment, libraries, leaf_check=configuration == "nonpower")
        (experiment.directory / "coverage.json").write_text(json.dumps(
            {"configuration": configuration, "geometry": geometry, "runs": ledger,
             "complete_byte_comparisons": experiment.receipt["complete_byte_comparisons"]},
            indent=2) + "\n")
    finally:
        simulation.close()
        parent.close()


def smoke(experiment, libraries=None, leaf_check=True):
    libraries = libraries or libraries_for(experiment)
    geometry = (32, 3, 8, 7)
    for simulator in ("icarus", "verilator"):
        simulation = Simulation(experiment, geometry, libraries, simulator=simulator)
        try:
            dictionary = b"abcdefg"
            cases = [Case("smoke-legacy", b"ababa", codec=0, capacity=128, wide=1),
                     Case("smoke-fse", rle_sequence_frame(), decompress=1, capacity=8),
                     Case("smoke-new", b"abcabcabcabc", codec=5, capacity=128),
                     Case("smoke-dictionary", b"abcdefgabcdefg", codec=6,
                          capacity=128, dictionary_id=0x12345678)]
            simulation.run("smoke-" + simulator, cases[:2], dictionary=dictionary)
            simulation.run("roundtrip-" + simulator, cases[2:], dictionary=dictionary,
                           roundtrip=True)
        finally:
            simulation.close()
    if leaf_check:
        leaf(experiment, "icarus")


def portable(experiment):
    copy = experiment.directory / ("clean-project-" + uuid4().hex[:8])
    copy.mkdir()
    manifest = []
    forbidden = re.compile(
        r"(?:(?<![A-Za-z0-9_])/(?:home|data|root|tmp)/[^\s`\"']+|gh[pousr]_[A-Za-z0-9]{20,}|"
        r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)")
    for pattern in ("rtl/*.sv", "tests/*.py", "design/*.md", "bellows_l4_reference/rtl/*.sv"):
        for path in sorted(ROOT.glob(pattern)):
            relative = path.relative_to(ROOT)
            if forbidden.search(path.read_text()):
                # Never print matched credential content.
                raise AssertionError(f"nonportable/private source content in {relative}")
            target = copy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            manifest.append({"path": relative.as_posix(), "sha256": sha256(path.read_bytes())})
    (copy / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    experiment.command("clean-project-smoke",
                       ["python3", "tests/verify.py", "--check", "smoke"], cwd=copy)
    receipts = list((copy / "evidence").glob("l1-smoke-*/receipt.json"))
    if len(receipts) != 1 or json.loads(receipts[0].read_text())["exit_code"] != 0:
        raise AssertionError("clean copied project has no successful real smoke receipt")
    experiment.receipt["clean_reproduction_receipt"] = experiment.relative(receipts[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", required=True,
                        choices=("behavior", "synthesis", "defects", "portable", "smoke"))
    parser.add_argument("--configuration", choices=CONFIGURATIONS)
    args = parser.parse_args()
    if args.check == "behavior" and not args.configuration:
        parser.error("--configuration is required for behavior")
    stem = "l1-" + args.check + ("-" + args.configuration if args.check == "behavior" else "")
    experiment = Experiment(stem, ["python3", "tests/verify.py", *sys.argv[1:]], admitted=True)
    if args.check == "behavior" and args.configuration == "default":
        experiment.receipt["execution_repair"] = {
            "repair_of": "evidence/l1-behavior-default-20261103T064957Z-83981782/receipt.json",
            "discrimination": (
                "evidence/preparation/timeout-discrimination-20261103T073827Z-97bfffa1/receipt.json"),
            "retained_192_flips": (
                "evidence/preparation/timeout-discrimination-20261103T074026Z-e55a1223/receipt.json"),
            "batch_selection_repair_of": (
                "evidence/l1-behavior-default-20261103T074610Z-0d47f0bb/receipt.json"),
            "change": "four-process independent transaction batching; completion-only flushing"}
    try:
        if args.check == "behavior":
            behavior(experiment, args.configuration)
        elif args.check == "synthesis":
            synthesis(experiment, [(n, CONFIGURATIONS[n]) for n in ("default", "singleton", "nonpower")])
        elif args.check == "defects":
            from l1_defects import defects
            defects(experiment, libraries_for(experiment))
        elif args.check == "portable":
            portable(experiment)
        else:
            smoke(experiment)
        experiment.finish(0)
        return 0
    except Exception as error:
        (experiment.directory / "failure.txt").write_text(traceback.format_exc())
        experiment.finish(1, str(error))
        print(f"L1 {args.check} failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
