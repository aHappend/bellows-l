module bellows_l4_arbiter #(parameter integer WIDTH=69) (
    input wire clk, input wire rst_n, input wire admit,
    input wire [3:0] lane_valid,
    input wire [4*WIDTH-1:0] lane_payload,
    output wire [3:0] lane_take, output wire [3:0] lane_retire,
    output wire valid, output wire [1:0] channel,
    output wire [WIDTH-1:0] payload, input wire ready
);
    reg occupied;
    reg [3:0] owner, pointer;
    reg [4*WIDTH-1:0] held;
    wire [3:0] priority_0={
        lane_valid[3] && !(|lane_valid[2:0]),
        lane_valid[2] && !(|lane_valid[1:0]),
        lane_valid[1] && !lane_valid[0],
        lane_valid[0]};
    wire [3:0] priority_1={
        lane_valid[3] && !(|lane_valid[2:1]),
        lane_valid[2] && !lane_valid[1],
        lane_valid[1],
        lane_valid[0] && !(|lane_valid[3:1])};
    wire [3:0] priority_2={
        lane_valid[3] && !lane_valid[2],
        lane_valid[2],
        lane_valid[1] && !(|{lane_valid[3:2],lane_valid[0]}),
        lane_valid[0] && !(|lane_valid[3:2])};
    wire [3:0] priority_3={
        lane_valid[3],
        lane_valid[2] && !(|{lane_valid[3],lane_valid[1:0]}),
        lane_valid[1] && !(|{lane_valid[3],lane_valid[0]}),
        lane_valid[0] && !lane_valid[3]};
    wire [3:0] choice=(priority_0 & {4{pointer[0]}}) |
        (priority_1 & {4{pointer[1]}}) |
        (priority_2 & {4{pointer[2]}}) |
        (priority_3 & {4{pointer[3]}});
    wire found=|lane_valid;
    wire [3:0] selected_owner=occupied ? owner : choice;
    wire [WIDTH-1:0] selected_payload=
        ((lane_payload[0*WIDTH +: WIDTH] & {WIDTH{choice[0]}}) |
         (lane_payload[1*WIDTH +: WIDTH] & {WIDTH{choice[1]}})) |
        ((lane_payload[2*WIDTH +: WIDTH] & {WIDTH{choice[2]}}) |
         (lane_payload[3*WIDTH +: WIDTH] & {WIDTH{choice[3]}}));
    wire [WIDTH-1:0] held_payload=
        ((held[0*WIDTH +: WIDTH] & {WIDTH{owner[0]}}) |
         (held[1*WIDTH +: WIDTH] & {WIDTH{owner[1]}})) |
        ((held[2*WIDTH +: WIDTH] & {WIDTH{owner[2]}}) |
         (held[3*WIDTH +: WIDTH] & {WIDTH{owner[3]}}));
    wire offered=admit && !occupied && found;
    assign valid=rst_n && (occupied || offered);
    assign channel=valid ?
        {selected_owner[2] | selected_owner[3],
         selected_owner[1] | selected_owner[3]} : 2'd0;
    assign payload=valid ? (occupied ? held_payload : selected_payload) :
        {WIDTH{1'b0}};
    assign lane_take=rst_n && admit && !occupied && found ?
        choice : 4'd0;
    assign lane_retire=valid && ready ? selected_owner : 4'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            occupied<=0; owner<=0; pointer<=4'b0001; held<=0;
        end else begin
            // Snapshot every lane before reservation, outside the eligibility cone.
            if (!occupied) held<=lane_payload;
            if (admit && !occupied && found) begin
                owner<=choice;
                if (ready) begin
                    occupied<=0; pointer<={choice[2:0],choice[3]};
                end else begin
                    occupied<=1;
                end
            end else if (valid && ready) begin
                occupied<=0; pointer<={owner[2:0],owner[3]};
            end
        end
    end
endmodule

module bellows_l4_scheduler (
    input wire clk, input wire rst_n,
    input wire [3:0] lane_rd_valid, input wire [275:0] lane_rd_payload,
    output wire [3:0] lane_rd_take,
    output wire rd_valid, output wire [1:0] rd_channel,
    output wire [68:0] rd_payload, input wire rd_ready, input wire rd_available,
    input wire [3:0] lane_wr_valid, input wire [547:0] lane_wr_payload,
    output wire [3:0] lane_wr_take,
    output wire wr_valid, output wire [1:0] wr_channel,
    output wire [136:0] wr_payload, input wire wr_ready, input wire wr_available,
    input wire [3:0] lane_status_valid, input wire [463:0] lane_status_payload,
    output wire [3:0] lane_status_retire,
    output wire status_valid, output wire [1:0] status_channel,
    output wire [115:0] status_payload, input wire status_ready
);
    bellows_l4_arbiter #(.WIDTH(69)) read_arbiter (
        .clk(clk), .rst_n(rst_n), .admit(rd_available),
        .lane_valid(lane_rd_valid), .lane_payload(lane_rd_payload),
        .lane_take(lane_rd_take), .lane_retire(),
        .valid(rd_valid), .channel(rd_channel), .payload(rd_payload),
        .ready(rd_ready)
    );
    bellows_l4_arbiter #(.WIDTH(137)) write_arbiter (
        .clk(clk), .rst_n(rst_n), .admit(wr_available),
        .lane_valid(lane_wr_valid), .lane_payload(lane_wr_payload),
        .lane_take(lane_wr_take), .lane_retire(),
        .valid(wr_valid), .channel(wr_channel), .payload(wr_payload),
        .ready(wr_ready)
    );
    bellows_l4_arbiter #(.WIDTH(116)) completion_arbiter (
        .clk(clk), .rst_n(rst_n), .admit(1'b1),
        .lane_valid(lane_status_valid), .lane_payload(lane_status_payload),
        .lane_take(), .lane_retire(lane_status_retire),
        .valid(status_valid), .channel(status_channel), .payload(status_payload),
        .ready(status_ready)
    );
endmodule
