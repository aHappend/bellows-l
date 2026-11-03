"""Public-port table and single-cycle FSE recurrence experiments."""

from l1_zstd import DEFAULT_COUNTS, build_table


def fixtures():
    result = []
    for alphabet, counts in enumerate(DEFAULT_COUNTS):
        result.append((alphabet, 0, 5 if alphabet == 1 else 6, counts))
        result.append((alphabet, 1, 0, (0,)))
    for alphabet in range(3):
        for log in ((5, 6, 8) if alphabet == 1 else (5, 6, 9)):
            # Include low-probability reserved cells and zero-count symbols.
            counts = (1, 0, -1, (1 << log) - 5, 2, -1)
            result.append((alphabet, 2, log, counts))
            result.append((alphabet, 2, log, (1 << log,)))
    return result


def table_testbench(directory):
    scenarios = fixtures()
    for index, (_, mode, log, counts) in enumerate(scenarios):
        padded = list(counts) + [0] * (64 - len(counts))
        (directory / f"counts-{index}.hex").write_text(
            "".join(f"{c & 2047:03x}\n" for c in padded))
        rows = ((0, 0, 0),) if mode == 1 else build_table(counts, log)
        (directory / f"rows-{index}.hex").write_text("".join(
            f"{(s << 13) | (k << 9) | b:05x}\n" for s, k, b in rows))
    (directory / "tables.txt").write_text("".join(
        f"{i} {a} {m} {log}\n" for i, (a, m, log, _) in enumerate(scenarios)))
    return r"""`timescale 1ns/1ps
module tb;
parameter integer CYCLE_LIMIT=450000;
reg clk=0, rst_n=0, clear=0;
reg start_valid=0, count_valid=0, count_last=0, done_ready=0;
reg [1:0] alphabet=0, mode=0;
reg [3:0] requested_log=0;
reg signed [10:0] count_value=0;
wire start_ready,count_ready,done_valid,table_valid;
wire [3:0] done_error,table_log;
reg [8:0] address=0;
wire [5:0] symbol;
wire [3:0] nbits;
wire [8:0] base;
reg use_state=0, init_valid=0, step_valid=0,m_ready=0;
reg [8:0] init_state=0,bits=0;
reg [3:0] available=0;
wire init_ready,step_ready,m_valid;
wire [8:0] state,m_state;
wire [5:0] m_symbol;
wire [3:0] m_nbits;
reg [10:0] counts[0:63];
reg [18:0] rows[0:511];
reg [255:0] filename;
integer fd,idx,alpha,md,lg,tokens,ti,ci,s,b,k,expected,cycles=0;
integer comparisons=0,continuous=0,stalls=0,n=0, table_checks=0;
reg [18:0] row;
reg [18:0] held;
reg [8:0] held_state;
bellows_l5_fse_table table_dut(
 .clk(clk),.rst_n(rst_n),.clear(clear),.start_valid(start_valid),.start_ready(start_ready),
 .alphabet(alphabet),.mode(mode),.requested_log(requested_log),.rle_symbol(6'd0),
 .count_valid(count_valid),.count_ready(count_ready),.count_value(count_value),
 .count_last(count_last),.done_valid(done_valid),.done_ready(done_ready),
 .done_error(done_error),.table_valid(table_valid),.table_log(table_log),
 .row_address(use_state?state:address),.row_symbol(symbol),.row_nbits(nbits),.row_base(base));
bellows_l5_fse_decoder leaf(
 .clk(clk),.rst_n(rst_n),.init_valid(init_valid),.init_ready(init_ready),
 .init_state(init_state),.state(state),.step_valid(step_valid),.step_ready(step_ready),
 .bits(bits),.available(available),.row_symbol(symbol),.row_nbits(nbits),.row_base(base),
 .m_valid(m_valid),.m_ready(m_ready),.m_symbol(m_symbol),.m_state(m_state),.m_nbits(m_nbits));
always #5 clk=~clk;
always @(posedge clk or negedge clk) begin
 if(!rst_n && {start_ready,count_ready,done_valid,done_error,table_valid,table_log,
               symbol,nbits,base,init_ready,step_ready,state,m_valid,m_symbol,m_state,m_nbits}!==0)
  $fatal(1,"FSE reset leakage at %0t",$time);
end
always @(posedge clk) begin
 cycles=cycles+1;
 if(cycles>CYCLE_LIMIT) $fatal(1,"compact FSE operation bound");
end
task edge_step;
begin @(posedge clk); #1; @(negedge clk); #1; end
endtask
task initialize(input integer value);
begin
 if(m_valid) begin m_ready=1; edge_step(); m_ready=0; end
 init_valid=1; init_state=value; step_valid=1; available=9; #1;
 if(init_ready!==1 || step_ready!==0) $fatal(1,"FSE init priority");
 edge_step(); init_valid=0; step_valid=0;
 if(state!==value[8:0] || m_valid!==0) $fatal(1,"FSE initialization latency");
end
endtask
task compare_transition(input reg [18:0] expected_row,input integer value);
integer next_value;
begin
 next_value=expected_row[8:0]+(value & ((1<<expected_row[12:9])-1));
 if(m_valid!==1 || m_symbol!==expected_row[18:13] || m_nbits!==expected_row[12:9] ||
    state!==next_value[8:0] || m_state!==next_value[8:0])
  $fatal(1,"FSE semantic transition mismatch table=%0d state=%0d bits=%0d",idx,s,value);
 comparisons=comparisons+1;
end
endtask
initial begin
 #0.001;
 if({start_ready,count_ready,done_valid,done_error,table_valid,table_log,
     symbol,nbits,base,init_ready,step_ready,state,m_valid,m_symbol,m_state,m_nbits}!==0)
  $fatal(1,"FSE time-zero reset leakage");
 #11.999; rst_n=1;
 @(negedge clk); #1; edge_step();
 // Reset while a compressed table has accepted only a partial count stream.
 alphabet=0; mode=2; requested_log=5; start_valid=1; #1;
 if(start_ready!==1) $fatal(1,"reset table fixture did not start");
 edge_step(); start_valid=0;
 n=0; while(!count_ready) begin edge_step(); n=n+1;
  if(n>200) $fatal(1,"reset table fixture did not request counts"); end
 count_valid=1; count_value=1; count_last=0; edge_step(); count_valid=0;
 rst_n=0; #1; edge_step(); rst_n=1; edge_step();
 if(table_valid!==0 || done_valid!==0) $fatal(1,"partial table survived reset");
 fd=$fopen("tables.txt","r");
 if(!fd) $fatal(1,"FSE missing fixture");
 for(ti=0;ti<TABLES;ti=ti+1) begin
  tokens=$fscanf(fd,"%d %d %d %d",idx,alpha,md,lg);
  if(tokens!=4 || idx!=ti) $fatal(1,"FSE malformed fixture");
  clear=1; edge_step(); clear=0; edge_step(); use_state=0;
  $sformat(filename,"counts-%0d.hex",idx); $readmemh(filename,counts);
  $sformat(filename,"rows-%0d.hex",idx); $readmemh(filename,rows,0,(1<<lg)-1);
  alphabet=alpha; mode=md; requested_log=lg; start_valid=1; #1;
  if(start_ready!==1) $fatal(1,"FSE table not ready");
  edge_step(); start_valid=0;
  if(md==2) begin
   for(ci=0;ci<((alpha==0)?36:((alpha==1)?32:53));ci=ci+1) begin
    n=0;
    while(!count_ready) begin edge_step(); n=n+1;
      if(n>200) $fatal(1,"FSE count-ready bound"); end
    count_valid=1; count_value=counts[ci];
    count_last=(ci==((alpha==0)?35:((alpha==1)?31:52)));
    edge_step(); count_valid=0;
   end
  end
  n=0;
  while(!done_valid) begin edge_step(); n=n+1;
   if(n>20000) $fatal(1,"FSE table-build bound"); end
  if(done_error!==0 || table_valid!==1 || table_log!==lg[3:0])
   $fatal(1,"FSE valid table rejected table=%0d mode=%0d log=%0d error=%0d",idx,md,lg,done_error);
  repeat(3) begin edge_step();
   if(done_valid!==1 || done_error!==0) $fatal(1,"FSE table completion stall"); end
  done_ready=1; edge_step(); done_ready=0;
  for(s=0;s<(1<<lg);s=s+1) begin
   address=s; #1;
   if({symbol,nbits,base}!==rows[s]) $fatal(1,"FSE row mismatch table=%0d row=%0d",idx,s);
   table_checks=table_checks+1;
  end
  use_state=1;
  for(s=0;s<(1<<lg);s=s+1) begin
   row=rows[s]; k=row[12:9];
   for(b=0;b<(1<<k);b=b+1) begin
    initialize(s); bits=b; available=k; step_valid=1; #1;
    if(step_ready!==1) $fatal(1,"FSE transition not available");
    edge_step(); step_valid=0; compare_transition(row,b);
    if(b==0) begin
     held={m_symbol,m_nbits,m_state}; held_state=state;
     bits=511; init_valid=1; init_state=0; step_valid=1; m_ready=0;
     repeat(2) begin edge_step();
      if({m_symbol,m_nbits,m_state}!==held || state!==held_state ||
         m_valid!==1 || step_ready!==0 || init_ready!==0) $fatal(1,"FSE stalled output");
      stalls=stalls+1;
     end
     init_valid=0; step_valid=0;
    end
    m_ready=1; edge_step(); m_ready=0;
   end
  end
  initialize(0); m_ready=1;
  for(ci=0;ci<300;ci=ci+1) begin
   row=rows[state]; bits=(ci*73)^17; available=9; step_valid=1; #1;
   if(step_ready!==1) $fatal(1,"FSE dependent recurrence not one-per-cycle");
   expected=bits;
   edge_step(); compare_transition(row,expected); continuous=continuous+1;
  end
  step_valid=0; edge_step(); m_ready=0;
  initialize(0); m_ready=1;
  for(ci=0;ci<300;ci=ci+1) begin
   row=rows[state]; bits=(ci*73)^17; available=9; step_valid=1; #1;
   if(step_ready!==1) $fatal(1,"FSE stalled-copy recurrence readiness");
   expected=bits;
   edge_step(); compare_transition(row,expected);
   if(ci%7==3) begin
    m_ready=0; held={m_symbol,m_nbits,m_state}; held_state=state;
    repeat(3) begin
     edge_step();
     if(m_valid!==1 || step_ready!==0 || state!==held_state ||
        {m_symbol,m_nbits,m_state}!==held) $fatal(1,"FSE stalled-copy recurrence changed");
     stalls=stalls+1;
    end
    m_ready=1;
   end
  end
  step_valid=0; edge_step(); m_ready=0;
  initialize(0); row=rows[0]; k=row[12:9];
  if(k>0) begin
   available=k-1; step_valid=1; #1;
   if(step_ready!==0) $fatal(1,"FSE consumed insufficient bits");
   edge_step();
   if(state!==0 || m_valid!==0) $fatal(1,"FSE advanced with insufficient bits");
   step_valid=0;
  end
 end
 $fclose(fd);
 if(comparisons==0 || table_checks==0 || continuous<256 || stalls==0)
  $fatal(1,"FSE empty coverage");
 $display("COMPARED table_rows=%0d transitions=%0d continuous=%0d stalls=%0d cycles=%0d",
          table_checks,comparisons,continuous,stalls,cycles);
 $finish;
end
endmodule
""".replace("TABLES", str(len(scenarios)))
