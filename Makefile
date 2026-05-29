# RiscForge top-level Makefile.
#
# I am keeping this thin and explicit. The real work happens in per-module
# Makefiles under tb/<module>/Makefile, which use the standard cocotb
# makefile pattern. This top-level file dispatches to those by name and
# provides repo-wide actions like lint and clean.
#
# Every new module test gets one explicit target here. I tried an auto-
# discovery pattern rule first and it interacted oddly with .PHONY, so I
# am going with the boring explicit version. Three lines per module, no
# surprises.
#
# Targets:
#   make test            run every cocotb test
#   make test-counter    run a single module's test
#   make lint            verilator --lint-only over every RTL file
#   make wave            open the most recent VCD in GTKWave
#   make clean           nuke sim build artifacts
#   make docs            render Mermaid diagrams to SVG

# ---------- repo layout
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RTL_DIR   := $(REPO_ROOT)/rtl
TB_DIR    := $(REPO_ROOT)/tb
SIM_DIR   := $(REPO_ROOT)/sim
DOCS_DIR  := $(REPO_ROOT)/docs

# Every SystemVerilog file in rtl/. Used by lint.
RTL_FILES := $(shell find $(RTL_DIR) -name '*.sv' 2>/dev/null)

# Every module test we know about. Add a new line here when adding a module.
TB_TARGETS := test-counter

# ---------- top-level targets
.PHONY: all test encoding-check refmodel-test assembler-test riscv-tests riscv-tests-build lint wave clean docs help $(TB_TARGETS)

all: test

# Run every cocotb test. Gated on the encoding tables agreeing, the
# reference emulator self-test passing, and the assembler self-test
# passing first. The order matters: if riscv_pkg.sv and encoding.py
# disagree, nothing downstream is safe; if the emulator is broken,
# any RTL lockstep that follows is just two wrong things agreeing;
# and if the assembler is broken, the programs we write for the
# lockstep would not match what we wrote in the source.
test: encoding-check refmodel-test assembler-test $(TB_TARGETS)

# Diff the SystemVerilog encoding package against the Python mirror.
encoding-check:
	@echo ">>> encoding_check.py: rtl/pkg/riscv_pkg.sv vs tools/refmodel/encoding.py"
	@python3 scripts/encoding_check.py

# Shallow sanity tests for the Python RV32I emulator. The deep gate is
# `make riscv-tests` (the official rv32ui suite); this catches bugs that
# would make even that suite useless.
refmodel-test:
	@echo ">>> rv32i_emu sanity tests"
	@python3 tools/refmodel/test_rv32i_emu.py

# Assembler self-tests. Cross-checks include hand-traced B-type and
# J-type bit scrambles, LI/LA expansions, and a small Fibonacci
# program run through the (already-validated) emulator.
assembler-test:
	@echo ">>> assembler sanity tests"
	@python3 tools/assembler/test_assemble.py

# Deep validation: run the official riscv-tests rv32ui suite through
# the Python emulator. Requires the RISC-V GCC toolchain (the build
# script prints an install hint if it is missing) and the pyelftools
# Python package. Not wired into `make test` because the one-time build
# step takes ~2 minutes; CI runs it explicitly.
RISCV_TESTS_MARKER := tools/refmodel/_riscv_tests_bin/.built

riscv-tests: $(RISCV_TESTS_MARKER)
	@echo ">>> running riscv-tests rv32ui through the emulator"
	@python3 tools/refmodel/riscv_tests_runner.py

riscv-tests-build: $(RISCV_TESTS_MARKER)

$(RISCV_TESTS_MARKER):
	@echo ">>> building riscv-tests rv32ui (one-time, ~2 min)"
	@bash scripts/build_riscv_tests.sh
	@touch $(RISCV_TESTS_MARKER)

# Explicit per-module dispatchers. One per testbench directory under tb/.
test-counter:
	@echo ">>> running counter tests"
	$(MAKE) -C $(TB_DIR)/counter SIM=verilator

# Static lint over every RTL file. I want this clean from day one because
# Verilator warnings catch real bugs (latches, width mismatches, unused).
# No -Wno-fatal and no `|| true`: warnings ARE errors here, both locally
# and in CI. If a real false positive shows up later, I will silence it
# in the source with an explicit waiver comment, not by weakening lint.
lint:
	@echo ">>> verilator lint over $(words $(RTL_FILES)) files"
	@verilator --lint-only -Wall -I$(RTL_DIR)/pkg $(RTL_FILES)

# Open the most recent VCD. cocotb dumps under tb/<module>/sim_build/, so
# this search covers all of tb/ and sim/.
wave:
	@latest=$$(find $(TB_DIR) $(SIM_DIR) -name '*.vcd' -printf '%T@ %p\n' 2>/dev/null \
		| sort -n | tail -1 | cut -d' ' -f2); \
	if [ -z "$$latest" ]; then \
		echo "no VCDs found. run make test first."; \
	else \
		echo "opening $$latest"; gtkwave $$latest & \
	fi

# Render every Mermaid diagram to SVG. Needs mmdc (mermaid-cli):
#   npm install -g @mermaid-js/mermaid-cli
docs:
	@for src in $(DOCS_DIR)/diagrams/*.mmd; do \
		[ -f "$$src" ] || continue; \
		out=$${src%.mmd}.svg; \
		echo "rendering $$src -> $$out"; \
		mmdc -i "$$src" -o "$$out" -b transparent; \
	done

clean:
	@echo ">>> cleaning sim artifacts"
	rm -rf $(SIM_DIR)/* sim_build/ obj_dir/ results.xml
	find $(TB_DIR) -type d -name sim_build -exec rm -rf {} + 2>/dev/null || true
	find $(TB_DIR) -name results.xml -delete 2>/dev/null || true
	find $(REPO_ROOT) -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

help:
	@echo "RiscForge make targets:"
	@echo "  test               encoding-check, refmodel-test, then all cocotb tests"
	@echo "  test-counter       run tb/counter/Makefile"
	@echo "  encoding-check     diff riscv_pkg.sv against encoding.py"
	@echo "  refmodel-test      sanity tests for the Python RV32I emulator"
	@echo "  assembler-test     sanity tests for the RV32I assembler"
	@echo "  riscv-tests        run the official rv32ui suite through the emulator"
	@echo "  riscv-tests-build  build the rv32ui ELFs (needs riscv64-unknown-elf-gcc)"
	@echo "  lint               verilator --lint-only over rtl/"
	@echo "  wave               open most recent VCD in GTKWave"
	@echo "  docs               render Mermaid diagrams to SVG"
	@echo "  clean              remove sim artifacts and caches"
