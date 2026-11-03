# BELLOWS-L5 frozen implementation contract

## Status and authority

This document records the independently admitted single-block profile. It is
not a passing verification result. The supplied parent RTL is an immutable
comparison input, not an L5 baseline certificate. Engineering acceptance,
native timing gates, native hardware gates and the final independently approved
product PDF remain separate requirements. Implementation status is recorded in
`ARCHITECTURE.md`; an unimplemented item is not an unsupported-profile exception.

## Product and interface

Top: `bellows_l5_top`. Preserve all ports of
`bellows_l4_reference/rtl/bellows_l4_top.sv` verbatim. Defaults and legal ranges:

| Parameter | Default | Legal |
|---|---:|---|
| MAX_BLOCK_BYTES | 65536 | 1..65536 |
| SG_DEPTH | 16 | 1..16 |
| COPY_BYTES | 8 | 4 or 8 |
| DICT_BYTES | 16384 | 1..16384 |

Invalid parameters must reach an explicit `PARAMETER ERROR` diagnostic using
safe widths and guarded datapaths. Required configurations are singleton
`(1,1,4,1)`, nonpower `(3,3,8,7)`, page4k `(4096,1,4,4096)`, page16k
`(16384,3,8,16384)`, default `(65536,16,8,16384)`, and default with COPY_BYTES=4.
Reject block 0/65537, SG 0/17, copy 1/16, dictionary 0/16385.

`cmd_codec[2:0]`: 0=LZ4, 1=byte Huffman, 2=inherited BF16 transform/Huffman,
3=inherited nibble transform/Huffman, 4=LZ4/Huffman, 5=Zstandard local history,
6=Zstandard with pinned raw dictionary, 7=invalid. Preserve codecs 0..4, including
empty input, odd BF16 rejection, private trailers, byte/wide DMA and errors.
Add unsigned input `cmd_dict_id[31:0]`, sampled only for codec 6.

| Dictionary port | Direction | Width |
|---|---|---:|
| dict_begin_valid, dict_begin_ready | in, out | 1 each |
| dict_begin_id, dict_begin_bytes | in | 32, 15 |
| dict_s_valid, dict_s_ready | in, out | 1 each |
| dict_s_data, dict_s_last | in | 8, 1 |
| dict_status_valid, dict_status_ready | out, in | 1 each |
| dict_status_error | out | 4 |
| dict_loaded, dict_id, dict_size | out | 1, 32, 15 |

All external values are unsigned. Only internal normalized counts are signed.
The common transport remains the inherited 69-bit read, 137-bit write and
116-bit completion payloads. Required hierarchy is
`bellows_l5_top.lanes[i].context` (`bellows_l5_context`), containing `legacy`
(`bellows_l4_context`) and `zstd` (`bellows_l5_zstd_context`), for i=0..3.
Latch route through completion retirement. Use parent `scheduler` and `dma`.
One shared `dictionary` has four synchronous byte read views:
`rd_en[3:0]`, `rd_addr[55:0]`, `rd_valid[3:0]`, `rd_data[31:0]`.
Each lane address occupies 14 bits, each result 8 bits.

## Cycle & Degenerate-Boundary Table

| Boundary/event | Required behavior |
|---|---|
| Before edge E | Only pre-edge valid AND ready transfers at E. |
| After edge E | Registers and outputs reflect E; newly asserted valid is not a transfer at E. |
| Active reset | New-top outputs, including ready/data/metadata/counters, are zero; control reset is asynchronous active-low. RAM data need not reset. |
| Reset release between edges | No admission before the next active edge. Clear ownership, not large RAM contents. |
| Command at E | Lane command-ready closes after E; descriptors first transfer on a later edge. |
| Final descriptor at D | Validate before DMA; no request before D+2. |
| Read request | Response minimum one edge later; at most one global outstanding read and one independent write. |
| Stalled request/result | Payload, response owner and pending completion remain stable. |
| Completion at C | All responses have settled; lane becomes command-ready after C, not speculatively at C. |
| Dictionary begin and command | Begin wins when all lanes idle, no DMA pending and no completion pending. Never displace an active command. |
| Dictionary upload/status | Commands blocked until preparation and held dictionary status retire. |
| Dictionary first AND last | One-byte dictionary accepts both on one edge and pins only after preparation. |
| Nonpower lengths | Compare explicit terminal counts; never mask a nonpower length for wrap. |
| Wide tail/segment end | Ascending byte addresses in low-to-high lanes, only valid strobes; never cross a segment. |
| FSE init at E | If empty, init has priority; state updates after E with no symbol. |
| FSE step at E+1 | Symbol, next state and consumed count valid after E+1, exactly one transition cycle. |
| FSE retire AND step | Retire old result and replace it at one edge; accept dependent transitions on consecutive edges. |
| FSE stall | Freeze state and every pending result field; init cannot replace a held symbol. |
| Zero-bit FSE row | Consume no bits; mask contribution to zero. |
| Error with outstanding DMA | Latch first error, stop new issues, settle owned responses, one completion. |
| Reset during upload/table/DMA/status | Abort epoch; no stale metadata/table/response becomes new work. |

