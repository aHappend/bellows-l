module bellows_l2_literal_buffer #(
    parameter integer MAX_BLOCK_BYTES = 65536
) (
    input wire clk, write_en,
    input wire [15:0] write_addr,
    input wire [7:0] write_data,
    input wire a_en, b_en,
    input wire [15:0] a_addr, b_addr,
    output wire [31:0] a_data, b_data
);
    localparam integer ROWS = (MAX_BLOCK_BYTES + 3) / 4;
    localparam integer ROW_BITS = ROWS > 1 ? $clog2(ROWS) : 1;
    wire [31:0] a_banks, b_banks;
    logic [1:0] a_lane, b_lane;

    // Four byte-interleaved banks allow an unaligned 4-byte window on each
    // read port. Input collection and the two read phases never overlap.
    genvar bank;
    generate
        for (bank = 0; bank < 4; bank = bank + 1) begin : banks
            localparam logic [1:0] LANE = 2'(bank);
            wire carry_a, carry_b;
            if (bank == 3) begin : last_lane
                assign carry_a = 1'b0;
                assign carry_b = 1'b0;
            end else begin : crossing
                assign carry_a = LANE < a_addr[1:0];
                assign carry_b = LANE < b_addr[1:0];
            end
            wire [ROW_BITS-1:0] row_a = write_en ? write_addr[2 +: ROW_BITS] :
                a_addr[2 +: ROW_BITS] + ROW_BITS'(carry_a);
            wire [ROW_BITS-1:0] row_b =
                b_addr[2 +: ROW_BITS] + ROW_BITS'(carry_b);
            (* ramstyle = "M20K, no_rw_check" *) logic [7:0] mem [0:(1 << ROW_BITS)-1];
            logic [7:0] qa, qb;
            always_ff @(posedge clk) begin
                if (write_en && write_addr[1:0] == LANE)
                    mem[row_a] <= write_data;
                else if (a_en)
                    qa <= mem[row_a];
                if (b_en)
                    qb <= mem[row_b];
            end
            assign a_banks[8*bank +: 8] = qa;
            assign b_banks[8*bank +: 8] = qb;
        end
    endgenerate

    always_ff @(posedge clk) begin
        if (a_en) a_lane <= a_addr[1:0];
        if (b_en) b_lane <= b_addr[1:0];
    end
    assign a_data = 32'({a_banks, a_banks} >> {a_lane, 3'b0});
    assign b_data = 32'({b_banks, b_banks} >> {b_lane, 3'b0});
endmodule
