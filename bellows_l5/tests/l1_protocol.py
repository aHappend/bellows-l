"""Concurrent four-lane DMA scoreboard and public dictionary/reset experiments."""

from l1_transport import INPUTS, OUTPUTS, top_testbench


def concurrent_testbench(cases, geometry, directory, seed=17, dictionary=b""):
    if len(cases) != 4 or {c.channel for c in cases} != set(range(4)):
        raise ValueError("concurrency fixture needs exactly one transaction per lane")
    cases = sorted(cases, key=lambda c: c.channel)
    text = top_testbench(cases, geometry, directory, seed, dictionary)
    start = text.index("always @(posedge clk) begin\n cycles")
    end = text.index("task step;", start)
    monitor = text[start:end]
    monitor = monitor.replace("read_bytes", "lane_reads[r_owner]")
    monitor = monitor.replace("write_bytes", "lane_writes[w_owner]")
    monitor = monitor.replace("r_pending || !case_active", "r_pending || !active[r_owner]")
    monitor = monitor.replace("w_pending || !case_active", "w_pending || !active[w_owner]")
    monitor = monitor.replace("!case_active || r_pending || w_pending",
                              "!active[status_channel] || r_pending || w_pending")
    # Other lanes may have outstanding responses when this lane completes.
    monitor = monitor.replace("!active[status_channel] || r_pending || w_pending",
                              "!active[status_channel] || (r_pending && r_owner==status_channel)"
                              " || (w_pending && w_owner==status_channel)")
    monitor = monitor.replace('if (cycles<descriptor_edge+2)',
                              'if (cycles<descriptor_edges[r_owner]+2)')
    monitor = monitor.replace(
        'if ((r_wide ? w_rd_req_channel : rd_req_channel)!==expected_channel[1:0])\n'
        '      $fatal(1,"read channel misassociation");', "")
    monitor = monitor.replace(
        'if ((w_wide ? w_wr_req_channel : wr_req_channel)!==expected_channel[1:0])\n'
        '      $fatal(1,"write channel misassociation");', "")
    monitor = monitor.replace('    if(first_fault) $fatal(1,"read issued',
                              "    r_owner=w_rd_req_valid ? w_rd_req_channel : rd_req_channel;\n"
                              '    if(first_fault) $fatal(1,"read issued')
    monitor = monitor.replace('    if(first_fault) $fatal(1,"write issued',
                              "    w_owner=w_wr_req_valid ? w_wr_req_channel : wr_req_channel;\n"
                              '    if(first_fault) $fatal(1,"write issued')
    monitor = monitor.replace("-64'h10000;", "-64'h10000-r_owner*64'h100000;")
    monitor = monitor.replace("-64'h100000;", "-64'h800000-w_owner*64'h100000;")
    monitor = monitor.replace("expected_source", "sizes[r_owner]")
    monitor = monitor.replace("expected_capacity", "capacities[w_owner]")
    monitor = monitor.replace('!descriptors_complete) $fatal(1,"read before',
                              '!descriptor_done[r_owner]) $fatal(1,"read before')
    monitor = monitor.replace('!descriptors_complete) $fatal(1,"write before',
                              '!descriptor_done[w_owner]) $fatal(1,"write before')
    monitor = monitor.replace("source[age+j]", "sources[r_owner][age+j]")
    monitor = monitor.replace("destination[age+j]", "destinations[w_owner][age+j]")
    monitor = monitor.replace("status_channel!==expected_channel[1:0] || ", "")
    monitor = monitor.replace('    if(cmd_ready!==0) $fatal(1,"same-edge speculative lane reuse");', "")
    monitor = monitor.replace("status_src_bytes!==lane_reads[r_owner]",
                              "status_src_bytes!==lane_reads[status_channel]")
    monitor = monitor.replace("status_dst_bytes!==lane_writes[w_owner]",
                              "status_dst_bytes!==lane_writes[status_channel]")
    monitor = monitor.replace("case_index,status_error", "status_channel,status_error")
    monitor = monitor.replace("destination[j]", "destinations[status_channel][j]")
    monitor = monitor.replace("    completions=completions+1;",
                              "    if(done[status_channel]) $fatal(1,\"duplicate completion\");\n"
                              "    done[status_channel]=1; active[status_channel]=0;\n"
                              "    completions=completions+1;")
    monitor = monitor.replace(" end\nend\n\n", """  if(active[0] && active[1] && active[2] && active[3])
    four_active=four_active+1;
 end
end

""")
    extra = """
reg [7:0] sources[0:3][0:MEM-1],destinations[0:3][0:MEM-1];
integer sizes[0:3],capacities[0:3],descriptor_edges[0:3];
integer descriptor_done[0:3];
integer lane_reads[0:3],lane_writes[0:3],active[0:3],done[0:3];
integer r_owner=0,w_owner=0,four_active=0,lane=0,st=0;
"""
    text = text[:start] + extra + monitor + text[end:]
    initial_start = text.index("initial begin\n input_fd=")
    preamble_end = text.index(' input_fd=$fopen("dictionary-size.txt"', initial_start)
    footer = text.index(' input_fd=$fopen("cases.txt"', preamble_end)
    body = text[initial_start:preamble_end] + text[preamble_end:footer]
    body += """
 ns=1; nd=1; tfault=0;
"""
    for lane, case in enumerate(cases):
        body += f"""
 sizes[{lane}]={len(case.source)}; capacities[{lane}]={case.capacity};
 lane_reads[{lane}]=0; lane_writes[{lane}]=0; active[{lane}]=1; done[{lane}]=0;
 descriptor_done[{lane}]=0;
 $readmemh("source-{lane}.hex",source,0,{len(case.source)-1});
 for(i=0;i<{len(case.source)};i=i+1) sources[{lane}][i]=source[i];
 cmd_channel={lane}; cmd_id=16'h5a5a; cmd_codec={case.codec};
 cmd_decompress={case.decompress}; cmd_wide={case.wide}; cmd_checksum_mode={case.mode};
 cmd_dict_id=32'h{case.dictionary_id:08x};
 cmd_src_bytes={len(case.source)}; cmd_dst_capacity={case.capacity};
 cmd_src_segments=1; cmd_dst_segments=1; cmd_valid=1; #1;
 st=0; while(!cmd_ready) begin step(); st=st+1;
  if(st>1000) $fatal(1,"concurrent command admission"); end
 step(); cmd_valid=0;
"""
    # Admit all commands before offering descriptors, guaranteeing real overlap.
    body += """
 dict_begin_valid=1; dict_begin_id=111; dict_begin_bytes=1; #1;
 repeat(3) begin
  if(dict_begin_ready!==0) $fatal(1,"dictionary displaced active commands");
  step();
 end
 dict_begin_valid=0;
"""
    for lane, case in enumerate(cases):
        body += f"""
 sg_channel={lane};
 send_descriptor(0,{len(case.source)},64'h10000+{lane}*64'h100000);
 send_descriptor(1,{case.capacity},64'h800000+{lane}*64'h100000);
 descriptor_edges[{lane}]=descriptor_edge;
 descriptor_done[{lane}]=1;
"""
    body += """
 st=0; while(!status_valid) begin step(); st=st+1;
  if(st>2000000) $fatal(1,"concurrent first completion"); end
 dict_begin_valid=1; dict_begin_id=222; dict_begin_bytes=1; #1;
 repeat(5) begin
  if(dict_begin_ready!==0) $fatal(1,"dictionary replaced with completion pending");
  step();
 end
 dict_begin_valid=0;
 st=0;
 while(completions<4) begin
  status_ready=(st%11)>=4;
  step(); st=st+1;
  if(st>2000000) $fatal(1,"concurrent operation bound");
 end
 if(four_active==0) $fatal(1,"four-lane concurrency not observed");
 repeat(4) step();
 if(completions!=4) $fatal(1,"completion conservation");
 $fclose(fd);
 $display("CONCURRENT compared=4 four_active_cycles=%0d",four_active);
 $finish;
end
endmodule
"""
    return text[:initial_start] + body


