"""Fresh project-relative, source-bound execution and lossless retention."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def sources(root=ROOT):
    return sorted(p for pattern in ("rtl/*.sv", "design/*.md", "tests/*.py",
                                    "bellows_l3_reference/rtl/*.sv")
                  for p in root.glob(pattern))


def hashes(root=ROOT):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources(root)}


class ToolFailure(RuntimeError):
    pass


class Execution:
    def __init__(self, stem, preparation=False, repair_of=None):
        parent = ROOT / ("evidence/preparation" if preparation else "evidence")
        self.directory = parent / f"{stem}-{uuid.uuid4().hex[:16]}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.receipt = {
            "cwd": ".", "start_time": now(), "source_hashes": hashes(),
            "commands": [], "tool_versions": {}, "repair_of": repair_of,
        }
        self.save()

    def relative(self, path):
        return Path(path).relative_to(ROOT).as_posix()

    def save(self):
        (self.directory / "receipt.json").write_text(
            json.dumps(self.receipt, indent=2) + "\n"
        )

    def run(self, argv, name, *, cwd=ROOT, timeout=2700, expected_exit=0):
        stdout = self.directory / f"{name}.stdout.txt"
        stderr = self.directory / f"{name}.stderr.txt"
        command = {
            "argv": [str(a) for a in argv], "cwd": self.relative(cwd) or ".",
            "start_time": now(), "timeout_seconds": timeout,
            "stdout": self.relative(stdout), "stderr": self.relative(stderr),
        }
        self.receipt["commands"].append(command)
        self.save()
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                process = subprocess.Popen(argv, cwd=cwd, stdout=out, stderr=err)
                start = time.monotonic()
                while True:
                    try:
                        exit_code = process.wait(timeout=30)
                        break
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - start
                        print(f"progress {name}: {int(elapsed)} seconds", flush=True)
                        if elapsed >= timeout:
                            process.terminate()
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                            command["timed_out"] = True
                            exit_code = process.returncode
                            break
            except OSError as exc:
                command["launch_error"] = str(exc)
                exit_code = None
        command.update(end_time=now(), exit_code=exit_code,
                       timed_out=command.get("timed_out", False))
        self.save()
        if exit_code != expected_exit or command["timed_out"]:
            raise ToolFailure(f"{name}: exit={exit_code}; {command['stderr']}; "
                              f"{command['stdout']}")
        return stdout.read_text()

    def versions(self, tools):
        arguments = {"python3": ["--version"], "iverilog": ["-V"],
                     "vvp": ["-V"], "verilator": ["--version"], "yosys": ["-V"]}
        for tool in tools:
            text = self.run([tool, *arguments[tool]], f"version-{tool}")
            self.receipt["tool_versions"][tool] = text.splitlines()[0] if text else (
                self.directory / f"version-{tool}.stderr.txt").read_text().splitlines()[0]
        self.save()

    def finish(self, outcome, **details):
        generated = {}
        for p in self.directory.rglob("*"):
            if p.is_file() and p.suffix in (".sv", ".txt", ".ys", ".patch"):
                generated[p.relative_to(self.directory).as_posix()] = {
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "bytes": p.stat().st_size,
                }
            if p.is_file() and p.suffix in (".o", ".a", ".gch", ".d"):
                p.unlink()
        self.receipt["retained_artifacts"] = generated
        self.receipt.update(end_time=now(), outcome=outcome, **details)
        self.save()
        print(json.dumps({"outcome": outcome, "receipt":
                          self.relative(self.directory / "receipt.json"), **details}),
              flush=True)
