# BELLOWS-L5 architecture and implementation handoff

## Current source state

The 23 parent modules have been copied byte-for-byte from
`bellows_l4_reference/rtl/` into `rtl/`. No parent interface or implementation
has been repaired or changed. The historical parent timing and connectivity
qualification is in `GENERATIONAL_HANDOFF.md`, with its private origin path
removed. Those results do not certify L5.

The new modules are connected beneath `bellows_l5_top`, using the frozen parent
transport. This is a Designer implementation handoff, not engineering
acceptance. No functional, interoperability, mutation, synthesis, timing or
hardware pass is claimed; those checks belong to the independent Verifier and
shared runtime.

| Source in rtl/ | Implemented responsibility |
|---|---|
| bellows_l5_top.sv | Four lanes, shared dictionary, inherited arbitration/DMA and configuration priority |
| bellows_l5_context.sv | Per-command legacy/Zstandard route ownership through completion retirement |
| bellows_l5_zstd_context.sv | Descriptor validation, byte/wide transport, queues, counters, first-error settlement and direct entropy instance |
| bellows_l5_frame_engine.sv | Single-block RFC parser/producer, sequence execution, reverse sequence encoding, checksum and output control |
| bellows_l5_buffer.sv | Synchronous byte memories with replicated read views and resettable response ownership |
| bellows_l5_sequences.sv | Nine byte-lane sequence RAM banks with synchronous reads |
| bellows_l5_fse_decoder.sv | One registered dependent table transition; elastic result slot |
| bellows_l5_fse_table.sv | Predefined/RLE/normalized-count table construction and per-alphabet ownership |
| bellows_l5_fse_counts.sv | Forward RFC normalized-count description parser, zero runs and padding |
| bellows_l5_fse_encoder.sv | Multicycle inverse transition lookup and terminal-symbol initialization |
| bellows_l5_bit_writer.sv | Forward little-endian bit packing, RFC terminal marker and byte padding |
| bellows_l5_reverse_reader.sv | Synchronous reverse byte fetching and non-reversed bit-field extraction |
| bellows_l5_entropy.sv | Three owned table banks, three named dependent decoders, shared inverse encoder |
| bellows_l5_dictionary.sv | Atomic dictionary loading, four byte/index views, ordered collision heads and predecessor links |
| bellows_l5_matcher.sv | Per-block dictionary index initialization, verified greedy matching and local updates |
| bellows_l5_mul64.sv | Low-64-bit serial product with two registered 32-bit carry stages per bit |
| bellows_l5_xxh64.sv | Streaming seed-zero XXH64 using registered rounds, merges, tails and avalanche |

Verifier independently authors all Python/tests after the design handoff.
Component interfaces below are private implementation choices; the top, lane
transport, dictionary byte-read and decoder-leaf interfaces remain frozen by
`SPEC.md`. Successful predefined, RLE and compressed-table decoding is
implemented. Repeat-table selectors are rejected before any sequence transition
or match output, including after a prior command; no successful table-reuse
mode is claimed.

The normalized-count builder accepts a single legal symbol with full mass L
without changing compressed mode or tableLog. Its ordinary row construction
starts symbol-next at L and increments through 2L-1: the computed bit count
is zero and base is row address for every row. The 10-bit working state holds
all used values through 1023 at tableLog=9; the final increment is unused.
Exact mass, count range, alphabet/log limits and ownership checks still apply.

## Production hierarchy

```text
bellows_l5_top
  dictionary : bellows_l5_dictionary
  lanes[0..3].context : bellows_l5_context
    legacy : bellows_l4_context
    zstd : bellows_l5_zstd_context
      engine : bellows_l5_frame_engine
        normalized_counts : bellows_l5_fse_counts
        bitstream_encoder : bellows_l5_bit_writer
        reverse_reader : bellows_l5_reverse_reader
        matcher : bellows_l5_matcher
        content_hash : bellows_l5_xxh64
          multiply : bellows_l5_mul64
        private_hash : bellows_l3_checksum
        input_image, raw_image, literal_image, compressed_image : bellows_l5_buffer
        sequences : bellows_l5_sequences
      entropy : bellows_l5_entropy
        tables[0..2].builder : bellows_l5_fse_table
        fse_ll_decoder : bellows_l5_fse_decoder
        fse_of_decoder : bellows_l5_fse_decoder
        fse_ml_decoder : bellows_l5_fse_decoder
        encoder : bellows_l5_fse_encoder
  scheduler : bellows_l4_scheduler
  dma : bellows_l4_sg_dma
```

