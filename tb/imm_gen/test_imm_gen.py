"""Cocotb tests for imm_gen.

The trusted source for what each immediate should be is the Python
assembler, which I built and tested against the spec table. So
instead of hand-tracing twenty bit-scrambles here, I assemble a
single instruction with known operands, hand the encoded word to
imm_gen, and check that imm matches what the assembler put in.

That collapses the test into one consistent loop and means a bug in
either the assembler or imm_gen surfaces here. The deep cross-check
that they agree with the emulator already lives in the assembler
tests; this file checks RTL vs assembler.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "assembler"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))

from assemble import assemble  # noqa: E402

MASK = 0xFFFFFFFF


def asm_word(src: str) -> int:
    """Assemble one line, return the first emitted instruction word."""
    words = assemble(src)
    assert words, f"assembler produced nothing for {src!r}"
    return words[0]


def s32(x):
    return x - (1 << 32) if x & (1 << 31) else x


async def drive_inst(dut, inst):
    dut.inst.value = inst & MASK
    await Timer(1, units="ns")
    return int(dut.imm.value) & MASK


@cocotb.test()
async def i_type_positive(dut):
    # addi a0, a1, 5 -> imm = 5
    w = asm_word("addi a0, a1, 5")
    assert s32(await drive_inst(dut, w)) == 5


@cocotb.test()
async def i_type_negative(dut):
    # addi a0, a1, -1 -> imm = -1 (sign-extended)
    w = asm_word("addi a0, a1, -1")
    assert s32(await drive_inst(dut, w)) == -1


@cocotb.test()
async def s_type(dut):
    # sw a0, -8(sp) -> imm = -8
    w = asm_word("sw a0, -8(sp)")
    assert s32(await drive_inst(dut, w)) == -8


@cocotb.test()
async def b_type_forward(dut):
    # beq a0, a1, +16
    src = "beq a0, a1, tgt\nnop\nnop\nnop\ntgt: nop\n"
    from assemble import assemble as A
    w = A(src)[0]
    assert s32(await drive_inst(dut, w)) == 16


@cocotb.test()
async def b_type_backward(dut):
    src = "start: nop\nnop\nbeq a0, a1, start\n"
    from assemble import assemble as A
    w = A(src)[2]
    assert s32(await drive_inst(dut, w)) == -8


@cocotb.test()
async def u_type(dut):
    # lui a0, 0x12345 -> imm should be 0x12345 << 12 = 0x12345000
    w = asm_word("lui a0, 0x12345")
    assert (await drive_inst(dut, w)) == 0x12345000


@cocotb.test()
async def j_type_forward(dut):
    src = "jal ra, tgt\nnop\nnop\ntgt: nop\n"
    from assemble import assemble as A
    w = A(src)[0]
    assert s32(await drive_inst(dut, w)) == 12


@cocotb.test()
async def jalr_uses_i_type(dut):
    # jalr ra, 12(a0) -> imm should be 12
    w = asm_word("jalr ra, a0, 12")
    assert s32(await drive_inst(dut, w)) == 12
