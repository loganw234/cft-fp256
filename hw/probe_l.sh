#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Probe L's driver (docs/ROADMAP.md, "Revision 8", part 3). For a build
# host with Vivado - amd-arc-box, by the lead, never beside a link or a
# long run.
#
#   bash hw/probe_l.sh [synth|impl] [out_dir]
#
# Runs hw/probe_l.tcl over the U50's four rungs with R21's lanes built
# and not (EN_AUGADD 1 and 0): eight out-of-context syntheses of one
# pipe (impl also places and routes each). With BASE_RTL set to the rtl/
# of a tree from before R21 (5e033f6's), four more runs of that pipe,
# which must equal EN_AUGADD=0's figures: the claim that EN_AUGADD=0
# builds the pipe revision 7 shipped. Then a table, and the arithmetic
# from one pipe's delta to R21's LUTs a tile:
#
#   cft_krnl.sv builds ONE cft_lanes (u_lanes - cft_engine_stream and
#   cft_seq take OWN_LANES 0 there) at BEAT_BITS = 256, with EN_FP32 to
#   EN_FP256 at 1 - cft_krnl.sv's own parameters, which the U50 builds
#   leave at their defaults (hw/rebuild-2022.sh, CFT_GENERICS unset). So
#   a tile has BEAT_BITS/32 = 8 fp32 pipes, /64 = 4 fp64, /128 = 2 fp128
#   and /256 = 1 fp256 (cft_lanes.sv's LANES32 to LANES256), and
#
#     R21's LUTs a tile = 8 d(fp32) + 4 d(fp64) + 2 d(fp128) + 1 d(fp256)
#
#   with d(rung) one pipe's LUTs at EN_AUGADD=1 less at 0 (registers
#   likewise). The quad has four tiles. Question 9: the quad carries R21
#   only if this is about 2,000 LUTs a tile or fewer.
#
# Env: VIVADO_SETTINGS (default /data/Xilinx/Vivado/2022.2/settings64.sh),
#      FREQ (135), PART (xcu50-fsvh2104-2-e), JOBS (2 runs at once),
#      BASE_RTL (unset: no control), RUNGS (default "fp32 fp64 fp128
#      fp256"; e.g. RUNGS=fp256 with impl places and routes the widest
#      pipe alone - the tile figure needs all four, at synth).
set -u
stage=${1:-synth}
out=${2:-build_probe_l}
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
VIVADO_SETTINGS=${VIVADO_SETTINGS:-/data/Xilinx/Vivado/2022.2/settings64.sh}
FREQ=${FREQ:-135}
PART=${PART:-xcu50-fsvh2104-2-e}
JOBS=${JOBS:-2}
case "$stage" in synth|impl) ;; *) echo "stage is synth or impl, not $stage" >&2; exit 2;; esac

# The tree is asserted by content as well as by commit: a checkout whose
# SHA is right and whose files never updated is the failure rev-parse
# cannot see (CLAUDE.md, "Before believing a remote build").
grep -q "g_r21_decide" "$root/rtl/cft_fpfma_pipe.sv" || {
  echo "this tree's pipe has no R21 decision (g_r21_decide): not R21's tree" >&2; exit 1; }
if [ -n "${BASE_RTL:-}" ] && grep -q "g_r21_decide" "$BASE_RTL/cft_fpfma_pipe.sv"; then
  echo "BASE_RTL's pipe HAS R21's decision: not a tree from before R21" >&2; exit 1
fi
# shellcheck disable=SC1090
source "$VIVADO_SETTINGS" >/dev/null 2>&1
command -v vivado >/dev/null || { echo "no vivado after $VIVADO_SETTINGS" >&2; exit 1; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
echo "probe L start $(date '+%F %T') stage=$stage freq=${FREQ}MHz part=$PART jobs=$JOBS load $(cut -d' ' -f1-3 /proc/loadavg)"
echo "tree: $(git -C "$root" log --oneline -1 2>/dev/null | cut -c1-90); $(git -C "$root" status --porcelain 2>/dev/null | wc -l) files differ from it"
echo "tree's rtl: $(git -C "$root" rev-parse HEAD:rtl 2>/dev/null)${BASE_RTL:+; base rtl: $BASE_RTL}"

run_one() { # name exp_w man_w en_augadd rtl_dir
  local name=$1 e=$2 m=$3 en=$4 rtl=$5 t0 rc
  mkdir -p "$out/$name"
  t0=$(date +%s)
  ( cd "$out/$name" && nice -n 10 vivado -mode batch -nojournal -nolog \
      -source "$here/probe_l.tcl" \
      -tclargs "$e" "$m" "$en" "$FREQ" "$stage" "." "$PART" "$rtl" > run.log 2>&1 )
  rc=$?
  echo "$(date +%T) $name rc=$rc $(( $(date +%s) - t0 ))s"
}

RUNGS=${RUNGS:-fp32 fp64 fp128 fp256}
runs=()
for r in "8 23 fp32" "11 52 fp64" "15 112 fp128" "19 236 fp256"; do
  set -- $r
  case " $RUNGS " in *" $3 "*) ;; *) continue;; esac
  runs+=("$3-en0 $1 $2 0 $root/rtl" "$3-en1 $1 $2 1 $root/rtl")
  [ -n "${BASE_RTL:-}" ] && runs+=("$3-base $1 $2 none $BASE_RTL")
