module bellows_l2_compressor #(
    parameter integer MAX_BLOCK_BYTES = 65536
) (
    input wire clk,
    input wire rst_n,
    input wire [7:0] s_data,
    input wire s_keep,
    input wire s_valid,
    input wire s_last,
    output wire s_ready,
    output wire [7:0] m_data,
    output wire m_valid,
    output wire m_last,
    input wire m_ready,
    output wire status_valid,
    output wire [2:0] status_error,
    input wire status_ready
);
    localparam integer LEGAL_PARAMETER =
        MAX_BLOCK_BYTES >= 1 && MAX_BLOCK_BYTES <= 65536;
    localparam integer STORAGE_BYTES = LEGAL_PARAMETER ? MAX_BLOCK_BYTES : 1;
    localparam integer ENCODED_BYTES = 2 * STORAGE_BYTES + 16;
    localparam [16:0] CAPACITY = STORAGE_BYTES;
    localparam [17:0] ENCODED_CAPACITY = ENCODED_BYTES;
    localparam [4:0]
        COLLECT = 5'd0, DISCARD = 5'd1,
        SIZE_INIT = 5'd2, SIZE_EXT = 5'd3, START = 5'd4,
        FIND = 5'd5, MATCH_DESC = 5'd6, MATCH_EMIT = 5'd7,
        MATCH_ACK = 5'd8, FINAL_DESC = 5'd9, FINAL_EMIT = 5'd10,
        SELECT = 5'd11, FALLBACK_DESC = 5'd12, FALLBACK_EMIT = 5'd13,
        OUTPUT_REQ = 5'd14, OUTPUT_LOAD = 5'd15,
        OUTPUT_HOLD = 5'd16, STATUS = 5'd17;

    reg [4:0] state;
    reg [16:0] raw_count;
    reg [16:0] anchor;
    reg [17:0] literal_only_size;
    reg [16:0] size_remainder;
    reg [17:0] encoded_count;
    reg [17:0] output_index;
    reg [2:0] block_error;
    reg [7:0] presented_data;
    reg presented_valid;
    reg presented_last;

    (* ramstyle = "M20K", nomem2reg *)
    reg [7:0] encoded_memory [0:ENCODED_BYTES-1];
    reg [7:0] encoded_read_data;

    wire input_transfer = s_valid && s_ready;
    wire raw_write = rst_n && state == COLLECT && input_transfer &&
                     s_keep && raw_count < CAPACITY;
    wire matcher_a_en, matcher_b_en;
    wire [15:0] matcher_a_addr, matcher_b_addr;
    wire [7:0] raw_a_data, raw_b_data;
    wire matcher_valid, matcher_done;
    wire [16:0] matcher_position, matcher_length;
    wire [15:0] matcher_offset;
    wire emitter_seq_ready, emitter_done;
    wire emitter_literal_en;
    wire [15:0] emitter_literal_addr;
    wire [7:0] emitter_byte_data;
    wire emitter_byte_valid;
    wire emitter_owner =
        state == MATCH_DESC || state == MATCH_EMIT ||
        state == FINAL_DESC || state == FINAL_EMIT ||
        state == FALLBACK_DESC || state == FALLBACK_EMIT;
    wire descriptor_valid = rst_n &&
        (state == MATCH_DESC || state == FINAL_DESC || state == FALLBACK_DESC);
    wire [16:0] descriptor_start =
        state == FALLBACK_DESC ? 17'd0 : anchor;
    wire [16:0] descriptor_literals =
        state == MATCH_DESC ? matcher_position - anchor :
        state == FALLBACK_DESC ? raw_count : raw_count - anchor;
    wire emitter_byte_ready = rst_n && emitter_owner &&
                              encoded_count < ENCODED_CAPACITY;
    wire encoded_write = emitter_byte_valid && emitter_byte_ready;

    assign s_ready = rst_n && LEGAL_PARAMETER &&
                     (state == COLLECT || state == DISCARD);
    assign m_valid = rst_n && presented_valid;
    assign m_data = m_valid ? presented_data : 8'd0;
    assign m_last = m_valid && presented_last;
    assign status_valid = rst_n && state == STATUS;
    assign status_error = status_valid ? block_error : 3'd0;

    generate
        if (!LEGAL_PARAMETER) begin : invalid_parameter
            initial $fatal(1, "PARAMETER ERROR: MAX_BLOCK_BYTES must be 1..65536");
        end
    endgenerate

    bellows_l2_literal_buffer #(.MAX_BLOCK_BYTES(MAX_BLOCK_BYTES)) literal_buffer (
        .clk(clk), .rst_n(rst_n),
        .write_en(raw_write), .write_addr(raw_count[15:0]), .write_data(s_data),
        .a_en(emitter_owner ? emitter_literal_en : matcher_a_en),
        .a_addr(emitter_owner ? emitter_literal_addr : matcher_a_addr),
        .a_data(raw_a_data),
        .b_en(!emitter_owner && matcher_b_en), .b_addr(matcher_b_addr),
        .b_data(raw_b_data)
    );

    bellows_l2_hash_match hash_match (
        .clk(clk), .rst_n(rst_n), .start(rst_n && state == START),
        .block_length(raw_count),
        .a_en(matcher_a_en), .a_addr(matcher_a_addr), .a_data(raw_a_data),
        .b_en(matcher_b_en), .b_addr(matcher_b_addr), .b_data(raw_b_data),
        .match_valid(matcher_valid), .match_position(matcher_position),
        .match_length(matcher_length), .match_offset(matcher_offset),
        .match_ready(rst_n && state == MATCH_ACK), .done(matcher_done)
    );

    bellows_l2_emitter emitter (
        .clk(clk), .rst_n(rst_n),
        .seq_valid(descriptor_valid), .seq_ready(emitter_seq_ready),
        .literal_start(descriptor_start), .literal_length(descriptor_literals),
        .match_length(state == MATCH_DESC ? matcher_length : 17'd0),
        .match_offset(state == MATCH_DESC ? matcher_offset : 16'd0),
        .final_sequence(state != MATCH_DESC),
        .literal_en(emitter_literal_en), .literal_addr(emitter_literal_addr),
        .literal_data(raw_a_data),
        .byte_data(emitter_byte_data), .byte_valid(emitter_byte_valid),
        .byte_ready(emitter_byte_ready), .done(emitter_done)
    );

    always @(posedge clk) begin
        if (rst_n && encoded_write)
            encoded_memory[encoded_count] <= emitter_byte_data;
        if (rst_n && state == OUTPUT_REQ)
            encoded_read_data <= encoded_memory[output_index];
    end

    // synthesis translate_off
    always @(posedge clk) begin
        if (rst_n && emitter_owner && emitter_byte_valid &&
            encoded_count >= ENCODED_CAPACITY)
            $fatal(1, "INVARIANT ERROR: candidate encoding storage exhausted");
    end
    // synthesis translate_on

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= COLLECT;
            raw_count <= 17'd0;
            anchor <= 17'd0;
            literal_only_size <= 18'd0;
            size_remainder <= 17'd0;
            encoded_count <= 18'd0;
            output_index <= 18'd0;
            block_error <= 3'd0;
            presented_data <= 8'd0;
            presented_valid <= 1'b0;
            presented_last <= 1'b0;
        end else begin
            if (encoded_write)
                encoded_count <= encoded_count + 18'd1;
            case (state)
                COLLECT: begin
                    if (input_transfer) begin
                        if (!s_keep) begin
                            if (raw_count == 17'd0 && s_last) begin
                                state <= SIZE_INIT;
                            end else begin
                                block_error <= 3'd6;
                                if (s_last)
                                    state <= STATUS;
                                else
                                    state <= DISCARD;
                            end
                        end else if (raw_count == CAPACITY) begin
                            block_error <= 3'd5;
                            if (s_last)
                                state <= STATUS;
                            else
                                state <= DISCARD;
                        end else begin
                            raw_count <= raw_count + 17'd1;
                            if (s_last)
                                state <= SIZE_INIT;
                        end
                    end
                end
                DISCARD: begin
                    if (input_transfer && s_last)
                        state <= STATUS;
                end
                SIZE_INIT: begin
                    anchor <= 17'd0;
                    encoded_count <= 18'd0;
                    output_index <= 18'd0;
                    literal_only_size <= {1'b0, raw_count} + 18'd1;
                    if (raw_count >= 17'd15) begin
                        size_remainder <= raw_count - 17'd15;
                        state <= SIZE_EXT;
                    end else begin
                        state <= START;
                    end
                end
                SIZE_EXT: begin
                    literal_only_size <= literal_only_size + 18'd1;
                    if (size_remainder >= 17'd255)
                        size_remainder <= size_remainder - 17'd255;
                    else
                        state <= START;
                end
                START: state <= FIND;
                FIND: begin
                    if (matcher_valid)
                        state <= MATCH_DESC;
                    else if (matcher_done)
                        state <= FINAL_DESC;
                end
                MATCH_DESC: begin
                    if (emitter_seq_ready)
                        state <= MATCH_EMIT;
                end
                MATCH_EMIT: begin
                    if (emitter_done) begin
                        anchor <= matcher_position + matcher_length;
                        state <= MATCH_ACK;
                    end
                end
                MATCH_ACK: state <= FIND;
                FINAL_DESC: begin
                    if (emitter_seq_ready)
                        state <= FINAL_EMIT;
                end
                FINAL_EMIT: begin
                    if (emitter_done)
                        state <= SELECT;
                end
                SELECT: begin
                    if (encoded_count < literal_only_size) begin
                        output_index <= 18'd0;
                        state <= OUTPUT_REQ;
                    end else begin
                        encoded_count <= 18'd0;
                        state <= FALLBACK_DESC;
                    end
                end
                FALLBACK_DESC: begin
                    if (emitter_seq_ready)
                        state <= FALLBACK_EMIT;
                end
                FALLBACK_EMIT: begin
                    if (emitter_done) begin
                        output_index <= 18'd0;
                        state <= OUTPUT_REQ;
                    end
                end
                OUTPUT_REQ: state <= OUTPUT_LOAD;
                OUTPUT_LOAD: begin
                    presented_data <= encoded_read_data;
                    presented_valid <= 1'b1;
                    presented_last <= output_index == encoded_count - 18'd1;
                    state <= OUTPUT_HOLD;
                end
                OUTPUT_HOLD: begin
                    if (presented_valid && m_ready) begin
                        presented_data <= 8'd0;
                        presented_valid <= 1'b0;
                        presented_last <= 1'b0;
                        if (presented_last) begin
                            state <= STATUS;
                        end else begin
                            output_index <= output_index + 18'd1;
                            state <= OUTPUT_REQ;
                        end
                    end
                end
                STATUS: begin
                    if (status_ready) begin
                        raw_count <= 17'd0;
                        block_error <= 3'd0;
                        state <= COLLECT;
                    end
                end
                default: state <= COLLECT;
            endcase
        end
    end
endmodule
