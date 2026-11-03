# BELLOWS-L1 architecture

## Scope and design decisions

The fixed top is `bellows_l1_top`. It instantiates `bellows_l1_history`
and `bellows_l1_output`; the parser and serialized match sequencer reside in
the top. There are no public parameters. The history is exactly 65,536 unsigned
bytes and the external streams carry one unsigned byte per transfer.

Correctness and the 10.0 ns Arria 10 GX timing objective take priority over
throughput. Literal acceptance, byte commitment, history read and dependent
read launch are distinct registered steps. No combinational parser loop,
division, remainder, speculative history write or input-to-output bypass is
used. These choices are architectural intent, not measured timing closure.

## Cycle & Degenerate-Boundary Table

Every edge samples pre-edge ready/valid; register updates are post-edge.
This table is the implementation contract, established before RTL.

| Boundary/event | Pre-edge condition | Post-edge action |
| --- | --- | --- |
| Active asynchronous reset | `rst_n=0` | Public ready, valid, data, last and error are zero; parser, pointers, validity, candidates and output buffers clear. RAM bytes need not clear. |
| First edge after reset release | Token state, no old history | A token can transfer; no old output or status is fabricated. |
| Literal accepted at N | Literal state, input transfer | Byte is registered. Earliest commit is N+1. Premature last still retains this literal. |
| Literal committed at N+1 | Candidate and output-stage ready | Write history, advance pointer/availability and retain byte in pending tail. |
| Match read launched at N | Read state | Synchronous RAM result becomes registered post-N. |
| Match committed at N+1 | Read result and output-stage ready | Append read byte to history/output; successor read is no earlier than N+2. |
| Commit with older pending byte | Presented slot empty or retiring | Promote old pending with last=0, install new pending; earliest external transfer of promoted byte is next edge. |
| Commit with empty pending | Even if presented slot stalls | Retain candidate without disturbing the presented byte. |
| Presented retirement plus promotion | Old valid and ready | Old beat retires; replacement occupies presented register post-edge. Promotion wins over clearing that register. |
| Final candidate commit | Literal or match commit state | Enter finish, but do not finish on this edge. |
| Finish | Pending exists and presented slot available | Promote pending with last=1; enter completion wait. |
| Final output retirement at N | Completion state, boundary consumed | Assert status post-N; earliest status acceptance is N+1. |
| Empty output | Finish state, boundary consumed | No beat is fabricated; assert status after the finish step. |
| Status accepted at N | Status state and status ready | Clear block-local state and history availability; token readiness returns post-N, earliest input transfer N+1. |
| Non-last error at N | Accepted malformed parser byte | Latch first error, enable discard post-N independently of output/status stalls; earliest discard transfer N+1. |
| Discard boundary at K | Discard input transfer with last | Disable input readiness post-K until status acceptance. Discarded bytes never reach RAM or candidates. |
| Boundary before final output | Completion wait | Wait for final retirement; status then asserts post-edge. |
| Final output before boundary | Completion wait | Wait with discard ready; status asserts after boundary transfer. |
| Boundary and final retirement together | Completion wait | Status asserts post-edge, not before either transfer. |
| Reset during any phase | Including discard or stalled output | Abort without completion; subsequent block starts with no valid history. |
| Empty block | One last-marked token with literal nibble zero | Ignore its match nibble; no output, one success status. |
| One-byte output | One last-marked literal | Register, commit, finish, present last, retire, then status. |
| Pointer wrap | Write at address 65535 | Next write address is zero by 16-bit truncation. |
| Full history | Availability already 65536 | Keep availability saturated while pointer continues to wrap. |
| Overlap, including offset one | Previous byte committed | Next read uses updated history, not a pre-match snapshot. |
| Simultaneous RAM read/write | Not requested by this sequencer | No read-during-write collision behavior is required. |
| Alternative depths/widths | Not exposed | DEPTH=1, non-power-of-two windows and parameter sweeps are unsupported, not silently clamped. |

## Modules and ownership dependencies

| Module | Storage/control | Guarantee to consumer |
| --- | --- | --- |
| Top/parser | Token, 32-bit lengths, 16-bit offset/write pointer, 17-bit saturated availability, registered literal, boundary/error state | Only validated matches launch; candidate stable while stalled; exactly one finish per block; no next input before status acceptance. |
| History | 65,536 x 8 RAM and registered read result | Enabled read at N is available for commit at N+1. Unwritten bytes are never requested by a legal match. |
| Output | One unclassified pending byte and one presented byte/last | Ready means candidate storage is safe; presented data never changes while stalled; finish labels only the pending tail. |

