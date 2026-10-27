#!/bin/bash
# M2X: the larger samples for fp32's triple word, handed to the lead for
# amd-arc-box (the study's section 8, items 3 and 4, at fp32 G = 40). Not run
# by M2X; RUN BY THE LEAD on amd-arc-box on 2026-10-27, 12:31 to 12:55, from a
# fresh clone at 64e57565 (the results are in docs/VALIDATION.md, M2X's entry).
# Cut from box_m2s.sh, which did the same for fp64, fp128 and fp256.
#
#   bash tw32_box.sh [JOBS]            (from any directory; default 21 jobs)
#
# 1. The budgets over larger samples: tw32_run.py budget, sin, cos and tan,
#    the study's five regions and the quadrant boundaries (`quad`: the floats
#    next to the odd multiples of pi/4 from k = 0, in every binade; 12,000 of
#    its 18,266 arguments), 12,000 lanes a region, seeds the desktop's plus
#    100, under rne (the tool's original run takes rne). 18 jobs. The six
#    `quad` jobs need numpy (tw32.half_family; the desktop's Miniconda has it,
#    and so had the box): check `python3 -c "import numpy"` on a box first,
#    and without it leave those six lines out.
# 2. The mark-rate law at volume: rne and rtz at G' = 6, 50,000 random
#    arguments, seed 7 (box_m2s.sh's), a job a function. 3 jobs.
#
# Times, MEASURED by the lead's run (all 21 jobs at once, one single-threaded
# process a job, every job ending 0): 1,388 s for the whole; a budget job 869
# to 1,387 s (median 973 s) at 12,000 lanes; a rate job 864 (cos), 1,228 (sin)
# and 1,282 s (tan) at 50,000 lanes; 22,541 s of job time, 6.3 hours, in all.
# This header's first version ESTIMATED, scaled linearly in lanes from the
# desktop's runs (which shared the desktop with parcel M2G1), 8 to 15 minutes
# a budget job (608 s from the desktop's median of 76 s a 1,500-lane run), about
# 15 minutes a rate job, about 3.5 hours of one core (about 3.8 by those same
# figures) and about 15 minutes for the whole: the measured budget jobs took
# 1.4 to 2.3 times the 608 s, the rate jobs 0.96 to 1.4 times their 900 s, the
# whole 1.5 times. Memory is an ESTIMATE; none was measured on the box: about
# 40 MB a job, the `quad` ones about 360 MB while the half family is built (one
# sample each of the desktop's working set, in M2X's ledger, not in an output).
# Outputs go to ./box-out-tw32/, the committed *.out.txt untouched.
#
# Run the model on the box in a CLEAN CLONE of the commit under test, its SHA
# and a grep of its sources for something only that commit has asserted
# first (CLAUDE.md, "Before believing a remote build"). The box's Python was
# 3.12.3 with mpmath 1.4.1 and numpy 2.5.2 (MEASURED, the lead's run of
# 2026-10-27); the desktop's is 3.12 with mpmath 1.3.0 and numpy 2.2.6.
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
