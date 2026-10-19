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
#
#   CFT_SOAK_ARTIFACT=<artifact.xclbin> QUICK=1 bash hw/run-c5-soak.sh
#       ... against a TILE. The oracle is the host CPU either way; see
#       hw/run-soak.sh's header for why this matters and what it costs.
#   JOBS=24 RANDN=100000000 bash hw/run-c5-soak.sh   # tune width/depth
#
# The campaign:
#   * EXHAUSTIVE fp32 - all 2^32 encodings - for roundToIntegral under
#     all five attributes (each lane checked as the named variant AND
#     as roundToIntegralExact), nextUp, nextDown, logB and class.
#     Nine sweeps, sliced so a stopped run loses one slice, not a
#     sweep.
#   * EXHAUSTIVE modes of the operations whose operand is 32 bits wide
#     and that the random campaign below only samples - the -all and
#     -wide jobs, each on the oracles, flag disciplines, probes and
#     sabotage of its random mode: conv32to64-all (every fp32 encoding
#     widened), cvtto32-all (every encoding against all four integer
#     targets, five attributes), cvtfrom32-all and cvtfrom64-all (every
#     32-bit integer as an i32 and a u32 source, under the probed
#     modes), scaleb32-all (every encoding against the directed
#     exponent list, probed modes) and scaleb32-wide (every encoding
#     against every exponent that can change a result, -278..277, and
#     twelve past those edges; probed modes, and only if
#     `probe scalebrange` finds the range holds on this libm). Their
#     verdict lines say what they covered - ", E encodings, S skipped" -
#     which hw/card_stress.py holds each slice to. Sliced like rint32's,
#     except the wide jobs, which do 568 checks an encoding and are cut
#     WIDE_SLICES ways (default 1024, so a slice is minutes of software
#     backend, not hours). Four of the six families are HOST operations
#     in libcft: a card soak of them never reaches the tile (see
#     hw/card_stress_lib.py, OP_REACH).
#     THE SIZE of the no-argument form: the four scaleb32-wide jobs alone
#     are about 23 to 25 process-days of software backend (sampled over
#     the space, 5.8 to 6.6 days an attribute; verifier-VEX's own measure
#     gives 23 in all), so the full campaign is roughly 19 to 21 hours on
#     30 workers, nearly all of it that one item; everything else this
#     adds is about a day of process time. hw/card-stress.sh names its
#     items with --sweep-items instead, and QUICK=1 cuts the wide jobs to
#     4 slices of 2^16 encodings.
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

WIDE_SLICES=${WIDE_SLICES:-1024}

if [ "${QUICK:-0}" = "1" ]; then
  RANDN=2000000
  SLICES=4
  QUICK_SPAN=$((1 << 24))
  # scaleb32-wide does 568 checks an encoding: a smoke of it covers 2^16 encodings in 4 slices
  WIDE_SLICES=4
  QUICK_WIDE_SPAN=$((1 << 16))
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
# scaleb32-wide's exponent range, measured on this libm: the range and its edges (host only, no device)
WIDE_MODES="$SCALEB_MODES"
if ! "$BIN" probe scalebrange; then
  WIDE_MODES=""
  echo "== scalebrange probe: the derived exponent range does NOT hold on this libm; no scaleb32-wide job runs"
fi

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
  # exhaustive modes of the conversions and scaleB (the -all and -wide jobs), sliced like rint32's:
  # they take no seed, so the random campaign's seeds below are what they were
  for i in $(seq 0 $((SLICES - 1))); do
    echo "conv32to64-all-$i conv32to64-all $((i * span)) $(((i + 1) * span))"
  done
  for mode in rne rtz rdn rup rmm; do
    for i in $(seq 0 $((SLICES - 1))); do
      echo "cvtto32-all-$mode-$i cvtto32-all $((i * span)) $(((i + 1) * span)) $mode"
    done
  done
  for op in cvtfrom32-all cvtfrom64-all; do
    for mode in $CVTFROM_MODES; do
      for i in $(seq 0 $((SLICES - 1))); do
        echo "$op-$mode-$i $op $((i * span)) $(((i + 1) * span)) $mode"
      done
    done
  done
  for mode in $SCALEB_MODES; do
    for i in $(seq 0 $((SLICES - 1))); do
      echo "scaleb32-all-$mode-$i scaleb32-all $((i * span)) $(((i + 1) * span)) $mode"
    done
  done
  # the wide item: 568 checks an encoding, so more and smaller slices
  wspan=$(( ${QUICK_WIDE_SPAN:-4294967296} / WIDE_SLICES ))
  for mode in $WIDE_MODES; do
    for i in $(seq 0 $((WIDE_SLICES - 1))); do
      echo "scaleb32-wide-$mode-$i scaleb32-wide $((i * wspan)) $(((i + 1) * wspan)) $mode"
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

# The same for each exhaustive mode, over a range whose results are never NaN (so the flipped bit
# cannot hide in the NaN class): each must FAIL, or its green means nothing either. The wide control
# runs only if the wide jobs do.
while read -r ctl; do
  [ -n "$ctl" ] || continue
  # shellcheck disable=SC2086
  if CFT_SOAK_SABOTAGE=1 "$BIN" $ctl > "$OUT/control-sabotage-${ctl%% *}.out" 2>&1; then
    echo "== NEGATIVE CONTROL FAILED TO FAIL ($ctl) - harness cannot detect"
    exit 1
  fi
  echo "== negative control: sabotaged ${ctl%% *} detected"
done <<EOF
conv32to64-all 0x3F800000 0x3F801000
cvtto32-all 0x3F800000 0x3F801000 rne
cvtfrom32-all 0x00001000 0x00002000 rne
cvtfrom64-all 0x00001000 0x00002000 rne
scaleb32-all 0x3F800000 0x3F801000 rne
$([ -n "$WIDE_MODES" ] && echo "scaleb32-wide 0x3F800000 0x3F800010 rne")
EOF

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
