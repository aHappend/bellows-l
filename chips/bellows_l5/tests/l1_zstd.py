"""Independent bounded RFC 8878 model and frame construction.

Numerical source: RFC 8878 sections 3.1.1.3--3.1.1.5 and 4.1.
This module never imports RTL, reads implementation tables, or invokes a codec
library. Library interoperability is checked separately by the experiment driver.
"""

from dataclasses import dataclass, field
import struct

from l1_oracle import frame, xxhash


LL_BASE = tuple(range(16)) + (
    16, 18, 20, 22, 24, 28, 32, 40, 48, 64, 128, 256, 512, 1024,
    2048, 4096, 8192, 16384, 32768, 65536)
LL_BITS = (0,) * 16 + (1,) * 4 + (2,) * 2 + (3,) * 2 + (4,) + tuple(range(6, 17))
ML_BASE = tuple(range(3, 35)) + (
    35, 37, 39, 41, 43, 47, 51, 59, 67, 83, 99, 131, 259, 515,
    1027, 2051, 4099, 8195, 16387, 32771, 65539)
ML_BITS = (0,) * 32 + (1,) * 4 + (2,) * 2 + (3,) * 2 + (4,) * 2 + (5,) + tuple(range(7, 17))
DEFAULT_COUNTS = (
    (4, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1,
     2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 2, 1, 1, 1, 1, 1, -1, -1, -1, -1),
    (1, 1, 1, 1, 1, 1, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1,
     1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1),
    (1, 4, 3, 2, 2, 2, 2, 2, 2) + (1,) * 37 + (-1,) * 7,
)
MAX_SYMBOL = (35, 31, 52)


class FrameError(ValueError):
    def __init__(self, message, code=11):
        super().__init__(message)
        self.code = code


