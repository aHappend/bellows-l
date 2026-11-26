"""Cross-direction DMA errors: hidden work must cancel, public work must settle.

All preconditions and accounting use top-level handshakes. Four directed cases
cross read/write with hidden/publicly-stalled requests; no DUT internals are read.
"""

import re

import oracle
from retention import write_json
from transactor import BENCH


BODY = r"""
  integer scenario,cycle=0,violations=0,failed=0,error_cycle=0;
  integer ids[0:3],nr[0:3],nw[0:3],cr[0:3],aw[0:3],done[0:3];
  integer commands=0,statuses=0,r_owner,w_owner,r_index,w_index;
  integer r_edge,w_edge,first_bad_cycle=0,settled_after_error=0;
  integer public_stall_cycles=0,hidden_cycles=0,reuse=0,blocker_progress=0;
  reg rbusy=0,wbusy=0,previous_r=0,previous_w=0,previous_s=0;
  reg [65:0] held_r,allowed_r;
  reg [73:0] held_w,allowed_w;
  reg [118:0] held_s;
  reg allow_r=0,allow_w=0;
  reg [7:0] pending_w_data;
  reg [63:0] pending_w_address;
  wire [65:0] r_bundle={rd_req_channel,rd_req_addr};
  wire [73:0] w_bundle={wr_req_channel,wr_req_addr,wr_req_data};
  wire [118:0] s_bundle={status_channel,status_id,status_error,status_src_bytes,
                        status_dst_bytes,status_checksum,err_checksum_mismatch};

  function automatic [7:0] source_byte(input integer id,input integer index);
    begin
      source_byte=0;
      case(id)
@SOURCE_CASES@
        default: $fatal(1,"SETTLEMENT_UNKNOWN_SOURCE_ID");
      endcase
    end
  endfunction
  function automatic [7:0] content_byte(input integer id,input integer index);
    begin
      content_byte=0;
      case(id)
@CONTENT_CASES@
        default: $fatal(1,"SETTLEMENT_UNKNOWN_CONTENT_ID");
      endcase
    end
  endfunction
  function automatic integer source_length(input integer id);
    source_length=id==100 ? 9 : 2;
  endfunction
  function automatic integer content_length(input integer id);
    content_length=id==100 ? 8 : 1;
  endfunction
  function automatic [63:0] source_base(input integer lane);
    source_base=64'h1000+lane*64'h1000;
  endfunction
  function automatic [63:0] destination_base(input integer lane);
    destination_base=64'h10000+lane*64'h1000;
  endfunction
  task automatic reset_check;
    if(all_outputs !== 266'd0) $fatal(1,"SETTLEMENT_RESET");
  endtask
  always @(posedge clk or negedge clk) if(!rst_n) reset_check();

  always @(posedge clk) begin
    cycle=cycle+1;
    if(cycle>20000)
      $fatal(1,"SETTLEMENT_EVENT_BOUND scenario=%0d victim_requests=%0d/%0d victim_responses=%0d/%0d pending=%0d/%0d owners=%0d/%0d public=%0d/%0d",
             scenario,nr[1],nw[1],cr[1],aw[1],rbusy,wbusy,r_owner,w_owner,
             rd_req_valid,wr_req_valid);
    if(rst_n) begin
      if((^all_outputs)===1'bx) $fatal(1,"SETTLEMENT_XZ");
      if(previous_r && (!rd_req_valid || r_bundle!==held_r))
        $fatal(1,"SETTLEMENT_PUBLIC_READ_WITHDRAWN");
      if(previous_w && (!wr_req_valid || w_bundle!==held_w))
        $fatal(1,"SETTLEMENT_PUBLIC_WRITE_WITHDRAWN");
      if(previous_s && (!status_valid || s_bundle!==held_s))
        $fatal(1,"SETTLEMENT_STATUS_STABILITY");
      if(err_checksum_mismatch !== (status_valid && status_error==7))
        $fatal(1,"SETTLEMENT_CHECKSUM_FLAG");
      if(failed && rd_req_valid && rd_req_channel==1 &&
         !(allow_r && r_bundle===allowed_r) && !previous_r) begin
        violations=violations+1;
        if(first_bad_cycle==0) first_bad_cycle=cycle;
        $display("POST_ERROR_FIRST_PRESENTATION scenario=%0d direction=read cycle=%0d error_cycle=%0d address=%h",
                 scenario,cycle,error_cycle,rd_req_addr);
      end
      if(failed && wr_req_valid && wr_req_channel==1 &&
         !(allow_w && w_bundle===allowed_w) && !previous_w) begin
        violations=violations+1;
        if(first_bad_cycle==0) first_bad_cycle=cycle;
        $display("POST_ERROR_FIRST_PRESENTATION scenario=%0d direction=write cycle=%0d error_cycle=%0d address=%h",
                 scenario,cycle,error_cycle,wr_req_addr);
      end
      if(cmd_valid && cmd_ready) begin
        if(ids[cmd_channel]!=0 && done[cmd_channel]==0)
          $fatal(1,"SETTLEMENT_COMMAND_BUSY");
        ids[cmd_channel]=cmd_id; nr[cmd_channel]=0; nw[cmd_channel]=0;
        cr[cmd_channel]=0; aw[cmd_channel]=0; done[cmd_channel]=0;
        commands=commands+1;
        if(cmd_id==201) begin
          failed=0; allow_r=0; allow_w=0;
        end
      end
      if(rd_req_valid && rd_req_ready) begin
        if(rbusy) $fatal(1,"SETTLEMENT_READ_OUTSTANDING");
        r_owner=rd_req_channel; r_index=nr[r_owner];
        if(ids[r_owner]==0 || done[r_owner] ||
           r_index>=source_length(ids[r_owner]) ||
           rd_req_addr!==source_base(r_owner)+r_index)
          $fatal(1,"SETTLEMENT_READ_ADDRESS");
        nr[r_owner]=nr[r_owner]+1; rbusy=1; r_edge=cycle;
        if(allow_r && rd_req_channel==1) allow_r=0;
      end
      if(wr_req_valid && wr_req_ready) begin
        if(wbusy) $fatal(1,"SETTLEMENT_WRITE_OUTSTANDING");
        w_owner=wr_req_channel; w_index=nw[w_owner];
        if(ids[w_owner]==0 || done[w_owner] ||
           w_index>=content_length(ids[w_owner]) ||
           wr_req_addr!==destination_base(w_owner)+w_index ||
           wr_req_data!==content_byte(ids[w_owner],w_index))
          $fatal(1,"SETTLEMENT_WRITE_ADDRESS_OR_CONTENT");
        pending_w_data=wr_req_data; pending_w_address=wr_req_addr;
        nw[w_owner]=nw[w_owner]+1; wbusy=1; w_edge=cycle;
        if(allow_w && wr_req_channel==1) allow_w=0;
      end
      if(rd_rsp_valid && rd_rsp_ready) begin
        if(!rbusy || cycle<=r_edge) $fatal(1,"SETTLEMENT_UNISSUED_READ_RESPONSE");
        cr[r_owner]=cr[r_owner]+1;
        if(failed && r_owner==1) settled_after_error=settled_after_error+1;
        if(rd_rsp_error) begin
          if(r_owner!=1 || failed || scenario%2!=1)
            $fatal(1,"SETTLEMENT_WRONG_READ_ERROR");
          failed=1; error_cycle=cycle;
          allow_w=wr_req_valid && !wr_req_ready && wr_req_channel==1;
          allowed_w=w_bundle;
        end
        rbusy=0;
      end
      if(wr_rsp_valid && wr_rsp_ready) begin
        if(!wbusy || cycle<=w_edge) $fatal(1,"SETTLEMENT_UNISSUED_WRITE_RESPONSE");
        if(!wr_rsp_error) begin
          if(pending_w_address!==destination_base(w_owner)+aw[w_owner] ||
             pending_w_data!==content_byte(ids[w_owner],aw[w_owner]))
            $fatal(1,"SETTLEMENT_ACKNOWLEDGED_CONTENT");
          aw[w_owner]=aw[w_owner]+1;
        end
        if(failed && w_owner==1) settled_after_error=settled_after_error+1;
        if(wr_rsp_error) begin
          if(w_owner!=1 || failed || scenario%2!=0)
            $fatal(1,"SETTLEMENT_WRONG_WRITE_ERROR");
          failed=1; error_cycle=cycle;
          allow_r=rd_req_valid && !rd_req_ready && rd_req_channel==1;
          allowed_r=r_bundle;
        end
        wbusy=0;
      end
      if(status_valid && status_ready) begin
        if(ids[status_channel]==0 || done[status_channel] ||
           status_id!==ids[status_channel] ||
           status_error!==(ids[status_channel]==100 ? 4'd10 : 4'd0) ||
           status_src_bytes!==cr[status_channel] ||
           status_dst_bytes!==aw[status_channel] || status_checksum!==0 ||
           (rbusy && r_owner==status_channel) ||
           (wbusy && w_owner==status_channel) ||
           (status_channel==1 && (allow_r || allow_w)))
          $fatal(1,"SETTLEMENT_COMPLETION scenario=%0d id=%0d error=%0d src=%0d/%0d dst=%0d/%0d",
                 scenario,status_id,status_error,status_src_bytes,cr[status_channel],
                 status_dst_bytes,aw[status_channel]);
        if(status_id!=100 &&
           (cr[status_channel]!=source_length(status_id) ||
            aw[status_channel]!=content_length(status_id)))
          $fatal(1,"SETTLEMENT_SUCCESS_LENGTH");
        done[status_channel]=1; statuses=statuses+1;
        if(status_id==101) blocker_progress=blocker_progress+1;
        if(status_id==201) reuse=reuse+1;
        $display("SETTLEMENT_COMPLETION scenario=%0d id=%0d error=%0d reads=%0d writes=%0d",
                 scenario,status_id,status_error,status_src_bytes,status_dst_bytes);
      end
      previous_r=rd_req_valid && !rd_req_ready; held_r=r_bundle;
      previous_w=wr_req_valid && !wr_req_ready; held_w=w_bundle;
      previous_s=status_valid && !status_ready; held_s=s_bundle;
    end
  end

  task automatic command(input integer lane,input integer id);
    @(negedge clk);
    cmd_valid=1; cmd_channel=lane; cmd_id=id; cmd_decompress=1;
    cmd_src_bytes=source_length(id); cmd_dst_capacity=content_length(id);
    cmd_src_segments=1; cmd_dst_segments=1;
    do @(posedge clk); while(!cmd_ready);
    @(negedge clk); cmd_valid=0;
    for(integer d=0;d<2;d=d+1) begin
      sg_valid=1; sg_channel=lane; sg_destination=d;
      sg_addr=d ? destination_base(lane) : source_base(lane);
      sg_bytes=d ? content_length(id) : source_length(id);
      do @(posedge clk); while(!sg_ready);
      @(negedge clk); sg_valid=0;
    end
  endtask
  task automatic take_read(input integer lane,input integer index);
    wait(rd_req_valid);
    @(negedge clk);
    if(!rd_req_valid || rd_req_channel!=lane ||
       rd_req_addr!==source_base(lane)+index)
      $fatal(1,"SETTLEMENT_READ_PRECONDITION scenario=%0d lane=%0d index=%0d got=%0d/%h",
             scenario,lane,index,rd_req_channel,rd_req_addr);
    rd_req_ready=1;
    @(posedge clk); @(negedge clk); rd_req_ready=0;
  endtask
  task automatic respond_read(input integer error);
    @(negedge clk);
    if(!rbusy) $fatal(1,"SETTLEMENT_READ_RESPONSE_PRECONDITION");
    rd_rsp_valid=1; rd_rsp_data=source_byte(ids[r_owner],r_index); rd_rsp_error=error;
    do @(posedge clk); while(!rd_rsp_ready);
    @(negedge clk); rd_rsp_valid=0; rd_rsp_error=0;
  endtask
  task automatic take_write(input integer lane);
    wait(wr_req_valid);
    @(negedge clk);
    if(!wr_req_valid || wr_req_channel!=lane)
      $fatal(1,"SETTLEMENT_WRITE_PRECONDITION");
    wr_req_ready=1;
    @(posedge clk); @(negedge clk); wr_req_ready=0;
  endtask
  task automatic respond_write(input integer error);
    @(negedge clk);
    if(!wbusy) $fatal(1,"SETTLEMENT_WRITE_RESPONSE_PRECONDITION");
    wr_rsp_valid=1; wr_rsp_error=error;
    do @(posedge clk); while(!wr_rsp_ready);
    @(negedge clk); wr_rsp_valid=0; wr_rsp_error=0;
  endtask
  task automatic drain(input integer target);
    while(statuses<target) begin
      @(negedge clk);
      rd_req_ready=1; wr_req_ready=1; status_ready=1;
      rd_rsp_valid=rbusy; rd_rsp_error=0;
      if(rbusy) rd_rsp_data=source_byte(ids[r_owner],r_index);
      wr_rsp_valid=wbusy; wr_rsp_error=0;
    end
    @(negedge clk);
    rd_req_ready=0; wr_req_ready=0; status_ready=0;
    rd_rsp_valid=0; wr_rsp_valid=0;
    if(rbusy || wbusy) $fatal(1,"SETTLEMENT_NOT_DRAINED");
  endtask

  initial begin
    if(!$value$plusargs("scenario=%d",scenario) || scenario<0 || scenario>3)
      $fatal(1,"SETTLEMENT_SCENARIO_ARGUMENT");
    for(integer lane=0;lane<4;lane=lane+1) begin
      ids[lane]=0; nr[lane]=0; nw[lane]=0; cr[lane]=0; aw[lane]=0; done[lane]=0;
    end
    rst_n=0; #1; reset_check();
    repeat(3) @(negedge clk);
    #1; rst_n=1;
    if(scenario==0) begin
      command(1,100);
      take_read(1,0); respond_read(0);
      take_read(1,1); respond_read(0);
      take_read(1,2);
      command(0,101);
      repeat(40) @(negedge clk);
      respond_read(0);
      take_read(0,0);
      take_write(1);
      repeat(40) begin
        @(negedge clk);
        if(!rbusy || r_owner!=0 || !wbusy || w_owner!=1 ||
           rd_req_valid || nr[1]!=3 || cr[1]!=3 || nw[1]!=1)
          $fatal(1,"SETTLEMENT_HIDDEN_READ_PRECONDITION");
        hidden_cycles=hidden_cycles+1;
      end
      respond_write(1);
      respond_read(0);
    end else if(scenario==1) begin
      command(0,101);
      take_read(0,0); respond_read(0);
      take_read(0,1); respond_read(0);
      take_write(0);
      command(1,100);
      take_read(1,0); respond_read(0);
      take_read(1,1); respond_read(0);
      take_read(1,2); respond_read(0);
      take_read(1,3);
      repeat(40) begin
        @(negedge clk);
        if(!wbusy || w_owner!=0 || !rbusy || r_owner!=1 ||
           wr_req_valid || cr[1]!=3 || nr[1]!=4 || nw[1]!=0)
          $fatal(1,"SETTLEMENT_HIDDEN_WRITE_PRECONDITION");
        hidden_cycles=hidden_cycles+1;
      end
      respond_read(1);
      respond_write(0);
    end else begin
      command(1,100);
      take_read(1,0); respond_read(0);
      take_read(1,1); respond_read(0);
      take_read(1,2); respond_read(0);
      if(scenario==2) begin
        take_write(1);
        wait(rd_req_valid && rd_req_channel==1);
      end else begin
        take_read(1,3);
        wait(wr_req_valid && wr_req_channel==1);
      end
      repeat(40) begin
        @(negedge clk);
        if(scenario==2 ?
           (!rd_req_valid || rd_req_ready || rd_req_channel!=1 ||
            !wbusy || w_owner!=1 || nr[1]!=3 || cr[1]!=3) :
           (!wr_req_valid || wr_req_ready || wr_req_channel!=1 ||
            !rbusy || r_owner!=1 || cr[1]!=3 || nr[1]!=4 || nw[1]!=0))
          $fatal(1,"SETTLEMENT_PUBLIC_STALL_PRECONDITION");
        public_stall_cycles=public_stall_cycles+1;
      end
      if(scenario==2) respond_write(1); else respond_read(1);
      repeat(17) begin
        @(negedge clk);
        if(scenario==2 ? (!rd_req_valid || r_bundle!==allowed_r) :
                         (!wr_req_valid || w_bundle!==allowed_w))
          $fatal(1,"SETTLEMENT_POST_ERROR_PUBLIC_STALL");
        public_stall_cycles=public_stall_cycles+1;
      end
    end
    drain(scenario<2 ? 2 : 1);
    if(!failed || error_cycle==0 || !done[1] ||
       (scenario<2 && (blocker_progress!=1 || hidden_cycles!=40)) ||
       (scenario>=2 && (public_stall_cycles!=57 || settled_after_error!=1)))
      $fatal(1,"SETTLEMENT_MISSING_MEASURED_COVERAGE");
    command(1,201);
    drain(scenario<2 ? 3 : 2);
    repeat(32) @(negedge clk);
    if(status_valid || rd_req_valid || wr_req_valid || rbusy || wbusy ||
       commands!=statuses || reuse!=1)
      $fatal(1,"SETTLEMENT_REUSE_OR_DUPLICATE_COMPLETION");
    $display("SETTLEMENT_OBSERVED scenario=%0d violations=%0d hidden_cycles=%0d public_stall_cycles=%0d settled_after_error=%0d blocker_progress=%0d reuse=%0d commands=%0d completions=%0d error_cycle=%0d first_bad_cycle=%0d",
             scenario,violations,hidden_cycles,public_stall_cycles,settled_after_error,
             blocker_progress,reuse,commands,statuses,error_cycle,first_bad_cycle);
    if(violations!=0) $fatal(1,"HIDDEN_RESERVATION_ERROR_SETTLEMENT");
    $finish;
  end
endmodule
"""


