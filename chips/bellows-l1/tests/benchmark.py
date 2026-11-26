#!/usr/bin/env python3
"""Reproduce the matched native Bellows-L1 CPU and GPU raw-block baselines."""

import argparse
import csv
import ctypes
import ctypes.util
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import struct
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
PINNED_NVCC = Path("/usr/local/cuda-12.8/bin/nvcc")
HEADER = struct.Struct("<BBQQ")
UUID = re.compile(r"GPU-[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}")

CUDA = r"""
#include <cuda_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <vector>

#define CUDA(call) do { cudaError_t e = (call); if (e != cudaSuccess) \
  throw std::runtime_error(std::string(#call) + ": " + cudaGetErrorString(e)); } while (0)

struct Row { int in_at, in_size, out_at, out_size; };

__device__ int length(const unsigned char *src, int &read, int n, int base) {
    if (base != 15) return base;
    for (int v = 255; v == 255;) {
        if (read >= n) return -1;
        v = src[read++];
        base += v;
    }
    return base;
}

__device__ int decode(const unsigned char *src, int n, unsigned char *dst, int cap) {
    int read = 0, out = 0;
    while (read < n) {
        unsigned token = src[read++];
        int lit = length(src, read, n, token >> 4);
        if (lit < 0 || lit > n-read || lit > cap-out) return -1;
        for (int i = 0; i < lit; ++i) dst[out++] = src[read++];
        if (read == n) return out;
        if (n-read < 2) return -2;
        unsigned off = src[read] | (unsigned(src[read+1]) << 8);
        read += 2;
        if (off == 0 || off > unsigned(out)) return -3;
        int len = length(src, read, n, token & 15);
        if (len < 0 || len + 4 > cap-out) return -4;
        for (int i = 0; i < len + 4; ++i) { dst[out] = dst[out-off]; ++out; }
    }
    return -5;
}

__global__ void blocks(const Row *rows, int count, const unsigned char *src,
                       unsigned char *dst, int *sizes) {
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i < count) {
        Row r = rows[i];
        sizes[i] = decode(src + r.in_at, r.in_size, dst + r.out_at, r.out_size);
    }
}

template<typename T> T *device(size_t n) {
    T *p;
    CUDA(cudaMalloc(&p, sizeof(T)*n));
    return p;
}
template<typename T> T *pinned(size_t n) {
    T *p;
    CUDA(cudaMallocHost(&p, sizeof(T)*n));
    return p;
}

int main(int argc, char **argv) {
    try {
        if (argc != 5) throw std::runtime_error("Need pack, copies, warmups, repetitions");
        int copies = std::stoi(argv[2]), warm = std::stoi(argv[3]), reps = std::stoi(argv[4]);
        int devices, driver_version, runtime_version;
        CUDA(cudaGetDeviceCount(&devices));
        if (devices != 1) throw std::runtime_error("Exactly one admitted device must be visible");
        cudaDeviceProp property;
        CUDA(cudaGetDeviceProperties(&property, 0));
        CUDA(cudaDriverGetVersion(&driver_version));
        CUDA(cudaRuntimeGetVersion(&runtime_version));
        std::printf("DEVICE GPU-");
        for (int i = 0; i < 16; ++i) {
            if (i == 4 || i == 6 || i == 8 || i == 10) std::printf("-");
            std::printf("%02x", static_cast<unsigned char>(property.uuid.bytes[i]));
        }
        std::printf(" %d %d\n", driver_version, runtime_version);
        std::ifstream input(argv[1], std::ios::binary);
        int count;
        if (!input.read(reinterpret_cast<char*>(&count), sizeof(count)) || count < 3 || count > 32)
            throw std::runtime_error("Invalid matched batch");
        std::vector<std::vector<unsigned char>> sources(count), expected(count);
        for (int i = 0; i < count; ++i) {
            int sizes[2];
            if (!input.read(reinterpret_cast<char*>(sizes), sizeof(sizes)) ||
                sizes[0] <= 0 || sizes[0] > 65536 || sizes[1] <= 0 || sizes[1] > 65536)
                throw std::runtime_error("Invalid row header");
            sources[i].resize(sizes[0]); expected[i].resize(sizes[1]);
            if (!input.read(reinterpret_cast<char*>(sources[i].data()), sizes[0]) ||
                !input.read(reinterpret_cast<char*>(expected[i].data()), sizes[1]))
                throw std::runtime_error("Incomplete matched row");
        }
        if (input.peek() != std::char_traits<char>::eof()) throw std::runtime_error("Extra batch data");
        std::vector<Row> rows;
        int in_size = 0, out_size = 0;
        for (int j = 0; j < copies; ++j) for (int i = 0; i < count; ++i) {
            rows.push_back({in_size, int(sources[i].size()), out_size, int(expected[i].size())});
            in_size += sources[i].size(); out_size += expected[i].size();
        }
        auto h_in = pinned<unsigned char>(in_size), h_out = pinned<unsigned char>(out_size);
        auto h_sizes = pinned<int>(rows.size());
        auto d_in = device<unsigned char>(in_size), d_out = device<unsigned char>(out_size);
        auto d_sizes = device<int>(rows.size());
        auto d_rows = device<Row>(rows.size());
        for (size_t i = 0; i < rows.size(); ++i)
            std::memcpy(h_in + rows[i].in_at, sources[i%count].data(), rows[i].in_size);
        CUDA(cudaMemcpy(d_rows, rows.data(), rows.size()*sizeof(Row), cudaMemcpyHostToDevice));
        auto kernel = [&] {
            blocks<<<(rows.size()+127)/128, 128>>>(d_rows, rows.size(), d_in, d_out, d_sizes);
            CUDA(cudaGetLastError());
        };
        auto receive = [&] {
            CUDA(cudaMemcpy(h_out, d_out, out_size, cudaMemcpyDeviceToHost));
            CUDA(cudaMemcpy(h_sizes, d_sizes, rows.size()*sizeof(int), cudaMemcpyDeviceToHost));
        };
        auto transfer = [&] {
            CUDA(cudaMemcpy(d_in, h_in, in_size, cudaMemcpyHostToDevice));
            kernel();
            receive();
        };
        auto compare = [&] {
            for (size_t i = 0; i < rows.size(); ++i)
                if (h_sizes[i] != rows[i].out_size ||
                    std::memcmp(h_out + rows[i].out_at, expected[i%count].data(), rows[i].out_size))
                    throw std::runtime_error("Decoded result mismatch at batch index " + std::to_string(i));
        };
        transfer(); compare();
        std::printf("CHECKED %zu %d\n", rows.size(), out_size);
        cudaEvent_t start, stop;
        CUDA(cudaEventCreate(&start)); CUDA(cudaEventCreate(&stop));
        for (int i = -warm; i < reps; ++i) {
            CUDA(cudaEventRecord(start)); kernel(); CUDA(cudaEventRecord(stop));
            CUDA(cudaEventSynchronize(stop));
            float ms;
            CUDA(cudaEventElapsedTime(&ms, start, stop));
            if (i >= 0) std::printf("RESIDENT %.4f\n", double(ms)*1e6);
        }
        receive(); compare();
        for (int i = -warm; i < reps; ++i) {
            auto start_wall = std::chrono::steady_clock::now();
            transfer();
            auto elapsed = std::chrono::steady_clock::now() - start_wall;
            if (i >= 0) std::printf("FULL %.0f\n", std::chrono::duration<double, std::nano>(elapsed).count());
        }
        compare();
        CUDA(cudaEventDestroy(start)); CUDA(cudaEventDestroy(stop));
        CUDA(cudaFree(d_rows)); CUDA(cudaFree(d_sizes)); CUDA(cudaFree(d_out)); CUDA(cudaFree(d_in));
        CUDA(cudaFreeHost(h_sizes)); CUDA(cudaFreeHost(h_out)); CUDA(cudaFreeHost(h_in));
        return 0;
    } catch (const std::exception &e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
}
"""


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bound(entry):
    path = ROOT / entry["path"]
    require(path.is_relative_to(ROOT / "tests/board_vectors") and path.resolve(strict=True) == path,
            f"Noncanonical board vector path: {path}")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == entry["sha256"], f"Changed workload row: {path}")
    return raw


