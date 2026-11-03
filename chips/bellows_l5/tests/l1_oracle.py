"""Independent integer/checksum and library oracles; no DUT tables are read."""

import ctypes
import ctypes.util
import struct
import zlib


def _crc_table():
    rows = []
    for byte in range(256):
        state = byte
        for _ in range(8):
            state = (state >> 1) ^ (0xEDB88320 if state & 1 else 0)
        rows.append(state)
    return tuple(rows)


CRC_TABLE = _crc_table()


def crc32(data):
    state = 0xFFFFFFFF
    for byte in data:
        state = (state >> 8) ^ CRC_TABLE[(state ^ byte) & 255]
    return state ^ 0xFFFFFFFF


def rotl(x, n, width):
    mask = (1 << width) - 1
    return ((x << n) | (x >> (width - n))) & mask


def xxhash(data, width):
    """xxHash seed zero, expressed directly using the published integer rules."""
    if width == 64:
        primes = (0x9E3779B185EBCA87, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9,
                  0x85EBCA77C2B2AE63, 0x27D4EB2F165667C5)
        word, stripe, rotation = 8, 32, 31
    elif width == 32:
        primes = (0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1)
        word, stripe, rotation = 4, 16, 13
    else:
        raise ValueError(width)
    p1, p2, p3, p4, p5 = primes
    mask = (1 << width) - 1

    def round_(acc, value):
        return rotl((acc + value * p2) & mask, rotation, width) * p1 & mask

    def load(pos, count):
        return int.from_bytes(data[pos:pos + count], "little")

    pos = 0
    if len(data) >= stripe:
        lanes = [(p1 + p2) & mask, p2, 0, (-p1) & mask]
        while pos + stripe <= len(data):
            for i in range(4):
                lanes[i] = round_(lanes[i], load(pos, word))
                pos += word
        h = sum(rotl(v, r, width) for v, r in zip(lanes, (1, 7, 12, 18))) & mask
        if width == 64:
            for v in lanes:
                h = ((h ^ round_(0, v)) * p1 + p4) & mask
    else:
        h = p5
    h = (h + len(data)) & mask
    if width == 64:
        while pos + 8 <= len(data):
            h = (rotl(h ^ round_(0, load(pos, 8)), 27, 64) * p1 + p4) & mask
            pos += 8
    while pos + 4 <= len(data):
        if width == 64:
            h = (rotl(h ^ (load(pos, 4) * p1 & mask), 23, 64) * p2 + p3) & mask
        else:
            h = rotl((h + load(pos, 4) * p3) & mask, 17, 32) * p4 & mask
        pos += 4
    while pos < len(data):
        if width == 64:
            h = rotl(h ^ (data[pos] * p5 & mask), 11, 64) * p1 & mask
        else:
            h = rotl((h + data[pos] * p5) & mask, 11, 32) * p1 & mask
        pos += 1
    if width == 64:
        h = ((h ^ (h >> 33)) * p2) & mask
        h = ((h ^ (h >> 29)) * p3) & mask
        return h ^ (h >> 32)
    h = ((h ^ (h >> 15)) * p2) & mask
    h = ((h ^ (h >> 13)) * p3) & mask
    return h ^ (h >> 16)


def private_checksum(data, mode):
    if mode == 0:
        return 0
    if mode == 1:
        return xxhash(data, 32)
    if mode == 2:
        return crc32(data)
    raise ValueError(mode)


def frame(raw, block=None, block_type=0):
    """Produce the frozen RFC header, one final block and real XXH64 trailer."""
    body = raw if block is None else block
    block_size = len(raw) if block_type == 1 else len(body)
    return (bytes.fromhex("28b52ffd8438") + struct.pack("<I", len(raw))
            + ((block_size << 3) | (block_type << 1) | 1).to_bytes(3, "little")
            + body + struct.pack("<I", xxhash(raw, 64) & 0xFFFFFFFF))


def rle_sequence_frame():
    """One raw literal 'a', LL=1, ML=7, ordinary distance=1, RLE tables.

    Sequence mode byte 0x54 selects RLE separately for LL, OF and ML.
    OF code 2 has base 4 and two zero extra bits; offset value 4 is distance 1.
    The reverse stream is 00 followed by its one stop bit, byte 0x04.
    """
    return frame(b"a" * 8, bytes((8, 97, 1, 0x54, 1, 2, 4, 4)), 2)


