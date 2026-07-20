# tb/if_id_reg/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/if_id_reg.sv

TOPLEVEL := if_id_reg
MODULE   := test_if_id_reg

include $(shell cocotb-config --makefiles)/Makefile.sim
