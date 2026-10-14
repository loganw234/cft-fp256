#!/bin/bash
# M2 model: the larger samples the study hands to the lead for amd-arc-box
# (the study's section 8, items 3 and 4). Not run by the study.
#
#   bash box_m2s.sh [JOBS]            (from any directory; default 24 jobs)
#
# 1. The mark-rate law at volume (3.4: sin's and cos's opposite departures
#    of about 2 sigma each at the study's size): rate.py at G' = 6, rne
#    and rtz, 50,000 random arguments at fp64 and 20,000 at fp128 and
#    fp256, seed 7.
# 2. The budgets over larger samples (3.2): m2budget.py, every function and
#    region, 12,000 lanes at fp64 and 3,000 at fp128 and fp256, seeds as
#    the study's plus 100.
# 3. fp128's whole range for the cancellation (1.4): worst_range.py over
#    all 16,384 binades (the study measured [1, 2^1024) only).
#
# Expected (ESTIMATE, from the desktop's times; one single-threaded
# process a job, about 150 MB each): (1) about 14, 6 and 7 minutes; (2)
# about 3.5 minutes a fp64 job and 1 to 1.5 minutes a fp128 or fp256 job,
# 45 jobs; (3) about 9 minutes. In all about 2 to 2.5 hours of one core;
# with 24 jobs at a time (the box has 36 threads) about 15 to 20 minutes,
# bounded by the fp64 rate job. Outputs go to ./box-out/, the committed
# *.out.txt untouched.
set -u
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY=${PY:-python3}
JOBS=${1:-24}
mkdir -p box-out
{
  echo "rate-fp64 rate.py fp64 sin,cos,tan 50000 0,1 6 7"
  echo "rate-fp128 rate.py fp128 sin,cos,tan 20000 0,1 6 7"
  echo "rate-fp256 rate.py fp256 sin,cos,tan 20000 0,1 6 7"
  echo "worst-fp128 worst_range.py fp128 0 16383"
  for fn in sin cos tan; do
    for md in edge:121 near:122 zero:125 small:123 random:124; do
      echo "budget-fp64-$fn-${md%%:*} m2budget.py fp64 $fn ${md%%:*} 12000 ${md##*:} 10"
      echo "budget-fp128-$fn-${md%%:*} m2budget.py fp128 $fn ${md%%:*} 3000 ${md##*:} 10"
      echo "budget-fp256-$fn-${md%%:*} m2budget.py fp256 $fn ${md%%:*} 3000 ${md##*:} 10"
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'name=$0; echo "== $(date "+%F %T") start: $name"; '"$PY"' "$@" > "box-out/$name.out.txt" 2>&1; echo "== $(date "+%F %T") end ($?): $name"' | tee box-out/box_m2s.log
echo "== the budgets' bounds"
grep -H "THE BUDGET'S BOUND" box-out/budget-*.out.txt
echo "== the rate law"
cat box-out/rate-*.out.txt
echo "== fp128's whole range"
head -2 box-out/worst-fp128.out.txt
