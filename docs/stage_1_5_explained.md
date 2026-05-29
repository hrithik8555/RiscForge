# Stage 1.5, explained from scratch

This document explains what we did in stage 1.5, what problems we ran
into, and why each fix is the right one. It is written so that someone
who knows what a CPU is, vaguely, can follow every single decision. No
words are used without being defined.

If you read this top to bottom, by the end you should understand every
line of the commit messages and the runner code without having to look
anything up.

---

## The big picture

We have a Python program that pretends to be a RISC-V processor. We
wrote it ourselves. We call it the "reference emulator" or "refmodel".
The plan is to use it as the answer key when we build the real processor
in SystemVerilog later: we will run the same program on both, and they
must agree on every step.

Before we trust the emulator as an answer key, we have to test the
emulator itself. The way to do that is to run real RISC-V test programs
through it and check that they say "I passed". The test programs we use
are the official ones from the RISC-V project, called `riscv-tests`.

Stage 1.5 is exactly that gate. By the end of it, the emulator passes
the official suite, so we can trust it as the oracle from now on.

This is the part of the project where the most jargon is dropped on
your head at once. The rest of this document is a vocabulary list and a
walk-through of three problems we hit.

---

## Vocabulary, defined once

I am going to define everything here and then reuse the words below.
If a word appears later that is not on this list, that is a bug in the
document; tell me.

- **CPU**: the chip that runs programs. We will eventually build one
  in SystemVerilog. For now we have only a Python imitation of one.
- **Instruction**: one command the CPU can do. For RISC-V every
  instruction is exactly 32 bits (4 bytes). "Add x1 and x2, put the
  result in x3" is an instruction.
- **Program**: a sequence of instructions stored in memory.
- **Register**: one of 32 small storage slots inside the CPU. Each
  holds a 32-bit number. We name them x0 through x31. Some of them
  have nicknames (a0, gp, t0, etc.) used by the calling convention.
- **Memory**: a much larger storage area outside the CPU. Each byte
  has an address.
- **PC (program counter)**: a special register that holds the address
  of the next instruction to run. Every step, the CPU reads the
  instruction at PC, runs it, then moves PC forward.
- **Emulator**: a program that pretends to be a CPU. Ours is in
  Python.
- **ISA (instruction set architecture)**: the rulebook for what
  instructions exist and what they do.
- **RV32I**: the name of one ISA. "RISC-V, 32-bit, Integer base." The
  minimum required set, about 47 instructions: add, subtract, compare,
  branch, load, store, jump. No multiply, no divide, no floating
  point.
- **Extension**: an optional bundle of instructions on top of the
  base ISA. Each has a letter or short name. The ones that matter for
  this document:
  - **M**: multiply and divide.
  - **Zicsr**: instructions for reading and writing control registers
    (defined below).
  - **Zifencei**: a synchronization fence for instruction fetch (we
    do not really care about this one, just have to mention it).
- **ELF**: a file format that holds compiled programs. Stands for
  "Executable and Linkable Format". When the compiler builds a test,
  the output is an ELF file. The file contains the actual machine-code
  bytes plus metadata that says where in memory each chunk should be
  loaded.
- **GCC**: the GNU C Compiler. We use a build of it that targets
  RISC-V instead of the chip in your laptop.
- **Assembler**: the part of GCC that takes assembly text (`add x3,
  x1, x2`) and turns it into the 32-bit instruction word.
- **Symbol**: a named address inside an ELF. The boot code in a test
  has a label called `tohost`; that label is a symbol, and it
  resolves to some specific memory address.
- **MMIO (memory-mapped I/O)**: a trick where reading or writing a
  specific memory address does not actually touch memory; instead it
  triggers some hardware behavior. Real CPUs use this to talk to
  peripherals. Our emulator uses it to let test programs say "I am
  done".

That is the basic kit. The next list is the words you only need for
this stage.

---

