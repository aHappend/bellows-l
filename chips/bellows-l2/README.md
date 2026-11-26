# BELLOWS-L2 (Gen-2 (v3.0))

[English](README.md) · [简体中文](README.zh-CN.md) · [Family Home](../../README.md) · [**Full Engineering Report (`REPORT.pdf`)**](REPORT.pdf)

## Overview

Full-duplex LZ4 hardware compressor + decompressor · On-chip hash-table match finder, literal buffer & token emitter.

This directory contains the **Vulcan 3.0 full-shell silicon release** of `BELLOWS-L2`, verified end-to-end through cycle-accurate simulation, negative-control mutation testing, matched `AMD EPYC 7662` CPU and `NVIDIA Tesla V100` GPU benchmarking, 4-corner full-shell Quartus Prime 17.1 static timing closure on Intel Arria 10 GX (`10AX115N3F40E2SG`), and physical PCIe Gen3x8 + DDR4-2133 hardware-in-the-loop (`board_hil`) execution.

## Physical Silicon Signoff Summary

| Metric | Verified Full-Shell Result |
| :--- | :--- |
| **Target FPGA Device** | Intel Arria 10 GX `10AX115N3F40E2SG` |
| **Platform Integration Scope** | Full PCIe Gen3x8 + DDR4-2133 Platform Shell (All 95 Active Clocks Closed) |
| **Core Clock STA (`100 MHz` Target)** | **`112.70 MHz`** (`WNS +1.127 ns`, `WHS +0.012 ns`) |
| **PCIe / DDR4 Clock Closure** | PCIe `coreclkout`: **`275.03 MHz`** · DDR4 `usr_clk`: **`297.53 MHz`** |
| **Whole-Shell Resource Utilization** | `46,320 / 427,200 ( 11 % ) ALMs` · `1 / 1,518 ( < 1 % ) DSPs` · `345 / 2,713 ( 13 % ) M20K` |
| **Physical Board HIL (`PCIe Gen3x8 + DDR4`)** | **PASSED** (`rpd_sha256: 7f206f642921ecb6…`) |

## Directory Contents

- [`REPORT.pdf`](REPORT.pdf) — Complete engineering report (architecture, RTL design, verification matrix, 4-corner STA, physical HIL, and matched CPU/GPU benchmarks)
- [`rtl/`](rtl/) — Synthesizable SystemVerilog RTL and timing constraints (`14` files: `Role_BellowsL2.sv`, `bellows_l1_ddr.sv`, `bellows_l1_history.sv`, `bellows_l1_output.sv`, `bellows_l1_reset_sync.sv`, `bellows_l1_top.sv`, `bellows_l2_compressor.sv`, `bellows_l2_dma.sv`, `bellows_l2_emitter.sv`, `bellows_l2_hash_match.sv`, `bellows_l2_literal_buffer.sv`, `bellows_l2_top.sv`, `vulcan_role.sdc`, `vulcan_role.sv`)
- [`tests/`](tests/) — Verification testbenches, reference models, and matched CPU/GPU benchmark harnesses (`11` files)
- [`evidence/`](evidence/) — Public post-fit STA ([`quartus-sta-summary.json`](evidence/quartus-sta-summary.json)) and physical board HIL ([`board-hil-summary.json`](evidence/board-hil-summary.json)) receipts
