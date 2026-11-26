# BELLOWS-L1 (Gen-1 (v3.0))

[English](README.md) · [简体中文](README.zh-CN.md) · [Family Home](../../README.md) · [**Full Engineering Report (`REPORT.pdf`)**](REPORT.pdf)

## Overview

Streaming LZ4 block decompressor · 64 KiB circular history SRAM, overlap RLE copy FSM & DDR4 burst DMA.

This directory contains the **Vulcan 3.0 full-shell silicon release** of `BELLOWS-L1`, verified end-to-end through cycle-accurate simulation, negative-control mutation testing, matched `AMD EPYC 7662` CPU and `NVIDIA Tesla V100` GPU benchmarking, 4-corner full-shell Quartus Prime 17.1 static timing closure on Intel Arria 10 GX (`10AX115N3F40E2SG`), and physical PCIe Gen3x8 + DDR4-2133 hardware-in-the-loop (`board_hil`) execution.

## Physical Silicon Signoff Summary

| Metric | Verified Full-Shell Result |
| :--- | :--- |
| **Target FPGA Device** | Intel Arria 10 GX `10AX115N3F40E2SG` |
| **Platform Integration Scope** | Full PCIe Gen3x8 + DDR4-2133 Platform Shell (All 95 Active Clocks Closed) |
| **Core Clock STA (`100 MHz` Target)** | **`133.71 MHz`** (`WNS +2.521 ns`, `WHS +0.015 ns`) |
| **PCIe / DDR4 Clock Closure** | PCIe `coreclkout`: **`279.02 MHz`** · DDR4 `usr_clk`: **`301.93 MHz`** |
| **Whole-Shell Resource Utilization** | `43,780 / 427,200 ( 10 % ) ALMs` · `1 / 1,518 ( < 1 % ) DSPs` · `206 / 2,713 ( 8 % ) M20K` |
| **Physical Board HIL (`PCIe Gen3x8 + DDR4`)** | **PASSED** (`rpd_sha256: a2ae14636f86610b…`) |

## Directory Contents

- [`REPORT.pdf`](REPORT.pdf) — Complete engineering report (architecture, RTL design, verification matrix, 4-corner STA, physical HIL, and matched CPU/GPU benchmarks)
- [`rtl/`](rtl/) — Synthesizable SystemVerilog RTL and timing constraints (`9` files: `Role_BellowsL1.sv`, `bellows_l1_ddr.sv`, `bellows_l1_dma.sv`, `bellows_l1_history.sv`, `bellows_l1_output.sv`, `bellows_l1_reset_sync.sv`, `bellows_l1_top.sv`, `vulcan_role.sdc`, `vulcan_role.sv`)
- [`tests/`](tests/) — Verification testbenches, reference models, and matched CPU/GPU benchmark harnesses (`9` files)
- [`evidence/`](evidence/) — Public post-fit STA ([`quartus-sta-summary.json`](evidence/quartus-sta-summary.json)) and physical board HIL ([`board-hil-summary.json`](evidence/board-hil-summary.json)) receipts
