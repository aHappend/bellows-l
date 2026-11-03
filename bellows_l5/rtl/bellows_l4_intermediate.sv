module bellows_l4_intermediate #(
    parameter integer MAX_BLOCK_BYTES=65536
) (
    input wire clk, input wire rst_n, input wire clear,
    input wire write_valid, input wire [31:0] write_index,
    input wire [7:0] write_data,
    input wire read_valid, output wire read_ready,
    input wire [31:0] read_index, input wire [3:0] read_count,
    output wire m_valid, input wire m_ready,
    output reg [63:0] m_data, output wire [3:0] m_count
);
    localparam integer LEGAL=MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536;
    localparam integer BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer CAPACITY=2*BLOCK+16;
    localparam integer ROWS=(CAPACITY+7)>>3;
    localparam integer ROW_BITS=ROWS>1 ? $clog2(ROWS) : 1;
    reg occupied;
    reg [2:0] first_bank;
    reg [3:0] held_count;
    wire [63:0] bank_data;
    wire accept=read_valid && read_ready;
    assign read_ready=rst_n && LEGAL && !clear && (!occupied || m_ready);
    assign m_valid=rst_n && LEGAL && !clear && occupied;
    assign m_count=m_valid ? held_count : 4'd0;
    genvar bank;
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: MAX_BLOCK_BYTES=1..65536");
        end
        for (bank=0;bank<8;bank=bank+1) begin : banks
            wire [7:0] q;
            wire [31:0] read_row=(read_index>>3)+
                (read_index[2:0]>bank ? 32'd1 : 32'd0);
            bellows_byte_ram #(.DEPTH(ROWS), .ADDR_BITS(ROW_BITS)) storage (
                .clk(clk),
                .write_en(rst_n && LEGAL && write_valid && write_index[2:0]==bank),
                .write_addr(write_index[ROW_BITS+2:3]), .write_data(write_data),
                .read_en(accept), .read_addr(read_row[ROW_BITS-1:0]),
                .read_data(q)
            );
            assign bank_data[bank*8 +: 8]=q;
        end
    endgenerate
    reg [2:0] selected_bank;
    integer i;
    always @* begin
        m_data=0;
        selected_bank=0;
        for (i=0;i<8;i=i+1) begin
            selected_bank=first_bank+i;
            if (m_valid && i<held_count)
                m_data[i*8 +: 8]=bank_data[selected_bank*8 +: 8];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            occupied<=0; first_bank<=0; held_count<=0;
        end else if (clear) begin
            occupied<=0; first_bank<=0; held_count<=0;
        end else if (accept) begin
            occupied<=1; first_bank<=read_index[2:0]; held_count<=read_count;
        end else if (m_valid && m_ready) occupied<=0;
    end
endmodule
