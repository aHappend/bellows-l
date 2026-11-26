module bellows_l5_bit_writer (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire s_valid, output wire s_ready,
    input wire [31:0] s_bits, input wire [5:0] s_nbits,
    input wire finish_valid, output wire finish_ready,
    output wire m_valid, input wire m_ready,
    output wire [7:0] m_data, output wire m_last,
    output wire done_valid, input wire done_ready, output wire [3:0] done_error
);
    localparam [2:0] IDLE=0, COLLECT=1, DRAIN=2, DONE=3;
    reg [2:0] phase;
    reg awake;
    reg [63:0] buffer_q;
    reg [6:0] fill;
    reg [3:0] error_code;
    wire [31:0] mask=32'hffffffff>>(6'd32-s_nbits);
    assign start_ready=rst_n && awake && !clear && phase==IDLE;
    assign s_ready=rst_n && !clear && phase==COLLECT && fill<8 && !finish_valid;
    assign finish_ready=rst_n && !clear && phase==COLLECT && fill<8;
    assign m_valid=rst_n && !clear &&
        ((phase==COLLECT && fill>=8) || (phase==DRAIN && fill!=0));
    assign m_data=m_valid ? buffer_q[7:0] : 8'd0;
    assign m_last=m_valid && phase==DRAIN && fill<=8;
    assign done_valid=rst_n && !clear && phase==DONE;
    assign done_error=done_valid ? error_code : 4'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; buffer_q<=0; fill<=0; error_code<=0;
        end else begin
            awake<=1;
            if (clear) begin phase<=IDLE; buffer_q<=0; fill<=0; error_code<=0; end
            else case (phase)
                IDLE: if (start_valid && start_ready) begin
                    buffer_q<=0; fill<=0; error_code<=0; phase<=COLLECT;
                end
                COLLECT: begin
                    if (m_valid && m_ready) begin
                        buffer_q<=buffer_q>>8; fill<=fill-7'd8;
                    end else if (finish_valid && finish_ready) begin
                        buffer_q<=buffer_q | (64'd1<<fill);
                        fill<=fill+7'd1; phase<=DRAIN;
                    end else if (s_valid && s_ready) begin
                        if (s_nbits>32) begin error_code<=11; phase<=DONE; end
                        else begin
                            buffer_q<=buffer_q | ({32'd0,(s_bits & mask)}<<fill);
                            fill<=fill+{1'b0,s_nbits};
                        end
                    end
                end
                DRAIN: if (m_valid && m_ready) begin
                    buffer_q<=buffer_q>>8;
                    if (fill<=8) begin fill<=0; phase<=DONE; end
                    else fill<=fill-7'd8;
                end
                DONE: if (done_ready) phase<=IDLE;
                default: begin error_code<=11; phase<=DONE; end
            endcase
        end
    end
endmodule