def load_workload(path):
    raw = path.read_bytes()
    manifest = json.loads(raw)
    require(manifest["schema"] == "bellows-matched-workload/v1", "Unknown matched workload schema")
    numbers = [manifest[key] for key in ("batch_copies", "warmup_repetitions", "measurement_repetitions")]
    require(all(type(n) is int for n in numbers) and 1 <= numbers[0] <= 256
            and 1 <= numbers[1] <= 20 and 5 <= numbers[2] <= 100, "Invalid benchmark bounds")
    rows = []
    for entry in manifest["rows"]:
        inp = json.loads(bound(entry["input"]))["inputs"]
        source = bytes.fromhex(inp["compressed_hex"])
        raw_expected = bound(entry["expected"])
        expected = raw_expected[HEADER.size:]
        require(0 < len(source) <= 65536 and 256 <= len(expected) <= 65536
                and HEADER.unpack_from(raw_expected) == (0, 0, len(source), len(expected))
                and inp["capacity"] >= len(expected) and inp["core_status"] == 0
                and inp["output_bytes"] == len(expected) and inp["expected_sha256"] == entry["expected"]["sha256"],
                f"Invalid matched row {entry['id']}")
        rows.append((entry["id"], source, expected))
    require(3 <= len(rows) <= 32 and len({row[0] for row in rows}) == len(rows)
            and min(len(row[2]) for row in rows) == 256 and max(len(row[2]) for row in rows) == 65536
            and any(len(source) >= len(expected) for _, source, expected in rows)
            and any(len(source)*4 < len(expected) for _, source, expected in rows), "Matched workload coverage differs")
    return rows, numbers, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                           "ordered_rows": manifest["rows"]}


