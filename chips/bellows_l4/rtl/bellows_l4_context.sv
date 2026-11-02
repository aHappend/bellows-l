module bellows_l4_context #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer SG_DEPTH=16,
    parameter integer COPY_BYTES=8
) (
    input wire clk, input wire rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [15:0] cmd_id, input wire cmd_decompress,
    input wire cmd_wide, input wire [2:0] cmd_codec,
    input wire [1:0] cmd_checksum_mode,
    input wire [31:0] cmd_src_bytes, input wire [31:0] cmd_dst_capacity,
    input wire [4:0] cmd_src_segments, input wire [4:0] cmd_dst_segments,
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
        SG_DEPTH>=1 && SG_DEPTH<=16 && (COPY_BYTES==4 || COPY_BYTES==8);
    localparam integer BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer DEPTH=LEGAL ? SG_DEPTH : 1;
    localparam integer WIDTH=LEGAL ? COPY_BYTES : 4;
    localparam integer INTER_LIMIT=2*BLOCK+16;
    localparam integer FRAME_LIMIT=4*BLOCK+1024;
    localparam [3:0] IDLE=0, COLLECT=1, VALIDATE=2, ARM=3,
        RUN=4, FINISH=5, TRAILER=6, SETTLE=7, COMPLETE=8;
    localparam [2:0] LZ_ENCODE=0, LZ_DECODE=1, ENTROPY=2,
        POST_LZ_ENCODE=3, POST_ENT_ENCODE=4,
        POST_ENT_DECODE=5, POST_LZ_DECODE=6;
    reg [3:0] state, error_code;
    reg [2:0] phase;
    reg [15:0] identifier;
    reg decoding, wide;
    reg [2:0] codec;
    reg [1:0] checksum_mode;
    reg [31:0] source_bytes, payload_bytes, capacity;
    reg [4:0] source_segments, destination_segments, source_seen, destination_seen;
    reg [36:0] source_sum, destination_sum;
    reg descriptor_bad;
    (* ramstyle="MLAB", nomem2reg *) reg [63:0] source_address [0:DEPTH-1];
    (* ramstyle="MLAB", nomem2reg *) reg [63:0] destination_address [0:DEPTH-1];
    (* ramstyle="MLAB", nomem2reg *) reg [31:0] source_size [0:DEPTH-1];
    (* ramstyle="MLAB", nomem2reg *) reg [31:0] destination_size [0:DEPTH-1];
    reg [4:0] source_segment, destination_segment;
    reg [31:0] source_offset, destination_offset;
    reg [63:0] read_address, write_address;
    reg [31:0] reads_consumed, writes_acked, writes_reserved, feed_index;
    reg read_pending, write_pending;
    reg [3:0] reserved_read_count, reserved_write_count;
    reg [127:0] input_queue;
    reg [4:0] input_fill;
    reg [255:0] output_queue;
    reg [5:0] output_fill;
    reg [31:0] raw_count, output_generated;
    reg empty_sent, codec_done, entropy_started;
    reg [31:0] intermediate_count, intermediate_read, declared_raw;
    reg intermediate_pending;
    reg [2:0] copy_pending;
    reg [63:0] checksum_beat;
    reg [3:0] checksum_left;
    reg checksum_finish_sent, checksum_done;
    reg [31:0] computed_checksum, expected_checksum;
    reg [2:0] trailer_received, trailer_sent;

    wire command_accept=cmd_valid && cmd_ready;
    wire source_accept=sg_valid && sg_ready && !sg_destination;
    wire destination_accept=sg_valid && sg_ready && sg_destination;
    wire [31:0] command_trailer=cmd_checksum_mode==0 ? 32'd0 : 32'd4;
    wire invalid_command=cmd_codec>4 || cmd_checksum_mode==3 ||
        cmd_src_segments>DEPTH || cmd_dst_segments==0 || cmd_dst_segments>DEPTH ||
        cmd_dst_capacity==0 || ((cmd_src_bytes==0)!=(cmd_src_segments==0)) ||
        (!cmd_decompress && (cmd_src_bytes>BLOCK ||
            (cmd_codec==2 && cmd_src_bytes[0]))) ||
        (cmd_decompress && (cmd_src_bytes<command_trailer+
            (cmd_codec==0 ? 32'd1 : 32'd20) ||
            cmd_src_bytes>command_trailer+
            (cmd_codec==0 ? INTER_LIMIT : FRAME_LIMIT)));
    wire [64:0] descriptor_end={1'b0,sg_addr}+{33'd0,sg_bytes-32'd1};
    wire [36:0] next_source_sum=source_sum+{5'd0,sg_bytes};
    wire [36:0] next_destination_sum=destination_sum+{5'd0,sg_bytes};
    wire all_descriptors=(source_seen+{4'd0,source_accept}==source_segments) &&
        (destination_seen+{4'd0,destination_accept}==destination_segments);
    assign cmd_ready=rst_n && LEGAL && state==IDLE;
    assign sg_ready=rst_n && LEGAL && state==COLLECT &&
        (sg_destination ? destination_seen<destination_segments :
                          source_seen<source_segments);
    wire running=rst_n && state==RUN && error_code==0;
    wire lz_encoding=phase==LZ_ENCODE || phase==POST_LZ_ENCODE;
    wire lz_decoding=phase==LZ_DECODE || phase==POST_LZ_DECODE;
    wire entropy_phase=phase==ENTROPY || phase==POST_ENT_ENCODE ||
        phase==POST_ENT_DECODE;
    wire internal_source=phase==POST_ENT_ENCODE || phase==POST_LZ_DECODE;
    wire original_source=phase==LZ_ENCODE || phase==POST_LZ_ENCODE ||
        (phase==ENTROPY && !decoding);
    wire post_store=phase==POST_LZ_ENCODE || phase==POST_ENT_DECODE;
    wire units_reset=rst_n && (state==ARM || state==RUN || state==FINISH ||
        state==TRAILER || state==SETTLE) && error_code==0;
    wire decoder_clear=state==ARM ||
        (running && phase==POST_ENT_DECODE && e_status_valid && e_status_error==0);
    wire checksum_start=state==ARM;
    wire checksum_ready, checksum_finish_ready, checksum_result_valid;
    wire [31:0] checksum_result;
    wire c_s_ready, c_m_valid, c_m_last, c_status_valid;
    wire [7:0] c_m_data;
    wire [2:0] c_status_error;
    wire e_start_ready, e_s_ready, e_m_valid, e_m_last, e_status_valid;
    wire [7:0] e_m_data;
    wire [3:0] e_status_error;
    wire [31:0] e_raw_bytes, e_source_bytes, e_output_bytes;
    wire d_s_ready, d_status_valid;
    wire [3:0] d_status_error;
    wire [31:0] d_decoded_bytes, d_consumed_bytes;
    wire op_valid, op_ready, op_match;
    wire [63:0] op_data, copy_data;
    wire [3:0] op_count, copy_count;
    wire [15:0] op_offset;
    wire copy_valid, copy_ready;
    wire inter_read_ready, inter_valid, inter_ready;
    wire [63:0] inter_data;
    wire [3:0] inter_count;
    wire checksumming=checksum_mode!=0;
    wire checksum_byte_ready=!checksumming || checksum_ready;
    reg [3:0] read_size, write_size, decoder_count, inter_request_count;
    reg [63:0] write_data, decoder_data;
    reg [7:0] write_strobe;
    integer i;
    wire [31:0] source_remaining=source_bytes-reads_consumed;
    wire [31:0] source_segment_remaining=source_size[source_segment]-source_offset;
    wire [31:0] destination_remaining=capacity-writes_reserved;
    wire [31:0] destination_segment_remaining=
        destination_size[destination_segment]-destination_offset;
    wire [31:0] payload_remaining=payload_bytes-feed_index;
    wire [31:0] inter_remaining=intermediate_count-intermediate_read;
    always @* begin
        read_size=wide ? WIDTH : 1;
        if (source_remaining<read_size) read_size=source_remaining[3:0];
        if (source_segment_remaining<read_size)
            read_size=source_segment_remaining[3:0];
        write_size=wide ? WIDTH : 1;
        if (destination_remaining<write_size) write_size=destination_remaining[3:0];
        if (destination_segment_remaining<write_size)
            write_size=destination_segment_remaining[3:0];
        if ((state==TRAILER || state==SETTLE || state==FINISH) && output_fill<write_size)
            write_size=output_fill[3:0];
        write_data=0; write_strobe=0;
        for (i=0;i<8;i=i+1) begin
            if (i<write_size) begin
                write_data[i*8 +: 8]=output_queue[i*8 +: 8];
                write_strobe[i]=1;
            end
        end
        decoder_count=WIDTH;
        if (input_fill<decoder_count) decoder_count=input_fill[3:0];
        if (payload_remaining<decoder_count) decoder_count=payload_remaining[3:0];
        decoder_data=0;
        for (i=0;i<8;i=i+1)
            if (i<decoder_count) decoder_data[i*8 +: 8]=input_queue[i*8 +: 8];
        inter_request_count=phase==POST_LZ_DECODE ? WIDTH : 1;
        if (inter_remaining<inter_request_count)
            inter_request_count=inter_remaining[3:0];
    end
    reg [3:0] fault;
    reg [3:0] input_take, output_push_count;
    reg [63:0] output_push_data;
    wire c_input=running && lz_encoding && !codec_done &&
        (input_fill!=0 || (source_bytes==0 && !empty_sent));
    wire e_input=running && entropy_phase && entropy_started &&
        (internal_source ? inter_valid : input_fill!=0 && feed_index<payload_bytes);
    wire d_input=running && lz_decoding &&
        (internal_source ? inter_valid : decoder_count!=0);
    wire c_input_last=source_bytes==0 || feed_index+32'd1==source_bytes;
    wire e_input_last=internal_source ?
        intermediate_read+{28'd0,inter_count}==intermediate_count :
        feed_index+32'd1==payload_bytes;
    wire d_input_last=internal_source ?
        intermediate_read+{28'd0,inter_count}==intermediate_count :
        feed_index+{28'd0,decoder_count}==payload_bytes;
    wire c_transfer=c_input && c_s_ready && checksum_byte_ready && fault==0;
    wire e_transfer=e_input && e_s_ready &&
        (!original_source || checksum_byte_ready) && fault==0;
    wire d_transfer=d_input && d_s_ready && fault==0;
    wire checksum_drain=running && checksum_left!=0 && checksum_ready && fault==0 &&
        output_fill<=31;
    wire normal_c_output=running && lz_encoding && c_m_valid;
    wire normal_e_output=running && entropy_phase && e_m_valid;
    wire normal_copy_output=running && lz_decoding && copy_valid;
    wire byte_output=normal_c_output || normal_e_output;
    wire [7:0] byte_output_data=normal_c_output ? c_m_data : e_m_data;
    wire [3:0] offered_count=normal_copy_output ? copy_count : 4'd1;
    wire output_offer=(byte_output && !post_store) || normal_copy_output;
    wire capacity_fault=output_offer &&
        ({1'b0,output_generated}+{29'd0,offered_count}>{1'b0,capacity});
    wire block_fault=decoding && !post_store && output_offer &&
        ({1'b0,raw_count}+{29'd0,offered_count}>BLOCK);
    wire inter_overflow=post_store && byte_output && intermediate_count>=INTER_LIMIT;
    wire codec_status=running && (lz_encoding ? c_status_valid :
        lz_decoding ? d_status_valid : e_status_valid);
    wire [3:0] codec_error=lz_encoding ? {1'b0,c_status_error} :
        lz_decoding ? d_status_error : e_status_error;
    wire output_room=output_fill<=24;
    wire byte_output_ready=running && fault==0 && (post_store ||
        (output_room && (!decoding || checksum_byte_ready)));
    wire byte_output_transfer=byte_output && byte_output_ready;
    assign copy_ready=running && lz_decoding && fault==0 &&
        (checksumming ? checksum_left==0 : output_room);
    wire copy_transfer=copy_valid && copy_ready;
    wire op_transfer=op_valid && op_ready;
    wire entropy_start=running && entropy_phase && !entropy_started;
    wire trailer_input=running && decoding && input_fill!=0 &&
        feed_index>=payload_bytes && trailer_received<4 && checksumming;
    wire inter_read_request=running && internal_source && !intermediate_pending &&
        intermediate_read<intermediate_count;
    assign inter_ready=phase==POST_ENT_ENCODE ? e_transfer : d_transfer;
    wire inter_write=running && post_store && byte_output_transfer;
    wire phase_output_done=codec_done &&
        (!lz_decoding || (copy_pending==0 && !copy_valid)) && checksum_left==0;
    wire checksum_finish=(state==RUN || state==FINISH || state==SETTLE) &&
        !checksum_finish_sent && (error_code!=0 ||
        (decoding ? phase_output_done && !post_store :
            feed_index==source_bytes && (source_bytes!=0 || !lz_encoding || empty_sent)));
    wire checksum_input_valid=checksumming && fault==0 &&
        (original_source ? (c_transfer && source_bytes!=0) || e_transfer :
            checksum_drain ||
            (decoding && !post_store && normal_e_output && byte_output_ready));
    wire [7:0] checksum_input_data=original_source ? input_queue[7:0] :
        checksum_left!=0 ? checksum_beat[7:0] : e_m_data;
    wire frame_drained=phase_output_done && reads_consumed==source_bytes &&
        input_fill==0 && !read_pending && checksum_done;
    always @* begin
        fault=0;
        if (state==RUN || state==FINISH || state==TRAILER || state==SETTLE) begin
            if ((rd_response && rd_error) || (wr_response && wr_error)) fault=10;
            else if (codec_status && codec_error!=0) fault=codec_error;
            else if (running && phase==POST_ENT_DECODE && e_status_valid &&
                intermediate_count==0) fault=11;
            else if (state==FINISH && phase==POST_LZ_DECODE &&
                raw_count!=declared_raw) fault=11;
            else if (inter_overflow) fault=5;
            else if (block_fault) fault=5;
            else if (capacity_fault) fault=9;
            else if (state==FINISH && decoding && checksum_done && checksumming &&
                computed_checksum!=expected_checksum) fault=7;
            else if (state==TRAILER && trailer_sent<4 && output_generated>=capacity)
                fault=9;
        end
    end
    always @* begin
        input_take=0;
        if (fault==0 && error_code==0) begin
            if (c_transfer && source_bytes!=0) input_take=1;
            else if (e_transfer && !internal_source) input_take=1;
            else if (d_transfer && !internal_source) input_take=decoder_count;
            else if (trailer_input) input_take=1;
        end
        output_push_data=0; output_push_count=0;
        if (fault==0 && error_code==0) begin
            if (copy_transfer && !checksumming) begin
                output_push_data=copy_data; output_push_count=copy_count;
            end else if (checksum_drain) begin
                output_push_data={56'd0,checksum_beat[7:0]}; output_push_count=1;
            end else if (byte_output_transfer && !post_store) begin
                output_push_data={56'd0,byte_output_data}; output_push_count=1;
            end else if (state==TRAILER && trailer_sent<4 && output_fill<=24 &&
                output_generated<capacity) begin
                output_push_data={56'd0,computed_checksum[trailer_sent*8 +: 8]};
                output_push_count=1;
            end
        end
    end
    wire [3:0] output_take=wr_take ? write_size : 4'd0;
    wire [5:0] output_after_take=output_fill-{2'd0,output_take};
    wire [4:0] input_after_take=input_fill-{1'b0,input_take};
    wire accept_read_data=rd_response && !rd_error && error_code==0 && fault==0;
    assign rd_valid=rst_n && LEGAL && running && fault==0 && !read_pending &&
        reads_consumed<source_bytes && input_fill<=8;
    assign rd_payload=rd_valid ? {wide,read_address,read_size} : 69'd0;
    assign wr_valid=rst_n && LEGAL && error_code==0 && fault==0 &&
        (state==RUN || state==FINISH || state==TRAILER || state==SETTLE) &&
        !write_pending && write_size!=0 && output_fill>={2'd0,write_size};
    assign wr_payload=wr_valid ? {wide,write_address,write_data,write_strobe} : 137'd0;
    assign status_valid=rst_n && LEGAL && state==COMPLETE;
    assign status_payload=status_valid ?
        {identifier,error_code,reads_consumed,writes_acked,computed_checksum} : 116'd0;

    bellows_l2_compressor #(.MAX_BLOCK_BYTES(BLOCK)) compressor (
        .clk(clk), .rst_n(units_reset),
        .s_data(input_queue[7:0]), .s_keep(source_bytes!=0),
        .s_valid(c_input && checksum_byte_ready && fault==0),
        .s_last(c_input_last), .s_ready(c_s_ready),
        .m_data(c_m_data), .m_valid(c_m_valid), .m_last(c_m_last),
        .m_ready(lz_encoding && byte_output_ready),
        .status_valid(c_status_valid), .status_error(c_status_error),
        .status_ready(1'b0)
    );
    bellows_l4_lz4_decoder #(.MAX_BLOCK_BYTES(BLOCK),.COPY_BYTES(WIDTH)) decoder (
        .clk(clk), .rst_n(units_reset), .clear(decoder_clear),
        .s_valid(d_input && fault==0), .s_ready(d_s_ready),
        .s_data(internal_source ? inter_data : decoder_data),
        .s_count(internal_source ? inter_count : decoder_count), .s_last(d_input_last),
        .op_valid(op_valid), .op_ready(op_ready), .op_match(op_match),
        .op_data(op_data), .op_count(op_count), .op_offset(op_offset),
        .status_valid(d_status_valid), .status_ready(1'b0),
        .status_error(d_status_error), .decoded_bytes(d_decoded_bytes),
        .consumed_bytes(d_consumed_bytes)
    );
    bellows_l4_copy_engine #(.MAX_BLOCK_BYTES(BLOCK),.COPY_BYTES(WIDTH)) copy (
        .clk(clk), .rst_n(units_reset), .clear(decoder_clear),
        .op_valid(op_valid && running && lz_decoding), .op_ready(op_ready),
        .op_match(op_match), .op_data(op_data), .op_count(op_count),
        .op_offset(op_offset), .m_valid(copy_valid), .m_ready(copy_ready),
        .m_data(copy_data), .m_count(copy_count)
    );
    bellows_l4_entropy #(.MAX_BLOCK_BYTES(BLOCK)) entropy (
        .clk(clk), .rst_n(units_reset),
        .start_valid(entropy_start), .start_ready(e_start_ready),
        .decompress(decoding), .codec(codec),
        .raw_bytes(source_bytes),
        .input_bytes(phase==POST_ENT_ENCODE ? intermediate_count : payload_bytes),
        .s_valid(e_input && (!original_source || checksum_byte_ready) && fault==0),
        .s_ready(e_s_ready), .s_data(internal_source ? inter_data[7:0] : input_queue[7:0]),
        .s_last(e_input_last), .m_valid(e_m_valid), .m_ready(entropy_phase && byte_output_ready),
        .m_data(e_m_data), .m_last(e_m_last),
        .status_valid(e_status_valid),
        .status_ready(running && phase==POST_ENT_DECODE && e_status_error==0),
        .status_error(e_status_error), .result_raw_bytes(e_raw_bytes),
        .result_source_bytes(e_source_bytes), .result_output_bytes(e_output_bytes)
    );
    bellows_l4_intermediate #(.MAX_BLOCK_BYTES(BLOCK)) intermediate (
        .clk(clk), .rst_n(rst_n), .clear(state==ARM || error_code!=0),
        .write_valid(inter_write), .write_index(intermediate_count),
        .write_data(byte_output_data), .read_valid(inter_read_request),
        .read_ready(inter_read_ready), .read_index(intermediate_read),
        .read_count(inter_request_count), .m_valid(inter_valid),
        .m_ready(inter_ready), .m_data(inter_data), .m_count(inter_count)
    );
    bellows_l3_checksum checksum (
        .clk(clk), .rst_n(rst_n), .start(checksum_start), .mode(checksum_mode),
        .s_data(checksum_input_data), .s_valid(checksum_input_valid),
        .s_ready(checksum_ready), .finish_valid(checksum_finish),
        .finish_ready(checksum_finish_ready), .result_valid(checksum_result_valid),
        .result(checksum_result)
    );
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: MAX_BLOCK_BYTES=1..65536, SG_DEPTH=1..16, COPY_BYTES=4 or 8");
        end
    endgenerate
    always @(posedge clk) begin
        if (source_accept) begin
            source_address[source_seen]<=sg_addr;
            source_size[source_seen]<=sg_bytes;
        end
        if (destination_accept) begin
            destination_address[destination_seen]<=sg_addr;
            destination_size[destination_seen]<=sg_bytes;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; error_code<=0; phase<=LZ_ENCODE; identifier<=0;
            decoding<=0; wide<=0; codec<=0; checksum_mode<=0;
            source_bytes<=0; payload_bytes<=0; capacity<=0;
            source_segments<=0; destination_segments<=0;
            source_seen<=0; destination_seen<=0; source_sum<=0; destination_sum<=0;
            descriptor_bad<=0; source_segment<=0; destination_segment<=0;
            source_offset<=0; destination_offset<=0; read_address<=0; write_address<=0;
            reads_consumed<=0; writes_acked<=0; writes_reserved<=0; feed_index<=0;
            read_pending<=0; write_pending<=0;
            reserved_read_count<=0; reserved_write_count<=0;
            input_queue<=0; input_fill<=0; output_queue<=0; output_fill<=0;
            raw_count<=0; output_generated<=0; empty_sent<=0; codec_done<=0;
            entropy_started<=0; intermediate_count<=0; intermediate_read<=0;
            declared_raw<=0; intermediate_pending<=0; copy_pending<=0;
            checksum_beat<=0; checksum_left<=0;
            checksum_finish_sent<=0; checksum_done<=0;
            computed_checksum<=0; expected_checksum<=0;
            trailer_received<=0; trailer_sent<=0;
        end else begin
            input_queue<=(input_queue>>({3'd0,input_take}<<3)) |
                (accept_read_data ?
                    ({64'd0,rd_data}<<({3'd0,input_after_take}<<3)) : 128'd0);
            input_fill<=input_after_take+
                (accept_read_data ? {1'b0,rd_count} : 5'd0);
            output_queue<=(output_queue>>({3'd0,output_take}<<3)) |
                ({192'd0,output_push_data}<<({3'd0,output_after_take}<<3));
            output_fill<=output_after_take+{2'd0,output_push_count};
            if (rd_take) begin
                read_pending<=1; reserved_read_count<=read_size;
            end
            if (rd_response) begin
                read_pending<=0;
                reads_consumed<=reads_consumed+{28'd0,reserved_read_count};
                if (source_offset+{28'd0,reserved_read_count}==source_size[source_segment]) begin
                    source_offset<=0;
                    if (source_segment+5'd1<source_segments) begin
                        source_segment<=source_segment+5'd1;
                        read_address<=source_address[source_segment+5'd1];
                    end
                end else begin
                    source_offset<=source_offset+{28'd0,reserved_read_count};
                    read_address<=read_address+{60'd0,reserved_read_count};
                end
            end
            if (wr_take) begin
                write_pending<=1; reserved_write_count<=write_size;
                writes_reserved<=writes_reserved+{28'd0,write_size};
                if (destination_offset+{28'd0,write_size}==destination_size[destination_segment]) begin
                    destination_offset<=0;
                    if (destination_segment+5'd1<destination_segments) begin
                        destination_segment<=destination_segment+5'd1;
                        write_address<=destination_address[destination_segment+5'd1];
                    end
                end else begin
                    destination_offset<=destination_offset+{28'd0,write_size};
                    write_address<=write_address+{60'd0,write_size};
                end
            end
            if (wr_response) begin
                write_pending<=0;
                if (!wr_error) writes_acked<=writes_acked+{28'd0,wr_count};
            end
            if (input_take!=0) feed_index<=feed_index+{28'd0,input_take};
            if (c_transfer && source_bytes==0) empty_sent<=1;
            if (original_source && ((c_transfer && source_bytes!=0) || e_transfer))
                raw_count<=raw_count+32'd1;
            if (trailer_input && fault==0) begin
                expected_checksum[trailer_received*8 +: 8]<=input_queue[7:0];
                trailer_received<=trailer_received+3'd1;
            end
            if (entropy_start && e_start_ready) entropy_started<=1;
            if (codec_status && codec_error==0) codec_done<=1;
            case ({op_transfer,copy_transfer})
                2'b10: copy_pending<=copy_pending+3'd1;
                2'b01: copy_pending<=copy_pending-3'd1;
                default: begin end
            endcase
            if (copy_transfer) begin
                raw_count<=raw_count+{28'd0,copy_count};
                output_generated<=output_generated+{28'd0,copy_count};
                if (checksumming) begin
                    checksum_beat<=copy_data; checksum_left<=copy_count;
                end
            end
            if (checksum_drain) begin
                checksum_beat<=checksum_beat>>8; checksum_left<=checksum_left-4'd1;
            end
            if (byte_output_transfer) begin
                if (post_store) intermediate_count<=intermediate_count+32'd1;
                else begin
                    output_generated<=output_generated+32'd1;
                    if (decoding) raw_count<=raw_count+32'd1;
                end
            end
            if (inter_read_request && inter_read_ready) intermediate_pending<=1;
            if (inter_valid && inter_ready) begin
                intermediate_pending<=0;
                intermediate_read<=intermediate_read+{28'd0,inter_count};
            end
            if (checksum_finish && checksum_finish_ready) checksum_finish_sent<=1;
            if (checksum_finish_sent && checksum_result_valid) begin
                checksum_done<=1; computed_checksum<=checksum_result;
            end
            if (state==TRAILER && output_push_count!=0) begin
                trailer_sent<=trailer_sent+3'd1;
                output_generated<=output_generated+32'd1;
            end
            case (state)
                IDLE: if (command_accept) begin
                    identifier<=cmd_id; decoding<=cmd_decompress; wide<=cmd_wide;
                    codec<=cmd_codec; checksum_mode<=cmd_checksum_mode;
                    source_bytes<=cmd_src_bytes; capacity<=cmd_dst_capacity;
                    payload_bytes<=cmd_decompress ? cmd_src_bytes-command_trailer : cmd_src_bytes;
                    source_segments<=cmd_src_segments; destination_segments<=cmd_dst_segments;
                    source_seen<=0; destination_seen<=0; source_sum<=0; destination_sum<=0;
                    descriptor_bad<=0; source_segment<=0; destination_segment<=0;
                    source_offset<=0; destination_offset<=0; read_address<=0; write_address<=0;
                    reads_consumed<=0; writes_acked<=0; writes_reserved<=0; feed_index<=0;
                    read_pending<=0; write_pending<=0;
                    reserved_read_count<=0; reserved_write_count<=0;
                    input_queue<=0; input_fill<=0; output_queue<=0; output_fill<=0;
                    raw_count<=0; output_generated<=0; empty_sent<=0; codec_done<=0;
                    entropy_started<=0; intermediate_count<=0; intermediate_read<=0;
                    declared_raw<=0; intermediate_pending<=0; copy_pending<=0;
                    checksum_beat<=0; checksum_left<=0; checksum_finish_sent<=0;
                    checksum_done<=0; computed_checksum<=0; expected_checksum<=0;
                    trailer_received<=0; trailer_sent<=0;
                    if (cmd_codec==0) begin
                        if (cmd_decompress) phase<=LZ_DECODE;
                        else phase<=LZ_ENCODE;
                    end else if (cmd_codec==4) begin
                        if (cmd_decompress) phase<=POST_ENT_DECODE;
                        else phase<=POST_LZ_ENCODE;
                    end else phase<=ENTROPY;
                    if (invalid_command) begin error_code<=8; state<=COMPLETE; end
                    else begin error_code<=0; state<=COLLECT; end
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
                    if (all_descriptors) state<=VALIDATE;
                end
                VALIDATE: begin
                    if (descriptor_bad || source_sum!={5'd0,source_bytes} ||
                        destination_sum!={5'd0,capacity}) begin
                        error_code<=8; state<=COMPLETE;
                    end else state<=ARM;
                end
                ARM: begin
                    if (source_segments!=0) read_address<=source_address[0];
                    write_address<=destination_address[0]; state<=RUN;
                end
                RUN: begin
                    if (phase==POST_LZ_ENCODE && c_status_valid && c_status_error==0) begin
                        phase<=POST_ENT_ENCODE; codec_done<=0;
                        entropy_started<=0; intermediate_read<=0;
                    end else if (phase==POST_ENT_DECODE && e_status_valid && e_status_error==0) begin
                        phase<=POST_LZ_DECODE; codec_done<=0;
                        declared_raw<=e_raw_bytes; intermediate_read<=0; copy_pending<=0;
                    end else if (frame_drained) state<=FINISH;
                end
                FINISH: begin
                    if (!decoding && checksumming) state<=TRAILER;
                    else state<=SETTLE;
                end
                TRAILER: if (trailer_sent==4) state<=SETTLE;
                SETTLE: if (!read_pending && !write_pending && output_fill==0 &&
                    checksum_done) state<=COMPLETE;
                COMPLETE: if (status_retire) state<=IDLE;
                default: state<=IDLE;
            endcase
            if (error_code==0 && fault!=0) begin
                error_code<=fault; state<=SETTLE;
                input_queue<=0; input_fill<=0; output_queue<=0; output_fill<=0;
                checksum_left<=0; copy_pending<=0;
            end
        end
    end
endmodule