## Dictionary ownership and matching

Begin accepts only in the globally quiescent condition. A valid begin has
nonzero application ID and length 1..DICT_BYTES. Any accepted begin invalidates
the old image. Invalid metadata returns 8 without requesting bytes. Stream
exactly the announced bytes; `last` must coincide with the final byte.
An incomplete upload waits under backpressure, not fabricated completion.
Failure leaves loaded=0; successful image pins atomically after match-index
preparation. Status is held until accepted. Reset aborts uploading.

Codec 6 with absent/mismatched ID returns 13 before DMA; codecs 0..5 ignore
cmd_dict_id. A block starts with dictionary logically before position zero,
otherwise empty history, and repeat offsets {1,4,8}. No prior page is history.
IDs are application metadata, never a trained dictionary header or an RFC
dictionary-ID field. Software receives the same raw dictionary out of band.
Raw bytes never initialize entropy tables.

Use a registered 1024-entry direct-mapped four-byte-prefix index. Seed dictionary
positions in increasing order; retain the most recent collision as the head.
Synchronous predecessor links retain earlier dictionary candidates for each
hash; local updates cannot evict them. Traverse candidates nearest first,
retaining the longest verified match (stop when it covers the complete remaining
input). Update local positions as parsing advances. Compare and extend every
candidate; a hash is not proof of equality. Prefer nearest offset on dictionary/local tie. Permit
dictionary-to-output crossing. Greedy encoding minimum match=4; decoding accepts
match=3 and incremental overlap, including distances 1 and 2.

## RFC frame and numerical rules

Emit magic `28 b5 2f fd`, descriptor `84`, window descriptor `38`, four-byte
little-endian content size, no RFC dictionary-ID field, one final block and an
always-present four-byte content checksum. Window=128 KiB. Raw/RLE literal
sections and actual FSE-coded LL/ML/OF sequences are required. Choose raw block
when completed compressed representation is not smaller. RLE block is legal.
Standard-frame output length <= raw length+17.

Decode raw/RLE blocks and compressed blocks with raw/RLE literals in this
header profile. Accept standard-frame input up to `2*MAX_BLOCK_BYTES+1024`;
check before DMA and account separately for private trailers without overflow.
Reject excessive content size before output overflow, malformed/reserved fields,
truncation, invalid termination and trailing bytes. Huffman Zstandard literals,
multiblock, concatenated and skippable frames are explicitly unsupported (12),
not successful partial output. This is not a universal Zstandard decompressor.
Existing L4 Huffman modes remain unchanged.

Content checksum is low 32 bits of XXH64(seed=0), little-endian, over all decoded
bytes. Arithmetic wraps modulo 2^64, using exact xxHash rotations and LE words.
Private checksum modes: 0=no private trailer/status_checksum=0;
1=inherited XXH32; 2=inherited CRC32; 3=invalid.
Modes 1/2 append their four-byte trailer outside the standard frame and retain
inherited status_checksum meaning. Pass only the standard portion to libzstd.
Truncated XXH64 is accidental-corruption detection, not cryptographic
authentication; checksum collisions remain possible.

RFC LL/ML/OF codes, bases, extra bits, sequence ordering, repeat offsets,
normalized counts, initialization and terminal-symbol rule apply exactly.
Offsets are positive distances into dictionary||output. Validate available
history, content size, capacity and wide arithmetic before narrowing.

## FSE and table lifecycle

