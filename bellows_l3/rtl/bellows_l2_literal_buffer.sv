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
    output wire [7:0] a_data,
    input wire b_en,
    input wire [15:0] b_addr,
    output wire [7:0] b_data
);
    localparam integer STORAGE_BYTES =
        (MAX_BLOCK_BYTES >= 1 && MAX_BLOCK_BYTES <= 65536) ?
        MAX_BLOCK_BYTES : 1;
    (* ramstyle = "M20K", nomem2reg *)
    reg [7:0] memory [0:STORAGE_BYTES-1];
    reg [7:0] a_read, b_read;
    reg a_valid, b_valid;
    assign a_data = rst_n && a_valid ? a_read : 8'd0;
    assign b_data = rst_n && b_valid ? b_read : 8'd0;

    generate
        if (MAX_BLOCK_BYTES < 1 || MAX_BLOCK_BYTES > 65536) begin : invalid_parameter
            initial $fatal(1, "PARAMETER ERROR: MAX_BLOCK_BYTES must be 1..65536");
        end
    endgenerate

    always @(posedge clk) begin
        if (rst_n && write_en)
            memory[write_addr] <= write_data;
        if (rst_n && a_en)
            a_read <= memory[a_addr];
        if (rst_n && b_en)
            b_read <= memory[b_addr];
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin a_valid<=0; b_valid<=0; end
        else begin
            if (a_en) a_valid<=1;
            if (b_en) b_valid<=1;
        end
    end
endmodule
