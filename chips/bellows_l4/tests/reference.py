"""Independent byte-level BELLOWS reference arithmetic and wire formats."""

from collections import Counter
import heapq
import struct
import zlib


class CodecError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def xxh32(data):
    mask = (1 << 32) - 1
    p1, p2, p3, p4, p5 = 2654435761, 2246822519, 3266489917, 668265263, 374761393

    def rol(x, n):
        x &= mask
        return ((x << n) | (x >> (32 - n))) & mask

    def rnd(a, word):
        return (rol(a + word * p2, 13) * p1) & mask

    pos = 0
    if len(data) >= 16:
        v = [(p1 + p2) & mask, p2, 0, (-p1) & mask]
        while pos + 16 <= len(data):
            for i, word in enumerate(struct.unpack_from("<4I", data, pos)):
                v[i] = rnd(v[i], word)
            pos += 16
        h = sum(rol(a, n) for a, n in zip(v, (1, 7, 12, 18))) & mask
    else:
        h = p5
    h = (h + len(data)) & mask
    while pos + 4 <= len(data):
        h = (rol(h + struct.unpack_from("<I", data, pos)[0] * p3, 17) * p4) & mask
        pos += 4
    for b in data[pos:]:
        h = (rol(h + b * p5, 11) * p1) & mask
    h ^= h >> 15
    h = (h * p2) & mask
    h ^= h >> 13
    h = (h * p3) & mask
    return (h ^ (h >> 16)) & mask


def checksum(data, mode):
    if mode == 0:
        return 0
    if mode == 1:
        return xxh32(data)
    if mode == 2:
        return zlib.crc32(data) & 0xFFFFFFFF
    raise ValueError("invalid checksum mode")


def trailer(data, mode):
    return struct.pack("<I", checksum(data, mode)) if mode else b""


def lz4_decode(block, limit=65536):
    """Parse independent token grammar, including parent's final-field rule."""
    output = bytearray()
    pos = 0

    def read():
        nonlocal pos
        if pos == len(block):
            raise CodecError(1, "truncated LZ4 field")
        value = block[pos]
        pos += 1
        return value

    def extension(n):
        while True:
            b = read()
            if pos == len(block):
                raise CodecError(1, "terminal extension byte")
            n += b
            if n > 0xFFFFFFFF:
                raise CodecError(4, "extension overflow")
            if b != 255:
                return n

    if not block:
        raise CodecError(1, "missing token")
    while pos < len(block):
        token = read()
        literals = token >> 4
        if pos == len(block):
            if literals:
                raise CodecError(1, "terminal token requires literals")
            return bytes(output)
        if literals == 15:
            literals = extension(literals)
        for _ in range(literals):
            b = read()
            if len(output) == limit:
                raise CodecError(5, "block limit")
            output.append(b)
        if pos == len(block):
            return bytes(output)
        lo = read()
        if pos == len(block):
            raise CodecError(1, "terminal offset low")
        offset = lo | (read() << 8)
        if pos == len(block):
            raise CodecError(1, "terminal offset high")
        if offset == 0:
            raise CodecError(2, "zero offset")
        if offset > len(output):
            raise CodecError(3, "unavailable history")
        length = (token & 15) + 4
        if (token & 15) == 15:
            length = extension(length)
        for _ in range(length):
            if len(output) == limit:
                raise CodecError(5, "block limit")
            output.append(output[-offset])
    raise CodecError(1, "missing terminal sequence")


def length_extension(length, base):
    if length < base:
        return b""
    q, r = divmod(length - base, 255)
    return bytes([255]) * q + bytes([r])


def literal_block(data):
    return bytes([min(len(data), 15) << 4]) + length_extension(len(data), 15) + data


def lz4_compress(raw):
    """Parent deterministic direct-mapped search, expressed as byte operations.

    Its wire output is also checked by the independent grammar decoder. No RTL
    transition, cycle count, memory signal or observed output enters this model.
    """
    table = {}
    position = anchor = 0
    encoded = bytearray()
    while len(raw) >= 13 and position <= len(raw) - 12:
        key = raw[position:position + 4]
        h = 0
        for shift, b in enumerate(key):
            h ^= ((b << shift) | (b >> (8 - shift))) & 255 if shift else b
        previous = table.get(h)
        table[h] = position
        if previous is None or not 1 <= position - previous <= 65535 or (
            raw[previous:previous + 4] != key
        ):
            position += 1
            continue
        end = position + 4
        while end < len(raw) - 5 and raw[end] == raw[previous + end - position]:
            end += 1
        literals = raw[anchor:position]
        match_length = end - position
        encoded.extend(bytes([(min(len(literals), 15) << 4) | min(match_length - 4, 15)])
                       + length_extension(len(literals), 15) + literals
                       + struct.pack("<H", position - previous)
                       + length_extension(match_length, 19))
        anchor = position = end
    encoded.extend(literal_block(raw[anchor:]))
    result = bytes(encoded) if len(encoded) < len(literal_block(raw)) else literal_block(raw)
    assert lz4_decode(result) == raw
    return result


def match_block(prefix, offset, length, tail=b"", *, limit=65536):
    if not 1 <= offset <= min(len(prefix), 65535) or length < 4:
        raise ValueError("invalid match fixture")
    block = (
        bytes([(min(len(prefix), 15) << 4) | min(length - 4, 15)])
        + length_extension(len(prefix), 15) + prefix
        + struct.pack("<H", offset) + length_extension(length, 19)
        + literal_block(tail)
    )
    return block, lz4_decode(block, limit)


