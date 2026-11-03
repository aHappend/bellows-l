"""Generated public-pin SystemVerilog transactor for bounded diagnostic cases."""

from dataclasses import dataclass


# Frozen public interface, independent of parsing the implementation.
INPUTS = {
    "rst_n": 1, "cmd_valid": 1, "cmd_channel": 2, "cmd_id": 16,
    "cmd_decompress": 1, "cmd_checksum_mode": 2, "cmd_src_bytes": 32,
    "cmd_dst_capacity": 32, "cmd_src_segments": 5, "cmd_dst_segments": 5,
    "sg_valid": 1, "sg_channel": 2, "sg_destination": 1, "sg_addr": 64,
    "sg_bytes": 32, "rd_req_ready": 1, "rd_rsp_valid": 1, "rd_rsp_data": 8,
    "rd_rsp_error": 1, "wr_req_ready": 1, "wr_rsp_valid": 1,
    "wr_rsp_error": 1, "status_ready": 1, "cmd_wide": 1, "cmd_codec": 3,
    "w_rd_req_ready": 1, "w_rd_rsp_valid": 1, "w_rd_rsp_data": 64,
    "w_rd_rsp_error": 1, "w_wr_req_ready": 1, "w_wr_rsp_valid": 1,
    "w_wr_rsp_error": 1, "cmd_dict_id": 32, "dict_begin_valid": 1,
    "dict_begin_id": 32, "dict_begin_bytes": 15, "dict_s_valid": 1,
    "dict_s_data": 8, "dict_s_last": 1, "dict_status_ready": 1,
}
OUTPUTS = {
    "cmd_ready": 1, "sg_ready": 1, "rd_req_valid": 1, "rd_req_channel": 2,
    "rd_req_addr": 64, "rd_rsp_ready": 1, "wr_req_valid": 1,
    "wr_req_channel": 2, "wr_req_addr": 64, "wr_req_data": 8, "wr_rsp_ready": 1,
    "status_valid": 1, "status_channel": 2, "status_id": 16, "status_error": 4,
    "status_src_bytes": 32, "status_dst_bytes": 32, "status_checksum": 32,
    "err_checksum_mismatch": 1, "w_rd_req_valid": 1, "w_rd_req_channel": 2,
    "w_rd_req_addr": 64, "w_rd_req_bytes": 4, "w_rd_rsp_ready": 1,
    "w_wr_req_valid": 1, "w_wr_req_channel": 2, "w_wr_req_addr": 64,
    "w_wr_req_data": 64, "w_wr_req_strb": 8, "w_wr_rsp_ready": 1,
    "dict_begin_ready": 1, "dict_s_ready": 1, "dict_status_valid": 1,
    "dict_status_error": 4, "dict_loaded": 1, "dict_id": 32, "dict_size": 15,
}


@dataclass(frozen=True)
class Case:
    name: str
    source: bytes
    codec: int = 5
    decompress: int = 0
    mode: int = 0
    wide: int = 0
    channel: int = 0
    capacity: int = 1024
    error: int = 0
    dictionary_id: int = 0
    pre_dma: bool = False
    segments: int = 1
    descriptor_error: int = 0
    dma_error: int = 0
    reset_before: bool = False
    command_source_bytes: int | None = None


