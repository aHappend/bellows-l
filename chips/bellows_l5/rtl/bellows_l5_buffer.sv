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
    wire [7:0] a_q, b_q;
    reg av, bv;
    genvar lane;
    generate
        for (lane=0;lane<2;lane=lane+1) begin : views
            (* ramstyle="M20K", nomem2reg *) reg [7:0] image [0:BYTES-1];
            reg [7:0] q;
            wire re=lane==0 ? a_en : b_en;
            wire [31:0] addr=lane==0 ? a_addr : b_addr;
            always @(posedge clk) begin
                if (rst_n && we && waddr<BYTES) image[waddr]<=wdata;
                if (rst_n && re && addr<BYTES) q<=image[addr];
            end
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
