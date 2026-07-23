"""Cocotb tests for forwarding_unit. Combinational, so I drive the
indices and reg_write flags and read the two selects.

Covers every path the plan cares about: no-forward, EX-EX for each
operand, MEM-EX for each operand, the EX-EX-wins priority when both
match, and the x0 / reg_write=0 cases that must NOT forward.
"""

import cocotb
from cocotb.triggers import Timer

FWD_NONE = 0b00
FWD_EXMEM = 0b01
FWD_MEMWB = 0b10


async def pick(dut, rs1, rs2, exmem_we, exmem_rd, memwb_we, memwb_rd):
    dut.ex_rs1_idx.value = rs1
    dut.ex_rs2_idx.value = rs2
    dut.ex_mem_reg_write.value = exmem_we
    dut.ex_mem_rd.value = exmem_rd
    dut.mem_wb_reg_write.value = memwb_we
    dut.mem_wb_rd.value = memwb_rd
    await Timer(1, units="ns")
    return int(dut.forward_a.value), int(dut.forward_b.value)


@cocotb.test()
async def no_forward_when_no_match(dut):
    a, b = await pick(dut, 5, 6, 1, 7, 1, 8)
    assert a == FWD_NONE and b == FWD_NONE


@cocotb.test()
async def ex_ex_forward_each_operand(dut):
    # MEM stage writes x5; EX reads x5 as rs1
    a, b = await pick(dut, 5, 9, 1, 5, 0, 0)
    assert a == FWD_EXMEM and b == FWD_NONE
    # ... as rs2
    a, b = await pick(dut, 9, 5, 1, 5, 0, 0)
    assert a == FWD_NONE and b == FWD_EXMEM


@cocotb.test()
async def mem_ex_forward_each_operand(dut):
    # WB stage writes x12; EX reads x12
    a, b = await pick(dut, 12, 9, 0, 0, 1, 12)
    assert a == FWD_MEMWB and b == FWD_NONE
    a, b = await pick(dut, 9, 12, 0, 0, 1, 12)
    assert a == FWD_NONE and b == FWD_MEMWB


@cocotb.test()
async def ex_ex_beats_mem_ex(dut):
    # both MEM and WB write x5; EX-EX (younger) must win
    a, b = await pick(dut, 5, 5, 1, 5, 1, 5)
    assert a == FWD_EXMEM and b == FWD_EXMEM


@cocotb.test()
async def x0_never_forwarded(dut):
    # a write to x0 (rd=0) must not forward even though rs=0 matches
    a, b = await pick(dut, 0, 0, 1, 0, 1, 0)
    assert a == FWD_NONE and b == FWD_NONE


@cocotb.test()
async def no_forward_without_reg_write(dut):
    # rd matches but the producer does not write a register (e.g. a store)
    a, b = await pick(dut, 5, 6, 0, 5, 0, 6)
    assert a == FWD_NONE and b == FWD_NONE


@cocotb.test()
async def mem_ex_when_exmem_is_different_reg(dut):
    # MEM writes x3 (irrelevant), WB writes x5 which EX needs -> MEM-EX
    a, b = await pick(dut, 5, 5, 1, 3, 1, 5)
    assert a == FWD_MEMWB and b == FWD_MEMWB
