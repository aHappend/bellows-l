"""V100 raw-LZ4 baseline against the native CPU benchmark's shared corpus."""

import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
from matched_workload import corpus, describe, publish, sha256
from oracle import decode


NVCC = Path("/usr/local/cuda-12.8/bin/nvcc")
INPUTS = ("tests/matched_gpu.py", "tests/matched_gpu.cu", "tests/matched_workload.py", "tests/oracle.py")
UUID = re.compile(r"GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
OUTPUT = "evidence/matched_gpu.json"


def managed_binding():
    locator = os.environ.get("VULCAN_COMPUTE_RESOURCE_CONTEXT")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if not locator or not visible or not UUID.fullmatch(visible):
        raise RuntimeError("matched_gpu requires Runtime's admitted compute context and one leased GPU UUID")
    path = Path(locator)
    if not path.is_absolute() or path.name != "compute-resources.json":
        raise RuntimeError(f"Invalid managed compute context path: {path}")
    encoded = path.read_bytes()
    grant = json.loads(encoded)
    project = Path(grant["project"])
    owner_folder = Path(grant["owner"]["execution_folder"])
    if (path.parent != owner_folder or not owner_folder.is_relative_to(project)
            or Path.cwd() not in (project, owner_folder / "workspace")
            or grant["contract"]["gpu_uuid"] != visible):
        raise RuntimeError("CUDA_VISIBLE_DEVICES or the check workspace does not match the Runtime grant")
    return {"gpu_uuid": visible, "grant_id": grant["id"], "check_sha256": grant["check_sha256"],
            "context_sha256": sha256(encoded)}


def execution_budget():
    limit = float(os.environ.get("VULCAN_PATROL_CHECK_TIMEOUT_S", "3600"))
    if not math.isfinite(limit) or limit <= 0:
        raise RuntimeError("Invalid Runtime check timeout for matched_gpu")
    if outer := os.environ.get("VULCAN_EXECUTION_DEADLINE"):
        remaining = float(outer) - time.time()
        if not math.isfinite(remaining) or remaining <= 0:
            raise RuntimeError("No positive Runtime time budget for matched_gpu")
        limit = min(limit, remaining)
    return time.monotonic() + limit / 2


def run(argv, deadline):
    remaining = deadline - time.monotonic()
    command = shlex.join(argv)
    if remaining <= 0:
        raise RuntimeError(f"matched_gpu exhausted its execution budget before {command}")
    result = subprocess.run(argv, capture_output=True, text=True, timeout=remaining)
    if result.returncode:
        raise RuntimeError(f"{command} exited {result.returncode}\n{result.stderr}\n{result.stdout}")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.stdout


def tool_identity(executable, deadline):
    path = Path(executable).resolve(strict=True)
    return {"path": str(executable), "resolved_path": str(path),
            "sha256": sha256(path.read_bytes()),
            "version": run([str(executable), "--version"], deadline).strip()}


def metrics(samples_ms, batch, raw_size):
    if (len(samples_ms) != 7 or any(type(ms) not in (float, int) or
                                  not math.isfinite(ms) or ms <= 0 for ms in samples_ms)):
        raise ValueError(f"Invalid CUDA timing samples for batch size {batch}: {samples_ms}")
    samples = [ms * 1e6 for ms in samples_ms]
    median = statistics.median(samples)
    return {"batch_latency_ns_samples": samples, "median_batch_latency_ns": median,
            "amortized_ns_per_block": median / batch,
            "uncompressed_bytes_per_second": batch * raw_size * 1e9 / median}


def summarize(operation, raw, logical_input, logical_output, output_capacity):
    if [row["batch_size"] for row in operation] != [1, 1024]:
        raise ValueError("Missing or unexpected CUDA batch sizes")
    rows = []
    for row in operation:
        batch = row["batch_size"]
        if (row["h2d_bytes_per_batch"] != logical_input * batch
                or row["d2h_bytes_per_batch"] != (output_capacity + 4) * batch):
            raise ValueError(f"Incorrect CUDA transfer byte counts for batch size {batch}")
        rows.append({"batch_size": batch, "logical_input_bytes_per_block": logical_input,
                     "logical_output_bytes_per_block": logical_output,
                     "h2d_bytes_per_batch": row["h2d_bytes_per_batch"],
                     "d2h_bytes_per_batch": row["d2h_bytes_per_batch"],
                     "kernel_only": metrics(row["kernel_only_ms"], batch, raw),
                     "transfer_inclusive": metrics(row["transfer_inclusive_ms"], batch, raw)})
    return rows


def verify_results(result, binding, blocks, scratch):
    if result["device"]["gpu_uuid"] != binding["gpu_uuid"]:
        raise RuntimeError("Measured CUDA device does not match Runtime's lease")
    if [row["id"] for row in result["blocks"]] != [name for name, _, _ in blocks]:
        raise RuntimeError("CUDA measurements do not cover the shared corpus in full")
    rows = []
    for (name, raw, common), measured in zip(blocks, result["blocks"], strict=True):
        encoded = (scratch / name / "gpu.lz4").read_bytes()
        n = len(raw)
        bound = n + n // 255 + 16
        if not 0 < len(encoded) <= bound or decode(encoded) != (raw, 0):
            raise RuntimeError(f"{name}: independent oracle cannot recover the input from CUDA output")
        rows.append(dict(
            describe(name, raw, common), gpu_encoded_bytes=len(encoded),
            gpu_encoded_sha256=sha256(encoded), gpu_compression_ratio=len(encoded) / n,
            common_compression_ratio=len(common) / n,
            encode=summarize(measured["encode"], n, n, len(encoded), bound),
            decode_common=summarize(measured["decode_common"], n, len(common), n, n),
        ))
    return rows


def main():
    if len(sys.argv) != 1:
        raise SystemExit("Usage: python3 tests/matched_gpu.py (Runtime-managed)")
    binding = managed_binding()
    deadline = execution_budget()
    compiler = shutil.which("c++")
    if not compiler:
        raise RuntimeError("The matched GPU benchmark requires the c++ host compiler")
    nvcc = tool_identity(NVCC, deadline)
    if not re.search(r"\brelease 12\.8,", nvcc["version"]):
        raise RuntimeError(f"Expected CUDA 12.8 at {NVCC}, got {nvcc['version']}")
    host = tool_identity(compiler, deadline)
    blocks = list(corpus())
    if (len({name for name, _, _ in blocks}) != 12 or len(blocks) != 12
            or sorted(len(raw) for _, raw, _ in blocks) != [4096] * 6 + [65536] * 6):
        raise RuntimeError("Expected the 12 admitted shared 4 KiB and 64 KiB corpus blocks")

    with tempfile.TemporaryDirectory(prefix="bellows-matched-gpu-", dir="/tmp") as work:
        scratch = Path(work)
        binary = scratch / "matched_gpu"
        compile_argv = [str(NVCC), "-std=c++17", "-O3", "-arch=sm_70", "--compiler-bindir", compiler,
                        "tests/matched_gpu.cu", "-o", str(binary)]
        run(compile_argv, deadline)
        bench_argv = [str(binary), binding["gpu_uuid"]]
        for name, raw, common in blocks:
            case = scratch / name
            case.mkdir()
            (case / "raw.bin").write_bytes(raw)
            (case / "common.lz4").write_bytes(common)
            bench_argv.append(str(case))
        measured = json.loads(run(bench_argv, deadline))
        rows = verify_results(measured, binding, blocks, scratch)
        binary_sha256 = sha256(binary.read_bytes())

    publish(OUTPUT, {
        "schema": "bellows-l2-matched-gpu/v1",
        "runtime_binding": binding,
        "runtime_cpu_affinity": sorted(os.sched_getaffinity(0)),
        "device": measured["device"],
        "tools": {"nvcc": nvcc, "host_compiler": host},
        "commands": {"check": ["python3", *sys.argv], "compile": compile_argv, "benchmark": bench_argv},
        "input_sha256": {name: sha256(Path(name).read_bytes()) for name in INPUTS},
        "benchmark_binary_sha256": binary_sha256,
        "correctness": ["exact CUDA recovery of common inputs and own encodings",
                        "independent oracle cross-decode of every CUDA encoding",
                        "byte and length checks on both timing paths"],
        "timing_scope": {
            "kernel_only": "CUDA events around one launch using resident buffers",
            "transfer_inclusive": "host wall clock for pinned H2D, launch, full output slots and "
                                  "lengths D2H, and stream synchronization; excludes allocation, "
                                  "staging, validation and file I/O",
            "batch": "one warp per raw block, identical independent blocks per corpus entry; "
                     "per-block times for large batches are amortized, not request latency",
        },
        "blocks": rows,
    })


if __name__ == "__main__":
    main()
