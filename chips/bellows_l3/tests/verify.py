#!/usr/bin/env python3
"""BELLOWS-L3 independent L1 checks; native timing/HIL remain runtime-owned.

Requirement map:
  oracle.py: raw-block parsing, legal block generation, XXH32 and zlib CRC.
  transactor.py: public DMA handshakes, stability, ownership, counters, guards,
                 registered descriptor/status boundaries and measured stalls.
  smoke/matrix: hardware bytes and completions against original content.

An unfinished verification surface is an explicit failure, never a skipped pass.
"""

import argparse
import collections
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle
import error_settlement
import parent
import protocols
import mutations
import scenarios
import synthesis
from retention import Run, sources, write_json
from transactor import bench


ROOT = Path(__file__).resolve().parent.parent
CELLS = ((1, 1), (3, 3), (15, 1), (16, 3), (255, 16), (256, 3),
         (4096, 16), (65536, 16))
SEEDS = (17, 89, 2027)


@dataclass
class Frame:
    identifier: int
    content: bytes
    decompress: bool
    mode: int
    source: bytes
    capacity: int
    error: int = 0
    bad_read: int = -1
    bad_write: int = -1
    command_length: int | None = None
    command_capacity: int | None = None
    command_ns: int | None = None
    command_nd: int | None = None
    source_segments: list | None = None
    destination_segments: list | None = None
    reject_command: bool = False
    require_matches: bool = False
    expected_checksum: int | None = None
    corruption_kind: str | None = None


def make_frame(identifier, content, decompress, mode, capacity=None, block=None):
    source = (oracle.frame(block if block is not None else oracle.literals(content),
                           content, mode) if decompress else content)
    if capacity is None:
        capacity = (max(1, len(content)) if decompress else
                    len(oracle.literals(content)) + (4 if mode else 0))
    return Frame(identifier, content, decompress, mode, source, capacity)


def segments(length, count, base):
    if length == 0:
        return []
    count = min(count, length)
    sizes = [1] * (count - 1) + [length - count + 1]
    if count >= 3:
        sizes = [1, length - count + 1] + [1] * (count - 2)
    result = []
    address = base
    for size in sizes:
        result.append((address, size))
        address += size + 19
    return result


def write_cases(path, batches, sg, seed):
    lines = [f"{len(batches)} {seed}"]
    manifest = []
    for batch, frames in enumerate(batches):
        assert len(frames) == 4
        for channel, frame in enumerate(frames):
            base = 0x100000 + channel * 0x10000000 + batch * 0x100000
            src = (segments(len(frame.source), sg, base)
                   if frame.source_segments is None else frame.source_segments)
            dst = (segments(frame.capacity, sg, base + 0x80000)
                   if frame.destination_segments is None else frame.destination_segments)
            source_length = (len(frame.source) if frame.command_length is None
                             else frame.command_length)
            capacity = (frame.capacity if frame.command_capacity is None
                        else frame.command_capacity)
            count_source = len(src) if frame.command_ns is None else frame.command_ns
            count_destination = len(dst) if frame.command_nd is None else frame.command_nd
            lines.append(" ".join(str(x) for x in
                                  (frame.identifier, int(frame.decompress), frame.mode,
                                   source_length, capacity, len(src), len(dst),
                                   frame.error, frame.bad_read, frame.bad_write,
                                   len(frame.source), count_source, count_destination,
                                   int(frame.reject_command))))
            lines.extend(f"{address:x} {size}" for address, size in src + dst)
            lines.append(frame.source.hex(" "))
            manifest.append({"batch": batch, "channel": channel,
                             "id": frame.identifier, "decompress": frame.decompress,
                             "mode": frame.mode, "source_hex": frame.source.hex(),
                             "content_hex": frame.content.hex(),
                             "capacity": frame.capacity, "expected_error": frame.error,
                             "command_length": source_length, "command_capacity": capacity,
                             "command_ns": count_source, "command_nd": count_destination,
                             "reject_command": frame.reject_command,
                             "corruption_kind": frame.corruption_kind,
                             "src_segments": src, "dst_segments": dst})
    path.write_text("\n".join(lines) + "\n")
    write_json(path.with_suffix(".json"), manifest)


