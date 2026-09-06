#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# One cell of the multi-cycle tile's measurement matrix: the kernel at a
# pass budget (and optionally the fused ladders) on one part, out of
# context, through hw/impl_krnl_ooc.tcl.
#
#   bash hw/mc_sweep.sh <part> <freq_mhz> <MUL_PASSES> <ladders 0|1> <synth|impl> [out_root]
#
# Writes <out_root>/<part>_mp<N>_l<L>_<stage>/ with Vivado's log and the
# reports, and appends the QOR_* summary lines to <out_root>/summary.txt.
# Picks up Vivado from VIVADO_BIN, else the 2026.1 install on this host.
# Run one implementation at a time (a placement can take 25-30 GB).

set -u
part=$1; freq=$2; mp=$3; lad=$4; stage=$5
out_root=${6:-build_mc}

here=$(cd -- "$(dirname -- "$0")/.." && pwd)
vivado=${VIVADO_BIN:-"C:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat"}

tag="${part}_mp${mp}_l${lad}_${stage}"
dir="$out_root/$tag"
mkdir -p "$dir"
generics="MUL_PASSES=$mp"
if [ "$lad" = 1 ]; then generics="$generics FUSE_NORM=1 FUSE_ALIGN=1"; fi

echo "== $tag: $generics at $freq MHz"
t0=$(date +%s)
# The generics go through the environment, not -tclargs: cmd.exe (which
# vivado.bat is) splits arguments at `=`, and the value would be lost.
CFT_GENERICS="$generics" "$vivado" -mode batch -nolog -nojournal \
  -source "$here/hw/impl_krnl_ooc.tcl" \
  -tclargs "$freq" "$part" "$dir" "" "$stage" > "$dir/vivado.log" 2>&1
rc=$?
t1=$(date +%s)
{
  echo "== $tag ($generics, $freq MHz) rc=$rc $((t1 - t0)) s"
  grep -E '^QOR_' "$dir/vivado.log"
  grep -E '^(ERROR|CRITICAL WARNING)' "$dir/vivado.log" | head -5
} | tee -a "$out_root/summary.txt"
exit $rc
