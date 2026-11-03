# BELLOWS-L2 implementation architecture

## Hierarchy and ownership

`bellows_l2_top` instantiates `bellows_l2_compressor` and the unmodified
`bellows_l1_top`, which retains `bellows_l1_history` and `bellows_l1_output`.
The compressor instantiates `bellows_l2_literal_buffer`,
`bellows_l2_hash_match`, and `bellows_l2_emitter`. All have one clock domain.
The top only selects stream routing; it does not alter decoder arithmetic,
framing, status, output staging or history.

The following internal contracts are fixed before RTL implementation.
Internal addresses are unsigned absolute block addresses, not circular offsets.

| Module | Inputs | Outputs and ownership |
|---|---|---|
| `bellows_l2_literal_buffer` | `clk,rst_n`, `write_en,write_addr[15:0],write_data[7:0]`, `a_en,a_addr[15:0]`, `b_en,b_addr[15:0]` | `a_data[7:0],b_data[7:0]` synchronous reads; owns `MAX_BLOCK_BYTES` original bytes |
| `bellows_l2_hash_match` | `clk,rst_n,start,block_length[16:0],match_ready`, `a_data[7:0],b_data[7:0]` | `a_en,a_addr[15:0],b_en,b_addr[15:0]`; held `match_valid,match_position[16:0],match_length[16:0],match_offset[15:0]`; held `done` |
| `bellows_l2_emitter` | `clk,rst_n`, `seq_valid,literal_start[16:0],literal_length[16:0],match_length[16:0],match_offset[15:0],final_sequence`, `literal_data[7:0]`, `byte_ready` | `seq_ready`, `literal_en,literal_addr[15:0]`, registered `byte_data[7:0],byte_valid`, one-cycle `done` |

`start` is a one-cycle matcher initialization request, permitted only when no
old result is owned. `match_valid` descriptors remain unchanged until
`match_ready`. `done` remains asserted until the next start. An emitter
descriptor transfers on `seq_valid&&seq_ready`; all fields are latched.
`done` follows retirement of its last internal byte and returns the emitter
to idle on the next edge. All read enables are reset-gated.

The compressor controller owns raw collection, error/discard, literal anchor,
candidate storage and size selection, output replay, and status. During search,
the matcher owns both raw read ports. While emitting a descriptor, it is paused
on its result (or done); the emitter owns port A and port B is disabled.
There is never simultaneous collection and read/encoding in one compressor.

## Memory resources and dependency contracts

| Resource | Logical size at default capacity | Access schedule |
|---|---|---|
| Original/literal RAM | 65536 x 8 bits | One collection write, two registered search reads, or one emission read |
| Hash positions | 256 x 16 bits | Same-edge registered old read and replacement write |
| Hash validity | 256 bits | Reset/start clear; per-lookup set |
| Candidate encoding RAM | 131088 x 8 bits | One emitter write or one synchronous output replay read |
| Parent history | 65536 x 8 bits | Preserved synchronous write/read schedule |

These are logical capacities, not measured M20K/ALM utilization. Two-read-port
raw storage may be replicated by the implementation tool. Data arrays have
dedicated clock-only RAM processes and are not bulk reset. Registered read
data need not be reset: ownership/state and valid bits prevent use before a
completed read. Read address widths are 16 bits for raw input and 18 bits for
candidate storage; occupancy and lengths are respectively 17 and 18 bits.
Non-power-of-two capacity is bounded by comparisons, never truncated into a
capacity-sized power-of-two ring. Diagnostic-only allocation for illegal
parameters does not permit traffic: an explicit fatal parameter diagnostic
rejects them before transactions.

Raw-buffer writes require collection acceptance, keep, and available capacity.
Matcher reads are only within the registered completed raw block. The emitter
gets original bytes, never bytes reconstructed from an in-progress match;
this makes overlapping greedy comparison well-defined. Candidate bytes are
not externally visible until the complete candidate and fallback choice are
known. Status ownership prevents a new collection from overwriting data needed
for an old output. Parent history ownership is reset between decoder statuses
exactly as in the supplied RTL.

