"""Cocotb tests for the ALU. Purely combinational, so I drive inputs
and read y after a small settle delay.

The cases pre-empt the bug list from the plan:
  - SRA must sign-extend, not zero-fill.
  - SLT vs SLTU on operands with different sign bits.
  - Shifts only use the low 5 bits of operand B.
"""

import cocotb
from cocotb.triggers import Timer

# Mirror of alu_op_e in rtl/pkg/riscv_pkg.sv. The encoding_check script
# guarantees this matches encoding.py, which we use as the truth.
ALU_ADD    = 0
ALU_SUB    = 1
ALU_AND    = 2
ALU_OR     = 3
ALU_XOR    = 4
ALU_SLL    = 5
ALU_SRL    = 6
ALU_SRA    = 7
ALU_SLT    = 8
ALU_SLTU   = 9
ALU_PASS_B = 10

MASK = 0xFFFFFFFF


def s32(x):
    """Interpret an unsigned 32-bit value as signed."""
    return x - (1 << 32) if x & (1 << 31) else x


async def drive(dut, a, b, op):
    dut.a.value = a & MASK
    dut.b.value = b & MASK
    dut.op.value = op
    await Timer(1, units="ns")
    return int(dut.y.value) & MASK


@cocotb.test()
async def add_sub(dut):
    assert (await drive(dut, 3, 4, ALU_ADD)) == 7
    assert (await drive(dut, 0, 0, ALU_ADD)) == 0
    # overflow wraps
    assert (await drive(dut, MASK, 1, ALU_ADD)) == 0
    assert (await drive(dut, 10, 3, ALU_SUB)) == 7
    # negative result wraps
    assert (await drive(dut, 0, 1, ALU_SUB)) == MASK


@cocotb.test()
async def bitwise(dut):
    assert (await drive(dut, 0xF0F0F0F0, 0x0F0F0F0F, ALU_AND)) == 0
    assert (await drive(dut, 0xF0F0F0F0, 0x0F0F0F0F, ALU_OR))  == 0xFFFFFFFF
    assert (await drive(dut, 0xF0F0F0F0, 0xFFFFFFFF, ALU_XOR)) == 0x0F0F0F0F


@cocotb.test()
async def shifts(dut):
    assert (await drive(dut, 0x1, 4, ALU_SLL)) == 0x10
    assert (await drive(dut, 0xF0000000, 4, ALU_SRL)) == 0x0F000000
    # SRA: signed shift, sign bit is preserved
    assert (await drive(dut, 0xF0000000, 4, ALU_SRA)) == 0xFF000000
    # only low 5 bits of b should count
    assert (await drive(dut, 0x1, 32 + 4, ALU_SLL)) == 0x10


@cocotb.test()
async def slt_signed_vs_unsigned(dut):
    # -1 vs 1: signed -1 < 1, unsigned 0xFFFFFFFF > 1
    assert (await drive(dut, MASK, 1, ALU_SLT))  == 1  # signed: -1 < 1
    assert (await drive(dut, MASK, 1, ALU_SLTU)) == 0  # unsigned: huge > 1
    # equal
    assert (await drive(dut, 5, 5, ALU_SLT))  == 0
    assert (await drive(dut, 5, 5, ALU_SLTU)) == 0
    # opposite signs: a positive, b negative
    assert (await drive(dut, 1, MASK, ALU_SLT))  == 0  # signed: 1 > -1
    assert (await drive(dut, 1, MASK, ALU_SLTU)) == 1  # unsigned: 1 < huge


@cocotb.test()
async def pass_b(dut):
    # PASS_B exists for LUI: result is the U-immediate, ignoring a.
    assert (await drive(dut, 0xAAAAAAAA, 0xC0FFEE00, ALU_PASS_B)) == 0xC0FFEE00


@cocotb.test()
async def sra_edge_positive(dut):
    # SRA of a positive number must zero-fill (the sign IS zero).
    assert (await drive(dut, 0x70000000, 4, ALU_SRA)) == 0x07000000
