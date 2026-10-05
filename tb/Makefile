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
#   make RD_LATENCY=125 WR_LATENCY=16 cycles
#                             give the memory model a round trip (see
#                             RD_LATENCY below); 0, the default,
#                             installs nothing at all

SIM ?= icarus

# The multi-cycle multiplier's pass budget for the *mc targets and
# `simmc` (rtl/cft_lanes.sv MUL_PASSES). 10 is the one-column-per-lane
# corner - fp64/fp128/fp256 at 3/5/10 passes; 2 halves every wide rung.
MC ?= 10

# THE MEMORY MODEL'S ROUND TRIP, in kernel-clock cycles.
#
# RD_LATENCY delays every R beat; WR_LATENCY delays every write
# response. Both reach the benches as CFT_RD_LATENCY / CFT_WR_LATENCY
# and are implemented in tb/busfx.py (section D) as a PIPELINED delay -
# one beat a cycle of bandwidth, `n` cycles of latency - not as a stall
# inside the slave, which would model a memory with one outstanding
# transaction and could never be beaten by a deeper read-ahead.
#
# ZERO IS THE DEFAULT AND INSTALLS NOTHING: no wrapper, no coroutine,
# no behaviour change. Every target below draws the stock cocotbext-axi
# slave, which answers in zero cycles, unless a latency is asked for.
#
# Why it exists: the card sustains 2.25 cycles a beat where `cycles`
# measured 1.250 on the same RTL, and a ceiling flat across format and
# size is a read path bounded by latency (docs/BENCHMARKS.md, "The
# engine, measured"). The knob is what lets that be reproduced, and
# what says whether a deeper read-ahead fixes it. Reads and writes are
# separate numbers because the two paths bound the engine for
# different reasons.
#
#   make RD_LATENCY=150 WR_LATENCY=150 cycles     the card's round trip
#   make RD_LATENCY=150 cycles                    reads only
#   make WR_LATENCY=150 cycles                    writes only
#   make RD_LATENCY=150 WR_LATENCY=150 krnl       the SAME bits, slowly
RD_LATENCY ?= 0
WR_LATENCY ?= 0
LATENCY_ENV = CFT_RD_LATENCY=$(RD_LATENCY) CFT_WR_LATENCY=$(WR_LATENCY)

# Matches the parent Makefile's default. The parent does not export
# it, and `make -C tb` is a fresh make.
PYTHON ?= python3

.PHONY: sim simmc fp32 fp64 fp128 fp256 mulfrac mulshare simpleops normseg normshare \
        normprobe seedop reduceacc reduce krnl krnlf128 krnlf64f128 krnlseq quarter faults \
        seq_core seq_coreu50 seq_coreu50mc seq_corestr ifetch seqprobe seqcycles seqcyclesstr seqtrace seqbp redprog krnlfused krnlplain cycles seqbanks \
        mulpass mulcycle mulcycle2 fp32mc fp64mc fp128mc fp256mc reducemc \
        krnlmc krnlseqmc quartermc faultsmc seq_coremc seqbanksmc cyclesmc clean

# The full suite, as one list. `sim` runs these and then READS WHAT THEY
# WROTE, which until 2026-09-12 it did not.
#
# cocotb cannot set an exit code - its own makefile says so at
# Makefile.inc:88 and checks only that a results file EXISTS. So a bench
# that ran, compared against the golden model, found a mismatch and
# recorded it in XML left `make sim` reporting success. Compile failures
# and hangs were always caught (cocotb deletes the results file before
# each run; the `timeout` wrappers handle the rest) - what escaped was
# the one outcome this project exists to detect.
SIM_BENCHES = fp32 fp64 fp128 fp256 mulfrac mulshare simpleops normseg \
              normshare seedop reduceacc reduce reducenowide krnl krnlf128 \
              krnlf64f128 \
              quarter faults redprog \
              seq_core seq_coreu50 seq_corestr krnlseq krnlseqnoaug \
              seqbanks mulpass mulcycle \
              mulcycle2

# A bench writes sim_build/<target name>/results.xml. One does not: the
# multi-cycle multiplier bench is parameterised by the pass budget, so
# its directory carries MC and the name cannot be derived. Override it
# here rather than keeping a second copy of the whole list - a list of
# twenty-one names maintained twice is how a bench ends up run but
# unchecked, which is the defect above wearing a typo.
SIM_DIR_mulcycle = mulcycle$(MC)
SIM_RESULTS = $(foreach b,$(SIM_BENCHES),\
    sim_build/$(if $(SIM_DIR_$(b)),$(SIM_DIR_$(b)),$(b))/results.xml)

# Every single bench target below ALSO runs the checker over its own
# results.xml, appended to its recipe (2026-09-15). cocotb cannot set an
# exit code, so until then `make <bench>` exited 0 with its tests
# failed - found by round 2's P4 with a deliberately broken pairing,
# while the suite-level line here was the only guard. The path in each
# `&& $(PYTHON) check_results.py` is the recipe's own COCOTB_RESULTS_FILE
# expression, so the two cannot name different files.
sim: $(SIM_BENCHES)
	@$(PYTHON) check_results.py $(SIM_RESULTS)

