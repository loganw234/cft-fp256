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

.PHONY: sim fp32 fp64 fp128 fp256 mulfrac mulshare simpleops normseg normshare \
        normprobe seedop reduceacc reduce krnl krnlseq quarter faults \
        seq_core seqprobe clean

sim: fp32 fp64 fp128 fp256 mulfrac mulshare simpleops normseg normshare \
     seedop reduceacc reduce krnl quarter faults

# The fractured significand array, scored against exact integer
# arithmetic rather than against another implementation. No rounding
# and no format semantics are involved in a significand multiply, so
# the reference is unarguable.
mulfrac:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_mulfrac \
		MODULE=test_mulfrac SIM_BUILD=sim_build/mulfrac \
		COCOTB_RESULTS_FILE=sim_build/mulfrac/results.xml

# Equivalence: the same four banks built twice, once with a private
# multiplier per lane and once with all lanes fed by one shared array,
# compared against each other rather than against the model. The fused
# array only ships if this is bit-identical.
mulshare:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulshare \
		MODULE=test_mulshare SIM_BUILD=sim_build/mulshare \
		COCOTB_RESULTS_FILE=sim_build/mulshare/results.xml

# Equivalence again, for the block that is not arithmetic: the flat
# case(op) form frozen at 7ab02b3 beside the eight-source form that
# replaced it, at all four rungs from one operand word. Area was the
# only thing meant to change, so the two must be bit-identical -
# results, flags and valid - or the rewrite does not ship.
simpleops:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_simpleops \
		MODULE=test_simpleops SIM_BUILD=sim_build/simpleops \
		COCOTB_RESULTS_FILE=sim_build/simpleops/results.xml

# One segmented normalise shifter against the fifteen private ones it
# would replace. Geometry says 2,706 bits of ladder collapse into 717;
# this says whether the bits come out the same. Area is a separate
# question and hw/synth_shiftcmp.tcl answers it - cft_mulfrac was
# correct and still did not pay.
#
# PINNED TO VERILATOR, and it is the only target that is. The DUT is
# 720 bits by twenty stages of multiplexer plus fifteen reference
# shifters beside it; Icarus spends over three hours on the sweep and
# Verilator does it in one second. It has its own variable rather than
# reading SIM, so `make sim` gets the fast simulator here and the
# default everywhere else; to check the two agree, run
# `make NORMSEG_SIM=icarus normseg` and bring a book.
NORMSEG_SIM ?= verilator

normseg:
	$(MAKE) -f cocotb.mk SIM=$(NORMSEG_SIM) TOPLEVEL=tb_normseg \
		MODULE=test_normseg SIM_BUILD=sim_build/normseg \
		COCOTB_RESULTS_FILE=sim_build/normseg/results.xml

# The same claim one level up: not "does the ladder shift correctly"
# (normseg answers that) but "is a LANE unchanged when its normalised
# significand comes from outside". Four banks built twice, EXT_NORM=0
# against EXT_NORM=1 fed by one cft_normseg, every result and flag word
# compared. Catches the plumbing - a cycle of skew, the two halves of
# the distance swapped, a lane reading its neighbour's slice - none of
# which tb_normseg can see, because it never goes through a pipe.
normshare:
	$(MAKE) -f cocotb.mk SIM=$(NORMSEG_SIM) TOPLEVEL=tb_normshare \
		MODULE=test_normshare SIM_BUILD=sim_build/normshare \
		COCOTB_RESULTS_FILE=sim_build/normshare/results.xml

# Diagnostic probe for tb_normseg, not part of `make sim`. Drives one
# known vector into a quiet pipeline and prints both halves every
# cycle, which pins latency and mode handling together.
normprobe:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_normseg \
		MODULE=test_normseg_probe SIM_BUILD=sim_build/normprobe \
		COCOTB_RESULTS_FILE=sim_build/normprobe/results.xml

