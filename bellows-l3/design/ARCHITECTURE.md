# BELLOWS-L3 implementation

## Status and source inventory

This is the Designer implementation handoff, not engineering acceptance.
Functional simulation, independent numerical comparisons, synthesis, timing and
hardware checks belong to subsequent independent stages. Source inspection and
syntax elaboration do not establish any of those results.

The self-contained delivery consists of `rtl/*.sv`, `design/SPEC.md`,
this document, and independent Verifier-owned `tests/*.py`. The product PDF is
authored and independently reviewed by the shared runtime after acceptance.
The eight reference files are retained unchanged in
`bellows_l2_reference/rtl/`; they are not needed to elaborate delivered RTL.

## Hierarchy and ownership

```
bellows_l3_top
  scheduler: bellows_l3_scheduler
    read_arbiter: bellows_l3_arbiter
    write_arbiter: bellows_l3_arbiter
    completion_arbiter: bellows_l3_arbiter
  dma: bellows_l3_sg_dma
  lanes[0..3]
    context: bellows_l3_context
      codec: bellows_l2_top
        compressor: bellows_l2_compressor
          literal_buffer: bellows_l2_literal_buffer
          hash_match: bellows_l2_hash_match
          emitter: bellows_l2_emitter
        decompressor: bellows_l1_top
          history: bellows_l1_history
          output_stage: bellows_l1_output
      checksum: bellows_l3_checksum
```

`context` is written as an escaped SystemVerilog identifier (`\context `)
because the unescaped spelling is a language keyword. The elaborated instance
name is still `context`.

Four full codec instances preserve independent history and genuine match
generation. There is no global whole-frame codec lock. Read and write buses
are independent byte masters for adaptation by the runtime PCIe bridge.
The design contains neither a PCIe endpoint nor host-specific cable/BDF data.
`roundtrip_enable` is tied low inside each context; standalone L2 retains it.

| Resource | Producer / owner | Release / consumer |
|---|---|---|
| Command registers | selected idle lane at command handshake | accepted lane completion |
| Source/destination SG lists | lane descriptor collector | same lane only, through frame retirement |
| Read reservation | scheduler takes one lane request | returned read response |
| Input holding byte | DMA response captured by owning lane | codec/checksum joint transfer, or trailer capture |
| Codec output slot | selected codec output handshake | scheduler write reservation |
| Write reservation | scheduler takes one lane slot | returned write acknowledgment |
| Checksum state | logical content transfer in owning lane | finalization and completion snapshot |
| Shared status slot | scheduler snapshots completed lane | public status handshake |

Scheduler reservations are internal handshakes, distinct from external DMA
request acceptance. They freeze address/data and mark the lane pending. DMA
exports independent read/write availability from its registered outstanding
bits, not from external request ready. An empty request arbiter takes a lane
only while its DMA direction is available. While another transaction is
outstanding, eligible requests remain in their lanes, where a fault can discard
them; no hidden shared reservation is created.

At reservation edge E, the direction has no outstanding transaction and the
shared slot is empty. The registered request therefore becomes publicly valid
post-E, without waiting behind another transaction. That presentation is
noncancelable: preserve valid/payload through external stalls and settle any
accepted response even if the other direction subsequently fails. Current
faults suppress lane eligibility before reservation, including checksum
mismatch at frame finalization; earlier DMA/codec/capacity errors retain their
priority. Availability gates slot loading only, never an occupied slot's valid
or retirement. Per-direction global outstanding ownership is set only by
external acceptance and cleared only by its response. A response at Er clears
that direction's outstanding bit post-Er; a new request can enter its empty
shared slot at Er+1 and first transfer at Er+2. Read and write scheduling remain
independent, and round-robin pointers advance only on accepted requests.

## Context controller and registered paths

The eight context states are:

| State | Operation and exit |
|---|---|
| IDLE | Accept one command; reject invalid metadata directly to COMPLETE. |
| COLLECT | Accept each declared direction count; retain bad-descriptor flag while draining the remaining list. Final descriptor enters VALIDATE. |
| VALIDATE | Compare registered widened sums and descriptor errors; valid list enters ARM, invalid list completes with code 8 and no DMA. |
| ARM | Initialize current segment addresses, start checksum, then enter RUN. |
| RUN | Independently feed codec, consume trailer, capture output and finish checksum. Await codec completion and all source bytes. |
| TRAILER | Compression only: queue four checksum bytes in little-endian order, with capacity enforcement. |
| SETTLE | Drain previously reserved reads/writes; allow queued successful output to reserve a write; finish checksum after processing errors. |
| COMPLETE | Stable lane status; retain busy until the shared status handshake retires it. |

