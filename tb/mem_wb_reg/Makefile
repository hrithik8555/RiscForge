# tb/mem_wb_reg/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/mem_wb_reg.sv

TOPLEVEL := mem_wb_reg
MODULE   := test_mem_wb_reg

include $(shell cocotb-config --makefiles)/Makefile.sim
