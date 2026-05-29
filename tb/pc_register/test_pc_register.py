"""Cocotb tests for pc_register.

What I am checking:
  - Reset puts pc at PC_RESET (default 0).
  - With en=1, pc latches next_pc on every rising edge.
  - With en=0, pc holds (stall).
  - Asserting rst mid-stream forces pc back to 0 next cycle.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10
SETTLE_NS = 1


async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut):
    dut.rst.value = 1
    dut.en.value = 0
    dut.next_pc.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def _step_and_read(dut, signal):
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")
    return int(signal.value)


@cocotb.test()
async def reset_to_zero(dut):
    await _start_clock(dut)
    await _reset(dut)
    assert int(dut.pc.value) == 0


@cocotb.test()
async def latches_next_pc_when_enabled(dut):
    await _start_clock(dut)
    await _reset(dut)
    await FallingEdge(dut.clk)
    dut.en.value = 1

    targets = [0x4, 0x8, 0xC, 0x100, 0xDEADBEE0]
    for t in targets:
        dut.next_pc.value = t
        got = await _step_and_read(dut, dut.pc)
        assert got == t, f"pc {got:08x}, expected {t:08x}"


@cocotb.test()
async def holds_when_disabled(dut):
    await _start_clock(dut)
    await _reset(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 1
    dut.next_pc.value = 0x1234
    got = await _step_and_read(dut, dut.pc)
    assert got == 0x1234

    await FallingEdge(dut.clk)
    dut.en.value = 0
    dut.next_pc.value = 0xFFFF_FFFF  # would-be next value, must be ignored

    for _ in range(5):
        now = await _step_and_read(dut, dut.pc)
        assert now == 0x1234, f"pc moved while stalled: {now:08x}"


@cocotb.test()
async def sync_reset_clears_mid_stream(dut):
    await _start_clock(dut)
    await _reset(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 1
    dut.next_pc.value = 0xABCD
    _ = await _step_and_read(dut, dut.pc)
    assert int(dut.pc.value) == 0xABCD

    await FallingEdge(dut.clk)
    dut.rst.value = 1
    got = await _step_and_read(dut, dut.pc)
    assert got == 0, f"reset failed to zero pc: {got:08x}"
