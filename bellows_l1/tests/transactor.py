"""Generated Icarus transactor: public pins only, pre-edge scoreboarding."""


BODY = r"""
`timescale 1ns/1ps
module tb;
  reg clk = 0;
  reg rst_n;
  reg [7:0] s_data = 0;
  reg s_valid = 0, s_last = 0, m_ready = 0, status_ready = 0;
  wire s_ready, m_valid, m_last, status_valid;
  wire [7:0] m_data;
  wire [2:0] status_error;
  bellows_l1_top dut(
    .clk(clk), .rst_n(rst_n), .s_data(s_data), .s_valid(s_valid),
    .s_last(s_last), .s_ready(s_ready), .m_data(m_data), .m_valid(m_valid),
    .m_last(m_last), .m_ready(m_ready), .status_valid(status_valid),
    .status_error(status_error), .status_ready(status_ready)
  );
  always #5 clk = ~clk;
  reg [7:0] compressed [0:@INPUT_MAX@];
  reg [7:0] expected [0:@OUTPUT_MAX@];
  integer mode, seed, rng, cycle_count = 0;
  integer ledger;
  integer nin, nout, wanted_error, special, order_kind, detection;
  integer inputs_seen, outputs_seen, statuses_seen, boundary_cycle;
  integer error_cycle, final_cycle, status_cycle, literal_cycle;
  integer match_offset_cycle;
  integer empty_status_due;
  integer output_stalls, status_stalls, discard_beats, discard_gaps;
  integer burst_remaining, bursts_seen, longest_stall, current_stall;
  integer status_age, boundary_age, comparisons, case_index = -1;
  integer status_total = 0, abort_total = 0, completed_cases = 0;
  integer coincidences = 0;
  integer previous_status_cycle = -100, back_to_back = 0;
  reg active_case = 0, boundary_seen = 0, detected = 0;
  reg old_out_stall = 0, old_status_stall = 0, old_input_stall = 0;
  reg [7:0] old_data, old_input;
  reg old_last, old_input_last;
  reg [2:0] old_error;
  reg transferred_input;
  reg [31:0] random_state;

  function automatic [31:0] next_random(input [31:0] value);
    reg [31:0] x;
    begin
      x = value ^ (value << 13);
      x = x ^ (x >> 17);
      next_random = x ^ (x << 5);
    end
  endfunction

  task automatic fail(input string message);
    begin
      $display("MISMATCH case=%0d cycle=%0d input=%0d output=%0d %s",
               case_index, cycle_count, inputs_seen, outputs_seen, message);
      $fatal(1, "byte/status/protocol scoreboard rejected");
    end
  endtask

  task automatic public_checks;
    begin
      if ((^{s_ready,m_valid,m_data,m_last,status_valid,status_error}) === 1'bx)
        fail("X/Z on public output");
      if (!rst_n) begin
        if ({s_ready,m_valid,m_data,m_last,status_valid,status_error} !== 16'd0)
          fail("reset outputs not zero");
      end else begin
        if (!m_valid && {m_data,m_last} !== 9'd0)
          fail("inactive output payload");
        if (!status_valid && status_error !== 3'd0)
          fail("inactive status error");
      end
    end
  endtask

  // Includes Active-region t=5 sampling, before any nonblocking updates.
  always @(posedge clk or negedge clk) begin
    if (rst_n === 1'b0 || rst_n === 1'b1)
      public_checks();
  end

  task automatic step(input reg sv, input [7:0] sd, input reg sl,
                      input reg mr, input reg sr);
    begin
      @(negedge clk);
      s_valid = sv; s_data = sd; s_last = sl;
      m_ready = mr; status_ready = sr;
      #1;
      public_checks();
      @(posedge clk);
      public_checks();
      cycle_count = cycle_count + 1;
      transferred_input = 0;
      if (rst_n && active_case) begin
        if (old_out_stall &&
            {m_valid,m_data,m_last} !== {1'b1,old_data,old_last})
          fail("output changed while stalled");
        if (old_status_stall &&
            {status_valid,status_error} !== {1'b1,old_error})
          fail("status changed while stalled");
        if (old_input_stall &&
            {s_valid,s_data,s_last} !== {1'b1,old_input,old_input_last})
          fail("source transactor broke stability");
        if (boundary_seen && s_ready !== 1'b0)
          fail("input ready before completion acceptance");
        if (detected && !boundary_seen && s_ready !== 1'b1)
          fail("discard readiness depends on backpressure");
        if (detected && !boundary_seen && !s_valid)
          discard_gaps = discard_gaps + 1;
        // Check status before counting this edge's output/boundary transfers.
        if (status_valid) begin
          if (!boundary_seen || outputs_seen != nout)
            fail("status before boundary and complete output retirement");
          if (status_error !== wanted_error[2:0])
            fail($sformatf("status got=%0d expected=%0d",status_error,wanted_error));
          if (status_cycle < 0) status_cycle = cycle_count;
          if (!status_ready) status_stalls = status_stalls + 1;
        end
        if (m_valid) begin
          if (outputs_seen >= nout) fail("unexpected extra output");
          if (m_data !== expected[outputs_seen])
            fail($sformatf("byte got=%02x expected=%02x",
                          m_data,expected[outputs_seen]));
          if (m_last !== (outputs_seen == nout-1))
            fail("last position mismatch");
          if (nin == 2 && nout == 1 && !special &&
              cycle_count < literal_cycle + 3)
            fail("literal bypassed registered candidate/finish schedule");
          if (nin == 5 && nout == 5 && !special && wanted_error == 0 &&
              compressed[0] == 8'h10 && compressed[2] == 8'h01 &&
              compressed[3] == 8'h00 && compressed[4] == 8'h00) begin
            if (cycle_count < match_offset_cycle+3+2*outputs_seen)
              fail("match bypassed read/commit/dependent-read schedule");
            if (mode == 0 &&
                cycle_count != match_offset_cycle+3+2*outputs_seen)
              fail("unstalled match cycle contract");
          end
          comparisons = comparisons + 1;
          if (m_ready) begin
            outputs_seen = outputs_seen + 1;
            if (m_last) final_cycle = cycle_count;
          end else output_stalls = output_stalls + 1;
        end
        if (m_valid && !m_ready) begin
          current_stall = current_stall + 1;
          if (current_stall > longest_stall) longest_stall = current_stall;
        end else current_stall = 0;
        if (s_valid && s_ready) begin
          transferred_input = 1;
          if (inputs_seen >= nin) fail("extra input accepted");
          if (s_data !== compressed[inputs_seen]) fail("source byte mismatch");
          if (inputs_seen == 0 && cycle_count == previous_status_cycle+1)
            back_to_back = back_to_back + 1;
          if (detected) discard_beats = discard_beats + 1;
          if (inputs_seen == detection && !s_last) begin
            detected = 1; error_cycle = cycle_count;
          end
          if (nin == 2 && nout == 1 && inputs_seen == 1)
            literal_cycle = cycle_count;
          if (inputs_seen == 3) match_offset_cycle = cycle_count;
          inputs_seen = inputs_seen + 1;
          if (s_last) begin
            boundary_seen = 1;
            boundary_cycle = cycle_count;
          end
        end
        if (status_valid && status_ready) begin
          statuses_seen = statuses_seen + 1;
          status_total = status_total + 1;
          previous_status_cycle = cycle_count;
          if (statuses_seen != 1) fail("duplicate completion");
        end
        old_out_stall = m_valid && !m_ready;
        old_data = m_data; old_last = m_last;
        old_status_stall = status_valid && !status_ready;
        old_error = status_error;
        old_input_stall = s_valid && !s_ready;
        old_input = s_data; old_input_last = s_last;
      end else if (rst_n && (m_valid || status_valid)) begin
        fail("output or status outside an active block");
      end
      #1;
      public_checks();
      if (rst_n && active_case && statuses_seen == 1 && s_ready !== 1'b1)
        fail("next-block readiness did not resume after status edge");
      if (rst_n && active_case && !statuses_seen && boundary_seen) begin
        if (nout > 0 && final_cycle >= 0 && status_valid !== 1'b1)
          fail("status not asserted immediately after later completion edge");
        if (nout == 0) begin
          empty_status_due = boundary_cycle + 1;
          if (detected) begin
            empty_status_due = error_cycle + 1;
            if (boundary_cycle > empty_status_due)
              empty_status_due = boundary_cycle;
          end
          if (status_valid !== (cycle_count >= empty_status_due))
            fail("empty-prefix completion step cycle contract");
        end
      end
    end
  endtask

  task automatic reset_now;
    begin
      @(negedge clk);
      #1;
      rst_n = 0; s_valid = 0; s_last = 0;
      m_ready = 0; status_ready = 0;
      #1;
      public_checks();
      // Release this asynchronous pulse before any rising clock edge.
      #1;
      rst_n = 1;
      #1;
      public_checks();
      if (m_valid || status_valid || !s_ready)
        fail("short asynchronous reset pulse did not abort immediately");
      old_out_stall = 0; old_status_stall = 0; old_input_stall = 0;
      active_case = 0;
      repeat (4) begin
        step(0,0,0,1,1);
        if (m_valid || status_valid || !s_ready)
          fail("reset abort leaked output/status or failed clean readiness");
      end
    end
  endtask

  task automatic run_case(
      input string input_file, input string expected_file,
      input integer input_length, input integer output_length,
      input integer expected_error, input integer detect_at,
      input integer recovery_order, input integer special_mode,
      input integer lookahead_valid, input [7:0] lookahead_data,
      input reg lookahead_last);
    integer fd, amount, iterations, bound, wait_cycles, after_boundary, gap_age;
    reg sv, sl, mr, sr, held;
    reg [7:0] sd;
    begin
      case_index = case_index + 1;
      nin = input_length; nout = output_length; wanted_error = expected_error;
      detection = detect_at; order_kind = recovery_order; special = special_mode;
      fd = $fopen(input_file,"rb");
      if (!fd) fail("missing compressed input");
      amount = $fread(compressed,fd); $fclose(fd);
      if (amount != nin) fail("compressed file length");
      if (nout) begin
        fd = $fopen(expected_file,"rb");
        if (!fd) fail("missing reference output");
        amount = $fread(expected,fd); $fclose(fd);
        if (amount != nout) fail("expected file length");
      end
      inputs_seen = 0; outputs_seen = 0; statuses_seen = 0;
      boundary_seen = 0; detected = 0; active_case = 1;
      boundary_cycle = -1; error_cycle = -1; final_cycle = -1;
      status_cycle = -1; literal_cycle = -100;
      match_offset_cycle = -100;
      output_stalls = 0; status_stalls = 0; discard_beats = 0; discard_gaps = 0;
      longest_stall = 0; current_stall = 0; comparisons = 0;
      old_out_stall = 0; old_status_stall = 0;
      burst_remaining = 0; bursts_seen = 0; status_age = 0;
      boundary_age = 0; wait_cycles = 0; after_boundary = 0;
      gap_age = 0; held = old_input_stall;
      // At most three parsing/commit/read edges per byte, plus bounded
      // deterministic gaps, <=257-cycle stalls and explicit recovery waits.
      // A very conservative factor 2048 covers each imposed stall per beat.
      // It is a functional cycle bound, not a wall-clock timeout.
      bound = 2048 * (nin + nout + 1) + 4096;
      // 32-bit SV integers cannot hold the deliberately long overflow bound.
      if (nin > 1000000) bound = 100 * nin + 4096;
      begin : run_loop
      for (iterations = 0; iterations < bound; iterations = iterations + 1) begin
        random_state = next_random(random_state);
        mr = 1; sr = 0;
        if (mode == 1) mr = random_state[7:0] < 193;
        if (mode == 1 && current_stall >= 7) mr = 1;
        if (mode == 2) begin
          if (m_valid && !bursts_seen) begin
            burst_remaining = 257; bursts_seen = 1;
          end
          if (burst_remaining > 0) begin
            mr = 0; burst_remaining = burst_remaining - 1;
          end else mr = (iterations % 37) >= 6;
        end
        if (status_valid) status_age = status_age + 1;
        if (status_age > 19) sr = 1;
        if (detected && order_kind == 1 && !boundary_seen) mr = 0;
        if (boundary_seen) after_boundary = after_boundary + 1;
        if (order_kind == 1 && after_boundary > 0 && after_boundary < 20) mr = 0;
        if (detected && order_kind == 3 && !boundary_seen) mr = 0;
        if (special == 3) mr = 0;
        sv = (inputs_seen < nin);
        if (!held && gap_age < 3 && mode != 0 && random_state[15:8] < 65) sv = 0;
        // Deterministic input gaps also exercise discard in always-ready mode.
        if (!held && detected && !boundary_seen &&
            (cycle_count <= error_cycle+2 || iterations % 7 == 0)) sv = 0;
        if (inputs_seen == nin-1 && !held && detected && order_kind == 2 &&
            (final_cycle < 0 || cycle_count < final_cycle + 7)) sv = 0;
        if (inputs_seen == nin-1 && detected && order_kind == 3) begin
          sv = m_valid && m_last;
          if (sv) mr = 1;
        end
        if (held) sv = 1;
        sd = 0; sl = 0;
        if (inputs_seen < nin) begin
          sd = compressed[inputs_seen];
          sl = inputs_seen == nin-1 &&
               (special == 0 || special == 3 || special == 7);
        end else if (!special && lookahead_valid) begin
          // Keep the next block's first byte asserted across status stalls.
          // It cannot transfer until the edge following status acceptance.
          sv = 1; sd = lookahead_data; sl = lookahead_last;
        end
        if (!sv && inputs_seen < nin) gap_age = gap_age + 1;
        else gap_age = 0;
        step(sv,sd,sl,mr,sr);
        held = sv && !transferred_input;
        if (statuses_seen) begin
          if (inputs_seen != nin || outputs_seen != nout)
            fail("completion conservation");
          if (status_stalls < 19) fail("status stall not observed");
          if (detection >= 0 && detection < nin-1) begin
            if (discard_beats != nin-1-detection)
              fail("discard byte conservation");
            if (discard_gaps == 0)
              fail("discard input gaps not observed");
          end
          if (order_kind == 1 && nout && !(boundary_cycle < final_cycle))
            fail("boundary-first recovery not observed");
          if (order_kind == 2 && !(final_cycle < boundary_cycle))
            fail("output-first recovery not observed");
          if (order_kind == 3) begin
            if (final_cycle != boundary_cycle) fail("simultaneous recovery absent");
            coincidences = coincidences + 1;
          end
          if (mode == 2 && nout && order_kind == 0 && longest_stall < 257)
            fail("257-cycle output stall not observed");
          if (nin == 2 && nout == 1 && mode == 0 && !order_kind &&
              final_cycle != literal_cycle+3)
            fail("unstalled literal cycle contract");
          completed_cases = completed_cases + 1;
          $display("CASE %0d PASS in=%0d out=%0d error=%0d comparisons=%0d discard=%0d gaps=%0d status_stalls=%0d max_output_stall=%0d boundary=%0d final=%0d status=%0d",
                   case_index,inputs_seen,outputs_seen,wanted_error,comparisons,
                   discard_beats,discard_gaps,status_stalls,longest_stall,
                   boundary_cycle,final_cycle,status_cycle);
          $fdisplay(ledger,"CASE %0d PASS in=%0d out=%0d error=%0d comparisons=%0d discard=%0d gaps=%0d status_stalls=%0d max_output_stall=%0d boundary=%0d final=%0d status=%0d",
                   case_index,inputs_seen,outputs_seen,wanted_error,comparisons,
                   discard_beats,discard_gaps,status_stalls,longest_stall,
                   boundary_cycle,final_cycle,status_cycle);
          $fflush();
          active_case = 0;
          if (!lookahead_valid) begin
            repeat (4) begin
              step(0,0,0,1,1);
              if (m_valid || status_valid || !s_ready)
                fail("duplicate output/status after completion");
            end
          end
          disable run_loop;
        end
        if (special && inputs_seen == nin) begin
          wait_cycles = wait_cycles + 1;
          if ((status_valid && special != 7) || statuses_seen)
            fail("completion during unbounded wait/abort");
          if ((special == 1 && wait_cycles >= 8) ||
              (special == 2 && outputs_seen >= 5) ||
              (special == 3 && m_valid && wait_cycles >= 8) ||
              (special == 4 && wait_cycles >= 8) ||
              (special == 7 && status_valid && status_age >= 8) ||
              ((special == 5 || special == 6) && wait_cycles >= 512)) begin
            if (special == 5 && !s_ready) fail("missing-byte wait not ready");
            if ((special == 4 || special == 6) && !s_ready)
              fail("missing-boundary discard wait not ready");
            if (special == 6 && outputs_seen != nout)
              fail("prefix did not drain independently of missing boundary");
            $display("CASE %0d ABORT in=%0d out=%0d wait=%0d special=%0d",
                     case_index,inputs_seen,outputs_seen,wait_cycles,special);
            $fdisplay(ledger,"CASE %0d ABORT in=%0d out=%0d wait=%0d special=%0d",
                     case_index,inputs_seen,outputs_seen,wait_cycles,special);
            $fflush();
            abort_total = abort_total + 1;
            reset_now();
            disable run_loop;
          end
        end
      end
      if (iterations == bound) fail("functional cycle bound exceeded");
      end
    end
  endtask

  initial begin
    // An actual time-zero assertion, not an artificial delayed 1->0 toggle.
    rst_n = 0;
    ledger = $fopen("@LEDGER@", "w");
    if (!ledger) $fatal(1, "cannot create executed-case ledger");
    seed = @SEED@; mode = @MODE@; random_state = seed;
    #0;
    public_checks();
    repeat (3) step(0,0,0,0,0);
    @(negedge clk); rst_n = 1;
    @CALLS@
    $display("SIMULATION_COMPLETE cases=%0d completed=%0d aborted=%0d statuses=%0d simultaneous=%0d back_to_back=%0d cycles=%0d",
             case_index+1,completed_cases,abort_total,status_total,coincidences,back_to_back,cycle_count);
    $fdisplay(ledger,"SIMULATION_COMPLETE cases=%0d completed=%0d aborted=%0d statuses=%0d simultaneous=%0d back_to_back=%0d cycles=%0d",
             case_index+1,completed_cases,abort_total,status_total,coincidences,back_to_back,cycle_count);
    $fflush();
    $fclose(ledger);
    $finish;
  end
endmodule
"""


def generate(cases: list[dict], seed: int, mode: int, ledger: str) -> str:
    calls = []
    for index, case in enumerate(cases):
        following = cases[index + 1] if index + 1 < len(cases) else None
        lookahead = 1 if following is not None else 0
        next_byte = following["first_byte"] if following is not None else 0
        next_last = int(
            following is not None and following["input_length"] == 1
            and following["special"] in (0, 3, 7)
        )
        calls.append(
            'run_case("{input}","{expected}",{input_length},{output_length},'
            '{error},{detection},{order},{special},'
            f'{lookahead},8\'d{next_byte},1\'b{next_last});'.format(**case)
        )
    return (
        BODY.replace("@INPUT_MAX@", str(max(c["input_length"] for c in cases)))
        .replace("@OUTPUT_MAX@", str(max(c["output_length"] for c in cases)))
        .replace("@SEED@", str(seed)).replace("@MODE@", str(mode))
        .replace("@LEDGER@", ledger)
        .replace("@CALLS@", "\n    ".join(calls))
    )
