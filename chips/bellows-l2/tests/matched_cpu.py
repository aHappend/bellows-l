"""Native liblz4 baseline against the common raw-LZ4 corpus."""

import ctypes
import ctypes.util
import os
import platform
from pathlib import Path
import statistics
import time

from matched_workload import corpus, describe, publish
from oracle import decode


def native_lz4():
    soname = ctypes.util.find_library("lz4")
    if not soname:
        raise RuntimeError("The matched CPU benchmark requires native liblz4")
    lib = ctypes.CDLL(soname)
    lib.LZ4_versionString.restype = ctypes.c_char_p
    lib.LZ4_compressBound.argtypes = [ctypes.c_int]
    for fn in (lib.LZ4_compress_default, lib.LZ4_decompress_safe):
        fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        fn.restype = ctypes.c_int
    return lib


def measure(fn, source, destination, n, capacity, expected_size):
    repeats = 7
    calls = max(128, (16 * 1024**2) // max(n, capacity))
    elapsed = []
    for _ in range(repeats):
        begin = time.perf_counter_ns()
        for _ in range(calls):
            count = fn(source, destination, n, capacity)
        duration_ns = time.perf_counter_ns() - begin
        if count != expected_size:
            raise RuntimeError(f"Unstable liblz4 result length: {count} != {expected_size}")
        elapsed.append(duration_ns / calls)
    return {"iterations_per_sample": calls, "ns_per_block_samples": elapsed,
            "median_ns_per_block": statistics.median(elapsed)}


def main():
    lib = native_lz4()
    encode = lib.LZ4_compress_default
    decompress = lib.LZ4_decompress_safe
    rows = []
    for name, raw, encoded in corpus():
        n = len(raw)
        source = ctypes.create_string_buffer(raw)
        common = ctypes.create_string_buffer(encoded)
        compressed = ctypes.create_string_buffer(lib.LZ4_compressBound(n))
        recovered = ctypes.create_string_buffer(n)
        actual = encode(source, compressed, n, len(compressed))
        if not 0 < actual <= len(compressed) or decode(compressed.raw[:actual]) != (raw, 0):
            raise RuntimeError(f"{name}: independent cross-decode of liblz4 output failed")
        native_block = ctypes.create_string_buffer(compressed.raw[:actual])
        for block, length in ((common, len(encoded)), (native_block, actual)):
            if decompress(block, recovered, length, n) != n or recovered.raw != raw:
                raise RuntimeError(f"{name}: liblz4 recovery failed")
        enc = measure(encode, source, compressed, n, len(compressed), actual)
        dec = measure(decompress, common, recovered, len(encoded), n, n)
        if recovered.raw != raw or compressed.raw[:actual] != native_block.raw[:actual]:
            raise RuntimeError(f"{name}: timed benchmark produced different bytes")
        for metrics in (enc, dec):
            metrics["uncompressed_bytes_per_second"] = n * 1e9 / metrics["median_ns_per_block"]
        rows.append(dict(describe(name, raw, encoded), native_encoded_bytes=actual,
                         native_compression_ratio=actual / n, common_compression_ratio=len(encoded) / n,
                         encode=enc, decode_common=dec))
    cpu_info = Path("/proc/cpuinfo").read_text().splitlines()
    model = next((line.partition(":")[2].strip() for line in cpu_info if line.startswith("model name")),
                 platform.machine())
    publish("evidence/matched_cpu.json", {
        "schema": "bellows-l2-matched-cpu/v1",
        "liblz4": {"library": lib._name, "version": lib.LZ4_versionString().decode("ascii")},
        "platform": platform.platform(),
        "cpu_model": model,
        "runtime_cpu_affinity": sorted(os.sched_getaffinity(0)),
        "timing_scope": "single CPU thread, native liblz4 calls including ctypes dispatch, buffers preallocated",
        "blocks": rows,
    })


if __name__ == "__main__":
    main()