def execute(run):
    directory = run.path / "hidden-reservation-error-settlement"
    directory.mkdir()
    prefix = BENCH.split("  integer inp,", 1)[0].replace("@BLOCK@", "16").replace("@SG@", "3")
    contents = {100: b"abcdefgh", 101: b"Z", 201: b"R"}
    wires = {identifier: oracle.literals(content) for identifier, content in contents.items()}
    for identifier, wire in wires.items():
        assert oracle.decode(wire) == contents[identifier]

    def cases(values):
        return "\n".join(
            f"        {identifier}: case(index)\n" +
            "\n".join(f"          {index}: {name}=8'h{value:02x};"
                      for index, value in enumerate(data)) +
            '\n          default: $fatal(1,"SETTLEMENT_REFERENCE_BOUNDS");\n        endcase'
            for identifier, (name, data) in values.items())

    body = BODY.replace("@SOURCE_CASES@", cases(
        {identifier: ("source_byte", wire) for identifier, wire in wires.items()}))
    body = body.replace("@CONTENT_CASES@", cases(
        {identifier: ("content_byte", data) for identifier, data in contents.items()}))
    tb, executable = directory / "tb.sv", directory / "simv"
    tb.write_text(prefix + body)
    write_json(directory / "oracle.json",
               {str(i): {"source_hex": wires[i].hex(), "content_hex": c.hex()}
                for i, c in contents.items()})
    rtl = [run.relative(p) for p in sorted(run.root.glob("rtl/*.sv"))]
    run.command(["verilator", "--binary", "--timing", "-Wno-fatal",
                 "--top-module", "tb", "--Mdir", run.relative(directory / "compile-obj"),
                 "-o", "../simv", "-j", "2", run.relative(tb), *rtl],
                "settlement-compile-verilator")
    rows = []
    for scenario, name in enumerate(("hidden-read", "hidden-write",
                                     "public-stalled-read", "public-stalled-write")):
        stdout, _ = run.command([run.relative(executable), f"+scenario={scenario}"],
                                f"settlement-{name}", expected=(0, 1, -6))
        match = re.search(r"^SETTLEMENT_OBSERVED (.+)$", stdout, re.MULTILINE)
        if match is None:
            raise AssertionError(f"{name}: missing completed functional comparisons; see raw log")
        row = {key: int(value) for key, value in
               (field.split("=") for field in match[1].split())}
        assert row["scenario"] == scenario
        row["name"] = name
        row["outcome"] = "failed" if row["violations"] else "passed"
        row["raw_stdout"] = run.receipt["commands"][-1]["stdout"]
        rows.append(row)
        write_json(directory / "compared.json", {"required_cases": 4, "cases": rows})
        if row["violations"]:
            assert "HIDDEN_RESERVATION_ERROR_SETTLEMENT" in stdout
            assert run.receipt["commands"][-1]["exit"] != 0
        else:
            assert run.receipt["commands"][-1]["exit"] == 0
    assert len(rows) == 4 and sum(row["violations"] for row in rows) == 0, (
        "hidden-reservation-error-settlement: first public DMA presentation after "
        "opposite-direction error", rows)
    return rows