Candidate size is conservatively bounded: match descriptors consume at least
four previously unencoded bytes and cost one token, two offset bytes and at
most one extension byte per 255 length units plus termination; literals cost
their bytes plus bounded length extension. Even a loose bound of two encoded
bytes per source byte plus 16 covers all legal blocks. Storage exhaustion is
an invariant violation, not a successful fallback. Independent tests must
observe the bound and mutation sensitivity.

## Exact local stages

### Collection and size calculation

`COLLECT` accepts one raw byte per ready/valid edge. A valid empty marker
closes a zero-length block. Framing/capacity errors enter discard until last,
then status without ever enabling encoding output. On successful last,
`SIZE_INIT` registers literal-only base size `N+1`. For `N>=15`, `SIZE_EXT`
adds one size byte per registered subtraction of 255, including the final
remainder byte. `START` pulses matcher initialization; `FIND` awaits results.

### Hash search

`CHECK` tests `N>=13` and `p<=N-12`. `KEY_REQ` requests one original byte;
`KEY_CAPTURE` consumes its registered response on the following edge and
registers it into one of four byte slots. Four such pairs acquire the key.
`HASH` registers the XOR/rotate hash. `LOOKUP` synchronously reads the old
position and validity and inserts the current position. `VALIDATE` consumes
that old registered response and checks validity, ordering and distance.

For a legal candidate, four `COMPARE_REQ` / `COMPARE_CAPTURE` pairs read and
compare candidate bytes against the registered key. A mismatch increments
`p` and returns to `CHECK`. Four matches initialize extension to length four.
`EXT_CHECK` enforces end `<=N-5`. Each additional byte uses `EXT_REQ` /
`EXT_CAPTURE`; the latter compares registered A/B data and commits at most
one matched byte. End-limit or mismatch enters `RESULT`.
`RESULT` holds the descriptor while its encoding is appended. Only a
`match_ready` edge advances `p` to the stored match end. `DONE` holds when no
further legal start exists. Skipped match-interior positions are not inserted.

The four-byte key, hash, table response, candidate legality and byte extension
are distinct registered stages. There is no combinational search over a block.

### Anchor and emitter

On a matcher result, `MATCH_DESC` transfers literal span `[anchor,p)` plus
match length/offset to the emitter. `MATCH_EMIT` appends encoded bytes to
candidate RAM. At emitter completion the controller advances anchor to match
end; `MATCH_ACK` acknowledges the matcher before returning to `FIND`.
On matcher done, `FINAL_DESC`/`FINAL_EMIT` encode `[anchor,N)` with no match.

The emitter latches a descriptor in `IDLE`. `TOKEN` registers the token.
`LITERAL_EXT` emits extension bytes by subtraction until the mandatory final
remainder. `LITERAL_REQ` requests one RAM byte, `LITERAL_CAPTURE` registers its
response, and `LITERAL_BYTE` presents it when the byte output slot is available.
`OFFSET_LOW` and `OFFSET_HIGH` register offset bytes in order.
`MATCH_EXT` emits the match extra length using the same subtraction convention.
`DRAIN` waits for the last presented byte to retire; `DONE` is one cycle.
The output register is only loaded when empty or its pre-edge byte retires,
and holds all data when stalled. No direct input-data-to-public-output path
exists.

### Fallback and public output

`SELECT` compares completed candidate count with the registered literal-only
size. A strictly smaller candidate is retained; otherwise count resets and
`FALLBACK_DESC`/`FALLBACK_EMIT` regenerate a complete final literal sequence.
Candidate RAM is overwritten only after selection; no external byte has yet
been presented.

