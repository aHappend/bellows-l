"""Interleaved command/descriptor traffic with a four-channel byte-memory oracle."""

from harnesses import top_bench
from scenarios import codec_pair


def concurrent_bench(width, *, reset_phase=None, stalled=True):
    header = top_bench(width, 65536).split("reg [7:0] source[")[0]
    setup = []
    for channel in range(4):
        codec = (0, 1, 2, 4)[channel]
        raw = bytes((i * 13 + channel) & 255 for i in range(512+32*channel))
        case = codec_pair(raw, codec, f"concurrent{channel}",
                          checksum_mode=channel % 3)[channel & 1]
        setup += [f"ns[{channel}]={len(case.source)}; nd[{channel}]={len(case.expected)};",
                  f"cm[{channel}]={case.checksum_mode}; ck[{channel}]=32'h{case.checksum_value:08x};",
                  f"co[{channel}]={codec}; de[{channel}]={case.decompress};",
                  f"wide[{channel}]={channel & 1};"]
        setup.extend(f"src[{channel}][{i}]=8'h{b:02x};" for i, b in enumerate(case.source))
        setup.extend(f"exp[{channel}][{i}]=8'h{b:02x};" for i, b in enumerate(case.expected))
    phase = -1 if reset_phase is None else reset_phase
    return header+CONCURRENT.replace("@SETUP@", "\n".join(setup)).replace(
        "@RESET_PHASE@", str(phase)).replace("@STALLED@", str(int(stalled)))


