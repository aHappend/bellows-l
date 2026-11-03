"""Source-bound, public-pin preparation experiments (not admitted L1 results).

Run from the project root:
    python3 tests/preparation.py --configuration nonpower --simulator icarus
Each run has a new exclusive evidence directory, including failed experiments.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from l1_oracle import Libraries, decode_lz4, frame, private_checksum, rle_sequence_frame
from l1_transport import Case, top_testbench
from l1_zstd import FrameError, decode_frame, sequence_frame
from l1_fse import table_testbench
from l1_synthesis import synthesis
from l1_legacy import decode_huffman, encode_huffman, literal_lz4


ROOT = Path(__file__).resolve().parent.parent
CONFIGURATIONS = {
    "singleton": (1, 1, 4, 1),
    "nonpower": (3, 3, 8, 7),
    "page4k": (4096, 1, 4, 4096),
    "page16k": (16384, 3, 8, 16384),
    "default": (65536, 16, 8, 16384),
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Experiment:
    def __init__(self, stem, argv, admitted=False):
        unique = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        parent = ROOT / "evidence" if admitted else ROOT / "evidence" / "preparation"
        self.directory = parent / f"{stem}-{unique}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.receipt = {"kind": "l1-check" if admitted else "verifier-preparation",
                        "argv": argv, "cwd": ".",
                        "start": timestamp(), "children": [], "source_sha256": {},
                        "python_version": sys.version}
        self.started = time.monotonic()
        self.deadline = self.started + 2700
        for pattern in ("rtl/*.sv", "tests/*.py", "design/*.md", "bellows_l4_reference/rtl/*.sv"):
            for path in sorted(ROOT.glob(pattern)):
                relative = path.relative_to(ROOT)
                data = path.read_bytes()
                self.receipt["source_sha256"][relative.as_posix()] = sha256(data)
                target = self.directory / "source" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

    def relative(self, path):
        return path.relative_to(ROOT).as_posix()

    def command(self, name, argv, timeout=2700, cwd=None, expect_failure=False):
        timeout = min(timeout, self.deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("complete check exceeded its 2700-second execution budget")
        print(f"Verification step: {name}", flush=True)
        cwd = self.directory if cwd is None else cwd
        out = self.directory / f"{name}.stdout.txt"
        err = self.directory / f"{name}.stderr.txt"
        record = {"argv": argv, "cwd": self.relative(cwd), "start": timestamp(),
                  "timeout_s": timeout, "timed_out": False,
                  "stdout": self.relative(out), "stderr": self.relative(err)}
        self.receipt["children"].append(record)
        started = time.monotonic()
        with out.open("xb") as stdout, err.open("xb") as stderr:
            process = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr)
            try:
                while True:
                    try:
                        code = process.wait(timeout=min(30, max(0.01, timeout - (time.monotonic()-started))))
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() - started >= timeout:
                            record["timed_out"] = True
                            process.kill()
                            code = process.wait()
                            break
                        print(f"Preparation {name}: child active ({int(time.monotonic()-started)}s)",
                              flush=True)
            finally:
                record["end"] = timestamp()
                record["exit_code"] = process.returncode
        record["exit_code"] = code
        if record["timed_out"] or (code != 0 and not expect_failure):
            raise RuntimeError(f"{name} failed, exit={code}, stderr={self.relative(err)}")
        if expect_failure and code == 0:
            raise AssertionError(f"{name}: required semantic rejection did not occur")
        return out.read_text()

    def finish(self, code, error=None):
        build = self.directory / "compile-obj"
        if build.is_dir():
            executable = build / "Vtb"
            if executable.is_file():
                shutil.copy2(executable, self.directory / "simulator")
            shutil.rmtree(build)
        self.receipt.update(end=timestamp(), duration_s=time.monotonic()-self.started,
                            timeout_s=2700, exit_code=code,
                            timed_out=any(c["timed_out"] for c in self.receipt["children"]))
        if error is not None:
            self.receipt["failure"] = error
        path = self.directory / "receipt.json"
        with path.open("x") as stream:
            json.dump(self.receipt, stream, indent=2)
            stream.write("\n")
        print(self.relative(path), flush=True)


def cases_for(geometry):
    block, _, _, _ = geometry
    result = []
    for mode in range(3):
        for wide in range(2):
            for raw in (b"", b"x", b"aba"[:block]):
                for codec in (0, 5):
                    result.append(Case(f"encode-c{codec}-m{mode}-w{wide}-n{len(raw)}",
                                       raw, codec, mode=mode, wide=wide, capacity=256,
                                       channel=(mode+wide) % 4))
                encoded = frame(raw)
                if mode:
                    encoded += private_checksum(raw, mode).to_bytes(4, "little")
                result.append(Case(f"raw-decode-m{mode}-w{wide}-n{len(raw)}", encoded,
                                   decompress=1, mode=mode, wide=wide, capacity=256,
                                   channel=(mode+wide) % 4))
    if block >= 8:
        result.append(Case("external-rle-fse", rle_sequence_frame(), decompress=1))
        result.append(Case("local-fse-encode", b"abcabcab" * min(32, block//8)))
    return result


def check_results(experiment, cases, libraries, dictionary=b"", directory=None):
    directory = experiment.directory if directory is None else directory
    lines = (directory / "results.txt").read_text().splitlines()
    if len(lines) != 2 * len(cases):
        raise AssertionError(f"expected {len(cases)} complete results, observed {len(lines)//2}")
    compared = []
    for index, case in enumerate(cases):
        words = lines[index*2].split()
        if len(words) != 6 or words[0] != "RESULT" or int(words[1]) != index:
            raise AssertionError(f"malformed result {index}: {words}")
        error, read, written = map(int, words[2:5])
        checksum = int(words[5], 16)
        actual = bytes.fromhex(lines[index*2+1])
        if (case.error == -1 and error == 0) or (case.error != -1 and error != case.error):
            raise AssertionError(f"{case.name}: completion error {error}, expected {case.error}")
        if read > len(case.source) or written != len(actual):
            raise AssertionError(f"{case.name}: incorrect exact byte counts")
        if not case.error and read != len(case.source):
            raise AssertionError(f"{case.name}: successful command did not consume full source")
        if case.pre_dma and (read or written):
            raise AssertionError(f"{case.name}: invalid command performed DMA")
        if case.error:
            compared.append({"case": case.name, "error": error, "input_bytes": read,
                             "output_bytes": written, "input_sha256": sha256(case.source),
                             "output_sha256": sha256(actual)})
            continue
        decoded = None
        if case.decompress:
            standard = case.source[:-4] if case.mode else case.source
            if case.codec == 0:
                raw = decode_lz4(standard)
                libraries.decompress_lz4(standard, raw)
            elif case.codec in (1, 2, 3, 4):
                raw = decode_huffman(standard, case.codec)
            else:
                decoded = decode_frame(standard, dictionary if case.codec == 6 else b"")
                raw = libraries.decompress_zstd(
                    standard, case.capacity, dictionary if case.codec == 6 else b"")
                if raw != decoded.data:
                    raise AssertionError(f"{case.name}: independent decoder disagreement")
            if actual != raw:
                raise AssertionError(f"{case.name}: full decoded output mismatch")
        else:
            raw = case.source
            standard = actual[:-4] if case.mode else actual
            if case.codec in (5, 6):
                decoded = decode_frame(standard, dictionary if case.codec == 6 else b"")
                recovered = libraries.decompress_zstd(
                    standard, len(raw), dictionary if case.codec == 6 else b"")
                if recovered != raw or decoded.data != raw:
                    raise AssertionError(f"{case.name}: libzstd full output mismatch")
                if len(standard) > len(raw)+17:
                    raise AssertionError(f"{case.name}: raw fallback length bound")
                if standard[:6] != bytes.fromhex("28b52ffd8438"):
                    raise AssertionError(f"{case.name}: emitted profile mismatch")
            elif case.codec == 0:
                if decode_lz4(standard) != raw:
                    raise AssertionError(f"{case.name}: Python LZ4 full output mismatch")
                libraries.decompress_lz4(standard, raw)
            elif case.codec in (1, 2, 3, 4):
                if decode_huffman(standard, case.codec) != raw:
                    raise AssertionError(f"{case.name}: inherited canonical-code mismatch")
            else:
                raise AssertionError(f"unimplemented probe oracle: codec {case.codec}")
        expected_checksum = private_checksum(raw, case.mode)
        if checksum != expected_checksum:
            raise AssertionError(f"{case.name}: status checksum mismatch")
        if case.mode and not case.decompress:
            if actual[-4:] != expected_checksum.to_bytes(4, "little"):
                raise AssertionError(f"{case.name}: private checksum trailer mismatch")
        compared.append({"case": case.name, "input_bytes": len(case.source),
                         "output_bytes": len(actual), "input_sha256": sha256(case.source),
                         "output_sha256": sha256(actual), "checksum": checksum,
                         "rfc_modes": list(decoded.modes) if decoded else [],
                         "fse_sequences": len(decoded.sequences) if decoded else 0,
                         "fse_transitions": decoded.transitions if decoded else 0,
                         "dictionary_matches": decoded.dictionary_matches if decoded else 0})
    (directory / "comparisons.json").write_text(json.dumps(compared, indent=2)+"\n")
    experiment.receipt["complete_byte_comparisons"] = (
        experiment.receipt.get("complete_byte_comparisons", 0) + len(compared))


def dictionary_cases(seed):
    """Freeze fixtures before execution: independently pinned bytes, then pages.

    Python MT19937(seed).randbytes(16384) supplies the raw dictionary.
    A separate MT19937(seed XOR 0xB31105) chooses each start offset uniformly
    in [0,16384-7*page_size/8], then supplies page_size/8 fresh random bytes.
    Dictionary generation never sees a page, and the same image serves all
    three sizes without replacement. No fixture is selected based on DUT gain.
    """
    dictionary = random.Random(seed).randbytes(16384)
    generator = random.Random(seed ^ 0xB31105)
    cases, manifest = [], []
    for size in (4096, 8192, 16384):
        prefix = size * 7 // 8
        offset = generator.randrange(16384-prefix+1)
        raw = dictionary[offset:offset+prefix] + generator.randbytes(size-prefix)
        cases.extend((Case(f"baseline-{size}", raw, codec=0, wide=1,
                           capacity=2*size+1024),
                      Case(f"dictionary-{size}", raw, codec=6, wide=1,
                           capacity=2*size+1024, dictionary_id=0x12345678)))
        manifest.append({"seed": seed, "page_bytes": size, "offset": offset,
                         "dictionary_prefix_bytes": prefix, "fresh_bytes": size-prefix,
                         "page_sha256": sha256(raw)})
    return dictionary, cases, manifest


def check_gain(experiment, manifest):
    lines = (experiment.directory / "results.txt").read_text().splitlines()
    comparisons = json.loads((experiment.directory / "comparisons.json").read_text())
    baseline_total = candidate_total = 0
    failed = []
    for i, record in enumerate(manifest):
        baseline = bytes.fromhex(lines[i*4+1])
        candidate = bytes.fromhex(lines[i*4+3])
        parsed = comparisons[i*2+1]
        if parsed["dictionary_matches"] == 0 or parsed["fse_transitions"] == 0:
            raise AssertionError("dictionary gain fixture did not execute dictionary/FSE processing")
        baseline_total += len(baseline)
        candidate_total += len(candidate)
        record.update(baseline_bytes=len(baseline), candidate_bytes=len(candidate),
                      threshold_numerator=3, threshold_denominator=4,
                      dictionary_matches=parsed["dictionary_matches"],
                      fse_transitions=parsed["fse_transitions"],
                      passed=4*len(candidate) <= 3*len(baseline))
        if not record["passed"]:
            failed.append(record["page_bytes"])
    result = {"cases": manifest, "aggregate_baseline_bytes": baseline_total,
              "aggregate_candidate_bytes": candidate_total,
              "aggregate_passed": 2*candidate_total <= baseline_total,
              "cold_load_bytes": 16384, "pinned_logical_dictionary_bytes": 16384}
    (experiment.directory / "dictionary-gain.json").write_text(json.dumps(result, indent=2)+"\n")
    if failed or not result["aggregate_passed"]:
        raise AssertionError(f"dictionary gain: failed pages={failed}, "
                             f"aggregate={candidate_total}/{baseline_total}, required <=1/2")


def roundtrip(experiment, cases, geometry, seed, dictionary, libraries):
    """Re-use the compiled public transactor with fresh input vectors and reset."""
    lines = (experiment.directory / "results.txt").read_text().splitlines()
    decodes = [Case("roundtrip-" + c.name, bytes.fromhex(lines[2*i+1]), codec=c.codec,
                    decompress=1, mode=c.mode, wide=c.wide, channel=c.channel,
                    capacity=max(1, len(c.source)), dictionary_id=c.dictionary_id)
               for i, c in enumerate(cases)]
    directory = experiment.directory / "roundtrip"
    directory.mkdir(exist_ok=False)
    tb = top_testbench(decodes, geometry, directory, seed, dictionary)
    if tb != (experiment.directory / "tb.sv").read_text():
        raise AssertionError("round-trip vectors changed compiled transactor geometry")
    experiment.command("roundtrip-simulation", ["../compile-obj/Vtb"], timeout=2400,
                       cwd=directory)
    check_results(experiment, decodes, libraries, dictionary, directory)
    decoded_lines = (directory / "results.txt").read_text().splitlines()
    for index, original in enumerate(cases):
        recovered = bytes.fromhex(decoded_lines[2*index+1])
        if recovered != original.source:
            raise AssertionError(f"{original.name}: complete RTL round-trip mismatch")
    experiment.receipt["rtl_roundtrips"] = len(cases)


def interop_cases(libraries, dictionary=b""):
    """Public-pin predefined/RLE/compressed combinations and repeat rejection."""
    from itertools import product
    result = []
    fresh = sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)], dictionary=dictionary)
    for mask in range(1, 8):
        changed = bytearray(fresh)
        for alphabet, shift in enumerate((6, 4, 2)):
            if mask & (1 << alphabet):
                changed[17] |= 3 << shift
        malformed = bytes(changed)
        try:
            decode_frame(malformed, dictionary)
        except FrameError as error:
            assert error.code == 11
        else:
            raise AssertionError("independent parser accepted fresh repeat selector")
        try:
            libraries.decompress_zstd(malformed, 4096, dictionary)
        except ValueError:
            pass
        else:
            raise AssertionError("libzstd accepted fresh repeat selector")
        result.append(Case(f"fresh-repeat-mask{mask}", malformed,
                           codec=6 if dictionary else 5, decompress=1, error=11,
                           dictionary_id=0x12345678 if dictionary else 0, reset_before=True))
    for modes in product(range(3), repeat=3):
        source = sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)], modes, dictionary)
        expected = decode_frame(source, dictionary)
        assert libraries.decompress_zstd(source, 4096, dictionary) == expected.data
        result.append(Case("external-modes-" + "".join(map(str, modes)), source,
                           codec=6 if dictionary else 5, decompress=1,
                           dictionary_id=0x12345678 if dictionary else 0))
        for mask in range(1, 8):
            # One-byte literal header, two literal bytes, one sequence count.
            changed = bytearray(source)
            for alphabet, shift in enumerate((6, 4, 2)):
                if mask & (1 << alphabet):
                    changed[17] |= 3 << shift
            malformed = bytes(changed)
            try:
                decode_frame(malformed, dictionary)
            except FrameError as error:
                assert error.code == 11
            else:
                raise AssertionError("independent parser accepted prior-table-free repeat")
            try:
                libraries.decompress_zstd(malformed, 4096, dictionary)
            except ValueError:
                pass
            else:
                raise AssertionError("libzstd accepted repeat fixture")
            result.append(Case(f"repeat-after-{modes}-mask{mask}", malformed,
                               codec=6 if dictionary else 5, decompress=1, error=11,
                               dictionary_id=0x12345678 if dictionary else 0))
            result.append(Case(f"recovery-after-{modes}-mask{mask}", source,
                               codec=6 if dictionary else 5, decompress=1,
                               dictionary_id=0x12345678 if dictionary else 0))
    for logs in ((5, 5, 5), (6, 6, 6), (9, 8, 9)):
        source = sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)], (2, 2, 2),
                                dictionary, logs)
        expected = decode_frame(source, dictionary)
        assert libraries.decompress_zstd(source, 4096, dictionary) == expected.data
        result.append(Case(f"external-compressed-logs{logs}", source,
                           codec=6 if dictionary else 5, decompress=1,
                           dictionary_id=0x12345678 if dictionary else 0))
    return result


def legacy_cases(geometry):
    block = geometry[0]
    cases = []
    for codec in range(5):
        for mode in range(3):
            for wide in range(2):
                for size in sorted({0, min(block, 1), min(block, 2), min(block, 3),
                                    min(block, 257)}):
                    if codec == 2 and size & 1:
                        continue
                    raw = bytes((i * 73 + 17) & 255 for i in range(size))
                    tag = f"legacy-c{codec}-m{mode}-w{wide}-n{size}"
                    cases.append(Case(tag + "-encode", raw, codec=codec, mode=mode,
                                      wide=wide, capacity=4*block+1024))
                    encoded = literal_lz4(raw) if codec == 0 else encode_huffman(raw, codec)
                    if mode:
                        encoded += private_checksum(raw, mode).to_bytes(4, "little")
                    cases.append(Case(tag + "-external-decode", encoded, codec=codec,
                                      mode=mode, wide=wide, decompress=1,
                                      capacity=max(1, size)))
    return cases


def corruption_cases(libraries, dictionary=b""):
    source = (sequence_frame(b"", [(0, 7, 33), (0, 7, 33)], dictionary=dictionary)
              if dictionary else sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)]))
    parsed = decode_frame(source, dictionary)
    if libraries.decompress_zstd(source, 4096, dictionary) != parsed.data:
        raise AssertionError("corruption control frame differs between independent models")
    vectors = [("control", source)]
    for bit in range(8 * len(source)):
        changed = bytearray(source)
        changed[bit // 8] ^= 1 << (bit % 8)
        vectors.append((f"bit-{bit}", bytes(changed)))
    vectors.extend((f"truncate-{length}", source[:length]) for length in range(len(source)))
    for position in range(len(source) + 1):
        vectors.append((f"insert-{position}", source[:position] + b"\x00" + source[position:]))
    vectors.append(("trailing", source + b"\x7f"))
    cases, manifest = [], []
    for label, changed in vectors:
        try:
            model = decode_frame(changed, dictionary)
        except FrameError:
            model = None
        try:
            library = libraries.decompress_zstd(changed, 4096, dictionary)
        except ValueError:
            library = None
        if model is not None and library is not None and model.data != library:
            raise AssertionError(f"independent corruption-oracle disagreement: {label}")
        expected_error = 0 if model is not None and library is not None else -1
        manifest.append({"case": label, "input_sha256": sha256(changed),
                         "parser_accepts": model is not None, "libzstd_accepts": library is not None,
                         "semantically_equivalent": model is not None and model.data == parsed.data})
        cases.append(Case(label, changed, codec=6 if dictionary else 5, decompress=1,
                          error=expected_error, capacity=4096,
                          dictionary_id=0x12345678 if dictionary else 0))
    return cases, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=CONFIGURATIONS, default="nonpower")
    parser.add_argument("--simulator", choices=("icarus", "verilator"), default="icarus")
    parser.add_argument("--suite", choices=("transport", "legacy", "dictionary", "interop", "corruption", "fse", "synthesis", "errors", "matrix", "boundaries", "protocol", "parameters", "parent", "defects", "portable", "smoke", "tables", "sequence-boundaries", "constant-table", "dictionary-edges"), default="transport")
    parser.add_argument("--pinned-dictionary", action="store_true")
    parser.add_argument("--seed", type=int, choices=(17, 89, 2026), default=17)
    parser.add_argument("--repair-of", help="Project-relative retained failure receipt")
    args = parser.parse_args()
    experiment = Experiment(f"l5-{args.suite}-{args.configuration}-{args.simulator}",
                            ["python3", "tests/preparation.py", *sys.argv[1:]])
    if args.repair_of:
        experiment.receipt["repair_of"] = args.repair_of
    try:
        if args.suite == "synthesis":
            synthesis(experiment, [(args.configuration, CONFIGURATIONS[args.configuration])])
            experiment.finish(0)
            return 0
        libraries = Libraries()
        experiment.receipt["libraries"] = libraries.versions()
        for data in (b"", b"a", b"abc", bytes(range(255)), b"a"*4096):
            libraries.check_hash(data)
        assert libraries.decompress_zstd(rle_sequence_frame(), 8) == b"a"*8
        geometry = CONFIGURATIONS[args.configuration]
        if args.suite in ("parameters", "parent", "defects", "portable", "smoke"):
            from l1_runner import Simulation
            from verify import parameters, portable, smoke
            if args.suite == "parameters":
                parameters(experiment)
            elif args.suite == "portable":
                portable(experiment)
            elif args.suite == "smoke":
                smoke(experiment, libraries)
            elif args.suite == "defects":
                from l1_defects import defects
                defects(experiment, libraries)
            else:
                simulation = Simulation(experiment, geometry, libraries, parent=True)
                try:
                    simulation.run("parent", legacy_cases(geometry))
                finally:
                    simulation.close()
            experiment.finish(0)
            return 0
        dictionary, manifest = b"", []
        if args.pinned_dictionary:
            if geometry[3] < 1024:
                raise ValueError("pinned diagnostic requires at least 1024 dictionary bytes")
            dictionary = bytes.fromhex("37a430ec") + random.Random(2026).randbytes(1020)
        if args.suite == "dictionary":
            if args.simulator != "verilator" or geometry[0] < 16384 or geometry[3] < 16384:
                raise ValueError("dictionary page diagnostic requires compiled page16k/default geometry")
            dictionary, cases, manifest = dictionary_cases(args.seed)
            (experiment.directory / "fixture-manifest.json").write_text(json.dumps(
                {"generator": dictionary_cases.__doc__, "cases": manifest,
                 "dictionary_sha256": sha256(dictionary)}, indent=2)+"\n")
        elif args.suite == "fse":
            cases = []
        elif args.suite == "legacy":
            cases = legacy_cases(geometry)
        elif args.suite == "protocol":
            from verify import protocol
            protocol(experiment, geometry, libraries, args.seed, args.simulator)
            experiment.finish(0)
            return 0
        elif args.suite in ("errors", "matrix", "boundaries", "tables", "sequence-boundaries", "constant-table", "dictionary-edges"):
            from l1_matrix import boundaries, codec_matrix, dictionary_edges, errors, malformed_tables, sequence_boundaries
            from l1_runner import Simulation
            dictionary = random.Random(args.seed).randbytes(min(geometry[3], 1024))
            def constant_table():
                source = sequence_frame(
                    b"aa", [(1, 7, 4), (1, 7, 4)], (2, 2, 2), logs=(5, 5, 5),
                    distributions=((0, 32), (0, 0, 32), (0, 0, 0, 0, 32)))
                expected = decode_frame(source).data
                if libraries.decompress_zstd(source, 4096) != expected:
                    raise AssertionError("constant normalized-table independent oracles disagree")
                return [Case("legal-single-symbol-compressed-tables", source,
                             decompress=1, capacity=4096)]
            builder = {"errors": lambda: errors(geometry, dictionary),
                       "matrix": lambda: codec_matrix(geometry, args.seed, dictionary),
                       "boundaries": lambda: boundaries(geometry, args.seed),
                       "tables": lambda: malformed_tables(libraries, dictionary),
                       "sequence-boundaries": lambda: sequence_boundaries(geometry, libraries),
                       "dictionary-edges": lambda: dictionary_edges(geometry, dictionary, libraries),
                       "constant-table": constant_table}[args.suite]
            simulation = Simulation(experiment, geometry, libraries)
            try:
                simulation.run(args.suite, builder(), args.seed, dictionary)
            finally:
                simulation.close()
            experiment.finish(0)
            return 0
        elif args.suite == "interop":
            cases = interop_cases(libraries, dictionary)
        elif args.suite == "corruption":
            cases, manifest = corruption_cases(libraries, dictionary)
            (experiment.directory / "corruption-manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n")
        else:
            cases = cases_for(geometry)
        experiment.receipt.update(configuration=args.configuration, geometry=geometry,
                                  seed=args.seed, cases=[c.name for c in cases])
        tb = (table_testbench(experiment.directory) if args.suite == "fse" else
              top_testbench(cases, geometry, experiment.directory, args.seed, dictionary))
        (experiment.directory / "tb.sv").write_text(tb)
        sources = [p.relative_to(experiment.directory).as_posix()
                   for p in sorted((experiment.directory/"source"/"rtl").glob("*.sv"))]
        if args.suite == "fse":
            sources = [p for p in sources if Path(p).stem in
                       ("bellows_l5_fse_table", "bellows_l5_fse_decoder")]
        experiment.receipt["generated_tb_sha256"] = sha256(tb.encode())
        if args.simulator == "icarus":
            experiment.command("tool-version", ["iverilog", "-V"])
            experiment.command("compile", ["iverilog", "-g2012", "-Wall", "-s", "tb",
                                          "-o", "sim.vvp", "tb.sv", *sources])
            simulation = experiment.command("simulation", ["vvp", "sim.vvp"], timeout=600)
        else:
            experiment.command("tool-version", ["verilator", "--version"])
            experiment.command("compile", ["verilator", "--binary", "--timing", "-Wno-fatal",
                                          "--top-module", "tb", "-j", "2", "--Mdir", "compile-obj",
                                          "tb.sv", *sources])
            simulation = experiment.command("simulation", ["./compile-obj/Vtb"], timeout=2400)
        if args.suite == "fse":
            experiment.receipt["comparison_summary"] = simulation.strip()
        else:
            check_results(experiment, cases, libraries, dictionary)
        if args.suite == "dictionary":
            check_gain(experiment, manifest)
            roundtrip(experiment, cases, geometry, args.seed, dictionary, libraries)
        experiment.finish(0)
        return 0
    except Exception as error:
        detail = traceback.format_exc()
        (experiment.directory / "failure.txt").write_text(detail)
        experiment.finish(1, str(error))
        print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
