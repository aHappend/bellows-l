module bellows_l1_history (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        write_en,
    input  wire [15:0] write_addr,
    input  wire [7:0]  write_data,
    input  wire        read_en,
    input  wire [15:0] read_addr,
    output reg  [7:0]  read_data
);
    reg [7:0] memory [0:65535];

    // The array is deliberately not reset, allowing block-memory inference.
    always @(posedge clk) begin
        if (rst_n && write_en)
            memory[write_addr] <= write_data;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            read_data <= 8'd0;
        else if (read_en)
            read_data <= memory[read_addr];
    end
endmodule
