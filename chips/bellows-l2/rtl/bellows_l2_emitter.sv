module bellows_l2_emitter (
    input wire clk, rst_n,
    input wire seq_valid,
    output wire seq_ready,
    input wire [16:0] literal_start, literal_length, match_length,
    input wire [15:0] match_offset,
    input wire final_sequence,
    output wire literal_en,
    output wire [15:0] literal_addr,
    input wire [7:0] literal_data,
    output logic [7:0] byte_data,
    output logic byte_valid,
    input wire byte_ready,
    output wire done
);
    typedef enum logic [3:0] {
        IDLE, TOKEN, LITERAL_EXT, LITERAL_REQ, LITERAL_BYTE,
        OFFSET_LOW, OFFSET_HIGH, MATCH_EXT, DONE
    } state_t;
    state_t state;
    logic [15:0] literal_pointer, offset;
    logic [16:0] literal_left, literal_extra, match_extra;
    logic [3:0] token_literal, token_match;
    logic final_only;
    wire [3:0] short_match_code = match_length[3:0] - 4'd4;
    wire literal_advance = state == LITERAL_BYTE && byte_ready && literal_left != 17'd1;

    assign seq_ready = rst_n && state == IDLE;
    assign literal_en = rst_n && (state == LITERAL_REQ || literal_advance);
    assign literal_addr = literal_pointer + {15'd0, literal_advance};
    assign done = rst_n && state == DONE;

    always_comb begin
        byte_valid = rst_n;
        byte_data = '0;
        case (state)
            TOKEN: byte_data = {token_literal, token_match};
            LITERAL_EXT: byte_data = literal_extra >= 17'd255 ? 8'd255 : literal_extra[7:0];
            LITERAL_BYTE: byte_data = literal_data;
            OFFSET_LOW: byte_data = offset[7:0];
            OFFSET_HIGH: byte_data = offset[15:8];
            MATCH_EXT: byte_data = match_extra >= 17'd255 ? 8'd255 : match_extra[7:0];
            default: byte_valid = 1'b0;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
        end else begin
            case (state)
                IDLE: if (seq_valid) begin
                    literal_pointer <= literal_start[15:0];
                    literal_left <= literal_length;
                    offset <= match_offset;
                    final_only <= final_sequence;
                    token_literal <= literal_length >= 17'd15 ? 4'd15 : literal_length[3:0];
                    literal_extra <= literal_length - 17'd15;
                    token_match <= final_sequence ? 4'd0 :
                        match_length >= 17'd19 ? 4'd15 : short_match_code;
                    match_extra <= match_length - 17'd19;
                    state <= TOKEN;
                end
                TOKEN: if (byte_ready) begin
                    if (token_literal == 4'd15)
                        state <= LITERAL_EXT;
                    else if (literal_left != 0)
                        state <= LITERAL_REQ;
                    else
                        state <= final_only ? DONE : OFFSET_LOW;
                end
                LITERAL_EXT: if (byte_ready) begin
                    if (literal_extra >= 17'd255)
                        literal_extra <= literal_extra - 17'd255;
                    else
                        state <= LITERAL_REQ;
                end
                LITERAL_REQ: state <= LITERAL_BYTE;
                LITERAL_BYTE: if (byte_ready) begin
                    literal_pointer <= literal_pointer + 16'd1;
                    literal_left <= literal_left - 17'd1;
                    if (literal_left == 17'd1)
                        state <= final_only ? DONE : OFFSET_LOW;
                end
                OFFSET_LOW: if (byte_ready)
                    state <= OFFSET_HIGH;
                OFFSET_HIGH: if (byte_ready)
                    state <= token_match == 4'd15 ? MATCH_EXT : DONE;
                MATCH_EXT: if (byte_ready) begin
                    if (match_extra >= 17'd255)
                        match_extra <= match_extra - 17'd255;
                    else
                        state <= DONE;
                end
                DONE: state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
