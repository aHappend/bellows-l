"""Requirement-to-stimulus map. Bins count only completed scoreboard cases."""

import random
from dataclasses import dataclass, field

from lz4_reference import MAX_LENGTH, decode, encode, sequence, terminal


@dataclass
class Case:
    name: str
    block: bytes
    expected: bytes
    error: int = 0
    tags: set[str] = field(default_factory=set)
    # Recovery order: 1 boundary first, 2 output first, 3 simultaneous.
    order: int = 0
    # Abort mode: 1 parser wait, 2 match active, 3 stalled output,
    # 4 discard; 5 missing required byte, 6 missing discard boundary.
    special: int = 0
    detection: int = -1

    def check(self) -> None:
        if self.special:
            return
        result = decode(self.block)
        assert result.output == self.expected, (self.name, "independent output")
        assert result.error == self.error, (self.name, result.error, self.error)
        self.detection = -1 if result.detection is None else result.detection


REQUIRED = {
    *(f"literal:{n}" for n in (0, 1, 14, 15, 16, 269, 270, 271, 524, 525)),
    *(f"match:{n}" for n in (4, 18, 19, 20, 269, 270, 274, 525)),
    *(f"offset:{n}" for n in (1, 2, 3, 255, 256, 257, 32768, 65535)),
    "extension:zero", "extension:two255", "overlap:lt", "overlap:eq",
    "overlap:gt", "history:all", "wrap:exact", "wrap:read", "wrap:three",
    "empty", "one-byte", "terminal:zero", "terminal:ignored", "mixed",
    "error:zero", "error:range", "error:stale",
    "truncated:token", "truncated:literal-extension", "truncated:literal",
    "truncated:offset-low", "truncated:offset-high", "truncated:match-extension",
    "overflow:literal", "overflow:match", "reset:parser", "reset:copy",
    "reset:output", "reset:discard", "waiting:byte", "waiting:boundary",
    "reset:status", "schedule:literal", "schedule:match",
    "recovery:boundary-first", "recovery:output-first", "recovery:simultaneous",
    "recovery:empty", "recovery:zero", "recovery:range",
    "recovery:literal-overflow", "recovery:match-overflow", "reuse",
}


def pattern(length: int, salt: int = 0) -> bytes:
    return bytes((i * 73 + (i >> 8) * 19 + salt) & 255 for i in range(length))


def good(name: str, parts: list[tuple[bytes, int, int]], tail: bytes,
         tags: set[str] | None = None) -> Case:
    block, plain = encode(parts, tail)
    return Case(name, block, plain, tags=tags or set())


def overflow(kind: str, *, last_on_overflow: bool = False) -> Case:
    base = 15 if kind == "literal" else 19
    count = (MAX_LENGTH - base) // 255 + 1
    header = b"\xf0" if kind == "literal" else b"\x1fR\x01\x00"
    prefix = b"" if kind == "literal" else b"R"
    # Actual 32-bit accumulator overflow, never a forced counter or narrow DUT.
    body = header + b"\xff" * count
    if last_on_overflow:
        return Case("overflow-last-" + kind, body, prefix, 1)
    return Case(
        "overflow-" + kind, body + b"\x10Z\x00",
        prefix, 4, {"overflow:" + kind, "recovery:" + kind + "-overflow"},
    )


def smoke() -> list[Case]:
    return [
        good("empty", [], b"", {"empty", "literal:0"}),
        good("literal", [], b"BELLOWS", {"literal"}),
        good("overlap", [(b"Q", 1, 70)], b"", {"overlap"}),
        Case("discard", b"\x30abc\x00\x00\x10Z\x00", b"abc", 2,
             {"recovery"}, order=1),
        good("reuse", [(b"ab", 2, 12)], b"!", {"reuse"}),
    ]


