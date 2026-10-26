# BELLOWS-L1 integration specification

## Product and fixed interface

BELLOWS-L1 decompresses streaming **raw LZ4 blocks** using an unsigned 8-bit
ready/valid interface and exactly 65,536 bytes of circular history.
Top: `bellows_l1_top`. Compile all `rtl/*.sv`; no public parameters exist.
Required child instances are `bellows_l1_history` and `bellows_l1_output`.
Target: Intel Arria 10 GX `10AX115N2F45E1SG`, clock period <=10.0 ns.
This is reusable RTL IP, not a framed-LZ4 parser, dictionary engine, PCIe
endpoint, checksum engine or host driver.

| Port | Direction | Meaning |
| --- | --- | --- |
| clk | input | Single synchronous clock |
| rst_n | input | Asynchronous active-low reset |
| s_data[7:0] | input | Compressed byte |
| s_valid | input | Compressed byte is valid |
| s_last | input | This accepted byte ends the compressed block |
| s_ready | output | Input byte can be accepted |
| m_data[7:0] | output | Decompressed byte |
| m_valid | output | Decompressed byte is valid |
| m_last | output | Final byte of this block's committed output prefix |
| m_ready | input | Consumer can accept output |
| status_valid | output | Completion is valid |
| status_error[2:0] | output | Completion code below |
| status_ready | input | Consumer can accept completion |

All ports are unsigned. A transfer occurs only at a rising edge with both
valid and ready. The producer holds data and last stable while valid is stalled;
output data/last and valid status/error remain stable until accepted. Inactive
output data, last and error are zero. During reset, input ready, output valid,
output data/last and status valid/error are zero.

Hold reset low to initialize control and output state, then deassert it safely
relative to the clock. RAM contents do not reset; validity and write pointer do.
Reset aborts parsing, copying, discard, buffered output and status without a
completion. A clean new block may begin after reset release.

Input last is a block boundary, not an output last. Exactly one completion is
returned per successful/rejected block whose boundary has been accepted.
No next-block input is accepted before the previous status handshake.
After a status handshake at N, readiness may resume post-N and the next input
may transfer at N+1. There is no cross-block history.

## Numerical and grammar rules

Token high nibble is literal length. High nibble 15 requires extension bytes:
add each byte, continue on 255, terminate on a value below 255 (including zero).
Token low nibble is match length minus four. Low nibble 15 similarly requires
extension bytes *after* the two-byte offset; initial match length is 19.
Other initial match lengths are 4 through 18.

Both sequence-length accumulators are unsigned 32-bit. Checked extension sums
larger than `0xffffffff` are rejected before wraparound. There is no total-output
length cap imposed by a total-output counter. Offset is unsigned, **low byte
first**, then high byte. A legal match offset is 1..65535 and is no greater
than the block's produced history availability, saturated at 65536 bytes.
Address addition/subtraction wraps by 16-bit truncation. No division or remainder
is used. Each match byte commits to history before its successor read, so
offset smaller than match length, including offset-one RLE, reads newly
produced bytes. A snapshot of pre-match history is incorrect.

A block ends with a literal-only final sequence. Its final literal carries
input last, or a token with literal nibble zero itself carries last.
`00(last)` is the canonical empty block. The terminal literal-only token's
match nibble is ignored. No compressor-specific last-five-literals or
last-match-distance restriction is imposed.

**A block ending in a match without a terminal literal sequence is truncated.**
In particular, last on an offset or match-extension byte is not a valid
match-ending delimiter. If no last is supplied, the engine waits rather than
inventing a completion.

## Errors, prefix preservation and recovery

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Truncated sequence |
| 2 | Zero offset |
| 3 | Offset exceeds produced history |
| 4 | Sequence-length overflow |
| 5..7 | Reserved, never emitted |

Last on a token requiring additional bytes, any extension byte, either offset
byte, or a nonfinal literal is truncation. At an accepted byte the priority is:
truncation, then arithmetic overflow, then zero offset, then history range.
A malformed offset never launches a match. A prematurely last-marked literal
is still registered and committed as part of the preserved output prefix.
Already committed bytes are not rolled back; uncommitted match bytes do not
appear. Nonempty output ends in exactly one final last, including a rejected
block's prefix. Empty output has no output beat.

An error before input last does **not** end the compressed block. The first
error is latched and, starting with the next edge, the engine discards every
accepted input byte through the first accepted last. During discard,
`s_ready=1` whenever reset is inactive, independent of input valid, output ready
and status ready. Discarded bytes cannot parse, create output, write history
or replace the error. Immediately after the discard-boundary edge input ready
drops and stays low until status acceptance.