# The suite at the multi-cycle pass budget MC: every bench that holds a
# pipe, a lane array or the kernel, run against the same golden model
# with the multiplier iterated and the array paced - plus the two
# benches that exist only for this configuration. `sim` is the
# shipping default; this is the third-tier tile's own census.
simmc: fp32mc fp64mc fp128mc fp256mc mulpass mulcycle reducemc krnlmc \
       quartermc faultsmc seq_coremc krnlseqmc seqbanksmc \
       board boardkrnl boardseq boardseqode boardfp256

# The iterated chunk-column multiplier against exact integer
# arithmetic, at every column count the three wide rungs can build -
# the block itself, before any pipe wraps it.
mulpass:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulpass \
		MODULE=test_mulpass SIM_BUILD=sim_build/mulpass \
		COCOTB_RESULTS_FILE=sim_build/mulpass/results.xml \
		&& $(PYTHON) check_results.py sim_build/mulpass/results.xml

# Equivalence, tb_mulshare's shape: the lane array at MUL_PASSES=1
# beside the same array at MUL_PASSES=MC, fed identical beats at a
# random cadence, every result and flag word compared. The multi-cycle
# tile ships only if this is bit-identical. mulcycle2 is the other
# corner: every wide rung at two passes, the fp256 lane keeping five
# columns and a three-level in-pass tree.
mulcycle:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulcycle \
		MODULE=test_mulcycle SIM_BUILD=sim_build/mulcycle$(MC) \
		KRNL_PARAMS="-Ptb_mulcycle.MC=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/mulcycle$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/mulcycle$(MC)/results.xml

mulcycle2:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulcycle \
		MODULE=test_mulcycle SIM_BUILD=sim_build/mulcycle2 \
		KRNL_PARAMS="-Ptb_mulcycle.MC=2" \
		COCOTB_RESULTS_FILE=sim_build/mulcycle2/results.xml \
		&& $(PYTHON) check_results.py sim_build/mulcycle2/results.xml

# The pipe benches, paced by their wrappers at the budget: the same
# vectors, the same model, the pipe held between passes.
fp32mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp32 \
		MODULE=test_fpfma_fp32 SIM_BUILD=sim_build/fp32mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp32.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp32mc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp32mc$(MC)/results.xml

fp64mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp64 \
		MODULE=test_fpfma_fp64 SIM_BUILD=sim_build/fp64mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp64.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp64mc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp64mc$(MC)/results.xml

fp128mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp128 \
		MODULE=test_fpfma_fp128 SIM_BUILD=sim_build/fp128mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp128.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp128mc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp128mc$(MC)/results.xml

fp256mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp256 \
		MODULE=test_fpfma_fp256 SIM_BUILD=sim_build/fp256mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp256.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp256mc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp256mc$(MC)/results.xml

# The kernel-level benches at the budget: the engine's issue and
# collection, the reduction accumulator's schedule, the sequencer's
# held request and the fault paths, all through the paced array.
reducemc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_reduce SIM_BUILD=sim_build/reducemc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/reducemc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/reducemc$(MC)/results.xml

krnlmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/krnlmc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlmc$(MC)/results.xml

krnlseqmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq SIM_BUILD=sim_build/krnlseqmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/krnlseqmc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlseqmc$(MC)/results.xml

seqbanksmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq_banks SIM_BUILD=sim_build/seqbanksmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/seqbanksmc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/seqbanksmc$(MC)/results.xml

quartermc:
	CFT_GENERICS="$(OPEN_CAPS_GENERICS)" CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_krnl_quarter \
		MODULE=test_krnl_quarter SIM_BUILD=sim_build/quartermc$(MC) \
		KRNL_PARAMS="-Ptb_krnl_quarter.MUL_PASSES=$(MC) $(foreach g,$(OPEN_CAPS_GENERICS),-Ptb_krnl_quarter.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/quartermc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/quartermc$(MC)/results.xml

faultsmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_faults SIM_BUILD=sim_build/faultsmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/faultsmc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/faultsmc$(MC)/results.xml

seq_coremc:
	CFT_MUL_PASSES=$(MC) timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_coremc$(MC) \
		KRNL_PARAMS="-Pcft_seq.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/seq_coremc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/seq_coremc$(MC)/results.xml

# Cycles per beat per rung at the budget - the throughput the
# multi-cycle tile trades, measured on the RTL rather than derived.
cyclesmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_cycles SIM_BUILD=sim_build/cyclesmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/cyclesmc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/cyclesmc$(MC)/results.xml

# The fractured significand array, scored against exact integer
# arithmetic rather than against another implementation. No rounding
# and no format semantics are involved in a significand multiply, so
# the reference is unarguable.
mulfrac:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_mulfrac \
		MODULE=test_mulfrac SIM_BUILD=sim_build/mulfrac \
		COCOTB_RESULTS_FILE=sim_build/mulfrac/results.xml \
		&& $(PYTHON) check_results.py sim_build/mulfrac/results.xml

# Equivalence: the same four banks built twice, once with a private
# multiplier per lane and once with all lanes fed by one shared array,
# compared against each other rather than against the model. The fused
# array only ships if this is bit-identical.
mulshare:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulshare \
		MODULE=test_mulshare SIM_BUILD=sim_build/mulshare \
		COCOTB_RESULTS_FILE=sim_build/mulshare/results.xml \
		&& $(PYTHON) check_results.py sim_build/mulshare/results.xml

