#!/bin/bash
# M2X: the larger samples for fp32's triple word, handed to the lead for
# amd-arc-box (the study's section 8, items 3 and 4, at fp32 G = 40). Not run
# by M2X. Cut from box_m2s.sh, which did the same for fp64, fp128 and fp256.
#
#   bash tw32_box.sh [JOBS]            (from any directory; default 24 jobs)
#
# 1. The budgets over larger samples: tw32_budget.py fp32, sin, cos and tan,
#    the study's five regions and the quadrant boundaries (`quad`, the
#    floats next to (k + 1/2) pi/2 from k = 0, where |r| is next to pi/4),
#    12,000 lanes a region, seeds the desktop's plus 100 (`quad` draws all
#    of its 2,632 arguments whatever N). 18 jobs.
# 2. The mark-rate law at volume: rne and rtz at G' = 6, 50,000 random
#    arguments, seed 7 (box_m2s.sh's), a job a function. 3 jobs.
#
# Expected (ESTIMATE, from the desktop's times in the batch of M2X's entry,
# docs/VALIDATION.md; one single-threaded process a job): a budget job
# EXPECT_BUDGET at 12,000 lanes (the desktop's 1,500-lane run took
# EXPECT_BUDGET_DESKTOP), about 250 MB each; a rate job EXPECT_RATE at
# 50,000 lanes (the desktop's 2,000-lane cell took EXPECT_RATE_DESKTOP), about
# 150 MB each. 21 jobs in all; with 21 at a time (the box has 36 threads) the
# whole is bounded by the longest budget job, about EXPECT_BUDGET. Outputs go
# to ./box-out-tw32/, the committed *.out.txt untouched.
#
# Run the model on the box in a CLEAN CLONE of the commit under test, its SHA
# and a grep of its sources for something only that commit has asserted
# first (CLAUDE.md, "Before believing a remote build"). The box's Python is
# 3.12 with mpmath 1.3.0, as the desktop's.
set -u
cd "$(dirname "$0")" || exit 1
export PYTHONDONTWRITEBYTECODE=1
PY=${PY:-python3}
JOBS=${1:-21}
mkdir -p box-out-tw32
{
  for fn in sin cos tan; do
    echo "rate-fp32-$fn tw32_run.py rate 50000 7 - $fn"
    for md in edge:121 near:122 zero:125 small:123 random:124 quad:126; do
      echo "budget-fp32-$fn-${md%%:*} tw32_run.py budget $fn ${md%%:*} 12000 ${md##*:}"
    done
  done
} | xargs -P "$JOBS" -L 1 bash -c 'name=$0; echo "== $(date "+%F %T") start: $name"; '"$PY"' "$@" > "box-out-tw32/$name.out.txt" 2>&1; rc=$?; echo "== $(date "+%F %T") end ($rc): $name"' | tee box-out-tw32/tw32_box.log
echo "== the budgets' bounds"
grep -H "THE BUDGET'S BOUND" box-out-tw32/budget-fp32-*.out.txt
echo "== the rate law"
cat box-out-tw32/rate-fp32-*.out.txt
