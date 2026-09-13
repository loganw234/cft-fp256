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
        normprobe seedop reduceacc reduce krnl krnlseq quarter faults \
        seq_core seqprobe krnlfused krnlplain cycles seqbanks \
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
              normshare seedop reduceacc reduce krnl quarter faults \
              seq_core krnlseq seqbanks mulpass mulcycle mulcycle2

# A bench writes sim_build/<target name>/results.xml. One does not: the
# multi-cycle multiplier bench is parameterised by the pass budget, so
# its directory carries MC and the name cannot be derived. Override it
# here rather than keeping a second copy of the whole list - a list of
# twenty-one names maintained twice is how a bench ends up run but
# unchecked, which is the defect above wearing a typo.
SIM_DIR_mulcycle = mulcycle$(MC)
SIM_RESULTS = $(foreach b,$(SIM_BENCHES),\
    sim_build/$(if $(SIM_DIR_$(b)),$(SIM_DIR_$(b)),$(b))/results.xml)

sim: $(SIM_BENCHES)
	@$(PYTHON) check_results.py $(SIM_RESULTS)

# The suite at the multi-cycle pass budget MC: every bench that holds a
# pipe, a lane array or the kernel, run against the same golden model
# with the multiplier iterated and the array paced - plus the two
# benches that exist only for this configuration. `sim` is the
# shipping default; this is the third-tier tile's own census.
simmc: fp32mc fp64mc fp128mc fp256mc mulpass mulcycle reducemc krnlmc \
       quartermc faultsmc seq_coremc krnlseqmc seqbanksmc \
       board boardkrnl boardseq boardfp256

# The iterated chunk-column multiplier against exact integer
# arithmetic, at every column count the three wide rungs can build -
# the block itself, before any pipe wraps it.
mulpass:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulpass \
		MODULE=test_mulpass SIM_BUILD=sim_build/mulpass \
		COCOTB_RESULTS_FILE=sim_build/mulpass/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/mulcycle$(MC)/results.xml

mulcycle2:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_mulcycle \
		MODULE=test_mulcycle SIM_BUILD=sim_build/mulcycle2 \
		KRNL_PARAMS="-Ptb_mulcycle.MC=2" \
		COCOTB_RESULTS_FILE=sim_build/mulcycle2/results.xml

# The pipe benches, paced by their wrappers at the budget: the same
# vectors, the same model, the pipe held between passes.
fp32mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp32 \
		MODULE=test_fpfma_fp32 SIM_BUILD=sim_build/fp32mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp32.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp32mc$(MC)/results.xml

fp64mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp64 \
		MODULE=test_fpfma_fp64 SIM_BUILD=sim_build/fp64mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp64.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp64mc$(MC)/results.xml

fp128mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp128 \
		MODULE=test_fpfma_fp128 SIM_BUILD=sim_build/fp128mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp128.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp128mc$(MC)/results.xml

fp256mc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp256 \
		MODULE=test_fpfma_fp256 SIM_BUILD=sim_build/fp256mc$(MC) \
		KRNL_PARAMS="-Ptb_fpfma_fp256.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/fp256mc$(MC)/results.xml

# The kernel-level benches at the budget: the engine's issue and
# collection, the reduction accumulator's schedule, the sequencer's
# held request and the fault paths, all through the paced array.
reducemc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_reduce SIM_BUILD=sim_build/reducemc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/reducemc$(MC)/results.xml

krnlmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/krnlmc$(MC)/results.xml

krnlseqmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq SIM_BUILD=sim_build/krnlseqmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/krnlseqmc$(MC)/results.xml

seqbanksmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq_banks SIM_BUILD=sim_build/seqbanksmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/seqbanksmc$(MC)/results.xml

quartermc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_krnl_quarter \
		MODULE=test_krnl_quarter SIM_BUILD=sim_build/quartermc$(MC) \
		KRNL_PARAMS="-Ptb_krnl_quarter.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/quartermc$(MC)/results.xml

faultsmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_faults SIM_BUILD=sim_build/faultsmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/faultsmc$(MC)/results.xml

