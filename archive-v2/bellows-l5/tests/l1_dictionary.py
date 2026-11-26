"""Independent exact-edge checks for the four synchronous dictionary byte views."""

import random


def dictionary_testbench(directory, capacity):
    size = min(capacity, 16384)
    image = random.Random(89).randbytes(size)
    (directory / "dictionary-view.hex").write_text("".join(f"{b:02x}\n" for b in image))
    return r"""`timescale 1ns/1ps
module tb;
parameter integer CYCLE_LIMIT=500000;
reg clk=0,rst_n=0;
reg begin_valid=0,s_valid=0,s_last=0,status_ready=0;
wire begin_ready,s_ready,status_valid,loaded;
wire [3:0] status_error;
wire [31:0] id;
wire [14:0] size;
reg [7:0] s_data=0;
reg [3:0] rd_en=0;
reg [55:0] rd_addr=0;
wire [3:0] rd_valid;
wire [31:0] rd_data;
wire [3:0] index_valid,index_found;
wire [55:0] index_position;
reg [7:0] expected[0:SIZE-1];
reg [3:0] previous_valid=0;
reg [31:0] previous_data=0;
integer i,j,n,cycles=0,comparisons=0;
bellows_l5_dictionary #(.DICT_BYTES(CAPACITY)) dut(
 .clk(clk),.rst_n(rst_n),.idle_all(1'b1),
 .dict_begin_valid(begin_valid),.dict_begin_ready(begin_ready),
 .dict_begin_id(32'h12345678),.dict_begin_bytes(15'dSIZE),
 .dict_s_valid(s_valid),.dict_s_ready(s_ready),.dict_s_data(s_data),.dict_s_last(s_last),
 .dict_status_valid(status_valid),.dict_status_ready(status_ready),.dict_status_error(status_error),
 .dict_loaded(loaded),.dict_id(id),.dict_size(size),
 .rd_en(rd_en),.rd_addr(rd_addr),.rd_valid(rd_valid),.rd_data(rd_data),
 .index_en(4'd0),.index_chain(4'd0),.index_addr(56'd0),
 .index_valid(index_valid),.index_found(index_found),.index_position(index_position));
always #5 clk=~clk;
always @(posedge clk or negedge clk) begin
 if(!rst_n && {begin_ready,s_ready,status_valid,status_error,loaded,id,size,
               rd_valid,rd_data,index_valid,index_found,index_position}!==0)
  $fatal(1,"dictionary reset leakage");
end
always @(posedge clk) begin
 cycles=cycles+1;
 if(cycles>CYCLE_LIMIT) $fatal(1,"dictionary view operation bound");
end
task step; begin @(posedge clk); #1; @(negedge clk); #1; end endtask
initial begin
 #0.001;
 if({begin_ready,s_ready,status_valid,status_error,loaded,id,size,rd_valid,rd_data}!==0)
  $fatal(1,"dictionary time-zero reset leakage");
 $readmemh("dictionary-view.hex",expected);
 #11.999; rst_n=1; #1;
 if(begin_ready!==0) $fatal(1,"dictionary admission before first edge");
 @(negedge clk); #1; step();
 begin_valid=1; #1;
 if(begin_ready!==1) $fatal(1,"dictionary begin unavailable");
 step(); begin_valid=0;
 for(i=0;i<SIZE;i=i+1) begin
  s_valid=1; s_data=expected[i]; s_last=(i==SIZE-1); #1;
  n=0; while(!s_ready) begin step(); n=n+1;
   if(n>16) $fatal(1,"dictionary upload service bound"); end
  step(); s_valid=0;
 end
 n=0; while(!status_valid) begin step(); n=n+1;
  if(n>16) $fatal(1,"dictionary final preparation bound"); end
 if(status_error!==0 || loaded!==1 || id!==32'h12345678 || size!==SIZE)
  $fatal(1,"dictionary pin metadata");
 status_ready=1; step(); status_ready=0;
 for(i=0;i<SIZE;i=i+1) begin
  rd_en=15;
  for(j=0;j<4;j=j+1) rd_addr[j*14 +: 14]=(i+j)%SIZE;
  #1;
  if(rd_valid!==previous_valid || rd_data!==previous_data)
   $fatal(1,"dictionary read changed before sampling edge");
  @(posedge clk); #1;
  if(rd_valid!==15) $fatal(1,"dictionary read not valid immediately after edge");
  for(j=0;j<4;j=j+1) begin
   if(rd_data[j*8 +: 8]!==expected[(i+j)%SIZE])
    $fatal(1,"dictionary synchronous byte mismatch");
   comparisons=comparisons+1;
  end
  previous_valid=rd_valid; previous_data=rd_data;
  @(negedge clk); #1;
 end
 rd_en=0; step();
 if(rd_valid!==0 || rd_data!==0) $fatal(1,"dictionary stale read-valid");
 if(comparisons!=4*SIZE) $fatal(1,"dictionary incomplete byte comparisons");
 $display("DICTIONARY_VIEWS compared_bytes=%0d cycles=%0d",comparisons,cycles);
 $finish;
end
endmodule
""".replace("15'dSIZE", f"15'd{size}").replace("CAPACITY", str(capacity)).replace("SIZE", str(size))
