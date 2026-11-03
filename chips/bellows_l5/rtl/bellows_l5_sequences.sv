module bellows_l5_sequences #(
    parameter integer DEPTH=16385
) (
    input wire clk, input wire rst_n,
    input wire we, input wire [16:0] waddr,
    input wire [23:0] wll, input wire [23:0] wml, input wire [23:0] wof,
    input wire re, input wire [16:0] raddr,
    output wire valid,
    output wire [23:0] ll, output wire [23:0] ml, output wire [23:0] of_value
);
    localparam integer ADDR_BITS=DEPTH>1 ? $clog2(DEPTH) : 1;
    wire write_en=rst_n && we && waddr<DEPTH;
    wire read_en=rst_n && re && raddr<DEPTH;
    wire [71:0] write_data={wof,wml,wll};
    wire [71:0] read_data;
    reg valid_q;
    genvar lane;
    generate
        for (lane=0;lane<9;lane=lane+1) begin : bytes
            wire [7:0] q;
            bellows_byte_ram #(.DEPTH(DEPTH), .ADDR_BITS(ADDR_BITS)) storage (
                .clk(clk),
                .write_en(write_en), .write_addr(waddr[ADDR_BITS-1:0]),
                .write_data(write_data[lane*8 +: 8]),
                .read_en(read_en), .read_addr(raddr[ADDR_BITS-1:0]),
                .read_data(q)
            );
            assign read_data[lane*8 +: 8]=q;
        end
    endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid_q<=0;
        else valid_q<=re && raddr<DEPTH;
    end
    assign valid=rst_n && valid_q;
    assign {of_value,ml,ll}=valid ? read_data : 72'd0;
endmodule
