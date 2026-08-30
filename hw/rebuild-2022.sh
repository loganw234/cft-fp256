#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The era-toolchain pipeline: package the .xo and link hardware +
# hw_emu xclbins with Vitis 2022.2 (the release whose Vivado owns this
# platform's IP encryption keys - BRINGUP.md gate 3). Run from the
# repo root on any 2022.2 host: the amd-arc-box (/data/Xilinx) or the
# cft2204 WSL distro (/opt/Xilinx).
#
#   bash hw/rebuild-2022.sh            # package + link hw + hw_emu
#   TARGETS="hw" bash hw/rebuild-2022.sh   # subset
set -euo pipefail

PLATFORM=${PLATFORM:-xilinx_u50_gen3x16_xdma_5_202210_1}
PART=${PART:-xcu50-fsvh2104-2-e}
KERNEL_FREQ=${KERNEL_FREQ:-10000000}   # v0 behavioural core: ~10 MHz
TARGETS=${TARGETS:-"hw hw_emu"}
# Output directory. Parameterized so several links can run side by
# side on one host at different clocks (a frequency sweep); each
# needs its own .xo, temp dir and xclbin or they overwrite one
# another.
BUILD=${BUILD:-build}
# Link configuration and the CUs the clock constraint names.
# hw/link.cfg is one tile; hw/link_quad.cfg is four. Keep the two
# in step: every CU in the connectivity section must appear here,
# or the unnamed ones run at the platform default clock.
LINK_CFG=${LINK_CFG:-hw/link.cfg}
CLOCK_CUS=${CLOCK_CUS:-cft_krnl_1}

# locate Vitis 2022.2
for root in /data/Xilinx /opt/Xilinx /tools/Xilinx; do
  if [ -f "$root/Vitis/2022.2/settings64.sh" ]; then
    source "$root/Vitis/2022.2/settings64.sh"
    break
  fi
done
command -v v++ >/dev/null || { echo "ERROR: Vitis 2022.2 not found"; exit 1; }
echo "Using: $(command -v v++)"

# locate (or extract) the U50 dev platform
export PLATFORM_REPO_PATHS=${PLATFORM_REPO_PATHS:-$HOME/platforms-root/opt/xilinx/platforms}
if [ ! -d "$PLATFORM_REPO_PATHS/$PLATFORM" ]; then
  for deb in "$HOME"/Downloads/xilinx-u50-*dev*.deb \
             "$HOME"/installers/u50/xilinx-u50-*dev*.deb \
             /mnt/d/cft-vitis2022/xilinx-u50-*dev*.deb \
             /staging/xilinx-u50-*dev*.deb; do
    if [ -f "$deb" ]; then
      echo "Extracting dev platform from $deb"
      mkdir -p "$HOME/platforms-root"
      dpkg-deb -x "$deb" "$HOME/platforms-root"
      break
    fi
  done
fi
[ -d "$PLATFORM_REPO_PATHS/$PLATFORM" ] || { echo "ERROR: platform $PLATFORM not found under $PLATFORM_REPO_PATHS"; exit 1; }

mkdir -p "$BUILD"
# stale cross-era artifacts poison the flow: package_xo inspects an
# existing .xo before replacing it and refuses newer-version files
rm -f "$BUILD/cft_krnl.xo"
rm -rf "$BUILD/packaged_kernel" "$BUILD/tmp_kernel_pack"

echo "== package_xo (Vivado $(vivado -version | head -1))"
vivado -mode batch -nolog -nojournal -source hw/package_kernel.tcl \
    -tclargs "$PART" "$BUILD"

for t in $TARGETS; do
  echo "== v++ link -t $t"
  extra=""
  [ "$t" = "hw" ] && extra="--clock.freqHz ${KERNEL_FREQ}:${CLOCK_CUS}"
  v++ -l -t "$t" --platform "$PLATFORM" --config "$LINK_CFG" $extra \
      --save-temps --temp_dir "$BUILD/_x_$t" \
      -o "$BUILD/cft_$t.xclbin" "$BUILD/cft_krnl.xo"
done

if [[ "$TARGETS" == *hw_emu* ]]; then
  emconfigutil --platform "$PLATFORM" --od "$BUILD"
fi

echo "== done:"
ls -la "$BUILD"/*.xclbin 2>/dev/null
