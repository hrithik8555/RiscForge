"""Cocotb tests for id_ex_reg.

This register carries the control bundle plus the execute-stage
operands. control_t is a 19-bit packed bus here; I drive it and read it
as a raw integer (the field layout is the decoder's concern, not this
register's). The one property that matters for the bundle is that flush
and reset force it to all-zero, which is a NOP (reg_write=0, etc.).
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10
SETTLE_NS = 1
CTRL_NONZERO = 0x7FFFF   # all 19 control bits set, an obvious "not a bubble"


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.en.value = 1
    dut.flush.value = 0
    for sig in (dut.ctrl_in, dut.pc_in, dut.pc4_in, dut.rs1_val_in,
                dut.rs2_val_in, dut.imm_in, dut.rs1_idx_in, dut.rs2_idx_in,
                dut.rd_idx_in):
        sig.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def _edge(dut):
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")


@cocotb.test()
async def reset_is_bubble(dut):
    await _start(dut)
    assert int(dut.ctrl.value) == 0


@cocotb.test()
async def latches_payload(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    dut.rs1_val_in.value = 0xCAFEBABE
    dut.rs2_val_in.value = 0x12345678
    dut.imm_in.value = 0x0000ABCD
    dut.rs1_idx_in.value = 5
    dut.rs2_idx_in.value = 6
    dut.rd_idx_in.value = 7
    await _edge(dut)
    assert int(dut.ctrl.value) == CTRL_NONZERO
    assert int(dut.rs1_val.value) == 0xCAFEBABE
    assert int(dut.rs2_val.value) == 0x12345678
    assert int(dut.imm.value) == 0x0000ABCD
    assert int(dut.rs1_idx.value) == 5
    assert int(dut.rs2_idx.value) == 6
    assert int(dut.rd_idx.value) == 7


@cocotb.test()
async def flush_makes_bubble(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    await _edge(dut)
    assert int(dut.ctrl.value) == CTRL_NONZERO

    await FallingEdge(dut.clk)
    dut.flush.value = 1
    await _edge(dut)
    assert int(dut.ctrl.value) == 0, "flush did not zero the control bundle"


@cocotb.test()
async def holds_on_stall(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    dut.rs1_val_in.value = 0x99999999
    await _edge(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 0
    dut.ctrl_in.value = 0          # would be a bubble if it latched
    dut.rs1_val_in.value = 0x11111111
    for _ in range(3):
        await _edge(dut)
        assert int(dut.ctrl.value) == CTRL_NONZERO, "control moved while stalled"
        assert int(dut.rs1_val.value) == 0x99999999


@cocotb.test()
async def flush_beats_stall(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    await _edge(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 0
    dut.flush.value = 1
    await _edge(dut)
    assert int(dut.ctrl.value) == 0, "flush should win over stall"
