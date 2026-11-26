#!/usr/bin/env python3
"""Vulcan's admitted Bellows-L1 verification entry points."""

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lz4_reference import HEADER, MAX_LENGTH, decode, frozen, observed_bytes, sequence


ROOT = Path(__file__).resolve().parents[1]
SHELL = "fpga/longspeak"
RTL_MANIFEST = "rtl/longspeak_sources.json"
TARGET = "bedrock-longspeak-arria10"
REF = "platform-inputs/netsys17/host-board-reference.json"
MAGIC = "0x42454c4c4f574c31"
POWER = "bellows_power.vcd"
SEEDS = (17, 89, 2026)
SOURCE_EXT = {".v", ".sv"}


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def binding(path):
    return {"path": path, "sha256": sha(ROOT / path)}


def read_json(path):
    return json.loads(Path(path).read_bytes())


def core_sources():
    manifest = read_json(ROOT / RTL_MANIFEST)
    require(manifest["schema"] == "vulcan-longspeak-sources/v1", "Unexpected RTL manifest schema")
    sv = [name for name in manifest["sources"] if Path(name).suffix in SOURCE_EXT]
    require(len(sv) == len(set(sv)) and all(Path(name).parts[0] == "rtl" for name in sv),
            "Invalid role source closure")
    return [name for name in sv if Path(name).name.startswith("bellows_l1_")], sv


def encode_rows(path, rows):
    with path.open("w", encoding="ascii") as stream:
        for name, kind, mode, seed, source, status, expected in rows:
            length = source if isinstance(source, int) else len(source)
            stream.write(f"{name} {kind} {mode} {seed} {length} {len(expected)} {status}\n")
            if isinstance(source, bytes):
                stream.write(source.hex(" ") + "\n")
            stream.write(expected.hex(" ") + "\n")


def simulation_originals(receipt):
    logs = {}
    for phase, info in receipt["phases"].items():
        for kind in ("stdout", "stderr"):
            path = Path(info[kind])
            raw = path.read_bytes()
            logs[f"{phase}/{kind}"] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                                      "bytes": len(raw), "gzip_base64": base64.b64encode(
                                          gzip.compress(raw, mtime=0)).decode("ascii")}
    return {"receipt": receipt, "receipt_sha256": sha(Path(receipt["receipt"])), "logs": logs}


def compiled_sim(scratch, suite, inputs, fixture, plusargs=(), integration=False, edits=None):
    project = scratch / suite
    require(not project.exists(), f"Simulation scratch already exists: {project}")
    project.mkdir()
    for path in inputs:
        dest = project / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
        if edits and path in edits:
            dest.write_text(edits[path](dest.read_text()), encoding="utf-8")
    shutil.copyfile(fixture, project / "vectors.txt")
    # Verilator 5.020 can abort during parallel build teardown even after linking.
    argv = [sys.executable, "-m", "vulcan_agent.vulcan_kit.simulation", "--project", str(project),
            "--target", TARGET, "--top", "tb_softshell" if integration else "tb_behavior",
            "--timeout-s", "900" if integration or suite == "behavior" else "240", "--jobs", "1"]
    if integration:
        argv.extend(("--define", "USE_ECC_DDR", "--vendor-lib", "altera_mf.v"))
    for name in [*inputs, "vectors.txt"]:
        argv.extend(("--input", name))
    for plusarg in ["+vectors=vectors.txt", *plusargs]:
        argv.extend(("--plusarg", plusarg))
    with (project / "driver.stdout").open("xb") as out, (project / "driver.stderr").open("xb") as err:
        run = subprocess.run(argv, cwd=project, stdout=out, stderr=err, check=False)
    require(run.returncode in (0, 1),
            f"{suite}: simulation runner exit {run.returncode}; see {project}/driver.stderr")
    receipt = read_json(project / "driver.stdout")
    require(receipt["inputs_current"] is True, f"{suite}: staged inputs changed")
    workspace = Path(receipt["workspace"])
    build = receipt["phases"]["build"]
    require(build["result"]["exit_code"] == 0 and build["result"]["process_scope_settled"] is True,
            f"{suite}: build failed; see {build['stderr']}")
    phase = receipt["phases"].get("run")
    require(phase is not None and phase["result"]["process_scope_settled"] is True
            and type(phase["result"]["exit_code"]) is int
            and (phase["result"]["status"] == "passed" or phase["result"]["detail"] == "nonzero_exit"),
            f"{suite}: no settled execution; see {receipt['receipt']}")
    stdout = Path(phase["stdout"]).read_text(encoding="utf-8")
    stderr = Path(phase["stderr"]).read_text(encoding="utf-8")
    provenance = {
        "argv": argv, "exit": run.returncode, "receipt": receipt["receipt"],
        "input_sha256": receipt["input_sha256"], "tool": receipt["tool"], "run_exit": phase["result"]["exit_code"],
        "stdout": phase["stdout"], "stderr": phase["stderr"], "workspace": str(workspace),
        "version": subprocess.check_output([receipt["tool"]["path"], "--version"], text=True).strip(),
        "originals": simulation_originals(receipt),
    }
    return provenance, stdout, stderr


