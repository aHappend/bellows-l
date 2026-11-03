module bellows_l5_dictionary #(
    parameter integer DICT_BYTES=16384
) (
    input wire clk, input wire rst_n, input wire idle_all,
    input wire dict_begin_valid, output wire dict_begin_ready,
    input wire [31:0] dict_begin_id, input wire [14:0] dict_begin_bytes,
    input wire dict_s_valid, output wire dict_s_ready,
    input wire [7:0] dict_s_data, input wire dict_s_last,
    output wire dict_status_valid, input wire dict_status_ready,
    output wire [3:0] dict_status_error,
    output wire dict_loaded, output wire [31:0] dict_id,
    output wire [14:0] dict_size,
    input wire [3:0] rd_en, input wire [55:0] rd_addr,
    output wire [3:0] rd_valid, output wire [31:0] rd_data,
    input wire [3:0] index_en, input wire [3:0] index_chain,
    input wire [55:0] index_addr,
    output wire [3:0] index_valid, output wire [3:0] index_found,
    output wire [55:0] index_position
);
    localparam integer LEGAL=DICT_BYTES>=1 && DICT_BYTES<=16384;
    localparam integer DEPTH=LEGAL ? DICT_BYTES : 1;
    localparam [2:0] IDLE=0, LOAD=1, HASH=2, INDEX=3, PIN=4, STATUS=5;
    reg [2:0] phase;
    reg awake, loaded;
    reg [31:0] pinned_id, pending_id;
    reg [14:0] pinned_size, pending_size, received;
    reg [3:0] error_code;
    reg [31:0] prefix;
    reg [9:0] hash_value;
    reg final_byte;
    reg [1023:0] seed_valid;
    wire [7:0] h0=prefix[7:0];
    wire [7:0] h1={prefix[14:8],prefix[15]};
    wire [7:0] h2={prefix[21:16],prefix[23:22]};
    wire [7:0] h3={prefix[28:24],prefix[31:29]};
    wire [9:0] prefix_hash={prefix[9:8]^prefix[25:24],h0^h1^h2^h3};
    wire take_begin=dict_begin_valid && dict_begin_ready;
    wire take_byte=dict_s_valid && dict_s_ready;
    wire [13:0] seed_position=received[13:0]-14'd4;
    assign dict_begin_ready=rst_n && awake && LEGAL && phase==IDLE && idle_all;
    assign dict_s_ready=rst_n && awake && LEGAL && phase==LOAD;
    assign dict_status_valid=rst_n && phase==STATUS;
    assign dict_status_error=dict_status_valid ? error_code : 4'd0;
    assign dict_loaded=rst_n && loaded;
    assign dict_id=dict_loaded ? pinned_id : 32'd0;
    assign dict_size=dict_loaded ? pinned_size : 15'd0;
    genvar lane;
    generate
        if (!LEGAL) begin : invalid_parameter
            initial $fatal(1,"PARAMETER ERROR: DICT_BYTES=1..16384");
        end
        for (lane=0;lane<4;lane=lane+1) begin : views
            (* ramstyle="M20K", nomem2reg *) reg [7:0] image [0:DEPTH-1];
            (* ramstyle="MLAB", nomem2reg *) reg [13:0] seeds [0:1023];
            (* ramstyle="M20K", nomem2reg *) reg [7:0] previous_lo [0:DEPTH-1];
            (* ramstyle="M20K", nomem2reg *) reg [7:0] previous_hi [0:DEPTH-1];
            reg [7:0] byte_q;
            reg [13:0] seed_q;
            reg [7:0] previous_lo_q, previous_hi_q;
            reg byte_valid_q, index_valid_q, found_q, chain_q, chain_address_valid_q;
            wire [13:0] byte_addr=rd_addr[lane*14 +: 14];
            wire [13:0] lookup_addr=index_addr[lane*14 +: 14];
            wire [9:0] seed_addr=lookup_addr[9:0];
            wire read_image=rd_en[lane] && loaded && phase==IDLE &&
                !take_begin && {1'b0,byte_addr}<pinned_size;
            wire read_index=index_en[lane] && loaded && phase==IDLE && !take_begin;
            wire chain_address_valid={2'd0,lookup_addr}+16'd4<={1'b0,pinned_size};
            always @(posedge clk) begin
                if (take_byte) image[received]<=dict_s_data;
                if (rst_n && phase==HASH) seed_q<=seeds[prefix_hash];
                if (rst_n && phase==INDEX) begin
                    previous_lo[seed_position]<=seed_q[7:0];
                    previous_hi[seed_position]<={1'b0,seed_valid[hash_value],seed_q[13:8]};
                    seeds[hash_value]<=seed_position;
                end
                if (rst_n && read_image) byte_q<=image[byte_addr];
                if (rst_n && read_index) begin
                    if (!index_chain[lane]) seed_q<=seeds[seed_addr];
                    else if (chain_address_valid) begin
                        previous_lo_q<=previous_lo[lookup_addr];
                        previous_hi_q<=previous_hi[lookup_addr];
                    end
                end
            end
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    byte_valid_q<=0; index_valid_q<=0; found_q<=0;
                    chain_q<=0; chain_address_valid_q<=0;
                end else begin
                    byte_valid_q<=read_image;
                    index_valid_q<=read_index;
                    found_q<=read_index && seed_valid[seed_addr];
                    chain_q<=read_index && index_chain[lane];
                    chain_address_valid_q<=read_index && chain_address_valid;
                end
            end
            assign rd_valid[lane]=rst_n && byte_valid_q;
            assign rd_data[lane*8 +: 8]=rd_valid[lane] ? byte_q : 8'd0;
            assign index_valid[lane]=rst_n && index_valid_q;
            assign index_found[lane]=index_valid[lane] &&
                (chain_q ? chain_address_valid_q && previous_hi_q[6] : found_q);
            assign index_position[lane*14 +: 14]=!index_found[lane] ? 14'd0 :
                chain_q ? {previous_hi_q[5:0],previous_lo_q} : seed_q;
        end
    endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=IDLE; awake<=0; loaded<=0; pinned_id<=0; pending_id<=0;
            pinned_size<=0; pending_size<=0; received<=0; error_code<=0;
            prefix<=0; hash_value<=0; final_byte<=0; seed_valid<=0;
        end else begin
            awake<=1;
            case (phase)
                IDLE: if (take_begin) begin
                    loaded<=0; pinned_id<=0; pinned_size<=0;
                    seed_valid<=0; received<=0; prefix<=0; error_code<=0;
                    pending_id<=dict_begin_id; pending_size<=dict_begin_bytes;
                    if (dict_begin_id==0 || dict_begin_bytes==0 ||
                        dict_begin_bytes>DEPTH) begin
                        error_code<=8; phase<=STATUS;
                    end else phase<=LOAD;
                end
                LOAD: if (take_byte) begin
                    received<=received+15'd1;
                    prefix<={dict_s_data,prefix[31:8]};
                    final_byte<=received+15'd1==pending_size;
                    if (dict_s_last!=(received+15'd1==pending_size)) begin
                        error_code<=8; phase<=STATUS;
                    end else if (received>=3) phase<=HASH;
                    else if (dict_s_last) phase<=PIN;
                end
                HASH: begin hash_value<=prefix_hash; phase<=INDEX; end
                INDEX: begin
                    seed_valid[hash_value]<=1;
                    if (final_byte) phase<=PIN;
                    else phase<=LOAD;
                end
                PIN: begin
                    loaded<=1; pinned_id<=pending_id; pinned_size<=pending_size;
                    phase<=STATUS;
                end
                STATUS: if (dict_status_valid && dict_status_ready) phase<=IDLE;
                default: begin
                    loaded<=0; error_code<=8; phase<=STATUS;
                end
            endcase
        end
    end
endmodule
