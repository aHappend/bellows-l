module bellows_l1_history (
    input  wire        clk,
    input  wire        write_en,
    input  wire [15:0] write_addr,
    input  wire [7:0]  write_data,
    input  wire        read_en,
    input  wire [15:0] read_addr,
    output logic [7:0] read_data
);
    // The parser alternates dependent reads and writes; no collision is used.
    (* ramstyle = "M20K, no_rw_check" *) logic [7:0] memory [0:65535];
    always_ff @(posedge clk) begin
        if (write_en)
            memory[write_addr] <= write_data;
        if (read_en)
            read_data <= memory[read_addr];
    end
endmodule
