module bellows_l5_reverse_reader #(
    parameter integer MAX_BYTES=132096
) (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire [31:0] start_base, input wire [31:0] start_bytes,
    output wire rd_en, output wire [31:0] rd_addr,
    input wire rd_valid, input wire [7:0] rd_data,
    input wire take_valid, output wire take_ready, input wire [5:0] take_nbits,
    output wire bits_valid, input wire bits_ready,
    output wire [31:0] bits_data, output wire [5:0] bits_nbits,
    output wire exhausted, output wire error_valid, output wire [3:0] error_code
);
    localparam [3:0] IDLE=0, LAST_REQ=1, LAST_WAIT=2, MARKER=3,
        READY=4, REFILL_REQ=5, REFILL_WAIT=6, RESULT=7, ERROR=8;
    reg [3:0] phase;
    reg awake;
    reg [31:0] base_q, cursor, bytes_left;
    reg [63:0] buffer_q;
    reg [6:0] fill;
    reg [5:0] requested;
    reg [31:0] result_q;
    reg [7:0] marker_byte;
    reg [3:0] marker_index;
    wire [32:0] end_address={1'b0,start_base}+{1'b0,start_bytes};
    wire [31:0] take_mask=32'hffffffff>>(6'd32-requested);
    wire [63:0] extracted=buffer_q>>(fill-{1'b0,requested});
    assign start_ready=rst_n && awake && !clear && phase==IDLE;
    assign rd_en=rst_n && !clear && (phase==LAST_REQ ||
        (phase==REFILL_REQ && fill<{1'b0,requested} && bytes_left!=0 && cursor>base_q));
    assign rd_addr=!rd_en ? 32'd0 : phase==LAST_REQ ? cursor : cursor-32'd1;
    assign take_ready=rst_n && !clear && phase==READY;
    assign bits_valid=rst_n && !clear && phase==RESULT;
    assign bits_data=bits_valid ? result_q : 32'd0;
    assign bits_nbits=bits_valid ? requested : 6'd0;
    assign exhausted=rst_n && (phase==READY || phase==RESULT) && bytes_left==0 && fill==0;
    assign error_valid=rst_n && !clear && phase==ERROR;
    assign error_code=error_valid ? 4'd11 : 4'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; base_q<=0; cursor<=0; bytes_left<=0;
            buffer_q<=0; fill<=0; requested<=0; result_q<=0;
            marker_byte<=0; marker_index<=0;
        end else begin
            awake<=1;
            if (clear) begin phase<=IDLE; buffer_q<=0; fill<=0; bytes_left<=0; end
            else case (phase)
                IDLE: if (start_valid && start_ready) begin
                    base_q<=start_base; cursor<=end_address[31:0]-32'd1;
                    bytes_left<=start_bytes; buffer_q<=0; fill<=0;
                    requested<=0; result_q<=0;
                    if (start_bytes==0 || start_bytes>MAX_BYTES || end_address[32])
                        phase<=ERROR;
                    else phase<=LAST_REQ;
                end
                LAST_REQ: phase<=LAST_WAIT;
                LAST_WAIT: if (rd_valid) begin
                    marker_byte<=rd_data; marker_index<=7;
                    bytes_left<=bytes_left-32'd1;
                    if (rd_data==0) phase<=ERROR;
                    else phase<=MARKER;
                end
                MARKER: begin
                    if (marker_byte[marker_index]) begin
                        fill<={3'd0,marker_index};
                        buffer_q<={56'd0,marker_byte} &
                            ((64'd1<<marker_index)-64'd1);
                        phase<=READY;
                    end else if (marker_index==0) phase<=ERROR;
                    else marker_index<=marker_index-4'd1;
                end
                READY: if (take_valid && take_ready) begin
                    requested<=take_nbits;
                    if (take_nbits>32) phase<=ERROR;
                    else phase<=REFILL_REQ;
                end
                REFILL_REQ: begin
                    if (fill>={1'b0,requested}) begin
                        result_q<=extracted[31:0] & take_mask;
                        buffer_q<=buffer_q & ((64'd1<<(fill-{1'b0,requested}))-64'd1);
                        fill<=fill-{1'b0,requested}; phase<=RESULT;
                    end else if (bytes_left==0 || cursor==base_q) phase<=ERROR;
                    else begin cursor<=cursor-32'd1; phase<=REFILL_WAIT; end
                end
                REFILL_WAIT: if (rd_valid) begin
                    buffer_q<=(buffer_q<<8) | {56'd0,rd_data};
                    fill<=fill+7'd8; bytes_left<=bytes_left-32'd1; phase<=REFILL_REQ;
                end
                RESULT: if (bits_ready) phase<=READY;
                ERROR: begin end
                default: phase<=ERROR;
            endcase
        end
    end
endmodule
