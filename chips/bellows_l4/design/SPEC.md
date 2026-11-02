# BELLOWS-L4 design contract

## Status and provenance

This is an implementation contract, not a verification or timing result.
The independently admitted work order is authoritative. The supplied
`bellows_l3_reference/rtl/` is read-only provenance and an executable
differential baseline, not a passing baseline for L4.
No repository-intake source index was supplied. The requested
`design/GENERATIONAL_HANDOFF.md` was not supplied; historical parent Quartus
frequency, slack and PPA are unknown. Current-product timing and physical
gates remain mandatory.

Designer owns `rtl/*.sv` and `design/*.md`. Independent Verifier owns
`tests/*.py`, reference models, generated simulation harnesses and all
functional and synthesis execution. The shared runtime produces the
independently approved product PDF only after engineering acceptance.

## Parameters and integration

The target is Arria 10 GX `10AX115N2F45E1SG`, with synchronous pipelined
logic at a clock period no greater than 10.0 ns. There are four independent
command channels. Defaults and legal values are:

| Parameter | Default | Legal |
| --- | --- | --- |
| `MAX_BLOCK_BYTES` | 65536 | integers 1 through 65536 |
| `SG_DEPTH` | 16 | integers 1 through 16 |
| `COPY_BYTES` | 8 | exactly 4 or 8 |

Illegal configurations must elaborate sufficiently to execute a fatal
diagnostic containing `PARAMETER ERROR`, without useful operation.
Diagnostic-only geometry does not redefine any legal configuration.
Raw input and reconstructed output are bounded by `MAX_BLOCK_BYTES`.
Intermediate LZ4 data is bounded by `2*MAX_BLOCK_BYTES+16`.
An entropy frame excluding its checksum trailer is bounded by
`4*MAX_BLOCK_BYTES+1024`.

`bellows_l4_top` retains every parent `bellows_l3_top` port, name, direction,
width and meaning. Its command extensions are `cmd_wide` and
`cmd_codec[2:0]`, sampled only with the accepted command. The additional
wide memory ports are:

| Direction | Ports |
| --- | --- |
| Input | `w_rd_req_ready`, `w_rd_rsp_valid`, `w_rd_rsp_data[63:0]`, `w_rd_rsp_error` |
| Output | `w_rd_req_valid`, `w_rd_req_channel[1:0]`, `w_rd_req_addr[63:0]`, `w_rd_req_bytes[3:0]`, `w_rd_rsp_ready` |
| Input | `w_wr_req_ready`, `w_wr_rsp_valid`, `w_wr_rsp_error` |
| Output | `w_wr_req_valid`, `w_wr_req_channel[1:0]`, `w_wr_req_addr[63:0]`, `w_wr_req_data[63:0]`, `w_wr_req_strb[7:0]`, `w_wr_rsp_ready` |

Transport selection is private to each accepted command. Byte commands use
only parent memory ports; wide commands use only wide ports. All modes work
on both. Wide transfers contain 1 through `COPY_BYTES` contiguous bytes,
least-addressed byte in the lowest lane. Writes use contiguous low strobes
and zero unused lanes. Requests must not cross descriptor boundaries, even
for unaligned addresses and short tails. There is at most one globally
outstanding read and one globally outstanding write across both transports;
each accepted request latches its channel, transport and byte count.

Source and destination segment totals must equal the declared source length
and capacity. Segments are positive sized, with no address overflow.
Zero source segments are legal exactly for zero source bytes. A positive
destination capacity and at least one destination segment are required.
Different live commands must not alias source or writable destination data:
this is a caller precondition, not relaxed boundary checking.

## Cycle and degenerate-boundary table

All handshakes use values immediately before a rising edge; state and
counters change after that edge. Reset is active-low asynchronous except
synchronous RAM data processes, which do not reset their arrays.

