# BELLOWS-L4 architecture

## Implementation status

The design contains the preserved L1/L2/L3 compatibility hierarchies and
the integrated `bellows_l4_top`. Four generated `bellows_l4_context`
instances share independent read, write and completion arbitration and
byte/wide DMA. Each context connects its LZ4 parser, two-stage copy engine,
hardware canonical Huffman codec, intermediate buffer and checksum unit.
All five codecs use the same descriptor-validated memory paths.

This is a design handoff, not a functional verification, timing or product
acceptance result. Independent functional/reference/performance/synthesis
checks, native timing/hardware gates and the final product PDF remain
pending. The contract in `SPEC.md` is unchanged.

## Source map and dependency contracts

| Module | Implemented responsibility | Required caller guarantee |
| --- | --- | --- |
| Original `bellows_l1_*` | Parent byte LZ4 decoding and history/output staging | Parent stream protocol |
| Original `bellows_l2_*` | Parent deterministic compressor and compatibility wrapper | Parent framing/keep protocol |
| Original `bellows_l3_*` | Parent four-channel byte SG subsystem | Parent descriptor/nonaliasing contract |
| `bellows_byte_ram` | Separately elaborated byte-wide synchronous one-read/one-write RAM | Depth-bounded addresses and externally gated enables; caller owns validity/reset |
| `bellows_l4_copy_engine` | Two registered stages, synchronous banked history, overlap forwarding | Valid bounded operations; clear only after drain |
| `bellows_l4_lz4_decoder` | Beat queue, LZ4 parsing, validated literal/match operations | Input counts 1 through COPY_BYTES, ordered input, clear before command |
| `bellows_l4_huffman_table` | Deterministic frequency tree, depth fallback, canonical validation/lookup | Load code lengths or histogram before build; observe ready/valid |
| `bellows_l4_entropy` | BL4H coding/decoding, hardware histogram, BF16/W4 transforms | Declared byte stream length with exact last; original N supplied for mode-4 encoding |
| `bellows_l4_intermediate` | Synchronous eight-bank LZ4 intermediate storage | Bounded indices; producer completely finished before consumer starts |
| `bellows_l4_context` | Descriptor validation, transport queues, codec routing, checksums, fault settlement | Nonaliasing descriptors and response counts guaranteed by DMA |
| `bellows_l4_top` | Four generated contexts and shared scheduler/DMA | External response timing and reset-epoch contract in SPEC |
| `bellows_l4_scheduler` | Independent rotating read/write/completion reservations | Hold each lane request until reservation; do not reuse context before completion |
| `bellows_l4_sg_dma` | Shared outstanding ownership across byte/wide ports | Descriptor-validated addresses/counts/strobes from context; bridge discards old reset responses |

No parent-reference source is edited. Delivered compatibility sources derive
from the actual supplied files, not regenerated implementations. The literal
buffer's physical storage is replicated as described below; its ports,
read latency and old-data collision semantics are unchanged.
The supplied `design/GENERATIONAL_HANDOFF.md` records `N/A` for parent
STA/PPA and physical HIL, so historical measurements remain unknown and
parent signoff is not established. The preserved compatibility ports and
data streams still require independent differential and numerical checks.

## Copy/history pipeline

Eight byte banks store logical positions by bank `position[2:0]` and
row `position[15:3]`. Each bank has synchronous read and write processes
without asynchronous array reset. Storage depth is `(MAX_BLOCK_BYTES+7)>>3`
rows per bank; unused physical bytes in the last row are not logical history.
Every operation reads at most one row per bank, starting at the logical
match source. Literal operations do not read history.

At accepted edge E, operands, operation count, source base and destination
start are latched and bank reads occur. At E+1, the second registered stage
captures the complete beat, and that beat commits once to history.
Earliest external retirement is E+2. Logical position advances on operation
acceptance, not on retirement, so younger operations include pending history.
The output register forwards same-edge read/write collisions to the younger
request by exact logical-address comparison.

For offsets below eight, intra-beat overlap selects a seed lane using a
small explicit offset/lane lookup. It repeats the first offset bytes,
including a seed forwarded from a preceding pending beat. No lane depends
on the combinational output of another lane; there is no serial chain of
eight general subtract/read operations. For larger offsets, every lane
selects its own preceding history byte. Unused output lanes are zero.

Both stages use a common elastic advance enable. If a valid output is
stalled, request operands, read registers, logical position and output
registers freeze. History writes occur only when a valid request advances,
preventing duplicate writes. Clear cancels both valid stages and resets
logical position without clearing RAM; its caller must first drain the
previous command. The decoder's offset and count checks prevent reads of
uninitialized logical history.

