module bellows_l2_top #(
    parameter integer MAX_BLOCK_BYTES = 65536
) (
    input wire clk,
    input wire rst_n,
    input wire roundtrip_enable,
    input wire [7:0] c_s_data,
    input wire c_s_keep,
    input wire c_s_valid,
    input wire c_s_last,
    output wire c_s_ready,
    output wire [7:0] c_m_data,
    output wire c_m_valid,
    output wire c_m_last,
    input wire c_m_ready,
    output wire c_status_valid,
    output wire [2:0] c_status_error,
    input wire c_status_ready,
    input wire [7:0] d_s_data,
    input wire d_s_valid,
    input wire d_s_last,
    output wire d_s_ready,
    output wire [7:0] d_m_data,
    output wire d_m_valid,
    output wire d_m_last,
    input wire d_m_ready,
    output wire d_status_valid,
    output wire [2:0] d_status_error,
    input wire d_status_ready
);
    wire [7:0] compressed_data;
    wire compressed_valid;
    wire compressed_last;
    wire compressor_ready, decoder_ready;
    reg c_active, d_active, roundtrip_mode;
    wire idle = !c_active && !d_active;
    wire route = idle ? roundtrip_enable : roundtrip_mode;
    wire new_block_allowed = idle || roundtrip_enable == roundtrip_mode;
    wire c_admit = c_active || (new_block_allowed && !(route && d_active));
    wire d_admit = !route && (d_active || new_block_allowed);
    wire decoder_valid = route ? compressed_valid : d_s_valid && d_admit;

    assign c_s_ready = c_admit && compressor_ready;
    assign c_m_data = !route ? compressed_data : 8'd0;
    assign c_m_valid = !route && compressed_valid;
    assign c_m_last = !route && compressed_last;
    assign d_s_ready = d_admit && decoder_ready;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            c_active <= 1'b0;
            d_active <= 1'b0;
            roundtrip_mode <= 1'b0;
        end else begin
            if (idle)
                roundtrip_mode <= roundtrip_enable;
            if (c_s_valid && c_s_ready)
                c_active <= 1'b1;
            if (decoder_valid && decoder_ready)
                d_active <= 1'b1;
            if (c_status_valid && c_status_ready)
                c_active <= 1'b0;
            if (d_status_valid && d_status_ready)
                d_active <= 1'b0;
        end
    end

    bellows_l2_compressor #(.MAX_BLOCK_BYTES(MAX_BLOCK_BYTES)) compressor (
        .clk(clk), .rst_n(rst_n),
        .s_data(c_s_data), .s_keep(c_s_keep),
        .s_valid(c_s_valid && c_admit), .s_last(c_s_last), .s_ready(compressor_ready),
        .m_data(compressed_data), .m_valid(compressed_valid), .m_last(compressed_last),
        .m_ready(route ? decoder_ready : c_m_ready),
        .status_valid(c_status_valid), .status_error(c_status_error),
        .status_ready(c_status_ready)
    );

    bellows_l1_top decompressor (
        .clk(clk), .rst_n(rst_n),
        .s_data(route ? compressed_data : d_s_data),
        .s_valid(decoder_valid),
        .s_last(route ? compressed_last : d_s_last),
        .s_ready(decoder_ready),
        .m_data(d_m_data), .m_valid(d_m_valid), .m_last(d_m_last), .m_ready(d_m_ready),
        .status_valid(d_status_valid), .status_error(d_status_error),
        .status_ready(d_status_ready)
    );
endmodule
