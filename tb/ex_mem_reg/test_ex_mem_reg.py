"""Cocotb tests for ex_mem_reg: latch the EX result, bubble on reset and
flush. Lighter than id_ex because the payload is smaller and the
behavior is identical in shape."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10
SETTLE_NS = 1
CTRL_NONZERO = 0x7FFFF


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.en.value = 1
    dut.flush.value = 0
    for sig in (dut.ctrl_in, dut.alu_y_in, dut.rs2_val_in, dut.rd_idx_in, dut.pc4_in):
        sig.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def _edge(dut):
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")


@cocotb.test()
async def latches_payload(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    dut.alu_y_in.value = 0xABCD1234
    dut.rs2_val_in.value = 0x0BADF00D
    dut.rd_idx_in.value = 9
    dut.pc4_in.value = 0x208
    await _edge(dut)
    assert int(dut.ctrl.value) == CTRL_NONZERO
    assert int(dut.alu_y.value) == 0xABCD1234
    assert int(dut.rs2_val.value) == 0x0BADF00D
    assert int(dut.rd_idx.value) == 9
    assert int(dut.pc4.value) == 0x208


@cocotb.test()
async def reset_and_flush_bubble(dut):
    await _start(dut)
    assert int(dut.ctrl.value) == 0   # after reset

    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    dut.alu_y_in.value = 0xFFFFFFFF
    await _edge(dut)
    assert int(dut.ctrl.value) == CTRL_NONZERO

    await FallingEdge(dut.clk)
    dut.flush.value = 1
    await _edge(dut)
    assert int(dut.ctrl.value) == 0, "flush did not bubble the control bundle"
