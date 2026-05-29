"""Cocotb tests for instr_memory.

Pre-empting the byte-ordering bug from the plan: $readmemh reads one
32-bit word per hex line. The test hex file (sim_input.hex) has the
canonical sequence and we check each byte address returns the right
word.

Also checks that addresses past the loaded region return zero (because
the initial loop zero-fills before $readmemh runs).
"""

import cocotb
from cocotb.triggers import Timer

EXPECTED = [
    0xDEADBEEF,
    0xCAFEBABE,
    0x12345678,
    0x00000000,
    0xFFFFFFFF,
    0xAAAAAAAA,
    0x55555555,
    0x0000BEEF,
]


async def read_at(dut, addr):
    dut.addr.value = addr
    await Timer(1, units="ns")
    return int(dut.inst.value)


@cocotb.test()
async def words_load_in_order(dut):
    for i, expected in enumerate(EXPECTED):
        got = await read_at(dut, i * 4)
        assert got == expected, (
            f"addr 0x{i*4:x}: got 0x{got:08x}, expected 0x{expected:08x}"
        )


@cocotb.test()
async def low_bits_of_addr_ignored(dut):
    # addr=1, 2, 3 all alias to word 0 because the bottom two bits
    # are stripped in the index calculation. This is intentional;
    # misaligned-fetch trapping is the top-level's job.
    for misaligned in (1, 2, 3):
        got = await read_at(dut, misaligned)
        assert got == EXPECTED[0], f"addr {misaligned}: got 0x{got:08x}"


@cocotb.test()
async def past_loaded_region_reads_zero(dut):
    # We loaded 8 words; address 0x40 (word 16) was zero-initialized.
    got = await read_at(dut, 0x40)
    assert got == 0, f"unloaded word: got 0x{got:08x}"
