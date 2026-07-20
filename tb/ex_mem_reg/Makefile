# tb/ex_mem_reg/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/ex_mem_reg.sv

TOPLEVEL := ex_mem_reg
MODULE   := test_ex_mem_reg

include $(shell cocotb-config --makefiles)/Makefile.sim