def symbols_and_residuals(raw, codec):
    if codec in (1, 4):
        return list(raw), b"", 256
    if codec == 2:
        if len(raw) & 1:
            raise CodecError(8, "odd BF16 bytes")
        symbols, residuals = [], bytearray()
        for lo, hi in zip(raw[::2], raw[1::2]):
            symbols.append(((hi & 127) << 1) | (lo >> 7))
            residuals.append((hi & 128) | (lo & 127))
        return symbols, bytes(residuals), 256
    if codec == 3:
        return [n for b in raw for n in (b & 15, b >> 4)], b"", 16
    raise ValueError("invalid codec")


def code_lengths(frequencies, alphabet):
    """Priority-queue Huffman algorithm, not a translation of RTL scans."""
    heap = []
    for symbol, frequency in sorted(frequencies.items()):
        if frequency:
            heapq.heappush(heap, (frequency, symbol, symbol))
    lengths = [0] * alphabet
    if not heap:
        return lengths
    if len(heap) == 1:
        lengths[heap[0][1]] = 1
        return lengths
    while len(heap) > 1:
        a, b = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, (a[0] + b[0], min(a[1], b[1]), (a[2], b[2])))

    def visit(node, depth):
        if isinstance(node, int):
            lengths[node] = depth
        else:
            visit(node[0], depth + 1)
            visit(node[1], depth + 1)

    visit(heap[0][2], 0)
    if max(lengths) > 15:
        return [4 if alphabet == 16 else 8] * alphabet
    return lengths


def canonical(lengths):
    if any(n < 0 or n > 15 for n in lengths):
        raise CodecError(11, "out-of-range code length")
    ordered = sorted((n, s) for s, n in enumerate(lengths) if n)
    if not ordered:
        return {}
    if len(ordered) == 1 and ordered[0][0] != 1:
        raise CodecError(11, "invalid singleton")
    code, previous, result = 0, 0, {}
    for n, symbol in ordered:
        code <<= n - previous
        if code >= 1 << n:
            raise CodecError(11, "oversubscribed table")
        result[symbol] = (code, n)
        previous = n
        code += 1
    if len(ordered) > 1 and code != 1 << previous:
        raise CodecError(11, "incomplete table")
    return result


def entropy_encode(raw, codec, *, intermediate=None, lengths=None):
    source = intermediate if codec == 4 else raw
    if source is None:
        raise ValueError("mode 4 needs independently chosen intermediate LZ4")
    symbols, residuals, alphabet = symbols_and_residuals(source, codec)
    if lengths is None:
        lengths = code_lengths(Counter(symbols), alphabet)
    codes = canonical(lengths)
    payload = bytearray()
    accumulator = bits = bit_count = 0
    for symbol in symbols:
        code, n = codes[symbol]
        accumulator = (accumulator << n) | code
        bits += n
        bit_count += n
        while bits >= 8:
            bits -= 8
            payload.append((accumulator >> bits) & 255)
    if bits:
        payload.append((accumulator << (8 - bits)) & 255)
    header = b"BL4H" + bytes([1, codec, 0, 0]) + struct.pack(
        "<III", len(raw), len(symbols), bit_count
    )
    return header + bytes(lengths) + residuals + bytes(payload)


def entropy_decode(frame, codec, limit=65536):
    def reject(message):
        raise CodecError(11, message)

    if len(frame) < 20 or frame[:8] != b"BL4H" + bytes([1, codec, 0, 0]):
        reject("header")
    n, count, bit_count = struct.unpack_from("<III", frame, 8)
    alphabet = 16 if codec == 3 else 256
    if n > limit or (codec == 1 and count != n) or (
        codec == 2 and (n & 1 or count != n // 2)
    ) or (codec == 3 and count != 2 * n) or (
        codec == 4 and count > 2 * limit + 16
    ):
        reject("length/count")
    residual_count = n // 2 if codec == 2 else 0
    start = 20 + alphabet + residual_count
    if len(frame) != start + (bit_count + 7) // 8 or len(frame) > 4 * limit + 1024:
        reject("exact frame length")
    codes = canonical(list(frame[20:20 + alphabet]))
    if not codes and (count or bit_count):
        reject("empty table")
    if (count == 0 and bit_count) or (count and not count <= bit_count <= 15 * count):
        reject("bit count")
    reverse = {(code, length): s for s, (code, length) in codes.items()}
    payload = frame[start:]
    if bit_count & 7 and payload[-1] & ((1 << (8 - (bit_count & 7))) - 1):
        reject("nonzero padding")
    symbols = []
    code = depth = 0
    for bit in range(bit_count):
        code = (code << 1) | ((payload[bit // 8] >> (7 - bit % 8)) & 1)
        depth += 1
        if (code, depth) in reverse:
            symbols.append(reverse[code, depth])
            code = depth = 0
        elif depth == 15:
            reject("nonexistent code")
    if depth or len(symbols) != count:
        reject("exact symbol/bit consumption")
    if codec == 2:
        output = bytearray()
        for exponent, residual in zip(symbols, frame[20 + alphabet:start]):
            output.extend(((residual & 127) | ((exponent & 1) << 7),
                           (residual & 128) | (exponent >> 1)))
        raw = bytes(output)
    elif codec == 3:
        raw = bytes(a | (b << 4) for a, b in zip(symbols[::2], symbols[1::2]))
    elif codec == 4:
        raw = lz4_decode(bytes(symbols), limit)
    else:
        raw = bytes(symbols)
    if len(raw) != n:
        reject("raw length")
    return raw


def self_test():
    assert xxh32(b"") == 0x02CC5D05
    assert xxh32(b"a") == 0x550D7456
    assert xxh32(b"abc") == 0x32D153FF
    assert checksum(b"123456789", 2) == 0xCBF43926
    assert lz4_decode(b"\x00") == b""
    for codec in (1, 2, 3):
        for raw in (b"", b"\0\0", bytes(range(256))):
            assert entropy_decode(entropy_encode(raw, codec), codec) == raw
