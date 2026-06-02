# tb/top/Makefile
#
# Single-cycle datapath end-to-end test. Before the sim runs we
# assemble smoke.s into smoke.hex with our own assembler, then load
# the same image into both instruction and data memory via plusargs.
# CUSTOM_SIM_DEPS is cocotb's documented hook for "build these before
# the sim runs" (see the $(COCOTB_RESULTS_FILE) rule in the verilator
# makefile).
#
# The smoke.hex rule and the clean override live AFTER the include on
# purpose: the include's `sim` target must stay the default goal, and
# whichever real target make reads first becomes that goal. Variables
# like CUSTOM_SIM_DEPS are fine to set before the include.

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl
ASM       := $(REPO_ROOT)/tools/assembler/assemble.py

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := \
	$(RTL_DIR)/pkg/riscv_pkg.sv \
	$(RTL_DIR)/pc_register.sv \
	$(RTL_DIR)/instr_memory.sv \
	$(RTL_DIR)/reg_file.sv \
	$(RTL_DIR)/alu.sv \
	$(RTL_DIR)/imm_gen.sv \
	$(RTL_DIR)/decoder.sv \
	$(RTL_DIR)/branch_unit.sv \
	$(RTL_DIR)/data_memory.sv \
	$(RTL_DIR)/top.sv

TOPLEVEL := top
MODULE   := test_top

# Same image into both memories.
PLUSARGS += +imem_hex=smoke.hex +dmem_hex=smoke.hex

# Assemble the program before the sim runs.
CUSTOM_SIM_DEPS += $(CURDIR)/smoke.hex

include $(shell cocotb-config --makefiles)/Makefile.sim

$(CURDIR)/smoke.hex: smoke.s $(ASM)
	python3 $(ASM) $< -o $@

clean::
	rm -f smoke.hex
