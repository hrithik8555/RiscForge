"""End-to-end test for top.sv: lockstep against the reference emulator.

The emulator is the oracle the whole project leans on. Here I load the
exact same image (smoke.hex, produced by our assembler from smoke.s)
into both the RTL and a fresh emulator, run both to halt, and compare
the full architectural register file. If they disagree the test prints
the first mismatched register.

Reading the RTL register file: the reg_file stores x1..x31 in an array
named xregs. I peek it hierarchically through the top instance. x0 is
not stored (it is hardwired zero), so I treat it as zero.

Halt: top.sv raises `halted` and a 3-bit `halt_cause`. For this program
the expected cause is ECALL (code 1).
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))
from rv32i_emu import RV32I  # noqa: E402

CLK_PERIOD_NS = 10
SETTLE_NS = 1
MAX_CYCLES = 1000

HALT_ECALL = 1


def load_hex_words(path: Path):
    """Read a $readmemh file (one 32-bit word per line) into a list of
    ints, then into a little-endian byte image for the emulator."""
    words = []
    for line in path.read_text().split():
        line = line.strip()
        if line:
            words.append(int(line, 16))
    image = bytearray()
    for w in words:
        image += int(w & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(image)


def run_emulator(image: bytes):
    cpu = RV32I(mem_size=64 * 1024, mem_base=0)
    cpu.pc = 0
    cpu.load_program(image, base=0)
    reason = cpu.run(max_steps=100000)
    return cpu, reason


def rtl_reg(dut, i):
    if i == 0:
        return 0
    return int(dut.u_regfile.xregs[i].value) & 0xFFFFFFFF


@cocotb.test()
async def smoke_lockstep(dut):
    # ----- oracle
    # The sim runs with cwd = tb/top, where the Makefile wrote smoke.hex.
    hex_path = Path("smoke.hex").resolve()
    image = load_hex_words(hex_path)
    cpu, reason = run_emulator(image)
    assert reason == "ecall", f"emulator did not halt on ecall: {reason}"

    # ----- RTL
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0

    halted = False
    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(SETTLE_NS, units="ns")
        if int(dut.halted.value) == 1:
            halted = True
            break
    assert halted, f"RTL did not halt within {MAX_CYCLES} cycles"
    assert int(dut.halt_cause.value) == HALT_ECALL, (
        f"halt cause {int(dut.halt_cause.value)}, expected ECALL ({HALT_ECALL})"
    )

    # ----- compare full register file
    mismatches = []
    for i in range(32):
        rtl = rtl_reg(dut, i)
        ref = cpu.regs[i] & 0xFFFFFFFF
        if rtl != ref:
            mismatches.append((i, rtl, ref))

    if mismatches:
        lines = "\n".join(
            f"  x{i}: RTL=0x{r:08x}  emu=0x{e:08x}" for i, r, e in mismatches
        )
        raise AssertionError(f"register mismatch:\n{lines}")
