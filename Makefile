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
.PHONY: all test lint wave clean docs help $(TB_TARGETS)

all: test

# Run every cocotb test.
test: $(TB_TARGETS)

# Explicit per-module dispatchers. One per testbench directory under tb/.
test-counter:
	@echo ">>> running counter tests"
	$(MAKE) -C $(TB_DIR)/counter SIM=verilator

# Static lint over every RTL file. I want this clean from day one because
# Verilator warnings catch real bugs (latches, width mismatches, unused).
lint:
	@echo ">>> verilator lint over $(words $(RTL_FILES)) files"
	@verilator --lint-only -Wall -Wno-fatal \
		-I$(RTL_DIR)/pkg $(RTL_FILES) || true

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
	@echo "  test             run all cocotb tests"
	@echo "  test-counter     run tb/counter/Makefile"
	@echo "  lint             verilator --lint-only over rtl/"
	@echo "  wave             open most recent VCD in GTKWave"
	@echo "  docs             render Mermaid diagrams to SVG"
	@echo "  clean            remove sim artifacts and caches"
