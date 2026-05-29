# tb/imm_gen/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/imm_gen.sv

TOPLEVEL := imm_gen
MODULE   := test_imm_gen

include $(shell cocotb-config --makefiles)/Makefile.sim
