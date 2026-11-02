"""Generate self-checking public-pin benches into fresh evidence namespaces."""


def copy_bench(width, block=65536):
    return COPY.replace("@WIDTH@", str(width)).replace("@BLOCK@", str(block))


def top_bench(width, block, depth=16, parent=False):
    text = TOP.replace("@WIDTH@", str(width)).replace("@BLOCK@", str(block))
    text = text.replace("@DEPTH@", str(depth))
    if parent:
        text = text.replace(
            "bellows_l4_top #(.MAX_BLOCK_BYTES(BLOCK),.SG_DEPTH(DEPTH),.COPY_BYTES(WIDTH))",
            "bellows_l3_top #(.MAX_BLOCK_BYTES(BLOCK),.SG_DEPTH(DEPTH))")
        text = text.replace("@EXTENSION@", "")
        text = text.replace("@PARENT_TIE@", """
assign w_rd_req_valid=0, w_rd_req_channel=0, w_rd_req_addr=0, w_rd_req_bytes=0;
assign w_rd_rsp_ready=0, w_wr_req_valid=0, w_wr_req_channel=0, w_wr_req_addr=0;
assign w_wr_req_data=0, w_wr_req_strb=0, w_wr_rsp_ready=0;
""")
    else:
        text = text.replace("@EXTENSION@", """
 ,.cmd_wide(cmd_wide),.cmd_codec(cmd_codec),.w_rd_req_ready(w_rd_req_ready),
 .w_rd_rsp_valid(w_rd_rsp_valid),.w_rd_rsp_data(w_rd_rsp_data),
 .w_rd_rsp_error(w_rd_rsp_error),.w_wr_req_ready(w_wr_req_ready),
 .w_wr_rsp_valid(w_wr_rsp_valid),.w_wr_rsp_error(w_wr_rsp_error),
 .w_rd_req_valid(w_rd_req_valid),.w_rd_req_channel(w_rd_req_channel),
 .w_rd_req_addr(w_rd_req_addr),.w_rd_req_bytes(w_rd_req_bytes),
 .w_rd_rsp_ready(w_rd_rsp_ready),.w_wr_req_valid(w_wr_req_valid),
 .w_wr_req_channel(w_wr_req_channel),.w_wr_req_addr(w_wr_req_addr),
 .w_wr_req_data(w_wr_req_data),.w_wr_req_strb(w_wr_req_strb),
 .w_wr_rsp_ready(w_wr_rsp_ready)
""").replace("@PARENT_TIE@", "")
    return text


