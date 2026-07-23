// top_pipeline.sv
//
// The 5-stage pipelined RV32I core: IF, ID, EX, MEM, WB. This is the
// stage-2 skeleton. It is deliberately additive: the single-cycle
// top.sv is untouched and all its tests stay green. When the pipeline
// is complete (forwarding + load-use stall + branch-in-ID), the test
// harnesses switch over to this module.
//
// What is here at 2.1:
//   - the four pipeline registers wired into a working pipe
//   - branches and jumps resolved in EX, with a 2-cycle flush of the
//     two wrong-path instructions in IF/ID and ID/EX (predict-not-taken)
//   - a clean halt that keeps the register file matching the emulator
//
// What is NOT here yet (so programs must be NOP-padded):
//   - no forwarding: a value written in WB is only visible to an ID
//     read via the write-first register file, which is three stages
//     later. So a dependent instruction needs two NOPs behind its
//     producer. Forwarding (2.2) removes that.
//   - no load-use stall (2.3).
//   - branch resolution is in EX, not ID (2.4/2.5), so the penalty is
//     two cycles, not one.
//
// Halt model. A shadow "cause pipeline" runs alongside the real one:
// ecall/ebreak/illegal are detected in ID, misaligned/tohost in MEM,
// and the cause is carried to WB. `halted` asserts when a nonzero
// cause reaches WB. At that instant every instruction older than the
// halting one has already passed WB (committed), the halting
// instruction itself commits nothing (ecall/illegal have reg_write=0),
// and every younger instruction is still upstream of WB, so none has
// written back. The architectural state therefore equals the
// emulator's state at the same instruction. Because illegal and ecall
// commit nothing, I do not need drain logic: even the garbage fetched
// past an ecall (zeroed memory decodes as illegal) is harmless, and
// the older ecall reaches WB first and freezes the pipe.

