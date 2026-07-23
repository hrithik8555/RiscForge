# RiscForge performance

This is where the CPI numbers live. Right now it holds the stage-2
pipeline baseline; stage 3 adds a predictor column and stage 4 a cache
column, so the story reads left to right as the microarchitecture gets
smarter.

## How the numbers are measured

`make cpi` runs the shared benchmark programs (`tools/benchmarks/`) on
the pipeline and counts clock cycles from reset release to the cycle the
core reports halted. That window includes the pipeline fill and the
final ECALL, a small fixed overhead. Instructions are the dynamic
instruction count the reference emulator reports for the same program.
CPI is cycles divided by instructions.

Two things keep the numbers honest:

- Every benchmark is lockstepped against the emulator (final register
  file compared) before its CPI is reported. A program that diverges
  from the oracle produces no number, because a fast wrong answer is not
  a data point.
- The measurement definition is fixed and lives in code, so the
  stage-3 and stage-4 numbers are produced the same way and are directly
  comparable to this baseline.

## Stage 2 baseline (predict-not-taken)

The pipeline fetches the fall-through of every branch and pays a
one-cycle flush when the branch turns out taken. Ideal CPI for this
5-stage pipeline is 1.0; the overhead above that is branch flushes,
load-use and branch-operand stalls, and the one-time pipeline fill.

| program   | instructions | cycles | CPI   |
|-----------|-------------:|-------:|------:|
| fib       |          130 |    154 | 1.185 |
| gcd       |           50 |     68 | 1.360 |
| factorial |          247 |    327 | 1.324 |
| sort      |          338 |    435 | 1.287 |
| matvec    |          213 |    277 | 1.300 |
| overall   |          978 |   1261 | 1.289 |

The workloads are branch-heavy on purpose. `gcd` is a tight subtraction
loop, so nearly every iteration ends in a taken branch and it pays the
most flush penalty (worst CPI, 1.36). `fib` has a longer loop body per
branch, so the flushes are amortized over more useful work (best CPI,
1.19). This spread is exactly what a branch predictor should compress:
the stage-3 target is to move the taken-branch flushes close to zero on
these loops.
