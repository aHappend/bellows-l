"""Generate a shared public-pin transactor for Icarus and compiled Verilator.

Icarus retains delta-cycle startup/X checks. Verilator is two-state and lacks
inactive-region #0 scheduling; its startup check waits one time unit instead.
Neither path delays the first Active-region rising-edge reset observation.
"""

from pathlib import Path


PORTS = """
reg clk = 0;
reg rst_n;
reg roundtrip_enable = 0;
reg [7:0] c_s_data = 0, d_s_data = 0;
reg c_s_keep = 0, c_s_valid = 0, c_s_last = 0;
reg d_s_valid = 0, d_s_last = 0;
reg c_m_ready = 0, d_m_ready = 0, c_status_ready = 0, d_status_ready = 0;
wire c_s_ready, d_s_ready;
wire [7:0] c_m_data, d_m_data;
wire c_m_valid, c_m_last, d_m_valid, d_m_last;
wire c_status_valid, d_status_valid;
wire [2:0] c_status_error, d_status_error;
bellows_l2_top #(.MAX_BLOCK_BYTES(CAPACITY)) dut (
 .clk(clk), .rst_n(rst_n), .roundtrip_enable(roundtrip_enable),
 .c_s_data(c_s_data), .c_s_keep(c_s_keep), .c_s_valid(c_s_valid),
 .c_s_last(c_s_last), .c_s_ready(c_s_ready),
 .c_m_data(c_m_data), .c_m_valid(c_m_valid), .c_m_last(c_m_last), .c_m_ready(c_m_ready),
 .c_status_valid(c_status_valid), .c_status_error(c_status_error),
 .c_status_ready(c_status_ready),
 .d_s_data(d_s_data), .d_s_valid(d_s_valid), .d_s_last(d_s_last), .d_s_ready(d_s_ready),
 .d_m_data(d_m_data), .d_m_valid(d_m_valid), .d_m_last(d_m_last), .d_m_ready(d_m_ready),
 .d_status_valid(d_status_valid), .d_status_error(d_status_error),
 .d_status_ready(d_status_ready)
);
always #5 clk = ~clk;
wire [31:0] outputs = {c_s_ready,d_s_ready,c_m_data,c_m_valid,c_m_last,
 d_m_data,d_m_valid,d_m_last,c_status_valid,c_status_error,d_status_valid,d_status_error};
reg hold_c = 0, hold_d = 0, hold_cs = 0, hold_ds = 0;
reg [8:0] saved_c, saved_d;
reg [2:0] saved_cs, saved_ds;
integer trace;
integer case_id = -1;
integer cs_seen = 0, ds_seen = 0;
integer monitor_active = 0;
task check_reset;
 begin
  if (outputs !== 32'b0) $fatal(1,"RESET_OUTPUT_X_OR_NONZERO outputs=%h",outputs);
 end
endtask
always @(posedge clk) begin
 if (!rst_n) begin
  check_reset();
  hold_c = 0; hold_d = 0; hold_cs = 0; hold_ds = 0;
 end else if (monitor_active) begin
  if ((^outputs) === 1'bx) $fatal(1,"ACTIVE_OUTPUT_X");
  if (roundtrip_enable && {c_m_data,c_m_valid,c_m_last,d_s_ready} !== 11'b0)
   $fatal(1,"ROUNDTRIP_EXTERNAL_ROUTE_NOT_ZERO");
  if (hold_c && {c_m_valid,c_m_data,c_m_last} !== {1'b1,saved_c}) begin
   $fflush(trace);
   $fatal(1,"HELD_C_OUTPUT case=%0d",case_id);
  end
  if (hold_d && {d_m_valid,d_m_data,d_m_last} !== {1'b1,saved_d}) begin
   $fflush(trace);
   $fatal(1,"HELD_D_OUTPUT case=%0d",case_id);
  end
  if (hold_cs && {c_status_valid,c_status_error} !== {1'b1,saved_cs})
   $fatal(1,"HELD_C_STATUS");
  if (hold_ds && {d_status_valid,d_status_error} !== {1'b1,saved_ds})
   $fatal(1,"HELD_D_STATUS");
  hold_c = c_m_valid && !c_m_ready;
  hold_d = d_m_valid && !d_m_ready;
  hold_cs = c_status_valid && !c_status_ready;
  hold_ds = d_status_valid && !d_status_ready;
  saved_c = {c_m_data,c_m_last}; saved_d = {d_m_data,d_m_last};
  saved_cs = c_status_error; saved_ds = d_status_error;
 end
end
always @(negedge clk) begin
 if (!rst_n) begin
`ifndef VERILATOR
  #0;
`endif
  check_reset();
 end else if (monitor_active) begin
  if (hold_c && {c_m_valid,c_m_data,c_m_last} !== {1'b1,saved_c}) begin
   $fflush(trace);
   $fatal(1,"HELD_C_OUTPUT_POST_EDGE");
  end
  if (hold_d && {d_m_valid,d_m_data,d_m_last} !== {1'b1,saved_d}) begin
   $fflush(trace);
   $fatal(1,"HELD_D_OUTPUT_POST_EDGE");
  end
 end
end
task reset_now;
 begin
  monitor_active = 0;
  rst_n = 0;
  c_s_valid = 0; d_s_valid = 0; c_s_keep = 0; c_s_last = 0; d_s_last = 0;
  c_m_ready = 0; d_m_ready = 0; c_status_ready = 0; d_status_ready = 0;
  #1; check_reset();
  repeat (3) @(negedge clk);
  #1;
  rst_n = 1;
  #1;
  monitor_active = 1;
 end
endtask
"""


