module bellows_l3_arbiter #(parameter integer WIDTH=64) (
    input wire clk, input wire rst_n, input wire admit,
    input wire [3:0] lane_valid,
    input wire [4*WIDTH-1:0] lane_payload,
    output wire [3:0] lane_take, output wire [3:0] lane_retire,
    output wire valid, output wire [1:0] channel,
    output wire [WIDTH-1:0] payload, input wire ready
);
    reg occupied;
    reg [1:0] owner, pointer;
    reg [WIDTH-1:0] held;
    reg found;
    reg [1:0] choice, index;
    integer i;
    always @* begin
        found=0; choice=0; index=0;
        for (i=0;i<4;i=i+1) begin
            index=pointer+i;
            if (!found && lane_valid[index]) begin found=1; choice=index; end
        end
    end
    assign valid=rst_n && occupied;
    assign channel=valid ? owner : 2'd0;
    assign payload=valid ? held : {WIDTH{1'b0}};
    assign lane_take=rst_n && admit && !occupied && found ? (4'b0001<<choice) : 4'd0;
    assign lane_retire=valid && ready ? (4'b0001<<owner) : 4'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin occupied<=0; owner<=0; pointer<=0; held<=0; end
        else begin
            if (admit && !occupied && found) begin
                occupied<=1; owner<=choice;
                held<=lane_payload[choice*WIDTH +: WIDTH];
            end else if (valid && ready) begin
                occupied<=0; pointer<=owner+2'd1;
            end
        end
    end
endmodule

module bellows_l3_scheduler (
    input wire clk, input wire rst_n,
    input wire [3:0] lane_rd_valid, input wire [255:0] lane_rd_addr,
    output wire [3:0] lane_rd_take,
    output wire rd_valid, output wire [1:0] rd_channel,
    output wire [63:0] rd_addr, input wire rd_ready, input wire rd_available,
    input wire [3:0] lane_wr_valid, input wire [287:0] lane_wr_payload,
    output wire [3:0] lane_wr_take,
    output wire wr_valid, output wire [1:0] wr_channel,
    output wire [71:0] wr_payload, input wire wr_ready, input wire wr_available,
    input wire [3:0] lane_status_valid, input wire [463:0] lane_status_payload,
    output wire [3:0] lane_status_retire,
    output wire status_valid, output wire [1:0] status_channel,
    output wire [115:0] status_payload, input wire status_ready
);
    bellows_l3_arbiter #(.WIDTH(64)) read_arbiter (
        .clk(clk), .rst_n(rst_n), .admit(rd_available), .lane_valid(lane_rd_valid),
        .lane_payload(lane_rd_addr), .lane_take(lane_rd_take), .lane_retire(),
        .valid(rd_valid), .channel(rd_channel), .payload(rd_addr), .ready(rd_ready)
    );
    bellows_l3_arbiter #(.WIDTH(72)) write_arbiter (
        .clk(clk), .rst_n(rst_n), .admit(wr_available), .lane_valid(lane_wr_valid),
        .lane_payload(lane_wr_payload), .lane_take(lane_wr_take), .lane_retire(),
        .valid(wr_valid), .channel(wr_channel), .payload(wr_payload), .ready(wr_ready)
    );
    bellows_l3_arbiter #(.WIDTH(116)) completion_arbiter (
        .clk(clk), .rst_n(rst_n), .admit(1'b1), .lane_valid(lane_status_valid),
        .lane_payload(lane_status_payload), .lane_take(), .lane_retire(lane_status_retire),
        .valid(status_valid), .channel(status_channel), .payload(status_payload),
        .ready(status_ready)
    );
endmodule