`entropy` is instantiated directly in each `zstd` context, not in a disconnected
leaf exercise. The frame controller drives its table loading, state
initialization, dependent decoder transitions and inverse encoder. Alphabet
order on packed helper buses is LL, OF, ML.

## Transport, admission and output ownership

The top's command admission gates every child with dictionary-begin priority.
A configuration-busy register spans the accepted begin, upload, index
preparation and status retirement, including an invalid begin. Global quiescence
requires every route wrapper idle, both DMA response slots available, no
reserved scheduler request and no pending completion. A configuration cannot
replace a dictionary that an active lane might read.

Each route wrapper latches codec 5/6 versus legacy only at command acceptance.
The legacy instance receives codecs 0..4 and invalid codec 7 unchanged; codec 7
therefore retains the inherited invalid-command completion. Dictionary ID and
size validation are confined to codec 6. The wrapper gates descriptors,
requests, responses and completion retirement with the selected owner until
retirement. It does not reinterpret any parent payload.

The Zstandard transport collects exact descriptor counts and 37-bit size sums,
checks zero lengths, address wrap and capacity sums, and only then arms the
engine. Following final descriptor edge D, validation is at D+1 and engine
arming at D+2; no DMA offer precedes D+2. Read size is bounded by the current
segment and COPY_BYTES (one in byte mode). One reserved read fills an eight-byte
queue; it is fully fed before reserving another. A 16-byte output queue packs
ascending bytes. A write reservation removes only its valid, strobed bytes;
the shared scheduler retains the payload if the external request stalls.
Partial final beats are released after engine completion, never across a
destination segment.

The first DMA/engine/capacity error stops new reservations and clears unissued
queue contents. Already reserved transactions remain owned and settle before a
single completion. Source counts include all accepted response bytes, including
an error response. Destination counts include only successful acknowledgments.
Private checksum results already computed before a write error are retained.
Completion payloads and the selected route remain held through retirement.

## Frame controller and memory ownership

The engine accepts a start, loads exactly the declared input bytes and then
processes the complete image. Encoding also loads the raw image during that
input pass; decoding writes the raw image only through validated literal/match
execution. Zero input needs no fabricated stream beat. Truncated frame input,
including an empty decode input, produces error 11, rather than a successful
empty output or an invalid-command length substitute.

The forward parser and reverse reader share one synchronous input-image read
port; a registered response owner distinguishes their replies. Their phases do
not overlap. The raw image has two physically replicated synchronous read views
for matching. Literal and candidate images use a single read view; unused
replicas in the generic helper can be removed by synthesis. No array contents
are asynchronously reset. RAM validity derives from command-local lengths and
control, not stale stored contents.

Encoding greedily accumulates raw literals and LL/ML/offset-value tuples from
the matcher. Verified long matches are split into legal chunks of at most 1024
bytes (adjusting a final chunk to stay at least four bytes). This deliberately
produces multiple actual FSE sequences for the dictionary page fixtures instead
of hiding the entire page in one terminal sequence. The first chunk receives
the pending literals; subsequent chunks use LL=0. Encoder offsets always use
the ordinary positive-distance representation `offset_value=distance+3`;
the decoder additionally implements every RFC repeat-offset case.

After constructing all three predefined banks, the encoder emits a three-byte
raw-literal header, compacted literals, sequence count and predefined-mode
selector. Sequence RAM is read backwards. Terminal symbols initialize encoder
states without transition bits. Earlier sequences emit inverse transition
fields in OF/ML/LL order and extra fields in LL/ML/OF order. Final state fields
are emitted ML/OF/LL, then the stop marker. Candidate bytes are counted as they
are actually packed. Use the candidate only when strictly smaller than the raw
block; equality and candidate-buffer exhaustion use raw fallback.

Decoding checks magic, the bounded descriptor/window, final-block bit, content
size, block type/size and exact frame extent. Recognized skippable frames,
non-final blocks, concatenated frames and unsupported literal/header profiles
do not decode partially. A compressed block parses its raw/RLE literal
section and variable sequence count. Any repeat selector is rejected for all
alphabets before preparing or executing a table. Predefined/RLE table starts
and compressed normalized-count parsing share the actual entropy banks.
Initial states are read LL/OF/ML. Each sequence reads extras OF/ML/LL,
validates literal and reconstructed bounds and available dictionary/history,
then executes incremental byte copies. Between nonterminal sequences it
updates the actual decoder leaves LL/ML/OF. Terminal sequences consume no
transition bits and require exact reverse-stream exhaustion.

