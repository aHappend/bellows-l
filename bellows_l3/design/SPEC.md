# BELLOWS-L3 contract

## Scope and compatibility

`bellows_l3_top` is a four-context, descriptor-framed raw LZ4 streaming DMA
subsystem. It is not the standard LZ4 Frame header/magic protocol. The standalone
`bellows_l2_top` and `bellows_l1_top` retain their raw-stream ports, errors,
unbounded standalone decoding and L2 round-trip mode. Reference RTL in
`bellows_l2_reference/rtl/` is provenance, not acceptance evidence.

The target is Intel Arria 10 GX 10AX115N2F45E1SG, at least 100 MHz (period at
most 10 ns). Physical timing and hardware qualification are pending independent
runtime gates, not inferred from RTL compilation.

## Cycle & Degenerate-Boundary Table

All handshakes sample valid and ready **pre-edge**. State, counters and holding
registers change **post-edge**. Stalls extend, never shorten, these boundaries.

| Event | Registered consequence |
|---|---|
| Reset asserted | Every public output is zero; all contexts and bus ownership abort. Memories are not cleared. |
| First edge after reset release | Idle channels can accept commands; no warmup workload. |
| Command at E0 | Captured post-E0; its descriptors cannot transfer at E0 and are first eligible at E1. |
| Final descriptor at Ek | Validate in Ek..Ek+1; validated state post-Ek+1; first DMA presentation no earlier than post-Ek+2. |
| DMA request presented post-En | First transfer at En+1. |
| Read response at Er | Reserved lane byte post-Er; codec transfer no earlier than Er+1. |
| Codec output at Ec | Lane write slot post-Ec; shared request register at Ec+1; transfer no earlier than Ec+2. |
| Final write acknowledgment at Ew, internal work finished | Completion eligible post-Ew; shared status register at Ew+1; transfer no earlier than Ew+2. |
| Empty output | Same completion stages measured from the final internal finish event. |
| MAX_BLOCK_BYTES=1 | Single content byte is both first and last; empty compression uses keep=0,last=1. |
| SG_DEPTH=1 | Index remains zero; no pointer-mask assumption. |
| SG_DEPTH=3 or 16 | Segment pointers advance only on explicit end-of-segment comparisons, never modulo masking. |
| Concurrent read and write | Independent ownership and responses; both counters may advance. |
| Error plus normal progress | First processing error wins; accepted transactions settle before completion. |
| Reset plus any handshake | Reset wins; bridge must discard pre-reset responses. |
| Status retirement plus command | Channel stays busy through status retirement; reuse starts on a later edge. |

## Exact external interface

All signals are unsigned. The only public parameters are integer
`MAX_BLOCK_BYTES=65536` (1..65536) and `SG_DEPTH=16` (1..16). Unsupported values
have safe diagnostic storage and issue `PARAMETER ERROR` at simulation startup.
There are exactly four channels.

| Bundle | Inputs | Outputs |
|---|---|---|
| Clock/reset | clk, rst_n | - |
| Command | cmd_valid, cmd_channel[1:0], cmd_id[15:0], cmd_decompress, cmd_checksum_mode[1:0], cmd_src_bytes[31:0], cmd_dst_capacity[31:0], cmd_src_segments[4:0], cmd_dst_segments[4:0] | cmd_ready |
| Segment | sg_valid, sg_channel[1:0], sg_destination, sg_addr[63:0], sg_bytes[31:0] | sg_ready |
| Read request | rd_req_ready | rd_req_valid, rd_req_channel[1:0], rd_req_addr[63:0] |
| Read response | rd_rsp_valid, rd_rsp_data[7:0], rd_rsp_error | rd_rsp_ready |
| Write request | wr_req_ready | wr_req_valid, wr_req_channel[1:0], wr_req_addr[63:0], wr_req_data[7:0] |
| Write response | wr_rsp_valid, wr_rsp_error | wr_rsp_ready |
| Completion | status_ready | status_valid, status_channel[1:0], status_id[15:0], status_error[3:0], status_src_bytes[31:0], status_dst_bytes[31:0], status_checksum[31:0], err_checksum_mismatch |

One command is active per channel, including its stalled completion. Commands
snapshot only at handshake. Segments concatenate in per-channel/per-direction
acceptance order; all declared segments are collected before DMA. Segment sizes
are positive. Widened sums must equal command source length and destination
capacity exactly; inclusive last addresses must fit 64 bits. Invalid command
metadata accepts no descriptors. Invalid descriptor lists consume the remaining
declared counts, then complete without DMA.