def lifecycle_testbench(geometry, directory):
    """Top-level tests only: no force, hierarchy or expected internal state."""
    from l1_transport import Case
    text = top_testbench([Case("recovery", b"x", capacity=64)], geometry, directory)
    insert = text.index("initial begin\n input_fd=")
    tasks = r"""
task reset_epoch;
begin
 rst_n=0; cmd_valid=0; sg_valid=0; dict_begin_valid=0; dict_s_valid=0;
 dict_status_ready=0; status_ready=0;
 #1; reset_outputs(); repeat(3) step();
 rst_n=1; #1;
 if(cmd_ready!==0 || dict_begin_ready!==0) $fatal(1,"reset release admitted before edge");
 repeat(3) step();
 if(dict_loaded!==0) $fatal(1,"dictionary survived reset");
end
endtask
task begin_image(input integer size,input reg [31:0] id);
integer n;
begin
 dict_begin_valid=1; dict_begin_bytes=size; dict_begin_id=id; #1;
 n=0; while(!dict_begin_ready) begin step(); n=n+1;
  if(n>1000) $fatal(1,"lifecycle begin"); end
 step(); dict_begin_valid=0;
 if(dict_loaded!==0) $fatal(1,"accepted begin did not invalidate");
end
endtask
task dict_result(input integer error);
integer n,k;
begin
 n=0; while(!dict_status_valid) begin step(); n=n+1;
  if(n>100000) $fatal(1,"lifecycle status"); end
 if(dict_status_error!==error[3:0]) $fatal(1,"dictionary error code");
 for(k=0;k<5;k=k+1) begin
  step();
  if(dict_status_valid!==1 || dict_status_error!==error[3:0] || cmd_ready!==0)
    $fatal(1,"dictionary status stability/admission");
 end
 dict_status_ready=1; step(); dict_status_ready=0; step();
end
endtask
task byte_image(input integer value,input integer last_byte);
integer n;
begin
 dict_s_valid=1; dict_s_data=value; dict_s_last=last_byte; #1;
 n=0; while(!dict_s_ready) begin step(); n=n+1;
  if(n>1000) $fatal(1,"dictionary data backpressure bound"); end
 step(); dict_s_valid=0;
end
endtask
task abort_transaction(input integer held_completion);
integer n;
begin
 case_active=1; expected_source=1; expected_capacity=64; expected_channel=0;
 read_bytes=0; write_bytes=0; ns=1; nd=1; tfault=0;
 descriptors_complete=0;
 source[0]=8'h78;
 cmd_channel=0; sg_channel=0; cmd_codec=5; cmd_id=16'h5a5a;
 cmd_decompress=0; cmd_checksum_mode=0; cmd_wide=0;
 cmd_src_bytes=1; cmd_dst_capacity=64; cmd_src_segments=1; cmd_dst_segments=1;
 cmd_valid=1; #1;
 n=0; while(!cmd_ready) begin step(); n=n+1;
  if(n>1000) $fatal(1,"reset command admission"); end
 step(); cmd_valid=0;
 send_descriptor(0,1,64'h10000); send_descriptor(1,64,64'h100000);
 descriptors_complete=1;
 n=0;
 if(held_completion) begin
  while(!status_valid) begin step(); n=n+1;
   if(n>100000) $fatal(1,"reset held-completion fixture"); end
  repeat(5) step();
 end else begin
  while(!r_pending) begin step(); n=n+1;
   if(n>1000) $fatal(1,"reset outstanding-DMA fixture"); end
 end
 reset_epoch(); case_active=0; repeat(4) step();
 if(status_valid!==0) $fatal(1,"stale completion after reset");
end
endtask
task exercise_lifecycle;
integer k;
begin
 begin_image(0,1); if(dict_s_ready!==0) $fatal(1,"invalid metadata requested data");
 dict_result(8);
 begin_image(1,0); dict_result(8);
 begin_image(DICT_LIMIT+1,123); dict_result(8);
 if(DICT_LIMIT>1) begin
  begin_image(2,123); byte_image(42,1); dict_result(8);
 end
 begin_image(1,123);
 repeat(7) begin step();
  if(dict_status_valid!==0 || dict_loaded!==0 || cmd_ready!==0)
   $fatal(1,"incomplete upload fabricated completion");
 end
 byte_image(42,0); dict_result(8);
 begin_image(1,123); byte_image(42,1); dict_result(0);
 if(dict_loaded!==1 || dict_id!==123 || dict_size!==1)
  $fatal(1,"singleton dictionary metadata");
 begin_image(1,456); reset_epoch();
 begin_image(1,456); byte_image(42,1);
 while(!dict_status_valid) step();
 reset_epoch();
 if(DICT_LIMIT>=7) begin
  begin_image(7,456);
  for(k=0;k<7;k=k+1) byte_image(k,k==6);
  if(dict_status_valid!==0 || dict_loaded!==0) $fatal(1,"preparation fixture already pinned");
  reset_epoch();
 end
 // Simultaneous begin has priority over an otherwise admissible command.
 cmd_channel=0; cmd_codec=5; cmd_src_bytes=0; cmd_src_segments=0;
 cmd_dst_capacity=64; cmd_dst_segments=1; cmd_valid=1;
 dict_begin_valid=1; dict_begin_id=789; dict_begin_bytes=1; #1;
 if(dict_begin_ready!==1 || cmd_ready!==0) $fatal(1,"dictionary priority");
 step(); dict_begin_valid=0; cmd_valid=0;
 byte_image(99,1); dict_result(0);
 reset_epoch();
 abort_transaction(0); abort_transaction(1);
 $display("LIFECYCLE invalid_metadata=3 singleton=1 reset_dma=1 reset_completion=1 priority=1");
end
endtask
"""
    text = text[:insert] + tasks + text[insert:]
    text = text.replace("DICT_LIMIT", str(geometry[3]))
    marker = ' input_fd=$fopen("dictionary-size.txt","r");'
    text = text.replace(marker, " exercise_lifecycle();\n" + marker)
    return text