## LZ4 operation decoder

A 16-byte register queue accepts at most eight bytes per beat and consumes
one parser byte or up to COPY_BYTES literal bytes per cycle. Incoming unused
lanes are masked. Input acceptance stops while a presented operation is
stalled, so that operation's lane count and payload cannot widen underneath
backpressure. Match runs submit successive COPY_BYTES operations without
re-reading the compressed input.

The parser tracks 32-bit extension lengths with 33-bit overflow checks,
private logical output length and a 16-bit offset. Offset zero and unavailable
history are rejected before launching a match. Block-limit tails issue
only remaining legal bytes and reject further production. A terminal literal
tail emits available literal bytes before a truncation report, matching the
parent's byte-level intent. Parser-field truncation priorities follow the
parent: in particular a terminal offset-high or extension byte is truncated,
even if its numerical value would otherwise be valid.

Errors discard remaining framed input, then report a sticky error. Successful
status means parsing and operation submission finished, not that copy/DMA
output drained. The context tracks outstanding copy operations and waits
for the copy and checksum staging to drain before finishing the frame.
Standalone `clear` starts parsing; reset or a retired status leaves the
decoder idle. `decoded_bytes` counts accepted copy operands and
`consumed_bytes` counts parser/discard queue consumption; neither is a memory
write acknowledgement.

## Hardware codebook

`bellows_l4_huffman_table` takes hardware-generated symbol frequencies,
or external frame length bytes for decoding. A fresh start resets control
validity, not storage arrays. The decoder path requires all alphabet length
entries loaded before building. Histograms use default inactive leaves;
nonzero frequency leaves are activated explicitly.

Encoder tree construction scans synchronous node memories and maintains
two registered candidates ordered by `(frequency, minimum contained symbol)`.
It then merges those nodes into a registered parent. Parent walks derive
each leaf depth. Encountering depth 16 activates the required full-alphabet
fixed-length fallback. Singleton depth zero becomes length one; absent
leaves remain length zero.

Validation counts each length, walks the Kraft slots by depth, and rejects
oversubscription or incompleteness except the empty/singleton definitions.
Canonical assignment scans symbols in ascending order at each ascending
length and stores codes and canonical symbol order. Exposed first-code,
length-count and first-index metadata are bounded 16-entry control tables,
not a large asynchronous history mux. Encoder and decoder symbol lookup
ports have synchronous memory data and registered validity; callers consume
each result on its following cycle.

The construction deliberately trades entropy codebook latency for bounded
between-register logic. There is no software-supplied encoder codebook.
Frequency sums use 40 bits, accommodating the full 256-leaf sum of 32-bit
input frequencies. This is storage/arithmetic sizing, not a timing result.

## Device RAM port normalization

The native mapper previously timed out after 3600 seconds before producing
a mapped netlist. This is not evidence of timing failure or proof of the
timeout's cause; no device utilization, M20K placement or WNS result was
obtained. The following source repair removes behavioral RAM port patterns
that require more ports than their intended physical memories support.
Fresh mandatory checks and native mapping/STA/HIL remain required.

`bellows_l2_literal_buffer` now has two byte-wide storage replicas, each
with one synchronous write and one synchronous read. Both receive every
enabled write at the same address and edge. The matcher can still read
independent A/B addresses simultaneously without serializing its extension
comparison. This doubles literal storage from `MAX_BLOCK_BYTES` to
`2*MAX_BLOCK_BYTES` physical bytes per compressor, but does not change
logical capacity, cycle count or the deterministic compressor algorithm.
No write-through bypass is added: a same-edge read/write collision returns
the old byte, as in the supplied parent's nonblocking RAM process.

Entropy histogram, symbol and BF16 residual memories each have one write
expression and one synchronous read expression. State-dependent enables,
addresses and write data are selected before those accesses. In particular,
encode-residual output and decode-residual reconstruction share the same
read port and existing read register; their state-machine phases cannot
overlap. W4 low/high symbol and histogram operations retain their existing
separate cycles.

Codebook node frequency/minimum writes similarly select histogram loading
or merging before one access. Code lengths use one write port and one
registered read port, shared between construction and completed-table
lookup. Construction and lookup occur in disjoint states, so the same
read register serves both without a pipeline change. Parent links use
two M20K-targeted ports: merge writes the two distinct child addresses
simultaneously; depth walks read through port A on non-merge cycles.
The small 16-entry canonical metadata tables remain control storage.