def directed(include_overflow: bool = True) -> list[Case]:
    cases = []
    for n in (0, 1, 14, 15, 16, 269, 270, 271, 524, 525):
        tags = {f"literal:{n}"}
        if n == 0:
            tags.add("empty")
        if n == 1:
            tags.update({"one-byte", "schedule:literal"})
        if n in (15, 270, 525):
            tags.add("extension:zero")
        if n == 525:
            tags.add("extension:two255")
        cases.append(good(f"literal-{n}", [], pattern(n), tags))
    cases.append(Case("ignored-terminal-nibble", b"\x0f", b"",
                      tags={"terminal:ignored", "terminal:zero"}))
    for n in (4, 18, 19, 20, 269, 270, 274, 525):
        tags = {f"match:{n}", "overlap:lt", "terminal:zero"}
        if n == 4:
            tags.add("schedule:match")
        cases.append(good(f"match-{n}", [(b"X", 1, n)], b"",
                          tags))
    cases.append(good("match-two-continuations", [(b"X", 1, 529)], b"",
                      {"extension:match-two255", "extension:match-zero"}))
    for offset in (1, 2, 3, 255, 256, 257, 32768, 65535):
        cases.append(good(f"offset-{offset}",
                          [(pattern(offset, 31), offset, max(4, min(offset, 20)))],
                          b"tail", {f"offset:{offset}", "history:all"}))
    cases.extend([
        good("equal-offset", [(pattern(20), 20, 20)], b"", {"overlap:eq"}),
        good("greater-offset", [(pattern(257), 257, 4)], b"", {"overlap:gt"}),
        good("exact-wrap", [], pattern(65536), {"wrap:exact"}),
        good("cross-wrap", [(pattern(65534), 3, 525)], b"", {"wrap:read"}),
        good("three-wraps-mixed",
             [(pattern(65530), 257, 65550), (pattern(3000), 65535, 65550)],
             pattern(1000), {"wrap:three", "mixed", "wrap:read"}),
        Case("zero-offset", b"\x30abc\x00\x00\x10Z\x00", b"abc", 2,
             {"error:zero", "recovery:zero", "recovery:boundary-first"}, 1),
        Case("range-offset", b"\x10R\x02\x00\x10Z\x00", b"R", 3,
             {"error:range", "recovery:range", "recovery:output-first"}, 2),
        Case("simultaneous", b"\x10S\x00\x00\x10Z\x00", b"S", 2,
             {"recovery:simultaneous"}, 3),
        Case("empty-prefix", b"\x00\x01\x00\x10Z\x00", b"", 3,
             {"recovery:empty"}, 1),
        good("history-before-stale-test", [], pattern(400), {"history-prime"}),
        Case("stale-history", b"\x00\x01\x00\x00", b"", 3, {"error:stale"}),
        Case("token-last", b"\x10", b"", 1, {"truncated:token"}),
        Case("extended-token-last", b"\xf0", b"", 1, {"truncated:token"}),
        Case("literal-extension-last", b"\xf0\x00", b"", 1,
             {"truncated:literal-extension"}),
        Case("literal-continuation-last", b"\xf0\xff", b"", 1,
             {"truncated:literal-extension"}),
        Case("premature-literal-last", b"\x30AB", b"AB", 1,
             {"truncated:literal"}),
        Case("offset-low-last", b"\x10A\x00", b"A", 1,
             {"truncated:offset-low"}),
        Case("offset-high-last-priority", b"\x10A\x00\x00", b"A", 1,
             {"truncated:offset-high"}),
        Case("valid-offset-high-last", b"\x10A\x01\x00", b"A", 1,
             {"truncated:offset-high"}),
        Case("range-offset-high-last", b"\x10A\x02\x00", b"A", 1,
             {"truncated:offset-high"}),
        Case("match-extension-last", b"\x1fA\x01\x00\x00", b"A", 1,
             {"truncated:match-extension"}),
        Case("match-continuation-last", b"\x1fA\x01\x00\xff", b"A", 1,
             {"truncated:match-extension"}),
        Case("reset-parser", b"\xf0", b"", tags={"reset:parser"}, special=1),
        Case("reset-copy", sequence(b"R", 1, 525), b"R" * 526,
             tags={"reset:copy"}, special=2),
        Case("reset-output", terminal(b"RST"), b"RST",
             tags={"reset:output"}, special=3),
        Case("reset-discard", b"\x10A\x00\x00", b"A",
             tags={"reset:discard"}, special=4, detection=3),
        Case("missing-byte", b"\xf0\xff", b"", tags={"waiting:byte"}, special=5),
        Case("missing-boundary", b"\x10A\x00\x00\x10Z", b"A",
             tags={"waiting:boundary"}, special=6, detection=3),
        Case("reset-status", b"\x00", b"", tags={"reset:status"}, special=7),
    ])
    if include_overflow:
        cases.extend([overflow("literal"), overflow("match"),
                      overflow("literal", last_on_overflow=True),
                      overflow("match", last_on_overflow=True)])
    # Clean reuse after every directed block, including each aborted epoch.
    expanded = []
    for case in cases:
        expanded.extend([case, good("reuse-after-" + case.name,
                                   [(b"uv", 2, 7)], b"!", {"reuse"})])
    return expanded


def randomized(seed: int) -> list[Case]:
    rng = random.Random(seed)
    cases = []
    for index in range(32):
        parts = []
        available = 0
        for _ in range(rng.randint(1, 9)):
            literals = rng.randbytes(rng.randint(1, 700))
            available += len(literals)
            offset = rng.randint(1, min(available, 65535))
            length = rng.randint(4, 1800)
            parts.append((literals, offset, length))
            available += length
        cases.append(good(f"random-{seed}-{index}", parts,
                          rng.randbytes(rng.randint(0, 300)), {"random"}))
    return cases
