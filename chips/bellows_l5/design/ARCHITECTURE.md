# BELLOWS-L5 architecture and implementation handoff

## Current source state

The 23 parent modules have been copied byte-for-byte from
`bellows_l4_reference/rtl/` into `rtl/`. No parent interface or implementation
has been repaired or changed. The historical parent timing and connectivity
qualification is in `GENERATIONAL_HANDOFF.md`, with its private origin path
removed. Those results do not certify L5.

The following new modules are implemented as standalone, synthesizable
components. They are **not yet integrated into a working L5 top**. No functional,
interoperability, mutation, synthesis, timing or hardware pass is claimed.

| Source in rtl/ | Implemented responsibility |
|---|---|
| bellows_l5_fse_decoder.sv | One registered dependent table transition; elastic result slot |
| bellows_l5_fse_table.sv | Predefined/RLE/normalized-count table construction and per-alphabet ownership |
| bellows_l5_fse_counts.sv | Forward RFC normalized-count description parser, zero runs and padding |
| bellows_l5_fse_encoder.sv | Multicycle inverse transition lookup and terminal-symbol initialization |
| bellows_l5_bit_writer.sv | Forward little-endian bit packing, RFC terminal marker and byte padding |
| bellows_l5_reverse_reader.sv | Synchronous reverse byte fetching and non-reversed bit-field extraction |
| bellows_l5_entropy.sv | Three owned table banks, three named dependent decoders, shared inverse encoder |
| bellows_l5_dictionary.sv | Atomic dictionary loading, four byte/index views, ordered collision seeding |
| bellows_l5_matcher.sv | Per-block dictionary index initialization, verified greedy matching and local updates |
| bellows_l5_mul64.sv | Low-64-bit serial product with two registered 32-bit carry stages per bit |
| bellows_l5_xxh64.sv | Streaming seed-zero XXH64 using registered rounds, merges, tails and avalanche |

Remaining implementation is mandatory, not a scope exclusion:
`bellows_l5_top`, route-latched `bellows_l5_context`, inherited-transport-compatible
`bellows_l5_zstd_context`, complete single-block RFC frame encode/decode control,
sequence/literal storage and execution, repeat-offset resolution, private
checksum integration and safe DMA/error completion. These must connect the
components above to production paths, not leave demonstration instances.
Verifier independently authors all Python/tests after the completed design
handoff. Existing component interfaces below are private implementation choices;
the top, lane transport, dictionary byte-read and decoder-leaf interfaces remain
frozen by `SPEC.md`.

## Intended production hierarchy

```text
bellows_l5_top
  dictionary : bellows_l5_dictionary
  lanes[0..3].context : bellows_l5_context
    legacy : bellows_l4_context
    zstd : bellows_l5_zstd_context
      entropy : bellows_l5_entropy
        tables[0..2].builder : bellows_l5_fse_table
        fse_ll_decoder : bellows_l5_fse_decoder
        fse_of_decoder : bellows_l5_fse_decoder
        fse_ml_decoder : bellows_l5_fse_decoder
        encoder : bellows_l5_fse_encoder
      bellows_l5_fse_counts
      bellows_l5_bit_writer
      bellows_l5_reverse_reader
      bellows_l5_matcher
      bellows_l5_xxh64
        multiply : bellows_l5_mul64
      inherited private-checksum unit and synchronous byte memories
  scheduler : bellows_l4_scheduler
  dma : bellows_l4_sg_dma
```

In this diagram only the component hierarchy beneath `bellows_l5_entropy` and
`bellows_l5_xxh64` exists so far. The enclosing production hierarchy is pending.

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

Private helper `clear` wins over all handshakes. Every valid result remains
stable until ready. The table builder invalidates ownership on reset, clear and
accepted replacement; a table becomes owned only at successful commit.
Physical table/seed/history arrays are not reset. No current component uses
division or remainder. None has an unbounded combinational search.

## Dictionary and match preconditioning

