"""Cocotb tests for reg_file.

Checks:
  - x0 reads zero, always.
  - Writing x0 is a no-op.
  - Write to xN, then read xN next cycle, gets the new value.
  - Write-first bypass: when we=1, ws=rsN, and rs=ws, the read port
    reflects the new value in the same cycle (not the stale one).
  - Reset clears the file.
  - Both read ports work independently.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

CLK_PERIOD_NS = 10
SETTLE_NS = 1


async def _start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut):
    dut.rst.value = 1
    dut.we.value = 0
    dut.ws.value = 0
    dut.wd.value = 0
    dut.rs1.value = 0
    dut.rs2.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


async def _write(dut, ws, wd):
    """Drive a write on the rising edge, then deassert."""
    await FallingEdge(dut.clk)
    dut.we.value = 1
    dut.ws.value = ws
    dut.wd.value = wd
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")
    await FallingEdge(dut.clk)
    dut.we.value = 0


async def _read(dut, rs1, rs2=0):
    dut.rs1.value = rs1
    dut.rs2.value = rs2
    await Timer(SETTLE_NS, units="ns")
    return int(dut.rd1.value), int(dut.rd2.value)


@cocotb.test()
async def x0_reads_zero(dut):
    await _start_clock(dut)
    await _reset(dut)
    rd1, rd2 = await _read(dut, 0, 0)
    assert rd1 == 0 and rd2 == 0


@cocotb.test()
async def write_x0_is_noop(dut):
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 0, 0xDEADBEEF)
    rd1, _ = await _read(dut, 0)
    assert rd1 == 0, f"x0 became {rd1:08x}"


@cocotb.test()
async def write_then_read(dut):
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 5, 0xCAFEBABE)
    rd1, _ = await _read(dut, 5)
    assert rd1 == 0xCAFEBABE, f"x5 = {rd1:08x}"


@cocotb.test()
async def write_first_bypass(dut):
    """Same cycle: we=1 with ws=10 and rs1=10 must return wd, not the
    stale stored value. This is the single critical safety property
    for the pipelined version landing in stage 2."""
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 10, 0x11111111)

    # Set up the bypass scenario: we=1, ws=10, rs1=10
    await FallingEdge(dut.clk)
    dut.we.value = 1
    dut.ws.value = 10
    dut.wd.value = 0x22222222
    dut.rs1.value = 10
    await Timer(SETTLE_NS, units="ns")
    rd1 = int(dut.rd1.value)
    assert rd1 == 0x22222222, f"bypass returned {rd1:08x}, want 22222222"


@cocotb.test()
async def both_read_ports_independent(dut):
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 7, 0xAAAAAAAA)
    await _write(dut, 8, 0xBBBBBBBB)
    rd1, rd2 = await _read(dut, 7, 8)
    assert rd1 == 0xAAAAAAAA and rd2 == 0xBBBBBBBB


@cocotb.test()
async def reset_clears_file(dut):
    await _start_clock(dut)
    await _reset(dut)
    await _write(dut, 12, 0x33333333)
    rd1, _ = await _read(dut, 12)
    assert rd1 == 0x33333333

    await FallingEdge(dut.clk)
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await Timer(SETTLE_NS, units="ns")
    await FallingEdge(dut.clk)
    dut.rst.value = 0

    rd1, _ = await _read(dut, 12)
    assert rd1 == 0, f"x12 = {rd1:08x} after reset"


@cocotb.test()
async def random_writes_then_readback(dut):
    """Write a bunch of random (xN, val) pairs, then read them all back."""
    await _start_clock(dut)
    await _reset(dut)
    rng = random.Random(0xC0FFEE)
    expected = {0: 0}
    for _ in range(20):
        reg = rng.randint(1, 31)
        val = rng.randrange(0, 1 << 32)
        await _write(dut, reg, val)
        expected[reg] = val
    for reg, val in expected.items():
        rd1, _ = await _read(dut, reg)
        assert rd1 == val, f"x{reg} = {rd1:08x}, expected {val:08x}"