def compile_bus(run, block, sg, simulator, rtl_dir=None, tag=""):
    directory = run.path / f"bus-{simulator}-{block}-{sg}{'-' + tag if tag else ''}"
    directory.mkdir()
    tb = directory / "tb.sv"
    tb.write_text(bench(block, sg, compact=simulator == "icarus"))
    rtl = [run.relative(p) for p in sorted((rtl_dir or run.root / "rtl").glob("*.sv"))]
    executable = directory / "simv"
    if simulator == "icarus":
        run.command(["iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
                     run.relative(executable), run.relative(tb), *rtl], "compile-icarus")
    else:
        run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                     "--top-module", "tb", "--Mdir",
                     run.relative(directory / "compile-obj"), "-o", "../simv",
                     "-j", "2", run.relative(tb), *rtl], "compile-verilator")
    return directory, executable


def compare_results(path, batches):
    records, coverage = {}, None
    for line in path.read_text().splitlines():
        parts = line.split()
        if parts[0] == "FRAME":
            batch, channel, identifier, error, source_count, destination_count = (
                int(x) for x in parts[1:7])
            value = int(parts[7], 16)
            actual = bytes.fromhex(parts[8]) if len(parts) == 9 else b""
            key = batch, channel
            if key in records:
                raise AssertionError(f"duplicate result {key}")
            expected = batches[batch][channel]
            assert identifier == expected.identifier, ("id", key, identifier)
            assert error == expected.error, ("status_error", key, error, expected.error)
            assert destination_count == len(actual), ("output count", key)
            if error == 0:
                assert source_count == len(expected.source), ("source count", key)
                assert value == oracle.checksum(expected.content, expected.mode), (
                    "status_checksum", key, hex(value),
                    hex(oracle.checksum(expected.content, expected.mode)))
                if expected.decompress:
                    assert actual == expected.content, ("decoded bytes", key,
                                                        actual[:64].hex(),
                                                        expected.content[:64].hex())
                else:
                    trailer = actual[-4:] if expected.mode else b""
                    payload = actual[:-4] if expected.mode else actual
                    assert trailer == (value.to_bytes(4, "little") if expected.mode
                                       else b""), ("trailer", key)
                    assert oracle.decode(payload) == expected.content, ("roundtrip", key)
                    if not expected.content:
                        assert payload == b"\x00", ("canonical empty", key)
                    if expected.require_matches:
                        assert len(payload) < len(oracle.literals(expected.content)), (
                            "not a match-producing compressor", key)
            elif error == 7:
                assert source_count == len(expected.source), ("mismatch source count", key)
                assert value == oracle.checksum(expected.content, expected.mode), (
                    "mismatch computed checksum", key)
                assert expected.decompress and expected.mode in (1, 2)
                assert oracle.decode(expected.source[:-4]) == expected.content
                assert expected.source[-4:] != value.to_bytes(4, "little")
                assert actual == expected.content[:len(actual)], ("mismatch output", key)
            elif error == 8:
                assert source_count == destination_count == value == 0, (
                    "metadata issued DMA", key)
            elif expected.decompress:
                assert actual == expected.content[:len(actual)], ("failure output prefix", key)
            if error not in (0, 7, 8):
                expected_checksum = 0 if expected.mode == 0 else expected.expected_checksum
                assert expected_checksum is not None, ("unscored failure checksum", key)
                assert value == expected_checksum, (
                    "failure checksum", key, hex(value), hex(expected_checksum))
            records[key] = {"id": identifier, "error": error, "source_bytes": source_count,
                            "destination_bytes": destination_count,
                            "checksum": value, "output_hex": actual.hex()}
        elif parts[0] == "COVER":
            assert coverage is None, "duplicate coverage"
            coverage = dict(zip(("four_active", "read_switches", "read_stall",
                                 "write_stall", "status_stall", "response_gaps",
                                 "compress_source_cross", "decode_source_cross",
                                 "compress_dest_cross", "decode_dest_cross",
                                 "single_segments", "depth16", "reset_collect",
                                 "reset_processing", "reset_status"),
                                (int(x) for x in parts[1:]), strict=True))
        else:
            raise AssertionError(f"unrecognized result: {line[:128]}")
    assert len(records) == 4 * len(batches), ("missing completions", len(records))
    assert coverage is not None, "missing measured coverage"
    assert coverage["four_active"] == 1, coverage
    for name in ("read_stall", "write_stall", "status_stall"):
        assert coverage[name] >= 17, coverage
    assert coverage["response_gaps"] > 0, coverage
    return records, coverage


