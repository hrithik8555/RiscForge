"""Integration + lockstep tests for the single-cycle core (top.sv).

Each test assembles a small program with our own assembler, writes the
words straight into the RTL's instruction and data memory over VPI,
resets, runs to halt, and compares the full register file against the
reference emulator running the same image. The emulator is the oracle;
expected values are never hand-written, they come from the model the
riscv-tests suite already validated.

Layout:
  - mechanism check (prove I can write the memory arrays)
  - per-opcode directed tests (plan step 1.15): one focused program
    per instruction family, lockstepped against the model
  - halt-path tests: misaligned store and illegal instruction drive
    the trap/halt plumbing, which the unit tests cannot reach
  - program-level lockstep (plan step 1.16): Fibonacci, GCD, factorial

Memory note: top.sv has separate instruction and data memory; I write
the same image into both. Programs keep their data clear of the code
region, because the emulator's unified memory would otherwise let a
store overwrite an instruction and diverge from the RTL.
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
from rv32i_emu import RV32I, Trap  # noqa: E402

CLK_PERIOD_NS = 10
SETTLE_NS = 1
MAX_CYCLES = 5000

# Generous clear windows. Programs are tiny and keep data below 0x1000.
IMEM_CLEAR_WORDS = 256
DMEM_CLEAR_WORDS = 1024

# halt cause codes, mirroring top.sv
HALT_NONE = 0
HALT_ECALL = 1
HALT_EBREAK = 2
HALT_ILLEGAL = 3
HALT_MISALIGNED = 4
HALT_TOHOST = 5

# ---------- low-level helpers

async def _ensure_clock(dut):
    # cocotb cancels tasks forked inside a test when that test ends, so
    # a clock started in an earlier test is dead by the next one. Start
    # a fresh clock at the top of every test instead of guarding once.
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())


async def _reset(dut):
    dut.rst.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0


def _write_mem(dut, words):
    """Clear both memories, then write the program image into both."""
    for i in range(IMEM_CLEAR_WORDS):
        dut.u_imem.mem[i].value = 0
    for i in range(DMEM_CLEAR_WORDS):
        dut.u_dmem.mem[i].value = 0
    for i, w in enumerate(words):
        dut.u_imem.mem[i].value = w & 0xFFFFFFFF
        dut.u_dmem.mem[i].value = w & 0xFFFFFFFF


def _rtl_reg(dut, i):
    if i == 0:
        return 0
    return int(dut.u_regfile.xregs[i].value) & 0xFFFFFFFF


def _emu(words, expect_ecall=True):
    image = bytearray()
    for w in words:
        image += int(w & 0xFFFFFFFF).to_bytes(4, "little")
    cpu = RV32I(mem_size=64 * 1024, mem_base=0)
    cpu.pc = 0
    cpu.load_program(bytes(image), base=0)
    try:
        reason = cpu.run(max_steps=200000)
    except Trap as t:
        return cpu, ("trap", t.kind)
    return cpu, ("halt", reason)


async def _run_to_halt(dut, words):
    _write_mem(dut, words)
    await Timer(SETTLE_NS, units="ns")
    await _reset(dut)
    for _ in range(MAX_CYCLES):
        await RisingEdge(dut.clk)
        await Timer(SETTLE_NS, units="ns")
        if int(dut.halted.value) == 1:
            return int(dut.halt_cause.value)
    raise AssertionError(f"RTL did not halt within {MAX_CYCLES} cycles")


async def lockstep(dut, src, name=""):
    """Assemble, run on RTL + emulator, compare the full register file."""
    await _ensure_clock(dut)
    words = assemble(src)
    assert words, f"{name}: assembler produced nothing"

    cpu, status = _emu(words)
    assert status == ("halt", "ecall"), f"{name}: emulator status {status}, want ecall"

    cause = await _run_to_halt(dut, words)
    assert cause == HALT_ECALL, f"{name}: RTL halt cause {cause}, want ECALL"

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


# ---------- 0. mechanism check

@cocotb.test()
async def mem_write_mechanism(dut):
    cpu = await lockstep(dut, "addi x1, x0, 7\necall\n", "mech")
    assert cpu.regs[1] == 7


# ---------- 1.15 per-opcode directed tests

@cocotb.test()
async def lui_auipc(dut):
    # auipc lands an address that depends on PC, so lockstep (not a
    # hand value) is the right check.
    await lockstep(dut, """
        lui   a0, 0x12345
        auipc a1, 0x1
        addi  a2, a0, 0x67
        ecall
    """, "lui_auipc")


@cocotb.test()
async def op_imm_arith(dut):
    await lockstep(dut, """
        addi  a0, x0, 100
        addi  a1, a0, -30        # 70
        slti  a2, a1, 80         # 1 (70 < 80 signed)
        slti  a3, a1, 60         # 0
        sltiu a4, a1, 80         # 1
        xori  a5, a1, -1         # ~70
        ori   a6, x0, 0x55
        andi  a7, a5, 0x0F
        ecall
    """, "op_imm_arith")


@cocotb.test()
async def op_imm_shifts(dut):
    # Set a value with the high bit set, then shift. srai must sign-fill.
    await lockstep(dut, """
        lui  a0, 0x80000          # a0 = 0x80000000
        slli a1, a0, 0            # shift by 0 (boundary)
        srli a2, a0, 31           # 1
        srai a3, a0, 31           # 0xFFFFFFFF (sign fill)
        srai a4, a0, 0            # boundary: unchanged
        slli a5, a0, 1            # 0 (shifted out)
        ecall
    """, "op_imm_shifts")


@cocotb.test()
async def op_reg_arith(dut):
    await lockstep(dut, """
        addi a0, x0, 17
        addi a1, x0, 5
        add  a2, a0, a1          # 22
        sub  a3, a0, a1          # 12
        slt  a4, a1, a0          # 1
        sltu a5, a1, a0          # 1
        xor  a6, a0, a1
        or   a7, a0, a1
        and  s0, a0, a1
        ecall
    """, "op_reg_arith")


@cocotb.test()
async def op_reg_shifts(dut):
    # Use register shift amounts including 0 and 31.
    await lockstep(dut, """
        lui  a0, 0x80000          # 0x80000000
        addi a1, x0, 31
        addi a2, x0, 0
        sll  a3, a0, a1           # huge << 31 = 0
        srl  a4, a0, a1           # 1
        sra  a5, a0, a1           # 0xFFFFFFFF
        srl  a6, a0, a2           # shift by 0: unchanged
        ecall
    """, "op_reg_shifts")


@cocotb.test()
async def loads_stores(dut):
    # Exercise every width and the sign/zero extension, through the
    # real datapath, with data at 0x400 (clear of code).
    await lockstep(dut, """
        lui  a0, 0xDEADC          # a0 ~ 0xDEADC000
        addi a0, a0, -0x111       # some 32-bit value with high bits set
        li   t0, 0x400            # data base
        sw   a0, 0(t0)
        lw   a1, 0(t0)            # full word back
        lb   a2, 0(t0)            # low byte, signed
        lbu  a3, 0(t0)            # low byte, unsigned
        lh   a4, 0(t0)            # low half, signed
        lhu  a5, 0(t0)            # low half, unsigned
        sb   a0, 16(t0)           # store low byte
        lbu  a6, 16(t0)
        sh   a0, 20(t0)           # store low half
        lhu  a7, 20(t0)
        ecall
    """, "loads_stores")


@cocotb.test()
async def branch_beq_bne(dut):
    await lockstep(dut, """
        li   a0, 0
        li   a1, 3
    loop:
        addi a0, a0, 1
        bne  a0, a1, loop        # taken while a0 != 3 -> a0 = 3
        li   a2, 0
        beq  a0, a1, eq           # taken (3 == 3)
        li   a2, 99               # skipped if beq works
    eq:
        li   a2, 7
        ecall
    """, "beq_bne")


@cocotb.test()
async def branch_blt_bge(dut):
    await lockstep(dut, """
        li   a0, 0
        li   a1, 5
    l1:
        addi a0, a0, 1
        blt  a0, a1, l1          # count to 5 (signed)
        li   t0, -1
        li   t1, 1
        li   a2, 0
        bge  t1, t0, ok          # 1 >= -1 signed -> taken
        li   a2, 99
    ok:
        li   a2, 1
        ecall
    """, "blt_bge")


@cocotb.test()
async def branch_bltu_bgeu(dut):
    await lockstep(dut, """
        li   t0, -1              # 0xFFFFFFFF, huge unsigned
        li   t1, 1
        li   a0, 0
        bltu t1, t0, a              # 1 < huge unsigned -> taken
        li   a0, 99
    a:
        li   a0, 1
        li   a1, 0
        bgeu t0, t1, b              # huge >= 1 unsigned -> taken
        li   a1, 99
    b:
        li   a1, 1
        ecall
    """, "bltu_bgeu")


@cocotb.test()
async def jal_jalr(dut):
    # call/ret expand to JAL-class and JALR; verifies link register and
    # control transfer through the datapath.
    await lockstep(dut, """
        li   a0, 0
        call setit
        addi a0, a0, 1           # runs after return -> a0 = 43
        ecall
    setit:
        li   a0, 42
        ret
    """, "jal_jalr")


# ---------- halt-path tests (trap / halt plumbing, end to end)

@cocotb.test()
async def misaligned_store_halts(dut):
    await _ensure_clock(dut)
    src = """
        li a0, 0x402            # deliberately not word-aligned
        li a1, 0x1234
        sw a1, 0(a0)            # misaligned word store
        ecall
    """
    words = assemble(src)
    # emulator should trap, not reach ecall
    _, status = _emu(words)
    assert status[0] == "trap", f"emulator did not trap: {status}"
    cause = await _run_to_halt(dut, words)
    assert cause == HALT_MISALIGNED, f"RTL halt cause {cause}, want MISALIGNED"


@cocotb.test()
async def illegal_instruction_halts(dut):
    await _ensure_clock(dut)
    # .word emits a raw illegal encoding (custom-0 opcode) inline.
    src = """
        addi a0, x0, 5
        .word 0x0000000B
        ecall
    """
    words = assemble(src)
    _, status = _emu(words)
    assert status[0] == "trap", f"emulator did not trap: {status}"
    cause = await _run_to_halt(dut, words)
    assert cause == HALT_ILLEGAL, f"RTL halt cause {cause}, want ILLEGAL"


# ---------- 1.16 program-level lockstep

@cocotb.test()
async def fibonacci(dut):
    cpu = await lockstep(dut, """
        li   a0, 0               # a = 0
        li   a1, 1               # b = 1
        li   a2, 10              # n
        li   a3, 0               # i
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
    assert cpu.regs[10] == 55, f"fib(10) = {cpu.regs[10]}"


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
    assert cpu.regs[10] == 12, f"gcd(48,36) = {cpu.regs[10]}"


@cocotb.test()
async def factorial(dut):
    # 5! = 120, computed with a multiply subroutine (RV32I has no MUL),
    # so this exercises a nested loop plus call/ret.
    cpu = await lockstep(dut, """
        li   s0, 5               # n
        li   s1, 1               # acc
    floop:
        beq  s0, x0, fdone
        mv   a0, s1
        mv   a1, s0
        call mul                 # a2 = a0 * a1
        mv   s1, a2
        addi s0, s0, -1
        j    floop
    fdone:
        mv   a0, s1
        ecall

    mul:
        li   a2, 0
    mloop:
        beq  a1, x0, mdone
        add  a2, a2, a0
        addi a1, a1, -1
        j    mloop
    mdone:
        ret
    """, "factorial")
    assert cpu.regs[10] == 120, f"5! = {cpu.regs[10]}"
