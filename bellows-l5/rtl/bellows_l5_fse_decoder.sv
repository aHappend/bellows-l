module bellows_l5_fse_decoder (
    input wire clk, input wire rst_n,
    input wire init_valid, output wire init_ready,
    input wire [8:0] init_state, output wire [8:0] state,
    input wire step_valid, output wire step_ready,
    input wire [8:0] bits, input wire [3:0] available,
    input wire [5:0] row_symbol, input wire [3:0] row_nbits,
    input wire [8:0] row_base,
    output wire m_valid, input wire m_ready,
    output wire [5:0] m_symbol, output wire [8:0] m_state,
    output wire [3:0] m_nbits
);
    reg awake, occupied;
    reg [8:0] current, result_state;
    reg [5:0] result_symbol;
    reg [3:0] result_nbits;
    wire [8:0] mask=9'h1ff >> (4'd9-row_nbits);
    wire [8:0] next_state=row_base+(bits & mask);
    assign init_ready=rst_n && awake && !occupied;
    assign step_ready=rst_n && awake && !init_valid &&
        (!occupied || m_ready) && available<=9 &&
        row_nbits<=9 && available>=row_nbits;
    assign state=rst_n ? current : 9'd0;
    assign m_valid=rst_n && occupied;
    assign m_symbol=m_valid ? result_symbol : 6'd0;
    assign m_state=m_valid ? result_state : 9'd0;
    assign m_nbits=m_valid ? result_nbits : 4'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            awake<=0; occupied<=0; current<=0;
            result_state<=0; result_symbol<=0; result_nbits<=0;
        end else begin
            awake<=1;
            if (m_valid && m_ready) occupied<=0;
            if (init_valid && init_ready) begin
                current<=init_state;
            end else if (step_valid && step_ready) begin
                current<=next_state;
                result_state<=next_state;
                result_symbol<=row_symbol;
                result_nbits<=row_nbits;
                occupied<=1;
            end
        end
    end
endmodule
