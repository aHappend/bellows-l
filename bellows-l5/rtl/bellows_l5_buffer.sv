module bellows_l5_buffer #(
    parameter integer BYTES=65536
) (
    input wire clk, input wire rst_n,
    input wire we, input wire [31:0] waddr, input wire [7:0] wdata,
    input wire a_en, input wire [31:0] a_addr,
    output wire a_valid, output wire [7:0] a_data,
    input wire b_en, input wire [31:0] b_addr,
    output wire b_valid, output wire [7:0] b_data
);
    localparam integer ADDR_BITS=BYTES>1 ? $clog2(BYTES) : 1;
    wire write_en=rst_n && we && waddr<BYTES;
    wire [7:0] a_q, b_q;
    reg av, bv;
    genvar lane;
    generate
        for (lane=0;lane<2;lane=lane+1) begin : views
            wire [7:0] q;
            wire re=lane==0 ? a_en : b_en;
            wire [31:0] addr=lane==0 ? a_addr : b_addr;
            bellows_byte_ram #(.DEPTH(BYTES), .ADDR_BITS(ADDR_BITS)) storage (
                .clk(clk),
                .write_en(write_en), .write_addr(waddr[ADDR_BITS-1:0]),
                .write_data(wdata),
                .read_en(rst_n && re && addr<BYTES),
                .read_addr(addr[ADDR_BITS-1:0]), .read_data(q)
            );
            if (lane==0) assign a_q=q;
            else assign b_q=q;
        end
    endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin av<=0; bv<=0; end
        else begin av<=a_en && a_addr<BYTES; bv<=b_en && b_addr<BYTES; end
    end
    assign a_valid=rst_n && av;
    assign b_valid=rst_n && bv;
    assign a_data=a_valid ? a_q : 8'd0;
    assign b_data=b_valid ? b_q : 8'd0;
endmodule
