module bellows_l2_hash_match (
    input wire clk,
    input wire rst_n,
    input wire start,
    input wire [16:0] block_length,
    output wire a_en,
    output wire [15:0] a_addr,
    input wire [7:0] a_data,
    output wire b_en,
    output wire [15:0] b_addr,
    input wire [7:0] b_data,
    output wire match_valid,
    output wire [16:0] match_position,
    output wire [16:0] match_length,
    output wire [15:0] match_offset,
    input wire match_ready,
    output wire done
);
    localparam [4:0]
        IDLE = 5'd0, CHECK = 5'd1,
        KEY_REQ = 5'd2, KEY_CAPTURE = 5'd3,
        HASH = 5'd4, LOOKUP = 5'd5, VALIDATE = 5'd6,
        COMPARE_REQ = 5'd7, COMPARE_CAPTURE = 5'd8,
        EXT_CHECK = 5'd9, EXT_REQ = 5'd10, EXT_CAPTURE = 5'd11,
        RESULT = 5'd12, DONE = 5'd13;

    reg [4:0] state;
    reg [16:0] size;
    reg [16:0] position;
    reg [1:0] byte_index;
    reg [7:0] key0, key1, key2, key3;
    reg [7:0] hash_value;
    reg [255:0] table_valid;
    (* ramstyle = "MLAB", nomem2reg *)
    reg [15:0] table_position [0:255];
    reg [15:0] old_position;
    reg old_valid;
    reg [15:0] offset;
    reg [16:0] length;
    reg [16:0] source_end;
    reg [16:0] candidate_end;
    reg [7:0] compare_key;

    wire [16:0] key_address = position + {15'd0, byte_index};
    wire [16:0] compare_address = {1'b0, old_position} + {15'd0, byte_index};
    wire [16:0] distance = position - {1'b0, old_position};
    wire [16:0] last_start = size - 17'd12;
    wire [16:0] extension_limit = size - 17'd5;

    assign a_en = rst_n && (state == KEY_REQ || state == EXT_REQ);
    assign a_addr = !rst_n ? 16'd0 :
                    state == EXT_REQ ? source_end[15:0] : key_address[15:0];
    assign b_en = rst_n && (state == COMPARE_REQ || state == EXT_REQ);
    assign b_addr = !rst_n ? 16'd0 :
                    state == EXT_REQ ? candidate_end[15:0] : compare_address[15:0];
    assign match_valid = rst_n && state == RESULT;
    assign match_position = rst_n ? position : 17'd0;
    assign match_length = rst_n ? length : 17'd0;
    assign match_offset = rst_n ? offset : 16'd0;
    assign done = rst_n && state == DONE;

    always @* begin
        case (byte_index)
            2'd0: compare_key = key0;
            2'd1: compare_key = key1;
            2'd2: compare_key = key2;
            default: compare_key = key3;
        endcase
    end

    // Nonblocking read/write preserves the old direct-mapped entry.
    always @(posedge clk) begin
        if (rst_n && state == LOOKUP) begin
            old_position <= table_position[hash_value];
            table_position[hash_value] <= position[15:0];
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            size <= 17'd0;
            position <= 17'd0;
            byte_index <= 2'd0;
            key0 <= 8'd0;
            key1 <= 8'd0;
            key2 <= 8'd0;
            key3 <= 8'd0;
            hash_value <= 8'd0;
            table_valid <= 256'd0;
            old_valid <= 1'b0;
            offset <= 16'd0;
            length <= 17'd0;
            source_end <= 17'd0;
            candidate_end <= 17'd0;
        end else if (start) begin
            size <= block_length;
            position <= 17'd0;
            table_valid <= 256'd0;
            old_valid <= 1'b0;
            byte_index <= 2'd0;
            length <= 17'd0;
            state <= CHECK;
        end else begin
            case (state)
                IDLE: begin end
                CHECK: begin
                    if (size < 17'd13 || position > last_start) begin
                        state <= DONE;
                    end else begin
                        byte_index <= 2'd0;
                        state <= KEY_REQ;
                    end
                end
                KEY_REQ: state <= KEY_CAPTURE;
                KEY_CAPTURE: begin
                    case (byte_index)
                        2'd0: key0 <= a_data;
                        2'd1: key1 <= a_data;
                        2'd2: key2 <= a_data;
                        2'd3: key3 <= a_data;
                    endcase
                    if (byte_index == 2'd3) begin
                        state <= HASH;
                    end else begin
                        byte_index <= byte_index + 2'd1;
                        state <= KEY_REQ;
                    end
                end
                HASH: begin
                    hash_value <= key0 ^ {key1[6:0], key1[7]} ^
                                  {key2[5:0], key2[7:6]} ^
                                  {key3[4:0], key3[7:5]};
                    state <= LOOKUP;
                end
                LOOKUP: begin
                    old_valid <= table_valid[hash_value];
                    table_valid[hash_value] <= 1'b1;
                    state <= VALIDATE;
                end
                VALIDATE: begin
                    if (old_valid && {1'b0, old_position} < position &&
                        distance >= 17'd1 && distance <= 17'd65535) begin
                        offset <= distance[15:0];
                        byte_index <= 2'd0;
                        state <= COMPARE_REQ;
                    end else begin
                        position <= position + 17'd1;
                        state <= CHECK;
                    end
                end
                COMPARE_REQ: state <= COMPARE_CAPTURE;
                COMPARE_CAPTURE: begin
                    if (b_data != compare_key) begin
                        position <= position + 17'd1;
                        state <= CHECK;
                    end else if (byte_index == 2'd3) begin
                        length <= 17'd4;
                        source_end <= position + 17'd4;
                        candidate_end <= {1'b0, old_position} + 17'd4;
                        state <= EXT_CHECK;
                    end else begin
                        byte_index <= byte_index + 2'd1;
                        state <= COMPARE_REQ;
                    end
                end
                EXT_CHECK: begin
                    if (source_end >= extension_limit)
                        state <= RESULT;
                    else
                        state <= EXT_REQ;
                end
                EXT_REQ: state <= EXT_CAPTURE;
                EXT_CAPTURE: begin
                    if (a_data == b_data) begin
                        length <= length + 17'd1;
                        source_end <= source_end + 17'd1;
                        candidate_end <= candidate_end + 17'd1;
                        state <= EXT_CHECK;
                    end else begin
                        state <= RESULT;
                    end
                end
                RESULT: begin
                    if (match_ready) begin
                        position <= source_end;
                        state <= CHECK;
                    end
                end
                DONE: begin end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
