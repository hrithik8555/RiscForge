# tb/counter/Makefile
#
# Standard cocotb makefile pattern: this includes cocotb's makefiles.simulator,
# which knows how to invoke Verilator on the named source files and run the
# named Python test module.
#
# Run with `make` from this directory, or `make test-counter` from the repo
# root.

REPO_ROOT := $(abspath $(CURDIR)/../..)
RTL_DIR   := $(REPO_ROOT)/rtl

SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
EXTRA_ARGS += --trace --trace-structs

VERILOG_SOURCES := $(RTL_DIR)/counter.sv

TOPLEVEL := counter
MODULE   := test_counter

include $(shell cocotb-config --makefiles)/Makefile.sim
