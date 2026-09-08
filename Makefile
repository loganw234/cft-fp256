# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# cft-fp256 top-level targets. Anything that needs Vitis/Vivado states
# so; everything else runs anywhere with Python 3.10+ (simulation via
# the docker image, or natively where Icarus/Verilator exist).

PYTHON       ?= python3
SIM          ?= icarus
DOCKER_IMAGE ?= cft-sim

# How many cores the two long software targets below may use. Four
# rather than all of them because this is usually a shared machine and
# a simulation or a Vitis build is beside them; verify/run.sh carries
# the same ceiling and the same reasoning, and neither can change a
# result - the generator's workers rebuild their own pools from the
# seed and write disjoint files, and pytest-xdist runs the same
# assertions in more processes.
VECTOR_JOBS  ?= 4
PYTEST_JOBS  ?= 4

# pytest-xdist only if this interpreter has it: `-n` is an unknown
# option to a bare pytest, and a gate that fails on the absence of an
# accelerator is worse than a slow one. Recursive (=, not :=) so the
# probe runs when `golden` runs and not on every `make help`.
XDIST_N       = $(shell $(PYTHON) -c "import xdist" >/dev/null 2>&1 && echo $(PYTEST_JOBS))

# hardware flow
PLATFORM ?= xilinx_u50_gen3x16_xdma_5_202210_1
PART     ?= xcu50-fsvh2104-2-e
TARGET   ?= hw        # hw | hw_emu
BUILD    := build

.PHONY: golden vectors sim docker-image sim-docker check-env emconfig xo xclbin \
        libcft libcft-test libcft-diff libcft-seq libcft-docker clean help \
        programs programs-check

help:
	@echo "golden       run the golden-model self-tests (pytest)"
	@echo "vectors      emit conformance vector sets to vectors/out/"
	@echo "libcft       build the C library (host/), no dependencies"
	@echo "libcft-test  contract tests + vector replay + the C/Python check"
	@echo "libcft-diff  libcft against the golden model, boundary-targeted"
	@echo "libcft-seq   the sequencer: C against the model, over fuzzed programs"
	@echo "libcft-docker  the same library tests on a second platform"
	@echo "programs     assemble programs/*.cfta into programs/out, write MANIFEST"
	@echo "programs-check  re-assemble with the model, compare, run every check"
	@echo "verify       the standardized verification run (verify/README.md)"
	@echo "sim          run cocotb RTL suite natively (needs iverilog)"
	@echo "docker-image build the simulation container"
	@echo "sim-docker   run the cocotb RTL suite inside the container"
	@echo "check-env    report Vitis/Vivado/XRT tool and card visibility"
	@echo "emconfig     emit build/emconfig.json for hw_emu runs"
	@echo "xo           package rtl/ into build/cft_krnl.xo (needs Vivado)"
	@echo "xclbin       link for $(PLATFORM), TARGET=$(TARGET) (needs Vitis)"

check-env:
	@echo "--- tools ---"
	@vivado -version 2>/dev/null | head -1 || echo "vivado: NOT FOUND (source Vitis settings64.sh)"
	@v++ --version 2>/dev/null | grep -m1 -i v++ || echo "v++: NOT FOUND (source Vitis settings64.sh)"
	@xbutil --version 2>/dev/null | head -2 || echo "xbutil: NOT FOUND (source /opt/xilinx/xrt/setup.sh)"
	@echo "--- platforms visible to v++ ---"
	@platforminfo -l 2>/dev/null | grep -i baseName || echo "platforminfo: none found (install the -dev platform package)"
	@echo "--- cards ---"
	@xbutil examine 2>/dev/null | sed -n '1,25p' || echo "no card visible (XRT not sourced, or no card in this box)"

emconfig: $(BUILD)/emconfig.json
$(BUILD)/emconfig.json:
	mkdir -p $(BUILD)
	emconfigutil --platform $(PLATFORM) --od $(BUILD)

golden:
	$(PYTHON) -m pytest python/tests -q $(if $(XDIST_N),-n $(XDIST_N),)

# Every format and every rounding attribute. Each attribute is its own
# deterministic contract, so a set covering only roundTiesToEven scores
# only the default and says nothing about the other four.
vectors:
	$(PYTHON) vectors/gen_vectors.py --out vectors/out \
		--formats fp32 fp64 fp128 fp256 \
		--rounding rne rtz rdn rup rmm \
		--directed 3000 --random 4000 --simple 200 \
		--jobs $(VECTOR_JOBS)

libcft:
	$(MAKE) -C host

libcft-test:
	$(MAKE) -C host test PYTHON=$(PYTHON)

libcft-seq:
	$(MAKE) -C host seqtest PYTHON=$(PYTHON)

libcft-diff:
	$(MAKE) -C host difftest PYTHON=$(PYTHON)

