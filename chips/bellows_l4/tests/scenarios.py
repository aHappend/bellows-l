"""Requirement-directed fixtures, independent expected bytes and descriptors."""

from dataclasses import dataclass
import random

from reference import (checksum, entropy_decode, entropy_encode, literal_block,
                       lz4_compress, match_block, trailer)


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
                         + f"{len(src)} {len(dst)} {case.stalls} {case.seed}\n")
            stream.write(" ".join(map(str, src + dst)) + "\n")
            stream.write(" ".join(f"{b:02x}" for b in case.source) + "\n")
            stream.write(" ".join(f"{b:02x}" for b in case.expected) + "\n")
            records.append({"id": test_id, "name": case.name, "input_bytes": len(case.source),
                            "output_bytes": len(case.expected), "codec": case.codec,
                            "channel": case.channel, "wide": case.wide,
                            "checksum_mode": case.checksum_mode, "seed": case.seed,
                            "expected_error": case.error})
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
    for i in range(64):
        length = rng.randrange(min(block, 4096) + 1)
        raw = bytes(rng.randrange(256) for _ in range(length))
        mode = i % 3
        cases.append(Case(f"random-seed{seed}-{i}", literal_block(raw)+trailer(raw, mode),
                          raw, channel=i & 3, wide=(i >> 2) & 1, checksum_mode=mode,
                          checksum_value=checksum(raw, mode), stalls=1, seed=seed))
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