# The divide/sqrt seed opcodes against the golden model: every table
# index at both exponent parities across the exponent range, the recip
# subnormal-landing exponents, every special class, at all four rungs.
# The ROM itself is drift-locked to the model on the python side; this
# proves the RTL around it.
seedop:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_seedop \
		MODULE=test_seedop SIM_BUILD=sim_build/seedop \
		COCOTB_RESULTS_FILE=sim_build/seedop/results.xml

# The streaming reduction accumulator against the model's tree. Every
# length from 1 to 40, because the shape varies with n and powers of two
# are the easy case.
reduceacc:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_reduce_acc \
		MODULE=test_reduce_acc SIM_BUILD=sim_build/reduceacc \
		COCOTB_RESULTS_FILE=sim_build/reduceacc/results.xml

# CFT_SUM through the whole kernel: CSR, engine serializer, borrowed
# adder, single-beat writer. Sizes straddle the beat boundary at every
# precision, because the partial tail must stop at the real element
# count - the padding is zeros and adding +0.0 is not the identity.
reduce:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_reduce SIM_BUILD=sim_build/reduce \
		COCOTB_RESULTS_FILE=sim_build/reduce/results.xml

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

# The orbit sequencer through the same kernel: program image staged in
# RAM, PROG_PTR and CNT_PTR written, MODE[15] set, deposits and counts
# scored against python/cft_golden/seq.py. It shares the A and D
# masters with the elementwise engine, so the bench runs BOTH - a
# sequencer run, an elementwise run, another sequencer run - because
# the mux is one claim and testing half of it proves nothing.
#
# Out of `make sim` for as long as seq_core is, and for its reason: an
# aggregate target that goes red for a module still being written
# trains people to ignore it. Both fold in on the same day.
krnlseq:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq SIM_BUILD=sim_build/krnlseq \
		COCOTB_RESULTS_FILE=sim_build/krnlseq/results.xml

quarter:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_krnl_quarter \
		MODULE=test_krnl_quarter SIM_BUILD=sim_build/quarter \
		COCOTB_RESULTS_FILE=sim_build/quarter/results.xml

# What the kernel does when the memory system misbehaves: error
# responses on every master, and burst-length violations in both
# directions. The only bench where STATUS is ever non-zero, and the
# only one that asserts ap_done arrives at all - a design that latches
# a fault and then waits forever passes every other target here.
faults:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_faults SIM_BUILD=sim_build/faults \
		COCOTB_RESULTS_FILE=sim_build/faults/results.xml

# The orbit sequencer against the golden model, bit for bit: deposits
# including the +0 of the slots no lane reached, per-lane deposit
# counts, FLAGS, the overflow bit, and which programs get refused.
# docs/SEQUENCER.md is the design; python/cft_golden/seq.py is the
# definition of correct, and this scores the RTL against it the way
# the FMA core was scored against softfloat.py.
#
# NOT in `make sim` yet, deliberately. cft_seq is being written, and an
# aggregate target that goes red for a module still under construction
# trains people to ignore it. Fold it in the day it is green - the
# suite is the place a finished module proves it stays finished.
#
# Wrapped in a timeout, and that is not belt and braces. Every timeout
# inside the bench is a SIMULATION-time timeout, and a simulation-time
# timeout cannot fire while the simulator is stuck inside one timestep
# - which is exactly how cft_seq failed the first time this target was
# pointed at it. Without this line the failure mode is a job that runs
# until someone notices; with it, it is a failure. Raise
# SEQ_TIMEOUT for a deliberately long run.
SEQ_TIMEOUT ?= 2400

seq_core:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_core \
		COCOTB_RESULTS_FILE=sim_build/seq_core/results.xml

# Diagnostic probe for seq_core, not part of `make sim`. One trivial
# program into a quiet cft_seq, printing the state register, both bus
# channels and the WALL-CLOCK cost of every cycle - which is what
# separates "this simulator is slow" from "this simulator has stopped".
# Follows normprobe, one level down.
seqprobe:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_probe SIM_BUILD=sim_build/seqprobe \
		COCOTB_RESULTS_FILE=sim_build/seqprobe/results.xml

clean:
	rm -rf sim_build results.xml
