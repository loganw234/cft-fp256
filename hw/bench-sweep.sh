#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Sweep cft-bench across the whole grid and emit one dataset, so the question
# "at what size does hardware start to pay?" has an answer with a number rather
# than an opinion.
#
#   bash hw/bench-sweep.sh --single ~/cardday-rev4/cft_hw_single.xclbin \
#                          --quad   ~/cardday-rev4/cft_hw_quad.xclbin
#   bash hw/bench-sweep.sh --quick            # the ladder thinned, for a smoke
#   bash hw/bench-sweep.sh                    # software only, no card needed
#
# THE GRID
#   backend x path : software(host) | device(host-pointer) | device(resident)
#                    - "host-pointer" stages operands across PCIe on every
#                      call, which is what a first port gets;
#                    - "resident" is cft_alloc'd, filled and published once,
#                      so the column reports the engine rather than the bus.
#                    Software has no second path: cft_alloc is a no-op there,
#                    so running it twice would be one number reported twice.
#   tiles          : whichever artifacts are given, by their own CU count
#   format         : fp32 fp64 fp128 fp256
#   op             : whatever cft-bench measures (abs..fma today)
#   n              : 1 to the largest that fits, doubling - the point of the
#                    exercise is the shape of the curve at BOTH ends, so it
#                    starts at a single element where call overhead is the
#                    whole cost, and ends where the working set is megabytes.
#
# WHY n STOPS WHERE IT DOES. Four operand buffers live at once, and on the
# card each is bound to its own HBM channel - 256 MB apiece on a U50. The
# ladder caps a buffer at 128 MB so the four fit with room, which is 32M
# elements at fp32 and 4M at fp256. Past that the run would be measuring the
# allocator's failure, which is a different study.
#
# WHAT IT DOES NOT COVER, said plainly rather than left to be discovered:
# division, square root and the transcendentals are not cft_run opcodes -
# they are their own entry points with their own signatures - so they are
# absent from cft-bench and therefore from this sweep. They are the calls
# where a tile has the most to win, so the tipping points here are a LOWER
# bound on the case for hardware, not an upper one.
#
# Each row carries the reps and seconds cft-bench actually achieved, so a
# point measured from a single repetition can be told from one measured over
# hundreds. Do not average them away.
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BENCH="$ROOT/host/cft-bench"
[ -x "$BENCH" ] || BENCH="$ROOT/host/cft-bench.exe"

SINGLE=""; QUAD=""; OUT="$ROOT/bench-sweep"; TSEC=0.15; QUICK=0
FORMATS="fp32 fp64 fp128 fp256"

die () { echo "FATAL: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --single)  SINGLE=${2:?}; shift 2;;
    --quad)    QUAD=${2:?};   shift 2;;
    --out)     OUT=${2:?};    shift 2;;
    --time)    TSEC=${2:?};   shift 2;;
    --formats) FORMATS=${2:?}; shift 2;;
    --quick)   QUICK=1; shift;;
    -h|--help) sed -n '2,48p' "$0"; exit 0;;
    *) die "unknown option $1";;
  esac
done

[ -x "$BENCH" ] || die "no cft-bench built; make -C host cft-bench"
for a in $SINGLE $QUAD; do [ -f "$a" ] || die "no such artifact: $a"; done

mkdir -p "$OUT"
CSV="$OUT/sweep.csv"
LOG="$OUT/sweep.log"
: > "$LOG"

# The ladder, per format. Doubling to 512 then coarser, because the
# interesting structure at the small end is per-call overhead and it changes
# fast, while the large end is bandwidth and changes slowly.
ladder_for () {          # <bytes per element>
  local esz=$1 cap n out=""
  cap=$(( 134217728 / esz ))          # 128 MB a buffer
  for n in 1 2 4 8 16 32 64 128 256 512 1024 2048 4096 8192 16384 32768 \
           65536 131072 262144 524288 1048576 2097152 4194304 8388608 \
           16777216 33554432; do
    [ "$n" -le "$cap" ] || break
    if [ "$QUICK" = 1 ]; then
      case "$n" in 1|16|256|4096|65536|1048576) ;; *) continue;; esac
    fi
    out="$out $n"
  done
  echo "$out"
}

esz_of () { case "$1" in fp32) echo 4;; fp64) echo 8;; fp128) echo 16;;
                         fp256) echo 32;; *) echo 0;; esac; }

echo "backend,path,tiles,format,bytes_per_elem,op,n,ns_per_elem,elems_per_s,mb_per_s,reps,seconds" > "$CSV"

rows=0; runs=0; failed=0

# one cft-bench invocation -> annotated rows
sweep_point () {         # <backend> <path> <tiles> <format> <n> [artifact] [--resident]
  local backend=$1 path=$2 tiles=$3 fmt=$4 n=$5; shift 5
  local out rc
  runs=$((runs + 1))
  out=$("$BENCH" "$@" -f "$fmt" -n "$n" -t "$TSEC" --csv 2>>"$LOG")
  rc=$?
  if [ "$rc" -ne 0 ] || [ -z "$out" ]; then
    failed=$((failed + 1))
    echo "  FAILED rc=$rc: $backend/$path/$tiles $fmt n=$n" | tee -a "$LOG"
    return 1
  fi
  # Drop cft-bench's own header, prefix ours, insert n after the op column.
  echo "$out" | tail -n +2 | awk -F, -v b="$backend" -v p="$path" \
      -v t="$tiles" -v n="$n" 'NF>=8 {
        printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n",
               b,p,t,$1,$2,$3,n,$4,$5,$6,$7,$8 }' >> "$CSV"
  rows=$(( rows + $(echo "$out" | tail -n +2 | wc -l) ))
  return 0
}

echo "== sweep begins $(date -Is)" | tee -a "$LOG"
echo "   bench $BENCH, -t $TSEC, quick=$QUICK" | tee -a "$LOG"

for fmt in $FORMATS; do
  esz=$(esz_of "$fmt")
  [ "$esz" -gt 0 ] || die "unknown format $fmt"
  for n in $(ladder_for "$esz"); do
    printf "%-6s n=%-9s" "$fmt" "$n" | tee -a "$LOG"
    sweep_point software host 0 "$fmt" "$n" && printf " sw" | tee -a "$LOG"
    if [ -n "$SINGLE" ]; then
      sweep_point device host     1 "$fmt" "$n" "$SINGLE"             && printf " 1t-host" | tee -a "$LOG"
      sweep_point device resident 1 "$fmt" "$n" "$SINGLE" --resident  && printf " 1t-res"  | tee -a "$LOG"
    fi
    if [ -n "$QUAD" ]; then
      sweep_point device host     4 "$fmt" "$n" "$QUAD"               && printf " 4t-host" | tee -a "$LOG"
      sweep_point device resident 4 "$fmt" "$n" "$QUAD" --resident    && printf " 4t-res"  | tee -a "$LOG"
    fi
    echo | tee -a "$LOG"
  done
done

echo "== sweep done $(date -Is)" | tee -a "$LOG"
echo "   $runs invocations, $rows rows, $failed failed -> $CSV" | tee -a "$LOG"
# A sweep that measured nothing must not read as a success.
[ "$rows" -gt 0 ] || { echo "NO ROWS - the dataset is empty" | tee -a "$LOG"; exit 1; }
exit 0
