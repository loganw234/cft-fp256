#!/bin/bash
# M4 model: the larger samples the study hands to the lead for amd-arc-box
# (the study's section 8, items 3 to 5). Not run by the study.
#
#   bash box_m4s.sh [JOBS]            (from any directory; default 24 jobs)
#
# 1. The budgets over larger samples (3.2): m4budget.py, every function and
#    region, 12,000 lanes at fp64 and 3,000 at fp128 and fp256, seeds 121
#    to 125 (the study's were seed 2, 1,000 and 300).
# 2. The mark-rate law at volume (3.4): rate.py at G' = 6, rne and rtz,
#    50,000 arguments at fp64 and 20,000 at fp128 and fp256, seed 7, in the
#    random region and in the edge region (whose values spread, so the
#    law's assumption holds there for atan too).
# 3. The tiny family at fp128 and fp256 past the census's c <= 16 (3.5):
#    census.py's tiny family is fixed at c 1..16; this runs it as the
#    study did, for the record at the box's seed-free size, nothing more
#    (the family's centres to c of about 2^12 and 2^33 are COMPUTED, not
#    enumerable).
# 4. fp32's triple word over larger regions (2.8): twrun.py measure, 20,000
#    lanes a region.
#
# Expected (ESTIMATE, scaled from the desktop's niced times in queue4.log
# and queue7.log; one single-threaded process a job, about 150 MB each; 70
# jobs): (1) 57 budget jobs, about 1.8 minutes a fp64 job, 0.7 a fp128 job
# and up to 3 a fp256 job; (2) 6 rate jobs, about 9 minutes at fp64, 4 at
# fp128 and 5.5 at fp256 a mode; (3) 2 census jobs, 0.5 and 1.2 minutes;
# (4) 5 triple-word jobs, about 4.5 minutes a region. In all about 2.5
# hours of one desktop core. M2's box script took 2.4 times its desktop
# estimate on the box (6.1 core-hours), so allow 6 core-hours, and with 24
# jobs at a time (the box has 36 threads) about 25 to 35 minutes, bounded
# by the fp64 rate jobs. Outputs go to ./box-out/, the committed *.out.txt
# untouched. On a nightly day it fits before 17:50 if started by 17:10;
# otherwise it waits for 08:00.
set -u
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY=${PY:-python3}
JOBS=${1:-24}
mkdir -p box-out
{
  for md in random edge; do
    echo "rate-fp64-$md rate.py fp64 atan,asin,acos,atan2 50000 0,1 6 7 $md"
    echo "rate-fp128-$md rate.py fp128 atan,asin,acos,atan2 20000 0,1 6 7 $md"
    echo "rate-fp256-$md rate.py fp256 atan,asin,acos,atan2 20000 0,1 6 7 $md"
  done
  for fn in atan asin acos atan2; do
    for md in random:121 edge:122 big:123 small:124 diag:125; do
      m=${md%%:*}; s=${md##*:}
      [ "$fn" = atan ] && [ "$m" = diag ] && continue
      echo "budget-fp64-$fn-$m m4budget.py fp64 $fn $m 12000 $s 10"
      echo "budget-fp128-$fn-$m m4budget.py fp128 $fn $m 3000 $s 10"
      echo "budget-fp256-$fn-$m m4budget.py fp256 $fn $m 3000 $s 10"
    done
  done
  echo "census-fp128-tiny census.py fp128 tiny"
  echo "census-fp256-tiny census.py fp256 tiny"
  for m in random edge big small diag; do
    echo "tw-measure-$m twrun.py measure 20000 $m"
  done
} | xargs -P "$JOBS" -L 1 bash -c 'name=$0; echo "== $(date "+%F %T") start: $name"; '"$PY"' "$@" > "box-out/$name.out.txt" 2>&1; echo "== $(date "+%F %T") end ($?): $name"' | tee box-out/box_m4s.log
echo "== the budgets' bounds"
grep -H "THE BUDGET'S BOUND" box-out/budget-*.out.txt
echo "== the rate law"
cat box-out/rate-*.out.txt
echo "== fp32's triple word"
cat box-out/tw-measure-*.out.txt
