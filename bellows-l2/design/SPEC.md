# BELLOWS-L2 frozen design contract

## Scope and provenance

Top: `bellows_l2_top`. Target: Intel Arria 10 GX `10AX115N2F45E1SG`,
100 MHz or faster (clock period at most 10.0 ns). This is a design target,
not a measured timing result. The admitted work order is authoritative.
The three sources in `bellows_l1_reference/rtl/` are the supplied parent;
their deliverable copies under `rtl/` must remain byte-identical. No linked
intake source index or parent specification was supplied. Intake and historical
parent acceptance do not establish current acceptance.

The compressor buffers one bounded block, performs actual hardware hash-based
match finding, and emits standard raw LZ4, not an LZ4 frame. No throughput or
fixed end-to-end latency is promised. The decoder retains its independent
64-KiB rolling history and is not constrained by compressor capacity.

## Public interface

All signals are synchronous to `clk`; `rst_n` is asynchronous active-low reset.
All datapath quantities are unsigned. `MAX_BLOCK_BYTES` is an integer parameter,
default 65536, legal inclusive range 1..65536. Illegal values receive an explicit
parameter diagnostic before transactions; they are not silently clamped.

| Port group | Inputs | Outputs |
|---|---|---|
| Clock and mode | `clk`, `rst_n`, `roundtrip_enable` | none |
| Raw compressor input | `c_s_data[7:0]`, `c_s_keep`, `c_s_valid`, `c_s_last` | `c_s_ready` |
| Compressed output | `c_m_ready` | `c_m_data[7:0]`, `c_m_valid`, `c_m_last` |
| Compression status | `c_status_ready` | `c_status_valid`, `c_status_error[2:0]` |
| External decoder input | `d_s_data[7:0]`, `d_s_valid`, `d_s_last` | `d_s_ready` |
| Decoded output | `d_m_ready` | `d_m_data[7:0]`, `d_m_valid`, `d_m_last` |
| Decoder status | `d_status_ready` | `d_status_valid`, `d_status_error[2:0]` |

Unannotated signals are one bit. `bellows_l2_compressor` exposes `clk`, `rst_n`
and the compressor ports above with the `c_` prefix removed, with the same
parameter. Internal module contracts and exact local stages are defined in
`ARCHITECTURE.md`.

Mode zero is independent full duplex. Mode one directly routes the actual
compressor output into the preserved decoder; `d_s_ready` and all `c_m_*`
outputs are zero, and `c_m_ready` has no effect. Both statuses remain independently
observable. Mode changes are legal only at reset or when both lanes have no
active block, output, or outstanding status. The mode is not sampled per byte
or switched speculatively during an active transaction.

## Cycle & Degenerate-Boundary Table

| Situation | Pre-edge observation | Post-edge update |
|---|---|---|
| `valid=0` | No transfer regardless of ready | No transaction progress |
| `valid=1, ready=0` | No transfer; sender holds valid and payload including last/keep | Presented payload remains identical |
| `valid=1, ready=1` | Exactly one beat transfers | Counters/state advance once |
| Raw final byte | Accepted by collection state | Block length is registered; size calculation and processing start later |
| Empty raw block | One `keep=0,last=1` beat, ignored data | Length zero; eventual output is exactly `00` |
| Reset asserted | All public outputs, including ready and status, zero | All transactions abandoned; data RAM is not cleared |
| First clock after reset release | Ready can be high in collection/parser state | Only pre-edge accepted data progresses; no stale output/status |
| Capacity one | Empty or first-and-last single byte is legal | A second data byte causes error 5, even if it is final |
| Capacity 5 or 13 | Short-block literal encoding; first eligible match at length 13 | Match start limit and last-five rule apply without special aliasing |
| Capacity 257 | Absolute addresses, explicit length comparisons | No power-of-two address masking or binary-depth wrap |
| Data and status completion | No next raw input until compression status retires | Status acknowledgement returns collection to length zero |
| Table lookup plus insertion | Old entry is read, new position inserted at same edge | Candidate uses registered old entry, never the just-inserted position |
| Reset plus write/request | Reset wins ownership/control; RAM writes are reset-gated | No stale RAM contents acquire validity |
| Presented output retirement plus replacement | Retire only pre-edge valid and ready | Parent may replace on the same edge; compressor replay deliberately inserts bubbles |
| Error plus accepted final boundary | First error selected from this beat or retained earlier error | Discard ends; status appears without compressed output |

## Compression framing and errors

Normal blocks have `keep=1` on every accepted byte, with `last=1` only on the
final byte. A nonempty block cannot use an empty marker as its terminator.
Any other accepted `keep=0` is error 6. Exceeding capacity is error 5.
If both occur on one beat, malformed keep is evaluated first. Once an error
is detected, its code is retained while input is discarded through accepted
last. No compressed block is emitted. Status follows complete discard.

Success code is 0; compressor codes 1..4 and 7 are reserved. Successful
compression status cannot precede retirement of the final compressed byte.
Status is held until accepted. No next raw block is accepted before that
acknowledgement.

