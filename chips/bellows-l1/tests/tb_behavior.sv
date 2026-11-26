`timescale 1ns/1ps
module tb_behavior;
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic [7:0] s_data = 0;
    logic s_valid = 0, s_last = 0, m_ready = 0, status_ready = 0;
    wire s_ready, m_valid, m_last, status_valid;
    wire [7:0] m_data;
    wire [2:0] status_error;
    bellows_l1_top dut (.*);

    byte unsigned src[], expected[];
    string label_name;
    int total, out_len, mode, kind, seed, err;
    int unsigned rng;
    int input_bubbles = 0, output_stalls = 0, longest_stall = 0, status_stalls = 0;
    logic pending_read;
    int schedule_writes;

    function automatic int unsigned next_random(input int unsigned value);
        value ^= value << 13;
        value ^= value >> 17;
        return value ^ (value << 5);
    endfunction

    function automatic byte unsigned input_byte(input int index);
        if (kind == 0) return src[index];
        if (index == total-1) return 8'h00;
        if (kind == 1) return index == 0 ? 8'hf0 : 8'hff;
        case (index)
            0: return 8'h1f;
            1: return 8'ha7;
            2: return 8'h01;
            3: return 8'h00;
            default: return 8'hff;
        endcase
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            pending_read <= 0;
            schedule_writes <= 0;
        end else begin
            if ((!m_valid && (m_data != 0 || m_last)) ||
                (!status_valid && status_error != 0))
                $fatal(1, "PROTOCOL inactive payload nonzero");
            if (pending_read && !dut.candidate_valid)
                $fatal(1, "PROTOCOL match candidate absent after synchronous read");
            if (dut.history.read_en) begin
                if (pending_read || dut.history.write_en)
                    $fatal(1, "PROTOCOL dependent history read launched before commit");
                pending_read <= 1;
            end
            if (dut.history.write_en) begin
                if (pending_read) pending_read <= 0;
                schedule_writes <= schedule_writes + 1;
            end
        end
    end

    task automatic run_block;
        int sent, received, waited_status, burst_left, current_stall, cycles, start_writes;
        bit input_held, output_held, status_held, burst_used;
        byte unsigned saved_data;
        bit saved_last;
        logic [2:0] saved_error;
        sent = 0; received = 0; waited_status = 0; current_stall = 0;
        start_writes = schedule_writes;
        burst_left = 0; rng = unsigned'(seed) ^ 32'h97cef527;
        input_held = 0; output_held = 0; status_held = 0; burst_used = 0;
        for (cycles = 0; cycles < 8*(total+out_len)+8192; cycles++) begin
            rng = next_random(rng);
            s_valid = sent == total || input_held || mode == 0 || rng[2:0] < 5;
            s_data = sent < total ? input_byte(sent) : 0;
            s_last = sent >= total-1;
            if (mode == 2 && !burst_used && m_valid) begin
                burst_left = 257;
                burst_used = 1;
            end
            m_ready = mode == 0 || (burst_left == 0 && rng[6:4] < 5);
            if (burst_left != 0) burst_left--;
            status_ready = mode == 0 || waited_status >= 11;
            @(posedge clk);
            if (output_held && (!m_valid || m_data != saved_data || m_last != saved_last))
                $fatal(1, "PROTOCOL %s output changed under stall", label_name);
            if (status_held && (!status_valid || status_error != saved_error))
                $fatal(1, "PROTOCOL %s status changed under stall", label_name);
            output_held = m_valid && !m_ready;
            status_held = status_valid && !status_ready;
            saved_data = m_data; saved_last = m_last; saved_error = status_error;
            if (sent == total && s_ready)
                $fatal(1, "PROTOCOL %s accepted next block before status retirement", label_name);
            input_held = sent < total && s_valid && !s_ready;
            if (s_ready && !s_valid) input_bubbles++;
            if (s_ready && s_valid) sent++;
            if (output_held) begin
                output_stalls++;
                current_stall++;
                if (current_stall > longest_stall) longest_stall = current_stall;
            end else current_stall = 0;
            if (status_held) begin
                status_stalls++;
                waited_status++;
            end
            if (status_valid && (sent != total || (received != out_len && !m_valid)))
                $fatal(1, "MISMATCH %s completion boundary input=%0d/%0d output=%0d/%0d",
                       label_name, sent, total, received, out_len);
            if (m_valid && m_ready) begin
                if (received >= out_len || m_data !== expected[received] ||
                    m_last != (received == out_len-1))
                    $fatal(1, "MISMATCH %s output[%0d] actual=%02x last=%0d expected=%02x len=%0d",
                           label_name, received, m_data, m_last,
                           received < out_len ? expected[received] : 8'h00, out_len);
                received++;
            end
            if (status_valid) begin
                if (m_valid)
                    $fatal(1, "PROTOCOL %s status before output retirement", label_name);
                if ({29'd0, status_error} != err || received != out_len)
                    $fatal(1, "MISMATCH %s status actual=%0d expected=%0d output=%0d/%0d",
                           label_name, status_error, err, received, out_len);
                if (status_ready) begin
                    if (schedule_writes-start_writes != out_len)
                        $fatal(1, "PROTOCOL %s incorrect committed history byte count", label_name);
                    $display("PASS_CASE %s %0d %0d %0d %0d", label_name, sent, received, err, cycles+1);
                    @(negedge clk);
                    s_valid = 0;
                    return;
                end
            end
            @(negedge clk);
        end
        $fatal(1, "TIMEOUT %s input=%0d/%0d output=%0d/%0d", label_name, sent, total, received, out_len);
    endtask

    task automatic reset_check;
        rst_n = 0; s_valid = 0; m_ready = 0; status_ready = 0;
        repeat (3) begin
            @(posedge clk);
            if (s_ready || m_valid || status_valid) $fatal(1, "PROTOCOL transfer during reset");
        end
        @(negedge clk);
        rst_n = 1;
        repeat (2) begin
            @(posedge clk);
            if (m_valid || status_valid || !s_ready) $fatal(1, "PROTOCOL reset left pending work");
        end
        @(negedge clk);
    endtask

    task automatic send(input byte unsigned data, input bit last);
        s_data = data; s_last = last; s_valid = 1;
        for (int i = 0; i < 80; i++) begin
            @(posedge clk);
            if (s_ready) begin
                @(negedge clk);
                s_valid = 0;
                return;
            end
            @(negedge clk);
        end
        $fatal(1, "TIMEOUT reset preconditioning input");
    endtask

    task automatic reset_exercises;
        send(8'h30, 0);
        send(8'ha7, 0);
        if (dut.history.write_en !== 1 || dut.history.write_data !== 8'ha7)
            $fatal(1, "PROTOCOL literal did not commit on the next edge after acceptance");
        send(8'hb9, 0);
        repeat (3) @(negedge clk);
        if (!m_valid || m_data != 8'ha7 || m_last)
            $fatal(1, "PROTOCOL reset precondition: pending output absent");
        reset_check();
        send(0, 1);
        repeat (8) @(negedge clk);
        if (!status_valid || status_error != 0)
            $fatal(1, "PROTOCOL reset precondition: pending completion absent");
        reset_check();
        $display("RESET_COVERAGE 2");
    endtask

    initial begin
        int fd, parsed, data;
        string vectors;
        if (!$value$plusargs("vectors=%s", vectors)) $fatal(1, "Missing vectors path");
        fd = $fopen(vectors, "r");
        if (fd == 0) $fatal(1, "Cannot open behavior vectors");
        @(negedge clk);
        reset_check();
        if ($test$plusargs("reset_cases")) reset_exercises();
        parsed = $fscanf(fd, "%s %d %d %d %d %d %d", label_name, kind, mode, seed, total, out_len, err);
        while (parsed == 7) begin
            src = new[kind == 0 ? total : 0];
            expected = new[out_len];
            foreach (src[i]) begin
                if ($fscanf(fd, "%h", data) != 1) $fatal(1, "Bad input fixture %s", label_name);
                src[i] = 8'(data);
            end
            foreach (expected[i]) begin
                if ($fscanf(fd, "%h", data) != 1) $fatal(1, "Bad output fixture %s", label_name);
                expected[i] = 8'(data);
            end
            run_block();
            parsed = $fscanf(fd, "%s %d %d %d %d %d %d", label_name, kind, mode, seed, total, out_len, err);
        end
        if (!$feof(fd)) $fatal(1, "Invalid behavior fixture");
        repeat (8) begin
            @(posedge clk);
            if (m_valid || status_valid || !s_ready) $fatal(1, "PROTOCOL extra output or status");
        end
        $fclose(fd);
        $display("COVERAGE %0d %0d %0d %0d", input_bubbles, output_stalls, longest_stall, status_stalls);
        $finish;
    end
endmodule
