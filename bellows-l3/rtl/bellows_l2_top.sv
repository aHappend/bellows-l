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
    wire decoder_ready;

    assign c_m_data = rst_n && !roundtrip_enable ? compressed_data : 8'd0;
    assign c_m_valid = rst_n && !roundtrip_enable && compressed_valid;
    assign c_m_last = rst_n && !roundtrip_enable && compressed_last;
    assign d_s_ready = rst_n && !roundtrip_enable && decoder_ready;

    bellows_l2_compressor #(.MAX_BLOCK_BYTES(MAX_BLOCK_BYTES)) compressor (
        .clk(clk), .rst_n(rst_n),
        .s_data(c_s_data), .s_keep(c_s_keep),
        .s_valid(c_s_valid), .s_last(c_s_last), .s_ready(c_s_ready),
        .m_data(compressed_data), .m_valid(compressed_valid), .m_last(compressed_last),
        .m_ready(roundtrip_enable ? decoder_ready : c_m_ready),
        .status_valid(c_status_valid), .status_error(c_status_error),
        .status_ready(c_status_ready)
    );

    bellows_l1_top decompressor (
        .clk(clk), .rst_n(rst_n),
        .s_data(roundtrip_enable ? compressed_data : d_s_data),
        .s_valid(rst_n && (roundtrip_enable ? compressed_valid : d_s_valid)),
        .s_last(roundtrip_enable ? compressed_last : d_s_last),
        .s_ready(decoder_ready),
        .m_data(d_m_data), .m_valid(d_m_valid), .m_last(d_m_last), .m_ready(d_m_ready),
        .status_valid(d_status_valid), .status_error(d_status_error),
        .status_ready(d_status_ready)
    );
endmodule