| RAM event | Pre-edge sampling | Post-edge behavior |
| --- | --- | --- |
| Enabled read at E | Selected address and enable | Read register holds the pre-write byte/entry after E; existing consumer samples it at E+1 |
| Read disabled | Enable low | Read register holds; no new result-valid event |
| Literal write with A/B reads | Common write and independent read addresses | Both replicas update; colliding reads retain old-data semantics |
| Parent merge | Two selected children, same parent value | Both links written at E, with no walk read that cycle |
| Reset/clear | Existing RAM access gates | No array reset; architectural validity suppresses stale data |
| Block sizes 1, 17, 65536 | Existing validated logical indices | Capacities and synchronous latency unchanged, including non-power-of-two tails |

### Separately elaborated bulk RAM leaves

A subsequent current-source native mapping attempt also reached its
3600-second deadline without a mapped netlist or setup/hold result.
The retained diagnostic at
`evidence/preparation/coordinator-native-map-audit-3383e9b4f5f04424/receipt.json`
identifies about 2.1 million pre-map hierarchy lines per intermediate-buffer
instance, including 1,048,704 array clock connections. This localizes an
elaboration-scalability target; it does not prove a final register
implementation, resource overflow or timing failure.

Each of the eight mode-4 intermediate banks now instantiates
`bellows_byte_ram`, a separately elaborated leaf containing only an 8-bit
array, one write enable/address/data port and one synchronous read
enable/address/result port. Addresses are explicitly `ROW_BITS` wide.
Bank selection, row increment, output rotation and elastic occupancy remain
in `bellows_l4_intermediate`; no extra register or queue stage is introduced.
The default bank depth remains 16386 bytes, including the original final
partial row, not a rounded-down power-of-two capacity.

The large entropy symbol and BF16 residual arrays and the compressor's
encoded-output array use the same leaf with their original exact depths.
Each instance has its own storage; no logical buffers or channels are
shared. Compressor address ports use the depth-derived width, with enabled
accesses still bounded by the existing encoded-capacity and output-count
control. The literal buffer already has two separate single-read replicas;
its storage, the successfully recognized copy-history banks, and L1 history
are unchanged. Histogram and codebook arrays have bounded 8/9-bit addresses
and normalized synchronous ports; their existing implementations remain.

| Leaf/buffer boundary | Pre-edge condition | Post-edge effect |
| --- | --- | --- |
| Read accepted at E | Read enable and bounded address | RAM result updates after E; existing consumer samples at E+1 |
| Read stalled/disabled | Read enable low | Result holds, including intermediate output backpressure |
| Read and write collide | Both enabled at the same address | Result captures old data; storage captures the new byte |
| Reset/clear | Caller gates access and clears architectural valid state | No RAM reset or read-result reset; stale data remains unobservable |
| Intermediate clear with write | Existing write enable remains asserted | Write still occurs; occupancy clears and no read is accepted |
| Minimum/non-power-of-two depth | Existing logical bounds | Exact depths retained; no new wrapping or clamping |
| Partial last intermediate beat | Existing read count below eight | Only requested rotated lanes are exposed; upper output lanes remain zero |

Compile all `rtl/*.sv`, including `bellows_byte_ram.sv`, for the L2/L3/L4
hierarchies. The leaf has no behavioral bypass, initialization, vendor
primitive or extra pipeline stage. Its memory and read-data register use
only `posedge clk`, with nonblocking assignments and no asynchronous reset.
The bounded descriptor tables retain their existing control semantics.
These changes express RAM inference intent; actual M20K inference, resource
fit and timing still require fresh native mapping and STA.

## Entropy stream codec

`bellows_l4_entropy` uses byte streaming adapters at its boundary. It
collects encode symbols in a synchronous symbol RAM, builds its histogram
in hardware, transfers frequencies to the table builder, computes B from
histogram times code length, and emits the exact BL4H header, length table,
BF16 residuals and MSB-first packed codes. The bit-count product and sum
are separately registered. Partial payload bytes start at zero and retain
zero unused low bits.

For BF16, each accepted low byte is held until the high byte arrives, then
the exact exponent and residual are stored. For W4, each accepted byte
creates a low-nibble histogram transaction followed by a high-nibble
transaction. Mode 4 treats input as the already-produced intermediate LZ4
byte stream, retaining the separately declared original raw N.