| Event/boundary | Pre-edge condition | Post-edge effect |
| --- | --- | --- |
| Active reset | `!rst_n` | All public ready/valid, status, data, addresses, counts, strobes, channels and errors are zero; contexts and ownership are aborted |
| First released edge | Idle context | Command-ready is available without memory traffic |
| Command at E | `cmd_valid && cmd_ready` | Only addressed channel captures command; its descriptors are eligible no earlier than E+1 |
| Descriptor at D | `sg_valid && sg_ready` | Only selected channel updates; memory waits for completed validation |
| Memory request at R | selected request valid and ready | Ownership and pending state are latched; response-ready is visible after R |
| Memory response | earliest edge R+1 | Read bytes are consumed or acknowledged write count advances; a failed write does not increase that count |
| Completion at C | `status_valid && status_ready` | Exactly that completion retires; channel-ready is available in the following cycle, not on the same handshake |
| Copy clear | `clear` | Both copy valid stages and logical history reset; no operation is accepted |
| Copy accept at E | `op_valid && op_ready` | Synchronous history-read/request stage occupies; this operation is not output-valid yet |
| Copy advance at E+1 | output stage can advance | Complete beat becomes output-valid; earliest retirement is E+2 |
| Copy stall | output valid and not ready | Operand state and RAM read registers freeze; no duplicate history commit |
| Simultaneous copy input/output | pipeline advances | Old output retires, old request commits once, and new request reads once |
| `MAX_BLOCK_BYTES=1` | legal COPY_BYTES 4 or 8 | One-byte literals use one lane; empty BF16 is legal, any nonempty BF16 raw input exceeds capacity |
| `MAX_BLOCK_BYTES=17, SG_DEPTH=3` | non-power-of-two geometry | Explicit descriptor wrap/limits, no binary-mask assumption |
| `SG_DEPTH=1` | first segment is also last | Exact sums and tails still checked; no access to segment 1 |
| Bus and codec faults together | live command | Bus fault wins, followed by codec, block limit, capacity and checksum mismatch |
| Reset and transactions | reset asserted | Reset wins; bridge must discard pre-reset responses before releasing reset |

Completion requires all issued transactions settled and codec, output and
checksum work finished or safely aborted. A write request is not a successful
write acknowledgement. Payloads remain stable under backpressure. A bus
error stops new command requests and remains a sticky failure; acknowledged
writes need not roll back. Independently rotating read, write and completion
arbitration must serve every continuously eligible channel within four
successful grants when downstream acceptance is available.

## Modes and numerical rules

| `cmd_codec` | Encode | Decode |
| --- | --- | --- |
| 0 | Parent raw LZ4 framing | Parent-compatible LZ4 semantics |
| 1 | Canonical byte Huffman | Canonical byte reconstruction |
| 2 | BF16 exponent Huffman plus residuals | Exact BF16 reassembly |
| 3 | Low-nibble-first W4 Huffman | Exact nibble packing |
| 4 | LZ4 then canonical byte Huffman | Huffman then LZ4 |
| 5 through 7 | Invalid command, no memory traffic | Invalid command, no memory traffic |

Entropy uses the versioned BELLOWS format, not the Zstandard wire format.
LZ4 tokens, extension lengths, little-endian offsets, minimum match four,
terminal-token handling and malformed-stream priorities follow the supplied
parent. Overlap reads each byte from its own logical output position minus
the offset, including earlier bytes in the same beat. History is private
per command/channel; legal offsets are 1 through 65535 with available history.

For little-endian BF16 bytes `lo,hi`,
`exponent=((hi & 0x7f)<<1)|(lo>>7)` and
`residual=(hi & 0x80)|(lo & 0x7f)`.
Reconstruction is `lo=(residual & 0x7f)|((exponent & 1)<<7)`,
`hi=(residual & 0x80)|(exponent>>1)`. No floating-point arithmetic,
rounding, quantization or exceptional-value canonicalization is permitted.
Encoding an odd raw length is an invalid command before memory traffic;
an odd length in a decoded entropy header is malformed.
W4 encodes the low nibble before the high nibble, without changing signed
bit patterns, with exactly two symbols per raw byte.

Checksum 0 has no trailer and reports zero. Checksum 1 is seed-zero XXH32
with published modular 32-bit arithmetic. Checksum 2 is reflected
CRC-32/ISO-HDLC, polynomial `0xedb88320`, initial and final XOR
`0xffffffff`. Mode 3 is invalid. Nonzero modes append exactly four
little-endian checksum bytes and cover original reconstructed user bytes,
never entropy metadata, intermediate LZ4 bytes or padding.

## Entropy wire contract

The first 20 bytes are:

| Bytes | Contents |
| --- | --- |
| 0 through 3 | ASCII `BL4H` |
| 4 | Version 1 |
| 5 | Codec value 1 through 4 matching the command |
| 6 through 7 | Zero |
| 8 through 11 | Original raw byte length N, little-endian |
| 12 through 15 | Symbol count S, little-endian |
| 16 through 19 | Meaningful bit count B, little-endian |

Next are ascending-symbol code-length bytes: 256 for modes 1, 2, 4;
16 for mode 3. Length zero is absent; nonzero lengths are 1 through 15.
Mode 2 next stores N/2 residual bytes in original word order.
The final field is exactly `(B+7)>>3` payload bytes with no extra fields
before the optional checksum. Canonical codes sort by `(length,symbol)`,
emit most-significant bit first, and fill bytes from bit 7 downward.
Unused low bits in the last byte are zero.

