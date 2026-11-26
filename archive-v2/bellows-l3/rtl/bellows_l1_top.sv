module bellows_l1_top (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] s_data,
    input  wire       s_valid,
    input  wire       s_last,
    output wire       s_ready,
    output wire [7:0] m_data,
    output wire       m_valid,
    output wire       m_last,
    input  wire       m_ready,
    output wire       status_valid,
    output wire [2:0] status_error,
    input  wire       status_ready
);
    localparam [3:0]
        ST_TOKEN         = 4'd0,
        ST_LITERAL_EXT   = 4'd1,
        ST_LITERAL       = 4'd2,
        ST_LITERAL_COMMIT= 4'd3,
        ST_OFFSET_LOW    = 4'd4,
        ST_OFFSET_HIGH   = 4'd5,
        ST_MATCH_EXT     = 4'd6,
        ST_MATCH_READ    = 4'd7,
        ST_MATCH_COMMIT  = 4'd8,
        ST_FINISH        = 4'd9,
        ST_COMPLETE      = 4'd10,
        ST_STATUS        = 4'd11;

    reg [3:0]  state;
    reg [3:0]  match_nibble;
    reg [31:0] literal_remaining;
    reg [31:0] match_remaining;
    reg [15:0] match_offset;
    reg [15:0] write_pointer;
    reg [16:0] history_available;
    reg [7:0]  literal_data;
    reg        literal_terminal;
    reg        input_closed;
    reg        discard_active;
    reg [2:0]  block_error;

    wire parser_accepts =
        state == ST_TOKEN || state == ST_LITERAL_EXT ||
        state == ST_LITERAL || state == ST_OFFSET_LOW ||
        state == ST_OFFSET_HIGH || state == ST_MATCH_EXT;

    assign s_ready = rst_n &&
        (discard_active || (!input_closed && parser_accepts));
    wire input_transfer = s_valid && s_ready;
    wire discard_boundary = discard_active && input_transfer && s_last;
    wire boundary_available = input_closed || discard_boundary;

    assign status_valid = rst_n && state == ST_STATUS;
    assign status_error = status_valid ? block_error : 3'd0;

    wire [32:0] literal_sum =
        {1'b0, literal_remaining} + {25'd0, s_data};
    wire [32:0] match_sum =
        {1'b0, match_remaining} + {25'd0, s_data};
    wire [15:0] assembled_offset = {s_data, match_offset[7:0]};
    wire [15:0] read_address = write_pointer - match_offset;
    wire [7:0] history_read_data;

    wire candidate_valid = rst_n &&
        (state == ST_LITERAL_COMMIT || state == ST_MATCH_COMMIT);
    wire [7:0] candidate_data =
        state == ST_LITERAL_COMMIT ? literal_data : history_read_data;
    wire candidate_ready;
    wire candidate_commit = candidate_valid && candidate_ready;
    wire finish_ready;
    wire output_idle;
    wire output_retiring_or_empty;

    bellows_l1_history history (
        .clk(clk),
        .rst_n(rst_n),
        .write_en(candidate_commit),
        .write_addr(write_pointer),
        .write_data(candidate_data),
        .read_en(rst_n && state == ST_MATCH_READ),
        .read_addr(read_address),
        .read_data(history_read_data)
    );

    bellows_l1_output output_stage (
        .clk(clk),
        .rst_n(rst_n),
        .candidate_data(candidate_data),
        .candidate_valid(candidate_valid),
        .candidate_ready(candidate_ready),
        .finish_valid(rst_n && state == ST_FINISH),
        .finish_ready(finish_ready),
        .idle(output_idle),
        .retiring_or_empty(output_retiring_or_empty),
        .m_data(m_data),
        .m_valid(m_valid),
        .m_last(m_last),
        .m_ready(m_ready)
    );

    // Called only for an accepted parser byte, before any match launches.
    task reject_sequence;
        input [2:0] error_code;
        input       boundary_seen;
        begin
            block_error <= error_code;
            input_closed <= boundary_seen;
            discard_active <= !boundary_seen;
            state <= ST_FINISH;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= ST_TOKEN;
            match_nibble <= 4'd0;
            literal_remaining <= 32'd0;
            match_remaining <= 32'd0;
            match_offset <= 16'd0;
            write_pointer <= 16'd0;
            history_available <= 17'd0;
            literal_data <= 8'd0;
            literal_terminal <= 1'b0;
            input_closed <= 1'b0;
            discard_active <= 1'b0;
            block_error <= 3'd0;
        end else begin
            if (candidate_commit) begin
                write_pointer <= write_pointer + 16'd1;
                if (history_available != 17'd65536)
                    history_available <= history_available + 17'd1;
            end

            // Input framing progresses independently of output completion.
            if (discard_boundary) begin
                discard_active <= 1'b0;
                input_closed <= 1'b1;
            end

            case (state)
                ST_TOKEN: begin
                    if (input_transfer) begin
                        match_nibble <= s_data[3:0];
                        literal_remaining <= {28'd0, s_data[7:4]};
                        match_remaining <= {28'd0, s_data[3:0]} + 32'd4;
                        if (s_last) begin
                            input_closed <= 1'b1;
                            if (s_data[7:4] != 4'd0)
                                reject_sequence(3'd1, 1'b1);
                            else
                                state <= ST_FINISH;
                        end else if (s_data[7:4] == 4'd15) begin
                            state <= ST_LITERAL_EXT;
                        end else if (s_data[7:4] != 4'd0) begin
                            state <= ST_LITERAL;
                        end else begin
                            state <= ST_OFFSET_LOW;
                        end
                    end
                end

                ST_LITERAL_EXT: begin
                    if (input_transfer) begin
                        if (s_last) begin
                            reject_sequence(3'd1, 1'b1);
                        end else if (literal_sum[32]) begin
                            reject_sequence(3'd4, 1'b0);
                        end else begin
                            literal_remaining <= literal_sum[31:0];
                            if (s_data != 8'd255)
                                state <= ST_LITERAL;
                        end
                    end
                end

                ST_LITERAL: begin
                    if (input_transfer) begin
                        literal_data <= s_data;
                        literal_terminal <= s_last;
                        if (s_last) begin
                            input_closed <= 1'b1;
                            if (literal_remaining != 32'd1)
                                block_error <= 3'd1;
                        end
                        state <= ST_LITERAL_COMMIT;
                    end
                end

                ST_LITERAL_COMMIT: begin
                    if (candidate_commit) begin
                        literal_remaining <= literal_remaining - 32'd1;
                        if (literal_terminal)
                            state <= ST_FINISH;
                        else if (literal_remaining == 32'd1)
                            state <= ST_OFFSET_LOW;
                        else
                            state <= ST_LITERAL;
                    end
                end

                ST_OFFSET_LOW: begin
                    if (input_transfer) begin
                        if (s_last) begin
                            reject_sequence(3'd1, 1'b1);
                        end else begin
                            match_offset[7:0] <= s_data;
                            state <= ST_OFFSET_HIGH;
                        end
                    end
                end

                ST_OFFSET_HIGH: begin
                    if (input_transfer) begin
                        if (s_last) begin
                            reject_sequence(3'd1, 1'b1);
                        end else if (assembled_offset == 16'd0) begin
                            reject_sequence(3'd2, 1'b0);
                        end else if ({1'b0, assembled_offset} > history_available) begin
                            reject_sequence(3'd3, 1'b0);
                        end else begin
                            match_offset <= assembled_offset;
                            if (match_nibble == 4'd15)
                                state <= ST_MATCH_EXT;
                            else
                                state <= ST_MATCH_READ;
                        end
                    end
                end

                ST_MATCH_EXT: begin
                    if (input_transfer) begin
                        if (s_last) begin
                            reject_sequence(3'd1, 1'b1);
                        end else if (match_sum[32]) begin
                            reject_sequence(3'd4, 1'b0);
                        end else begin
                            match_remaining <= match_sum[31:0];
                            if (s_data != 8'd255)
                                state <= ST_MATCH_READ;
                        end
                    end
                end

                ST_MATCH_READ: begin
                    state <= ST_MATCH_COMMIT;
                end

                ST_MATCH_COMMIT: begin
                    if (candidate_commit) begin
                        match_remaining <= match_remaining - 32'd1;
                        if (match_remaining == 32'd1)
                            state <= ST_TOKEN;
                        else
                            state <= ST_MATCH_READ;
                    end
                end

                ST_FINISH: begin
                    if (finish_ready) begin
                        if (output_idle && boundary_available)
                            state <= ST_STATUS;
                        else
                            state <= ST_COMPLETE;
                    end
                end

                ST_COMPLETE: begin
                    if (output_retiring_or_empty && boundary_available)
                        state <= ST_STATUS;
                end

                ST_STATUS: begin
                    if (status_ready) begin
                        state <= ST_TOKEN;
                        match_nibble <= 4'd0;
                        literal_remaining <= 32'd0;
                        match_remaining <= 32'd0;
                        match_offset <= 16'd0;
                        write_pointer <= 16'd0;
                        history_available <= 17'd0;
                        literal_data <= 8'd0;
                        literal_terminal <= 1'b0;
                        input_closed <= 1'b0;
                        discard_active <= 1'b0;
                        block_error <= 3'd0;
                    end
                end

                default: begin
                    state <= ST_TOKEN;
                    match_nibble <= 4'd0;
                    literal_remaining <= 32'd0;
                    match_remaining <= 32'd0;
                    match_offset <= 16'd0;
                    write_pointer <= 16'd0;
                    history_available <= 17'd0;
                    literal_data <= 8'd0;
                    literal_terminal <= 1'b0;
                    input_closed <= 1'b0;
                    discard_active <= 1'b0;
                    block_error <= 3'd0;
                end
            endcase
        end
    end
endmodule
