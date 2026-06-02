// top.sv
//
// Single-cycle RV32I datapath. One instruction per clock: fetch,
// decode, read registers, compute, access memory, write back, and
// pick the next PC, all in one cycle. This is plan stage 1's working
// artifact; stage 2 splits this same datapath across pipeline
// registers.
//
// Memory is Harvard-style for stage 1: separate instr_memory and
// data_memory, both loaded from the same hex image by the testbench
// (+imem_hex and +dmem_hex point at the same file). Data writes only
// touch the data_memory copy, which is fine because stage-1 programs
// are not self-modifying. The reference emulator uses one unified
// array; for non-self-modifying code the two behave identically, so
// lockstep holds.
//
// Halt: a recognizable stop condition freezes the PC and stops
// register writes, then raises `halted` with a cause code the
// testbench reads. Causes:
//   HALT_NONE       still running
//   HALT_ECALL      ECALL executed
//   HALT_EBREAK     EBREAK executed
//   HALT_ILLEGAL    decoder raised illegal
//   HALT_MISALIGNED data_memory flagged a misaligned access
//   HALT_TOHOST     a store hit the tohost MMIO address (test signal)
//
// Control-flow target math, all in one place at the next-PC mux:
//   - branch taken / JAL: target = PC + imm, which is exactly the ALU
//     result because the decoder sets alu_src_a=PC, alu_src_b=IMM for
//     those. So branch_target = alu_y.
//   - JALR: target = (rs1 + imm) with bit 0 cleared, which is the ALU
//     result (alu_src_a=RS1, alu_src_b=IMM) ANDed with ~1.
//   The ALU is therefore doing target arithmetic for control-flow
//   instructions and value arithmetic for everything else; the two
//   never collide because they are different opcodes.

