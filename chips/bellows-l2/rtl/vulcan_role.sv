// Source provenance: binding.json (ddd8cc155aa097027c5884d8d05ae50a4a7732ecf7d5c82a8b8746247a29ce49).
// The wrapper, SDC, and bellows_l1_{ddr,reset_sync,history,output} are from
// accepted_parent_3_0_rtl. bellows_l1_top and the bellows_l2 codec are ports
// of seed_files/rtl. Role_BellowsL2 ports the seed ABI using the parent
// DDR/Avalon implementation and the scaffold's role-clock DMA interface.
module vulcan_role #(
    parameter integer MAX_BLOCK_BYTES = 65536
) (
    input  wire         clk, reset,
    input  wire         reg_read, reg_write,
    input  wire [17:0]  reg_addr,
    input  wire [63:0]  reg_wdata,
    output wire [63:0]  reg_rdata,
    output wire         reg_rvalid,
    output wire [31:0]  role_id, role_version, role_status,
    input  wire         ddr_clk, ddr_reset, amm_ready,
    output wire         amm_read, amm_write,
    output wire [25:0]  amm_address,
    input  wire [511:0] amm_readdata,
    output wire [511:0] amm_writedata,
    output wire [6:0]   amm_burstcount,
    output wire [63:0]  amm_byteenable,
    input  wire         amm_readdatavalid,
    output wire         dma_cmd_valid, dma_cmd_write,
    input  wire         dma_cmd_ready,
    output wire [63:0]  dma_cmd_addr,
    output wire [25:0]  dma_cmd_bytes,
    input  wire         dma_cpl_valid, dma_cpl_error, dma_abort,
    output wire         dma_cpl_ready,
    output wire         dma_tx_valid, dma_tx_last,
    input  wire         dma_tx_ready,
    output wire [127:0] dma_tx_data,
    output wire [15:0]  dma_tx_keep,
    input  wire         dma_rx_valid, dma_rx_last,
    output wire         dma_rx_ready,
    input  wire [127:0] dma_rx_data,
    input  wire [15:0]  dma_rx_keep
);
    Role_BellowsL2 #(.MAX_BLOCK_BYTES(MAX_BLOCK_BYTES)) bellows (.*);
endmodule