The preserved prefix can finish while discard continues; neither operation
waits for the other. Status becomes valid only after **both** input-boundary
consumption and complete prefix retirement, including its last beat. If they
occur together, status may assert immediately after that edge. If input last
never arrives, no status or next-block reuse is allowed even after output
drains. A detecting byte already carrying last needs no discard, subject to
truncation priority. Reset during discard aborts the block without status.
This applies uniformly to zero offset, history range and both overflow paths.

## Registered schedule and integration

An accepted literal at N becomes a registered candidate post-N and commits
no earlier than N+1. A history read launched at N becomes registered post-N
and commits at N+1 if unstalled; a dependent successor read launches no earlier
than N+2. History writes coincide only with committed output candidates.

The output stage retains one unclassified pending byte and one presented byte.
A new candidate promotes the older pending byte with last=0 when the presented
slot is empty or retiring. Finish is a separate step after the final candidate
commit and promotes pending with last=1. Never expose pending directly or
change an already presented beat's last bit. External output transfer can
occur no earlier than the edge after presentation.

On a boundary-consumed block, final output retirement at N asserts status
post-N; earliest status acceptance is N+1. Empty output completes through the
finish step without fabricating a byte. Output/status stalls can extend all
latencies indefinitely. There is no required one-byte-per-cycle throughput.
See `design/ARCHITECTURE.md` for the boundary table, waveforms, simultaneous
retirement/commit priority and module dependency guarantees.

## Reproduction and evidence boundaries

Required tools are `python3`, `iverilog`, `vvp` and `yosys`; tool versions and
availability must be recorded by actual verification, not assumed here.
No installation is authorized by this specification.

Run from the delivered root:

```sh
python3 tests/verify.py --suite smoke
python3 tests/verify.py --suite all
```

`python3 tests/verify.py` also selects all. Verification sources are owned by
the independent Verifier and are supplied at that next workflow stage.
The smoke suite must compare empty, literal, overlapping-match and malformed
blocks, including malformed suffix discard and subsequent clean reuse.
The all suite must perform the admitted seed/traffic coverage, independent
reference comparisons, real defect injections, retained-memory Yosys inspection
and clean-directory reproduction without dependence on private workspace state.
Child deadlines are at least 3600 seconds; functional bounds are separately
derived from the frozen byte schedule and imposed traffic.

The required execution matrix uses seeds 17, 89 and 2026 with always-ready,
independently randomized gaps/readiness and burst backpressure including a
257-cycle output stall. Every combination includes all directed semantic
categories and at least 32 randomized valid blocks. Directed boundaries include
literal lengths 0,1,14,15,16,269,270,271,524,525; match lengths
4,18,19,20,269,270,274,525; offsets 1,2,3,255,256,257,32768,65535;
extension zero termination and consecutive 255 continuation; all overlap
relations, full-available-history offset, wrap/cross-wrap reads and mixed
output longer than 196608 bytes. Reset, truncation, stale history, status
stalls and every admitted recovery ordering remain required. Both real
32-bit overflow paths must execute without forcing internal counters.

Separate compiling/executing mutants reverse offset endianness, omit match +4
and use stale overlap history; syntax failures or timeouts are not detection.
Each must pass a relevant positive control and fail the targeted byte/status
scoreboard. Actual Yosys netlist inspection must establish no latches or
unresolved cells, nonempty reachable sequential logic and retained
65536-by-8 history with registered read behavior.

Each invocation retains fresh, non-overwritten command/source/version/time/
exit/log evidence. Engineering source inputs are only `rtl/*.sv`,
`design/SPEC.md`, `design/ARCHITECTURE.md` and `tests/*.py`.
Do not include runtime metadata, private paths, credentials or transcripts in
the delivered source package. Preparation diagnostics, if any, are advisory.

Native shared-runtime L1.5 timing lint, L2 Quartus 17.1 STA at <=10.0 ns with
WNS>=0, and L3 Arria 10 GX PCIe Gen3x8 hardware-bridge execution remain
mandatory and are not replaced by tests/verify.py. Hardware requires at least
three consecutive deterministic passes. No timing waiver can waive the
100-MHz objective. The runtime-owned, independently approved product PDF is
created only after engineering acceptance; it is not an engineering input or
pre-acceptance check dependency. All results are pending independent execution
at this design handoff.
