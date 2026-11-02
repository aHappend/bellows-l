"""Requirement-directed fixtures, independent expected bytes and descriptors."""

from dataclasses import dataclass
import random
import struct

from reference import (CodecError, checksum, entropy_decode, entropy_encode, literal_block,
                       lz4_compress, lz4_decode, match_block, trailer)


@dataclass
class Case:
    name: str
    source: bytes
    expected: bytes
    codec: int = 0
    decompress: int = 1
    wide: int = 1
    channel: int = 0
    checksum_mode: int = 0
    checksum_value: int = 0
    error: int = 0
    capacity: int | None = None
    source_sizes: list | None = None
    dest_sizes: list | None = None
    stalls: int = 0
    seed: int = 17
    descriptors_invalid: bool = False
    source_addresses: list | None = None
    dest_addresses: list | None = None
    read_fault: int = 0
    write_fault: int = 0


def write_cases(path, cases):
    records = []
    with path.open("w") as stream:
        for test_id, case in enumerate(cases, 1):
            capacity = case.capacity if case.capacity is not None else max(1, len(case.expected))
            src = case.source_sizes if case.source_sizes is not None else (
                [len(case.source)] if case.source else [])
            dst = case.dest_sizes if case.dest_sizes is not None else [capacity]
            fields = (test_id, case.channel, case.codec, case.decompress, case.wide,
                      case.checksum_mode, len(case.source), len(case.expected), capacity,
                      case.error)
            stream.write(" ".join(map(str, fields)) + f" {case.checksum_value:08x} "
                         + f"{len(src)} {len(dst)} {case.stalls} {case.seed} "
                         + f"{int(case.descriptors_invalid)} {case.read_fault} "
                         + f"{case.write_fault}\n")
            stream.write(" ".join(map(str, src + dst)) + "\n")
            src_addresses = case.source_addresses or [
                4099 + sum(src[:i]) for i in range(len(src))]
            dst_addresses = case.dest_addresses or [
                1048579 + sum(dst[:i]) for i in range(len(dst))]
            stream.write(" ".join(f"{a:016x}" for a in src_addresses + dst_addresses) + "\n")
            stream.write(" ".join(f"{b:02x}" for b in case.source) + "\n")
            stream.write(" ".join(f"{b:02x}" for b in case.expected) + "\n")
            records.append({"id": test_id, "name": case.name, "input_bytes": len(case.source),
                            "output_bytes": len(case.expected), "codec": case.codec,
                            "channel": case.channel, "wide": case.wide,
                            "checksum_mode": case.checksum_mode, "seed": case.seed,
                            "expected_error": case.error,
                            "descriptors_invalid": case.descriptors_invalid,
                            "read_fault": case.read_fault, "write_fault": case.write_fault})
    return records


def smoke_cases(block=17):
    cases = []
    for channel in range(4):
        for wide in (0, 1):
            raw = bytes((i * 37 + channel) & 255 for i in range(min(block, 17)))
            cases.append(Case(f"literal-ch{channel}-wide{wide}",
                              literal_block(raw), raw, channel=channel, wide=wide,
                              stalls=wide, seed=17 + channel))
    if block >= 17:
        encoded, raw = match_block(b"abc", 3, 14)
        cases.append(Case("overlap-offset3", encoded, raw))
        cases.append(Case("sg-one-byte", literal_block(b"abcdefg"), b"abcdefg",
                          source_sizes=[1] * 8, dest_sizes=[1] * 7, stalls=1))
    for codec in (1, 2, 3):
        raw = b"\x80\x3f\xff\xff" if codec == 2 and block >= 4 else (
            b"" if codec == 2 else b"\x33")
        frame = entropy_encode(raw, codec)
        cases.append(Case(f"entropy{codec}-encode", raw, frame, codec=codec,
                          decompress=0, capacity=len(frame)))
        cases.append(Case(f"entropy{codec}-decode", frame, raw, codec=codec))
    return cases