DRIVER = r"""
reg [41:0] cb [0:MAX_SEGMENTS-1], db [0:MAX_SEGMENTS-1];
integer ci, di;
reg [31:0] cr, dr;
integer csa, dsa, cfa, dfa, cg, dg;
integer ch, dh;
integer c_in, d_in, c_out, d_out, cst, dst, cfinal, dfinal;
integer c_block_final;
integer c_input_final, d_input_final;
integer c_input_stall, d_input_stall, c_output_stall, d_output_stall;
integer c_status_stall, d_status_stall, c_final_stall, d_final_stall;
integer coincident, concurrent;
integer ca, da;
longint unsigned cycle, finished_input, bound;
reg [31:0] random_state = SEED;
reg [31:0] random_c = SEED ^ 32'h938a75b1;
reg [31:0] random_d = SEED ^ 32'h724fd821;
reg [31:0] random_cs = SEED ^ 32'h561ac327;
reg [31:0] random_ds = SEED ^ 32'hbf792cd1;
task random_step;
 begin
  random_state = random_state ^ (random_state << 13);
  random_state = random_state ^ (random_state >> 17);
  random_state = random_state ^ (random_state << 5);
  random_c = random_c ^ (random_c << 13);
  random_c = random_c ^ (random_c >> 17);
  random_c = random_c ^ (random_c << 5);
  random_d = random_d ^ (random_d << 13);
  random_d = random_d ^ (random_d >> 17);
  random_d = random_d ^ (random_d << 5);
  random_cs = random_cs ^ (random_cs << 13);
  random_cs = random_cs ^ (random_cs >> 17);
  random_cs = random_cs ^ (random_cs << 5);
  random_ds = random_ds ^ (random_ds << 13);
  random_ds = random_ds ^ (random_ds >> 17);
  random_ds = random_ds ^ (random_ds << 5);
 end
endtask
task run_case;
 input integer id;
 input [4095:0] cpath, dpath;
 input integer cn, dn, expected_cs, expected_ds, route, abort_kind;
 input [63:0] cycle_bound;
 begin
  @(negedge clk);
  case_id = id;
  roundtrip_enable = route;
  ci=0; di=0; cr=0; dr=0; cs_seen=0; ds_seen=0;
  csa=0; dsa=0; cfa=0; dfa=0; cg=0; dg=0; ch=0; dh=0;
  c_in=0; d_in=0; c_out=0; d_out=0; cst=0; dst=0; cfinal=0; dfinal=0;
  c_block_final=0;
  c_input_final=0; d_input_final=0;
  c_input_stall=0; d_input_stall=0; c_output_stall=0; d_output_stall=0;
  c_status_stall=0; d_status_stall=0; c_final_stall=0; d_final_stall=0;
  coincident=0; concurrent=0;
  cycle=0; finished_input=0; bound=cycle_bound;
  c_s_valid=0; d_s_valid=0;
  ca=0; da=0;
  if(cn>0) begin $readmemh(cpath,cb,0,cn-1); cr=cb[0][41:10]; end
  if(dn>0) begin $readmemh(dpath,db,0,dn-1); dr=db[0][41:10]; end
  begin : traffic
   forever begin
    random_step();
    if (!c_s_valid || ca) begin
     if (ci<cn && (random_state[0] || cg>=3)) begin
      {c_s_last,c_s_keep,c_s_data}=cb[ci][9:0]; c_s_valid=1; cg=0;
     end else begin c_s_valid=0; cg=cg+1; end
    end
    if(route) begin
     d_s_valid=1; d_s_data=8'hd7; d_s_last=1;
    end else if (!d_s_valid || da) begin
     if (di<dn && (random_d[0] || dg>=3)) begin
      d_s_data=db[di][7:0]; d_s_last=db[di][9]; d_s_valid=1; dg=0;
     end else begin d_s_valid=0; dg=dg+1; end
    end
    c_m_ready=random_c[0] || ch>=4;
    d_m_ready=random_d[1] || dh>=4;
    if(route) c_m_ready=0;
    if(c_m_valid && ch<3) c_m_ready=0;
    if(d_m_valid && dh<3) d_m_ready=0;
    if(c_m_valid && c_m_last && cfa<5) c_m_ready=0;
    if(d_m_valid && d_m_last && dfa<5) d_m_ready=0;
    if(abort_kind==4) c_m_ready=0;
    c_status_ready=csa>=7 && (random_cs[2] || csa>=12);
    d_status_ready=dsa>=9 && (random_ds[3] || dsa>=15);
    @(posedge clk);
    cycle=cycle+1;
    ca=c_s_valid && c_s_ready;
    da=!route && d_s_valid && d_s_ready;
    if(c_s_valid && !c_s_ready) c_input_stall=c_input_stall+1;
    if(!route && d_s_valid && !d_s_ready) d_input_stall=d_input_stall+1;
    if(c_m_valid && !c_m_ready) begin
     if(ch==0) $fwrite(trace,"STALL_C %0d %0d %02h %0d\n",id,cs_seen,c_m_data,c_m_last);
     c_output_stall=c_output_stall+1;
     ch=ch+1;
     if(c_m_last) begin cfa=cfa+1; c_final_stall=c_final_stall+1; end
    end
    if(d_m_valid && !d_m_ready) begin
     d_output_stall=d_output_stall+1;
     dh=dh+1;
     if(d_m_last) begin dfa=dfa+1; d_final_stall=d_final_stall+1; end
    end
    if(c_status_valid && !c_status_ready) c_status_stall=c_status_stall+1;
    if(d_status_valid && !d_status_ready) d_status_stall=d_status_stall+1;
    if((ca || c_m_valid) && (da || d_m_valid)) concurrent=concurrent+1;
    if(c_m_valid && c_m_ready && d_m_valid && d_m_ready) coincident=coincident+1;
    if(ca) begin
     c_in=c_in+1;
     if(c_s_last) begin
      c_input_final=c_input_final+1;
      $fwrite(trace,"CI %0d %0d %0d\n",id,c_in,cycle);
     end
     if(cr==1) begin ci=ci+1; if(ci<cn) cr=cb[ci][41:10]; end
     else cr=cr-1;
    end
    if(da) begin
     d_in=d_in+1;
     if(d_s_last) begin
      d_input_final=d_input_final+1;
      $fwrite(trace,"DI %0d %0d %0d\n",id,d_in,cycle);
     end
     if(dr==1) begin di=di+1; if(di<dn) dr=db[di][41:10]; end
     else dr=dr-1;
    end
    if(c_m_valid && c_m_ready) begin
     if(c_input_final<=cs_seen) $fatal(1,"C_OUTPUT_BEFORE_INPUT_BOUNDARY");
     $fwrite(trace,"C %0d %0d %02h %0d\n",id,cs_seen,c_m_data,c_m_last);
     c_out=c_out+1; ch=0;
     if(c_m_last) begin cfinal=cfinal+1; c_block_final=c_block_final+1; cfa=0; end
    end
    if(d_m_valid && d_m_ready) begin
     $fwrite(trace,"D %0d %0d %02h %0d\n",id,ds_seen,d_m_data,d_m_last);
     d_out=d_out+1; dh=0;
     if(d_m_last) begin dfinal=dfinal+1; dfa=0; end
    end
    if(c_status_valid) begin
     if(c_s_ready) $fatal(1,"C_ACCEPT_WHILE_STATUS_HELD");
     if(c_input_final<=cs_seen) $fatal(1,"C_STATUS_BEFORE_DISCARD_BOUNDARY");
     csa=csa+1;
     if(!route && c_status_error==0 && c_block_final!=1)
      $fatal(1,"C_STATUS_BEFORE_FINAL_OUTPUT");
     if(!route && c_status_error!=0 && c_block_final!=0)
      $fatal(1,"C_ERROR_WITH_OUTPUT");
     if(c_status_ready) begin
      $fwrite(trace,"CS %0d %0d %0d\n",id,cs_seen,c_status_error);
      cs_seen=cs_seen+1; cst=cst+1; csa=0; c_block_final=0;
      if(cs_seen>expected_cs && abort_kind==0) $fatal(1,"EXTRA_C_STATUS");
     end
    end
    if(d_status_valid) begin
     if(d_m_valid) $fatal(1,"D_STATUS_BEFORE_OUTPUT_RETIREMENT");
     if(!route && d_input_final<=ds_seen) $fatal(1,"D_STATUS_BEFORE_INPUT_BOUNDARY");
     dsa=dsa+1;
     if(d_status_ready) begin
      $fwrite(trace,"DS %0d %0d %0d\n",id,ds_seen,d_status_error);
      ds_seen=ds_seen+1; dst=dst+1; dsa=0;
      if(ds_seen>expected_ds && abort_kind==0) $fatal(1,"EXTRA_D_STATUS");
     end
    end
    if(ci==cn && finished_input==0) finished_input=cycle;
    if(abort_kind==1 && c_in>=1 && !c_s_last) disable traffic;
    if(abort_kind==2 && ci==cn && cycle>=finished_input+80) begin
     if(c_m_valid || c_status_valid) $fatal(1,"RESET_PROCESSING_PRECONDITION");
     disable traffic;
    end
    if(abort_kind==3 && c_m_valid && c_m_ready) disable traffic;
    if(abort_kind==4 && c_m_valid && c_output_stall>=3) disable traffic;
    if(abort_kind==0 && ci==cn && di==dn &&
       cs_seen==expected_cs && ds_seen==expected_ds) disable traffic;
    if(cycle>=bound) $fatal(1,"CYCLE_PROGRESS_BOUND case=%0d cycles=%0d",id,cycle);
    @(negedge clk);
   end
  end
  $fwrite(trace,"COV %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
    id,c_input_stall,d_input_stall,c_output_stall,d_output_stall,
    c_status_stall,d_status_stall,c_final_stall,d_final_stall,
    concurrent,coincident,c_in,d_in,c_out,d_out,cst,dst,cfinal,dfinal);
  if(abort_kind!=0) begin
   $fwrite(trace,"ABORT %0d %0d %0d\n",id,abort_kind,cycle);
   @(negedge clk); reset_now();
  end else begin
   @(negedge clk);
   c_s_valid=0; d_s_valid=0;
   c_status_ready=1; d_status_ready=1; c_m_ready=1; d_m_ready=1;
   repeat(16) begin
    @(posedge clk);
    if(c_m_valid || d_m_valid || c_status_valid || d_status_valid)
     $fatal(1,"RESIDUAL_OUTPUT_OR_STATUS");
   end
  end
  $fwrite(trace,"END %0d %0d\n",id,cycle);
 end
endtask
"""


