module bellows_l1_history (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        write_en,
    input  wire [15:0] write_addr,
    input  wire [7:0]  write_data,
    input  wire        read_en,
    input  wire [15:0] read_addr,
    output wire [7:0]  read_data
);
    (* ramstyle = "M20K", nomem2reg *) reg [7:0] memory [0:65535];
    reg [7:0] memory_read;
    reg read_valid;
    assign read_data = rst_n && read_valid ? memory_read : 8'd0;

    // The array is deliberately not reset, allowing block-memory inference.
    always @(posedge clk) begin
        if (rst_n && write_en)
            memory[write_addr] <= write_data;
        if (rst_n && read_en)
            memory_read <= memory[read_addr];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            read_valid <= 1'b0;
        else if (read_en)
            read_valid <= 1'b1;
    end
endmodule