Decoder error codes and output-prefix behavior are unchanged: 0 success,
1 truncation, 2 zero offset, 3 unavailable history, 4 length overflow.
The parent drains to the input block boundary and retires its valid output
prefix before status. Empty decoded blocks produce no output beat and still
produce success status.

## Frozen hash and match rules

For four bytes at ascending visited source position `p`, compute
`h = b0 XOR rol8(b1,1) XOR rol8(b2,2) XOR rol8(b3,3)`.
There are exactly 256 direct-mapped entries, each with validity and its most
recent inserted absolute block position. Clear validity between blocks without
resetting position RAM. Read old entry then insert `p` on each visited start.
A candidate `q` is legal only when valid, `q<p`, offset `p-q` is 1..65535,
and all four bytes agree. Collisions can only lose opportunities.

Minimum match length is exactly four. Extend greedily against buffered original
input, including overlaps. A match resumes search at its end; skipped starts
are not inserted. A miss advances one byte. Literal anchor starts at zero
and advances to the end of each emitted match. Blocks shorter than 13 use
literal-only encoding. Otherwise match starts satisfy `p<=N-12`, and extension
ends at or before `N-5`. Every block ends in a literal-only sequence.

## Raw LZ4 encoding and fallback

Token high nibble is `min(literal_length,15)`. Match token low nibble is
`min(match_length-4,15)`; the final sequence low nibble is zero.
A saturated nibble has extension bytes: repeated 255 and a final remainder
0..254, including a zero terminator on exact multiples. Emit token, literal
extension if needed, literals, nonzero offset low byte then high byte, and
match extension if needed.

The empty block is one byte `00`. Literal-only size is `1+N`, plus
`floor((N-15)/255)+1` when `N>=15`. This formula is a format definition,
not hardware division. The implementation uses repeated registered subtraction.
Retain candidate encoding only if strictly smaller than literal-only encoding;
otherwise regenerate the complete literal-only encoding. No external fallback
flag is used. Candidate RAM has `2*MAX_BLOCK_BYTES+16` bytes. Legal candidate
encoding cannot exhaust this conservative bound; verification must assert that
fact rather than regard overflow as success.

Ratio is actual compressed bytes divided by nonempty original bytes, excluding
status. Each of repeated `A`, repeated `ABCD`, and repeated bytes 0..255 must
separately have ratio below one at lengths 4096 and 65536, with real matches.

## Acceptance and reproduction ownership

The Designer supplies `rtl/*.sv` and these two design documents. The Verifier
independently supplies `tests/*.py`, including `tests/verify.py`, and immediately
follows design handoff. From the delivered project root:

```
python3 tests/verify.py --output evidence/l1
```

The destination must be fresh. Required tools are Python 3, Icarus (`iverilog`,
`vvp`) and Yosys; exact versions must be recorded by the independent checks,
not assumed from this document. No external Python package is required.
Verifier owns the concrete targeted clean-directory reproduction invocation.
Only declared RTL, supplied reference RTL, design documents, and test Python
files are reproduction inputs; generated outputs and runtime state are not.

Mandatory checks retain exact commands, input hashes, versions, timestamps,
timeouts, exits, and complete raw logs. They cover seeds 1,17,89 at capacities
1,5,13,257,4096,65536; empty/singleton/max/back-to-back and all applicable
boundary lengths 4,5,11,12,13,14,15,16,19,20,254,255,269,270,271,510,65535,65536.
They must compare every recovered byte and exact length, independently decode
every hardware-compressed block, and cross-check independently constructed
software blocks against the preserved decoder.

Coverage also includes extension saturation/255 boundaries, hash collisions,
offset-one overlap, four-byte matches, end restrictions, hash clearing, decoder
offset 65535, history wrap and output beyond 65536, exact incompressible fallback,
malformed blocks/recovery, compressor errors/recovery, reset at collection,
matching, emission and stalls, simultaneous independent duplex and actual
internal round-trip. Observe stalls on every applicable public handshake,
including final outputs and statuses, with exactly associated completions and
no residual output. Compressor capacity and end restrictions prevent generating
offset 65535 itself; independent decoder stimulus must cover that offset.

At least three separately elaborating and executing synthesizable mutants must
fail the relevant checks for offset corruption, trailing-literal violation,
and changing held output. Compiler failures/timeouts do not count.
Real Yosys hierarchy/state/memory checks and zero latches, illegal parameter
diagnostics, and bounded clean-directory simulation/synthesis are required.
All child wall-clock limits must be generous (at least 3600 seconds), with
finite functional cycle bounds derived from block work and bounded stalls.

Portable checks do not replace native runtime L1.5 timing lint, Quartus 17.1
STA at <=10.0 ns with WNS>=0, or three consecutive deterministic Arria 10 GX
PCIe Gen3x8 hardware-bridge passes exercising both lanes and round-trip.
Missing native prerequisites remain blockers. No JTAG cable identity or PCIe
BDF belongs in the portable entrypoint. The runtime-authored, independently
approved product PDF follows engineering acceptance; it is not an input gate.