`default_nettype none

module top_pipeline
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
    output logic [31:0] tohost_value,   // latched tohost word at halt
    output logic        tohost_we,      // MEM-stage tohost store strobe
    output logic [31:0] tohost_data,    // MEM-stage tohost store data
    output logic        uart_we,        // MEM-stage UART store strobe
    output logic [7:0]  uart_data
);

    // halt cause codes, same as single-cycle top.sv
    localparam logic [2:0] HC_NONE       = 3'd0;
    localparam logic [2:0] HC_ECALL      = 3'd1;
    localparam logic [2:0] HC_EBREAK     = 3'd2;
    localparam logic [2:0] HC_ILLEGAL    = 3'd3;
    localparam logic [2:0] HC_MISALIGNED = 3'd4;
    localparam logic [2:0] HC_TOHOST     = 3'd5;

    // ---------------------------------------------------------------
    // stall / flush wiring
    // ---------------------------------------------------------------
    logic pipe_en;               // back of pipe (EX/MEM/WB): frozen on halt
    logic front_en;              // PC + IF/ID: also frozen on a stall
    logic id_redirect;           // a taken branch/jump resolved in ID
    logic stall;                 // load-use or branch-operand stall
    logic halted_q;

    assign halted     = (wb_hc != HC_NONE) | halted_q;
    assign pipe_en    = ~halted;
    // On a stall the front of the pipe holds (the stalling instruction
    // waits in ID) while the back keeps draining, and a bubble goes
    // into ID/EX. A branch resolves in ID and redirects the PC while
    // flushing only the one wrong-path instruction behind it in IF/ID.
    assign front_en   = ~halted & ~stall;
    // wb_hc is nonzero only for a halting instruction in WB, and the
    // pipe freezes the same cycle (pipe_en=0), so wb_hc holds. Drive
    // the cause straight from it, valid the cycle halted asserts.
    assign halt_cause = wb_hc;

    // ===============================================================
    // IF stage
    // ===============================================================
    logic [31:0] if_pc, if_pc4, if_inst, next_pc;

    pc_register #(.PC_RESET(PC_RESET)) u_pc (
        .clk     (clk),
        .rst     (rst),
        .en      (front_en),
        .next_pc (next_pc),
        .pc      (if_pc)
    );

    assign if_pc4  = if_pc + 32'd4;
    assign pc_out  = if_pc;

    instr_memory #(.DEPTH_WORDS(IMEM_WORDS)) u_imem (
        .addr (if_pc),
        .inst (if_inst)
    );

    // ---------------- IF/ID register
    logic [31:0] id_pc, id_pc4, id_inst;

    if_id_reg u_if_id (
        .clk     (clk),
        .rst     (rst),
        .en      (front_en),
        .flush   (id_redirect),
        .pc_in   (if_pc),
        .pc4_in  (if_pc4),
        .inst_in (if_inst),
        .pc      (id_pc),
        .pc4     (id_pc4),
        .inst    (id_inst)
    );

    // ===============================================================
    // ID stage
    // ===============================================================
    control_t    id_ctrl;
    logic [31:0] id_imm;
    logic [4:0]  id_rs1_idx, id_rs2_idx, id_rd_idx;
    logic [31:0] id_rs1_val, id_rs2_val;

    decoder u_decoder (.inst(id_inst), .ctrl(id_ctrl));
    imm_gen u_immgen  (.inst(id_inst), .imm(id_imm));

    assign id_rs1_idx = id_inst[19:15];
    assign id_rs2_idx = id_inst[24:20];
    assign id_rd_idx  = id_inst[11:7];

    // Load-use hazard: a load in EX feeding a source this ID
    // instruction reads. ex_ctrl and ex_rd_idx are the ID/EX register
    // outputs (declared in the EX section below).
    logic load_use_stall;
    hazard_unit u_hazard (
        .ex_mem_read (ex_ctrl.mem_read),
        .ex_rd_idx   (ex_rd_idx),
        .id_opcode   (opcode_e'(id_inst[6:0])),
        .id_rs1_idx  (id_rs1_idx),
        .id_rs2_idx  (id_rs2_idx),
        .stall       (load_use_stall)
    );

    // register file: read here in ID, write from WB. Write-first so a
    // WB write is visible to a same-cycle ID read (the only hazard the
    // NOP padding relies on).
    logic        wb_we;
    logic [4:0]  wb_rd_idx;
    logic [31:0] wb_data;

    reg_file #(.WRITE_FIRST(1'b1)) u_regfile (
        .clk (clk),
        .rst (rst),
        .we  (wb_we),
        .ws  (wb_rd_idx),
        .wd  (wb_data),
        .rs1 (id_rs1_idx),
        .rs2 (id_rs2_idx),
        .rd1 (id_rs1_val),
        .rd2 (id_rs2_val)
    );

    // halt cause of the instruction currently in ID (combinational)
    logic        id_is_system, id_is_ecall, id_is_ebreak;
    logic [2:0]  id_hc;
    assign id_is_system = (opcode_e'(id_inst[6:0]) == OP_SYSTEM) && (id_inst[14:12] == 3'b000);
    assign id_is_ecall  = id_is_system && (id_inst[31:20] == F12_ECALL);
    assign id_is_ebreak = id_is_system && (id_inst[31:20] == F12_EBREAK);
    always_comb begin
        if      (id_ctrl.illegal) id_hc = HC_ILLEGAL;
        else if (id_is_ecall)     id_hc = HC_ECALL;
        else if (id_is_ebreak)    id_hc = HC_EBREAK;
        else                      id_hc = HC_NONE;
    end

    // ---------------------------------------------------------------
    // Branch / jump resolution in ID (1-cycle penalty)
    // ---------------------------------------------------------------
    // Which control instruction this is and which registers it reads.
    logic id_is_cond_branch, id_is_jalr, id_ctrl_reads_rs1, id_ctrl_reads_rs2;
    assign id_is_cond_branch = (id_ctrl.branch_op != BR_NONE) && (id_ctrl.branch_op != BR_JUMP);
    assign id_is_jalr        = (id_ctrl.branch_op == BR_JUMP) && id_ctrl.jalr;
    assign id_ctrl_reads_rs1 = id_is_cond_branch || id_is_jalr; // compare or target base
    assign id_ctrl_reads_rs2 = id_is_cond_branch;               // second compare operand

    // Forward to the ID comparator from the MEM stage. mem_wb_value is
    // the value the MEM instruction will write back, INCLUDING a load's
    // data (mem_rdata), so a load feeding a branch two instructions
    // later needs no stall. A producer already in WB is covered by the
    // write-first register file, so id_rs*_val already reflects it.
    logic [31:0] id_rs1_cmp, id_rs2_cmp;
    logic        mem_writes_rs1, mem_writes_rs2;
    assign mem_writes_rs1 = mem_ctrl.reg_write && (mem_rd_idx != 5'd0) && (mem_rd_idx == id_rs1_idx);
    assign mem_writes_rs2 = mem_ctrl.reg_write && (mem_rd_idx != 5'd0) && (mem_rd_idx == id_rs2_idx);
    assign id_rs1_cmp = mem_writes_rs1 ? mem_wb_value : id_rs1_val;
    assign id_rs2_cmp = mem_writes_rs2 ? mem_wb_value : id_rs2_val;

    // The one case forwarding cannot cover: the operand is still being
    // computed by the instruction in EX (the producer immediately ahead
    // of the branch). Stall one cycle so that producer reaches MEM,
    // where its value can be forwarded. Only stall on a register the
    // control instruction actually reads.
    logic branch_stall;
    assign branch_stall =
        ex_ctrl.reg_write && (ex_rd_idx != 5'd0) &&
        ((id_ctrl_reads_rs1 && (ex_rd_idx == id_rs1_idx)) ||
         (id_ctrl_reads_rs2 && (ex_rd_idx == id_rs2_idx)));

    assign stall = load_use_stall | branch_stall;

    // Resolve. branch_unit handles the six conditions and BR_JUMP
    // (always taken). Do not act while stalling: the operands are not
    // ready yet, so the redirect waits until the stall clears.
    logic id_taken;
    branch_unit u_branch (
        .branch_op (id_ctrl.branch_op),
        .rs1       (id_rs1_cmp),
        .rs2       (id_rs2_cmp),
        .taken     (id_taken)
    );

    logic [31:0] id_jalr_target, id_pcrel_target;
    assign id_jalr_target  = (id_rs1_cmp + id_imm) & ~32'h1;   // JALR: rs1 + imm
    assign id_pcrel_target = id_pc + id_imm;                    // branch / JAL: PC + imm
    logic [31:0] id_target;
    assign id_target   = id_ctrl.jalr ? id_jalr_target : id_pcrel_target;
    assign id_redirect = id_taken && ~stall;

    // next PC: redirect on a resolved branch/jump, else fall through.
    assign next_pc = id_redirect ? id_target : if_pc4;

    // ---------------- ID/EX register
    control_t    ex_ctrl;
    logic [31:0] ex_pc, ex_pc4, ex_rs1_val, ex_rs2_val, ex_imm;
    logic [4:0]  ex_rd_idx, ex_rs1_idx, ex_rs2_idx;

    // A stall inserts a bubble here (the stalling instruction stays in
    // ID). A branch redirect does NOT bubble ID/EX: the branch itself
    // flows on into EX; only its wrong-path successor in IF/ID is
    // squashed.
    id_ex_reg u_id_ex (
        .clk        (clk),
        .rst        (rst),
        .en         (pipe_en),
        .flush      (stall),
        .ctrl_in    (id_ctrl),
        .pc_in      (id_pc),
        .pc4_in     (id_pc4),
        .rs1_val_in (id_rs1_val),
        .rs2_val_in (id_rs2_val),
        .imm_in     (id_imm),
        .rs1_idx_in (id_rs1_idx),
        .rs2_idx_in (id_rs2_idx),
        .rd_idx_in  (id_rd_idx),
        .ctrl       (ex_ctrl),
        .pc         (ex_pc),
        .pc4        (ex_pc4),
        .rs1_val    (ex_rs1_val),
        .rs2_val    (ex_rs2_val),
        .imm        (ex_imm),
        .rs1_idx    (ex_rs1_idx),
        .rs2_idx    (ex_rs2_idx),
        .rd_idx     (ex_rd_idx)
    );

    // ===============================================================
    // EX stage
    // ===============================================================
    logic [31:0] ex_alu_a, ex_alu_b, ex_alu_y;

    // Forwarding. mem_* and wb_* are the EX/MEM and MEM/WB register
    // outputs declared further down; referencing them here is fine at
    // module scope. The selects come from forwarding_unit; the value
    // each source carries is decided in the datapath below.
    logic [1:0]  fwd_a, fwd_b;
    forwarding_unit u_fwd (
        .ex_rs1_idx       (ex_rs1_idx),
        .ex_rs2_idx       (ex_rs2_idx),
        .ex_mem_reg_write (mem_ctrl.reg_write),
        .ex_mem_rd        (mem_rd_idx),
        .mem_wb_reg_write (wb_ctrl.reg_write),
        .mem_wb_rd        (wb_rd_idx),
        .forward_a        (fwd_a),
        .forward_b        (fwd_b)
    );

    // The value the MEM-stage instruction will write back, for an
    // EX-EX forward. A JAL/JALR writes PC+4 (the link), not the ALU
    // result, so pick by wb_src. A load (WB_MEM) has no data yet in
    // MEM; that is the load-use case handled by the stall in 2.3, so
    // the default (mem_alu_y) is never actually consumed for a load.
    logic [31:0] mem_fwd_value;
    always_comb begin
        unique case (mem_ctrl.wb_src)
            WB_PC4:  mem_fwd_value = mem_pc4;
            default: mem_fwd_value = mem_alu_y;
        endcase
    end

    // Forwarded operands. MEM/WB forwards the final writeback value
    // (wb_data), which for a load is the loaded data, so a load-use
    // hazard with one instruction of separation is covered here.
    logic [31:0] ex_rs1_fwd, ex_rs2_fwd;
    always_comb begin
        unique case (fwd_a)
            2'b01:   ex_rs1_fwd = mem_fwd_value;  // EX/MEM
            2'b10:   ex_rs1_fwd = wb_data;        // MEM/WB
            default: ex_rs1_fwd = ex_rs1_val;
        endcase
        unique case (fwd_b)
            2'b01:   ex_rs2_fwd = mem_fwd_value;
            2'b10:   ex_rs2_fwd = wb_data;
            default: ex_rs2_fwd = ex_rs2_val;
        endcase
    end

    assign ex_alu_a = (ex_ctrl.alu_src_a == ALU_A_PC)  ? ex_pc  : ex_rs1_fwd;
    assign ex_alu_b = (ex_ctrl.alu_src_b == ALU_B_IMM) ? ex_imm : ex_rs2_fwd;

    alu u_alu (.a(ex_alu_a), .b(ex_alu_b), .op(ex_ctrl.alu_op), .y(ex_alu_y));

    // Branches, JAL and JALR are resolved in ID (see the ID stage), so
    // the EX stage no longer redirects. For a jump the EX ALU result is
    // unused (the link value PC+4 is what gets written back).

    // ---------------- EX/MEM register
    control_t    mem_ctrl;
    logic [31:0] mem_alu_y, mem_rs2_val, mem_pc4;
    logic [4:0]  mem_rd_idx;

    ex_mem_reg u_ex_mem (
        .clk        (clk),
        .rst        (rst),
        .en         (pipe_en),
        .flush      (1'b0),
        .ctrl_in    (ex_ctrl),
        .alu_y_in   (ex_alu_y),
        .rs2_val_in (ex_rs2_fwd),   // store data, forwarded
        .rd_idx_in  (ex_rd_idx),
        .pc4_in     (ex_pc4),
        .ctrl       (mem_ctrl),
        .alu_y      (mem_alu_y),
        .rs2_val    (mem_rs2_val),
        .rd_idx     (mem_rd_idx),
        .pc4        (mem_pc4)
    );

    // ===============================================================
    // MEM stage
    // ===============================================================
    logic [31:0] mem_rdata;
    logic        mem_misaligned;
    // tohost_we/tohost_data/uart_we/uart_data are module output ports.

    data_memory #(
        .DEPTH_WORDS (DMEM_WORDS),
        .TOHOST_ADDR (TOHOST_ADDR),
        .UART_ADDR   (UART_ADDR)
    ) u_dmem (
        .clk          (clk),
        .rst          (rst),
        .addr         (mem_alu_y),
        .write_data   (mem_rs2_val),
        .mem_read     (mem_ctrl.mem_read),
        .mem_write    (mem_ctrl.mem_write & pipe_en),
        .mem_size     (mem_ctrl.mem_size),
        .mem_unsigned (mem_ctrl.mem_unsigned),
        .read_data    (mem_rdata),
        .misaligned   (mem_misaligned),
        .tohost_we    (tohost_we),
        .tohost_data  (tohost_data),
        .uart_we      (uart_we),
        .uart_data    (uart_data)
    );

    // The value the MEM instruction will write back, used to forward to
    // the ID-stage branch comparator. Unlike the EX-EX mem_fwd_value,
    // this one includes a load's data (mem_rdata), because a branch in
    // ID can legitimately depend on a load already in MEM.
    logic [31:0] mem_wb_value;
    always_comb begin
        unique case (mem_ctrl.wb_src)
            WB_MEM:  mem_wb_value = mem_rdata;
            WB_PC4:  mem_wb_value = mem_pc4;
            default: mem_wb_value = mem_alu_y;
        endcase
    end

    // ---------------- MEM/WB register
    // verilator lint_off UNUSEDSIGNAL
    // WB consumes only reg_write and wb_src; the rest of the bundle
    // rode along because every pipeline register threads the whole
    // control_t struct (one edit to add a signal, per the design note).
    control_t    wb_ctrl;
    // verilator lint_on UNUSEDSIGNAL
    logic [31:0] wb_alu_y, wb_mem_rdata, wb_pc4;

    mem_wb_reg u_mem_wb (
        .clk          (clk),
        .rst          (rst),
        .en           (pipe_en),
        .flush        (1'b0),
        .ctrl_in      (mem_ctrl),
        .alu_y_in     (mem_alu_y),
        .mem_rdata_in (mem_rdata),
        .rd_idx_in    (mem_rd_idx),
        .pc4_in       (mem_pc4),
        .ctrl         (wb_ctrl),
        .alu_y        (wb_alu_y),
        .mem_rdata    (wb_mem_rdata),
        .rd_idx       (wb_rd_idx),
        .pc4          (wb_pc4)
    );

    // ===============================================================
    // WB stage
    // ===============================================================
    always_comb begin
        unique case (wb_ctrl.wb_src)
            WB_ALU:  wb_data = wb_alu_y;
            WB_MEM:  wb_data = wb_mem_rdata;
            WB_PC4:  wb_data = wb_pc4;
            default: wb_data = wb_alu_y;
        endcase
    end
    assign wb_we = wb_ctrl.reg_write & ~halted;

    // ===============================================================
    // shadow halt-cause pipeline (ID -> EX -> MEM -> WB)
    // ===============================================================
    logic [2:0] ex_hc, mem_hc_carried, mem_hc, wb_hc;

    // At MEM, a misaligned access or a tohost store overrides whatever
    // cause the instruction carried from ID (a plain store carries none).
    always_comb begin
        if      (mem_misaligned) mem_hc = HC_MISALIGNED;
        else if (tohost_we)      mem_hc = HC_TOHOST;
        else                     mem_hc = mem_hc_carried;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            ex_hc          <= HC_NONE;
            mem_hc_carried <= HC_NONE;
            wb_hc          <= HC_NONE;
        end else if (pipe_en) begin
            // A stall bubble carries no halt cause, matching the ID/EX
            // bubble. A branch redirect does not bubble ID/EX (the
            // branch flows on), so there is no redirect term here.
            ex_hc          <= stall ? HC_NONE : id_hc;
            mem_hc_carried <= ex_hc;
            wb_hc          <= mem_hc;
        end
    end

    // latch the halt cause and tohost value at the moment we stop
    always_ff @(posedge clk) begin
        if (rst) begin
            halted_q     <= 1'b0;
            tohost_value <= 32'h0;
        end else begin
            if (tohost_we && !halted) begin
                tohost_value <= tohost_data;
            end
            if (halted) begin
                halted_q <= 1'b1;
            end
        end
    end

endmodule

`default_nettype wire
