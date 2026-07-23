"""Run the official rv32ui test suite on the 5-stage pipeline.

Same idea as tb/riscv (single-cycle) but for top_pipeline.sv: load each
ELF into the core's memory over VPI, run to halt, and check the tohost
result. This is the strongest branch/flush/hazard validation there is,
because the rv32ui bodies (beq, bne, blt, bge, bltu, bgeu, jal, jalr,
and every arithmetic/memory case) are the official conformance vectors,
run through all the forwarding, stalls, and the ID-stage branch flush.

Difference from the single-cycle harness: the tohost strobe fires in
the MEM stage, but the core does not report halted until that store
reaches WB, so tohost_data (a MEM-stage combinational output) is stale
by then. top_pipeline latches the written value into tohost_value when
the strobe fires, so that is what we read at halt.

The env excludes fence_i and ma_data, so the pipeline is checked on the
same 38 tests as the single-cycle core.
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
MAX_CYCLES = 100000   # pipeline adds latency and stall cycles

HALT_TOHOST = 5

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
    words = {}
    for paddr, data in segments:
        for off, b in enumerate(data):
            addr = paddr + off
            words[addr >> 2] = words.get(addr >> 2, 0) | (b << ((addr & 3) * 8))
    return words


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


async def run_one(dut, path: Path):
    segs = load_segments(path)
    if not segs:
        return False, "no loadable segments"
    _load(dut, image_words(segs))
    await Timer(SETTLE_NS, units="ns")
    await _reset(dut)

    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(SETTLE_NS, units="ns")
        if int(dut.halted.value) == 1:
            cause = int(dut.halt_cause.value)
            if cause != HALT_TOHOST:
                return False, f"halt cause {cause} (not tohost), pc=0x{int(dut.pc_out.value):08x}"
            val = int(dut.tohost_value.value)
            if val == 1:
                return True, "tohost=1"
            return False, f"tohost=0x{val:x} (failing subtest {val >> 1})"
    return False, f"no halt within {MAX_CYCLES} cycles"


@cocotb.test()
async def rv32ui_on_pipeline(dut):
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

    dut._log.info(f"rv32ui on pipeline: {passes}/{len(tests)} passed, {len(fails)} failed")
    if fails:
        lines = "\n".join(f"  {n}: {r}" for n, r in fails)
        raise AssertionError(f"{len(fails)} pipeline conformance failures:\n{lines}")