def top_testbench(cases, geometry, directory, seed=17, dictionary=b""):
    """Generate vectors, not expected DUT values or hierarchical observations."""
    block, depth, copy, dict_bytes = geometry
    memory = max(2048, 4 * block + 4096, *(len(c.source) + 16 for c in cases),
                 *(c.capacity + 16 for c in cases))
    for i, case in enumerate(cases):
        (directory / f"source-{i}.hex").write_text(
            "\n".join(f"{b:02x}" for b in case.source) + "\n")
    (directory / "dictionary.hex").write_text(
        "\n".join(f"{b:02x}" for b in dictionary) + "\n")
    declarations = ["reg clk=0;"]
    declarations += [f"reg [{width-1}:0] {name}=0;" for name, width in INPUTS.items()]
    declarations += [f"wire [{width-1}:0] {name};" for name, width in OUTPUTS.items()]
    connection = ",\n".join(f".{name}({name})" for name in ("clk", *INPUTS, *OUTPUTS))
    reset_bus = "{" + ",".join(OUTPUTS) + "}"
    (directory / "dictionary-size.txt").write_text(f"{len(dictionary)}\n")
    (directory / "seed.txt").write_text(f"{seed}\n")
    calls = [r"""
 input_fd=$fopen("dictionary-size.txt","r");
 tokens=$fscanf(input_fd,"%d",ts); $fclose(input_fd);
 if(tokens!=1) $fatal(1,"missing dictionary length");
 if(ts>0) load_dictionary(ts,32'h12345678);
"""]
    (directory / "cases.txt").write_text("".join(
        [f"{len(cases)}\n"] + [
        f"{i} {len(c.source)} {c.codec} {c.decompress} {c.mode} {c.wide} "
        f"{c.channel} {c.capacity} {c.dictionary_id} {int(c.pre_dma)} "
        f"{c.segments} {c.descriptor_error} {c.dma_error} {int(c.reset_before)} "
        f"{len(c.source) if c.command_source_bytes is None else c.command_source_bytes}\n"
        for i, c in enumerate(cases)]))
    calls.append(r"""
 input_fd=$fopen("cases.txt","r");
 if(!input_fd) $fatal(1,"cannot open case metadata");
 tokens=$fscanf(input_fd,"%d",total_cases);
 if(tokens!=1) $fatal(1,"missing case count");
 for(tc=0;tc<total_cases;tc=tc+1) begin
  tokens=$fscanf(input_fd,"%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                 tn,ts,tcodec,td,tm,tw,tch,tcap,tid,tp,tsegments,tbad,tfault,treset,tdeclared);
  if(tokens!=15 || tn!=tc) $fatal(1,"malformed case metadata");
  run_case(tn,ts,tcodec,td,tm,tw,tch,tcap,tid);
 end
 $fclose(input_fd);
""")
    return r"""`timescale 1ns/1ps
module tb;
parameter integer CYCLE_LIMIT=2000000000;
""" + "\n".join(declarations) + f"""
bellows_l5_top #(.MAX_BLOCK_BYTES({block}), .SG_DEPTH({depth}),
 .COPY_BYTES({copy}), .DICT_BYTES({dict_bytes})) dut (
{connection});
localparam integer MEM={memory};
localparam integer BLOCK_BOUND={block};
""" + r"""
reg [7:0] source [0:MEM-1], destination [0:MEM-1], dictionary_image [0:16383];
integer cycles=0, command_edge=-1, descriptor_edge=-1;
integer case_begin_cycle=0;
integer r_pending=0, w_pending=0, r_delay=0, w_delay=0;
integer r_count=0, w_count=0, r_wide=0, w_wide=0;
integer read_bytes=0, write_bytes=0, completions=0, case_index=-1;
integer expected_source=0, expected_capacity=0, expected_channel=0, case_active=0;
integer i, j, fd, age;
integer input_fd,tc,tokens,tn,ts,tcodec,td,tm,tw,tch,tcap,total_cases;
integer tp,tsegments,tbad,tfault,read_fault=0,write_fault=0;
integer treset=0,pinned_size=0;
integer first_fault=0;
integer descriptors_complete=0;
integer source_ends[0:15], destination_ends[0:15], ns, nd;
reg [31:0] tid;
reg [31:0] tdeclared;
reg [63:0] held_read, held_write;
reg [7:0] held_strobe;
reg [127:0] old_status;
reg [127:0] old_read;
reg [141:0] old_write;
reg stalled_status=0, stalled_read=0, stalled_write=0;
reg [31:0] random_state;
always #5 clk=~clk;
task reset_outputs;
begin
 if (""" + reset_bus + r""" !== 0)
   $fatal(1,"RESET output not zero at time %0t",$time);
end
endtask
always @(posedge clk or negedge clk) if (!rst_n) reset_outputs();

always @(negedge clk) begin
 if (!rst_n) begin
  rd_req_ready=0; wr_req_ready=0; w_rd_req_ready=0; w_wr_req_ready=0;
  rd_rsp_valid=0; wr_rsp_valid=0; w_rd_rsp_valid=0; w_wr_rsp_valid=0;
 end else begin
  if(err_checksum_mismatch !== (status_valid && status_error==7))
    $fatal(1,"checksum flag outside matching valid completion");
  random_state = (random_state >> 1) ^ ((0-(random_state&1)) & 32'hd0000001);
  rd_req_ready=|random_state[2:0]; w_rd_req_ready=|random_state[2:0];
  wr_req_ready=|random_state[5:3]; w_wr_req_ready=|random_state[5:3];
  rd_rsp_valid=r_pending && r_delay==0 && !r_wide;
  w_rd_rsp_valid=r_pending && r_delay==0 && r_wide;
  wr_rsp_valid=w_pending && w_delay==0 && !w_wide;
  w_wr_rsp_valid=w_pending && w_delay==0 && w_wide;
  rd_rsp_data=held_read[7:0]; w_rd_rsp_data=held_read;
  rd_rsp_error=read_fault; w_rd_rsp_error=read_fault;
  wr_rsp_error=write_fault; w_wr_rsp_error=write_fault;
 end
end

always @(posedge clk) begin
 cycles=cycles+1;
 if(case_active && cycles-case_begin_cycle<=8000000 &&
    (cycles-case_begin_cycle)%1000000==0) begin
  $display("PROGRESS case=%0d cycles=%0d read=%0d written=%0d read_pending=%0d write_pending=%0d status=%0d error=%0d",
           case_index,cycles-case_begin_cycle,read_bytes,write_bytes,
           r_pending,w_pending,status_valid,status_error);
  $fflush();
 end
 if (cycles>CYCLE_LIMIT) $fatal(1,"operation-count bound, case=%0d",case_index);
 if (!rst_n) begin
  r_pending=0; w_pending=0; stalled_status=0; stalled_read=0; stalled_write=0;
 end else begin
  if (stalled_status &&
      (!status_valid || {status_channel,status_id,status_error,status_src_bytes,
                        status_dst_bytes,status_checksum} !== old_status))
    $fatal(1,"completion changed under stall");
  stalled_status=status_valid && !status_ready;
  old_status={status_channel,status_id,status_error,status_src_bytes,
              status_dst_bytes,status_checksum};
  if (stalled_read &&
      {w_rd_req_valid,rd_req_valid,w_rd_req_channel,rd_req_channel,
       w_rd_req_addr|rd_req_addr,w_rd_req_bytes} !== old_read)
    $fatal(1,"read request changed under stall");
  stalled_read=(rd_req_valid && !rd_req_ready)||(w_rd_req_valid && !w_rd_req_ready);
  old_read={w_rd_req_valid,rd_req_valid,w_rd_req_channel,rd_req_channel,
            w_rd_req_addr|rd_req_addr,w_rd_req_bytes};
  if (stalled_write &&
      {w_wr_req_valid,wr_req_valid,w_wr_req_channel,wr_req_channel,w_wr_req_addr|wr_req_addr,
       w_wr_req_data|{56'd0,wr_req_data},w_wr_req_strb} !== old_write)
    $fatal(1,"write request changed under stall");
  stalled_write=(wr_req_valid && !wr_req_ready)||(w_wr_req_valid && !w_wr_req_ready);
  old_write={w_wr_req_valid,wr_req_valid,w_wr_req_channel,wr_req_channel,w_wr_req_addr|wr_req_addr,
             w_wr_req_data|{56'd0,wr_req_data},w_wr_req_strb};
  if ((rd_rsp_valid && rd_rsp_ready)||(w_rd_rsp_valid && w_rd_rsp_ready)) begin
    if (!r_pending) $fatal(1,"unowned read response");
    if(read_fault) first_fault=1;
    read_bytes=read_bytes+r_count; r_pending=0;
  end
  if ((wr_rsp_valid && wr_rsp_ready)||(w_wr_rsp_valid && w_wr_rsp_ready)) begin
    if (!w_pending) $fatal(1,"unowned write response");
    if(write_fault) first_fault=1;
    if(!write_fault) write_bytes=write_bytes+w_count;
    w_pending=0;
  end
  if (r_pending && r_delay>0) r_delay=r_delay-1;
  if (w_pending && w_delay>0) w_delay=w_delay-1;
  if ((rd_req_valid && rd_req_ready)||(w_rd_req_valid && w_rd_req_ready)) begin
    if(first_fault) $fatal(1,"read issued after DMA error");
    if(!descriptors_complete) $fatal(1,"read before complete descriptors");
    if (r_pending || !case_active) $fatal(1,"unexpected/duplicate read");
    if (cycles<descriptor_edge+2) $fatal(1,"early DMA before D+2");
    r_wide=w_rd_req_valid; r_count=r_wide ? w_rd_req_bytes : 1;
    if ((r_wide ? w_rd_req_channel : rd_req_channel)!==expected_channel[1:0])
      $fatal(1,"read channel misassociation");
    age=(r_wide ? w_rd_req_addr : rd_req_addr)-64'h10000;
    if (r_count<1 || r_count>8 || age<0 || age+r_count>expected_source)
      $fatal(1,"read outside source");
    for(j=0;j<ns-1;j=j+1)
      if(age<source_ends[j] && age+r_count>source_ends[j])
        $fatal(1,"read crosses segment");
    held_read=0;
    for (j=0;j<r_count;j=j+1) held_read[j*8 +: 8]=source[age+j];
    r_delay=random_state[8:6]; r_pending=1;
    read_fault=(tfault==1 && read_bytes==0);
  end
  if ((wr_req_valid && wr_req_ready)||(w_wr_req_valid && w_wr_req_ready)) begin
    if(first_fault) $fatal(1,"write issued after DMA error");
    if(!descriptors_complete) $fatal(1,"write before complete descriptors");
    if (w_pending || !case_active) $fatal(1,"unexpected/duplicate write");
    w_wide=w_wr_req_valid; held_strobe=w_wide ? w_wr_req_strb : 8'd1;
    held_write=w_wide ? w_wr_req_data : {56'd0,wr_req_data};
    if ((w_wide ? w_wr_req_channel : wr_req_channel)!==expected_channel[1:0])
      $fatal(1,"write channel misassociation");
    age=(w_wide ? w_wr_req_addr : wr_req_addr)-64'h100000;
    if (held_strobe==0 || (held_strobe & (held_strobe+8'd1))!=0)
      $fatal(1,"noncontiguous/empty write strobes");
    w_count=0;
    for (j=0;j<8;j=j+1) if (held_strobe[j]) begin
      if (age+j<0 || age+j>=expected_capacity) $fatal(1,"write outside destination");
      destination[age+j]=held_write[j*8 +: 8]; w_count=w_count+1;
    end
    for(j=0;j<nd-1;j=j+1)
      if(age<destination_ends[j] && age+w_count>destination_ends[j])
        $fatal(1,"write crosses segment");
    w_delay=random_state[11:9]; w_pending=1;
    write_fault=(tfault==2 && write_bytes==0);
  end
  if (status_valid && status_ready) begin
    if (!case_active || r_pending || w_pending) $fatal(1,"early/duplicate completion");
    if (status_channel!==expected_channel[1:0] || status_id!==16'h5a5a)
      $fatal(1,"completion misassociation");
    if (status_src_bytes!==read_bytes || status_dst_bytes!==write_bytes)
      $fatal(1,"completion byte accounting");
    if (err_checksum_mismatch !== (status_error==7))
      $fatal(1,"checksum flag");
    if(cmd_ready!==0) $fatal(1,"same-edge speculative lane reuse");
    completions=completions+1;
    $fdisplay(fd,"RESULT %0d %0d %0d %0d %08x",case_index,status_error,
              status_src_bytes,status_dst_bytes,status_checksum);
    for (j=0;j<status_dst_bytes;j=j+1) $fwrite(fd,"%02x",destination[j]);
    $fwrite(fd,"\n");
    $fflush(fd);
    $display("TRANSACTION case=%0d cycles=%0d error=%0d read=%0d written=%0d",
             case_index,cycles-case_begin_cycle,status_error,read_bytes,write_bytes);
    $fflush();
  end
 end
end

task step;
begin @(posedge clk); #1; @(negedge clk); #1; end
endtask
task send_descriptor(input integer dest, input integer count, input reg [63:0] address);
integer n;
begin
 sg_destination=dest; sg_bytes=count; sg_addr=address; sg_valid=1; n=0;
 #1;
 while (!sg_ready) begin step(); n=n+1; if(n>1000) $fatal(1,"descriptor timeout"); end
 descriptor_edge=cycles+1;
 step(); sg_valid=0;
end
endtask
task load_dictionary(input integer size, input reg [31:0] id);
integer n,k,begin_cycle;
begin
 begin_cycle=cycles;
 $readmemh("dictionary.hex",dictionary_image,0,size-1);
 dict_begin_valid=1; dict_begin_id=id; dict_begin_bytes=size; #1;
 n=0;
 while (!dict_begin_ready) begin step(); n=n+1; if(n>1000) $fatal(1,"dictionary begin"); end
 step(); dict_begin_valid=0;
 for(k=0;k<size;k=k+1) begin
  dict_s_valid=1; dict_s_data=dictionary_image[k]; dict_s_last=(k==size-1); #1;
  n=0;
  while(!dict_s_ready) begin step(); n=n+1; if(n>1000) $fatal(1,"dictionary data"); end
  step(); dict_s_valid=0;
 end
 n=0;
 while(!dict_status_valid) begin step(); n=n+1; if(n>10000) $fatal(1,"dictionary status"); end
 if(dict_status_error!==0 || dict_loaded!==1 || dict_id!==id || dict_size!==size)
  $fatal(1,"dictionary load metadata");
 repeat(4) step();
 dict_status_ready=1; step(); dict_status_ready=0;
 $display("DICTIONARY_COLD_LOAD bytes=%0d cycles=%0d",size,cycles-begin_cycle);
 pinned_size=size;
end
endtask
task run_case(input integer number, input integer size, input integer codec,
 input integer decoding, input integer mode, input integer wide,
 input integer channel, input integer capacity, input reg [31:0] dictionary_id);
reg [63:0] n,operation_limit;
integer old_completions,k,offset,count;
reg [255:0] filename;
begin
 if(treset) begin
  rst_n=0; #1; reset_outputs(); repeat(3) step(); rst_n=1; #1;
  if(cmd_ready!==0 || dict_begin_ready!==0) $fatal(1,"early post-reset admission");
  repeat(3) step();
  if(pinned_size>0) load_dictionary(pinned_size,32'h12345678);
 end
 case_index=number; case_begin_cycle=cycles;
 expected_source=size; expected_capacity=capacity;
 expected_channel=channel; case_active=1; read_bytes=0; write_bytes=0;
 old_completions=completions;
 // Architecture's conservative operation bounds, plus fair DMA service.
 operation_limit=64'd64*((codec==6 ? pinned_size : 0)+2)*(BLOCK_BOUND+1)*(BLOCK_BOUND+1)
                 +64'd8192*(BLOCK_BOUND+1)+65536+64'd32*(size+capacity+1);
 read_fault=0; write_fault=0; first_fault=0; descriptors_complete=0;
 ns=size==0 ? 0 : (size<tsegments ? size:tsegments);
 nd=capacity<tsegments ? capacity:tsegments;
 for(i=0;i<MEM;i=i+1) begin source[i]=0; destination[i]=8'hcd; end
 if(size>0) begin
  $sformat(filename,"source-%0d.hex",number); $readmemh(filename,source,0,size-1);
 end
 cmd_channel=channel; sg_channel=channel; cmd_id=16'h5a5a;
 cmd_codec=codec; cmd_decompress=decoding; cmd_checksum_mode=mode; cmd_wide=wide;
 cmd_src_bytes=tdeclared; cmd_dst_capacity=capacity; cmd_src_segments=ns;
 cmd_dst_segments=nd; cmd_dict_id=dictionary_id; cmd_valid=1; #1;
 n=0;
 while(!cmd_ready) begin step(); n=n+1; if(n>1000) $fatal(1,"command timeout"); end
 command_edge=cycles+1; step(); cmd_valid=0;
 if(cmd_ready!==0) $fatal(1,"lane command admission remained open");
 if(!tp) begin
  offset=0;
  for(k=0;k<ns;k=k+1) begin
   count=k==ns-1 ? size-offset : 1+((random_state>>5)%(size-offset-(ns-k)+1));
   source_ends[k]=offset+count;
   send_descriptor(0,tbad==5 ? 0 : count+(tbad==1 && k==ns-1),
                   tbad==3 && k==0 ? 64'hffffffffffffffff : 64'h10000+offset);
   offset=offset+count;
  end
  offset=0;
  for(k=0;k<nd;k=k+1) begin
   count=k==nd-1 ? capacity-offset : 1+((random_state>>7)%(capacity-offset-(nd-k)+1));
   destination_ends[k]=offset+count;
   send_descriptor(1,count+(tbad==2 && k==nd-1),
                   tbad==4 && k==0 ? 64'hffffffffffffffff : 64'h100000+offset);
   offset=offset+count;
  end
  descriptors_complete=1;
 end
 n=0;
 while(!status_valid) begin
  step(); n=n+1;
  if(n>operation_limit) $fatal(1,"operation bound case=%0d",number);
 end
 repeat(7) step();
 status_ready=1; step(); status_ready=0;
 if(completions!=old_completions+1) $fatal(1,"missing completion");
 case_active=0; repeat(3) step();
end
endtask
initial begin
 input_fd=$fopen("seed.txt","r");
 tokens=$fscanf(input_fd,"%d",random_state); $fclose(input_fd);
 if(tokens!=1) $fatal(1,"missing seed");
 fd=$fopen("results.txt","w");
 if(!fd) $fatal(1,"cannot open results");
 rst_n=0;
 #0.001; reset_outputs();
 #11.999; rst_n=1;
 @(negedge clk); #1; repeat(3) step();
""" + "\n".join(calls) + r"""
 $fclose(fd);
 $display("COMPARED transactions=%0d cycles=%0d",completions,cycles);
 $finish;
end
endmodule
"""