def simulate(run, build, batches, sg, seed, label, resets=False):
    directory, executable = build
    case_path = directory / f"{label}.cases"
    result_path = directory / f"{label}.results"
    write_cases(case_path, batches, sg, seed)
    command = [run.relative(executable), "+case=" + run.relative(case_path),
               "+result=" + run.relative(result_path), f"+resets={int(resets)}"]
    if "icarus" in directory.name:
        command.insert(0, "vvp")
    stdout, _ = run.command(command, label)
    assert "SIMULATION_COMPLETE" in stdout, "missing simulator completion marker"
    records, coverage = compare_results(result_path, batches)
    if resets:
        for stage in ("reset_collect", "reset_processing", "reset_status"):
            assert coverage[stage] > 0, (stage, coverage)
    write_json(directory / f"{label}.compared.json",
               {"frames": [dict(batch=b, channel=c, **record)
                           for (b, c), record in records.items()],
                "coverage": coverage})
    return records, coverage


def compact_batches(block=33):
    batches = []
    for op in (False, True):
        for mode in range(3):
            batch = []
            for ch, length in enumerate((0, 1, min(16, block), block)):
                content = bytes((i * 13 + ch * 61) & 255 for i in range(length))
                batch.append(make_frame(1 + len(batches) * 4 + ch, content, op, mode))
            batches.append(batch)
    return batches


def prepare(run, kind):
    """Bounded development probe; not a mandatory check/acceptance substitute."""
    for tool in (("iverilog", "vvp") if kind in ("compact", "parent", "protocol") else
                 ("iverilog", "vvp", "yosys") if kind == "portable" else
                 ("yosys",) if kind in ("synthesis", "default-synthesis")
                 else ("verilator", "g++", "make")):
        run.tool(tool)
    oracle.selftest()
    if kind == "protocol":
        protocols.execute(run)
        protocols.serviceability(run)
    elif kind == "portable":
        reproduce(run, development=True)
    elif kind == "full-parent":
        parent.execute(run, "verilator", full=True, l1=True)
    elif kind == "parent":
        parent.execute(run)
        if (run.root / "bellows_l2_reference/rtl").is_dir():
            parent.execute(run, reference=True)
    elif kind == "compact":
        build = compile_bus(run, 33, 3, "icarus")
        simulate(run, build, compact_batches(), 3, 17, "compact-dma-probe", resets=True)
    elif kind in ("synthesis", "default-synthesis"):
        synthesis.structural_rules(run.root)
        synthesis.synthesize(run, "bellows_l3_top",
                             65536 if kind == "default-synthesis" else 1,
                             16 if kind == "default-synthesis" else 1)
    elif kind == "endpoint":
        build = compile_bus(run, 65536, 16, "verilator")
        batches = [[make_frame(6000 + c, content, bool(c & 1), c % 3, block=encoded)
                    for c, (content, encoded) in enumerate((
                        (b"Q" * 65536, None),
                        (b"Z" * 65536, oracle.periodic_block(b"Z" * 65536)),
                        (b"123456789", None), (b"", None)))]]
        simulate(run, build, batches, 16, 17, "maximum-endpoint")
    elif kind in ("mutation", "mutation-transfer"):
        mutations.execute(run, compile_bus, write_cases, compare_results, make_frame,
                          only=("channel-ownership" if kind == "mutation-transfer"
                                else "suppressed-mismatch"))
    elif kind == "matrix-cell":
        build = compile_bus(run, 3, 3, "verilator")
        simulate(run, build, scenarios.matrix_batches(3, 89, make_frame),
                 3, 89, "nonpower-seed89", resets=True)
    elif kind == "hidden-reservation-error-settlement":
        error_settlement.execute(run)
    else:
        build = compile_bus(run, 255, 16, "verilator")
        batches = (scenarios.boundaries(make_frame) +
                   scenarios.corruption_batches(make_frame) +
                   scenarios.errors(255, 16, make_frame))
        simulate(run, build, batches, 16, 17, "error-and-boundary-probe")


