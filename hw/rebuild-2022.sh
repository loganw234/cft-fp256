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

# The CUs the kernel clock constraint names. DERIVED from the link
# configuration rather than defaulted, because the failure mode of
# getting it wrong is expensive and silent until the end: a quad build
# whose constraint names only cft_krnl_1 leaves the other three at the
# platform default (300 MHz on this shell, roughly double the design's
# ceiling), and you learn that after a full ~1h45m implementation run.
# The nk= line already lists every CU, so there is one source of truth
# and it is the file that defines them.
#
# The two syntaxes are NOT the same, which is easy to miss because both
# use dots. nk= separates CU names with dots; --clock.freqHz separates
# entries with COMMAS and uses the dot inside an entry to separate the
# instance from its clock pin. Handing it the nk= list verbatim gets
#
#   ERROR: [CFGEN 83-2243] Malformed --clock.freqHz switch argument
#
# which is at least loud and immediate. Probed against cfgen directly:
# "f:cu1.ap_clk,cu2.ap_clk", "f:cu1,cu2", "f:cu1" and "f:cu1.ap_clk"
# are all accepted; only the dot-joined list is not. The explicit
# instance.pin form is used below because it is the documented shape
# and it stays unambiguous if a kernel ever carries a second clock.
if [ -z "${CLOCK_CUS:-}" ]; then
  CLOCK_CUS=$(sed -n 's/^[[:space:]]*nk=[^:]*:[0-9]*:\(.*\)$/\1/p' "$LINK_CFG" \
              | tr -d ' ' | head -1)
fi

# Validate, do not merely default. An EMPTY result would fall back
# harmlessly; a GARBLED one will not, because it is non-empty and so
# sails through any "is it set?" test straight into --clock.freqHz,
# naming a compute unit that does not exist.
#
# That is not hypothetical. This line shipped with its sed
# backreference mangled into a literal 0x01 byte, in the very commit
# that added it to stop a silent clock misconfiguration. It survived
# review because the corrupt value was non-empty and the character is
# invisible in a terminal. CU names are identifiers joined by dots, so
# anything else is a parse failure - and it stops the run here rather
# than an hour and three quarters from now.
case "$CLOCK_CUS" in
  "" | *[!A-Za-z0-9_.]* )
    echo "ERROR: no usable CU names from the nk= line of $LINK_CFG" >&2
    printf '       got: %s\n' "$(printf '%q' "$CLOCK_CUS")" >&2
    exit 1 ;;
esac

# nk= form -> --clock.freqHz form: split on dots, give each CU its
# clock pin, rejoin with commas.
CLOCK_ARG=$(printf '%s\n' "$CLOCK_CUS" | tr '.' '\n' | sed 's/$/.ap_clk/' \
            | paste -sd,)
echo "Clock constraint targets: $CLOCK_CUS"
echo "Clock constraint argument: ${KERNEL_FREQ}:${CLOCK_ARG}"

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

# Capture the provenance NOW, not when the build ends.
#
# A link takes about two hours, and the tree does not stop moving for
# it. Reading `git rev-parse HEAD` in the manifest step - which is
# where this used to happen - records whatever the checkout had become
# by then, which for a long build is routinely a different commit from
# the one that was packaged. The manifest would then name a commit the
# artifact was not built from, which is worse than naming none: the
# whole point of it is that a result can be traced to the exact RTL
# that produced it.
#
# Nearly done wrong on 2026-08-29, when a second build was about to
# sync the checkout forward while a quad link still had an hour to go.
SRC_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)
SRC_DESCRIBE=$(git describe --tags --always --dirty 2>/dev/null || echo unknown)
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  SRC_TREE="DIRTY - this artifact does not correspond to any commit"
else
  SRC_TREE="clean"
fi
SRC_STAMP=$(date -Iseconds)

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
  [ "$t" = "hw" ] && extra="--clock.freqHz ${KERNEL_FREQ}:${CLOCK_ARG}"
  v++ -l -t "$t" --platform "$PLATFORM" --config "$LINK_CFG" $extra \
      --save-temps --temp_dir "$BUILD/_x_$t" \
      -o "$BUILD/cft_$t.xclbin" "$BUILD/cft_krnl.xo"
done

# A manifest per built artifact. The determinism claim is only worth
# something if a result can be traced to the exact RTL that produced
# it, and a git tag cannot do that once the tag starts moving - which
# it will, because most of this design is verifiable without the card
# and the verified point advances daily.
#
# The xclbin's own hash is the key: hash the file you ran and look it
# up. That works even if the tree moved on, the tag moved on, or the
# file was copied to another machine under a different name. Recorded
# the way BRINGUP.md asks a bring-up to be recorded, so first light is
# replayable rather than remembered.
for t in $TARGETS; do
  xb="$BUILD/cft_$t.xclbin"
  [ -f "$xb" ] || continue
  man="$BUILD/cft_$t.manifest.txt"
  {
    echo "artifact:      $(basename "$xb")"
    echo "sha256:        $(sha256sum "$xb" | cut -d' ' -f1)"
    echo "bytes:         $(stat -c%s "$xb")"
    echo "built:         $(date -Iseconds)"
    echo "started:       $SRC_STAMP"
    echo "host:          $(hostname)"
    # Sampled before package_xo, not here - see the comment there.
    echo "commit:        $SRC_COMMIT"
    echo "describe:      $SRC_DESCRIBE"
    echo "tree:          $SRC_TREE"
    echo "target:        $t"
    echo "platform:      $PLATFORM"
    echo "part:          $PART"
    echo "link_cfg:      $LINK_CFG"
    echo "kernel_freq:   $KERNEL_FREQ"
    echo "clock_cus:     $CLOCK_CUS"
    echo "clock_arg:     ${KERNEL_FREQ}:${CLOCK_ARG}"
    echo "vivado:        $(vivado -version 2>/dev/null | head -1)"
    rpt="$BUILD/_x_$t/link/vivado/vpl/prj/prj.runs/impl_1/dr_timing_summary.rpt"
    if [ -f "$rpt" ]; then
      wns=$(grep -A6 'Design Timing Summary' "$rpt" | tail -1 | awk '{print $1}')
      echo "routed_wns_ns: ${wns:-unknown}"
    fi
  } > "$man"
  echo "== manifest: $man"
  cat "$man"
done

if [[ "$TARGETS" == *hw_emu* ]]; then
  emconfigutil --platform "$PLATFORM" --od "$BUILD"
fi

echo "== done:"
ls -la "$BUILD"/*.xclbin 2>/dev/null
