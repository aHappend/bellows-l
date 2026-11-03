module bellows_l4_lz4_decoder #(
    parameter integer COPY_BYTES=8,
    parameter integer MAX_BLOCK_BYTES=65536
) (
    input wire clk, input wire rst_n, input wire clear,
    input wire s_valid, output wire s_ready,
    input wire [63:0] s_data, input wire [3:0] s_count,
    input wire s_last,
    output wire op_valid, input wire op_ready, output wire op_match,
    output wire [63:0] op_data, output wire [3:0] op_count,
    output wire [15:0] op_offset,
    output wire status_valid, input wire status_ready,
    output wire [3:0] status_error,
    output wire [31:0] decoded_bytes, output wire [31:0] consumed_bytes
);
    localparam integer LEGAL=(COPY_BYTES==4 || COPY_BYTES==8) &&
        MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536;
    localparam integer SAFE_BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer WIDTH=LEGAL ? COPY_BYTES : 4;
    localparam [3:0] IDLE=0, TOKEN=1, LITERAL_EXT=2, LITERAL=3,
        OFFSET_LOW=4, OFFSET_HIGH=5, MATCH_EXT=6, MATCH=7,
        DISCARD=8, FINISH=9, STATUS=10;
    reg [3:0] state, error_code, match_nibble;
    reg [127:0] queue_data;
    reg [4:0] queue_count;
    reg input_closed;
    reg [31:0] literal_remaining, match_remaining, produced, consumed;
    reg [15:0] offset;
    reg [3:0] count, take;
    reg [63:0] literal_data;
    integer lane;
    wire [7:0] byte_data=queue_data[7:0];
    wire parser=state==TOKEN || state==LITERAL_EXT || state==OFFSET_LOW ||
        state==OFFSET_HIGH || state==MATCH_EXT;
    wire parser_byte=parser && queue_count!=0;
    wire last_byte=input_closed && queue_count==1;
    wire [32:0] literal_sum={1'b0,literal_remaining}+{25'd0,byte_data};
    wire [32:0] match_sum={1'b0,match_remaining}+{25'd0,byte_data};
    wire [15:0] assembled_offset={byte_data,offset[7:0]};
    wire [31:0] room=SAFE_BLOCK-produced;
    wire operation=state==MATCH ? match_remaining!=0 :
        state==LITERAL && literal_remaining!=0 && queue_count!=0;
    wire op_transfer=op_valid && op_ready;

    always @* begin
        count=0; take=0; literal_data=0;
        if (state==LITERAL) begin
            count=WIDTH;
            if (literal_remaining<count) count=literal_remaining[3:0];
            if (queue_count<count) count=queue_count[3:0];
            if (room<count) count=room[3:0];
        end else if (state==MATCH) begin
            count=WIDTH;
            if (match_remaining<count) count=match_remaining[3:0];
            if (room<count) count=room[3:0];
        end
        for (lane=0;lane<8;lane=lane+1)
            if (lane<count) literal_data[lane*8 +: 8]=queue_data[lane*8 +: 8];
        if (parser_byte) take=1;
        else if (state==LITERAL && op_transfer) take=count;
        else if (state==DISCARD) begin
            if (queue_count>WIDTH) take=WIDTH;
            else take=queue_count[3:0];
        end
        if (!rst_n || clear) take=0;
    end

    assign op_valid=rst_n && LEGAL && !clear && operation && count!=0;
    assign op_match=op_valid && state==MATCH;
    assign op_data=op_valid && state==LITERAL ? literal_data : 64'd0;
    assign op_count=op_valid ? count : 4'd0;
    assign op_offset=op_match ? offset : 16'd0;
    assign s_ready=rst_n && LEGAL && !clear && state!=IDLE &&
        state!=STATUS && state!=FINISH && !input_closed && queue_count<=8 &&
        !(op_valid && !op_ready);
    wire input_transfer=s_valid && s_ready;
    wire [4:0] remaining_queue=queue_count-{1'b0,take};
    wire [4:0] next_queue_count=remaining_queue+
        (input_transfer ? {1'b0,s_count} : 5'd0);
    reg [63:0] clean_input;
    always @* begin
        clean_input=0;
        for (integer i=0;i<8;i=i+1)
            if (i<s_count) clean_input[i*8 +: 8]=s_data[i*8 +: 8];
    end
    wire [127:0] next_queue_data=(queue_data>>({3'd0,take}<<3)) |
        (input_transfer ? ({64'd0,clean_input}<<({3'd0,remaining_queue}<<3)) : 128'd0);
    assign status_valid=rst_n && LEGAL && state==STATUS;
    assign status_error=status_valid ? error_code : 4'd0;
    assign decoded_bytes=rst_n ? produced : 32'd0;
    assign consumed_bytes=rst_n ? consumed : 32'd0;

    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: COPY_BYTES=4 or 8, MAX_BLOCK_BYTES=1..65536");
        end
    endgenerate

    task reject;
        input [3:0] code;
        begin
            error_code<=code;
            state<=DISCARD;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE; error_code<=0; match_nibble<=0;
            queue_data<=0; queue_count<=0; input_closed<=0;
            literal_remaining<=0; match_remaining<=0;
            offset<=0; produced<=0; consumed<=0;
        end else if (clear) begin
            state<=TOKEN; error_code<=0; match_nibble<=0;
            queue_data<=0; queue_count<=0; input_closed<=0;
            literal_remaining<=0; match_remaining<=0;
            offset<=0; produced<=0; consumed<=0;
        end else begin
            queue_data<=next_queue_data; queue_count<=next_queue_count;
            consumed<=consumed+{28'd0,take};
            if (input_transfer && s_last) input_closed<=1;
            if (op_transfer) produced<=produced+{28'd0,count};
            case (state)
                IDLE: begin end
                TOKEN: if (parser_byte) begin
                    match_nibble<=byte_data[3:0];
                    literal_remaining<={28'd0,byte_data[7:4]};
                    match_remaining<={28'd0,byte_data[3:0]}+32'd4;
                    if (last_byte) begin
                        if (byte_data[7:4]!=0) reject(1);
                        else state<=FINISH;
                    end else if (byte_data[7:4]==15) state<=LITERAL_EXT;
                    else if (byte_data[7:4]!=0) state<=LITERAL;
                    else state<=OFFSET_LOW;
                end
                LITERAL_EXT: if (parser_byte) begin
                    if (last_byte) reject(1);
                    else if (literal_sum[32]) reject(4);
                    else begin
                        literal_remaining<=literal_sum[31:0];
                        if (byte_data!=255) state<=LITERAL;
                    end
                end
                LITERAL: begin
                    if (queue_count!=0 && room==0) reject(5);
                    else if (op_transfer) begin
                        literal_remaining<=literal_remaining-{28'd0,count};
                        if (input_closed && queue_count=={1'b0,count}) begin
                            if (literal_remaining!={28'd0,count}) reject(1);
                            else state<=FINISH;
                        end else if (literal_remaining=={28'd0,count})
                            state<=OFFSET_LOW;
                    end
                end
                OFFSET_LOW: if (parser_byte) begin
                    if (last_byte) reject(1);
                    else begin offset[7:0]<=byte_data; state<=OFFSET_HIGH; end
                end
                OFFSET_HIGH: if (parser_byte) begin
                    if (last_byte) reject(1);
                    else if (assembled_offset==0) reject(2);
                    else if ({16'd0,assembled_offset}>produced) reject(3);
                    else begin
                        offset<=assembled_offset;
                        if (match_nibble==15) state<=MATCH_EXT;
                        else state<=MATCH;
                    end
                end
                MATCH_EXT: if (parser_byte) begin
                    if (last_byte) reject(1);
                    else if (match_sum[32]) reject(4);
                    else begin
                        match_remaining<=match_sum[31:0];
                        if (byte_data!=255) state<=MATCH;
                    end
                end
                MATCH: begin
                    if (room==0) reject(5);
                    else if (op_transfer) begin
                        match_remaining<=match_remaining-{28'd0,count};
                        if (match_remaining=={28'd0,count}) state<=TOKEN;
                    end
                end
                DISCARD: if (input_closed && queue_count==0) state<=FINISH;
                FINISH: state<=STATUS;
                STATUS: if (status_ready) state<=IDLE;
                default: state<=IDLE;
            endcase
            if ((parser || state==LITERAL) && input_closed && queue_count==0)
                reject(1);
            if (input_transfer && (s_count==0 || s_count>WIDTH))
                reject(6);
        end
    end
endmodule
