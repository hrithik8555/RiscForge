# tb/riscv_pipeline/Makefile
#
# Runs the official rv32ui test bodies on the 5-stage pipeline
# (top_pipeline.sv), the same way tb/riscv runs them on the single-
# cycle core. This is the strong end-to-end check that the pipeline,
# with all its forwarding, stalls, and branch-in-ID flush, is
# genuinely RISC-V conformant.

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
MODULE   := test_riscv_pipeline

include $(shell cocotb-config --makefiles)/Makefile.sim
