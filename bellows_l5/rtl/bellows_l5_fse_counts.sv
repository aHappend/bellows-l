module bellows_l5_fse_counts (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire [1:0] alphabet,
    input wire s_valid, output wire s_ready,
    input wire [7:0] s_data, input wire s_last,
    output wire log_valid, input wire log_ready, output wire [3:0] table_log,
    output wire count_valid, input wire count_ready,
    output wire [5:0] count_symbol,
    output wire signed [10:0] count_value, output wire count_last,
    output wire done_valid, input wire done_ready,
    output wire [3:0] done_error, output wire [7:0] bytes_used
);
    localparam [3:0] IDLE=0, HEADER=1, CONFIG=2, WIDTH=3, SHORT=4,
        FULL=5, EMIT=6, ZERO_FLAG=7, ZERO_OUT=8, PAD=9, DONE=10;
    reg [3:0] phase;
    reg awake, ended, more_zeros;
    reg [1:0] alphabet_q, zero_left;
    reg [3:0] log_q, nbits, error_code;
    reg [5:0] symbol_q, max_symbol;
    reg [7:0] byte_count;
    reg [23:0] buffer_q;
    reg [4:0] fill;
    reg [10:0] remaining, threshold;
    reg signed [10:0] value_q;
    reg [3:0] need;
    wire [23:0] short_mask=(24'd1<<(nbits-4'd1))-24'd1;
    wire [23:0] full_mask=(24'd1<<nbits)-24'd1;
    wire [10:0] short_value=buffer_q[10:0] & short_mask[10:0];
    wire [10:0] full_value=buffer_q[10:0] & full_mask[10:0];
    wire [11:0] cutoff=({1'b0,threshold}<<1)-12'd1-{1'b0,remaining};
    wire [10:0] selected_value=phase==SHORT ? short_value :
        full_value>=threshold ? full_value-cutoff[10:0] : full_value;
    wire signed [11:0] probability=$signed({1'b0,selected_value})-12'sd1;
    wire [10:0] mass=probability==-12'sd1 ? 11'd1 : probability[10:0];
    wire accepting_value=(phase==SHORT && {7'd0,short_value}<cutoff) || phase==FULL;
    wire needs_input=phase==HEADER || phase==SHORT || phase==FULL || phase==ZERO_FLAG;
    wire enough=fill>={1'b0,need};
    assign start_ready=rst_n && awake && !clear && phase==IDLE;
    assign s_ready=rst_n && !clear && needs_input && !enough && !ended;
    assign log_valid=rst_n && !clear && phase==CONFIG;
    assign table_log=rst_n && phase!=IDLE ? log_q : 4'd0;
    assign count_valid=rst_n && !clear && (phase==EMIT || phase==ZERO_OUT || phase==PAD);
    assign count_symbol=count_valid ? symbol_q : 6'd0;
    assign count_value=count_valid && phase==EMIT ? value_q : 11'sd0;
    assign count_last=count_valid && symbol_q==max_symbol;
    assign done_valid=rst_n && !clear && phase==DONE;
    assign done_error=done_valid ? error_code : 4'd0;
    assign bytes_used=rst_n ? byte_count : 8'd0;
    always @* begin
        need=0;
        case (phase)
            HEADER: need=4;
            SHORT: need=nbits-4'd1;
            FULL: need=nbits;
            ZERO_FLAG: need=2;
            default: need=0;
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; ended<=0; more_zeros<=0; alphabet_q<=0;
            zero_left<=0; log_q<=0; nbits<=0; error_code<=0; symbol_q<=0;
            max_symbol<=0; byte_count<=0; buffer_q<=0; fill<=0;
            remaining<=0; threshold<=0; value_q<=0;
        end else begin
            awake<=1;
            if (clear) begin
                phase<=IDLE; buffer_q<=0; fill<=0; ended<=0; error_code<=0;
            end else if (needs_input && !enough) begin
                if (ended) begin error_code<=11; phase<=DONE; end
                else if (s_valid && s_ready) begin
                    buffer_q<=buffer_q | ({16'd0,s_data}<<fill);
                    fill<=fill+5'd8; byte_count<=byte_count+8'd1; ended<=s_last;
                end
            end else case (phase)
                IDLE: if (start_valid && start_ready) begin
                    alphabet_q<=alphabet; symbol_q<=0; buffer_q<=0; fill<=0;
                    byte_count<=0; ended<=0; error_code<=0; value_q<=0;
                    log_q<=0; zero_left<=0; more_zeros<=0;
                    case (alphabet)
                        0: max_symbol<=35;
                        1: max_symbol<=31;
                        2: max_symbol<=52;
                        default: max_symbol<=0;
                    endcase
                    if (alphabet==3) begin error_code<=11; phase<=DONE; end
                    else phase<=HEADER;
                end
                HEADER: begin
                    if (buffer_q[3:0]>(alphabet_q==1 ? 3 : 4)) begin
                        error_code<=11; phase<=DONE;
                    end else begin
                        log_q<=buffer_q[3:0]+4'd5;
                        nbits<=buffer_q[3:0]+4'd6;
                        threshold<=11'd32<<buffer_q[3:0];
                        remaining<=(11'd32<<buffer_q[3:0])+11'd1;
                        buffer_q<=buffer_q>>4; fill<=fill-5'd4; phase<=CONFIG;
                    end
                end
                CONFIG: if (log_ready) phase<=WIDTH;
                WIDTH: begin
                    if (remaining==1) phase<=PAD;
                    else if (remaining<threshold) begin
                        threshold<=threshold>>1; nbits<=nbits-4'd1;
                    end else phase<=SHORT;
                end
                SHORT, FULL: begin
                    if (!accepting_value) phase<=FULL;
                    else if (probability < -12'sd1 || mass>=remaining ||
                        probability>12'sd512) begin
                        error_code<=11; phase<=DONE;
                    end else begin
                        value_q<=probability[10:0]; remaining<=remaining-mass;
                        buffer_q<=buffer_q>>need; fill<=fill-{1'b0,need}; phase<=EMIT;
                    end
                end
                EMIT: if (count_ready) begin
                    if (symbol_q==max_symbol) begin
                        if (remaining!=1) error_code<=11;
                        phase<=DONE;
                    end else begin
                        symbol_q<=symbol_q+6'd1;
                        if (remaining==1) phase<=PAD;
                        else if (value_q==0) phase<=ZERO_FLAG;
                        else phase<=WIDTH;
                    end
                end
                ZERO_FLAG: begin
                    buffer_q<=buffer_q>>2; fill<=fill-5'd2;
                    zero_left<=buffer_q[1:0]; more_zeros<=buffer_q[1:0]==3;
                    if (buffer_q[1:0]==0) phase<=WIDTH;
                    else phase<=ZERO_OUT;
                end
                ZERO_OUT: if (count_ready) begin
                    if (symbol_q==max_symbol) begin error_code<=11; phase<=DONE; end
                    else begin
                        symbol_q<=symbol_q+6'd1; zero_left<=zero_left-2'd1;
                        if (zero_left==1) begin
                            if (more_zeros) phase<=ZERO_FLAG;
                            else phase<=WIDTH;
                        end
                    end
                end
                PAD: if (count_ready) begin
                    if (symbol_q==max_symbol) phase<=DONE;
                    else symbol_q<=symbol_q+6'd1;
                end
                DONE: if (done_ready) phase<=IDLE;
                default: begin error_code<=11; phase<=DONE; end
            endcase
        end
    end
endmodule
