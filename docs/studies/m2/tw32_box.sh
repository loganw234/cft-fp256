#!/bin/bash
# M2X: the larger samples for fp32's triple word, handed to the lead for
# amd-arc-box (the study's section 8, items 3 and 4, at fp32 G = 40). Not run
# by M2X. Cut from box_m2s.sh, which did the same for fp64, fp128 and fp256.
#
#   bash tw32_box.sh [JOBS]            (from any directory; default 21 jobs)
#
# 1. The budgets over larger samples: tw32_run.py budget, sin, cos and tan,
#    the study's five regions and the quadrant boundaries (`quad`: the floats
#    next to the odd multiples of pi/4 from k = 0, in every binade; 12,000 of
#    its 18,266 arguments), 12,000 lanes a region, seeds the desktop's plus
#    100. 18 jobs. The six `quad` jobs need numpy (tw32.half_family; the
#    desktop's Miniconda has it): check `python3 -c "import numpy"` on the box
#    first, and without it leave those six lines out.
# 2. The mark-rate law at volume: rne and rtz at G' = 6, 50,000 random
#    arguments, seed 7 (box_m2s.sh's), a job a function. 3 jobs.
#
# Expected (ESTIMATE, scaled linearly in lanes from the desktop's runs of
# M2X's entry, docs/VALIDATION.md, which shared the desktop with parcel M2G1;
# one single-threaded process a job): a budget job takes about 8 to 15
# minutes at 12,000 lanes (the desktop's 1,500-lane runs took 59 to 109
# seconds, median 76) and about 40 MB, the `quad` ones about 360 MB at their
# start, while the half family is built; a rate job about 15 minutes at
# 50,000 lanes (the desktop's 2,000-lane cell took about 18 seconds, two
# cells a job), about 40 MB. 21 jobs in all, about 3.5 hours of one core;
# with all 21 at a time (the box has 36 threads) the whole is bounded by the
# longest budget or rate job, about 15 minutes, if the box's cores are the
# desktop's speed. Outputs go to ./box-out-tw32/, the committed *.out.txt
# untouched.
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