Require S=N in mode 1, even N and S=N/2 in mode 2, S=2*N in mode 3,
and S equal to the bounded intermediate LZ4 byte count in mode 4.
Mode 4's subsequent LZ4 result must be exactly N bytes.
Length arithmetic detects overflow before truncation. Decoder validates
exact source consumption, exact S, exact B, N and padding, rejecting magic,
version or mode mismatch, reserved bytes, illegal code lengths, oversubscribed
or forbidden incomplete tables, nonexistent codes, impossible sizes,
truncation, extra data and bad padding.

Encoder codebook construction is hardware histogram/tree work. Repeatedly
merge active nodes with smallest `(frequency,minimum contained symbol)`.
A singleton has code 0 of length one. Empty input has all-zero lengths and
B=0. If the unconstrained tree exceeds depth 15, use a complete fixed table
of eight bits for all 256 symbols or four bits for all 16 symbols. Otherwise
absent symbols have zero length. Decoder accepts any complete canonical
table, not only this encoder's table, plus the empty/singleton exceptions.
No raw-storage fallback or software-supplied encoder codebook is permitted.

## Errors

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Truncated LZ4 |
| 2 | Zero match offset |
| 3 | Unavailable history |
| 4 | Length overflow |
| 5 | Block-size overflow |
| 6 | Invalid stream usage |
| 7 | Checksum mismatch |
| 8 | Invalid command/descriptors |
| 9 | Destination-capacity overflow |
| 10 | Memory error |
| 11 | Malformed entropy format/table/bitstream |
| 12 through 15 | Reserved |

The first fault is sticky through completion. Corresponding simultaneous
faults use bus-before-codec-before-block-before-capacity-before-checksum
priority. `err_checksum_mismatch` is high only with valid code-7 completion.

## Acceptance and reproduction

Independent Verifier supplies `tests/verify.py`; the mandatory portable
commands, from the delivered project root, are:

```
python3 tests/verify.py --suite lz4
python3 tests/verify.py --suite entropy
python3 tests/verify.py --suite defects
python3 tests/verify.py --suite synthesis
python3 tests/verify.py --suite portability
```

All five remain mandatory and self-contained. Expected values come from
independent Python numerical/codec models, supplemented by parent differential
checks. Main behavioral, maximum-geometry, performance and mutation work uses
compiled Verilator; compact Icarus runs demonstrate portability. Required
versions identified at planning are Icarus 12.0, Verilator 5.020,
Yosys 0.33 and Python 3; discovery is not a passing experiment.

Frozen coverage includes seeds 17,89,203 at both COPY_BYTES values; at least
64 generated valid blocks per width/seed through all channels, modes,
transports and legal checksums; directed 65536-byte cases; all BF16 bit
patterns and W4 positions; at least 100 balanced malformed entropy cases;
the six compiled non-equivalent functional mutants; all admitted parameter,
descriptor, reset, bus-fault and arbitration cases. No coverage is established
by this document.

Leaf copy performance requires at least `0.99*COPY_BYTES` actual output
bytes/cycle over steady-state streams of at least 4096 bytes, including
offsets 1,3,7,16. Integrated mode-0 decode speedup is measured against the
supplied L3 command-through-completion cycles on identical literal-heavy and
match-heavy blocks of at least 32768 output bytes: at least 4.0x for width
4 and 8.0x for width 8. Full entropy-frame compressibility limits are 50%
for 8192 repeated bytes, 70% for 4096 BF16 words with exponent 127 and
varied residuals, and 35% for 8192 zero-W4 bytes, excluding only checksum.
These are directed claims, not universal compression or speedup claims.

Generic synthesis must inspect the actual hierarchy and inferred memories,
with zero latches, combinational division/modulo, multiple-driven or
undriven functional nets. Native shared-runtime timing lint, Quartus 17.1
STA (nonnegative WNS at at most 10.0 ns with no unconstrained functional
clock paths) and three consecutive deterministic physical bridge passes
remain required. No timing waiver is admitted.

Fresh evidence directories use `evidence/l1-<timestamp_or_hash>/`,
`evidence/portable-<timestamp_or_hash>/`, and, for an optional static
Designer diagnostic, `evidence/preparation/<stem>-<timestamp_or_hash>/`.
Source-bound receipts and raw failures are retained, not overwritten.
Clean reproduction copies only declared RTL, design, tests and parent
reference inputs; it must not depend on preexisting evidence or runtime
metadata. Measured results and final PDF are pending independent execution
and acceptance.
