module Role_BellowsL1 (
    input  wire         clk, reset,
    input  wire         reg_read, reg_write,
    input  wire [17:0]  reg_addr,
    input  wire [63:0]  reg_wdata,
    output logic [63:0] reg_rdata,
    output logic        reg_rvalid,
    output wire [31:0]  role_id, role_version, role_status,
    input  wire         ddr_clk, ddr_reset, amm_ready,
    output wire         amm_read, amm_write,
    output wire [25:0]  amm_address,
    input  wire [511:0] amm_readdata,
    output wire [511:0] amm_writedata,
    output wire [6:0]   amm_burstcount,
    output wire [63:0]  amm_byteenable,
    input  wire         amm_readdatavalid,
    output wire         dma_cmd_valid, dma_cmd_write,
    input  wire         dma_cmd_ready,
    output wire [63:0]  dma_cmd_addr,
    output wire [25:0]  dma_cmd_bytes,
    input  wire         dma_cpl_valid, dma_cpl_error, dma_abort,
    output wire         dma_cpl_ready,
    output wire         dma_tx_valid, dma_tx_last,
    input  wire         dma_tx_ready,
    output wire [127:0] dma_tx_data,
    output wire [15:0]  dma_tx_keep,
    input  wire         dma_rx_valid, dma_rx_last,
    output wire         dma_rx_ready,
    input  wire [127:0] dma_rx_data,
    input  wire [15:0]  dma_rx_keep
);
    localparam logic [63:0] MAGIC = 64'h4245_4C4C_4F57_4C31;
    localparam logic [31:0] ROLE_ID = 32'h0002_424C;
    localparam logic [31:0] ROLE_VERSION = 32'h0002_0000;
    localparam logic [63:0] DDR_LIMIT = 64'h0000_0000_8000_0000;
    localparam logic [2:0] DIAG_BUSY = 1, DIAG_INVALID = 2,
                           DIAG_CAPACITY = 3, DIAG_DMA = 4;

    typedef enum logic [4:0] {
        IDLE, VALIDATE, FETCH_PREP, FETCH, FETCH_WAIT, STAGE, STAGE_WAIT,
        INPUT_READ, INPUT_WAIT, DECODE, OUTPUT_WRITE, OUTPUT_WAIT,
        EGRESS_READ, EGRESS_WAIT, EGRESS_PREP, MERGE_READ, MERGE_WAIT, SEND,
        SEND_WAIT, COMPLETE, WINDOW, WINDOW_WAIT
    } state_t;
    state_t state;

    wire ctrl_rst_n;
    bellows_l1_reset_sync control_release(clk, reset, ctrl_rst_n);

    logic [63:0] descriptor [5:10];
    logic [63:0] host_source, input_length, host_destination, output_capacity;
    logic [63:0] ddr_input, ddr_output;
    logic busy, done, transport_error, resident, owns_epoch;
    logic [2:0] core_error, diagnostic;
    logic [31:0] consumed, produced;
    logic [63:0] core_cycles, job_cycles, ddr_beats, pcie_beats;
    logic [31:0] stage_offset, output_offset, send_offset;
    logic [63:0] chunk_addr;
    logic [5:0] chunk_size, chunk_padded;
    logic chunk_last;
    logic [255:0] pcie_buffer, egress_upper;
    logic [511:0] input_buffer, output_buffer;
    logic [6:0] input_count, output_count;
    logic core_running;

    logic [63:0] window_cursor;
    logic [511:0] window_data;
    logic window_busy, window_done, window_error, window_write;

    assign role_id = ROLE_ID;
    assign role_version = ROLE_VERSION;
    assign role_status = {26'd0, transport_error, core_error, done, busy};

    wire ddr_online, ddr_cmd_ready, ddr_rsp_valid;
    logic ddr_cmd_write;
    logic [25:0] ddr_cmd_address;
    logic [511:0] ddr_cmd_data;
    logic [63:0] ddr_cmd_mask;
    wire [511:0] ddr_rsp_data;

    wire dma_start_ready, dma_idle, dma_result_valid, dma_result_error;
    wire [255:0] dma_result_data;
    wire job_online = ddr_online && (resident || !dma_abort);
    wire job_abort = busy && owns_epoch && !job_online;
    wire ddr_cmd_valid = ctrl_rst_n && ddr_online && !job_abort &&
        (state == STAGE || state == INPUT_READ || state == OUTPUT_WRITE ||
         state == EGRESS_READ || state == WINDOW);

    bellows_l1_ddr ddr (
        .clk(clk), .reset(reset), .online(ddr_online),
        .cmd_valid(ddr_cmd_valid), .cmd_write(ddr_cmd_write), .cmd_ready(ddr_cmd_ready),
        .cmd_address(ddr_cmd_address), .cmd_data(ddr_cmd_data), .cmd_mask(ddr_cmd_mask),
        .rsp_valid(ddr_rsp_valid), .rsp_data(ddr_rsp_data),
        .ddr_clk(ddr_clk), .ddr_reset(ddr_reset), .amm_ready(amm_ready),
        .amm_read(amm_read), .amm_write(amm_write), .amm_address(amm_address),
        .amm_readdata(amm_readdata), .amm_writedata(amm_writedata), .amm_burstcount(amm_burstcount),
        .amm_byteenable(amm_byteenable), .amm_readdatavalid(amm_readdatavalid)
    );

    bellows_l1_dma dma (
        .clk(clk), .rst_n(ctrl_rst_n), .cancel(!ddr_online),
        .start_valid(state == FETCH || state == MERGE_READ || state == SEND),
        .start_write(state == SEND), .start_ready(dma_start_ready), .idle(dma_idle),
        .start_addr(chunk_addr), .start_bytes(chunk_padded), .start_data(pcie_buffer),
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

    function automatic logic host_range_ok(input [63:0] base, input [31:0] count);
        logic [32:0] padded;
        padded = ({1'b0, count} + 33'd3) & 33'h1_ffff_fffc;
        return ({1'b0, base} + {32'd0, padded}) <= 65'h0_ffff_ffff_ffff_ffff;
    endfunction

    function automatic [5:0] chunk_count(input [31:0] remaining);
        return remaining >= 32'd32 ? 6'd32 : remaining[5:0];
    endfunction

    function automatic [5:0] round_chunk(input [5:0] count);
        return (count + 6'd3) & 6'h3c;
    endfunction

    wire [32:0] input_end = {1'b0, ddr_input[31:0]} + {1'b0, input_length[31:0]};
    wire [32:0] output_end = {1'b0, ddr_output[31:0]} + {1'b0, output_capacity[31:0]};
    wire descriptor_valid = input_length != 0 && output_capacity != 0 &&
        {input_length[63:32], output_capacity[63:32], ddr_input[63:32], ddr_output[63:32]} == 0 &&
        ddr_input[5:0] == 0 && ddr_output[5:0] == 0 &&
        input_end <= DDR_LIMIT[32:0] && output_end <= DDR_LIMIT[32:0] &&
        (input_end <= {1'b0, ddr_output[31:0]} || output_end <= {1'b0, ddr_input[31:0]}) &&
        (resident || (host_source[4:0] == 0 && host_destination[4:0] == 0 &&
                      host_range_ok(host_source, input_length[31:0]) &&
                      host_range_ok(host_destination, output_capacity[31:0])));

    wire [31:0] input_left = input_length[31:0] - consumed;
    wire [31:0] fetch_left = input_length[31:0] - stage_offset;
    wire [31:0] send_left = produced - send_offset;
    wire [5:0] fetch_size = chunk_count(fetch_left);
    wire [5:0] send_size = chunk_count(send_left);
    wire [31:0] stage_mask = 32'hffff_ffff >> (6'd32 - chunk_size);
    always_comb begin
        ddr_cmd_write = 1'b0;
        ddr_cmd_address = '0;
        ddr_cmd_mask = '1;
        ddr_cmd_data = '0;
        case (state)
            STAGE: begin
                ddr_cmd_write = 1'b1;
                ddr_cmd_address = ddr_input[31:6] + stage_offset[31:6];
                ddr_cmd_mask = stage_offset[5] ? {stage_mask, 32'd0} : {32'd0, stage_mask};
                ddr_cmd_data = stage_offset[5] ? {pcie_buffer, 256'd0} : {256'd0, pcie_buffer};
            end
            INPUT_READ: ddr_cmd_address = ddr_input[31:6] + consumed[31:6];
            OUTPUT_WRITE: begin
                ddr_cmd_write = 1'b1;
                ddr_cmd_address = ddr_output[31:6] + output_offset[31:6];
                ddr_cmd_mask = 64'hffff_ffff_ffff_ffff >> (7'd64 - output_count);
                ddr_cmd_data = output_buffer;
            end
            EGRESS_READ: ddr_cmd_address = ddr_output[31:6] + send_offset[31:6];
            WINDOW: begin
                ddr_cmd_write = window_write;
                ddr_cmd_address = window_cursor[31:6];
                ddr_cmd_data = window_data;
            end
            default: ;
        endcase
    end

    wire core_s_ready, core_m_valid, core_status_valid, unused_core_m_last;
    wire [7:0] core_m_data;
    wire [2:0] core_status_error;
    wire core_s_valid = core_running && input_count != 0;
    wire capacity_reached = produced == output_capacity[31:0];
    wire core_m_ready = core_running && state == DECODE && output_count != 64 && !capacity_reached;

    bellows_l1_top u_bellows_l1_top (
        .clk(clk), .rst_n(core_running),
        .s_data(input_buffer[7:0]), .s_valid(core_s_valid), .s_last(input_left == 1),
        .s_ready(core_s_ready), .m_data(core_m_data), .m_valid(core_m_valid),
        .m_last(unused_core_m_last), .m_ready(core_m_ready),
        .status_valid(core_status_valid), .status_error(core_status_error),
        .status_ready(state == DECODE)
    );

    wire command = reg_write && reg_addr == 18'd3;
    wire dma_start = command && reg_wdata[0];
    wire resident_start = command && reg_wdata[3];
    wire start_requested = dma_start || resident_start;
    wire start_accepted = !busy && !window_busy && (dma_start != resident_start);
    wire soft_reset = command && reg_wdata[2] && !start_requested && !busy && !window_busy;
    wire window_request = reg_write && reg_addr == 18'd19 && (|reg_wdata[1:0]);
    wire window_cursor_valid = window_cursor[5:0] == 0 && window_cursor < DDR_LIMIT;

    always_ff @(posedge clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            reg_rvalid <= 1'b0;
            reg_rdata <= '0;
        end else begin
            reg_rvalid <= reg_read;
            reg_rdata <= '0;
            if (reg_read) begin
                case (reg_addr)
                    18'd0: reg_rdata <= MAGIC;
                    18'd1: reg_rdata <= {32'd0, ROLE_VERSION};
                    18'd2: reg_rdata <= {32'd0, ROLE_ID};
                    18'd4: reg_rdata <= {32'd0, role_status};
                    18'd5, 18'd6, 18'd7, 18'd8, 18'd9, 18'd10:
                        reg_rdata <= descriptor[reg_addr[3:0]];
                    18'd11: reg_rdata <= {32'd0, consumed};
                    18'd12: reg_rdata <= {32'd0, produced};
                    18'd13: reg_rdata <= core_cycles;
                    18'd14: reg_rdata <= ddr_beats;
                    18'd15: reg_rdata <= pcie_beats;
                    18'd16: reg_rdata <= {61'd0, diagnostic};
                    18'd17: reg_rdata <= job_cycles;
                    18'd18: reg_rdata <= window_cursor;
                    18'd19: reg_rdata <= {61'd0, window_error, window_done, window_busy};
                    18'd24, 18'd25, 18'd26, 18'd27, 18'd28, 18'd29, 18'd30, 18'd31:
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

    always_ff @(posedge clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            for (int i = 5; i <= 10; i++)
                descriptor[i] <= '0;
            window_cursor <= '0;
            window_data <= '0;
            window_busy <= 1'b0;
            window_done <= 1'b0;
            window_error <= 1'b0;
            window_write <= 1'b0;
        end else if (soft_reset) begin
            for (int i = 5; i <= 10; i++)
                descriptor[i] <= '0;
            window_cursor <= '0;
            window_data <= '0;
            window_busy <= 1'b0;
            window_done <= 1'b0;
            window_error <= 1'b0;
            window_write <= 1'b0;
        end else begin
            if (reg_write && !busy && !window_busy) begin
                if (reg_addr >= 18'd5 && reg_addr <= 18'd10)
                    descriptor[reg_addr[3:0]] <= reg_wdata;
                if (reg_addr == 18'd18)
                    window_cursor <= reg_wdata;
                if (reg_addr >= 18'd24 && reg_addr <= 18'd31)
                    window_data[64*reg_addr[2:0] +: 64] <= reg_wdata;
            end
            if (state == WINDOW_WAIT && ddr_rsp_valid) begin
                if (!window_write)
                    window_data <= ddr_rsp_data;
                window_busy <= 1'b0;
                window_done <= 1'b1;
            end
            if (window_request) begin
                if (busy || window_busy || !ddr_online || !window_cursor_valid || (&reg_wdata[1:0])) begin
                    window_error <= 1'b1;
                    if (!window_busy)
                        window_done <= 1'b1;
                end else begin
                    window_busy <= 1'b1;
                    window_done <= 1'b0;
                    window_error <= 1'b0;
                    window_write <= reg_wdata[1];
                end
            end
            if (window_busy && !ddr_online) begin
                window_busy <= 1'b0;
                window_done <= 1'b0;
                window_error <= 1'b1;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (start_accepted) begin
            host_source <= descriptor[5];
            input_length <= descriptor[6];
            host_destination <= descriptor[7];
            output_capacity <= descriptor[8];
            ddr_input <= descriptor[9];
            ddr_output <= descriptor[10];
        end

        if (state == FETCH_PREP || state == EGRESS_PREP) begin
            chunk_addr <= state == FETCH_PREP ? host_source + {32'd0, stage_offset} :
                                               host_destination + {32'd0, send_offset};
            chunk_size <= state == FETCH_PREP ? fetch_size : send_size;
            chunk_padded <= round_chunk(state == FETCH_PREP ? fetch_size : send_size);
            chunk_last <= state == FETCH_PREP ? fetch_left <= 32 : send_left <= 32;
        end
        if (state == FETCH_WAIT && dma_result_valid)
            pcie_buffer <= dma_result_data;
        if (state == EGRESS_WAIT && ddr_rsp_valid) begin
            egress_upper <= ddr_rsp_data[511:256];
            pcie_buffer <= ddr_rsp_data[255:0];
        end
        if (state == SEND_WAIT && dma_result_valid && !dma_result_error && !chunk_last && !send_offset[5])
            pcie_buffer <= egress_upper;
        // The aligned destination read supplies only the bytes above the logical prefix.
        if (state == MERGE_WAIT && dma_result_valid)
            for (int i = 0; i < 32; i++)
                if (i >= int'(chunk_size))
                    pcie_buffer[8*i +: 8] <= dma_result_data[8*i +: 8];

        if (state == INPUT_WAIT && ddr_rsp_valid)
            input_buffer <= ddr_rsp_data;
        else if (core_s_valid && core_s_ready)
            input_buffer <= {8'd0, input_buffer[511:8]};

        if (core_m_valid && core_m_ready)
            output_buffer[8*output_count[5:0] +: 8] <= core_m_data;
    end

    always_ff @(posedge clk or negedge ctrl_rst_n) begin
        if (!ctrl_rst_n) begin
            state <= IDLE;
            busy <= 1'b0;
            done <= 1'b0;
            owns_epoch <= 1'b0;
            resident <= 1'b0;
            core_running <= 1'b0;
            transport_error <= 1'b0;
            core_error <= '0;
            diagnostic <= '0;
            consumed <= '0;
            produced <= '0;
            core_cycles <= '0;
            job_cycles <= '0;
            ddr_beats <= '0;
            pcie_beats <= '0;
            input_count <= '0;
            output_count <= '0;
            stage_offset <= '0;
            output_offset <= '0;
            send_offset <= '0;
        end else begin
            if (busy)
                job_cycles <= job_cycles + 1'b1;
            if (core_running)
                core_cycles <= core_cycles + 1'b1;
            if (ddr_rsp_valid && (state == STAGE_WAIT || state == INPUT_WAIT ||
                                  state == OUTPUT_WAIT || state == EGRESS_WAIT))
                ddr_beats <= ddr_beats + 1'b1;
            if (dma_result_valid && !dma_result_error &&
                (state == FETCH_WAIT || state == MERGE_WAIT || state == SEND_WAIT))
                pcie_beats <= pcie_beats + 1'b1;

            if (core_s_valid && core_s_ready) begin
                input_count <= input_count - 1'b1;
                consumed <= consumed + 1'b1;
            end
            if (core_m_valid && core_m_ready) begin
                output_count <= output_count + 1'b1;
                produced <= produced + 1'b1;
            end

            case (state)
                IDLE: if (window_request && ddr_online && window_cursor_valid && !(&reg_wdata[1:0]))
                    state <= WINDOW;
                VALIDATE: if (!descriptor_valid) begin
                    transport_error <= 1'b1;
                    diagnostic <= DIAG_INVALID;
                    state <= COMPLETE;
                end else if (job_online && dma_idle) begin
                    owns_epoch <= 1'b1;
                    core_running <= resident;
                    state <= resident ? INPUT_READ : FETCH_PREP;
                end
                FETCH_PREP: state <= FETCH;
                FETCH: if (dma_start_ready)
                    state <= FETCH_WAIT;
                FETCH_WAIT: if (dma_result_valid)
                    state <= STAGE;
                STAGE: if (ddr_cmd_ready)
                    state <= STAGE_WAIT;
                STAGE_WAIT: if (ddr_rsp_valid) begin
                    if (chunk_last) begin
                        core_running <= 1'b1;
                        state <= INPUT_READ;
                    end else begin
                        stage_offset <= stage_offset + 32'd32;
                        state <= FETCH_PREP;
                    end
                end
                INPUT_READ: if (ddr_cmd_ready)
                    state <= INPUT_WAIT;
                INPUT_WAIT: if (ddr_rsp_valid) begin
                    input_count <= input_left >= 64 ? 7'd64 : input_left[6:0];
                    state <= DECODE;
                end
                DECODE: begin
                    if (core_status_valid || (core_m_valid && capacity_reached)) begin
                        core_running <= 1'b0;
                        if (core_status_valid)
                            core_error <= core_status_error;
                        else begin
                            transport_error <= 1'b1;
                            diagnostic <= DIAG_CAPACITY;
                        end
                        if (output_count != 0)
                            state <= OUTPUT_WRITE;
                        else
                            state <= (resident || produced == 0) ? COMPLETE : EGRESS_READ;
                    end else if (output_count == 64)
                        state <= OUTPUT_WRITE;
                    else if (input_count == 0 && consumed != input_length[31:0])
                        state <= INPUT_READ;
                end
                OUTPUT_WRITE: if (ddr_cmd_ready)
                    state <= OUTPUT_WAIT;
                OUTPUT_WAIT: if (ddr_rsp_valid) begin
                    output_offset <= output_offset + 32'd64;
                    output_count <= '0;
                    if (core_running)
                        state <= DECODE;
                    else
                        state <= resident ? COMPLETE : EGRESS_READ;
                end
                EGRESS_READ: if (ddr_cmd_ready)
                    state <= EGRESS_WAIT;
                EGRESS_WAIT: if (ddr_rsp_valid)
                    state <= EGRESS_PREP;
                EGRESS_PREP: state <= send_size[1:0] != 0 ? MERGE_READ : SEND;
                MERGE_READ: if (dma_start_ready)
                    state <= MERGE_WAIT;
                MERGE_WAIT: if (dma_result_valid)
                    state <= SEND;
                SEND: if (dma_start_ready)
                    state <= SEND_WAIT;
                SEND_WAIT: if (dma_result_valid) begin
                    if (chunk_last)
                        state <= COMPLETE;
                    else begin
                        send_offset <= send_offset + 32'd32;
                        state <= send_offset[5] ? EGRESS_READ : EGRESS_PREP;
                    end
                end
                COMPLETE: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    owns_epoch <= 1'b0;
                    state <= IDLE;
                end
                WINDOW: if (ddr_cmd_ready)
                    state <= WINDOW_WAIT;
                WINDOW_WAIT: if (ddr_rsp_valid)
                    state <= IDLE;
                default: state <= IDLE;
            endcase

            if (dma_result_valid && dma_result_error &&
                (state == FETCH_WAIT || state == MERGE_WAIT || state == SEND_WAIT)) begin
                transport_error <= 1'b1;
                diagnostic <= DIAG_DMA;
                state <= COMPLETE;
            end
            if (start_requested && !start_accepted) begin
                transport_error <= 1'b1;
                diagnostic <= (busy || window_busy) ? DIAG_BUSY : DIAG_INVALID;
            end
            if (window_busy && !ddr_online)
                state <= IDLE;

            if (start_accepted || soft_reset || job_abort) begin
                state <= start_accepted ? VALIDATE : IDLE;
                busy <= start_accepted;
                resident <= start_accepted && resident_start;
                done <= 1'b0;
                owns_epoch <= start_accepted && ddr_online && (resident_start || !dma_abort);
                core_running <= 1'b0;
                transport_error <= 1'b0;
                core_error <= '0;
                diagnostic <= '0;
                consumed <= '0;
                produced <= '0;
                core_cycles <= '0;
                job_cycles <= '0;
                ddr_beats <= '0;
                pcie_beats <= '0;
                input_count <= '0;
                output_count <= '0;
                stage_offset <= '0;
                output_offset <= '0;
                send_offset <= '0;
            end
            if (command && reg_wdata[1])
                done <= 1'b0;
        end
    end
endmodule
