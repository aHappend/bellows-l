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
    def __init__(self, stem, argv):
        unique = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        self.directory = ROOT / "evidence" / "preparation" / f"{stem}-{unique}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.receipt = {"kind": "verifier-preparation", "argv": argv, "cwd": ".",
                        "start": timestamp(), "children": [], "source_sha256": {}}
        self.started = time.monotonic()
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

    def command(self, name, argv, timeout=3600):
        out = self.directory / f"{name}.stdout.txt"
        err = self.directory / f"{name}.stderr.txt"
        record = {"argv": argv, "cwd": self.relative(self.directory), "start": timestamp(),
                  "timeout_s": timeout, "timed_out": False,
                  "stdout": self.relative(out), "stderr": self.relative(err)}
        self.receipt["children"].append(record)
        started = time.monotonic()
        with out.open("xb") as stdout, err.open("xb") as stderr:
            process = subprocess.Popen(argv, cwd=self.directory, stdout=stdout, stderr=stderr)
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
        if code != 0 or record["timed_out"]:
            raise RuntimeError(f"{name} failed, exit={code}, stderr={self.relative(err)}")
        return out.read_text()

    def finish(self, code, error=None):
        build = self.directory / "compile-obj"
        if build.is_dir():
            executable = build / "Vtb"
            if executable.is_file():
                shutil.copy2(executable, self.directory / "simulator")
            shutil.rmtree(build)
        self.receipt.update(end=timestamp(), duration_s=time.monotonic()-self.started,
                            timeout_s=3600, exit_code=code, timed_out=False)
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


def check_results(experiment, cases, libraries, dictionary=b""):
    lines = (experiment.directory / "results.txt").read_text().splitlines()
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
        if error != case.error:
            raise AssertionError(f"{case.name}: completion error {error}, expected {case.error}")
        if read != len(case.source) or written != len(actual):
            raise AssertionError(f"{case.name}: incorrect exact byte counts")
        if case.decompress:
            raw = libraries.decompress_zstd(
                case.source[:-4] if case.mode else case.source, case.capacity,
                dictionary if case.codec == 6 else b"")
            if actual != raw:
                raise AssertionError(f"{case.name}: full decoded output mismatch")
        else:
            raw = case.source
            standard = actual[:-4] if case.mode else actual
            if case.codec in (5, 6):
                recovered = libraries.decompress_zstd(
                    standard, len(raw), dictionary if case.codec == 6 else b"")
                if recovered != raw:
                    raise AssertionError(f"{case.name}: libzstd full output mismatch")
                if len(standard) > len(raw)+17:
                    raise AssertionError(f"{case.name}: raw fallback length bound")
                if standard[:6] != bytes.fromhex("28b52ffd8438"):
                    raise AssertionError(f"{case.name}: emitted profile mismatch")
            elif case.codec == 0:
                if decode_lz4(standard) != raw:
                    raise AssertionError(f"{case.name}: Python LZ4 full output mismatch")
                libraries.decompress_lz4(standard, raw)
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
                         "output_sha256": sha256(actual), "checksum": checksum})
    (experiment.directory / "comparisons.json").write_text(json.dumps(compared, indent=2)+"\n")
    experiment.receipt["complete_byte_comparisons"] = len(compared)


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
    baseline_total = candidate_total = 0
    failed = []
    for i, record in enumerate(manifest):
        baseline = bytes.fromhex(lines[i*4+1])
        candidate = bytes.fromhex(lines[i*4+3])
        baseline_total += len(baseline)
        candidate_total += len(candidate)
        record.update(baseline_bytes=len(baseline), candidate_bytes=len(candidate),
                      threshold_numerator=3, threshold_denominator=4,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=CONFIGURATIONS, default="nonpower")
    parser.add_argument("--simulator", choices=("icarus", "verilator"), default="icarus")
    parser.add_argument("--suite", choices=("transport", "dictionary"), default="transport")
    parser.add_argument("--seed", type=int, choices=(17, 89, 2026), default=17)
    args = parser.parse_args()
    experiment = Experiment(f"l5-{args.suite}-{args.configuration}-{args.simulator}",
                            ["python3", "tests/preparation.py", *sys.argv[1:]])
    try:
        libraries = Libraries()
        experiment.receipt["libraries"] = libraries.versions()
        for data in (b"", b"a", b"abc", bytes(range(255)), b"a"*4096):
            libraries.check_hash(data)
        assert libraries.decompress_zstd(rle_sequence_frame(), 8) == b"a"*8
        geometry = CONFIGURATIONS[args.configuration]
        dictionary, manifest = b"", []
        if args.suite == "dictionary":
            if args.simulator != "verilator" or geometry[0] < 16384 or geometry[3] < 16384:
                raise ValueError("dictionary page diagnostic requires compiled page16k/default geometry")
            dictionary, cases, manifest = dictionary_cases(args.seed)
            (experiment.directory / "fixture-manifest.json").write_text(json.dumps(
                {"generator": dictionary_cases.__doc__, "cases": manifest,
                 "dictionary_sha256": sha256(dictionary)}, indent=2)+"\n")
        else:
            cases = cases_for(geometry)
        experiment.receipt.update(configuration=args.configuration, geometry=geometry,
                                  seed=args.seed, cases=[c.name for c in cases])
        tb = top_testbench(cases, geometry, experiment.directory, args.seed, dictionary)
        (experiment.directory / "tb.sv").write_text(tb)
        sources = [p.relative_to(experiment.directory).as_posix()
                   for p in sorted((experiment.directory/"source"/"rtl").glob("*.sv"))]
        experiment.receipt["generated_tb_sha256"] = sha256(tb.encode())
        if args.simulator == "icarus":
            experiment.command("tool-version", ["iverilog", "-V"])
            experiment.command("compile", ["iverilog", "-g2012", "-Wall", "-s", "tb",
                                          "-o", "sim.vvp", "tb.sv", *sources])
            experiment.command("simulation", ["vvp", "sim.vvp"])
        else:
            experiment.command("tool-version", ["verilator", "--version"])
            experiment.command("compile", ["verilator", "--binary", "--timing", "-Wno-fatal",
                                          "--top-module", "tb", "-j", "2", "--Mdir", "compile-obj",
                                          "tb.sv", *sources])
            experiment.command("simulation", ["./compile-obj/Vtb"])
        check_results(experiment, cases, libraries, dictionary)
        if args.suite == "dictionary":
            check_gain(experiment, manifest)
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
