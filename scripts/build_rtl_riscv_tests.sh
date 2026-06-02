#!/usr/bin/env bash
# scripts/build_rtl_riscv_tests.sh
#
# Build the rv32ui test BODIES against our bare-metal, CSR-free
# environment (tools/rtl_tests/env/riscv_test.h + link.ld) so they run
# on the pure RV32I RTL. The test sources and test_macros.h come from
# the upstream riscv-tests clone unchanged; only the environment around
# them is ours.
#
# Output: one ELF per test in tools/rtl_tests/_bin/.
#
# I reuse the clone from build_riscv_tests.sh if it is already in
# .riscv_tests_work; otherwise I clone it. The march is plain rv32i:
# our environment uses no CSR and no fence.i, which is the whole point
# (it proves the core is exercised as pure RV32I).
#
# Required: riscv64-unknown-elf-gcc with rv32i/ilp32 multilib.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK_DIR="$REPO_ROOT/.riscv_tests_work"
ENV_DIR="$REPO_ROOT/tools/rtl_tests/env"
LINK_LD="$REPO_ROOT/tools/rtl_tests/link.ld"
OUT_DIR="$REPO_ROOT/tools/rtl_tests/_bin"
REMOTE="https://github.com/riscv-software-src/riscv-tests.git"
GCC="riscv64-unknown-elf-gcc"

# rv32ui tests to build for the RTL. fence_i and ma_data are excluded:
#   - fence_i needs self-modifying code; the stage-1 core is Harvard.
#   - ma_data needs misaligned-access handling; the core traps and halts.
# Both are covered on the emulator path instead.
TESTS=(
    simple
    add addi
    and andi
    auipc
    beq bge bgeu blt bltu bne
    jal jalr
    lb lbu lh lhu lw
    lui
    or ori
    sb sh sw
    sll slli
    slt slti sltiu sltu
    sra srai
    srl srli
    sub
    xor xori
)

# ---------- toolchain check
if ! command -v "$GCC" >/dev/null 2>&1; then
    cat >&2 <<EOF
error: $GCC not found.
  on Debian / Ubuntu, install with:
    sudo apt install -y gcc-riscv64-unknown-elf
EOF
    exit 1
fi

mkdir -p "$OUT_DIR" "$WORK_DIR"

# ---------- clone (or refresh) the upstream tests repository
cd "$WORK_DIR"
if [ ! -d riscv-tests/.git ]; then
    echo ">>> cloning $REMOTE"
    git clone --depth 1 "$REMOTE" riscv-tests
fi
cd riscv-tests
git submodule update --init --recursive >/dev/null 2>&1 || true

ISA_DIR="$PWD/isa"
MACROS_DIR="$ISA_DIR/macros/scalar"

# -march=rv32i: no zicsr, no zifencei. Our env needs neither.
CFLAGS=(-march=rv32i -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles)
INCLUDES=(-I"$ENV_DIR" -I"$MACROS_DIR")
LDFLAGS=(-T"$LINK_LD")

cd "$ISA_DIR"

# ---------- compile each test
rm -f "$OUT_DIR"/rv32ui-* 2>/dev/null || true
built=0
missing=0
failed=0
for t in "${TESTS[@]}"; do
    src="rv32ui/${t}.S"
    out="rv32ui-rtl-${t}"
    if [ ! -f "$src" ]; then
        echo "  skip  $t  (source $src not found upstream)"
        missing=$((missing + 1))
        continue
    fi
    if "$GCC" "${CFLAGS[@]}" "${INCLUDES[@]}" "${LDFLAGS[@]}" "$src" -o "$OUT_DIR/$out" 2>"$OUT_DIR/$out.log"; then
        built=$((built + 1))
        rm -f "$OUT_DIR/$out.log"
    else
        failed=$((failed + 1))
        echo "  FAIL  $t  (gcc returned nonzero; see $OUT_DIR/$out.log)" >&2
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "error: $failed tests failed to compile" >&2
    exit 1
fi

echo ">>> built $built rv32ui RTL binaries in $OUT_DIR (missing upstream: $missing)"
