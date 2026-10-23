#!/bin/bash
# M4 model: send-back 1's re-measurement, for amd-arc-box, run by the lead
# (the study's 3.6, items 9 and 10; agents do not touch the box). Not run by
# the study. Everything atan2's two fixes touch, and what part 1 and part 2
# of the send-back asked to be measured again or kept checkable:
#
#   bash box_m4s2.sh [JOBS]           (from any directory; default 24 jobs)
#
#  A. the pools, on the model and as programs on seq.py, the specials, the
#     costs, the sharing, the live counts, the fingerprint, the G check, at
#     every format (fp32 is the double word at G = 18);
#  B. the corner (corner.py): atan2 with a tiny |y| against |x| over the
#     range above it, on the model and on seq.py, at every format and the
#     triple word, and with each fix removed (the plants prescale-d and,
#     for the triple word, range-low), red then green;
#  C. atan2's budgets in every region, at the desktop's sizes and seed
#     (overwriting their outputs) and at the box's (12,000 / 3,000 lanes,
#     seeds 121 to 125);
#  D. the census, every family at every format;
#  E. the rate law with its crowding split and its count of distinct
#     arguments: at the box's sizes (seed 7, random and edge) and at the
#     desktop's (seed 3);
#  F. the plants, with their new corner check, double word and triple word;
#  G. the triple word: pools, costs, seq.py, and the five regions at 2,000
#     and at 20,000 lanes;
#  H. the exact-quotient rule (exactq.py), tinyc.py and sbias_probe.py;
#  J. the five regions of m4measure at every format (atan2's figures).
#
# Expected (ESTIMATE, from the desktop's niced times and the first box run's
# log, box-out/box_m4s.log): 144 single-threaded jobs, about 150 MB each;
# about 2 hours of one desktop core, about 5 core-hours on the box at its
# measured ratio; with 24 at a time about 20 to 25 minutes, bounded by the
# rate law's fp64 random job (899 s in the first run) and the triple word's
# 20,000-lane regions (about 400 s each). On a nightly day it fits before
# 17:50 if started by 17:20; otherwise it waits for 08:00. Outputs go to
# ./box-out2/, each job's end line carrying its own exit code, and nothing
# committed is overwritten here: the study copies what it cites.
set -u
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY=${PY:-python3}
JOBS=${1:-24}
mkdir -p box-out2
{
  # the longest first
  for md in random edge; do
    echo "rate-box-fp64-$md rate.py fp64 atan,asin,acos,atan2 50000 0,1 6 7 $md"
    echo "rate-box-fp128-$md rate.py fp128 atan,asin,acos,atan2 20000 0,1 6 7 $md"
    echo "rate-box-fp256-$md rate.py fp256 atan,asin,acos,atan2 20000 0,1 6 7 $md"
  done
  for m in random edge big small diag; do
    echo "tw-measure-box-$m twrun.py measure 20000 $m"
  done
  for md in random:121 edge:122 big:123 small:124 diag:125; do
    m=${md%%:*}; s=${md##*:}
    echo "budget-box-fp64-atan2-$m m4budget.py fp64 atan2 $m 12000 $s 10"
    echo "budget-box-fp128-atan2-$m m4budget.py fp128 atan2 $m 3000 $s 10"
    echo "budget-box-fp256-atan2-$m m4budget.py fp256 atan2 $m 3000 $s 10"
  done
  echo "plants.fp64 plants.py fp64"
  echo "twrun-plants.fp32-tw twrun.py plants"
  # B. the corner
  for a in "fp64 2000" "fp32 2000" "fp128 500" "fp256 300" "fp32-tw 1000"; do
    set -- $a
    nm=$1; [ "$nm" = fp32 ] && nm=fp32-dw18
    echo "corner.$nm corner.py $1 $2 101"
    echo "corner-seq.$nm corner.py $1 $2 101 seq"
    echo "corner-prescale-d.$nm corner.py $1 $2 101 prescale-d"
  done
  echo "corner-range-low.fp32-tw corner.py fp32-tw 1000 101 range-low"
  # A.
  for f in fp64 fp128 fp256 fp32; do
    nm=$f; [ "$f" = fp32 ] && nm=fp32-dw18
    echo "pools_run.$nm pools_run.py $f"
    echo "onseq.$nm onseq.py $f"
    echo "specials.$nm specials.py $f"
    echo "costs.$nm costs.py $f"
  done
  for f in fp64 fp128 fp256; do
    echo "share.$f share.py $f"
  done
  echo "sched sched.py"
  echo "fingerprint fingerprint.py"
  echo "gcheck gcheck.py"
  # C. atan2's budgets at the desktop's sizes and seed
  for f in fp64 fp128 fp256 fp32; do
    nm=$f; [ "$f" = fp32 ] && nm=fp32-dw18
    n=1000; { [ "$f" = fp128 ] || [ "$f" = fp256 ]; } && n=300
    for m in random edge big small diag; do
      echo "budget.$nm-atan2-$m m4budget.py $f atan2 $m $n 2"
    done
  done
  # D. the census
  for f in fp64 fp128 fp256 fp32; do
    nm=$f; [ "$f" = fp32 ] && nm=fp32-dw18
    for fam in tiny near acos1 ratio diag; do
      echo "census.$nm-$fam census.py $f $fam"
    done
  done
  # E. the rate law at the desktop's size
  for f in fp64 fp128 fp256 fp32; do
    nm=$f; [ "$f" = fp32 ] && nm=fp32-dw18
    echo "rate.$nm-seed3 rate.py $f atan,asin,acos,atan2 2000 0,1 6 3"
  done
  # G. the triple word
  echo "twrun-pools.fp32-tw twrun.py pools"
  echo "twrun-costs.fp32-tw twrun.py costs"
  echo "twrun-onseq.fp32-tw twrun.py onseq"
  for m in random edge big small diag; do
    echo "twrun-measure.fp32-tw-$m twrun.py measure 2000 $m"
  done
  # H.
  for a in "fp64 2000" "fp32 2000" "fp128 500" "fp256 300"; do
    set -- $a
    nm=$1; [ "$nm" = fp32 ] && nm=fp32-dw18
    echo "exactq.$nm exactq.py $1 $2 1"
  done
  echo "tinyc tinyc.py"
  echo "sbias_probe sbias_probe.py"
  # J. the regions
  for f in fp64 fp128 fp256 fp32; do
    nm=$f; [ "$f" = fp32 ] && nm=fp32-dw18
    n=2000; { [ "$f" = fp128 ] || [ "$f" = fp256 ]; } && n=500
    for m in random edge big small diag; do
      echo "measure.$nm-$m m4measure.py $f atan,asin,acos,atan2 $n $m 0 1"
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'name=$0; echo "== $(date "+%F %T") start: $name"; '"$PY"' "$@" > "box-out2/$name.out.txt" 2>&1; rc=$?; echo "== $(date "+%F %T") end ($rc): $name"' | tee box-out2/box_m4s2.log
echo "== jobs that did not end 0"
grep "end (" box-out2/box_m4s2.log | grep -v "end (0)" || echo "(none)"
echo "== the corner"
cat box-out2/corner*.out.txt
echo "== the plants"
grep -v "^     " box-out2/plants.fp64.out.txt
cat box-out2/twrun-plants.fp32-tw.out.txt
