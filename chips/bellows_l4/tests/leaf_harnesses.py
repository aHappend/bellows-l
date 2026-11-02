"""Public interfaces for canonical tables, arbitration and preserved streams."""

from collections import Counter

from reference import canonical, code_lengths


def table_vectors(path):
    fixtures = [
        ("empty", True, False, [0]*256),
        ("singleton", True, False, [0, 41]+[0]*254),
        ("equal-frequency-ties", True, False, [3]*256),
        ("W4-equal-ties", True, True, [7]*16),
        ("mixed-histogram", True, False, [i % 11 for i in range(256)]),
        ("complete-depth15", False, False, list(range(1, 15))+[15, 15]+[0]*240),
        ("complete-multilevel-W4", False, True, [1, 2, 3, 3]+[0]*12),
        ("incomplete", False, False, [2, 2]+[0]*254),
        ("oversubscribed", False, True, [1, 1, 1]+[0]*13),
        ("out-of-range", False, False, [16]+[0]*255),
        ("forbidden-singleton", False, True, [2]+[0]*15),
    ]
    fib = [1, 1]
    for _ in range(18):
        fib.append(sum(fib[-2:]))
    fixtures.append(("depth-limit-fallback", True, False, fib+[0]*236))
    records = []
    with path.open("w") as stream:
        for name, encoder, w4, operands in fixtures:
            error = 0
            lengths = code_lengths(Counter({i: f for i, f in enumerate(operands)}),
                                   len(operands)) if encoder else operands
            try:
                codes = canonical(lengths)
            except ValueError:
                error, codes = 11, {}
            fallback = encoder and name == "depth-limit-fallback"
            if fallback and lengths != [8]*256:
                raise AssertionError("fallback fixture does not exceed depth15")
            stream.write(f"{int(encoder)} {int(w4)} {error} {int(fallback)}\n")
            for i, value in enumerate(operands):
                code, length = codes.get(i, (0, 0))
                stream.write(f"{value} {length} {code}\n")
            records.append({"name": name, "encode": encoder, "W4": w4,
                            "expected_error": error, "depth_fallback": bool(fallback)})
    return records


