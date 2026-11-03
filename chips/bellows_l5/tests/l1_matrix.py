"""Requirement-derived boundary and error fixtures, independent of RTL control."""

from dataclasses import replace
import random

from l1_oracle import frame, private_checksum
from l1_legacy import encode_huffman, literal_lz4
from l1_transport import Case
from l1_zstd import LL_BASE, ML_BASE, decode_frame, sequence_frame


SEEDS = (17, 89, 2026)
SIZES = (0, 1, 2, 3, 15, 16, 17, 255, 256, 257, 4095, 4096,
         8192, 16384, 65535, 65536)


def codec_matrix(geometry, seed, dictionary):
    block, depth, _, _ = geometry
    random_bytes = random.Random(seed).randbytes(max(1, min(block, 257)))
    result = []
    for codec in range(7):
        for mode in range(3):
            for wide in range(2):
                n = min(block, 17)
                if codec == 2:
                    n &= ~1
                raw = random_bytes[:n]
                tag = f"seed{seed}-c{codec}-m{mode}-w{wide}"
                common = dict(codec=codec, mode=mode, wide=wide,
                              channel=(codec + mode + wide) & 3,
                              dictionary_id=0x12345678 if codec == 6 else 0,
                              segments=depth)
                result.append(Case(tag + "-encode", raw, capacity=4*block+1024, **common))
                encoded = (literal_lz4(raw) if codec == 0 else
                           encode_huffman(raw, codec) if codec < 5 else frame(raw))
                if mode:
                    encoded += private_checksum(raw, mode).to_bytes(4, "little")
                result.append(Case(tag + "-decode", encoded, decompress=1,
                                   capacity=max(1, len(raw)), **common))
    return result


