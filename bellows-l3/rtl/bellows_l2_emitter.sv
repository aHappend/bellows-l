module bellows_l2_emitter (
    input wire clk,
    input wire rst_n,
    input wire seq_valid,
    output wire seq_ready,
    input wire [16:0] literal_start,
    input wire [16:0] literal_length,
    input wire [16:0] match_length,
    input wire [15:0] match_offset,
    input wire final_sequence,
    output wire literal_en,
    output wire [15:0] literal_addr,
    input wire [7:0] literal_data,
    output wire [7:0] byte_data,
    output wire byte_valid,
    input wire byte_ready,
    output wire done
);
    localparam [3:0]
        IDLE = 4'd0, TOKEN = 4'd1, LITERAL_EXT = 4'd2,
        LITERAL_REQ = 4'd3, LITERAL_CAPTURE = 4'd4,
        LITERAL_BYTE = 4'd5, OFFSET_LOW = 4'd6,
        OFFSET_HIGH = 4'd7, MATCH_EXT = 4'd8,
        DRAIN = 4'd9, DONE = 4'd10;
    reg [3:0] state;
    reg [16:0] literal_pointer;
    reg [16:0] literal_remaining;
    reg [16:0] literal_extra;
    reg [16:0] match_extra;
    reg [15:0] offset;
    reg final_only;
    reg literal_saturated;
    reg match_saturated;
    reg [3:0] token_literal;
    reg [3:0] token_match;
    reg [7:0] literal_hold;
    reg [7:0] presented_data;
    reg presented_valid;
    wire slot_available = !presented_valid || byte_ready;
    wire [16:0] match_code = match_length - 17'd4;

    assign seq_ready = rst_n && state == IDLE;
    assign literal_en = rst_n && state == LITERAL_REQ;
    assign literal_addr = literal_pointer[15:0];
    assign byte_valid = rst_n && presented_valid;
    assign byte_data = byte_valid ? presented_data : 8'd0;
    assign done = rst_n && state == DONE;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            literal_pointer <= 17'd0;
            literal_remaining <= 17'd0;
            literal_extra <= 17'd0;
            match_extra <= 17'd0;
            offset <= 16'd0;
            final_only <= 1'b0;
            literal_saturated <= 1'b0;
            match_saturated <= 1'b0;
            token_literal <= 4'd0;
            token_match <= 4'd0;
            literal_hold <= 8'd0;
            presented_data <= 8'd0;
            presented_valid <= 1'b0;
        end else begin
            if (presented_valid && byte_ready)
                presented_valid <= 1'b0;
            case (state)
                IDLE: begin
                    if (seq_valid && seq_ready) begin
                        literal_pointer <= literal_start;
                        literal_remaining <= literal_length;
                        offset <= match_offset;
                        final_only <= final_sequence;
                        literal_saturated <= literal_length >= 17'd15;
                        match_saturated <= !final_sequence && match_length >= 17'd19;
                        if (literal_length >= 17'd15) begin
                            token_literal <= 4'd15;
                            literal_extra <= literal_length - 17'd15;
                        end else begin
                            token_literal <= literal_length[3:0];
                            literal_extra <= 17'd0;
                        end
                        if (final_sequence) begin
                            token_match <= 4'd0;
                            match_extra <= 17'd0;
                        end else if (match_length >= 17'd19) begin
                            token_match <= 4'd15;
                            match_extra <= match_length - 17'd19;
                        end else begin
                            token_match <= match_code[3:0];
                            match_extra <= 17'd0;
                        end
                        state <= TOKEN;
                    end
                end
                TOKEN: begin
                    if (slot_available) begin
                        presented_data <= {token_literal, token_match};
                        presented_valid <= 1'b1;
                        if (literal_saturated)
                            state <= LITERAL_EXT;
                        else if (literal_remaining != 17'd0)
                            state <= LITERAL_REQ;
                        else if (final_only)
                            state <= DRAIN;
                        else
                            state <= OFFSET_LOW;
                    end
                end
                LITERAL_EXT: begin
                    if (slot_available) begin
                        presented_valid <= 1'b1;
                        if (literal_extra >= 17'd255) begin
                            presented_data <= 8'd255;
                            literal_extra <= literal_extra - 17'd255;
                        end else begin
                            presented_data <= literal_extra[7:0];
                            if (literal_remaining != 17'd0)
                                state <= LITERAL_REQ;
                            else if (final_only)
                                state <= DRAIN;
                            else
                                state <= OFFSET_LOW;
                        end
                    end
                end
                LITERAL_REQ: state <= LITERAL_CAPTURE;
                LITERAL_CAPTURE: begin
                    literal_hold <= literal_data;
                    state <= LITERAL_BYTE;
                end
                LITERAL_BYTE: begin
                    if (slot_available) begin
                        presented_data <= literal_hold;
                        presented_valid <= 1'b1;
                        literal_pointer <= literal_pointer + 17'd1;
                        literal_remaining <= literal_remaining - 17'd1;
                        if (literal_remaining != 17'd1)
                            state <= LITERAL_REQ;
                        else if (final_only)
                            state <= DRAIN;
                        else
                            state <= OFFSET_LOW;
                    end
                end
                OFFSET_LOW: begin
                    if (slot_available) begin
                        presented_data <= offset[7:0];
                        presented_valid <= 1'b1;
                        state <= OFFSET_HIGH;
                    end
                end
                OFFSET_HIGH: begin
                    if (slot_available) begin
                        presented_data <= offset[15:8];
                        presented_valid <= 1'b1;
                        if (match_saturated)
                            state <= MATCH_EXT;
                        else
                            state <= DRAIN;
                    end
                end
                MATCH_EXT: begin
                    if (slot_available) begin
                        presented_valid <= 1'b1;
                        if (match_extra >= 17'd255) begin
                            presented_data <= 8'd255;
                            match_extra <= match_extra - 17'd255;
                        end else begin
                            presented_data <= match_extra[7:0];
                            state <= DRAIN;
                        end
                    end
                end
                DRAIN: begin
                    if (slot_available)
                        state <= DONE;
                end
                DONE: state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