`idle_all` at the dictionary input is a guarantee required from the future top:
all four lane admissions idle, all responses settled, no pending completion.
The top must gate commands with dictionary begin priority and with the complete
upload/preparation/status lifetime. The dictionary itself does not arbitrate
commands or inspect DMA state.

Four image replicas use byte arrays. Four synchronous seed views contain
1024 direct-mapped positions each, with shared resettable validity metadata.
Upload maintains a rolling little-endian four-byte prefix and seeds in strictly
increasing start address order. HASH and INDEX are separate states; backpressure
prevents another byte changing the key before insertion. After the last byte,
finish any insertion, atomically pin ID/size, then offer the held status.
Length-one images have no four-byte seeds and still pin correctly.

The common ten-bit prefix hash is defined explicitly:

```text
H[7:0] = byte0 XOR rotl8(byte1,1) XOR rotl8(byte2,2) XOR rotl8(byte3,3)
H[9:8] = prefix[9:8] XOR prefix[25:24]
```

The matcher queries each prepared dictionary seed once per dictionary-assisted
block and copies the valid positions into its private index. No dictionary
content from a preceding block becomes local history. Local updates overwrite
older virtual positions, naturally preferring the nearest candidate in a hash
collision. A virtual position addresses dictionary||current-input.

Every candidate byte is compared, including all four prefix bytes. The local
input image is fully available before matching. Comparing an overlapping
candidate against that image is valid by induction: preceding compared bytes
establish that an incremental decoder copy reproduces each following byte.
A dictionary candidate can continue past the dictionary end into local byte zero.
Matcher output is one token: position, length and distance; a literal token has
length one and m_match=0, a match has length>=4. Tokens are held under stalls.
After a match, every skipped position with a complete four-byte prefix is
inserted before searching at the resume position.

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
The controller still must traverse sequences backward and interleave extra bits,
states and marker in the exact RFC order.

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
to 64 bits. The future frame controller emits result[31:0] in LE order.

Each low-64-bit product uses the serial `bellows_l5_mul64` component: two clocks
per multiplier bit, low-half addition then high-half addition with registered
carry, 64 iterations. There is no one-cycle 64x64 combinational multiply.
Other checksum additions, rotations, XORs and stores have distinct control
states. The area/latency tradeoff is deliberate; no whole-block throughput was
specified. This is an implementation rationale, not timing proof.

Start and result have separate handshakes. s_ready is low during arithmetic.
finish_valid has priority over another byte in COLLECT; callers must finish
only after the final byte handshake. Empty input runs the ordinary seed-zero
short-message path. Private XXH32/CRC32 remain the parent unit and must be
fed the same complete raw bytes by future integration.

## Analytical operation limits for later verification

These are conservative operation-count bounds under fair service, not measured
latencies or wall-clock acceptance thresholds:

| Component | Bound excluding external stalls |
|---|---|
| Dictionary preparation | <=3*D+8 clocks after begin through offered status |
| Matcher per block | <=32*(B+1)*(B+1)+4096 clocks with synchronous one-edge byte/index responses |
| Table build | <=64+64+2*L+L*(tableLog+4)+1024 clocks after count stream |
| Inverse transition | <=L+4 clocks |
| Bit writer | One input field plus up to five byte handshakes per <=32-bit field |
| Reverse reader | <=32 clocks per <=32-bit field with one-edge memory service |
| XXH64 | <=2048*(B+1)+8192 clocks from start to result, excluding input gaps |

The quadratic matcher bound permits repeated long comparisons on adversarial
hash collisions. Typical greedy operation is much smaller but unmeasured.
Use compiled Verilator for page/multi-seed/defect workloads; Icarus only for the
admitted compact startup/leaf/frame cases.

## Integration obligations and evidence map

The remaining controller must validate command/descriptors before issuing DMA,
buffer complete source data, latch the first error, and count only accepted
source responses and successful output acknowledgments. It must enforce the
128-KiB frame profile, capacity and overflow guards, all three table modes and
repeat rejection, exact reverse exhaustion, repeat offsets, output history,
content checksum and optional inherited trailer. A raw fallback cannot replace
FSE or dictionary-gain coverage.

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