def boundaries(geometry, seed):
    block, depth, _, _ = geometry
    rng = random.Random(seed)
    result = []
    for size in sorted({n for n in SIZES if n <= block} | {block}):
        patterns = (
            bytes(size), b"Q"*size, (b"ab"*((size+1)//2))[:size],
            bytes(i & 255 for i in range(size)),
            bytes(0 if rng.randrange(8) else rng.randrange(256) for _ in range(size)),
            rng.randbytes(size),
        )
        for pattern, raw in enumerate(patterns):
            # Every required size/data class; avoid a redundant huge Cartesian product.
            codec = 5
            tag = f"boundary-seed{seed}-n{size}-pattern{pattern}"
            result.append(Case(tag, raw, codec=codec, mode=pattern % 3, wide=pattern & 1,
                               channel=pattern & 3, capacity=4*block+1024, segments=depth))
    return result


def errors(geometry, dictionary):
    block, depth, _, _ = geometry
    n = min(block, 16)
    raw = bytes(range(n))
    source = frame(raw)
    result = []
    for codec in range(7):
        data = raw[:len(raw) & ~1] if codec == 2 else raw
        common = dict(codec=codec, dictionary_id=0x12345678 if codec == 6 else 0,
                      capacity=1024)
        result.append(Case(f"invalid-mode-c{codec}", data, mode=3, error=8,
                           pre_dma=True, **common))
        if data:
            result.append(Case(f"source-sum-c{codec}", data, descriptor_error=1,
                               error=8, **common))
            result.append(Case(f"destination-sum-c{codec}", data, descriptor_error=2,
                               error=8, **common))
        for wide in (0, 1):
            if data:
                result.append(Case(f"read-fault-c{codec}-w{wide}", data, wide=wide,
                                   dma_error=1, error=10, **common))
            result.append(Case(f"write-fault-c{codec}-w{wide}", data, wide=wide,
                               dma_error=2, error=10, **common))
            for mode in (1, 2):
                encoded = (literal_lz4(data) if codec == 0 else
                           encode_huffman(data, codec) if codec < 5 else frame(data))
                corrupted = (private_checksum(data, mode) ^ 1).to_bytes(4, "little")
                result.append(Case(f"private-checksum-c{codec}-w{wide}-m{mode}",
                                   encoded+corrupted, decompress=1, mode=mode, wide=wide,
                                   error=7, **common))
        result.append(Case(f"zero-capacity-c{codec}", data, error=8, pre_dma=True,
                           **{**common, "capacity": 0}))
        result.append(Case(f"excess-segments-c{codec}", data, segments=depth+1,
                           error=8, pre_dma=True, **common))
        if codec == 2:
            result.append(Case("odd-bf16", b"x", error=8, pre_dma=True, **common))
        result.append(Case(f"recovery-c{codec}", data, **common))
    result.append(Case("invalid-codec", raw, codec=7, capacity=1024, error=8, pre_dma=True))
    for codec in (5, 6):
        common = dict(codec=codec, decompress=1, capacity=max(1, n),
                      dictionary_id=0x12345678 if codec == 6 else 0)
        bad_checksum = source[:-1] + bytes((source[-1] ^ 128,))
        result.append(Case(f"checksum-c{codec}", bad_checksum, error=7, **common))
        if n > 1:
            result.append(Case(f"capacity-c{codec}", source, error=9,
                               **{**common, "capacity": n-1}))
        result.append(Case(f"exact-capacity-c{codec}", source, **common))
        too_big = bytearray(source)
        too_big[6:10] = (block+1).to_bytes(4, "little")
        result.append(Case(f"decoded-limit-c{codec}", bytes(too_big), error=5, **common))
        result.append(Case(f"source-limit-c{codec}", bytes(2*block+1025), error=8,
                           pre_dma=True, **common))
        result.append(Case(f"block-limit-c{codec}", bytes(block+1), codec=codec,
                           capacity=1024, error=8, pre_dma=True,
                           dictionary_id=common["dictionary_id"]))
        nonfinal = bytearray(source)
        nonfinal[10] &= 254
        result.append(Case(f"nonfinal-c{codec}", bytes(nonfinal), error=12, **common))
        result.append(Case(f"trailing-c{codec}", source+b"\0", error=11, **common))
        result.append(Case(f"recovery-final-c{codec}", source, **common))
    result.append(Case("wrong-dictionary-id", raw, codec=6, dictionary_id=1,
                       capacity=1024, error=13, pre_dma=True))
    expanded = []
    for case in result:
        expanded.append(case)
        if case.error:
            codec = 5 if case.codec == 7 else case.codec
            expanded.append(Case("recovery-" + case.name,
                                 raw[:len(raw)&~1] if codec == 2 else raw,
                                 codec=codec, capacity=1024,
                                 dictionary_id=0x12345678 if codec == 6 else 0))
    return expanded


def sequence_boundaries(geometry, libraries):
    block = geometry[0]
    vectors = []
    for base in LL_BASE:
        for ll in (max(0, base-1), base, base+1):
            if ll+3 <= block and ll:
                literals = bytes(i & 255 for i in range(ll))
                vectors.append((f"ll{ll}", sequence_frame(literals, [(ll, 3, 4)])))
    for base in ML_BASE:
        for ml in (max(3, base-1), base, base+1):
            if 1+ml <= block:
                vectors.append((f"ml{ml}", sequence_frame(b"a", [(1, ml, 4)])))
    for bit in range(1, 17):
        for distance in ((1 << bit)-1, 1 << bit, (1 << bit)+1):
            if distance+3 <= block:
                literals = bytes(i & 255 for i in range(distance))
                vectors.append((f"of{distance}", sequence_frame(
                    literals, [(distance, 3, distance+3)])))
    if block >= 32:
        # Initial reps {1,4,8}, their updates, ll=0 adjustment, rep1-1,
        # overlap offsets 1 and 2, and trailing literals.
        for seq in (
            [(8, 3, 1), (0, 4, 1), (0, 4, 2)],
            [(8, 3, 2), (0, 4, 3), (0, 4, 1)],
            [(8, 3, 3), (0, 4, 1), (0, 4, 2)],
            [(2, 9, 5), (0, 9, 1)],
        ):
            vectors.append((f"reps-{seq}", sequence_frame(b"abcdefgh"[:sum(s[0] for s in seq)], seq)))
    if block >= 4:
        literals = bytes(i & 255 for i in range(block-3))
        vectors.append(("maximum-ll", sequence_frame(literals, [(block-3, 3, 4)])))
        vectors.append(("maximum-ml", sequence_frame(b"a", [(1, block-1, 4)])))
        vectors.append(("maximum-of", sequence_frame(literals, [(block-3, 3, block)])))
    result, seen = [], set()
    for label, encoded in vectors:
        if encoded in seen:
            continue
        seen.add(encoded)
        expected = decode_frame(encoded, max_block=block).data
        if libraries.decompress_zstd(encoded, block) != expected:
            raise AssertionError(f"boundary oracle/library disagreement: {label}")
        result.append(Case(label, encoded, decompress=1, capacity=max(1, len(expected)), wide=1))
    return result


def dictionary_edges(geometry, dictionary, libraries):
    block = geometry[0]
    if block < 3 or not dictionary:
        return []
    result = []
    for distance in sorted({1, min(2, len(dictionary)), min(7, len(dictionary)), len(dictionary)}):
        length = min(block, distance + 8)
        if length < 3:
            continue
        source = sequence_frame(b"", [(0, length, distance+3)], dictionary=dictionary)
        expected = decode_frame(source, dictionary, block)
        if not expected.dictionary_matches or libraries.decompress_zstd(
                source, block, dictionary) != expected.data:
            raise AssertionError("dictionary crossing fixture lacks verified reference")
        result.append(Case(f"dictionary-distance{distance}", source, codec=6,
                           decompress=1, capacity=length, dictionary_id=0x12345678, wide=1))
    return result


def malformed_tables(libraries, dictionary=b""):
    from l1_zstd import FrameError
    valid = sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)], (1, 1, 1), dictionary)
    vectors = []
    for alphabet, symbol in enumerate((36, 32, 53)):
        source = bytearray(valid)
        source[18+alphabet] = symbol
        vectors.append((f"forbidden-rle-symbol-{alphabet}", bytes(source)))
    compressed = sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)], (2, 2, 2), dictionary)
    changed = bytearray(compressed)
    changed[18] |= 15
    vectors.append(("excessive-log", bytes(changed)))
    changed = bytearray(compressed)
    changed[18:21] = b"\xf0\xff\xff"
    vectors.append(("normalized-mass-overflow", bytes(changed)))
    # A complete frame around a deliberately truncated table section.
    vectors.append(("truncated-count-table", frame(b"a"*16, b"\x10aa\x02\xa8\x00", 2)))
    result = []
    for label, source in vectors:
        try:
            decode_frame(source, dictionary)
        except FrameError:
            pass
        else:
            raise AssertionError(f"malformed table fixture accepted by parser: {label}")
        try:
            libraries.decompress_zstd(source, 4096, dictionary)
        except ValueError:
            pass
        else:
            raise AssertionError(f"malformed table fixture accepted by libzstd: {label}")
        result.append(Case(label, source, codec=6 if dictionary else 5, decompress=1,
                           error=11, dictionary_id=0x12345678 if dictionary else 0))
        result.append(Case("recover-" + label, valid, codec=6 if dictionary else 5,
                           decompress=1, dictionary_id=0x12345678 if dictionary else 0))
    return result
