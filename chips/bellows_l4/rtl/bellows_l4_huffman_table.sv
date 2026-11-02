module bellows_l4_huffman_table (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire encode, input wire alphabet_w4,
    input wire hist_valid, output wire hist_ready,
    input wire [7:0] hist_symbol, input wire [31:0] hist_frequency,
    input wire length_valid, output wire length_ready,
    input wire [7:0] length_symbol, input wire [7:0] length_value,
    input wire build_valid, output wire build_ready,
    output wire table_valid, output wire [3:0] table_error,
    output wire depth_fallback,
    input wire lookup_valid, input wire [7:0] lookup_symbol,
    output wire lookup_result_valid,
    output wire [3:0] lookup_length, output wire [14:0] lookup_code,
    input wire decode_read, input wire [7:0] decode_index,
    output wire decode_result_valid, output wire [7:0] decode_symbol,
    output wire [255:0] first_codes,
    output wire [159:0] length_counts,
    output wire [159:0] first_indices
);
    localparam [4:0] IDLE=0, LOAD=1, SCAN_BEGIN=2, SCAN_REQ=3,
        SCAN_COMPARE=4, SCAN_END=5, MERGE=6, DEPTH_BEGIN=7,
        DEPTH_REQ=8, DEPTH_STEP=9, DEPTH_STORE=10, FALLBACK=11,
        CLEAR_COUNTS=12, COUNT_REQ=13, COUNT_USE=14, KRAFT=15,
        CODE_BEGIN=16, CODE_REQ=17, CODE_USE=18, DONE=19;
    reg [4:0] state;
    reg encoder, nibble_alphabet, bad_input, fallback;
    reg [3:0] error_code;
    reg [511:0] active, has_parent;
    reg [255:0] loaded_lengths;
    reg [8:0] last_node, next_node, scan_node, walk_node;
    reg [7:0] leaf, symbol_index;
    reg [4:0] depth;
    reg first_valid, second_valid;
    reg [8:0] first_node, second_node;
    reg [39:0] first_frequency, second_frequency;
    reg [7:0] first_minimum, second_minimum;
    reg [3:0] metric_length, code_length;
    reg [9:0] nonzero_symbols, prefix_count, sorted_count;
    reg singleton_one;
    reg [16:0] slots;
    reg [15:0] canonical_code;
    reg lookup_pending, decode_pending;

    (* ramstyle="MLAB", nomem2reg *) reg [39:0] frequency [0:511];
    (* ramstyle="MLAB", nomem2reg *) reg [7:0] minimum_symbol [0:511];
    (* ramstyle="MLAB", nomem2reg *) reg [8:0] parent [0:511];
    (* ramstyle="MLAB", nomem2reg *) reg [3:0] lengths [0:255];
    (* ramstyle="MLAB", nomem2reg *) reg [14:0] codes [0:255];
    (* ramstyle="MLAB", nomem2reg *) reg [7:0] sorted_symbols [0:255];
    (* nomem2reg *) reg [9:0] counts [0:15];
    (* nomem2reg *) reg [15:0] first_code [0:15];
    (* nomem2reg *) reg [9:0] first_index [0:15];
    reg [39:0] frequency_q;
    reg [7:0] minimum_q;
    reg [8:0] parent_q;
    reg [3:0] length_q, lookup_length_q;
    reg [14:0] lookup_code_q;
    reg [7:0] decode_symbol_q;

    wire [7:0] last_symbol=nibble_alphabet ? 8'd15 : 8'd255;
    wire better_first=!first_valid || frequency_q<first_frequency ||
        (frequency_q==first_frequency && minimum_q<first_minimum);
    wire better_second=!second_valid || frequency_q<second_frequency ||
        (frequency_q==second_frequency && minimum_q<second_minimum);
    wire [17:0] doubled_slots={slots,1'b0};
    wire [17:0] next_slots=doubled_slots-{8'd0,counts[metric_length]};
    wire special_table=nonzero_symbols==0 ||
        (nonzero_symbols==1 && singleton_one);
    wire histogram_accept=hist_valid && hist_ready;
    wire length_accept=length_valid && length_ready;
    wire start_accept=start_valid && start_ready;
    wire lookup_accept=lookup_valid && table_valid && error_code==0 &&
        (!nibble_alphabet || lookup_symbol<16);
    wire decode_accept=decode_read && table_valid && error_code==0;

    assign start_ready=rst_n && !clear && (state==IDLE || state==DONE);
    assign hist_ready=rst_n && !clear && state==LOAD && encoder && !build_valid;
    assign length_ready=rst_n && !clear && state==LOAD && !encoder && !build_valid;
    assign build_ready=rst_n && !clear && state==LOAD;
    assign table_valid=rst_n && !clear && state==DONE;
    assign table_error=table_valid ? error_code : 4'd0;
    assign depth_fallback=table_valid && fallback;
    assign lookup_result_valid=rst_n && !clear && lookup_pending;
    assign lookup_length=lookup_result_valid ? lookup_length_q : 4'd0;
    assign lookup_code=lookup_result_valid && lookup_length_q!=0 ?
        lookup_code_q : 15'd0;
    assign decode_result_valid=rst_n && !clear && decode_pending;
    assign decode_symbol=decode_result_valid ? decode_symbol_q : 8'd0;
    genvar l;
    generate
        for (l=0;l<16;l=l+1) begin : canonical_metadata
            assign first_codes[l*16 +: 16]=table_valid && error_code==0 ?
                first_code[l] : 16'd0;
            assign length_counts[l*10 +: 10]=table_valid && error_code==0 ?
                counts[l] : 10'd0;
            assign first_indices[l*10 +: 10]=table_valid && error_code==0 ?
                first_index[l] : 10'd0;
        end
    endgenerate

    // Array processes have no asynchronous data reset. Validity and complete
    // per-command leaf loading protect all reads of uninitialized storage.
    always @(posedge clk) begin
        if (rst_n && !clear) begin
            if (histogram_accept && (!nibble_alphabet || hist_symbol<16)) begin
                frequency[{1'b0,hist_symbol}]<={8'd0,hist_frequency};
                minimum_symbol[{1'b0,hist_symbol}]<=hist_symbol;
            end
            if (length_accept && (!nibble_alphabet || length_symbol<16) &&
                length_value<=15)
                lengths[length_symbol]<=length_value[3:0];
            if (state==SCAN_REQ) begin
                frequency_q<=frequency[scan_node];
                minimum_q<=minimum_symbol[scan_node];
            end
            if (state==MERGE) begin
                frequency[next_node]<=first_frequency+second_frequency;
                minimum_symbol[next_node]<=first_minimum<second_minimum ?
                    first_minimum : second_minimum;
                parent[first_node]<=next_node;
                parent[second_node]<=next_node;
            end
            if (state==DEPTH_REQ && has_parent[walk_node])
                parent_q<=parent[walk_node];
            if (state==DEPTH_STORE)
                lengths[leaf]<=depth==0 ? 4'd1 : depth[3:0];
            if (state==DEPTH_BEGIN && !active[{1'b0,leaf}] &&
                !has_parent[{1'b0,leaf}])
                lengths[leaf]<=0;
            if (state==FALLBACK)
                lengths[leaf]<=nibble_alphabet ? 4'd4 : 4'd8;
            if (state==CLEAR_COUNTS) begin
                counts[metric_length]<=0;
                first_code[metric_length]<=0;
                first_index[metric_length]<=0;
            end
            if (state==COUNT_REQ) length_q<=lengths[leaf];
            if (state==COUNT_USE && length_q!=0)
                counts[length_q]<=counts[length_q]+10'd1;
            if (state==KRAFT) begin
                first_code[metric_length]<=canonical_code;
                first_index[metric_length]<=prefix_count;
            end
            if (state==CODE_REQ) length_q<=lengths[symbol_index];
            if (state==CODE_USE && length_q==code_length) begin
                codes[symbol_index]<=canonical_code[14:0];
                sorted_symbols[sorted_count[7:0]]<=symbol_index;
            end
            if (lookup_accept) begin
                lookup_length_q<=lengths[lookup_symbol];
                lookup_code_q<=codes[lookup_symbol];
            end
            if (decode_accept) decode_symbol_q<=sorted_symbols[decode_index];
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; encoder<=0; nibble_alphabet<=0; bad_input<=0;
            fallback<=0; error_code<=0; active<=0; has_parent<=0; loaded_lengths<=0;
            last_node<=0; next_node<=0; scan_node<=0; walk_node<=0;
            leaf<=0; symbol_index<=0; depth<=0;
            first_valid<=0; second_valid<=0; first_node<=0; second_node<=0;
            first_frequency<=0; second_frequency<=0;
            first_minimum<=0; second_minimum<=0;
            metric_length<=0; code_length<=0; nonzero_symbols<=0;
            prefix_count<=0; sorted_count<=0; singleton_one<=0;
            slots<=0; canonical_code<=0; lookup_pending<=0; decode_pending<=0;
        end else if (clear) begin
            state<=IDLE; bad_input<=0; fallback<=0; error_code<=0;
            active<=0; has_parent<=0; loaded_lengths<=0;
            lookup_pending<=0; decode_pending<=0;
        end else begin
            lookup_pending<=lookup_accept;
            decode_pending<=decode_accept;
            if (start_accept) begin
                state<=LOAD; encoder<=encode; nibble_alphabet<=alphabet_w4;
                bad_input<=0; fallback<=0; error_code<=0;
                active<=0; has_parent<=0; loaded_lengths<=0; leaf<=0; symbol_index<=0;
                last_node<=alphabet_w4 ? 9'd15 : 9'd255;
                next_node<=alphabet_w4 ? 9'd16 : 9'd256;
                scan_node<=0; walk_node<=0; depth<=0;
                first_valid<=0; second_valid<=0;
                metric_length<=0; code_length<=0; nonzero_symbols<=0;
                prefix_count<=0; sorted_count<=0; singleton_one<=0;
                slots<=0; canonical_code<=0;
            end else begin
                if (histogram_accept) begin
                    if (nibble_alphabet && hist_symbol>=16) bad_input<=1;
                    else active[{1'b0,hist_symbol}]<=hist_frequency!=0;
                end
                if (length_accept && (length_value>15 ||
                    (nibble_alphabet && length_symbol>=16))) bad_input<=1;
                if (length_accept && length_value<=15 &&
                    (!nibble_alphabet || length_symbol<16))
                    loaded_lengths[length_symbol]<=1;
                case (state)
                    IDLE: begin end
                    LOAD: if (build_valid) begin
                        if (bad_input || (!encoder &&
                            (nibble_alphabet ? loaded_lengths[15:0]!=16'hffff :
                                loaded_lengths!={256{1'b1}}))) begin
                            error_code<=11; state<=DONE;
                        end
                        else if (encoder) state<=SCAN_BEGIN;
                        else begin metric_length<=0; state<=CLEAR_COUNTS; end
                    end
                    SCAN_BEGIN: begin
                        first_valid<=0; second_valid<=0; scan_node<=0;
                        state<=SCAN_REQ;
                    end
                    SCAN_REQ: state<=SCAN_COMPARE;
                    SCAN_COMPARE: begin
                        if (active[scan_node]) begin
                            if (better_first) begin
                                second_valid<=first_valid;
                                second_node<=first_node;
                                second_frequency<=first_frequency;
                                second_minimum<=first_minimum;
                                first_valid<=1; first_node<=scan_node;
                                first_frequency<=frequency_q; first_minimum<=minimum_q;
                            end else if (better_second) begin
                                second_valid<=1; second_node<=scan_node;
                                second_frequency<=frequency_q; second_minimum<=minimum_q;
                            end
                        end
                        if (scan_node==last_node) state<=SCAN_END;
                        else begin scan_node<=scan_node+9'd1; state<=SCAN_REQ; end
                    end
                    SCAN_END: begin
                        if (second_valid) state<=MERGE;
                        else begin leaf<=0; state<=DEPTH_BEGIN; end
                    end
                    MERGE: begin
                        active[first_node]<=0; active[second_node]<=0;
                        active[next_node]<=1;
                        has_parent[first_node]<=1; has_parent[second_node]<=1;
                        last_node<=next_node; next_node<=next_node+9'd1;
                        state<=SCAN_BEGIN;
                    end
                    DEPTH_BEGIN: begin
                        depth<=0; walk_node<={1'b0,leaf};
                        if (!active[{1'b0,leaf}] && !has_parent[{1'b0,leaf}]) begin
                            if (leaf==last_symbol) begin
                                metric_length<=0; state<=CLEAR_COUNTS;
                            end else leaf<=leaf+8'd1;
                        end else state<=DEPTH_REQ;
                    end
                    DEPTH_REQ: begin
                        if (has_parent[walk_node]) state<=DEPTH_STEP;
                        else state<=DEPTH_STORE;
                    end
                    DEPTH_STEP: begin
                        walk_node<=parent_q; depth<=depth+5'd1;
                        if (depth==15) begin
                            fallback<=1; leaf<=0; state<=FALLBACK;
                        end else state<=DEPTH_REQ;
                    end
                    DEPTH_STORE: begin
                        if (leaf==last_symbol) begin
                            metric_length<=0; state<=CLEAR_COUNTS;
                        end else begin leaf<=leaf+8'd1; state<=DEPTH_BEGIN; end
                    end
                    FALLBACK: begin
                        if (leaf==last_symbol) begin
                            metric_length<=0; state<=CLEAR_COUNTS;
                        end else leaf<=leaf+8'd1;
                    end
                    CLEAR_COUNTS: begin
                        if (metric_length==15) begin
                            leaf<=0; nonzero_symbols<=0; singleton_one<=0;
                            state<=COUNT_REQ;
                        end else metric_length<=metric_length+4'd1;
                    end
                    COUNT_REQ: state<=COUNT_USE;
                    COUNT_USE: begin
                        if (length_q!=0) begin
                            nonzero_symbols<=nonzero_symbols+10'd1;
                            singleton_one<=length_q==1;
                        end
                        if (leaf==last_symbol) begin
                            metric_length<=1; slots<=1; canonical_code<=0;
                            prefix_count<=0; state<=KRAFT;
                        end else begin leaf<=leaf+8'd1; state<=COUNT_REQ; end
                    end
                    KRAFT: begin
                        if (doubled_slots<{8'd0,counts[metric_length]}) begin
                            error_code<=11; state<=DONE;
                        end else begin
                            slots<=next_slots[16:0];
                            canonical_code<=(canonical_code+counts[metric_length])<<1;
                            prefix_count<=prefix_count+counts[metric_length];
                            if (metric_length==15) begin
                                if (next_slots!=0 && !special_table) begin
                                    error_code<=11; state<=DONE;
                                end else state<=CODE_BEGIN;
                            end else metric_length<=metric_length+4'd1;
                        end
                    end
                    CODE_BEGIN: begin
                        code_length<=1; symbol_index<=0; canonical_code<=first_code[1];
                        sorted_count<=0; state<=CODE_REQ;
                    end
                    CODE_REQ: state<=CODE_USE;
                    CODE_USE: begin
                        if (length_q==code_length) begin
                            canonical_code<=canonical_code+16'd1;
                            sorted_count<=sorted_count+10'd1;
                        end
                        if (symbol_index==last_symbol) begin
                            if (code_length==15) state<=DONE;
                            else begin
                                code_length<=code_length+4'd1; symbol_index<=0;
                                canonical_code<=first_code[code_length+4'd1];
                                state<=CODE_REQ;
                            end
                        end else begin
                            symbol_index<=symbol_index+8'd1; state<=CODE_REQ;
                        end
                    end
                    DONE: begin end
                    default: begin error_code<=11; state<=DONE; end
                endcase
            end
        end
    end
endmodule