TABLE = r"""
module tb;
reg clk=0; always #5 clk=~clk;
reg rst_n,clear=0,start_valid=0,encode=0,alphabet_w4=0;
wire start_ready,hist_ready,length_ready,build_ready,table_valid,depth_fallback;
reg hist_valid=0,length_valid=0,build_valid=0,lookup_valid=0,decode_read=0;
reg [7:0] hist_symbol=0,length_symbol=0,length_value=0,lookup_symbol=0,decode_index=0;
reg [31:0] hist_frequency=0;
wire [3:0] table_error,lookup_length;
wire [14:0] lookup_code;
wire lookup_result_valid,decode_result_valid;
wire [7:0] decode_symbol;
wire [255:0] first_codes;
wire [159:0] length_counts,first_indices;
bellows_l4_huffman_table dut(.*);
integer file,scan,enc,w4,err,fallback,alphabet,i,j,operand,wait_cycles;
integer expected_length[0:255],expected_code[0:255],cases=0,lookups=0,sorted_index;
string vectors;
task reset_check;
 begin
  if({start_ready,hist_ready,length_ready,build_ready,table_valid,table_error,
      depth_fallback,lookup_result_valid,lookup_length,lookup_code,
      decode_result_valid,decode_symbol,first_codes,length_counts,first_indices} !== '0)
   $fatal(1,"ASSERT TABLE RESET");
 end
endtask
always @(posedge clk) if(!rst_n) reset_check();
always @(negedge clk) if(!rst_n) reset_check();
task tick; begin @(posedge clk); #1; @(negedge clk); end endtask
initial begin
 rst_n=0; #0; reset_check(); tick(); tick(); rst_n=1; tick();
 if(!$value$plusargs("vectors=%s",vectors)) $fatal(1,"missing table vectors");
 file=$fopen(vectors,"r"); if(!file) $fatal(1,"table vector open");
 while(!$feof(file)) begin
  scan=$fscanf(file,"%d %d %d %d",enc,w4,err,fallback);
  if(scan!=4) $fatal(1,"table record header");
  alphabet=w4 ? 16 : 256;
  start_valid=1; encode=enc; alphabet_w4=w4;
  if(start_ready!==1'b1) $fatal(1,"ASSERT TABLE start ready");
  tick(); start_valid=0;
  for(i=0;i<alphabet;i=i+1) begin
   scan=$fscanf(file,"%d %d %d",operand,expected_length[i],expected_code[i]);
   if(scan!=3) $fatal(1,"table operands");
   hist_valid=enc; length_valid=!enc;
   hist_symbol=i; hist_frequency=operand; length_symbol=i; length_value=operand;
   if((enc && hist_ready!==1'b1) || (!enc && length_ready!==1'b1))
    $fatal(1,"ASSERT TABLE load ready");
   tick();
  end
  hist_valid=0; length_valid=0; build_valid=1;
  if(build_ready!==1'b1) $fatal(1,"ASSERT TABLE build ready");
  tick(); build_valid=0; wait_cycles=0;
  while(!table_valid) begin
   tick(); wait_cycles=wait_cycles+1;
   if(wait_cycles>500000) $fatal(1,"ASSERT TABLE finite construction");
  end
  if(table_error!==err[3:0] || depth_fallback!==fallback[0])
   $fatal(1,"ASSERT TABLE status case=%0d error=%0d/%0d fallback=%0d/%0d",
       cases,table_error,err,depth_fallback,fallback);
  if(err==0) begin
   for(i=0;i<alphabet;i=i+1) begin
    lookup_symbol=i; lookup_valid=1;
    @(posedge clk); #1;
    if(lookup_result_valid!==1'b1 || lookup_length!==expected_length[i][3:0] ||
       lookup_code!==expected_code[i][14:0])
     $fatal(1,"ASSERT TABLE canonical lookup symbol=%0d length=%0d/%0d code=%0d/%0d",
        i,lookup_length,expected_length[i],lookup_code,expected_code[i]);
    lookups=lookups+1; @(negedge clk);
   end
   lookup_valid=0; tick();
   if(lookup_result_valid!==1'b0) $fatal(1,"ASSERT TABLE lookup validity");
   sorted_index=0;
   for(j=1;j<=15;j=j+1)
    for(i=0;i<alphabet;i=i+1) if(expected_length[i]==j) begin
     decode_index=sorted_index; decode_read=1;
     @(posedge clk); #1;
     if(decode_result_valid!==1'b1 || decode_symbol!==i[7:0])
      $fatal(1,"ASSERT TABLE sorted symbol lookup");
     sorted_index=sorted_index+1; @(negedge clk);
    end
   decode_read=0; tick();
  end
  cases=cases+1;
  $display("CASE TABLE %0d error=%0d fallback=%0d cycles=%0d",cases,err,fallback,wait_cycles);
  clear=1; tick(); clear=0; tick();
  scan=$fscanf(file,"\n");
 end
 if(cases!=12 || lookups<1000) $fatal(1,"ASSERT TABLE incomplete comparisons");
 $display("SUMMARY TABLE cases=%0d lookups=%0d",cases,lookups);
 $fclose(file); $finish;
end
endmodule
"""


