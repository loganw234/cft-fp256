#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Fan the native-oracle soak (host/tools/divsqrt_soak.c) across idle
# cores. Meant for a build host whose big cores are otherwise waiting
# on a Vivado route: every job runs under nice -19, so the soak takes
# whatever the implementation runs leave on the table.
#
#   bash hw/run-soak.sh                 # the full campaign
#   QUICK=1 bash hw/run-soak.sh        # minutes-long smoke of the same shape
#   JOBS=24 RANDN=100000000 bash hw/run-soak.sh   # tune width and depth
#
#   CFT_SOAK_ARTIFACT=~/cardday-rev4/cft_hw_single.xclbin \
#       QUICK=1 bash hw/run-soak.sh    # ... against a TILE instead
#
# THE ARTIFACT VARIANT IS THE POINT OF THIS SCRIPT ON A CARD DAY. The oracle
# does not change - it is the host CPU's own IEEE hardware either way - so the
# same billions of cases that have only ever scored the software backend can
# score silicon. Until 2026-09-13 both soak tools opened `cft_open(NULL, ...)`
# and nothing else, so the strongest independent oracle in the project had
# never been pointed at a tile: the card's entire coverage was device-test's
# matrix, measured at 2,660 checks in 0.348 s on a U50.
#
# Each job prints which backend it opened, first line, because a card soak and
# a software soak are otherwise indistinguishable in a log and one of them is
# evidence about hardware. Expect it to be far slower than software per case -
# every case crosses the bus - so use QUICK or a reduced RANDN the first time
# and read the rate before committing a night to it.
#
# The campaign:
#   * fp32 sqrt EXHAUSTIVE - all 2^32 encodings - under all five
#     rounding attributes (RMM rides the RNE oracle; sqrt has no ties,
#     so they must agree case by case). 64 ranges x 5 modes.
#   * random banded div32 / div64 / sqrt64 under the four native
#     modes, RANDN cases per (op, mode), seeds fixed and distinct so
#     a failure names its reproducer.
#
# Every job writes its own log under soak-out/; the aggregate verdict
# is the exit status plus the last lines here. A job that dies or
# disagrees leaves its log naming the exact operands.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$ROOT/soak-out}
JOBS=${JOBS:-$(( $(nproc) > 6 ? $(nproc) - 4 : 2 ))}
RANDN=${RANDN:-200000000}
SLICES=${SLICES:-64}

if [ "${QUICK:-0}" = "1" ]; then
  RANDN=2000000
  SLICES=4
  QUICK_SPAN=$((1 << 24))
fi

make -C "$ROOT/host" divsqrt-soak >/dev/null
BIN="$ROOT/host/divsqrt-soak"

mkdir -p "$OUT"
rm -f "$OUT"/*.log "$OUT"/joblist

# ---- job list -------------------------------------------------------
{
  # exhaustive fp32 sqrt (or a shrunken span for QUICK)
  span=$(( ${QUICK_SPAN:-4294967296} / SLICES ))
  for mode in rne rtz rdn rup rmm; do
    for i in $(seq 0 $((SLICES - 1))); do
      lo=$((i * span))
      hi=$(((i + 1) * span))
      echo "sqrt32-$mode-$i sqrt32 $lo $hi $mode"
    done
  done
  # random campaigns; seed encodes op and mode so reruns reproduce
  s=1
  for op in div32 div64 sqrt64; do
    for mode in rne rtz rdn rup; do
      echo "$op-$mode $op $RANDN $((0x50AC0000 + s)) $mode"
      s=$((s + 1))
    done
  done
} > "$OUT/joblist"

total=$(wc -l < "$OUT/joblist")
echo "== $total jobs across $JOBS workers, logs in $OUT"

run_one() {
  # shellcheck disable=SC2086
  set -- $1
  name=$1; shift
  if nice -n 19 "$BIN" "$@" > "$OUT/$name.log" 2>&1; then
    echo "ok   $name"
  else
    echo "FAIL $name"
    return 1
  fi
}
export -f run_one
export BIN OUT

if xargs -P "$JOBS" -I{} -a "$OUT/joblist" bash -c 'run_one "{}"'; then
  :
fi

# Negative control: a sabotaged run over a range whose results are
# never NaN (so the flipped bit cannot hide in the NaN class) must
# FAIL, or the harness's green means nothing. Its log is NOT named
# *.log on purpose: the summary below sweeps every job log, and the
# control's 65,536 intentional mismatches poisoned the aggregate the
# first time this ran - a negative control that fails the run it just
# validated is the control eating the experiment.
if CFT_SOAK_SABOTAGE=1 "$BIN" sqrt32 0x3F800000 0x3F810000 rne \
     > "$OUT/control-sabotage.out" 2>&1; then
  echo "== NEGATIVE CONTROL FAILED TO FAIL - harness cannot detect"
  exit 1
fi
echo "== negative control: sabotaged run detected, harness can fail"

echo "== summary"
cat "$OUT"/*.log | grep -E "cases," | \
  awk '{c+=$3; v+=$5; f+=$8} END {printf "   %d cases, %d value mismatches, %d flag mismatches\n", c, v, f}'
if cat "$OUT"/*.log | grep -E "cases," | \
   awk '{v+=$5; f+=$8} END {exit (v+f) ? 1 : 0}'; then
  echo "== SOAK CLEAN"
else
  echo "== SOAK FOUND DISAGREEMENTS - see $OUT"
  exit 1
fi
