module bellows_l1_reset_sync (
    input wire clk, arst,
    output wire rst_n
);
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *)
    logic [2:0] release_sync = '0 /* synthesis preserve dont_replicate */;
    always_ff @(posedge clk or posedge arst) begin
        if (arst)
            release_sync <= '0;
        else
            release_sync <= {release_sync[1:0], 1'b1};
    end
    assign rst_n = release_sync[2];
endmodule
