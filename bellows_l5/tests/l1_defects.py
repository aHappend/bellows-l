"""Disposable source-bound mutants; only real semantic mismatches kill a defect."""

import json
import os
import random
import shutil
from uuid import uuid4

from l1_oracle import frame
from l1_runner import Simulation
from l1_transport import Case
from l1_zstd import sequence_frame
from preparation import sha256


def dma_testbench():
    """Direct public-interface response-ownership comparison (not a DUT mirror)."""
    return r"""`timescale 1ns/1ps
module tb;
reg clk=0,rst_n=0;
reg read_valid=0,write_valid=0;
reg [1:0] read_channel=0,write_channel=0;
reg [68:0] read_payload=0;
reg [136:0] write_payload=0;
wire read_ready,read_available,write_ready,write_available;
wire [3:0] lane_read_response,lane_write_response,lane_read_count,lane_write_count;
wire [63:0] lane_read_data;
wire lane_read_error,lane_write_error;
reg rd_rsp_valid=0,wr_rsp_valid=0;
reg [7:0] rd_rsp_data=0;
wire rd_req_valid,wr_req_valid,rd_rsp_ready,wr_rsp_ready;
wire [1:0] rd_req_channel,wr_req_channel;
wire [63:0] rd_req_addr,wr_req_addr;
wire [7:0] wr_req_data;
wire w_rd_req_valid,w_rd_rsp_ready,w_wr_req_valid,w_wr_rsp_ready;
wire [1:0] w_rd_req_channel,w_wr_req_channel;
wire [63:0] w_rd_req_addr,w_wr_req_addr,w_wr_req_data;
wire [3:0] w_rd_req_bytes;
wire [7:0] w_wr_req_strb;
integer ch,fd;
bellows_l4_sg_dma dut(
 .clk(clk),.rst_n(rst_n),.read_valid(read_valid),.read_channel(read_channel),
 .read_payload(read_payload),.read_ready(read_ready),.read_available(read_available),
 .write_valid(write_valid),.write_channel(write_channel),.write_payload(write_payload),
 .write_ready(write_ready),.write_available(write_available),
 .lane_read_response(lane_read_response),.lane_read_data(lane_read_data),
 .lane_read_count(lane_read_count),.lane_read_error(lane_read_error),
 .lane_write_response(lane_write_response),.lane_write_count(lane_write_count),
 .lane_write_error(lane_write_error),
 .rd_req_valid(rd_req_valid),.rd_req_channel(rd_req_channel),.rd_req_addr(rd_req_addr),
 .rd_req_ready(1'b1),.rd_rsp_valid(rd_rsp_valid),.rd_rsp_data(rd_rsp_data),
 .rd_rsp_error(1'b0),.rd_rsp_ready(rd_rsp_ready),
 .wr_req_valid(wr_req_valid),.wr_req_channel(wr_req_channel),.wr_req_addr(wr_req_addr),
 .wr_req_data(wr_req_data),.wr_req_ready(1'b1),.wr_rsp_valid(wr_rsp_valid),
 .wr_rsp_error(1'b0),.wr_rsp_ready(wr_rsp_ready),
 .w_rd_req_valid(w_rd_req_valid),.w_rd_req_channel(w_rd_req_channel),
 .w_rd_req_addr(w_rd_req_addr),.w_rd_req_bytes(w_rd_req_bytes),.w_rd_req_ready(1'b1),
 .w_rd_rsp_valid(1'b0),.w_rd_rsp_data(64'd0),.w_rd_rsp_error(1'b0),
 .w_rd_rsp_ready(w_rd_rsp_ready),.w_wr_req_valid(w_wr_req_valid),
 .w_wr_req_channel(w_wr_req_channel),.w_wr_req_addr(w_wr_req_addr),
 .w_wr_req_data(w_wr_req_data),.w_wr_req_strb(w_wr_req_strb),.w_wr_req_ready(1'b1),
 .w_wr_rsp_valid(1'b0),.w_wr_rsp_error(1'b0),.w_wr_rsp_ready(w_wr_rsp_ready));
always #5 clk=~clk;
task step; begin @(posedge clk); #1; @(negedge clk); #1; end endtask
initial begin
 fd=$fopen("ownership.txt","w"); #12; rst_n=1; step();
 for(ch=0;ch<4;ch=ch+1) begin
  read_channel=ch; read_payload={1'b0,64'h1234,4'd1}; read_valid=1; #1;
  if(read_ready!==1 || rd_req_channel!==ch[1:0]) $fatal(1,"DMA request fixture");
  step(); read_valid=0; repeat(3) step();
  rd_rsp_valid=1; rd_rsp_data=ch+17; #1;
  $fdisplay(fd,"%0d %0d %0d %0d",ch,lane_read_response,lane_read_data,lane_read_count);
  step(); rd_rsp_valid=0; step();
 end
 $fclose(fd); $finish;
end
endmodule
"""


