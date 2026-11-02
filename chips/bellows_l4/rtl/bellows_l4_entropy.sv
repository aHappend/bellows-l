module bellows_l4_entropy #(
    parameter integer MAX_BLOCK_BYTES=65536
) (
    input wire clk, input wire rst_n,
    input wire start_valid, output wire start_ready,
    input wire decompress, input wire [2:0] codec,
    input wire [31:0] raw_bytes, input wire [31:0] input_bytes,
    input wire s_valid, output wire s_ready,
    input wire [7:0] s_data, input wire s_last,
    output wire m_valid, input wire m_ready,
    output wire [7:0] m_data, output wire m_last,
    output wire status_valid, input wire status_ready,
    output wire [3:0] status_error,
    output wire [31:0] result_raw_bytes,
    output wire [31:0] result_source_bytes,
    output wire [31:0] result_output_bytes
);
    localparam integer LEGAL=MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536;
    localparam integer SAFE_BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer SYMBOL_BYTES=2*SAFE_BLOCK+16;
    localparam integer RESIDUAL_BYTES=(SAFE_BLOCK+1)>>1;
    localparam integer SYMBOL_BITS=$clog2(SYMBOL_BYTES);
    localparam integer RESIDUAL_BITS=RESIDUAL_BYTES>1 ? $clog2(RESIDUAL_BYTES) : 1;
    localparam integer FRAME_LIMIT=4*SAFE_BLOCK+1024;
    localparam [5:0] IDLE=0, E_INIT=1, E_COLLECT=2, E_HIST_UPDATE=3,
        E_HIGH_REQ=4, E_HIGH_UPDATE=5, E_HIST_REQ=6, E_HIST_SEND=7,
        BUILD_REQ=8, BUILD_WAIT=9, E_SUM_REQ=10, E_SUM_WAIT=11,
        E_SUM_ADD=12, E_SIZE=13, E_HEADER=14, E_LENGTH_REQ=15,
        E_LENGTH_WAIT=16, E_LENGTH_SEND=17, E_RES_REQ=18,
        E_RES_WAIT=19, E_RES_SEND=20, E_SYMBOL_REQ=21,
        E_SYMBOL_LOOKUP=22, E_SYMBOL_WAIT=23, E_BIT=24,
        E_FLUSH=25, E_NEXT=26, E_TAIL=27, D_HEADER=28,
        D_HEADER_CHECK=29, D_LENGTH=30, D_RES=31, D_PREP=32,
        D_PAYLOAD=33, D_BIT=34, D_SYMBOL_WAIT=35, D_BYTE=36,
        D_BF_LOW=37, D_BF_HIGH=38, D_NEXT=39, FINISH=40, STATUS=41;
    reg [5:0] state;
    reg decoding;
    reg [2:0] selected_codec;
    reg [3:0] error_code;
    reg [31:0] source_length, original_length, symbol_count, bit_count;
    reg [31:0] input_index, output_count, symbol_index, residual_index;
    reg [31:0] target_output, emitted_symbols, consumed_bits;
    reg [7:0] table_index, low_byte, high_nibble, held_upper, held_nibble;
    reg [4:0] header_index, decode_depth;
    reg [7:0] histogram_symbol;
    reg [36:0] bit_product;
    reg [15:0] code_bits, decode_code;
    reg [4:0] code_remaining;
    reg [7:0] packed_byte, payload_byte, output_data;
    reg [2:0] pack_fill;
    reg [3:0] payload_left;
    reg output_valid;

    (* ramstyle="MLAB", nomem2reg *) reg [31:0] histogram [0:255];
    (* ramstyle="M20K", nomem2reg *) reg [7:0] symbols [0:SYMBOL_BYTES-1];
    (* ramstyle="M20K", nomem2reg *) reg [7:0] residuals [0:RESIDUAL_BYTES-1];
    reg [31:0] histogram_q;
    reg [7:0] symbol_q, residual_q;

    wire table_start_ready, hist_ready, length_ready, build_ready;
    wire table_valid;
    wire [3:0] table_error;
    wire lookup_result_valid, decode_result_valid;
    wire [3:0] lookup_length;
    wire [14:0] lookup_code;
    wire [7:0] decoded_symbol;
    wire [255:0] first_codes;
    wire [159:0] length_counts, first_indices;
    wire start_accept=start_valid && start_ready;
    wire source_accept=s_valid && s_ready;
    wire output_accept=m_valid && m_ready;
    wire [31:0] table_bytes=selected_codec==3 ? 32'd16 : 32'd256;
    wire [7:0] last_symbol=selected_codec==3 ? 8'd15 : 8'd255;
    wire [31:0] residual_length=selected_codec==2 ? original_length>>1 : 32'd0;
    wire [32:0] payload_length=({1'b0,bit_count}+33'd7)>>3;
    wire [32:0] frame_length=33'd20+{1'b0,table_bytes}+
        {1'b0,residual_length}+payload_length;
    wire [37:0] next_bit_sum={6'd0,bit_count}+{1'b0,bit_product};
    wire [36:0] maximum_bits={5'd0,symbol_count}*37'd15;
    wire [10:0] codebook_symbols=
        {1'b0,first_indices[15*10 +: 10]}+
        {1'b0,length_counts[15*10 +: 10]};
    wire [7:0] input_symbol=selected_codec==2 ?
        {s_data[6:0],low_byte[7]} :
        selected_codec==3 ? {4'd0,s_data[3:0]} : s_data;
    wire collect_symbol=source_accept && state==E_COLLECT &&
        (selected_codec!=2 || input_index[0]);
    wire header_bad=(header_index==0 && s_data!=8'h42) ||
        (header_index==1 && s_data!=8'h4c) ||
        (header_index==2 && s_data!=8'h34) ||
        (header_index==3 && s_data!=8'h48) ||
        (header_index==4 && s_data!=1) ||
        (header_index==5 && s_data!={5'd0,selected_codec}) ||
        ((header_index==6 || header_index==7) && s_data!=0);
    wire header_sizes_bad=original_length>SAFE_BLOCK ||
        (selected_codec==1 && symbol_count!=original_length) ||
        (selected_codec==2 && (original_length[0] ||
            symbol_count!=(original_length>>1))) ||
        (selected_codec==3 && {1'b0,symbol_count}!=({1'b0,original_length}<<1)) ||
        (selected_codec==4 && symbol_count>SYMBOL_BYTES) ||
        (symbol_count==0 && bit_count!=0) ||
        (symbol_count!=0 && (bit_count<symbol_count ||
            {5'd0,bit_count}>maximum_bits)) ||
        frame_length!={1'b0,source_length} || frame_length>FRAME_LIMIT;
    wire command_bad=codec<1 || codec>4 ||
        (!decompress && (raw_bytes>SAFE_BLOCK ||
            (codec!=4 && input_bytes!=raw_bytes) ||
            (codec==4 && input_bytes>SYMBOL_BYTES) ||
            (codec==2 && raw_bytes[0]))) ||
        (decompress && input_bytes>FRAME_LIMIT);
    wire [4:0] next_depth=decode_depth+5'd1;
    wire [15:0] next_decode_code={decode_code[14:0],payload_byte[7]};
    wire [15:0] selected_first=next_depth<=15 ?
        first_codes[next_depth*16 +: 16] : 16'd0;
    wire [9:0] selected_count=next_depth<=15 ?
        length_counts[next_depth*10 +: 10] : 10'd0;
    wire [9:0] selected_index=next_depth<=15 ?
        first_indices[next_depth*10 +: 10] : 10'd0;
    wire [16:0] relative_code={1'b0,next_decode_code}-{1'b0,selected_first};
    wire decode_match=next_depth<=15 && next_decode_code>=selected_first &&
        relative_code<{7'd0,selected_count};
    wire [9:0] canonical_index=selected_index+relative_code[9:0];
    wire decode_request=rst_n && state==D_BIT && payload_left!=0 &&
        consumed_bits<bit_count && decode_match;
    wire table_lookup=rst_n && (state==E_SUM_REQ ||
        state==E_LENGTH_REQ || state==E_SYMBOL_LOOKUP);
    wire [7:0] lookup_symbol=state==E_SYMBOL_LOOKUP ? symbol_q : table_index;

    assign start_ready=rst_n && LEGAL && state==IDLE && table_start_ready;
    assign s_ready=rst_n && LEGAL && error_code==0 && input_index<source_length &&
        (state==E_COLLECT || state==D_HEADER ||
         (state==D_LENGTH && length_ready) || state==D_RES || state==D_PAYLOAD);
    assign m_valid=rst_n && LEGAL && error_code==0 && output_valid;
    assign m_data=m_valid ? output_data : 8'd0;
    assign m_last=m_valid && output_count+32'd1==target_output;
    assign status_valid=rst_n && LEGAL && state==STATUS;
    assign status_error=status_valid ? error_code : 4'd0;
    assign result_raw_bytes=rst_n ? original_length : 32'd0;
    assign result_source_bytes=rst_n ? input_index : 32'd0;
    assign result_output_bytes=rst_n ? output_count : 32'd0;

    bellows_l4_huffman_table codebook (
        .clk(clk), .rst_n(rst_n), .clear(state==STATUS && status_ready),
        .start_valid(start_accept), .start_ready(table_start_ready),
        .encode(!decompress), .alphabet_w4(codec==3),
        .hist_valid(state==E_HIST_SEND), .hist_ready(hist_ready),
        .hist_symbol(table_index), .hist_frequency(histogram_q),
        .length_valid(state==D_LENGTH && source_accept), .length_ready(length_ready),
        .length_symbol(table_index), .length_value(s_data),
        .build_valid(state==BUILD_REQ), .build_ready(build_ready),
        .table_valid(table_valid), .table_error(table_error), .depth_fallback(),
        .lookup_valid(table_lookup), .lookup_symbol(lookup_symbol),
        .lookup_result_valid(lookup_result_valid),
        .lookup_length(lookup_length), .lookup_code(lookup_code),
        .decode_read(decode_request), .decode_index(canonical_index[7:0]),
        .decode_result_valid(decode_result_valid), .decode_symbol(decoded_symbol),
        .first_codes(first_codes), .length_counts(length_counts),
        .first_indices(first_indices)
    );

    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: MAX_BLOCK_BYTES=1..65536");
        end
    endgenerate

    always @(posedge clk) begin
        if (rst_n) begin
            if (state==E_INIT) histogram[table_index]<=0;
            if (collect_symbol) begin
                histogram_q<=histogram[input_symbol];
                symbols[symbol_index[SYMBOL_BITS-1:0]]<=input_symbol;
                if (selected_codec==2)
                    residuals[input_index>>1]<={s_data[7],low_byte[6:0]};
            end
            if (state==E_HIST_UPDATE)
                histogram[histogram_symbol]<=histogram_q+32'd1;
            if (state==E_HIGH_REQ) begin
                histogram_q<=histogram[{4'd0,high_nibble[3:0]}];
                symbols[symbol_index[SYMBOL_BITS-1:0]]<={4'd0,high_nibble[3:0]};
            end
            if (state==E_HIGH_UPDATE)
                histogram[{4'd0,high_nibble[3:0]}]<=histogram_q+32'd1;
            if (state==E_HIST_REQ || state==E_SUM_REQ)
                histogram_q<=histogram[table_index];
            if (state==E_SYMBOL_REQ)
                symbol_q<=symbols[symbol_index[SYMBOL_BITS-1:0]];
            if (state==E_RES_REQ)
                residual_q<=residuals[residual_index[RESIDUAL_BITS-1:0]];
            if (state==D_RES && source_accept)
                residuals[residual_index[RESIDUAL_BITS-1:0]]<=s_data;
            if (decode_request && selected_codec==2)
                residual_q<=residuals[emitted_symbols[RESIDUAL_BITS-1:0]];
        end
    end

    task reject;
        input [3:0] code;
        begin
            error_code<=code; output_valid<=0; state<=STATUS;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; decoding<=0; selected_codec<=0; error_code<=0;
            source_length<=0; original_length<=0; symbol_count<=0; bit_count<=0;
            input_index<=0; output_count<=0; symbol_index<=0; residual_index<=0;
            target_output<=0; emitted_symbols<=0; consumed_bits<=0;
            table_index<=0; low_byte<=0; high_nibble<=0; held_upper<=0;
            held_nibble<=0; header_index<=0; decode_depth<=0; histogram_symbol<=0;
            bit_product<=0; code_bits<=0; decode_code<=0; code_remaining<=0;
            packed_byte<=0; payload_byte<=0; output_data<=0;
            pack_fill<=0; payload_left<=0; output_valid<=0;
        end else begin
            if (source_accept) input_index<=input_index+32'd1;
            if (output_accept) begin
                output_count<=output_count+32'd1; output_valid<=0;
            end
            if (start_accept) begin
                decoding<=decompress; selected_codec<=codec; error_code<=0;
                source_length<=input_bytes;
                original_length<=decompress ? 32'd0 : raw_bytes;
                symbol_count<=0; bit_count<=0; input_index<=0; output_count<=0;
                symbol_index<=0; residual_index<=0; target_output<=0;
                emitted_symbols<=0; consumed_bits<=0; table_index<=0;
                low_byte<=0; high_nibble<=0; held_upper<=0; held_nibble<=0;
                header_index<=0; decode_depth<=0; histogram_symbol<=0;
                bit_product<=0; code_bits<=0; decode_code<=0; code_remaining<=0;
                packed_byte<=0; payload_byte<=0; output_data<=0;
                pack_fill<=0; payload_left<=0; output_valid<=0;
                if (command_bad) reject(8);
                else if (decompress && input_bytes<20) reject(11);
                else if (decompress) state<=D_HEADER;
                else state<=E_INIT;
            end else begin
                case (state)
                    IDLE: begin end
                    E_INIT: begin
                        if (table_index==255) begin
                            table_index<=0;
                            if (source_length==0) state<=E_HIST_REQ;
                            else state<=E_COLLECT;
                        end else table_index<=table_index+8'd1;
                    end
                    E_COLLECT: if (source_accept) begin
                        if (selected_codec==2 && !input_index[0]) low_byte<=s_data;
                        else begin
                            histogram_symbol<=input_symbol;
                            high_nibble<={4'd0,s_data[7:4]};
                            symbol_index<=symbol_index+32'd1;
                            symbol_count<=symbol_count+32'd1;
                            state<=E_HIST_UPDATE;
                        end
                    end
                    E_HIST_UPDATE: begin
                        if (selected_codec==3) state<=E_HIGH_REQ;
                        else if (input_index==source_length) begin
                            table_index<=0; state<=E_HIST_REQ;
                        end else state<=E_COLLECT;
                    end
                    E_HIGH_REQ: begin
                        symbol_index<=symbol_index+32'd1;
                        symbol_count<=symbol_count+32'd1;
                        state<=E_HIGH_UPDATE;
                    end
                    E_HIGH_UPDATE: begin
                        if (input_index==source_length) begin
                            table_index<=0; state<=E_HIST_REQ;
                        end else state<=E_COLLECT;
                    end
                    E_HIST_REQ: state<=E_HIST_SEND;
                    E_HIST_SEND: if (hist_ready) begin
                        if (table_index==last_symbol) begin
                            table_index<=0; state<=BUILD_REQ;
                        end else begin table_index<=table_index+8'd1; state<=E_HIST_REQ; end
                    end
                    BUILD_REQ: if (build_ready) state<=BUILD_WAIT;
                    BUILD_WAIT: if (table_valid) begin
                        if (table_error!=0) reject(11);
                        else if (!decoding) begin
                            table_index<=0; state<=E_SUM_REQ;
                        end else if (codebook_symbols==0 && (symbol_count!=0 || bit_count!=0))
                            reject(11);
                        else if (residual_length!=0) begin
                            residual_index<=0; state<=D_RES;
                        end else state<=D_PREP;
                    end
                    E_SUM_REQ: state<=E_SUM_WAIT;
                    E_SUM_WAIT: if (lookup_result_valid) begin
                        bit_product<={5'd0,histogram_q}*{33'd0,lookup_length};
                        state<=E_SUM_ADD;
                    end
                    E_SUM_ADD: begin
                        if (next_bit_sum>38'h00ffffffff) reject(11);
                        else begin
                            bit_count<=next_bit_sum[31:0];
                            if (table_index==last_symbol) state<=E_SIZE;
                            else begin table_index<=table_index+8'd1; state<=E_SUM_REQ; end
                        end
                    end
                    E_SIZE: begin
                        if (frame_length>FRAME_LIMIT || frame_length[32]) reject(11);
                        else begin
                            target_output<=frame_length[31:0]; header_index<=0;
                            symbol_index<=0; table_index<=0; state<=E_HEADER;
                        end
                    end
                    E_HEADER: begin
                        if (!output_valid) begin
                            output_valid<=1;
                            case (header_index)
                                0: output_data<=8'h42;
                                1: output_data<=8'h4c;
                                2: output_data<=8'h34;
                                3: output_data<=8'h48;
                                4: output_data<=1;
                                5: output_data<={5'd0,selected_codec};
                                6,7: output_data<=0;
                                8,9,10,11: output_data<=original_length[(header_index-8)*8 +: 8];
                                12,13,14,15: output_data<=symbol_count[(header_index-12)*8 +: 8];
                                default: output_data<=bit_count[(header_index-16)*8 +: 8];
                            endcase
                        end else if (output_accept) begin
                            if (header_index==19) state<=E_LENGTH_REQ;
                            else header_index<=header_index+5'd1;
                        end
                    end
                    E_LENGTH_REQ: state<=E_LENGTH_WAIT;
                    E_LENGTH_WAIT: if (lookup_result_valid) begin
                        output_data<={4'd0,lookup_length};
                        output_valid<=1; state<=E_LENGTH_SEND;
                    end
                    E_LENGTH_SEND: if (output_accept) begin
                        if (table_index==last_symbol) begin
                            residual_index<=0;
                            if (residual_length!=0) state<=E_RES_REQ;
                            else if (symbol_count!=0) state<=E_SYMBOL_REQ;
                            else state<=FINISH;
                        end else begin table_index<=table_index+8'd1; state<=E_LENGTH_REQ; end
                    end
                    E_RES_REQ: state<=E_RES_WAIT;
                    E_RES_WAIT: begin
                        output_data<=residual_q; output_valid<=1; state<=E_RES_SEND;
                    end
                    E_RES_SEND: if (output_accept) begin
                        if (residual_index+32'd1==residual_length) begin
                            if (symbol_count!=0) state<=E_SYMBOL_REQ;
                            else state<=FINISH;
                        end else begin residual_index<=residual_index+32'd1; state<=E_RES_REQ; end
                    end
                    E_SYMBOL_REQ: state<=E_SYMBOL_LOOKUP;
                    E_SYMBOL_LOOKUP: state<=E_SYMBOL_WAIT;
                    E_SYMBOL_WAIT: if (lookup_result_valid) begin
                        if (lookup_length==0) reject(11);
                        else begin
                            code_bits<={1'b0,lookup_code}<<(16-lookup_length);
                            code_remaining<={1'b0,lookup_length}; state<=E_BIT;
                        end
                    end
                    E_BIT: begin
                        code_bits<=code_bits<<1; code_remaining<=code_remaining-5'd1;
                        if (pack_fill==7) begin
                            output_data<={packed_byte[7:1],code_bits[15]};
                            output_valid<=1; packed_byte<=0; pack_fill<=0;
                            state<=E_FLUSH;
                        end else begin
                            packed_byte[7-pack_fill]<=code_bits[15];
                            pack_fill<=pack_fill+3'd1;
                            if (code_remaining==1) state<=E_NEXT;
                        end
                    end
                    E_FLUSH: if (output_accept) begin
                        if (code_remaining==0) state<=E_NEXT;
                        else state<=E_BIT;
                    end
                    E_NEXT: begin
                        if (symbol_index+32'd1==symbol_count) begin
                            if (pack_fill!=0) begin
                                output_data<=packed_byte; output_valid<=1; state<=E_TAIL;
                            end else state<=FINISH;
                        end else begin symbol_index<=symbol_index+32'd1; state<=E_SYMBOL_REQ; end
                    end
                    E_TAIL: if (output_accept) state<=FINISH;
                    D_HEADER: if (source_accept) begin
                        if (header_bad) reject(11);
                        else begin
                            if (header_index>=8 && header_index<=11)
                                original_length[(header_index-8)*8 +: 8]<=s_data;
                            if (header_index>=12 && header_index<=15)
                                symbol_count[(header_index-12)*8 +: 8]<=s_data;
                            if (header_index>=16)
                                bit_count[(header_index-16)*8 +: 8]<=s_data;
                            if (header_index==19) state<=D_HEADER_CHECK;
                            else header_index<=header_index+5'd1;
                        end
                    end
                    D_HEADER_CHECK: begin
                        if (header_sizes_bad) reject(11);
                        else begin
                            table_index<=0; state<=D_LENGTH;
                            target_output<=selected_codec==4 ? symbol_count : original_length;
                        end
                    end
                    D_LENGTH: if (source_accept) begin
                        if (s_data>15) reject(11);
                        else if (table_index==last_symbol) state<=BUILD_REQ;
                        else table_index<=table_index+8'd1;
                    end
                    D_RES: if (source_accept) begin
                        if (residual_index+32'd1==residual_length) state<=D_PREP;
                        else residual_index<=residual_index+32'd1;
                    end
                    D_PREP: begin
                        emitted_symbols<=0; consumed_bits<=0;
                        decode_depth<=0; decode_code<=0; payload_left<=0;
                        if (symbol_count==0) begin
                            if (bit_count!=0 || input_index!=source_length) reject(11);
                            else state<=FINISH;
                        end else state<=D_PAYLOAD;
                    end
                    D_PAYLOAD: if (source_accept) begin
                        payload_byte<=s_data; payload_left<=8; state<=D_BIT;
                    end
                    D_BIT: begin
                        if (payload_left==0 || consumed_bits>=bit_count) reject(11);
                        else begin
                            payload_byte<=payload_byte<<1; payload_left<=payload_left-4'd1;
                            consumed_bits<=consumed_bits+32'd1;
                            decode_code<=next_decode_code; decode_depth<=next_depth;
                            if (decode_match) state<=D_SYMBOL_WAIT;
                            else if (next_depth==15 || consumed_bits+32'd1==bit_count)
                                reject(11);
                            else if (payload_left==1) state<=D_PAYLOAD;
                        end
                    end
                    D_SYMBOL_WAIT: if (decode_result_valid) begin
                        emitted_symbols<=emitted_symbols+32'd1;
                        decode_depth<=0; decode_code<=0;
                        if (selected_codec==2) begin
                            output_data<={decoded_symbol[0],residual_q[6:0]};
                            held_upper<={residual_q[7],decoded_symbol[7:1]};
                            output_valid<=1; state<=D_BF_LOW;
                        end else if (selected_codec==3 && !emitted_symbols[0]) begin
                            held_nibble<={4'd0,decoded_symbol[3:0]}; state<=D_NEXT;
                        end else begin
                            output_data<=selected_codec==3 ?
                                {decoded_symbol[3:0],held_nibble[3:0]} : decoded_symbol;
                            output_valid<=1; state<=D_BYTE;
                        end
                    end
                    D_BYTE: if (output_accept) state<=D_NEXT;
                    D_BF_LOW: if (output_accept) begin
                        output_data<=held_upper; output_valid<=1; state<=D_BF_HIGH;
                    end
                    D_BF_HIGH: if (output_accept) state<=D_NEXT;
                    D_NEXT: begin
                        if (emitted_symbols==symbol_count) begin
                            if (consumed_bits!=bit_count || payload_byte!=0 ||
                                input_index!=source_length) reject(11);
                            else state<=FINISH;
                        end else if (consumed_bits==bit_count) reject(11);
                        else if (payload_left==0) state<=D_PAYLOAD;
                        else state<=D_BIT;
                    end
                    FINISH: if (!output_valid) begin
                        if (output_count!=target_output || input_index!=source_length)
                            reject(11);
                        else state<=STATUS;
                    end
                    STATUS: if (status_ready) state<=IDLE;
                    default: reject(11);
                endcase
            end
            if (source_accept && (s_last!=(input_index+32'd1==source_length)))
                reject(11);
        end
    end
endmodule
