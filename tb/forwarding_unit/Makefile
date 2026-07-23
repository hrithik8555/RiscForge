# tb/forwarding_unit/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/forwarding_unit.sv

TOPLEVEL := forwarding_unit
MODULE   := test_forwarding_unit

include $(shell cocotb-config --makefiles)/Makefile.sim
