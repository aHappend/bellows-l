module bellows_l2_literal_buffer #(
    parameter integer MAX_BLOCK_BYTES = 65536
) (
    input wire clk,
    input wire rst_n,
    input wire write_en,
    input wire [15:0] write_addr,
    input wire [7:0] write_data,
    input wire a_en,
    input wire [15:0] a_addr,
    output reg [7:0] a_data,
    input wire b_en,
    input wire [15:0] b_addr,
    output reg [7:0] b_data
);
    localparam integer STORAGE_BYTES =
        (MAX_BLOCK_BYTES >= 1 && MAX_BLOCK_BYTES <= 65536) ?
        MAX_BLOCK_BYTES : 1;
    (* ramstyle = "M20K", nomem2reg *)
    reg [7:0] memory [0:STORAGE_BYTES-1];

    generate
        if (MAX_BLOCK_BYTES < 1 || MAX_BLOCK_BYTES > 65536) begin : invalid_parameter
            initial $fatal(1, "PARAMETER ERROR: MAX_BLOCK_BYTES must be 1..65536");
        end
    endgenerate

    always @(posedge clk) begin
        if (rst_n && write_en)
            memory[write_addr] <= write_data;
        if (rst_n && a_en)
            a_data <= memory[a_addr];
        if (rst_n && b_en)
            b_data <= memory[b_addr];
    end
endmodule
