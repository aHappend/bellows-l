"""Reproduce the retained attempt-15 page corruption with its valid control."""

import json
import argparse
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

from l1_oracle import Libraries
from l1_runner import Simulation
from l1_transport import Case
from preparation import CONFIGURATIONS, Experiment, ROOT, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="execute all 192 retained flips")
    args = parser.parse_args()
    experiment = Experiment("timeout-discrimination",
                            ["python3", "tests/timeout_diagnosis.py", *sys.argv[1:]])
    previous = Path("evidence/l1-behavior-default-20261103T064957Z-83981782")
    experiment.receipt["repair_of"] = str(previous / "receipt.json")
    simulation = Simulation(experiment, CONFIGURATIONS["default"], Libraries(),
                            cycle_limit=100000000 if args.all else 5000000)
    try:
        runs = list((ROOT / previous).glob("simulation-*/page-corruption-*"))
        if len(runs) != 1:
            raise AssertionError("retained corruption run is ambiguous")
        retained = runs[0]
        changed = bytes(int(b, 16) for b in (retained / "source-0.hex").read_text().split())
        dictionary = bytes(int(b, 16) for b in
                           (retained / "dictionary.hex").read_text().split())
        original = bytearray(changed)
        original[393] ^= 0x80
        if len(changed) != 553:
            raise AssertionError("unexpected retained corruption vector length")
        experiment.receipt["retained_vectors"] = {
            "corrupt_sha256": sha256(changed), "valid_sha256": sha256(original),
            "dictionary_sha256": sha256(dictionary), "changed_byte": 393, "xor": 128}
        cases = [
            Case("unchanged-valid-control", bytes(original), codec=6, decompress=1,
                 capacity=4096, wide=1, dictionary_id=0x12345678),
            Case("retained-byte393-bit7", changed, codec=6, decompress=1,
                 capacity=4096, wide=1, dictionary_id=0x12345678, error=-1),
        ]
        simulation.run("retained-pair", cases, 2026, dictionary)
        if args.all:
            cases = []
            metadata = (retained / "cases.txt").read_text().splitlines()
            if int(metadata[0]) != 192:
                raise AssertionError("retained page corruption count")
            for line in metadata[1:]:
                values = list(map(int, line.split()))
                index, size, codec, decompress, mode, wide, channel, capacity, identity = values[:9]
                source = bytes(int(b, 16) for b in
                               (retained / f"source-{index}.hex").read_text().split())
                if len(source) != size:
                    raise AssertionError("retained vector size")
                cases.append(Case(f"retained-page-flip-{index}", source, codec=codec,
                                  decompress=decompress, mode=mode, wide=wide,
                                  channel=channel, capacity=capacity,
                                  dictionary_id=identity, error=-1))
            simulation.run("page-corruption-retained", cases, 2026, dictionary)
        experiment.finish(0)
        return 0
    except Exception as error:
        (experiment.directory / "failure.txt").write_text(traceback.format_exc())
        experiment.finish(1, str(error))
        return 1
    finally:
        simulation.close()


if __name__ == "__main__":
    sys.exit(main())
