"""Independent raw LZ4 and descriptor-frame reference algorithms.

The parser operates on byte strings, not DUT state. The encoder deliberately
uses specified sequences rather than reproducing the hardware match finder.
"""

import struct
import zlib

MASK = (1 << 32) - 1
P1, P2, P3, P4, P5 = (0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D,
                      0x27D4EB2F, 0x165667B1)


def rol(value, bits):
    value &= MASK
    return ((value << bits) | (value >> (32 - bits))) & MASK


def xxh32(data):
    position = 0
    if len(data) >= 16:
        accumulators = [(P1 + P2) & MASK, P2, 0, (-P1) & MASK]
        while position + 16 <= len(data):
            words = struct.unpack_from("<4I", data, position)
            accumulators = [
                (rol(v + word * P2, 13) * P1) & MASK
                for v, word in zip(accumulators, words)
            ]
            position += 16
        h = sum(rol(v, shift) for v, shift in
                zip(accumulators, (1, 7, 12, 18))) & MASK
    else:
        h = P5
    h = (h + len(data)) & MASK
    while position + 4 <= len(data):
        word = int.from_bytes(data[position:position + 4], "little")
        h = (rol(h + word * P3, 17) * P4) & MASK
        position += 4
    for byte in data[position:]:
        h = (rol(h + byte * P5, 11) * P1) & MASK
    h ^= h >> 15
    h = (h * P2) & MASK
    h ^= h >> 13
    h = (h * P3) & MASK
    return h ^ (h >> 16)


def checksum(data, mode):
    if mode == 0:
        return 0
    if mode == 1:
        return xxh32(data)
    if mode == 2:
        return zlib.crc32(data)
    raise ValueError("invalid checksum mode")


class LZ4Error(ValueError):
    def __init__(self, code, output):
        super().__init__(f"LZ4 error {code} after {len(output)} bytes")
        self.code = code
        self.output = bytes(output)


def decode(block, limit=None):
    """Parse the frozen parent's terminal-byte raw-block convention."""
    cursor, output = 0, bytearray()

    def fail(code):
        raise LZ4Error(code, output)

    def extension(base):
        nonlocal cursor
        length = base
        while True:
            if cursor >= len(block) - 1:
                fail(1)
            byte = block[cursor]
            cursor += 1
            length += byte
            if length > MASK:
                fail(4)
            if byte != 255:
                return length

    def emit(byte):
        if limit is not None and len(output) >= limit:
            fail(5)
        output.append(byte)

    if not block:
        fail(1)
    while cursor < len(block):
        token = block[cursor]
        cursor += 1
        literals = token >> 4
        if cursor == len(block):
            if literals:
                fail(1)
            return bytes(output)
        if literals == 15:
            literals = extension(15)
        for i in range(literals):
            if cursor == len(block):
                fail(1)
            emit(block[cursor])
            cursor += 1
            if cursor == len(block):
                if i != literals - 1:
                    fail(1)
                return bytes(output)
        if cursor + 2 >= len(block):
            fail(1)
        offset = int.from_bytes(block[cursor:cursor + 2], "little")
        cursor += 2
        if offset == 0:
            fail(2)
        if offset > min(len(output), 65536):
            fail(3)
        match = (token & 15) + 4
        if token & 15 == 15:
            match = extension(19)
        for _ in range(match):
            emit(output[-offset])
    fail(1)


def ext(length):
    return bytes([255] * (length // 255) + [length % 255])


def literals(content):
    length = len(content)
    return (bytes([min(length, 15) << 4]) +
            (ext(length - 15) if length >= 15 else b"") + content)


def sequence(literal, offset, match_length):
    if not 1 <= offset <= 65535 or match_length < 4:
        raise ValueError("illegal match")
    return (bytes([(min(len(literal), 15) << 4) |
                   min(match_length - 4, 15)]) +
            (ext(len(literal) - 15) if len(literal) >= 15 else b"") +
            literal + offset.to_bytes(2, "little") +
            (ext(match_length - 19) if match_length >= 19 else b""))


def periodic_block(content, period=1):
    """Encode an intentional overlapping match and five final literals."""
    if len(content) < period + 9:
        return literals(content)
    if any(content[i] != content[i % period] for i in range(len(content))):
        raise ValueError("not periodic")
    return (sequence(content[:period], period, len(content) - period - 5) +
            literals(content[-5:]))


def frame(block, content, mode):
    return block + (checksum(content, mode).to_bytes(4, "little") if mode else b"")


def selftest():
    assert xxh32(b"") == 0x02CC5D05
    assert xxh32(b"abc") == 0x32D153FF
    assert checksum(b"123456789", 2) == 0xCBF43926
    assert checksum(b"", 2) == 0
    for n in (0, 1, 3, 4, 15, 16, 17, 31, 32, 33, 255, 256, 4096, 65536):
        content = bytes(i & 255 for i in range(n))
        assert decode(literals(content)) == content
        repeat = b"A" * n
        assert decode(periodic_block(repeat)) == repeat
    for block, expected in ((b"\x10", 1), (b"\x10A\x00\x00\x00", 2),
                            (b"\x00\x01\x00\x00", 3)):
        try:
            decode(block)
        except LZ4Error as error:
            assert error.code == expected
        else:
            raise AssertionError("malformed fixture accepted")