def lz4_cases(seed, block=65536):
    rng = random.Random(seed)
    cases = []
    for data in (b"", b"a", b"abc", b"123456789"):
        if len(data) <= block:
            for mode in (1, 2):
                cases.append(Case(f"known-checksum-{data.hex()}-mode{mode}",
                                  literal_block(data)+trailer(data, mode), data,
                                  checksum_mode=mode, checksum_value=checksum(data, mode)))
    for length in (0, 1, 3, 4, 7, 8, 15, 16, 254, 255, 256):
        if length > block:
            continue
        raw = bytes(rng.randrange(256) for _ in range(length))
        for mode in (0, 1, 2):
            cases.append(Case(f"literal-{length}-checksum{mode}",
                              literal_block(raw) + trailer(raw, mode), raw,
                              checksum_mode=mode, checksum_value=checksum(raw, mode),
                              channel=(length + mode) & 3, wide=mode & 1))
    for offset in (*range(1, 10), 15, 16, 255, 256, 65535):
        for length in (4, 7, 8, 9, 18, 19, 255, 256):
            if offset + length > block:
                continue
            prefix = bytes(rng.randrange(256) for _ in range(offset))
            encoded, raw = match_block(prefix, offset, length)
            cases.append(Case(f"match-offset{offset}-len{length}", encoded, raw,
                              channel=offset & 3, wide=1, stalls=1, seed=seed))
    if block == 65536:
        encoded, raw = match_block(bytes((i * 13) & 255 for i in range(65532)),
                                   65532, 4)
        cases.append(Case("full-history-window", encoded, raw))
        # Offset 65535 is legal only with 65535 bytes of private history.
        encoded, raw = match_block(bytes((i * 7) & 255 for i in range(65535)),
                                   65535, 4, limit=65539)
        cases.append(Case("offset65535-block-overflow", encoded, b"", error=5,
                          capacity=65539))
    for i in range(64):
        length = rng.randrange(min(block, 4096) + 1)
        raw = bytes(rng.randrange(256) for _ in range(length))
        mode = i % 3
        cases.append(Case(f"random-seed{seed}-{i}", literal_block(raw)+trailer(raw, mode),
                          raw, channel=i & 3, wide=(i >> 2) & 1, checksum_mode=mode,
                          checksum_value=checksum(raw, mode), stalls=1, seed=seed))
    return cases


def lz4_negative_cases(block=65536):
    cases = []
    malformed = [("terminal-literal-token", b"\x10"),
                 ("terminal-literal-extension", b"\xf0\0"),
                 ("literal-extension-continuation", b"\xf0\xff"),
                 ("truncated-literal", b"\x30ab"),
                 ("offset-low-truncation", b"\x10a\x01"),
                 ("offset-high-truncation", b"\x10a\x01\0"),
                 ("match-extension-truncation", b"\x1fa\x01\0\xff"),
                 ("zero-offset", b"\x10a\0\0\0"),
                 ("unavailable-history", b"\x10a\x02\0\0")]
    for name, source in malformed:
        try:
            lz4_decode(source, block)
        except CodecError as exc:
            cases.append(Case(name, source, b"", error=exc.code, capacity=block))
        else:
            raise AssertionError(f"negative reference accepted {name}")
    raw = b"x" * min(17, block)
    if len(raw) > 1:
        cases.append(Case("capacity-one-short", literal_block(raw), b"",
                          capacity=len(raw)-1, error=9))
    cases.append(Case("block-limit", literal_block(bytes(block+1)), b"", error=5,
                      capacity=block+1))
    for codec in range(5):
        raw = b"\x81\xbf\xff\x7f" if codec == 2 else b"123456789"
        if len(raw) > block:
            raw = b"" if codec == 2 else b"a"
        for mode in (1, 2):
            source = (literal_block(raw) if codec == 0 else entropy_encode(
                raw, codec, intermediate=lz4_compress(raw) if codec == 4 else None))
            corrupt = bytearray(trailer(raw, mode))
            corrupt[0] ^= 1
            cases.append(Case(f"checksum-mismatch-codec{codec}-mode{mode}",
                              source+corrupt, b"", codec=codec,
                              checksum_mode=mode, error=7,
                              capacity=max(1, len(raw))))
    return cases