def smoke(run):
    oracle.selftest()
    for tool in ("iverilog", "vvp"):
        run.tool(tool)
    protocols.execute(run)
    protocols.serviceability(run)
    ledger = []
    for block, sg in ((1, 1), (3, 3), (33, 3)):
        build = compile_bus(run, block, sg, "icarus")
        records, coverage = simulate(run, build, compact_batches(block), sg, 17,
                                     "smoke", resets=block == 33)
        ledger.append({"MAX_BLOCK_BYTES": block, "SG_DEPTH": sg, "seed": 17,
                       "compared_frames": len(records), "coverage": coverage})
    parent.execute(run, l1=True)
    parent.execute(run)
    if (run.root / "bellows_l2_reference/rtl").is_dir():
        parent.execute(run, reference=True)
    write_json(run.path / "smoke-summary.json", ledger)


def matrix(run):
    oracle.selftest()
    for tool in ("verilator", "g++", "make"):
        run.tool(tool)
    settlement = error_settlement.execute(run)
    ledger, combined = [], collections.Counter()
    observed = collections.Counter()
    for block, sg in CELLS:
        build = compile_bus(run, block, sg, "verilator")
        for seed in SEEDS:
            batches = scenarios.matrix_batches(block, seed, make_frame)
            records, coverage = simulate(run, build, batches, sg, seed,
                                         f"seed-{seed}", resets=True)
            combinations = collections.Counter()
            maximums = set()
            for (batch, channel), record in records.items():
                frame = batches[batch][channel]
                combinations[channel, int(frame.decompress), frame.mode] += 1
                assert record["error"] == 0
                observed["compared_content_bytes"] += len(frame.content)
                if not frame.content:
                    observed["empty"] += 1
                if len(frame.content) == 1:
                    observed["one_byte"] += 1
                if record["destination_bytes"] == frame.capacity:
                    observed["exact_fit"] += 1
                if len(frame.content) > 256 and len({
                        frame.content[i:i + 4] for i in range(len(frame.content) - 3)}) > 256:
                    observed["collision_heavy_completed"] += 1
                if len(frame.content) == block:
                    maximums.add(int(frame.decompress))
            assert len(records) >= 48, ("48-frame minimum", block, sg, seed)
            assert len(combinations) == 24 and min(combinations.values()) >= 2
            assert maximums == {0, 1}, ("maximum-length endpoints", block, sg, seed)
            roundtrips = []
            for batch in range(3):
                group = []
                for channel in range(4):
                    original = batches[batch][channel]
                    source = bytes.fromhex(records[batch, channel]["output_hex"])
                    group.append(Frame(8000 + batch * 4 + channel, original.content,
                                       True, original.mode, source,
                                       max(1, len(original.content))))
                roundtrips.append(group)
            rt_records, rt_coverage = simulate(run, build, roundtrips, sg, seed,
                                               f"roundtrip-{seed}")
            for name, value in coverage.items():
                combined[name] += value
            for name, value in rt_coverage.items():
                combined[name] += value
            row = {"MAX_BLOCK_BYTES": block, "SG_DEPTH": sg, "seed": seed,
                   "required_frames": 48, "compared_frames": len(records),
                   "hardware_roundtrip_frames": len(rt_records),
                   "channel_operation_mode_combinations": len(combinations),
                   "minimum_frames_per_combination": min(combinations.values()),
                   "maximum_length_compression_and_decompression": True,
                   "coverage": coverage, "outcome": "passed",
                   "results": run.relative(build[0] / f"seed-{seed}.compared.json")}
            ledger.append(row)
            write_json(run.path / "matrix-ledger.json", {"required_runs": 24, "runs": ledger})
        if (block, sg) == (255, 16):
            extra = (scenarios.boundaries(make_frame) +
                     scenarios.corruption_batches(make_frame) +
                     scenarios.errors(block, sg, make_frame))
            extra_records, extra_coverage = simulate(
                run, build, extra, sg, 17, "directed-boundaries-errors")
            corruption = collections.Counter()
            bits = collections.defaultdict(set)
            boundary_corruptions = collections.Counter()
            body_corruptions = collections.Counter()
            error_codes = collections.Counter()
            lengths = set()
            for (batch, channel), record in extra_records.items():
                f = extra[batch][channel]
                error_codes[record["error"]] += 1
                if f.error == 7:
                    corruption[channel, f.mode] += 1
                    difference = (int.from_bytes(f.source[-4:], "little") ^
                                  oracle.checksum(f.content, f.mode))
                    if f.corruption_kind == "body":
                        body_corruptions[f.mode] += 1
                    else:
                        bits[channel, f.mode].update(bit for bit in range(32)
                                                    if difference & (1 << bit))
                    if f.corruption_kind == "trailer" and difference == ((1 << 23) | (1 << 24)):
                        boundary_corruptions[channel, f.mode] += 1
                if f.mode == 1 and f.error == 0:
                    lengths.add(len(f.content))
            assert len(corruption) == 8 and min(corruption.values()) >= 8
            assert all(value == set(range(32)) for value in bits.values())
            assert len(boundary_corruptions) == 8 and min(boundary_corruptions.values()) >= 1
            assert set(body_corruptions) == {1, 2} and min(body_corruptions.values()) >= 4
            assert set((0, 1, 3, 4, 15, 16, 17, 31, 32, 33)) <= lengths
            assert {0, 1, 2, 3, 5, 7, 8, 9, 10} <= set(error_codes)
            for name, value in extra_coverage.items():
                combined[name] += value
            write_json(run.path / "directed-summary.json",
                       {"otherwise_valid_corruptions": {
                           f"channel-{c}-mode-{m}": n for (c, m), n in corruption.items()},
                        "compared_errors": dict(error_codes),
                        "every_checksum_bit_compared": len(bits) == 8,
                        "otherwise_valid_body_corruptions": dict(body_corruptions),
                        "multi_byte_boundary_corruptions": {
                            f"channel-{c}-mode-{m}": n
                            for (c, m), n in boundary_corruptions.items()},
                        "XXH32_lengths": sorted(lengths), "coverage": extra_coverage})
    assert len(ledger) == 24
    for name in ("compress_source_cross", "decode_source_cross",
                 "compress_dest_cross", "decode_dest_cross", "single_segments",
                 "depth16", "reset_collect", "reset_processing", "reset_status"):
        assert combined[name] > 0, ("missing measured matrix coverage", name)
    assert combined["read_switches"] >= 32, combined
    for event in ("empty", "one_byte", "exact_fit", "collision_heavy_completed"):
        assert observed[event] > 0, ("missing successfully compared content", event)
    parent.execute(run, "verilator", full=True, l1=True)
    write_json(run.path / "matrix-summary.json",
               {"required_runs": 24, "completed_runs": len(ledger), "runs": ledger,
                "hidden-reservation-error-settlement": settlement,
                "aggregate_public_dma_coverage": dict(combined),
                "successfully_compared_content_coverage": dict(observed),
                "fairness_reference": "smoke scheduler public-input all-eligible experiment"})


