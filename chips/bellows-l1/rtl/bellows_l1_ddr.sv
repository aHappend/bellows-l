module bellows_l1_ddr (
    input  wire         clk, reset,
    output wire         online,
    input  wire         cmd_valid, cmd_write,
    output wire         cmd_ready,
    input  wire [25:0]  cmd_address,
    input  wire [511:0] cmd_data,
    input  wire [63:0]  cmd_mask,
    output wire         rsp_valid,
    output logic [511:0] rsp_data,
    input  wire         ddr_clk, ddr_reset, amm_ready,
    output wire         amm_read, amm_write,
    output wire [25:0]  amm_address,
    input  wire [511:0] amm_readdata,
    output wire [511:0] amm_writedata,
    output wire [6:0]   amm_burstcount,
    output wire [63:0]  amm_byteenable,
    input  wire         amm_readdatavalid
);
    wire flush = reset || ddr_reset;
    wire role_mailbox_n, native_mailbox_n, native_rst_n;
    bellows_l1_reset_sync role_release(clk, flush, role_mailbox_n);
    bellows_l1_reset_sync mailbox_release(ddr_clk, flush, native_mailbox_n);
    bellows_l1_reset_sync native_release(ddr_clk, ddr_reset, native_rst_n);

    logic [602:0] role_command, native_command;
    logic [511:0] native_response;
    wire [602:0] command_front;
    wire [511:0] response_front;
    wire command_full, command_empty, response_full, response_empty;
    logic issue_pending, pending, result_valid;

    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION \"FORCED IF ASYNCHRONOUS\"" *)
    logic [1:0] online_sync /* synthesis preserve dont_replicate */;

    typedef enum logic [1:0] {IDLE, ISSUE, WAIT_READ, REPLY} native_state_t;
    native_state_t native_state = IDLE;
    logic native_online /* synthesis preserve dont_replicate */;
    wire native_take = native_online && native_state == IDLE && !command_empty;
    wire native_reply = native_online && native_state == REPLY && !response_full;
    wire role_send = cmd_valid && cmd_ready;
    wire command_push = online && issue_pending && !command_full;
    wire role_receive = online && pending && !response_empty;
    assign online = role_mailbox_n && online_sync[1];
    assign cmd_ready = online && !pending && !result_valid;
    assign rsp_valid = online && result_valid;

    // Keep the 603- and 512-bit payloads in dual-clock RAM. Only FIFO pointers
    // and the epoch-ready flag cross through synchronizers.
    dcfifo #(.lpm_width(603), .lpm_widthu(3), .lpm_numwords(8),
        .lpm_showahead("ON"), .rdsync_delaypipe(4), .wrsync_delaypipe(4),
        .add_ram_output_register("ON"), .lpm_hint("RAM_BLOCK_TYPE=M20K"),
        .read_aclr_synch("ON"), .write_aclr_synch("ON"), .intended_device_family("Arria 10"))
    command_fifo (.aclr(flush), .wrclk(clk), .rdclk(ddr_clk),
        .data(role_command), .q(command_front), .wrreq(command_push), .rdreq(native_take),
        .wrfull(command_full), .rdempty(command_empty),
        .rdfull(), .rdusedw(), .wrempty(), .wrusedw(), .eccstatus());

    dcfifo #(.lpm_width(512), .lpm_widthu(3), .lpm_numwords(8),
        .lpm_showahead("ON"), .rdsync_delaypipe(4), .wrsync_delaypipe(4),
        .add_ram_output_register("ON"), .lpm_hint("RAM_BLOCK_TYPE=M20K"),
        .read_aclr_synch("ON"), .write_aclr_synch("ON"), .intended_device_family("Arria 10"))
    response_fifo (.aclr(flush), .wrclk(ddr_clk), .rdclk(clk),
        .data(native_response), .q(response_front), .wrreq(native_reply), .rdreq(role_receive),
        .wrfull(response_full), .rdempty(response_empty),
        .rdfull(), .rdusedw(), .wrempty(), .wrusedw(), .eccstatus());

    always_ff @(posedge clk or negedge role_mailbox_n) begin
        if (!role_mailbox_n) begin
            online_sync <= '0;
            issue_pending <= 1'b0;
            pending <= 1'b0;
            result_valid <= 1'b0;
        end else begin
            online_sync <= {online_sync[0], native_online};
            if (role_send) begin
                issue_pending <= 1'b1;
                pending <= 1'b1;
            end
            if (command_push)
                issue_pending <= 1'b0;
            if (role_receive)
                pending <= 1'b0;
            result_valid <= role_receive;
        end
    end

    always_ff @(posedge clk) begin
        if (role_send)
            role_command <= {cmd_write, cmd_address, cmd_mask, cmd_data};
        if (role_receive)
            rsp_data <= response_front;
    end

    assign amm_write = native_rst_n && native_state == ISSUE && native_command[602];
    assign amm_read = native_rst_n && native_state == ISSUE && !native_command[602];
    assign amm_address = native_command[601:576];
    assign amm_byteenable = native_command[575:512];
    assign amm_writedata = native_command[511:0];
    assign amm_burstcount = 7'd1;
    wire write_done = amm_write && amm_ready;
    wire read_done = amm_readdatavalid && (native_state == WAIT_READ || (amm_read && amm_ready));

    // A role reset clears both queues, but does not withdraw an Avalon
    // command. Stay offline and discard its result until it has retired.
    always_ff @(posedge ddr_clk or negedge native_rst_n) begin
        if (!native_rst_n)
            native_state <= IDLE;
        else if (native_take)
            native_state <= ISSUE;
        else if (write_done || read_done)
            native_state <= native_online ? REPLY : IDLE;
        else if (amm_read && amm_ready)
            native_state <= WAIT_READ;
        else if (native_state == REPLY && (native_reply || !native_online))
            native_state <= IDLE;
    end

    always_ff @(posedge ddr_clk or negedge native_mailbox_n) begin
        if (!native_mailbox_n)
            native_online <= 1'b0;
        else if (native_rst_n && native_state == IDLE)
            native_online <= 1'b1;
    end

    always_ff @(posedge ddr_clk) begin
        if (native_take)
            native_command <= command_front;
        if (read_done)
            native_response <= amm_readdata;
    end
endmodule