Each zstd context owns a separate encoder, reverse reader, sequence-table builder,
matcher, XXH64 and `entropy`. Within entropy the actual production decoder
instances are `fse_ll_decoder`, `fse_ml_decoder`, `fse_of_decoder`.
Encoder lives in `rtl/bellows_l5_fse_encoder.sv`.

Leaf interface: clk/rst_n; init_valid/init_ready/init_state[8:0]; state[8:0];
step_valid/step_ready/bits[8:0]/available[3:0];
row_symbol[5:0]/row_nbits[3:0]/row_base[8:0];
m_valid/m_ready/m_symbol[5:0]/m_state[8:0]/m_nbits[3:0].
The current state selects a validated combinational row. A transition returns
row_symbol, consumes k=row_nbits and sets state=row_base+low_k(bits).
Initialization requires an empty output slot; transition permits an empty or
retiring slot but no asserted initialization. available=0..9.
Controller must not read nonexistent transition bits for the final symbols.

L=1<<tableLog; LL/ML maximum log=9, OF maximum=8, compressed minimum=5.
Normalized -1 has mass 1; zero absent; positive counts have their stated mass;
sum exactly L. Spread step=(L>>1)+(L>>3)+3 with power-of-two masking and reserved
low-probability cells. Rows contain symbol, bit count and next-state base.
Compressed tables may assign the entire mass L to one legal symbol; these
retain tableLog and L states, with zero-bit rows and next-state base equal to
the row address. They are not RLE-mode tables.
RLE has constant symbol/zero bits. Reverse sequence encoding uses inverse
transforms and the RFC stop marker; table preparation may be multicycle.

**Successful predefined, RLE and compressed table modes are mandatory. Repeat
table mode cannot succeed in this one-block, raw-content-dictionary profile:
return error 11 for every repeat selector without a prior table.**
Track alphabet validity independently. Reset and each new command invalidate
ownership, irrespective of lane reuse or dictionary. A predefined constant is
not prior ownership; a new table for one alphabet cannot authorize another,
and no current-section table retroactively authorizes repeat. Raw/RLE blocks and
zero sequences establish no entropy tables. Malformed builds never become valid.
Check repeat before transitions/output. Match repeat offsets are unrelated.

## Errors

| Error | Meaning for new codecs |
|---:|---|
| 0 | success |
| 5 | decoded-size limit |
| 7 | checksum mismatch |
| 8 | invalid command/descriptors/configuration |
| 9 | destination capacity |
| 10 | DMA response error |
| 11 | malformed/truncated frame, table/state/offset/termination, unowned repeat table |
| 12 | well-formed unsupported profile |
| 13 | absent/mismatched dictionary |

Keep inherited legacy codes. err_checksum_mismatch is true exactly with valid
error-7 completion. Pre-DMA failures count zero consumed/written bytes. Otherwise
source counts accepted response bytes; destination counts successful
acknowledgments. Output before a late checksum failure is untrusted; no atomic
rollback is promised.

## Timing and storage

Target Arria 10 GX 10AX115N2F45E1SG, <=10.0 ns register-to-register paths.
No combinational division/remainder, mixed blocking/nonblocking clocked
assignments, inferred latches, combinational FSM loops or one-cycle giant
search chains. Stage hashing, address/capacity decisions and checksum arithmetic.
RAM >=2 KiB uses explicit byte-lane arrays with synchronous access, no
asynchronous array reset. Small FSE banks may be distributed/combinational read.
Only actual post-synthesis Quartus STA can support a Coordinator timing waiver.

## Independent acceptance (unchanged)

Verifier owns all tests and independent Python models. Every check is
self-contained, fails on assertions/child errors, generates fresh required
inputs, and retains exclusive project-relative evidence and source hashes.
No final product PDF is a precondition to engineering checks.

`tests/verify.py` must implement these mandatory root-relative invocations:

```text
python3 tests/verify.py --check behavior --configuration singleton
python3 tests/verify.py --check behavior --configuration nonpower
python3 tests/verify.py --check behavior --configuration page4k
python3 tests/verify.py --check behavior --configuration page16k
python3 tests/verify.py --check behavior --configuration default
python3 tests/verify.py --check synthesis
python3 tests/verify.py --check defects
python3 tests/verify.py --check portable
```

