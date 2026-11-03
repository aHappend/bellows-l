module bellows_byte_ram #(
    parameter integer DEPTH=1,
    parameter integer ADDR_BITS=DEPTH>1 ? $clog2(DEPTH) : 1
) (
    input wire clk,
    input wire write_en,
    input wire [ADDR_BITS-1:0] write_addr,
    input wire [7:0] write_data,
    input wire read_en,
    input wire [ADDR_BITS-1:0] read_addr,
    output reg [7:0] read_data
);
    (* ramstyle="M20K", nomem2reg *) reg [7:0] memory [0:DEPTH-1];

    // Nonblocking accesses retain old data on a same-address collision.
    always @(posedge clk) begin
        if (write_en)
            memory[write_addr]<=write_data;
        if (read_en)
            read_data<=memory[read_addr];
    end
endmodule
