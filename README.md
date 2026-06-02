# RiscForge

A 5-stage pipelined RISC-V processor implementing the RV32I base integer
instruction set in SystemVerilog. This repo holds the design document, the
RTL, a Python reference model, an assembler, a test suite, and (eventually)
a writeup of how it performs.

Status: v0.1-singlecycle. A complete single-cycle RV32I core with an assembler,
a reference model, and the official riscv-tests rv32ui suite passing on both the
model and the RTL. The pipeline and its performance features come next. See
`CHANGELOG.md` for the full per-stage narrative and `docs/architecture.md` for
the design.

## What this is and is not

This is a from-scratch educational processor: 5-stage pipeline (IF, ID, EX,
MEM, WB), data hazard forwarding, load-use stall, branches resolved in ID,
2-bit saturating branch predictor with a BTB, direct-mapped instruction
cache, custom Python assembler, and a Python reference model used as the
test oracle.

It is not a tutorial follow-along. The design decisions, hazard handling, and
verification approach are mine, informed by the RISC-V Unprivileged ISA
specification, Patterson and Hennessy, and Harris and Harris.

Out of scope (for v1.0): M, A, F, D extensions; virtual memory; full
interrupt handling; out-of-order or superscalar execution; D-cache. Those
live in the post-v1.0 stretch list.

## Project design document

The pre-code planning lives in `docs/RiscForge_PDD.docx`. The implementation
plan that supersedes it (with branch predictor and I-cache promoted to
mandatory) is mirrored alongside the code as it gets built.

## Building and running

I do all simulation in WSL on Ubuntu 22.04. Native Windows works for Yosys
synthesis later, but cocotb plus Verilator is much smoother on Linux.

Dependencies:

- Verilator (5.x recommended)
- Python 3.10 or newer
- cocotb (`pip install cocotb`)
- GTKWave for waveform viewing

Quick start (once Stage 1.1 lands):

```
make test    # run the cocotb suite
make lint    # verilator --lint-only over all RTL
make wave    # open the most recent VCD in GTKWave
make clean   # nuke sim build artifacts
```

## Repository layout

```
rtl/                 SystemVerilog source
rtl/pkg/             shared packages (opcodes, control structs)
tb/                  cocotb testbenches, one folder per module
asm/                 assembly test programs (.s files)
tools/assembler/     Python assembler (two-pass, RV32I + pseudo-ops)
tools/refmodel/      Python RV32I reference emulator (the test oracle)
docs/                architecture writeup, performance analysis, PDD
docs/diagrams/       Mermaid/graphviz sources for diagrams
scripts/             build scripts, run_benchmarks, lint helpers
sim/                 transient simulation outputs (gitignored)
syn/                 FPGA synthesis scripts (added in Stage 5)
```

## License

TBD. Will pick a permissive one (MIT or BSD-2-Clause) before v1.0.
