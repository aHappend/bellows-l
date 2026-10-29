"""Exclusive source-bound run directories and retained subprocess receipts."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sources(root):
    paths = sorted([*root.glob("rtl/*.sv"), *root.glob("tests/*.py"),
                    root / "design/SPEC.md", root / "design/ARCHITECTURE.md"])
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


class Run:
    def __init__(self, root, out_root, label, argv, repair_of=None):
        self.root = Path(root).resolve()
        out_root = Path(out_root)
        if out_root.is_absolute() or ".." in out_root.parts:
            raise ValueError("--out-root must be project-relative")
        parent = self.root / out_root
        parent.mkdir(parents=True, exist_ok=True)
        name = (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
                "-" + label + "-" + uuid.uuid4().hex[:8])
        self.path = parent / name
        self.path.mkdir()
        self.receipt = {
            "argv": argv, "cwd": ".", "start": stamp(), "end": None,
            "source_hashes": sources(self.root), "exit": None,
            "timed_out": False, "commands": [], "repair_of": repair_of,
            "stdout": self.relative(self.path / "stdout.txt"),
            "stderr": self.relative(self.path / "stderr.txt"),
        }
        (self.path / "stdout.txt").touch()
        (self.path / "stderr.txt").touch()
        self.save()

    def relative(self, path):
        return str(Path(path).relative_to(self.root))

    def save(self):
        write_json(self.path / "receipt.json", self.receipt)

    def tool(self, tool):
        if shutil.which(tool) is None:
            raise RuntimeError(f"missing required tool: {tool}")
        version_args = {"iverilog": ["-V"], "vvp": ["-V"],
                        "yosys": ["-V"], "verilator": ["--version"],
                        "g++": ["--version"], "make": ["--version"]}
        self.command([tool, *version_args[tool]], f"version-{tool}", timeout=3600)

    def command(self, argv, label, timeout=3600, expected=(0,), cwd=None):
        directory = self.path / f"{len(self.receipt['commands']):03d}-{label}"
        directory.mkdir()
        stdout, stderr = directory / "stdout.txt", directory / "stderr.txt"
        record = {"argv": [str(x) for x in argv],
                  "cwd": "." if cwd is None else self.relative(cwd),
                  "start": stamp(), "timeout_s": timeout,
                  "stdout": self.relative(stdout), "stderr": self.relative(stderr),
                  "exit": None, "timed_out": False}
        self.receipt["commands"].append(record)
        self.save()
        start = time.monotonic()
        process = None
        try:
            with stdout.open("wb") as out, stderr.open("wb") as err:
                process = subprocess.Popen(record["argv"], cwd=cwd or self.root,
                                           stdout=out, stderr=err, start_new_session=True)
                try:
                    record["exit"] = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    os.killpg(process.pid, 15)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, 9)
                        process.wait()
                    record["exit"] = process.returncode
        finally:
            record["end"] = stamp()
            record["duration_s"] = time.monotonic() - start
            self.save()
        if record["timed_out"] or record["exit"] not in expected:
            raise RuntimeError(f"{label}: exit={record['exit']} "
                               f"timeout={record['timed_out']}; "
                               f"see {record['stdout']} and {record['stderr']}")
        return stdout.read_text(errors="replace"), stderr.read_text(errors="replace")

    def finish(self, error=None):
        self.receipt["end"] = stamp()
        self.receipt["exit"] = 1 if error else 0
        if error:
            self.receipt["error"] = str(error)
            (self.path / "stderr.txt").write_text(str(error) + "\n")
        self.save()