def reproduce(run, development=False):
    stage = run.path / "staging"
    stage.mkdir()
    manifest = {}
    for pattern in ("rtl/*.sv", "tests/*.py", "design/SPEC.md", "design/ARCHITECTURE.md"):
        selected = sorted(run.root.glob(pattern))
        assert selected, f"empty shipped source selector: {pattern}"
        for original in selected:
            relative = original.relative_to(run.root)
            assert not original.is_symlink(), f"shipped symlink: {relative}"
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
            assert str(run.root).encode() not in target.read_bytes(), (
                "private project dependency in shipped source", str(relative))
            manifest[str(relative)] = digest
    write_json(run.path / "copy-manifest.json", manifest)
    for check in ("smoke", "synthesis"):
        selection = (["--prepare", "compact" if check == "smoke" else "synthesis"]
                     if development else ["--check", check, "--portable-child"])
        run.command(["python3", "tests/verify.py", *selection, "--out-root",
                     f"evidence/portable-{check}"], f"portable-{check}", cwd=stage)
    receipts = sorted(stage.glob("evidence/portable-*/*/receipt.json"))
    assert len(receipts) == 2, "missing clean-stage receipts"
    for path in receipts:
        receipt = json.loads(path.read_text())
        assert receipt["exit"] == 0
        assert receipt["cwd"] == "."
        assert receipt["source_hashes"] == manifest, "staging source closure"
    write_json(run.path / "reproduction.json",
               {"scope": "bounded portable reproduction, not hardware qualification",
                "copied_files": len(manifest), "child_receipts": [
                    run.relative(p) for p in receipts], "outcome": "passed"})


