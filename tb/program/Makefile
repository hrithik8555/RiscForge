# tb/program/Makefile
#
# Integration tests for the whole single-cycle core. Unlike tb/top,
# these do NOT preload a hex via plusargs. Instead each test writes a
# freshly assembled program straight into the RTL's instruction and
# data memory arrays over VPI (Verilator is built with --public-flat-rw),
# resets, runs to halt, and locksteps the register file against the
# reference emulator. One sim run executes many programs with a reset
# between each.

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
MODULE   := test_programs

include $(shell cocotb-config --makefiles)/Makefile.sim
