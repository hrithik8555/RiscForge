"""Benchmark programs for CPI measurement.

I keep the workloads in one place so every stage measures the same
thing: the pipeline baseline here (stage 2), then again with the
branch predictor (stage 3) and the I-cache (stage 4). Each program is
plain RV32I assembly for our own assembler, ends in ECALL, and leaves
a checkable result in a register so the measurement harness can also
lockstep it against the emulator (a wrong benchmark is worse than
none).

The `expect` dict per program lists register -> value that both the
emulator and the RTL must land on. Register numbers are x-numbers
(a0=10, a1=11, a3=13).

Branch-heaviness is the point: fib and gcd are tight loops, sort is a
doubly-nested loop with a data-dependent branch, matvec is nested
loops with a multiply subroutine. These are exactly the programs a
branch predictor should help.
"""

# A small unsigned multiply by repeated addition, appended where needed
# (RV32I has no MUL). Uses a0*a1 -> a2, clobbers a1.
_MUL = """
mul:
    li   a2, 0
mul_loop:
    beq  a1, x0, mul_done
    add  a2, a2, a0
    addi a1, a1, -1
    j    mul_loop
mul_done:
    ret
"""

FIB = """
    li   a0, 0
    li   a1, 1
    li   a2, 20
    li   a3, 0
loop:
    beq  a3, a2, done
    add  a4, a0, a1
    mv   a0, a1
    mv   a1, a4
    addi a3, a3, 1
    j    loop
done:
    ecall
"""

GCD = """
    li   a0, 1071
    li   a1, 462
gloop:
    beq  a0, a1, gdone
    blt  a0, a1, aless
    sub  a0, a0, a1
    j    gloop
aless:
    sub  a1, a1, a0
    j    gloop
gdone:
    ecall
"""

FACTORIAL = """
    li   s0, 8
    li   s1, 1
floop:
    beq  s0, x0, fdone
    mv   a0, s1
    mv   a1, s0
    call mul
    mv   s1, a2
    addi s0, s0, -1
    j    floop
fdone:
    mv   a0, s1
    ecall
""" + _MUL

# Bubble sort of 8 words, ascending. Leaves min in a0 and max in a1.
SORT = """
    la   s0, arr
    li   s1, 8
    addi s2, s1, -1
outer:
    beq  s2, x0, sorted
    li   s3, 0
    mv   s4, s2
inner:
    beq  s4, x0, next_pass
    slli s5, s3, 2
    add  s6, s0, s5
    lw   s7, 0(s6)
    lw   s8, 4(s6)
    bge  s8, s7, no_swap
    sw   s8, 0(s6)
    sw   s7, 4(s6)
no_swap:
    addi s3, s3, 1
    addi s4, s4, -1
    j    inner
next_pass:
    addi s2, s2, -1
    j    outer
sorted:
    la   s0, arr
    lw   a0, 0(s0)
    lw   a1, 28(s0)
    ecall
.data
arr:
.word 5, 2, 8, 1, 9, 3, 7, 4
"""

# 3x3 matrix times a 3-vector of ones, so result[i] is the row sum.
# M = [[1,2,3],[4,5,6],[7,8,9]] -> result = [6, 15, 24].
MATVEC = """
    la   s0, mat
    la   s2, res
    li   s3, 0
    li   s4, 3
irow:
    beq  s3, s4, mvdone
    la   s1, vec
    li   s5, 0
    li   s6, 0
icol:
    beq  s6, s4, storerow
    lw   a0, 0(s0)
    lw   a1, 0(s1)
    call mul
    add  s5, s5, a2
    addi s0, s0, 4
    addi s1, s1, 4
    addi s6, s6, 1
    j    icol
storerow:
    sw   s5, 0(s2)
    addi s2, s2, 4
    addi s3, s3, 1
    j    irow
mvdone:
    la   s2, res
    lw   a0, 0(s2)
    lw   a1, 4(s2)
    lw   a3, 8(s2)
    ecall
""" + _MUL + """
.data
mat:
.word 1, 2, 3, 4, 5, 6, 7, 8, 9
vec:
.word 1, 1, 1
res:
.word 0, 0, 0
"""

# name -> (source, {reg: expected_value})
BENCHMARKS = {
    "fib":       (FIB,       {10: 6765}),
    "gcd":       (GCD,       {10: 21}),
    "factorial": (FACTORIAL, {10: 40320}),
    "sort":      (SORT,      {10: 1, 11: 9}),
    "matvec":    (MATVEC,    {10: 6, 11: 15, 13: 24}),
}
