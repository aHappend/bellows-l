module bellows_l5_zstd_context #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer SG_DEPTH=16,
    parameter integer COPY_BYTES=8,
    parameter integer DICT_BYTES=16384
) (
    input wire clk, input wire rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [15:0] cmd_id, input wire cmd_decompress, input wire cmd_wide,
    input wire [1:0] cmd_checksum_mode,
    input wire [31:0] cmd_src_bytes, input wire [31:0] cmd_dst_capacity,
    input wire [4:0] cmd_src_segments, input wire [4:0] cmd_dst_segments,
    input wire cmd_use_dictionary, input wire cmd_dictionary_ok,
    input wire [14:0] dictionary_bytes,
    output wire dict_rd_en, output wire [13:0] dict_rd_addr,
    input wire dict_rd_valid, input wire [7:0] dict_rd_data,
    output wire dict_index_en, output wire dict_index_chain,
    output wire [13:0] dict_index_addr,
    input wire dict_index_valid, input wire dict_index_found,
    input wire [13:0] dict_index_position,
    input wire sg_valid, output wire sg_ready, input wire sg_destination,
    input wire [63:0] sg_addr, input wire [31:0] sg_bytes,
    output wire rd_valid, output wire [68:0] rd_payload, input wire rd_take,
    input wire rd_response, input wire [63:0] rd_data,
    input wire [3:0] rd_count, input wire rd_error,
    output wire wr_valid, output wire [136:0] wr_payload, input wire wr_take,
    input wire wr_response, input wire [3:0] wr_count, input wire wr_error,
    output wire status_valid, output wire [115:0] status_payload,
    input wire status_retire
);
    localparam integer LEGAL=MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536 &&
        SG_DEPTH>=1 && SG_DEPTH<=16 && (COPY_BYTES==4 || COPY_BYTES==8) &&
        DICT_BYTES>=1 && DICT_BYTES<=16384;
    localparam integer BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer DEPTH=LEGAL ? SG_DEPTH : 1;
    localparam integer WIDTH=LEGAL ? COPY_BYTES : 4;
    localparam integer DICTIONARY=LEGAL ? DICT_BYTES : 1;
    localparam integer FRAME_LIMIT=2*BLOCK+1024;
    localparam [3:0] IDLE=0, COLLECT=1, VALIDATE=2, ARM=3, RUN=4,
        SETTLE=5, COMPLETE=6;
    reg [3:0] phase, error_code;
    reg awake, decoding, wide, use_dictionary;
    reg [15:0] identifier;
    reg [14:0] dict_bytes;
    reg [1:0] checksum_mode;
    reg [31:0] source_bytes, capacity, reads_consumed, writes_acked, generated;
    reg [31:0] computed_checksum;
    reg [4:0] source_segments, destination_segments, source_seen, destination_seen;
    reg [4:0] source_segment, destination_segment;
    reg [36:0] source_sum, destination_sum;
    reg descriptor_bad, read_pending, write_pending, engine_done;
    reg [63:0] read_address, write_address;
    reg [31:0] read_remaining, write_remaining;
    reg [3:0] reserved_read, reserved_write;
    reg [63:0] input_queue;
    reg [3:0] input_fill;
    reg [127:0] output_queue;
    reg [4:0] output_fill;
    (* ramstyle="MLAB", nomem2reg *) reg [63:0] source_address [0:DEPTH-1];
    (* ramstyle="MLAB", nomem2reg *) reg [63:0] destination_address [0:DEPTH-1];
    (* ramstyle="MLAB", nomem2reg *) reg [31:0] source_size [0:DEPTH-1];
    (* ramstyle="MLAB", nomem2reg *) reg [31:0] destination_size [0:DEPTH-1];
    wire take_command=cmd_valid && cmd_ready;
    wire source_accept=sg_valid && sg_ready && !sg_destination;
    wire destination_accept=sg_valid && sg_ready && sg_destination;
    wire [32:0] trailer=cmd_checksum_mode==0 ? 33'd0 : 33'd4;
    wire invalid_command=cmd_checksum_mode==3 ||
        cmd_src_segments>DEPTH || cmd_dst_segments==0 || cmd_dst_segments>DEPTH ||
        cmd_dst_capacity==0 || ((cmd_src_bytes==0)!=(cmd_src_segments==0)) ||
        (!cmd_decompress && cmd_src_bytes>BLOCK) ||
        (cmd_decompress && {1'b0,cmd_src_bytes}>FRAME_LIMIT+trailer);
    wire [64:0] descriptor_end={1'b0,sg_addr}+{33'd0,sg_bytes-32'd1};
    wire [36:0] next_source_sum=source_sum+{5'd0,sg_bytes};
    wire [36:0] next_destination_sum=destination_sum+{5'd0,sg_bytes};
    wire all_descriptors=(source_seen+{4'd0,source_accept}==source_segments) &&
        (destination_seen+{4'd0,destination_accept}==destination_segments);
    wire running=rst_n && phase==RUN && error_code==0;
    wire engine_clear=phase==IDLE || phase==COLLECT || phase==VALIDATE ||
        error_code!=0;
    wire engine_start_ready, engine_s_ready, engine_m_valid, engine_status_valid;
    wire [7:0] engine_m_data;
    wire [3:0] engine_error;
    wire [31:0] engine_checksum;
    wire feed=running && input_fill!=0 && engine_s_ready && fault==0;
    wire accept_output=engine_m_valid && engine_m_ready;
    wire engine_m_ready=running && output_fill<=8 && generated<capacity && fault==0;
    wire [3:0] read_size=read_remaining==0 ? 4'd0 : !wide ? 4'd1 :
        read_remaining<WIDTH ? read_remaining[3:0] : WIDTH;
    wire [3:0] write_limit=write_remaining==0 ? 4'd0 : !wide ? 4'd1 :
        write_remaining<WIDTH ? write_remaining[3:0] : WIDTH;
    wire [3:0] write_size=engine_done && output_fill<{1'b0,write_limit} ?
        output_fill[3:0] : write_limit;
    wire [4:0] output_after_take=output_fill-(wr_take ? {1'b0,write_size} : 5'd0);
    wire accept_read_data=rd_response && !rd_error && error_code==0 && fault==0;
    reg [3:0] fault;
    reg [7:0] write_strobe;
    integer i;
    always @* begin
        fault=0;
        if (phase==RUN || phase==SETTLE) begin
            if ((rd_response && rd_error) || (wr_response && wr_error)) fault=10;
            else if (running && engine_status_valid && engine_error!=0) fault=engine_error;
            else if (running && engine_m_valid && generated>=capacity) fault=9;
        end
        write_strobe=0;
        for (i=0;i<8;i=i+1) if (i<write_size) write_strobe[i]=1;
    end
    assign cmd_ready=rst_n && awake && LEGAL && phase==IDLE;
    assign sg_ready=rst_n && LEGAL && phase==COLLECT &&
        (sg_destination ? destination_seen<destination_segments : source_seen<source_segments);
    assign rd_valid=running && fault==0 && !read_pending && input_fill==0 &&
        reads_consumed<source_bytes && read_size!=0 && !engine_done;
    assign rd_payload=rd_valid ? {wide,read_address,read_size} : 69'd0;
    assign wr_valid=running && fault==0 && !write_pending && write_size!=0 &&
        output_fill>={1'b0,write_size};
    assign wr_payload=wr_valid ? {wide,write_address,output_queue[63:0],write_strobe} : 137'd0;
    assign status_valid=rst_n && LEGAL && phase==COMPLETE;
    assign status_payload=status_valid ?
        {identifier,error_code,reads_consumed,writes_acked,computed_checksum} : 116'd0;

    wire table_start_valid, table_start_ready, count_valid, count_ready, count_last;
    wire [1:0] table_alphabet, table_mode;
    wire [3:0] table_requested_log;
    wire [5:0] table_rle_symbol;
    wire signed [10:0] count_value;
    wire table_done_valid, table_done_ready;
    wire [3:0] table_done_error;
    wire [2:0] tables_valid, init_valid, init_ready, step_valid, step_ready, m_valid, m_ready;
    wire [11:0] tables_log, available, m_nbits, peek_nbits;
    wire [26:0] init_state, bits, m_state, states;
    wire [17:0] m_symbol, peek_symbol;
    wire enc_valid, enc_ready, enc_terminal, enc_result_valid, enc_result_ready;
    wire [1:0] enc_alphabet;
    wire [5:0] enc_symbol;
    wire [8:0] enc_next_state, enc_state, enc_bits;
    wire [3:0] enc_error, enc_nbits, entropy_error;
    wire entropy_error_valid;
    bellows_l5_entropy entropy (
        .clk(clk), .rst_n(rst_n), .clear(engine_clear),
        .table_start_valid(table_start_valid), .table_start_ready(table_start_ready),
        .table_alphabet(table_alphabet), .table_mode(table_mode),
        .table_requested_log(table_requested_log), .table_rle_symbol(table_rle_symbol),
        .count_valid(count_valid), .count_ready(count_ready), .count_value(count_value),
        .count_last(count_last), .table_done_valid(table_done_valid),
        .table_done_ready(table_done_ready), .table_done_error(table_done_error),
        .tables_valid(tables_valid), .tables_log(tables_log),
        .init_valid(init_valid), .init_ready(init_ready), .init_state(init_state),
        .step_valid(step_valid), .step_ready(step_ready), .bits(bits), .available(available),
        .m_valid(m_valid), .m_ready(m_ready), .m_symbol(m_symbol), .m_state(m_state),
        .m_nbits(m_nbits), .states(states), .peek_symbol(peek_symbol), .peek_nbits(peek_nbits),
        .enc_valid(enc_valid), .enc_ready(enc_ready), .enc_alphabet(enc_alphabet),
        .enc_symbol(enc_symbol), .enc_next_state(enc_next_state), .enc_terminal(enc_terminal),
        .enc_result_valid(enc_result_valid), .enc_result_ready(enc_result_ready),
        .enc_error(enc_error), .enc_state(enc_state), .enc_bits(enc_bits), .enc_nbits(enc_nbits),
        .error_valid(entropy_error_valid), .error_code(entropy_error)
    );
    bellows_l5_frame_engine #(.MAX_BLOCK_BYTES(BLOCK), .DICT_BYTES(DICTIONARY)) engine (
        .clk(clk), .rst_n(rst_n), .clear(engine_clear),
        .start_valid(phase==ARM), .start_ready(engine_start_ready),
        .decompress(decoding), .use_dictionary(use_dictionary), .dictionary_bytes(dict_bytes),
        .checksum_mode(checksum_mode), .input_bytes(source_bytes), .output_capacity(capacity),
        .s_valid(running && input_fill!=0 && fault==0), .s_ready(engine_s_ready),
        .s_data(input_queue[7:0]),
        .m_valid(engine_m_valid), .m_ready(engine_m_ready), .m_data(engine_m_data),
        .done_valid(engine_status_valid), .done_ready(1'b0),
        .done_error(engine_error), .done_checksum(engine_checksum),
        .dict_rd_en(dict_rd_en), .dict_rd_addr(dict_rd_addr),
        .dict_rd_valid(dict_rd_valid), .dict_rd_data(dict_rd_data),
        .dict_index_en(dict_index_en), .dict_index_chain(dict_index_chain),
        .dict_index_addr(dict_index_addr),
        .dict_index_valid(dict_index_valid), .dict_index_found(dict_index_found),
        .dict_index_position(dict_index_position),
        .table_start_valid(table_start_valid), .table_start_ready(table_start_ready),
        .table_alphabet(table_alphabet), .table_mode(table_mode),
        .table_requested_log(table_requested_log), .table_rle_symbol(table_rle_symbol),
        .count_valid(count_valid), .count_ready(count_ready), .count_value(count_value),
        .count_last(count_last), .table_done_valid(table_done_valid),
        .table_done_ready(table_done_ready), .table_done_error(table_done_error),
        .tables_valid(tables_valid), .tables_log(tables_log),
        .init_valid(init_valid), .init_ready(init_ready), .init_state(init_state),
        .step_valid(step_valid), .step_ready(step_ready), .bits(bits), .available(available),
        .m_valid_fse(m_valid), .m_ready_fse(m_ready), .m_symbol(m_symbol),
        .m_state(m_state), .m_nbits(m_nbits), .states(states),
        .peek_symbol(peek_symbol), .peek_nbits(peek_nbits),
        .enc_valid(enc_valid), .enc_ready(enc_ready), .enc_alphabet(enc_alphabet),
        .enc_symbol(enc_symbol), .enc_next_state(enc_next_state), .enc_terminal(enc_terminal),
        .enc_result_valid(enc_result_valid), .enc_result_ready(enc_result_ready),
        .enc_error(enc_error), .enc_state(enc_state), .enc_bits(enc_bits), .enc_nbits(enc_nbits),
        .entropy_error_valid(entropy_error_valid), .entropy_error(entropy_error)
    );
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: block=1..65536, SG=1..16, copy=4 or 8, dictionary=1..16384");
        end
    endgenerate
    always @(posedge clk) begin
        if (source_accept) begin
            source_address[source_seen]<=sg_addr; source_size[source_seen]<=sg_bytes;
        end
        if (destination_accept) begin
            destination_address[destination_seen]<=sg_addr;
            destination_size[destination_seen]<=sg_bytes;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; error_code<=0; awake<=0; decoding<=0; wide<=0;
            use_dictionary<=0; identifier<=0; dict_bytes<=0; checksum_mode<=0;
            source_bytes<=0; capacity<=0; reads_consumed<=0; writes_acked<=0;
            generated<=0; computed_checksum<=0;
            source_segments<=0; destination_segments<=0; source_seen<=0; destination_seen<=0;
            source_segment<=0; destination_segment<=0; source_sum<=0; destination_sum<=0;
            descriptor_bad<=0; read_pending<=0; write_pending<=0; engine_done<=0;
            read_address<=0; write_address<=0; read_remaining<=0; write_remaining<=0;
            reserved_read<=0; reserved_write<=0;
            input_queue<=0; input_fill<=0; output_queue<=0; output_fill<=0;
        end else begin
            awake<=1;
            if (feed) begin input_queue<=input_queue>>8; input_fill<=input_fill-4'd1; end
            if (accept_read_data) begin input_queue<=rd_data; input_fill<=rd_count; end
            output_queue<=(output_queue>>(wr_take ? {write_size,3'b000} : 7'd0)) |
                (accept_output ? ({120'd0,engine_m_data}<<{output_after_take,3'b000}) : 128'd0);
            output_fill<=output_after_take+{4'd0,accept_output};
            if (accept_output) generated<=generated+32'd1;
            if (rd_take) begin read_pending<=1; reserved_read<=read_size; end
            if (rd_response) begin
                read_pending<=0; reads_consumed<=reads_consumed+{28'd0,rd_count};
                if (read_remaining=={28'd0,reserved_read} &&
                    source_segment+5'd1<source_segments) begin
                    source_segment<=source_segment+5'd1;
                    read_address<=source_address[source_segment+5'd1];
                    read_remaining<=source_size[source_segment+5'd1];
                end else begin
                    read_address<=read_address+{60'd0,reserved_read};
                    read_remaining<=read_remaining-{28'd0,reserved_read};
                end
            end
            if (wr_take) begin
                write_pending<=1; reserved_write<=write_size;
                if (write_remaining=={28'd0,write_size} &&
                    destination_segment+5'd1<destination_segments) begin
                    destination_segment<=destination_segment+5'd1;
                    write_address<=destination_address[destination_segment+5'd1];
                    write_remaining<=destination_size[destination_segment+5'd1];
                end else begin
                    write_address<=write_address+{60'd0,write_size};
                    write_remaining<=write_remaining-{28'd0,write_size};
                end
            end
            if (wr_response) begin
                write_pending<=0;
                if (!wr_error) writes_acked<=writes_acked+{28'd0,wr_count};
            end
            case (phase)
                IDLE: if (take_command) begin
                    identifier<=cmd_id; decoding<=cmd_decompress; wide<=cmd_wide;
                    use_dictionary<=cmd_use_dictionary;
                    dict_bytes<=cmd_use_dictionary ? dictionary_bytes : 15'd0;
                    checksum_mode<=cmd_checksum_mode; source_bytes<=cmd_src_bytes;
                    capacity<=cmd_dst_capacity; error_code<=0;
                    reads_consumed<=0; writes_acked<=0; generated<=0; computed_checksum<=0;
                    source_segments<=cmd_src_segments; destination_segments<=cmd_dst_segments;
                    source_seen<=0; destination_seen<=0; source_sum<=0; destination_sum<=0;
                    source_segment<=0; destination_segment<=0; descriptor_bad<=0;
                    read_pending<=0; write_pending<=0; engine_done<=0;
                    read_address<=0; write_address<=0; read_remaining<=0; write_remaining<=0;
                    reserved_read<=0; reserved_write<=0;
                    input_queue<=0; input_fill<=0; output_queue<=0; output_fill<=0;
                    if (cmd_use_dictionary && !cmd_dictionary_ok) begin
                        error_code<=13; phase<=COMPLETE;
                    end else if (invalid_command) begin error_code<=8; phase<=COMPLETE; end
                    else phase<=COLLECT;
                end
                COLLECT: begin
                    if (source_accept) begin
                        source_seen<=source_seen+5'd1; source_sum<=next_source_sum;
                        if (sg_bytes==0 || descriptor_end[64] || next_source_sum>37'h0ffffffff)
                            descriptor_bad<=1;
                    end
                    if (destination_accept) begin
                        destination_seen<=destination_seen+5'd1; destination_sum<=next_destination_sum;
                        if (sg_bytes==0 || descriptor_end[64] || next_destination_sum>37'h0ffffffff)
                            descriptor_bad<=1;
                    end
                    if (all_descriptors) phase<=VALIDATE;
                end
                VALIDATE: begin
                    if (descriptor_bad || source_sum!={5'd0,source_bytes} ||
                        destination_sum!={5'd0,capacity}) begin error_code<=8; phase<=COMPLETE; end
                    else phase<=ARM;
                end
                ARM: if (engine_start_ready) begin
                    if (source_segments!=0) begin
                        read_address<=source_address[0]; read_remaining<=source_size[0];
                    end
                    write_address<=destination_address[0]; write_remaining<=destination_size[0];
                    phase<=RUN;
                end
                RUN: begin
                    computed_checksum<=engine_checksum;
                    if (engine_status_valid) begin
                        engine_done<=1; computed_checksum<=engine_checksum;
                    end
                    if (engine_done && output_fill==0 && !read_pending && !write_pending)
                        phase<=COMPLETE;
                end
                SETTLE: if (!read_pending && !write_pending) phase<=COMPLETE;
                COMPLETE: if (status_retire) phase<=IDLE;
                default: begin error_code<=8; phase<=SETTLE; end
            endcase
            if (error_code==0 && fault!=0) begin
                error_code<=fault; phase<=SETTLE;
                input_queue<=0; input_fill<=0; output_queue<=0; output_fill<=0;
                computed_checksum<=engine_checksum;
            end
        end
    end
endmodule