# Equivalence again, for the block that is not arithmetic: the flat
# case(op) form frozen at 7ab02b3 beside the eight-source form that
# replaced it, at all four rungs from one operand word. Area was the
# only thing meant to change, so the two must be bit-identical -
# results, flags and valid - or the rewrite does not ship.
simpleops:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_simpleops \
		MODULE=test_simpleops SIM_BUILD=sim_build/simpleops \
		COCOTB_RESULTS_FILE=sim_build/simpleops/results.xml \
		&& $(PYTHON) check_results.py sim_build/simpleops/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/normseg/results.xml \
		&& $(PYTHON) check_results.py sim_build/normseg/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/normshare/results.xml \
		&& $(PYTHON) check_results.py sim_build/normshare/results.xml

# Diagnostic probe for tb_normseg, not part of `make sim`. Drives one
# known vector into a quiet pipeline and prints both halves every
# cycle, which pins latency and mode handling together.
normprobe:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_normseg \
		MODULE=test_normseg_probe SIM_BUILD=sim_build/normprobe \
		COCOTB_RESULTS_FILE=sim_build/normprobe/results.xml \
		&& $(PYTHON) check_results.py sim_build/normprobe/results.xml

# The divide/sqrt seed opcodes against the golden model: every table
# index at both exponent parities across the exponent range, the recip
# subnormal-landing exponents, every special class, at all four rungs.
# The ROM itself is drift-locked to the model on the python side; this
# proves the RTL around it.
seedop:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_seedop \
		MODULE=test_seedop SIM_BUILD=sim_build/seedop \
		COCOTB_RESULTS_FILE=sim_build/seedop/results.xml \
		&& $(PYTHON) check_results.py sim_build/seedop/results.xml

# The streaming reduction accumulator against the model's tree. Every
# length from 1 to 40, because the shape varies with n and powers of two
# are the easy case.
reduceacc:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_reduce_acc \
		MODULE=test_reduce_acc SIM_BUILD=sim_build/reduceacc \
		COCOTB_RESULTS_FILE=sim_build/reduceacc/results.xml \
		&& $(PYTHON) check_results.py sim_build/reduceacc/results.xml

# CFT_SUM through the whole kernel: CSR, engine serializer, borrowed
# adder, single-beat writer. Sizes straddle the beat boundary at every
# precision, because the partial tail must stop at the real element
# count - the padding is zeros and adding +0.0 is not the identity.
reduce:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_reduce SIM_BUILD=sim_build/reduce \
		COCOTB_RESULTS_FILE=sim_build/reduce/results.xml \
		&& $(PYTHON) check_results.py sim_build/reduce/results.xml

# The same reductions with the beat-wide tree left out (round 2, P4):
# the serial path alone must give the same bits, and the bench's
# wide-beat counter must read zero at every shape - CFT_NO_WIDE=1 in the
# environment tells test_krnl_reduce.py to expect that. In the suite so
# that the control P4's "same bits, old cycle count" rests on is built
# every time rather than by a source edit (V4, 2026-09-15).
reducenowide:
	CFT_NO_WIDE=1 $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_reduce SIM_BUILD=sim_build/reducenowide \
		KRNL_PARAMS="-Pcft_krnl.EN_WIDE=0" \
		COCOTB_RESULTS_FILE=sim_build/reducenowide/results.xml \
		&& $(PYTHON) check_results.py sim_build/reducenowide/results.xml

fp32:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp32 \
		MODULE=test_fpfma_fp32 SIM_BUILD=sim_build/fp32 \
		COCOTB_RESULTS_FILE=sim_build/fp32/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp32/results.xml

fp64:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp64 \
		MODULE=test_fpfma_fp64 SIM_BUILD=sim_build/fp64 \
		COCOTB_RESULTS_FILE=sim_build/fp64/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp64/results.xml

fp128:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp128 \
		MODULE=test_fpfma_fp128 SIM_BUILD=sim_build/fp128 \
		COCOTB_RESULTS_FILE=sim_build/fp128/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp128/results.xml

fp256:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp256 \
		MODULE=test_fpfma_fp256 SIM_BUILD=sim_build/fp256 \
		COCOTB_RESULTS_FILE=sim_build/fp256/results.xml \
		&& $(PYTHON) check_results.py sim_build/fp256/results.xml

krnl:
	$(LATENCY_ENV) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnl \
		COCOTB_RESULTS_FILE=sim_build/krnl/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnl/results.xml

# The full-beat tile with binary256 left out - the kernel cft-rebound
# shipped (EN_FP256=0 at BEAT_BITS=256) - which no bench had proved
# before 2026-09-14: test_krnl issued fp256 unconditionally and
# test_krnl_quarter is trimmed the other way, to BEAT_BITS=64. Same
# bench, same golden model; CAPS[3:0] must read 0x7, the three rungs are
# bit-exact, precision 3 is refused with STATUS[3] and touches nothing.
#
# ONE list is the source of both the -P override the simulator builds
# with and the CFT_GENERICS the bench derives its expected CAPS from, in
# the NAME=VALUE spelling hw/package_kernel.tcl takes - so the build and
# the expectation cannot be told two different stories.
KRNLF128_GENERICS = EN_FP256=0
krnlf128:
	CFT_GENERICS="$(KRNLF128_GENERICS)" $(LATENCY_ENV) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlf128 \
		KRNL_PARAMS="$(foreach g,$(KRNLF128_GENERICS),-Pcft_krnl.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/krnlf128/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlf128/results.xml