done
n=0
for job in "${runs[@]}"; do
  # shellcheck disable=SC2086
  run_one $job &
  n=$((n + 1))
  if [ "$n" -ge "$JOBS" ]; then wait -n; n=$((n - 1)); fi
done
wait

python3 - "$out" "$stage" <<'PY'
import re
import sys
from pathlib import Path

out, stage = Path(sys.argv[1]), sys.argv[2]
st = "routed" if stage == "impl" else "synth"
PIPES = {"fp32": 8, "fp64": 4, "fp128": 2, "fp256": 1}
UTIL = re.compile(r"PROBE_L_UTIL_(\w+): \|\s*(CLB LUTs|CLB Registers|CARRY8|DSPs)\*?\s*\|\s*(\d+)")
PATH = re.compile(r"PROBE_L_(WORST|S6|S10|S13)_(\w+): slack=(\S+) delay=(\S+) levels=(\S+) (\S+) -> (\S+)")

def read(name):
    f = out / name / "run.log"
    if not f.exists():
        return None
    r = {}
    for line in f.read_text(errors="replace").splitlines():
        m = UTIL.search(line)
        if m:
            r[(m.group(1), m.group(2))] = int(m.group(3))
        m = PATH.search(line)
        if m:
            r[(m.group(2), m.group(1))] = (float(m.group(3)), float(m.group(4)),
                                         m.group(5), m.group(6), m.group(7))
    return r

def num(x):
    return f"{x:,}" if isinstance(x, int) else "-"

print()
print(f"== probe L ({st}), one pipe a run: LUTs / registers / CARRY8 / DSPs; "
      f"the worst path's slack (data path delay, levels) overall and into S6, S10, S13")
rows = {}
for rung in PIPES:
    for v in ("en0", "en1", "base"):
        r = read(f"{rung}-{v}")
        if r is None:
            continue
        rows[(rung, v)] = r
        def pth(g):
            p = r.get((st, g))
            return f"{p[0]:+.3f} ({p[1]:.3f} ns, {p[2]})" if p else "-"
        print(f"  {rung:6s} {v:4s}  LUT {num(r.get((st, 'CLB LUTs'))):>8s}  "
              f"FF {num(r.get((st, 'CLB Registers'))):>7s}  "
              f"CARRY8 {num(r.get((st, 'CARRY8'))):>6s}  DSP {num(r.get((st, 'DSPs'))):>4s}  |  "
              f"worst {pth('WORST')}  S6 {pth('S6')}  S10 {pth('S10')}  S13 {pth('S13')}")

print()
print("== R21's cost: one pipe's EN_AUGADD=1 less EN_AUGADD=0, and a tile's "
      "(8 fp32 + 4 fp64 + 2 fp128 + 1 fp256 pipes)")
tl = tr = 0
whole = True
for rung, k in PIPES.items():
    a, b = rows.get((rung, "en1")), rows.get((rung, "en0"))
    if not a or not b or (st, "CLB LUTs") not in a or (st, "CLB LUTs") not in b:
        print(f"  {rung}: a run is missing"); whole = False; continue
    dl = a[(st, "CLB LUTs")] - b[(st, "CLB LUTs")]
    dr = a.get((st, "CLB Registers"), 0) - b.get((st, "CLB Registers"), 0)
    tl += k * dl; tr += k * dr
    def ds(g):
        pa, pb = a.get((st, g)), b.get((st, g))
        return f"{pa[0] - pb[0]:+.3f} ns" if pa and pb else "-"
    print(f"  {rung:6s} x{k}: +{dl:,} LUTs, +{dr:,} registers a pipe; "
          f"slack change: S6 {ds('S6')}, S10 {ds('S10')}, worst {ds('WORST')}")
if whole:
    print(f"  a tile: {tl:+,} LUTs, {tr:+,} registers; the quad (4 tiles): {4 * tl:+,} LUTs")
    print(f"  question 9: {'at or under' if tl <= 2000 else 'OVER'} about 2,000 LUTs a tile")

if any(v == "base" for _, v in rows):
    print()
    print("== the control: EN_AUGADD=0 against the tree before R21 (must be equal)")
    for rung in PIPES:
        a, b = rows.get((rung, "en0")), rows.get((rung, "base"))
        if a and b:
            same = all(a.get((st, u)) == b.get((st, u)) for u in ("CLB LUTs", "CLB Registers", "CARRY8", "DSPs"))
            print(f"  {rung}: {'EQUAL' if same else 'DIFFERENT'} "
                  f"(LUT {num(a.get((st, 'CLB LUTs')))} vs {num(b.get((st, 'CLB LUTs')))}, "
                  f"FF {num(a.get((st, 'CLB Registers')))} vs {num(b.get((st, 'CLB Registers')))})")

print()
print("Against the kernel: its worst out-of-context path is +1.576 ns at 135 MHz today")
print("(revision 7, an engine path); a pipe whose worst slack falls below that would")
print("become the kernel's worst. The per-stage reports are in <out>/<run>/paths_*.rpt.")
PY
echo "probe L end $(date '+%F %T') load $(cut -d' ' -f1-3 /proc/loadavg)"
