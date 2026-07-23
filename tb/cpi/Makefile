# tb/cpi/Makefile
#
# CPI measurement for the pipeline. Runs the shared benchmark programs
# on top_pipeline, counts clock cycles to halt, and divides by the
# instruction count the emulator reports. Also lockstep-checks the
# final registers, so a wrong benchmark cannot quietly produce a
# meaningless CPI.

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
	$(RTL_DIR)/if_id_reg.sv \
	$(RTL_DIR)/id_ex_reg.sv \
	$(RTL_DIR)/ex_mem_reg.sv \
	$(RTL_DIR)/mem_wb_reg.sv \
	$(RTL_DIR)/forwarding_unit.sv \
	$(RTL_DIR)/hazard_unit.sv \
	$(RTL_DIR)/top_pipeline.sv

TOPLEVEL := top_pipeline
MODULE   := test_cpi

include $(shell cocotb-config --makefiles)/Makefile.sim
