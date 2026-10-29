"""Scheduler public-port fairness and registered-selection experiments."""

from retention import write_json


TB = r"""
module tb;
  reg clk=0,rst_n;
  always #5 clk=~clk;
  reg [3:0] lane_rd_valid=15,lane_wr_valid=15,lane_status_valid=15;
  wire [255:0] lane_rd_addr={64'h12340003,64'h12340002,64'h12340001,64'h12340000};
  wire [287:0] lane_wr_payload={72'h56780003,72'h56780002,72'h56780001,72'h56780000};
  wire [463:0] lane_status_payload={116'h9abc0003,116'h9abc0002,116'h9abc0001,116'h9abc0000};
  wire [3:0] lane_rd_take,lane_wr_take,lane_status_retire;
  wire rd_valid,wr_valid,status_valid;
  wire [1:0] rd_channel,wr_channel,status_channel;
  wire [63:0] rd_addr;
  wire [71:0] wr_payload;
  wire [115:0] status_payload;
  reg rd_ready=0,wr_ready=0,status_ready=0;
  bellows_l3_scheduler dut(.*);
  wire [2:0] valids={status_valid,wr_valid,rd_valid};
  wire [2:0] readies={status_ready,wr_ready,rd_ready};
  wire [5:0] channels={status_channel,wr_channel,rd_channel};
  wire [351:0] bundles={status_payload,wr_channel,wr_payload,rd_channel,rd_addr,96'd0};
  integer grants[0:2],switches[0:2],last[0:2],stall[0:2],maximum[0:2];
  integer cycle=0,phase=0,lane,expected;
  reg [2:0] stalled=0;
  reg [1:0] held[0:2];
  reg [63:0] held_rd;
  reg [71:0] held_wr;
  reg [115:0] held_status;
  task automatic reset_check;
    if ({lane_rd_take,lane_wr_take,lane_status_retire,valids,channels,
         rd_addr,wr_payload,status_payload} !== 273'd0)
      $fatal(1,"SCHEDULER_RESET");
  endtask
  always @(posedge clk or negedge clk) if (!rst_n) reset_check();
  always @(posedge clk) begin
    cycle=cycle+1;
    if (rst_n) begin
      if ((^{lane_rd_take,lane_wr_take,lane_status_retire,valids,channels,
             rd_addr,wr_payload,status_payload})===1'bx) $fatal(1,"SCHEDULER_XZ");
      for (integer a=0;a<3;a=a+1) begin
        if (stalled[a] && (!valids[a] || channels[a*2 +: 2]!==held[a]))
          $fatal(1,"SCHEDULER_LOCK arbiter=%0d",a);
        if (valids[a] && readies[a]) begin
          lane=channels[a*2 +: 2];
          expected=phase==0 ? grants[a]%4 : 3;
          if (lane!=expected) $fatal(1,"SCHEDULER_FAIRNESS arbiter=%0d grant=%0d got=%0d expected=%0d",
                                     a,grants[a],lane,expected);
          if (last[a]>=0 && last[a]!=lane) switches[a]=switches[a]+1;
          grants[a]=grants[a]+1; last[a]=lane;
        end
        stalled[a]=valids[a] && !readies[a]; held[a]=channels[a*2 +: 2];
        if (stalled[a]) stall[a]=stall[a]+1; else stall[a]=0;
        if (stall[a]>maximum[a]) maximum[a]=stall[a];
      end
      if (stalled[0] && rd_addr!==held_rd && stall[0]>1) $fatal(1,"SCHEDULER_READ_PAYLOAD");
      if (stalled[1] && wr_payload!==held_wr && stall[1]>1) $fatal(1,"SCHEDULER_WRITE_PAYLOAD");
      if (stalled[2] && status_payload!==held_status && stall[2]>1) $fatal(1,"SCHEDULER_STATUS_PAYLOAD");
      if (rd_valid && rd_addr!==64'h12340000+rd_channel) $fatal(1,"SCHEDULER_READ_OWNER");
      if (wr_valid && wr_payload!==72'h56780000+wr_channel) $fatal(1,"SCHEDULER_WRITE_OWNER");
      if (status_valid && status_payload!==116'h9abc0000+status_channel)
        $fatal(1,"SCHEDULER_STATUS_OWNER");
      held_rd=rd_addr; held_wr=wr_payload; held_status=status_payload;
      if (cycle>10000) $fatal(1,"SCHEDULER_BOUND");
    end
  end
  always @(negedge clk) if (rst_n) begin
    rd_ready=cycle%31>=17;
    wr_ready=cycle%37>=17;
    status_ready=cycle%41>=17;
  end
  initial begin
    rst_n=0;
`ifdef VERILATOR
    #1;
`else
    #0;
`endif
    reset_check();
    for (integer a=0;a<3;a=a+1) begin
      grants[a]=0; switches[a]=0; last[a]=-1; stall[a]=0; maximum[a]=0;
    end
    repeat(3) @(negedge clk);
    #1; rst_n=1;
    wait(grants[0]>=68 && grants[1]>=68 && grants[2]>=68);
    for (integer a=0;a<3;a=a+1) begin
      if (switches[a]<64 || maximum[a]<17) $fatal(1,"SCHEDULER_COVERAGE");
    end
    @(negedge clk); #1; rst_n=0; rd_ready=0; wr_ready=0; status_ready=0; stalled=0;
    phase=1; lane_rd_valid=8; lane_wr_valid=8; lane_status_valid=8;
    for (integer a=0;a<3;a=a+1) grants[a]=0;
    repeat(3) @(negedge clk);
    #1; rst_n=1;
    wait(grants[0]>=8 && grants[1]>=8 && grants[2]>=8);
    $display("SCHEDULER_COMPLETE all_eligible_switches_min=64 four_grant_fairness=1 ineligible_skip=1");
    $finish;
  end
endmodule
"""


def execute(run):
    directory = run.path / "scheduler"
    directory.mkdir()
    tb, executable = directory / "tb.sv", directory / "simv"
    tb.write_text(TB)
    run.command(["iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
                 run.relative(executable), run.relative(tb),
                 "rtl/bellows_l3_scheduler.sv"], "scheduler-compile")
    stdout, _ = run.command(["vvp", run.relative(executable)], "scheduler-run")
    assert "SCHEDULER_COMPLETE" in stdout
    write_json(directory / "compared.json",
               {"three_independent_arbiters": True,
                "all_eligible_adjacent_switches_each_minimum": 64,
                "four_accepted_grant_fairness": True, "ineligible_skip": True})