The decoder parses and checks the complete header before loading lengths.
It validates frame size using 33-bit arithmetic, including table/residual
overhead and rounded payload length. After table validation it stores
residuals, decodes bits against canonical first-code/count metadata and
reads the canonical symbol order synchronously. BF16 reassembly outputs
the low byte then high byte. W4 emits one byte after the second decoded
nibble. Mode 4 emits intermediate LZ4 bytes into its context's synchronous
banked buffer. The context subsequently decodes those bytes through the
LZ4 parser and copy engine and requires exactly N reconstructed bytes.

Every decode checks S, B, zero padding, full input consumption and output
length. The last marker must match the declared stream length exactly.
Error status drops unconsumed local output, not memory writes already
acknowledged by the system. Codebook control clears on status retirement,
including early malformed-header and invalid-command exits, preventing
an unfinished build from blocking channel reuse.

This module excludes the outer checksum: the context supplies/verifies
checksums over original user bytes and removes/appends the four-byte trailer.
Byte entropy throughput is intentionally data dependent. The claimed
superscalar throughput applies to the copy pipeline and the integrated LZ4
path, not to every entropy or checksum phase.

## Scheduler and DMA

Read payload layout is `{wide, address[63:0], count[3:0]}`.
Write payload layout is `{wide, address[63:0], data[63:0], strobe[7:0]}`.
Completion layout remains `{id[15:0], error[3:0], src_bytes[31:0],
dst_bytes[31:0], checksum[31:0]}`.

Each arbiter offers the rotating winner directly when empty. On an
unstalled grant it reserves and forwards the transaction at the same edge;
on a stalled offer it captures the owner/payload into its hold register.
`lane_take` means an irrevocable reservation, not necessarily external
memory acceptance. The payload remains stable until the selected transport
accepts it; the rotation pointer advances only after that successful grant.
The registered hold path is also used for completion backpressure.

DMA latches owner, width and count on external acceptance and makes
response-ready visible afterward. There can be no same-edge response
acceptance to a new request. Read and write pending bits are independent.
The fall-through arbitration removes a compulsory reservation-only cycle
on unstalled transfers; it does not permit two outstanding requests in
either direction or combinational response acceptance.

The response one-hot routes only to the stored owner and the selected
transport. Read data is masked to the stored count. Byte writes count one
byte; wide write acknowledgement count is derived from the accepted strobe
using a balanced three-level population count (four two-bit sums, two
three-bit sums and one four-bit sum), not a serial eight-lane accumulator.
The context, not DMA, owns source/capacity/segment validation and sticky
fault priority. Local pending flags cover an arbiter reservation until
its response, including an externally stalled held request. DMA pending
flags cover externally accepted requests only. Completion waits for both
local pending flags to clear; destination counts advance only on successful
write responses.

## Context, descriptors and transport adapters

Contexts progress through IDLE, COLLECT, VALIDATE, ARM, RUN, FINISH,
optional TRAILER, SETTLE and COMPLETE. Command extensions are latched
alongside the parent's command fields. Only COLLECT accepts descriptors,
with separate source/destination indices. Each descriptor is checked for
positive size, 65-bit inclusive address-end overflow and 37-bit accumulated
size overflow. VALIDATE requires both exact totals before ARM loads the
first addresses and starts the checksum unit. The cycle/degenerate table
in `SPEC.md` applies to these transitions, including singleton descriptors
and explicit non-power-of-two index bounds.

Short entropy frames are not rejected by command-field validation. After
descriptor validation, the entropy unit rejects a declared payload shorter
than its 20-byte header with code 11, including an empty payload. The context
guards checksum-trailer subtraction when the source is shorter than four
bytes; it passes zero payload bytes rather than a wrapped length. This error
uses the existing bus-first sticky fault and SETTLE path, which drains any
already reserved transactions. Mode-0 command-length validation is unchanged.

The 16-byte input queue accepts only returned bytes. A request reserves
enough free queue space for its entire response, requests the minimum of
transport width, validated remaining source bytes and current segment
remainder, and advances its source position on response. A byte command
requests one byte regardless of COPY_BYTES. Entropy and compression consume
one byte at a time; the LZ4 decoder consumes up to COPY_BYTES while excluding
the optional checksum trailer.

