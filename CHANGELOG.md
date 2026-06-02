# Changelog

I am keeping this changelog as a narrative of how the project actually got built,
stage by stage. Each tagged version is a working artifact that you can clone and
run; the entry describes what is new and what now works compared to the previous
tag.

The format is loosely based on Keep a Changelog. Versions are project stages,
not semver: v0.1 is a working single-cycle processor, v0.2 adds the pipeline,
v0.3 adds the branch predictor, v0.4 adds the I-cache, v1.0 is the polished
release.

## Unreleased

Nothing yet. Next up is stage 2, the pipeline.

## v0.1-singlecycle (2026-06-02)

A complete, working single-cycle RV32I processor. You can write a program in
assembly, assemble it, run it on the hardware (through Verilator), and get the
right answer, with the official RISC-V test suite passing on both the reference
model and the RTL. The only thing missing versus the final design is the
pipeline and the performance features that ride on it.

### What now works

- **Full RV32I single-cycle core.** Ten small SystemVerilog modules wired
  together in `top.sv`: `pc_register`, `instr_memory`, `reg_file`, `imm_gen`,
  `alu`, `decoder`, `branch_unit`, `data_memory`, plus the `riscv_pkg` package.
  Every base integer instruction executes in one cycle. See
  `docs/architecture.md` and `docs/diagrams/datapath.mmd`.
- **A custom two-pass assembler** (`tools/assembler/`). Full RV32I, the common
  pseudo-instructions (LI, LA, MV, NOP, J, JR, CALL, RET, NOT, NEG, BEQZ,
  BNEZ), directives (.text, .data, .word, .byte, .align), and line-numbered
  error messages. It shares the same encoding tables as the rest of the project.
- **A Python reference emulator** (`tools/refmodel/`) used as the oracle for
  every RTL test.
- **Conformance on two fronts.** The official `riscv-tests rv32ui` suite passes
  on the reference model (38/39, `ma_data` skipped) and on the RTL itself
  (38/38, `fence_i` and `ma_data` excluded by design).
- **CI from the start.** Every push runs the encoding diff, the model sanity
  tests, the assembler tests, both riscv-tests runs, the Verilator lint, and
  every cocotb testbench.

### How it is verified (the two-path model)

The single most important idea in the project: the reference model is the
oracle, but its own correctness and the RTL's correctness are checked
separately.

- **Path A, is the oracle right.** The Python emulator runs the official
  `riscv-tests rv32ui` vectors. To boot the upstream binaries it implements a
  minimal slice of Zicsr and a trap mechanism (mtvec/mepc/mcause, MRET, a
  `trap_on_ecall` flag). That CSR/trap code lives ONLY in the emulator.
- **Path B, is the RTL right.** The RTL is lockstepped against the emulator:
  assemble a program, run it on both, compare the full 32-register file. The
  per-opcode directed tests and the program suite (Fibonacci, GCD, factorial)
  all run this way.

### The trick that makes the RTL "RISC-V passing"

The official rv32ui binaries cannot run on our core directly, because their
boot and pass/fail code uses CSR instructions and an ECALL trap handler, and
the RTL is pure RV32I by design. Rather than add CSRs to the hardware, I
rebuilt the same upstream test bodies against a bare-metal, CSR-free
environment of my own (`tools/rtl_tests/env/`): `_start` sits at the reset PC,
and pass/fail is signaled by writing the tohost MMIO word directly. The core
halts on that store and the testbench reads 1 for pass.

This is the deliberate mirror image of Path A. The same obstacle (riscv-tests
boot needs CSRs) was solved opposite ways: the emulator gained minimal CSR
support so the real binaries run unmodified; the hardware stayed pure and the
complexity moved into the build. Both are honest; keeping CSRs out of the
datapath avoids putting untested machinery on the critical path.

### Problems hit and how they got solved

These are the bugs and gotchas worth remembering, because most of them will
come back in some form during the pipeline.

- **Write-first bypass was a combinational loop in single-cycle.** The register
  file's write-first bypass (a pipeline feature: ID reads while WB writes a
  different instruction, fed from a flop) formed a real cycle in single-cycle,
  where the read and write are the same instruction
  (`wd -> rd -> alu -> wd`). Verilator flagged it as UNOPTFLAT, and it was also
  architecturally wrong (the read must see the old value). Fixed by
  parameterizing the bypass: `WRITE_FIRST=0` for single-cycle, default `1` kept
  for the pipeline.
- **Code/data collision in the emulator's unified memory.** A smoke program
  stored to an address that overlapped its own code. The RTL's separate
  instruction and data memories hid it, but the emulator's single memory
  overwrote an instruction and diverged. This is exactly the kind of bug
  lockstep exists to catch. The rule baked in: hand-written programs keep their
  data clear of their code.
- **cocotb cancels a test's forked tasks when it ends.** Running many programs
  in one simulation, the clock started in the first test was dead by the
  second, so the simulator exited "prematurely." Each test now starts its own
  clock.
- **The B-type and J-type immediate bit scrambles.** The classic RV32I trap.
  Hand-traced both directions against the spec table in the assembler tests,
  and the RTL `imm_gen` is cross-checked against the assembler so the two
  cannot drift.
- **SRA, SLT/SLTU, SLTIU.** SRA sign-fills via an explicit `$signed` cast (the
  default would zero-fill). SLT and SLTU are mapped straight from the enum with
  a test asserting they are not swapped. SLTIU's immediate is still
  sign-extended even though the compare is unsigned.
- **riscv-tests would not build from the upstream Makefile.** Its rv32ui
  aggregate target produced nothing, so the build script invokes gcc directly.
  Modern binutils also no longer implies Zicsr/Zifencei from plain `rv32i`, so
  the emulator build uses `-march=rv32i_zicsr_zifencei` (the RTL build uses
  plain `rv32i`, which is the point).
- **Verilator lint details.** The package is wrapped to silence UNUSEDPARAM
  noise when a small module is linted alongside it; leaf-module lint needs a
  MULTITOP waiver; and the package file has to be listed before the modules
  that import it.
- **Loading programs into the RTL.** The integration and conformance tests
  write program words straight into the core's memory arrays over VPI
  (Verilator built with `--public-flat-rw`), so one simulation can run many
  programs with a reset between each. The single-program smoke test instead
  assembles a hex at build time via cocotb's `CUSTOM_SIM_DEPS` hook.

### Encoding stays in sync

The RTL package (`rtl/pkg/riscv_pkg.sv`) and the Python tables
(`tools/refmodel/encoding.py`) are hand-kept mirrors. `scripts/encoding_check.py`
diffs them and CI fails on any drift, so the assembler, the emulator, and the
hardware can never disagree about what an opcode means.

### Honest caveats at this tag

- Single-cycle, not pipelined. Long critical path; this tag is about
  correctness, not speed.
- Harvard memories, so no self-modifying code (`fence_i` excluded from RTL
  conformance).
- No CSRs in the RTL (`ma_data` excluded; the core traps and halts).
- FENCE and FENCE.I decode as NOPs.
- The assembler emits a flat image, not real ELF.

### Scaffolding (folded in from the initial setup)

- Repository layout matching the design document (rtl, tb, asm, tools, docs,
  scripts, sim).
- Top-level Makefile with explicit per-module test targets, lint, wave, clean,
  docs, and the riscv-tests targets.
- A trivial 4-bit counter module with a cocotb test, kept as the toolchain
  smoke test that confirms Verilator, cocotb, and VCD dumping all work.
- .gitignore covering simulation artifacts, Python caches, build outputs, and
  the pulled/generated test binaries.
