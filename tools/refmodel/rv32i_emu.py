"""rv32i_emu.py - Python RV32I reference emulator.

This is the oracle for the project. Stage 1.5 validates it against
the official riscv-tests rv32ui suite; once that passes, every RTL
test from stage 1.7 onward lockstep against the trace this produces.

Honest shortcuts and decisions:
- Memory is a flat bytearray with little-endian byte access. No
  virtual addressing, no caches. The RTL gets caches in stage 4;
  the reference does not need them to be the oracle.
- 32-bit overflow wraps at 2^32. Python ints are arbitrary precision,
  so every result is masked back to 32 bits explicitly.
- Misaligned LW / LH / SW / SH trap, matching the RTL behavior
  picked in the cross-cutting decisions.
- ECALL and EBREAK halt simulation with a flag the harness can read.
- tohost MMIO at a configurable address (default 0x80001000), used by
  riscv-tests to signal pass/fail by writing to that location.
- FENCE and FENCE.I decode as NOPs because there are no caches at
  this layer of the stack.
- CSR instructions (Zicsr extension) are not implemented at stage 1.
  They trap as illegal. Tests in rv32ui do not use them.

Spec reference: RISC-V Unprivileged ISA Specification, Volume 1,
version 20191213. Section and table references inline where helpful.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

from encoding import (
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


XLEN = 32
XMASK = (1 << XLEN) - 1


# ---------- small helpers used everywhere
def u32(x: int) -> int:
    """Mask to 32 unsigned bits."""
    return x & XMASK


def s32(x: int) -> int:
    """Interpret the low 32 bits of x as a signed two's-complement int."""
    x &= XMASK
    return x - (1 << XLEN) if x & (1 << (XLEN - 1)) else x


def sext(value: int, bits: int) -> int:
    """Sign-extend a `bits`-wide int to a Python signed int."""
    sign = 1 << (bits - 1)
    value &= (1 << bits) - 1
    return (value ^ sign) - sign


# ---------- immediate decoders
# The RISC-V spec scrambles immediate bits across the instruction word
# so the same imm[X] bit always sits in the same hardware position
# across formats. Hardware decode is cheap; these Python decoders are
# fiddly to read. Recipe per spec table 24.1.
def imm_i(inst: int) -> int:
    """I-type immediate: bits[31:20], sign-extended from 12 bits."""
    return sext((inst >> 20) & 0xFFF, 12)


def imm_s(inst: int) -> int:
    """S-type immediate: imm[11:5] from inst[31:25], imm[4:0] from inst[11:7]."""
    raw = (((inst >> 25) & 0x7F) << 5) | ((inst >> 7) & 0x1F)
    return sext(raw, 12)


def imm_b(inst: int) -> int:
    """B-type immediate: 13-bit branch offset, bit 0 implicit zero.

      imm[12]   = inst[31]
      imm[10:5] = inst[30:25]
      imm[4:1]  = inst[11:8]
      imm[11]   = inst[7]
      imm[0]    = 0
    """
    raw = (
        (((inst >> 31) & 0x1) << 12)
        | (((inst >> 25) & 0x3F) << 5)
        | (((inst >> 8) & 0xF) << 1)
        | (((inst >> 7) & 0x1) << 11)
    )
    return sext(raw, 13)


def imm_u(inst: int) -> int:
    """U-type immediate: inst[31:12] << 12, low 12 bits zero."""
    return inst & 0xFFFFF000


def imm_j(inst: int) -> int:
    """J-type immediate: 21-bit jump offset, bit 0 implicit zero.

      imm[20]    = inst[31]
      imm[10:1]  = inst[30:21]
      imm[11]    = inst[20]
      imm[19:12] = inst[19:12]
      imm[0]     = 0
    """
    raw = (
        (((inst >> 31) & 0x1) << 20)
        | (((inst >> 21) & 0x3FF) << 1)
        | (((inst >> 20) & 0x1) << 11)
        | (((inst >> 12) & 0xFF) << 12)
    )
    return sext(raw, 21)


