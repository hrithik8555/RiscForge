#!/usr/bin/env bash
# scripts/build_riscv_tests.sh
#
# Build the rv32ui test suite from the official riscv-tests repository
# into tools/refmodel/_riscv_tests_bin/.
#
# I tried `make rv32ui` first; the upstream Makefile reported "Nothing
# to be done" because its rv32ui aggregate target is gated on a
# compiler-feature probe and an XLEN default that did not match what I
# wanted. Rather than tease apart their build system, I invoke gcc
# directly with the same flags they document. Each test source is one
# .S file; each output is one statically linked ELF.
#
# Required: riscv64-unknown-elf-gcc with multilib for rv32i/ilp32.
# On Debian / Ubuntu:
#   sudo apt install -y gcc-riscv64-unknown-elf

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK_DIR="$REPO_ROOT/.riscv_tests_work"
OUT_DIR="$REPO_ROOT/tools/refmodel/_riscv_tests_bin"
REMOTE="https://github.com/riscv-software-src/riscv-tests.git"
GCC="riscv64-unknown-elf-gcc"

# The canonical rv32ui test set. ma_data is included; the runner
# reports it as skipped because we deliberately do not implement
# misaligned-access trap handling at stage 1.
TESTS=(
    simple
    add addi
    and andi
    auipc
    beq bge bgeu blt bltu bne
    fence_i
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
    ma_data
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
git submodule update --init --recursive >/dev/null

ISA_DIR="$PWD/isa"
ENV_DIR="$PWD/env/p"

if [ ! -f "$ENV_DIR/link.ld" ]; then
    echo "error: missing $ENV_DIR/link.ld; submodule init may have failed" >&2
    exit 1
fi

# Flags lifted from riscv-tests/isa/Makefile, plus zicsr and zifencei
# in the -march string. Modern GCC (binutils >= 2.38) no longer implies
# those from plain rv32i; they are standalone extensions you have to
# opt into. The riscv-tests trap-handler env code uses csr* instructions
# and fence.i, so without them the assembler rejects every test.
# -static + -nostdlib + -nostartfiles give a bare-metal ELF; the link.ld
# script lays it out at 0x80000000 with a tohost symbol in .data.
CFLAGS=(-march=rv32i_zicsr_zifencei -mabi=ilp32 -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles)
INCLUDES=(-I"$ENV_DIR" -I"$ISA_DIR/macros/scalar")
LDFLAGS=(-T"$ENV_DIR/link.ld")

cd "$ISA_DIR"

# ---------- compile each test
rm -f "$OUT_DIR"/rv32ui-* "$OUT_DIR"/.built 2>/dev/null || true
built=0
missing=0
failed=0
for t in "${TESTS[@]}"; do
    src="rv32ui/${t}.S"
    out="rv32ui-p-${t}"
    if [ ! -f "$src" ]; then
        echo "  skip  $t  (source $src not found upstream)"
        missing=$((missing + 1))
        continue
    fi
    if "$GCC" "${CFLAGS[@]}" "${INCLUDES[@]}" "${LDFLAGS[@]}" "$src" -o "$OUT_DIR/$out"; then
        built=$((built + 1))
    else
        failed=$((failed + 1))
        echo "  FAIL  $t  (gcc returned nonzero)" >&2
    fi
done

if [ "$failed" -gt 0 ]; then
    echo "error: $failed tests failed to compile" >&2
    exit 1
fi

echo ">>> built $built rv32ui binaries in $OUT_DIR (missing upstream: $missing)"
