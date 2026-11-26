"""Independent raw-block oracle; no simulator state or DUT-generated data."""

import json
import struct
from pathlib import Path


MAX_LENGTH = (1 << 32) - 1
HEADER = struct.Struct("<BBQQ")


def decode(data):
    """Return (core status, committed prefix) for an input with an end marker."""
    cursor = 0
    result = bytearray()

    def length(base, extended):
        nonlocal cursor
        if not extended:
            return base, 0
        while cursor < len(data):
            part = data[cursor]
            cursor += 1
            if cursor == len(data):
                return base, 1
            base += part
            if base > MAX_LENGTH:
                return base, 4
            if part != 255:
                return base, 0
        return base, 1

    while cursor < len(data):
        token = data[cursor]
        cursor += 1
        literals, error = length(token >> 4, token >> 4 == 15)
        if error:
            return error, bytes(result)
        result.extend(data[cursor:cursor + min(literals, len(data) - cursor)])
        cursor += literals
        if cursor >= len(data):
            return int(cursor > len(data)), bytes(result)
        if cursor + 2 >= len(data):
            return 1, bytes(result)
        offset = int.from_bytes(data[cursor:cursor + 2], "little")
        cursor += 2
        if not offset:
            return 2, bytes(result)
        if offset > len(result):
            return 3, bytes(result)
        matches, error = length((token & 15) + 4, token & 15 == 15)
        if error:
            return error, bytes(result)
        # A match is repetition of the suffix present before that match.
        period = bytes(result[-offset:])
        whole, tail = divmod(matches, offset)
        result.extend(period * whole + period[:tail])
    return 1, bytes(result)


def sequence(literals, offset=None, matches=0):
    def ext(value):
        return b"\xff" * (value // 255) + bytes([value % 255])

    n = len(literals)
    m = matches - 4 if offset is not None else 0
    token = bytes([min(n, 15) << 4 | min(m, 15)])
    result = token + (ext(n - 15) if n >= 15 else b"") + literals
    if offset is not None:
        result += offset.to_bytes(2, "little")
        if m >= 15:
            result += ext(m - 15)
    return result


def observed_bytes(data, capacity):
    status, decoded = decode(data)
    if len(decoded) > capacity:
        raise ValueError("Board vectors must not require capacity-abort semantics")
    return HEADER.pack(status, 0, len(data), len(decoded)) + decoded


def frozen(path):
    document = json.loads(Path(path).read_bytes())
    if document["schema"] != "vulcan-black-box-vectors/v1" or not document["cases"]:
        raise ValueError("Invalid frozen oracle")
    for name, row in document["cases"].items():
        inp, out = row["inputs"], row["expected"]
        if any(type(x) is not int or x < 0 for x in (*inp.values(), *out.values())):
            raise ValueError(f"{name}: oracle fields must be unsigned integers")
        source = bytes(inp[f"in{i}"] for i in range(inp["in_len"]))
        expected = bytes(out[f"out{i}"] for i in range(out["out_len"]))
        if (out["last_count"], out["status_count"]) != (int(bool(expected)), 1):
            raise ValueError(f"{name}: oracle transaction counts differ")
        if any(out[f"out{i}"] for i in range(len(expected), 7)):
            raise ValueError(f"{name}: inactive expected bytes are nonzero")
        if decode(source) != (out["status_error"], expected):
            raise ValueError(f"{name}: frozen/independent oracle disagreement")
        yield name, source, out["status_error"], expected
