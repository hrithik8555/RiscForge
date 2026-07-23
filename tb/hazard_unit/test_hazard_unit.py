"""Cocotb tests for hazard_unit. Combinational load-use detection.

The important cases: stall when a load in EX feeds a register the ID
instruction really reads, and DO NOT stall when the match is only on a
field that this opcode does not use as a register (the over-stall the
plan warns about), when it is not a load, when rd is x0, or when there
is no match.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))
from encoding import Opcode  # noqa: E402


async def probe(dut, mem_read, ex_rd, opcode, rs1, rs2):
    dut.ex_mem_read.value = mem_read
    dut.ex_rd_idx.value = ex_rd
    dut.id_opcode.value = int(opcode)
    dut.id_rs1_idx.value = rs1
    dut.id_rs2_idx.value = rs2
    await Timer(1, units="ns")
    return int(dut.stall.value)


@cocotb.test()
async def no_stall_when_not_a_load(dut):
    # EX writes x5 but is not a load (mem_read=0)
    assert (await probe(dut, 0, 5, Opcode.REG, 5, 9)) == 0


@cocotb.test()
async def stall_on_rs1_dependency(dut):
    # load into x5; an I-type in ID reads x5 as rs1
    assert (await probe(dut, 1, 5, Opcode.IMM, 5, 0)) == 1


@cocotb.test()
async def stall_on_rs2_dependency(dut):
    # load into x7; an R-type in ID reads x7 as rs2
    assert (await probe(dut, 1, 7, Opcode.REG, 3, 7)) == 1


@cocotb.test()
async def no_stall_when_no_match(dut):
    assert (await probe(dut, 1, 5, Opcode.REG, 3, 9)) == 0


@cocotb.test()
async def no_stall_on_x0_load(dut):
    # a load into x0 (dropped) never causes a stall, even if rs matches 0
    assert (await probe(dut, 1, 0, Opcode.REG, 0, 0)) == 0


@cocotb.test()
async def no_overstall_on_unused_rs2_field(dut):
    # An I-type (OP_IMM) does not read rs2; inst[24:20] is immediate
    # bits. Even if that field equals the load's rd, there must be no
    # stall on an rs2 match.
    assert (await probe(dut, 1, 12, Opcode.IMM, 3, 12)) == 0
    # but a genuine rs1 match on the same I-type still stalls
    assert (await probe(dut, 1, 12, Opcode.IMM, 12, 3)) == 1


@cocotb.test()
async def no_stall_on_non_reading_opcodes(dut):
    # LUI and JAL read no register source; a matching field must not stall
    assert (await probe(dut, 1, 5, Opcode.LUI, 5, 5)) == 0
    assert (await probe(dut, 1, 5, Opcode.JAL, 5, 5)) == 0


@cocotb.test()
async def branch_and_store_read_rs2(dut):
    # both branches and stores read rs2, so a load feeding rs2 stalls
    assert (await probe(dut, 1, 8, Opcode.BRANCH, 1, 8)) == 1
    assert (await probe(dut, 1, 8, Opcode.STORE, 1, 8)) == 1