The 32-byte output queue decouples copy/codec production from memory
acknowledgement. Copy beats enter together in checksum mode zero. Other
codecs produce bytes which are packed into wide writes. Writes reserve
the minimum of transport width, segment remainder and remaining capacity;
short final queues are flushed in FINISH/TRAILER/SETTLE. Reservation pops
the corresponding queue bytes and advances the destination address.
An outstanding write blocks another local reservation until its response.
Unused write lanes are zero and strobes are contiguous low bits. Segment
addresses may be unaligned; no request relies on aligned descriptor sizes.

### Registered descriptor remainders and beat limits

The pre-repair native post-fit result reported setup WNS -2.420 ns and
hold slack +0.037 ns at 10.000 ns, with no unconstrained functional
endpoints. Mapping/fitting completed at 59,123 ALMs and 1,256 M20Ks.
The reported critical cone ran from the active destination descriptor
index through descriptor lookup, subtraction, chained beat limits,
lane masking and arbitration into the DMA write count; an arbiter payload
hold register was another endpoint. These are retained pre-repair
measurements, not timing signoff for the changed sources.

Each context now caches the active source/destination segment's unsigned
32-bit remaining byte count and a four-bit transfer limit. ARM loads the
first descriptor's count and `min(transport width, segment remaining)`.
A read response updates the source remainder; an irrevocable write
reservation updates the destination remainder. A segment-ending event
loads the next descriptor and its limit at that same edge, or clears
both caches at the final segment. All descriptor lookup, remainder
subtraction and full-width limit construction terminate at these
registers rather than feeding outgoing request lane masks or arbitration.

The outgoing read count is the cached limit. The outgoing write count
only adds the existing short-final-queue limit in FINISH/TRAILER/SETTLE.
Exact validated descriptor totals guarantee that every segment-bounded
transfer also fits the remaining command source length or destination
capacity; a separate combinational total-minus-position limit is redundant.
The final segment's zero limit prevents any further write reservation.
Output queue occupancy still gates reservation, so no ungenerated bytes
are written. Unused data lanes remain zero.

| Event | Pre-edge sampling | Post-edge cache behavior |
| --- | --- | --- |
| Reset or new command | Existing reset/command handshake | Remainders and limits clear; no inherited descriptor state |
| ARM | Validated descriptor zero and latched transport | First remainders/limits and addresses become available for RUN |
| Read reservation | Cached read limit | Existing pending/count capture; source cache remains unchanged |
| Read response | Reserved count, including a failed response as before | Subtract count or load next source descriptor; final limit becomes zero |
| Write reservation | Cached write limit, limited by final queue occupancy | Pop exactly those bytes and subtract/load destination cache immediately |
| Write response | Stored owner/count/error | Only a successful response advances acknowledged bytes; caches do not advance again |
| Held request or pending response | No new local reservation | Cached count/address cannot change underneath the arbiter-held payload |
| Simultaneous read response/write reservation | Independent direction events | Both caches update independently |
| One-byte/non-power-of-two segment | Positive validated size | Exact tail limit, explicit next-segment bound, no alignment or wrap assumption |

This repair introduces no request-preparation state, mandatory bubble,
additional outstanding transaction or change to fault priority. Read,
write and completion arbitration, stalled-payload holding, response
ownership and successful-write accounting are unchanged. The integrated
4x/8x speedup requirements remain mandatory, not inferred from the absence
of added cycles. Fresh independent checks, native STA and three consecutive
physical HIL passes are required on the repaired sources.

`reads_consumed` counts returned request bytes, including a failed read
as in the parent, not codec-consumed payload symbols. `writes_reserved`
tracks reserved address space independently of `writes_acked`, which
counts only successful memory acknowledgements. `raw_count` tracks original
user bytes, and `output_generated` includes complete frame/trailer output
but not mode-4 intermediate bytes. Block/capacity checks use widened
addition before accepting codec output. These counters have distinct
ownership and are not interchangeable.

Mode-0 compression directly adapts the preserved parent
`bellows_l2_compressor`: ordered bytes, keep=true for nonempty input,
keep=false/last=true for empty input, and framed last on the final raw
byte. No recompression heuristic or output rewrite is applied to its
deterministic byte stream. Mode-0 decompression uses the new integrated
operation parser and copy engine. The preserved legacy tops remain
separate compatibility implementations; only the literal RAM replication
changes their physical storage, not their interfaces or algorithms.

## Mode-4 routing and checksum lifetime

For mode-4 encoding, the parent compressor consumes the original source
and writes its complete LZ4 result into `bellows_l4_intermediate`.
Only after successful compressor status does the context start entropy
encoding, passing the recorded intermediate length as S and the command's
original source length as N. Synchronous single-byte reads supply the
entropy encoder; its resulting BL4H frame enters the normal output queue.

