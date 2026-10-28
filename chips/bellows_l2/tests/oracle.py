"""Independent raw-LZ4 grammar, direct-sequence encoder, and public test vectors.

No expected compressed block is obtained from the DUT or its hash search.
The encoder accepts explicit sequences; the decoder uses a byte-list history.
"""

from dataclasses import dataclass, field
import random


BOUNDARIES = (4, 5, 11, 12, 13, 14, 15, 16, 19, 20, 254, 255,
              269, 270, 271, 510, 65535, 65536)


class FormatError(AssertionError):
    pass


def extension(value):
    assert value >= 0
    return bytes([255]) * (value // 255) + bytes([value % 255])


def literals(data):
    return (bytes([min(len(data), 15) << 4])
            + (extension(len(data) - 15) if len(data) >= 15 else b"") + data)


def sequence(data, offset, length):
    assert 1 <= offset <= 65535 and length >= 4
    return (bytes([(min(len(data), 15) << 4) | min(length - 4, 15)])
            + (extension(len(data) - 15) if len(data) >= 15 else b"")
            + data + offset.to_bytes(2, "little")
            + (extension(length - 19) if length >= 19 else b""))


def decode(encoded, strict=False):
    """Parse independently; return all bytes and sequence metadata.

    strict=True additionally checks the compressor's canonical final sequence,
    minimum-start distance and five-literal tail rules, not decoder extensions.
    """
    out = bytearray()
    records = []
    cursor = 0
    while cursor < len(encoded):
        token = encoded[cursor]
        cursor += 1
        litlen = token >> 4
        litext = []
        if litlen == 15:
            while True:
                if cursor == len(encoded):
                    raise FormatError("TRUNCATED_LITERAL_EXTENSION")
                extra = encoded[cursor]
                cursor += 1
                litext.append(extra)
                litlen += extra
                if extra != 255:
                    break
        if cursor + litlen > len(encoded):
            raise FormatError("TRUNCATED_LITERALS")
        literal_start = len(out)
        out.extend(encoded[cursor:cursor + litlen])
        cursor += litlen
        if cursor == len(encoded):
            if strict and token & 15:
                raise FormatError("FINAL_MATCH_NIBBLE")
            records.append(dict(literals=litlen, start=literal_start, final=True,
                                literal_extension=litext))
            break
        if cursor + 2 > len(encoded):
            raise FormatError("TRUNCATED_OFFSET")
        offset = int.from_bytes(encoded[cursor:cursor + 2], "little")
        cursor += 2
        if offset == 0:
            raise FormatError("ZERO_OFFSET")
        if offset > len(out):
            raise FormatError("UNAVAILABLE_HISTORY")
        matchlen = (token & 15) + 4
        matchext = []
        if token & 15 == 15:
            while True:
                if cursor == len(encoded):
                    raise FormatError("TRUNCATED_MATCH_EXTENSION")
                extra = encoded[cursor]
                cursor += 1
                matchext.append(extra)
                matchlen += extra
                if extra != 255:
                    break
        start = len(out)
        for _ in range(matchlen):
            out.append(out[-offset])
        records.append(dict(literals=litlen, start=start, length=matchlen,
                            offset=offset, final=False,
                            literal_extension=litext, match_extension=matchext))
    if not records or not records[-1]["final"]:
        raise FormatError("MISSING_FINAL_LITERAL_SEQUENCE")
    if strict:
        for record in records:
            if record["final"]:
                continue
            if record["start"] > len(out) - 12:
                raise FormatError("LAST_MATCH_START")
            if record["start"] + record["length"] > len(out) - 5:
                raise FormatError("TRAILING_FIVE_LITERALS")
        if any(not r["final"] for r in records) and records[-1]["literals"] < 5:
            raise FormatError("TRAILING_FIVE_LITERALS")
    return bytes(out), records


def expand(prefix, offset, length, tail=b"12345"):
    data = bytearray(prefix)
    for _ in range(length):
        data.append(data[-offset])
    return bytes(data) + tail


def hash4(key):
    """Fixture construction only, never an expected-compression search."""
    return key[0] ^ (
        ((key[1] << 1) | (key[1] >> 7)) & 255
    ) ^ (((key[2] << 2) | (key[2] >> 6)) & 255) ^ (
        ((key[3] << 3) | (key[3] >> 5)) & 255
    )


def unique_bytes(length, rng):
    while True:
        data = rng.randbytes(length)
        keys = [data[i:i + 4] for i in range(max(0, length - 3))]
        if len(set(keys)) == len(keys):
            return data


def collision_fixture():
    rng = random.Random(773)
    first = b"ABCD"
    while True:
        other = rng.randbytes(4)
        if other != first and hash4(other) == hash4(first):
            break
    while True:
        data = bytearray(rng.randbytes(80))
        data[0:4], data[20:24], data[40:44] = first, other, first
        keys = [bytes(data[i:i + 4]) for i in range(len(data) - 3)]
        if len(set(keys)) == len(keys) - 1:
            return bytes(data)


def boundary_match(length=7):
    """A sole repeated key at the last legal start, with no intervening collision."""
    rng = random.Random(881 + length)
    while True:
        prefix = unique_bytes(8, rng)
        data = prefix + prefix[:length] + b"\xf0\xf1\xf2\xf3\xf4"
        target = hash4(data[:4])
        if (all(hash4(data[p:p + 4]) != target for p in range(1, 8))
                and (length != 4 or prefix[4] != 0xf0)):
            keys = [data[p:p + 4] for p in range(1, 8)]
            if len(set(keys)) == 7:
                return data


def latest_entry_fixture():
    rng = random.Random(505)
    while True:
        key, gap1, gap2 = rng.randbytes(8), rng.randbytes(8), rng.randbytes(8)
        if gap1[0] == gap2[0] or key[0] == 0xf0:
            continue
        data = key + gap1 + key + gap2 + key + b"\xf0\xf1\xf2\xf3\xf4"
        target = hash4(key[:4])
        visits = list(range(1, 16)) + list(range(24, 32))
        if all(hash4(data[p:p + 4]) != target for p in visits):
            windows = [data[p:p + 4] for p in range(len(data) - 3)]
            expected_duplicates = sum(windows.count(key[i:i + 4]) - 1 for i in range(5))
            if len(windows) - len(set(windows)) == expected_duplicates == 10:
                return data


@dataclass
class Raw:
    name: str
    data: bytes
    error: int = 0
    beats: list | None = None
    fallback: bool = False
    require_match: bool = False
    ratio: bool = False
    tags: tuple = ()

    def segments(self):
        if self.beats is not None:
            return self.beats
        if not self.data:
            return [(1, 0x200)]
        return [(1, value | 0x100 | (0x200 if i == len(self.data) - 1 else 0))
                for i, value in enumerate(self.data)]


@dataclass
class Decoded:
    name: str
    encoded: bytes
    expected: bytes
    error: int = 0
    segments_override: list | None = None
    tags: tuple = ()

    def segments(self):
        if self.segments_override is not None:
            return self.segments_override
        return [(1, value | (0x200 if i == len(self.encoded) - 1 else 0))
                for i, value in enumerate(self.encoded)]


@dataclass
class Case:
    name: str
    raw: list = field(default_factory=list)
    decoder: list = field(default_factory=list)
    roundtrip: bool = False
    abort: str = ""


def decoder_vectors(large=False, overflow=False):
    cases = [Decoded("parent-empty-low-nibble", b"\x0f", b"")]
    for size in (0, 1, 4, 5, 14, 15, 16, 269, 270, 271, 524, 525):
        raw = bytes((i * 73 + 19) & 255 for i in range(size))
        cases.append(Decoded(f"literal-{size}", literals(raw), raw,
                             tags=("literal-extension",) if size >= 15 else ()))
    for length in (4, 18, 19, 20, 273, 274, 275, 528, 529, 530):
        prefix = b"ABCDEFGH"
        encoded = sequence(prefix, 1, length) + literals(b"12345")
        expected = expand(prefix, 1, length)
        assert decode(encoded)[0] == expected
        cases.append(Decoded(f"overlap-{length}", encoded, expected,
                             tags=("match-extension", "offset-one")))
    malformed = (
        ("token-truncated", b"\x10", b"", 1),
        ("literal-ext-truncated", b"\xf0\x00", b"", 1),
        ("literal-short", b"\x30AB", b"AB", 1),
        ("offset-low-truncated", b"\x10A\x01", b"A", 1),
        ("offset-high-truncated", b"\x10A\x01\x00", b"A", 1),
        ("zero-offset", b"\x10A\x00\x00\x00", b"A", 2),
        ("missing-history", b"\x10A\x02\x00\x00", b"A", 3),
        ("match-ext-truncated", b"\x1fA\x01\x00\x00", b"A", 1),
    )
    for name, encoded, prefix, error in malformed:
        cases.append(Decoded(name, encoded, prefix, error, tags=("malformed",)))
        cases.append(Decoded(name + "-recovery", literals(b"OK"), b"OK",
                             tags=("post-error-recovery",)))
    if large:
        prefix = bytes(range(256)) * 256
        expected = expand(prefix, 65535, 600, b"tail!")
        encoded = sequence(prefix, 65535, 600) + literals(b"tail!")
        assert decode(encoded)[0] == expected and len(expected) > 65536
        cases.append(Decoded("offset-65535-wrap", encoded, expected,
                             tags=("offset-65535", "history-wrap", "output-over-65536")))
    if overflow:
        count = ((2**32 - 1 - 15) // 255) + 1
        cases.append(Decoded("literal-length-overflow", b"", b"", 4,
                             [(1, 0xf0), (count, 0xff), (1, 0x200)],
                             ("length-overflow",)))
        count = ((2**32 - 1 - 19) // 255) + 1
        cases.append(Decoded("match-length-overflow", b"", b"A", 4,
                             [(1, 0x1f), (1, ord("A")), (1, 1), (1, 0),
                              (count, 0xff), (1, 0x200)],
                             ("length-overflow",)))
        cases.append(Decoded("overflow-recovery", literals(b"OK"), b"OK"))
    return cases


def matrix_cases(capacity, seed, targeted=False):
    rng = random.Random(seed)
    sizes = sorted({0, 1, capacity} | {n for n in BOUNDARIES if n <= capacity})
    raw = [Raw(f"unique-{n}", unique_bytes(n, rng), fallback=True,
               tags=("empty",) if n == 0 else ("literal-boundary",))
           for n in sizes]
    raw += [Raw("back-to-back-1", b"X", fallback=True),
            Raw("back-to-back-2", b"Y", fallback=True)]
    if capacity >= 20:
        raw.append(Raw("last-start-tail-five", boundary_match(), require_match=True,
                       tags=("last-match-start", "five-trailing")))
        four = boundary_match(4) + b"\xe5\xe6\xe7"
        raw.append(Raw("four-byte-match", four, require_match=True, tags=("match-four",)))
    if capacity >= 80:
        raw.append(Raw("hash-collision", collision_fixture(), fallback=True,
                       tags=("hash-collision",)))
        clear = latest_entry_fixture()
        raw += [Raw("latest-entry-before", clear, require_match=True,
                    tags=("latest-hash-entry",)),
                Raw("intervening-hash-owner", b"B" * min(capacity, 80)),
                Raw("latest-entry-after", clear, require_match=True,
                    tags=("hash-clearing",))]
    for length in (19, 20, 273, 274, 275, 528, 529, 530):
        size = length + 6
        if size <= capacity:
            raw.append(Raw(f"hardware-match-extension-{length}", b"A" * (size - 5)
                           + b"12345", require_match=True,
                           tags=("match-extension", "offset-one")))
    if capacity >= 13:
        raw.append(Raw("capacity-repetitive", b"A" * capacity,
                       require_match=True))
    if capacity in (4096, 65536):
        for pattern, name in ((b"A", "A"), (b"ABCD", "ABCD"),
                              (bytes(range(256)), "byte-ramp")):
            raw.append(Raw(f"ratio-{name}", (pattern * capacity)[:capacity],
                           require_match=True, ratio=True, tags=("ratio",)))
    if targeted:
        raw = [Raw("target-fallback", unique_bytes(min(capacity, 80), rng), fallback=True),
               Raw("target-repeat", b"A" * capacity, require_match=capacity >= 14)]
    decoder = decoder_vectors(large=capacity == 65536) if not targeted else [
        Decoded("target-independent-match", sequence(b"ABCDEFGH", 1, 274)
                + literals(b"12345"), expand(b"ABCDEFGH", 1, 274))]
    duplex = Case("duplex", raw, decoder)
    rt_raw = [Raw("route-empty", b""), Raw("route-single", b"Z"),
              Raw("route-max", (b"route-DIFFERENT!" * capacity)[:capacity]),
              Raw("route-back-to-back", b"Q")]
    roundtrip = Case("internal-route", rt_raw, roundtrip=True)
    if targeted:
        return [duplex, roundtrip]
    errors = [
        Raw("overflow", b"", 5, [(capacity, 0x141), (1, 0x142), (1, 0x343)]),
        Raw("overflow-recovery", b"R"),
        Raw("framing-first", b"", 6, [(1, 0), (1, 0x344)]),
        Raw("framing-recovery", b"S"),
        Raw("framing-final", b"", 6, [(1, 0x141), (1, 0x200)]),
        Raw("framing-final-recovery", b"T"),
        Raw("first-error-framing", b"", 6,
            [(1, 0), (capacity + 2, 0x141), (1, 0x341)]),
        Raw("first-error-overflow", b"", 5,
            [(capacity + 1, 0x141), (1, 0), (1, 0x341)]),
        Raw("final-recovery", b"U"),
    ]
    result = [duplex, roundtrip, Case("errors", errors)]
    # Reset probes intentionally abandon work, followed by a byte-checked epoch.
    result.append(Case("reset-collect", [Raw("aborted", b"", beats=[(capacity + 2, 0x141)])],
                       abort="collect"))
    if capacity >= 257:
        result.append(Case("reset-match", [Raw("aborted", b"A" * capacity)], abort="match"))
    if capacity >= 13:
        result.append(Case("reset-emission", [Raw("aborted", b"A" * capacity)], abort="emission"))
    result.append(Case("reset-stalled", [Raw("aborted", b"Z")], abort="stalled"))
    return result