def measurements(values, decoded, boundary):
    require(len(values) >= 5 and all(math.isfinite(x) and x > 0 for x in values), "Invalid timing data")
    ordered = sorted(values)
    median = statistics.median(values)
    return {"boundary": boundary, "batch_latency_ns": values, "median_ns": median,
            "p95_ns": ordered[math.ceil(0.95 * len(values)) - 1], "min_ns": ordered[0],
            "decoded_bytes_per_s_at_median": decoded * 1e9 / median}


def inventory(selector=None):
    fields = ("index", "uuid", "name", "driver_version", "compute_cap")
    command = ["nvidia-smi", "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"]
    if selector:
        command.extend(("-i", selector))
    run = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    rows = []
    if run.returncode == 0:
        for line in csv.reader(run.stdout.splitlines(), skipinitialspace=True):
            require(len(line) == len(fields) and UUID.fullmatch(line[1]), f"Invalid GPU inventory row: {line}")
            rows.append(dict(zip(fields, line)))
    return {"argv": command, "exit": run.returncode, "stdout": run.stdout, "stderr": run.stderr, "gpus": rows}


def cpu(rows, counts):
    copies, warmups, reps = counts
    affinity = os.sched_getaffinity(0)
    selected = min(affinity)
    os.sched_setaffinity(0, {selected})
    try:
        library_name = ctypes.util.find_library("lz4")
        require(library_name is not None, "liblz4 is unavailable")
        lib = ctypes.CDLL(library_name)
        func = lib.LZ4_decompress_safe
        func.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        func.restype = ctypes.c_int
        lib.LZ4_versionString.restype = ctypes.c_char_p
        paths = {Path(line.split()[-1]) for line in Path("/proc/self/maps").read_text().splitlines()
                 if "/liblz4.so." in line and line.split()[-1].startswith("/")}
        require(len(paths) == 1, "Could not identify loaded liblz4 path")
        library = paths.pop()
        model = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                      if line.startswith("model name")), platform.processor())
        buffers = [(name, source, expected, ctypes.create_string_buffer(source, len(source)),
                    ctypes.create_string_buffer(len(expected))) for name, source, expected in rows]

        def verify():
            for name, source, expected, inp, out in buffers:
                require(func(inp, out, len(source), len(out)) == len(out) and out.raw == expected,
                        f"liblz4 pre/post-timing comparison failed: {name}")

        def run(full):
            for _ in range(copies):
                for name, source, expected, inp, out in buffers:
                    if full:
                        inp = ctypes.create_string_buffer(source, len(source))
                        out = ctypes.create_string_buffer(len(expected))
                    if func(inp, out, len(source), len(out)) != len(out):
                        raise ValueError(f"liblz4 timed length mismatch: {name}")
                    if full:
                        host_result = out.raw
            return host_result if full else None

        verify()
        for name, source, expected, _, _ in buffers:
            inp = ctypes.create_string_buffer(source, len(source))
            out = ctypes.create_string_buffer(len(expected))
            require(func(inp, out, len(source), len(out)) == len(out) and out.raw == expected,
                    f"CPU full path output materialization mismatch: {name}")
        values = []
        for full in (False, True):
            samples = []
            for i in range(-warmups, reps):
                start = time.perf_counter_ns()
                run(full)
                elapsed = time.perf_counter_ns() - start
                if i >= 0:
                    samples.append(elapsed)
            values.append(samples)
        verify()
        decoded = sum(len(row[2]) for row in rows) * copies
        return {"device": {"os_cpu": selected, "model": model, "threads": 1, "platform": platform.platform()},
                "liblz4": {"path": str(library), "sha256": sha(library),
                           "version": lib.LZ4_versionString().decode("ascii")},
                "resident": measurements(values[0], decoded, "Host wall: liblz4 calls over resident buffers; includes Python/FFI dispatch."),
                "full": measurements(values[1], decoded, "Host wall: buffer allocation, input copy, liblz4 dispatch, output materialization.")}
    finally:
        os.sched_setaffinity(0, affinity)