TOP = r"""
module tb;
localparam integer WIDTH=@WIDTH@, BLOCK=@BLOCK@, DEPTH=@DEPTH@;
reg clk=0;
always #5 clk=~clk;
reg rst_n;
reg cmd_valid=0, cmd_decompress=0, cmd_wide=0;
reg [1:0] cmd_channel=0, cmd_checksum_mode=0;
reg [15:0] cmd_id=0;
reg [31:0] cmd_src_bytes=0, cmd_dst_capacity=0;
reg [4:0] cmd_src_segments=0, cmd_dst_segments=0;
reg [2:0] cmd_codec=0;
wire cmd_ready;
reg sg_valid=0, sg_destination=0;
reg [1:0] sg_channel=0;
reg [63:0] sg_addr=0;
reg [31:0] sg_bytes=0;
wire sg_ready;
wire rd_req_valid, rd_rsp_ready, wr_req_valid, wr_rsp_ready;
wire [1:0] rd_req_channel, wr_req_channel;
wire [63:0] rd_req_addr, wr_req_addr;
wire [7:0] wr_req_data;
reg rd_req_ready=0, rd_rsp_valid=0, rd_rsp_error=0;
reg [7:0] rd_rsp_data=0;
reg wr_req_ready=0, wr_rsp_valid=0, wr_rsp_error=0;
wire w_rd_req_valid, w_rd_rsp_ready, w_wr_req_valid, w_wr_rsp_ready;
wire [1:0] w_rd_req_channel, w_wr_req_channel;
wire [63:0] w_rd_req_addr, w_wr_req_addr, w_wr_req_data;
wire [3:0] w_rd_req_bytes;
wire [7:0] w_wr_req_strb;
reg w_rd_req_ready=0, w_rd_rsp_valid=0, w_rd_rsp_error=0;
reg [63:0] w_rd_rsp_data=0;
reg w_wr_req_ready=0, w_wr_rsp_valid=0, w_wr_rsp_error=0;
wire status_valid, err_checksum_mismatch;
wire [1:0] status_channel;
wire [15:0] status_id;
wire [3:0] status_error;
wire [31:0] status_src_bytes, status_dst_bytes, status_checksum;
reg status_ready=0;
bellows_l4_top #(.MAX_BLOCK_BYTES(BLOCK),.SG_DEPTH(DEPTH),.COPY_BYTES(WIDTH)) dut (
 .clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_channel(cmd_channel),
 .cmd_id(cmd_id),.cmd_decompress(cmd_decompress),.cmd_checksum_mode(cmd_checksum_mode),
 .cmd_src_bytes(cmd_src_bytes),.cmd_dst_capacity(cmd_dst_capacity),
 .cmd_src_segments(cmd_src_segments),.cmd_dst_segments(cmd_dst_segments),.cmd_ready(cmd_ready),
 .sg_valid(sg_valid),.sg_channel(sg_channel),.sg_destination(sg_destination),
 .sg_addr(sg_addr),.sg_bytes(sg_bytes),.sg_ready(sg_ready),
 .rd_req_valid(rd_req_valid),.rd_req_channel(rd_req_channel),.rd_req_addr(rd_req_addr),
 .rd_req_ready(rd_req_ready),.rd_rsp_valid(rd_rsp_valid),.rd_rsp_data(rd_rsp_data),
 .rd_rsp_error(rd_rsp_error),.rd_rsp_ready(rd_rsp_ready),
 .wr_req_valid(wr_req_valid),.wr_req_channel(wr_req_channel),.wr_req_addr(wr_req_addr),
 .wr_req_data(wr_req_data),.wr_req_ready(wr_req_ready),.wr_rsp_valid(wr_rsp_valid),
 .wr_rsp_error(wr_rsp_error),.wr_rsp_ready(wr_rsp_ready),
 .status_valid(status_valid),.status_channel(status_channel),.status_id(status_id),
 .status_error(status_error),.status_src_bytes(status_src_bytes),
 .status_dst_bytes(status_dst_bytes),.status_checksum(status_checksum),
 .err_checksum_mismatch(err_checksum_mismatch),.status_ready(status_ready)
 @EXTENSION@ );
@PARENT_TIE@
reg [7:0] source[0:263171], expected[0:263171], destination[0:263171];
integer source_sizes[0:15], dest_sizes[0:15];
integer file, scan, test_id, total_cases=0, compared_bytes=0;
integer nsource, nexpected, capacity, expected_error, checksum_value;
integer channel_value, codec_value, decompress_value, wide_value, checksum_mode_value;
integer source_count, dest_count, stalls, seed, i, j, boundary, cursor, wait_count;
integer cycles=0, command_cycle, acked=0, consumed=0, issued_reads=0, issued_writes=0;
integer command_handshake, descriptor_handshake;
reg done_status=0, pending_read=0, pending_write=0, pending_read_wide, pending_write_wide;
integer read_index, read_count, write_index, write_count, read_delay, write_delay;
reg [63:0] read_data, write_data;
reg [31:0] random_state;
reg held_read=0, held_write=0, held_status=0;
reg [68:0] held_read_payload;
reg [136:0] held_write_payload;
reg [118:0] held_status_payload;
wire read_valid=rd_req_valid || w_rd_req_valid;
wire write_valid=wr_req_valid || w_wr_req_valid;
wire read_wide=w_rd_req_valid;
wire write_wide=w_wr_req_valid;
wire [63:0] request_read_addr=read_wide ? w_rd_req_addr : rd_req_addr;
wire [63:0] request_write_addr=write_wide ? w_wr_req_addr : wr_req_addr;
wire [1:0] request_read_channel=read_wide ? w_rd_req_channel : rd_req_channel;
wire [1:0] request_write_channel=write_wide ? w_wr_req_channel : wr_req_channel;
wire [3:0] request_read_count=read_wide ? w_rd_req_bytes : 4'd1;
wire [63:0] request_write_data=write_wide ? w_wr_req_data : {56'd0,wr_req_data};
wire [7:0] request_write_strobe=write_wide ? w_wr_req_strb : 8'd1;
wire read_ready=read_wide ? w_rd_req_ready : rd_req_ready;
wire write_ready=write_wide ? w_wr_req_ready : wr_req_ready;
string vectors;
task reset_outputs;
 begin
  if ({cmd_ready,sg_ready,rd_req_valid,rd_req_channel,rd_req_addr,rd_rsp_ready,
    wr_req_valid,wr_req_channel,wr_req_addr,wr_req_data,wr_rsp_ready,
    status_valid,status_channel,status_id,status_error,status_src_bytes,
    status_dst_bytes,status_checksum,err_checksum_mismatch,
    w_rd_req_valid,w_rd_req_channel,w_rd_req_addr,w_rd_req_bytes,w_rd_rsp_ready,
    w_wr_req_valid,w_wr_req_channel,w_wr_req_addr,w_wr_req_data,w_wr_req_strb,
    w_wr_rsp_ready} !== '0)
   $fatal(1,"ASSERT TOP RESET public outputs");
 end
endtask
always @(negedge clk) if (!rst_n) reset_outputs();
task tick;
 integer size, idx;
 begin
  @(posedge clk);
  command_handshake=cmd_valid && cmd_ready;
  descriptor_handshake=sg_valid && sg_ready;
  if(!rst_n) reset_outputs();
  else begin
   cycles=cycles+1;
   if ((^{cmd_ready,sg_ready,rd_req_valid,rd_rsp_ready,wr_req_valid,wr_rsp_ready,
     w_rd_req_valid,w_rd_rsp_ready,w_wr_req_valid,w_wr_rsp_ready,status_valid})
       === 1'bx) $fatal(1,"ASSERT TOP XZ control");
   if (held_read && {read_valid,read_wide,request_read_addr,request_read_count}
       !== {1'b1,held_read_payload})
    $fatal(1,"ASSERT TOP READ STABILITY case=%0d",test_id);
   if (held_write && {write_valid,write_wide,request_write_addr,
        request_write_data,request_write_strobe}
       !== {1'b1,held_write_payload})
    $fatal(1,"ASSERT TOP WRITE STABILITY case=%0d",test_id);
   if (held_status && {status_valid,status_channel,status_id,status_error,
       status_src_bytes,status_dst_bytes,status_checksum,err_checksum_mismatch}
       !== {1'b1,held_status_payload})
    $fatal(1,"ASSERT TOP STATUS STABILITY case=%0d",test_id);
   held_read=read_valid && !read_ready;
   held_read_payload={read_wide,request_read_addr,request_read_count};
   held_write=write_valid && !write_ready;
   held_write_payload={write_wide,request_write_addr,request_write_data,request_write_strobe};
   held_status=status_valid && !status_ready;
   held_status_payload={status_channel,status_id,status_error,status_src_bytes,
       status_dst_bytes,status_checksum,err_checksum_mismatch};
   if(command_handshake) command_cycle=cycles;
   if(rd_rsp_valid && rd_rsp_ready || w_rd_rsp_valid && w_rd_rsp_ready) begin
    if(!pending_read) $fatal(1,"ASSERT TOP unexpected read response");
    pending_read=0; consumed=consumed+read_count;
   end
   if(wr_rsp_valid && wr_rsp_ready || w_wr_rsp_valid && w_wr_rsp_ready) begin
    if(!pending_write) $fatal(1,"ASSERT TOP unexpected write response");
    pending_write=0;
    for(idx=0;idx<write_count;idx=idx+1) begin
     destination[write_index+idx]=write_data[idx*8 +: 8];
     if(expected_error==0 &&
       (write_index+idx>=nexpected ||
        write_data[idx*8 +: 8] !== expected[write_index+idx]))
      $fatal(1,"ASSERT TOP BYTE case=%0d channel=%0d codec=%0d index=%0d expected=%02h got=%02h",
        test_id,channel_value,codec_value,write_index+idx,
        expected[write_index+idx],write_data[idx*8 +: 8]);
    end
    acked=acked+write_count;
   end
   if(read_valid && read_ready) begin
    if(pending_read || rd_req_valid && w_rd_req_valid)
     $fatal(1,"ASSERT TOP outstanding read limit");
    if(read_wide !== wide_value[0] || request_read_channel !== channel_value[1:0])
     $fatal(1,"ASSERT TOP READ OWNERSHIP");
    if((^{request_read_addr,request_read_count})===1'bx ||
       request_read_count<1 || request_read_count>(read_wide ? WIDTH : 1) ||
       request_read_addr<4099 || request_read_addr+request_read_count>4099+nsource)
     $fatal(1,"ASSERT TOP READ BOUNDS case=%0d",test_id);
    read_index=request_read_addr-4099; read_count=request_read_count;
    boundary=0;
    for(idx=0;idx<source_count;idx=idx+1) begin
     boundary=boundary+source_sizes[idx];
     if(read_index<boundary && read_index+read_count>boundary)
      $fatal(1,"ASSERT TOP source descriptor crossing");
    end
    read_data=64'hdeadbeefcafebabe;
    for(idx=0;idx<read_count;idx=idx+1) read_data[idx*8 +: 8]=source[read_index+idx];
    pending_read=1; pending_read_wide=read_wide;
    read_delay=stalls ? random_state[3:1] : 0;
    issued_reads=issued_reads+1;
   end
   if(write_valid && write_ready) begin
    if(pending_write || wr_req_valid && w_wr_req_valid)
     $fatal(1,"ASSERT TOP outstanding write limit");
    if(write_wide !== wide_value[0] || request_write_channel !== channel_value[1:0])
     $fatal(1,"ASSERT TOP WRITE OWNERSHIP");
    size=0;
    for(idx=0;idx<8;idx=idx+1) if(request_write_strobe[idx]) size=size+1;
    if((^{request_write_addr,request_write_data,request_write_strobe})===1'bx ||
       size<1 || size>(write_wide ? WIDTH : 1) ||
       request_write_strobe !== ((8'd1<<size)-8'd1) ||
       (size<8 && (request_write_data>>(size*8))!==64'd0) ||
       request_write_addr<1048579 || request_write_addr+size>1048579+capacity)
     $fatal(1,"ASSERT TOP WRITE BOUNDS/TAIL case=%0d",test_id);
    write_index=request_write_addr-1048579; write_count=size;
    boundary=0;
    for(idx=0;idx<dest_count;idx=idx+1) begin
     boundary=boundary+dest_sizes[idx];
     if(write_index<boundary && write_index+size>boundary)
      $fatal(1,"ASSERT TOP destination descriptor crossing");
    end
    write_data=request_write_data;
    pending_write=1; pending_write_wide=write_wide;
    write_delay=stalls ? random_state[6:4] : 0;
    issued_writes=issued_writes+1;
   end
   if(status_valid && status_ready) begin
    if(pending_read || pending_write)
     $fatal(1,"ASSERT TOP completion before transaction settlement");
    if(status_error !== expected_error[3:0] || status_channel !== channel_value[1:0] ||
       status_id !== test_id[15:0] || status_dst_bytes !== acked ||
       status_src_bytes !== consumed ||
       (expected_error==0 && (status_checksum !== checksum_value || acked!=nexpected ||
                              consumed!=nsource)) ||
       err_checksum_mismatch !== (expected_error==7))
     $fatal(1,"ASSERT TOP STATUS case=%0d expected_error=%0d got=%0d src=%0d/%0d dst=%0d/%0d checksum=%08h/%08h",
      test_id,expected_error,status_error,status_src_bytes,nsource,
      status_dst_bytes,nexpected,status_checksum,checksum_value);
    if(expected_error==8 && (issued_reads!=0 || issued_writes!=0))
     $fatal(1,"ASSERT TOP invalid command traffic");
    if(expected_error==0) begin
     for(idx=0;idx<nexpected;idx=idx+1)
      if(destination[idx] !== expected[idx]) $fatal(1,"ASSERT TOP full output");
     compared_bytes=compared_bytes+nexpected;
    end
    done_status=1; total_cases=total_cases+1;
    $display("CASE %0d width=%0d codec=%0d wide=%0d channel=%0d checksum_mode=%0d error=%0d bytes=%0d cycles=%0d",
      test_id,WIDTH,codec_value,wide_value,channel_value,checksum_mode_value,
      status_error,nexpected,cycles-command_cycle+1);
   end
  end
  #1;
  random_state=(random_state<<1)^((random_state[31] ? 32'h00400007 : 0));
  rd_req_ready=!stalls || random_state[0];
  w_rd_req_ready=!stalls || random_state[1];
  wr_req_ready=!stalls || random_state[2];
  w_wr_req_ready=!stalls || random_state[3];
  status_ready=!stalls || random_state[4];
  rd_rsp_valid=pending_read && !pending_read_wide && read_delay==0;
  w_rd_rsp_valid=pending_read && pending_read_wide && read_delay==0;
  rd_rsp_data=read_data[7:0]; w_rd_rsp_data=read_data;
  wr_rsp_valid=pending_write && !pending_write_wide && write_delay==0;
  w_wr_rsp_valid=pending_write && pending_write_wide && write_delay==0;
  if(read_delay>0) read_delay=read_delay-1;
  if(write_delay>0) write_delay=write_delay-1;
  @(negedge clk);
 end
endtask
task descriptor;
 input integer destination_kind; input integer address; input integer bytes_count;
 begin
  sg_valid=1; sg_destination=destination_kind; sg_addr=address; sg_bytes=bytes_count;
  descriptor_handshake=0;
  while(!descriptor_handshake) tick();
  sg_valid=0;
 end
endtask
initial begin
 rst_n=0; random_state=17; read_delay=0; write_delay=0; stalls=0;
 #1; reset_outputs(); tick(); tick(); rst_n=1; tick();
 if(!$value$plusargs("vectors=%s",vectors)) $fatal(1,"missing vectors");
 file=$fopen(vectors,"r"); if(file==0) $fatal(1,"cannot open vectors");
 while(!$feof(file)) begin
  scan=$fscanf(file,"%d %d %d %d %d %d %d %d %d %d %h %d %d %d %d\n",
   test_id,channel_value,codec_value,decompress_value,wide_value,checksum_mode_value,
   nsource,nexpected,capacity,expected_error,checksum_value,
   source_count,dest_count,stalls,seed);
  if(scan==0 && $feof(file)) begin end
  else begin
   if(scan!=15) $fatal(1,"malformed vector record %0d",scan);
   for(i=0;i<source_count;i=i+1) begin
    scan=$fscanf(file,"%d",source_sizes[i]); if(scan!=1) $fatal(1,"source descriptor vector");
   end
   for(i=0;i<dest_count;i=i+1) begin
    scan=$fscanf(file,"%d",dest_sizes[i]); if(scan!=1) $fatal(1,"destination descriptor vector");
   end
   for(i=0;i<nsource;i=i+1) begin
    scan=$fscanf(file,"%h",source[i]); if(scan!=1) $fatal(1,"source byte vector");
   end
   for(i=0;i<nexpected;i=i+1) begin
    scan=$fscanf(file,"%h",expected[i]); if(scan!=1) $fatal(1,"expected byte vector");
   end
   for(i=0;i<capacity;i=i+1) destination[i]=8'ha5;
   acked=0; consumed=0; issued_reads=0; issued_writes=0; done_status=0;
   random_state=seed; command_cycle=cycles;
   cmd_valid=1; cmd_channel=channel_value; cmd_id=test_id;
   cmd_decompress=decompress_value; cmd_wide=wide_value; cmd_codec=codec_value;
   cmd_checksum_mode=checksum_mode_value; cmd_src_bytes=nsource; cmd_dst_capacity=capacity;
   cmd_src_segments=source_count; cmd_dst_segments=dest_count; sg_channel=channel_value;
   command_handshake=0;
   while(!command_handshake) tick();
   cmd_valid=0;
   if(expected_error!=8) begin
    cursor=4099;
    for(i=0;i<source_count;i=i+1) begin
     descriptor(0,cursor,source_sizes[i]); cursor=cursor+source_sizes[i];
    end
    cursor=1048579;
    for(i=0;i<dest_count;i=i+1) begin
     descriptor(1,cursor,dest_sizes[i]); cursor=cursor+dest_sizes[i];
    end
   end
   wait_count=0;
   while(!done_status) begin
    tick(); wait_count=wait_count+1;
    if(wait_count>30000000) $fatal(1,"ASSERT TOP finite work did not complete case=%0d",test_id);
   end
   tick(); tick();
  end
 end
 $fclose(file);
 if(total_cases==0) $fatal(1,"ASSERT TOP no cases");
 $display("SUMMARY TOP cases=%0d bytes=%0d",total_cases,compared_bytes);
 $finish;
end
endmodule
"""


