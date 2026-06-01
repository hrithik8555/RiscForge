"""Cocotb tests for branch_unit.

Combinational, so I drive operands and the branch kind, then read
`taken` after a settle delay.

The cases that matter most are the signed-vs-unsigned ones: a pair
like (-1, 1) flips the answer between BLT and BLTU, which is the named
bug class from the plan. I test both directions and the boundary case
where the values are equal.

BranchOp enum values come from encoding.py so the test cannot drift
from the package.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))
from encoding import BranchOp  # noqa: E402

MASK = 0xFFFFFFFF


async def decide(dut, op, rs1, rs2):
    dut.branch_op.value = int(op)
    dut.rs1.value = rs1 & MASK
    dut.rs2.value = rs2 & MASK
    await Timer(1, units="ns")
    return int(dut.taken.value)


@cocotb.test()
async def none_never_taken(dut):
    assert (await decide(dut, BranchOp.NONE, 5, 5)) == 0
    assert (await decide(dut, BranchOp.NONE, 0, 99)) == 0


@cocotb.test()
async def jump_always_taken(dut):
    assert (await decide(dut, BranchOp.JUMP, 0, 0)) == 1
    assert (await decide(dut, BranchOp.JUMP, 123, 456)) == 1


@cocotb.test()
async def eq_ne(dut):
    assert (await decide(dut, BranchOp.EQ, 7, 7)) == 1
    assert (await decide(dut, BranchOp.EQ, 7, 8)) == 0
    assert (await decide(dut, BranchOp.NE, 7, 8)) == 1
    assert (await decide(dut, BranchOp.NE, 7, 7)) == 0


@cocotb.test()
async def signed_lt_ge(dut):
    # -1 < 1 as signed
    assert (await decide(dut, BranchOp.LT, MASK, 1)) == 1
    assert (await decide(dut, BranchOp.GE, MASK, 1)) == 0
    # 1 vs -1
    assert (await decide(dut, BranchOp.LT, 1, MASK)) == 0
    assert (await decide(dut, BranchOp.GE, 1, MASK)) == 1
    # equal: LT false, GE true
    assert (await decide(dut, BranchOp.LT, 5, 5)) == 0
    assert (await decide(dut, BranchOp.GE, 5, 5)) == 1


@cocotb.test()
async def unsigned_lt_ge(dut):
    # 0xFFFFFFFF is huge unsigned, so NOT < 1
    assert (await decide(dut, BranchOp.LTU, MASK, 1)) == 0
    assert (await decide(dut, BranchOp.GEU, MASK, 1)) == 1
    # 1 < huge unsigned
    assert (await decide(dut, BranchOp.LTU, 1, MASK)) == 1
    assert (await decide(dut, BranchOp.GEU, 1, MASK)) == 0
    # equal
    assert (await decide(dut, BranchOp.LTU, 5, 5)) == 0
    assert (await decide(dut, BranchOp.GEU, 5, 5)) == 1


@cocotb.test()
async def signed_unsigned_disagree(dut):
    # The exact pair that separates signed from unsigned: a = -1, b = 1.
    # Signed: -1 < 1 -> BLT taken, BLTU not. This is the bug class.
    a, b = MASK, 1
    assert (await decide(dut, BranchOp.LT, a, b)) == 1
    assert (await decide(dut, BranchOp.LTU, a, b)) == 0
