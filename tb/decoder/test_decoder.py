"""Cocotb tests for the decoder, one assertion group per instruction.

The control struct is a single packed bundle on the wire. Rather than
rely on Verilator exposing every struct member to VPI (which is not
portable), I read ctrl as one integer and slice it with the field
table below. That table is the ONE place the layout lives; if
control_t in riscv_pkg.sv changes field order, this table changes too
and every test re-checks the new layout.

Expected enum values come from tools/refmodel/encoding.py, the same
mirror the encoding_check script keeps in lockstep with riscv_pkg.sv.
So this test cannot disagree with the package by drift.

Instruction encodings come from the assembler I already validated, so
I am not hand-assembling words here except for the deliberately-illegal
cases (which the assembler would refuse to emit, correctly).
"""

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "assembler"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))

from assemble import assemble  # noqa: E402
from encoding import AluOp, WbSrc, BranchOp, MemSize, AluSrcA, AluSrcB  # noqa: E402

# control_t layout, MSB-first: the first-declared struct field occupies
# the most significant bits of a SystemVerilog packed struct.
CTRL_FIELDS = [
    ("reg_write", 1),
    ("wb_src", 2),
    ("mem_read", 1),
    ("mem_write", 1),
    ("mem_size", 2),
    ("mem_unsigned", 1),
    ("alu_op", 4),
    ("alu_src_a", 1),
    ("alu_src_b", 1),
    ("branch_op", 3),
    ("jalr", 1),
    ("illegal", 1),
]
CTRL_WIDTH = sum(w for _, w in CTRL_FIELDS)


def unpack_ctrl(value):
    bits = int(value)
    out = {}
    pos = CTRL_WIDTH
    for name, w in CTRL_FIELDS:
        pos -= w
        out[name] = (bits >> pos) & ((1 << w) - 1)
    return out


def asm_word(src: str) -> int:
    words = assemble(src)
    assert words, f"assembler produced nothing for {src!r}"
    return words[0]


async def decode(dut, inst: int) -> dict:
    dut.inst.value = inst & 0xFFFFFFFF
    await Timer(1, units="ns")
    return unpack_ctrl(dut.ctrl.value)


def expect(c: dict, **fields):
    """Assert each named field equals the given value; everything not
    named is left unchecked."""
    for k, v in fields.items():
        assert c[k] == int(v), f"{k}={c[k]}, expected {int(v)} (full ctrl: {c})"


# ---------- U-types and jumps

@cocotb.test()
async def lui(dut):
    c = await decode(dut, asm_word("lui a0, 0x12345"))
    expect(c, reg_write=1, wb_src=WbSrc.ALU, alu_op=AluOp.PASS_B,
           alu_src_b=AluSrcB.IMM, branch_op=BranchOp.NONE, illegal=0)


@cocotb.test()
async def auipc(dut):
    c = await decode(dut, asm_word("auipc a0, 0x12345"))
    expect(c, reg_write=1, wb_src=WbSrc.ALU, alu_op=AluOp.ADD,
           alu_src_a=AluSrcA.PC, alu_src_b=AluSrcB.IMM, illegal=0)


@cocotb.test()
async def jal(dut):
    c = await decode(dut, asm_word("jal ra, tgt\nnop\ntgt: nop\n"))
    expect(c, reg_write=1, wb_src=WbSrc.PC4, alu_src_a=AluSrcA.PC,
           alu_src_b=AluSrcB.IMM, branch_op=BranchOp.JUMP, jalr=0, illegal=0)


@cocotb.test()
async def jalr(dut):
    c = await decode(dut, asm_word("jalr ra, a0, 0"))
    expect(c, reg_write=1, wb_src=WbSrc.PC4, alu_src_a=AluSrcA.RS1,
           alu_src_b=AluSrcB.IMM, branch_op=BranchOp.JUMP, jalr=1, illegal=0)


# ---------- branches (all six conditions)

@cocotb.test()
async def branches(dut):
    cases = [
        ("beq",  BranchOp.EQ),
        ("bne",  BranchOp.NE),
        ("blt",  BranchOp.LT),
        ("bge",  BranchOp.GE),
        ("bltu", BranchOp.LTU),
        ("bgeu", BranchOp.GEU),
    ]
    for mnem, br in cases:
        c = await decode(dut, asm_word(f"{mnem} a0, a1, tgt\nnop\ntgt: nop\n"))
        expect(c, reg_write=0, mem_read=0, mem_write=0,
               alu_src_a=AluSrcA.PC, alu_src_b=AluSrcB.IMM,
               branch_op=br, illegal=0)


# ---------- loads (all five)

@cocotb.test()
async def loads(dut):
    cases = [
        ("lb",  MemSize.B, 0),
        ("lh",  MemSize.H, 0),
        ("lw",  MemSize.W, 0),
        ("lbu", MemSize.B, 1),
        ("lhu", MemSize.H, 1),
    ]
    for mnem, size, uns in cases:
        c = await decode(dut, asm_word(f"{mnem} a0, 0(a1)"))
        expect(c, reg_write=1, wb_src=WbSrc.MEM, mem_read=1, mem_write=0,
               mem_size=size, mem_unsigned=uns, alu_op=AluOp.ADD,
               alu_src_a=AluSrcA.RS1, alu_src_b=AluSrcB.IMM, illegal=0)


