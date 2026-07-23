# tb/hazard_unit/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/hazard_unit.sv

TOPLEVEL := hazard_unit
MODULE   := test_hazard_unit

include $(shell cocotb-config --makefiles)/Makefile.sim