Repeat offsets begin at {1,4,8}, independently of dictionary and entropy tables.
Non-repeat distances shift all three entries. With nonzero LL, repeat 1 is
unchanged, repeat 2 swaps the first two, and repeat 3 rotates all three.
With zero LL the selector advances one, including inserting repeat1-1 for
offset value 3; distance zero is rejected. The match source is computed in
registered address stages after literal execution, then incremented per copied
byte. This supports distance-1/2 overlap and dictionary-to-output crossing
without a combinational history search or speculative unverified copy.

Both hashes consume the complete reconstructed raw image through coupled
byte handshakes; the faster hash cannot consume a byte twice while the other
stalls. Decode checks the standard XXH64 trailer and any selected private
trailer before exposing raw output. This implementation therefore buffers
checksum-failing output rather than promising rollback of earlier writes.
Integrators must still follow the contract's general rule that any output of
an unsuccessful command is untrusted. Encoding emits the exact 13-byte
frame/block prefix, selected body, low-32-bit XXH64 and optional private trailer.
Frame/output sizes and destination capacity are checked before emission.

## Cycle, reset and storage decisions

The normative Cycle & Degenerate-Boundary Table is in `SPEC.md`; it was fixed
before new RTL. New components deassert readiness during active reset and before
the first post-reset active edge. Asynchronous resets initialize control and
valid metadata, never large arrays. A private synchronous `clear` cancels a
component transaction; it must only be driven by clocked command/abort control.
The entropy wrapper also holds its decoder leaves reset while clear is asserted
so pending symbol slots cannot survive a command epoch.

Dictionary byte views are physical replicas with a common write handshake and
registered reads. Each enabled view samples its address at E and asserts data/
valid immediately after E. Seed views have the same timing. The matcher likewise
expects synchronous byte-read responses, qualified by valid; it tolerates
additional response latency. Requests are one-edge pulses, not ready/valid DMA.
The reverse reader has at most one such memory read outstanding.

`bellows_l5_buffer` implements each replicated byte view with the unchanged
inherited `bellows_byte_ram` primitive. `bellows_l5_sequences` uses nine
instances of that primitive, preserving the byte-lane order of `{wof,wml,wll}`.
Physical RAM addresses use `max(1,$clog2(depth))` bits. Full-width address
comparisons remain outside the primitive and gate its enables before address
narrowing; an invalid address cannot alias a valid entry. This includes depth
one and unused binary addresses at non-power-of-two depths.

| Buffer/sequence boundary | Preserved behavior |
|---|---|
| Before edge E | Sample enables, full-width addresses and write payload. |
| Valid read at E | Registered RAM data and response valid appear immediately after E; no extra pipeline stage. |
| Read and write at E, same address | Read returns the old byte/tuple; write updates storage for later reads. |
| Read and write at E, different addresses | Both operations proceed independently. |
| Invalid read/write address | Suppress that RAM access; invalid read produces valid=0 and zero public data. |
| Active reset | Gate all RAM accesses; asynchronously clear response validity and mask public data to zero, without resetting storage. |
| Depth one | Physical address width remains one; only full-width address zero is enabled. |

This storage repair addresses the demonstrated failure in
`evidence/preparation/ram-resource-discriminator-20261103T103801Z-32b5f677/receipt.json`:
the inherited control retained 16384 block-memory bits while the previous L5
buffer and sequence arrays retained none. The repaired inference, functional
latency/reset/collision behavior and legal geometries require fresh independent
Verifier checks. That failed receipt remains historical evidence; neither this
repair nor static elaboration establishes native RAM retention or timing.

Private helper `clear` wins over all handshakes. Every valid result remains
stable until ready. The table builder invalidates ownership on reset, clear and
accepted replacement; a table becomes owned only at successful commit.
Physical table/seed/history arrays are not reset. No current component uses
division or remainder. None has an unbounded combinational search.

The public top diagnoses illegal parameters explicitly and gives its children
safe diagnostic-only parameter values, avoiding zero-width/negative-range
elaboration before the diagnostic. This applies the bounded lesson in
`exp-6d5cc92e6f5a86894eaae275`; it does not clamp any legal geometry or replace
the independent illegal-parameter checks.

