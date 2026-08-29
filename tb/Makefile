# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
# Testbench dispatcher. Each target is one cocotb run with its own
# build directory. `make sim` is the full suite; it is what CI runs
# and what docker/Dockerfile.sim exists to run.
#
#   make sim                  everything (icarus)
#   make fp32 | fp64 | fp128 | fp256 | krnl   one bench
#   make SIM=verilator sim    alternative simulator
#   CFT_RANDOM=20000 make fp32   crank the vector count

SIM ?= icarus

.PHONY: sim fp32 fp64 fp128 fp256 krnl clean

sim: fp32 fp64 fp128 fp256 krnl

fp32:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp32 \
		MODULE=test_fpfma_fp32 SIM_BUILD=sim_build/fp32 \
		COCOTB_RESULTS_FILE=sim_build/fp32/results.xml

fp64:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp64 \
		MODULE=test_fpfma_fp64 SIM_BUILD=sim_build/fp64 \
		COCOTB_RESULTS_FILE=sim_build/fp64/results.xml

fp128:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp128 \
		MODULE=test_fpfma_fp128 SIM_BUILD=sim_build/fp128 \
		COCOTB_RESULTS_FILE=sim_build/fp128/results.xml

fp256:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp256 \
		MODULE=test_fpfma_fp256 SIM_BUILD=sim_build/fp256 \
		COCOTB_RESULTS_FILE=sim_build/fp256/results.xml

krnl:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnl \
		COCOTB_RESULTS_FILE=sim_build/krnl/results.xml

clean:
	rm -rf sim_build results.xml
