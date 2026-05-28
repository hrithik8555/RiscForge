"""Cocotb test for the trivial 4-bit counter.

I am only using this as a toolchain smoke test. The real verification
happens against the reference model once that lands. If this test passes,
I know Verilator, cocotb, and VCD dumping all work on this machine.

Reset convention for the whole project: synchronous, active-high.

Timing pattern used here:
  - Inputs are driven on the falling edge so the new value is stable well
    before the next rising edge samples it.
  - Outputs are read AFTER a small Timer delay past the rising edge, so the
    non-blocking assignments from that edge have settled before we look.
  This is the cocotb idiom that works the same way across Verilator,
  Icarus, and the commercial sims, so it survives the toolchain swap I
  might do later if I ever upgrade Verilator.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10
SETTLE_NS = 1  # small delay past a rising edge before reading outputs


async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut):
    """Hold synchronous reset for three cycles, release on a falling edge."""
    dut.rst.value = 1
    dut.en.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def _step_and_read(dut, signal):
    """Advance one clock cycle, then read the signal after NBA settles."""
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")
    return int(signal.value)


@cocotb.test()
async def counts_when_enabled(dut):
    """Counter goes 1, 2, 3, ... on each enabled rising edge."""
    await _start_clock(dut)
    await _reset(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 1

    for expected in range(1, 9):
        got = await _step_and_read(dut, dut.count)
        assert got == expected, f"count {got}, expected {expected}"


@cocotb.test()
async def holds_when_disabled(dut):
    """With en=0, the counter freezes at its current value."""
    await _start_clock(dut)
    await _reset(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 1

    held = 0
    for _ in range(3):
        held = await _step_and_read(dut, dut.count)

    await FallingEdge(dut.clk)
    dut.en.value = 0

    for _ in range(5):
        now = await _step_and_read(dut, dut.count)
        assert now == held, f"counter moved while disabled: {now} != {held}"


@cocotb.test()
async def wraps_at_max(dut):
    """4-bit counter wraps from 15 back to 0 after 16 enabled cycles."""
    await _start_clock(dut)
    await _reset(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 1

    last = None
    for _ in range(16):
        last = await _step_and_read(dut, dut.count)

    assert last == 0, f"expected wrap to 0 after 16 cycles, got {last}"


@cocotb.test()
async def reset_clears_mid_count(dut):
    """Asserting sync reset mid-count zeroes the count on the next edge."""
    await _start_clock(dut)
    await _reset(dut)

    await FallingEdge(dut.clk)
    dut.en.value = 1

    for _ in range(5):
        _ = await _step_and_read(dut, dut.count)

    pre = int(dut.count.value)
    assert pre != 0, f"expected nonzero count before reset, got {pre}"

    await FallingEdge(dut.clk)
    dut.rst.value = 1

    after = await _step_and_read(dut, dut.count)
    assert after == 0, f"sync reset failed to clear count: got {after}"
