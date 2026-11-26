module Role_BellowsL2 #(
    parameter integer MAX_BLOCK_BYTES = 65536
) (
    input wire clk, reset,
    input wire reg_read, reg_write,
    input wire [17:0] reg_addr,
    input wire [63:0] reg_wdata,
    output logic [63:0] reg_rdata,
    output logic reg_rvalid,
    output wire [31:0] role_id, role_version, role_status,
    input wire ddr_clk, ddr_reset, amm_ready,
    output wire amm_read, amm_write,
    output wire [25:0] amm_address,
    input wire [511:0] amm_readdata,
    output wire [511:0] amm_writedata,
    output wire [6:0] amm_burstcount,
    output wire [63:0] amm_byteenable,
    input wire amm_readdatavalid,
    output wire dma_cmd_valid, dma_cmd_write,
    input wire dma_cmd_ready,
    output wire [63:0] dma_cmd_addr,
    output wire [25:0] dma_cmd_bytes,
    input wire dma_cpl_valid, dma_cpl_error, dma_abort,
    output wire dma_cpl_ready,
    output wire dma_tx_valid, dma_tx_last,
    input wire dma_tx_ready,
    output wire [127:0] dma_tx_data,
    output wire [15:0] dma_tx_keep,
    input wire dma_rx_valid, dma_rx_last,
    output wire dma_rx_ready,
    input wire [127:0] dma_rx_data,
    input wire [15:0] dma_rx_keep
);
    localparam logic [63:0] MAGIC = 64'h4245_4C4C_4F57_4C32;
    localparam logic [31:0] ROLE_ID = 32'h0002_424D;
    localparam logic [31:0] ROLE_VERSION = 32'h0002_0000;
    localparam logic [32:0] DDR_LIMIT = 33'h1_0000_0000;
    localparam logic [1:0] COMPRESS = 0, DECODE = 1, ROUNDTRIP = 2;
    localparam logic [7:0] INVALID = 1, BUSY_CMD = 2, ABORTED = 3, CAPACITY = 4;

    typedef enum logic [4:0] {
        IDLE, LIMITS, VALIDATE, FETCH_ADDR, FETCH_SIZE, FETCH, FETCH_WAIT,
        STAGE, STAGE_WAIT, COMPUTE, SEND_ADDR, SEND_SIZE, GATHER, GATHER_WAIT,
        MERGE, MERGE_WAIT, SEND, SEND_WAIT, COMPLETE, ABORT_DRAIN, WINDOW, WINDOW_WAIT
    } state_t;
    state_t state;
    wire rst_n;
    bellows_l1_reset_sync control_release(clk, reset, rst_n);

    logic [63:0] descriptor [4:10];
    logic busy, done, resident;
    logic [7:0] completion, job_code;
    logic [63:0] cycles, pcie_bytes, ddr_bytes;
    logic [63:0] pcie_native_bytes /* synthesis noprune */;
    logic [63:0] ddr_native_bytes /* synthesis noprune */;
    logic [31:0] produced, delivered;
    logic [1:0] mode;
    logic [63:0] host_src, host_dst;
    logic [31:0] bytes_in, capacity;
    logic [25:0] ddr_src, ddr_dst;
    logic bad_shape;
    logic [64:0] host_src_end, host_dst_end;
    logic [32:0] ddr_src_end, ddr_dst_end;

    logic [63:0] window_cursor;
    logic [511:0] window_data;
    logic window_busy, window_done, window_error, window_write;
    wire locked = busy || window_busy;
    wire control = reg_write && reg_addr == 18'h2;
    wire clear = control && reg_wdata[1];
    wire cancel = control && reg_wdata[2];
    wire dma_start = control && reg_wdata[0];
    wire resident_start = control && reg_wdata[3];
    wire start = (dma_start || resident_start) && !cancel;
    wire config_write = reg_write && reg_addr >= 18'h4 && reg_addr <= 18'ha;
    wire window_cursor_write = reg_write && reg_addr == 18'h12;
    wire window_lane_write = reg_write && reg_addr >= 18'h18 && reg_addr <= 18'h1f;
    wire window_request = reg_write && reg_addr == 18'h13 && (|reg_wdata[1:0]);
    wire window_cursor_ok = window_cursor[5:0] == 0 && window_cursor[63:32] == 0;
    wire reserved_window_write = window_request || window_cursor_write || window_lane_write;
    wire rejected_busy = locked && (start || config_write || reserved_window_write);

    assign role_id = ROLE_ID;
    assign role_version = ROLE_VERSION;
    assign role_status = {29'd0, completion != 0, done, busy};

    function automatic [32:0] padded_extent(input [31:0] count);
        return ({1'b0, count} + 33'd3) & 33'h1_ffff_fffc;
    endfunction

    wire ddr_overlap = bytes_in != 0 && capacity != 0 &&
        ddr_src_end > {1'b0, ddr_dst, 6'b0} && ddr_dst_end > {1'b0, ddr_src, 6'b0};
    wire host_overlap = bytes_in != 0 && capacity != 0 &&
        host_src_end > {1'b0, host_dst} && host_dst_end > {1'b0, host_src};
    wire descriptor_valid = !bad_shape &&
        ddr_src_end <= DDR_LIMIT && ddr_dst_end <= DDR_LIMIT && !ddr_overlap &&
        (resident || (!host_src_end[64] && !host_dst_end[64] && !host_overlap));

    wire ddr_online, ddr_cmd_ready, ddr_rsp_valid;
    logic ddr_pending, ddr_valid, ddr_write;
    logic [25:0] ddr_address;
    logic [511:0] ddr_data;
    logic [63:0] ddr_mask;
    wire [511:0] ddr_rsp_data;
    wire dma_start_ready, dma_idle, dma_result_valid, dma_result_error;
    wire [1023:0] dma_result_data;
    wire transport_lost = busy && state != LIMITS && state != VALIDATE &&
        state != COMPLETE && (!ddr_online || (!resident && dma_abort));
    wire window_lost = window_busy && !ddr_online;
    wire stop_issue = cancel || transport_lost || window_lost || state == ABORT_DRAIN;
    wire ddr_cmd_valid = rst_n && ddr_online && !stop_issue && !ddr_pending && ddr_valid;
    wire ddr_fire = ddr_cmd_valid && ddr_cmd_ready;

    bellows_l1_ddr ddr (
        .clk(clk), .reset(reset), .online(ddr_online),
        .cmd_valid(ddr_cmd_valid), .cmd_write(ddr_write), .cmd_ready(ddr_cmd_ready),
        .cmd_address(ddr_address), .cmd_data(ddr_data), .cmd_mask(ddr_mask),
        .rsp_valid(ddr_rsp_valid), .rsp_data(ddr_rsp_data),
        .ddr_clk(ddr_clk), .ddr_reset(ddr_reset), .amm_ready(amm_ready),
        .amm_read(amm_read), .amm_write(amm_write), .amm_address(amm_address),
        .amm_readdata(amm_readdata), .amm_writedata(amm_writedata),
        .amm_burstcount(amm_burstcount), .amm_byteenable(amm_byteenable),
        .amm_readdatavalid(amm_readdatavalid)
    );

    logic [31:0] transfer_pos;
    logic [63:0] chunk_addr;
    logic [7:0] chunk_len, chunk_padded, chunk_pos;
    logic [1023:0] chunk_data;
    wire [31:0] chunk_left = (state == FETCH_SIZE ? bytes_in : produced) - transfer_pos;
    wire [12:0] page_left = 13'd4096 - {1'b0, chunk_addr[11:0]};
    wire [7:0] chunk_limit = page_left >= 13'd128 ? 8'd128 : page_left[7:0];
    wire [7:0] chunk_size = chunk_left >= {24'd0, chunk_limit} ? chunk_limit : chunk_left[7:0];
    wire [7:0] chunk_remaining = chunk_len - chunk_pos;
    wire [7:0] part_limit = transfer_pos[5] ? 8'd32 : 8'd64;
    wire [7:0] part_size = chunk_remaining < part_limit ? chunk_remaining : part_limit;
    // Read only the aligned native word group containing the last DWORD;
    // the bytes above the logical end must be written back unchanged.
    wire [7:0] merge_offset = {chunk_len[7:5], 5'b0};
    wire [7:0] merge_bytes = chunk_padded - merge_offset;
    wire merge_active = state == MERGE || state == MERGE_WAIT;
    wire [63:0] dma_address = merge_active ? chunk_addr + {56'd0, merge_offset} : chunk_addr;
    wire [7:0] dma_bytes = merge_active ? merge_bytes : chunk_padded;
    wire [1:0] lane = chunk_pos[6:5];
    wire [1:0] next_lane = lane + 2'd1;
    wire [255:0] stage_lo = chunk_data[256*lane +: 256];
    wire [255:0] stage_hi = chunk_data[256*next_lane +: 256];
    wire [255:0] gather_lo = transfer_pos[5] ? ddr_rsp_data[511:256] : ddr_rsp_data[255:0];
    wire [63:0] stage_mask = 64'hffff_ffff_ffff_ffff >> (8'd64 - part_size);
    wire [31:0] next_transfer = transfer_pos + {24'd0, part_size};
    wire final_part = part_size == chunk_remaining;

    bellows_l2_dma dma (
        .clk(clk), .rst_n(rst_n), .cancel(stop_issue),
        .start_valid(state == FETCH || state == MERGE || state == SEND),
        .start_write(state == SEND), .start_ready(dma_start_ready), .idle(dma_idle),
        .start_addr(dma_address), .start_bytes(dma_bytes), .start_data(chunk_data),
        .result_valid(dma_result_valid), .result_error(dma_result_error), .result_data(dma_result_data),
        .dma_cmd_valid(dma_cmd_valid), .dma_cmd_write(dma_cmd_write), .dma_cmd_ready(dma_cmd_ready),
        .dma_cmd_addr(dma_cmd_addr), .dma_cmd_bytes(dma_cmd_bytes),
        .dma_cpl_valid(dma_cpl_valid), .dma_cpl_error(dma_cpl_error), .dma_cpl_ready(dma_cpl_ready),
        .dma_abort(dma_abort),
        .dma_tx_valid(dma_tx_valid), .dma_tx_last(dma_tx_last), .dma_tx_ready(dma_tx_ready),
        .dma_tx_data(dma_tx_data), .dma_tx_keep(dma_tx_keep),
        .dma_rx_valid(dma_rx_valid), .dma_rx_last(dma_rx_last), .dma_rx_ready(dma_rx_ready),
        .dma_rx_data(dma_rx_data), .dma_rx_keep(dma_rx_keep)
    );

    logic core_run, empty_sent, c_seen, d_seen, cap_failed;
    logic [2:0] c_error, d_error;
    logic [31:0] fetched, consumed, stored;
    logic [511:0] input_beat [0:1];
    wire [511:0] output_beat [0:1];
    logic mem_write;
    logic [6:0] mem_count;
    wire c_ready, d_ready, c_valid, d_valid;
    wire c_status, d_status;
    wire [7:0] c_data, d_data;
    wire [2:0] c_result, d_result;
    wire core_done = (mode == DECODE || c_seen) &&
        (mode == COMPRESS || (mode == ROUNDTRIP && c_error != 0) || d_seen);
    wire core_finished = core_done || cap_failed;
    wire [31:0] fetch_remaining = bytes_in - fetched;
    wire [6:0] input_read_size = fetch_remaining >= 32'd64 ? 7'd64 : fetch_remaining[6:0];
    wire [1:0] input_queued = fetched[7:6] - consumed[7:6];
    wire [7:0] output_pending = produced[7:0] - stored[7:0];
    wire [6:0] output_write_size = output_pending >= 8'd64 ? 7'd64 : output_pending[6:0];
    wire need_input = !core_finished && fetched != bytes_in && input_queued < 2;
    wire need_output = output_pending >= 8'd64 || (core_finished && output_pending != 0);
    wire [7:0] source_data = input_beat[consumed[6]][8*consumed[5:0] +: 8];
    wire source_valid = core_run && !stop_issue &&
        (fetched != consumed || (bytes_in == 0 && !empty_sent));
    wire source_last = bytes_in == 0 || consumed + 32'd1 == bytes_in;
    wire source_fire = source_valid && (mode == DECODE ? d_ready : c_ready);
    wire sink_valid = mode == COMPRESS ? c_valid : d_valid;
    wire [7:0] sink_data = mode == COMPRESS ? c_data : d_data;
    wire capacity_hit = produced == capacity;
    wire sink_ready = core_run && !stop_issue && output_pending < 8'd128 && !capacity_hit;
    wire sink_fire = sink_valid && sink_ready;

    bellows_l2_top #(.MAX_BLOCK_BYTES(MAX_BLOCK_BYTES)) core (
        .clk(clk), .rst_n(core_run), .roundtrip_enable(mode == ROUNDTRIP),
        .c_s_data(source_data), .c_s_keep(bytes_in != 0),
        .c_s_valid(source_valid && mode != DECODE), .c_s_last(source_last), .c_s_ready(c_ready),
        .c_m_data(c_data), .c_m_valid(c_valid), .c_m_last(), .c_m_ready(sink_ready && mode == COMPRESS),
        .c_status_valid(c_status), .c_status_error(c_result), .c_status_ready(core_run && !c_seen),
        .d_s_data(source_data), .d_s_valid(source_valid && mode == DECODE), .d_s_last(source_last), .d_s_ready(d_ready),
        .d_m_data(d_data), .d_m_valid(d_valid), .d_m_last(), .d_m_ready(sink_ready && mode != COMPRESS),
        .d_status_valid(d_status), .d_status_error(d_result), .d_status_ready(core_run && !d_seen)
    );

    always_comb begin
        ddr_valid = 1'b1;
        ddr_write = 1'b0;
        ddr_address = '0;
        ddr_data = '0;
        ddr_mask = '1;
        case (state)
            STAGE: begin
                ddr_write = 1'b1;
                ddr_address = ddr_src + transfer_pos[31:6];
                ddr_data = transfer_pos[5] ? {stage_lo, 256'd0} : {stage_hi, stage_lo};
                ddr_mask = transfer_pos[5] ? {stage_mask[31:0], 32'd0} : stage_mask;
            end
            COMPUTE: begin
                ddr_valid = need_output || need_input;
                ddr_write = need_output;
                ddr_address = need_output ? ddr_dst + stored[31:6] : ddr_src + fetched[31:6];
                ddr_data = output_beat[stored[6]];
                ddr_mask = need_output ? 64'hffff_ffff_ffff_ffff >> (7'd64 - output_write_size) : '1;
            end
            GATHER: ddr_address = ddr_dst + transfer_pos[31:6];
            WINDOW: begin
                ddr_write = window_write;
                ddr_address = window_cursor[31:6];
                ddr_data = window_data;
            end
            default: ddr_valid = 1'b0;
        endcase
    end

    genvar b;
    generate
        for (b = 0; b < 128; b = b + 1) begin : output_bytes
            logic [7:0] data;
            always_ff @(posedge clk)
                if (sink_fire && produced[6:0] == 7'(b))
                    data <= sink_data;
            assign output_beat[b/64][8*(b%64) +: 8] = data;
        end
        for (b = 0; b < 128; b = b + 1) begin : chunk_bytes
            localparam logic [1:0] LANE = 2'(b/32);
            always_ff @(posedge clk) begin
                if (state == FETCH_WAIT && dma_result_valid)
                    chunk_data[8*b +: 8] <= dma_result_data[8*b +: 8];
                else if (state == GATHER_WAIT && ddr_rsp_valid) begin
                    if (lane == LANE)
                        chunk_data[8*b +: 8] <= gather_lo[8*(b%32) +: 8];
                    else if (part_size > 8'd32 && next_lane == LANE)
                        chunk_data[8*b +: 8] <= ddr_rsp_data[256+8*(b%32) +: 8];
                end else if (state == MERGE_WAIT && dma_result_valid &&
                             8'(b) >= chunk_len && 8'(b) < chunk_padded)
                    chunk_data[8*b +: 8] <= dma_result_data[8*(b%32) +: 8];
            end
        end
    endgenerate
    always_ff @(posedge clk)
        if (state == COMPUTE && ddr_rsp_valid && !mem_write)
            input_beat[fetched[6]] <= ddr_rsp_data;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_rvalid <= 1'b0;
            reg_rdata <= '0;
        end else begin
            reg_rvalid <= reg_read;
            reg_rdata <= '0;
            if (reg_read) begin
                case (reg_addr)
                    18'h0: reg_rdata <= MAGIC;
                    18'h1: reg_rdata <= {ROLE_VERSION, ROLE_ID};
                    18'h3: reg_rdata <= {32'd0, role_status};
                    18'h4, 18'h5, 18'h6, 18'h7, 18'h8, 18'h9, 18'ha:
                        reg_rdata <= descriptor[reg_addr[3:0]];
                    18'hb: reg_rdata <= {32'd0, delivered};
                    18'hc: reg_rdata <= {56'd0, completion};
                    18'hd: reg_rdata <= cycles;
                    18'he: reg_rdata <= pcie_bytes;
                    18'hf: reg_rdata <= ddr_bytes;
                    18'h12: reg_rdata <= window_cursor;
                    18'h13: reg_rdata <= {61'd0, window_error, window_done, window_busy};
                    18'h18, 18'h19, 18'h1a, 18'h1b, 18'h1c, 18'h1d, 18'h1e, 18'h1f:
                        reg_rdata <= window_data[64*reg_addr[2:0] +: 64];
                    18'd63, 18'h20000: reg_rdata <= 64'h8926_FC9C_4E62_56D9;
                    18'h20001: reg_rdata <= 64'd65536;
                    18'h20002: reg_rdata <= 64'd64;
                    18'h20003: reg_rdata <= 64'd128;
                    default: ;
                endcase
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 4; i <= 10; i++)
                descriptor[i] <= '0;
            window_cursor <= '0;
            window_data <= '0;
        end else if (!locked) begin
            if (config_write)
                descriptor[reg_addr[3:0]] <= reg_wdata;
            if (window_cursor_write)
                window_cursor <= reg_wdata;
            if (window_lane_write)
                window_data[64*reg_addr[2:0] +: 64] <= reg_wdata;
        end else if (state == WINDOW_WAIT && ddr_rsp_valid && !window_write && !stop_issue) begin
            window_data <= ddr_rsp_data;
        end
    end

    always_ff @(posedge clk) begin
        if (state == IDLE && start) begin
            mode <= descriptor[4][1:0];
            host_src <= descriptor[5];
            host_dst <= descriptor[6];
            bytes_in <= descriptor[7][31:0];
            capacity <= descriptor[8][31:0];
            ddr_src <= descriptor[9][31:6];
            ddr_dst <= descriptor[10][31:6];
            bad_shape <= (dma_start && resident_start) || descriptor[4] > 64'd2 ||
                {descriptor[7][63:32], descriptor[8][63:32],
                 descriptor[9][63:32], descriptor[10][63:32]} != 0 ||
                {descriptor[9][5:0], descriptor[10][5:0]} != 0 ||
                (dma_start && {descriptor[5][4:0], descriptor[6][4:0]} != 0) ||
                (descriptor[4] == 64'd1 ? descriptor[7] == 0 : descriptor[7] > 64'(MAX_BLOCK_BYTES));
        end
        if (state == LIMITS) begin
            host_src_end <= {1'b0, host_src} + {32'd0, padded_extent(bytes_in)};
            host_dst_end <= {1'b0, host_dst} + {32'd0, padded_extent(capacity)};
            ddr_src_end <= {1'b0, ddr_src, 6'b0} + {1'b0, bytes_in};
            ddr_dst_end <= {1'b0, ddr_dst, 6'b0} + {1'b0, capacity};
        end
        if (state == FETCH_ADDR || state == SEND_ADDR)
            chunk_addr <= (state == FETCH_ADDR ? host_src : host_dst) + {32'd0, transfer_pos};
        if (state == FETCH_SIZE || state == SEND_SIZE) begin
            chunk_len <= chunk_size;
            chunk_padded <= (chunk_size + 8'd3) & 8'hfc;
        end
        if (state == COMPUTE && ddr_fire) begin
            mem_write <= ddr_write;
            mem_count <= ddr_write ? output_write_size : input_read_size;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            completion <= '0;
            delivered <= '0;
            cycles <= '0;
            pcie_bytes <= '0;
            ddr_bytes <= '0;
            pcie_native_bytes <= '0;
            ddr_native_bytes <= '0;
            window_busy <= 1'b0;
            window_done <= 1'b0;
            window_error <= 1'b0;
            core_run <= 1'b0;
            ddr_pending <= 1'b0;
        end else begin
            if (!ddr_online || ddr_rsp_valid)
                ddr_pending <= 1'b0;
            else if (ddr_fire)
                ddr_pending <= 1'b1;
            if (busy) begin
                cycles <= cycles + 64'd1;
                if (ddr_rsp_valid)
                    ddr_native_bytes <= ddr_native_bytes + 64'd64;
                if (dma_result_valid && !dma_result_error)
                    pcie_native_bytes <= pcie_native_bytes + {56'd0, dma_bytes};
            end
            if (clear) begin
                done <= 1'b0;
                completion <= '0;
            end
            if (rejected_busy)
                completion <= BUSY_CMD;
            if (reserved_window_write && locked)
                window_error <= 1'b1;

            case (state)
                IDLE: if (start) begin
                    busy <= 1'b1;
                    done <= 1'b0;
                    completion <= '0;
                    resident <= resident_start;
                    cycles <= '0;
                    delivered <= '0;
                    pcie_bytes <= '0;
                    ddr_bytes <= '0;
                    pcie_native_bytes <= '0;
                    ddr_native_bytes <= '0;
                    job_code <= '0;
                    transfer_pos <= '0;
                    fetched <= '0;
                    consumed <= '0;
                    produced <= '0;
                    stored <= '0;
                    empty_sent <= 1'b0;
                    c_seen <= 1'b0;
                    d_seen <= 1'b0;
                    c_error <= '0;
                    d_error <= '0;
                    cap_failed <= 1'b0;
                    state <= LIMITS;
                end else if (cancel) begin
                    done <= 1'b0;
                    completion <= '0;
                    delivered <= '0;
                    cycles <= '0;
                    pcie_bytes <= '0;
                    ddr_bytes <= '0;
                    pcie_native_bytes <= '0;
                    ddr_native_bytes <= '0;
                    window_done <= 1'b0;
                    window_error <= 1'b0;
                end else if (window_request) begin
                    window_error <= !window_cursor_ok || !ddr_online || (&reg_wdata[1:0]);
                    if (window_cursor_ok && ddr_online && !(&reg_wdata[1:0])) begin
                        window_busy <= 1'b1;
                        window_done <= 1'b0;
                        window_write <= reg_wdata[1];
                        state <= WINDOW;
                    end else begin
                        window_done <= 1'b1;
                    end
                end
                LIMITS: state <= VALIDATE;
                VALIDATE: if (!descriptor_valid) begin
                    job_code <= INVALID;
                    state <= COMPLETE;
                end else if (!ddr_online || (!resident && (dma_abort || !dma_idle))) begin
                    job_code <= ABORTED;
                    state <= COMPLETE;
                end else if (resident || bytes_in == 0) begin
                    core_run <= 1'b1;
                    state <= COMPUTE;
                end else begin
                    state <= FETCH_ADDR;
                end
                FETCH_ADDR: state <= FETCH_SIZE;
                FETCH_SIZE: begin
                    chunk_pos <= '0;
                    state <= FETCH;
                end
                FETCH: if (dma_start_ready) state <= FETCH_WAIT;
                FETCH_WAIT: if (dma_result_valid) begin
                    if (dma_result_error) begin
                        job_code <= ABORTED;
                        state <= COMPLETE;
                    end else begin
                        pcie_bytes <= pcie_bytes + {56'd0, chunk_len};
                        state <= STAGE;
                    end
                end
                STAGE: if (ddr_fire) state <= STAGE_WAIT;
                STAGE_WAIT: if (ddr_rsp_valid) begin
                    transfer_pos <= next_transfer;
                    chunk_pos <= chunk_pos + part_size;
                    ddr_bytes <= ddr_bytes + {56'd0, part_size};
                    if (next_transfer == bytes_in) begin
                        core_run <= 1'b1;
                        state <= COMPUTE;
                    end else
                        state <= final_part ? FETCH_ADDR : STAGE;
                end
                COMPUTE: begin
                    if (source_fire) begin
                        if (bytes_in == 0)
                            empty_sent <= 1'b1;
                        else
                            consumed <= consumed + 32'd1;
                    end
                    if (sink_fire) produced <= produced + 32'd1;
                    if (core_run && c_status && !c_seen) begin
                        c_seen <= 1'b1;
                        c_error <= c_result;
                    end
                    if (core_run && d_status && !d_seen) begin
                        d_seen <= 1'b1;
                        d_error <= d_result;
                    end
                    if (core_run && sink_valid && capacity_hit) begin
                        cap_failed <= 1'b1;
                        core_run <= 1'b0;
                    end
                    if (ddr_rsp_valid) begin
                        ddr_bytes <= ddr_bytes + {57'd0, mem_count};
                        if (mem_write) begin
                            stored <= stored + {25'd0, mem_count};
                            if (resident) delivered <= stored + {25'd0, mem_count};
                        end else begin
                            fetched <= fetched + {25'd0, mem_count};
                        end
                    end
                    if (core_finished && output_pending == 0 && !ddr_pending) begin
                        core_run <= 1'b0;
                        if (cap_failed)
                            job_code <= CAPACITY;
                        else if (mode != DECODE && c_error != 0)
                            job_code <= 8'h10 + {5'd0, c_error};
                        else if (mode != COMPRESS && d_error != 0)
                            job_code <= 8'h20 + {5'd0, d_error};
                        transfer_pos <= '0;
                        state <= (resident || produced == 0) ? COMPLETE : SEND_ADDR;
                    end
                end
                SEND_ADDR: state <= SEND_SIZE;
                SEND_SIZE: begin
                    chunk_pos <= '0;
                    state <= GATHER;
                end
                GATHER: if (ddr_fire) state <= GATHER_WAIT;
                GATHER_WAIT: if (ddr_rsp_valid) begin
                    transfer_pos <= next_transfer;
                    chunk_pos <= chunk_pos + part_size;
                    ddr_bytes <= ddr_bytes + {56'd0, part_size};
                    if (final_part)
                        state <= chunk_len[1:0] != 0 ? MERGE : SEND;
                    else
                        state <= GATHER;
                end
                MERGE: if (dma_start_ready) state <= MERGE_WAIT;
                MERGE_WAIT: if (dma_result_valid) begin
                    if (dma_result_error) begin
                        job_code <= ABORTED;
                        state <= COMPLETE;
                    end else
                        state <= SEND;
                end
                SEND: if (dma_start_ready) state <= SEND_WAIT;
                SEND_WAIT: if (dma_result_valid) begin
                    if (dma_result_error) begin
                        job_code <= ABORTED;
                        state <= COMPLETE;
                    end else begin
                        pcie_bytes <= pcie_bytes + {56'd0, chunk_len};
                        delivered <= transfer_pos;
                        state <= transfer_pos == produced ? COMPLETE : SEND_ADDR;
                    end
                end
                COMPLETE: begin
                    completion <= job_code;
                    done <= 1'b1;
                    busy <= 1'b0;
                    state <= IDLE;
                end
                WINDOW: if (ddr_fire) state <= WINDOW_WAIT;
                WINDOW_WAIT: if (ddr_rsp_valid) begin
                    window_busy <= 1'b0;
                    window_done <= 1'b1;
                    state <= IDLE;
                end
                ABORT_DRAIN: if (!ddr_pending && dma_idle) begin
                    if (busy) begin
                        completion <= ABORTED;
                        done <= 1'b1;
                        busy <= 1'b0;
                    end else begin
                        window_busy <= 1'b0;
                        window_done <= 1'b1;
                        window_error <= 1'b1;
                    end
                    state <= IDLE;
                end
                default: state <= ABORT_DRAIN;
            endcase

            // Preserve any accepted operation's ownership until it replies
            // or its endpoint resets. No new command can issue on this edge.
            if (state != ABORT_DRAIN && state != COMPLETE &&
                ((cancel && locked) || transport_lost || window_lost)) begin
                state <= ABORT_DRAIN;
                core_run <= 1'b0;
                if (window_busy) window_busy <= 1'b1;
            end
        end
    end
endmodule
