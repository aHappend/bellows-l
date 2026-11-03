module bellows_l5_fse_table (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire [1:0] alphabet, input wire [1:0] mode,
    input wire [3:0] requested_log, input wire [5:0] rle_symbol,
    input wire count_valid, output wire count_ready,
    input wire signed [10:0] count_value, input wire count_last,
    output wire done_valid, input wire done_ready,
    output wire [3:0] done_error,
    output wire table_valid, output wire [3:0] table_log,
    input wire [8:0] row_address,
    output wire [5:0] row_symbol, output wire [3:0] row_nbits,
    output wire [8:0] row_base
);
    localparam [3:0] IDLE=0, CLEAR=1, COUNTS=2, CHECK=3, RESERVE=4,
        SPREAD=5, ADVANCE=6, ROW_LOAD=7, ROW_LOG=8, ROW_STORE=9,
        RLE=10, COMMIT=11, DONE=12;
    reg [3:0] phase;
    reg awake, owned;
    reg [1:0] selected_alphabet, selected_mode;
    reg [3:0] log_q, error_code;
    reg [5:0] symbol_index, max_symbol, rle_q;
    reg [6:0] nonzero;
    reg [11:0] total;
    reg [9:0] table_size, high_threshold, position, remaining, row_index;
    reg [9:0] row_next, logarithm_work;
    reg [3:0] row_bits;
    reg [5:0] row_code;
    (* ramstyle="MLAB", nomem2reg *) reg signed [10:0] counts [0:63];
    (* ramstyle="MLAB", nomem2reg *) reg [9:0] symbol_next [0:63];
    (* ramstyle="MLAB", nomem2reg *) reg [5:0] symbols [0:511];
    (* ramstyle="MLAB", nomem2reg *) reg [3:0] bit_counts [0:511];
    (* ramstyle="MLAB", nomem2reg *) reg [8:0] bases [0:511];
    reg signed [10:0] predefined_count;
    wire signed [10:0] incoming_count=selected_mode==0 ? predefined_count : count_value;
    wire [10:0] mass=incoming_count==-11'sd1 ? 11'd1 : incoming_count[10:0];
    wire [11:0] next_total=total+{1'b0,mass};
    wire [9:0] spread_step=(table_size>>1)+(table_size>>3)+10'd3;
    wire [9:0] next_position=(position+spread_step) & (table_size-10'd1);
    wire [18:0] base_value=({9'd0,row_next}<<row_bits)-{9'd0,table_size};
    wire valid_row=table_valid && {1'b0,row_address}<table_size;
    wire take_count=phase==COUNTS &&
        (selected_mode==0 || (count_valid && count_ready));
    assign start_ready=rst_n && awake && !clear && phase==IDLE;
    assign count_ready=rst_n && !clear && phase==COUNTS && selected_mode==2;
    assign done_valid=rst_n && !clear && phase==DONE;
    assign done_error=done_valid ? error_code : 4'd0;
    assign table_valid=rst_n && !clear && owned;
    assign table_log=table_valid ? log_q : 4'd0;
    assign row_symbol=valid_row ? symbols[row_address] : 6'd0;
    assign row_nbits=valid_row ? bit_counts[row_address] : 4'd0;
    assign row_base=valid_row ? bases[row_address] : 9'd0;
    always @* begin
        predefined_count=0;
        case (selected_alphabet)
            0: begin
                if (symbol_index==0) predefined_count=4;
                else if (symbol_index==1 || symbol_index==25) predefined_count=3;
                else if ((symbol_index>=2 && symbol_index<=12) ||
                         (symbol_index>=16 && symbol_index<=24) ||
                         symbol_index==26) predefined_count=2;
                else if (symbol_index>=32 && symbol_index<=35) predefined_count=-1;
                else if (symbol_index<=35) predefined_count=1;
            end
            1: begin
                if (symbol_index>=6 && symbol_index<=8) predefined_count=2;
                else if (symbol_index>=24 && symbol_index<=28) predefined_count=-1;
                else if (symbol_index<=23) predefined_count=1;
            end
            2: begin
                if (symbol_index==1) predefined_count=4;
                else if (symbol_index==2) predefined_count=3;
                else if (symbol_index>=3 && symbol_index<=8) predefined_count=2;
                else if (symbol_index>=46 && symbol_index<=52) predefined_count=-1;
                else if (symbol_index<=45) predefined_count=1;
            end
            default: predefined_count=0;
        endcase
    end
    always @(posedge clk) begin
        if (rst_n && !clear) begin
            if (phase==CLEAR) begin
                counts[symbol_index]<=0; symbol_next[symbol_index]<=0;
            end
            if (take_count && incoming_count>=-11'sd1 &&
                incoming_count<=11'sd512 && next_total<={2'd0,table_size}) begin
                counts[symbol_index]<=incoming_count;
                symbol_next[symbol_index]<=mass[9:0];
            end
            if (phase==RESERVE && counts[symbol_index]==-11'sd1)
                symbols[high_threshold[8:0]]<=symbol_index;
            if (phase==SPREAD && counts[symbol_index]>0 && remaining!=0)
                symbols[position[8:0]]<=symbol_index;
            if (phase==ROW_STORE) begin
                bit_counts[row_index[8:0]]<=row_bits;
                bases[row_index[8:0]]<=base_value[8:0];
                symbol_next[row_code]<=row_next+10'd1;
            end
            if (phase==RLE) begin
                symbols[0]<=rle_q; bit_counts[0]<=0; bases[0]<=0;
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; owned<=0; selected_alphabet<=0;
            selected_mode<=0; log_q<=0; error_code<=0; symbol_index<=0;
            max_symbol<=0; rle_q<=0; nonzero<=0; total<=0; table_size<=0;
            high_threshold<=0; position<=0; remaining<=0; row_index<=0;
            row_next<=0; logarithm_work<=0; row_bits<=0; row_code<=0;
        end else begin
            awake<=1;
            if (clear) begin
                phase<=IDLE; owned<=0; error_code<=0;
            end else case (phase)
                IDLE: if (start_valid && start_ready) begin
                    owned<=0; error_code<=0; selected_alphabet<=alphabet;
                    selected_mode<=mode; rle_q<=rle_symbol;
                    symbol_index<=0; nonzero<=0; total<=0; position<=0;
                    remaining<=0; row_index<=0;
                    case (alphabet)
                        0: max_symbol<=35;
                        1: max_symbol<=31;
                        2: max_symbol<=52;
                        default: max_symbol<=0;
                    endcase
                    if (mode==0) begin
                        log_q<=alphabet==1 ? 4'd5 : 4'd6;
                        table_size<=alphabet==1 ? 10'd32 : 10'd64;
                    end else begin
                        log_q<=requested_log; table_size<=10'd1<<requested_log;
                    end
                    if (alphabet==3 || mode==3 ||
                        (mode==2 && (requested_log<5 ||
                            requested_log>(alphabet==1 ? 8 : 9))) ||
                        (mode==1 && rle_symbol>(alphabet==0 ? 35 :
                            alphabet==1 ? 31 : 52))) begin
                        error_code<=11; phase<=DONE;
                    end else if (mode==1) begin
                        log_q<=0; table_size<=1; phase<=RLE;
                    end else phase<=CLEAR;
                end
                CLEAR: begin
                    if (symbol_index==63) begin symbol_index<=0; phase<=COUNTS; end
                    else symbol_index<=symbol_index+6'd1;
                end
                COUNTS: if (take_count) begin
                    if (incoming_count < -11'sd1 || incoming_count>11'sd512 ||
                        next_total>{2'd0,table_size} ||
                        (selected_mode==2 && count_last!=(symbol_index==max_symbol))) begin
                        error_code<=11; phase<=DONE;
                    end else begin
                        total<=next_total;
                        if (incoming_count!=0) nonzero<=nonzero+7'd1;
                        if (symbol_index==max_symbol) phase<=CHECK;
                        else symbol_index<=symbol_index+6'd1;
                    end
                end
                CHECK: begin
                    if (total!={2'd0,table_size} || nonzero<2) begin
                        error_code<=11; phase<=DONE;
                    end else begin
                        symbol_index<=0; high_threshold<=table_size-10'd1;
                        phase<=RESERVE;
                    end
                end
                RESERVE: begin
                    if (counts[symbol_index]==-11'sd1)
                        high_threshold<=high_threshold-10'd1;
                    if (symbol_index==max_symbol) begin
                        symbol_index<=0; remaining<=0; phase<=SPREAD;
                    end else symbol_index<=symbol_index+6'd1;
                end
                SPREAD: begin
                    if (symbol_index>max_symbol) begin
                        if (position!=0) begin error_code<=11; phase<=DONE; end
                        else begin row_index<=0; phase<=ROW_LOAD; end
                    end else if (counts[symbol_index]<=0) begin
                        symbol_index<=symbol_index+6'd1;
                    end else if (remaining==0) begin
                        remaining<=counts[symbol_index][9:0];
                    end else begin
                        remaining<=remaining-10'd1; position<=next_position; phase<=ADVANCE;
                    end
                end
                ADVANCE: begin
                    if (position>high_threshold) position<=next_position;
                    else begin
                        if (remaining==0) symbol_index<=symbol_index+6'd1;
                        phase<=SPREAD;
                    end
                end
                ROW_LOAD: begin
                    row_code<=symbols[row_index[8:0]];
                    row_next<=symbol_next[symbols[row_index[8:0]]];
                    logarithm_work<=symbol_next[symbols[row_index[8:0]]];
                    row_bits<=log_q; phase<=ROW_LOG;
                end
                ROW_LOG: begin
                    if (logarithm_work>=2) begin
                        logarithm_work<=logarithm_work>>1; row_bits<=row_bits-4'd1;
                    end else phase<=ROW_STORE;
                end
                ROW_STORE: begin
                    if (row_index+10'd1==table_size) phase<=COMMIT;
                    else begin row_index<=row_index+10'd1; phase<=ROW_LOAD; end
                end
                RLE: phase<=COMMIT;
                COMMIT: begin owned<=1; phase<=DONE; end
                DONE: if (done_ready) phase<=IDLE;
                default: begin owned<=0; error_code<=11; phase<=DONE; end
            endcase
        end
    end
endmodule
