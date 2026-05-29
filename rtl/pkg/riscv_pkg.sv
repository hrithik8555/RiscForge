// riscv_pkg.sv
//
// Single source of truth for RV32I encoding constants and the control
// bundle the decoder produces. Every RTL module that needs an opcode,
// a funct3 value, an ALU op selector, or a control struct imports from
// here.
//
// The Python reference model and the Python assembler keep matching
// tables in tools/refmodel/encoding.py. The two are hand-kept in sync;
// scripts/encoding_check.py diffs them and CI fails on drift.
//
// Spec reference: RISC-V Unprivileged ISA Specification, Volume 1,
// version 20191213. Section numbers cited inline where relevant.
//
// Honest note: the control struct here is the full pipeline-stage shape
// (writeback source, branch op, mem size, etc.) even though stage 1 is
// single-cycle. Defining it once means adding pipeline registers later
// touches only the register modules, not the decoder.

`ifndef RISCV_PKG_SV
`define RISCV_PKG_SV

// This package is a constants library. Many of its localparams and enum
// members are referenced by some downstream modules but not by others.
// When Verilator lints a small module like counter.sv alongside the
// package, it flags every package localparam as UNUSEDPARAM "in instance
// counter", which is noise. I silence UNUSEDPARAM only at the package
// level; UNUSED warnings in real modules still fail lint.
/* verilator lint_off UNUSEDPARAM */

package riscv_pkg;

  // ---------- word geometry
  localparam int XLEN = 32;

  // ---------- opcodes (Spec section 24, inst[6:0])
  typedef enum logic [6:0] {
    OP_LUI    = 7'b0110111,
    OP_AUIPC  = 7'b0010111,
    OP_JAL    = 7'b1101111,
    OP_JALR   = 7'b1100111,
    OP_BRANCH = 7'b1100011,
    OP_LOAD   = 7'b0000011,
    OP_STORE  = 7'b0100011,
    OP_IMM    = 7'b0010011,
    OP_REG    = 7'b0110011,
    OP_FENCE  = 7'b0001111,
    OP_SYSTEM = 7'b1110011
  } opcode_e;

  // ---------- funct3 for OP-IMM and OP (R-type)
  // Same funct3 values for the immediate and register-register forms,
  // differentiated by opcode and (for SUB / SRA) by funct7.
  typedef enum logic [2:0] {
    F3_ADD_SUB = 3'b000,
    F3_SLL     = 3'b001,
    F3_SLT     = 3'b010,
    F3_SLTU    = 3'b011,
    F3_XOR     = 3'b100,
    F3_SR      = 3'b101,
    F3_OR      = 3'b110,
    F3_AND     = 3'b111
  } funct3_op_e;

  // ---------- funct3 for conditional branches
  typedef enum logic [2:0] {
    F3_BEQ  = 3'b000,
    F3_BNE  = 3'b001,
    F3_BLT  = 3'b100,
    F3_BGE  = 3'b101,
    F3_BLTU = 3'b110,
    F3_BGEU = 3'b111
  } funct3_branch_e;

  // ---------- funct3 for loads
  typedef enum logic [2:0] {
    F3_LB  = 3'b000,
    F3_LH  = 3'b001,
    F3_LW  = 3'b010,
    F3_LBU = 3'b100,
    F3_LHU = 3'b101
  } funct3_load_e;

  // ---------- funct3 for stores
  typedef enum logic [2:0] {
    F3_SB = 3'b000,
    F3_SH = 3'b001,
    F3_SW = 3'b010
  } funct3_store_e;

  // ---------- funct7 distinguishers (the only ones that matter for RV32I)
  localparam logic [6:0] F7_DEFAULT = 7'b0000000; // ADD, SRL, SRLI, etc.
  localparam logic [6:0] F7_ALT     = 7'b0100000; // SUB, SRA, SRAI

  // ---------- SYSTEM funct12 (used to distinguish ECALL from EBREAK)
  localparam logic [11:0] F12_ECALL  = 12'h000;
  localparam logic [11:0] F12_EBREAK = 12'h001;

  // ---------- ALU operation selector consumed by the EX stage.
  // PASS_B passes operand B through unchanged. Used for LUI, where the
  // immediate IS the result. Cheaper than threading a constant zero
  // into operand A and adding.
  typedef enum logic [3:0] {
    ALU_ADD    = 4'd0,
    ALU_SUB    = 4'd1,
    ALU_AND    = 4'd2,
    ALU_OR     = 4'd3,
    ALU_XOR    = 4'd4,
    ALU_SLL    = 4'd5,
    ALU_SRL    = 4'd6,
    ALU_SRA    = 4'd7,
    ALU_SLT    = 4'd8,
    ALU_SLTU   = 4'd9,
    ALU_PASS_B = 4'd10
  } alu_op_e;

  // ---------- ALU operand source selects
  typedef enum logic {
    ALU_A_RS1 = 1'b0,
    ALU_A_PC  = 1'b1
  } alu_src_a_e;

  typedef enum logic {
    ALU_B_RS2 = 1'b0,
    ALU_B_IMM = 1'b1
  } alu_src_b_e;

  // ---------- writeback source: what value reaches rd in WB
  typedef enum logic [1:0] {
    WB_ALU = 2'd0,
    WB_MEM = 2'd1,
    WB_PC4 = 2'd2
  } wb_src_e;

  // ---------- branch / jump kind. JUMP covers both JAL and JALR (the
  // jalr flag below distinguishes them).
  typedef enum logic [2:0] {
    BR_NONE = 3'd0,
    BR_EQ   = 3'd1,
    BR_NE   = 3'd2,
    BR_LT   = 3'd3,
    BR_GE   = 3'd4,
    BR_LTU  = 3'd5,
    BR_GEU  = 3'd6,
    BR_JUMP = 3'd7
  } branch_op_e;

  // ---------- memory access size for loads and stores
  typedef enum logic [1:0] {
    MEM_B = 2'd0,
    MEM_H = 2'd1,
    MEM_W = 2'd2
  } mem_size_e;

  // ---------- decoder output. The full pipeline-stage shape; stage 1
  // single-cycle uses every field, the pipeline just carries it through
  // the ID/EX, EX/MEM, MEM/WB registers.
  typedef struct packed {
    logic         reg_write;     // write rd in WB?
    wb_src_e      wb_src;        // what value goes to rd
    logic         mem_read;      // load?
    logic         mem_write;     // store?
    mem_size_e    mem_size;      // byte / halfword / word
    logic         mem_unsigned;  // zero-extend the loaded value (LBU, LHU)?
    alu_op_e      alu_op;
    alu_src_a_e   alu_src_a;
    alu_src_b_e   alu_src_b;
    branch_op_e   branch_op;     // BR_NONE for non-branches
    logic         jalr;          // JALR target is rs1+imm, not PC+imm
    logic         illegal;       // decoder raises this on unrecognised inst
  } control_t;

endpackage

/* verilator lint_on UNUSEDPARAM */

`endif