## Vocabulary, specifically for stage 1.5

- **CSR (control and status register)**: a special-purpose register,
  separate from x0 through x31. There are thousands of possible CSRs,
  each with a 12-bit address. They control or report state that is
  not normal program data. The ones we touch:
  - **mtvec** (address 0x305): "Machine Trap Vector". Stores the
    address of the trap handler. When a trap happens, the CPU sets PC
    to this value.
  - **mepc** (address 0x341): "Machine Exception PC". When a trap
    happens, the CPU saves the trapping PC here so the handler can
    return to it later.
  - **mcause** (address 0x342): "Machine Cause". When a trap happens,
    the CPU records why (illegal instruction, ECALL, etc.) here.
  - **mhartid** (address 0xF14): "Machine Hardware Thread ID".
    Identifies which CPU core you are running on. Always 0 in our
    single-core sim.
- **CSR instructions** (the Zicsr extension, six of them):
  - `csrrw rd, csr, rs1`: put the old value of csr into rd, then
    write rs1 into csr.
  - `csrrs rd, csr, rs1`: put the old value into rd, then OR rs1
    into csr (sets the bits that are set in rs1).
  - `csrrc rd, csr, rs1`: put the old value into rd, then clear the
    bits in csr that are set in rs1.
  - `csrrwi`, `csrrsi`, `csrrci`: same three operations but the
    source is a 5-bit immediate from the instruction itself, not a
    register.
- **ECALL**: "Environment Call". An instruction whose entire job is
  to ask the surrounding software for service. Real programs use it
  for system calls. In our case the test code uses ECALL to say "I am
  done, here is my result".
- **EBREAK**: "Environment Breakpoint". An instruction that pauses
  execution. Originally for debuggers. We treat it the same shape as
  ECALL.
- **MRET**: "Machine Return". The instruction that pops the CPU out
  of a trap and resumes execution at the address saved in mepc.
- **WFI**: "Wait For Interrupt". The CPU stops fetching and waits for
  something to wake it. In our emulator there are no interrupts to
  wait for, so it is a no-op.
- **Trap**: a CPU mechanism for handling an exceptional event. When a
  trap happens, the CPU automatically saves the current PC into mepc,
  records the reason in mcause, and jumps to whatever address is in
  mtvec. It is the hardware version of "drop everything and run this
  other code."
- **Trap handler**: the code that runs after a trap. It reads mcause
  to figure out what happened, does whatever is appropriate, and
  usually returns via MRET.
- **tohost**: a memory address that test programs write to in order
  to signal pass or fail. By riscv-tests convention:
  - Write 1 to tohost: test passed.
  - Write any other nonzero value: test failed, the value encodes
    which subtest.

---

## What a "test" really is

When you compile one of the riscv-tests sources, the output is an ELF
file. That ELF, loaded into memory and started at PC = 0x80000000, does
this:

```
[BOOT WRAPPER, written in machine-mode assembly, about 60 instructions]
  install our trap handler:    csrw mtvec, <trap_handler_address>
  set the entry point:         csrw mepc, <user_test_code_address>
  return from machine mode:    mret

[USER TEST CODE, pure RV32I, anywhere from 30 to 500 instructions]
  run the actual test (lots of ADDs, BNEs, LWs, etc.)
  load 1 into the result register
  ecall

[TRAP HANDLER, installed by the boot wrapper, about 30 instructions]
  read mcause: was this an ECALL? yes
  read the result register
  store it to the tohost address
  loop forever waiting for the host to terminate the program
```

The thing to notice: the boot wrapper and the trap handler are NOT
pure RV32I. They use CSR instructions and ECALL / MRET. The user test
code IS pure RV32I.

Our emulator started off knowing only pure RV32I. So every test crashed
the emulator before the actual test code even got a chance to run.

The rest of this document walks through the three walls we hit, in
order, and how each one was knocked down.

---

