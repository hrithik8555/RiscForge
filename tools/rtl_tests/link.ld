/* link.ld - bare-metal layout for the RTL riscv-tests.
 *
 * Everything starts at address 0 because the RTL's reset PC is 0 and
 * _start (in .text.init) must be the first instruction fetched. Code,
 * then read-only data, then data, then bss, all packed low so they fit
 * in the small instruction/data memories (the testbench loads the same
 * image into both).
 *
 * tohost is NOT placed here; the pass/fail code writes the MMIO address
 * 0x80001000 as a literal. begin_signature/end_signature come from the
 * test data macros and just bracket the test data region.
 */

OUTPUT_ARCH("riscv")
ENTRY(_start)

SECTIONS
{
  . = 0x00000000;

  .text.init : { *(.text.init) }

  . = ALIGN(4);
  .text : { *(.text) *(.text.*) }

  . = ALIGN(4);
  .rodata : { *(.rodata) *(.rodata.*) *(.srodata) *(.srodata.*) }

  . = ALIGN(4);
  .data : { *(.data) *(.data.*) *(.sdata) *(.sdata.*) }

  . = ALIGN(4);
  .bss : { *(.bss) *(.sbss) *(COMMON) }

  . = ALIGN(4);
  _end = .;
}
