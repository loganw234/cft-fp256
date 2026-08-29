#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Frequency sweep: link the same kernel at several clocks at once and
# report which ones close, with the routed WNS for each.
#
#   bash hw/sweep_freq.sh 115 145 175
#
# Why a sweep and not a calculation: Vitis implementation is
# constraint-driven. It optimises until the clock you asked for is met
# and then stops, so a routed WNS tells you the design met its target,
# not how much faster it could have gone (docs/BRINGUP.md gate 3). The
# only way to find the ceiling is to ask for it and see.
#
# Each point is an independent full link in its own BUILD directory
# (~12 GB peak, ~1h45m), so run no more concurrent points than
# RAM/12 GB allows - the memory is the limit, not the core count. A
# point that closes leaves a usable xclbin behind, so a sweep is also
# how you acquire faster images.
#
# Results land in <outdir>/sweep_summary.txt as they finish.

set -u
cd "$(dirname "$0")/.."

FREQS=${*:-"115 145 175"}
OUT=${CFT_SWEEP_OUT:-sweep}
mkdir -p "$OUT"
SUMMARY="$OUT/sweep_summary.txt"
: > "$SUMMARY"

echo "sweep: $FREQS MHz  ->  $OUT/" | tee -a "$SUMMARY"

for f in $FREQS; do
  d="$OUT/f${f}"
  mkdir -p "$d"
  (
    hz=$((f * 1000000))
    if BUILD="$d" TARGETS=hw KERNEL_FREQ="$hz" \
         bash hw/rebuild-2022.sh > "$d/build.log" 2>&1; then
      rpt="$d/_x_hw/link/vivado/vpl/prj/prj.runs/impl_1/dr_timing_summary.rpt"
      wns=$(grep -A6 'Design Timing Summary' "$rpt" 2>/dev/null \
            | tail -1 | awk '{print $1}')
      printf '%4s MHz  CLOSED   WNS %s ns   %s\n' \
             "$f" "${wns:-?}" "$d/cft_hw.xclbin" >> "$SUMMARY"
    else
      # v++ fails the link on a timing violation, so a failed build at
      # a plausible clock is almost always "did not close" - but check
      # the log before assuming it, since a tool or disk error looks
      # the same from out here.
      why=$(grep -m1 -E 'Timing constraints are not met|^ERROR' \
            "$d/build.log" 2>/dev/null | cut -c1-90)
      printf '%4s MHz  FAILED   %s\n' "$f" "${why:-see $d/build.log}" \
             >> "$SUMMARY"
    fi
  ) &
  sleep 45   # stagger: keep the memory spikes from landing together
done

wait
echo "== sweep complete =="
sort -n "$SUMMARY"
