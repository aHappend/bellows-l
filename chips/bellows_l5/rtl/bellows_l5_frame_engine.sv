module bellows_l5_frame_engine #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer DICT_BYTES=16384
) (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire decompress, input wire use_dictionary,
    input wire [14:0] dictionary_bytes, input wire [1:0] checksum_mode,
    input wire [31:0] input_bytes, input wire [31:0] output_capacity,
    input wire s_valid, output wire s_ready, input wire [7:0] s_data,
    output wire m_valid, input wire m_ready, output wire [7:0] m_data,
    output wire done_valid, input wire done_ready,
    output wire [3:0] done_error, output wire [31:0] done_checksum,
    output wire dict_rd_en, output wire [13:0] dict_rd_addr,
    input wire dict_rd_valid, input wire [7:0] dict_rd_data,
    output wire dict_index_en, output wire [9:0] dict_index_addr,
    input wire dict_index_valid, input wire dict_index_found,
    input wire [13:0] dict_index_position,
    output wire table_start_valid, input wire table_start_ready,
    output wire [1:0] table_alphabet, output wire [1:0] table_mode,
    output wire [3:0] table_requested_log, output wire [5:0] table_rle_symbol,
    output wire count_valid, input wire count_ready,
    output wire signed [10:0] count_value, output wire count_last,
    input wire table_done_valid, output wire table_done_ready,
    input wire [3:0] table_done_error,
    input wire [2:0] tables_valid, input wire [11:0] tables_log,
    output wire [2:0] init_valid, input wire [2:0] init_ready,
    output wire [26:0] init_state,
    output wire [2:0] step_valid, input wire [2:0] step_ready,
    output wire [26:0] bits, output wire [11:0] available,
    input wire [2:0] m_valid_fse, output wire [2:0] m_ready_fse,
    input wire [17:0] m_symbol, input wire [26:0] m_state,
    input wire [11:0] m_nbits, input wire [26:0] states,
    input wire [17:0] peek_symbol, input wire [11:0] peek_nbits,
    output wire enc_valid, input wire enc_ready,
    output wire [1:0] enc_alphabet, output wire [5:0] enc_symbol,
    output wire [8:0] enc_next_state, output wire enc_terminal,
    input wire enc_result_valid, output wire enc_result_ready,
    input wire [3:0] enc_error, input wire [8:0] enc_state,
    input wire [8:0] enc_bits, input wire [3:0] enc_nbits,
    input wire entropy_error_valid, input wire [3:0] entropy_error
);
    localparam integer LEGAL=MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536 &&
        DICT_BYTES>=1 && DICT_BYTES<=16384;
    localparam integer BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer DICTIONARY=LEGAL ? DICT_BYTES : 1;
    localparam integer FRAME=2*BLOCK+1024;
    localparam integer SEQUENCES=BLOCK>=4 ? (BLOCK>>2) : 1;
    localparam [7:0] IDLE=0, LOAD=1, DISPATCH=2, FETCH=3, FETCH_WAIT=4,
        HEADER=5, HEADER_BYTE=6, HEADER_CHECK=7, RAW_COPY=8, RAW_BYTE=9,
        RLE_BYTE=10, RLE_FILL=11, LIT_HEADER=12, LIT_FIRST=13,
        LIT_MORE=14, LIT_NEXT=15, LIT_CHECK=16, LIT_LOAD=17, LIT_BYTE=18,
        LIT_RLE=19, LIT_FILL=20, SEQ_HEADER=21, SEQ_FIRST=22, SEQ_MORE=23,
        SEQ_NEXT=24, SEQ_CHECK=25, MODE_BYTE=26, MODE_CHECK=27,
        TABLE_SELECT=28, TABLE_RLE=29, TABLE_START=30, TABLE_WAIT=31,
        COUNT_START=32, COUNT_STREAM=33, COUNT_BYTE=34,
        REVERSE_START=35, INIT_REQUEST=36, INIT_BITS=37, INIT_APPLY=38,
        BIT_REQUEST=39, BIT_WAIT=40, SYMBOLS=41, EXTRA_OF=42, EXTRA_ML=43,
        EXTRA_LL=44, SEQ_VALIDATE=45, OFFSET_VALIDATE=46,
        COPY_LITERALS=47, COPY_LITERAL_WAIT=48, COPY_MATCH=49,
        COPY_MATCH_WAIT=50, SEQ_FINISH=51, TRANS_REQUEST=52,
        TRANS_BITS=53, TRANS_APPLY=54, TRANS_RESULT=55, TAIL=56,
        CHECKSUM_START=57, CHECKSUM_READ=58, CHECKSUM_WAIT=59,
        CHECKSUM_FEED=60, CHECKSUM_FINISH=61, CHECKSUM_RESULT=62,
        EXPECT_START=63, EXPECT_BYTE=64, EXPECT_CHECK=65,
        MATCH_START=66, MATCH_RUN=67, MATCH_LITERAL=68, MATCH_LITERAL_WAIT=69,
        MATCH_SPLIT=70, ENCODE_BEGIN=71, PREFIX=72, PREFIX_LITERAL=73,
        PREFIX_LITERAL_WAIT=74, PREFIX_SEQUENCE=75, APPEND=76,
        WRITER_START=77, SEQUENCE_READ=78, SEQUENCE_WAIT=79, CODE_LL=80,
        CODE_ML=81, CODE_OF=82, INVERSE_REQUEST=83, INVERSE_RESULT=84,
        INVERSE_BITS=85, WRITE_FIELD=86, WRITE_EXTRA=87, FLUSH_STATES=88,
        WRITER_FINISH=89, WRITER_DONE=90, CHOOSE=91,
        OUTPUT_START=92, OUTPUT_REQUEST=93, OUTPUT_WAIT=94,
        OUTPUT_VALID=95, DONE=96, TRAILING=97, TRAILING_BYTE=98,
        MATCH_ADDRESS=99, MATCH_DISTANCE=100, SKIP_SIZE=101,
        SKIP_BYTE=102, SKIP_CHECK=103;
    reg [7:0] phase, return_phase, bit_return, append_return, field_return;
    reg awake, decoding, dictionary_q, raw_fallback, literals_rle;
    reg [14:0] dict_bytes;
    reg [1:0] private_mode, alphabet, selected_mode, block_type, extra_index;
    reg [3:0] error_code;
    reg [31:0] source_size, standard_size, capacity, loaded, cursor, block_end, fetch_limit;
    reg [31:0] raw_size, raw_count, block_size, literal_size, literal_used;
    reg [31:0] copy_left, match_left, match_offset, repeat1, repeat2, repeat3;
    reg [32:0] match_source, history_position;
    reg [31:0] ll_value, ml_value, of_value;
    reg [31:0] magic, frame_content, header_word, literal_header;
    reg [7:0] descriptor, window_descriptor, byte_q, modes, rle_byte, rle_symbol;
    reg [3:0] header_index, header_left;
    reg [16:0] sequence_count, sequence_index, ll_run, literal_count;
    reg [16:0] split_left, split_offset, token_position;
    reg [5:0] ll_code, ml_code, of_code, code_cursor;
    reg [31:0] of_work;
    reg [26:0] encoder_states;
    reg [5:0] request_bits, field_nbits;
    reg [31:0] bit_value, field_bits;
    reg [31:0] compressed_size, prefix_index, output_index, output_size, checksum_index;
    reg [31:0] content_checksum, private_checksum, expected_content, expected_private;
    reg [7:0] output_byte, checksum_byte;
    reg hash_seen, private_seen;
    wire active=rst_n && !clear;
    wire reset_units=rst_n && !clear;
    wire load_byte=active && phase==LOAD && s_valid && s_ready;

    function [31:0] length_base;
        input match_length;
        input [5:0] code;
        begin
            length_base=0;
            if (!match_length) begin
                if (code<16) length_base={26'd0,code};
                else case (code)
                    16: length_base=16; 17: length_base=18;
                    18: length_base=20; 19: length_base=22;
                    20: length_base=24; 21: length_base=28;
                    22: length_base=32; 23: length_base=40;
                    24: length_base=48;
                    default: if (code<=35) length_base=32'd1<<(code-6'd19);
                endcase
            end else begin
                if (code<32) length_base={26'd0,code}+32'd3;
                else case (code)
                    32: length_base=35; 33: length_base=37;
                    34: length_base=39; 35: length_base=41;
                    36: length_base=43; 37: length_base=47;
                    38: length_base=51; 39: length_base=59;
                    40: length_base=67; 41: length_base=83; 42: length_base=99;
                    default: if (code<=52) length_base=(32'd1<<(code-6'd36))+32'd3;
                endcase
            end
        end
    endfunction
    function [5:0] length_bits;
        input match_length;
        input [5:0] code;
        begin
            length_bits=0;
            if (!match_length) begin
                if (code>=16 && code<=19) length_bits=1;
                else if (code==20 || code==21) length_bits=2;
                else if (code==22 || code==23) length_bits=3;
                else if (code==24) length_bits=4;
                else if (code>=25 && code<=35) length_bits=code-6'd19;
            end else begin
                if (code>=32 && code<=35) length_bits=1;
                else if (code==36 || code==37) length_bits=2;
                else if (code==38 || code==39) length_bits=3;
                else if (code==40 || code==41) length_bits=4;
                else if (code==42) length_bits=5;
                else if (code>=43 && code<=52) length_bits=code-6'd36;
            end
        end
    endfunction
    wire [31:0] ll_base=length_base(1'b0,ll_code);
    wire [31:0] ml_base=length_base(1'b1,ml_code);
    wire [5:0] ll_bits=length_bits(1'b0,ll_code);
    wire [5:0] ml_bits=length_bits(1'b1,ml_code);
    wire [31:0] scan_ll_base=length_base(1'b0,code_cursor);
    wire [31:0] scan_ml_base=length_base(1'b1,code_cursor);
    wire [5:0] scan_ll_bits=length_bits(1'b0,code_cursor);
    wire [5:0] scan_ml_bits=length_bits(1'b1,code_cursor);
    wire [32:0] end_sequence={1'b0,raw_count}+{1'b0,ll_value}+{1'b0,ml_value};
    wire [32:0] available_history={18'd0,dict_bytes}+{1'b0,raw_count}+{1'b0,ll_value};
    reg [31:0] resolved_offset;
    reg [2:0] repeat_selection;
    always @* begin
        repeat_selection=of_value[2:0]+(ll_value==0 ? 3'd1 : 3'd0);
        resolved_offset=0;
        if (of_value>3) resolved_offset=of_value-32'd3;
        else case (repeat_selection)
            1: resolved_offset=repeat1;
            2: resolved_offset=repeat2;
            3: resolved_offset=repeat3;
            4: resolved_offset=repeat1-32'd1;
            default: resolved_offset=0;
        endcase
    end

    wire source_a_valid, source_b_valid, raw_a_valid, raw_b_valid;
    wire source_port_valid;
    wire literal_a_valid, compressed_a_valid;
    wire [7:0] source_a_data, source_b_data, raw_a_data, raw_b_data;
    wire [7:0] source_port_data;
    reg source_reverse_q;
    wire [7:0] literal_a_data, compressed_a_data;
    wire reverse_rd_en;
    wire [31:0] reverse_rd_addr;
    wire matcher_a_en, matcher_b_en, matcher_dict_en;
    wire [15:0] matcher_a_addr, matcher_b_addr;
    wire [13:0] matcher_dict_addr;
    wire [32:0] match_virtual=match_source;
    wire match_from_dictionary=match_virtual<{18'd0,dict_bytes};
    wire [32:0] match_local=match_virtual-{18'd0,dict_bytes};
    reg raw_we, literal_we, raw_read;
    reg [31:0] raw_waddr, raw_raddr, literal_waddr, literal_raddr;
    reg [7:0] raw_wdata, literal_wdata;
    wire literal_read=active && ((phase==COPY_LITERALS && copy_left!=0) ||
        (phase==PREFIX_LITERAL && prefix_index<{15'd0,literal_count}));
    wire compressed_read=active && phase==OUTPUT_REQUEST && !decoding && !raw_fallback &&
        output_index>=13 && output_index<13+compressed_size;
    wire [31:0] output_body_index=decoding ? output_index : output_index-32'd13;
    wire raw_output_read=phase==OUTPUT_REQUEST &&
        (decoding || (raw_fallback && output_index>=13 && output_index<13+raw_size));
    always @* begin
        raw_we=0; raw_waddr=raw_count; raw_wdata=byte_q;
        literal_we=0; literal_waddr=literal_count; literal_wdata=byte_q;
        raw_read=0; raw_raddr=0;
        literal_raddr=phase==PREFIX_LITERAL ? prefix_index : literal_used;
        if (active) begin
            if (load_byte && !decoding) begin
                raw_we=1; raw_waddr=loaded; raw_wdata=s_data;
            end
            if (phase==RAW_BYTE || (phase==RLE_FILL && raw_count<raw_size)) begin
                raw_we=1; raw_wdata=phase==RLE_FILL ? rle_byte : byte_q;
            end
            if (phase==COPY_LITERAL_WAIT && literal_a_valid) begin
                raw_we=1; raw_wdata=literal_a_data;
            end
            if (phase==COPY_MATCH_WAIT &&
                (match_from_dictionary ? dict_rd_valid : raw_a_valid)) begin
                raw_we=1; raw_wdata=match_from_dictionary ? dict_rd_data : raw_a_data;
            end
            if (phase==LIT_BYTE || (phase==LIT_FILL && literal_used<literal_size)) begin
                literal_we=1; literal_waddr=literal_used;
                literal_wdata=phase==LIT_FILL ? rle_byte : byte_q;
            end
            if (phase==MATCH_LITERAL_WAIT && raw_a_valid) begin
                literal_we=1; literal_wdata=raw_a_data;
            end
            if (matcher_a_en) begin raw_read=1; raw_raddr={16'd0,matcher_a_addr}; end
            else if (phase==MATCH_LITERAL) begin raw_read=1; raw_raddr={15'd0,token_position}; end
            else if (phase==CHECKSUM_READ && checksum_index<raw_size) begin
                raw_read=1; raw_raddr=checksum_index;
            end
            else if (phase==COPY_MATCH && match_left!=0 && !match_from_dictionary) begin
                raw_read=1; raw_raddr=match_local[31:0];
            end else if (raw_output_read) begin raw_read=1; raw_raddr=output_body_index; end
        end
    end
    bellows_l5_buffer #(.BYTES(FRAME+4)) input_image (
        .clk(clk), .rst_n(reset_units), .we(load_byte && decoding), .waddr(loaded), .wdata(s_data),
        .a_en(active && ((phase==FETCH && cursor<fetch_limit) || reverse_rd_en)),
        .a_addr(reverse_rd_en ? reverse_rd_addr : cursor),
        .a_valid(source_port_valid), .a_data(source_port_data),
        .b_en(1'b0), .b_addr(32'd0), .b_valid(), .b_data()
    );
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) source_reverse_q<=0;
        else if (clear) source_reverse_q<=0;
        else source_reverse_q<=reverse_rd_en;
    end
    assign source_a_valid=source_port_valid && !source_reverse_q;
    assign source_b_valid=source_port_valid && source_reverse_q;
    assign source_a_data=source_a_valid ? source_port_data : 8'd0;
    assign source_b_data=source_b_valid ? source_port_data : 8'd0;
    bellows_l5_buffer #(.BYTES(BLOCK)) raw_image (
        .clk(clk), .rst_n(reset_units), .we(raw_we), .waddr(raw_waddr), .wdata(raw_wdata),
        .a_en(raw_read), .a_addr(raw_raddr), .a_valid(raw_a_valid), .a_data(raw_a_data),
        .b_en(matcher_b_en), .b_addr({16'd0,matcher_b_addr}),
        .b_valid(raw_b_valid), .b_data(raw_b_data)
    );
    bellows_l5_buffer #(.BYTES(BLOCK)) literal_image (
        .clk(clk), .rst_n(reset_units), .we(literal_we),
        .waddr(literal_waddr), .wdata(literal_wdata),
        .a_en(literal_read), .a_addr(literal_raddr),
        .a_valid(literal_a_valid), .a_data(literal_a_data),
        .b_en(1'b0), .b_addr(32'd0), .b_valid(), .b_data()
    );
    wire writer_valid, writer_ready, writer_last, writer_done;
    wire [7:0] writer_data;
    wire [3:0] writer_error;
    wire compressed_write=active && (phase==APPEND || (writer_valid && writer_ready));
    bellows_l5_buffer #(.BYTES(FRAME)) compressed_image (
        .clk(clk), .rst_n(reset_units), .we(compressed_write), .waddr(compressed_size),
        .wdata(phase==APPEND ? byte_q : writer_data),
        .a_en(compressed_read), .a_addr(output_body_index),
        .a_valid(compressed_a_valid), .a_data(compressed_a_data),
        .b_en(1'b0), .b_addr(32'd0), .b_valid(), .b_data()
    );
    wire sequence_valid;
    wire [23:0] sequence_ll, sequence_ml, sequence_of;
    wire [16:0] split_length=split_left<=1024 ? split_left :
        split_left<1028 ? split_left-17'd4 : 17'd1024;
    bellows_l5_sequences #(.DEPTH(SEQUENCES)) sequences (
        .clk(clk), .rst_n(reset_units), .we(active && phase==MATCH_SPLIT),
        .waddr(sequence_count), .wll({7'd0,ll_run}), .wml({7'd0,split_length}),
        .wof({7'd0,split_offset}+24'd3),
        .re(active && phase==SEQUENCE_READ), .raddr(sequence_index),
        .valid(sequence_valid), .ll(sequence_ll), .ml(sequence_ml), .of_value(sequence_of)
    );

    wire matcher_ready, matcher_valid, matcher_match, matcher_done;
    wire [16:0] matcher_position, matcher_length, matcher_offset;
    wire [3:0] matcher_error;
    wire matcher_start=active && phase==MATCH_START;
    bellows_l5_matcher #(.MAX_BLOCK_BYTES(BLOCK), .DICT_BYTES(DICTIONARY)) matcher (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .start_valid(matcher_start), .start_ready(matcher_ready),
        .block_bytes(raw_size[16:0]), .use_dictionary(dictionary_q),
        .dictionary_bytes(dict_bytes),
        .seed_en(dict_index_en), .seed_addr(dict_index_addr),
        .seed_valid(dict_index_valid), .seed_found(dict_index_found),
        .seed_position(dict_index_position),
        .a_en(matcher_a_en), .a_addr(matcher_a_addr),
        .a_valid(raw_a_valid), .a_data(raw_a_data),
        .b_en(matcher_b_en), .b_addr(matcher_b_addr),
        .b_valid(raw_b_valid), .b_data(raw_b_data),
        .dict_en(matcher_dict_en), .dict_addr(matcher_dict_addr),
        .dict_valid(dict_rd_valid), .dict_data(dict_rd_data),
        .m_valid(matcher_valid), .m_ready(active && phase==MATCH_RUN),
        .m_position(matcher_position), .m_length(matcher_length),
        .m_offset(matcher_offset), .m_match(matcher_match),
        .done_valid(matcher_done), .done_ready(active && phase==MATCH_RUN),
        .done_error(matcher_error)
    );
    assign dict_rd_en=active && (matcher_dict_en ||
        (phase==COPY_MATCH && match_left!=0 && match_from_dictionary));
    assign dict_rd_addr=!dict_rd_en ? 14'd0 : matcher_dict_en ?
        matcher_dict_addr : match_virtual[13:0];

    wire counts_start_ready, counts_s_ready, counts_log_valid, counts_done;
    wire [3:0] counts_log, counts_error;
    wire [7:0] counts_bytes;
    bellows_l5_fse_counts normalized_counts (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .start_valid(active && phase==COUNT_START), .start_ready(counts_start_ready),
        .alphabet(alphabet), .s_valid(active && phase==COUNT_BYTE),
        .s_ready(counts_s_ready), .s_data(byte_q), .s_last(cursor==block_end),
        .log_valid(counts_log_valid), .log_ready(table_start_ready),
        .table_log(counts_log), .count_valid(count_valid), .count_ready(count_ready),
        .count_symbol(), .count_value(count_value), .count_last(count_last),
        .done_valid(counts_done), .done_ready(active && phase==COUNT_STREAM),
        .done_error(counts_error), .bytes_used(counts_bytes)
    );
    assign table_start_valid=active &&
        (phase==TABLE_START || (selected_mode==2 && counts_log_valid));
    assign table_alphabet=alphabet;
    assign table_mode=selected_mode;
    assign table_requested_log=selected_mode==2 ? counts_log : 4'd0;
    assign table_rle_symbol=rle_symbol[5:0];
    assign table_done_ready=active && phase==TABLE_WAIT;

    wire reverse_start_ready, reverse_take_ready, reverse_bits_valid, reverse_exhausted;
    wire reverse_error_valid;
    wire [3:0] reverse_error;
    wire [31:0] reverse_bits;
    bellows_l5_reverse_reader #(.MAX_BYTES(FRAME)) reverse_reader (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .start_valid(active && phase==REVERSE_START), .start_ready(reverse_start_ready),
        .start_base(cursor), .start_bytes(block_end-cursor),
        .rd_en(reverse_rd_en), .rd_addr(reverse_rd_addr),
        .rd_valid(source_b_valid), .rd_data(source_b_data),
        .take_valid(active && phase==BIT_REQUEST), .take_ready(reverse_take_ready),
        .take_nbits(request_bits), .bits_valid(reverse_bits_valid),
        .bits_ready(active && phase==BIT_WAIT), .bits_data(reverse_bits), .bits_nbits(),
        .exhausted(reverse_exhausted), .error_valid(reverse_error_valid), .error_code(reverse_error)
    );
    assign init_valid=active && phase==INIT_APPLY ? (3'b001<<alphabet) : 3'd0;
    assign init_state={3{bit_value[8:0]}};
    assign step_valid=active && phase==TRANS_APPLY ? (3'b001<<alphabet) : 3'd0;
    assign bits={3{bit_value[8:0]}};
    assign available={3{request_bits[3:0]}};
    assign m_ready_fse=active && phase==TRANS_RESULT ? (3'b001<<alphabet) : 3'd0;
    assign enc_valid=active && phase==INVERSE_REQUEST;
    assign enc_alphabet=alphabet;
    assign enc_symbol=alphabet==0 ? ll_code : alphabet==1 ? of_code : ml_code;
    assign enc_next_state=encoder_states[alphabet*9 +: 9];
    assign enc_terminal=sequence_index+17'd1==sequence_count;
    assign enc_result_ready=active && phase==INVERSE_RESULT;
    wire writer_start_ready, writer_s_ready, writer_finish_ready;
    bellows_l5_bit_writer bitstream_encoder (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .start_valid(active && phase==WRITER_START), .start_ready(writer_start_ready),
        .s_valid(active && phase==WRITE_FIELD), .s_ready(writer_s_ready),
        .s_bits(field_bits), .s_nbits(field_nbits),
        .finish_valid(active && phase==WRITER_FINISH), .finish_ready(writer_finish_ready),
        .m_valid(writer_valid), .m_ready(writer_ready),
        .m_data(writer_data), .m_last(writer_last),
        .done_valid(writer_done), .done_ready(active && phase==WRITER_DONE),
        .done_error(writer_error)
    );
    assign writer_ready=active && compressed_size<FRAME && phase!=APPEND;

    wire hash_start_ready, hash_s_ready, hash_finish_ready, hash_result_valid;
    wire [63:0] hash_result;
    wire private_s_ready, private_finish_ready, private_result_valid;
    wire [31:0] private_result;
    wire checksum_feed=active && phase==CHECKSUM_FEED && hash_s_ready && private_s_ready;
    wire checksum_finish=active && phase==CHECKSUM_FINISH && hash_finish_ready &&
        private_finish_ready;
    bellows_l5_xxh64 content_hash (
        .clk(clk), .rst_n(reset_units),
        .start_valid(active && phase==CHECKSUM_START), .start_ready(hash_start_ready),
        .s_valid(checksum_feed), .s_ready(hash_s_ready), .s_data(checksum_byte),
        .finish_valid(checksum_finish), .finish_ready(hash_finish_ready),
        .result_valid(hash_result_valid), .result_ready(active && phase==CHECKSUM_RESULT),
        .result(hash_result)
    );
    bellows_l3_checksum private_hash (
        .clk(clk), .rst_n(reset_units), .start(active && phase==CHECKSUM_START),
        .mode(private_mode), .s_data(checksum_byte), .s_valid(checksum_feed),
        .s_ready(private_s_ready), .finish_valid(checksum_finish),
        .finish_ready(private_finish_ready), .result_valid(private_result_valid),
        .result(private_result)
    );
    assign start_ready=active && awake && LEGAL && phase==IDLE;
    assign s_ready=active && phase==LOAD && loaded<source_size;
    assign m_valid=active && phase==OUTPUT_VALID;
    assign m_data=m_valid ? output_byte : 8'd0;
    assign done_valid=active && phase==DONE;
    assign done_error=done_valid ? error_code : 4'd0;
    assign done_checksum=active ? private_checksum : 32'd0;
    wire [31:0] parsed_block_size={11'd0,header_word[23:3]};
    wire [31:0] parsed_body_size=header_word[2:1]==1 ? 32'd1 : parsed_block_size;
    wire [32:0] parsed_frame_size=33'd17+{1'b0,parsed_body_size};
    wire candidate_smaller=sequence_count!=0 && compressed_size<raw_size;
    wire [31:0] encoded_body_size=raw_fallback ? raw_size : compressed_size;
    wire [31:0] encoded_block_header=(encoded_body_size<<3) |
        (raw_fallback ? 32'd1 : 32'd5);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; return_phase<=IDLE; bit_return<=IDLE;
            append_return<=IDLE; field_return<=IDLE; awake<=0;
            decoding<=0; dictionary_q<=0; raw_fallback<=0; literals_rle<=0;
            dict_bytes<=0; private_mode<=0; alphabet<=0; selected_mode<=0;
            block_type<=0; extra_index<=0; error_code<=0;
            source_size<=0; standard_size<=0; capacity<=0; loaded<=0;
            cursor<=0; block_end<=0; fetch_limit<=0; raw_size<=0; raw_count<=0;
            block_size<=0; literal_size<=0; literal_used<=0;
            copy_left<=0; match_left<=0; match_offset<=0;
            match_source<=0; history_position<=0;
            repeat1<=1; repeat2<=4; repeat3<=8;
            ll_value<=0; ml_value<=0; of_value<=0;
            magic<=0; frame_content<=0; header_word<=0; literal_header<=0;
            descriptor<=0; window_descriptor<=0; byte_q<=0; modes<=0;
            rle_byte<=0; rle_symbol<=0; header_index<=0; header_left<=0;
            sequence_count<=0; sequence_index<=0; ll_run<=0; literal_count<=0;
            split_left<=0; split_offset<=0; token_position<=0;
            ll_code<=0; ml_code<=0; of_code<=0; code_cursor<=0; of_work<=0;
            encoder_states<=0; request_bits<=0; field_nbits<=0;
            bit_value<=0; field_bits<=0; compressed_size<=0; prefix_index<=0;
            output_index<=0; output_size<=0; checksum_index<=0;
            content_checksum<=0; private_checksum<=0;
            expected_content<=0; expected_private<=0;
            output_byte<=0; checksum_byte<=0; hash_seen<=0; private_seen<=0;
        end else begin
            awake<=1;
            if (clear) begin
                phase<=IDLE; error_code<=0; loaded<=0; compressed_size<=0;
                content_checksum<=0; private_checksum<=0;
            end else begin
                if (compressed_write) compressed_size<=compressed_size+32'd1;
                case (phase)
                    IDLE: if (start_valid && start_ready) begin
                        decoding<=decompress; dictionary_q<=use_dictionary;
                        dict_bytes<=use_dictionary ? dictionary_bytes : 15'd0;
                        private_mode<=checksum_mode; source_size<=input_bytes;
                        if (decompress && checksum_mode!=0) begin
                            if (input_bytes>=4) standard_size<=input_bytes-32'd4;
                            else standard_size<=0;
                        end else standard_size<=input_bytes;
                        capacity<=output_capacity; loaded<=0; cursor<=0;
                        block_end<=0; fetch_limit<=0; raw_size<=0; raw_count<=0;
                        block_size<=0; literal_size<=0; literal_used<=0;
                        copy_left<=0; match_left<=0; match_offset<=0;
                        match_source<=0; history_position<=0;
                        repeat1<=1; repeat2<=4; repeat3<=8;
                        ll_value<=0; ml_value<=0; of_value<=0;
                        magic<=0; frame_content<=0; header_word<=0; literal_header<=0;
                        descriptor<=0; window_descriptor<=0; byte_q<=0; modes<=0;
                        rle_byte<=0; rle_symbol<=0; header_index<=0; header_left<=0;
                        sequence_count<=0; sequence_index<=0; ll_run<=0; literal_count<=0;
                        split_left<=0; split_offset<=0; token_position<=0;
                        ll_code<=0; ml_code<=0; of_code<=0; code_cursor<=0; of_work<=0;
                        encoder_states<=0; request_bits<=0; field_nbits<=0;
                        bit_value<=0; field_bits<=0; compressed_size<=0; prefix_index<=0;
                        output_index<=0; output_size<=0; checksum_index<=0;
                        content_checksum<=0; private_checksum<=0;
                        expected_content<=0; expected_private<=0;
                        output_byte<=0; checksum_byte<=0; hash_seen<=0; private_seen<=0;
                        alphabet<=0; selected_mode<=0; block_type<=0; extra_index<=0;
                        raw_fallback<=0; literals_rle<=0; error_code<=0;
                        if (checksum_mode==3 ||
                            input_bytes>FRAME+(checksum_mode==0 ? 0 : 4) ||
                            (!decompress && input_bytes>BLOCK) ||
                            (use_dictionary && (dictionary_bytes==0 || dictionary_bytes>DICTIONARY))) begin
                            error_code<=8; phase<=DONE;
                        end else phase<=LOAD;
                    end
                    LOAD: begin
                        if (load_byte) loaded<=loaded+32'd1;
                        if (loaded==source_size) phase<=DISPATCH;
                    end
                    DISPATCH: begin
                        if (decoding) begin
                            cursor<=0; fetch_limit<=standard_size; header_index<=0;
                            if (standard_size<4) begin error_code<=11; phase<=DONE; end
                            else phase<=HEADER;
                        end else begin raw_size<=source_size; phase<=CHECKSUM_START; end
                    end
                    FETCH: begin
                        if (cursor>=fetch_limit) begin error_code<=11; phase<=DONE; end
                        else phase<=FETCH_WAIT;
                    end
                    FETCH_WAIT: if (source_a_valid) begin
                        byte_q<=source_a_data; cursor<=cursor+32'd1; phase<=return_phase;
                    end
                    HEADER: begin return_phase<=HEADER_BYTE; phase<=FETCH; end
                    HEADER_BYTE: begin
                        if (header_index<4) magic[header_index*8 +: 8]<=byte_q;
                        else if (header_index==4) descriptor<=byte_q;
                        else if (header_index==5) window_descriptor<=byte_q;
                        else if (header_index<10) frame_content[(header_index-6)*8 +: 8]<=byte_q;
                        else header_word[(header_index-10)*8 +: 8]<=byte_q;
                        if (header_index==3 &&
                            ({byte_q,magic[23:0]} & 32'hfffffff0)==32'h184d2a50) begin
                            header_index<=0; header_word<=0; phase<=SKIP_SIZE;
                        end else if (header_index==3 && {byte_q,magic[23:0]}!=32'hfd2fb528) begin
                            error_code<=11; phase<=DONE;
                        end else if (header_index==4 && byte_q[4:3]!=0) begin
                            error_code<=11; phase<=DONE;
                        end else if (header_index==4 && byte_q!=8'h84) begin
                            error_code<=12; phase<=DONE;
                        end else if (header_index==4 && standard_size<17) begin
                            error_code<=11; phase<=DONE;
                        end else if (header_index==5 && byte_q!=8'h38) begin
                            error_code<=12; phase<=DONE;
                        end else if (header_index==12) phase<=HEADER_CHECK;
                        else begin header_index<=header_index+4'd1; phase<=HEADER; end
                    end
                    SKIP_SIZE: begin return_phase<=SKIP_BYTE; phase<=FETCH; end
                    SKIP_BYTE: begin
                        header_word[header_index*8 +: 8]<=byte_q;
                        if (header_index==3) phase<=SKIP_CHECK;
                        else begin header_index<=header_index+4'd1; phase<=SKIP_SIZE; end
                    end
                    SKIP_CHECK: begin
                        if (33'd8+{1'b0,header_word}>{1'b0,standard_size}) error_code<=11;
                        else error_code<=12;
                        phase<=DONE;
                    end
                    HEADER_CHECK: begin
                        block_type<=header_word[2:1]; block_size<=parsed_block_size;
                        raw_size<=frame_content; block_end<=32'd13+parsed_body_size;
                        if ((magic & 32'hfffffff0)==32'h184d2a50) begin
                            error_code<=12; phase<=DONE;
                        end else if (magic!=32'hfd2fb528 || descriptor[4:3]!=0 ||
                            header_word[2:1]==3 || parsed_block_size>131072) begin
                            error_code<=11; phase<=DONE;
                        end else if (descriptor!=8'h84 || window_descriptor!=8'h38 ||
                            !header_word[0]) begin error_code<=12; phase<=DONE; end
                        else if (frame_content>BLOCK) begin error_code<=5; phase<=DONE; end
                        else if (frame_content>capacity) begin error_code<=9; phase<=DONE; end
                        else if (parsed_frame_size!={1'b0,standard_size}) begin
                            if ({1'b0,standard_size}>parsed_frame_size+33'd3) begin
                                cursor<=parsed_frame_size[31:0]; header_index<=0; magic<=0;
                                phase<=TRAILING;
                            end else begin error_code<=11; phase<=DONE; end
                        end else begin
                            fetch_limit<=32'd13+parsed_body_size;
                            if (header_word[2:1]==0) begin
                                if (parsed_block_size!=frame_content) begin error_code<=11; phase<=DONE; end
                                else phase<=RAW_COPY;
                            end else if (header_word[2:1]==1) begin
                                if (parsed_block_size!=frame_content) begin error_code<=11; phase<=DONE; end
                                else begin return_phase<=RLE_BYTE; phase<=FETCH; end
                            end else phase<=LIT_HEADER;
                        end
                    end
                    TRAILING: begin return_phase<=TRAILING_BYTE; phase<=FETCH; end
                    TRAILING_BYTE: begin
                        magic[header_index*8 +: 8]<=byte_q;
                        if (header_index==3) begin
                            if ({byte_q,magic[23:0]}==32'hfd2fb528 ||
                                ({byte_q,magic[23:0]} & 32'hfffffff0)==32'h184d2a50)
                                error_code<=12;
                            else error_code<=11;
                            phase<=DONE;
                        end else begin header_index<=header_index+4'd1; phase<=TRAILING; end
                    end
                    RAW_COPY: begin
                        if (raw_count==raw_size) phase<=CHECKSUM_START;
                        else begin return_phase<=RAW_BYTE; phase<=FETCH; end
                    end
                    RAW_BYTE: begin raw_count<=raw_count+32'd1; phase<=RAW_COPY; end
                    RLE_BYTE: begin rle_byte<=byte_q; phase<=RLE_FILL; end
                    RLE_FILL: begin
                        if (raw_count<raw_size) raw_count<=raw_count+32'd1;
                        if (raw_count+32'd1>=raw_size) phase<=CHECKSUM_START;
                    end
                    LIT_HEADER: begin return_phase<=LIT_FIRST; phase<=FETCH; end
                    LIT_FIRST: begin
                        literals_rle<=byte_q[1:0]==1;
                        literal_header<={24'd0,byte_q}; header_index<=1;
                        if (byte_q[1]) begin error_code<=12; phase<=DONE; end
                        else if (!byte_q[2]) begin
                            literal_size<={27'd0,byte_q[7:3]}; phase<=LIT_CHECK;
                        end else begin
                            header_left<=byte_q[3:2]==1 ? 4'd1 : 4'd2;
                            phase<=LIT_MORE;
                        end
                    end
                    LIT_MORE: begin return_phase<=LIT_NEXT; phase<=FETCH; end
                    LIT_NEXT: begin
                        literal_header[header_index*8 +: 8]<=byte_q;
                        header_index<=header_index+4'd1; header_left<=header_left-4'd1;
                        if (header_left==1) begin
                            if (header_index==1)
                                literal_size<={20'd0,byte_q,literal_header[7:4]};
                            else literal_size<={12'd0,byte_q,literal_header[15:4]};
                            phase<=LIT_CHECK;
                        end else phase<=LIT_MORE;
                    end
                    LIT_CHECK: begin
                        literal_used<=0;
                        if (literal_size>raw_size || literal_size>BLOCK ||
                            {1'b0,cursor}+(literals_rle ? 33'd1 : {1'b0,literal_size})>={1'b0,block_end}) begin
                            error_code<=11; phase<=DONE;
                        end else if (literals_rle) begin return_phase<=LIT_RLE; phase<=FETCH; end
                        else phase<=LIT_LOAD;
                    end
                    LIT_LOAD: begin
                        if (literal_used==literal_size) begin literal_used<=0; phase<=SEQ_HEADER; end
                        else begin return_phase<=LIT_BYTE; phase<=FETCH; end
                    end
                    LIT_BYTE: begin literal_used<=literal_used+32'd1; phase<=LIT_LOAD; end
                    LIT_RLE: begin rle_byte<=byte_q; phase<=LIT_FILL; end
                    LIT_FILL: begin
                        if (literal_used<literal_size) literal_used<=literal_used+32'd1;
                        if (literal_used+32'd1>=literal_size) begin
                            literal_used<=0; phase<=SEQ_HEADER;
                        end
                    end
                    SEQ_HEADER: begin return_phase<=SEQ_FIRST; phase<=FETCH; end
                    SEQ_FIRST: begin
                        header_word<={24'd0,byte_q}; header_index<=0;
                        if (byte_q<128) begin sequence_count<={9'd0,byte_q}; phase<=SEQ_CHECK; end
                        else begin header_left<=byte_q==255 ? 4'd2 : 4'd1; phase<=SEQ_MORE; end
                    end
                    SEQ_MORE: begin return_phase<=SEQ_NEXT; phase<=FETCH; end
                    SEQ_NEXT: begin
                        if (header_word[7:0]==255) begin
                            if (header_index==0) begin
                                header_word[15:8]<=byte_q; header_index<=1; phase<=SEQ_MORE;
                            end else begin
                                sequence_count<=17'h07f00+{1'b0,byte_q,header_word[15:8]};
                                phase<=SEQ_CHECK;
                            end
                        end else begin
                            sequence_count<={2'd0,header_word[6:0],byte_q}; phase<=SEQ_CHECK;
                        end
                    end
                    SEQ_CHECK: begin
                        sequence_index<=0;
                        if (sequence_count==0) begin
                            if (cursor!=block_end) begin error_code<=11; phase<=DONE; end
                            else phase<=TAIL;
                        end else if ({15'd0,sequence_count}>raw_size) begin
                            error_code<=11; phase<=DONE;
                        end else begin return_phase<=MODE_BYTE; phase<=FETCH; end
                    end
                    MODE_BYTE: begin modes<=byte_q; phase<=MODE_CHECK; end
                    MODE_CHECK: begin
                        alphabet<=0;
                        if (modes[1:0]!=0 || modes[7:6]==3 || modes[5:4]==3 ||
                            modes[3:2]==3) begin error_code<=11; phase<=DONE; end
                        else phase<=TABLE_SELECT;
                    end
                    TABLE_SELECT: begin
                        case (alphabet)
                            0: selected_mode<=modes[7:6];
                            1: selected_mode<=modes[5:4];
                            default: selected_mode<=modes[3:2];
                        endcase
                        case (alphabet==0 ? modes[7:6] : alphabet==1 ? modes[5:4] : modes[3:2])
                            0: phase<=TABLE_START;
                            1: begin return_phase<=TABLE_RLE; phase<=FETCH; end
                            2: phase<=COUNT_START;
                            default: begin error_code<=11; phase<=DONE; end
                        endcase
                    end
                    TABLE_RLE: begin
                        rle_symbol<=byte_q;
                        if (byte_q>(alphabet==0 ? 35 : alphabet==1 ? 31 : 52)) begin
                            error_code<=11; phase<=DONE;
                        end else phase<=TABLE_START;
                    end
                    TABLE_START: if (table_start_valid && table_start_ready) phase<=TABLE_WAIT;
                    TABLE_WAIT: if (table_done_valid) begin
                        if (table_done_error!=0) begin error_code<=table_done_error; phase<=DONE; end
                        else if (alphabet==2) begin
                            alphabet<=0;
                            if (decoding) phase<=REVERSE_START;
                            else phase<=ENCODE_BEGIN;
                        end else begin
                            alphabet<=alphabet+2'd1;
                            if (decoding) phase<=TABLE_SELECT;
                            else phase<=TABLE_START;
                        end
                    end
                    COUNT_START: if (counts_start_ready) phase<=COUNT_STREAM;
                    COUNT_STREAM: begin
                        if (counts_done) begin
                            if (counts_error!=0) begin error_code<=counts_error; phase<=DONE; end
                            else phase<=TABLE_WAIT;
                        end else if (counts_s_ready) begin return_phase<=COUNT_BYTE; phase<=FETCH; end
                    end
                    COUNT_BYTE: if (counts_s_ready) phase<=COUNT_STREAM;
                    REVERSE_START: begin
                        if (cursor>=block_end) begin error_code<=11; phase<=DONE; end
                        else if (reverse_start_ready) begin alphabet<=0; phase<=INIT_REQUEST; end
                    end
                    INIT_REQUEST: begin
                        request_bits<={2'd0,tables_log[alphabet*4 +: 4]};
                        bit_return<=INIT_BITS; phase<=BIT_REQUEST;
                    end
                    BIT_REQUEST: if (reverse_take_ready) phase<=BIT_WAIT;
                    BIT_WAIT: if (reverse_bits_valid) begin bit_value<=reverse_bits; phase<=bit_return; end
                    INIT_BITS: phase<=INIT_APPLY;
                    INIT_APPLY: if (init_ready[alphabet]) begin
                        if (alphabet==2) phase<=SYMBOLS;
                        else begin alphabet<=alphabet+2'd1; phase<=INIT_REQUEST; end
                    end
                    SYMBOLS: begin
                        ll_code<=peek_symbol[5:0]; of_code<=peek_symbol[11:6];
                        ml_code<=peek_symbol[17:12];
                        if (peek_symbol[5:0]>35 || peek_symbol[11:6]>31 ||
                            peek_symbol[17:12]>52 || tables_valid!=7) begin
                            error_code<=11; phase<=DONE;
                        end else begin
                            request_bits<=peek_symbol[11:6]; bit_return<=EXTRA_OF; phase<=BIT_REQUEST;
                        end
                    end
                    EXTRA_OF: begin
                        of_value<=(32'd1<<of_code)+bit_value;
                        request_bits<=ml_bits; bit_return<=EXTRA_ML; phase<=BIT_REQUEST;
                    end
                    EXTRA_ML: begin
                        ml_value<=ml_base+bit_value;
                        request_bits<=ll_bits; bit_return<=EXTRA_LL; phase<=BIT_REQUEST;
                    end
                    EXTRA_LL: begin ll_value<=ll_base+bit_value; phase<=SEQ_VALIDATE; end
                    SEQ_VALIDATE: begin
                        if ({1'b0,ll_value}>{1'b0,literal_size}-{1'b0,literal_used} ||
                            end_sequence>{1'b0,raw_size} || ml_value<3) begin
                            error_code<=11; phase<=DONE;
                        end else phase<=OFFSET_VALIDATE;
                    end
                    OFFSET_VALIDATE: begin
                        if (of_value==0 || resolved_offset==0 ||
                            {1'b0,resolved_offset}>available_history || resolved_offset>131072) begin
                            error_code<=11; phase<=DONE;
                        end else begin
                            match_offset<=resolved_offset; copy_left<=ll_value; match_left<=ml_value;
                            if (of_value>3 || repeat_selection==4) begin
                                repeat3<=repeat2; repeat2<=repeat1; repeat1<=resolved_offset;
                            end else if (repeat_selection==2) begin
                                repeat2<=repeat1; repeat1<=repeat2;
                            end else if (repeat_selection==3) begin
                                repeat3<=repeat2; repeat2<=repeat1; repeat1<=repeat3;
                            end
                            phase<=COPY_LITERALS;
                        end
                    end
                    COPY_LITERALS: begin
                        if (copy_left==0) begin
                            if (match_left==0) phase<=CHECKSUM_START;
                            else phase<=MATCH_ADDRESS;
                        end else phase<=COPY_LITERAL_WAIT;
                    end
                    MATCH_ADDRESS: begin
                        history_position<={18'd0,dict_bytes}+{1'b0,raw_count};
                        phase<=MATCH_DISTANCE;
                    end
                    MATCH_DISTANCE: begin
                        match_source<=history_position-{1'b0,match_offset}; phase<=COPY_MATCH;
                    end
                    COPY_LITERAL_WAIT: if (literal_a_valid) begin
                        raw_count<=raw_count+32'd1; literal_used<=literal_used+32'd1;
                        copy_left<=copy_left-32'd1; phase<=COPY_LITERALS;
                    end
                    COPY_MATCH: begin
                        if (match_left==0) phase<=SEQ_FINISH;
                        else phase<=COPY_MATCH_WAIT;
                    end
                    COPY_MATCH_WAIT: if (match_from_dictionary ? dict_rd_valid : raw_a_valid) begin
                        raw_count<=raw_count+32'd1; match_left<=match_left-32'd1;
                        match_source<=match_source+33'd1; phase<=COPY_MATCH;
                    end
                    SEQ_FINISH: begin
                        if (sequence_index+17'd1==sequence_count) begin
                            if (!reverse_exhausted) begin error_code<=11; phase<=DONE; end
                            else phase<=TAIL;
                        end else begin alphabet<=0; phase<=TRANS_REQUEST; end
                    end
                    TRANS_REQUEST: begin
                        request_bits<={2'd0,peek_nbits[alphabet*4 +: 4]};
                        bit_return<=TRANS_BITS; phase<=BIT_REQUEST;
                    end
                    TRANS_BITS: phase<=TRANS_APPLY;
                    TRANS_APPLY: if (step_ready[alphabet]) phase<=TRANS_RESULT;
                    TRANS_RESULT: if (m_valid_fse[alphabet]) begin
                        if (alphabet==0) begin alphabet<=2; phase<=TRANS_REQUEST; end
                        else if (alphabet==2) begin alphabet<=1; phase<=TRANS_REQUEST; end
                        else begin sequence_index<=sequence_index+17'd1; phase<=SYMBOLS; end
                    end
                    TAIL: begin
                        if ({1'b0,raw_count}+{1'b0,literal_size}-{1'b0,literal_used}!={1'b0,raw_size}) begin
                            error_code<=11; phase<=DONE;
                        end else begin
                            copy_left<=literal_size-literal_used; match_left<=0; phase<=COPY_LITERALS;
                        end
                    end
                    CHECKSUM_START: if (hash_start_ready) begin
                        checksum_index<=0; hash_seen<=0; private_seen<=0; phase<=CHECKSUM_READ;
                    end
                    CHECKSUM_READ: begin
                        if (checksum_index==raw_size) phase<=CHECKSUM_FINISH;
                        else phase<=CHECKSUM_WAIT;
                    end
                    CHECKSUM_WAIT: if (raw_a_valid) begin checksum_byte<=raw_a_data; phase<=CHECKSUM_FEED; end
                    CHECKSUM_FEED: if (checksum_feed) begin
                        checksum_index<=checksum_index+32'd1; phase<=CHECKSUM_READ;
                    end
                    CHECKSUM_FINISH: if (checksum_finish) phase<=CHECKSUM_RESULT;
                    CHECKSUM_RESULT: begin
                        if (hash_result_valid) begin content_checksum<=hash_result[31:0]; hash_seen<=1; end
                        if (private_result_valid) begin private_checksum<=private_result; private_seen<=1; end
                        if ((hash_seen || hash_result_valid) && (private_seen || private_result_valid)) begin
                            if (decoding) phase<=EXPECT_START;
                            else phase<=MATCH_START;
                        end
                    end
                    EXPECT_START: begin
                        cursor<=block_end; fetch_limit<=source_size; header_index<=0;
                        expected_content<=0; expected_private<=0;
                        return_phase<=EXPECT_BYTE; phase<=FETCH;
                    end
                    EXPECT_BYTE: begin
                        if (header_index<4) expected_content[header_index*8 +: 8]<=byte_q;
                        else expected_private[(header_index-4)*8 +: 8]<=byte_q;
                        if (header_index==(private_mode==0 ? 3 : 7)) phase<=EXPECT_CHECK;
                        else begin
                            header_index<=header_index+4'd1; return_phase<=EXPECT_BYTE; phase<=FETCH;
                        end
                    end
                    EXPECT_CHECK: begin
                        if (content_checksum!=expected_content ||
                            (private_mode!=0 && private_checksum!=expected_private)) begin
                            error_code<=7; phase<=DONE;
                        end else begin output_size<=raw_size; phase<=OUTPUT_START; end
                    end
                    MATCH_START: if (matcher_ready) begin
                        literal_count<=0; sequence_count<=0; ll_run<=0; phase<=MATCH_RUN;
                    end
                    MATCH_RUN: begin
                        if (matcher_valid) begin
                            if (matcher_match) begin
                                split_left<=matcher_length; split_offset<=matcher_offset; phase<=MATCH_SPLIT;
                            end else begin token_position<=matcher_position; phase<=MATCH_LITERAL; end
                        end else if (matcher_done) begin
                            if (matcher_error!=0) begin error_code<=matcher_error; phase<=DONE; end
                            else if (sequence_count==0) phase<=CHOOSE;
                            else begin alphabet<=0; selected_mode<=0; phase<=TABLE_START; end
                        end
                    end
                    MATCH_LITERAL: phase<=MATCH_LITERAL_WAIT;
                    MATCH_LITERAL_WAIT: if (raw_a_valid) begin
                        literal_count<=literal_count+17'd1; ll_run<=ll_run+17'd1; phase<=MATCH_RUN;
                    end
                    MATCH_SPLIT: begin
                        if (sequence_count>=SEQUENCES || split_left<4) begin error_code<=8; phase<=DONE; end
                        else begin
                            sequence_count<=sequence_count+17'd1; ll_run<=0;
                            if (split_left==split_length) phase<=MATCH_RUN;
                            else split_left<=split_left-split_length;
                        end
                    end
                    ENCODE_BEGIN: begin
                        literal_header<=({15'd0,literal_count}<<4) | 32'd12;
                        header_index<=0; prefix_index<=0; compressed_size<=0; phase<=PREFIX;
                    end
                    PREFIX: begin
                        if (header_index==3) phase<=PREFIX_LITERAL;
                        else begin
                            byte_q<=literal_header[header_index*8 +: 8];
                            header_index<=header_index+4'd1; append_return<=PREFIX; phase<=APPEND;
                        end
                    end
                    PREFIX_LITERAL: begin
                        if (prefix_index=={15'd0,literal_count}) begin
                            header_index<=0; phase<=PREFIX_SEQUENCE;
                        end else phase<=PREFIX_LITERAL_WAIT;
                    end
                    PREFIX_LITERAL_WAIT: if (literal_a_valid) begin
                        byte_q<=literal_a_data; prefix_index<=prefix_index+32'd1;
                        append_return<=PREFIX_LITERAL; phase<=APPEND;
                    end
                    PREFIX_SEQUENCE: begin
                        if (sequence_count<128) begin
                            if (header_index==0) begin
                                byte_q<=sequence_count[7:0]; header_index<=1;
                                append_return<=PREFIX_SEQUENCE; phase<=APPEND;
                            end else if (header_index==1) begin
                                byte_q<=0; header_index<=2; append_return<=PREFIX_SEQUENCE; phase<=APPEND;
                            end else phase<=WRITER_START;
                        end else begin
                            if (header_index==0) begin
                                byte_q<=8'd128+sequence_count[15:8]; header_index<=1;
                                append_return<=PREFIX_SEQUENCE; phase<=APPEND;
                            end else if (header_index==1) begin
                                byte_q<=sequence_count[7:0]; header_index<=2;
                                append_return<=PREFIX_SEQUENCE; phase<=APPEND;
                            end else if (header_index==2) begin
                                byte_q<=0; header_index<=3; append_return<=PREFIX_SEQUENCE; phase<=APPEND;
                            end else phase<=WRITER_START;
                        end
                    end
                    APPEND: phase<=append_return;
                    WRITER_START: if (writer_start_ready) begin
                        sequence_index<=sequence_count-17'd1; encoder_states<=0; phase<=SEQUENCE_READ;
                    end
                    SEQUENCE_READ: phase<=SEQUENCE_WAIT;
                    SEQUENCE_WAIT: if (sequence_valid) begin
                        ll_value<={8'd0,sequence_ll}; ml_value<={8'd0,sequence_ml};
                        of_value<={8'd0,sequence_of}; code_cursor<=0; phase<=CODE_LL;
                    end
                    CODE_LL: begin
                        if (ll_value>=scan_ll_base && ll_value<scan_ll_base+(32'd1<<scan_ll_bits)) begin
                            ll_code<=code_cursor; code_cursor<=0; phase<=CODE_ML;
                        end else if (code_cursor==35) begin error_code<=8; phase<=DONE; end
                        else code_cursor<=code_cursor+6'd1;
                    end
                    CODE_ML: begin
                        if (ml_value>=scan_ml_base && ml_value<scan_ml_base+(32'd1<<scan_ml_bits)) begin
                            ml_code<=code_cursor; of_code<=0; of_work<=of_value; phase<=CODE_OF;
                        end else if (code_cursor==52) begin error_code<=8; phase<=DONE; end
                        else code_cursor<=code_cursor+6'd1;
                    end
                    CODE_OF: begin
                        if (of_work>1) begin of_work<=of_work>>1; of_code<=of_code+6'd1; end
                        else begin
                            if (sequence_index+17'd1==sequence_count) alphabet<=0;
                            else alphabet<=1;
                            phase<=INVERSE_REQUEST;
                        end
                    end
                    INVERSE_REQUEST: if (enc_ready) phase<=INVERSE_RESULT;
                    INVERSE_RESULT: if (enc_result_valid) begin
                        if (enc_error!=0) begin error_code<=enc_error; phase<=DONE; end
                        else begin
                            encoder_states[alphabet*9 +: 9]<=enc_state;
                            if (sequence_index+17'd1==sequence_count) begin
                                if (alphabet==2) begin extra_index<=0; phase<=WRITE_EXTRA; end
                                else begin alphabet<=alphabet+2'd1; phase<=INVERSE_REQUEST; end
                            end else begin
                                field_bits<={23'd0,enc_bits}; field_nbits<={2'd0,enc_nbits};
                                field_return<=INVERSE_BITS; phase<=WRITE_FIELD;
                            end
                        end
                    end
                    INVERSE_BITS: begin
                        if (alphabet==1) begin alphabet<=2; phase<=INVERSE_REQUEST; end
                        else if (alphabet==2) begin alphabet<=0; phase<=INVERSE_REQUEST; end
                        else begin extra_index<=0; phase<=WRITE_EXTRA; end
                    end
                    WRITE_FIELD: if (writer_s_ready) phase<=field_return;
                    WRITE_EXTRA: begin
                        if (extra_index==3) begin
                            if (sequence_index==0) begin extra_index<=0; phase<=FLUSH_STATES; end
                            else begin sequence_index<=sequence_index-17'd1; phase<=SEQUENCE_READ; end
                        end else begin
                            case (extra_index)
                                0: begin field_bits<=ll_value-ll_base; field_nbits<=ll_bits; end
                                1: begin field_bits<=ml_value-ml_base; field_nbits<=ml_bits; end
                                default: begin field_bits<=of_value-(32'd1<<of_code); field_nbits<=of_code; end
                            endcase
                            extra_index<=extra_index+2'd1; field_return<=WRITE_EXTRA; phase<=WRITE_FIELD;
                        end
                    end
                    FLUSH_STATES: begin
                        case (extra_index)
                            0: begin
                                field_bits<={23'd0,encoder_states[26:18]};
                                field_nbits<={2'd0,tables_log[11:8]};
                            end
                            1: begin
                                field_bits<={23'd0,encoder_states[17:9]};
                                field_nbits<={2'd0,tables_log[7:4]};
                            end
                            default: begin
                                field_bits<={23'd0,encoder_states[8:0]};
                                field_nbits<={2'd0,tables_log[3:0]};
                            end
                        endcase
                        if (extra_index==3) phase<=WRITER_FINISH;
                        else begin
                            extra_index<=extra_index+2'd1; field_return<=FLUSH_STATES; phase<=WRITE_FIELD;
                        end
                    end
                    WRITER_FINISH: if (writer_finish_ready) phase<=WRITER_DONE;
                    WRITER_DONE: if (writer_done) begin
                        if (writer_error!=0) begin error_code<=writer_error; phase<=DONE; end
                        else phase<=CHOOSE;
                    end
                    CHOOSE: begin
                        raw_fallback<=!candidate_smaller;
                        output_size<=32'd17+(candidate_smaller ? compressed_size : raw_size)+
                            (private_mode==0 ? 32'd0 : 32'd4);
                        phase<=OUTPUT_START;
                    end
                    OUTPUT_START: begin
                        output_index<=0;
                        if (output_size>capacity) begin error_code<=9; phase<=DONE; end
                        else if (output_size==0) phase<=DONE;
                        else phase<=OUTPUT_REQUEST;
                    end
                    OUTPUT_REQUEST: begin
                        if (decoding || (output_index>=13 && output_index<13+encoded_body_size))
                            phase<=OUTPUT_WAIT;
                        else begin
                            case (output_index)
                                0: output_byte<=8'h28; 1: output_byte<=8'hb5;
                                2: output_byte<=8'h2f; 3: output_byte<=8'hfd;
                                4: output_byte<=8'h84; 5: output_byte<=8'h38;
                                6,7,8,9: output_byte<=raw_size[(output_index-6)*8 +: 8];
                                10,11,12: output_byte<=encoded_block_header[(output_index-10)*8 +: 8];
                                default: begin
                                    if (output_index<17+encoded_body_size)
                                        output_byte<=content_checksum[(output_index-13-encoded_body_size)*8 +: 8];
                                    else output_byte<=private_checksum[(output_index-17-encoded_body_size)*8 +: 8];
                                end
                            endcase
                            phase<=OUTPUT_VALID;
                        end
                    end
                    OUTPUT_WAIT: if ((decoding || raw_fallback) ? raw_a_valid : compressed_a_valid) begin
                        output_byte<=decoding || raw_fallback ? raw_a_data : compressed_a_data;
                        phase<=OUTPUT_VALID;
                    end
                    OUTPUT_VALID: if (m_ready) begin
                        if (output_index+32'd1==output_size) phase<=DONE;
                        else begin output_index<=output_index+32'd1; phase<=OUTPUT_REQUEST; end
                    end
                    DONE: if (done_ready) phase<=IDLE;
                    default: begin error_code<=8; phase<=DONE; end
                endcase
                if (active && phase!=IDLE && phase!=DONE && entropy_error_valid) begin
                    error_code<=entropy_error; phase<=DONE;
                end else if (active && phase!=IDLE && phase!=DONE && reverse_error_valid) begin
                    error_code<=reverse_error; phase<=DONE;
                end else if (!decoding && compressed_size>=FRAME && phase!=OUTPUT_START &&
                    phase!=OUTPUT_REQUEST && phase!=OUTPUT_WAIT && phase!=OUTPUT_VALID &&
                    phase!=DONE && phase!=CHOOSE) phase<=CHOOSE;
            end
        end
    end
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: frame block=1..65536, dictionary=1..16384");
        end
    endgenerate
endmodule