def gpu(rows, counts, nvcc, destination):
    from vulcan_agent.compute_resources import CONTEXT, inherited

    locator = os.environ.get(CONTEXT)
    require(locator is not None, "CUDA requires the original active Vulcan compute lease")
    lease_root = next((p.parent for p in Path(locator).parents if p.name == ".vulcan"), ROOT)
    lease = inherited(lease_root)
    require(lease is not None, "CUDA requires the original active Vulcan compute lease")
    require(ROOT in (lease_root, Path(lease["owner"]["execution_folder"]) / "workspace"),
            "CUDA workload is outside the leased project and its execution workspace")
    contract = lease["contract"]
    uuid = contract["gpu_uuid"]
    require(isinstance(uuid, str) and UUID.fullmatch(uuid) and contract["cpu_threads"] == 2
            and os.environ.get("CUDA_VISIBLE_DEVICES") == uuid, "CUDA runtime grant is not the selected GPU")
    require(nvcc == PINNED_NVCC and nvcc.is_file(), f"CUDA compiler must be {PINNED_NVCC}")
    local_inventory = inventory(uuid)
    require(len(local_inventory["gpus"]) == 1 and local_inventory["gpus"][0]["uuid"] == uuid,
            "Admitted GPU UUID is no longer visible")
    selected = local_inventory["gpus"][0]
    require(re.fullmatch(r"\d\.\d", selected["compute_cap"]), "Invalid admitted compute capability")
    arch = selected["compute_cap"].replace(".", "")
    work = Path(tempfile.mkdtemp(prefix="bellows-cuda-", dir=destination))
    source, binary, pack = work / "baseline.cu", work / "baseline", work / "batch.bin"
    source.write_text(CUDA, encoding="ascii")
    with pack.open("xb") as stream:
        stream.write(struct.pack("<i", len(rows)))
        for _, compressed, expected in rows:
            stream.write(struct.pack("<ii", len(compressed), len(expected)))
            stream.write(compressed)
            stream.write(expected)
    compile_argv = [str(nvcc), "-std=c++14", "-O3", f"-arch=sm_{arch}", str(source), "-o", str(binary)]
    source_hash = sha(source)
    compiler_hash = sha(nvcc)
    version = subprocess.check_output([str(nvcc), "--version"], text=True, timeout=20).strip()
    with (work / "compile.log").open("xb") as log:
        compiled = subprocess.run(compile_argv, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=False)
    require(compiled.returncode == 0 and sha(nvcc) == compiler_hash and sha(source) == source_hash,
            f"CUDA compilation failed or inputs changed; see {work}/compile.log")
    run_argv = [str(binary), str(pack), *map(str, counts)]
    with (work / "stdout.log").open("xb") as out, (work / "stderr.log").open("xb") as err:
        run = subprocess.run(run_argv, stdout=out, stderr=err, timeout=720, check=False)
    require(run.returncode == 0, f"CUDA verification/timing failed; see {work}/stderr.log")
    output = (work / "stdout.log").read_text(encoding="ascii")
    device = re.search(r"^DEVICE (\S+) (\d+) (\d+)$", output, re.M)
    require(device is not None and device[1] == uuid, "CUDA-reported device UUID differs from lease")
    decoded = sum(len(row[2]) for row in rows) * counts[0]
    checked = re.search(r"^CHECKED (\d+) (\d+)$", output, re.M)
    require(checked is not None and (int(checked[1]), int(checked[2])) == (len(rows)*counts[0], decoded),
            "Matched CUDA correctness proof missing")
    timings = {}
    for label, description in (
        ("RESIDENT", "CUDA events: batched kernel on resident device data; excludes host dispatch and transfers."),
        ("FULL", "Host wall: pinned H2D data copy, kernel dispatch, synchronized decoded bytes and lengths D2H."),
    ):
        values = [float(s) for s in re.findall(rf"^{label} ([0-9.]+)$", output, re.M)]
        require(len(values) == counts[2], f"Missing CUDA {label} repetitions")
        timings[label.lower()] = measurements(values, decoded, description)
    return {**timings, "device": {**selected, "cuda_driver": int(device[2]), "cuda_runtime": int(device[3])},
            "compute_lease_id": lease["id"], "compiler": {"path": str(nvcc), "sha256": compiler_hash,
            "version": version, "argv": compile_argv, "exit": compiled.returncode},
            "execution": {"argv": run_argv, "exit": run.returncode, "scratch": str(work),
                          "source_sha256": source_hash, "binary_sha256": sha(binary), "batch_sha256": sha(pack)}}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument("--backend", choices=("inventory", "cpu", "gpu"), required=True)
    parser.add_argument("--nvcc", type=Path)
    parser.add_argument("--workload", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if (args.backend == "inventory") != (args.workload is None) or (args.backend == "gpu") != (args.nvcc is not None):
        parser.error("Use --workload for cpu/gpu and --nvcc only for gpu")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result = {"schema": "bellows-matched-baseline/v1", "backend": args.backend, "argv": sys.argv,
              "engineering_acceptance": False, "source_sha256": sha(Path(__file__))}
    try:
        if args.backend == "inventory":
            result["inventory"] = inventory()
            require(result["inventory"]["gpus"], "No GPU UUID visible; inspect retained inventory")
        else:
            rows, counts, binding = load_workload(args.workload)
            result.update(workload=binding, batch_copies=counts[0], warmup_repetitions=counts[1],
                          measurement_repetitions=counts[2], blocks_per_batch=len(rows)*counts[0],
                          decoded_bytes_per_batch=sum(len(row[2]) for row in rows)*counts[0])
            result["measurement"] = cpu(rows, counts) if args.backend == "cpu" else gpu(
                rows, counts, args.nvcc, args.report.parent.resolve())
        result["status"] = "passed"
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.SubprocessError) as exc:
        result.update(status="failed", detail=str(exc))
        print(str(exc), file=sys.stderr)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