# The tile cft-rebound actually wants (its docs/BITSTREAM.md, ask 5):
# binary64 and binary128 with NEITHER end, which fp32's generic made
# expressible on 2026-09-14. The bench's shape-specific cases are
# written in beats of the narrowest rung a build carries, so the same
# test_krnl proves this tile: CAPS[3:0] 0x6, both rungs bit-exact, and
# precisions 0 and 3 refused with STATUS[3].
KRNLF64F128_GENERICS = EN_FP32=0 EN_FP256=0
krnlf64f128:
	CFT_GENERICS="$(KRNLF64F128_GENERICS)" $(LATENCY_ENV) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlf64f128 \
		KRNL_PARAMS="$(foreach g,$(KRNLF64F128_GENERICS),-Pcft_krnl.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/krnlf64f128/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlf64f128/results.xml

# The orbit sequencer through the same kernel: program image staged in
# RAM, PROG_PTR and CNT_PTR written, MODE[15] set, deposits and counts
# scored against python/cft_golden/seq.py. It shares the A and D
# masters with the elementwise engine, so the bench runs BOTH - a
# sequencer run, an elementwise run, another sequencer run - because
# the mux is one claim and testing half of it proves nothing.
#
# Folded into `make sim` on 2026-09-01, the day the core went green -
# the aggregate stayed clear of both targets while the module was
# still being written, because an aggregate that is red for months
# trains people to ignore it, and folded in the moment that stopped
# being true.
krnlseq:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq SIM_BUILD=sim_build/krnlseq \
		COCOTB_RESULTS_FILE=sim_build/krnlseq/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlseq/results.xml

# The quad's tile (revision 8's R21; docs/ROADMAP.md, question 9): the
# kernel built WITHOUT R21, EN_AUGADD=0, which is how the quad ships -
# Logan's answer to question 9 was "Only if probe L finds it cheap", and
# probe L measured R21's lanes at +10,595 LUTs a tile. Every other target
# builds R21 (the default, the single's and the deep build's), so without
# this one `make sim` would never build the tile the quad carries.
# A named subset of test_krnl_seq, not the whole bench a second time
# (krnlseq is among the suite's longest):
#   krnl_augadd, flipped by CAPS2[11] clear: the plan's words for this
#     tile, an augadd and an augerr image each ending its block where
#     the code stands (an unknown code's HALT, as on revision 7), and an
#     R21-free program bit-exact;
#   krnl_lane_mask, the ordinary sequencer case: ordinary programs,
#     masked and not, on the array the engine shares;
#   krnl_lane_flags, so R23 is held on the quad's configuration too.
# A case added to test_krnl_seq reaches this target only when named here.
krnlseqnoaug:
	TESTCASE=krnl_augadd,krnl_lane_mask,krnl_lane_flags CFT_GENERICS="EN_AUGADD=0" $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq SIM_BUILD=sim_build/krnlseqnoaug \
		KRNL_PARAMS="-Pcft_krnl.EN_AUGADD=0" \
		COCOTB_RESULTS_FILE=sim_build/krnlseqnoaug/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlseqnoaug/results.xml

# The kernel with BOTH fused ladders on - the configuration the size
# campaign built, measured and equivalence-proved lane by lane, and
# then never ran through the full-kernel bench, because Alveo had room
# and, until 2026-09-14, hw/package_kernel.tcl stripped every user
# parameter, so no bitstream could carry it (CFT_GENERICS can set them
# since; no bitstream built with the fused ladders is recorded). This
# bench says the kernel, not just the ladder, is
# bit-exact with them on. They do NOT ship at 135 MHz - they cost more
# slack than their 16k LUT is worth (docs/ROADMAP.md) - so this target
# is what keeps the configuration honest for the slower clock and the
# smaller open-core part where it does pay.
krnlfused:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlfused \
		KRNL_PARAMS="-Pcft_krnl.FUSE_NORM=1 -Pcft_krnl.FUSE_ALIGN=1" \
		COCOTB_RESULTS_FILE=sim_build/krnlfused/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlfused/results.xml

# The kernel with both fused ladders pinned OFF by explicit parameter.
# That is also the shipping default as of 2026-09-01 (they cost more
# timing than the area is worth at 135 MHz - docs/ROADMAP.md), so this
# duplicates `krnl` today and is kept anyway: it pins the configuration
# rather than inheriting it, so a future default flip cannot silently
# take the off path out of coverage. Neither variant is in `sim`; the
# aggregate runs the default, and these two bracket it.
krnlplain:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlplain \
		KRNL_PARAMS="-Pcft_krnl.FUSE_NORM=0 -Pcft_krnl.FUSE_ALIGN=0" \
		COCOTB_RESULTS_FILE=sim_build/krnlplain/results.xml \
		&& $(PYTHON) check_results.py sim_build/krnlplain/results.xml