# ---------- per-step trace record used for RTL lockstep later
@dataclass
class StepTrace:
    pc: int                       # PC at which this instruction was fetched
    inst: int                     # the 32-bit instruction word
    # (reg_idx, new_value) if rd was written this cycle, else None
    rd_write: Optional[tuple[int, int]] = None
    # (addr, value, size_bytes) if a store happened this cycle, else None
    mem_write: Optional[tuple[int, int, int]] = None


class Trap(Exception):
    """Raised on a fatal condition: illegal instruction, misaligned
    access, ECALL, EBREAK. The kind field lets the harness tell them
    apart without parsing the message text."""

    def __init__(self, kind: str, pc: int, detail: str = ""):
        super().__init__(f"{kind} at PC=0x{pc:08x}: {detail}")
        self.kind = kind
        self.pc = pc
        self.detail = detail


class RV32I:
    """One instance is one CPU's worth of state."""

    def __init__(
        self,
        mem_size: int = 64 * 1024,
        mem_base: int = 0,
        tohost_addr: int = 0x80001000,
    ):
        self.regs = [0] * 32
        self.pc = mem_base
        self.mem = bytearray(mem_size)
        self.mem_base = mem_base
        self.tohost_addr = tohost_addr
        self.tohost_value: Optional[int] = None
        self.halted = False
        self.halt_reason: Optional[str] = None
        self.steps = 0

    # ---------- memory: tohost is intercepted in store(), everything
    # else routes through _mem_index for a flat bytearray.
    def _mem_index(self, addr: int, size: int) -> int:
        if addr < self.mem_base or addr + size > self.mem_base + len(self.mem):
            raise Trap("mem-range", self.pc, f"addr=0x{addr:08x} size={size}")
        return addr - self.mem_base

    def load_program(self, data: bytes, base: Optional[int] = None) -> None:
        """Drop bytes into memory starting at `base` (defaults to mem_base)."""
        if base is None:
            base = self.mem_base
        offset = base - self.mem_base
        end = offset + len(data)
        if offset < 0 or end > len(self.mem):
            raise ValueError(
                f"program does not fit: base=0x{base:x}, len={len(data)}, "
                f"mem=[0x{self.mem_base:x}, 0x{self.mem_base + len(self.mem):x})"
            )
        self.mem[offset:end] = data

    def fetch(self, addr: int) -> int:
        if addr & 0x3:
            raise Trap("misaligned-fetch", self.pc, f"addr=0x{addr:08x}")
        i = self._mem_index(addr, 4)
        return struct.unpack_from("<I", self.mem, i)[0]

    def load(self, addr: int, size: int, signed: bool) -> int:
        if size in (2, 4) and (addr & (size - 1)):
            raise Trap("misaligned-load", self.pc, f"addr=0x{addr:08x} size={size}")
        i = self._mem_index(addr, size)
        if size == 1:
            v = self.mem[i]
            return sext(v, 8) & XMASK if signed else v
        if size == 2:
            v = struct.unpack_from("<H", self.mem, i)[0]
            return sext(v, 16) & XMASK if signed else v
        v = struct.unpack_from("<I", self.mem, i)[0]
        return v  # size 4: no sign extension needed

    def store(self, addr: int, value: int, size: int) -> None:
        # MMIO check first so tohost writes don't need to land in mem_base.
        if addr == self.tohost_addr:
            self.tohost_value = u32(value)
            self.halted = True
            self.halt_reason = "tohost-pass" if self.tohost_value == 1 else "tohost-fail"
            return
        if size in (2, 4) and (addr & (size - 1)):
            raise Trap("misaligned-store", self.pc, f"addr=0x{addr:08x} size={size}")
        i = self._mem_index(addr, size)
        if size == 1:
            self.mem[i] = value & 0xFF
        elif size == 2:
            struct.pack_into("<H", self.mem, i, value & 0xFFFF)
        else:
            struct.pack_into("<I", self.mem, i, u32(value))

    # ---------- register file with x0 forced to zero on read and write
    def r(self, idx: int) -> int:
        return 0 if idx == 0 else self.regs[idx]

    def wr(self, idx: int, value: int) -> None:
        if idx != 0:
            self.regs[idx] = u32(value)

    # ---------- one instruction step
    def step(self) -> StepTrace:
        if self.halted:
            raise RuntimeError("step() called on halted CPU")

        pc = self.pc
        inst = self.fetch(pc)
        trace = StepTrace(pc=pc, inst=inst)

        opcode = inst & 0x7F
        rd = (inst >> 7) & 0x1F
        funct3 = (inst >> 12) & 0x7
        rs1 = (inst >> 15) & 0x1F
        rs2 = (inst >> 20) & 0x1F
        funct7 = (inst >> 25) & 0x7F

        next_pc = u32(pc + 4)

        if opcode == Opcode.LUI:
            self.wr(rd, imm_u(inst))

        elif opcode == Opcode.AUIPC:
            self.wr(rd, u32(pc + imm_u(inst)))

        elif opcode == Opcode.JAL:
            link = next_pc
            target = u32(pc + imm_j(inst))
            if target & 0x3:
                raise Trap("misaligned-fetch", pc, f"JAL target=0x{target:08x}")
            self.wr(rd, link)
            next_pc = target

        elif opcode == Opcode.JALR:
            link = next_pc
            target = u32((self.r(rs1) + imm_i(inst)) & ~1)
            if target & 0x3:
                raise Trap("misaligned-fetch", pc, f"JALR target=0x{target:08x}")
            self.wr(rd, link)
            next_pc = target

        elif opcode == Opcode.BRANCH:
            a, b = self.r(rs1), self.r(rs2)
            if funct3 == F3Branch.BEQ:
                taken = a == b
            elif funct3 == F3Branch.BNE:
                taken = a != b
            elif funct3 == F3Branch.BLT:
                taken = s32(a) < s32(b)
            elif funct3 == F3Branch.BGE:
                taken = s32(a) >= s32(b)
            elif funct3 == F3Branch.BLTU:
                taken = u32(a) < u32(b)
            elif funct3 == F3Branch.BGEU:
                taken = u32(a) >= u32(b)
            else:
                raise Trap("illegal", pc, f"branch funct3={funct3}")
            if taken:
                target = u32(pc + imm_b(inst))
                if target & 0x3:
                    raise Trap("misaligned-fetch", pc, f"BR target=0x{target:08x}")
                next_pc = target

        elif opcode == Opcode.LOAD:
            addr = u32(self.r(rs1) + imm_i(inst))
            if funct3 == F3Load.LB:
                v = self.load(addr, 1, signed=True)
            elif funct3 == F3Load.LH:
                v = self.load(addr, 2, signed=True)
            elif funct3 == F3Load.LW:
                v = self.load(addr, 4, signed=False)
            elif funct3 == F3Load.LBU:
                v = self.load(addr, 1, signed=False)
            elif funct3 == F3Load.LHU:
                v = self.load(addr, 2, signed=False)
            else:
                raise Trap("illegal", pc, f"load funct3={funct3}")
            self.wr(rd, v)

        elif opcode == Opcode.STORE:
            addr = u32(self.r(rs1) + imm_s(inst))
            v = self.r(rs2)
            if funct3 == F3Store.SB:
                size = 1
            elif funct3 == F3Store.SH:
                size = 2
            elif funct3 == F3Store.SW:
                size = 4
            else:
                raise Trap("illegal", pc, f"store funct3={funct3}")
            self.store(addr, v, size)
            trace.mem_write = (addr, u32(v), size)

        elif opcode == Opcode.IMM:
            v = self._alu_imm(funct3, self.r(rs1), imm_i(inst), inst, pc)
            self.wr(rd, v)

        elif opcode == Opcode.REG:
            v = self._alu_reg(funct3, funct7, self.r(rs1), self.r(rs2), pc)
            self.wr(rd, v)

        elif opcode == Opcode.FENCE:
            # No caches at this layer; FENCE / FENCE.I are NOPs.
            pass

        elif opcode == Opcode.SYSTEM:
            funct12 = (inst >> 20) & 0xFFF
            if funct3 != 0:
                # CSR instructions are not implemented at stage 1.
                raise Trap(
                    "illegal", pc, f"system funct3={funct3} (CSR not implemented)"
                )
            if funct12 == F12_ECALL:
                self.halted = True
                self.halt_reason = "ecall"
            elif funct12 == F12_EBREAK:
                self.halted = True
                self.halt_reason = "ebreak"
            else:
                raise Trap("illegal", pc, f"system funct12=0x{funct12:03x}")

        else:
            raise Trap("illegal", pc, f"opcode=0x{opcode:02x}")

        # Record rd write if a non-x0 destination was actually updated by
        # this instruction (a write to x0 was silently discarded by wr()).
        # I detect "did we write?" by checking the opcode classes that
        # write rd. This keeps the trace honest for lockstep purposes.
        if rd != 0 and opcode in (
            Opcode.LUI,
            Opcode.AUIPC,
            Opcode.JAL,
            Opcode.JALR,
            Opcode.LOAD,
            Opcode.IMM,
            Opcode.REG,
        ):
            trace.rd_write = (rd, self.regs[rd])

        self.pc = next_pc
        self.steps += 1
        return trace

    def _alu_imm(self, f3: int, a: int, imm: int, inst: int, pc: int) -> int:
        if f3 == F3Op.ADD_SUB:
            return u32(a + imm)
        if f3 == F3Op.SLT:
            return 1 if s32(a) < s32(imm) else 0
        if f3 == F3Op.SLTU:
            return 1 if u32(a) < u32(imm) else 0
        if f3 == F3Op.XOR:
            return u32(a ^ imm)
        if f3 == F3Op.OR:
            return u32(a | imm)
        if f3 == F3Op.AND:
            return u32(a & imm)
        if f3 == F3Op.SLL:
            return u32(a << (imm & 0x1F))
        if f3 == F3Op.SR:
            # funct7 distinguishes SRLI from SRAI for the immediate form.
            f7 = (inst >> 25) & 0x7F
            shamt = imm & 0x1F
            if f7 == F7_DEFAULT:
                return u32(a) >> shamt
            if f7 == F7_ALT:
                return u32(s32(a) >> shamt)
            raise Trap("illegal", pc, f"OP-IMM SR funct7=0x{f7:02x}")
        raise Trap("illegal", pc, f"OP-IMM funct3={f3}")

    def _alu_reg(self, f3: int, f7: int, a: int, b: int, pc: int) -> int:
        if f3 == F3Op.ADD_SUB:
            if f7 == F7_DEFAULT:
                return u32(a + b)
            if f7 == F7_ALT:
                return u32(a - b)
            raise Trap("illegal", pc, f"OP ADD/SUB funct7=0x{f7:02x}")
        if f3 == F3Op.SLL:
            return u32(a << (b & 0x1F))
        if f3 == F3Op.SLT:
            return 1 if s32(a) < s32(b) else 0
        if f3 == F3Op.SLTU:
            return 1 if u32(a) < u32(b) else 0
        if f3 == F3Op.XOR:
            return u32(a ^ b)
        if f3 == F3Op.SR:
            shamt = b & 0x1F
            if f7 == F7_DEFAULT:
                return u32(a) >> shamt
            if f7 == F7_ALT:
                return u32(s32(a) >> shamt)
            raise Trap("illegal", pc, f"OP SR funct7=0x{f7:02x}")
        if f3 == F3Op.OR:
            return u32(a | b)
        if f3 == F3Op.AND:
            return u32(a & b)
        raise Trap("illegal", pc, f"OP funct3={f3}")

    def run(self, max_steps: int = 1_000_000) -> str:
        """Run until halted or step limit reached. Returns the halt reason."""
        while not self.halted and self.steps < max_steps:
            self.step()
        if not self.halted:
            return "step-limit"
        return self.halt_reason or "halted"
