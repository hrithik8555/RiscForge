# top.sv smoke program.
#
# Exercises a spread of instruction types end to end and halts on
# ECALL so the testbench sees a clean stop. The reference emulator is
# the oracle: the test runs this same image on the emulator and the
# RTL and compares the final register file. Expected (for a human
# reading along): a0=5 a1=3 a2=8 a3=2 a4=42 a5=8 t0=3 t1=3.
#
# Data address note: I store to 0x400, well past this program's code
# (about 0x44 bytes). The reference emulator uses ONE unified memory,
# so a store into the code region would overwrite an instruction and
# diverge from the RTL (which has separate imem/dmem). Keeping data
# clear of code is the rule for every hand-written lockstep program.

    li   a0, 5
    li   a1, 3
    add  a2, a0, a1       # 8
    sub  a3, a0, a1       # 2
    beq  a0, a1, skip     # not taken (5 != 3)
    addi a4, zero, 42     # reached: a4 = 42
skip:
    sw   a2, 0x400(zero)  # mem[0x400] = 8
    lw   a5, 0x400(zero)  # a5 = 8 (load path)
    li   t0, 0
    li   t1, 3
loop:
    addi t0, t0, 1        # count up
    blt  t0, t1, loop     # taken backward branch while t0 < 3
    ecall                 # halt
