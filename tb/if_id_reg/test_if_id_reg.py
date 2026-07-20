"""Cocotb tests for if_id_reg.

Checks the four behaviors every pipeline register needs: latch on en,
hold on en=0 (stall), inject a NOP on flush, and inject a NOP on reset.
Plus the priority case: flush must win over en, because a branch
redirect cannot be held back by a stall.

The bubble for this register is the NOP instruction 0x00000013.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10
SETTLE_NS = 1
NOP = 0x00000013


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.en.value = 1
    dut.flush.value = 0
    dut.pc_in.value = 0
    dut.pc4_in.value = 0
    dut.inst_in.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def _edge_read(dut, sig):
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")
    return int(sig.value)


@cocotb.test()
async def reset_is_nop(dut):
    await _start(dut)
    assert int(dut.inst.value) == NOP, f"{int(dut.inst.value):08x}"


@cocotb.test()
async def latches_on_en(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.en.value = 1
    dut.pc_in.value = 0x100
    dut.pc4_in.value = 0x104
    dut.inst_in.value = 0xDEADBEEF
    assert (await _edge_read(dut, dut.inst)) == 0xDEADBEEF
    assert int(dut.pc.value) == 0x100
    assert int(dut.pc4.value) == 0x104


@cocotb.test()
async def holds_on_stall(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.inst_in.value = 0x11111111
    await _edge_read(dut, dut.inst)
    assert int(dut.inst.value) == 0x11111111

    await FallingEdge(dut.clk)
    dut.en.value = 0
    dut.inst_in.value = 0x22222222   # must be ignored while stalled
    for _ in range(3):
        now = await _edge_read(dut, dut.inst)
        assert now == 0x11111111, f"moved while stalled: {now:08x}"


@cocotb.test()
async def flush_injects_nop(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.inst_in.value = 0xAAAAAAAA
    await _edge_read(dut, dut.inst)
    assert int(dut.inst.value) == 0xAAAAAAAA

    await FallingEdge(dut.clk)
    dut.flush.value = 1
    assert (await _edge_read(dut, dut.inst)) == NOP


@cocotb.test()
async def flush_beats_stall(dut):
    await _start(dut)
    await FallingEdge(dut.clk)
    dut.inst_in.value = 0xBBBBBBBB
    await _edge_read(dut, dut.inst)

    await FallingEdge(dut.clk)
    dut.en.value = 0       # stall asserted
    dut.flush.value = 1    # but flush should win
    assert (await _edge_read(dut, dut.inst)) == NOP