Destination count and capacity are nonzero. Counts cannot exceed SG_DEPTH.
Source count is zero exactly when source length is zero, legal only for
compression. Compression source length is at most MAX_BLOCK_BYTES. Decompression
source length is at least one payload byte plus trailer and at most
2*MAX_BLOCK_BYTES+20. Destination capacity is any positive representable 32-bit
sum. The caller prevents overlap between source/destination and active writable
ranges. Unaligned segments and gaps are legal and must not be touched.

Every DMA request transfers one byte. There is one globally outstanding read
and one globally outstanding write, independently. Responses are ordered,
untagged, exactly one per accepted request, and cannot arrive before the next
edge. Completion counts consumed read responses and successful write
acknowledgments, not speculative requests. Completion waits for outstanding
transactions. Reset requires the environment to reset/drain its bridge too.

## Framing and numerical rules

Mode 0 has no trailer and reports checksum zero. Mode 1 appends canonical seed
zero XXH32; mode 2 appends CRC-32/ISO-HDLC. Mode 3 is invalid. The four trailer
bytes are little-endian. Checksums cover original uncompressed content exactly
once per logical byte, not compressed bytes. No dictionary survives a frame.
Empty compression emits token 00, then the optional checksum; empty decode
writes no content bytes. Successful L3 decoded length is at most MAX_BLOCK_BYTES.
Compression retains genuine LZ4 matches, rather than a literal-only substitute.

XXH32 arithmetic wraps to 32 bits. Words are little-endian. Hex primes:
P1=9E3779B1, P2=85EBCA77, P3=C2B2AE3D, P4=27D4EB2F, P5=165667B1.
Initial lanes are P1+P2, P2, 0, -P1. Each complete 16-byte stripe updates each
lane with rotl(v+word*P2,13)*P1. Combine rotl(v1,1)+rotl(v2,7)+
rotl(v3,12)+rotl(v4,18), without an XXH64 merge round. Short inputs start
at P5. Add content length; remaining words use rotl(h+word*P3,17)*P4;
remaining bytes use rotl(h+byte*P5,11)*P1. Avalanche: xor logical >>15,
multiply P2, xor logical >>13, multiply P3, xor logical >>16.
XXH32(empty)=02CC5D05; XXH32(abc)=32D153FF.

CRC initializes FFFFFFFF, XORs each byte into low bits, performs eight reflected
bit steps with EDB88320, and finally XORs FFFFFFFF.
CRC32(123456789)=CBF43926; CRC32(empty)=00000000.

## Errors and recovery

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | truncated/malformed LZ4 boundary or missing trailer |
| 2 | zero offset |
| 3 | unavailable-history offset |
| 4 | LZ4 length arithmetic overflow |
| 5 | block-size limit |
| 6 | retained parent invalid keep |
| 7 | content checksum mismatch |
| 8 | invalid command or descriptor |
| 9 | destination-capacity exhaustion |
| 10 | DMA response error |

First detected processing error is retained. Stop new lane transactions on
failure, settle accepted transactions, and issue exactly one completion.
Other channels continue. `err_checksum_mismatch` is exactly
`status_valid && status_error==7`, stable with stalled status. Enabled modes
report the computed content checksum, including on mismatch. Earlier codec,
DMA or capacity failures are not relabeled as checksum errors. Decoded writes
may precede checksum verification and remain untrusted until successful status;
there is no rollback.

## Arbitration and stability

Independent round-robin read, write and status arbiters lock presentations
through stalls and advance only on accepted transfers. A continuously eligible
lane is serviced within four accepted grants; ineligible lanes cannot monopolize
selection. Every valid/payload bundle is stable while stalled. Read and codec
output paths have reserved registered slots, with no same-edge bypass.

## Reproduction and acceptance ownership

Required tools: Python 3, Icarus/vvp, Verilator, C++ compiler, make and Yosys.
No particular installed version or passing result is claimed here.
From the delivered root, independent Verifier-owned entry points are:

```
python3 tests/verify.py --check smoke --out-root evidence/l1/smoke
python3 tests/verify.py --check matrix --out-root evidence/l1/matrix
python3 tests/verify.py --check synthesis --out-root evidence/l1/synthesis
python3 tests/verify.py --check mutations --out-root evidence/l1/mutations
python3 tests/verify.py --check reproduce --out-root evidence/l1/reproduce
```

Each invocation must retain a fresh exclusive run directory, exact commands,
source hashes, versions, timestamps, exit/timeout status and raw logs.
Design sources are `rtl/*.sv`, this document and `design/ARCHITECTURE.md`;
verification sources are `tests/*.py`. Generated transactors are outputs.
Independent mandatory checks, native timing lint, Quartus 17.1 STA with
nonnegative WNS at 100 MHz, and three consecutive deterministic Arria 10 GX
PCIe Gen3x8 HIL passes remain required. The runtime prepares the independently
approved product PDF only after engineering acceptance.
