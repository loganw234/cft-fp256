# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# cft-fp256 top-level targets. Anything that needs Vitis/Vivado states
# so; everything else runs anywhere with Python 3.10+ (simulation via
# the docker image, or natively where Icarus/Verilator exist).

PYTHON       ?= python3
SIM          ?= icarus
DOCKER_IMAGE ?= cft-sim

# hardware flow
PLATFORM ?= xilinx_u50_gen3x16_xdma_5_202210_1
PART     ?= xcu50-fsvh2104-2-e
TARGET   ?= hw        # hw | hw_emu
BUILD    := build

.PHONY: golden vectors sim docker-image sim-docker check-env emconfig xo xclbin clean help

help:
	@echo "golden       run the golden-model self-tests (pytest)"
	@echo "vectors      emit conformance vector sets to vectors/out/"
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
	$(PYTHON) -m pytest python/tests -q

vectors:
	$(PYTHON) vectors/gen_vectors.py --out vectors/out

sim:
	$(MAKE) -C tb sim SIM=$(SIM)

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