# THE OPEN-CORE BOARD CONFIGURATION, simulated as one thing.
#
# hw/mc_sweep.sh measured a tile for the Kintex-7 325T at MUL_PASSES=10
# with both fused ladders on - 98,929 LUT, 48.5% of the part, 9.698 ns
# of implied path against a 100 MHz ask (docs/ARCHITECTURE.md). Every
# one of those three parameters has been simulated, and never all three
# at once: `krnlfused` runs the ladders at one pass, the `*mc` targets
# run the passes with the ladders off. A configuration that is only
# ever covered a parameter at a time is a configuration nobody has run.
#
# These targets are that configuration, on the three benches that
# matter for a board with no host streaming a beat a cycle: the kernel
# through its CSR and AXI interfaces, the same kernel driven by the
# sequencer (which is how an open tile actually computes), and the
# fp256 bank itself. MC defaults to 10, so `make board` is the board.
# The capacities an open-core configuration keeps (revision 7,
# 2026-09-29). cft_krnl's SEQ_MAXD, SEQ_IMEM_D and SEQ_SCRATCH_D are
# parameters since that revision and default to the U50's - 1,024
# deposit slots, 32,768 instructions (since revision 8 a 4,096-word store
# and a 2^24 capacity), 2,048 scratch slots - while the
# board was measured through openXC7 with 64, 16,384 and 256
# (hw/openxc7, 2026-09-22) and the quarter tile has always had them. So
# both name them. ONE list, handed to the simulator as -P and to the
# bench as CFT_GENERICS, which is what test_krnl.py derives its
# expected CAPS and CAPS2 from - KRNLF128_GENERICS's rule, so the build
# and the expectation cannot be told two different stories.
# SEQ_STREAM_D joined at revision 8 (R8S): equal to SEQ_IMEM_D it builds
# no stream, and the open-core configurations keep streaming off - the
# kernel's default is the U50's 2^24, which with a 16,384-word store would
# stream past it. EN_AUGADD=0 joined with R21's decode (revision 8): the
# open-core configurations build without R21, as the quad does, where the
# kernel's default (the single's and the deep build's) builds it.
OPEN_CAPS_GENERICS = SEQ_MAXD=64 SEQ_IMEM_D=16384 SEQ_SCRATCH_D=256 SEQ_STREAM_D=16384 EN_AUGADD=0
BOARD_PARAMS = -Pcft_krnl.FUSE_NORM=1 -Pcft_krnl.FUSE_ALIGN=1                -Pcft_krnl.MUL_PASSES=$(MC) \
               $(foreach g,$(OPEN_CAPS_GENERICS),-Pcft_krnl.$(g))

board: boardkrnl boardseq boardseqode boardfp256

# The board targets' hang guard (2026-09-29). None had one, which is why
# boardseq could stall for 3.5 hours with nothing to show it (above).
# 7,200 s is about twice the longest board bench measured on amd-arc-box
# that day: boardseq's two cases took 3,371 s from its first build file
# to its results (SIM_JOBS=4, beside a bitstream build). By the same
# measure boardseqode took 1,234 s and boardkrnl 496 s, a little under
# their time under the guard, since Verilator writes its first file only
# after its front end has run; boardfp256 took 53 s. It catches a hang; it is not a budget. It also turns
# BOARDKRNL_SIM=icarus or BOARDSEQODE_SIM=icarus into a failure after
# two hours rather than a run of days. Raise BOARD_TIMEOUT for a
# deliberately long run.
BOARD_TIMEOUT ?= 7200

