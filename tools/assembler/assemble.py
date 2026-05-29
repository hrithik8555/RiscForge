"""assemble.py - a small two-pass RV32I assembler.

What this is: a hand-written assembler that takes an .s text file and
emits a hex image suitable for $readmemh in the RTL. One 32-bit word
per line, hex, no prefix, no commas. The same output also drives the
Python emulator's load_program path (after a tiny adapter on the
reader side).

Why it exists: I want to write programs in real assembly (Fibonacci,
GCD, sort) and have them assembled by code I control. I do not want
the reference path to be "trust riscv64-unknown-elf-as", because then
any disagreement with the RTL is a three-way debug session between
the GNU toolchain, my emulator, and my hardware. With my own
assembler the encoding is the same table the emulator and the RTL
package already share (tools/refmodel/encoding.py).

What is honest:
  - This is RV32I only. Zicsr and Zifencei are NOT supported; those
    live in the emulator for riscv-tests bring-up and never appear
    in handwritten programs. The two-path testing story stays clean.
  - The data segment is laid out immediately after .text in the
    output image, with a runtime base address the caller sets. There
    is no real ELF, no real linker script, no relocation table.
  - LA expands to AUIPC + ADDI relative to the LA instruction itself
    (PC-relative, like GAS does for `la` with -fpic off). That means
    code is position-independent for jumps/branches/LA, but absolute
    addresses must be loaded with LI.
  - Pseudo `CALL sym` is AUIPC + JALR with x1 as link. `RET` is
    `JALR x0, 0(x1)`. Same convention as GAS.
  - Error messages carry the source line number and the offending
    text. They do not try to be cute.

Two passes:
  1. Parse every line. Record labels and the byte offset they sit at
     in the current section. Compute the encoded size of each line
     (4 for instructions, 4 for `.word`, 1 for `.byte`, alignment
     padding, etc.) and stash a parsed-line record.
  2. Walk the parsed-line records and emit encoded words, resolving
     labels and PC-relative immediates against the now-complete
     symbol table.

CLI:
    python3 tools/assembler/assemble.py prog.s -o prog.hex
    python3 tools/assembler/assemble.py prog.s -o prog.hex --base 0
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Pull in the shared encoding tables. Same source-of-truth the
# emulator uses, so the assembler cannot disagree with it by drift.
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "refmodel"))
from encoding import (  # noqa: E402
    Opcode,
    F3Op,
    F3Branch,
    F3Load,
    F3Store,
    F7_DEFAULT,
    F7_ALT,
    F12_ECALL,
    F12_EBREAK,
)


class AsmError(Exception):
    """Raised on any user-facing assembly error. Carries line number."""

    def __init__(self, lineno: int, msg: str, src: str | None = None):
        if src is not None:
            super().__init__(f"line {lineno}: {msg}\n    {src.rstrip()}")
        else:
            super().__init__(f"line {lineno}: {msg}")
        self.lineno = lineno


# ---------- register name table

# ABI names and x-names. x0..x31 and the standard aliases. I do not
# accept fp as an alias for s0 because that is the only one that
# tends to confuse readers; s0 is unambiguous.
_REG_ALIASES = {
    "zero": 0,
    "ra": 1,
    "sp": 2,
    "gp": 3,
    "tp": 4,
    "t0": 5, "t1": 6, "t2": 7,
    "s0": 8, "fp": 8, "s1": 9,
    "a0": 10, "a1": 11, "a2": 12, "a3": 13,
    "a4": 14, "a5": 15, "a6": 16, "a7": 17,
    "s2": 18, "s3": 19, "s4": 20, "s5": 21,
    "s6": 22, "s7": 23, "s8": 24, "s9": 25,
    "s10": 26, "s11": 27,
    "t3": 28, "t4": 29, "t5": 30, "t6": 31,
}


def parse_reg(tok: str, lineno: int, src: str) -> int:
    t = tok.strip().lower()
    if t in _REG_ALIASES:
        return _REG_ALIASES[t]
    m = re.fullmatch(r"x([0-9]+)", t)
    if m:
        n = int(m.group(1))
        if 0 <= n <= 31:
            return n
    raise AsmError(lineno, f"bad register name {tok!r}", src)


# ---------- integer literal parsing

def parse_int(tok: str, lineno: int, src: str) -> int:
    """Parse a decimal, hex (0x), binary (0b), or octal (0o) integer.

    Negative values are accepted. The returned int is a normal Python
    int; range checks are done by the immediate fitters below.
    """
    t = tok.strip().replace("_", "")
    try:
        if t.startswith(("-0x", "-0X")):
            return -int(t[3:], 16)
        if t.startswith(("0x", "0X")):
            return int(t[2:], 16)
        if t.startswith(("-0b", "-0B")):
            return -int(t[3:], 2)
        if t.startswith(("0b", "0B")):
            return int(t[2:], 2)
        if t.startswith(("-0o", "-0O")):
            return -int(t[3:], 8)
        if t.startswith(("0o", "0O")):
            return int(t[2:], 8)
        return int(t, 10)
    except ValueError:
        raise AsmError(lineno, f"bad integer literal {tok!r}", src) from None


def fit_signed(v: int, bits: int, lineno: int, src: str, what: str) -> int:
    """Range-check a signed immediate and return its `bits`-wide two's
    complement bit pattern as a non-negative int."""
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    if not (lo <= v <= hi):
        raise AsmError(
            lineno,
            f"{what}={v} out of signed {bits}-bit range [{lo}, {hi}]",
            src,
        )
    return v & ((1 << bits) - 1)


def fit_unsigned(v: int, bits: int, lineno: int, src: str, what: str) -> int:
    if not (0 <= v < (1 << bits)):
        raise AsmError(
            lineno,
            f"{what}={v} out of unsigned {bits}-bit range [0, {(1 << bits) - 1}]",
            src,
        )
    return v


# ---------- field packers

def r_type(opcode: int, rd: int, f3: int, rs1: int, rs2: int, f7: int) -> int:
    return (
        (f7 & 0x7F) << 25
        | (rs2 & 0x1F) << 20
        | (rs1 & 0x1F) << 15
        | (f3 & 0x7) << 12
        | (rd & 0x1F) << 7
        | (opcode & 0x7F)
    )


def i_type(opcode: int, rd: int, f3: int, rs1: int, imm12: int) -> int:
    # imm12 must already be the 12-bit two's complement bit pattern.
    return (
        (imm12 & 0xFFF) << 20
        | (rs1 & 0x1F) << 15
        | (f3 & 0x7) << 12
        | (rd & 0x1F) << 7
        | (opcode & 0x7F)
    )


def s_type(opcode: int, f3: int, rs1: int, rs2: int, imm12: int) -> int:
    hi = (imm12 >> 5) & 0x7F
    lo = imm12 & 0x1F
    return (
        hi << 25
        | (rs2 & 0x1F) << 20
        | (rs1 & 0x1F) << 15
        | (f3 & 0x7) << 12
        | lo << 7
        | (opcode & 0x7F)
    )


def b_type(opcode: int, f3: int, rs1: int, rs2: int, imm13: int) -> int:
    """B-type immediate is 13 bits with bit 0 forced to zero.

    The bit-scramble that always trips me up:
      inst[31]    = imm[12]
      inst[30:25] = imm[10:5]
      inst[11:8]  = imm[4:1]
      inst[7]     = imm[11]
    """
    b12 = (imm13 >> 12) & 1
    b11 = (imm13 >> 11) & 1
    b10_5 = (imm13 >> 5) & 0x3F
    b4_1 = (imm13 >> 1) & 0xF
    return (
        b12 << 31
        | b10_5 << 25
        | (rs2 & 0x1F) << 20
        | (rs1 & 0x1F) << 15
        | (f3 & 0x7) << 12
        | b4_1 << 8
        | b11 << 7
        | (opcode & 0x7F)
    )


def u_type(opcode: int, rd: int, imm20: int) -> int:
    # imm20 here is already the value that goes into inst[31:12].
    return ((imm20 & 0xFFFFF) << 12) | ((rd & 0x1F) << 7) | (opcode & 0x7F)


def j_type(opcode: int, rd: int, imm21: int) -> int:
    """J-type immediate is 21 bits with bit 0 forced to zero.

    Scramble:
      inst[31]    = imm[20]
      inst[30:21] = imm[10:1]
      inst[20]    = imm[11]
      inst[19:12] = imm[19:12]
    """
    b20 = (imm21 >> 20) & 1
    b19_12 = (imm21 >> 12) & 0xFF
    b11 = (imm21 >> 11) & 1
    b10_1 = (imm21 >> 1) & 0x3FF
    return (
        b20 << 31
        | b10_1 << 21
        | b11 << 20
        | b19_12 << 12
        | (rd & 0x1F) << 7
        | (opcode & 0x7F)
    )


# ---------- parser data structures

@dataclass
class Line:
    lineno: int
    raw: str            # original source line, for error messages
    label: str | None   # label defined on this line, if any
    op: str | None      # mnemonic or directive (lowercased), if any
    args: list[str]     # raw comma-split argument tokens
    section: str        # 'text' or 'data', whichever was active when parsed
    pc: int             # address this line lives at (filled in pass 1)
    size: int           # bytes contributed to the image (filled in pass 1)


_COMMENT_RE = re.compile(r"(#|//).*$")
_LABEL_RE = re.compile(r"^([A-Za-z_.][A-Za-z0-9_.$]*)\s*:\s*(.*)$")


def _split_args(rest: str) -> list[str]:
    """Split an instruction's argument string by commas, honoring the
    'imm(rs1)' form used by loads/stores and JALR.

    I do not try to support general expressions; the assembler is
    deliberately small. `1(sp)` -> ['1', 'sp'] at parse time, and the
    encoder knows that loads/stores expect (imm, rs1) in that order.
    """
    rest = rest.strip()
    if not rest:
        return []
    # Replace `imm(reg)` with `imm, reg` to normalize.
    rest = re.sub(r"\(\s*([^()]+?)\s*\)", r", \1", rest)
    return [a.strip() for a in rest.split(",") if a.strip()]


def tokenize(source: str) -> list[Line]:
    """Strip comments, split labels off, and produce one Line per
    non-empty source line. Multiple statements per line are NOT
    supported (no `addi a0, a0, 1; addi a1, a1, 1`); use one per line."""
    out: list[Line] = []
    section = "text"  # default
    for lineno, raw in enumerate(source.splitlines(), start=1):
        # strip comments
        line = _COMMENT_RE.sub("", raw)
        line = line.strip()
        if not line:
            continue

        label: str | None = None
        m = _LABEL_RE.match(line)
        if m:
            label = m.group(1)
            line = m.group(2).strip()

        if not line:
            # bare label on its own line is fine
            out.append(Line(lineno, raw, label, None, [], section, 0, 0))
            continue

        # first token is mnemonic or directive, the rest are args.
        parts = line.split(None, 1)
        op = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        args = _split_args(rest)

        out.append(Line(lineno, raw, label, op, args, section, 0, 0))
    return out


# ---------- pass 1: lay out sections, build the symbol table

def pass1(lines: list[Line], text_base: int, data_base: int) -> dict[str, int]:
    """Walk lines, assigning each one a (section, pc) and computing its
    encoded size. Returns the symbol table mapping label -> address.

    Sections start empty. .text starts at text_base, .data at
    data_base. .align N rounds the current section pointer up to a
    2^N boundary. Sizes:
      instruction mnemonic -> 4
      .word        -> 4 per value
      .byte        -> 1 per value
      .align N     -> pad bytes
      .text/.data  -> switches section, contributes 0 bytes
    """
    syms: dict[str, int] = {}
    pc = {"text": text_base, "data": data_base}
    current = "text"

    for ln in lines:
        ln.section = current

        # Handle directives that change the section first; labels on
        # those lines still belong to the section that was active
        # before the directive, which matches how GAS behaves.
        if ln.label is not None:
            if ln.label in syms:
                raise AsmError(ln.lineno, f"duplicate label {ln.label!r}", ln.raw)
            syms[ln.label] = pc[current]

        if ln.op is None:
            ln.pc = pc[current]
            ln.size = 0
            continue

        op = ln.op
        if op == ".text":
            current = "text"
            ln.section = current
            ln.pc = pc[current]
            ln.size = 0
            continue
        if op == ".data":
            current = "data"
            ln.section = current
            ln.pc = pc[current]
            ln.size = 0
            continue
        if op == ".align":
            if len(ln.args) != 1:
                raise AsmError(ln.lineno, ".align needs exactly one argument", ln.raw)
            n = parse_int(ln.args[0], ln.lineno, ln.raw)
            if not (0 <= n <= 12):
                raise AsmError(ln.lineno, f".align {n} unreasonable", ln.raw)
            boundary = 1 << n
            padded = (pc[current] + boundary - 1) & ~(boundary - 1)
            ln.pc = pc[current]
            ln.size = padded - pc[current]
            pc[current] = padded
            continue
        if op == ".word":
            if not ln.args:
                raise AsmError(ln.lineno, ".word needs at least one value", ln.raw)
            ln.pc = pc[current]
            ln.size = 4 * len(ln.args)
            pc[current] += ln.size
            continue
        if op == ".byte":
            if not ln.args:
                raise AsmError(ln.lineno, ".byte needs at least one value", ln.raw)
            ln.pc = pc[current]
            ln.size = len(ln.args)
            pc[current] += ln.size
            continue

        # Otherwise it must be an instruction. Every real or pseudo
        # mnemonic we accept encodes to a multiple of 4 bytes.
        size = _instruction_size(op, ln)
        ln.pc = pc[current]
        ln.size = size
        pc[current] += size

    return syms


# Pseudo-instructions that expand to two real instructions. Everything
# else is one. LI is special: it expands to ADDI when the value fits
# in 12 bits, otherwise to LUI + ADDI.
_TWO_INSN_PSEUDOS = {"la", "call"}


def _instruction_size(op: str, ln: Line) -> int:
    if op in _TWO_INSN_PSEUDOS:
        return 8
    if op == "li":
        # Pass 1 cannot always tell if LI will be one or two
        # instructions without resolving its argument, because the
        # argument might be a label (forward reference). I conservatively
        # reserve 8 bytes for LI in pass 1, and pad with a NOP in pass 2
        # when one instruction suffices. This wastes at most one word
        # per LI; the alternative is two passes inside pass 1, which I
        # would rather not do for a small win.
        return 8
    return 4


# ---------- pass 2: encode

# Map an R-type mnemonic to (funct3, funct7).
_R_TABLE: dict[str, tuple[int, int]] = {
    "add":  (F3Op.ADD_SUB, F7_DEFAULT),
    "sub":  (F3Op.ADD_SUB, F7_ALT),
    "sll":  (F3Op.SLL,     F7_DEFAULT),
    "slt":  (F3Op.SLT,     F7_DEFAULT),
    "sltu": (F3Op.SLTU,    F7_DEFAULT),
    "xor":  (F3Op.XOR,     F7_DEFAULT),
    "srl":  (F3Op.SR,      F7_DEFAULT),
    "sra":  (F3Op.SR,      F7_ALT),
    "or":   (F3Op.OR,      F7_DEFAULT),
    "and":  (F3Op.AND,     F7_DEFAULT),
}

# I-type ALU (OP-IMM) mnemonic -> funct3. SLLI/SRLI/SRAI need a funct7-
# flavored top bit and are handled specially.
_I_ALU_TABLE: dict[str, int] = {
    "addi":  F3Op.ADD_SUB,
    "slti":  F3Op.SLT,
    "sltiu": F3Op.SLTU,
    "xori":  F3Op.XOR,
    "ori":   F3Op.OR,
    "andi":  F3Op.AND,
}

# Loads
_LOAD_TABLE: dict[str, int] = {
    "lb":  F3Load.LB,
    "lh":  F3Load.LH,
    "lw":  F3Load.LW,
    "lbu": F3Load.LBU,
    "lhu": F3Load.LHU,
}

# Stores
_STORE_TABLE: dict[str, int] = {
    "sb": F3Store.SB,
    "sh": F3Store.SH,
    "sw": F3Store.SW,
}

# Branches
_BRANCH_TABLE: dict[str, int] = {
    "beq":  F3Branch.BEQ,
    "bne":  F3Branch.BNE,
    "blt":  F3Branch.BLT,
    "bge":  F3Branch.BGE,
    "bltu": F3Branch.BLTU,
    "bgeu": F3Branch.BGEU,
}


def _resolve(tok: str, syms: dict[str, int], lineno: int, src: str) -> int:
    """Resolve a token that may be an integer literal or a label."""
    t = tok.strip()
    if not t:
        raise AsmError(lineno, "empty operand", src)
    if t[0].isalpha() or t[0] == "_" or t[0] == ".":
        if t in syms:
            return syms[t]
        # Allow integer-only tokens that happen to start with a letter?
        # No: keep parse_int strict. Fall through to a clear error.
        raise AsmError(lineno, f"undefined symbol {t!r}", src)
    return parse_int(t, lineno, src)


def _expect_args(ln: Line, n: int, what: str) -> None:
    if len(ln.args) != n:
        raise AsmError(
            ln.lineno,
            f"{what}: expected {n} operands, got {len(ln.args)}",
            ln.raw,
        )


def encode_line(
    ln: Line,
    syms: dict[str, int],
) -> list[int]:
    """Return a list of 32-bit words for this instruction line.

    Most lines return one word. LI returns one or two (padded to two
    with a trailing NOP if the constant fits in 12 bits, see pass1).
    LA and CALL return two. Directives and bare labels return [].
    """
    if ln.op is None:
        return []
    op = ln.op

    # ---------- directives
    if op in (".text", ".data", ".align"):
        # .align is just padding; emit zero bytes here and let the
        # writer pad with zeros up to ln.size.
        return []
    if op == ".word":
        vals = []
        for a in ln.args:
            v = _resolve(a, syms, ln.lineno, ln.raw) & 0xFFFFFFFF
            vals.append(v)
        return vals
    if op == ".byte":
        # Pack into 32-bit words later, in the writer. Here we return
        # the byte values masked into ints; the writer interprets size.
        # I take the shortcut of returning bytes as ints in a list
        # and the writer figures it out.
        return [_resolve(a, syms, ln.lineno, ln.raw) & 0xFF for a in ln.args]

    # ---------- R-type
    if op in _R_TABLE:
        _expect_args(ln, 3, op)
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs1 = parse_reg(ln.args[1], ln.lineno, ln.raw)
        rs2 = parse_reg(ln.args[2], ln.lineno, ln.raw)
        f3, f7 = _R_TABLE[op]
        return [r_type(Opcode.REG, rd, f3, rs1, rs2, f7)]

    # ---------- I-type ALU
    if op in _I_ALU_TABLE:
        _expect_args(ln, 3, op)
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs1 = parse_reg(ln.args[1], ln.lineno, ln.raw)
        imm = _resolve(ln.args[2], syms, ln.lineno, ln.raw)
        # SLTIU sign-extends its immediate too, per the spec. The fit
        # check is signed-12-bit regardless of the unsigned compare.
        imm12 = fit_signed(imm, 12, ln.lineno, ln.raw, "imm")
        return [i_type(Opcode.IMM, rd, _I_ALU_TABLE[op], rs1, imm12)]

    # ---------- shift-immediate
    if op in ("slli", "srli", "srai"):
        _expect_args(ln, 3, op)
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs1 = parse_reg(ln.args[1], ln.lineno, ln.raw)
        sh = _resolve(ln.args[2], syms, ln.lineno, ln.raw)
        sh = fit_unsigned(sh, 5, ln.lineno, ln.raw, "shamt")
        f3 = F3Op.SLL if op == "slli" else F3Op.SR
        f7 = F7_ALT if op == "srai" else F7_DEFAULT
        # I-type with the top 7 bits acting like funct7 carrying the
        # SRA-or-SRL discriminator. Pack via r_type to reuse the bits.
        return [r_type(Opcode.IMM, rd, f3, rs1, sh, f7)]

    # ---------- loads
    if op in _LOAD_TABLE:
        _expect_args(ln, 3, op)
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        # After _split_args, `lw a0, 4(sp)` becomes args ['a0', '4', 'sp'].
        imm = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        rs1 = parse_reg(ln.args[2], ln.lineno, ln.raw)
        imm12 = fit_signed(imm, 12, ln.lineno, ln.raw, "offset")
        return [i_type(Opcode.LOAD, rd, _LOAD_TABLE[op], rs1, imm12)]

    # ---------- stores
    if op in _STORE_TABLE:
        _expect_args(ln, 3, op)
        rs2 = parse_reg(ln.args[0], ln.lineno, ln.raw)
        imm = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        rs1 = parse_reg(ln.args[2], ln.lineno, ln.raw)
        imm12 = fit_signed(imm, 12, ln.lineno, ln.raw, "offset")
        return [s_type(Opcode.STORE, _STORE_TABLE[op], rs1, rs2, imm12)]

    # ---------- branches
    if op in _BRANCH_TABLE:
        _expect_args(ln, 3, op)
        rs1 = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs2 = parse_reg(ln.args[1], ln.lineno, ln.raw)
        target = _resolve(ln.args[2], syms, ln.lineno, ln.raw)
        offset = target - ln.pc
        if offset & 1:
            raise AsmError(ln.lineno, f"branch target {target:#x} not 2-byte aligned", ln.raw)
        imm13 = fit_signed(offset, 13, ln.lineno, ln.raw, "branch offset")
        return [b_type(Opcode.BRANCH, _BRANCH_TABLE[op], rs1, rs2, imm13)]

    # ---------- JAL / JALR
    if op == "jal":
        # Two forms: `jal label` (rd=ra) and `jal rd, label`.
        if len(ln.args) == 1:
            rd = 1  # ra
            target = _resolve(ln.args[0], syms, ln.lineno, ln.raw)
        elif len(ln.args) == 2:
            rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
            target = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        else:
            raise AsmError(ln.lineno, "jal: expected 1 or 2 operands", ln.raw)
        offset = target - ln.pc
        if offset & 1:
            raise AsmError(ln.lineno, f"jal target {target:#x} not 2-byte aligned", ln.raw)
        imm21 = fit_signed(offset, 21, ln.lineno, ln.raw, "jal offset")
        return [j_type(Opcode.JAL, rd, imm21)]

    if op == "jalr":
        # Accept three forms:
        #   jalr rs1                  -> jalr x1, rs1, 0    (Note: actually rd=ra? GAS uses x1, but conventional `jalr rs` is jalr x0, rs, 0)
        # I follow GAS: bare `jalr rs1` means `jalr x1, 0(rs1)`. That
        # matches how `call` is built and how function returns get
        # written when not using `ret`.
        #   jalr rd, rs1, imm
        #   jalr rd, imm(rs1)         -> after _split_args this is rd, imm, rs1
        if len(ln.args) == 1:
            rd = 1
            rs1 = parse_reg(ln.args[0], ln.lineno, ln.raw)
            imm = 0
        elif len(ln.args) == 3:
            rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
            # disambiguate (rd, rs1, imm) vs (rd, imm, rs1) by trying
            # to parse arg[1] as a register first
            try:
                rs1 = parse_reg(ln.args[1], ln.lineno, ln.raw)
                imm = _resolve(ln.args[2], syms, ln.lineno, ln.raw)
            except AsmError:
                imm = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
                rs1 = parse_reg(ln.args[2], ln.lineno, ln.raw)
        else:
            raise AsmError(ln.lineno, "jalr: expected 1 or 3 operands", ln.raw)
        imm12 = fit_signed(imm, 12, ln.lineno, ln.raw, "offset")
        return [i_type(Opcode.JALR, rd, 0, rs1, imm12)]

    # ---------- LUI / AUIPC
    if op in ("lui", "auipc"):
        _expect_args(ln, 2, op)
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        v = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        # Allow either a raw 20-bit unsigned (0..0xFFFFF) or a signed
        # 20-bit value. RISC-V LUI's immediate is the top 20 bits of a
        # 32-bit constant, conceptually unsigned, but GAS lets you
        # write negative values that wrap.
        if -(1 << 19) <= v < (1 << 20):
            imm20 = v & 0xFFFFF
        else:
            raise AsmError(
                ln.lineno,
                f"{op} immediate {v} out of 20-bit range",
                ln.raw,
            )
        opcode = Opcode.LUI if op == "lui" else Opcode.AUIPC
        return [u_type(opcode, rd, imm20)]

    # ---------- FENCE / FENCE.I (decoded as NOPs by the core; assemble
    # to the canonical encodings so a disassembler still recognizes them)
    if op == "fence":
        # `fence` with no args -> fence iorw,iorw; the predecessor and
        # successor sets default to 0xF each in GAS. I do the same.
        # Encoding: imm[11:0] = (fm=0)(pred=1111)(succ=1111), rs1=0, f3=0, rd=0
        imm12 = 0b0000_1111_1111
        return [i_type(Opcode.FENCE, 0, 0, 0, imm12)]
    if op == "fence.i":
        # f3=001, imm=0
        return [i_type(Opcode.FENCE, 0, 1, 0, 0)]

    # ---------- ECALL / EBREAK
    if op == "ecall":
        return [i_type(Opcode.SYSTEM, 0, 0, 0, F12_ECALL)]
    if op == "ebreak":
        return [i_type(Opcode.SYSTEM, 0, 0, 0, F12_EBREAK)]

    # ---------- pseudo-instructions
    if op == "nop":
        # addi x0, x0, 0
        return [i_type(Opcode.IMM, 0, F3Op.ADD_SUB, 0, 0)]
    if op == "mv":
        _expect_args(ln, 2, "mv")
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs = parse_reg(ln.args[1], ln.lineno, ln.raw)
        return [i_type(Opcode.IMM, rd, F3Op.ADD_SUB, rs, 0)]
    if op == "not":
        _expect_args(ln, 2, "not")
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs = parse_reg(ln.args[1], ln.lineno, ln.raw)
        # xori rd, rs, -1
        return [i_type(Opcode.IMM, rd, F3Op.XOR, rs, (-1) & 0xFFF)]
    if op == "neg":
        _expect_args(ln, 2, "neg")
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        rs = parse_reg(ln.args[1], ln.lineno, ln.raw)
        # sub rd, x0, rs
        return [r_type(Opcode.REG, rd, F3Op.ADD_SUB, 0, rs, F7_ALT)]
    if op == "j":
        _expect_args(ln, 1, "j")
        target = _resolve(ln.args[0], syms, ln.lineno, ln.raw)
        offset = target - ln.pc
        imm21 = fit_signed(offset, 21, ln.lineno, ln.raw, "j offset")
        return [j_type(Opcode.JAL, 0, imm21)]
    if op == "jr":
        _expect_args(ln, 1, "jr")
        rs1 = parse_reg(ln.args[0], ln.lineno, ln.raw)
        return [i_type(Opcode.JALR, 0, 0, rs1, 0)]
    if op == "ret":
        if ln.args:
            raise AsmError(ln.lineno, "ret takes no operands", ln.raw)
        return [i_type(Opcode.JALR, 0, 0, 1, 0)]
    if op == "beqz":
        _expect_args(ln, 2, "beqz")
        rs1 = parse_reg(ln.args[0], ln.lineno, ln.raw)
        target = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        offset = target - ln.pc
        imm13 = fit_signed(offset, 13, ln.lineno, ln.raw, "beqz offset")
        return [b_type(Opcode.BRANCH, F3Branch.BEQ, rs1, 0, imm13)]
    if op == "bnez":
        _expect_args(ln, 2, "bnez")
        rs1 = parse_reg(ln.args[0], ln.lineno, ln.raw)
        target = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        offset = target - ln.pc
        imm13 = fit_signed(offset, 13, ln.lineno, ln.raw, "bnez offset")
        return [b_type(Opcode.BRANCH, F3Branch.BNE, rs1, 0, imm13)]
    if op == "li":
        _expect_args(ln, 2, "li")
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        v = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        v32 = v & 0xFFFFFFFF
        # If v fits in 12-bit signed, just ADDI from x0. Pad with NOP
        # because pass 1 reserved 8 bytes.
        if -(1 << 11) <= v <= (1 << 11) - 1:
            insn = i_type(Opcode.IMM, rd, F3Op.ADD_SUB, 0, v & 0xFFF)
            nop = i_type(Opcode.IMM, 0, F3Op.ADD_SUB, 0, 0)
            return [insn, nop]
        # Otherwise LUI + ADDI. Account for the sign extension of the
        # ADDI's 12-bit immediate by bumping the upper half when bit 11
        # of the low half is set.
        lo = v32 & 0xFFF
        hi = (v32 >> 12) & 0xFFFFF
        if lo & 0x800:
            hi = (hi + 1) & 0xFFFFF
        lui_w = u_type(Opcode.LUI, rd, hi)
        addi_w = i_type(Opcode.IMM, rd, F3Op.ADD_SUB, rd, lo)
        return [lui_w, addi_w]
    if op == "la":
        # la rd, sym -> auipc rd, hi20(sym - pc); addi rd, rd, lo12
        _expect_args(ln, 2, "la")
        rd = parse_reg(ln.args[0], ln.lineno, ln.raw)
        target = _resolve(ln.args[1], syms, ln.lineno, ln.raw)
        offset = (target - ln.pc) & 0xFFFFFFFF
        lo = offset & 0xFFF
        hi = (offset >> 12) & 0xFFFFF
        if lo & 0x800:
            hi = (hi + 1) & 0xFFFFF
        auipc_w = u_type(Opcode.AUIPC, rd, hi)
        addi_w = i_type(Opcode.IMM, rd, F3Op.ADD_SUB, rd, lo)
        return [auipc_w, addi_w]
    if op == "call":
        # call sym -> auipc x1, hi(sym - pc); jalr x1, lo(x1)
        _expect_args(ln, 1, "call")
        target = _resolve(ln.args[0], syms, ln.lineno, ln.raw)
        offset = (target - ln.pc) & 0xFFFFFFFF
        lo = offset & 0xFFF
        hi = (offset >> 12) & 0xFFFFF
        if lo & 0x800:
            hi = (hi + 1) & 0xFFFFF
        auipc_w = u_type(Opcode.AUIPC, 1, hi)
        jalr_w = i_type(Opcode.JALR, 1, 0, 1, lo)
        return [auipc_w, jalr_w]

    raise AsmError(ln.lineno, f"unknown mnemonic or directive {op!r}", ln.raw)


# ---------- image writer

def assemble(source: str, text_base: int = 0, data_base: int | None = None) -> list[int]:
    """Assemble a source string, returning a list of 32-bit words.

    The returned list is the .text image, word-indexed from text_base.
    The data section, if used, is laid out immediately after .text in
    the same word list. data_base defaults to (text_base + size(.text)),
    word-aligned. The caller controls absolute addressing via text_base.

    I keep the API flat-image because the RTL side reads with
    $readmemh into a single memory; ELF and segment-based loading are
    out of scope for the assembler.
    """
    lines = tokenize(source)

    # First, do a layout pass that just sums sizes, so I can compute
    # data_base if the caller did not pin it.
    sizes = {"text": 0, "data": 0}
    current = "text"
    for ln in lines:
        if ln.op == ".text":
            current = "text"
            continue
        if ln.op == ".data":
            current = "data"
            continue
        if ln.op == ".align":
            if not ln.args:
                continue
            n = parse_int(ln.args[0], ln.lineno, ln.raw)
            boundary = 1 << n
            sizes[current] = (sizes[current] + boundary - 1) & ~(boundary - 1)
            continue
        if ln.op == ".word":
            sizes[current] += 4 * len(ln.args)
            continue
        if ln.op == ".byte":
            sizes[current] += len(ln.args)
            continue
        if ln.op is None:
            continue
        sizes[current] += _instruction_size(ln.op, ln)

    if data_base is None:
        data_base = text_base + ((sizes["text"] + 3) & ~3)

    syms = pass1(lines, text_base=text_base, data_base=data_base)

    # Build a byte image keyed by absolute address, then pack to words.
    image: dict[int, int] = {}

    for ln in lines:
        if ln.op is None:
            continue
        out = encode_line(ln, syms)
        if not out:
            continue
        if ln.op == ".byte":
            for i, b in enumerate(out):
                image[ln.pc + i] = b & 0xFF
            continue
        if ln.op == ".word":
            for i, w in enumerate(out):
                _emit_word(image, ln.pc + 4 * i, w)
            continue
        # everything else is 4-byte instructions
        for i, w in enumerate(out):
            _emit_word(image, ln.pc + 4 * i, w)

    if not image:
        return []

    # Word-pack: cover [lo, hi) rounded out to word boundaries, default
    # to zero where unwritten.
    lo = min(image.keys()) & ~3
    hi = ((max(image.keys()) + 1) + 3) & ~3
    words = []
    for addr in range(lo, hi, 4):
        b0 = image.get(addr + 0, 0)
        b1 = image.get(addr + 1, 0)
        b2 = image.get(addr + 2, 0)
        b3 = image.get(addr + 3, 0)
        words.append(b0 | (b1 << 8) | (b2 << 16) | (b3 << 24))
    return words


def _emit_word(image: dict[int, int], addr: int, word: int) -> None:
    word &= 0xFFFFFFFF
    image[addr + 0] = word & 0xFF
    image[addr + 1] = (word >> 8) & 0xFF
    image[addr + 2] = (word >> 16) & 0xFF
    image[addr + 3] = (word >> 24) & 0xFF


def to_hex_lines(words: list[int]) -> str:
    """Return a $readmemh-friendly string, one 8-hex-digit word per line."""
    return "".join(f"{w:08x}\n" for w in words)


# ---------- CLI

def _cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="RV32I assembler (RiscForge)")
    p.add_argument("source", type=Path, help="input .s file")
    p.add_argument("-o", "--output", type=Path, required=True, help="output .hex file")
    p.add_argument(
        "--base", type=lambda s: int(s, 0), default=0,
        help="text segment base address (default 0)",
    )
    args = p.parse_args(argv)

    try:
        text = args.source.read_text()
    except OSError as e:
        print(f"cannot read {args.source}: {e}", file=sys.stderr)
        return 2

    try:
        words = assemble(text, text_base=args.base)
    except AsmError as e:
        print(f"{args.source}: {e}", file=sys.stderr)
        return 1

    args.output.write_text(to_hex_lines(words))
    print(f"wrote {len(words)} words to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