class ForwardBits:
    def __init__(self, data):
        self.data, self.position = data, 0

    def read(self, count):
        if count < 0 or self.position + count > 8 * len(self.data):
            raise FrameError("truncated normalized-count description")
        value = 0
        for bit in range(count):
            p = self.position + bit
            value |= ((self.data[p // 8] >> (p % 8)) & 1) << bit
        self.position += count
        return value


class ReverseBits:
    def __init__(self, data):
        if not data or not data[-1]:
            raise FrameError("missing reverse-stream stop marker")
        self.value = int.from_bytes(data, "little")
        self.remaining = 8 * (len(data) - 1) + data[-1].bit_length() - 1

    def read(self, count):
        if count < 0 or count > self.remaining:
            raise FrameError("reverse-stream underflow")
        self.remaining -= count
        return (self.value >> self.remaining) & ((1 << count) - 1)


def decode_counts(data, alphabet):
    reader = ForwardBits(data)
    log = reader.read(4) + 5
    if not 5 <= log <= (8 if alphabet == 1 else 9):
        raise FrameError("excessive FSE accuracy log")
    remaining = (1 << log) + 1
    counts = []
    while remaining > 1:
        width = remaining.bit_length()
        threshold = 1 << (width - 1)
        small = 2 * threshold - 1 - remaining
        low = reader.read(width - 1)
        if low < small:
            value = low
        else:
            value = low + reader.read(1) * threshold
            if value >= threshold:
                value -= small
        count = value - 1
        if count < -1:
            raise FrameError("invalid normalized count")
        remaining -= abs(count)
        counts.append(count)
        if remaining < 1:
            raise FrameError("excess normalized mass")
        if count == 0:
            while True:
                zeros = reader.read(2)
                counts.extend([0] * zeros)
                if len(counts) > MAX_SYMBOL[alphabet] + 1:
                    raise FrameError("zero run exceeds alphabet")
                if zeros != 3:
                    break
        if len(counts) > MAX_SYMBOL[alphabet] + 1:
            raise FrameError("normalized symbol exceeds alphabet")
    build_table(counts, log)
    return tuple(counts), log, (reader.position + 7) // 8


def encode_counts(counts, log):
    build_table(counts, log)
    fields = [(log - 5, 4)]
    remaining = (1 << log) + 1
    for count in counts:
        if remaining == 1:
            if count:
                raise ValueError("nonzero count after completed description")
            continue
        width = remaining.bit_length()
        threshold = 1 << (width - 1)
        small = 2 * threshold - 1 - remaining
        value = count + 1
        if value < small:
            fields.append((value, width - 1))
        else:
            fields.append((value if value < threshold else value + small, width))
        remaining -= abs(count)
        if count == 0:
            fields.append((0, 2))
    if remaining != 1:
        raise ValueError("incomplete normalized distribution")
    value = position = 0
    for bits, width in fields:
        if not 0 <= bits < 1 << width:
            raise ValueError("count description field overflow")
        value |= bits << position
        position += width
    return value.to_bytes((position + 7) // 8, "little")


def build_table(counts, log):
    """Allocate RFC cells, then assign per-symbol ranges in sorted-state order.

    The range formulation deliberately does not implement a symbolNext counter
    or derive any expected value from the DUT's table-building datapath.
    """
    size = 1 << log
    if not 5 <= log <= 9 or any(c < -1 for c in counts):
        raise FrameError("invalid FSE distribution")
    if sum(abs(c) for c in counts) != size or sum(c != 0 for c in counts) < 2:
        raise FrameError("invalid FSE normalized mass")
    symbols = [None] * size
    reserved = size
    for symbol, count in enumerate(counts):
        if count == -1:
            reserved -= 1
            symbols[reserved] = symbol
    positions = [0]
    stride = size // 2 + size // 8 + 3
    for _ in range(size - 1):
        positions.append((positions[-1] + stride) % size)
    available = iter(p for p in positions if p < reserved)
    for symbol, count in enumerate(counts):
        for _ in range(max(0, count)):
            symbols[next(available)] = symbol
    rows = [None] * size
    for symbol, count in enumerate(counts):
        if not count:
            continue
        states = [i for i, s in enumerate(symbols) if s == symbol]
        mass = len(states)
        unit = 1 << (mass - 1).bit_length()
        wide = unit - mass
        narrow_width = size // unit
        for rank, state in enumerate(states):
            width = narrow_width * (2 if rank < wide else 1)
            base = (mass - wide + 2 * rank) * narrow_width if rank < wide else (
                rank - wide) * narrow_width
            rows[state] = (symbol, width.bit_length() - 1, base)
    if any(row is None for row in rows):
        raise FrameError("unassigned FSE table cell")
    return tuple(rows)


def default_table(alphabet):
    log = 5 if alphabet == 1 else 6
    return build_table(DEFAULT_COUNTS[alphabet], log), log


@dataclass
class Decoded:
    data: bytes
    modes: tuple = ()
    sequences: list = field(default_factory=list)
    transitions: int = 0
    dictionary_matches: int = 0
    block_type: int = 0


def execute_sequences(literals, sequences, dictionary=b"", capacity=65536):
    output = bytearray()
    literal_pos = 0
    offsets = [1, 4, 8]
    dictionary_matches = 0
    for ll, ml, value in sequences:
        if ll < 0 or ml < 3 or literal_pos + ll > len(literals):
            raise FrameError("invalid sequence lengths")
        output.extend(literals[literal_pos:literal_pos + ll])
        literal_pos += ll
        if value > 3:
            distance = value - 3
            offsets = [distance, *offsets[:2]]
        else:
            selected = value - 1 + (ll == 0)
            if selected == 3:
                distance = offsets[0] - 1
                offsets = [distance, *offsets[:2]]
            elif 0 <= selected < 3:
                distance = offsets[selected]
                offsets = [distance, *offsets[:selected], *offsets[selected + 1:]]
            else:
                raise FrameError("invalid repeat offset code")
        if distance <= 0 or distance > len(dictionary) + len(output) or distance > 131072:
            raise FrameError("match offset outside available history")
        if len(output) + ml > capacity:
            raise FrameError("sequence exceeds decoded-size limit", 5)
        if distance > len(output):
            dictionary_matches += 1
        for _ in range(ml):
            virtual = len(dictionary) + len(output) - distance
            output.append(dictionary[virtual] if virtual < len(dictionary)
                          else output[virtual - len(dictionary)])
    output.extend(literals[literal_pos:])
    if len(output) > capacity:
        raise FrameError("literal tail exceeds decoded-size limit", 5)
    return bytes(output), dictionary_matches


def decode_frame(encoded, dictionary=b"", max_block=65536):
    if len(encoded) > 2 * max_block + 1024:
        raise FrameError("source frame exceeds input limit", 8)
    if len(encoded) < 17:
        raise FrameError("truncated frame")
    if encoded[:4] != bytes.fromhex("28b52ffd"):
        if int.from_bytes(encoded[:4], "little") & 0xFFFFFFF0 == 0x184D2A50:
            raise FrameError("skippable frame unsupported", 12)
        raise FrameError("invalid magic")
    if encoded[4:6] != bytes.fromhex("8438"):
        raise FrameError("unsupported frame header", 12)
    content_size = int.from_bytes(encoded[6:10], "little")
    if content_size > max_block:
        raise FrameError("content size exceeds decoded-size limit", 5)
    block_header = int.from_bytes(encoded[10:13], "little")
    if not block_header & 1:
        raise FrameError("multi-block frame unsupported", 12)
    block_type, block_size = (block_header >> 1) & 3, block_header >> 3
    if block_type == 3:
        raise FrameError("reserved block type")
    body_bytes = 1 if block_type == 1 else block_size
    end = 13 + body_bytes
    if len(encoded) != end + 4:
        raise FrameError("truncated or trailing frame bytes")
    body = encoded[13:end]
    if block_type == 0:
        result = Decoded(body, block_type=0)
    elif block_type == 1:
        result = Decoded(body * block_size, block_type=1)
    else:
        if not body:
            raise FrameError("missing literal section")
        kind, form = body[0] & 3, (body[0] >> 2) & 3
        if kind >= 2:
            raise FrameError("Huffman literals unsupported", 12)
        hbytes = 1 if form in (0, 2) else (2 if form == 1 else 3)
        if len(body) < hbytes:
            raise FrameError("truncated literal header")
        size = int.from_bytes(body[:hbytes], "little") >> (3 if hbytes == 1 else 4)
        pos = hbytes + (1 if kind == 1 else size)
        if pos >= len(body):
            raise FrameError("truncated literal or sequence section")
        literals = body[hbytes:pos] if kind == 0 else body[hbytes:pos] * size
        first = body[pos]
        pos += 1
        if first < 128:
            count = first
        elif first < 255:
            if pos == len(body):
                raise FrameError("truncated sequence count")
            count = ((first - 128) << 8) + body[pos]
            pos += 1
        else:
            if pos + 2 > len(body):
                raise FrameError("truncated long sequence count")
            count = int.from_bytes(body[pos:pos + 2], "little") + 0x7F00
            pos += 2
        modes, sequences, transitions = (), [], 0
        if count:
            if pos == len(body):
                raise FrameError("missing sequence modes")
            mode_byte = body[pos]
            pos += 1
            if mode_byte & 3:
                raise FrameError("reserved sequence mode bits")
            modes = tuple((mode_byte >> shift) & 3 for shift in (6, 4, 2))
            if 3 in modes:
                raise FrameError("repeat table without preceding ownership")
            tables, logs = [], []
            for alphabet, mode in enumerate(modes):
                if mode == 0:
                    table, log = default_table(alphabet)
                elif mode == 1:
                    if pos == len(body) or body[pos] > MAX_SYMBOL[alphabet]:
                        raise FrameError("invalid RLE sequence symbol")
                    table, log = ((body[pos], 0, 0),), 0
                    pos += 1
                else:
                    counts, log, used = decode_counts(body[pos:], alphabet)
                    pos += used
                    table = build_table(counts, log)
                tables.append(table)
                logs.append(log)
            bits = ReverseBits(body[pos:])
            states = [bits.read(log) for log in logs]
            for sequence_index in range(count):
                codes = [table[state][0] for table, state in zip(tables, states)]
                ll, of, ml = codes
                value = (1 << of) + bits.read(of)
                match = ML_BASE[ml] + bits.read(ML_BITS[ml])
                literal = LL_BASE[ll] + bits.read(LL_BITS[ll])
                sequences.append((literal, match, value))
                if sequence_index != count - 1:
                    for alphabet in (0, 2, 1):
                        _, width, base = tables[alphabet][states[alphabet]]
                        states[alphabet] = base + bits.read(width)
                        if states[alphabet] >= len(tables[alphabet]):
                            raise FrameError("transition outside FSE table")
                        transitions += 1
            if bits.remaining:
                raise FrameError("unconsumed reverse-stream bits")
        elif pos != len(body):
            raise FrameError("trailing bytes after zero sequences")
        raw, references = execute_sequences(literals, sequences, dictionary, content_size)
        result = Decoded(raw, modes, sequences, transitions, references, block_type)
    if len(result.data) != content_size:
        raise FrameError("decoded content size mismatch")
    checksum = int.from_bytes(encoded[end:end + 4], "little")
    if xxhash(result.data, 64) & 0xFFFFFFFF != checksum:
        raise FrameError("content checksum mismatch", 7)
    return result


def length_code(length, match=False):
    bases, widths = (ML_BASE, ML_BITS) if match else (LL_BASE, LL_BITS)
    for code, (base, width) in enumerate(zip(bases, widths)):
        if base <= length < base + (1 << width):
            return code, length - base, width
    raise ValueError("length has no RFC sequence code")


def sequence_frame(literals, sequences, modes=(0, 0, 0), dictionary=b"", logs=(6, 5, 6)):
    """Construct independent supported frames with actual inverse FSE transforms.

    Each tuple is (literal length, match length, RFC offset value), not distance.
    RLE selections require constant codes; compressed selections use two-symbol
    distributions. All state inverses are searched in independent model rows.
    """
    if not sequences or len(sequences) >= 128:
        raise ValueError("fixture requires 1..127 sequences")
    codes, extras = [], []
    for ll, ml, value in sequences:
        lc, le, lb = length_code(ll)
        mc, me, mb = length_code(ml, True)
        oc = value.bit_length() - 1
        if value < 1:
            raise ValueError("invalid offset value")
        codes.append((lc, oc, mc))
        extras.append(((value - (1 << oc), oc), (me, mb), (le, lb)))
    descriptions, tables, table_logs = bytearray(), [], []
    for alphabet, mode in enumerate(modes):
        present = sorted({c[alphabet] for c in codes})
        if mode == 0:
            table, log = default_table(alphabet)
        elif mode == 1:
            if len(present) != 1:
                raise ValueError("nonconstant RLE fixture")
            descriptions.append(present[0])
            table, log = ((present[0], 0, 0),), 0
        elif mode == 2:
            log = logs[alphabet]
            other = next(s for s in range(MAX_SYMBOL[alphabet] + 1) if s not in present)
            symbols = sorted(set(present + [other]))
            counts = [0] * (symbols[-1] + 1)
            for symbol in symbols[:-1]:
                counts[symbol] = 1
            counts[symbols[-1]] = (1 << log) - len(symbols) + 1
            descriptions.extend(encode_counts(counts, log))
            table = build_table(counts, log)
        else:
            raise ValueError("repeat mode is not a successful bounded-profile fixture")
        tables.append(table)
        table_logs.append(log)
    state_rows = [None] * len(sequences)
    for index in reversed(range(len(sequences))):
        selected = []
        for alphabet, symbol in enumerate(codes[index]):
            candidates = [(s, row) for s, row in enumerate(tables[alphabet]) if row[0] == symbol]
            if index != len(sequences) - 1:
                target = state_rows[index + 1][alphabet]
                candidates = [(s, row) for s, row in candidates
                              if row[2] <= target < row[2] + (1 << row[1])]
            if not candidates:
                raise ValueError("symbol absent or inverse transition missing")
            selected.append(candidates[0][0])
        state_rows[index] = selected
    fields = list(zip(state_rows[0], table_logs))
    for index in range(len(sequences)):
        fields.extend(extras[index])
        if index != len(sequences) - 1:
            for alphabet in (0, 2, 1):
                _, width, base = tables[alphabet][state_rows[index][alphabet]]
                fields.append((state_rows[index + 1][alphabet] - base, width))
    packed = position = 0
    for value, width in reversed(fields):
        packed |= value << position
        position += width
    packed |= 1 << position
    stream = packed.to_bytes((position + 8) // 8, "little")
    size = len(literals)
    if size < 32:
        literal_header = bytes((size << 3,))
    elif size < 4096:
        literal_header = ((size << 4) | 4).to_bytes(2, "little")
    else:
        literal_header = ((size << 4) | 12).to_bytes(3, "little")
    mode_byte = sum(mode << shift for mode, shift in zip(modes, (6, 4, 2)))
    body = (literal_header + literals + bytes((len(sequences), mode_byte))
            + descriptions + stream)
    raw, _ = execute_sequences(literals, sequences, dictionary)
    return frame(raw, body, 2)