def run_check(run, check, portable_child=False):
    if check == "smoke":
        smoke(run)
    elif check == "matrix":
        assert not portable_child
        matrix(run)
    elif check == "synthesis":
        if portable_child:
            run.tool("yosys")
            synthesis.structural_rules(run.root)
            synthesis.synthesize(run, "bellows_l3_top", 3, 3)
        else:
            synthesis.check(run, CELLS)
    elif check == "mutations":
        assert not portable_child
        oracle.selftest()
        for tool in ("verilator", "g++", "make"):
            run.tool(tool)
        mutations.execute(run, compile_bus, write_cases, compare_results, make_frame)
    elif check == "reproduce":
        assert not portable_child
        reproduce(run)
    else:
        raise ValueError(f"unknown check {check}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=("smoke", "matrix", "synthesis",
                                          "mutations", "reproduce"))
    parser.add_argument("--prepare", nargs="?", const="compact",
                        choices=("compact", "errors", "synthesis", "parent",
                                 "protocol", "full-parent", "endpoint", "default-synthesis",
                                 "mutation", "mutation-transfer", "matrix-cell", "portable",
                                 "hidden-reservation-error-settlement"),
                        help="bounded development probe, not acceptance")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--repair-of")
    parser.add_argument("--portable-child", action="store_true",
                        help="bounded smoke/representative synthesis in clean staging")
    args = parser.parse_args()
    if bool(args.prepare) == bool(args.check):
        parser.error("select exactly one of --check or --prepare")
    run = Run(ROOT, args.out_root, args.check or "preparation", ["python3", *sys.argv],
              repair_of=args.repair_of)
    try:
        if not __debug__:
            raise RuntimeError("Python assertion disabling is unsupported for verification")
        if args.prepare:
            prepare(run, args.prepare)
        else:
            run_check(run, args.check, args.portable_child)
        if sources(run.root) != run.receipt["source_hashes"]:
            raise RuntimeError("declared verification inputs changed during execution")
    except Exception as error:
        run.finish(error)
        message = f"FAIL: {error}\nReceipt: {run.relative(run.path / 'receipt.json')}\n"
        (run.path / "stderr.txt").write_text(message)
        sys.stderr.write(message)
        return 1
    finally:
        for directory in run.path.glob("**/compile-obj"):
            shutil.rmtree(directory)
    run.finish()
    message = f"Completed; receipt: {run.relative(run.path / 'receipt.json')}\n"
    (run.path / "stdout.txt").write_text(message)
    sys.stdout.write(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