def checked_rows(stdout, rows):
    actual = [line.split()[1:] for line in stdout.splitlines() if line.startswith("PASS_CASE ")]
    wanted = [(label, source if isinstance(source, int) else len(source), len(out), status)
              for label, _, _, _, source, status, out in rows]
    require(len(actual) == len(wanted), "Missing or extra behavior comparisons")
    for (name, sent, received, err, cycles), target in zip(actual, wanted):
        require((name, int(sent), int(received), int(err)) == target and int(cycles) > 0,
                f"Incorrect executed comparison summary: {name}")
    return [{"case": name, "input_bytes": int(sent), "output_bytes": int(received),
             "status": int(err), "cycles": int(cycles)} for name, sent, received, err, cycles in actual]


def mutation_rows():
    pattern = bytes(range(256))
    return {
        "offset_byte_swap": (sequence(b"positive"),
                             sequence(pattern, 256, 8) + sequence(b"tail")),
        "missing_match_plus_four": (sequence(b"control"),
                                    sequence(b"xy", 2, 6) + sequence(b"tail")),
        "stale_overlap_history": (sequence(b"abcdefgh", 8, 4) + sequence(b"tail"),
                                  sequence(b"xy", 2, 10) + sequence(b"tail")),
    }


def direct_rows():
    for n in (14, 15, 16, 269, 270, 271, 525):
        yield f"literal_{n}", sequence(bytes(i & 255 for i in range(n)))
    for n in (14, 15, 16, 18, 19, 20, 273, 274, 275, 529):
        yield f"match_{n}", sequence(b"xyz", 3, n) + sequence(b"tail")
    for offset in (1, 2, 3, 255, 256, 257, 32768, 65535):
        prefix = random.Random(offset).randbytes(offset)
        yield f"offset_{offset}", sequence(prefix, offset, min(66000, offset + 5)) + sequence(b"tail")
    yield "mixed_three_wraps", (sequence(b"abcd", 4, 65823) + sequence(b"03", 257, 65831)
                                + sequence(b"XY", 65535, 66212) + sequence(b"done"))
    for name, data in {
        "missing_literals": b"\x20",
        "literal_extension_last": b"\xf0\x00",
        "literal_extension_continue_last": b"\xf0\xff",
        "offset_low_last": b"\x10\xaf\x00",
        "offset_high_last": b"\x10\xaf\x00\x00",
        "match_extension_last": b"\x1f\xab\x01\x00\x00",
        "match_extension_continue_last": b"\x1f\xab\x01\x00\xff",
        "discard_many_bubbled_bytes": b"\x10\xab\x00\x00" + bytes(range(255)) + b"\x00",
        "history_must_be_fresh": b"\x00\x01\x00\x00",
    }.items():
        yield name, data
    for mutant, (control, trigger) in mutation_rows().items():
        yield f"{mutant}_positive", control
        yield f"{mutant}_target", trigger


