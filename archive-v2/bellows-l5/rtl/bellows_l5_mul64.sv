module bellows_l5_mul64 (
    input wire clk, input wire rst_n,
    input wire s_valid, output wire s_ready,
    input wire [63:0] s_a, input wire [63:0] s_b,
    output wire m_valid, input wire m_ready, output wire [63:0] m_product
);
    localparam [1:0] IDLE=0, LOW=1, HIGH=2, RESULT=3;
    reg [1:0] phase;
    reg awake;
    reg [63:0] a, b, sum;
    reg [31:0] low_q;
    reg carry_q;
    reg [5:0] bit_index;
    wire [32:0] low_sum={1'b0,sum[31:0]}+
        {1'b0,(a[31:0] & {32{b[0]}})};
    wire [32:0] high_sum={1'b0,sum[63:32]}+
        {1'b0,(a[63:32] & {32{b[0]}})}+{32'd0,carry_q};
    assign s_ready=rst_n && awake && phase==IDLE;
    assign m_valid=rst_n && phase==RESULT;
    assign m_product=m_valid ? sum : 64'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; a<=0; b<=0; sum<=0;
            low_q<=0; carry_q<=0; bit_index<=0;
        end else begin
            awake<=1;
            case (phase)
                IDLE: if (s_valid && s_ready) begin
                    a<=s_a; b<=s_b; sum<=0; bit_index<=0; phase<=LOW;
                end
                LOW: begin
                    low_q<=low_sum[31:0]; carry_q<=low_sum[32]; phase<=HIGH;
                end
                HIGH: begin
                    sum<={high_sum[31:0],low_q};
                    a<=a<<1; b<=b>>1;
                    if (bit_index==63) phase<=RESULT;
                    else begin bit_index<=bit_index+6'd1; phase<=LOW; end
                end
                RESULT: if (m_ready) phase<=IDLE;
            endcase
        end
    end
endmodule
