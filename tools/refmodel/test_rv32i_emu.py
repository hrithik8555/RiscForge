"""test_rv32i_emu.py - sanity tests for the reference emulator.

The real validation gate for the emulator is stage 1.5 (riscv-tests
rv32ui). These tests are deliberately shallow; they only confirm
structural soundness: the register file behaves, the instruction
decoders extract the right bits, traps fire, x0 stays zero. If any
of these fail, the emulator is broken in an obvious way and stage 1.5
will not even start.

No pytest dependency. Plain assertions, a __main__ runner. Run from
the repo root:

    python3 tools/refmodel/test_rv32i_emu.py

The tiny inline encoder at the top exists ONLY so these tests do not
have to hand-type 0xDEADBEEF for every instruction. The real
assembler lands in stage 1.6.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make rv32i_emu and encoding importable when this script is run from
# anywhere (including the repo root, where `python3 path/to/this`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rv32i_emu import RV32I, Trap, u32  # noqa: E402


# ---------- a tiny instruction encoder used only by these tests
# This is NOT the assembler. It does just enough to write readable
# tests. Each helper returns a 32-bit instruction word.

def _r(funct7, rs2, rs1, funct3, rd, opcode):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def _i(imm, rs1, funct3, rd, opcode):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def _s(imm, rs2, rs1, funct3, opcode):
    return (
        ((imm >> 5) & 0x7F) << 25
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | (imm & 0x1F) << 7
        | opcode
    )


def _b(imm, rs2, rs1, funct3, opcode):
    # imm[12|10:5|4:1|11], bit 0 is 0
    return (
        ((imm >> 12) & 0x1) << 31
        | ((imm >> 5) & 0x3F) << 25
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | ((imm >> 1) & 0xF) << 8
        | ((imm >> 11) & 0x1) << 7
        | opcode
    )


def _u(imm, rd, opcode):
    return (imm & 0xFFFFF000) | (rd << 7) | opcode


def _j(imm, rd, opcode):
    return (
        ((imm >> 20) & 0x1) << 31
        | ((imm >> 1) & 0x3FF) << 21
        | ((imm >> 11) & 0x1) << 20
        | ((imm >> 12) & 0xFF) << 12
        | (rd << 7)
        | opcode
    )


# Opcode constants (also in encoding.py but duplicating is fine for tests).
OP_LUI    = 0b0110111
OP_AUIPC  = 0b0010111
OP_JAL    = 0b1101111
OP_JALR   = 0b1100111
OP_BRANCH = 0b1100011
OP_LOAD   = 0b0000011
OP_STORE  = 0b0100011
OP_IMM    = 0b0010011
OP_REG    = 0b0110011
OP_FENCE  = 0b0001111
OP_SYSTEM = 0b1110011

# Convenience constructors used inside tests.
def addi(rd, rs1, imm):  return _i(imm, rs1, 0b000, rd, OP_IMM)
def slti(rd, rs1, imm):  return _i(imm, rs1, 0b010, rd, OP_IMM)
def sltiu(rd, rs1, imm): return _i(imm, rs1, 0b011, rd, OP_IMM)
def xori(rd, rs1, imm):  return _i(imm, rs1, 0b100, rd, OP_IMM)
def ori(rd, rs1, imm):   return _i(imm, rs1, 0b110, rd, OP_IMM)
def andi(rd, rs1, imm):  return _i(imm, rs1, 0b111, rd, OP_IMM)
def slli(rd, rs1, shamt): return _r(0x00, shamt, rs1, 0b001, rd, OP_IMM)
def srli(rd, rs1, shamt): return _r(0x00, shamt, rs1, 0b101, rd, OP_IMM)
def srai(rd, rs1, shamt): return _r(0x20, shamt, rs1, 0b101, rd, OP_IMM)

def add(rd, rs1, rs2):  return _r(0x00, rs2, rs1, 0b000, rd, OP_REG)
def sub(rd, rs1, rs2):  return _r(0x20, rs2, rs1, 0b000, rd, OP_REG)
def sll(rd, rs1, rs2):  return _r(0x00, rs2, rs1, 0b001, rd, OP_REG)
def slt(rd, rs1, rs2):  return _r(0x00, rs2, rs1, 0b010, rd, OP_REG)
def sltu(rd, rs1, rs2): return _r(0x00, rs2, rs1, 0b011, rd, OP_REG)
def xor_(rd, rs1, rs2): return _r(0x00, rs2, rs1, 0b100, rd, OP_REG)
def srl(rd, rs1, rs2):  return _r(0x00, rs2, rs1, 0b101, rd, OP_REG)
def sra(rd, rs1, rs2):  return _r(0x20, rs2, rs1, 0b101, rd, OP_REG)
def or_(rd, rs1, rs2):  return _r(0x00, rs2, rs1, 0b110, rd, OP_REG)
def and_(rd, rs1, rs2): return _r(0x00, rs2, rs1, 0b111, rd, OP_REG)

def lui(rd, imm20):   return _u(imm20 << 12, rd, OP_LUI)
def auipc(rd, imm20): return _u(imm20 << 12, rd, OP_AUIPC)
def jal(rd, imm):     return _j(imm, rd, OP_JAL)
def jalr(rd, rs1, imm): return _i(imm, rs1, 0b000, rd, OP_JALR)

def beq(rs1, rs2, imm): return _b(imm, rs2, rs1, 0b000, OP_BRANCH)
def bne(rs1, rs2, imm): return _b(imm, rs2, rs1, 0b001, OP_BRANCH)
def blt(rs1, rs2, imm): return _b(imm, rs2, rs1, 0b100, OP_BRANCH)
def bge(rs1, rs2, imm): return _b(imm, rs2, rs1, 0b101, OP_BRANCH)
def bltu(rs1, rs2, imm): return _b(imm, rs2, rs1, 0b110, OP_BRANCH)
def bgeu(rs1, rs2, imm): return _b(imm, rs2, rs1, 0b111, OP_BRANCH)

def lb(rd, rs1, imm):  return _i(imm, rs1, 0b000, rd, OP_LOAD)
def lh(rd, rs1, imm):  return _i(imm, rs1, 0b001, rd, OP_LOAD)
def lw(rd, rs1, imm):  return _i(imm, rs1, 0b010, rd, OP_LOAD)
def lbu(rd, rs1, imm): return _i(imm, rs1, 0b100, rd, OP_LOAD)
def lhu(rd, rs1, imm): return _i(imm, rs1, 0b101, rd, OP_LOAD)

def sb(rs1, rs2, imm): return _s(imm, rs2, rs1, 0b000, OP_STORE)
def sh(rs1, rs2, imm): return _s(imm, rs2, rs1, 0b001, OP_STORE)
def sw(rs1, rs2, imm): return _s(imm, rs2, rs1, 0b010, OP_STORE)

ECALL  = 0x00000073
EBREAK = 0x00100073


# ---------- helpers
def make_cpu(*words: int, tohost_addr: int = 0x80001000) -> RV32I:
    """Build a CPU with the given instructions loaded at PC=0."""
    cpu = RV32I(mem_size=64 * 1024, mem_base=0, tohost_addr=tohost_addr)
    payload = b"".join(w.to_bytes(4, "little") for w in words)
    cpu.load_program(payload, base=0)
    return cpu


def run_n(cpu: RV32I, n: int) -> None:
    """Run exactly n instructions, asserting we did not halt early."""
    for k in range(n):
        if cpu.halted:
            raise AssertionError(f"halted early at step {k} ({cpu.halt_reason})")
        cpu.step()


# ---------- the actual tests
def test_x0_stays_zero():
    cpu = make_cpu(addi(0, 0, 0x123))  # ADDI x0, x0, 0x123
    run_n(cpu, 1)
    assert cpu.regs[0] == 0


def test_addi_basic():
    cpu = make_cpu(addi(1, 0, 5))
    run_n(cpu, 1)
    assert cpu.regs[1] == 5


def test_addi_negative():
    cpu = make_cpu(addi(1, 0, -1))
    run_n(cpu, 1)
    assert cpu.regs[1] == 0xFFFFFFFF


def test_add_sub():
    cpu = make_cpu(addi(1, 0, 7), addi(2, 0, 3), add(3, 1, 2), sub(4, 1, 2))
    run_n(cpu, 4)
    assert cpu.regs[3] == 10
    assert cpu.regs[4] == 4


def test_overflow_wraps():
    cpu = make_cpu(addi(1, 0, -1), addi(2, 0, 1), add(3, 1, 2))
    run_n(cpu, 3)
    # 0xFFFFFFFF + 1 = 0x100000000, masked to 0.
    assert cpu.regs[3] == 0


def test_logical():
    # 0x550 and 0x6A0 both fit in 12-bit signed, so the ADDI immediates
    # arrive at the registers without surprise sign extension.
    cpu = make_cpu(
        addi(1, 0, 0x550), addi(2, 0, 0x6A0),
        and_(3, 1, 2), or_(4, 1, 2), xor_(5, 1, 2),
    )
    run_n(cpu, 5)
    assert cpu.regs[3] == 0x550 & 0x6A0
    assert cpu.regs[4] == 0x550 | 0x6A0
    assert cpu.regs[5] == 0x550 ^ 0x6A0


def test_slt_signed_vs_unsigned():
    # x1 = -1 (all ones), x2 = 1
    cpu = make_cpu(addi(1, 0, -1), addi(2, 0, 1), slt(3, 1, 2), sltu(4, 1, 2))
    run_n(cpu, 4)
    assert cpu.regs[3] == 1  # signed: -1 < 1
    assert cpu.regs[4] == 0  # unsigned: 0xFFFFFFFF >= 1


def test_shifts():
    # x1 = 0x80000000 (signed -2147483648), shift right by 4
    cpu = make_cpu(
        lui(1, 0x80000),         # x1 = 0x80000000
        srli(2, 1, 4),           # logical right
        srai(3, 1, 4),           # arithmetic right
        slli(4, 0, 0),           # nop
        addi(5, 0, 1),
        slli(6, 5, 5),           # 1 << 5 = 32
    )
    run_n(cpu, 6)
    assert cpu.regs[2] == 0x80000000 >> 4              # 0x08000000
    assert cpu.regs[3] == u32(-(0x80000000 >> 4))      # 0xF8000000
    assert cpu.regs[6] == 32


def test_lui_auipc():
    cpu = make_cpu(lui(1, 0xABCDE), auipc(2, 0x10000))
    # PC for auipc = 4 (the second instruction). Expected: 4 + 0x10000000.
    run_n(cpu, 2)
    assert cpu.regs[1] == 0xABCDE000
    assert cpu.regs[2] == u32(4 + 0x10000000)


def test_branch_taken_and_not_taken():
    # Layout:
    #   0: addi x1, x0, 5
    #   4: addi x2, x0, 5
    #   8: bne x1, x2, +12      (not taken, fall through)
    #  12: addi x3, x0, 99      (executes, x3 = 99)
    #  16: beq x1, x2, +8       (taken, skips 20)
    #  20: addi x4, x0, 77      (should NOT execute)
    #  24: addi x5, x0, 88
    cpu = make_cpu(
        addi(1, 0, 5),
        addi(2, 0, 5),
        bne(1, 2, 12),
        addi(3, 0, 99),
        beq(1, 2, 8),
        addi(4, 0, 77),
        addi(5, 0, 88),
    )
    run_n(cpu, 6)  # bne not taken, addi 99, beq taken, addi 88. 6 retired.
    assert cpu.regs[3] == 99
    assert cpu.regs[4] == 0
    assert cpu.regs[5] == 88


def test_blt_signed():
    cpu = make_cpu(
        addi(1, 0, -1),         # x1 = -1 (unsigned 0xFFFFFFFF)
        addi(2, 0, 1),          # x2 = 1
        blt(1, 2, 8),           # taken: -1 < 1
        addi(3, 0, 1),          # skipped
        addi(4, 0, 1),          # x4 = 1
    )
    run_n(cpu, 4)
    assert cpu.regs[3] == 0
    assert cpu.regs[4] == 1


def test_jal_links_and_jumps():
    cpu = make_cpu(
        jal(1, 8),              # x1 = pc + 4 = 4; jump to pc + 8 = 8
        addi(2, 0, 99),         # skipped
        addi(3, 0, 7),          # x3 = 7
    )
    run_n(cpu, 2)
    assert cpu.regs[1] == 4
    assert cpu.regs[2] == 0
    assert cpu.regs[3] == 7


def test_jalr():
    cpu = make_cpu(
        addi(1, 0, 12),         # x1 = 12 (target)
        jalr(2, 1, 0),          # x2 = pc + 4 = 8; jump to x1 = 12
        addi(3, 0, 99),         # skipped
        addi(4, 0, 5),          # x4 = 5
    )
    run_n(cpu, 3)
    assert cpu.regs[2] == 8
    assert cpu.regs[3] == 0
    assert cpu.regs[4] == 5


def test_sw_lw_roundtrip():
    cpu = make_cpu(
        addi(1, 0, 0x100),      # base addr
        lui(2, 0xDEADC),        # x2 = 0xDEADC000
        addi(2, 2, -544),       # x2 = 0xDEADC000 + 0xFDE0 = 0xDEADBDE0 (approx)
        sw(1, 2, 0),            # mem[0x100] = x2
        lw(3, 1, 0),            # x3 = mem[0x100]
    )
    run_n(cpu, 5)
    assert cpu.regs[3] == cpu.regs[2]


def test_lb_lbu_sign_vs_zero_extension():
    # Store 0x80 at addr 0x200, then load it as LB and LBU.
    cpu = make_cpu(
        addi(1, 0, 0x80),       # x1 = 0x80
        addi(2, 0, 0x200),
        sb(2, 1, 0),            # mem[0x200] = 0x80
        lb(3, 2, 0),             # x3 = sign-ext(0x80) = 0xFFFFFF80
        lbu(4, 2, 0),            # x4 = zero-ext(0x80) = 0x00000080
    )
    run_n(cpu, 5)
    assert cpu.regs[3] == 0xFFFFFF80
    assert cpu.regs[4] == 0x80


def test_ecall_halts():
    cpu = make_cpu(addi(1, 0, 1), ECALL, addi(2, 0, 99))
    reason = cpu.run(max_steps=10)
    assert reason == "ecall"
    assert cpu.regs[1] == 1
    assert cpu.regs[2] == 0


def test_tohost_pass():
    # Write 1 to tohost; CPU should halt with tohost-pass.
    TOHOST = 0x1000
    cpu = make_cpu(
        addi(1, 0, 1),                  # x1 = 1
        lui(2, TOHOST >> 12),           # x2 = TOHOST
        sw(2, 1, 0),                    # mem[TOHOST] = 1
        addi(3, 0, 99),                 # should NOT execute
        tohost_addr=TOHOST,
    )
    reason = cpu.run(max_steps=10)
    assert reason == "tohost-pass"
    assert cpu.tohost_value == 1
    assert cpu.regs[3] == 0


def test_misaligned_load_traps():
    cpu = make_cpu(addi(1, 0, 0x101), lw(2, 1, 0))
    try:
        run_n(cpu, 2)
    except Trap as t:
        assert t.kind == "misaligned-load"
        return
    raise AssertionError("expected misaligned-load trap")


def test_illegal_opcode_traps():
    # 0x00000000 has opcode 0x00, which is not a valid RV32I opcode.
    cpu = make_cpu(0x00000000)
    try:
        cpu.step()
    except Trap as t:
        assert t.kind == "illegal"
        return
    raise AssertionError("expected illegal trap")


# ---------- runner
def main() -> int:
    tests = [
        (name, fn)
        for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    ]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  pass  {name}")
        except Exception as e:
            failures.append((name, e))
            print(f"  FAIL  {name}: {e!r}")
    print()
    print(f"refmodel sanity: {len(tests) - len(failures)}/{len(tests)} passed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