## Wall 1: GCC refused to assemble the tests

The first error was not even at runtime. When we tried to compile a
test, GCC's assembler refused:

```
Error: unrecognized opcode `csrw mtvec,t0', extension `zicsr' required
```

What it meant: the boot wrapper sources contain CSR instructions, but
we told GCC the target was plain `rv32i`. The Zicsr extension is
technically separate; in modern GCC you have to opt in by adding it to
the architecture string. The same is true of Zifencei (which contains
`fence.i`).

The fix was one character in the build script: `-march=rv32i` became
`-march=rv32i_zicsr_zifencei`. That string says "this code uses RV32I,
plus Zicsr, plus Zifencei; please assemble all of those."

After that, GCC produced the ELF files. Notice this was entirely a
problem on the GCC side; we had not yet touched the emulator.

---

## Wall 2: the emulator rejected CSR instructions

With the ELFs built, we ran the suite. Every test failed at the same
PC (0x800000cc) with the same message: "system funct3=2 (CSR not
implemented)".

Translation: the boot wrapper hit its very first CSR instruction,
which our emulator did not know about, so the emulator stopped and said
"illegal instruction". Same instruction in every test because every
test uses the same boot wrapper.

The fix was to implement enough of Zicsr that the boot code can run.
About 30 lines of Python. The semantics are dead simple:

- Every CSR is a slot in a Python dictionary, keyed by its 12-bit
  address.
- Reading a CSR returns the current value, or 0 if nothing has been
  written yet.
- Writing a CSR stores the new value.
- The six CSR instructions are combinations of read-then-write that
  fall out of the above.

We also added MRET (jump to whatever address is in mepc) and WFI (do
nothing).

We deliberately did NOT add real CSR semantics. There are spec rules
about which CSRs are read-only, what privilege mode you must be in to
touch each one, what happens on illegal access. We ignore all of that.
The boot wrapper is well-behaved code and does not poke at things it
shouldn't, so our laid-back CSR layer is enough.

The CSR work lives entirely inside `rv32i_emu.py`. It does NOT show up
in `rtl/pkg/riscv_pkg.sv` or `tools/refmodel/encoding.py`. The real
processor we are building stays pure RV32I.

After this fix the boot wrapper ran. MRET jumped into the test code.
The test code ran. The test code ran ALL the way to ECALL. And then
everything died for a third reason.

---

## Wall 3: ECALL was killing the emulator before the trap handler ran

With wall 2 down, every test halted at ECALL. The emulator stopped with
reason "ecall" and the runner counted that as a failure, because a
passing test is supposed to write 1 to tohost, and that never happened.

To understand why, you have to know how the test ACTUALLY signals
"pass":

```
[in the test code, at the very end:]
  li gp, 1     # gp is x3. load the constant 1 into it.
  ecall        # ask the environment to handle it.

[in the trap handler installed by the boot wrapper:]
  csrr t0, mcause   # what was the reason for this trap?
  # ...check the cause is "ECALL"...
  sw gp, 0(tohost_pointer)   # write gp to the tohost address
  loop forever
