#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Fan the clause-5 native-oracle soak (host/tools/clause5_soak.c)
# across idle cores, the way run-soak.sh fans out divsqrt. Meant for a
# build host whose big cores are otherwise waiting on a Vivado route:
# every job runs under nice -19, and the default worker count reads
# the room - 12 while any vivado process is alive, up to 30 once the
# routes are done.
#
#   bash hw/run-c5-soak.sh                # the full campaign
#   QUICK=1 bash hw/run-c5-soak.sh       # minutes-long smoke, same shape
#   JOBS=24 RANDN=100000000 bash hw/run-c5-soak.sh   # tune width/depth
#
# The campaign:
#   * EXHAUSTIVE fp32 - all 2^32 encodings - for roundToIntegral under
#     all five attributes (each lane checked as the named variant AND
#     as roundToIntegralExact), nextUp, nextDown, logB and class.
#     Nine sweeps, sliced so a stopped run loses one slice, not a
#     sweep.
#   * random banded fp64 rint; scaleB and the integer conversions in
#     both widths under every mode their oracle honours (probed, not
#     assumed - a failed probe drops the directed modes and the log
#     says so); fp64<->fp32 conversion; remainder with directed
#     exponent-gap families; fp64 next/logb/class.
#
# Every job writes its own log under c5-soak-out/; the aggregate
# verdict is the exit status plus the last lines here. A job that dies
# or disagrees leaves its log naming the exact operands.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$ROOT/c5-soak-out}
CC=${CC:-cc}
RANDN=${RANDN:-30000000}
SLICES=${SLICES:-64}

# Read the room: a Vivado route on this box outranks the soak.
VIV=$(pgrep -c vivado || true)
if [ -z "${JOBS:-}" ]; then
  if [ "${VIV:-0}" -gt 0 ]; then JOBS=12; else JOBS=30; fi
  NP=$(nproc)
  MAXJ=$(( NP > 6 ? NP - 4 : 2 ))
  [ "$JOBS" -gt "$MAXJ" ] && JOBS=$MAXJ
fi

if [ "${QUICK:-0}" = "1" ]; then
  RANDN=2000000
  SLICES=4
  QUICK_SPAN=$((1 << 24))
fi

mkdir -p "$OUT"

# roundeven arrived in glibc 2.25; probe the libc rather than trust a
# version macro. The fallback (rint under FE_TONEAREST) is the same
# function, so this only chooses a symbol.
C5DEFS=""
if printf '#define _GNU_SOURCE\n#include <math.h>\nint main(void){return (int)(roundeven(1.5)+roundevenf(2.5f));}\n' \
     > "$OUT/.re-probe.c" 2>/dev/null && \
   $CC "$OUT/.re-probe.c" -lm -o "$OUT/.re-probe" 2>/dev/null; then
  C5DEFS="-DCFT_SOAK_HAVE_ROUNDEVEN=1"
  echo "== roundeven probe: present"
else
  echo "== roundeven probe: absent, rne oracle is rint under FE_TONEAREST"
fi
rm -f "$OUT/.re-probe.c" "$OUT/.re-probe"

make -C "$ROOT/host" clause5-soak C5DEFS="$C5DEFS" >/dev/null
BIN="$ROOT/host/clause5-soak"

# The environment probes decide which directed-mode jobs exist at all.
# Their verdicts are part of the record, so they go to stdout here and
# each affected job re-probes and restates its own degradation.
SCALEB_MODES="rne"
if "$BIN" probe scalbn; then SCALEB_MODES="rne rtz rdn rup"; fi
CVTFROM_MODES="rne"
if "$BIN" probe cvtfrom; then CVTFROM_MODES="rne rtz rdn rup"; fi
"$BIN" probe castflags || true

rm -f "$OUT"/*.log "$OUT"/joblist

# ---- job list -------------------------------------------------------
{
  # exhaustive fp32 sweeps (or a shrunken span for QUICK)
  span=$(( ${QUICK_SPAN:-4294967296} / SLICES ))
  for mode in rne rtz rdn rup rmm; do
    for i in $(seq 0 $((SLICES - 1))); do
      echo "rint32-$mode-$i rint32 $((i * span)) $(((i + 1) * span)) $mode"
    done
  done
  for op in nextup32 nextdown32 logb32 class32; do
    for i in $(seq 0 $((SLICES - 1))); do
      echo "$op-$i $op $((i * span)) $(((i + 1) * span))"
    done
  done
  # random campaigns; seed encodes op and mode so reruns reproduce
  s=1
  for mode in rne rtz rdn rup rmm; do
    echo "rint64-$mode rint64 $RANDN $((0xC5000000 + s)) $mode"; s=$((s+1))
    echo "cvtto32-$mode cvtto32 $((RANDN * 2 / 3)) $((0xC5000000 + s)) $mode"; s=$((s+1))
    echo "cvtto64-$mode cvtto64 $((RANDN * 2 / 3)) $((0xC5000000 + s)) $mode"; s=$((s+1))
  done
  for mode in $SCALEB_MODES; do
    echo "scaleb32-$mode scaleb32 $RANDN $((0xC5000000 + s)) $mode"; s=$((s+1))
    echo "scaleb64-$mode scaleb64 $RANDN $((0xC5000000 + s)) $mode"; s=$((s+1))
  done
  for mode in rne rtz rdn rup; do
    echo "conv64to32-$mode conv64to32 $RANDN $((0xC5000000 + s)) $mode"; s=$((s+1))
  done
  for mode in $CVTFROM_MODES; do
    echo "cvtfrom32-$mode cvtfrom32 $((RANDN * 2 / 3)) $((0xC5000000 + s)) $mode"; s=$((s+1))
    echo "cvtfrom64-$mode cvtfrom64 $((RANDN * 2 / 3)) $((0xC5000000 + s)) $mode"; s=$((s+1))
  done
  echo "conv32to64 conv32to64 $RANDN $((0xC5000000 + s))"; s=$((s+1))
  echo "rem32 rem32 $RANDN $((0xC5000000 + s))"; s=$((s+1))
  echo "rem64 rem64 $((RANDN * 2 / 3)) $((0xC5000000 + s))"; s=$((s+1))
  for op in nextup64 nextdown64 logb64 class64; do
    echo "$op $op $((RANDN * 3)) $((0xC5000000 + s))"; s=$((s+1))
  done
} > "$OUT/joblist"

total=$(wc -l < "$OUT/joblist")
echo "== $total jobs across $JOBS workers (vivado count: ${VIV:-0}), logs in $OUT"

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
# never NaN (1.0..2.0-ish, so the flipped bit cannot hide in the NaN
# class) must FAIL, or the harness's green means nothing. Its log is
# NOT named *.log, for the reason run-soak.sh records: a control that
# poisons the aggregate it just validated is the control eating the
# experiment.
if CFT_SOAK_SABOTAGE=1 "$BIN" rint32 0x3F800000 0x3F810000 rne \
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
