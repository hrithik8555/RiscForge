"""Lockstep tests for the 5-stage pipeline skeleton (top_pipeline.sv).

Stage 2.1 has no forwarding and no load-use stall yet, so a value
written in WB is only visible to an ID read three stages later, via the
write-first register file. That means dependent instructions need two
NOPs between them. Rather than hand-pad every program, I insert two
NOPs after every real instruction, which is always safe (over-padding
never introduces a hazard). Branches do not need padding: the pipeline
flushes the two wrong-path instructions when a taken branch resolves in
EX.

The emulator treats a NOP (addi x0, x0, 0) as a real do-nothing
instruction, so the padded program lands on exactly the same final
register state as the unpadded one. So the check is the same lockstep
as the single-cycle core: run the padded program on both, compare the
full register file at halt.

This is the proof that the pipeline skeleton is wired correctly. Once
forwarding (2.2) and the load-use stall (2.3) are in, the same programs
run un-padded.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "assembler"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "refmodel"))
from assemble import assemble  # noqa: E402
from rv32i_emu import RV32I  # noqa: E402

CLK_PERIOD_NS = 10
SETTLE_NS = 1
MAX_CYCLES = 20000
IMEM_WORDS = 1024
DMEM_WORDS = 4096
HALT_ECALL = 1


def pad(src, n=2):
    """Insert n NOPs after every real instruction. Label-only lines,
    directives, comments, and blank lines are left alone so branch
    offsets still resolve. Over-padding is always safe without
    forwarding.

    Limitation: this pads at the SOURCE-LINE level, so it cannot pad
    inside a pseudo-instruction that the assembler expands to several
    dependent real instructions (a large `li` becomes LUI+ADDI, `call`
    becomes AUIPC+JALR, `la` becomes AUIPC+ADDI). Those internal pairs
    would hazard on this no-forwarding pipeline. So the test programs
    below avoid them: large constants are written as explicit lui+addi
    on separate lines, and jumps use jal/ret rather than call. Once
    forwarding lands in 2.2 the restriction goes away."""
    out = []
    for line in src.strip().splitlines():
        out.append(line)
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        if s.endswith(":") or s.startswith("."):
            continue   # bare label or directive: no padding
        for _ in range(n):
            out.append("    nop")
    return "\n".join(out)


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
    if i == 0:
        return 0
    return int(dut.u_regfile.xregs[i].value) & 0xFFFFFFFF


def _emu(words):
    image = bytearray()
    for w in words:
        image += int(w & 0xFFFFFFFF).to_bytes(4, "little")
    cpu = RV32I(mem_size=64 * 1024, mem_base=0)
    cpu.pc = 0
    cpu.load_program(bytes(image), base=0)
    reason = cpu.run(max_steps=200000)
    return cpu, reason


async def lockstep(dut, src, name="", do_pad=False):
    """Assemble, run on RTL + emulator, compare the register file.

    do_pad=True inserts NOPs between dependent instructions (the stage
    2.1 mode). With forwarding in place most programs run un-padded, so
    do_pad defaults to False now; the few remaining hazards forwarding
    cannot cover (a load used one instruction later) get an explicit
    NOP in the program itself."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    words = assemble(pad(src) if do_pad else src)
    assert words, f"{name}: assembler produced nothing"

    cpu, reason = _emu(words)
    assert reason == "ecall", f"{name}: emulator halted on {reason}, not ecall"

    words_by_idx = {i: w for i, w in enumerate(words)}
    _load(dut, words_by_idx)
    await Timer(SETTLE_NS, units="ns")
    await _reset(dut)

    halted = False
    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(SETTLE_NS, units="ns")
        if int(dut.halted.value) == 1:
            halted = True
            break
    assert halted, f"{name}: pipeline did not halt within {MAX_CYCLES} cycles"
    assert int(dut.halt_cause.value) == HALT_ECALL, (
        f"{name}: halt cause {int(dut.halt_cause.value)}, expected ECALL"
    )

    mism = []
    for i in range(32):
        r = _rtl_reg(dut, i)
        e = cpu.regs[i] & 0xFFFFFFFF
        if r != e:
            mism.append((i, r, e))
    if mism:
        lines = "\n".join(f"  x{i}: RTL=0x{r:08x} emu=0x{e:08x}" for i, r, e in mism)
        raise AssertionError(f"{name}: register mismatch:\n{lines}")
    return cpu


