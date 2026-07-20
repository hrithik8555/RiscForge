"""Cocotb tests for mem_wb_reg: latch the memory-stage result, bubble on
reset and flush. Same shape as the other carrying registers."""

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
    for sig in (dut.ctrl_in, dut.alu_y_in, dut.mem_rdata_in, dut.rd_idx_in, dut.pc4_in):
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
    dut.alu_y_in.value = 0x11223344
    dut.mem_rdata_in.value = 0x55667788
    dut.rd_idx_in.value = 12
    dut.pc4_in.value = 0x30C
    await _edge(dut)
    assert int(dut.ctrl.value) == CTRL_NONZERO
    assert int(dut.alu_y.value) == 0x11223344
    assert int(dut.mem_rdata.value) == 0x55667788
    assert int(dut.rd_idx.value) == 12
    assert int(dut.pc4.value) == 0x30C


@cocotb.test()
async def reset_and_flush_bubble(dut):
    await _start(dut)
    assert int(dut.ctrl.value) == 0

    await FallingEdge(dut.clk)
    dut.ctrl_in.value = CTRL_NONZERO
    await _edge(dut)
    assert int(dut.ctrl.value) == CTRL_NONZERO

    await FallingEdge(dut.clk)
    dut.flush.value = 1
    await _edge(dut)
    assert int(dut.ctrl.value) == 0
