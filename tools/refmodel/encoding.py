"""RV32I encoding constants for the reference model and the assembler.

This file is the Python mirror of rtl/pkg/riscv_pkg.sv. The two are
hand-kept in sync; scripts/encoding_check.py diffs them and CI fails
on drift.

Spec reference: RISC-V Unprivileged ISA Specification, Volume 1,
version 20191213.

I am keeping the names and values structurally identical to the
SystemVerilog file. Where SV uses a typedef enum named foo_e with
members FOO_BAR, the Python side uses a class Foo(IntEnum) with
member BAR (the underscore-prefix is stripped because each Python
class scopes its own members).
"""

from enum import IntEnum

XLEN = 32


# ---------- opcodes (inst[6:0])
class Opcode(IntEnum):
    LUI    = 0b0110111
    AUIPC  = 0b0010111
    JAL    = 0b1101111
    JALR   = 0b1100111
    BRANCH = 0b1100011
    LOAD   = 0b0000011
    STORE  = 0b0100011
    IMM    = 0b0010011
    REG    = 0b0110011
    FENCE  = 0b0001111
    SYSTEM = 0b1110011


# ---------- funct3 for OP-IMM and OP (R-type). Same values either way.
class F3Op(IntEnum):
    ADD_SUB = 0b000
    SLL     = 0b001
    SLT     = 0b010
    SLTU    = 0b011
    XOR     = 0b100
    SR      = 0b101  # SRL or SRA, funct7 picks
    OR      = 0b110
    AND     = 0b111


class F3Branch(IntEnum):
    BEQ  = 0b000
    BNE  = 0b001
    BLT  = 0b100
    BGE  = 0b101
    BLTU = 0b110
    BGEU = 0b111


class F3Load(IntEnum):
    LB  = 0b000
    LH  = 0b001
    LW  = 0b010
    LBU = 0b100
    LHU = 0b101


class F3Store(IntEnum):
    SB = 0b000
    SH = 0b001
    SW = 0b010


# ---------- funct7 distinguishers
F7_DEFAULT = 0b0000000  # ADD, SRL, SRLI, etc.
F7_ALT     = 0b0100000  # SUB, SRA, SRAI

# ---------- SYSTEM funct12 values for ECALL and EBREAK
F12_ECALL  = 0x000
F12_EBREAK = 0x001


# ---------- ALU operation selector (matches alu_op_e in riscv_pkg.sv)
class AluOp(IntEnum):
    ADD    = 0
    SUB    = 1
    AND    = 2
    OR     = 3
    XOR    = 4
    SLL    = 5
    SRL    = 6
    SRA    = 7
    SLT    = 8
    SLTU   = 9
    PASS_B = 10


# ---------- ALU operand source selects
class AluSrcA(IntEnum):
    RS1 = 0
    PC  = 1


class AluSrcB(IntEnum):
    RS2 = 0
    IMM = 1


# ---------- writeback source
class WbSrc(IntEnum):
    ALU = 0
    MEM = 1
    PC4 = 2


# ---------- branch / jump kind
class BranchOp(IntEnum):
    NONE = 0
    EQ   = 1
    NE   = 2
    LT   = 3
    GE   = 4
    LTU  = 5
    GEU  = 6
    JUMP = 7


# ---------- memory access size
class MemSize(IntEnum):
    B = 0
    H = 1
    W = 2