# ---------- straight-line dependent arithmetic (the core hazard case)

@cocotb.test()
async def dependent_arith(dut):
    # Each instruction depends on the previous result; the padding is
    # what makes this correct without forwarding.
    await lockstep(dut, """
        addi a0, x0, 1
        addi a1, a0, 1
        addi a2, a1, 1
        add  a3, a2, a2
        sub  a4, a3, a0
        ecall
    """, "dependent_arith")


# ---------- loads and stores through the pipeline

@cocotb.test()
async def load_store(dut):
    # With forwarding a large li (LUI+ADDI) needs no padding: the ADDI
    # gets the LUI result by EX-EX forward. The one hazard left is the
    # load-use: a1 is loaded then used one instruction later, and a
    # load's data is not ready in MEM so it cannot be forwarded EX-EX.
    # One NOP bridges it until the load-use stall lands in 2.3.
    await lockstep(dut, """
        li   t0, 0x400
        li   a0, 0x1234
        sw   a0, 0(t0)
        lw   a1, 0(t0)
        nop
        addi a2, a1, 1
        ecall
    """, "load_store")


# ---------- forwarding-specific paths

@cocotb.test()
async def back_to_back_deps(dut):
    # The plan's EX-EX-vs-MEM-EX case. `add a3` reads a2 (produced by
    # the instruction right before it: EX-EX) and a1 (two before it:
    # MEM-EX) in the same instruction.
    cpu = await lockstep(dut, """
        li  a0, 1
        add a1, a0, a0
        add a2, a1, a1
        add a3, a2, a1
        ecall
    """, "back_to_back_deps")
    assert cpu.regs[10] == 1    # a0
    assert cpu.regs[11] == 2    # a1
    assert cpu.regs[12] == 4    # a2
    assert cpu.regs[13] == 6    # a3 = a2 + a1 = 4 + 2


@cocotb.test()
async def pseudo_ops_unpadded(dut):
    # Forwarding removes the 2.1 restriction: a large li (LUI+ADDI) and
    # call (AUIPC+JALR) have internal dependencies that are now handled,
    # so these run with no padding at all.
    cpu = await lockstep(dut, """
        li   a0, 0x12345
        call double
        ecall
    double:
        add  a0, a0, a0
        ret
    """, "pseudo_ops_unpadded")
    assert cpu.regs[10] == 0x2468A


# ---------- a taken branch loop (exercises EX-resolved flush)

@cocotb.test()
async def branch_loop(dut):
    cpu = await lockstep(dut, """
        li   a0, 0
        li   a1, 5
    loop:
        addi a0, a0, 1
        blt  a0, a1, loop
        ecall
    """, "branch_loop")
    assert cpu.regs[10] == 5


# ---------- jumps: call/ret

@cocotb.test()
async def jal_jalr(dut):
    # jal (single instruction) instead of call (AUIPC+JALR pair).
    cpu = await lockstep(dut, """
        li   a0, 0
        jal  ra, setit
        addi a0, a0, 1
        ecall
    setit:
        li   a0, 42
        ret
    """, "jal_jalr")
    assert cpu.regs[10] == 43


# ---------- program-level: Fibonacci

@cocotb.test()
async def fibonacci(dut):
    cpu = await lockstep(dut, """
        li   a0, 0
        li   a1, 1
        li   a2, 10
        li   a3, 0
    loop:
        beq  a3, a2, done
        add  a4, a0, a1
        mv   a0, a1
        mv   a1, a4
        addi a3, a3, 1
        j    loop
    done:
        ecall
    """, "fibonacci")
    assert cpu.regs[10] == 55


# ---------- program-level: GCD by subtraction

@cocotb.test()
async def gcd(dut):
    cpu = await lockstep(dut, """
        li   a0, 48
        li   a1, 36
    gloop:
        beq  a0, a1, gdone
        blt  a0, a1, aless
        sub  a0, a0, a1
        j    gloop
    aless:
        sub  a1, a1, a0
        j    gloop
    gdone:
        ecall
    """, "gcd")
    assert cpu.regs[10] == 12
