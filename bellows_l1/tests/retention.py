"""Fresh source-bound execution directories; failures are retained, never reused."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid


SOURCES = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md", "tests/*.py")


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    # All evidence paths are freshly allocated by this invocation.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def source_files(root: Path) -> list[Path]:
    files = sorted({p for selector in SOURCES for p in root.glob(selector)})
    for selector in SOURCES:
        if not list(root.glob(selector)):
            raise RuntimeError(f"required source selector is empty: {selector}")
    return files


class Run:
    def __init__(self, root: Path, *, preparation: bool, repair_of: str | None):
        self.root = root
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        category = "preparation" if preparation else "l1"
        self.path = root / "evidence" / category / (stamp + "-" + uuid.uuid4().hex[:12])
        self.path.mkdir(parents=True, exist_ok=False)
        self.record = {
            "kind": "advisory-preparation" if preparation else "portable-l1",
            "start_time": utc(), "cwd": ".", "timeout_s": 86400,
            "repair_of": repair_of, "commands": [], "tool_versions": {},
            "source_sha256": {},
        }
        for file in source_files(root):
            relative = file.relative_to(root)
            target = self.path / "sources" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
            self.record["source_sha256"][relative.as_posix()] = digest(target)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def source_changes(self) -> dict:
        current = {
            p.relative_to(self.root).as_posix(): digest(p)
            for selector in SOURCES for p in self.root.glob(selector)
            if p.is_file()
        }
        expected = self.record["source_sha256"]
        return {
            name: {"expected": expected.get(name), "observed": current.get(name)}
            for name in sorted(expected.keys() | current.keys())
            if expected.get(name) != current.get(name)
        }

    def assert_sources_unchanged(self) -> None:
        changes = self.source_changes()
        if changes:
            raise RuntimeError("verification inputs changed during execution: "
                               + json.dumps(changes, sort_keys=True))

    def command(self, argv: list[str], name: str, *, cwd: Path | None = None,
                timeout: int = 14400, require_success: bool = True,
                env: dict | None = None) -> dict:
        if timeout < 3600:
            raise ValueError("child operational deadlines must be at least 3600s")
        self.assert_sources_unchanged()
        cwd = self.root if cwd is None else cwd
        folder = self.path / name
        folder.mkdir(parents=True, exist_ok=False)
        stdout, stderr = folder / "stdout.log", folder / "stderr.log"
        record = {
            "argv": argv, "cwd": self.relative(cwd), "timeout_s": timeout,
            "start_time": utc(), "stdout": self.relative(stdout),
            "stderr": self.relative(stderr), "timed_out": False,
            "source_sha256": self.record["source_sha256"],
            "file_arguments_sha256": {
                arg: digest(cwd / arg) for arg in argv[1:]
                if not arg.startswith("-") and (cwd / arg).is_file()
            },
            "tool_version": self.record["tool_versions"].get(
                argv[0], {"kind": "version-query", "argv": argv}
            ),
            "environment_policy": "clean-python-imports" if env is not None else "inherited",
        }
        start = time.monotonic()
        try:
            with stdout.open("xb") as out, stderr.open("xb") as err:
                result = subprocess.run(
                    argv, cwd=cwd, stdout=out, stderr=err,
                    timeout=timeout, check=False, env=env,
                )
                record["exit_status"] = result.returncode
        except subprocess.TimeoutExpired:
            record["timed_out"] = True
            record["exit_status"] = None
        except OSError as error:
            record["exit_status"] = None
            record["launch_error"] = str(error)
        record["end_time"] = utc()
        record["elapsed_s"] = time.monotonic() - start
        record["source_changes"] = self.source_changes()
        write_json(folder / "receipt.json", record)
        self.record["commands"].append(self.relative(folder / "receipt.json"))
        if record["source_changes"]:
            raise RuntimeError("verification inputs changed during execution: "
                               + json.dumps(record["source_changes"], sort_keys=True))
        if require_success and record["exit_status"] != 0:
            raise RuntimeError(f"tool execution failed: {self.relative(folder / 'receipt.json')}")
        return record

    def versions(self) -> None:
        for tool, flag in (("python3", "--version"), ("iverilog", "-V"),
                           ("vvp", "-V"), ("yosys", "-V")):
            if shutil.which(tool) is None:
                raise RuntimeError(f"missing required tool: {tool}; no installation attempted")
            receipt = self.command([tool, flag], "versions/" + tool)
            self.record["tool_versions"][tool] = {
                key: receipt[key] for key in ("argv", "stdout", "stderr", "exit_status")
            }

    def finish(self, code: int, error: str | None = None, *,
               stdout: str = "", stderr: str = "") -> None:
        self.record["source_changes"] = self.source_changes()
        if code == 0:
            self.assert_sources_unchanged()
        out, err = self.path / "stdout.log", self.path / "stderr.log"
        with out.open("x", encoding="utf-8") as stream:
            stream.write(stdout)
        with err.open("x", encoding="utf-8") as stream:
            stream.write(stderr)
        self.record["stdout"] = self.relative(out)
        self.record["stderr"] = self.relative(err)
        self.record.update(end_time=utc(), exit_status=code, error=error)
        write_json(self.path / "receipt.json", self.record)


def clean_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
