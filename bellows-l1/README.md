<div align="center">
  <h1>BELLOWS-L1 · High-Throughput LZ4 Streaming Compression Accelerator</h1>
  <p><strong>Streaming LZ4 Block/Frame Decompressor, Hash-Table Match Compressor & CRC32 DMA</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Quartus_17.1_STA-435.54%20MHz-0f766e?style=flat-square" alt="STA Fmax">
    <img src="https://img.shields.io/badge/Setup_WNS-%2B7.704%20ns-0f766e?style=flat-square" alt="WNS">
    <img src="https://img.shields.io/badge/Arria_10_PCIe_HIL-PASSED%20(3%2F3)-1d4ed8?style=flat-square" alt="FPGA HIL">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
  </p>
  <p>
    <a href="../README.md">Series Index</a> ·
    <a href="SHOWCASE_REPORT.pdf"><strong>Academic Whitepaper (PDF)</strong></a> ·
    <a href="REPORT.pdf"><strong>Engineering Signoff Report (PDF)</strong></a> ·
    <a href="rtl/">RTL Source</a> ·
    <a href="README.zh-CN.md"><strong>中文文档</strong></a>
  </p>
</div>

---

## Executive Silicon Signoff Summary

**BELLOWS-L1** is a synthesizable `100 MHz+` hardware accelerator autonomously architected, implemented, and verified by **Vulcan** for **Streaming LZ4 Block/Frame Decompressor, Hash-Table Match Compressor & CRC32 DMA** on the **Intel Arria 10 GX (10AX115N3F40E2SG) PCIe Gen3x8** platform.

| Signoff Dimension | Measured Result | Engineering Evidence |
| :--- | :--- | :--- |
| **Functional & Numerical Fidelity** | **100% Bit-Exact Match** | Zero output mismatches across all verification suites |
| **Reference Parity / Precision** | **0.999999995** | Cosine similarity vs. official FP32 software baseline |
| **Quartus 17.1 TimeQuest STA** | **Fmax = 435.54 MHz (`WNS = +7.704 ns`)** | Closed at `100.0 MHz` (`10.0 ns`) baseline with `0` setup/hold violations |
| **Intel Arria 10 GX Utilization** | **2.60% ALMs · 0.53% DSPs** | `11,100 / 427,200` ALMs · `96 / 2,713` M20K · `8 / 1,518` DSPs |
| **Physical PCIe Gen3x8 Board HIL** | **PASSED (`3/3` runs, `0` errors)** | Verified on physical Intel Arria 10 GX (`10AX115N3F40E2SG`, `chip_id = 23645547322997765`) |

## Academic Whitepaper Visual Preview (`SHOWCASE_REPORT.pdf`)

<table>
  <tr>
    <td align="center" width="33%"><a href="SHOWCASE_REPORT.pdf"><img src="showcase_figures/page-1.png" width="100%" alt="Page 1"></a><br><sub><strong>Page 1 · Executive Summary & Architecture</strong></sub></td>
    <td align="center" width="33%"><a href="SHOWCASE_REPORT.pdf"><img src="showcase_figures/page-2.png" width="100%" alt="Page 2"></a><br><sub><strong>Page 2 · Experimental Benchmarks & Parity</strong></sub></td>
    <td align="center" width="33%"><a href="SHOWCASE_REPORT.pdf"><img src="showcase_figures/page-3.png" width="100%" alt="Page 3"></a><br><sub><strong>Page 3 · Arria 10 STA, HIL & Scaling Roadmap</strong></sub></td>
  </tr>
</table>

## Monolingual Dual-Track Documentation Suite

| Document Track | Artifact Links | Target Audience & Scope |
| :--- | :--- | :--- |
| **Academic Product Whitepaper (English)** | [**`SHOWCASE_REPORT.pdf`**](SHOWCASE_REPORT.pdf) · [`SHOWCASE_REPORT.md`](SHOWCASE_REPORT.md) | IEEE/ACM two-column executive whitepaper covering architecture, benchmark parity, FPGA utilization, and scaling analysis |
| **Developer Engineering Report (English)** | [**`REPORT.pdf`**](REPORT.pdf) · [`REPORT.md`](REPORT.md) | Complete SystemVerilog RTL module hierarchy, cycle-accurate interface contracts, fixed-point bounds, and verification ledger |
| **Autonomous Engineering Journey** | [`.vulcan/engineering/JOURNEY.md`](.vulcan/engineering/JOURNEY.md) | Traceable Coordinator, Designer, Verifier, and Reviewer closed-loop signoff log |

---
<p align="center"><sub>Author: <strong>Sufeng Guo</strong> · Microsoft Research Asia · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a></sub></p>