def randomized_block(rng):
    data = b""
    history = 0
    for _ in range(rng.randrange(1, 8)):
        literals = rng.randbytes(rng.choice((0, 1, 3, 14, 15, 16, 28, 269, 270, rng.randrange(1, 97))))
        if not literals and not history:
            literals = rng.randbytes(1)
        history += len(literals)
        offset = rng.choice((1, min(history, 2), min(history, 257), rng.randint(1, min(history, 65535))))
        matches = rng.choice((4, 5, 18, 19, 20, 273, 274, 275, rng.randrange(4, 500)))
        data += sequence(literals, offset, matches)
        history += matches
    return data + sequence(rng.randbytes(rng.randrange(0, 45)))


def behavior_rows(oracle):
    rows = [(name, 0, i % 3, 17, data, status, decoded)
            for i, (name, data, status, decoded) in enumerate(oracle)]
    rows += [(name, 0, 1, 89, data, *decode(data)) for name, data in direct_rows()]
    for seed in SEEDS:
        for mode in range(3):
            rng = random.Random(seed)
            for index in range(32):
                data = randomized_block(rng)
                status, out = decode(data)
                require(status == 0, "Invalid generated randomized block")
                rows.append((f"random_{seed}_{mode}_{index}", 0, mode, seed, data, status, out))
    # First overflowing 255 byte is not last; a separate accepted byte closes discard.
    for kind, prefix, base, expected in ((1, 1, 15, b""), (2, 4, 19, b"\xa7")):
        n = (MAX_LENGTH - base) // 255 + 1
        literal = b"\xf0" if kind == 1 else b"\x1f\xa7\x01\x00"
        data = literal + b"\xff" * n + b"\x00"
        require(decode(data) == (4, expected), "Incorrect overflow stimulus")
        rows.append((f"overflow_{kind}", kind, 0, 17, prefix + n + 1, 4, expected))
    return rows


def behavior(scratch, oracle):
    rows = behavior_rows(oracle)
    fixture = scratch / "behavior.txt"
    encode_rows(fixture, rows)
    inputs = [*core_sources()[0], "tests/tb_behavior.sv"]
    record, output, _ = compiled_sim(scratch, "behavior", inputs, fixture, ("+reset_cases",))
    require(record["exit"] == 0, f"Behavior failed; see {record['stdout']} and {record['stderr']}")
    comparisons = checked_rows(output, rows)
    match = re.search(r"^COVERAGE (\d+) (\d+) (\d+) (\d+)$", output, re.M)
    require(match is not None and "RESET_COVERAGE 2\n" in output, "Missing protocol coverage")
    bubbles, stalls, longest, status = map(int, match.groups())
    require(bubbles > 0 and stalls > 0 and longest >= 257 and status > 0, "Backpressure coverage incomplete")
    return {"simulation": record, "comparisons": comparisons,
            "coverage": {"input_bubbles": bubbles, "output_stalls": stalls, "longest_output_stall": longest,
                         "status_stalls": status, "reset_cases": 2}}


def replace_exact(text, old, new, count=1):
    require(text.count(old) == count, f"Mutation anchor changed: {old}")
    return text.replace(old, new)


