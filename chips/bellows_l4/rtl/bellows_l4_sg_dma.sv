module bellows_l4_sg_dma (
    input wire clk, input wire rst_n,
    input wire read_valid, input wire [1:0] read_channel,
    input wire [68:0] read_payload,
    output wire read_ready, output wire read_available,
    input wire write_valid, input wire [1:0] write_channel,
    input wire [136:0] write_payload,
    output wire write_ready, output wire write_available,
    output wire [3:0] lane_read_response,
    output wire [63:0] lane_read_data, output wire [3:0] lane_read_count,
    output wire lane_read_error,
    output wire [3:0] lane_write_response, output wire [3:0] lane_write_count,
    output wire lane_write_error,
    output wire rd_req_valid, output wire [1:0] rd_req_channel,
    output wire [63:0] rd_req_addr, input wire rd_req_ready,
    input wire rd_rsp_valid, input wire [7:0] rd_rsp_data,
    input wire rd_rsp_error, output wire rd_rsp_ready,
    output wire wr_req_valid, output wire [1:0] wr_req_channel,
    output wire [63:0] wr_req_addr, output wire [7:0] wr_req_data,
    input wire wr_req_ready, input wire wr_rsp_valid,
    input wire wr_rsp_error, output wire wr_rsp_ready,
    output wire w_rd_req_valid, output wire [1:0] w_rd_req_channel,
    output wire [63:0] w_rd_req_addr, output wire [3:0] w_rd_req_bytes,
    input wire w_rd_req_ready,
    input wire w_rd_rsp_valid, input wire [63:0] w_rd_rsp_data,
    input wire w_rd_rsp_error, output wire w_rd_rsp_ready,
    output wire w_wr_req_valid, output wire [1:0] w_wr_req_channel,
    output wire [63:0] w_wr_req_addr, output wire [63:0] w_wr_req_data,
    output wire [7:0] w_wr_req_strb, input wire w_wr_req_ready,
    input wire w_wr_rsp_valid, input wire w_wr_rsp_error,
    output wire w_wr_rsp_ready
);
    reg read_pending, write_pending, read_wide, write_wide;
    reg [1:0] read_owner, write_owner;
    reg [3:0] read_count, write_count;
    wire selected_read_wide=read_payload[68];
    wire selected_write_wide=write_payload[136];
    wire request_read=rst_n && !read_pending && read_valid;
    wire request_write=rst_n && !write_pending && write_valid;
    wire accept_read=read_valid && read_ready;
    wire accept_write=write_valid && write_ready;
    wire response_read=rst_n && read_pending &&
        (read_wide ? w_rd_rsp_valid : rd_rsp_valid);
    wire response_write=rst_n && write_pending &&
        (write_wide ? w_wr_rsp_valid : wr_rsp_valid);
    wire [63:0] response_data=read_wide ? w_rd_rsp_data : {56'd0,rd_rsp_data};
    reg [63:0] masked_data;
    reg [3:0] requested_write_count;
    integer i;
    always @* begin
        masked_data=0; requested_write_count=0;
        for (i=0;i<8;i=i+1) begin
            if (i<read_count) masked_data[i*8 +: 8]=response_data[i*8 +: 8];
            requested_write_count=requested_write_count+{3'd0,write_payload[i]};
        end
    end

    assign read_available=rst_n && !read_pending;
    assign write_available=rst_n && !write_pending;
    assign read_ready=rst_n && !read_pending &&
        (selected_read_wide ? w_rd_req_ready : rd_req_ready);
    assign write_ready=rst_n && !write_pending &&
        (selected_write_wide ? w_wr_req_ready : wr_req_ready);
    assign rd_req_valid=request_read && !selected_read_wide;
    assign rd_req_channel=rd_req_valid ? read_channel : 2'd0;
    assign rd_req_addr=rd_req_valid ? read_payload[67:4] : 64'd0;
    assign w_rd_req_valid=request_read && selected_read_wide;
    assign w_rd_req_channel=w_rd_req_valid ? read_channel : 2'd0;
    assign w_rd_req_addr=w_rd_req_valid ? read_payload[67:4] : 64'd0;
    assign w_rd_req_bytes=w_rd_req_valid ? read_payload[3:0] : 4'd0;
    assign rd_rsp_ready=rst_n && read_pending && !read_wide;
    assign w_rd_rsp_ready=rst_n && read_pending && read_wide;
    assign lane_read_response=response_read ? (4'b0001<<read_owner) : 4'd0;
    assign lane_read_data=response_read ? masked_data : 64'd0;
    assign lane_read_count=response_read ? read_count : 4'd0;
    assign lane_read_error=response_read && (read_wide ? w_rd_rsp_error : rd_rsp_error);

    assign wr_req_valid=request_write && !selected_write_wide;
    assign wr_req_channel=wr_req_valid ? write_channel : 2'd0;
    assign wr_req_addr=wr_req_valid ? write_payload[135:72] : 64'd0;
    assign wr_req_data=wr_req_valid ? write_payload[15:8] : 8'd0;
    assign w_wr_req_valid=request_write && selected_write_wide;
    assign w_wr_req_channel=w_wr_req_valid ? write_channel : 2'd0;
    assign w_wr_req_addr=w_wr_req_valid ? write_payload[135:72] : 64'd0;
    assign w_wr_req_data=w_wr_req_valid ? write_payload[71:8] : 64'd0;
    assign w_wr_req_strb=w_wr_req_valid ? write_payload[7:0] : 8'd0;
    assign wr_rsp_ready=rst_n && write_pending && !write_wide;
    assign w_wr_rsp_ready=rst_n && write_pending && write_wide;
    assign lane_write_response=response_write ? (4'b0001<<write_owner) : 4'd0;
    assign lane_write_count=response_write ? write_count : 4'd0;
    assign lane_write_error=response_write && (write_wide ? w_wr_rsp_error : wr_rsp_error);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_pending<=0; write_pending<=0; read_wide<=0; write_wide<=0;
            read_owner<=0; write_owner<=0; read_count<=0; write_count<=0;
        end else begin
            if (accept_read) begin
                read_pending<=1; read_owner<=read_channel;
                read_wide<=selected_read_wide;
                read_count<=selected_read_wide ? read_payload[3:0] : 4'd1;
            end
            if (response_read) read_pending<=0;
            if (accept_write) begin
                write_pending<=1; write_owner<=write_channel;
                write_wide<=selected_write_wide;
                write_count<=selected_write_wide ? requested_write_count : 4'd1;
            end
            if (response_write) write_pending<=0;
        end
    end
endmodule