ARBITRATION = r"""
module tb;
reg clk=0; always #5 clk=~clk;
reg rst_n;
reg [3:0] lane_rd_valid=0,lane_wr_valid=0,lane_status_valid=0;
reg [275:0] lane_rd_payload=0;
reg [547:0] lane_wr_payload=0;
reg [463:0] lane_status_payload=0;
wire [3:0] lane_rd_take,lane_wr_take,lane_status_retire;
wire rd_valid,wr_valid,status_valid;
wire [1:0] rd_channel,wr_channel,status_channel;
wire [68:0] rd_payload;
wire [136:0] wr_payload;
wire [115:0] status_payload;
reg rd_ready=0,wr_ready=0,status_ready=0,rd_available=0,wr_available=0;
bellows_l4_scheduler dut(.*);
integer i,n,rg=0,wg=0,sg=0,rptr=0,wptr=0,sptr=0;
reg rh=0,wh=0,sh=0;
reg [70:0] rp;
reg [138:0] wp;
reg [117:0] sp;
task reset_check;
 begin
  if({lane_rd_take,lane_wr_take,lane_status_retire,rd_valid,rd_channel,rd_payload,
      wr_valid,wr_channel,wr_payload,status_valid,status_channel,status_payload} !== '0)
   $fatal(1,"ASSERT ARBITRATION RESET");
 end
endtask
always @(negedge clk) if(!rst_n) reset_check();
task tick;
 begin
  @(posedge clk);
  if(!rst_n) reset_check();
  else begin
   if(rh && {rd_valid,rd_channel,rd_payload} !== {1'b1,rp})
    $fatal(1,"ASSERT ARBITRATION read stability");
   if(wh && {wr_valid,wr_channel,wr_payload} !== {1'b1,wp})
    $fatal(1,"ASSERT ARBITRATION write stability");
   if(sh && {status_valid,status_channel,status_payload} !== {1'b1,sp})
    $fatal(1,"ASSERT ARBITRATION status stability");
   rh=rd_valid && !rd_ready; rp={rd_channel,rd_payload};
   wh=wr_valid && !wr_ready; wp={wr_channel,wr_payload};
   sh=status_valid && !status_ready; sp={status_channel,status_payload};
   if(rd_valid && rd_ready) begin
    if(rd_channel!==rptr[1:0] || rd_payload!==lane_rd_payload[rptr*69 +: 69])
     $fatal(1,"ASSERT ARBITRATION read grant bound/ownership");
    rg=rg+1; rptr=(rptr+1)&3;
   end
   if(wr_valid && wr_ready) begin
    if(wr_channel!==wptr[1:0] || wr_payload!==lane_wr_payload[wptr*137 +: 137])
     $fatal(1,"ASSERT ARBITRATION write grant bound/ownership");
    wg=wg+1; wptr=(wptr+1)&3;
   end
   if(status_valid && status_ready) begin
    if(status_channel!==sptr[1:0] || status_payload!==lane_status_payload[sptr*116 +: 116] ||
       lane_status_retire!==(4'b1<<sptr))
     $fatal(1,"ASSERT ARBITRATION completion grant bound/ownership");
    sg=sg+1; sptr=(sptr+1)&3;
   end
  end
  #1; @(negedge clk);
 end
endtask
initial begin
 rst_n=0; #0; reset_check(); tick(); tick(); rst_n=1;
 for(i=0;i<4;i=i+1) begin
  lane_rd_payload[i*69 +: 69]=69'h1234567890+i;
  lane_wr_payload[i*137 +: 137]=137'hfedcba0987654321+i;
  lane_status_payload[i*116 +: 116]=116'h112233445566778899+i;
 end
 lane_rd_valid=15; lane_wr_valid=15; lane_status_valid=15;
 rd_available=1; wr_available=1; rd_ready=1; wr_ready=1; status_ready=1;
 repeat(32) tick();
 if(rg!=32 || wg!=32 || sg!=32) $fatal(1,"ASSERT ARBITRATION four eligible coverage");
 rd_ready=0;
 repeat(16) tick();
 if(rg!=32 || wg!=48 || sg!=48)
  $fatal(1,"ASSERT ARBITRATION independent stalled read direction");
 rd_ready=1;
 for(n=0;n<128;n=n+1) begin
  wr_ready=(n%3)!=0; status_ready=(n%5)!=0; rd_ready=(n%7)!=0;
  tick();
 end
 if(rg<100 || wg<100 || sg<100) $fatal(1,"ASSERT ARBITRATION stalled comparison count");
 $display("SUMMARY ARBITRATION read=%0d write=%0d status=%0d maximum_grant_gap=4",rg,wg,sg);
 $finish;
end
endmodule
"""


def stream_bench(generation, block=65536):
    if generation == 1:
        instance = """
bellows_l1_top dut(.clk(clk),.rst_n(rst_n),.s_data(s_data),.s_valid(s_valid),
 .s_last(s_last),.s_ready(s_ready),.m_data(m_data),.m_valid(m_valid),.m_last(m_last),
 .m_ready(m_ready),.status_valid(status_valid),.status_error(status_error),
 .status_ready(status_ready));
"""
    else:
        instance = f"""
wire cs_ready,cv,cl,csv,ds_ready,dv,dl,dsv;
wire [7:0] cd,dd;
wire [2:0] cse,dse;
bellows_l2_top #(.MAX_BLOCK_BYTES({block})) dut(.clk(clk),.rst_n(rst_n),
 .roundtrip_enable(1'b0),.c_s_data(s_data),.c_s_keep(nsource!=0),
 .c_s_valid(s_valid && !decompress),.c_s_last(s_last),.c_s_ready(cs_ready),
 .c_m_data(cd),.c_m_valid(cv),.c_m_last(cl),.c_m_ready(m_ready),
 .c_status_valid(csv),.c_status_error(cse),.c_status_ready(status_ready),
 .d_s_data(s_data),.d_s_valid(s_valid && decompress),.d_s_last(s_last),
 .d_s_ready(ds_ready),.d_m_data(dd),.d_m_valid(dv),.d_m_last(dl),.d_m_ready(m_ready),
 .d_status_valid(dsv),.d_status_error(dse),.d_status_ready(status_ready));
assign s_ready=decompress ? ds_ready : cs_ready;
assign m_data=decompress ? dd : cd, m_valid=decompress ? dv : cv;
assign m_last=decompress ? dl : cl;
assign status_valid=decompress ? dsv : csv, status_error=decompress ? dse : cse;
"""
    return STREAM.replace("@INSTANCE@", instance)


