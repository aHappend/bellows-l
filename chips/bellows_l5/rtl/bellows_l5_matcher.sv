module bellows_l5_matcher #(
    parameter integer MAX_BLOCK_BYTES=65536,
    parameter integer DICT_BYTES=16384
) (
    input wire clk, input wire rst_n, input wire clear,
    input wire start_valid, output wire start_ready,
    input wire [16:0] block_bytes,
    input wire use_dictionary, input wire [14:0] dictionary_bytes,
    output wire seed_en, output wire seed_chain, output wire [13:0] seed_addr,
    input wire seed_valid, input wire seed_found, input wire [13:0] seed_position,
    output wire a_en, output wire [15:0] a_addr,
    input wire a_valid, input wire [7:0] a_data,
    output wire b_en, output wire [15:0] b_addr,
    input wire b_valid, input wire [7:0] b_data,
    output wire dict_en, output wire [13:0] dict_addr,
    input wire dict_valid, input wire [7:0] dict_data,
    output wire m_valid, input wire m_ready,
    output wire [16:0] m_position, output wire [16:0] m_length,
    output wire [16:0] m_offset, output wire m_match,
    output wire done_valid, input wire done_ready, output wire [3:0] done_error
);
    localparam integer LEGAL=MAX_BLOCK_BYTES>=1 && MAX_BLOCK_BYTES<=65536 &&
        DICT_BYTES>=1 && DICT_BYTES<=16384;
    localparam [4:0] IDLE=0, SEED_REQ=1, SEED_WAIT=2, SEED_STORE=3,
        CHECK=4, KEY_REQ=5, KEY_WAIT=6, HASH=7, LOOKUP=8, CANDIDATE=9,
        COMPARE_REQ=10, COMPARE_WAIT=11, COMPARE=12, RESULT=13,
        INSERT=14, DONE=15, CANDIDATE_DONE=16, DICT_LOOKUP=17, SELECT_RESULT=18,
        CHAIN_REQ=19, CHAIN_WAIT=20;
    reg [4:0] phase;
    reg awake, dict_q, seed_present, old_valid, updating, a_seen, b_seen;
    reg checking_dictionary;
    reg [14:0] dictionary_size;
    reg [16:0] size, position, resume, length, offset, seed_q;
    reg [16:0] local_position_q;
    reg [13:0] dictionary_position_q;
    reg [16:0] best_length, best_offset;
    reg [9:0] seed_cursor, hash_q;
    reg [1:0] key_index;
    reg [31:0] prefix;
    reg [7:0] compare_a, compare_b;
    reg [3:0] error_code;
    reg [1023:0] index_owned, dictionary_owned;
    (* ramstyle="M20K", nomem2reg *) reg [7:0] index_lo [0:1023];
    (* ramstyle="M20K", nomem2reg *) reg [7:0] index_mid [0:1023];
    (* ramstyle="MLAB", nomem2reg *) reg index_hi [0:1023];
    (* ramstyle="M20K", nomem2reg *) reg [7:0] dictionary_lo [0:1023];
    (* ramstyle="M20K", nomem2reg *) reg [7:0] dictionary_hi [0:1023];
    wire [16:0] old_position=checking_dictionary ?
        {3'd0,dictionary_position_q} : local_position_q;
    wire [17:0] virtual_position={3'd0,dictionary_size}+{1'b0,position};
    wire [17:0] candidate_address={1'b0,old_position}+{1'b0,length};
    wire candidate_dictionary=candidate_address<{3'd0,dictionary_size};
    wire [17:0] source_address={1'b0,position}+{1'b0,length};
    wire [17:0] local_candidate=candidate_address-{3'd0,dictionary_size};
    wire [17:0] distance=virtual_position-{1'b0,old_position};
    wire [7:0] h0=prefix[7:0], h1={prefix[14:8],prefix[15]};
    wire [7:0] h2={prefix[21:16],prefix[23:22]};
    wire [7:0] h3={prefix[28:24],prefix[31:29]};
    wire [9:0] prefix_hash={prefix[9:8]^prefix[25:24],h0^h1^h2^h3};
    wire write_enable=rst_n && !clear &&
        (phase==LOOKUP || phase==INSERT);
    wire better_match=length>=4 &&
        (length>best_length || (length==best_length && offset<best_offset));
    assign start_ready=rst_n && awake && LEGAL && !clear && phase==IDLE;
    assign seed_en=rst_n && !clear && (phase==SEED_REQ || phase==CHAIN_REQ);
    assign seed_chain=seed_en && phase==CHAIN_REQ;
    assign seed_addr=!seed_en ? 14'd0 : seed_chain ?
        dictionary_position_q : {4'd0,seed_cursor};
    assign a_en=rst_n && !clear && (phase==KEY_REQ || phase==COMPARE_REQ);
    assign a_addr=!a_en ? 16'd0 : phase==KEY_REQ ?
        position[15:0]+{14'd0,key_index} : source_address[15:0];
    assign b_en=rst_n && !clear && phase==COMPARE_REQ && !candidate_dictionary;
    assign b_addr=b_en ? local_candidate[15:0] : 16'd0;
    assign dict_en=rst_n && !clear && phase==COMPARE_REQ && candidate_dictionary;
    assign dict_addr=dict_en ? candidate_address[13:0] : 14'd0;
    assign m_valid=rst_n && !clear && phase==RESULT;
    assign m_position=m_valid ? position : 17'd0;
    assign m_length=m_valid ? length : 17'd0;
    assign m_match=m_valid && length>=4;
    assign m_offset=m_match ? offset : 17'd0;
    assign done_valid=rst_n && !clear && phase==DONE;
    assign done_error=done_valid ? error_code : 4'd0;
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: matcher block=1..65536, dictionary=1..16384");
        end
    endgenerate
    always @(posedge clk) begin
        if (write_enable) begin
            index_lo[hash_q]<=virtual_position[7:0];
            index_mid[hash_q]<=virtual_position[15:8];
            index_hi[hash_q]<=virtual_position[16];
        end
        if (rst_n && !clear && phase==SEED_STORE && seed_present) begin
            dictionary_lo[seed_cursor]<=seed_q[7:0];
            dictionary_hi[seed_cursor]<={2'd0,seed_q[13:8]};
        end
        // LOOKUP captures the previous local entry before installing this position.
        if (rst_n && !clear && phase==LOOKUP)
            local_position_q<={index_hi[hash_q],index_mid[hash_q],index_lo[hash_q]};
        if (rst_n && !clear && phase==DICT_LOOKUP)
            dictionary_position_q<={dictionary_hi[hash_q][5:0],dictionary_lo[hash_q]};
        if (rst_n && !clear && phase==CHAIN_WAIT && seed_valid && seed_found)
            dictionary_position_q<=seed_position;
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; dict_q<=0; seed_present<=0; old_valid<=0;
            updating<=0; a_seen<=0; b_seen<=0; dictionary_size<=0;
            checking_dictionary<=0; best_length<=0; best_offset<=0;
            size<=0; position<=0; resume<=0; length<=0; offset<=0; seed_q<=0;
            seed_cursor<=0; hash_q<=0; key_index<=0; prefix<=0;
            compare_a<=0; compare_b<=0; error_code<=0; index_owned<=0;
            dictionary_owned<=0;
        end else begin
            awake<=1;
            if (clear) begin
                phase<=IDLE; index_owned<=0; dictionary_owned<=0; error_code<=0;
                checking_dictionary<=0; best_length<=0; best_offset<=0;
            end
            else case (phase)
                IDLE: if (start_valid && start_ready) begin
                    size<=block_bytes; position<=0; resume<=0; length<=0; offset<=0;
                    dict_q<=use_dictionary;
                    dictionary_size<=use_dictionary ? dictionary_bytes : 15'd0;
                    index_owned<=0; dictionary_owned<=0; seed_cursor<=0; error_code<=0;
                    updating<=0; old_valid<=0; seed_present<=0;
                    checking_dictionary<=0; best_length<=0; best_offset<=0;
                    if (block_bytes>MAX_BLOCK_BYTES ||
                        (use_dictionary && (dictionary_bytes==0 || dictionary_bytes>DICT_BYTES))) begin
                        error_code<=8; phase<=DONE;
                    end else if (use_dictionary) phase<=SEED_REQ;
                    else phase<=CHECK;
                end
                SEED_REQ: phase<=SEED_WAIT;
                SEED_WAIT: if (seed_valid) begin
                    seed_present<=seed_found; seed_q<={3'd0,seed_position};
                    if (seed_found && {1'b0,seed_position}+15'd4>dictionary_size) begin
                        error_code<=8; phase<=DONE;
                    end else phase<=SEED_STORE;
                end
                SEED_STORE: begin
                    dictionary_owned[seed_cursor]<=seed_present;
                    if (seed_cursor==1023) phase<=CHECK;
                    else begin seed_cursor<=seed_cursor+10'd1; phase<=SEED_REQ; end
                end
                CHECK: begin
                    length<=0; offset<=0; key_index<=0;
                    checking_dictionary<=0; best_length<=0; best_offset<=0;
                    if (position>=size) phase<=DONE;
                    else if ({1'b0,position}+18'd4>{1'b0,size}) begin
                        if (position<resume) position<=position+17'd1;
                        else begin length<=1; phase<=RESULT; end
                    end else begin updating<=position<resume; phase<=KEY_REQ; end
                end
                KEY_REQ: phase<=KEY_WAIT;
                KEY_WAIT: if (a_valid) begin
                    prefix[key_index*8 +: 8]<=a_data;
                    if (key_index==3) phase<=HASH;
                    else begin key_index<=key_index+2'd1; phase<=KEY_REQ; end
                end
                HASH: begin
                    hash_q<=prefix_hash;
                    if (updating) phase<=INSERT;
                    else phase<=LOOKUP;
                end
                LOOKUP: begin
                    old_valid<=index_owned[hash_q];
                    index_owned[hash_q]<=1; phase<=CANDIDATE;
                end
                DICT_LOOKUP: begin
                    old_valid<=dictionary_owned[hash_q];
                    checking_dictionary<=1; phase<=CANDIDATE;
                end
                CANDIDATE: begin
                    if (!old_valid || {1'b0,old_position}>=virtual_position ||
                        distance==0 || distance>18'd81920 ||
                        (!dict_q && old_position<{2'd0,dictionary_size})) begin
                        length<=0; phase<=CANDIDATE_DONE;
                    end else begin offset<=distance[16:0]; length<=0; phase<=COMPARE_REQ; end
                end
                COMPARE_REQ: begin a_seen<=0; b_seen<=0; phase<=COMPARE_WAIT; end
                COMPARE_WAIT: begin
                    if (a_valid) begin compare_a<=a_data; a_seen<=1; end
                    if (candidate_dictionary ? dict_valid : b_valid) begin
                        compare_b<=candidate_dictionary ? dict_data : b_data; b_seen<=1;
                    end
                    if ((a_seen || a_valid) &&
                        (b_seen || (candidate_dictionary ? dict_valid : b_valid))) phase<=COMPARE;
                end
                COMPARE: begin
                    if (compare_a!=compare_b) begin
                        phase<=CANDIDATE_DONE;
                    end else begin
                        length<=length+17'd1;
                        if (source_address+18'd1=={1'b0,size}) phase<=CANDIDATE_DONE;
                        else phase<=COMPARE_REQ;
                    end
                end
                CANDIDATE_DONE: begin
                    if (better_match) begin best_length<=length; best_offset<=offset; end
                    // Candidates are visited nearest first; a full-tail match cannot improve.
                    if (length>=4 && {1'b0,position}+{1'b0,length}=={1'b0,size})
                        phase<=SELECT_RESULT;
                    else if (dict_q && !checking_dictionary) phase<=DICT_LOOKUP;
                    else if (checking_dictionary && old_valid) phase<=CHAIN_REQ;
                    else phase<=SELECT_RESULT;
                end
                CHAIN_REQ: phase<=CHAIN_WAIT;
                CHAIN_WAIT: if (seed_valid) begin
                    if (!seed_found) phase<=SELECT_RESULT;
                    else if (seed_position>=dictionary_position_q ||
                        {1'b0,seed_position}+15'd4>dictionary_size) begin
                        error_code<=8; phase<=DONE;
                    end else begin
                        old_valid<=1; phase<=CANDIDATE;
                    end
                end
                SELECT_RESULT: begin
                    length<=best_length>=4 ? best_length : 17'd1;
                    offset<=best_offset; phase<=RESULT;
                end
                RESULT: if (m_ready) begin
                    resume<=position+length; position<=position+17'd1; phase<=CHECK;
                end
                INSERT: begin
                    index_owned[hash_q]<=1; position<=position+17'd1; phase<=CHECK;
                end
                DONE: if (done_ready) phase<=IDLE;
                default: begin error_code<=8; phase<=DONE; end
            endcase
        end
    end
endmodule
