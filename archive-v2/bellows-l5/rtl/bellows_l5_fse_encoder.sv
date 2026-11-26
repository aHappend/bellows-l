module bellows_l5_fse_encoder (
    input wire clk, input wire rst_n, input wire clear,
    input wire table_valid, input wire [3:0] table_log,
    input wire s_valid, output wire s_ready,
    input wire [5:0] s_symbol, input wire [8:0] s_next_state,
    input wire s_terminal,
    output wire [8:0] row_address,
    input wire [5:0] row_symbol, input wire [3:0] row_nbits,
    input wire [8:0] row_base,
    output wire m_valid, input wire m_ready,
    output wire [3:0] m_error, output wire [8:0] m_state,
    output wire [8:0] m_bits, output wire [3:0] m_nbits
);
    localparam [2:0] IDLE=0, FIND=1, RESULT=2;
    reg [2:0] phase;
    reg awake, terminal;
    reg [5:0] symbol_q;
    reg [8:0] target, cursor, encoded_state, encoded_bits;
    reg [3:0] log_q, encoded_nbits, error_code;
    wire [9:0] limit=10'd1<<log_q;
    wire [9:0] interval_end={1'b0,row_base}+(10'd1<<row_nbits);
    wire hit=row_symbol==symbol_q &&
        (terminal || ({1'b0,target}>={1'b0,row_base} && {1'b0,target}<interval_end));
    assign s_ready=rst_n && awake && !clear && phase==IDLE;
    assign row_address=rst_n && phase==FIND ? cursor : 9'd0;
    assign m_valid=rst_n && !clear && phase==RESULT;
    assign m_error=m_valid ? error_code : 4'd0;
    assign m_state=m_valid ? encoded_state : 9'd0;
    assign m_bits=m_valid ? encoded_bits : 9'd0;
    assign m_nbits=m_valid ? encoded_nbits : 4'd0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; terminal<=0; symbol_q<=0;
            target<=0; cursor<=0; encoded_state<=0; encoded_bits<=0;
            log_q<=0; encoded_nbits<=0; error_code<=0;
        end else begin
            awake<=1;
            if (clear) phase<=IDLE;
            else case (phase)
                IDLE: if (s_valid && s_ready) begin
                    terminal<=s_terminal; symbol_q<=s_symbol; target<=s_next_state;
                    cursor<=0; log_q<=table_log; error_code<=0;
                    encoded_state<=0; encoded_bits<=0; encoded_nbits<=0;
                    if (!table_valid || table_log>9 ||
                        (!s_terminal && {1'b0,s_next_state}>=(10'd1<<table_log))) begin
                        error_code<=11; phase<=RESULT;
                    end else phase<=FIND;
                end
                FIND: begin
                    if (!table_valid || row_nbits>log_q || interval_end>limit) begin
                        error_code<=11; phase<=RESULT;
                    end else if (hit) begin
                        encoded_state<=cursor;
                        encoded_bits<=terminal ? 9'd0 : target-row_base;
                        encoded_nbits<=terminal ? 4'd0 : row_nbits;
                        phase<=RESULT;
                    end else if ({1'b0,cursor}+10'd1==limit) begin
                        error_code<=11; phase<=RESULT;
                    end else cursor<=cursor+9'd1;
                end
                RESULT: if (m_ready) phase<=IDLE;
                default: begin error_code<=11; phase<=RESULT; end
            endcase
        end
    end
endmodule