def mutants(scratch):
    inputs = [*core_sources()[0], "tests/tb_behavior.sv"]
    edits = {
        "offset_byte_swap": lambda t: replace_exact(t, "{s_data, match_offset[7:0]}",
                                                     "{match_offset[7:0], s_data}"),
        "missing_match_plus_four": lambda t: replace_exact(t, "{28'd0, s_data[3:0]} + 32'd4",
                                                             "{28'd0, s_data[3:0]}", 1),
        "stale_overlap_history": lambda t: replace_exact(
            replace_exact(t, "wire [7:0] history_read_data;",
                          """wire [7:0] history_read_data;
    logic [31:0] mutant_commits;
    always_ff @(posedge clk)
        if (!rst_n || state == ST_OFFSET_HIGH) mutant_commits <= 0;
        else if (state == ST_MATCH_COMMIT && candidate_commit) mutant_commits <= mutant_commits + 1;"""),
            ".read_en(rst_n && state == ST_MATCH_READ)",
            ".read_en(rst_n && state == ST_MATCH_READ && mutant_commits < {16'd0, match_offset})"),
    }
    results = {}
    for name, patterns in mutation_rows().items():
        rows = [(f"{name}_{label}", 0, 0, 17, data, *decode(data))
                for label, data in zip(("positive", "target"), patterns)]
        fixture = scratch / f"{name}.txt"
        encode_rows(fixture, rows)
        record, output, error = compiled_sim(scratch, name, inputs, fixture,
                                            edits={"rtl/bellows_l1_top.sv": edits[name]})
        require(record["exit"] == 1 and record["run_exit"] not in (0, None),
                f"{name}: mutant unexpectedly passed or did not reach simulation; see {record['receipt']}")
        comparisons = checked_rows(output, rows[:1])
        mismatches = [line for line in (output + "\n" + error).splitlines()
                      if f"MISMATCH {name}_target " in line]
        require(len(mismatches) == 1 and "TIMEOUT" not in output + error,
                f"{name}: not killed by the designated oracle comparison; see {record['stdout']}")
        results[name] = {"simulation": record, "positive_comparisons": comparisons, "detected": mismatches[0]}
    return results


def inputs_and_output(row):
    def vector_bytes(asset):
        path = ROOT / asset["path"]
        require(path.is_relative_to(ROOT / "tests/board_vectors") and path.resolve(strict=True) == path,
                f"{row['id']}: invalid bound vector path {path}")
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == asset["sha256"],
                f"{row['id']}: bound vector contents changed")
        return data

    source = vector_bytes(row["input"])
    expected = vector_bytes(row["expected"])
    values = json.loads(source)["inputs"]
    data = bytes.fromhex(values["compressed_hex"])
    wanted = observed_bytes(data, values["capacity"])
    require(wanted == expected and values["expected_sha256"] == row["expected"]["sha256"],
            f"{row['id']}: oracle, staged digest and expected file differ")
    return data, values, expected


def integration_rows(oracle, workload):
    rows = [(f"frozen_{name}", 0, 0, 17, data, status, expected)
            for name, data, status, expected in oracle]
    for name, kind, data in (
        ("dma_page_tail", 1, sequence(random.Random(89).randbytes(93))),
        ("ddr_busy_descriptor_snapshot", 4, sequence(b"BUSY!")),
        ("ddr_aperture_last_word", 5, sequence(b"top word")),
    ):
        rows.append((name, kind, 0, 17, data, *decode(data)))
    data = sequence(b"A", 1, 10) + sequence(b"tail")
    rows.append(("capacity_returns_prefix", 3, 0, 17, data, 0, decode(data)[1][:2]))
    for row in workload["rows"]:
        data, _, expected = inputs_and_output(row)
        rows.append((row["id"], 2, 0, 17, data, 0, expected[HEADER.size:]))
    data = sequence(b"rearmed after both native resets")
    rows.append(("rearmed_after_native_resets", 6, 0, 17, data, *decode(data)))
    rows.append(("dma_rearmed_after_native_resets", 1, 0, 17, data, *decode(data)))
    return rows


