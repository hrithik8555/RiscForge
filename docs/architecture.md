# RiscForge architecture (v0.1, single-cycle)

This is the architecture as it stands at the `v0.1-singlecycle` tag: a
complete single-cycle RV32I processor with an assembler, a Python
reference model, a unit and integration test suite, and conformance
against the official RISC-V tests on both the model and the hardware.

It is single-cycle on purpose. The pipeline (stage 2), branch predictor
(stage 3), and instruction cache (stage 4) build on top of this. Writing
it single-cycle first means every module is validated end to end before
the timing gets hard.

## The datapath at a glance

One instruction finishes every clock. Within a cycle the work flows:
fetch the instruction, decode it, read the registers, compute in the
ALU, touch memory if it is a load or store, write the result back, and
pick the next PC. The only thing that crosses a clock edge is the PC
itself; everything else is combinational from the fetched instruction.

See `docs/diagrams/datapath.mmd` for the wiring (run `make docs` to
render it to SVG). The dashed edge there is the single sequential
feedback path: `next_pc` is chosen combinationally and latched into the
PC at the clock edge.

## Module list

Each module is small and does one thing. Every one has its own cocotb
testbench under `tb/<module>/`.

| Module           | Responsibility |
|------------------|----------------|
| `pkg/riscv_pkg`  | Single source of truth for opcodes, funct3/funct7, the ALU op enum, and the `control_t` decode bundle. Mirrored in Python by `tools/refmodel/encoding.py`, diffed in CI. |
| `pc_register`    | Program counter. Synchronous reset, stall enable (`en=0` holds) for later stages. |
| `instr_memory`   | Combinational instruction ROM, loaded via `$readmemh` or written directly in tests. |
| `reg_file`       | 32x32 register file. `x0` hardwired to zero. Optional write-first bypass (`WRITE_FIRST` parameter), off for single-cycle, on for the pipeline. |
| `imm_gen`        | Pulls and sign-extends the immediate for I, S, B, U, J formats, including the B-type and J-type bit scrambles. |
| `alu`            | ADD, SUB, AND, OR, XOR, SLL, SRL, SRA, SLT, SLTU, plus PASS_B for LUI. |
| `decoder`        | Every RV32I base encoding into the `control_t` bundle. Raises `illegal` on anything it does not recognize. |
| `branch_unit`    | Resolves taken/not-taken for the six conditional branches; always-taken for JAL/JALR. |
| `data_memory`    | Byte/halfword/word load and store with sign or zero extension, sub-word read-modify-write, misalignment flag, and tohost/UART MMIO. |
| `top`            | Wires all of the above into the single-cycle core, including the next-PC mux and halt detection. |

## How control flow and targets are computed

The ALU does double duty, and the decoder arranges it so the two uses
never collide because they are different opcodes:

- For arithmetic and address calculation the ALU computes the value
  (e.g. `rs1 + imm` for a load address, `rs1 op rs2` for an R-type).
- For branches and JAL the decoder sets the ALU inputs to `PC` and
  `imm`, so the ALU result is the branch target (`PC + imm`).
- For JALR the ALU computes `rs1 + imm`; the next-PC mux clears bit 0.

So the next-PC mux picks between `pc + 4`, the ALU result (branch/JAL),
and the ALU result with bit 0 cleared (JALR), based on the branch unit's
`taken` output and the decoder's `jalr` flag.

## Halt and the tohost convention

The core stops on a recognizable condition and raises `halted` with a
3-bit `halt_cause`: ECALL, EBREAK, illegal instruction, misaligned
access, or a store to the tohost MMIO address (`0x80001000`). On halt
the PC freezes and register writes stop.

The tohost address is the RISC-V test convention: a program signals
"done" by writing there, with `1` meaning pass and `(n << 1) | 1`
encoding a failing subtest `n`. The testbench watches the `tohost_we`
strobe and the `tohost_data` word.

## Memory model

Stage 1 is Harvard: separate `instr_memory` and `data_memory`, both
loaded with the same image. A store touches only the data memory copy,
so self-modifying code does not work yet. That is fine for stage 1, and
the reference emulator (which uses one unified memory) agrees with the
RTL as long as a program keeps its data clear of its code. Latency is a
single cycle; stage 4 raises it and adds the cache.

## Testing strategy: two paths

The reference model is the oracle for everything, but "is the oracle
right?" and "is the RTL right?" are separate questions, so there are two
validation paths.

**Path A, ISA conformance.** The Python emulator (`tools/refmodel/`) is
validated against the official `riscv-tests rv32ui` suite. To boot the
upstream binaries the emulator implements a minimal slice of the Zicsr
extension and a trap mechanism (`mtvec`/`mepc`/`mcause`, MRET,
`trap_on_ecall`). This lives only in the emulator. 38/39 pass with
`ma_data` skipped (misaligned-access handling we deliberately do not
implement at stage 1).

**Path B, RTL correctness.** The RTL is lockstepped against the
emulator: assemble a program, run it on both, compare the full register
file. Per-opcode directed tests and program-level tests (Fibonacci, GCD,
factorial) all run this way under `tb/program/`.

**RTL conformance.** On top of lockstep, the official rv32ui vectors run
on the hardware itself (`tb/riscv/`). Because the RTL is pure RV32I with
no CSRs, the upstream boot code (which uses CSRs and a trap handler)
cannot run on it. Instead the same upstream test bodies are rebuilt
against a bare-metal, CSR-free environment (`tools/rtl_tests/env/`)
whose pass/fail code writes tohost directly. 38/38 pass.

Note the deliberate contrast with Path A: the same problem (riscv-tests
boot needs CSRs) was solved two opposite ways. For the emulator I added
minimal CSR support so the real binaries run unmodified. For the RTL I
kept the hardware pure and moved the complexity into the build. Adding
CSRs to the core would have violated the "CSRs are emulator-only"
decision and put untested machinery into the datapath.

## Honest caveats at v0.1

- Single-cycle, not pipelined. The critical path is long; this is about
  correctness, not speed. The pipeline is stage 2.
- Harvard memories, so no self-modifying code. `fence_i` is excluded
  from the RTL conformance run for this reason.
- No CSRs in the RTL. `ma_data` (misaligned-access traps) is excluded;
  the core traps and halts instead.
- FENCE and FENCE.I decode as NOPs.
- The assembler is RV32I only and emits a flat image, not real ELF.