```

The actual tohost write happens INSIDE the trap handler, not in the
test code. Our emulator was treating ECALL as "halt, we are done", so
the trap handler never ran, and tohost never got written.

The fix: stop halting on ECALL. Make ECALL take a real trap.

A real trap means:
1. Save the current PC into mepc (so the handler could return later if
   it wanted to).
2. Set mcause to 11 (which is the spec code for "ECALL from machine
   mode").
3. Set PC to mtvec (which the boot wrapper already set to the trap
   handler's address back in step 4 of the boot wrapper).

Now the trap handler runs. It reads mcause, sees it was an ECALL,
reads gp, writes it to tohost. Our emulator's `store()` notices the
write to the tohost address, sets `halted = True` with reason
`tohost-pass`, and the runner reports success.

There was one subtlety. Our own sanity tests in `test_rv32i_emu.py`
also use ECALL, and they expect the emulator to halt cleanly on it.
We did not want to break them. So we made the new behavior a flag on
the emulator constructor: `trap_on_ecall`, defaulting to `False`. The
sanity tests use the default. The riscv-tests runner sets it to `True`.
Same emulator code, two modes, picked by the caller.

---

## The whole flow now, end to end, for one test

1. The runner opens an ELF, finds the address of the `tohost` symbol,
   and notes where in memory the program lives.
2. The runner builds an emulator with `trap_on_ecall=True` and the
   right `tohost_addr`.
3. The runner sets PC to the program's start address.
4. The boot wrapper runs. It executes about 60 instructions, most of
   them CSR writes that configure the trap vector, the entry point,
   and various status bits.
5. The boot wrapper executes MRET. Our emulator pops PC out of mepc,
   which now points at the test code.
6. The user test code runs. This is pure RV32I. The emulator runs
   each instruction, updating registers and memory.
7. At the end, the test code loads its result (`1` for pass) into `gp`
   and executes ECALL.
8. With `trap_on_ecall=True`, the emulator takes a trap: saves PC to
   mepc, sets mcause to 11, jumps to mtvec.
9. The trap handler runs. It stores `gp` to the `tohost` address.
10. The emulator's `store()` sees the address matches `tohost_addr`,
    sets `halted = True` with reason `tohost-pass`.
11. The runner reports the outcome.

---

## Why the actual RTL processor does NOT need any of this

The RTL processor we are building only implements pure RV32I. No CSRs,
no MRET, no traps. None of stages 2 through 5 will change that.

That is fine because we have two separate testing paths, and they do
not overlap:

| Path | What runs | Validates what | How it is checked |
|---|---|---|---|
| A: ISA correctness of the emulator | riscv-tests (wrapper + test code) | the emulator is right per the spec | the suite passing |
| B: RTL correctness | hand-written RV32I programs (no wrapper) | the RTL agrees with the emulator | trace from both must match |

The RTL never executes a CSR instruction or an ECALL because the
programs we write for RTL testing in stage 1.8 will be pure RV32I.
Our assembler in stage 1.6 will only emit RV32I. The CSR machinery we
added to the emulator is dead code on path B.

So the cost of stage 1.5 is bounded: about 50 lines of CSR / trap
handling in the emulator, which exists only to make the official test
suite work, and which the rest of the project will never extend unless
we decide we want to run the full suite through the RTL itself (which
is a stage 5 question, and a well-trodden one).

---

## What we did NOT do, on purpose

- The CSR layer is not spec-compliant for illegal access. The spec
  says writes to read-only CSRs trap; ours quietly overwrites them.
  This works because the boot wrapper does not write to read-only
  CSRs. A real OS would notice.
- The trap layer does not faithfully update mstatus (the "machine
  status" CSR that records previous privilege level, interrupt enable
  state, etc.). The riscv-tests handler does not check these bits, so
  this works. A real OS would notice.
- There is one skipped test: `rv32ui-p-ma_data`. It tests misaligned
  memory access (loading a 4-byte word from an address that is not a
  multiple of 4). The spec lets implementations either trap or handle
  it; we chose trap-and-halt. The official test expects the handler
  to fix up the access and resume; we deliberately do not have that.
  The skip is in `KNOWN_SKIPS` in the runner with a one-line reason.
  When we decide we want misaligned handling, we delete the entry and
  the test runs.

---

## Why we now trust the emulator

The official rv32ui suite tries roughly a hundred edge cases per
instruction. Sign extension, overflow, register zero, boundary
immediates, every branch direction, every shift amount, signed and
unsigned comparison. If the emulator passes all of that, the standard
corner cases that catch out a first emulator implementation are not
present.

This was the gate we needed before starting on the assembler and the
RTL. With it green, the emulator is a trustworthy oracle for every
test we run from here on.
