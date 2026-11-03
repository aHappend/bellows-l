module bellows_l5_xxh64 (
    input wire clk, input wire rst_n,
    input wire start_valid, output wire start_ready,
    input wire s_valid, output wire s_ready, input wire [7:0] s_data,
    input wire finish_valid, output wire finish_ready,
    output wire result_valid, input wire result_ready,
    output wire [63:0] result
);
    localparam [63:0] P1=64'h9e3779b185ebca87, P2=64'hc2b2ae3d27d4eb4f,
        P3=64'h165667b19e3779f9, P4=64'h85ebca77c2b2ae63, P5=64'h27d4eb2f165667c5;
    localparam [5:0] IDLE=0, COLLECT=1,
        STRIPE_PRODUCT=2, STRIPE_SUM=3, STRIPE_ROTATE=4, STRIPE_SCALE=5,
        STRIPE_STORE=6, COMBINE0=7, COMBINE1=8, COMBINE2=9, COMBINE3=10,
        MERGE_PRODUCT=11, MERGE_ROTATE=12, MERGE_SCALE=13, MERGE_XOR=14,
        MERGE_HASH_SCALE=15, MERGE_HASH_ADD=16, LENGTH_ADD=17, TAIL=18,
        TAIL8_PRODUCT=19, TAIL8_ROTATE=20, TAIL8_SCALE=21, TAIL8_XOR=22,
        TAIL8_HASH_ROTATE=23, TAIL8_HASH_SCALE=24, TAIL8_STORE=25,
        TAIL4_PRODUCT=26, TAIL4_XOR=27, TAIL4_ROTATE=28,
        TAIL4_SCALE=29, TAIL4_STORE=30, TAIL1_PRODUCT=31, TAIL1_XOR=32,
        TAIL1_ROTATE=33, TAIL1_SCALE=34, TAIL1_STORE=35,
        AV_XOR33=36, AV_SCALE2=37, AV_XOR29=38, AV_SCALE3=39,
        AV_XOR32=40, RESULT=41;
    reg [5:0] phase;
    reg awake, striped, multiply_pending;
    reg [1:0] lane;
    reg [255:0] bytes_q;
    reg [5:0] fill;
    reg [63:0] length, v1, v2, v3, v4, h, work, product;
    reg [63:0] mul_a, mul_b, lane_value;
    reg mul_request;
    wire mul_ready, mul_valid;
    wire [63:0] mul_result;
    wire mul_done=multiply_pending && mul_valid;
    assign start_ready=rst_n && awake && phase==IDLE;
    assign s_ready=rst_n && phase==COLLECT && !finish_valid;
    assign finish_ready=rst_n && phase==COLLECT;
    assign result_valid=rst_n && phase==RESULT;
    assign result=result_valid ? h : 64'd0;
    always @* begin
        case (lane)
            0: lane_value=v1;
            1: lane_value=v2;
            2: lane_value=v3;
            default: lane_value=v4;
        endcase
    end
    always @* begin
        mul_request=1;
        mul_a=0; mul_b=0;
        case (phase)
            STRIPE_PRODUCT: begin mul_a=bytes_q[63:0]; mul_b=P2; end
            STRIPE_SCALE: begin mul_a=work; mul_b=P1; end
            MERGE_PRODUCT: begin mul_a=lane_value; mul_b=P2; end
            MERGE_SCALE: begin mul_a=work; mul_b=P1; end
            MERGE_HASH_SCALE: begin mul_a=h; mul_b=P1; end
            TAIL8_PRODUCT: begin mul_a=bytes_q[63:0]; mul_b=P2; end
            TAIL8_SCALE: begin mul_a=work; mul_b=P1; end
            TAIL8_HASH_SCALE: begin mul_a=h; mul_b=P1; end
            TAIL4_PRODUCT: begin mul_a={32'd0,bytes_q[31:0]}; mul_b=P1; end
            TAIL4_SCALE: begin mul_a=h; mul_b=P2; end
            TAIL1_PRODUCT: begin mul_a={56'd0,bytes_q[7:0]}; mul_b=P5; end
            TAIL1_SCALE: begin mul_a=h; mul_b=P1; end
            AV_SCALE2: begin mul_a=h; mul_b=P2; end
            AV_SCALE3: begin mul_a=h; mul_b=P3; end
            default: mul_request=0;
        endcase
    end
    bellows_l5_mul64 multiply (
        .clk(clk), .rst_n(rst_n),
        .s_valid(mul_request && !multiply_pending), .s_ready(mul_ready),
        .s_a(mul_a), .s_b(mul_b),
        .m_valid(mul_valid), .m_ready(multiply_pending), .m_product(mul_result)
    );
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; striped<=0; multiply_pending<=0;
            lane<=0; bytes_q<=0; fill<=0; length<=0;
            v1<=0; v2<=0; v3<=0; v4<=0; h<=0; work<=0; product<=0;
        end else begin
            awake<=1;
            if (mul_request && !multiply_pending && mul_ready) multiply_pending<=1;
            if (mul_done) begin multiply_pending<=0; product<=mul_result; end
            case (phase)
                IDLE: if (start_valid && start_ready) begin
                    striped<=0; lane<=0; bytes_q<=0; fill<=0; length<=0;
                    v1<=64'h60ea27eeadc0b5d6; v2<=P2; v3<=0;
                    v4<=64'h61c8864e7a143579; h<=0; work<=0; product<=0;
                    phase<=COLLECT;
                end
                COLLECT: begin
                    if (finish_valid && finish_ready) begin
                        if (striped) phase<=COMBINE0;
                        else begin h<=P5; phase<=LENGTH_ADD; end
                    end else if (s_valid && s_ready) begin
                        bytes_q[fill*8 +: 8]<=s_data;
                        length<=length+64'd1; fill<=fill+6'd1;
                        if (fill==31) begin lane<=0; phase<=STRIPE_PRODUCT; end
                    end
                end
                STRIPE_PRODUCT: if (mul_done) phase<=STRIPE_SUM;
                STRIPE_SUM: begin work<=lane_value+product; phase<=STRIPE_ROTATE; end
                STRIPE_ROTATE: begin work<={work[32:0],work[63:33]}; phase<=STRIPE_SCALE; end
                STRIPE_SCALE: if (mul_done) phase<=STRIPE_STORE;
                STRIPE_STORE: begin
                    case (lane)
                        0: v1<=product;
                        1: v2<=product;
                        2: v3<=product;
                        3: v4<=product;
                    endcase
                    bytes_q<=bytes_q>>64;
                    if (lane==3) begin striped<=1; fill<=0; phase<=COLLECT; end
                    else begin lane<=lane+2'd1; phase<=STRIPE_PRODUCT; end
                end
                COMBINE0: begin h<={v1[62:0],v1[63]}; phase<=COMBINE1; end
                COMBINE1: begin h<=h+{v2[56:0],v2[63:57]}; phase<=COMBINE2; end
                COMBINE2: begin h<=h+{v3[51:0],v3[63:52]}; phase<=COMBINE3; end
                COMBINE3: begin h<=h+{v4[45:0],v4[63:46]}; lane<=0; phase<=MERGE_PRODUCT; end
                MERGE_PRODUCT: if (mul_done) phase<=MERGE_ROTATE;
                MERGE_ROTATE: begin work<={product[32:0],product[63:33]}; phase<=MERGE_SCALE; end
                MERGE_SCALE: if (mul_done) phase<=MERGE_XOR;
                MERGE_XOR: begin h<=h^product; phase<=MERGE_HASH_SCALE; end
                MERGE_HASH_SCALE: if (mul_done) phase<=MERGE_HASH_ADD;
                MERGE_HASH_ADD: begin
                    h<=product+P4;
                    if (lane==3) phase<=LENGTH_ADD;
                    else begin lane<=lane+2'd1; phase<=MERGE_PRODUCT; end
                end
                LENGTH_ADD: begin h<=h+length; phase<=TAIL; end
                TAIL: begin
                    if (fill>=8) phase<=TAIL8_PRODUCT;
                    else if (fill>=4) phase<=TAIL4_PRODUCT;
                    else if (fill!=0) phase<=TAIL1_PRODUCT;
                    else phase<=AV_XOR33;
                end
                TAIL8_PRODUCT: if (mul_done) phase<=TAIL8_ROTATE;
                TAIL8_ROTATE: begin work<={product[32:0],product[63:33]}; phase<=TAIL8_SCALE; end
                TAIL8_SCALE: if (mul_done) phase<=TAIL8_XOR;
                TAIL8_XOR: begin h<=h^product; phase<=TAIL8_HASH_ROTATE; end
                TAIL8_HASH_ROTATE: begin h<={h[36:0],h[63:37]}; phase<=TAIL8_HASH_SCALE; end
                TAIL8_HASH_SCALE: if (mul_done) phase<=TAIL8_STORE;
                TAIL8_STORE: begin
                    h<=product+P4; bytes_q<=bytes_q>>64; fill<=fill-6'd8; phase<=TAIL;
                end
                TAIL4_PRODUCT: if (mul_done) phase<=TAIL4_XOR;
                TAIL4_XOR: begin h<=h^product; phase<=TAIL4_ROTATE; end
                TAIL4_ROTATE: begin h<={h[40:0],h[63:41]}; phase<=TAIL4_SCALE; end
                TAIL4_SCALE: if (mul_done) phase<=TAIL4_STORE;
                TAIL4_STORE: begin
                    h<=product+P3; bytes_q<=bytes_q>>32; fill<=fill-6'd4; phase<=TAIL;
                end
                TAIL1_PRODUCT: if (mul_done) phase<=TAIL1_XOR;
                TAIL1_XOR: begin h<=h^product; phase<=TAIL1_ROTATE; end
                TAIL1_ROTATE: begin h<={h[52:0],h[63:53]}; phase<=TAIL1_SCALE; end
                TAIL1_SCALE: if (mul_done) phase<=TAIL1_STORE;
                TAIL1_STORE: begin
                    h<=product; bytes_q<=bytes_q>>8; fill<=fill-6'd1; phase<=TAIL;
                end
                AV_XOR33: begin h<=h^(h>>33); phase<=AV_SCALE2; end
                AV_SCALE2: if (mul_done) phase<=AV_XOR29;
                AV_XOR29: begin h<=product^(product>>29); phase<=AV_SCALE3; end
                AV_SCALE3: if (mul_done) phase<=AV_XOR32;
                AV_XOR32: begin h<=product^(product>>32); phase<=RESULT; end
                RESULT: if (result_ready) phase<=IDLE;
                default: phase<=IDLE;
            endcase
        end
    end
endmodule
