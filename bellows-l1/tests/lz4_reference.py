"""Independent raw-block construction and unbounded-integer decoding.

The format deliberately requires a terminal literal sequence; a match cannot
terminate a block. Error results preserve the literal prefix, including a
prematurely last-marked literal, and consume the remaining framed input.
"""

from dataclasses import dataclass


MAX_LENGTH = (1 << 32) - 1


@dataclass(frozen=True)
class Decoded:
    output: bytes
    error: int
    detection: int | None = None


def extension(length: int, base: int) -> bytes:
    if length < base:
        return b""
    quotient, remainder = divmod(length - base, 255)
    return b"\xff" * quotient + bytes([remainder])


def sequence(literals: bytes, offset: int, length: int) -> bytes:
    if not 1 <= offset <= 65535 or length < 4:
        raise ValueError("invalid encoder match")
    return (
        bytes([(min(len(literals), 15) << 4) | min(length - 4, 15)])
        + extension(len(literals), 15)
        + literals
        + offset.to_bytes(2, "little")
        + extension(length, 19)
    )


def terminal(literals: bytes, ignored_nibble: int = 0) -> bytes:
    return (
        bytes([(min(len(literals), 15) << 4) | ignored_nibble])
        + extension(len(literals), 15)
        + literals
    )


def encode(parts: list[tuple[bytes, int, int]], tail: bytes) -> tuple[bytes, bytes]:
    """Construct blocks from explicit phrases, with separately built plaintext."""
    compressed = bytearray()
    plain = bytearray()
    for literals, offset, length in parts:
        plain.extend(literals)
        if offset > min(len(plain), 65536):
            raise ValueError("encoder phrase exceeds its dictionary")
        compressed.extend(sequence(literals, offset, length))
        # Periodic word construction differs from the decoder's byte-wise copy.
        period = bytes(plain[-offset:])
        plain.extend((period * ((length + offset - 1) // offset))[:length])
    compressed.extend(terminal(tail))
    plain.extend(tail)
    return bytes(compressed), bytes(plain)


def decode(block: bytes) -> Decoded:
    """Decode a bounded framed string, without any DUT state or cycle model."""
    if not block:
        raise ValueError("a framed input requires an accepted last byte")
    out = bytearray()
    position = 0

    def failure(code: int, where: int) -> Decoded:
        return Decoded(bytes(out), code, where)

    def read_length(value: int) -> tuple[int, Decoded | None]:
        nonlocal position
        while True:
            at = position
            if at >= len(block):
                raise AssertionError("boundary was not handled at its input byte")
            digit = block[at]
            position += 1
            if position == len(block):
                return value, failure(1, at)
            value += digit
            if value > MAX_LENGTH:
                return value, failure(4, at)
            if digit != 255:
                return value, None

    while position < len(block):
        at = position
        token = block[position]
        position += 1
        literal_length = token >> 4
        if position == len(block):
            return Decoded(bytes(out), 0) if literal_length == 0 else failure(1, at)
        if literal_length == 15:
            literal_length, error = read_length(15)
            if error is not None:
                return error
        # Copy in one slice while preserving the last accepted partial literal.
        remaining = len(block) - position
        taken = min(literal_length, remaining)
        out.extend(block[position:position + taken])
        position += taken
        if position == len(block):
            return (
                Decoded(bytes(out), 0)
                if taken == literal_length
                else failure(1, position - 1)
            )
        low_at = position
        lo = block[position]
        position += 1
        if position == len(block):
            return failure(1, low_at)
        high_at = position
        hi = block[position]
        position += 1
        if position == len(block):
            return failure(1, high_at)
        distance = lo + 256 * hi
        if distance == 0:
            return failure(2, high_at)
        if distance > min(len(out), 65536):
            return failure(3, high_at)
        match_length = 4 + (token & 15)
        if (token & 15) == 15:
            match_length, error = read_length(match_length)
            if error is not None:
                return error
        for _ in range(match_length):
            out.append(out[len(out) - distance])
    raise AssertionError("unterminated decoder path")


def arithmetic_boundaries() -> dict[str, int]:
    """Executable wider-integer checks, additional to real long RTL inputs."""
    comparisons = 0
    for base in (15, 19):
        count, remainder = divmod(MAX_LENGTH - base, 255)
        value = base + count * 255
        assert value <= MAX_LENGTH
        assert value + remainder == MAX_LENGTH
        assert value + remainder + 1 > MAX_LENGTH
        assert base + (count + 1) * 255 > MAX_LENGTH
        comparisons += 4
    return {"independent_arithmetic_comparisons": comparisons}