def descriptor_cases(block=65536, depth=16):
    raw = bytes(range(min(17, block)))
    cases = []
    encoded = literal_block(raw)
    cases += [Case("zero-source-segment", encoded, b"", error=8,
                   source_sizes=[0], descriptors_invalid=True),
              Case("wrong-source-sum", encoded, b"", error=8,
                   source_sizes=[len(encoded)+1], descriptors_invalid=True),
              Case("wrong-destination-sum", encoded, b"", error=8, capacity=17,
                   dest_sizes=[16], descriptors_invalid=True),
              Case("source-address-overflow", encoded, b"", error=8,
                   source_addresses=[0xffffffffffffffff], descriptors_invalid=True),
              Case("destination-address-overflow", encoded, b"", error=8,
                   capacity=17, dest_addresses=[0xffffffffffffffff],
                   descriptors_invalid=True),
              Case("excess-source-count", b"\x00", b"", error=8,
                   source_sizes=[1]*(depth+1)),
              Case("excess-destination-count", b"\x00", b"", error=8,
                   capacity=depth+1, dest_sizes=[1]*(depth+1)),
              Case("zero-destination-count", b"\x00", b"", error=8,
                   dest_sizes=[]),
              Case("zero-destination-capacity", b"\x00", b"", error=8, capacity=0)]
    for codec in (5, 6, 7):
        cases.append(Case(f"invalid-codec{codec}", b"\x00", b"", codec=codec, error=8))
    cases.append(Case("invalid-checksum-mode", b"\x00", b"", checksum_mode=3, error=8))
    cases.append(Case("odd-BF16-encoding", b"a", b"", codec=2, decompress=0, error=8))
    if depth >= 3 and block >= 17:
        cases.append(Case("non-power-two-segments", encoded, raw, stalls=1,
                          source_sizes=[3, 7, len(encoded)-10], dest_sizes=[3, 7, 7]))
    if depth == 16 and block >= 15:
        data = bytes(range(15))
        cases.append(Case("sixteen-single-byte-source-segments", literal_block(data), data,
                          source_sizes=[1]*16, dest_sizes=[1]*15, stalls=1))
        data = bytes(range(16))
        cases.append(Case("sixteen-single-byte-destination-segments", literal_block(data), data,
                          dest_sizes=[1]*16, stalls=1))
    for transport in (0, 1):
        for direction in ("read", "write"):
            cases.append(Case(f"{direction}-bus-error-wide{transport}", encoded, b"",
                              wide=transport, error=10, capacity=max(1, len(raw)),
                              read_fault=1 if direction == "read" else 0,
                              write_fault=1 if direction == "write" else 0,
                              stalls=1))
    return cases


def performance_cases(parent=False):
    raw = bytes((i * 37 + 11) & 255 for i in range(32768))
    encoded, matched = match_block(bytes(range(16)), 16, 32768 - 16)
    cases = []
    for name, block, decoded in (("literal-heavy", literal_block(raw), raw),
                                  ("match-heavy", encoded, matched)):
        for mode in (0, 1, 2):
            cases.append(Case(f"{name}-checksum{mode}",
                              block + trailer(decoded, mode), decoded,
                              wide=0 if parent else 1, checksum_mode=mode,
                              checksum_value=checksum(decoded, mode)))
    return cases


def codec_pair(raw, codec, name, checksum_mode=0, **kwargs):
    if codec == 0:
        encoded = lz4_compress(raw)
    elif codec == 4:
        encoded = entropy_encode(raw, 4, intermediate=lz4_compress(raw))
    else:
        encoded = entropy_encode(raw, codec)
    if codec:
        assert entropy_decode(encoded, codec) == raw
    check = checksum(raw, checksum_mode)
    frame = encoded + trailer(raw, checksum_mode)
    return [Case(name + "-encode", raw, frame, codec=codec, decompress=0,
                 checksum_mode=checksum_mode, checksum_value=check, **kwargs),
            Case(name + "-decode", frame, raw, codec=codec,
                 checksum_mode=checksum_mode, checksum_value=check, **kwargs)]