STREAM = r"""
module tb;
reg clk=0; always #5 clk=~clk;
reg rst_n,s_valid=0,s_last=0,m_ready=0,status_ready=0,decompress=1;
reg [7:0] s_data=0;
wire s_ready,m_valid,m_last,status_valid;
wire [7:0] m_data;
wire [2:0] status_error;
integer nsource,nexpected;
@INSTANCE@
reg [7:0] source[0:131100],expected[0:131100];
integer file,scan,id,ch,codec,wide,cm,capacity,err,cv,sc,dc,stalls,seed,di,rf,wf;
integer ignored,i,received=0,sent=0,cases=0,bytes=0,cycles=0;
reg [63:0] address;
reg done=0,held=0,handshake;
reg [8:0] held_payload;
string vectors;
task reset_check;
 begin
  if({s_ready,m_valid,m_data,m_last,status_valid,status_error} !== '0)
   $fatal(1,"ASSERT LEGACY RESET");
 end
endtask
always @(negedge clk) if(!rst_n) reset_check();
task tick;
 begin
  @(posedge clk); handshake=s_valid && s_ready;
  if(!rst_n) reset_check();
  else begin
   cycles=cycles+1;
   if((^{s_ready,m_valid,status_valid})===1'bx) $fatal(1,"ASSERT LEGACY XZ");
   if(held && {m_valid,m_data,m_last} !== {1'b1,held_payload})
    $fatal(1,"ASSERT LEGACY output stability");
   held=m_valid && !m_ready; held_payload={m_data,m_last};
   if(handshake) sent=sent+1;
   if(m_valid && m_ready) begin
    if(received>=nexpected || m_data!==expected[received] ||
       m_last!==(received+1==nexpected))
     $fatal(1,"ASSERT LEGACY BYTE id=%0d index=%0d expected=%02h got=%02h last=%0d",
         id,received,expected[received],m_data,m_last);
    received=received+1; bytes=bytes+1;
   end
   if(status_valid && status_ready) begin
    if(status_error!==err[2:0] || (err==0 && received!=nexpected))
     $fatal(1,"ASSERT LEGACY STATUS id=%0d got=%0d expected=%0d bytes=%0d/%0d",
         id,status_error,err,received,nexpected);
    done=1;
   end
  end
  #1; @(negedge clk);
 end
endtask
initial begin
 rst_n=0; #0; reset_check(); tick(); tick(); rst_n=1; tick();
 if(!$value$plusargs("vectors=%s",vectors)) $fatal(1,"legacy vectors missing");
 file=$fopen(vectors,"r"); if(!file) $fatal(1,"legacy vectors open");
 while(!$feof(file)) begin
  scan=$fscanf(file,"%d %d %d %d %d %d %d %d %d %d %h %d %d %d %d %d %d %d\n",
    id,ch,codec,decompress,wide,cm,nsource,nexpected,capacity,err,cv,sc,dc,
    stalls,seed,di,rf,wf);
  if(scan!=18) $fatal(1,"legacy header");
  for(i=0;i<sc+dc;i=i+1) scan=$fscanf(file,"%d",ignored);
  for(i=0;i<sc+dc;i=i+1) scan=$fscanf(file,"%h",address);
  for(i=0;i<nsource;i=i+1) begin
   scan=$fscanf(file,"%h",source[i]); if(scan!=1) $fatal(1,"legacy source");
  end
  for(i=0;i<nexpected;i=i+1) begin
   scan=$fscanf(file,"%h",expected[i]); if(scan!=1) $fatal(1,"legacy expected");
  end
  sent=0; received=0; done=0; status_ready=0; m_ready=1;
  // Empty compression is a single keep=0 terminal transfer.
  for(i=0;i<(nsource==0 ? 1 : nsource);i=i+1) begin
   s_valid=1; s_data=nsource==0 ? 0 : source[i]; s_last=i+1>=nsource;
   handshake=0;
   while(!handshake) begin
    m_ready=!stalls || (cycles%5)!=0; tick();
   end
  end
  s_valid=0; s_last=0; m_ready=1;
  repeat(5) tick(); status_ready=1;
  while(!done) tick();
  if(sent!=(nsource==0 ? 1 : nsource) || (err==0 && received!=nexpected))
   $fatal(1,"ASSERT LEGACY consumption");
  cases=cases+1; $display("CASE LEGACY %0d bytes=%0d",id,received);
  tick(); tick();
 end
 if(cases==0) $fatal(1,"ASSERT LEGACY no comparisons");
 $display("SUMMARY LEGACY cases=%0d bytes=%0d",cases,bytes);
 $fclose(file); $finish;
end
endmodule
"""