CONCURRENT = r"""
localparam integer RESET_PHASE=@RESET_PHASE@, STALLED=@STALLED@;
reg [7:0] src[0:3][0:4095],exp[0:3][0:4095],dst[0:3][0:4095];
integer ns[0:3],nd[0:3],cm[0:3],co[0:3],de[0:3],wide[0:3];
reg [31:0] ck[0:3];
integer read_bytes[0:3],write_bytes[0:3],read_grants[0:3],write_grants[0:3];
reg [3:0] admitted=0,validated=0,completed=0;
integer cycle=0,start_cycle,finish_cycle,channel,index,count,i,j,k,n;
integer read_owner,write_owner,read_size,write_size,read_index,write_index,rd_due,wr_due;
reg pr=0,pw=0,rwide,wwide;
reg [63:0] rdata,wdata;
reg [31:0] rng=17;
reg cmd_hs=0,sg_hs=0;
reg hr=0,hw=0,hs=0;
reg [70:0] rp;
reg [138:0] wp;
reg [118:0] sp;
integer total_reads=0,total_writes=0,total_status=0,epochs=0;
integer rd_snapshot,wr_snapshot;
wire rv=rd_req_valid || w_rd_req_valid;
wire wv=wr_req_valid || w_wr_req_valid;
wire rw=w_rd_req_valid,ww=w_wr_req_valid;
wire rr=rw ? w_rd_req_ready : rd_req_ready;
wire wr=ww ? w_wr_req_ready : wr_req_ready;
wire [1:0] rc=rw ? w_rd_req_channel : rd_req_channel;
wire [1:0] wc=ww ? w_wr_req_channel : wr_req_channel;
wire [63:0] ra=rw ? w_rd_req_addr : rd_req_addr;
wire [63:0] wa=ww ? w_wr_req_addr : wr_req_addr;
wire [3:0] rn=rw ? w_rd_req_bytes : 4'd1;
wire [63:0] wd=ww ? w_wr_req_data : {56'd0,wr_req_data};
wire [7:0] ws=ww ? w_wr_req_strb : 8'd1;
task reset_check;
 begin
  if({cmd_ready,sg_ready,rd_req_valid,rd_req_channel,rd_req_addr,rd_rsp_ready,
      wr_req_valid,wr_req_channel,wr_req_addr,wr_req_data,wr_rsp_ready,
      w_rd_req_valid,w_rd_req_channel,w_rd_req_addr,w_rd_req_bytes,w_rd_rsp_ready,
      w_wr_req_valid,w_wr_req_channel,w_wr_req_addr,w_wr_req_data,w_wr_req_strb,
      w_wr_rsp_ready,status_valid,status_channel,status_id,status_error,
      status_src_bytes,status_dst_bytes,status_checksum,err_checksum_mismatch} !== '0)
   $fatal(1,"ASSERT CONCURRENT RESET");
 end
endtask
always @(negedge clk) if(!rst_n) reset_check();
task tick;
 begin
  @(posedge clk); cmd_hs=cmd_valid && cmd_ready; sg_hs=sg_valid && sg_ready;
  if(!rst_n) reset_check();
  else begin
   cycle=cycle+1;
   if((^{cmd_ready,sg_ready,rv,wv,status_valid,rd_rsp_ready,wr_rsp_ready,
          w_rd_rsp_ready,w_wr_rsp_ready})===1'bx) $fatal(1,"ASSERT CONCURRENT XZ");
   if(hr && {rv,rc,rw,ra,rn} !== {1'b1,rp})
    $fatal(1,"ASSERT CONCURRENT read stability");
   if(hw && {wv,wc,ww,wa,wd,ws} !== {1'b1,wp})
    $fatal(1,"ASSERT CONCURRENT write stability");
   if(hs && {status_valid,status_channel,status_id,status_error,status_src_bytes,
       status_dst_bytes,status_checksum,err_checksum_mismatch} !== {1'b1,sp})
    $fatal(1,"ASSERT CONCURRENT completion stability");
   hr=rv && !rr; rp={rc,rw,ra,rn};
   hw=wv && !wr; wp={wc,ww,wa,wd,ws};
   hs=status_valid && !status_ready;
   sp={status_channel,status_id,status_error,status_src_bytes,status_dst_bytes,
       status_checksum,err_checksum_mismatch};
   if(rd_rsp_valid && rd_rsp_ready || w_rd_rsp_valid && w_rd_rsp_ready) begin
    if(!pr || cycle<=rd_due) $fatal(1,"ASSERT CONCURRENT response/read ownership");
    pr=0; read_bytes[read_owner]=read_bytes[read_owner]+read_size;
   end
   if(wr_rsp_valid && wr_rsp_ready || w_wr_rsp_valid && w_wr_rsp_ready) begin
    if(!pw || cycle<=wr_due) $fatal(1,"ASSERT CONCURRENT response/write ownership");
    pw=0;
    for(k=0;k<write_size;k=k+1) begin
     if(wdata[k*8 +: 8] !== exp[write_owner][write_index+k])
      $fatal(1,"ASSERT CONCURRENT BYTE channel=%0d index=%0d",write_owner,write_index+k);
     dst[write_owner][write_index+k]=wdata[k*8 +: 8];
    end
    write_bytes[write_owner]=write_bytes[write_owner]+write_size;
   end
   if(rv && rr) begin
    if(pr || rd_req_valid && w_rd_req_valid || !validated[rc] || completed[rc] ||
       rw!==wide[rc][0] || ra<4099+rc*65536 ||
       ra+rn>4099+rc*65536+ns[rc] || rn<1 || rn>(rw ? WIDTH : 1))
     $fatal(1,"ASSERT CONCURRENT READ OWNERSHIP/BOUNDS");
    read_owner=rc; read_size=rn; read_index=ra-(4099+rc*65536);
    if(read_index!=read_bytes[rc]) $fatal(1,"ASSERT CONCURRENT source consumption");
    rdata=64'hdeadbeefcafebabe;
    for(k=0;k<rn;k=k+1) rdata[k*8 +: 8]=src[rc][read_index+k];
    pr=1; rwide=rw; rd_due=cycle;
    read_grants[rc]=read_grants[rc]+1; total_reads=total_reads+1;
   end
   if(wv && wr) begin
    count=0; for(k=0;k<8;k=k+1) if(ws[k]) count=count+1;
    if(pw || wr_req_valid && w_wr_req_valid || !validated[wc] || completed[wc] ||
       ww!==wide[wc][0] || wa<1048579+wc*65536 ||
       wa+count>1048579+wc*65536+nd[wc] || count<1 || count>(ww ? WIDTH : 1) ||
       ws!==((8'd1<<count)-8'd1) || (count<8 && (wd>>(count*8))!==64'd0))
     $fatal(1,"ASSERT CONCURRENT WRITE OWNERSHIP/BOUNDS/TAIL");
    write_owner=wc; write_size=count; write_index=wa-(1048579+wc*65536);
    if(write_index!=write_bytes[wc]) $fatal(1,"ASSERT CONCURRENT destination consumption");
    wdata=wd; pw=1; wwide=ww; wr_due=cycle;
    write_grants[wc]=write_grants[wc]+1; total_writes=total_writes+1;
   end
   if(status_valid && status_ready) begin
    channel=status_channel;
    if(!admitted[channel] || completed[channel] || status_id!==16'(101+channel) ||
       status_error!==0 || status_checksum!==ck[channel] || err_checksum_mismatch!==0 ||
       status_src_bytes!==ns[channel] || status_src_bytes!==read_bytes[channel] ||
       status_dst_bytes!==nd[channel] || status_dst_bytes!==write_bytes[channel] ||
       (pr && read_owner==channel) || (pw && write_owner==channel))
     $fatal(1,"ASSERT CONCURRENT STATUS channel=%0d",channel);
    for(k=0;k<nd[channel];k=k+1)
     if(dst[channel][k]!==exp[channel][k]) $fatal(1,"ASSERT CONCURRENT full output");
    completed[channel]=1; total_status=total_status+1; finish_cycle=cycle;
   end
  end
  #1;
  rng=(rng<<1)^(rng[31] ? 32'h00400007 : 0);
  rd_req_ready=!STALLED || rng[0]; w_rd_req_ready=!STALLED || rng[1];
  wr_req_ready=!STALLED || rng[2]; w_wr_req_ready=!STALLED || rng[3];
  status_ready=!STALLED || rng[4];
  rd_rsp_valid=pr && !rwide && (!STALLED || rng[5] || rd_rsp_valid);
  w_rd_rsp_valid=pr && rwide && (!STALLED || rng[6] || w_rd_rsp_valid);
  wr_rsp_valid=pw && !wwide && (!STALLED || rng[7] || wr_rsp_valid);
  w_wr_rsp_valid=pw && wwide && (!STALLED || rng[8] || w_wr_rsp_valid);
  rd_rsp_data=rdata[7:0]; w_rd_rsp_data=rdata;
  @(negedge clk);
 end
endtask
task abort_epoch;
 begin
  rst_n=0; cmd_valid=0; sg_valid=0; pr=0; pw=0; hr=0; hw=0; hs=0;
  rd_rsp_valid=0; w_rd_rsp_valid=0; wr_rsp_valid=0; w_wr_rsp_valid=0;
  admitted=0; validated=0; completed=0;
  total_status=0; total_reads=0; total_writes=0;
  for(j=0;j<4;j=j+1) begin
   read_bytes[j]=0; write_bytes[j]=0; read_grants[j]=0; write_grants[j]=0;
  end
  #1; reset_check(); tick(); tick(); rst_n=1; tick();
 end
endtask
task commands;
 begin
  for(i=0;i<4;i=i+1) begin
   cmd_channel=i; cmd_id=101+i; cmd_codec=co[i]; cmd_wide=wide[i];
   cmd_decompress=de[i]; cmd_checksum_mode=cm[i]; cmd_src_bytes=ns[i];
   cmd_dst_capacity=nd[i]; cmd_src_segments=1; cmd_dst_segments=1;
   cmd_valid=1; cmd_hs=0;
   while(!cmd_hs) tick();
   admitted[i]=1; cmd_valid=0;
  end
 end
endtask
task descriptors;
 input integer partial;
 begin
  for(n=0;n<2;n=n+1) begin
   for(i=3;i>=0;i=i-1) begin
    sg_channel=i; sg_destination=n; sg_valid=1;
    sg_addr=n ? 1048579+i*65536 : 4099+i*65536;
    sg_bytes=n ? nd[i] : ns[i]; sg_hs=0;
    while(!sg_hs) tick();
    sg_valid=0;
    if(n) validated[i]=1;
   end
   if(partial) n=2;
  end
 end
endtask
initial begin
 @SETUP@
 rst_n=0; #0; reset_check(); abort_epoch(); start_cycle=cycle; commands();
 if(admitted!==4'b1111) $fatal(1,"ASSERT CONCURRENT four live admissions");
 if(RESET_PHASE==0) begin abort_epoch(); epochs=epochs+1; commands(); end
 if(RESET_PHASE==1) begin
  descriptors(1); abort_epoch(); epochs=epochs+1; commands();
 end
 descriptors(0);
 if(RESET_PHASE>=2) begin
  if(RESET_PHASE==2) begin while(!pr) tick(); end
  if(RESET_PHASE==3) begin while(!pw) tick(); end
  if(RESET_PHASE==4) begin while(!(total_reads>32 && total_writes>16)) tick(); end
  if(RESET_PHASE==5) begin
   status_ready=0;
   while(!status_valid) begin tick(); status_ready=0; end
  end
  abort_epoch(); epochs=epochs+1; commands(); descriptors(0);
 end
 while(completed!=15) tick();
 for(i=0;i<4;i=i+1)
  if(read_grants[i]==0 || write_grants[i]==0)
   $fatal(1,"ASSERT CONCURRENT unserviced channel");
 if(total_status!=4) $fatal(1,"ASSERT CONCURRENT unexpected completion epoch");
 // Reuse all four channels after retiring their statuses, without reset.
 admitted=0; validated=0; completed=0;
 for(j=0;j<4;j=j+1) begin read_bytes[j]=0; write_bytes[j]=0; end
 tick(); commands(); descriptors(0);
 while(completed!=15) tick();
 if(total_status!=8) $fatal(1,"ASSERT CONCURRENT channel reuse");
 $display("SUMMARY CONCURRENT width=%0d completions=%0d resets=%0d reads=%0d writes=%0d bytes=%0d cycles=%0d",
   WIDTH,total_status,epochs,total_reads,total_writes,2*(nd[0]+nd[1]+nd[2]+nd[3]),
   finish_cycle-start_cycle+1);
 $finish;
end
endmodule
"""
