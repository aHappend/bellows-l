"""Generated, public-pin-only SystemVerilog DMA environment.

The same transactor is compiled by Icarus for compact smoke and Verilator for
the parameter/seed matrix. No hierarchical DUT references are used.
"""

BENCH = r"""
module tb;
  localparam integer B = @BLOCK@;
  localparam integer SG = @SG@;
  localparam integer STORE = 2*B+4096;
  reg clk=0;
  reg rst_n;
  always #5 clk=~clk;
  reg cmd_valid=0;
  reg [1:0] cmd_channel=0;
  reg [15:0] cmd_id=0;
  reg cmd_decompress=0;
  reg [1:0] cmd_checksum_mode=0;
  reg [31:0] cmd_src_bytes=0, cmd_dst_capacity=0;
  reg [4:0] cmd_src_segments=0, cmd_dst_segments=0;
  wire cmd_ready;
  reg sg_valid=0;
  reg [1:0] sg_channel=0;
  reg sg_destination=0;
  reg [63:0] sg_addr=0;
  reg [31:0] sg_bytes=0;
  wire sg_ready;
  wire rd_req_valid;
  wire [1:0] rd_req_channel;
  wire [63:0] rd_req_addr;
  reg rd_req_ready=0;
  reg rd_rsp_valid=0;
  reg [7:0] rd_rsp_data=0;
  reg rd_rsp_error=0;
  wire rd_rsp_ready;
  wire wr_req_valid;
  wire [1:0] wr_req_channel;
  wire [63:0] wr_req_addr;
  wire [7:0] wr_req_data;
  reg wr_req_ready=0;
  reg wr_rsp_valid=0, wr_rsp_error=0;
  wire wr_rsp_ready;
  wire status_valid;
  wire [1:0] status_channel;
  wire [15:0] status_id;
  wire [3:0] status_error;
  wire [31:0] status_src_bytes, status_dst_bytes, status_checksum;
  wire err_checksum_mismatch;
  reg status_ready=0;
  bellows_l3_top #(.MAX_BLOCK_BYTES(B), .SG_DEPTH(SG)) dut (.*);
  wire [265:0] all_outputs = {
    cmd_ready,sg_ready,rd_req_valid,rd_req_channel,rd_req_addr,rd_rsp_ready,
    wr_req_valid,wr_req_channel,wr_req_addr,wr_req_data,wr_rsp_ready,
    status_valid,status_channel,status_id,status_error,status_src_bytes,
    status_dst_bytes,status_checksum,err_checksum_mismatch};

  integer inp, outp, batches, batch, ch, k, direction, result, word;
  reg [63:0] scan_address;
  reg [31:0] scan_length;
  string case_path, result_path;
  integer seed, cycle=0, batch_start, completions=0;
  integer op[0:3], mode[0:3], ids[0:3], lengths[0:3], capacities[0:3];
  integer ns[0:3], nd[0:3], error_expected[0:3], bad_read[0:3], bad_write[0:3];
  integer declared_ns[0:3], declared_nd[0:3], reject_command[0:3];
  integer input_length[0:3];
  reg [63:0] sa[0:3][0:15], da[0:3][0:15];
  reg [31:0] sl[0:3][0:15], dl[0:3][0:15];
  reg [7:0] source[0:3][0:STORE-1], destination[0:3][0:STORE-1];
  reg [7:0] captured[0:3][0:STORE-1];
  integer ri[0:3], ro[0:3], wi[0:3], wo[0:3];
  integer requested_reads[0:3], consumed_reads[0:3];
  integer requested_writes[0:3], acknowledged_writes[0:3];
  integer cmd_cycle[0:3], desc_cycle[0:3], ack_cycle[0:3];
  reg active[0:3], completed[0:3];
  reg rbusy=0, wbusy=0;
  integer r_owner, w_owner, r_due, w_due, r_index, w_index;
  reg [7:0] w_data;
  reg [63:0] w_address;
  reg r_error, w_error;
  integer rd_window=-1, wr_window=-1, st_window=-1;
  integer rd_stall=0, wr_stall=0, st_stall=0;
  integer max_rd_stall=0, max_wr_stall=0, max_st_stall=0;
  integer switches=0, previous_read=-1, four_active=0, response_gaps=0;
  integer source_cross[0:1], dest_cross[0:1], single_segments=0, depth16=0;
  integer reset_probes=0, reset_collect=0, reset_processing=0, reset_status=0;
  integer total_commands=0, total_status=0, total_aborted=0;
  reg record_enabled=1;
  reg prev_rd_stalled=0, prev_wr_stalled=0, prev_status_stalled=0;
  reg [65:0] held_rd;
  reg [73:0] held_wr;
  reg [118:0] held_status;

  task automatic checked_scan(input integer count);
    if (result != count) $fatal(1,"HARNESS input scan expected %0d got %0d",count,result);
  endtask

  task automatic check_reset;
    if (all_outputs !== 266'd0)
      $fatal(1,"RESET nonzero/X public outputs at t=%0t: %h",$time,all_outputs);
  endtask

  always @(posedge clk or negedge clk) begin
    if (rst_n === 1'b0) check_reset();
  end

  always @(posedge clk) begin
    cycle=cycle+1;
    if (rst_n) begin
      if ((^all_outputs) === 1'bx)
        $fatal(1,"ACTIVE_XZ cycle=%0d outputs=%h",cycle,all_outputs);
      if (err_checksum_mismatch !== (status_valid && status_error==7))
        $fatal(1,"CHECKSUM_FLAG cycle=%0d",cycle);
      if (prev_rd_stalled && {rd_req_channel,rd_req_addr} !== held_rd)
        $fatal(1,"READ_STABILITY cycle=%0d",cycle);
      if (prev_rd_stalled && !rd_req_valid) $fatal(1,"READ_VALID_DROPPED");
      if (prev_wr_stalled && {wr_req_channel,wr_req_addr,wr_req_data} !== held_wr)
        $fatal(1,"WRITE_STABILITY cycle=%0d",cycle);
      if (prev_wr_stalled && !wr_req_valid) $fatal(1,"WRITE_VALID_DROPPED");
      if (prev_status_stalled &&
          {status_channel,status_id,status_error,status_src_bytes,status_dst_bytes,
           status_checksum,err_checksum_mismatch} !== held_status)
        $fatal(1,"STATUS_STABILITY cycle=%0d",cycle);
      if (prev_status_stalled && !status_valid) $fatal(1,"STATUS_VALID_DROPPED");
      prev_rd_stalled=rd_req_valid && !rd_req_ready;
      prev_wr_stalled=wr_req_valid && !wr_req_ready;
      prev_status_stalled=status_valid && !status_ready;
      held_rd={rd_req_channel,rd_req_addr};
      held_wr={wr_req_channel,wr_req_addr,wr_req_data};
      held_status={status_channel,status_id,status_error,status_src_bytes,
                   status_dst_bytes,status_checksum,err_checksum_mismatch};
      if (prev_rd_stalled) rd_stall=rd_stall+1; else rd_stall=0;
      if (prev_wr_stalled) wr_stall=wr_stall+1; else wr_stall=0;
      if (prev_status_stalled) st_stall=st_stall+1; else st_stall=0;
      if (rd_stall>max_rd_stall) max_rd_stall=rd_stall;
      if (wr_stall>max_wr_stall) max_wr_stall=wr_stall;
      if (st_stall>max_st_stall) max_st_stall=st_stall;
      if (active[0] && active[1] && active[2] && active[3]) four_active=1;
      if (cmd_valid && cmd_ready) begin
        if (active[cmd_channel]) $fatal(1,"COMMAND_BUSY");
        active[cmd_channel]=1;
        cmd_cycle[cmd_channel]=cycle;
        total_commands=total_commands+1;
      end
      if (sg_valid && sg_ready) begin
        if (cycle<=cmd_cycle[sg_channel]) $fatal(1,"DESCRIPTOR_BYPASS");
        desc_cycle[sg_channel]=cycle;
      end
      if (rd_req_valid && rd_req_ready) begin
        if (rbusy) $fatal(1,"READ_OUTSTANDING");
        if (!active[rd_req_channel] || completed[rd_req_channel])
          $fatal(1,"READ_INACTIVE channel=%0d",rd_req_channel);
        if (cycle<desc_cycle[rd_req_channel]+3)
          $fatal(1,"DESCRIPTOR_DMA_LATENCY");
        if (requested_reads[rd_req_channel]>=input_length[rd_req_channel])
          $fatal(1,"READ_BEYOND_SOURCE");
        if (rd_req_addr !== sa[rd_req_channel][ri[rd_req_channel]]+
                            ro[rd_req_channel])
          $fatal(1,"READ_ADDRESS ch=%0d index=%0d got=%h expected=%h",
                 rd_req_channel,requested_reads[rd_req_channel],rd_req_addr,
                 sa[rd_req_channel][ri[rd_req_channel]]+ro[rd_req_channel]);
        if (previous_read>=0 && previous_read!=rd_req_channel)
          switches=switches+1;
        previous_read=rd_req_channel;
        rbusy=1; r_owner=rd_req_channel;
        r_index=requested_reads[r_owner];
        r_error=(r_index==bad_read[r_owner]);
        r_due=cycle+1+((r_index+seed)%5);
        if (r_due>cycle+1) response_gaps=response_gaps+1;
        requested_reads[r_owner]=requested_reads[r_owner]+1;
        if (ro[r_owner]+1==sl[r_owner][ri[r_owner]]) begin
          if (ri[r_owner]+1<ns[r_owner]) source_cross[op[r_owner]]=source_cross[op[r_owner]]+1;
          if (sl[r_owner][ri[r_owner]]==1) single_segments=single_segments+1;
          ri[r_owner]=ri[r_owner]+1; ro[r_owner]=0;
        end else ro[r_owner]=ro[r_owner]+1;
      end
      if (wr_req_valid && wr_req_ready) begin
        if (wbusy) $fatal(1,"WRITE_OUTSTANDING");
        if (!active[wr_req_channel] || completed[wr_req_channel])
          $fatal(1,"WRITE_INACTIVE");
        if (requested_writes[wr_req_channel]>=capacities[wr_req_channel])
          $fatal(1,"WRITE_BEYOND_CAPACITY");
        if (wr_req_addr !== da[wr_req_channel][wi[wr_req_channel]]+
                            wo[wr_req_channel])
          $fatal(1,"WRITE_ADDRESS ch=%0d index=%0d got=%h expected=%h",
                 wr_req_channel,requested_writes[wr_req_channel],wr_req_addr,
                 da[wr_req_channel][wi[wr_req_channel]]+wo[wr_req_channel]);
        wbusy=1; w_owner=wr_req_channel;
        w_index=requested_writes[w_owner]; w_data=wr_req_data;
        w_address=wr_req_addr;
        w_error=(w_index==bad_write[w_owner]);
        w_due=cycle+1+((w_index+seed)%7);
        requested_writes[w_owner]=requested_writes[w_owner]+1;
        if (wo[w_owner]+1==dl[w_owner][wi[w_owner]]) begin
          if (wi[w_owner]+1<nd[w_owner]) dest_cross[op[w_owner]]=dest_cross[op[w_owner]]+1;
          if (dl[w_owner][wi[w_owner]]==1) single_segments=single_segments+1;
          wi[w_owner]=wi[w_owner]+1; wo[w_owner]=0;
        end else wo[w_owner]=wo[w_owner]+1;
      end
      if (rd_rsp_valid && rd_rsp_ready) begin
        if (!rbusy) $fatal(1,"UNSOLICITED_READ");
        consumed_reads[r_owner]=consumed_reads[r_owner]+1;
        rbusy=0;
      end
      if (wr_rsp_valid && wr_rsp_ready) begin
        if (!wbusy) $fatal(1,"UNSOLICITED_WRITE");
        ack_cycle[w_owner]=cycle;
        if (!w_error) begin
          if (w_address<da[w_owner][0] ||
              w_address-da[w_owner][0]>=STORE) $fatal(1,"HARNESS destination storage");
          destination[w_owner][w_address-da[w_owner][0]]=w_data;
          captured[w_owner][acknowledged_writes[w_owner]]=w_data;
          acknowledged_writes[w_owner]=acknowledged_writes[w_owner]+1;
        end
        wbusy=0;
      end
      if (status_valid && status_ready) begin
        if (!active[status_channel] || completed[status_channel])
          $fatal(1,"DUPLICATE_STATUS");
        if ((rbusy && r_owner==status_channel) ||
            (wbusy && w_owner==status_channel)) $fatal(1,"EARLY_STATUS");
        if (acknowledged_writes[status_channel]!=0 &&
            cycle<ack_cycle[status_channel]+2) $fatal(1,"STATUS_LATENCY");
        if (status_src_bytes !== consumed_reads[status_channel] ||
            status_dst_bytes !== acknowledged_writes[status_channel])
          $fatal(1,"COMPLETION_COUNTS ch=%0d src=%0d/%0d dst=%0d/%0d",
                 status_channel,status_src_bytes,consumed_reads[status_channel],
                 status_dst_bytes,acknowledged_writes[status_channel]);
        if (record_enabled) begin
          $fwrite(outp,"FRAME %0d %0d %0d %0d %0d %0d %08h ",
                batch,status_channel,status_id,status_error,status_src_bytes,
                status_dst_bytes,status_checksum);
          for (integer q=0;q<acknowledged_writes[status_channel];q=q+1)
            $fwrite(outp,"%02h",captured[status_channel][q]);
          $fwrite(outp,"\n");
        end
        active[status_channel]=0; completed[status_channel]=1;
        total_status=total_status+1;
        completions=completions+1;
      end
      if (cycle-batch_start>@CYCLES@) $fatal(1,"CYCLE_BOUND batch=%0d",batch);
      @COMPACT_BOUND@
    end
  end

  always @(negedge clk) begin
    if (!rst_n) begin
      rd_req_ready=0; wr_req_ready=0; status_ready=0;
      rd_rsp_valid=0; wr_rsp_valid=0;
    end else begin
      if (rd_window==-1 && rd_req_valid) rd_window=cycle+17;
      if (wr_window==-1 && wr_req_valid) wr_window=cycle+17;
      if (st_window==-1 && status_valid) st_window=cycle+17;
      rd_req_ready=(rd_window>=0 && cycle>=rd_window && (cycle+seed)%11!=0);
      wr_req_ready=(wr_window>=0 && cycle>=wr_window && (cycle+seed)%13!=0);
      status_ready=(st_window>=0 && cycle>=st_window && (cycle+seed)%7!=0);
      rd_rsp_valid=rbusy && cycle>=r_due;
      rd_rsp_data=rbusy ? source[r_owner][r_index] : 0;
      rd_rsp_error=rbusy && r_error;
      wr_rsp_valid=wbusy && cycle>=w_due;
      wr_rsp_error=wbusy && w_error;
    end
  end

  task automatic send_command(input integer lane);
    @(negedge clk);
    cmd_valid=1; cmd_channel=lane; cmd_id=ids[lane];
    cmd_decompress=op[lane]; cmd_checksum_mode=mode[lane];
    cmd_src_bytes=lengths[lane]; cmd_dst_capacity=capacities[lane];
    cmd_src_segments=declared_ns[lane]; cmd_dst_segments=declared_nd[lane];
    do @(posedge clk); while (!cmd_ready);
    @(negedge clk); cmd_valid=0;
  endtask

  task automatic send_segment(input integer lane, input integer dest,
                               input integer number);
    @(negedge clk);
    sg_valid=1; sg_channel=lane; sg_destination=dest;
    sg_addr=dest ? da[lane][number] : sa[lane][number];
    sg_bytes=dest ? dl[lane][number] : sl[lane][number];
    do @(posedge clk); while (!sg_ready);
    @(negedge clk); sg_valid=0;
  endtask

  task automatic issue_batch;
    for (integer lane=0;lane<4;lane=lane+1) send_command(lane);
    for (integer seg=0;seg<16;seg=seg+1)
      for (integer lane=0;lane<4;lane=lane+1)
        if (!reject_command[lane]) begin
          if (seg<ns[lane]) send_segment(lane,0,seg);
          if (seg<nd[lane]) send_segment(lane,1,seg);
        end
  endtask

  task automatic clear_environment;
    for (integer lane=0;lane<4;lane=lane+1) begin
      ri[lane]=0; ro[lane]=0; wi[lane]=0; wo[lane]=0;
      requested_reads[lane]=0; consumed_reads[lane]=0;
      requested_writes[lane]=0; acknowledged_writes[lane]=0;
      active[lane]=0; completed[lane]=0; cmd_cycle[lane]=0;
      desc_cycle[lane]=0; ack_cycle[lane]=0;
      for (integer address=0;address<STORE;address=address+1)
        destination[lane][address]=8'ha5;
    end
    completions=0;
  endtask

  task automatic reset_epoch(input integer stage);
    @(negedge clk);
    if (stage==1) begin
      if (!active[0] || requested_reads[0]!=0) $fatal(1,"RESET_COLLECTION_PRECONDITION");
      reset_collect=reset_collect+1;
    end
    if (stage==2) begin
      if (!rbusy && !wbusy) $fatal(1,"RESET_PROCESSING_PRECONDITION");
      reset_processing=reset_processing+1;
    end
    if (stage==3) begin
      if (!status_valid || status_ready) $fatal(1,"RESET_STATUS_PRECONDITION");
      reset_status=reset_status+1;
    end
    for (integer lane=0;lane<4;lane=lane+1)
      if (active[lane]) total_aborted=total_aborted+1;
    #1;
    rst_n=0; cmd_valid=0; sg_valid=0; rd_rsp_valid=0; wr_rsp_valid=0;
    rd_req_ready=0; wr_req_ready=0; status_ready=0;
    rbusy=0; wbusy=0; prev_rd_stalled=0; prev_wr_stalled=0; prev_status_stalled=0;
    rd_window=-1; wr_window=-1; st_window=-1;
    clear_environment();
    #1; check_reset();
    repeat(3) @(negedge clk);
    #1; rst_n=1;
  endtask

  initial begin
    rst_n=0;
`ifdef VERILATOR
    #1;
`else
    #0;
`endif
    check_reset();
    if (!$value$plusargs("case=%s",case_path)) $fatal(1,"HARNESS missing case");
    if (!$value$plusargs("result=%s",result_path)) $fatal(1,"HARNESS missing result");
    result=$value$plusargs("resets=%d",reset_probes);
    inp=$fopen(case_path,"r"); outp=$fopen(result_path,"w");
    if (!inp || !outp) $fatal(1,"HARNESS file open");
    result=$fscanf(inp,"%d %d",batches,seed); checked_scan(2);
    source_cross[0]=0; source_cross[1]=0; dest_cross[0]=0; dest_cross[1]=0;
    repeat(3) @(negedge clk);
    #1; rst_n=1;
    for (batch=0;batch<batches;batch=batch+1) begin
      batch_start=cycle; completions=0;
      for (ch=0;ch<4;ch=ch+1) begin
        result=$fscanf(inp,"%d %d %d %d %d %d %d %d %d %d %d %d %d %d",
                       ids[ch],op[ch],mode[ch],lengths[ch],capacities[ch],
                       ns[ch],nd[ch],error_expected[ch],bad_read[ch],bad_write[ch],
                       input_length[ch],declared_ns[ch],declared_nd[ch],
                       reject_command[ch]); checked_scan(14);
        if (input_length[ch]>=STORE ||
            (capacities[ch]>=STORE && error_expected[ch]!=8))
          $fatal(1,"HARNESS storage limit");
        if (ns[ch]>16 || nd[ch]>16) $fatal(1,"HARNESS descriptor storage limit");
        if (ns[ch]==16 || nd[ch]==16) depth16=depth16+1;
        for (k=0;k<ns[ch];k=k+1) begin
          result=$fscanf(inp,"%h %d",scan_address,scan_length); checked_scan(2);
          sa[ch][k]=scan_address; sl[ch][k]=scan_length;
        end
        for (k=0;k<nd[ch];k=k+1) begin
          result=$fscanf(inp,"%h %d",scan_address,scan_length); checked_scan(2);
          da[ch][k]=scan_address; dl[ch][k]=scan_length;
        end
        for (k=0;k<input_length[ch];k=k+1) begin
          result=$fscanf(inp,"%h",word); checked_scan(1); source[ch][k]=word;
        end
        for (k=0;k<STORE;k=k+1) destination[ch][k]=8'ha5;
        ri[ch]=0; ro[ch]=0; wi[ch]=0; wo[ch]=0;
        requested_reads[ch]=0; consumed_reads[ch]=0;
        requested_writes[ch]=0; acknowledged_writes[ch]=0;
        active[ch]=0; completed[ch]=0; cmd_cycle[ch]=0; desc_cycle[ch]=0;
        ack_cycle[ch]=0;
      end
      if (batch==0 && reset_probes) begin
        record_enabled=0;
        for (ch=0;ch<4;ch=ch+1) send_command(ch);
        send_segment(0,1,0);
        reset_epoch(1);
        issue_batch();
        wait(rbusy || wbusy);
        reset_epoch(2);
        issue_batch();
        wait(status_valid && !status_ready);
        reset_epoch(3);
        record_enabled=1;
      end
      issue_batch();
      wait(completions==4);
      @(negedge clk);
      for (ch=0;ch<4;ch=ch+1) begin
        for (k=0;k<STORE;k=k+1) begin
          word=0;
          for (integer seg=0;seg<nd[ch];seg=seg+1)
            if (k>=da[ch][seg]-da[ch][0] &&
                k<da[ch][seg]-da[ch][0]+dl[ch][seg]) word=1;
          if (!word && destination[ch][k] !== 8'ha5)
            $fatal(1,"GUARD_CHANGED channel=%0d offset=%0d",ch,k);
        end
      end
    end
    repeat(8) @(negedge clk);
    if (total_commands!=total_status+total_aborted) $fatal(1,"COMMAND_CONSERVATION");
    $fwrite(outp,"COVER %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
            four_active,switches,max_rd_stall,max_wr_stall,max_st_stall,response_gaps,
            source_cross[0],source_cross[1],dest_cross[0],dest_cross[1],
            single_segments,depth16,reset_collect,reset_processing,reset_status);
    $fclose(inp); $fclose(outp);
    $display("SIMULATION_COMPLETE batches=%0d cycles=%0d",batches,cycle);
    $finish;
  end
endmodule
"""


def bench(block, sg, compact=False):
    return (BENCH.replace("@BLOCK@", str(block)).replace("@SG@", str(sg))
            .replace("@COMPACT_BOUND@", 'if (cycle>500000) $fatal(1,"SMOKE_CYCLE_LIMIT");'
                     if compact else "")
            .replace("@CYCLES@", str(450000 if compact else max(500000, block * 200))))