At final descriptor edge Ek the state becomes VALIDATE. Ek+1 registers successful
validation by entering ARM. Ek+2 enters RUN, making a lane DMA request eligible;
the shared request register can load at Ek+3. This is deliberately not a
combinational descriptor-to-DMA bypass.

Read responses enter `input_data/input_valid/input_index` on Er and cannot
reach the codec before Er+1. The input slot is reserved before the external
request, so response ready never depends on instantaneous codec readiness.
Compression content transfers to codec and checksum atomically, gated by both
readies. Empty compression injects exactly one keep=0,last=1 marker and never
reads source memory. Decompression sends only payload bytes into the codec;
four optional trailer bytes are assembled separately. Decoded codec output
transfers atomically into its lane write slot and checksum.

A codec output captured at Ec can reserve the shared write register at Ec+1
and transfer externally no earlier than Ec+2. The lane can hold another codec
output while its previous write awaits acknowledgment. It cannot reserve that
next write until the acknowledgment updates the segment address. Counts and
segment pointers advance on responses, not on request presentation.

Codec status is consumed once and remembered by `codec_done`. Checksum finish
is handshaken once and remembered separately. Compression finalizes after the
last content input (possibly while its codec is still matching); decompression
finalizes after its codec has retired all output. Once internal work is done,
SETTLE tests outstanding-response retirement, registers COMPLETE, and the shared
status register adds one more stage before public transfer. A response on the
settlement edge counts before the status payload is snapshotted. An empty
decoded frame uses the same internal completion and shared-status registers,
without manufacturing a destination beat.

The first current fault suppresses new codec transfers and DMA reservations,
discards unreserved input/output slots and resets the lane codec. Reserved bus
transactions still retire and update consumed-read/successful-write counters.
Checksum finalization proceeds over content accepted before the fault. A trailer
mismatch is detected only after otherwise successful parsing and checksum
finalization; it discards unreserved output, preserves accepted bus work and
reports the computed checksum. Destination bytes are untrusted until status
success. Descriptor/command errors complete without starting the checksum.

## Checksum microarchitecture

The checksum module shares a registered 32-bit product/work datapath. Every
dependent multiplication, addition and rotation is separated by a clocked state.
All registers and operands are unsigned, with assignment truncation implementing
32-bit wrapping. Fixed rotate wiring and logical shifts implement the exact
rules in SPEC.md. No divide or remainder operator is used.

| Local states | Purpose / edge count |
|---|---|
| COLLECT | Accept one content byte; finish has priority over input. |
| CRC_STEP | Exactly eight single-bit CRC edges per accepted byte. Next byte is first accepted nine edges after the previous byte. |
| STRIPE_MUL, STRIPE_ADD, STRIPE_ROT, STRIPE_SCALE, STRIPE_STORE | Five edges per XXH32 accumulator, four accumulators, 20 processing edges per complete stripe. |
| COMBINE1, COMBINE2, COMBINE3 | Add the three remaining rotated lanes to rotated v1, one per edge. |
| LENGTH_ADD | Add registered total content length. |
| TAIL | Select a remaining word, byte or avalanche. |
| WORD_MUL, WORD_ADD, WORD_ROT, WORD_SCALE, WORD_STORE | Five arithmetic/storage edges plus TAIL selection for each remaining word. |
| BYTE_MUL, BYTE_ADD, BYTE_ROT, BYTE_SCALE, BYTE_STORE | Five arithmetic/storage edges plus TAIL selection for each remaining byte. |
| XOR15, AV_MUL2, XOR13, AV_MUL3, XOR16 | Five avalanche edges, then DONE. |
| DONE | Hold result until the next frame's start. |

The XXH buffer is 128 bits of registers with a 0..16 fill count. Full stripes
are processed immediately, then the buffer is shifted empty before accepting
the next byte. Following stripe-completing acceptance at E, processing edges
E+1..E+20 return to COLLECT and the next byte can transfer at E+21. There are
no length-dependent combinational loops.

After an accepted finish at F, mode none/CRC produces a result post-F.
XXH short-input result appears post-F+7+6W+6B; after at least one stripe it
appears post-F+10+6W+6B. W is the remaining full-word count and B the remaining
byte count (0..3); W<=3. These counts begin only when finish_ready is high:
CRC or stripe work already in progress delays finish acceptance. The lane
captures result on a following edge. Checksum latency therefore does not imply
a fixed frame latency.

## Parent reuse and memory implementation

Parent codec control, matching, encoding, decoding and public interfaces are
copied rather than replaced. The compressor retains collection, candidate
encoding, comparison with literal-only size and its valid literal fallback.
Hash matches require valid direct-mapped entries and byte comparison, preserve
overlap support and reserve final literals. Decoder retains malformed-boundary,
offset, arithmetic and keep/error semantics.