For mode-4 decoding, entropy validates the complete frame and writes the
decoded intermediate stream into the same private buffer. Successful entropy
status captures N, clears the LZ4 history/parser, and starts synchronous
wide reads of the intermediate stream. Empty intermediate streams are
malformed because the parent LZ4 framing requires at least a terminal token.
Final original output length must equal captured N; otherwise code 11 wins
over a simultaneously observed checksum mismatch. The buffer holds
`2*MAX_BLOCK_BYTES+16` bytes, is never shared across channels, and has
synchronous bank reads/writes with no asynchronous array reset.

The preserved pipelined `bellows_l3_checksum` unit consumes original raw
bytes on encoding and reconstructed bytes on decoding. Nonzero checksums
serialize a returned copy beat through an eight-byte checksum staging
register before appending those bytes to the output queue. Mode zero
bypasses that byte serialization and reports zero. Intermediate, codebook,
header, residual framing and padding bytes never enter the checksum.
BF16 residuals enter only as part of reconstructed original words.

Encoding finishes the checksum after accepting every raw source byte;
decoding finishes it only after codec status, all accepted copy operations
and checksum staging drain. Exactly four little-endian checksum bytes are
then appended for encoding, or consumed separately from the input queue
and compared for decoding. Empty inputs use the published empty-message
checksum values, not an assumed zero for nonzero modes.

## Fault, reset and completion settlement

A coincident bus fault has highest priority, followed by codec faults,
block overflow, capacity overflow and checksum mismatch. The first latched
fault remains sticky. A fault gates all new lane reservations, discards
unreserved queue contents, asynchronously aborts local codec/copy control,
and clears intermediate valid state without clearing RAM arrays.
An arbiter-held request is already reserved and must still issue and
settle; it is never silently cancelled. Acknowledged earlier writes are
not rolled back, and failing writes do not increase destination byte count.

SETTLE waits for all locally reserved reads/writes and checksum work to
finish, or for already-aborted local codec work to be irrelevant. Successful
frames first wait for exact source consumption and copy/checksum drain,
then flush all final output before completion. No status is produced based
only on a write request or parser status. COMPLETE holds its fields until
the completion arbiter retires it; that edge cannot also admit a command
to the same context.

Reset gates every public output to zero, aborts all contexts, clears queue
and ownership validity and asynchronously resets architectural controls.
RAM read/write processes do not reset their arrays. Stale contents are
unobservable until fresh, validated command data initializes their logical
range. The external bridge must discard responses from the aborted reset
epoch before release. Read, write and completion directions progress
independently; downstream status backpressure does not block DMA for other
contexts.

## Source-only elaboration and independent evidence

From the delivered root, a static source-only command is:

```
iverilog -g2012 -t null -s bellows_l4_top rtl/*.sv
```

For a legal alternate configuration, add e.g.
`-Pbellows_l4_top.COPY_BYTES=4 -Pbellows_l4_top.MAX_BLOCK_BYTES=17
-Pbellows_l4_top.SG_DEPTH=3` before the source list. See `SPEC.md` for
the five independent verification commands and native gate requirements.
Generated compiler outputs and verification evidence are not design inputs.

Only a fast static syntax/elaboration diagnostic is permitted to Designer.
Functional/reference/performance/defect/synthesis checks belong to the
independent Verifier. All mandatory commands and coverage remain as
specified in `SPEC.md`; no passing result, target PPA or end-to-end speedup
is inferred from this architecture.

The integrated source-only Icarus 12.0 elaboration exited zero at all six
admitted legal geometry tuples. Its retained source hashes, exact commands,
tool version and raw logs are indexed by
`evidence/preparation/integrated-static-elaboration-4075d73cb6244b2e/receipt.json`.
That historical receipt records byte-identical copies of all 13 supplied
parent sources before the RAM-port repair; it does not cover the changed
literal buffer. The earlier partial-source static receipt remains at
`evidence/preparation/static-elaboration-8f4caadab8054f5b/receipt.json`.
Neither diagnostic ran a simulation or synthesis experiment; no failed
diagnostic or measured functional/performance result is claimed.

The RAM-port repair's source-only diagnostic is retained separately at
`evidence/preparation/ram-port-static-elaboration-7e121f18e1784df6/receipt.json`,
with pre-repair snapshots, current source hashes, exact commands and raw
logs. It links the preserved native mapping failure and does not replace
any mandatory functional, synthesis or hardware check.
