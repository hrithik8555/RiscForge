"""riscv_tests_runner.py - run the rv32ui suite through the reference emulator.

The deep validation gate for the reference model. The official
riscv-tests are the de facto conformance suite for RV32I; if the
emulator passes them, the ISA implementation is right where it
matters. Once this gate is green, every RTL test downstream uses
this emulator as the oracle.

What this script does:
  1. Walk the binaries in tools/refmodel/_riscv_tests_bin/.
  2. For each ELF, extract loadable segments and the address of the
     `tohost` symbol from the symbol table.
  3. Build an emulator with mem_base at the lowest segment, room above
     for stack and BSS, and tohost_addr set from the symbol.
  4. Run until the emulator halts. Per riscv-tests convention, a write
     of 1 to `tohost` means the test passed; any other halt is a fail.

CLI:
    python3 tools/refmodel/riscv_tests_runner.py             # all tests
    python3 tools/refmodel/riscv_tests_runner.py add lui     # subset by substring

Honest note on skips: KNOWN_SKIPS lists tests that need behavior we
deliberately did not implement at stage 1, with a one-line reason.
Today the only skip is ma_data (misaligned-access trap handling).
The runner reports those as skipped, not failed, and they do not
affect the exit code.
"""

from __future__ import annotations

import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tools" / "refmodel" / "_riscv_tests_bin"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rv32i_emu import RV32I, Trap  # noqa: E402

# Tests known to need behavior we deliberately did not implement at
# stage 1. Each entry: test name -> reason. The runner reports these
# as skipped, not failed, and does NOT count them toward the exit code.
KNOWN_SKIPS = {
    "rv32ui-p-ma_data":
        "misaligned-access trap handler not implemented at stage 1; "
        "the emulator and the RTL both trap-and-halt per our cross-cutting decisions",
}

# Generous step cap. Tests run a few hundred instructions in practice;
# this catches infinite loops caused by emulator bugs without letting
# them stall CI forever.
MAX_STEPS = 1_000_000


def load_elf(path: Path) -> tuple[list[tuple[int, bytes]], int | None]:
    """Return (segments, tohost_addr) for one ELF binary.

    `segments` is a list of (physical_address, bytes) for every
    PT_LOAD program header with file content.
    `tohost_addr` is the address of the `tohost` symbol or None.
    """
    segments: list[tuple[int, bytes]] = []
    tohost: int | None = None
    with open(path, "rb") as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            if sec.name == ".symtab":
                for sym in sec.iter_symbols():
                    if sym.name == "tohost":
                        tohost = int(sym["st_value"])
                        break
        for seg in elf.iter_segments():
            if seg["p_type"] == "PT_LOAD" and seg["p_filesz"] > 0:
                segments.append((int(seg["p_paddr"]), seg.data()))
    return segments, tohost


def run_test(elf_path: Path) -> tuple[bool, str]:
    """Run one test ELF. Returns (passed, human-readable reason)."""
    segments, tohost = load_elf(elf_path)
    if tohost is None:
        return False, "no `tohost` symbol in ELF"
    if not segments:
        return False, "no loadable segments in ELF"

    base = min(s[0] for s in segments)
    top = max(s[0] + len(s[1]) for s in segments)
    # Round mem size up by 64 KiB above the highest loaded segment.
    # That gives the test some BSS / stack room without us having to
    # parse every section header.
    mem_size = ((top - base + 0xFFFF) & ~0xFFFF) + 0x10000

    # trap_on_ecall=True: the riscv-tests env code expects ECALL to
    # take a real trap so its handler can read the test result and
    # write to tohost. Hand-written sanity tests do not need this and
    # rely on the default (halt on ECALL).
    cpu = RV32I(
        mem_size=mem_size,
        mem_base=base,
        tohost_addr=tohost,
        trap_on_ecall=True,
    )
    cpu.pc = base

    for paddr, data in segments:
        cpu.load_program(data, base=paddr)

    try:
        reason = cpu.run(max_steps=MAX_STEPS)
    except Trap as t:
        return False, f"trap: {t.kind} at PC=0x{t.pc:08x}: {t.detail}"

    if reason == "tohost-pass":
        return True, f"tohost=1 after {cpu.steps} steps"
    if reason == "tohost-fail":
        v = cpu.tohost_value or 0
        # riscv-tests encode failing test number as (n << 1) | 1.
        return False, f"tohost=0x{v:x} (failing subtest {v >> 1})"
    return False, f"halt={reason}, last PC=0x{cpu.pc:08x}, {cpu.steps} steps"


def main(argv: list[str]) -> int:
    if not TESTS_DIR.exists() or not any(TESTS_DIR.iterdir()):
        print(
            f"no built tests at {TESTS_DIR}.\n"
            f"  run `make riscv-tests-build` (or scripts/build_riscv_tests.sh) first.",
            file=sys.stderr,
        )
        return 2

    all_tests = sorted(
        p for p in TESTS_DIR.iterdir()
        if p.is_file() and not p.name.endswith(".dump") and not p.name.startswith(".")
    )
    if not all_tests:
        print(f"no test binaries in {TESTS_DIR}", file=sys.stderr)
        return 2

    # Optional substring filters: `... add lui` runs every test whose
    # name contains "add" or "lui".
    filters = argv[1:] if len(argv) > 1 else None
    if filters:
        all_tests = [t for t in all_tests if any(f in t.name for f in filters)]
        if not all_tests:
            print(f"no tests match filters {filters}", file=sys.stderr)
            return 2

    passes = 0
    fails: list[tuple[str, str]] = []
    skips: list[tuple[str, str]] = []

    for t in all_tests:
        if t.name in KNOWN_SKIPS:
            skips.append((t.name, KNOWN_SKIPS[t.name]))
            print(f"  skip  {t.name}: {KNOWN_SKIPS[t.name]}")
            continue
        ok, reason = run_test(t)
        if ok:
            passes += 1
            print(f"  pass  {t.name}  ({reason})")
        else:
            fails.append((t.name, reason))
            print(f"  FAIL  {t.name}: {reason}")

    print()
    counted = len(all_tests) - len(skips)
    print(
        f"riscv-tests rv32ui: {passes}/{counted} passed, "
        f"{len(fails)} failed, {len(skips)} skipped"
    )
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
