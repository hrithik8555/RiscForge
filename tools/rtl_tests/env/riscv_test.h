// riscv_test.h - bare-metal RV32I test environment for the RiscForge RTL.
//
// The official riscv-tests ship with a machine-mode environment
// (env/p) whose boot and trap-handler code uses CSR instructions
// (csrw mtvec, csrr mcause, mret, ...) and signals pass/fail through
// an ECALL that the trap handler turns into a tohost write.
//
// Our RTL is pure RV32I by deliberate design: CSRs and traps live
// only in the Python emulator (the two-path testing decision). So the
// upstream ELFs cannot run on the hardware. This header is a drop-in
// replacement that keeps the exact same test BODIES (the rv32ui .S
// files and test_macros.h are unchanged) but provides a CSR-free
// environment:
//
//   - _start sits at address 0, which is the RTL's reset PC. It zeros
//     the TESTNUM register and sets a stack pointer, then falls into
//     the test body.
//   - pass / fail are signaled by writing the tohost MMIO word at
//     0x80001000 directly (no ECALL, no trap handler). The data_memory
//     decodes that address, pulses tohost_we, and the core halts. The
//     testbench reads the written value: 1 means pass, (n<<1)|1 means
//     failing subtest n, matching the riscv-tests convention.
//   - after writing tohost the code spins; on the RTL the tohost store
//     already halted the core, so the spin only matters on real silicon.
//
// What this does NOT support, on purpose:
//   - fence_i (self-modifying code): our stage-1 core is Harvard, so a
//     store cannot change the instruction stream. Skipped in the build.
//   - ma_data (misaligned access): the core traps and halts. Skipped.
//
// This means the RTL is exercised by the same instruction-level test
// vectors as the official suite, just wrapped in an environment a pure
// RV32I machine can actually boot.

#ifndef _ENV_RISCFORGE_RTL_TEST_H
#define _ENV_RISCFORGE_RTL_TEST_H

//-----------------------------------------------------------------------
// Architecture-flavor markers. The rv32ui .S files redefine RVTEST_RV64U
// to RVTEST_RV32U and then invoke it; we only need these to expand to
// nothing.
//-----------------------------------------------------------------------
#define RVTEST_RV32U
#define RVTEST_RV32UF
#define RVTEST_RV64U
#define RVTEST_RV64UF
#define RVTEST_RV32M
#define RVTEST_RV64M

// TESTNUM holds the current subtest index; test_macros.h writes it
// before each case and branches to `fail` on a mismatch.
#define TESTNUM gp

// tohost MMIO address. Must match data_memory's TOHOST_ADDR default.
#define RISCFORGE_TOHOST 0x80001000

//-----------------------------------------------------------------------
// Code section. _start at address 0 = the RTL reset vector.
//-----------------------------------------------------------------------
#define RVTEST_CODE_BEGIN                                               \
        .section .text.init;                                            \
        .globl _start;                                                  \
_start:                                                                 \
        li TESTNUM, 0;                                                  \
        li sp, 0x00003f00;   /* stack well above code/data, inside dmem */

#define RVTEST_CODE_END

//-----------------------------------------------------------------------
// Pass / fail. Write the tohost word and spin. The store triggers the
// RTL halt; the spin is only reached on real hardware.
//-----------------------------------------------------------------------
#define RVTEST_PASS                                                     \
        li a0, 1;                                                       \
        li a1, RISCFORGE_TOHOST;                                        \
        sw a0, 0(a1);                                                   \
1:      j 1b;

#define RVTEST_FAIL                                                     \
        sll TESTNUM, TESTNUM, 1;                                        \
        ori TESTNUM, TESTNUM, 1;                                        \
        mv  a0, TESTNUM;                                                \
        li  a1, RISCFORGE_TOHOST;                                       \
        sw  a0, 0(a1);                                                  \
1:      j 1b;

//-----------------------------------------------------------------------
// Data section. We keep the begin/end signature labels the test data
// macros expect, but we do NOT define a tohost symbol in memory: the
// pass/fail code writes the MMIO address as a literal instead.
//-----------------------------------------------------------------------
#define RVTEST_DATA_BEGIN                                               \
        .align 4; .global begin_signature; begin_signature:

#define RVTEST_DATA_END                                                 \
        .align 4; .global end_signature; end_signature:

#endif