seq_coremc:
	CFT_MUL_PASSES=$(MC) timeout $(SEQ_TIMEOUT) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_seq \
		MODULE=test_seq_core SIM_BUILD=sim_build/seq_coremc$(MC) \
		KRNL_PARAMS="-Pcft_seq.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/seq_coremc$(MC)/results.xml

# Cycles per beat per rung at the budget - the throughput the
# multi-cycle tile trades, measured on the RTL rather than derived.
cyclesmc:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_cycles SIM_BUILD=sim_build/cyclesmc$(MC) \
		KRNL_PARAMS="-Pcft_krnl.MUL_PASSES=$(MC)" \
		COCOTB_RESULTS_FILE=sim_build/cyclesmc$(MC)/results.xml

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
	$(LATENCY_ENV) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnl \
		COCOTB_RESULTS_FILE=sim_build/krnl/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/krnlseq/results.xml

# The kernel with BOTH fused ladders on - the configuration the size
# campaign built, measured and equivalence-proved lane by lane, and
# then never ran through the full-kernel bench, because Alveo had room
# and hw/package_kernel.tcl strips user parameters so no bitstream
# ever carried it. This bench says the kernel, not just the ladder, is
# bit-exact with them on. They do NOT ship at 135 MHz - they cost more
# slack than their 16k LUT is worth (docs/ROADMAP.md) - so this target
# is what keeps the configuration honest for the slower clock and the
# smaller open-core part where it does pay.
krnlfused:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl SIM_BUILD=sim_build/krnlfused \
		KRNL_PARAMS="-Pcft_krnl.FUSE_NORM=1 -Pcft_krnl.FUSE_ALIGN=1" \
		COCOTB_RESULTS_FILE=sim_build/krnlfused/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/krnlplain/results.xml

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
BOARD_PARAMS = -Pcft_krnl.FUSE_NORM=1 -Pcft_krnl.FUSE_ALIGN=1                -Pcft_krnl.MUL_PASSES=$(MC)

board: boardkrnl boardseq boardfp256

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
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(BOARDKRNL_SIM) TOPLEVEL=cft_krnl 		MODULE=test_krnl SIM_BUILD=sim_build/boardkrnl$(MC) 		KRNL_PARAMS="$(BOARD_PARAMS)" 		COCOTB_RESULTS_FILE=sim_build/boardkrnl$(MC)/results.xml

boardseq:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl 		MODULE=test_krnl_seq SIM_BUILD=sim_build/boardseq$(MC) 		KRNL_PARAMS="$(BOARD_PARAMS)" 		COCOTB_RESULTS_FILE=sim_build/boardseq$(MC)/results.xml

boardfp256:
	CFT_MUL_PASSES=$(MC) $(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_fpfma_fp256 		MODULE=test_fpfma_fp256 SIM_BUILD=sim_build/boardfp256$(MC) 		KRNL_PARAMS="-Ptb_fpfma_fp256.MUL_PASSES=$(MC)" 		COCOTB_RESULTS_FILE=sim_build/boardfp256$(MC)/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/cycles$(RD_LATENCY)_$(WR_LATENCY)/results.xml

# The sequencer against BANKED memory: one private store per master,
# nothing mirrored. test_krnl_seq.py shares a single store on purpose
# and therefore cannot see a read that leaves through the wrong
# master - which is how the operand loads reached the card wired to
# m_axi_a alone and answered DECERR on every program. This target is
# the regression that would have caught it.
seqbanks:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=cft_krnl \
		MODULE=test_krnl_seq_banks SIM_BUILD=sim_build/seqbanks \
		COCOTB_RESULTS_FILE=sim_build/seqbanks/results.xml

quarter:
	$(MAKE) -f cocotb.mk SIM=$(SIM) TOPLEVEL=tb_krnl_quarter \
		MODULE=test_krnl_quarter SIM_BUILD=sim_build/quarter \
		COCOTB_RESULTS_FILE=sim_build/quarter/results.xml

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
		COCOTB_RESULTS_FILE=sim_build/faults/results.xml

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
