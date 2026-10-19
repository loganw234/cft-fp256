#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# sw_rates.sh - the rate of each soak job on the SOFTWARE backend, on this machine's CPU.
#
# The stress run measured each job's rate with the soak tool driving a tile
# (CFT_SOAK_ARTIFACT set). For the operations that are libcft HOST code (conversions,
# logb, next, class, rem: host/src/clause5.c, "the device argument is context") the tool does
# the same work on the software backend, so the two rates should differ by the CPU alone.
# For the operations that run on the tile (div, sqrt, rint, scaleb) the software backend
# does the composed passes in C softfloat, a different computation. sw_rates_compare.py
# reads this output beside the stress run's rates and says what it sees.
#
# One process at a time, niced, `timeout 300` each. Counts are chosen to run a few seconds.
# The exhaustive jobs run 8 slices of 2^19 encodings spread over [0, 2^32), so the mix of
# classes (finite, subnormal, infinite, NaN, either sign) is the sweep's own.
#
#   usage: bash sw_rates.sh DIR       DIR holds the built divsqrt-soak and clause5-soak
#
# Output lines: RATE <job> <tool> <argv...> units=<n> seconds=<s> rate=<units a second>

set -u
D=${1:?usage: bash sw_rates.sh DIR}
DS="$D/divsqrt-soak"
C5="$D/clause5-soak"
[ -x "$DS" ] && [ -x "$C5" ] || { echo "missing tools in $D" >&2; exit 2; }

now() { date +%s.%N; }

# job NAME BIN UNITS ARGV...   (UNITS is the count, or the encodings in all, for the rate)
job() {
  local name=$1 bin=$2 units=$3; shift 3
  local t0 t1 rc out
  t0=$(now)
  out=$(nice -n 10 timeout 300 "$bin" "$@" 2>&1); rc=$?
  t1=$(now)
  local secs rate
  secs=$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.3f", b - a }')
  rate=$(awk -v u="$units" -v s="$secs" 'BEGIN { printf "%.0f", u / s }')
  printf 'RATE %-14s %s %s units=%s seconds=%s rate=%s rc=%s\n' "$name" "$(basename "$bin")" "$*" "$units" "$secs" "$rate" "$rc"
}

# exhaustive: 8 slices of 2^19 at lo = i * 2^29, run one after another and timed as one
exh() {   # exh NAME BIN OP [MODE]
  local name=$1 bin=$2 op=$3 mode=${4:-}
  local t0 t1 i lo hi rc=0
  t0=$(now)
  for i in 0 1 2 3 4 5 6 7; do
    lo=$((i * 536870912)); hi=$((lo + 524288))
    nice -n 10 timeout 300 "$bin" "$op" "$lo" "$hi" $mode > /dev/null 2>&1 || rc=$?
  done
  t1=$(now)
  local secs rate
  secs=$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.3f", b - a }')
  rate=$(awk -v u=4194304 -v s="$secs" 'BEGIN { printf "%.0f", u / s }')
  printf 'RATE %-14s %s %s 8x[lo,lo+2^19) units=4194304 seconds=%s rate=%s rc=%s\n' "$name" "$(basename "$bin")" "$op $mode" "$secs" "$rate" "$rc"
}

echo "sw_rates: the software backend, one process, niced; $(uname -sr), $(nproc) threads, load $(cut -d' ' -f1-3 /proc/loadavg)"
echo "          CPU: $(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)"
echo

# random jobs: the tile items first, then the host items
job div32-rne     "$DS" 2000000  div32 2000000 7 rne
job div64-rne     "$DS" 2000000  div64 2000000 7 rne
job sqrt64-rne    "$DS" 2000000  sqrt64 2000000 7 rne
job rint64-rne    "$C5" 2000000  rint64 2000000 7 rne
job scaleb32-rne  "$C5" 8000000  scaleb32 8000000 7 rne
job scaleb64-rne  "$C5" 8000000  scaleb64 8000000 7 rne
job conv64to32-rne "$C5" 8000000 conv64to32 8000000 7 rne
job conv32to64    "$C5" 8000000  conv32to64 8000000 7
job cvtto32-rne   "$C5" 4000000  cvtto32 4000000 7 rne
job cvtto64-rne   "$C5" 4000000  cvtto64 4000000 7 rne
job cvtfrom32-rne "$C5" 2000000  cvtfrom32 2000000 7 rne
job cvtfrom64-rne "$C5" 2000000  cvtfrom64 2000000 7 rne
job rem32         "$C5" 1000000  rem32 1000000 7
job rem64         "$C5" 100000   rem64 100000 7
job nextup64      "$C5" 8000000  nextup64 8000000 7
job nextdown64    "$C5" 8000000  nextdown64 8000000 7
job logb64        "$C5" 8000000  logb64 8000000 7
job class64       "$C5" 20000000 class64 20000000 7

# exhaustive jobs
exh sqrt32-rne    "$DS" sqrt32 rne
exh rint32-rne    "$C5" rint32 rne
exh nextup32      "$C5" nextup32
exh nextdown32    "$C5" nextdown32
exh logb32        "$C5" logb32
exh class32       "$C5" class32