# boardkrnl runs under Verilator by default. Icarus evaluates this one
# configuration - the engine-driven kernel at ten passes with both
# ladders on - at about 2.5 ns of simulated time a second through the
# bench's 32-element operations and about 0.03 ns a second once its
# 1,104-element stream begins: on 2026-09-07 four hours of simulation
# reached 57 of the 71 operations, every one bit-exact, and the
# control on the tree before the leading-zero cone became a stage ran
# the same way, so the configuration is the cause, not a change - and
# the ingredient is the shared ladders themselves, not the pass
# budget: both ladders on at one pass, 1.7 ns a second; ten passes
# with neither, 1,636 (docs/VALIDATION.md, that evening). The
# bench has no finite Icarus duration worth quoting. Verilator runs
# it in 16 s after an eleven-minute compile - 44,920 ns simulated,
# both tests, the parameters applied, which they were NOT until that
# evening: cocotb.mk handed KRNL_PARAMS to Icarus only, and the first
# "Verilator passes it in seconds" was the default kernel wearing
# this target's name (docs/VALIDATION.md). A simulator cost, not a
# reason to skip the bench. BOARDKRNL_SIM=icarus puts it back.
BOARDKRNL_SIM ?= verilator
boardkrnl:
	CFT_GENERICS="$(OPEN_CAPS_GENERICS)" CFT_MUL_PASSES=$(MC) timeout $(BOARD_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(BOARDKRNL_SIM) TOPLEVEL=cft_krnl 		MODULE=test_krnl SIM_BUILD=sim_build/boardkrnl$(MC) 		KRNL_PARAMS="$(BOARD_PARAMS)" 		COCOTB_RESULTS_FILE=sim_build/boardkrnl$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/boardkrnl$(MC)/results.xml

# boardseq and boardseqode are one module, test_krnl_seq, split by case
# (2026-09-29). Revision 7 gave the module a third case,
# krnl_ode_programs (4b790b4): the three ODE programs through the whole
# kernel, about 684,000 cycles start to done at ten passes in krnlseqmc
# (unfused, at the U50's capacities). In the board configuration that
# is boardkrnl's Icarus cost again. On amd-arc-box boardseq passed its
# first two cases, then ran the third at 0.53 ns of simulated time a
# second. At that rate the 2.74 ms of simulated time the case took in
# krnlseqmc would need about 60 days, and every Icarus rate on record
# for this configuration means it cannot finish. The stage was stopped
# after 12,551 s, boardseq about 3 h 26 min in and 14 us into the case,
# so simmc never finished on the tree that added it (docs/VALIDATION.md,
# revision 7).
# So boardseq keeps the two cases it ran before revision 7, on the
# suite's simulator, and boardseqode runs the ODE case under Verilator
# by default, as boardkrnl does. BOARDSEQODE_SIM=icarus puts it back.
# Both case lists are pinned by name: a case added to test_krnl_seq
# reaches neither target until it is named in one of them.
boardseq:
	TESTCASE=krnl_sequencer,krnl_lane_mask CFT_GENERICS="$(OPEN_CAPS_GENERICS)" CFT_MUL_PASSES=$(MC) timeout $(BOARD_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl 		MODULE=test_krnl_seq SIM_BUILD=sim_build/boardseq$(MC) 		KRNL_PARAMS="$(BOARD_PARAMS)" 		COCOTB_RESULTS_FILE=sim_build/boardseq$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/boardseq$(MC)/results.xml

BOARDSEQODE_SIM ?= verilator
boardseqode:
	TESTCASE=krnl_ode_programs CFT_GENERICS="$(OPEN_CAPS_GENERICS)" CFT_MUL_PASSES=$(MC) timeout $(BOARD_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(BOARDSEQODE_SIM) TOPLEVEL=cft_krnl 		MODULE=test_krnl_seq SIM_BUILD=sim_build/boardseqode$(MC) 		KRNL_PARAMS="$(BOARD_PARAMS)" 		COCOTB_RESULTS_FILE=sim_build/boardseqode$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/boardseqode$(MC)/results.xml

boardfp256:
	CFT_MUL_PASSES=$(MC) timeout $(BOARD_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp256 		MODULE=test_fpfma_fp256 SIM_BUILD=sim_build/boardfp256$(MC) 		KRNL_PARAMS="-Ptb_fpfma_fp256.MUL_PASSES=$(MC)" 		COCOTB_RESULTS_FILE=sim_build/boardfp256$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/boardfp256$(MC)/results.xml

# Cycle counts on the RTL, which is where they actually live: hw_emu's
# wall clock measures the simulator, and its XRT timeline trace came
# back empty (2026-09-01). Prints cycles per 256-bit beat per rung
# and the rate those imply at the shipping clock, labelled a
# prediction. Out of `sim` on purpose - it measures rather than
# checks, and its numbers move for legitimate reasons.
#
# RD_LATENCY / WR_LATENCY above give the memory model a round trip; the
# build directory carries the pair so a sweep does not re-elaborate and
# does not overwrite the zero-latency run's results.
cycles:
	$(LATENCY_ENV) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_cycles \
		SIM_BUILD=sim_build/cycles$(RD_LATENCY)_$(WR_LATENCY) \
		COCOTB_RESULTS_FILE=sim_build/cycles$(RD_LATENCY)_$(WR_LATENCY)/results.xml \
		&& $(PYTHON) check_results.py sim_build/cycles$(RD_LATENCY)_$(WR_LATENCY)/results.xml

# The sequencer against BANKED memory: one private store per master,
# nothing mirrored. test_krnl_seq.py shares a single store on purpose
# and therefore cannot see a read that leaves through the wrong
# master - which is how the operand loads reached the card wired to
# m_axi_a alone and answered DECERR on every program. This target is
# the regression that would have caught it.
seqbanks:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq_banks SIM_BUILD=sim_build/seqbanks \
		COCOTB_RESULTS_FILE=sim_build/seqbanks/results.xml \
		&& $(PYTHON) check_results.py sim_build/seqbanks/results.xml

quarter:
	CFT_GENERICS="$(OPEN_CAPS_GENERICS)" $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_krnl_quarter \
		MODULE=test_krnl_quarter SIM_BUILD=sim_build/quarter \
		KRNL_PARAMS="$(foreach g,$(OPEN_CAPS_GENERICS),-Ptb_krnl_quarter.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/quarter/results.xml \
		&& $(PYTHON) check_results.py sim_build/quarter/results.xml

# What the kernel does when the memory system misbehaves: error
# responses on every master, and burst-length violations in both
# directions. The only bench where STATUS is ever non-zero, and the
# only one that asserts ap_done arrives at all - a design that latches
# a fault and then waits forever passes every other target here.
#
# Takes RD_LATENCY / WR_LATENCY too, and it is the bench where they buy
# the most: an abort has to unwind every read burst and write response
# still in the air, and at zero latency there is nothing in the air.
faults:
	$(LATENCY_ENV) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_faults SIM_BUILD=sim_build/faults \
		COCOTB_RESULTS_FILE=sim_build/faults/results.xml \
		&& $(PYTHON) check_results.py sim_build/faults/results.xml

# The orbit sequencer against the golden model, bit for bit: deposits
# including the +0 of the slots no lane reached, per-lane deposit
# counts, FLAGS, the overflow bit, and which programs get refused.
# docs/SEQUENCER.md is the design; python/cft_golden/seq.py is the
# definition of correct, and this scores the RTL against it the way
# the FMA core was scored against softfloat.py.
#
# In `make sim`. It was held out while cft_seq was being written - an
# aggregate target that goes red for a module still under construction
# trains people to ignore it - and folded in the day it went green,
# alongside krnlseq, because the suite is the place a finished module
# proves it stays finished.
#
# Wrapped in a timeout, and that is not belt and braces. Every timeout
# inside the bench is a SIMULATION-time timeout, and a simulation-time
# timeout cannot fire while the simulator is stuck inside one timestep
# - which is exactly how cft_seq failed the first time this target was
# pointed at it. Without this line the failure mode is a job that runs
# until someone notices; with it, it is a failure. Raise
# SEQ_TIMEOUT for a deliberately long run.
#
# It catches a hang; it is not a budget. 14,400 s since 2026-09-29, when
# revision 7's final tree (9fc9c0d, 63 cases) ran past the 4,800 this
# line then said. Under Icarus on amd-arc-box, in the runner's sim stage
# at SIM_JOBS=6 beside a bitstream build, seq_core was terminated at
# 4,800 s with no wrong answer (run 20260929-114401-9fc9c0d), while the
# same 63 cases at the U50's capacities took about 5,350 s (seq_coreu50
# in that stage, seq_coreu50mc at MC=10 beside it). seq_coremc, the same
# bench at MC=10, runs under this line too. 4,800 had been twice the
# 2,400 before it, set when seq_core took 1,923 s on the desktop at 48
# cases (run 20260929-080541-9ff114e). Measure it again when the suite
# grows, on the slower host and loaded as the runner loads it, and keep
# this at about twice the measurement.
SEQ_TIMEOUT ?= 14400

seq_core:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_core \
		COCOTB_RESULTS_FILE=sim_build/seq_core/results.xml \
		&& $(PYTHON) check_results.py sim_build/seq_core/results.xml

# The same bench with cft_seq built at the U50's capacities (revision 7,
# 2026-09-29): 1,024 deposit slots, 32,768 instructions, 2,048 scratch
# slots - and since revision 8 (R8S) a 4,096-word instruction store and a
# 2^24 capacity, so a program past 4,096 instructions streams here -
# rtl/cft_krnl.sv's SEQ_* defaults, which krnl_caps.py reads out
# of that file so the numbers exist once. seq_core runs cft_seq at its
# own defaults (64, 1,024, 256); this one is where every model run is at
# 2,048 slots, the top slot is 2,047, a non-strict index wraps at 2,048
# and a strict one is reported past it. One list: each word reaches the
# simulator as -Pcft_seq.<word> and the whole line reaches the bench as
# CFT_GENERICS. The scratch cases build their indices from SCRATCH_D and
# write near its top. Until P2's broadcast wipe (ffc4195) their blocks
# wiped up to 32,768 cycles here against 4,096 in seq_core, about three
# times seq_core's simulation under Verilator (275 s against 93), and so
# this target got a timeout of its own. Since then no block wipes more
# than 4,096 cycles at either depth, and the two take about the same
# time: 754 s here against 857 s for seq_core under Verilator on
# amd-arc-box (9fc9c0d, 2026-09-29). So the timeout is SEQ_TIMEOUT's,
# with its reason; the variable stays, so a run can raise one alone.
SEQ_U50_GENERICS = $(shell $(PYTHON) krnl_caps.py)
SEQ_U50_TIMEOUT ?= $(SEQ_TIMEOUT)
seq_coreu50:
	CFT_GENERICS="$(SEQ_U50_GENERICS)" timeout $(SEQ_U50_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_coreu50 \
		KRNL_PARAMS="$(foreach g,$(SEQ_U50_GENERICS),-Pcft_seq.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/seq_coreu50/results.xml \
		&& $(PYTHON) check_results.py sim_build/seq_coreu50/results.xml

# ...and the same machine on the multi-pass tile (MC=10 unless MC= says
# otherwise): the sub-arrays' read hold under issue_hold and the
# broadcast wipe where the issue pipe holds. Not in simmc, whose
# seq_coremc is the 256-slot machine; TESTCASE= runs a subset.
seq_coreu50mc:
	CFT_MUL_PASSES=$(MC) CFT_GENERICS="$(SEQ_U50_GENERICS)" timeout $(SEQ_U50_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_coreu50mc$(MC) \
		KRNL_PARAMS="-Pcft_seq.MUL_PASSES=$(MC) $(foreach g,$(SEQ_U50_GENERICS),-Pcft_seq.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/seq_coreu50mc$(MC)/results.xml \
		&& $(PYTHON) check_results.py sim_build/seq_coreu50mc$(MC)/results.xml

# The same bench through the instruction fetch (revision 8, R8S; S8's
# seq_corestr, docs/studies/R8S-streaming.md section 8): cft_seq with a
# 64-word store and a 2^16 capacity, so that nearly every program in
# tb/test_seq_core.py streams past the store, against SeqRam with a read
# latency of 0, 125 and 256 cycles taken a run at a time (CFT_SEQ_LAT; the
# card's round trip is bounded by 144 and the design is sized for 256). The
# cases that hold cycles pin latency 0, and their programs fit the store;
# the streaming cases hold their own. One list again: each word reaches the
# simulator as -Pcft_seq.<word> and the bench as CFT_GENERICS.
SEQ_STR_GENERICS = IMEM_D=64 STREAM_D=65536
SEQ_STR_LAT ?= 0,125,256
seq_corestr:
	CFT_SEQ_LAT=$(SEQ_STR_LAT) CFT_GENERICS="$(SEQ_STR_GENERICS)" timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_corestr \
		KRNL_PARAMS="$(foreach g,$(SEQ_STR_GENERICS),-Pcft_seq.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/seq_corestr/results.xml \
		&& $(PYTHON) check_results.py sim_build/seq_corestr/results.xml

# The instruction fetch unit alone (revision 8, R8S; rtl/cft_ifetch.sv),
# against SeqRam at read latencies 0, 125 and 256, driven by a model of
# cft_seq's fetch states and held to a reference walk of each program
# (tb/test_ifetch.py). A 64-word store - S8's seq_corestr store - so that
# nearly every program streams, and a 4,096-word capacity, so that a
# program of exactly the capacity is eight thousand cycles; the rest are
# the U50's. Each word reaches the simulator as -Pcft_ifetch.<word> and
# the line reaches the bench as CFT_GENERICS, as seq_coreu50's does.
# Not in SIM_BENCHES yet: joining it moves the bench count that CLAUDE.md,
# README.md, docs/VERIFICATION.md and verify/run.sh state, which is the
# lead's to restate (parcel RD1 handed it back, 2026-10-03).
IFETCH_GENERICS ?= STORE_D=64 STREAM_D=4096
ifetch:
	CFT_GENERICS="$(IFETCH_GENERICS)" timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_ifetch \
		MODULE=test_ifetch SIM_BUILD=sim_build/ifetch \
		KRNL_PARAMS="$(foreach g,$(IFETCH_GENERICS),-Pcft_ifetch.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/ifetch/results.xml \
		&& $(PYTHON) check_results.py sim_build/ifetch/results.xml

# Diagnostic probe for seq_core, not part of `make sim`. One trivial
# program into a quiet cft_seq, printing the state register, both bus
# channels and the WALL-CLOCK cost of every cycle - which is what
# separates "this simulator is slow" from "this simulator has stopped".
# Follows normprobe, one level down.
seqprobe:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_probe SIM_BUILD=sim_build/seqprobe \
		COCOTB_RESULTS_FILE=sim_build/seqprobe/results.xml \
		&& $(PYTHON) check_results.py sim_build/seqprobe/results.xml

# The other diagnostic, also not part of `make sim`: cycles per block and
# per lane for the programs the card was measured with on 2026-09-14
# (docs/VALIDATION.md, "the sequencer is the wall") - a halt, one
# deposit, four, twenty instructions - through the unit bench's harness.
# Run it before and after a change to cft_seq.sv; it is how the four
# per-lane changes of that afternoon were priced without a bitstream.
seqcycles:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=probe_seq_cycles SIM_BUILD=sim_build/seqcycles \
		COCOTB_RESULTS_FILE=sim_build/seqcycles/results.xml \
		&& $(PYTHON) check_results.py sim_build/seqcycles/results.xml

# ...and its streaming rows (revision 8, R8S): the same probe at
# seq_corestr's build, a 64-word store and a 2^16 capacity, where its
# streaming_costs prints what a program past the store costs at read
# latencies 0, 125 and 256; at seqcycles' build (no stream) it says so.
seqcyclesstr:
	CFT_GENERICS="$(SEQ_STR_GENERICS)" timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=probe_seq_cycles SIM_BUILD=sim_build/seqcyclesstr \
		KRNL_PARAMS="$(foreach g,$(SEQ_STR_GENERICS),-Pcft_seq.$(g))" \
		COCOTB_RESULTS_FILE=sim_build/seqcyclesstr/results.xml \
		&& $(PYTHON) check_results.py sim_build/seqcyclesstr/results.xml

# The other diagnostic: one program, every cycle of the issue pipe and
# the retire written to sim_build/trace/trace.txt (tb/probe_trace.py).
seqtrace:
	mkdir -p sim_build/trace
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=probe_trace SIM_BUILD=sim_build/trace \
		COCOTB_RESULTS_FILE=sim_build/trace/results.xml \
		&& $(PYTHON) check_results.py sim_build/trace/results.xml

# Two more, through the whole kernel (2026-09-14, the evening the first
# revision-5 image hung a compute unit): every program shape with READY
# withheld on every AXI channel at three duties (tb/probe_seq_bp.py),
# and an engine reduction followed by a program - the sequence that
# hung, because the lane array is shared (tb/probe_reduce_then_prog.py).
seqbp:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=probe_seq_bp SIM_BUILD=sim_build/seqbp \
		COCOTB_RESULTS_FILE=sim_build/seqbp/results.xml \
		&& $(PYTHON) check_results.py sim_build/seqbp/results.xml

redprog:
	timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=probe_reduce_then_prog SIM_BUILD=sim_build/redprog \
		COCOTB_RESULTS_FILE=sim_build/redprog/results.xml \
		&& $(PYTHON) check_results.py sim_build/redprog/results.xml

clean:
	rm -rf sim_build results.xml
