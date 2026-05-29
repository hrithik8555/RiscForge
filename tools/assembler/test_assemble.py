"""Sanity tests for the RV32I assembler.

Strategy: for each instruction family I assemble a single line of
source, then check the emitted word against a hand-computed bit
pattern OR against the same word the reference emulator would
recognize by running it. The first style catches bit-scramble bugs
(B-type, J-type, U-type). The second style catches semantic mistakes
(picking the wrong funct3, swapping operands, missing pseudo-instr
expansion).

These are shallow tests, on purpose. The deep gate is the program-
level tests in stage 1.8 where assembled programs run on the
emulator and the RTL in lockstep.

Run:
    python3 tools/assembler/test_assemble.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(THIS_DIR.parent / "refmodel"))

from assemble import assemble, AsmError  # noqa: E402
from rv32i_emu import RV32I  # noqa: E402


# ---------- tiny test harness

_FAILED: list[tuple[str, str]] = []
_PASSED = 0


def check(name: str, fn):
    global _PASSED
    try:
        fn()
        _PASSED += 1
        print(f"  pass  {name}")
    except Exception as e:
        tb = traceback.format_exc()
        _FAILED.append((name, tb))
        print(f"  FAIL  {name}: {e}")


def asm_one(src: str) -> int:
    """Assemble one line, return the first emitted word."""
    words = assemble(src)
    assert words, f"no output from {src!r}"
    return words[0]


def asm_all(src: str) -> list[int]:
    return assemble(src)


# ---------- R-type

def test_add():
    # add a0, a1, a2 -> rd=10 rs1=11 rs2=12 f3=0 f7=0 opcode=0110011
    w = asm_one("add a0, a1, a2")
    assert w == 0x00C58533, f"got {w:08x}"


def test_sub():
    # sub a0, a1, a2 -> f7=0100000
    w = asm_one("sub a0, a1, a2")
    assert w == 0x40C58533, f"got {w:08x}"


def test_sra_vs_srl():
    w_srl = asm_one("srl a0, a1, a2")
    w_sra = asm_one("sra a0, a1, a2")
    assert (w_srl >> 25) & 0x7F == 0b0000000
    assert (w_sra >> 25) & 0x7F == 0b0100000


# ---------- I-type ALU + shifts

def test_addi_positive():
    # addi a0, a1, 5
    w = asm_one("addi a0, a1, 5")
    assert w == (5 << 20) | (11 << 15) | (0 << 12) | (10 << 7) | 0b0010011


def test_addi_negative():
    # addi a0, a1, -1 -> imm12 = 0xFFF
    w = asm_one("addi a0, a1, -1")
    assert w == (0xFFF << 20) | (11 << 15) | (10 << 7) | 0b0010011


def test_slli():
    w = asm_one("slli a0, a1, 4")
    # shamt=4, funct3=001 (SLL), opcode=OP-IMM, funct7=0
    assert w == (4 << 20) | (11 << 15) | (1 << 12) | (10 << 7) | 0b0010011


def test_srai():
    w = asm_one("srai a0, a1, 4")
    # shamt=4, funct3=101, funct7=0100000
    assert (w >> 25) & 0x7F == 0b0100000
    assert (w >> 12) & 0x7 == 0b101


# ---------- loads / stores

def test_lw_paren_form():
    # lw a0, 8(sp)  -> opcode LOAD, f3=010, rs1=sp(2), rd=a0(10), imm=8
    w = asm_one("lw a0, 8(sp)")
    assert w == (8 << 20) | (2 << 15) | (0b010 << 12) | (10 << 7) | 0b0000011


def test_sw_paren_form():
    # sw a0, -4(sp) -> opcode STORE, f3=010, rs1=sp, rs2=a0, imm=-4
    w = asm_one("sw a0, -4(sp)")
    imm = (-4) & 0xFFF
    hi = (imm >> 5) & 0x7F
    lo = imm & 0x1F
    expected = (hi << 25) | (10 << 20) | (2 << 15) | (0b010 << 12) | (lo << 7) | 0b0100011
    assert w == expected, f"got {w:08x}, want {expected:08x}"


# ---------- branches: hand-traced B-type bit scramble

def test_beq_forward_8():
    # At pc=0, branch to pc=8: offset = +8 = 0b00000_0001000
    # B-imm bits: imm[12]=0, imm[11]=0, imm[10:5]=000000, imm[4:1]=0100, imm[0]=0
    # Encoding: inst[31]=0, inst[30:25]=000000, inst[11:8]=0100, inst[7]=0
    src = "beq a0, a1, target\nnop\ntarget: nop\n"
    words = asm_all(src)
    w = words[0]
    # Expected by hand: B-imm 8.
    f3 = (w >> 12) & 0x7
    rs1 = (w >> 15) & 0x1F
    rs2 = (w >> 20) & 0x1F
    op = w & 0x7F
    assert op == 0b1100011
    assert f3 == 0b000
    assert rs1 == 10 and rs2 == 11
    # reconstruct immediate
    b12 = (w >> 31) & 1
    b11 = (w >> 7) & 1
    b10_5 = (w >> 25) & 0x3F
    b4_1 = (w >> 8) & 0xF
    imm = (b12 << 12) | (b11 << 11) | (b10_5 << 5) | (b4_1 << 1)
    # sign-extend
    if imm & (1 << 12):
        imm -= 1 << 13
    assert imm == 8, f"branch imm was {imm}, want 8"


def test_beq_backward():
    # backward branch: target is at 0, branch is at 8
    src = "start: nop\nnop\nbeq a0, a1, start\n"
    words = asm_all(src)
    w = words[2]  # the beq
    b12 = (w >> 31) & 1
    b11 = (w >> 7) & 1
    b10_5 = (w >> 25) & 0x3F
    b4_1 = (w >> 8) & 0xF
    imm = (b12 << 12) | (b11 << 11) | (b10_5 << 5) | (b4_1 << 1)
    if imm & (1 << 12):
        imm -= 1 << 13
    assert imm == -8, f"backward branch imm was {imm}, want -8"


# ---------- JAL: hand-traced J-type bit scramble

def test_jal_forward():
    # jal ra, target where target = pc + 12
    src = "jal ra, target\nnop\nnop\ntarget: nop\n"
    words = asm_all(src)
    w = words[0]
    op = w & 0x7F
    rd = (w >> 7) & 0x1F
    assert op == 0b1101111 and rd == 1
    b20 = (w >> 31) & 1
    b19_12 = (w >> 12) & 0xFF
    b11 = (w >> 20) & 1
    b10_1 = (w >> 21) & 0x3FF
    imm = (b20 << 20) | (b19_12 << 12) | (b11 << 11) | (b10_1 << 1)
    if imm & (1 << 20):
        imm -= 1 << 21
    assert imm == 12, f"jal imm was {imm}"


# ---------- U-type

def test_lui():
    # lui a0, 0x12345 -> a0 = 0x12345000
    w = asm_one("lui a0, 0x12345")
    assert w == (0x12345 << 12) | (10 << 7) | 0b0110111


# ---------- LI expansion

def test_li_small():
    # fits in 12-bit signed -> ADDI + NOP padding
    words = asm_all("li a0, 5")
    assert len(words) == 2
    # ADDI a0, x0, 5
    expected0 = (5 << 20) | (0 << 15) | (0 << 12) | (10 << 7) | 0b0010011
    nop = 0b0010011  # addi x0, x0, 0
    assert words[0] == expected0
    assert words[1] == nop


def test_li_large():
    # 0xDEADBEEF needs LUI + ADDI with sign-bumped upper
    words = asm_all("li a0, 0xDEADBEEF")
    assert len(words) == 2
    # Run through the emulator to confirm semantics.
    cpu = RV32I(mem_size=4096, mem_base=0)
    for i, w in enumerate(words):
        cpu.mem[4 * i:4 * i + 4] = w.to_bytes(4, "little")
    cpu.pc = 0
    cpu.step()
    cpu.step()
    assert cpu.regs[10] == 0xDEADBEEF, f"a0 = {cpu.regs[10]:08x}"


# ---------- LA expansion (PC-relative)

def test_la_to_data_word():
    src = """
        la a0, mydata
        ecall
    .data
    mydata:
        .word 0xCAFEBABE
    """
    words = asm_all(src)
    # Run the emulator to confirm a0 ends up holding the address of
    # mydata and that load from a0 gets the right value.
    cpu = RV32I(mem_size=4096, mem_base=0)
    for i, w in enumerate(words):
        cpu.mem[4 * i:4 * i + 4] = w.to_bytes(4, "little")
    cpu.pc = 0
    # Step through la's two instructions
    cpu.step()
    cpu.step()
    # a0 should be the address of mydata. Find mydata in the image:
    # the assembler put it right after the .text in this minimal
    # program. After auipc+addi+ecall (three words), the .word is at
    # offset 12.
    assert cpu.regs[10] == 12, f"la put {cpu.regs[10]:08x} in a0, want 12"


# ---------- pseudo-instructions

def test_nop():
    w = asm_one("nop")
    assert w == 0b0010011  # addi x0, x0, 0


def test_mv():
    # mv a0, a1 -> addi a0, a1, 0
    w = asm_one("mv a0, a1")
    expected = (0 << 20) | (11 << 15) | (0 << 12) | (10 << 7) | 0b0010011
    assert w == expected


def test_ret():
    # ret -> jalr x0, 0(x1)
    w = asm_one("ret")
    expected = (0 << 20) | (1 << 15) | (0 << 12) | (0 << 7) | 0b1100111
    assert w == expected


def test_beqz():
    src = "beqz a0, target\nnop\ntarget: nop\n"
    words = asm_all(src)
    w = words[0]
    rs1 = (w >> 15) & 0x1F
    rs2 = (w >> 20) & 0x1F
    assert rs1 == 10 and rs2 == 0


def test_j():
    src = "j target\nnop\ntarget: nop\n"
    w = asm_all(src)[0]
    op = w & 0x7F
    rd = (w >> 7) & 0x1F
    assert op == 0b1101111 and rd == 0


# ---------- directives + program-level emulator cross-check

def test_data_word_layout():
    src = """
        .word 0x11111111
        .word 0x22222222
    """
    words = asm_all(src)
    assert words == [0x11111111, 0x22222222]


def test_align():
    src = """
        .byte 0xAA
        .align 2
        .word 0xDEADBEEF
    """
    words = asm_all(src)
    # byte at addr 0, then 3 zero bytes from .align 2, then the word.
    # That packs into [0x000000AA, 0xDEADBEEF].
    assert words == [0x000000AA, 0xDEADBEEF], [hex(w) for w in words]


def test_fibonacci_runs():
    # tiny program: compute fib(10) in a register.
    # I encode iterative two-variable update.
    src = """
        li a0, 0          # a = 0
        li a1, 1          # b = 1
        li a2, 10         # n = 10
        li a3, 0          # i = 0
    loop:
        beq a3, a2, done
        add a4, a0, a1    # t = a + b
        mv  a0, a1
        mv  a1, a4
        addi a3, a3, 1
        j loop
    done:
        ecall
    """
    words = asm_all(src)
    cpu = RV32I(mem_size=4096, mem_base=0)
    for i, w in enumerate(words):
        cpu.mem[4 * i:4 * i + 4] = w.to_bytes(4, "little")
    cpu.pc = 0
    cpu.run(max_steps=1000)
    # After 10 iterations starting from (0, 1), a0 should hold fib(10) = 55.
    assert cpu.regs[10] == 55, f"fib(10) was {cpu.regs[10]}, want 55"


# ---------- errors are line-numbered

def test_undefined_symbol_line_number():
    src = "nop\nnop\nbeq a0, a1, notalabel\n"
    try:
        asm_all(src)
    except AsmError as e:
        assert e.lineno == 3, f"line was {e.lineno}"
        return
    raise AssertionError("expected AsmError")


def test_out_of_range_imm():
    src = "addi a0, a1, 9999\n"
    try:
        asm_all(src)
    except AsmError as e:
        assert e.lineno == 1
        return
    raise AssertionError("expected AsmError")


# ---------- run all

def main() -> int:
    tests = [
        ("add", test_add),
        ("sub", test_sub),
        ("sra-vs-srl funct7", test_sra_vs_srl),
        ("addi positive", test_addi_positive),
        ("addi negative", test_addi_negative),
        ("slli", test_slli),
        ("srai funct7", test_srai),
        ("lw imm(rs1)", test_lw_paren_form),
        ("sw imm(rs1)", test_sw_paren_form),
        ("beq forward bit-scramble", test_beq_forward_8),
        ("beq backward bit-scramble", test_beq_backward),
        ("jal forward bit-scramble", test_jal_forward),
        ("lui", test_lui),
        ("li small (1 insn + nop)", test_li_small),
        ("li large 0xDEADBEEF", test_li_large),
        ("la to data word", test_la_to_data_word),
        ("nop", test_nop),
        ("mv", test_mv),
        ("ret", test_ret),
        ("beqz", test_beqz),
        ("j", test_j),
        (".word layout", test_data_word_layout),
        (".align padding", test_align),
        ("fibonacci program", test_fibonacci_runs),
        ("undefined symbol line number", test_undefined_symbol_line_number),
        ("out-of-range imm error", test_out_of_range_imm),
    ]
    for name, fn in tests:
        check(name, fn)
    print()
    print(f"assembler: {_PASSED}/{_PASSED + len(_FAILED)} passed")
    if _FAILED:
        print()
        for name, tb in _FAILED:
            print(f"=== {name} ===")
            print(tb)
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