def integration(scratch, oracle, output_vcd):
    workload_name = "tests/performance_workload.json"
    workload = read_json(ROOT / workload_name)
    rows = integration_rows(oracle, workload)
    fixture = scratch / "integration.txt"
    encode_rows(fixture, rows)
    inputs = [f"{SHELL}/Types/ShellTypes.sv", f"{SHELL}/longspeak_dma_cdc.sv", f"{SHELL}/SoftShell.sv",
              *core_sources()[1], "tests/tb_softshell.sv"]
    record, output, _ = compiled_sim(scratch, "integration", inputs, fixture, integration=True)
    require(record["exit"] == 0, f"SoftShell integration failed; see {record['stdout']} and {record['stderr']}")
    comparisons = checked_rows(output, rows)
    match = re.search(r"^INTEGRATION_COVERAGE (\d+) (\d+) (\d+) (\d+) (\d+)$", output, re.M)
    require(match is not None and all(int(value) > 0 for value in match.groups())
            and "RESET_COVERAGE 4\n" in output and "ROLE_DDR_RESET_COVERAGE 2\n" in output
            and "INVALID_COVERAGE 9\n" in output,
            "Missing observed integration coverage")
    telemetry = {}
    for name, consumed, cycles, ddr, pcie in re.findall(r"^TELEMETRY (\S+) (\d+) (\d+) (\d+) (\d+)$", output, re.M):
        require(name not in telemetry and int(cycles) > 0 and int(ddr) > 0, f"Invalid job telemetry: {name}")
        telemetry[name] = {"consumed_bytes": int(consumed), "core_cycles": int(cycles),
                           "ddr_beats": int(ddr), "pcie_chunks": int(pcie)}
    require(set(telemetry) == {row[0] for row in rows}, "Missing job telemetry")
    activity = Path(record["workspace"]) / POWER
    require(0 < activity.stat().st_size <= 64 * 1024**2, "Owned VCD activity absent or oversized")
    duration = 0
    with activity.open("rb") as stream:
        require(b"$enddefinitions" in stream.read(4096), "Invalid owned VCD header")
        for line in stream:
            if line.startswith(b"#"):
                stamp = int(line[1:])
                require(stamp >= duration, "Nonmonotonic VCD timestamps")
                duration = stamp
    require(duration > 0, "Empty owned workload activity interval")
    with output_vcd.open("xb") as out, activity.open("rb") as stream:
        shutil.copyfileobj(stream, out)
    return {"simulation": record, "comparisons": comparisons, "telemetry": telemetry,
            "coverage": dict(zip(("ddr_stalls", "ddr_delayed_reads", "pcie_request_stalls",
                                 "pcie_write_done_wait_cycles", "role_frame_beats"), map(int, match.groups())),
                             reset_cases=4, role_ddr_reset_cases=2, invalid_cases=9),
            "activity": {"path": str(output_vcd), "sha256": sha(output_vcd), "bytes": activity.stat().st_size,
                         "duration_ns": duration, "workload": binding(workload_name),
                         "rows": [r["id"] for r in workload["rows"]],
                         "scope_map": {"tb_softshell.dut": "Shell|SoftShell",
                                       "tb_softshell.dut.role.bellows": "Shell|SoftShell|role|bellows"},
                         "scope": "Observed shell and decoder signals; not fitted power or annotation coverage."}}


