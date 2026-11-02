"""Generate self-checking public-pin benches into fresh evidence namespaces."""


def copy_bench(width, block=65536):
    return COPY.replace("@WIDTH@", str(width)).replace("@BLOCK@", str(block))


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
