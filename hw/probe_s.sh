#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Probe S's driver (docs/ROADMAP.md, "Revision 8", part 3; the plan's
# question 6). For a build host with Vivado - amd-arc-box, by the lead,
# never beside a link or a long run: an out-of-context place and route of
# the whole kernel wants the memory a link does.
#
#   bash hw/probe_s.sh [out_dir]
#
# Runs hw/probe_s.tcl on THIS tree's rtl/ - revision 8's seam, the abort
# and the instruction fetch with its hooks, and nothing else (round 2's
# order, so the fetch is read alone) - out of context at the U50's
# capacities (cft_krnl.sv's defaults: a 4,096-word store, a 2^24
# capacity), synthesis then place and route, at FREQ MHz. With BASE_RTL
# set to the rtl/ of the tree before the fetch's hooks (s6-c's 587c39f,
# the abort alone, whose IMEM is the 32K memory revision 7 shipped), the
# same script on that rtl, to BASE_STAGE (synth by default; impl for its
# routed u_seq list): the control the fetch's figures are read against.
# Then the PROBE_S_* lines, gathered into summary.txt.
#
# What it must show (the plan, part 3, probe S; R8S-streaming.md section 13,
# "Left for round 2 and for probe S"):
#   - the fetch path off u_seq's worst list (PROBE_S_SEQ_WORST: no line
#     marked FETCH near the top, where the base's IMEM cascade stood);
#   - the store without a cascade (PROBE_S_CASCADE: 0 of the fetch unit's
#     block RAMs in one). The store carries `cascade_height = 1` since
#     verifier-VC12's synthesis found Vivado chaining it (6 of the unit's 9
#     block RAMs, in cascades of four and two);
#   - from the hierarchical report, the instruction memory's real share of
#     the tile's block-RAM tiles (PROBE_S_HIER, against the base's);
#   - verifier-VRD1's two paths, the take -> rp path, and the redirect's
#     combinational path from pc through the 25-bit compares and mux into
#     the FIFO's clear (PROBE_S_PATH_*).
#
# Env: VIVADO_SETTINGS (default /data/Xilinx/Vivado/2022.2/settings64.sh),
#      FREQ (135), PART (xcu50-fsvh2104-2-e), BASE_RTL (unset: no
#      control), BASE_STAGE (synth).
set -u
out=${1:-build_probe_s}
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
VIVADO_SETTINGS=${VIVADO_SETTINGS:-/data/Xilinx/Vivado/2022.2/settings64.sh}
FREQ=${FREQ:-135}
PART=${PART:-xcu50-fsvh2104-2-e}
BASE_STAGE=${BASE_STAGE:-synth}

# The tree is asserted by content as well as by commit: a checkout whose
# SHA is right and whose files never updated is the failure rev-parse
# cannot see (CLAUDE.md, "Before believing a remote build"). This tree has
# the fetch's instance and the abort's state; it must not have R24's
# decode yet (QUIET), or it is not the tree probe S reads.
grep -q "cft_ifetch #" "$root/rtl/cft_seq.sv" || {
  echo "this tree's cft_seq has no cft_ifetch instance: not probe S's tree" >&2; exit 1; }
grep -q "S_ABORT" "$root/rtl/cft_seq.sv" || {
  echo "this tree's cft_seq has no S_ABORT: not probe S's tree" >&2; exit 1; }
if grep -q "C_QUIET" "$root/rtl/cft_seq.sv"; then
  echo "this tree's cft_seq decodes QUIET (R24): later than probe S's tree" >&2; exit 1
fi
grep -q "parameter int SEQ_STREAM_D  = 16777216" "$root/rtl/cft_krnl.sv" || {
  echo "cft_krnl's SEQ_STREAM_D is not the U50's 2^24 here" >&2; exit 1; }
if [ -n "${BASE_RTL:-}" ] && grep -q "cft_ifetch #" "$BASE_RTL/cft_seq.sv"; then
  echo "BASE_RTL's cft_seq instantiates the fetch: not a tree from before it" >&2; exit 1
fi
# The vendor script reads unset variables, so -u is off around it, as
# every other hw script sources its setup (verifier-VC12).
# shellcheck disable=SC1090
set +u; source "$VIVADO_SETTINGS" >/dev/null 2>&1; set -u
command -v vivado >/dev/null || { echo "no vivado after $VIVADO_SETTINGS" >&2; exit 1; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
echo "probe S start $(date '+%F %T') freq=${FREQ}MHz part=$PART load $(cut -d' ' -f1-3 /proc/loadavg) $(free -g | awk '/^Mem:/ {print $7}') GB available"
echo "tree: $(git -C "$root" log --oneline -1 2>/dev/null | cut -c1-90); $(git -C "$root" status --porcelain 2>/dev/null | wc -l) files differ from it"
echo "tree's rtl: $(git -C "$root" rev-parse HEAD:rtl 2>/dev/null)${BASE_RTL:+; base rtl: $BASE_RTL}"

run_one() { # name rtl_dir stage
  local name=$1 rtl=$2 st=$3 t0 rc
  mkdir -p "$out/$name"
  t0=$(date +%s)
  ( cd "$out/$name" && nice -n 10 vivado -mode batch -nojournal -nolog \
      -source "$here/probe_s.tcl" \
      -tclargs "$FREQ" "$PART" "." "$rtl" "$st" > run.log 2>&1 )
  rc=$?
  echo "$(date +%T) $name ($st) rc=$rc $(( ($(date +%s) - t0) / 60 )) min"
}

# One at a time: a place and route of the kernel wants 25-30 GB.
run_one fetch "$root/rtl" impl
[ -n "${BASE_RTL:-}" ] && run_one base "$BASE_RTL" "$BASE_STAGE"

{
  echo "== probe S at $(git -C "$root" rev-parse --short HEAD 2>/dev/null), ${FREQ} MHz, $PART"
  for name in fetch base; do
    [ -f "$out/$name/run.log" ] || continue
    echo "-- $name"
    grep -E "^PROBE_S" "$out/$name/run.log"
  done
} > "$out/summary.txt"
cat "$out/summary.txt"
echo "probe S done $(date '+%F %T')"
