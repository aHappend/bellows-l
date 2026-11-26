"""Deterministic codec inputs shared by native CPU, FPGA, board and GPU."""

import hashlib
import json
import os
import random
import tempfile
from pathlib import Path

from oracle import compress


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def publish(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False,
                                     prefix=f"{path.name}.", suffix=".tmp") as handle:
        tmp = Path(handle.name)
        try:
            handle.write(encoded)
            handle.flush()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def _repeat(pattern, size):
    return (pattern * ((size + len(pattern) - 1) // len(pattern)))[:size]


def corpus():
    structured = b"".join(b"%04d,sensor-%02d,%03d,OK\n" % (i, i % 8, i % 13) for i in range(32))
    text = (b"A good measurement states what moved, how long it took, and what was checked. "
            b"Repeat the observation with the same input but a different schedule.\n")
    source = b"".join(b"unsigned lane_%d(unsigned x) { return x * %du + %du; }\n" % (i, i + 1, i % 5)
                      for i in range(31))
    binary = b"".join(i.to_bytes(2, "little") + b"\x00\x00\xb2\x11" + (i % 7).to_bytes(2, "big")
                      for i in range(128))
    for size in (4096, 65536):
        blocks = dict(structured=_repeat(structured, size), text=_repeat(text, size),
                      source=_repeat(source, size), binary=_repeat(binary, size),
                      repetitive=_repeat(b"ABCD", size),
                      entropy=random.Random(89 + size).randbytes(size))
        for name, raw in blocks.items():
            yield f"{name}_{size}", raw, compress(raw)


def describe(name, raw, encoded):
    return {"id": name, "input_bytes": len(raw), "input_sha256": sha256(raw),
            "common_decode_bytes": len(encoded), "common_decode_sha256": sha256(encoded)}
