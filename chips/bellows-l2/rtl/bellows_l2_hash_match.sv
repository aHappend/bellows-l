module bellows_l2_hash_match (
    input wire clk, rst_n, start,
    input wire [16:0] block_length,
    output wire a_en, b_en,
    output wire [15:0] a_addr, b_addr,
    input wire [31:0] a_data, b_data,
    output wire match_valid,
    output wire [16:0] match_position, match_length,
    output wire [15:0] match_offset,
    input wire match_ready,
    output wire done
);
    typedef enum logic [3:0] {
        IDLE, KEY, HASH, LOOKUP, INSERT, HEAD_READ, HEAD_CHECK,
        EXT_READ, EXT_COMPARE, RESULT, DONE
    } state_t;
    state_t state;
    logic [16:0] position, last_start, limit_addr;
    logic [16:0] source_end, candidate_end, length;
    logic [15:0] offset, old_position;
    logic [7:0] hash_value;
    logic [2:0] ext_width;
    logic ext_last;
    logic [255:0] table_valid;
    logic old_valid;
    logic [31:0] key_data;
    (* ramstyle = "MLAB, no_rw_check" *) logic [15:0] table_position [0:255];

    wire [7:0] k0 = a_data[7:0], k1 = a_data[15:8];
    wire [7:0] k2 = a_data[23:16], k3 = a_data[31:24];
    wire [2:0] equal_prefix =
        a_data[7:0] != b_data[7:0] ? 3'd0 :
        a_data[15:8] != b_data[15:8] ? 3'd1 :
        a_data[23:16] != b_data[23:16] ? 3'd2 :
        a_data[31:24] != b_data[31:24] ? 3'd3 : 3'd4;
    wire [16:0] tail_left = limit_addr - source_end;
    wire [2:0] step = equal_prefix <= ext_width ? equal_prefix : ext_width;

    assign a_en = rst_n && (state == KEY || state == EXT_READ);
    assign b_en = rst_n && (state == HEAD_READ || state == EXT_READ);
    assign a_addr = state == EXT_READ ? source_end[15:0] : position[15:0];
    assign b_addr = state == EXT_READ ? candidate_end[15:0] : old_position;
    assign match_valid = rst_n && state == RESULT;
    assign match_position = position;
    assign match_length = length;
    assign match_offset = offset;
    assign done = rst_n && state == DONE;

    // Use separate edges for old-entry lookup and insertion, independent
    // of the inferred RAM's read-during-write behavior.
    always_ff @(posedge clk) begin
        if (rst_n && state == LOOKUP)
            old_position <= table_position[hash_value];
        if (rst_n && state == INSERT)
            table_position[hash_value] <= position[15:0];
        if (state == HASH)
            key_data <= a_data;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            table_valid <= '0;
        end else if (start) begin
            position <= '0;
            table_valid <= '0;
            last_start <= block_length - 17'd12;
            limit_addr <= block_length - 17'd5;
            state <= block_length < 17'd13 ? DONE : KEY;
        end else begin
            case (state)
                KEY: state <= HASH;
                HASH: begin
                    hash_value <= k0 ^ {k1[6:0], k1[7]} ^ {k2[5:0], k2[7:6]} ^ {k3[4:0], k3[7:5]};
                    state <= LOOKUP;
                end
                LOOKUP: begin
                    old_valid <= table_valid[hash_value];
                    state <= INSERT;
                end
                INSERT: begin
                    table_valid[hash_value] <= 1'b1;
                    if (old_valid) begin
                        // Visited starts are strictly increasing and fit in 16 bits.
                        offset <= position[15:0] - old_position;
                        state <= HEAD_READ;
                    end else begin
                        position <= position + 17'd1;
                        state <= position == last_start ? DONE : KEY;
                    end
                end
                HEAD_READ: state <= HEAD_CHECK;
                HEAD_CHECK: begin
                    if (key_data == b_data) begin
                        source_end <= position + 17'd4;
                        candidate_end <= {1'b0, old_position} + 17'd4;
                        length <= 17'd4;
                        state <= EXT_READ;
                    end else begin
                        position <= position + 17'd1;
                        state <= position == last_start ? DONE : KEY;
                    end
                end
                EXT_READ: begin
                    ext_width <= tail_left >= 17'd4 ? 3'd4 : tail_left[2:0];
                    ext_last <= tail_left <= 17'd4;
                    state <= EXT_COMPARE;
                end
                EXT_COMPARE: begin
                    source_end <= source_end + {14'd0, step};
                    candidate_end <= candidate_end + 17'd4;
                    length <= length + {14'd0, step};
                    if (step < 3'd4 || ext_last)
                        state <= RESULT;
                    else
                        state <= EXT_READ;
                end
                RESULT: if (match_ready) begin
                    position <= source_end;
                    state <= source_end > last_start ? DONE : KEY;
                end
                default: ;
            endcase
        end
    end
endmodule