# ---------- stores (all three)

@cocotb.test()
async def stores(dut):
    cases = [
        ("sb", MemSize.B),
        ("sh", MemSize.H),
        ("sw", MemSize.W),
    ]
    for mnem, size in cases:
        c = await decode(dut, asm_word(f"{mnem} a0, 0(a1)"))
        expect(c, reg_write=0, mem_read=0, mem_write=1, mem_size=size,
               alu_op=AluOp.ADD, alu_src_a=AluSrcA.RS1,
               alu_src_b=AluSrcB.IMM, illegal=0)


# ---------- OP-IMM (all nine), with the SLTIU and SRAI gotchas

@cocotb.test()
async def op_imm(dut):
    cases = [
        ("addi  a0, a1, 5",  AluOp.ADD),
        ("slti  a0, a1, 5",  AluOp.SLT),
        ("sltiu a0, a1, 5",  AluOp.SLTU),   # immediate still sign-extended (imm_gen)
        ("xori  a0, a1, 5",  AluOp.XOR),
        ("ori   a0, a1, 5",  AluOp.OR),
        ("andi  a0, a1, 5",  AluOp.AND),
        ("slli  a0, a1, 4",  AluOp.SLL),
        ("srli  a0, a1, 4",  AluOp.SRL),
        ("srai  a0, a1, 4",  AluOp.SRA),    # F7_ALT must be honored, else logical
    ]
    for src, op in cases:
        c = await decode(dut, asm_word(src))
        expect(c, reg_write=1, wb_src=WbSrc.ALU, alu_op=op,
               alu_src_a=AluSrcA.RS1, alu_src_b=AluSrcB.IMM,
               mem_read=0, mem_write=0, illegal=0)


# ---------- OP-REG (all ten), with SUB vs ADD and SRA vs SRL by funct7

@cocotb.test()
async def op_reg(dut):
    cases = [
        ("add  a0, a1, a2", AluOp.ADD),
        ("sub  a0, a1, a2", AluOp.SUB),     # F7_ALT
        ("sll  a0, a1, a2", AluOp.SLL),
        ("slt  a0, a1, a2", AluOp.SLT),
        ("sltu a0, a1, a2", AluOp.SLTU),
        ("xor  a0, a1, a2", AluOp.XOR),
        ("srl  a0, a1, a2", AluOp.SRL),
        ("sra  a0, a1, a2", AluOp.SRA),     # F7_ALT
        ("or   a0, a1, a2", AluOp.OR),
        ("and  a0, a1, a2", AluOp.AND),
    ]
    for src, op in cases:
        c = await decode(dut, asm_word(src))
        expect(c, reg_write=1, wb_src=WbSrc.ALU, alu_op=op,
               alu_src_a=AluSrcA.RS1, alu_src_b=AluSrcB.RS2,
               mem_read=0, mem_write=0, branch_op=BranchOp.NONE, illegal=0)


# ---------- explicit SLT/SLTU and SRA/SRL discrimination (named bug class)

@cocotb.test()
async def slt_not_swapped_with_sltu(dut):
    slt  = await decode(dut, asm_word("slt  a0, a1, a2"))
    sltu = await decode(dut, asm_word("sltu a0, a1, a2"))
    assert slt["alu_op"] == int(AluOp.SLT)
    assert sltu["alu_op"] == int(AluOp.SLTU)
    assert slt["alu_op"] != sltu["alu_op"]


@cocotb.test()
async def sra_not_logical(dut):
    sra = await decode(dut, asm_word("sra a0, a1, a2"))
    srl = await decode(dut, asm_word("srl a0, a1, a2"))
    assert sra["alu_op"] == int(AluOp.SRA), "SRA decoded as logical shift"
    assert srl["alu_op"] == int(AluOp.SRL)


# ---------- FENCE / FENCE.I / ECALL / EBREAK decode as legal NOPs

@cocotb.test()
async def fences_and_system_are_nops(dut):
    for src in ("fence", "fence.i", "ecall", "ebreak"):
        c = await decode(dut, asm_word(src))
        expect(c, reg_write=0, mem_read=0, mem_write=0,
               branch_op=BranchOp.NONE, illegal=0)


# ---------- illegal encodings raise the illegal flag

@cocotb.test()
async def illegal_encodings(dut):
    # opcode 0b0001011 is the "custom-0" slot, not part of RV32I base.
    c = await decode(dut, 0x0000000B)
    expect(c, illegal=1)

    # a BRANCH opcode with reserved funct3=010
    branch_resv = (0b1100011) | (0b010 << 12)
    c = await decode(dut, branch_resv)
    expect(c, illegal=1)

    # a SYSTEM opcode with funct3=001 (CSRRW) is unsupported in RTL
    csrrw = (0b1110011) | (0b001 << 12)
    c = await decode(dut, csrrw)
    expect(c, illegal=1)
