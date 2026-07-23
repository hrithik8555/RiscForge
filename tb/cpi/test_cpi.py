"""CPI measurement for the 5-stage pipeline (predict-not-taken baseline).

For each shared benchmark program I:
  1. run it on the emulator to get the dynamic instruction count and the
     expected final registers,
  2. run it on the RTL, counting clock cycles from reset release to halt,
  3. lockstep-check the final registers (a benchmark that diverges gives
     a meaningless CPI, so I refuse to report it),
  4. report CPI = cycles / instructions.

"Cycles" is measured from the cycle after reset is released to the cycle
the core reports halted, so it includes the pipeline fill and the ECALL.
That is a small fixed overhead; what matters is that the same definition
is used at every stage, so the stage-3 predictor and stage-4 cache
numbers are comparable to this baseline.

The baseline branch policy is predict-not-taken (the pipeline simply
fetches the fall-through and pays a one-cycle flush on every taken
branch), so loop-heavy programs like fib and gcd should show the most
room for the predictor to improve.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "assembler"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "benchmarks"))
from assemble import assemble  # noqa: E402
from rv32i_emu import RV32I  # noqa: E402
from programs import BENCHMARKS  # noqa: E402

CLK_PERIOD_NS = 10
SETTLE_NS = 1
MAX_CYCLES = 200000
IMEM_WORDS = 1024
DMEM_WORDS = 4096
HALT_ECALL = 1


async def _reset(dut):
    dut.rst.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


def _load(dut, words):
    for i in range(IMEM_WORDS):
        dut.u_imem.mem[i].value = words.get(i, 0) & 0xFFFFFFFF
    for i in range(DMEM_WORDS):
        dut.u_dmem.mem[i].value = words.get(i, 0) & 0xFFFFFFFF


def _rtl_reg(dut, i):
    return 0 if i == 0 else int(dut.u_regfile.xregs[i].value) & 0xFFFFFFFF


def _emu(words):
    img = b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in words)
    cpu = RV32I(mem_size=64 * 1024, mem_base=0)
    cpu.pc = 0
    cpu.load_program(img, base=0)
    reason = cpu.run(max_steps=500000)
    return cpu, reason


async def measure(dut, name, src, expect):
    words = assemble(src)
    cpu, reason = _emu(words)
    assert reason == "ecall", f"{name}: emulator halted on {reason}"
    for r, v in expect.items():
        assert cpu.regs[r] == v, f"{name}: emulator x{r}={cpu.regs[r]}, want {v}"

    _load(dut, {i: w for i, w in enumerate(words)})
    await Timer(SETTLE_NS, units="ns")
    await _reset(dut)

    cycles = 0
    halted = False
    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(SETTLE_NS, units="ns")
        cycles += 1
        if int(dut.halted.value) == 1:
            halted = True
            break
    assert halted, f"{name}: no halt within {MAX_CYCLES} cycles"
    assert int(dut.halt_cause.value) == HALT_ECALL, f"{name}: halt cause not ECALL"

    # lockstep the final registers before trusting the number
    for i in range(32):
        r, e = _rtl_reg(dut, i), cpu.regs[i] & 0xFFFFFFFF
        assert r == e, f"{name}: x{i} RTL=0x{r:08x} emu=0x{e:08x}"

    instrs = cpu.steps
    cpi = cycles / instrs
    return instrs, cycles, cpi


@cocotb.test()
async def cpi_baseline(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())

    dut._log.info("CPI baseline (predict-not-taken), 5-stage pipeline")
    dut._log.info(f"  {'program':10s} {'instrs':>8s} {'cycles':>8s} {'CPI':>6s}")
    rows = []
    for name, (src, expect) in BENCHMARKS.items():
        instrs, cycles, cpi = await measure(dut, name, src, expect)
        rows.append((name, instrs, cycles, cpi))
        dut._log.info(f"  {name:10s} {instrs:8d} {cycles:8d} {cpi:6.3f}")

    tot_i = sum(r[1] for r in rows)
    tot_c = sum(r[2] for r in rows)
    dut._log.info(f"  {'overall':10s} {tot_i:8d} {tot_c:8d} {tot_c/tot_i:6.3f}")
