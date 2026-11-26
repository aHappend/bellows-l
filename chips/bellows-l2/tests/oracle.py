"""Byte-oriented raw LZ4 reference and frozen publication reader."""

import json
from pathlib import Path


def _extension(count):
    quot, rem = divmod(count - 15, 255)
    return b"\xff" * quot + bytes([rem])


def sequence(literals, distance=None, match=0):
    m = match - 4 if distance is not None else 0
    n = len(literals)
    return (
        bytes([(min(n, 15) << 4) | min(m, 15)])
        + (_extension(n) if n >= 15 else b"")
        + literals
        + (distance.to_bytes(2, "little") if distance is not None else b"")
        + (_extension(m) if m >= 15 else b"")
    )


def compress(raw):
    def rol(byte, shift):
        return ((byte << shift) | (byte >> (8 - shift))) & 255

    latest = {}
    p = anchor = 0
    out = bytearray()
    while p <= len(raw) - 12:
        word = raw[p:p + 4]
        a, b, c, d = word
        key = a ^ rol(b, 1) ^ rol(c, 2) ^ rol(d, 3)
        previous = latest.get(key)
        latest[key] = p
        if previous is None or not 1 <= p - previous <= 65535 or raw[previous:previous + 4] != word:
            p += 1
            continue
        end = p + 4
        while end < len(raw) - 5 and raw[end] == raw[previous + end - p]:
            end += 1
        out += sequence(raw[anchor:p], p - previous, end - p)
        p = anchor = end
    out += sequence(raw[anchor:])
    literal = sequence(raw)
    return bytes(out) if len(out) < len(literal) else literal


def decode(encoded):
    """Return the valid decoded prefix and the external decoder status."""
    i = 0
    out = bytearray()

    def length(n, saturated):
        nonlocal i
        if not saturated:
            return n, 0
        while i < len(encoded):
            part = encoded[i]
            i += 1
            n += part
            if i == len(encoded):
                return n, 1
            if n > 0xffffffff:
                return n, 4
            if part != 255:
                return n, 0
        return n, 1

    while i < len(encoded):
        token = encoded[i]
        i += 1
        literals, error = length(token >> 4, token >> 4 == 15)
        if error:
            return bytes(out), error
        literal_end = i + literals
        out.extend(encoded[i:literal_end])
        if literal_end >= len(encoded):
            return bytes(out), int(literal_end != len(encoded))
        i = literal_end
        if i + 2 >= len(encoded):
            return bytes(out), 1
        distance = int.from_bytes(encoded[i:i + 2], "little")
        i += 2
        if distance == 0:
            return bytes(out), 2
        if distance > len(out):
            return bytes(out), 3
        n, error = length(4 + (token & 15), token & 15 == 15)
        if error:
            return bytes(out), error
        pattern = out[-distance:]
        repeats, tail = divmod(n, distance)
        out.extend(pattern * repeats + pattern[:tail])
    return bytes(out), 1


def role(mode, raw, capacity):
    if mode == 0:
        output, error = compress(raw), 0
    elif mode == 1:
        if not raw:
            return b"", 1
        output, error = decode(raw)
    elif mode == 2:
        output, error = decode(compress(raw))
    else:
        raise ValueError(f"Unknown role mode {mode}")
    return output[:capacity], 4 if len(output) > capacity else 32 + error if error else 0


def _patterns(row, fields):
    if row.keys() != fields.keys() or any(
        type(row[name]) is not int or not 0 <= row[name] < 2**width
        for name, width in fields.items()
    ):
        raise ValueError(f"Invalid unsigned oracle signals: {row}")


def _unpack(row, prefix):
    return b"".join(row[f"{prefix}_w{i}"].to_bytes(4, "little") for i in range(4))


def frozen(path):
    doc = json.loads(Path(path).read_bytes())
    ids = {"compress_overlap", "decode_external", "roundtrip_distinct", "compress_empty", "decode_truncated"}
    if doc["schema"] != "vulcan-black-box-vectors/v1" or doc["cases"].keys() != ids:
        raise ValueError("Frozen publication must contain the five admitted cases")
    cases = {}
    for name, case in doc["cases"].items():
        inp, gold = case["inputs"], case["expected"]
        _patterns(inp, dict(mode=2, input_length=5, output_capacity=5,
                            **{f"input_w{i}": 32 for i in range(4)}))
        _patterns(gold, dict(completion_code=8, output_length=5,
                             **{f"output_w{i}": 32 for i in range(4)}))
        size, capacity = inp["input_length"], inp["output_capacity"]
        packed = _unpack(gold, "output")
        length = gold["output_length"]
        if not 0 <= length <= capacity <= 16 or size > 16 or any(packed[length:]):
            raise ValueError(f"{name}: invalid oracle byte length or padding")
        raw = _unpack(inp, "input")[:size]
        expected = (packed[:length], gold["completion_code"])
        if role(inp["mode"], raw, capacity) != expected:
            raise ValueError(f"{name}: frozen answer disagrees with independent codec")
        cases[name] = (inp["mode"], raw, capacity, *expected)
    return cases
