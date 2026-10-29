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
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle
import scenarios
from retention import Run, write_json
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
                             "src_segments": src, "dst_segments": dst})
    path.write_text("\n".join(lines) + "\n")
    write_json(path.with_suffix(".json"), manifest)


def compile_bus(run, block, sg, simulator):
    directory = run.path / f"bus-{simulator}-{block}-{sg}"
    directory.mkdir()
    tb = directory / "tb.sv"
    tb.write_text(bench(block, sg, compact=simulator == "icarus"))
    rtl = [run.relative(p) for p in sorted(run.root.glob("rtl/*.sv"))]
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
            records[key] = {"id": identifier, "error": error, "source_bytes": source_count,
                            "destination_bytes": destination_count,
                            "checksum": value, "output_hex": actual.hex()}
        elif parts[0] == "COVER":
            assert coverage is None, "duplicate coverage"
            coverage = dict(zip(("four_active", "read_switches", "read_stall",
                                 "write_stall", "status_stall", "response_gaps",
                                 "compress_source_cross", "decode_source_cross",
                                 "compress_dest_cross", "decode_dest_cross",
                                 "single_segments", "depth16"),
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


def simulate(run, build, batches, sg, seed, label):
    directory, executable = build
    case_path = directory / f"{label}.cases"
    result_path = directory / f"{label}.results"
    write_cases(case_path, batches, sg, seed)
    command = [run.relative(executable), "+case=" + run.relative(case_path),
               "+result=" + run.relative(result_path)]
    if "icarus" in directory.name:
        command.insert(0, "vvp")
    stdout, _ = run.command(command, label)
    assert "SIMULATION_COMPLETE" in stdout, "missing simulator completion marker"
    records, coverage = compare_results(result_path, batches)
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
    for tool in (("iverilog", "vvp") if kind == "compact" else
                 ("verilator", "g++", "make")):
        run.tool(tool)
    oracle.selftest()
    if kind == "compact":
        build = compile_bus(run, 33, 3, "icarus")
        simulate(run, build, compact_batches(), 3, 17, "compact-dma-probe")
    else:
        build = compile_bus(run, 255, 16, "verilator")
        batches = (scenarios.boundaries(make_frame) +
                   scenarios.corruption_batches(make_frame) +
                   scenarios.errors(255, 16, make_frame))
        simulate(run, build, batches, 16, 17, "error-and-boundary-probe")


def run_check(run, check):
    raise RuntimeError(f"{check}: verification authoring is incomplete; "
                       "do not request engineering acceptance")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", choices=("smoke", "matrix", "synthesis",
                                          "mutations", "reproduce"))
    parser.add_argument("--prepare", nargs="?", const="compact", choices=("compact", "errors"),
                        help="bounded development probe, not acceptance")
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    if bool(args.prepare) == bool(args.check):
        parser.error("select exactly one of --check or --prepare")
    run = Run(ROOT, args.out_root, args.check or "preparation", sys.argv,
              repair_of=args.repair_of)
    try:
        if args.prepare:
            prepare(run, args.prepare)
        else:
            run_check(run, args.check)
    except Exception as error:
        run.finish(error)
        print(f"FAIL: {error}\nReceipt: {run.relative(run.path / 'receipt.json')}",
              file=sys.stderr)
        return 1
    finally:
        for directory in run.path.glob("bus-*/compile-obj"):
            shutil.rmtree(directory)
    run.finish()
    print(f"Completed; receipt: {run.relative(run.path / 'receipt.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
