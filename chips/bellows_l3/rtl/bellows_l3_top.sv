module bellows_l3_top #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer SG_DEPTH=16
) (
    input wire clk, input wire rst_n,
    input wire cmd_valid, input wire [1:0] cmd_channel,
    input wire [15:0] cmd_id, input wire cmd_decompress,
    input wire [1:0] cmd_checksum_mode,
    input wire [31:0] cmd_src_bytes, input wire [31:0] cmd_dst_capacity,
    input wire [4:0] cmd_src_segments, input wire [4:0] cmd_dst_segments,
    output wire cmd_ready,
    input wire sg_valid, input wire [1:0] sg_channel, input wire sg_destination,
    input wire [63:0] sg_addr, input wire [31:0] sg_bytes, output wire sg_ready,
    output wire rd_req_valid, output wire [1:0] rd_req_channel,
    output wire [63:0] rd_req_addr, input wire rd_req_ready,
    input wire rd_rsp_valid, input wire [7:0] rd_rsp_data,
    input wire rd_rsp_error, output wire rd_rsp_ready,
    output wire wr_req_valid, output wire [1:0] wr_req_channel,
    output wire [63:0] wr_req_addr, output wire [7:0] wr_req_data,
    input wire wr_req_ready, input wire wr_rsp_valid,
    input wire wr_rsp_error, output wire wr_rsp_ready,
    output wire status_valid, output wire [1:0] status_channel,
    output wire [15:0] status_id, output wire [3:0] status_error,
    output wire [31:0] status_src_bytes, output wire [31:0] status_dst_bytes,
    output wire [31:0] status_checksum, output wire err_checksum_mismatch,
    input wire status_ready
);
    localparam integer LEGAL=MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536 &&
                             SG_DEPTH>=1 && SG_DEPTH<=16;
    localparam integer SAFE_BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer SAFE_SG=LEGAL ? SG_DEPTH : 1;
    wire [3:0] lane_cmd_ready, lane_sg_ready;
    wire [3:0] lane_rd_valid, lane_rd_take, lane_read_response;
    wire [3:0] lane_wr_valid, lane_wr_take, lane_write_response;
    wire [255:0] lane_rd_addr;
    wire [287:0] lane_wr_payload;
    wire [3:0] lane_status_valid, lane_status_retire;
    wire [463:0] lane_status_payload;
    wire [7:0] lane_read_data;
    wire lane_read_error, lane_write_error;
    wire read_valid, read_ready, write_valid, write_ready;
    wire [1:0] read_channel, write_channel;
    wire [63:0] read_addr;
    wire [71:0] write_payload;
    wire [115:0] completion_payload;
    assign cmd_ready=rst_n && LEGAL && lane_cmd_ready[cmd_channel];
    assign sg_ready=rst_n && LEGAL && lane_sg_ready[sg_channel];
    assign {status_id,status_error,status_src_bytes,status_dst_bytes,status_checksum}=
        completion_payload;
    assign err_checksum_mismatch=status_valid && status_error==4'd7;
    genvar lane;
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1, "PARAMETER ERROR: MAX_BLOCK_BYTES=1..65536, SG_DEPTH=1..16");
        end
        for (lane=0;lane<4;lane=lane+1) begin : lanes
            localparam integer INDEX=lane;
            bellows_l3_context #(.MAX_BLOCK_BYTES(SAFE_BLOCK),.SG_DEPTH(SAFE_SG)) \context (
                .clk(clk), .rst_n(rst_n),
                .cmd_valid(cmd_valid && LEGAL && cmd_channel==INDEX),
                .cmd_ready(lane_cmd_ready[INDEX]), .cmd_id(cmd_id),
                .cmd_decompress(cmd_decompress), .cmd_checksum_mode(cmd_checksum_mode),
                .cmd_src_bytes(cmd_src_bytes), .cmd_dst_capacity(cmd_dst_capacity),
                .cmd_src_segments(cmd_src_segments), .cmd_dst_segments(cmd_dst_segments),
                .sg_valid(sg_valid && LEGAL && sg_channel==INDEX),
                .sg_ready(lane_sg_ready[INDEX]),
                .sg_destination(sg_destination), .sg_addr(sg_addr), .sg_bytes(sg_bytes),
                .rd_valid(lane_rd_valid[INDEX]), .rd_addr(lane_rd_addr[INDEX*64 +: 64]),
                .rd_take(lane_rd_take[INDEX]), .rd_response(lane_read_response[INDEX]),
                .rd_data(lane_read_data), .rd_error(lane_read_error),
                .wr_valid(lane_wr_valid[INDEX]), .wr_payload(lane_wr_payload[INDEX*72 +: 72]),
                .wr_take(lane_wr_take[INDEX]), .wr_response(lane_write_response[INDEX]),
                .wr_error(lane_write_error), .status_valid(lane_status_valid[INDEX]),
                .status_payload(lane_status_payload[INDEX*116 +: 116]),
                .status_retire(lane_status_retire[INDEX])
            );
        end
    endgenerate
    bellows_l3_scheduler scheduler (
        .clk(clk), .rst_n(rst_n),
        .lane_rd_valid(lane_rd_valid), .lane_rd_addr(lane_rd_addr),
        .lane_rd_take(lane_rd_take), .rd_valid(read_valid),
        .rd_channel(read_channel), .rd_addr(read_addr), .rd_ready(read_ready),
        .lane_wr_valid(lane_wr_valid), .lane_wr_payload(lane_wr_payload),
        .lane_wr_take(lane_wr_take), .wr_valid(write_valid),
        .wr_channel(write_channel), .wr_payload(write_payload), .wr_ready(write_ready),
        .lane_status_valid(lane_status_valid), .lane_status_payload(lane_status_payload),
        .lane_status_retire(lane_status_retire), .status_valid(status_valid),
        .status_channel(status_channel), .status_payload(completion_payload),
        .status_ready(status_ready)
    );
    bellows_l3_sg_dma dma (
        .clk(clk), .rst_n(rst_n),
        .read_valid(read_valid), .read_channel(read_channel),
        .read_addr(read_addr), .read_ready(read_ready),
        .write_valid(write_valid), .write_channel(write_channel),
        .write_payload(write_payload), .write_ready(write_ready),
        .lane_read_response(lane_read_response), .lane_read_data(lane_read_data),
        .lane_read_error(lane_read_error), .lane_write_response(lane_write_response),
        .lane_write_error(lane_write_error),
        .rd_req_valid(rd_req_valid), .rd_req_channel(rd_req_channel),
        .rd_req_addr(rd_req_addr), .rd_req_ready(rd_req_ready),
        .rd_rsp_valid(rd_rsp_valid), .rd_rsp_data(rd_rsp_data),
        .rd_rsp_error(rd_rsp_error), .rd_rsp_ready(rd_rsp_ready),
        .wr_req_valid(wr_req_valid), .wr_req_channel(wr_req_channel),
        .wr_req_addr(wr_req_addr), .wr_req_data(wr_req_data), .wr_req_ready(wr_req_ready),
        .wr_rsp_valid(wr_rsp_valid), .wr_rsp_error(wr_rsp_error), .wr_rsp_ready(wr_rsp_ready)
    );
endmodule