def board_contract():
    from vulcan_agent import board_campaign
    from vulcan_agent.hardware_extension import preflight_collector

    reference = read_json(ROOT / REF)
    config = read_json(ROOT / "tests/platform_config.json")
    require(config == reference["platform_config_template"], "Platform template differs from NETSYS17 reference")
    for key in ("prior_campaign", "prior_campaign_result", "prior_image"):
        expected = config.get(f"{key}_sha256", reference.get(f"{key}_sha256"))
        require(sha(ROOT / config[key]) == expected, f"Prior input identity mismatch: {key}")
    entry = reference["collector_entrypoint"]
    require((ROOT / entry["path"]).read_text(encoding="utf-8") == entry["exact_python_source"],
            "Native collector source differs from the reference")
    board = read_json(ROOT / "fpga/board_hil.json")
    native = reference["board_hil_json_contract"]["required_top_level_fields"]["native_collector"]
    expected_native = {**native, "configuration": binding("tests/platform_config.json"),
                       "api_sources": [binding(REF)],
                       "workload_sources": {"business_script": binding("tests/business-test.ps1"),
                                            "companion": binding("tests/Workload.cs")}}
    require(set(board) == {"expected_magic_hex", "runs", "native_collector", "experiment_plan"}
            and board["native_collector"] == expected_native
            and board["expected_magic_hex"] == MAGIC and type(board["runs"]) is int and board["runs"] >= 3,
            "Invalid managed board binding")
    plan = board["experiment_plan"]
    require(plan["protocol"] == "reviewed-native-v1" and plan["workload_protocol"] == "softreg-readback/v1",
            "Invalid experiment protocol")
    identities = set()
    cases = {}
    for row in plan["vectors"]:
        name = row["id"]
        require(re.fullmatch(r"[a-zA-Z0-9_-]+", name) and name not in cases,
                "Duplicate or invalid board vector ID")
        require(row["comparison"] == {"format": "bytes"}
                and row["oracle_source"] == binding("tests/lz4_reference.py"), f"{name}: invalid oracle binding")
        data, config_row, output = inputs_and_output(row)
        core, transport, count, produced = HEADER.unpack_from(output)
        require(bool(data) and data not in identities and set(config_row) == {
            "compressed_hex", "capacity", "core_status", "output_bytes", "expected_sha256"
        } and count == len(data) and produced == config_row["output_bytes"]
            and core == config_row["core_status"] and transport == 0, f"{name}: invalid job contract")
        identities.add(data)
        cases[name] = {"input_bytes": count, "output_bytes": produced, "core_status": core}
    require(len(cases) >= 3 and {"empty", "literal", "overlap", "malformed_prefix", "reuse"} <= cases.keys(),
            "Missing physical functional vector coverage")
    perf = read_json(ROOT / "tests/performance_workload.json")
    cohort = perf["rows"]
    require(len(cohort) >= 3 and len({row["id"] for row in cohort}) == len(cohort) and all(
        row == next((v for v in plan["vectors"] if v["id"] == row["id"]), None) and
        cases[row["id"]]["core_status"] == 0 for row in cohort), "Matched workload does not bind board rows")
    sizes = [cases[row["id"]]["output_bytes"] for row in cohort]
    require(min(sizes) == 256 and max(sizes) == 65536, "Matched workload size envelope differs")
    script = (ROOT / "tests/business-test.ps1").read_text(encoding="utf-8")
    for param in reference["windows_workload_contract"]["cli_parameters"]:
        require(param in script, f"Missing workload CLI parameter {param}")
    protocol = board_campaign.workload_protocol(board)
    staged = board_campaign.workload_payload(board, protocol, board_campaign.workload_vectors(ROOT, board, protocol))
    require(len(staged["runs"]) == board["runs"]
            and all([row["id"] for row in run["vectors"]] == list(cases) for run in staged["runs"]),
            "Runtime staging does not preserve the admitted vector order")
    require(preflight_collector(ROOT, board) == expected_native, "Runtime collector preflight differs")
    return {"scope": "Offline binding/oracle validation only; no Windows compile, hardware, or current App1 proof.",
            "runs": board["runs"], "vectors": cases, "cohort": cohort, "native_collector": expected_native,
            "staged_sha256": hashlib.sha256(json.dumps(staged, sort_keys=True).encode()).hexdigest(),
            "runtime_collector_preflight": "passed"}


def main():
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument("--suite", required=True, choices=("behavior", "integration", "mutations", "board-contract"))
    parser.add_argument("--golden", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if (args.golden is None) != (args.suite == "board-contract"):
        parser.error("--golden is required for RTL suites and not used by board-contract")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema": "bellows-verification/v1", "suite": args.suite, "engineering_acceptance": False,
              "physical_execution": False, "argv": sys.argv}
    try:
        if args.suite == "board-contract":
            report["results"] = board_contract()
        else:
            ghash = sha(args.golden)
            oracle = list(frozen(args.golden))
            report["golden_sha256"] = ghash
            scratch = Path(tempfile.mkdtemp(prefix="bellows-sim-", dir=args.report.parent.resolve()))
            report["scratch"] = str(scratch)
            if args.suite == "behavior":
                report["results"] = behavior(scratch, oracle)
            elif args.suite == "mutations":
                report["results"] = mutants(scratch)
            else:
                report["results"] = integration(scratch, oracle, args.report.parent / POWER)
            require(sha(args.golden) == ghash, "Frozen oracle changed while executing")
        report["status"] = "passed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        report.update(status="failed", detail=str(exc))
        print(str(exc), file=sys.stderr)
    write_json(args.report, report)
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
