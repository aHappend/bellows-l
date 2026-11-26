module bellows_l2_dma (
    input wire clk, rst_n, cancel,
    input wire start_valid, start_write,
    output wire start_ready, idle,
    input wire [63:0] start_addr,
    input wire [7:0] start_bytes,
    input wire [1023:0] start_data,
    output wire result_valid,
    output logic result_error,
    output wire [1023:0] result_data,
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
    typedef enum logic [1:0] {IDLE, COMMAND, ACTIVE, RESULT} state_t;
    state_t state;
    logic [63:0] addr;
    logic [7:0] length, left;
    logic [2:0] index;
    logic [1023:0] tx_data;
    logic write, frame_done, frame_error, cpl_seen;
    wire last_beat = left <= 8'd16;
    wire [4:0] beat_size = last_beat ? left[4:0] : 5'd16;
    wire [15:0] beat_keep = 16'hffff >> (5'd16 - beat_size);

    assign idle = state == IDLE;
    assign start_ready = rst_n && idle && !cancel && !dma_abort;
    assign result_valid = rst_n && state == RESULT;
    assign dma_cmd_valid = rst_n && state == COMMAND && !cancel && !dma_abort;
    assign dma_cmd_write = write;
    assign dma_cmd_addr = addr;
    assign dma_cmd_bytes = {18'd0, length};
    assign dma_cpl_ready = 1'b1;
    // Cancel only prevents unaccepted commands. Keep servicing both
    // channels of an accepted transaction until the live bridge retires it.
    assign dma_tx_valid = rst_n && state == ACTIVE && write && !frame_done && !dma_abort;
    assign dma_tx_last = dma_tx_valid && last_beat;
    assign dma_tx_data = tx_data[128*index +: 128];
    assign dma_tx_keep = beat_keep;
    assign dma_rx_ready = rst_n && state == ACTIVE && !write && !frame_done && !dma_abort;
    wire rx_fire = dma_rx_ready && dma_rx_valid;
    wire tx_fire = dma_tx_ready && dma_tx_valid;
    wire frame_end = (rx_fire && dma_rx_last) || (tx_fire && last_beat);
    wire rx_bad = rx_fire && (dma_rx_keep != beat_keep || dma_rx_last != last_beat || left == 0);

    genvar beat;
    generate
        for (beat = 0; beat < 8; beat = beat + 1) begin : receive
            logic [127:0] data;
            always_ff @(posedge clk)
                if (rx_fire && left != 0 && index == 3'(beat))
                    data <= dma_rx_data;
            assign result_data[128*beat +: 128] = data;
        end
    endgenerate
    always_ff @(posedge clk) begin
        if (start_valid && start_ready) begin
            write <= start_write;
            addr <= start_addr;
            length <= start_bytes;
            if (start_write)
                tx_data <= start_data;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            result_error <= 1'b0;
        end else if (dma_abort) begin
            state <= IDLE;
        end else begin
            case (state)
                IDLE: if (start_valid && start_ready) begin
                    left <= start_bytes;
                    index <= '0;
                    frame_done <= 1'b0;
                    frame_error <= 1'b0;
                    cpl_seen <= 1'b0;
                    state <= COMMAND;
                end
                COMMAND: if (cancel)
                    state <= IDLE;
                else if (dma_cmd_ready)
                    state <= ACTIVE;
                ACTIVE: begin
                    if (rx_fire || tx_fire) begin
                        left <= last_beat ? '0 : left - 8'd16;
                        index <= index + 3'd1;
                    end
                    if (frame_end) frame_done <= 1'b1;
                    if (rx_bad) frame_error <= 1'b1;
                    if (dma_cpl_valid) cpl_seen <= 1'b1;
                    if (dma_cpl_valid && dma_cpl_error) begin
                        result_error <= 1'b1;
                        state <= RESULT;
                    end else if ((cpl_seen || dma_cpl_valid) && (frame_done || frame_end)) begin
                        result_error <= frame_error || rx_bad;
                        state <= RESULT;
                    end
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