The output stage owns tail classification. History writes and output candidate
acceptance are the *same event*. Thus every history-valid byte is already
retained for eventual output. Availability is block-local, saturates at 65536,
and is independent of the 32-bit per-sequence counters. Total decoded length
has no fixed-width accumulator or artificial cap.

The RAM array has a clocked write without array reset; the read-result register
has asynchronous active-low reset. All control and output storage has
asynchronous active-low reset. A reset-qualified write enable prevents writes
during reset. The read and write schedule avoids target-dependent collision
semantics. The large array is intended for inferred FPGA block memory, not an
asynchronous mux. Independent synthesis must inspect the actual inference.

## Parser and recovery

Token, literal extension, literal acceptance/commit, offset-low, offset-high,
match extension, match read/commit, finish, completion and status are explicit
states. A nonextended length is initialized from the nibble; extended lengths
use a 33-bit sum to reject carry before updating the 32-bit counter.
Little-endian offset assembly is validated before entering any match state.

An error detecting an input boundary enters finish directly. A premature-last
literal first passes through ordinary literal commit, then finish. An error
without a boundary enables a separate discard flag while the output controller
finishes the preserved prefix. Discard accepts bytes with readiness independent
of output and status backpressure. Its first accepted last clears discard and
sets the boundary flag. Completion tests both boundary consumption (including
the current edge's discard boundary) and output retirement (including the
current edge's final transfer). Neither side can block progress of the other.

Error and boundary state remain block-local until status acceptance. No error
can be replaced by discarded input. Waiting for a missing byte or missing last
is intentional and has no timeout in RTL.

## Example unstalled waveforms

Edges listed below describe transfers sampled at the edge and updates after it.
Input data/last must remain stable wherever valid is held against not-ready.

For compressed bytes `10 41(last)`:

| Edge | Action |
| --- | --- |
| N | Accept token `10`. |
| N+1 | Accept literal `41(last)` into literal register; close input boundary. |
| N+2 | Commit `41` to pending and history address zero. |
| N+3 | Finish promotes `41` into presented with last=1. |
| N+4 | Output transfers; success status asserts post-edge. |
| N+5 | Status transfers if ready; next-block input readiness resumes. |

For an offset-one match, a read at A yields a registered byte; A+1 commits
that byte at the current write pointer; A+2 reads the just-written byte for
the next match iteration. A stalled output can delay A+1 indefinitely without
changing the read result. A stalled presented beat is never reclassified.

For a non-last zero-offset rejection with a nonempty prefix, the high-offset
edge enables discard and enters finish. The pending tail can become the final
presented beat while trailing compressed bytes are discarded. If output stalls,
discard still accepts through last. If trailing input stalls, output still drains.
Status waits for the later event, then remains valid/error-stable against
status backpressure. Status stalls also keep next-block input not-ready.

Reset assertion immediately masks all public outputs and clears retained
control/output state without waiting for a clock. Integration must deassert
reset safely relative to `clk`; all input/ready signals belong to that clock
domain. No CDC, host transport or hardware bridge is part of this RTL.

## Claim-to-evidence index and handoff

| Claim | Required independent evidence | Current design-handoff status |
| --- | --- | --- |
| Parser, arithmetic, overlap, wrap, prefix, reset and handshake correctness | Verifier-owned `python3 tests/verify.py --suite all`, independent model, real Icarus matrix and observed coverage | Pending |
| Offset byte order, +4 and overlap sensitivity | Compiling/executing disposable mutants with positive controls and real scoreboards | Pending |
| Synthesizable hierarchy, zero latches, retained synchronous history | Actual Yosys netlist/statistics and logs from all suite | Pending |
| Portable shipped-source reproduction | All suite clean-directory smoke, including suffix discard/reuse | Pending |
| Static timing discipline | Native shared-runtime L1.5 rtl-timing-lint | Pending |
| 100 MHz+ on 10AX115N2F45E1SG | Native Quartus 17.1 post-synthesis STA, period <=10.0 ns, WNS>=0 | Pending |
| Physical bridge operation | Native Arria 10 GX PCIe Gen3x8 gate, at least three consecutive deterministic passes | Pending |
| Product PDF | Runtime authors, independently reviews and renders after engineering acceptance | Not a pre-acceptance input |

Generic synthesis does not establish timing closure, and simulation does not
establish physical operation. No such result is claimed by this document.
The independent Verifier owns `tests/*.py`, models, generated transactors,
retained execution records and verification instructions. The Designer owns
only the RTL and these design documents.
