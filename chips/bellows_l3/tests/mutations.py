"""Executed functional rejection of disposable, source-bound RTL defects."""

import difflib
import hashlib
import shutil

import oracle
from retention import write_json


DEFECTS = (
    ("suppressed-mismatch", "bellows_l3_context.sv",
     "error_code<=7;", "error_code<=0;", "status_error"),
    ("checksum-arithmetic", "bellows_l3_checksum.sv",
     "P5=32'h165667b1", "P5=32'h165667b0", "status_checksum"),
    ("channel-ownership", "bellows_l3_sg_dma.sv",
     "read_owner<=read_channel;", "read_owner<=read_channel+2'd1;", "channel_transfer_bytes"),
    ("sg-boundary", "bellows_l3_context.sv",
     "read_address<=source_address[source_index+1'b1];",
     "read_address<=source_address[source_index+1'b1]+64'd1;", "READ_ADDRESS"),
)


def execute(run, compile_bus, write_cases, compare_results, make_frame, only=None):
    results = []
    for label, filename, original, changed, observable in DEFECTS:
        if only is not None and label != only:
            continue
        directory = run.path / label
        directory.mkdir()
        rtl = directory / "rtl"
        rtl.mkdir()
        hashes = {}
        for path in sorted(run.root.glob("rtl/*.sv")):
            target = rtl / path.name
            shutil.copy2(path, target)
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        path = rtl / filename
        text = path.read_text()
        assert text.count(original) == 1, ("mutation anchor changed", label)
        mutated = text.replace(original, changed)
        path.write_text(mutated)
        (directory / "mutation.diff").write_text("".join(difflib.unified_diff(
            text.splitlines(True), mutated.splitlines(True),
            fromfile="rtl/" + filename, tofile="mutant/rtl/" + filename)))
        write_json(directory / "source-manifest.json",
                   {"original": hashes, "mutated": {
                       p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(rtl.glob("*.sv"))}})
        build_dir, executable = compile_bus(run, 33, 3, "verilator",
                                             rtl_dir=rtl, tag=label)
        frames = [make_frame(7000 + ch, bytes((ch * 31 + i) & 255 for i in range(33)),
                             False, 1) for ch in range(4)]
        if label == "suppressed-mismatch":
            frames = [make_frame(7100 + ch, bytes((ch * 31 + i) & 255 for i in range(33)),
                                 True, 1) for ch in range(4)]
            for f in frames:
                wire = bytearray(f.source)
                wire[-1] ^= 0x80
                f.source, f.error = bytes(wire), 7
        case_path, result_path = build_dir / "cases.txt", build_dir / "results.txt"
        write_cases(case_path, [frames], 3, 17)
        stdout, stderr = run.command(
            [run.relative(executable), "+case=" + run.relative(case_path),
             "+result=" + run.relative(result_path)], label + "-functional",
            expected=(0, 1, -6, 134))
        child = run.receipt["commands"][-1]
        if child["exit"] == 0:
            assert "SIMULATION_COMPLETE" in stdout, ("mutant missing simulation", label)
            try:
                compare_results(result_path, [frames])
            except AssertionError as mismatch:
                diagnosis = str(mismatch)
                if label == "channel-ownership":
                    assert "status_checksum" in diagnosis, (
                        "wrong mutant rejection", label, diagnosis)
                    rows = [line.split() for line in result_path.read_text().splitlines()
                            if line.startswith("FRAME ")]
                    assert len(rows) == 4, "incomplete ownership counterexample"
                    for row in rows:
                        channel = int(row[2])
                        wire = bytes.fromhex(row[8])
                        wrong_content = frames[(channel - 1) & 3].content
                        assert oracle.decode(wire[:-4]) == wrong_content
                        assert wrong_content != frames[channel].content
                        assert int(row[7], 16) == oracle.checksum(wrong_content, 1)
                    diagnosis += "; all four decoded outputs match predecessor-channel content"
                else:
                    assert observable in diagnosis, ("wrong mutant rejection", label, diagnosis)
            else:
                raise AssertionError(f"surviving mutant: {label}")
        else:
            assert observable in stdout + stderr, (
                "mutant failed without intended functional assertion", label, stdout, stderr)
            assert "CYCLE_BOUND" not in stdout + stderr, ("mutant only timed out", label)
            diagnosis = next(line for line in (stdout + stderr).splitlines()
                             if observable in line)
        record = {"defect": label, "compiled": True, "detected": True,
                  "intended_observable": observable, "observed_mismatch": diagnosis,
                  "functional_exit": child["exit"],
                  "functional_stdout": child["stdout"], "functional_stderr": child["stderr"],
                  "diff": run.relative(directory / "mutation.diff")}
        write_json(directory / "rejection.json", record)
        results.append(record)
    assert len(results) == (1 if only else 4)
    write_json(run.path / "mutation-summary.json", results)
