# tb/branch_unit/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/branch_unit.sv

TOPLEVEL := branch_unit
MODULE   := test_branch_unit

include $(shell cocotb-config --makefiles)/Makefile.sim
