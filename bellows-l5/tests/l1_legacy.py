"""Independent canonical-code model for the inherited BL4H byte format."""

import struct

from l1_oracle import decode_lz4


def literal_lz4(raw):
    size = len(raw)
    encoded = bytearray((min(15, size) << 4,))
    if size >= 15:
        remaining = size - 15
        while remaining >= 255:
            encoded.append(255)
            remaining -= 255
        encoded.append(remaining)
    return bytes(encoded) + raw


def _codes(lengths):
    if any(not 0 <= width <= 15 for width in lengths):
        raise ValueError("illegal inherited Huffman code length")
    ordered = sorted((width, symbol) for symbol, width in enumerate(lengths) if width)
    result, code, previous = {}, 0, 0
    for width, symbol in ordered:
        code <<= width - previous
        if code >= 1 << width:
            raise ValueError("oversubscribed inherited Huffman code")
        result[symbol] = (code, width)
        code += 1
        previous = width
    return result


def encode_huffman(raw, codec):
    if codec not in (1, 2, 3, 4):
        raise ValueError("not an inherited Huffman codec")
    residual = b""
    if codec == 2:
        if len(raw) & 1:
            raise ValueError("odd BF16 input")
        symbols = bytes(((raw[p + 1] & 127) << 1) | (raw[p] >> 7)
                        for p in range(0, len(raw), 2))
        residual = bytes((raw[p + 1] & 128) | (raw[p] & 127)
                         for p in range(0, len(raw), 2))
    elif codec == 3:
        symbols = bytes(n for byte in raw for n in (byte & 15, byte >> 4))
    elif codec == 4:
        symbols = literal_lz4(raw)
    else:
        symbols = raw
    width = 4 if codec == 3 else 8
    lengths = [width] * (1 << width)
    codes = _codes(lengths)
    bits, bit_count = 0, 0
    for symbol in symbols:
        code, count = codes[symbol]
        bits = (bits << count) | code
        bit_count += count
    padding = (-bit_count) % 8
    payload = (bits << padding).to_bytes((bit_count + 7) // 8, "big")
    return (b"BL4H" + bytes((1, codec, 0, 0))
            + struct.pack("<III", len(raw), len(symbols), bit_count)
            + bytes(lengths) + residual + payload)


def decode_huffman(encoded, codec):
    if len(encoded) < 20 or encoded[:8] != b"BL4H" + bytes((1, codec, 0, 0)):
        raise ValueError("invalid inherited Huffman header")
    raw_size, symbol_size, bit_count = struct.unpack_from("<III", encoded, 8)
    table_size = 16 if codec == 3 else 256
    residual_size = raw_size // 2 if codec == 2 else 0
    start = 20 + table_size + residual_size
    if len(encoded) != start + (bit_count + 7) // 8:
        raise ValueError("inherited Huffman frame size mismatch")
    lengths = encoded[20:20 + table_size]
    codes = _codes(lengths)
    reverse = {(count, code): symbol for symbol, (code, count) in codes.items()}
    residual = encoded[20 + table_size:start]
    payload = encoded[start:]
    decoded, current, depth = bytearray(), 0, 0
    for pos in range(bit_count):
        current = (current << 1) | ((payload[pos // 8] >> (7 - pos % 8)) & 1)
        depth += 1
        if (depth, current) in reverse:
            decoded.append(reverse[(depth, current)])
            current, depth = 0, 0
        elif depth >= 15:
            raise ValueError("invalid inherited Huffman codeword")
    if depth or len(decoded) != symbol_size:
        raise ValueError("inherited Huffman symbol count/termination mismatch")
    if codec == 2:
        if raw_size % 2 or symbol_size != raw_size // 2:
            raise ValueError("invalid BF16 sizes")
        raw = bytes(byte for symbol, saved in zip(decoded, residual)
                    for byte in (((symbol & 1) << 7) | (saved & 127),
                                 (saved & 128) | (symbol >> 1)))
    elif codec == 3:
        if symbol_size != raw_size * 2 or any(symbol > 15 for symbol in decoded):
            raise ValueError("invalid nibble symbols")
        raw = bytes(decoded[p] | (decoded[p + 1] << 4) for p in range(0, symbol_size, 2))
    elif codec == 4:
        raw = decode_lz4(decoded)
    elif codec == 1:
        raw = bytes(decoded)
    else:
        raise ValueError("invalid inherited Huffman codec")
    if len(raw) != raw_size:
        raise ValueError("inherited Huffman reconstructed-size mismatch")
    return raw
