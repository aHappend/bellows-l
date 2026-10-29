module bellows_l3_sg_dma (
    input wire clk, input wire rst_n,
    input wire read_valid, input wire [1:0] read_channel,
    input wire [63:0] read_addr, output wire read_ready,
    input wire write_valid, input wire [1:0] write_channel,
    input wire [71:0] write_payload, output wire write_ready,
    output wire [3:0] lane_read_response,
    output wire [7:0] lane_read_data, output wire lane_read_error,
    output wire [3:0] lane_write_response, output wire lane_write_error,
    output wire rd_req_valid, output wire [1:0] rd_req_channel,
    output wire [63:0] rd_req_addr, input wire rd_req_ready,
    input wire rd_rsp_valid, input wire [7:0] rd_rsp_data,
    input wire rd_rsp_error, output wire rd_rsp_ready,
    output wire wr_req_valid, output wire [1:0] wr_req_channel,
    output wire [63:0] wr_req_addr, output wire [7:0] wr_req_data,
    input wire wr_req_ready, input wire wr_rsp_valid,
    input wire wr_rsp_error, output wire wr_rsp_ready
);
    reg read_pending, write_pending;
    reg [1:0] read_owner, write_owner;
    assign rd_req_valid=rst_n && !read_pending && read_valid;
    assign rd_req_channel=rd_req_valid ? read_channel : 2'd0;
    assign rd_req_addr=rd_req_valid ? read_addr : 64'd0;
    assign read_ready=rst_n && !read_pending && rd_req_ready;
    assign rd_rsp_ready=rst_n && read_pending;
    assign lane_read_response=rd_rsp_valid && rd_rsp_ready ?
        (4'b0001<<read_owner) : 4'd0;
    assign lane_read_data=rst_n ? rd_rsp_data : 8'd0;
    assign lane_read_error=rst_n && rd_rsp_error;
    assign wr_req_valid=rst_n && !write_pending && write_valid;
    assign wr_req_channel=wr_req_valid ? write_channel : 2'd0;
    assign wr_req_addr=wr_req_valid ? write_payload[71:8] : 64'd0;
    assign wr_req_data=wr_req_valid ? write_payload[7:0] : 8'd0;
    assign write_ready=rst_n && !write_pending && wr_req_ready;
    assign wr_rsp_ready=rst_n && write_pending;
    assign lane_write_response=wr_rsp_valid && wr_rsp_ready ?
        (4'b0001<<write_owner) : 4'd0;
    assign lane_write_error=rst_n && wr_rsp_error;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_pending<=0; write_pending<=0; read_owner<=0; write_owner<=0;
        end else begin
            if (rd_req_valid && rd_req_ready) begin
                read_pending<=1; read_owner<=read_channel;
            end
            if (rd_rsp_valid && rd_rsp_ready) read_pending<=0;
            if (wr_req_valid && wr_req_ready) begin
                write_pending<=1; write_owner<=write_channel;
            end
            if (wr_rsp_valid && wr_rsp_ready) write_pending<=0;
        end
    end
endmodule
