# tb/riscv/Makefile
#
# Runs the official rv32ui test bodies (built against our bare-metal
# env by scripts/build_rtl_riscv_tests.sh) on the single-cycle RTL.
# Each ELF is loaded into the core's memory over VPI, run to halt, and
# checked for a tohost write of 1. No plusargs: the Python side does
# all the loading.

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

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
MODULE   := test_riscv

include $(shell cocotb-config --makefiles)/Makefile.sim
