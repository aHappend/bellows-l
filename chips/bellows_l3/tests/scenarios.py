"""Requirement-directed public transactions, independent of codec internals."""

import random

import oracle


def matrix_batches(block, seed, make_frame):
    rng = random.Random(seed)
    batches = []
    lengths = sorted(set(min(block, n) for n in (0, 1, 3, 4, 15, 16, 17, 31, 32, 33)))
    for batch in range(12):
        operation = bool((batch // 3) & 1)
        mode = batch % 3
        frames = []
        for channel in range(4):
            length = lengths[(batch * 4 + channel + seed) % len(lengths)]
            if batch in (0, 3) and channel == 3:
                length = block
            kind = (batch + channel) % 4
            if kind == 0:
                content = bytes(rng.randrange(256) for _ in range(length))
            elif kind == 1:
                content = bytes([65 + channel]) * length
            elif kind == 2:
                content = bytes((i % 3) + 32 for i in range(length))
            else:
                content = bytes((i * 193 + (i >> 3) * 17) & 255 for i in range(length))
            if batch in (0, 3) and channel == 3:
                content = b"Q" * length
            encoded = None
            if operation and length >= 12 and len(set(content)) == 1:
                encoded = oracle.periodic_block(content)
            frame = make_frame(1000 + batch * 4 + channel, content, operation,
                               mode, block=encoded)
            frame.require_matches = not operation and length >= 32 and len(set(content)) == 1
            frames.append(frame)
        batches.append(frames)
    return batches


def corruption_batches(make_frame):
    batches = []
    for mode in (1, 2):
        for bit in (0, 1, 7, 8, 15, 16, 23, 31):
            frames = []
            for channel in range(4):
                content = bytes((i * 43 + channel * 17) & 255 for i in range(33))
                f = make_frame(3000 + len(batches) * 4 + channel, content, True, mode)
                wire = bytearray(f.source)
                wire[len(wire) - 4 + bit // 8] ^= 1 << (bit % 8)
                f.source, f.error = bytes(wire), 7
                frames.append(f)
            batches.append(frames)
    return batches


def boundaries(make_frame):
    batches, current = [], []
    for op in (False, True):
        for length in (0, 1, 3, 4, 15, 16, 17, 31, 32, 33):
            content = bytes((i * 17 + 3) & 255 for i in range(length))
            current.append(make_frame(4000 + len(batches) * 4 + len(current),
                                      content, op, 1))
            if len(current) == 4:
                batches.append(current)
                current = []
    assert not current
    batches.append([make_frame(4100 + ch, (b"", b"123456789", b"abc", b"x")[ch],
                               bool(ch & 1), 2) for ch in range(4)])
    return batches


def errors(block, sg, make_frame):
    fixtures = []

    def add(frame):
        frame.identifier = 5000 + len(fixtures)
        fixtures.append(frame)
        return frame

    for payload, code in ((b"\x10", 1), (b"\xf0\xff", 1),
                          (b"\x10A\x00\x00\x00", 2),
                          (b"\x00\x01\x00\x00", 3)):
        f = make_frame(0, b"", True, 0)
        f.source, f.error = payload, code
        add(f)
    content = b"Z" * (block + 1)
    f = make_frame(0, content, True, 0, capacity=block + 1,
                   block=oracle.periodic_block(content))
    f.error = 5
    add(f)
    for op in (False, True):
        f = make_frame(0, b"abcdefghijklmnop", op, 0, capacity=1)
        f.error = 9
        add(f)
    for op in (False, True):
        for direction in ("read", "write"):
            f = make_frame(0, b"abcdefgh", op, 1)
            if direction == "read":
                f.bad_read = 0
            else:
                f.bad_write = 0
            f.error = 10
            add(f)
    f = make_frame(0, b"abc", True, 1)
    f.source, f.error = f.source[:-1], 1
    add(f)
    for field, value in (("mode", 3), ("command_ns", sg + 1),
                         ("command_nd", 0), ("command_nd", sg + 1),
                         ("command_capacity", 0), ("command_length", block + 1)):
        f = make_frame(0, b"x", False, 0)
        setattr(f, field, value)
        f.error, f.reject_command = 8, True
        add(f)
    f = make_frame(0, b"", False, 0)
    f.command_ns, f.error, f.reject_command = 1, 8, True
    add(f)
    f = make_frame(0, b"", True, 0)
    f.source, f.command_length, f.error, f.reject_command = b"", 0, 8, True
    add(f)
    for direction in ("source_segments", "destination_segments"):
        for descriptors in ([(0x1000, 0)], [(0x1000, 2)],
                            [(0xFFFFFFFFFFFFFFFF, 2)],
                            [(0x1000, 0xFFFFFFFF), (0x200000000, 2)]):
            f = make_frame(0, b"x", False, 0, capacity=1)
            setattr(f, direction, descriptors)
            f.error = 8
            add(f)
    while len(fixtures) % 4:
        add(make_frame(0, b"after-error", False, 2))
    batches = [fixtures[i:i + 4] for i in range(0, len(fixtures), 4)]
    batches.append([make_frame(5900 + c, b"recovered", bool(c & 1), c % 3)
                    for c in range(4)])
    return batches
