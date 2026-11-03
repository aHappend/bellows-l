module bellows_l5_context #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer SG_DEPTH=16,
    parameter integer COPY_BYTES=8,
    parameter integer DICT_BYTES=16384
) (
    input wire clk, input wire rst_n,
    input wire cmd_valid, output wire cmd_ready,
    input wire [15:0] cmd_id, input wire cmd_decompress,
    input wire cmd_wide, input wire [2:0] cmd_codec,
    input wire [1:0] cmd_checksum_mode,
    input wire [31:0] cmd_src_bytes, input wire [31:0] cmd_dst_capacity,
    input wire [4:0] cmd_src_segments, input wire [4:0] cmd_dst_segments,
    input wire [31:0] cmd_dict_id,
    input wire dict_loaded, input wire [31:0] dict_id,
    input wire [14:0] dict_size,
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
    input wire status_retire, output wire idle
);
    reg awake, occupied, selected_zstd;
    wire route=cmd_codec==5 || cmd_codec==6;
    wire [1:0] c_ready, s_ready, r_valid, w_valid, c_valid;
    wire [137:0] r_payload;
    wire [273:0] w_payload;
    wire [231:0] c_payload;
    wire accept=cmd_valid && cmd_ready;
    assign idle=rst_n && awake && !occupied;
    assign cmd_ready=idle && c_ready[route];
    assign sg_ready=rst_n && occupied && s_ready[selected_zstd];
    assign rd_valid=rst_n && occupied && r_valid[selected_zstd];
    assign rd_payload=rd_valid ? r_payload[selected_zstd*69 +: 69] : 69'd0;
    assign wr_valid=rst_n && occupied && w_valid[selected_zstd];
    assign wr_payload=wr_valid ? w_payload[selected_zstd*137 +: 137] : 137'd0;
    assign status_valid=rst_n && occupied && c_valid[selected_zstd];
    assign status_payload=status_valid ? c_payload[selected_zstd*116 +: 116] : 116'd0;
    bellows_l4_context #(
        .MAX_BLOCK_BYTES(MAX_BLOCK_BYTES), .SG_DEPTH(SG_DEPTH), .COPY_BYTES(COPY_BYTES)
    ) legacy (
        .clk(clk), .rst_n(rst_n), .cmd_valid(accept && !route), .cmd_ready(c_ready[0]),
        .cmd_id(cmd_id), .cmd_decompress(cmd_decompress), .cmd_wide(cmd_wide),
        .cmd_codec(cmd_codec), .cmd_checksum_mode(cmd_checksum_mode),
        .cmd_src_bytes(cmd_src_bytes), .cmd_dst_capacity(cmd_dst_capacity),
        .cmd_src_segments(cmd_src_segments), .cmd_dst_segments(cmd_dst_segments),
        .sg_valid(sg_valid && occupied && !selected_zstd), .sg_ready(s_ready[0]),
        .sg_destination(sg_destination), .sg_addr(sg_addr), .sg_bytes(sg_bytes),
        .rd_valid(r_valid[0]), .rd_payload(r_payload[0 +: 69]),
        .rd_take(rd_take && occupied && !selected_zstd),
        .rd_response(rd_response && occupied && !selected_zstd),
        .rd_data(rd_data), .rd_count(rd_count), .rd_error(rd_error),
        .wr_valid(w_valid[0]), .wr_payload(w_payload[0 +: 137]),
        .wr_take(wr_take && occupied && !selected_zstd),
        .wr_response(wr_response && occupied && !selected_zstd),
        .wr_count(wr_count), .wr_error(wr_error),
        .status_valid(c_valid[0]), .status_payload(c_payload[0 +: 116]),
        .status_retire(status_retire && occupied && !selected_zstd)
    );
    bellows_l5_zstd_context #(
        .MAX_BLOCK_BYTES(MAX_BLOCK_BYTES), .SG_DEPTH(SG_DEPTH),
        .COPY_BYTES(COPY_BYTES), .DICT_BYTES(DICT_BYTES)
    ) zstd (
        .clk(clk), .rst_n(rst_n), .cmd_valid(accept && route), .cmd_ready(c_ready[1]),
        .cmd_id(cmd_id), .cmd_decompress(cmd_decompress), .cmd_wide(cmd_wide),
        .cmd_checksum_mode(cmd_checksum_mode),
        .cmd_src_bytes(cmd_src_bytes), .cmd_dst_capacity(cmd_dst_capacity),
        .cmd_src_segments(cmd_src_segments), .cmd_dst_segments(cmd_dst_segments),
        .cmd_use_dictionary(cmd_codec==6),
        .cmd_dictionary_ok(dict_loaded && cmd_dict_id==dict_id),
        .dictionary_bytes(dict_size),
        .dict_rd_en(dict_rd_en), .dict_rd_addr(dict_rd_addr),
        .dict_rd_valid(dict_rd_valid), .dict_rd_data(dict_rd_data),
        .dict_index_en(dict_index_en), .dict_index_chain(dict_index_chain),
        .dict_index_addr(dict_index_addr),
        .dict_index_valid(dict_index_valid), .dict_index_found(dict_index_found),
        .dict_index_position(dict_index_position),
        .sg_valid(sg_valid && occupied && selected_zstd), .sg_ready(s_ready[1]),
        .sg_destination(sg_destination), .sg_addr(sg_addr), .sg_bytes(sg_bytes),
        .rd_valid(r_valid[1]), .rd_payload(r_payload[69 +: 69]),
        .rd_take(rd_take && occupied && selected_zstd),
        .rd_response(rd_response && occupied && selected_zstd),
        .rd_data(rd_data), .rd_count(rd_count), .rd_error(rd_error),
        .wr_valid(w_valid[1]), .wr_payload(w_payload[137 +: 137]),
        .wr_take(wr_take && occupied && selected_zstd),
        .wr_response(wr_response && occupied && selected_zstd),
        .wr_count(wr_count), .wr_error(wr_error),
        .status_valid(c_valid[1]), .status_payload(c_payload[116 +: 116]),
        .status_retire(status_retire && occupied && selected_zstd)
    );
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin awake<=0; occupied<=0; selected_zstd<=0; end
        else begin
            awake<=1;
            if (accept) begin occupied<=1; selected_zstd<=route; end
            if (status_valid && status_retire) occupied<=0;
        end
    end
endmodule
