# tb/instr_memory/Makefile

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs -I$(RTL_DIR)

VERILOG_SOURCES := $(RTL_DIR)/pkg/riscv_pkg.sv $(RTL_DIR)/instr_memory.sv

# Pass the hex file path to the simulator via plusargs. The test
# generates this file (sim_input.hex) at runtime before calling
# the cocotb step.
PLUSARGS += +imem_hex=sim_input.hex

TOPLEVEL := instr_memory
MODULE   := test_instr_memory

include $(shell cocotb-config --makefiles)/Makefile.sim
