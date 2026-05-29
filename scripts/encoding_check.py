#!/usr/bin/env python3
"""Diff rtl/pkg/riscv_pkg.sv against tools/refmodel/encoding.py.

The SystemVerilog package and the Python encoding tables are the same
information in two languages: RTL uses one, the Python reference model
and the assembler use the other. They are hand-kept in sync. This
script catches drift before it becomes hours of "but the bits look
right" debugging.

Run from anywhere; paths are resolved off this script's location:
    python3 scripts/encoding_check.py

Exit code 0 means agreement. Nonzero means drift; the diff prints to
stderr. CI gates on this.

Honest note: the SV parser here is a small regex job, not a real
Verilog parser. It works because riscv_pkg.sv is hand-written in a
very narrow style (enum members on their own lines, no nested types,
no macros inside enum bodies). If I ever generate the package from a
YAML, this script comes out and gets replaced by "load the YAML".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SV_PATH = REPO_ROOT / "rtl" / "pkg" / "riscv_pkg.sv"
PY_DIR = REPO_ROOT / "tools" / "refmodel"

sys.path.insert(0, str(PY_DIR))
import encoding  # noqa: E402  (after path insert)


# (sv typedef name, python class, sv-name prefix to strip)
ENUM_MAPPINGS = [
    ("opcode_e",        encoding.Opcode,   "OP_"),
    ("funct3_op_e",     encoding.F3Op,     "F3_"),
    ("funct3_branch_e", encoding.F3Branch, "F3_"),
    ("funct3_load_e",   encoding.F3Load,   "F3_"),
    ("funct3_store_e",  encoding.F3Store,  "F3_"),
    ("alu_op_e",        encoding.AluOp,    "ALU_"),
    ("alu_src_a_e",     encoding.AluSrcA,  "ALU_A_"),
    ("alu_src_b_e",     encoding.AluSrcB,  "ALU_B_"),
    ("wb_src_e",        encoding.WbSrc,    "WB_"),
    ("branch_op_e",     encoding.BranchOp, "BR_"),
    ("mem_size_e",      encoding.MemSize,  "MEM_"),
]

# Standalone constants. SV uses `localparam`, Python uses module attrs;
# both sides spell the name the same.
LOCALPARAMS = ["XLEN", "F7_DEFAULT", "F7_ALT", "F12_ECALL", "F12_EBREAK"]


_INT_LITERAL = re.compile(r"(\d+)'([bdhoBDHO])([0-9a-fA-F_]+)")


def parse_sv_int_literal(s: str) -> int:
    """Parse Verilog int literals: 7'b0110111, 12'h001, plain decimal, etc."""
    s = s.strip().replace("_", "")
    m = _INT_LITERAL.fullmatch(s)
    if m:
        base = {"b": 2, "d": 10, "h": 16, "o": 8}[m.group(2).lower()]
        return int(m.group(3), base)
    # No sized literal; fall back to plain int (covers `localparam int XLEN = 32`).
    return int(s, 0)


def parse_sv_enum(sv_text: str, typedef_name: str) -> dict[str, int]:
    """Find an enum whose closing line is `} typedef_name;` and return its
    members as {name: int_value}.

    Earlier version used a single regex with a non-greedy capture and got
    bitten by edge cases. Line-based scanning is more obvious to debug:
    find the closing line first, then walk back to the opening
    `typedef enum` line, then parse the lines in between.
    """
    lines = sv_text.splitlines()
    close_pat = re.compile(r"^\s*\}\s*" + re.escape(typedef_name) + r"\s*;")
    open_pat = re.compile(r"^\s*typedef\s+enum\b")

    close_idx = next((i for i, ln in enumerate(lines) if close_pat.match(ln)), None)
    if close_idx is None:
        raise ValueError(f"could not find closing line `}} {typedef_name};`")

    open_idx = None
    for i in range(close_idx - 1, -1, -1):
        if open_pat.match(lines[i]):
            open_idx = i
            break
    if open_idx is None:
        raise ValueError(f"found close for {typedef_name} but no `typedef enum` opener above it")

    members: dict[str, int] = {}
    for raw in lines[open_idx + 1:close_idx]:
        line = re.sub(r"//.*", "", raw).strip().rstrip(",").strip()
        if not line:
            continue
        name, sep, val = line.partition("=")
        if not sep:
            raise ValueError(f"{typedef_name}: member line {raw!r} has no `=`")
        members[name.strip()] = parse_sv_int_literal(val.strip())
    return members


def parse_sv_localparam(sv_text: str, name: str) -> int:
    """Find a `localparam ... NAME = VALUE;` and return the integer value."""
    pat = re.compile(
        r"localparam\s+(?:logic\s*\[[^\]]+\]\s+|int\s+)?"
        + re.escape(name) + r"\s*=\s*([^;]+);"
    )
    m = pat.search(sv_text)
    if not m:
        raise ValueError(f"could not find localparam {name}")
    return parse_sv_int_literal(m.group(1))


def main() -> int:
    sv_text = SV_PATH.read_text()
    errors: list[str] = []
    total_members = 0

    for typedef_name, py_cls, prefix in ENUM_MAPPINGS:
        sv_members = parse_sv_enum(sv_text, typedef_name)
        total_members += len(sv_members)

        stripped: dict[str, int] = {}
        for sv_name, val in sv_members.items():
            if not sv_name.startswith(prefix):
                errors.append(
                    f"{typedef_name}: member {sv_name!r} does not start with "
                    f"expected prefix {prefix!r}"
                )
                continue
            stripped[sv_name[len(prefix):]] = val

        py_members = {m.name: int(m.value) for m in py_cls}

        if stripped != py_members:
            errors.append(
                f"{typedef_name} ({py_cls.__name__}) disagree:\n"
                f"    SV:     {sorted(stripped.items())}\n"
                f"    Python: {sorted(py_members.items())}"
            )

    for name in LOCALPARAMS:
        sv_val = parse_sv_localparam(sv_text, name)
        py_val = getattr(encoding, name)
        if sv_val != py_val:
            errors.append(f"{name}: SV={sv_val}, Python={py_val}")

    if errors:
        print(
            "encoding_check: rtl/pkg/riscv_pkg.sv and tools/refmodel/encoding.py disagree",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(
        f"encoding_check OK: {len(ENUM_MAPPINGS)} enums "
        f"({total_members} members) and {len(LOCALPARAMS)} localparams agree"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