Behavior: seeds 17/89/2026, real compiled Verilator, all legal
codec/direction/checksum/wide combinations at each geometry; compact Icarus
startup/leaf/frame tests <=500000 cycles. Independent Python RFC/canonical
Huffman/LZ4/checksum models and libzstd/liblz4/libxxhash/zlib comparisons require
complete bytes, lengths, checksums and completion metadata, not samples.
Compare immutable parent and delivered legacy paths independently, distinguishing
pre-existing defects from regressions.

Cover four mixed concurrent lanes, same IDs on different lanes, random SG splits,
stalls, delayed responses, held completions, DMA errors, reset during each phase,
every error's recovery and descriptor/length/parameter boundaries. At default
include lengths 0,1,2,3,15,16,17,255,256,257,4095,4096,8192,16384,65535,65536.
Include zero/constant/alternating/all-symbol/skewed/random/local/dictionary
prefix/suffix/crossing/overlap datasets. Cover all reachable LL/ML/OF boundaries,
repeat offsets, bit alignments and zero/one/multiple sequences. Independently
exercise predefined/RLE/compressed mixed alphabet tables and malformed sums/logs/
symbols/truncations. Exhaust all states/legal bits of predefined and independent
compressed tables at logs 5,6,9 where permitted; prove >=256 dependent
consecutive one-cycle transitions and stalled equivalents.

Repeat rejection must cover each alphabet and combinations on fresh/reused
lanes after successful predefined/RLE/compressed commands, with/without dictionary,
after errors and reset: exactly one error 11, no success, next valid recovery.
Python and libzstd independently reject these frames with raw dictionary
semantics; do not invent preceding blocks or formatted entropy dictionaries.

Dictionary gain: independently generate a pinned 16384-byte random dictionary
before pages. Nine cases = seeds 17/89/2026 x sizes 4096/8192/16384. Each page is
seven-eighths unique contiguous dictionary content at deterministic varying offset,
one-eighth fresh random content; retain generator/hashes, never reload from page.
Each entire codec-6 standard frame <=75% of actual inherited LZ4 block;
aggregate <=50%. Require full RTL/Python/libzstd recovery, liblz4 baseline
cross-decode, real dictionary matches and FSE transitions in each case.
Report cold load/storage separately. Unrelated pages need losslessness, not gain.

Corruption: every bit of a short FSE frame and short dictionary frame;
>=64 seeded flips at each page size; header/table/payload/marker/checksum,
every-byte short truncations, insertions/trailing bytes, absent/wrong dictionary.
Never success with wrong output. Frames rejected by both independent parsers
cannot succeed. Record valid, identical-output semantic equivalents honestly.

Defects: independent disposable copied-source simulation kills for next-state
off-by-one, reverse order/marker, dictionary base, XXH64 checksum, channel response
association and inherited output mutation. Normal targeted cases must pass;
compile failure/string search is not a semantic kill.

Synthesis: real Yosys default/singleton/nonpower; retain inferred memories, full
logs/statistics/netlists, hierarchy/connectivity/state checks, zero latches and
unexpected black boxes. Disconnected engines fail. Lossless gzip requires
verified decompressed hash/size. Generic synthesis is not Fmax evidence.
Portable: clean copied declared sources only, fresh compact Icarus and compiled
Verilator legacy/new/dictionary tests and library checks; scan for secrets/private
paths without printing secret content.

Required tools/libraries: Python 3, Icarus, Verilator, make, C++ compiler, Yosys,
libzstd, liblz4, libxxhash. Actual versions belong in fresh receipts.
For Designer-only syntax/elaboration from the delivered root:

```text
iverilog -g2012 -t null -s bellows_l5_top rtl/*.sv
```

This static command does not execute behavior, build a simulation harness or
establish synthesis/timing correctness. Compile only the delivered RTL, not
both copies of the parent modules. Integration/startup and actual production
module ownership are described in `ARCHITECTURE.md`.

Shared runtime independently executes mandatory native L1.5 timing lint,
L2 Quartus 17.1 STA and L3 Arria 10 PCIe hardware-bridge gates. Connectivity-only
hardware observations are not codec-workload measurements.

Evidence roots: exclusive `evidence/l1-<check>-<timestamp_or_hash>/`, including
behavior configuration in the check name. Preserve failed receipts. Each records
argv/cwd/versions/timeouts/start/end/exits/sources/child invocations/raw logs.
Keep compact coverage, complete compared hashes, seeds and reproductions;
no per-cycle logging or persistent large transient dumps. Designer does not
author these verification sources or run functional/synthesis acceptance.
