module bellows_l5_entropy (
    input wire clk, input wire rst_n, input wire clear,
    input wire table_start_valid, output wire table_start_ready,
    input wire [1:0] table_alphabet, input wire [1:0] table_mode,
    input wire [3:0] table_requested_log, input wire [5:0] table_rle_symbol,
    input wire count_valid, output wire count_ready,
    input wire signed [10:0] count_value, input wire count_last,
    output wire table_done_valid, input wire table_done_ready,
    output wire [3:0] table_done_error,
    output wire [2:0] tables_valid, output wire [11:0] tables_log,
    input wire [2:0] init_valid, output wire [2:0] init_ready,
    input wire [26:0] init_state,
    input wire [2:0] step_valid, output wire [2:0] step_ready,
    input wire [26:0] bits, input wire [11:0] available,
    output wire [2:0] m_valid, input wire [2:0] m_ready,
    output wire [17:0] m_symbol, output wire [26:0] m_state,
    output wire [11:0] m_nbits,
    output wire [26:0] states, output wire [17:0] peek_symbol,
    output wire [11:0] peek_nbits,
    input wire enc_valid, output wire enc_ready,
    input wire [1:0] enc_alphabet, input wire [5:0] enc_symbol,
    input wire [8:0] enc_next_state, input wire enc_terminal,
    output wire enc_result_valid, input wire enc_result_ready,
    output wire [3:0] enc_error, output wire [8:0] enc_state,
    output wire [8:0] enc_bits, output wire [3:0] enc_nbits,
    output wire error_valid, output wire [3:0] error_code
);
    reg loading, encoding, fault;
    reg [1:0] load_alphabet, encode_alphabet;
    wire [2:0] builder_ready, builder_done, builder_count_ready, owned;
    wire [11:0] builder_error, logs;
    wire [26:0] addresses, bases, leaf_states;
    wire [17:0] symbols;
    wire [11:0] nbits;
    wire [2:0] leaf_init_ready, leaf_step_ready, leaf_m_valid, init_legal;
    wire encoder_ready, encoder_result_valid;
    wire [8:0] encoder_address;
    wire active=rst_n && !clear && !fault;
    wire decode_enable=active && (&owned) && !loading && !encoding &&
        !table_start_valid && !enc_valid;
    wire config_admit=active && !loading && !encoding && !(|leaf_m_valid) &&
        !(|init_valid) && !(|step_valid) && !enc_valid;
    wire encode_admit=active && !loading && !encoding && !(|leaf_m_valid) &&
        !(|init_valid) && !(|step_valid) && !table_start_valid;
    wire [1:0] safe_table_alphabet=table_alphabet==3 ? 2'd0 : table_alphabet;
    wire take_table=table_start_valid && table_start_ready;
    wire take_encoding=enc_valid && enc_ready;
    wire [1:0] encoder_select=encoding ? encode_alphabet : enc_alphabet;
    wire encoder_table_valid=encoder_select!=3 && owned[encoder_select];
    wire [3:0] encoder_log=encoder_select==3 ? 4'd0 : logs[encoder_select*4 +: 4];
    wire [5:0] encoder_symbol=encoder_select==3 ? 6'd0 : symbols[encoder_select*6 +: 6];
    wire [3:0] encoder_row_nbits=encoder_select==3 ? 4'd0 : nbits[encoder_select*4 +: 4];
    wire [8:0] encoder_row_base=encoder_select==3 ? 9'd0 : bases[encoder_select*9 +: 9];
    wire leaf_reset_n=rst_n && !clear;
    assign table_start_ready=config_admit && builder_ready[safe_table_alphabet];
    assign count_ready=active && loading && builder_count_ready[load_alphabet];
    assign table_done_valid=rst_n && !clear && loading && builder_done[load_alphabet];
    assign table_done_error=table_done_valid ? builder_error[load_alphabet*4 +: 4] : 4'd0;
    assign tables_valid=rst_n && !clear ? owned : 3'd0;
    assign tables_log=rst_n && !clear ? logs : 12'd0;
    assign init_ready=leaf_init_ready & init_legal & {3{decode_enable}};
    assign step_ready=leaf_step_ready & {3{decode_enable}};
    assign m_valid=leaf_m_valid & {3{rst_n && !clear}};
    assign states=rst_n && !clear ? leaf_states : 27'd0;
    assign peek_symbol=decode_enable ? symbols : 18'd0;
    assign peek_nbits=decode_enable ? nbits : 12'd0;
    assign enc_ready=encode_admit && encoder_ready;
    assign enc_result_valid=rst_n && !clear && encoding && encoder_result_valid;
    assign error_valid=rst_n && !clear && fault;
    assign error_code=error_valid ? 4'd11 : 4'd0;
    genvar i;
    generate
        for (i=0;i<3;i=i+1) begin : tables
            assign addresses[i*9 +: 9]=encoding && encode_alphabet==i ?
                encoder_address : leaf_states[i*9 +: 9];
            assign init_legal[i]={1'b0,init_state[i*9 +: 9]}<
                (10'd1<<logs[i*4 +: 4]);
            bellows_l5_fse_table builder (
                .clk(clk), .rst_n(rst_n), .clear(clear),
                .start_valid(take_table && safe_table_alphabet==i),
                .start_ready(builder_ready[i]),
                .alphabet(table_alphabet), .mode(table_mode),
                .requested_log(table_requested_log), .rle_symbol(table_rle_symbol),
                .count_valid(count_valid && loading && load_alphabet==i && !fault),
                .count_ready(builder_count_ready[i]), .count_value(count_value),
                .count_last(count_last), .done_valid(builder_done[i]),
                .done_ready(table_done_ready && loading && load_alphabet==i),
                .done_error(builder_error[i*4 +: 4]), .table_valid(owned[i]),
                .table_log(logs[i*4 +: 4]), .row_address(addresses[i*9 +: 9]),
                .row_symbol(symbols[i*6 +: 6]), .row_nbits(nbits[i*4 +: 4]),
                .row_base(bases[i*9 +: 9])
            );
        end
    endgenerate
    bellows_l5_fse_decoder fse_ll_decoder (
        .clk(clk), .rst_n(leaf_reset_n),
        .init_valid(init_valid[0] && decode_enable && init_legal[0]),
        .init_ready(leaf_init_ready[0]), .init_state(init_state[0 +: 9]),
        .state(leaf_states[0 +: 9]),
        .step_valid(step_valid[0] && decode_enable), .step_ready(leaf_step_ready[0]),
        .bits(bits[0 +: 9]), .available(available[0 +: 4]),
        .row_symbol(symbols[0 +: 6]), .row_nbits(nbits[0 +: 4]),
        .row_base(bases[0 +: 9]), .m_valid(leaf_m_valid[0]), .m_ready(m_ready[0]),
        .m_symbol(m_symbol[0 +: 6]), .m_state(m_state[0 +: 9]), .m_nbits(m_nbits[0 +: 4])
    );
    bellows_l5_fse_decoder fse_of_decoder (
        .clk(clk), .rst_n(leaf_reset_n),
        .init_valid(init_valid[1] && decode_enable && init_legal[1]),
        .init_ready(leaf_init_ready[1]), .init_state(init_state[9 +: 9]),
        .state(leaf_states[9 +: 9]),
        .step_valid(step_valid[1] && decode_enable), .step_ready(leaf_step_ready[1]),
        .bits(bits[9 +: 9]), .available(available[4 +: 4]),
        .row_symbol(symbols[6 +: 6]), .row_nbits(nbits[4 +: 4]),
        .row_base(bases[9 +: 9]), .m_valid(leaf_m_valid[1]), .m_ready(m_ready[1]),
        .m_symbol(m_symbol[6 +: 6]), .m_state(m_state[9 +: 9]), .m_nbits(m_nbits[4 +: 4])
    );
    bellows_l5_fse_decoder fse_ml_decoder (
        .clk(clk), .rst_n(leaf_reset_n),
        .init_valid(init_valid[2] && decode_enable && init_legal[2]),
        .init_ready(leaf_init_ready[2]), .init_state(init_state[18 +: 9]),
        .state(leaf_states[18 +: 9]),
        .step_valid(step_valid[2] && decode_enable), .step_ready(leaf_step_ready[2]),
        .bits(bits[18 +: 9]), .available(available[8 +: 4]),
        .row_symbol(symbols[12 +: 6]), .row_nbits(nbits[8 +: 4]),
        .row_base(bases[18 +: 9]), .m_valid(leaf_m_valid[2]), .m_ready(m_ready[2]),
        .m_symbol(m_symbol[12 +: 6]), .m_state(m_state[18 +: 9]), .m_nbits(m_nbits[8 +: 4])
    );
    bellows_l5_fse_encoder encoder (
        .clk(clk), .rst_n(rst_n), .clear(clear),
        .table_valid(encoder_table_valid), .table_log(encoder_log),
        .s_valid(take_encoding), .s_ready(encoder_ready),
        .s_symbol(enc_symbol), .s_next_state(enc_next_state), .s_terminal(enc_terminal),
        .row_address(encoder_address), .row_symbol(encoder_symbol),
        .row_nbits(encoder_row_nbits), .row_base(encoder_row_base),
        .m_valid(encoder_result_valid), .m_ready(enc_result_ready && encoding),
        .m_error(enc_error), .m_state(enc_state), .m_bits(enc_bits), .m_nbits(enc_nbits)
    );
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            loading<=0; encoding<=0; fault<=0; load_alphabet<=0; encode_alphabet<=0;
        end else if (clear) begin
            loading<=0; encoding<=0; fault<=0; load_alphabet<=0; encode_alphabet<=0;
        end else begin
            if (take_table) begin
                loading<=1; load_alphabet<=safe_table_alphabet;
                if (table_mode==3 || table_alphabet==3) fault<=1;
            end
            if (table_done_valid) begin
                if (table_done_error!=0) fault<=1;
                if (table_done_ready) loading<=0;
            end
            if (take_encoding) begin encoding<=1; encode_alphabet<=enc_alphabet; end
            if (enc_result_valid && enc_result_ready) encoding<=0;
            if (decode_enable && (|(init_valid & ~init_legal))) fault<=1;
        end
    end
endmodule
