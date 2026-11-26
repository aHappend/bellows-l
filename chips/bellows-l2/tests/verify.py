"""Vulcan's independent RTL behavior entry point."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

from matched_workload import corpus, describe, publish, sha256
from oracle import compress, decode, frozen, role, sequence

PROJECT = Path(__file__).resolve().parents[1]
SHELL = "fpga/longspeak"
CAPACITIES = (1, 5, 13, 257, 4096, 65536)
SEEDS = (1, 17, 89)
MUTANTS = {
    "offset": ("bellows_l2_emitter.sv", "OFFSET_LOW: byte_data = offset[7:0];",
               "OFFSET_LOW: byte_data = 8'd0;", "invalid_match_offset"),
    "tail": ("bellows_l2_hash_match.sv", "limit_addr <= block_length - 17'd5;",
             "limit_addr <= block_length - 17'd4;", "trailing_literals"),
    "stall": ("bellows_l2_compressor.sv", "m_valid ? encoded_read_data : 8'd0;",
              "m_valid ? (encoded_read_data ^ {7'd0, !m_ready}) : 8'd0;", "stalled_output_stability"),
}
CORE_TB = """`timescale 1ns/1ps
module bellows_core_tb;
    import "DPI-C" function void core_init(input string path, input int capacity);
    import "DPI-C" function void core_drive(output int ci, di, ctl);
    import "DPI-C" function int core_sample(input int co, dout, cr, dr, cs, ds);
    bit clk;
    int ci, di, ctl;
    wire [7:0] cb, db;
    wire cv, dv, cl, dl, cr, dr, cvst, dvst;
    wire [2:0] ce, de;
    bellows_l2_top #(.MAX_BLOCK_BYTES(`TEST_CAPACITY)) dut (
        .clk(clk), .rst_n(ctl[0]), .roundtrip_enable(ctl[1]),
        .c_s_data(ci[7:0]), .c_s_keep(ci[8]), .c_s_valid(ci[9]), .c_s_last(ci[10]), .c_s_ready(cr),
        .d_s_data(di[7:0]), .d_s_valid(di[9]), .d_s_last(di[10]), .d_s_ready(dr),
        .c_m_data(cb), .c_m_valid(cv), .c_m_last(cl), .c_m_ready(ctl[2]),
        .d_m_data(db), .d_m_valid(dv), .d_m_last(dl), .d_m_ready(ctl[3]),
        .c_status_valid(cvst), .c_status_error(ce), .c_status_ready(ctl[4]),
        .d_status_valid(dvst), .d_status_error(de), .d_status_ready(ctl[5])
    );
    string scenario;
    int done;
    initial begin
        if (!$value$plusargs("scenario=%s", scenario)) $fatal(1, "Missing core scenario");
        core_init(scenario, `TEST_CAPACITY);
        do begin
            core_drive(ci, di, ctl);
            #5;
            done = core_sample({21'b0, cl, cv, 1'b0, cb}, {21'b0, dl, dv, 1'b0, db},
                               int'(cr), int'(dr), {28'b0, cvst, ce}, {28'b0, dvst, de});
            clk = 1;
            #5;
            clk = 0;
        end while (!done);
        $finish;
    end
endmodule
"""
SHELL_TB = """`timescale 1ps/1ps
module bellows_shell_tb;
    import "DPI-C" function void shell_init(input string scenario, output int r, d, p);
    import "DPI-C" function void shell_drive(input int rise, output int resets, reg_ctl,
        output longint unsigned reg_value, output int dd_ctl, output bit [511:0] dd_in,
        output int pci_ctl, output bit [255:0] pci_in);
    import "DPI-C" function int shell_gate_rx(input int flags);
    import "DPI-C" function void shell_sample(input int rise, dd_flags, dd_addr, burst,
        input longint unsigned mask, input bit [511:0] dd_out,
        input int pci_flags, input longint unsigned rd_addr, input int rd_size,
        input longint unsigned wr_addr, input int wr_size, input bit [255:0] wr_out);
    import "DPI-C" function int shell_post(input int rise, valid, input longint unsigned reg_value,
        input int a_id, r_id, a_ver, r_ver);
    bit [2:0] clocks;
    int resets, reg_ctl, dd_ctl, pci_ctl;
    longint unsigned reg_value;
    bit [511:0] dd_in;
    bit [255:0] pci_in;
    wire [63:0] rd_value, be, rd_addr, wr_addr;
    wire [31:0] a_id, r_id, a_ver, r_ver;
    wire reg_valid, dd_read, dd_write, rd_req, wr_req, rd_afull;
    wire [25:0] dd_addr, rd_size, wr_size;
    wire [6:0] burst;
    wire [511:0] dd_out;
    wire [255:0] wr_out;
    SoftShell dut (
        .pcie_refclk(clocks[2]), .pcie_pinrst_n(!resets[2]), .nic_refclk(1'b0), .tor_refclk(1'b0),
        .clk_100(clocks[0]), .rst_100(resets[0]), .asl_id_out(a_id), .role_id_out(r_id),
        .asl_version_out(a_ver), .role_version_out(r_ver),
        .aslregA_read_in(reg_ctl[18]), .aslregA_write_in(reg_ctl[19]), .aslregA_addr_in(reg_ctl[17:0]),
        .aslregA_wrdata_in(reg_value), .aslregA_rddata_out(rd_value), .aslregA_rdvalid_out(reg_valid),
        .aslregB_read_in(1'b0), .aslregB_write_in(1'b0), .aslregB_addr_in('0), .aslregB_wrdata_in('0),
        .shellreg_rddata_in('0), .shellreg_rdvalid_in(1'b0), .asl_network_active_in(1'b0),
        .nic_clk(1'b0), .nic_rst(1'b1), .tor_clk(1'b0), .tor_rst(1'b1), .nic_rx_in('0), .tor_rx_in('0),
        .nic_rx_valid_in(1'b0), .nic_rx_error_in(1'b0), .nic_rx_fcs_error_in(1'b0), .nic_rx_fcs_valid_in(1'b0),
        .tor_rx_valid_in(1'b0), .tor_rx_error_in(1'b0), .tor_rx_fcs_error_in(1'b0), .tor_rx_fcs_valid_in(1'b0),
        .nic_tx_ready_in(1'b0), .tor_tx_ready_in(1'b0),
        .ammA_clk(clocks[1]), .ammA_rst(resets[1]), .ammA_ready_in(dd_ctl[0]), .ammA_readdatavalid_in(dd_ctl[1]),
        .ammA_read_out(dd_read), .ammA_write_out(dd_write), .ammA_address_out(dd_addr),
        .ammA_readdata_in(dd_in), .ammA_writedata_out(dd_out), .ammA_burstcount_out(burst), .ammA_byteenable_out(be),
        .ammB_clk(1'b0), .ammB_rst(1'b1), .ammB_ready_in(1'b0), .ammB_readdata_in('0), .ammB_readdatavalid_in(1'b0),
        .pcieA_clk(clocks[2]), .pcieA_rst(resets[2]), .pcieB_clk(1'b0), .pcieB_rst(1'b1),
        .pcieA_intack_in(1'b0), .pcieB_intack_in(1'b0), .pcieA_intmax_in('0), .pcieB_intmax_in('0),
        .pcieA_intaux_read_in(1'b0), .pcieB_intaux_read_in(1'b0), .pcieB_wrack_in(1'b0),
        .pcieA_wrreq_out(wr_req), .pcieA_wrack_in(pci_ctl[2]), .pcieA_wrbytes_out(wr_size), .pcieA_wraddr_out(wr_addr),
        .pcieA_wrdata_out(wr_out), .pcieA_wrdata_rden_in(pci_ctl[3]), .pcieA_wrdone_in(pci_ctl[4]),
        .pcieB_wrdata_rden_in(1'b0), .pcieB_wrdone_in(1'b0),
        .pcieA_rdreq_out(rd_req), .pcieA_rdack_in(pci_ctl[0]), .pcieA_rdbytes_out(rd_size), .pcieA_rdaddr_out(rd_addr),
        .pcieA_rddata_in(pci_in), .pcieA_rddata_wren_in(pci_ctl[1]), .pcieA_rddata_afull_out(rd_afull),
        .pcieB_rdack_in(1'b0), .pcieB_rddata_in('0), .pcieB_rddata_wren_in(1'b0)
    );
    int r, d, p, done;
    longint nr, nd, np, at_ps, previous_ps;
    logic [2:0] edges, rises;
    string scenario;
    initial begin
        if (!$value$plusargs("scenario=%s", scenario)) $fatal(1, "Missing shell scenario");
        shell_init(scenario, r, d, p);
        nr = r; nd = d; np = p;
        do begin
            at_ps = nr < nd ? nr : nd;
            if (np < at_ps) at_ps = np;
            edges = {np == at_ps, nd == at_ps, nr == at_ps};
            rises = edges & ~clocks;
            #(at_ps - previous_ps - 3);
            shell_drive(int'(rises), resets, reg_ctl, reg_value, dd_ctl, dd_in, pci_ctl, pci_in);
            #1;
            pci_ctl = shell_gate_rx({29'b0, rd_afull, wr_req, rd_req});
            #1;
            shell_sample(int'(rises), {30'b0, dd_write, dd_read}, int'(dd_addr), int'(burst), be, dd_out,
                         {29'b0, rd_afull, wr_req, rd_req}, rd_addr, int'(rd_size), wr_addr, int'(wr_size), wr_out);
            #1;
            clocks ^= edges;
            #1;
            done = shell_post(int'(rises), int'(reg_valid), rd_value, a_id, r_id, a_ver, r_ver);
            if (edges[0]) nr += r;
            if (edges[1]) nd += d;
            if (edges[2]) np += p;
            previous_ps = at_ps + 1;
        end while (!done);
        $finish;
    end
endmodule
"""


@dataclass(frozen=True)
class CoreCase:
    name: str
    mode: int
    seed: int
    ci: bytes = b""
    co: bytes = b""
    cs: int = -1
    di: bytes | str = b""
    do: bytes = b""
    ds: int = -1
    flags: int = 0
    bad_keep: int = -1
    mutant: str = "-"

    def line(self):
        def field(value):
            return value if isinstance(value, str) else value.hex() or "-"
        return " ".join(map(str, (self.name, self.mode, self.seed, self.flags, self.bad_keep, self.mutant,
                                  field(self.ci), field(self.co), self.cs, field(self.di), field(self.do), self.ds)))


def encoding(name, raw, seed=17, **options):
    return CoreCase(name, 0, seed, ci=raw, co=compress(raw), cs=0, **options)


def decoding(name, raw, seed=17):
    expected, error = decode(raw)
    return CoreCase(name, 1, seed, di=raw, do=expected, ds=error)


def roundtrip(name, raw, seed=17, **options):
    return CoreCase(name, 2, seed, ci=raw, cs=0, do=raw, ds=0, **options)


def core_groups(capacity, matched):
    for seed in SEEDS:
        raw = random.Random(seed).randbytes(capacity)
        yield [encoding(f"empty_{seed}", b"", seed), encoding(f"singleton_{seed}", raw[:1], seed),
               encoding(f"exact_capacity_{seed}", raw, seed),
               encoding(f"back_to_back_hash_clear_{seed}", raw[::-1], seed),
               roundtrip(f"roundtrip_{seed}", raw, seed, flags=1)]
    raw = b"A" * (capacity + 2)
    yield [CoreCase("capacity_overflow_drain", 0, 17, ci=raw, cs=5),
           CoreCase("overflow_and_framing_same_edge", 0, 17, ci=raw, cs=6, bad_keep=capacity),
           CoreCase("overflow_then_framing_retains_first", 0, 17, ci=raw + b"B", cs=5, bad_keep=capacity + 1),
           CoreCase("framing_then_overflow_retains_first", 0, 17, ci=raw, cs=6, bad_keep=0),
           CoreCase("bad_keep_on_nonempty_last", 0, 17, ci=b"\x80\xff", cs=6, bad_keep=1),
           encoding("recovery_after_discard", b"Z")]
    yield [encoding("reset_stalled_encoder", b"A" * capacity, flags=2), roundtrip("recover_from_encoder_reset", b"Z"),
           CoreCase("reset_stalled_decoder", 1, 89, di=sequence(b"reset me"), do=b"reset me", ds=0, flags=2),
           decoding("recover_from_decoder_reset", sequence(b"recovered"))]
    decoded = b"ABCD" * 100
    ext = sequence(b"ABCD", 4, len(decoded) - 8) + sequence(b"ABCD")
    raw = b"B" * min(257, capacity)
    yield [CoreCase("simultaneous_independent_then_mode_request", 3, 89, ci=raw, co=compress(raw), cs=0,
                    di=ext, do=decoded, ds=0, flags=1),
           decoding("external_decode_beyond_compressor", ext), roundtrip("mode_transition", b"z")]
    if capacity in (1, 65536):
        literals = random.Random(17).randbytes(65535)
        wrap = sequence(literals, 65535, 40) + sequence(b"12345", 65535, 100) + sequence(b"abcde")
        yield [decoding("empty_raw_lz4", b"\x00"), decoding("history_wrap_and_offset_65535", wrap),
               decoding("stale_history_not_visible", b"\x00\x01\x00\x00"),
               decoding("decoder_final_recovery", b"\x10\xff")]
    if capacity == 65536:
        malformed = {
            "truncated_literal_extension": b"\xf0\xff",
            "truncated_literal_prefix": b"\x40abc",
            "truncated_low_offset": b"\x10a",
            "truncated_high_offset": b"\x10a\x01",
            "no_sequence_after_offset": b"\x10a\x01\x00",
            "truncated_match_extension": b"\x1fa\x01\x00\xff",
            "zero_offset_drains": b"\x10a\x00\x00\xff\x10b",
            "unavailable_history_drains": b"\x20ab\x03\x00\xff\x00",
            "extension_termination_zero": sequence(b"x" * 270, 1, 274) + sequence(b"tail!"),
        }
        yield [decoding(name, raw) for name, raw in malformed.items()]
        yield [CoreCase("literal_length_uint32_overflow", 1, 17, di="overflow", ds=4),
               decoding("overflow_recovery", b"\x10\xa2")]
        for size in (11, 12, 13, 14, 15, 16, 24, 25, 26, 269, 270, 271, 279, 280, 281, 65535):
            raw = b"A" * size
            yield [encoding(f"match_or_extension_boundary_{size}", raw),
                   encoding(f"literal_extension_boundary_{size}", random.Random(size).randbytes(size))]
        for size in (4096, 65536):
            for name, pattern in (("a", b"A"), ("abcd", b"ABCD"), ("ramp", bytes(range(256)))):
                raw = pattern * (size // len(pattern))
                yield [encoding(f"ratio_{name}_{size}", raw), roundtrip(f"repeated_roundtrip_{name}_{size}", raw)]
        # These four-byte starts share a key but not a word.
        collide = b"\x00\x00\x00\x00x\x02\x01\x00\x00y" * 25
        yield [encoding("most_recent_collision", collide), encoding("no_stale_collision", collide[::-1])]
        tie = bytes(range(20)) + bytes(range(4, 8)) + bytes(range(24, 48))
        yield [CoreCase("all_literal_on_equal_candidate", 0, 17, ci=tie, co=sequence(tie), cs=0)]
        for name, raw, common in matched:
            yield [encoding(f"matched_encode_{name}", raw), decoding(f"matched_decode_{name}", common)]


def canary(address, size):
    return bytes(((address + i) * 29 + 0xa5) & 255 for i in range(size))


class ShellCase:
    def __init__(self, name, clocks=(5000, 3500, 2700)):
        self.name, self.clocks = name, clocks
        self.commands = ["Z 7 12", "D 35"]
        self.work = 0
        self.encodings = []

    def add(self, *commands):
        self.commands.extend(commands)

    def reg(self, op, address, value):
        self.add(f"{op} {address} {value}")

    def memory(self, op, bank, address, value):
        if value:
            self.add(f"{op} {bank} {address} {value.hex()}")

    def descriptor(self, mode, n, cap, ds, dd, hs=0x100fe0, hd=0x200fe0):
        for index, value in enumerate((mode, hs, hd, n, cap, ds, dd), 4):
            self.reg("W", index, value)

    def window(self, offset, data, write):
        for start in range(0, len(data), 64):
            address = offset + start
            beat = data[start:start + 64]
            beat += canary(address + len(beat), 64 - len(beat))
            self.reg("W", 0x12, address)
            for lane in range(8):
                if write:
                    self.reg("W", 0x18 + lane, int.from_bytes(beat[8*lane:8*lane + 8], "little"))
            self.reg("W", 0x13, 2 if write else 1)
            self.add(f"P {0x13} 7 2")
            for lane in range(8):
                if not write:
                    self.reg("R", 0x18 + lane, int.from_bytes(beat[8*lane:8*lane + 8], "little"))

    def complete(self, code, count=None, pcie=None, ddr=None):
        self.add("P 3 3 2")
        self.reg("R", 3, 2 | (4 if code else 0))
        self.reg("R", 12, code)
        if count is not None:
            self.reg("R", 11, count)
        self.add("Y 13")
        if pcie is not None:
            self.reg("R", 14, pcie)
        if ddr is not None:
            self.reg("R", 15, ddr)

    def job(self, mode, data, cap, expected, code, *, native=False, windows=False,
            ds=0x10000, dd=0x40000, hs=0x100fe0, hd=0x200fe0):
        self.work += len(data) + len(expected)
        src_end = (len(data) + 63) & ~63
        dst_end = ((len(expected) + 63) & ~63) + 64
        for bank, address, size in (("d", ds, src_end + 64), ("d", dd, dst_end),
                                    ("h", hd & ~63, dst_end + 64)):
            self.memory("M", bank, address, canary(address, size))
        if native:
            self.memory("M", "h", hs, data + canary(hs + len(data), 64))
        elif windows:
            self.window(ds, data, True)
        else:
            self.memory("M", "d", ds, data)
        self.descriptor(mode, len(data), cap, ds, dd, hs, hd)
        self.reg("W", 2, 1 if native else 8)
        self.complete(code, len(expected), (len(data) + len(expected)) if native else 0,
                      (1 + native) * (len(data) + len(expected)))
        self.memory("C", "d", dd, expected + canary(dd + len(expected), dst_end - len(expected)))
        self.memory("C", "d", ds, data + canary(ds + len(data), src_end + 64 - len(data)))
        self.memory("C", "d", dd - 64, canary(dd - 64, 64))
        if native:
            self.memory("C", "h", hs, data + canary(hs + len(data), 64))
            self.memory("C", "h", hd - 32, canary(hd - 32, 32))
            self.memory("C", "h", hd, expected + canary(hd + len(expected), dst_end - len(expected)))
        if mode == 0 and code == 0:
            self.add(f"E {'h' if native else 'd'} {hd if native else dd} {len(expected)}")
            self.encodings.append(data)
        if windows:
            self.window(dd, expected, False)

    def content(self):
        role_guard = 20000 + 96 * self.work
        event_guard = math.ceil(role_guard * 2 * sum(self.clocks[0] / p for p in self.clocks))
        return "\n".join((" ".join(map(str, (self.name, *self.clocks, event_guard))), *self.commands)) + "\n"


def shell_cases(golden, matched):
    test = ShellCase("frozen_softreg_resident")
    test.reg("R", 0, 0x42454c4c4f574c32)
    test.reg("R", 1, 0x000200000002424d)
    for address, expected in ((63, 0x8926fc9c4e6256d9), (0x20000, 0x8926fc9c4e6256d9),
                              (0x20001, 65536), (0x20002, 64), (0x20003, 128),
                              (0x20004, 0), (0x20012, 0), (0x3ffff, 0)):
        test.reg("R", address, expected)
    for address in (63, 0x20002, 0x20004):
        test.reg("W", address, 99)
    test.reg("R", 4, 0)
    test.reg("R", 0x20002, 64)
    test.reg("W", 0x12, 1)
    test.reg("W", 0x13, 2)
    test.reg("R", 0x13, 6)
    for values in golden.values():
        test.job(*values, windows=True)
    yield test

    test = ShellCase("dma_page_partial_canaries", (5000, 7300, 8100))
    data = random.Random(89).randbytes(257)
    expected, code = role(0, data, 300)
    test.job(0, data, 300, expected, code, native=True)
    # Native read also fetches the last destination DWORD's unowned bytes.
    test.add("L 264 260", "T 511")
    for mode, raw in ((1, sequence(b"ab", 2, 123) + sequence(b"12345")),
                      (2, random.Random(17).randbytes(193))):
        expected, code = role(mode, raw, 512)
        test.job(mode, raw, 512, expected, code, native=True)
    yield test

    test = ShellCase("descriptor_and_capacity", (5000, 8200, 3100))
    test.add("A")
    bad = [(3, 16, 16, 0x10000, 0x40000, 0x100fe0, 0x200fe0, 8),
           (1, 0, 16, 0x10000, 0x40000, 0x100fe0, 0x200fe0, 8),
           (0, 65537, 16, 0x10000, 0x40000, 0x100fe0, 0x200fe0, 8),
           (2, 65, 16, 0x10000, 0x10040, 0x100fe0, 0x200fe0, 8),
           (2, 65, 16, 0xffffffc0, 0x40000, 0x100fe0, 0x200fe0, 8),
           (2, 16, 65, 0x10000, 0xffffffc0, 0x100fe0, 0x200fe0, 8),
           (2, 16, 16, 0x10001, 0x40000, 0x100fe0, 0x200fe0, 8),
           (2, 33, 16, 0x10000, 0x40000, 0x100fe0, 0x101000, 1),
           (2, 33, 16, 0x10000, 0x40000, (1 << 64) - 32, 0x200fe0, 1),
           (2, 16, 16, 0x10000, 0x40000, 0x100fe1, 0x200fe0, 1),
           (2, 16, 16, 0x10000, 0x40000, 0x100fe0, 0x200fe0, 9)]
    for mode, n, cap, ds, dd, hs, hd, start in bad:
        test.descriptor(mode, n, cap, ds, dd, hs, hd)
        test.reg("W", 2, start)
        test.complete(1, 0, 0, 0)
    test.descriptor(3, 1, 4, 0x10000, 0x40000)
    test.add("W 2 8", "D 2", "W 2 2")
    test.complete(1, 0)
    test.add("W 2 2", "R 3 0", "R 12 0", "N")
    for mode, data, cap in ((0, b'A' * 16, 3), (2, b'x' * 16, 10), (1, b"\x00", 0),
                            (1, b"\x40abc", 16), (1, b"\x10a\x00\x00\x00", 16),
                            (1, b"\x10a\x02\x00\x00", 16)):
        expected, code = role(mode, data, cap)
        test.job(mode, data, cap, expected, code)
    yield test

    test = ShellCase("busy_cancel_reset_and_recovery", (5000, 2600, 6600))
    data = b"AB" * 16
    for barrier, start, reset in (("d", 8, 0), ("r", 1, 0), ("s", 1, 0),
                                  ("p", 8, 2), ("r", 1, 4), ("p", 8, 1)):
        test.memory("M", "d", 0x10000, data)
        test.memory("M", "h", 0x100fe0, data)
        test.descriptor(2, len(data), 64, 0x10000, 0x40000)
        test.add(f"F {barrier}", f"W 2 {start}", f"B {barrier}")
        if reset:
            test.add(f"Z {reset} 18", "F -", "D 35")
            if reset == 1:
                test.add("R 3 0", "R 12 0")
            else:
                test.complete(3)
        else:
            test.add("W 4 0", "R 4 2", "W 2 8", "R 12 2", "W 2 4", "R 3 5", "F -")
            test.complete(3)
        test.add("D 16")
        test.job(1, b"\x20xy", 2, b"xy", 0, native=start == 1)
    yield test
    for name, data, common in matched:
        case = ShellCase(f"matched_resident_{name}")
        case.job(0, data, len(common), common, 0)
        case.job(1, common, len(data), data, 0)
        yield case


def manifest():
    doc = json.loads((PROJECT / "rtl/longspeak_sources.json").read_bytes())
    paths = doc["sources"]
    if (doc["schema"] != "vulcan-longspeak-sources/v1" or len(set(paths)) != len(paths)
            or any(not re.fullmatch(r"rtl/[A-Za-z0-9_]+\.(?:sv|sdc)", path) for path in paths)
            or set(paths) != {str(p.relative_to(PROJECT)) for p in (PROJECT / "rtl").glob("*.sv")}
            | {"rtl/vulcan_role.sdc"}):
        raise ValueError("Invalid or incomplete LongsPeak source manifest")
    return [p for p in paths if p.endswith(".sv")]


def execution_deadline():
    now = time.time()
    deadline = float(os.environ.get("VULCAN_EXECUTION_DEADLINE", now + 5400))
    patrol = float(os.environ.get("VULCAN_PATROL_CHECK_TIMEOUT_S", 5400))
    if not math.isfinite(deadline) or not math.isfinite(patrol) or patrol <= 0:
        raise ValueError("Invalid Runtime execution deadline")
    return time.monotonic() + min(deadline - now, patrol, 5400)


def headroom(deadline):
    seconds = (deadline - time.monotonic()) / 2
    if seconds < 1:
        raise TimeoutError("Runtime deadline has no remaining execution headroom")
    return seconds


def build(folder, deadline, *, capacity=None, mutant=None, shell=False, first):
    folder.mkdir()
    inputs = manifest()
    defines = []
    if shell:
        if not re.search(r"(?m)^setShellParam use_ecc_ddr 1\s*$",
                         (PROJECT / SHELL / "LongsPeak_Role.qsf").read_text()):
            raise ValueError("QSF does not select the admitted LongsPeak ECC geometry")
        inputs = [f"{SHELL}/Types/ShellTypes.sv", *inputs,
                  f"{SHELL}/longspeak_dma_cdc.sv", f"{SHELL}/SoftShell.sv", "tests/tb_softshell.cpp"]
        top, wrapper = "bellows_shell_tb", SHELL_TB
        defines = ["--define", "USE_ECC_DDR", "--vendor-lib", "altera_mf.v"]
    else:
        omit = {"bellows_l1_ddr.sv", "bellows_l1_reset_sync.sv", "bellows_l2_dma.sv",
                "Role_BellowsL2.sv", "vulcan_role.sv"}
        inputs = [p for p in inputs if Path(p).name not in omit] + ["tests/tb_core.cpp"]
        top, wrapper = "bellows_core_tb", CORE_TB
        defines = ["--define", f"TEST_CAPACITY={capacity}"]
    for path in inputs:
        dest = folder / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / path, dest)
    if mutant:
        filename, old, new, _ = MUTANTS[mutant]
        path = folder / "rtl" / filename
        source = path.read_text()
        if source.count(old) != 1:
            raise ValueError(f"{mutant}: target RTL must contain exactly one mutation site")
        path.write_text(source.replace(old, new))
        publish(folder / "mutation.json", {"file": f"rtl/{filename}", "original_sha256": sha256(source.encode()),
                                           "old": old, "new": new})
    (folder / f"tests/{top}.sv").write_text(wrapper)
    (folder / "cases").mkdir()
    first_path = "cases/first.txt"
    (folder / first_path).write_text(first)
    # Parallelize across configurations, not inside Verilator 5.020's build thread pool.
    argv = [sys.executable, "-m", "vulcan_agent.vulcan_kit.simulation", "--project", str(folder),
            "--top", top, "--target", "bedrock-longspeak-arria10", "--jobs", "1",
            "--timeout-s", str(headroom(deadline)), *defines]
    for path in (*inputs, f"tests/{top}.sv", first_path):
        argv.extend(("--input", path))
    argv.append(f"--plusarg=+scenario={first_path}")
    with (folder / "runner.jsonl").open("x") as out, (folder / "runner.stderr").open("x") as err:
        result = subprocess.run(argv, stdout=out, stderr=err, timeout=headroom(deadline) * 1.1, check=False)
    lines = (folder / "runner.jsonl").read_text().splitlines()
    if not lines:
        raise RuntimeError(f"No simulator runner receipt: {folder}/runner.stderr")
    report = json.loads(lines[-1])
    stages = report["phases"]
    if (not report["inputs_current"] or stages["build"]["result"]["status"] != "passed"
            or not stages["build"]["result"]["process_scope_settled"] or "run" not in stages):
        raise RuntimeError(f"Simulator build did not complete: {report['receipt']}")
    stage = stages["run"]
    stdout, stderr = Path(stage["stdout"]), Path(stage["stderr"])
    if mutant:
        intended = MUTANTS[mutant][3]
        if (result.returncode != 1 or stage["result"]["status"] != "failed"
                or not stage["result"]["process_scope_settled"] or not stderr.is_file()
                or not re.search(rf"(?m)^CORE_ASSERT {intended} case=", stderr.read_text())):
            raise RuntimeError(f"{mutant}: expected executed assertion {intended}; see {report['receipt']}")
    elif result.returncode or report["status"] != "passed":
        detail = stderr.read_text().splitlines()[-4:]
        raise RuntimeError(f"Behavior failed {report['receipt']}: {'; '.join(detail)}")
    return report, stdout


def reuse(folder, binary, name, contents, deadline):
    path = folder / "cases" / f"{name}.txt"
    path.write_text(contents)
    stdout, stderr = path.with_suffix(".stdout"), path.with_suffix(".stderr")
    with stdout.open("x") as out, stderr.open("x") as err:
        result = subprocess.run([str(binary), f"+scenario={path}"], cwd=folder, stdout=out, stderr=err,
                                timeout=headroom(deadline), check=False)
    if result.returncode:
        raise RuntimeError(f"Behavior failed {stderr}: {'; '.join(stderr.read_text().splitlines()[-4:])}")
    return stdout


def core_receipt(path, cases):
    observed = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields[:1] == ["CORE_PASS"]:
            _, name, *counts, encoded = fields
            if name in observed:
                raise ValueError(f"Duplicate core observation {name}: {path}")
            payload = bytes.fromhex(encoded) if encoded != "-" else b""
            observed[name] = (list(map(int, counts)), payload)
        if fields[:1] == ["CORE_RESET"]:
            _, name, cycles = fields
            if name in observed:
                raise ValueError(f"Duplicate reset observation {name}: {path}")
            observed[name] = ([int(cycles)], b"")
    if set(observed) != {case.name for case in cases}:
        raise ValueError(f"Incomplete core observations: {path}")
    for case in cases:
        counts, encoded = observed[case.name]
        if len(counts) == 1:
            if not (case.flags & 2):
                raise ValueError(f"Unscheduled reset: {case.name}")
            yield {"id": case.name, "reset_while_stalled": True, "cycles_to_reset": counts[0]}
            continue
        if case.cs == 0 and case.mode != 2 and decode(encoded) != (case.ci, 0):
            raise ValueError(f"Independent cross-decode failed: {case.name}")
        if case.name.startswith("ratio_") and len(encoded) >= len(case.ci):
            raise ValueError(f"Compression ratio is not below one: {case.name}")
        keys = ("capacity", "cycles", "compress_input_stalls", "decode_input_stalls", "compress_output_stalls",
                "decode_output_stalls", "compress_status_stalls", "decode_status_stalls")
        yield dict(zip(keys, counts, strict=True), id=case.name,
                   encoded_bytes=len(encoded), encoded_sha256=sha256(encoded) if encoded else None,
                   compression_ratio=len(encoded) / len(case.ci) if encoded and case.ci else None)


def shell_receipt(path, case):
    summary, cycles, compressed = [], [], []
    for line in path.read_text().splitlines():
        if line.startswith("SHELL_PASS "):
            summary.append(line.split())
        if line.startswith("SHELL_CYCLES "):
            cycles.append(int(line.split()[-1]))
        if line.startswith("SHELL_ENCODE "):
            compressed.append(bytes.fromhex(line.split()[-1]))
    if len(summary) != 1 or summary[0][1] != case.name:
        raise ValueError(f"Incomplete shell observations: {path}")
    expected_jobs = sum(c.startswith("Y ") for c in case.commands)
    if len(cycles) != expected_jobs:
        raise ValueError(f"Missing shell hardware-cycle observations: {path}")
    encoded = []
    for data, block in zip(case.encodings, compressed, strict=True):
        if decode(block) != (data, 0):
            raise ValueError(f"Independent cross-decode of SoftShell readback failed: {path}")
        encoded.append({"input_sha256": sha256(data), "encoded_sha256": sha256(block),
                        "encoded_bytes": len(block), "input_bytes": len(data)})
    keys = ("role_cycles", "avalon_reads", "avalon_writes", "native_pcie_reads", "native_pcie_writes",
            "native_pcie_read_bytes", "native_pcie_write_bytes", "transport_coverage_mask")
    return dict(zip(keys, map(int, summary[0][2:]), strict=True), id=case.name, job_cycles=cycles,
                clock_half_period_ps=case.clocks, cross_decoded_outputs=encoded)


def behavior(attempt, gold, deadline):
    matched = tuple(corpus())
    groups = {f"core-{n}": tuple(core_groups(n, matched)) for n in CAPACITIES}
    shell = tuple(shell_cases(gold, matched))
    slots = len(os.sched_getaffinity(0))
    configs = {name: {"capacity": int(name.split("-")[-1]),
                      "first": "\n".join(c.line() for c in cases[0]) + "\n"} for name, cases in groups.items()}
    configs["shell"] = {"shell": True, "first": shell[0].content()}
    for name in MUTANTS:
        configs[f"mutant-{name}"] = {"mutant": name, "capacity": 257,
                                     "first": encoding(f"negative_{name}", b"A" * 37, mutant=name).line() + "\n"}
    with ThreadPoolExecutor(max_workers=min(slots, len(configs))) as pool:
        pending = {name: pool.submit(build, attempt / name, deadline, **opts)
                   for name, opts in configs.items()}
        built = {name: task.result() for name, task in pending.items()}
    with ThreadPoolExecutor(max_workers=min(slots, 64)) as pool:
        running = []
        core_rows, shell_rows = [], []
        for name, batches in groups.items():
            simulation, path = built[name]
            core_rows.extend(core_receipt(path, batches[0]))
            binary = Path(simulation["workspace"]) / "obj/sim"
            for i, batch in enumerate(batches[1:], 1):
                text = "\n".join(c.line() for c in batch) + "\n"
                task = pool.submit(reuse, attempt / name, binary, f"batch-{i}", text, deadline)
                running.append((task, batch, False))
        simulation, path = built["shell"]
        shell_rows.append(shell_receipt(path, shell[0]))
        for case in shell[1:]:
            task = pool.submit(reuse, attempt / "shell", Path(simulation["workspace"]) / "obj/sim",
                               case.name, case.content(), deadline)
            running.append((task, case, True))
        for task, cases, is_shell in running:
            path = task.result()
            if is_shell:
                shell_rows.append(shell_receipt(path, cases))
            else:
                core_rows.extend(core_receipt(path, cases))
    for key in ("compress_output_stalls", "decode_output_stalls", "compress_status_stalls", "decode_status_stalls"):
        if not any(row.get(key) for row in core_rows):
            raise RuntimeError(f"Core schedule did not exercise {key}")
    frozen_rows = [{"id": name, "mode": mode, "input_sha256": sha256(raw), "output_capacity": cap,
                    "output_length": len(expected), "output_sha256": sha256(expected),
                    "completion_code": code, "cycles": cycles}
                   for (name, (mode, raw, cap, expected, code)), cycles in zip(
                       gold.items(), shell_rows[0]["job_cycles"], strict=True)]
    return {"schema": "bellows-l2-behavior/v1", "attempt": str(attempt), "simulation_only": True,
            "clock_basis_hz": 100000000, "frozen_cases": frozen_rows,
            "simulator_receipts": {name: report["receipt"] for name, (report, _) in built.items()},
            "core": core_rows, "softshell": shell_rows,
            "negative_assertions": {name: spec[-1] for name, spec in MUTANTS.items()},
            "matched_corpus": [describe(*block) for block in matched]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--golden", required=True, type=Path)
    args = parser.parse_args()
    deadline = execution_deadline()
    evidence = PROJECT / "evidence"
    evidence.mkdir(exist_ok=True)
    # Preserve prior simulator artifacts when Runtime retries a check (exp-2fc5173640375068134ba439).
    attempt = Path(tempfile.mkdtemp(prefix="bellows-behavior-", dir=evidence))
    print(f"Behavior attempt: {attempt}", flush=True)
    gold_bytes = args.golden.read_bytes()
    gold = frozen(args.golden)
    report = behavior(attempt, gold, deadline)
    if args.golden.read_bytes() != gold_bytes:
        raise ValueError("Frozen oracle publication changed during behavior execution")
    publish(evidence / "behavior.json", dict(report, golden_sha256=sha256(gold_bytes)))


if __name__ == "__main__":
    main()