`default_nettype none

module top
    import riscv_pkg::*;
#(
    parameter logic [31:0] PC_RESET    = 32'h0000_0000,
    parameter int          IMEM_WORDS  = 1024,
    parameter int          DMEM_WORDS  = 4096,
    parameter logic [31:0] TOHOST_ADDR = 32'h8000_1000,
    parameter logic [31:0] UART_ADDR   = 32'hFFFF_0000
) (
    input  logic        clk,
    input  logic        rst,
    output logic [31:0] pc_out,
    output logic        halted,
    output logic [2:0]  halt_cause,
    output logic        tohost_we,
    output logic [31:0] tohost_data,
    output logic        uart_we,
    output logic [7:0]  uart_data
);

    // halt cause codes
    localparam logic [2:0] HALT_NONE       = 3'd0;
    localparam logic [2:0] HALT_ECALL      = 3'd1;
    localparam logic [2:0] HALT_EBREAK     = 3'd2;
    localparam logic [2:0] HALT_ILLEGAL    = 3'd3;
    localparam logic [2:0] HALT_MISALIGNED = 3'd4;
    localparam logic [2:0] HALT_TOHOST     = 3'd5;

    // ---------- fetch
    logic [31:0] pc, next_pc, pc_plus_4;
    logic [31:0] inst;

    logic halted_q;
    logic halt_now;

    // PC advances only while running.
    pc_register #(.PC_RESET(PC_RESET)) u_pc (
        .clk     (clk),
        .rst     (rst),
        .en      (~halted_q),
        .next_pc (next_pc),
        .pc      (pc)
    );

    assign pc_plus_4 = pc + 32'd4;
    assign pc_out    = pc;

    instr_memory #(.DEPTH_WORDS(IMEM_WORDS)) u_imem (
        .addr (pc),
        .inst (inst)
    );

    // ---------- decode
    control_t ctrl;
    decoder u_decoder (
        .inst (inst),
        .ctrl (ctrl)
    );

    logic [4:0] rs1_idx, rs2_idx, rd_idx;
    assign rs1_idx = inst[19:15];
    assign rs2_idx = inst[24:20];
    assign rd_idx  = inst[11:7];

    logic [31:0] imm;
    imm_gen u_immgen (
        .inst (inst),
        .imm  (imm)
    );

    // ---------- register read
    logic [31:0] rs1_val, rs2_val;
    logic [31:0] wb_data;
    logic        reg_we;

    // WRITE_FIRST=0: single-cycle reads the old value; read and write
    // are the same instruction, so the bypass would be a comb loop.
    reg_file #(.WRITE_FIRST(1'b0)) u_regfile (
        .clk (clk),
        .rst (rst),
        .we  (reg_we),
        .ws  (rd_idx),
        .wd  (wb_data),
        .rs1 (rs1_idx),
        .rs2 (rs2_idx),
        .rd1 (rs1_val),
        .rd2 (rs2_val)
    );

    // ---------- execute
    logic [31:0] alu_a, alu_b, alu_y;
    assign alu_a = (ctrl.alu_src_a == ALU_A_PC)  ? pc  : rs1_val;
    assign alu_b = (ctrl.alu_src_b == ALU_B_IMM) ? imm : rs2_val;

    alu u_alu (
        .a  (alu_a),
        .b  (alu_b),
        .op (ctrl.alu_op),
        .y  (alu_y)
    );

    logic branch_taken;
    branch_unit u_branch (
        .branch_op (ctrl.branch_op),
        .rs1       (rs1_val),
        .rs2       (rs2_val),
        .taken     (branch_taken)
    );

    // ---------- memory
    logic [31:0] dmem_rdata;
    logic        dmem_misaligned;

    data_memory #(
        .DEPTH_WORDS (DMEM_WORDS),
        .TOHOST_ADDR (TOHOST_ADDR),
        .UART_ADDR   (UART_ADDR)
    ) u_dmem (
        .clk          (clk),
        .rst          (rst),
        .addr         (alu_y),
        .write_data   (rs2_val),
        .mem_read     (ctrl.mem_read),
        .mem_write    (ctrl.mem_write & ~halted_q),
        .mem_size     (ctrl.mem_size),
        .mem_unsigned (ctrl.mem_unsigned),
        .read_data    (dmem_rdata),
        .misaligned   (dmem_misaligned),
        .tohost_we    (tohost_we),
        .tohost_data  (tohost_data),
        .uart_we      (uart_we),
        .uart_data    (uart_data)
    );

    // ---------- writeback mux
    always_comb begin
        unique case (ctrl.wb_src)
            WB_ALU:  wb_data = alu_y;
            WB_MEM:  wb_data = dmem_rdata;
            WB_PC4:  wb_data = pc_plus_4;
            default: wb_data = alu_y;
        endcase
    end

    // Register write is suppressed once halted so a frozen PC cannot
    // keep committing the same instruction's result.
    assign reg_we = ctrl.reg_write & ~halted_q;

    // ---------- next PC
    logic [31:0] branch_target, jalr_target;
    assign branch_target = alu_y;            // PC + imm for branch / JAL
    assign jalr_target   = alu_y & ~32'h1;   // (rs1 + imm) with bit 0 cleared

    always_comb begin
        if (branch_taken) begin
            next_pc = ctrl.jalr ? jalr_target : branch_target;
        end else begin
            next_pc = pc_plus_4;
        end
    end

    // ---------- halt detection
    logic is_system, is_ecall, is_ebreak;
    assign is_system = (opcode_e'(inst[6:0]) == OP_SYSTEM) && (inst[14:12] == 3'b000);
    assign is_ecall  = is_system && (inst[31:20] == F12_ECALL);
    assign is_ebreak = is_system && (inst[31:20] == F12_EBREAK);

    // Priority order for the cause code if several fire at once. A
    // misaligned access and an illegal instruction are mutually
    // exclusive in practice (illegal does not access memory), but I
    // pin an order anyway so the reported cause is deterministic.
    always_comb begin
        halt_now = 1'b0;
        halt_cause = HALT_NONE;
        if (!halted_q) begin
            if (ctrl.illegal) begin
                halt_now   = 1'b1;
                halt_cause = HALT_ILLEGAL;
            end else if (dmem_misaligned) begin
                halt_now   = 1'b1;
                halt_cause = HALT_MISALIGNED;
            end else if (is_ecall) begin
                halt_now   = 1'b1;
                halt_cause = HALT_ECALL;
            end else if (is_ebreak) begin
                halt_now   = 1'b1;
                halt_cause = HALT_EBREAK;
            end else if (tohost_we) begin
                halt_now   = 1'b1;
                halt_cause = HALT_TOHOST;
            end
        end else begin
            halt_cause = HALT_NONE; // already stopped; cause was latched by tb
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            halted_q <= 1'b0;
        end else if (halt_now) begin
            halted_q <= 1'b1;
        end
    end

    assign halted = halted_q | halt_now;

endmodule

`default_nettype wire