## Dictionary and match preconditioning

`idle_all` at the dictionary input is guaranteed by the top:
all four lane admissions idle, all responses settled, no pending completion.
The top gates commands with dictionary begin priority and with the complete
upload/preparation/status lifetime. The dictionary itself does not arbitrate
commands or inspect DMA state.

Four image replicas use byte arrays. Four synchronous seed views contain
1024 direct-mapped head positions each, with shared resettable validity metadata.
Each view also contains two byte-lane predecessor arrays, one entry per
dictionary byte. Every entry stores a 14-bit prior position and its valid bit;
unused bits are zero. At default geometry the image replicas total 65536 bytes,
the predecessor replicas total 131072 bytes, and the head positions total
7168 logical bytes, excluding validity/control and physical RAM allocation.
Upload maintains a rolling little-endian four-byte prefix and seeds in strictly
increasing start address order. At HASH, register the key and synchronously read
the old head. At INDEX, save that head and its validity as the new position's
predecessor, then replace the head. Backpressure prevents another byte changing
the key before insertion. The newest collision remains the direct-mapped head,
but no earlier four-byte dictionary prefix is discarded. After the last byte,
finish any insertion, atomically pin ID/size, then offer the held status.
Length-one images have no four-byte seeds and still pin correctly.

The private index request has per-lane enable, chain-select and 14-bit address.
With chain-select zero, address[9:0] selects a hash head; with it one, the address
selects a predecessor entry. The response is registered valid/found/position,
with the same one-edge timing as a byte read. No request overlaps configuration.
Only initialized entries with address+4 <= pinned_size may be read. Invalid
head ownership or a terminal predecessor returns found=0. The externally frozen
dictionary byte-read interface and all top-level ports are unchanged.

The common ten-bit prefix hash is defined explicitly:

```text
H[7:0] = byte0 XOR rotl8(byte1,1) XOR rotl8(byte2,2) XOR rotl8(byte3,3)
H[9:8] = prefix[9:8] XOR prefix[25:24]
```

The matcher queries each prepared dictionary seed once per dictionary-assisted
block and copies the valid positions into a private, dictionary-only 1024-entry
bank. A separate 1024-entry local bank starts unowned for every block. Both
banks use synchronous reads and unreset storage; their ownership metadata is
invalidated on reset, clear and command start. Dictionary preparation preserves
the most recent dictionary position per hash as its chain head. Local updates replace only local
positions, including insertions at skipped positions after a match: they cannot
evict a dictionary candidate. No preceding page becomes local history.
A virtual position addresses dictionary||current-input.

At LOOKUP edge E, capture the old local candidate and its ownership while
installing the current local position (read-before-write). CANDIDATE after E
validates its positive distance before issuing any byte reads. After comparing
that candidate, a separate DICT_LOOKUP edge synchronously captures the pinned
candidate and ownership for the same hash; codec 5 skips this step entirely.
Each candidate is extended through registered byte requests/comparisons. A
candidate-completion stage retains the longer verified match, choosing the
smaller positive offset on equal lengths. After each dictionary candidate,
CHAIN_REQ/CHAIN_WAIT retrieve its predecessor; traversal continues until the
chain ends or a verified match covers the complete remaining input. Local
candidates precede dictionary candidates, and dictionary positions strictly
decrease, so no later candidate can improve the offset of a full-tail match.
The controller rejects a non-decreasing or out-of-range predecessor with error
8 instead of following a corrupted internal index. A separate result-selection
stage publishes the winning token, or one literal if no length reaches four.
A rejected hash collision therefore never suppresses an earlier pinned
dictionary candidate. No new requests occur while the final token is stalled.
Reset/replacement invalidates head ownership; unreset predecessor RAM is
reachable only through the new image's initialized, strictly descending chains.

Every candidate byte is compared, including all four prefix bytes. The local
input image is fully available before matching. Comparing an overlapping
candidate against that image is valid by induction: preceding compared bytes
establish that an incremental decoder copy reproduces each following byte.
A dictionary candidate can continue past the dictionary end into local byte zero.
Matcher output is one token: position, length and distance; a literal token has
length one and m_match=0, a match has length>=4. Tokens are held under stalls.
After a match, every skipped position with a complete four-byte prefix is
inserted before searching at the resume position.