def entropy_cases(seed, maximum=False):
    rng = random.Random(seed)
    cases = []
    for codec in (1, 2, 3, 4):
        fixtures = [b"", b"\0\0", bytes(range(256)), b"\x55" * 64]
        if codec == 2:
            fixtures += [b"\0\0\0\x80\x01\0\xff\x7f\0\x7f\xff\xff"]
        if codec == 3:
            fixtures += [bytes(a | (b << 4) for a in range(16) for b in range(16))]
        for i, raw in enumerate(fixtures):
            cases += codec_pair(raw, codec, f"directed-mode{codec}-{i}",
                                checksum_mode=i % 3, channel=i & 3, wide=i & 1,
                                stalls=i & 1, seed=seed)
    for i in range(64):
        codec = 1 + i % 4
        length = rng.randrange(4097)
        if codec == 2:
            length &= ~1
            raw = b"".join(bytes([(rng.randrange(128) | 128), 0x3F])
                           for _ in range(length // 2))
        elif codec == 3:
            raw = bytes(rng.choice((0x00, 0xF0, 0x0F, 0xFF)) for _ in range(length))
        else:
            raw = bytes(rng.randrange(256) for _ in range(length))
        cases += codec_pair(raw, codec, f"seed{seed}-mode{codec}-random{i}",
                            checksum_mode=i % 3, channel=i & 3, wide=(i >> 2) & 1,
                            stalls=1, seed=seed)
    for length in range(8, 16):
        raw = b"\x33" * length
        cases += codec_pair(raw, 1, f"final-bit-remainder{length & 7}", seed=seed)
    # A complete comb-shaped tree exercises the maximum accepted depth and
    # codebooks selected independently of the encoder's histogram.
    lengths = list(range(1, 15)) + [15, 15] + [0]*240
    raw = bytes(range(16))*3
    frame = entropy_encode(raw, 1, lengths=lengths)
    cases.append(Case("independent-complete-length15-table", frame, raw, codec=1))
    frame = entropy_encode(b"ab"*33, 1, lengths=[8]*256)
    cases.append(Case("independent-full-fixed-table", frame, b"ab"*33, codec=1))
    fixtures = [(1, b"A" * 8192, 0.50),
                (2, b"".join(bytes([128 | (i & 127), 0x3F | ((i & 1) << 7)])
                            for i in range(4096)), 0.70),
                (3, bytes(8192), 0.35)]
    for codec, raw, ratio in fixtures:
        encoded = entropy_encode(raw, codec)
        assert len(encoded) <= ratio * len(raw)
        cases += codec_pair(raw, codec, f"compressibility-mode{codec}", seed=seed)
    if maximum:
        for codec in range(5):
            raw = bytes((i * 13 + (i >> 9)) & 255 for i in range(65536))
            for mode in range(3):
                cases += codec_pair(raw, codec, f"maximum-mode{codec}-checksum{mode}",
                                    checksum_mode=mode, seed=seed)
        all_bf16 = b"".join(i.to_bytes(2, "little") for i in range(65536))
        for i in range(2):
            cases += codec_pair(all_bf16[i * 65536:(i + 1) * 65536], 2,
                                f"all-BF16-patterns-half{i}", seed=seed)
    return cases


def malformed_entropy_cases():
    """Balanced, byte-distinct malformed frames checked before DUT execution."""
    cases = []
    base = entropy_encode(b"\x05"*9, 1)
    groups = {}

    def add(group, name, frame, codec=1):
        try:
            entropy_decode(frame, codec)
        except CodecError as exc:
            assert exc.code == 11
        else:
            raise AssertionError(f"negative reference accepted {name}")
        groups[group] = groups.get(group, 0)+1
        cases.append(Case(f"malformed-{group}-{name}", bytes(frame), b"",
                          codec=codec, error=11, capacity=65536,
                          channel=len(cases) & 3, wide=(len(cases) >> 2) & 1))

    for i in range(20):
        frame = bytearray(base)
        field = i % 8
        frame[field] ^= 1+(i//8)
        add("header", str(i), frame)
    for i in range(20):
        frame = bytearray(base)
        frame[20+5] = 2+(i % 14)  # forbidden singleton depth
        frame[20+6+i] = 16 if i & 1 else 1  # oversubscription or range error
        add("codebook", str(i), frame)
    for i in range(20):
        frame = bytearray(base)
        offset = (8, 12, 16)[i % 3]
        struct.pack_into("<I", frame, offset, (0xffffffff, 65537, 0, 10)[i % 4])
        add("length-count", str(i), frame)
    for i in range(20):
        # Include table truncation and payload truncation, not a synthetic
        # source-count label. Short header cases are tested separately.
        add("truncation", str(i), base[:20+i*13])
    for i in range(20):
        frame = bytearray(entropy_encode(bytes([i])*9, 1))
        frame[276] = 0x80
        add("invalid-code", str(i), frame)
    for i in range(20):
        frame = bytearray(entropy_encode(bytes([i])*9, 1))
        frame[-1] |= 1+(i % 127)
        add("padding", str(i), frame)
    for codec in (1, 2, 3, 4):
        raw = b"\x80\x3f"*4
        frame = entropy_encode(raw, codec,
                               intermediate=lz4_compress(raw) if codec == 4 else None)
        add("extra-payload", f"mode{codec}", frame+b"\0", codec)
    frame = bytearray(entropy_encode(b"\x80\x3f", 2))
    struct.pack_into("<I", frame, 8, 1)
    add("odd-BF16-header", "odd", frame, 2)
    for length in range(1, 20):
        add("short-header", str(length), base[:length])
    assert len(cases) >= 100 and all(groups[g] >= 20 for g in
        ("header", "codebook", "length-count", "truncation", "invalid-code", "padding"))
    return cases
