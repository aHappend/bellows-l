module bellows_l3_context #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer SG_DEPTH=16
) (
    input wire clk, input wire rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [15:0] cmd_id, input wire cmd_decompress,
    input wire [1:0] cmd_checksum_mode,
    input wire [31:0] cmd_src_bytes, input wire [31:0] cmd_dst_capacity,
    input wire [4:0] cmd_src_segments, input wire [4:0] cmd_dst_segments,
    input wire sg_valid, output wire sg_ready, input wire sg_destination,
    input wire [63:0] sg_addr, input wire [31:0] sg_bytes,
    output wire rd_valid, output wire [63:0] rd_addr, input wire rd_take,
    input wire rd_response, input wire [7:0] rd_data, input wire rd_error,
    output wire wr_valid, output wire [71:0] wr_payload, input wire wr_take,
    input wire wr_response, input wire wr_error,
    output wire status_valid, output wire [115:0] status_payload,
    input wire status_retire
);
    localparam integer SAFE_BLOCK =
        MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536 ? MAX_BLOCK_BYTES : 1;
    localparam integer SAFE_SG=SG_DEPTH>=1 && SG_DEPTH<=16 ? SG_DEPTH : 1;
    localparam [3:0] IDLE=0, COLLECT=1, VALIDATE=2, ARM=3,
        RUN=4, TRAILER=5, SETTLE=6, COMPLETE=7;
    reg [3:0] state, error_code;
    reg [15:0] identifier;
    reg decompress;
    reg [1:0] checksum_mode;
    reg [31:0] source_bytes, destination_capacity, payload_bytes;
    reg [4:0] source_segments, destination_segments, source_seen, destination_seen;
    reg [36:0] source_sum, destination_sum;
    reg descriptor_bad;
    (* nomem2reg *) reg [63:0] source_address [0:SAFE_SG-1];
    (* nomem2reg *) reg [63:0] destination_address [0:SAFE_SG-1];
    (* nomem2reg *) reg [31:0] source_size [0:SAFE_SG-1];
    (* nomem2reg *) reg [31:0] destination_size [0:SAFE_SG-1];
    reg [4:0] source_index, destination_index;
    reg [31:0] source_offset, destination_offset;
    reg [63:0] read_address, write_address;
    reg read_pending, write_pending;
    reg input_valid, output_valid;
    reg [7:0] input_data, output_data;
    reg [31:0] input_index;
    reg [31:0] reads_consumed, writes_acked, content_count, output_count;
    reg input_done, empty_sent, codec_done, checksum_finish_sent, checksum_done;
    reg [31:0] computed_checksum, expected_checksum;
    reg [2:0] trailer_received, trailer_sent;

    wire [31:0] command_trailer=cmd_checksum_mode==0 ? 32'd0 : 32'd4;
    wire invalid_command =
        cmd_checksum_mode==3 || cmd_src_segments>SAFE_SG ||
        cmd_dst_segments==0 || cmd_dst_segments>SAFE_SG ||
        cmd_dst_capacity==0 ||
        ((cmd_src_bytes==0)!=(cmd_src_segments==0)) ||
        (!cmd_decompress && cmd_src_bytes>SAFE_BLOCK) ||
        (cmd_decompress && (cmd_src_bytes<command_trailer+1 ||
                           cmd_src_bytes>2*SAFE_BLOCK+20));
    wire source_accept=sg_valid && sg_ready && !sg_destination;
    wire destination_accept=sg_valid && sg_ready && sg_destination;
    wire [31:0] segment_last_offset=sg_bytes-32'd1;
    wire [64:0] segment_last_address={1'b0,sg_addr}+{33'd0,segment_last_offset};
    wire [36:0] next_source_sum=source_sum+{5'd0,sg_bytes};
    wire [36:0] next_destination_sum=destination_sum+{5'd0,sg_bytes};
    wire all_descriptors =
        (source_seen+{4'd0,source_accept}==source_segments) &&
        (destination_seen+{4'd0,destination_accept}==destination_segments);
    assign cmd_ready=rst_n && state==IDLE;
    assign sg_ready=rst_n && state==COLLECT &&
        (sg_destination ? destination_seen<destination_segments :
                          source_seen<source_segments);

    wire codec_reset=rst_n && (state==RUN || state==TRAILER || state==SETTLE) &&
                     error_code==0;
    wire c_s_ready, d_s_ready, c_m_valid, d_m_valid, c_m_last, d_m_last;
    wire [7:0] c_m_data, d_m_data;
    wire c_status_valid, d_status_valid;
    wire [2:0] c_status_error, d_status_error;
    wire checksum_ready, checksum_finish_ready, checksum_result_valid;
    wire [31:0] checksum_result;
    wire content_input=state==RUN && !decompress && input_valid && error_code==0;
    wire payload_input=state==RUN && decompress && input_valid &&
                       input_index<payload_bytes && error_code==0;
    wire empty_input=state==RUN && !decompress && source_bytes==0 &&
                     !empty_sent && error_code==0;
    wire codec_output_valid=decompress ? d_m_valid : c_m_valid;
    wire [7:0] codec_output_data=decompress ? d_m_data : c_m_data;
    wire codec_status_valid=decompress ? d_status_valid : c_status_valid;
    wire [2:0] codec_status_error=decompress ? d_status_error : c_status_error;
    wire output_limit=state==RUN && error_code==0 && codec_output_valid &&
                      decompress && content_count>=SAFE_BLOCK;
    wire capacity_limit=error_code==0 &&
        ((state==RUN && codec_output_valid && output_count>=destination_capacity) ||
         (state==TRAILER && trailer_sent<4 && output_count>=destination_capacity));
    reg [3:0] fault;
    always @* begin
        fault=0;
        if (state==RUN || state==TRAILER || state==SETTLE) begin
            if ((rd_response && rd_error) || (wr_response && wr_error)) fault=10;
            else if (!codec_done && codec_status_valid && codec_status_error!=0)
                fault={1'b0,codec_status_error};
            else if (output_limit) fault=5;
            else if (capacity_limit) fault=9;
        end
    end
    wire output_ready=state==RUN && error_code==0 && fault==0 && !output_valid &&
                      (!decompress || checksum_ready);
    wire content_transfer=content_input && c_s_ready && checksum_ready && fault==0;
    wire payload_transfer=payload_input && d_s_ready && fault==0;
    wire output_transfer=codec_output_valid && output_ready;
    wire checksum_input_valid=decompress ? output_transfer : content_transfer;
    wire [7:0] checksum_input_data=decompress ? codec_output_data : input_data;
    wire finish_checksum=(state==RUN || state==TRAILER || state==SETTLE) &&
        !checksum_finish_sent &&
        (error_code!=0 || (decompress ? codec_done : input_done));
    bellows_l2_top #(.MAX_BLOCK_BYTES(SAFE_BLOCK)) codec (
        .clk(clk), .rst_n(codec_reset), .roundtrip_enable(1'b0),
        .c_s_data(input_data), .c_s_keep(!empty_input),
        .c_s_valid(fault==0 && (empty_input || (content_input && checksum_ready))),
        .c_s_last(empty_input || input_index==source_bytes-1'b1),
        .c_s_ready(c_s_ready), .c_m_data(c_m_data), .c_m_valid(c_m_valid),
        .c_m_last(c_m_last), .c_m_ready(!decompress && output_ready),
        .c_status_valid(c_status_valid), .c_status_error(c_status_error),
        .c_status_ready(!decompress && state==RUN),
        .d_s_data(input_data), .d_s_valid(payload_input && fault==0),
        .d_s_last(input_index==payload_bytes-1'b1), .d_s_ready(d_s_ready),
        .d_m_data(d_m_data), .d_m_valid(d_m_valid), .d_m_last(d_m_last),
        .d_m_ready(decompress && output_ready),
        .d_status_valid(d_status_valid), .d_status_error(d_status_error),
        .d_status_ready(decompress && state==RUN)
    );
    bellows_l3_checksum checksum (
        .clk(clk), .rst_n(rst_n), .start(state==ARM), .mode(checksum_mode),
        .s_data(checksum_input_data), .s_valid(checksum_input_valid),
        .s_ready(checksum_ready), .finish_valid(finish_checksum),
        .finish_ready(checksum_finish_ready), .result_valid(checksum_result_valid),
        .result(checksum_result)
    );
    assign rd_valid=rst_n && state==RUN && error_code==0 && fault==0 &&
        !read_pending && !input_valid && reads_consumed<source_bytes;
    assign rd_addr=rd_valid ? read_address : 64'd0;
    assign wr_valid=rst_n && error_code==0 && fault==0 &&
        (state==RUN || state==TRAILER || state==SETTLE) &&
        output_valid && !write_pending;
    assign wr_payload=wr_valid ? {write_address,output_data} : 72'd0;
    assign status_valid=rst_n && state==COMPLETE;
    assign status_payload=status_valid ?
        {identifier,error_code,reads_consumed,writes_acked,computed_checksum} : 116'd0;

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
            state<=IDLE; error_code<=0; identifier<=0; decompress<=0;
            checksum_mode<=0; source_bytes<=0; destination_capacity<=0;
            payload_bytes<=0; source_segments<=0; destination_segments<=0;
            source_seen<=0; destination_seen<=0; source_sum<=0; destination_sum<=0;
            descriptor_bad<=0; source_index<=0; destination_index<=0;
            source_offset<=0; destination_offset<=0; read_address<=0; write_address<=0;
            read_pending<=0; write_pending<=0; input_valid<=0; output_valid<=0;
            input_data<=0; output_data<=0; input_index<=0; reads_consumed<=0;
            writes_acked<=0; content_count<=0; output_count<=0; input_done<=0;
            empty_sent<=0; codec_done<=0; checksum_finish_sent<=0;
            checksum_done<=0; computed_checksum<=0; expected_checksum<=0;
            trailer_received<=0; trailer_sent<=0;
        end else begin
            if (rd_take) read_pending<=1;
            if (wr_take) begin write_pending<=1; output_valid<=0; end
            if (rd_response) begin
                read_pending<=0;
                reads_consumed<=reads_consumed+1'b1;
                if (error_code==0 && fault==0) begin
                    input_valid<=1; input_data<=rd_data; input_index<=reads_consumed;
                end
                if (source_offset==source_size[source_index]-1'b1) begin
                    source_offset<=0;
                    if (source_index+1'b1<source_segments) begin
                        source_index<=source_index+1'b1;
                        read_address<=source_address[source_index+1'b1];
                    end
                end else begin
                    source_offset<=source_offset+1'b1;
                    read_address<=read_address+64'd1;
                end
            end
            if (wr_response) begin
                write_pending<=0;
                if (!wr_error) writes_acked<=writes_acked+1'b1;
                if (destination_offset==destination_size[destination_index]-1'b1) begin
                    destination_offset<=0;
                    if (destination_index+1'b1<destination_segments) begin
                        destination_index<=destination_index+1'b1;
                        write_address<=destination_address[destination_index+1'b1];
                    end
                end else begin
                    destination_offset<=destination_offset+1'b1;
                    write_address<=write_address+64'd1;
                end
            end
            if (finish_checksum && checksum_finish_ready) checksum_finish_sent<=1;
            if (checksum_finish_sent && checksum_result_valid) begin
                checksum_done<=1; computed_checksum<=checksum_result;
            end
            if (content_transfer) begin
                input_valid<=0; content_count<=content_count+1'b1;
                if (input_index==source_bytes-1'b1) input_done<=1;
            end
            if (empty_input && c_s_ready && fault==0) begin
                empty_sent<=1; input_done<=1;
            end
            if (payload_transfer) begin
                input_valid<=0;
                if (input_index==payload_bytes-1'b1) input_done<=1;
            end
            if (state==RUN && decompress && input_valid &&
                input_index>=payload_bytes && error_code==0 && fault==0) begin
                expected_checksum[trailer_received*8 +: 8]<=input_data;
                trailer_received<=trailer_received+1'b1;
                input_valid<=0;
            end
            if (output_transfer) begin
                output_data<=codec_output_data; output_valid<=1;
                output_count<=output_count+1'b1;
                if (decompress) content_count<=content_count+1'b1;
            end
            if (state==RUN && codec_status_valid) codec_done<=1;
            case (state)
                IDLE: if (cmd_valid && cmd_ready) begin
                    identifier<=cmd_id; decompress<=cmd_decompress;
                    checksum_mode<=cmd_checksum_mode; source_bytes<=cmd_src_bytes;
                    destination_capacity<=cmd_dst_capacity;
                    payload_bytes<=cmd_src_bytes-command_trailer;
                    source_segments<=cmd_src_segments; destination_segments<=cmd_dst_segments;
                    source_seen<=0; destination_seen<=0; source_sum<=0; destination_sum<=0;
                    descriptor_bad<=0; source_index<=0; destination_index<=0;
                    source_offset<=0; destination_offset<=0;
                    read_address<=0; write_address<=0;
                    read_pending<=0; write_pending<=0; input_valid<=0; output_valid<=0;
                    input_data<=0; output_data<=0; input_index<=0;
                    reads_consumed<=0; writes_acked<=0; content_count<=0; output_count<=0;
                    input_done<=0; empty_sent<=0; codec_done<=0;
                    checksum_finish_sent<=0; checksum_done<=0; computed_checksum<=0;
                    expected_checksum<=0; trailer_received<=0; trailer_sent<=0;
                    if (invalid_command) begin error_code<=8; state<=COMPLETE; end
                    else begin error_code<=0; state<=COLLECT; end
                end
                COLLECT: begin
                    if (source_accept) begin
                        source_seen<=source_seen+1'b1; source_sum<=next_source_sum;
                        if (sg_bytes==0 || segment_last_address[64] ||
                            next_source_sum>37'h0ffffffff) descriptor_bad<=1;
                    end
                    if (destination_accept) begin
                        destination_seen<=destination_seen+1'b1;
                        destination_sum<=next_destination_sum;
                        if (sg_bytes==0 || segment_last_address[64] ||
                            next_destination_sum>37'h0ffffffff) descriptor_bad<=1;
                    end
                    if (all_descriptors) state<=VALIDATE;
                end
                VALIDATE: begin
                    if (descriptor_bad || source_sum!={5'd0,source_bytes} ||
                        destination_sum!={5'd0,destination_capacity}) begin
                        error_code<=8; state<=COMPLETE;
                    end else state<=ARM;
                end
                ARM: begin
                    if (source_segments!=0) read_address<=source_address[0];
                    write_address<=destination_address[0];
                    state<=RUN;
                end
                RUN: begin
                    if (codec_done && reads_consumed==source_bytes && !input_valid &&
                        checksum_done) begin
                        if (decompress) begin
                            if (checksum_mode!=0 && computed_checksum!=expected_checksum) begin
                                error_code<=7;
                                output_valid<=0;
                            end
                            state<=SETTLE;
                        end else if (checksum_mode!=0) state<=TRAILER;
                        else state<=SETTLE;
                    end
                end
                TRAILER: begin
                    if (trailer_sent<4 && !output_valid && !write_pending &&
                        fault==0) begin
                        output_data<=computed_checksum[trailer_sent*8 +: 8];
                        output_valid<=1; output_count<=output_count+1'b1;
                        trailer_sent<=trailer_sent+1'b1;
                    end
                    if (trailer_sent==4 && !output_valid) state<=SETTLE;
                end
                SETTLE: begin
                    if ((!read_pending || rd_response) &&
                        (!write_pending || wr_response) && !output_valid &&
                        checksum_done) state<=COMPLETE;
                end
                COMPLETE: if (status_retire) state<=IDLE;
                default: state<=IDLE;
            endcase
            if (error_code==0 && fault!=0) begin
                error_code<=fault; state<=SETTLE; input_valid<=0; output_valid<=0;
            end
        end
    end
endmodule
