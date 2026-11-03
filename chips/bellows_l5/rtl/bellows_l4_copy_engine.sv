module bellows_l4_copy_engine #(
    parameter integer COPY_BYTES=8,
    parameter integer MAX_BLOCK_BYTES=65536
) (
    input wire clk, input wire rst_n, input wire clear,
    input wire op_valid, input wire op_match, output wire op_ready,
    input wire [63:0] op_data, input wire [3:0] op_count,
    input wire [15:0] op_offset,
    output wire m_valid, input wire m_ready,
    output wire [63:0] m_data, output wire [3:0] m_count
);
    localparam integer LEGAL=(COPY_BYTES==4 || COPY_BYTES==8) &&
        MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536;
    localparam integer SAFE_BLOCK=LEGAL ? MAX_BLOCK_BYTES : 1;
    localparam integer ROWS=(SAFE_BLOCK+7)>>3;
    reg [15:0] position;
    reg request_valid, request_match, output_valid;
    reg [63:0] request_data, output_data;
    reg [3:0] request_count, output_count;
    reg [15:0] request_offset, request_start, request_base, output_start;
    wire advance=!output_valid || m_ready;
    wire accept=op_valid && op_ready;
    wire commit=rst_n && !clear && advance && request_valid;
    wire [15:0] read_base=position-op_offset;
    wire [63:0] bank_data;
    wire [63:0] assembled;

    assign op_ready=rst_n && LEGAL && !clear && advance;
    assign m_valid=rst_n && LEGAL && !clear && output_valid;
    assign m_data=m_valid ? output_data : 64'd0;
    assign m_count=m_valid ? output_count : 4'd0;

    // Only the first offset bytes are seeds. Small offsets repeat those
    // seeds through a bounded lane lookup rather than a serial copy chain.
    function automatic [2:0] seed_lane;
        input [2:0] lane;
        input [15:0] distance;
        begin
            seed_lane=lane;
            case (distance)
                1: seed_lane=0;
                2: seed_lane={2'd0,lane[0]};
                3: case (lane)
                    3,6: seed_lane=0;
                    4,7: seed_lane=1;
                    5: seed_lane=2;
                    default: seed_lane=lane;
                endcase
                4: seed_lane={1'b0,lane[1:0]};
                5: if (lane>=5) seed_lane=lane-3'd5;
                6: if (lane>=6) seed_lane=lane-3'd6;
                7: if (lane==7) seed_lane=0;
                default: seed_lane=lane;
            endcase
        end
    endfunction

    genvar bank, lane;
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: COPY_BYTES=4 or 8, MAX_BLOCK_BYTES=1..65536");
        end
        for (bank=0;bank<8;bank=bank+1) begin : history_banks
            localparam [2:0] BANK=bank;
            (* ramstyle="M20K", nomem2reg *) reg [7:0] memory [0:ROWS-1];
            reg [7:0] read_data;
            wire [2:0] read_lane=BANK-read_base[2:0];
            wire [2:0] write_lane=BANK-request_start[2:0];
            wire [15:0] read_address=read_base+{13'd0,read_lane};
            wire [15:0] write_address=request_start+{13'd0,write_lane};
            assign bank_data[bank*8 +: 8]=read_data;
            always @(posedge clk) begin
                if (accept && op_match) begin
                    if ({1'b0,read_address[15:3]}<ROWS)
                        read_data<=memory[read_address[15:3]];
                    else read_data<=0;
                end
                if (commit && write_lane<request_count)
                    memory[write_address[15:3]]<=assembled[write_lane*8 +: 8];
            end
        end
        for (lane=0;lane<8;lane=lane+1) begin : output_lanes
            localparam [2:0] LANE=lane;
            wire [2:0] seed=seed_lane(LANE,request_offset);
            wire [15:0] address=request_base+{13'd0,seed};
            wire [15:0] forward_lane=address-output_start;
            wire forwarded=output_valid && forward_lane<{12'd0,output_count};
            wire [7:0] history_byte=forwarded ?
                output_data[forward_lane[2:0]*8 +: 8] :
                bank_data[address[2:0]*8 +: 8];
            assign assembled[lane*8 +: 8]=lane<request_count ?
                (request_match ? history_byte : request_data[lane*8 +: 8]) : 8'd0;
        end
    endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            position<=0; request_valid<=0; request_match<=0;
            request_data<=0; request_count<=0; request_offset<=0;
            request_start<=0; request_base<=0; output_valid<=0;
            output_data<=0; output_count<=0; output_start<=0;
        end else if (clear) begin
            position<=0; request_valid<=0; request_match<=0;
            request_data<=0; request_count<=0; request_offset<=0;
            request_start<=0; request_base<=0; output_valid<=0;
            output_data<=0; output_count<=0; output_start<=0;
        end else if (advance) begin
            output_valid<=request_valid;
            output_data<=request_valid ? assembled : 64'd0;
            output_count<=request_valid ? request_count : 4'd0;
            output_start<=request_start;
            request_valid<=accept;
            if (accept) begin
                request_match<=op_match; request_data<=op_data;
                request_count<=op_count; request_offset<=op_offset;
                request_start<=position; request_base<=read_base;
                position<=position+{12'd0,op_count};
            end
        end
    end
endmodule
