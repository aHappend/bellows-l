module bellows_l1_output (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] candidate_data,
    input  wire       candidate_valid,
    output wire       candidate_ready,
    input  wire       finish_valid,
    output wire       finish_ready,
    output wire       idle,
    output wire       retiring_or_empty,
    output wire [7:0] m_data,
    output wire       m_valid,
    output wire       m_last,
    input  wire       m_ready
);
    reg [7:0] pending_data;
    reg       pending_valid;
    reg [7:0] presented_data;
    reg       presented_valid;
    reg       presented_last;

    wire slot_available = !presented_valid || m_ready;
    assign candidate_ready = rst_n && (!pending_valid || slot_available);
    assign finish_ready = rst_n && (!pending_valid || slot_available);
    assign idle = !pending_valid && !presented_valid;
    assign retiring_or_empty = !pending_valid && slot_available;
    assign m_valid = rst_n && presented_valid;
    assign m_data = m_valid ? presented_data : 8'd0;
    assign m_last = m_valid && presented_last;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_data <= 8'd0;
            pending_valid <= 1'b0;
            presented_data <= 8'd0;
            presented_valid <= 1'b0;
            presented_last <= 1'b0;
        end else begin
            if (presented_valid && m_ready) begin
                presented_data <= 8'd0;
                presented_valid <= 1'b0;
                presented_last <= 1'b0;
            end

            // A promotion replaces a retiring beat on the same edge.
            if (candidate_valid && candidate_ready) begin
                if (pending_valid) begin
                    presented_data <= pending_data;
                    presented_valid <= 1'b1;
                    presented_last <= 1'b0;
                end
                pending_data <= candidate_data;
                pending_valid <= 1'b1;
            end else if (finish_valid && finish_ready) begin
                if (pending_valid) begin
                    presented_data <= pending_data;
                    presented_valid <= 1'b1;
                    presented_last <= 1'b1;
                end
                pending_data <= 8'd0;
                pending_valid <= 1'b0;
            end
        end
    end
endmodule
