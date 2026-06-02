"""Run the official rv32ui test suite on the single-cycle RTL.

This is the stage-1 verification gate the plan calls for: the RISC-V
conformance vectors, executed on the actual hardware, not just the
emulator. Each ELF was built by scripts/build_rtl_riscv_tests.sh from
the upstream rv32ui .S bodies wrapped in our bare-metal, CSR-free env
(tools/rtl_tests/env). Pass/fail is signaled by a write to the tohost
MMIO address, which the core detects and halts on.

For each binary:
  1. parse the ELF, collect its PT_LOAD segments
  2. write the image into both instruction and data memory over VPI
  3. reset, run to halt
  4. a halt with cause TOHOST and tohost_data == 1 is a pass; any other
     tohost value encodes a failing subtest as (n << 1) | 1; any other
     halt cause (illegal, misaligned) or a timeout is a failure

One cocotb test loops over every binary so the log reads like the
emulator runner: a line per test and an overall count. The whole thing
fails if any binary fails.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

from elftools.elf.elffile import ELFFile

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "tools" / "rtl_tests" / "_bin"

CLK_PERIOD_NS = 10
SETTLE_NS = 1
MAX_CYCLES = 50000

HALT_TOHOST = 5

# Memory depths must match top.sv defaults: imem 1024 words, dmem 4096.
# The env sets sp to 0x3f00 (word 0xFC0), which lives in dmem only, so
# the dmem clear must cover the stack region; imem only holds code.
IMEM_WORDS = 1024
DMEM_WORDS = 4096


def load_segments(path: Path):
    segs = []
    with open(path, "rb") as f:
        elf = ELFFile(f)
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_filesz"] > 0:
                segs.append((int(seg["p_paddr"]), seg.data()))
    return segs


def image_words(segments):
    """Flatten segments into a {word_index: word_value} dict."""
    words = {}
    for paddr, data in segments:
        for off, b in enumerate(data):
            addr = paddr + off
            widx = addr >> 2
            sh = (addr & 3) * 8
            words[widx] = words.get(widx, 0) | (b << sh)
    return words


async def _reset(dut):
    dut.rst.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


def _load(dut, words):
    # Clear each memory fully, then drop in the program words. Writing
    # both keeps fetch and load/store consistent (Harvard, same image).
    for i in range(IMEM_WORDS):
        dut.u_imem.mem[i].value = words.get(i, 0) & 0xFFFFFFFF
    for i in range(DMEM_WORDS):
        dut.u_dmem.mem[i].value = words.get(i, 0) & 0xFFFFFFFF


async def run_one(dut, path: Path):
    """Return (passed, reason) for one test ELF."""
    segs = load_segments(path)
    if not segs:
        return False, "no loadable segments"
    words = image_words(segs)

    _load(dut, words)
    await Timer(SETTLE_NS, units="ns")
    await _reset(dut)

    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(SETTLE_NS, units="ns")
        if int(dut.halted.value) == 1:
            cause = int(dut.halt_cause.value)
            if cause != HALT_TOHOST:
                return False, f"halt cause {cause} (not tohost), pc=0x{int(dut.pc_out.value):08x}"
            val = int(dut.tohost_data.value)
            if val == 1:
                return True, "tohost=1"
            return False, f"tohost=0x{val:x} (failing subtest {val >> 1})"
    return False, f"no halt within {MAX_CYCLES} cycles"


@cocotb.test()
async def rv32ui_on_rtl(dut):
    if not BIN_DIR.exists() or not any(BIN_DIR.glob("rv32ui-rtl-*")):
        raise AssertionError(
            f"no RTL test binaries in {BIN_DIR}; "
            f"run scripts/build_rtl_riscv_tests.sh first"
        )

    tests = sorted(p for p in BIN_DIR.glob("rv32ui-rtl-*") if not p.name.endswith(".log"))

    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())

    passes = 0
    fails = []
    for t in tests:
        ok, reason = await run_one(dut, t)
        name = t.name.replace("rv32ui-rtl-", "")
        if ok:
            passes += 1
            dut._log.info(f"  pass  {name}  ({reason})")
        else:
            fails.append((name, reason))
            dut._log.error(f"  FAIL  {name}: {reason}")

    dut._log.info(f"rv32ui on RTL: {passes}/{len(tests)} passed, {len(fails)} failed")
    if fails:
        lines = "\n".join(f"  {n}: {r}" for n, r in fails)
        raise AssertionError(f"{len(fails)} RTL conformance failures:\n{lines}")