`OUTPUT_REQ` reads one candidate byte synchronously. `OUTPUT_LOAD` registers
that response and its final-byte flag. `OUTPUT_HOLD` changes neither until
pre-edge public valid and ready. Nonfinal retirement increments address and
returns to request; final retirement enters `STATUS`. Thus even permanently
ready output has deliberate replay bubbles. Status is never predicted from
ready alone. A held final byte delays status; held status delays new raw input.

### Preserved parent cycles

The decoder accepts tokens, extensions and offset bytes in their parser states.
A literal acceptance registers its data; `ST_LITERAL_COMMIT` waits for output
candidate readiness and writes history only on candidate commit.
`ST_MATCH_READ` requests synchronous history data, then `ST_MATCH_COMMIT`
waits for candidate readiness and writes the next reconstructed byte. Each
successful match byte returns to read unless it was the last.

The parent output stage holds a pending byte so the actual final byte can be
marked last. A new candidate promotes a previous pending byte to the presented
register when that slot is empty or retiring. Finish promotes pending with last.
`ST_FINISH`/`ST_COMPLETE` wait for output retirement and the accepted input
boundary before `ST_STATUS`. Simultaneous retire/promote uses the parent's
existing nonblocking-assignment priority. Its prefix/error behavior is unchanged.

## Reset, timing and tradeoffs

All sequential control is posedge with asynchronous active-low reset. RAM
storage processes preserve synchronous memory inference; reset gates writes
and public ports and invalidates ownership without data-array clearing.
Hash validity is a small explicit resettable bitmap, not a reset data RAM.
There are no division or remainder datapath operators and no mixed
blocking/nonblocking sequential assignments. Arithmetic is limited to bounded
17/18-bit add/subtract/compare and 8-bit XOR/rotate between registers.

One full input block and conservative encoded storage trade resource capacity
for simple backpressure and exact fallback. Serial key acquisition, comparison,
extension and emission trade latency for bounded combinational depth. The
architecture contains no unbounded combinational path through a hash collision
chain, block scan, or variable-length extension loop. These design choices
support, but do not establish, 100 MHz timing. Actual Quartus STA and native
hardware checks remain mandatory. No timing waiver is assumed.

There is no fixed end-to-end cycle count: it depends on matches, extensions,
fallback, decoder work and consumer stalls. All protocol progress is based on
pre-edge handshakes, not combinational input forwarding.

## Claim-to-evidence map and portable inputs

| Claim | Required independent evidence |
|---|---|
| Syntax and hierarchy are elaboratable | Optional Designer static Icarus check; Verifier compilation at all legal/illegal endpoints |
| Byte-exact recovery and LZ4 format | Independent Python parser/generator and actual RTL simulations |
| Real compression and fallback | Hardware encoded lengths and parsed matches; exact literal-only fallback comparisons |
| Backpressure and mode correctness | Per-channel observed stalls, held-payload assertions, simultaneous duplex and internal route traffic |
| Error/reset/history boundaries | Malformed/recovery/reset cases and independently generated large decoder blocks |
| Checker defect sensitivity | Three executing disposable mutants failing their intended assertions |
| Synthesizable state and memory, zero latches | Real Yosys hierarchy/state/memory checks |
| Portable reproduction | Fresh copied declared inputs, targeted simulation and real synthesis |
| Arria 10 100 MHz+ operation | Native timing lint, Quartus 17.1 STA and hardware-bridge checks |
| Final product report | Runtime authors/reviews/renders after engineering acceptance |

No functional, synthesis, timing or hardware result is asserted by this design
document. Required sources are `rtl/*.sv`; provenance comparison additionally
uses `bellows_l1_reference/rtl/*.sv`. Verification input is `tests/*.py`, authored
independently. Design documentation is `design/SPEC.md` and this file.
See `SPEC.md` for the portable full-check command and frozen coverage. There
are no dependencies on account directories, private execution records, runtime
metadata, local cables, or local PCIe addresses.