def ownership(experiment, source, name):
    directory = experiment.directory / (name + "-" + uuid4().hex[:8])
    directory.mkdir()
    (directory / "tb.sv").write_text(dma_testbench())
    try:
        experiment.command(name + "-compile",
                           ["verilator", "--binary", "--timing", "-Wno-fatal",
                            "--top-module", "tb", "-j", "2", "--Mdir", "compile-obj",
                            "tb.sv", os.path.relpath(source / "bellows_l4_sg_dma.sv", directory)],
                           cwd=directory)
        experiment.command(name + "-simulation", ["./compile-obj/Vtb"], cwd=directory)
        records = [tuple(map(int, row.split()))
                   for row in (directory / "ownership.txt").read_text().splitlines()]
        if len(records) != 4:
            raise RuntimeError("DMA ownership fixture failed to execute four responses")
        if any((response, data, count) != (1 << ch, ch+17, 1)
               for ch, response, data, count in records):
            raise AssertionError("DMA response ownership semantic mismatch")
    finally:
        if (directory / "compile-obj").is_dir():
            shutil.rmtree(directory / "compile-obj")


def defects(experiment, libraries):
    geometry = (256, 3, 8, 256)
    dictionary = random.Random(2026).randbytes(256)
    independent = sequence_frame(b"aa", [(1, 7, 4), (1, 7, 4)])
    dict_frame = sequence_frame(b"", [(0, 7, 33), (0, 7, 33)], dictionary=dictionary)
    definitions = [
        ("fse-state", "bellows_l5_fse_decoder.sv",
         "next_state=row_base+(bits & mask);", "next_state=row_base+(bits & mask)+9'd1;",
         [Case("fse-state-control", independent, decompress=1)]),
        ("reverse-bits", "bellows_l5_reverse_reader.sv",
         "result_q<=extracted[31:0] & take_mask;",
         "result_q<=(extracted[31:0] ^ 32'd1) & take_mask;",
         [Case("reverse-bits-control", independent, decompress=1)]),
        ("dictionary-base", "bellows_l5_dictionary.sv",
         "byte_q<=image[byte_addr];", "byte_q<=image[byte_addr ^ 14'd1];",
         [Case("dictionary-base-control", dict_frame, codec=6, decompress=1,
               dictionary_id=0x12345678)]),
        ("xxh64-checksum", "bellows_l5_xxh64.sv",
         "h<=product^(product>>32);", "h<=product^(product>>32)^64'd1;",
         [Case("xxh64-control", b"0123456789abcdef0123456789")]),
        ("channel-owner", "bellows_l4_sg_dma.sv",
         "(4'b0001<<read_owner)", "(4'b0001<<(read_owner ^ 2'd1))", None),
        ("legacy-output", "bellows_l2_emitter.sv",
         "presented_data <= literal_hold;", "presented_data <= literal_hold ^ 8'd1;",
         [Case("legacy-control", b"abcdefghij", codec=0)]),
    ]
    source = experiment.directory / "source/rtl"
    records = []
    for name, filename, before, after, cases in definitions:
        original = (source / filename).read_text()
        if original.count(before) != 1:
            raise AssertionError(f"{name}: exact mutation anchor is not unique")
        # Prove the unmodified production source passes the same semantic fixture.
        if cases is None:
            ownership(experiment, source, "control-" + name)
        else:
            normal = Simulation(experiment, geometry, libraries)
            try:
                normal.run("control-" + name, cases, dictionary=dictionary)
            finally:
                normal.close()
        copied = experiment.directory / ("mutant-" + name + "-" + uuid4().hex[:8])
        shutil.copytree(source, copied)
        modified = original.replace(before, after)
        (copied / filename).write_text(modified)
        killed = False
        failure = None
        try:
            if cases is None:
                ownership(experiment, copied, "mutant-" + name)
            else:
                mutant = Simulation(experiment, geometry, libraries, source_directory=copied)
                try:
                    mutant.run("mutant-" + name, cases, dictionary=dictionary)
                finally:
                    mutant.close()
        except (AssertionError, ValueError) as error:
            # Child-tool failures are RuntimeError and cannot count as semantic kills.
            killed, failure = True, str(error)
        record = {"name": name, "file": filename, "before": before, "after": after,
                  "original_sha256": sha256(original.encode()),
                  "mutant_sha256": sha256(modified.encode()), "killed": killed,
                  "semantic_failure": failure}
        records.append(record)
        (experiment.directory / "mutations.json").write_text(json.dumps(records, indent=2) + "\n")
        if not killed:
            raise AssertionError(f"semantic mutant survived: {name}")