This separation repairs the destructive dictionary/local replacement exposed
by `evidence/preparation/l5-dictionary-page16k-verilator-20261103T043535Z-b185db0e/receipt.json`.
That retained run failed the unchanged gain thresholds (aggregate frame/raw-LZ4
bytes 28723/28790). Independent same-seed rerun and all nine gain cases remain
required; the RTL repair and static elaboration do not establish compression
gain, round-trip correctness or physical timing.

## FSE construction, decoding and encoding

Alphabet order on private packed buses is LL=0, OF=1, ML=2. Each has an independent
table builder and owner. Modes are RFC predefined=0, RLE=1, compressed=2, repeat=3.
The entropy wrapper latches table-load selection through its held completion,
routes the normalized count stream only to that bank, and prevents transitions
during table loading/inverse encoding. Any failed table or repeat selector
latches a frame fault until clear. Repeat always reports malformed error 11,
even when physical RAM previously held a successful table.

The count parser accepts bytes only when its reservoir lacks the next required
field. It first decodes tableLog and holds log_valid until the controller starts
the matching compressed table bank. It does not read a full-width field before
deciding whether the short representation suffices, avoiding an extra table byte
being consumed from the next section. Once the probability mass is complete,
unused bits in the last byte are ignored and missing trailing symbols are
explicitly output as zeros. count_last coincides with the alphabet's maximum
symbol. s_last denotes the end of the available source span, not a guessed
table boundary. bytes_used counts accepted table bytes.

The builder's compressed-count input is ordered and complete: all codes 0..35
for LL, 0..31 for OF and 0..52 for ML, including zeros. Count -1 has mass one;
positive values use their value; total mass must equal L with at least two
nonzero symbols. Predefined distributions are numerical constants from RFC 8878
section 3.1.1.3.2.2, not tables extracted from the DUT or verification model.

The builder clears only its small normalized-count scratch ownership by a
64-cycle walk; reserves -1 cells from the high end; places positive symbols
using masked RFC spreading; and constructs rows in ascending state order.
For symbol-next value n:

```text
k = tableLog - floor(log2(n))
base = (n << k) - L
symbolNext[symbol] = n + 1
```

The logarithm is a bounded multicycle shift, not a priority tree. Small
distributed row memories have combinational reads to permit a single dependent
transition every edge. Decoder state selects the row; the leaf itself is exactly
one register-to-register transition cycle. Frame-controller/reverse-reader
latency is additional and must not be reported as one-cycle end-to-end decoding.

The inverse encoder scans one row per cycle for a matching symbol whose
interval includes the desired following state. It emits the predecessor state
and interval displacement. For the terminal sequence, select a row for each
last symbol with s_terminal=1 and emit no transition bits. This is the RFC
final-symbol rule, not a zero-fill attempt to consume nonexistent bits.
The connected controller traverses sequences backward and interleaves extra
bits, states and marker as described above.

`bellows_l5_bit_writer` appends low s_nbits bits of each input field, LSB first,
drains full bytes in ascending output order, then appends one stop bit and
zero padding. nbits=0 is legal. The reverse reader finds that marker, retains
only lower useful bits, and consumes each requested field from the high end
without reversing bits inside that field. It issues no speculative extra read
when buffered bits already suffice. It errors rather than zero-filling an
over-read; exact exhaustion is available for terminal validation.

## XXH64 arithmetic

XXH64 uses the standard seed-zero four accumulators, 32-byte stripes, LE 64-bit
lanes, round rotation 31, stripe combination rotations 1/7/12/18, merge rounds,
8/4/1-byte tails, rotations 27/23/11 and avalanche shifts 33/29/32.
The five 64-bit primes are literal constants. All stored arithmetic truncates
to 64 bits. The frame controller emits result[31:0] in LE order.

Each low-64-bit product uses the serial `bellows_l5_mul64` component: two clocks
per multiplier bit, low-half addition then high-half addition with registered
carry, 64 iterations. There is no one-cycle 64x64 combinational multiply.
Other checksum additions, rotations, XORs and stores have distinct control
states. The area/latency tradeoff is deliberate; no whole-block throughput was
specified. This is an implementation rationale, not timing proof.