COPY = r"""
module tb;
localparam integer WIDTH=@WIDTH@, BLOCK=@BLOCK@;
reg clk=0;
always #5 clk=~clk;
reg rst_n;
reg clear=0, op_valid=0, op_match=0, m_ready=0;
reg [63:0] op_data=0;
reg [3:0] op_count=0;
reg [15:0] op_offset=0;
wire op_ready, m_valid;
wire [63:0] m_data;
wire [3:0] m_count;
bellows_l4_copy_engine #(.COPY_BYTES(WIDTH),.MAX_BLOCK_BYTES(BLOCK)) dut (
 .clk(clk),.rst_n(rst_n),.clear(clear),.op_valid(op_valid),.op_match(op_match),
 .op_ready(op_ready),.op_data(op_data),.op_count(op_count),.op_offset(op_offset),
 .m_valid(m_valid),.m_ready(m_ready),.m_data(m_data),.m_count(m_count));
reg [7:0] history[0:65535];
reg [63:0] expected[0:20000];
integer counts[0:20000], accepted_cycle[0:20000];
integer head=0, tail=0, position=0, cycles=0, compared=0, compared_bytes=0;
integer i, j, repeat_index, count, distance, first_retire, last_retire;
integer before_bytes, steady_bytes;
reg [63:0] assembled, held_data;
reg [3:0] held_count;
reg held=0;
task reset_outputs;
 begin
  if ({op_ready,m_valid,m_data,m_count} !== 70'd0)
   $fatal(1,"ASSERT COPY RESET public outputs");
 end
endtask
always @(negedge clk) if (!rst_n) reset_outputs();
task tick;
 begin
  @(posedge clk);
  if (!rst_n) reset_outputs();
  else begin
   cycles=cycles+1;
   if ((m_valid !== 1'b0 && m_valid !== 1'b1) ||
       (op_ready !== 1'b0 && op_ready !== 1'b1))
    $fatal(1,"ASSERT COPY XZ handshake");
   if (held && {m_valid,m_data,m_count} !== {1'b1,held_data,held_count})
    $fatal(1,"ASSERT COPY STABILITY");
   held=m_valid && !m_ready;
   held_data=m_data; held_count=m_count;
   if (m_valid) begin
    if (head==tail || m_data !== expected[head] || m_count !== counts[head])
     $fatal(1,"ASSERT COPY DATA beat=%0d expected=%016h got=%016h count=%0d/%0d",
       head,expected[head],m_data,counts[head],m_count);
    if (cycles<accepted_cycle[head]+2)
     $fatal(1,"ASSERT COPY LATENCY earliest retirement E+2");
   end
   if (m_valid && m_ready) begin
    if (first_retire<0) first_retire=cycles;
    last_retire=cycles;
    compared=compared+1; compared_bytes=compared_bytes+m_count; head=head+1;
   end
   if (op_valid && op_ready) begin
    assembled=0;
    for (j=0;j<op_count;j=j+1) begin
     if (op_match) assembled[j*8 +: 8]=history[(position-op_offset)&65535];
     else assembled[j*8 +: 8]=op_data[j*8 +: 8];
     history[position&65535]=assembled[j*8 +: 8]; position=position+1;
    end
    expected[tail]=assembled; counts[tail]=op_count; accepted_cycle[tail]=cycles;
    tail=tail+1;
   end
  end
  #1;
  if (rst_n && tail>head && cycles==accepted_cycle[head] && m_valid !== 1'b0)
   $fatal(1,"ASSERT COPY LATENCY request must not bypass first stage");
  @(negedge clk);
 end
endtask
task send;
 input match_kind; input integer n; input integer offset_value; input [63:0] data;
 integer done;
 begin
  op_valid=1; op_match=match_kind; op_count=n; op_offset=offset_value; op_data=data;
  done=0;
  while (!done) begin
   done=op_ready; tick();
  end
  op_valid=0;
 end
endtask
task drain;
 begin
  op_valid=0; m_ready=1;
  while(head<tail) tick();
  tick();
  if (m_valid !== 1'b0) $fatal(1,"ASSERT COPY duplicate output");
 end
endtask
initial begin
 rst_n=0;
 first_retire=-1; last_retire=-1;
 #1; reset_outputs();
 tick(); tick(); rst_n=1; tick();
 clear=1; op_valid=1; op_count=1; tick();
 if (op_ready !== 1'b0) $fatal(1,"ASSERT COPY clear acceptance");
 clear=0; op_valid=0; m_ready=1; tick();
 for (i=0;i<(BLOCK<32 ? BLOCK : 32);i=i+1)
  send(0,1,0,64'h00000000000000a0+i);
 drain();
 if (BLOCK>32) begin
  for (repeat_index=0;repeat_index<5;repeat_index=repeat_index+1) begin
   case(repeat_index) 0:distance=0; 1:distance=1; 2:distance=3;
    3:distance=7; default:distance=16; endcase
   first_retire=-1; before_bytes=compared_bytes;
   for(i=0;i<4096/WIDTH;i=i+1)
    send(distance!=0,WIDTH,distance,64'h0807060504030201+i);
   drain();
   steady_bytes=compared_bytes-before_bytes;
   if (steady_bytes!=4096 ||
       100*steady_bytes < 99*WIDTH*(last_retire-first_retire+1))
    $fatal(1,"ASSERT COPY THROUGHPUT bytes=%0d cycles=%0d width=%0d offset=%0d",
      steady_bytes,last_retire-first_retire+1,WIDTH,distance);
   $display("MEASURE COPY width=%0d offset=%0d bytes=%0d cycles=%0d",
     WIDTH,distance,steady_bytes,last_retire-first_retire+1);
  end
 end
 // Directed stalls and short tails exercise the same reference scoreboard.
 if (position+32<BLOCK) begin
  m_ready=0; send(0,1,0,64'h55); send(1,WIDTH,1,0);
  op_valid=0;
  repeat(9) tick();
  m_ready=1; drain();
  for(i=1;i<WIDTH;i=i+1) send(1,i,3,0);
  drain();
 end
 if(compared==0 || compared_bytes==0)
  $fatal(1,"ASSERT COPY empty comparison ledger");
 $display("SUMMARY COPY width=%0d block=%0d beats=%0d bytes=%0d",
   WIDTH,BLOCK,compared,compared_bytes);
 $finish;
end
endmodule
"""