class Libraries:
    def __init__(self):
        self.zstd = ctypes.CDLL(self._find("zstd"))
        self.xx = ctypes.CDLL(self._find("xxhash"))
        self.lz4 = ctypes.CDLL(self._find("lz4"))
        self.zstd.ZSTD_createDCtx.restype = ctypes.c_void_p
        self.zstd.ZSTD_freeDCtx.argtypes = [ctypes.c_void_p]
        self.zstd.ZSTD_decompress_usingDict.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
            ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        self.zstd.ZSTD_decompress_usingDict.restype = ctypes.c_size_t
        self.zstd.ZSTD_DCtx_loadDictionary_advanced.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int]
        self.zstd.ZSTD_DCtx_loadDictionary_advanced.restype = ctypes.c_size_t
        self.zstd.ZSTD_decompressDCtx.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.c_void_p, ctypes.c_size_t]
        self.zstd.ZSTD_decompressDCtx.restype = ctypes.c_size_t
        self.zstd.ZSTD_isError.argtypes = [ctypes.c_size_t]
        self.zstd.ZSTD_isError.restype = ctypes.c_uint
        self.zstd.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
        self.zstd.ZSTD_getErrorName.restype = ctypes.c_char_p
        self.zstd.ZSTD_versionString.restype = ctypes.c_char_p
        self.xx.XXH_versionNumber.restype = ctypes.c_uint
        self.lz4.LZ4_versionString.restype = ctypes.c_char_p
        self.lz4.LZ4_decompress_safe.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.lz4.LZ4_decompress_safe.restype = ctypes.c_int
        for width, out in ((32, ctypes.c_uint32), (64, ctypes.c_uint64)):
            fn = getattr(self.xx, f"XXH{width}")
            fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, out]
            fn.restype = out

    @staticmethod
    def _find(name):
        path = ctypes.util.find_library(name)
        if path is None:
            raise RuntimeError(f"required installed shared library not found: {name}")
        return path

    def versions(self):
        return {"libzstd": self.zstd.ZSTD_versionString().decode(),
                "liblz4": self.lz4.LZ4_versionString().decode(),
                "libxxhash": self.xx.XXH_versionNumber()}

    def check_hash(self, raw):
        assert crc32(raw) == zlib.crc32(raw), ("CRC32", len(raw))
        for width in (32, 64):
            observed = getattr(self.xx, f"XXH{width}")(raw, len(raw), 0)
            expected = xxhash(raw, width)
            assert observed == expected, (width, len(raw), observed, expected)

    def decompress_zstd(self, encoded, capacity, dictionary=b""):
        context = self.zstd.ZSTD_createDCtx()
        if not context:
            raise MemoryError("ZSTD_createDCtx")
        try:
            output = ctypes.create_string_buffer(max(1, capacity))
            # ZSTD_dct_rawContent=1: dictionary magic-looking bytes are still
            # raw history, never a trained entropy dictionary.
            loaded = self.zstd.ZSTD_DCtx_loadDictionary_advanced(
                context, dictionary, len(dictionary), 0, 1)
            if self.zstd.ZSTD_isError(loaded):
                raise ValueError(self.zstd.ZSTD_getErrorName(loaded).decode())
            n = self.zstd.ZSTD_decompressDCtx(context, output, capacity, encoded, len(encoded))
            if self.zstd.ZSTD_isError(n):
                raise ValueError(self.zstd.ZSTD_getErrorName(n).decode())
            return output.raw[:n]
        finally:
            self.zstd.ZSTD_freeDCtx(context)

    def decompress_lz4(self, encoded, expected):
        output = ctypes.create_string_buffer(max(1, len(expected)))
        n = self.lz4.LZ4_decompress_safe(encoded, output, len(encoded), max(1, len(expected)))
        assert n == len(expected), (n, len(expected))
        assert output.raw[:n] == expected


def decode_lz4(encoded):
    """Independent byte-oriented LZ4 block decoder with incremental overlap."""
    pos, output = 0, bytearray()

    def length(base):
        nonlocal pos
        n = base
        if base == 15:
            while True:
                if pos >= len(encoded):
                    raise ValueError("truncated LZ4 length")
                byte = encoded[pos]
                pos += 1
                n += byte
                if byte != 255:
                    break
        return n

    while pos < len(encoded):
        token = encoded[pos]
        pos += 1
        n = length(token >> 4)
        if pos + n > len(encoded):
            raise ValueError("truncated LZ4 literals")
        output.extend(encoded[pos:pos + n])
        pos += n
        if pos == len(encoded):
            return bytes(output)
        if pos + 2 > len(encoded):
            raise ValueError("truncated LZ4 offset")
        offset = int.from_bytes(encoded[pos:pos + 2], "little")
        pos += 2
        if not 0 < offset <= len(output):
            raise ValueError("invalid LZ4 offset")
        n = length(token & 15) + 4
        for _ in range(n):
            output.append(output[-offset])
    return bytes(output)