Start and result have separate handshakes. s_ready is low during arithmetic.
finish_valid has priority over another byte in COLLECT; callers must finish
only after the final byte handshake. Empty input runs the ordinary seed-zero
short-message path. Private XXH32/CRC32 use the parent unit and receive the same
complete raw bytes.

## Analytical operation limits for later verification

These are conservative operation-count bounds under fair service, not measured
latencies or wall-clock acceptance thresholds:

| Component | Bound excluding external stalls |
|---|---|
| Dictionary preparation | <=3*D+8 clocks after begin through offered status |
| Matcher per block | <=32*(D+2)*(B+1)*(B+1)+4096 clocks with synchronous one-edge byte/index responses |
| Table build | <=64+64+2*L+L*(tableLog+4)+1024 clocks after count stream |
| Inverse transition | <=L+4 clocks |
| Bit writer | One input field plus up to five byte handshakes per <=32-bit field |
| Reverse reader | <=32 clocks per <=32-bit field with one-edge memory service |
| XXH64 | <=2048*(B+1)+8192 clocks from start to result, excluding input gaps |
| Frame controller | <=64*(D+2)*(B+1)*(B+1)+8192*(B+1)+65536 internal clocks for a valid supported block, including matching, tables and hashes |

Here B is the block size and D is the selected dictionary size (zero for codec
5). Each dictionary chain has at most max(0,D-3) entries. The conservative matcher
bound permits repeated long comparisons for every collision at every input
position; all searches are sequential, not a combinational priority chain.
Typical greedy operation is much smaller but unmeasured.
Use compiled Verilator for page/multi-seed/defect workloads; Icarus only for the
admitted compact startup/leaf/frame cases.

## Integration and evidence map

Compile the complete `rtl/*.sv` source set with `bellows_l5_top` as top; do not
compile the immutable reference directory into the same library (its parent
module names intentionally match the delivered copies). No source generation,
memory initialization file, software codec, host address or runtime state file
is a product prerequisite. Use one synchronous clock and active-low asynchronous
control reset, with reset released between edges. Reset the attached DMA peer's
transaction epoch as well: the inherited untagged response interface cannot
identify responses from an external transaction abandoned by reset.

After the first active post-reset edge, load a dictionary if codec 6 is needed:
handshake begin, stream the exact declared bytes/last, and retire status.
Then handshake each command and its exact declared source/destination
descriptors. Descriptor streams can be interleaved by channel and destination
flag. Service the selected byte or wide DMA requests and their responses;
completion must be retired before that lane can accept another command.
While a dictionary upload/status is active, command admission remains closed.
All external addresses are application-supplied unsigned values, never local
device identifiers.

The connected controller's command/descriptor checks, raw buffering, first-error
retirement, frame guards, three successful table modes, repeat rejection,
exact reverse exhaustion, repeat offsets, history copies and both checksum
layers all require independent execution evidence. A raw fallback cannot
replace FSE or dictionary-gain coverage. The earlier component-only static
receipt is `evidence/preparation/l5-static-20261103T041543Z-34f7fb76/receipt.json`;
the first integrated-top static receipt is
`evidence/preparation/l5-top-static-20261103T042403Z-def7d1de/receipt.json`.
Neither is functional acceptance. Later source-bound static receipts, if any,
are cited in the Designer handoff rather than replacing these records.

| Claim | Required independent evidence |
|---|---|
| Legacy preservation | Parent comparison plus independent numerical/library scoreboards |
| RFC losslessness/interoperability | Python, RTL and libzstd full-byte cross-decodes |
| Dictionary gain | All nine fixed page cases and actual inherited/liblz4 baseline |
| One-cycle FSE recurrence | Exhaustive row/state/bit checks and >=256 dependent cycles |
| Corruption/recovery | Exhaustive short flips/truncations, seeded pages, negative/recovery scoreboards |
| Defect sensitivity | Six separately executed semantic mutant kills |
| Structural hardware | Real Yosys, retained memories, connected engines and zero latches |
| 100-MHz physical timing | Mandatory shared-runtime Quartus STA, not generic synthesis |
| Arria 10 hardware behavior | Native hardware bridge gate, accurately qualified workload tier |
| Portable delivery | Fresh copied-source Icarus/Verilator/library reproduction |

All commands and tool prerequisites are in `SPEC.md`; Verifier must implement
the listed commands without reducing their admitted coverage. No such check
has yet been authored or run by Designer. The final product PDF is a later,
shared-runtime-owned artifact after independent engineering acceptance.