def compact(segments):
    result = []
    for count, word in segments:
        assert 0 < count < 2**32 and 0 <= word < 1024
        if result and result[-1][1] == word:
            result[-1] = (result[-1][0] + count, word)
        else:
            result.append((count, word))
    return result


def write_vectors(path, blocks):
    segments = compact([segment for block in blocks for segment in block.segments()])
    path.write_text("".join(f"{(count << 10) | word:011x}\n" for count, word in segments))
    return len(segments), sum(count for count, _ in segments)


def generate(directory, capacity, seed, cases):
    directory = Path(directory)
    calls = []
    max_segments = 1
    info = []
    for index, case in enumerate(cases):
        cp, dp = directory / f"case-{index}-c.hex", directory / f"case-{index}-d.hex"
        cn, ct = write_vectors(cp, case.raw)
        dn, dt = write_vectors(dp, case.decoder)
        max_segments = max(max_segments, cn, dn)
        expected_ds = len(case.raw) if case.roundtrip else len(case.decoder)
        decoded_work = (sum(len(b.data) for b in case.raw) if case.roundtrip
                        else sum(len(b.expected) for b in case.decoder))
        # Serial key lookup, comparison, emission, fallback and replay each have
        # bounded per-byte work; 256 cycles/byte also covers the bounded stalls.
        bound = 10000 + 256 * (ct + dt + decoded_work + capacity + 1)
        abort = {"": 0, "collect": 1, "match": 2, "emission": 3, "stalled": 4}[case.abort]
        calls.append(f'run_case({index},"{cp.as_posix()}","{dp.as_posix()}",'
                     f'{cn},{dn},{len(case.raw)},{expected_ds},{int(case.roundtrip)},'
                     f"{abort},64'd{bound});")
        info.append(dict(name=case.name, raw_beats=ct, decoder_beats=dt,
                         bound_cycles=bound, reset_abort=case.abort))
    source = (f"module tb;\nlocalparam CAPACITY={capacity}, SEED={seed}, "
              f"MAX_SEGMENTS={max_segments};\n" + PORTS + DRIVER + """
initial begin
 rst_n=0;
 trace=$fopen("TRACE_PATH","w");
 if(trace==0) $fatal(1,"TRACE_OPEN");
`ifdef VERILATOR
 #1;
`else
 #0;
`endif
 check_reset();
 repeat(3) @(negedge clk);
 #1;
 rst_n=1;
 #1; monitor_active=1;
 CALLS
 $fwrite(trace,"DONE\\n");
 $fclose(trace);
 $finish;
end
endmodule
""".replace("TRACE_PATH", (directory / "trace.txt").as_posix())
              .replace("CALLS", "\n ".join(calls)))
    path = directory / "tb.sv"
    path.write_text(source)
    return path, info
