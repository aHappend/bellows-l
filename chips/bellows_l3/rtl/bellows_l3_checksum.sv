module bellows_l3_checksum (
    input wire clk, input wire rst_n,
    input wire start, input wire [1:0] mode,
    input wire [7:0] s_data, input wire s_valid, output wire s_ready,
    input wire finish_valid, output wire finish_ready,
    output wire result_valid, output wire [31:0] result
);
    localparam [31:0] P1=32'h9e3779b1, P2=32'h85ebca77,
        P3=32'hc2b2ae3d, P4=32'h27d4eb2f, P5=32'h165667b1;
    localparam [5:0] COLLECT=0, CRC_STEP=1,
        STRIPE_MUL=2, STRIPE_ADD=3, STRIPE_ROT=4, STRIPE_SCALE=5,
        STRIPE_STORE=6, COMBINE1=7, COMBINE2=8, COMBINE3=9,
        LENGTH_ADD=10, TAIL=11, WORD_MUL=12, WORD_ADD=13,
        WORD_ROT=14, WORD_SCALE=15, WORD_STORE=16,
        BYTE_MUL=17, BYTE_ADD=18, BYTE_ROT=19, BYTE_SCALE=20,
        BYTE_STORE=21, XOR15=22, AV_MUL2=23, XOR13=24,
        AV_MUL3=25, XOR16=26, DONE=27;
    reg [5:0] state;
    reg [1:0] selected_mode, lane;
    reg [127:0] buffer_data;
    reg [4:0] fill;
    reg [31:0] length, v1, v2, v3, v4, h, product, work, crc;
    reg [2:0] crc_bit;
    reg striped;
    reg [31:0] lane_value;
    wire [31:0] rotated13 = {work[18:0],work[31:19]};
    wire [31:0] rotated17 = {work[14:0],work[31:15]};
    wire [31:0] rotated11 = {work[20:0],work[31:21]};
    assign s_ready = rst_n && state==COLLECT && !finish_valid;
    assign finish_ready = rst_n && state==COLLECT;
    assign result_valid = rst_n && state==DONE;
    assign result = result_valid ? h : 32'd0;
    always @* begin
        case (lane)
            0: lane_value=v1;
            1: lane_value=v2;
            2: lane_value=v3;
            default: lane_value=v4;
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=COLLECT; selected_mode<=0; lane<=0; buffer_data<=0;
            fill<=0; length<=0; v1<=0; v2<=0; v3<=0; v4<=0;
            h<=0; product<=0; work<=0; crc<=32'hffffffff;
            crc_bit<=0; striped<=0;
        end else if (start) begin
            state<=COLLECT; selected_mode<=mode; lane<=0; buffer_data<=0;
            fill<=0; length<=0; v1<=32'h24234428; v2<=P2;
            v3<=0; v4<=32'h61c8864f; h<=0; product<=0; work<=0;
            crc<=32'hffffffff; crc_bit<=0; striped<=0;
        end else begin
            case (state)
                COLLECT: begin
                    if (finish_valid) begin
                        if (selected_mode==0) begin h<=0; state<=DONE; end
                        else if (selected_mode==2) begin
                            h<=crc ^ 32'hffffffff; state<=DONE;
                        end else if (striped) begin
                            h<={v1[30:0],v1[31]}; state<=COMBINE1;
                        end else begin h<=P5; state<=LENGTH_ADD; end
                    end else if (s_valid && s_ready) begin
                        length<=length+1'b1;
                        if (selected_mode==2) begin
                            crc<=crc ^ {24'd0,s_data};
                            crc_bit<=0; state<=CRC_STEP;
                        end else if (selected_mode==1) begin
                            buffer_data[fill*8 +: 8]<=s_data;
                            fill<=fill+1'b1;
                            if (fill==15) begin lane<=0; state<=STRIPE_MUL; end
                        end
                    end
                end
                CRC_STEP: begin
                    if (crc[0]) crc<=(crc>>1)^32'hedb88320;
                    else crc<=crc>>1;
                    if (crc_bit==7) state<=COLLECT;
                    else crc_bit<=crc_bit+1'b1;
                end
                STRIPE_MUL: begin product<=buffer_data[31:0]*P2; state<=STRIPE_ADD; end
                STRIPE_ADD: begin work<=lane_value+product; state<=STRIPE_ROT; end
                STRIPE_ROT: begin work<=rotated13; state<=STRIPE_SCALE; end
                STRIPE_SCALE: begin product<=work*P1; state<=STRIPE_STORE; end
                STRIPE_STORE: begin
                    case (lane)
                        0: v1<=product;
                        1: v2<=product;
                        2: v3<=product;
                        3: v4<=product;
                    endcase
                    buffer_data<=buffer_data>>32;
                    if (lane==3) begin fill<=0; striped<=1; state<=COLLECT; end
                    else begin lane<=lane+1'b1; state<=STRIPE_MUL; end
                end
                COMBINE1: begin h<=h+{v2[24:0],v2[31:25]}; state<=COMBINE2; end
                COMBINE2: begin h<=h+{v3[19:0],v3[31:20]}; state<=COMBINE3; end
                COMBINE3: begin h<=h+{v4[13:0],v4[31:14]}; state<=LENGTH_ADD; end
                LENGTH_ADD: begin h<=h+length; state<=TAIL; end
                TAIL: begin
                    if (fill>=4) state<=WORD_MUL;
                    else if (fill!=0) state<=BYTE_MUL;
                    else state<=XOR15;
                end
                WORD_MUL: begin product<=buffer_data[31:0]*P3; state<=WORD_ADD; end
                WORD_ADD: begin work<=h+product; state<=WORD_ROT; end
                WORD_ROT: begin work<=rotated17; state<=WORD_SCALE; end
                WORD_SCALE: begin product<=work*P4; state<=WORD_STORE; end
                WORD_STORE: begin
                    h<=product; buffer_data<=buffer_data>>32;
                    fill<=fill-4; state<=TAIL;
                end
                BYTE_MUL: begin product<={24'd0,buffer_data[7:0]}*P5; state<=BYTE_ADD; end
                BYTE_ADD: begin work<=h+product; state<=BYTE_ROT; end
                BYTE_ROT: begin work<=rotated11; state<=BYTE_SCALE; end
                BYTE_SCALE: begin product<=work*P1; state<=BYTE_STORE; end
                BYTE_STORE: begin
                    h<=product; buffer_data<=buffer_data>>8;
                    fill<=fill-1'b1; state<=TAIL;
                end
                XOR15: begin h<=h^(h>>15); state<=AV_MUL2; end
                AV_MUL2: begin h<=h*P2; state<=XOR13; end
                XOR13: begin h<=h^(h>>13); state<=AV_MUL3; end
                AV_MUL3: begin h<=h*P3; state<=XOR16; end
                XOR16: begin h<=h^(h>>16); state<=DONE; end
                DONE: begin end
                default: state<=COLLECT;
            endcase
        end
    end
endmodule
