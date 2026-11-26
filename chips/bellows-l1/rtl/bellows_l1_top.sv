module bellows_l1_top (
    input  wire       clk, rst_n,
    input  wire [7:0] s_data,
    input  wire       s_valid, s_last,
    output wire       s_ready,
    output wire [7:0] m_data,
    output wire       m_valid, m_last,
    input  wire       m_ready,
    output wire       status_valid,
    output wire [2:0] status_error,
    input  wire       status_ready
);
    typedef enum logic [3:0] {
        ST_TOKEN, ST_LITERAL_EXT, ST_LITERAL, ST_LITERAL_COMMIT,
        ST_OFFSET_LOW, ST_OFFSET_HIGH, ST_MATCH_EXT, ST_MATCH_READ,
        ST_MATCH_COMMIT, ST_FINISH, ST_COMPLETE, ST_STATUS
    } state_t;
    state_t state;
    logic [3:0] match_nibble;
    logic [31:0] literal_remaining, match_remaining;
    logic [15:0] match_offset, write_pointer;
    logic [16:0] history_available;
    logic [7:0] literal_data;
    logic literal_terminal, input_closed, discard_active;
    logic [2:0] block_error;

    wire parser_accepts = state == ST_TOKEN || state == ST_LITERAL_EXT ||
        state == ST_LITERAL || state == ST_OFFSET_LOW ||
        state == ST_OFFSET_HIGH || state == ST_MATCH_EXT;
    assign s_ready = rst_n && (discard_active || (!input_closed && parser_accepts));
    wire input_transfer = s_valid && s_ready;
    wire discard_boundary = discard_active && input_transfer && s_last;
    wire boundary_available = input_closed || discard_boundary;

    assign status_valid = rst_n && state == ST_STATUS;
    assign status_error = status_valid ? block_error : 3'd0;

    wire [32:0] literal_sum = {1'b0, literal_remaining} + {25'd0, s_data};
    wire [32:0] match_sum = {1'b0, match_remaining} + {25'd0, s_data};
    wire [15:0] assembled_offset = {s_data, match_offset[7:0]};
    wire [15:0] read_address = write_pointer - match_offset;
    wire [7:0] history_read_data;
    wire candidate_valid = rst_n && (state == ST_LITERAL_COMMIT || state == ST_MATCH_COMMIT);
    wire [7:0] candidate_data = state == ST_LITERAL_COMMIT ? literal_data : history_read_data;
    wire candidate_ready;
    wire candidate_commit = candidate_valid && candidate_ready;
    wire finish_ready, output_idle, output_retiring_or_empty;

    bellows_l1_history history (
        .clk(clk),
        .write_en(candidate_commit), .write_addr(write_pointer), .write_data(candidate_data),
        .read_en(rst_n && state == ST_MATCH_READ), .read_addr(read_address),
        .read_data(history_read_data)
    );

    bellows_l1_output output_stage (
        .clk(clk), .rst_n(rst_n),
        .candidate_data(candidate_data), .candidate_valid(candidate_valid),
        .candidate_ready(candidate_ready),
        .finish_valid(rst_n && state == ST_FINISH), .finish_ready(finish_ready),
        .idle(output_idle), .retiring_or_empty(output_retiring_or_empty),
        .m_data(m_data), .m_valid(m_valid), .m_last(m_last), .m_ready(m_ready)
    );

    task automatic reject_sequence(input logic [2:0] error_code, input logic boundary_seen);
        block_error <= error_code;
        input_closed <= boundary_seen;
        discard_active <= !boundary_seen;
        state <= ST_FINISH;
    endtask

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_TOKEN;
            match_nibble <= '0;
            literal_remaining <= '0;
            match_remaining <= '0;
            match_offset <= '0;
            write_pointer <= '0;
            history_available <= '0;
            literal_data <= '0;
            literal_terminal <= 1'b0;
            input_closed <= 1'b0;
            discard_active <= 1'b0;
            block_error <= '0;
        end else begin
            if (candidate_commit) begin
                write_pointer <= write_pointer + 16'd1;
                if (history_available != 17'd65536)
                    history_available <= history_available + 17'd1;
            end
            if (discard_boundary) begin
                discard_active <= 1'b0;
                input_closed <= 1'b1;
            end

            case (state)
                ST_TOKEN: if (input_transfer) begin
                    match_nibble <= s_data[3:0];
                    literal_remaining <= {28'd0, s_data[7:4]};
                    match_remaining <= {28'd0, s_data[3:0]} + 32'd4;
                    if (s_last) begin
                        if (s_data[7:4] != 0)
                            reject_sequence(3'd1, 1'b1);
                        else begin
                            input_closed <= 1'b1;
                            state <= ST_FINISH;
                        end
                    end else if (s_data[7:4] == 15)
                        state <= ST_LITERAL_EXT;
                    else if (s_data[7:4] != 0)
                        state <= ST_LITERAL;
                    else
                        state <= ST_OFFSET_LOW;
                end

                ST_LITERAL_EXT: if (input_transfer) begin
                    if (s_last)
                        reject_sequence(3'd1, 1'b1);
                    else if (literal_sum[32])
                        reject_sequence(3'd4, 1'b0);
                    else begin
                        literal_remaining <= literal_sum[31:0];
                        if (s_data != 255)
                            state <= ST_LITERAL;
                    end
                end

                ST_LITERAL: if (input_transfer) begin
                    literal_data <= s_data;
                    literal_terminal <= s_last;
                    if (s_last) begin
                        input_closed <= 1'b1;
                        if (literal_remaining != 1)
                            block_error <= 3'd1;
                    end
                    state <= ST_LITERAL_COMMIT;
                end

                ST_LITERAL_COMMIT: if (candidate_commit) begin
                    literal_remaining <= literal_remaining - 32'd1;
                    if (literal_terminal)
                        state <= ST_FINISH;
                    else if (literal_remaining == 1)
                        state <= ST_OFFSET_LOW;
                    else
                        state <= ST_LITERAL;
                end

                ST_OFFSET_LOW: if (input_transfer) begin
                    if (s_last)
                        reject_sequence(3'd1, 1'b1);
                    else begin
                        match_offset[7:0] <= s_data;
                        state <= ST_OFFSET_HIGH;
                    end
                end

                ST_OFFSET_HIGH: if (input_transfer) begin
                    if (s_last)
                        reject_sequence(3'd1, 1'b1);
                    else if (assembled_offset == 0)
                        reject_sequence(3'd2, 1'b0);
                    else if ({1'b0, assembled_offset} > history_available)
                        reject_sequence(3'd3, 1'b0);
                    else begin
                        match_offset <= assembled_offset;
                        state <= match_nibble == 15 ? ST_MATCH_EXT : ST_MATCH_READ;
                    end
                end

                ST_MATCH_EXT: if (input_transfer) begin
                    if (s_last)
                        reject_sequence(3'd1, 1'b1);
                    else if (match_sum[32])
                        reject_sequence(3'd4, 1'b0);
                    else begin
                        match_remaining <= match_sum[31:0];
                        if (s_data != 255)
                            state <= ST_MATCH_READ;
                    end
                end

                ST_MATCH_READ: state <= ST_MATCH_COMMIT;
                ST_MATCH_COMMIT: if (candidate_commit) begin
                    match_remaining <= match_remaining - 32'd1;
                    state <= match_remaining == 1 ? ST_TOKEN : ST_MATCH_READ;
                end

                ST_FINISH: if (finish_ready)
                    state <= output_idle && boundary_available ? ST_STATUS : ST_COMPLETE;
                ST_COMPLETE: if (output_retiring_or_empty && boundary_available)
                    state <= ST_STATUS;
                default: if (state != ST_STATUS || status_ready) begin
                    state <= ST_TOKEN;
                    write_pointer <= '0;
                    history_available <= '0;
                    input_closed <= 1'b0;
                    discard_active <= 1'b0;
                    block_error <= '0;
                end
            endcase
        end
    end
endmodule