Two memory-read reset implementations were adjusted for FPGA RAM inference:
`bellows_l1_history` and `bellows_l2_literal_buffer` use clock-only registered
RAM reads plus asynchronously reset valid bits and zero-gated public data.
No history/payload array is reset wholesale. The literal-buffer legal storage
range and latency remain unchanged. Hash-match public address/result outputs
are explicitly zero-gated during reset. These bounded internal changes require
independent parent regression; the reference directory is unmodified.

Large arrays carry `nomem2reg` and block-memory style attributes. Each lane
has approximately B raw bytes, 2B+16 encoded bytes, 65536 history bytes and
512 hash-table bytes, where B=MAX_BLOCK_BYTES. At the default this is
262672 bytes per lane before FPGA port replication, or 1050688 bytes across
four lanes. This is an analytical storage estimate, not a mapped utilization
claim. Small SG metadata lists use indexed register storage; their entries are
never observed before the complete-list validation barrier. Maximum SG metadata
is two lists of 16*(64+32) bits, or 384 bytes per lane.

No sequential process mixes blocking and nonblocking assignments. Memory
storage processes are clock-only; control uses asynchronous active-low reset.
Address arithmetic is widened for descriptor validation. Explicit segment-end
comparisons handle singleton and non-power-of-two SG depths. There is no
division/remainder, unrolled variable-length loop or chained multiply/rotate
cascade. Generic synthesis is not proof of the required 10 ns physical period.

## Integration and reproduction

Compile all delivered RTL together, selecting `bellows_l3_top`. Example static
syntax/elaboration command, run from the project root:

```
iverilog -g2012 -s bellows_l3_top -t null rtl/*.sv
```

Assert rst_n low before traffic; reset/drain the DMA bridge at the same time.
Release reset, handshake commands on available channels, then supply exactly
their declared source/destination segments in each direction's acceptance order.
Keep command and SG payloads stable through stalls. Serve accepted byte
requests with exactly one ordered response each, no earlier than the next edge.
Hold DMA responses stable through any response stall. Acknowledge status before
reusing its channel. Never overlap active source/destination memory ranges.

Portable functional/synthesis/reproduction entry points and prerequisites are
listed in SPEC.md. Clean staging must copy only declared RTL, Python verification
and design documentation, not reference binaries, evidence or runtime metadata.
Use fresh output directories. No final PDF is an engineering-check dependency.

## Claim-to-evidence obligations

| Claim | Mandatory independent evidence |
|---|---|
| Parent behavior and IEEE-1800 portability | Real compact Icarus/vvp smoke, including keep/error/empty/round-trip APIs |
| Bit-exact content and checksum correctness | Independent Python LZ4 parser/block generator, canonical XXH vectors, zlib CRC, DMA hardware round-trips |
| Four-channel ownership, stalls and guards | Compiled Verilator matrix with byte/address/completion scoreboard and measured coverage |
| Real defect sensitivity | Four executed disposable RTL mutants with intended functional failure, not compile failure |
| Synthesizable state/memory and no latches | Actual memory-preserving Yosys synthesis, check -assert, explicit latch checks and retained JSON |
| Portable delivery | Fresh output-owned staging and real compact simulation/reference plus representative synthesis |
| Physical 100 MHz operation | Runtime-native timing lint and Quartus 17.1 STA, WNS>=0 at 100 MHz |
| Physical PCIe bridge integration | Runtime Arria 10 GX Gen3x8 HIL, three consecutive deterministic passes |

The admitted matrix is (B,SG)=(1,1),(3,3),(15,1),(16,3),(255,16),
(256,3),(4096,16),(65536,16), each at seeds 17,89,2027, at least 48 frames
per cell/seed and every channel x operation x checksum mode. Every cell includes
maximum-length successful compression and decompression and consecutive channel
reuse. Unsupported long or multi-segment cases must be exercised in capable
cells, not silently counted in singleton cells.

Measured coverage must include four simultaneous contexts, 32 adjacent accepted
channel switches with multiple eligible contexts, bounded arbiter fairness,
17-cycle read/write/status stalls, response gaps, both-direction SG crossings,
single-byte segments, untouched guards, all 16 descriptors, exact/insufficient
capacity, empty and first/last bytes, checksum boundary lengths and known answers,
MAX and MAX+1, malformed offsets/extensions/history wrap, descriptor/address/sum
errors, DMA errors, reset in collection/processing/stalled completion and reuse
after success/failure. Each channel and enabled checksum algorithm needs at
least eight otherwise-valid trailer-corruption detections, including individual
bit flips and an SG boundary. No successful corrupted output is admissible.

Synthesis must cover default, (1,1), (3,3), retained parents, legal elaboration
boundaries and executable illegal-parameter diagnostics. Native timing and HIL
gates remain independent and mandatory. This table identifies evidence still
to be produced; it does not assert those checks have passed.