# ---- programs as files (docs/PROGRAMS.md, programs/README.md) --------
#
# `programs` assembles every .cfta with cft-asm into programs/out
# (gitignored) and writes programs/MANIFEST, which IS committed - so a
# change that moves a byte of an image is a line in a diff.
#
# `programs-check` re-assembles every source with the Python reference,
# compares byte for byte, disassembles both ways and re-assembles, then
# runs every row's own check. cft-collatz is a prerequisite because the
# Collatz kernel's check is that tool's own records; a check whose tool
# is missing says SKIP and why rather than passing quietly.
#
# The host build's variables ride down as command-line variables do, so
# on Windows the whole thing is one line:
#
#   PATH="/c/msys64/mingw64/bin:$PATH" make programs-check CC=gcc \
#        OS=Windows_NT PYTHON=python
PROGRAM_TOOLS = $(MAKE) -C host cft-asm$(HOSTEXE) positive-run$(HOSTEXE)
HOSTEXE = $(if $(filter Windows_NT,$(OS)),.exe,)

programs:
	$(PROGRAM_TOOLS)
	$(PYTHON) programs/build.py --asm host/cft-asm$(HOSTEXE)

# Deliberately NOT `programs-check: programs`. `programs` REWRITES the
# MANIFEST, so a check that ran it first would be comparing every hash
# against one it had just computed - a gate that cannot fail. check.py
# assembles the sources itself and compares against the COMMITTED
# manifest, which is the only version of that comparison worth having.
programs-check:
	$(PROGRAM_TOOLS)
	$(MAKE) -C host cft-collatz$(HOSTEXE)
	$(PYTHON) programs/check.py --asm host/cft-asm$(HOSTEXE) \
		--runner host/positive-run$(HOSTEXE) --tools-dir host

# The library's own tests on a second platform. The point is the
# checksum lines printed by the examples: identical here and on the
# developer's own machine, or "the same bits everywhere" is not true.
# Cleans either side because the objects it leaves are Linux ELF and
# would confuse the next native build.
libcft-docker:
	docker run --rm -v "$(CURDIR):/work" -w /work $(DOCKER_IMAGE) \
		sh -c "make -C host clean && make -C host test PYTHON=python3 && \
		       make -C host clean"

sim:
	$(MAKE) -C tb sim SIM=$(SIM)

# Open-toolchain portability gate: the whole kernel must elaborate in
# Yosys with no latches and no errors. This is what keeps the open-core
# port (docs/ROADMAP.md) a wrapper instead of a fork.
# -I rtl: cft_seedop includes its generated ROM by bare name.
# hierarchy -check: an unlisted module becomes a silent blackbox
# without it, and this list HAS drifted (cft_reduce_acc shipped
# unlisted, so one gate run "passed" while skipping it).
# cft_normseg's ports are packed vectors now, which is all 0.33 could not parse.
yosys-lint:
	yosys -q -p "read_verilog -sv -I rtl rtl/cft_fpfma.sv rtl/cft_fpfma_pipe.sv \
	  rtl/cft_opmux.sv rtl/cft_simpleops.sv rtl/cft_seedop.sv rtl/cft_csr.sv \
	  rtl/cft_fifo.sv rtl/cft_mulfrac.sv rtl/cft_mulpass.sv rtl/cft_reduce_acc.sv rtl/cft_normseg.sv \
	  rtl/cft_engine.sv rtl/cft_engine_stream.sv \
	  rtl/cft_lanes.sv rtl/cft_seq.sv rtl/cft_krnl.sv; \
	  hierarchy -check -top cft_krnl; proc; opt -fast; stat -top cft_krnl"

# The standardized verification run: every gate, one command,
# resumable and logged, census block at the end. verify/README.md.
verify:
	bash verify/run.sh

.PHONY: verify formal formal-image yosys-lint

# The formal property gate (formal/README.md): unbounded FIFO proof,
# complete seedop special-routing proof, and the simpleops-vs-frozen-
# ref equivalence miter, all inside the pinned cft-formal image. The
# recipe exits nonzero unless every proof passes AND the negative
# control is refuted.
formal: formal-image
	docker run --rm -v "$(CURDIR):/work" -w /work cft-formal \
	  ./formal/run.sh

formal-image:
	docker build -t cft-formal -f docker/Dockerfile.formal docker

docker-image:
	docker build -t $(DOCKER_IMAGE) -f docker/Dockerfile.sim .

sim-docker:
	docker run --rm -v "$(CURDIR):/work" -w /work/tb $(DOCKER_IMAGE) \
		make sim SIM=$(SIM)

xo: $(BUILD)/cft_krnl.xo
$(BUILD)/cft_krnl.xo: rtl/*.sv hw/kernel.xml hw/package_kernel.tcl
	vivado -mode batch -source hw/package_kernel.tcl -tclargs $(PART) $(BUILD)

xclbin: $(BUILD)/cft_$(TARGET).xclbin
$(BUILD)/cft_$(TARGET).xclbin: $(BUILD)/cft_krnl.xo hw/link.cfg
	v++ -l -t $(TARGET) --platform $(PLATFORM) --config hw/link.cfg \
		--save-temps --temp_dir $(BUILD)/_x -o $@ $(BUILD)/cft_krnl.xo

clean:
	rm -rf $(BUILD) tb/sim_build tb/results.xml
