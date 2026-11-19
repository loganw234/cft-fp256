#!/bin/sh
# M3 model, send-back 1: the larger samples that hold fp64's fixed bound,
# for the lead to run on amd-arc-box (agents do not touch the box). Run from
# a clone of the commit that adds this file, in docs/studies/m3/:
#
#   sh box_m3s_sb1.sh python3 OUTDIR [JOBS]
#
# 37 jobs, JOBS at a time (default 8), each single-threaded, under 400 MB;
# the longest first. ESTIMATE, from the box's own times on 2026-11-19
# (budgets at fp64 0.036 s a lane, fp128 0.06, fp256 up to 0.33; the
# regions and the census at the first run's): about 55 minutes at 8 jobs,
# the fp256 compound budgets the longest single jobs. It needs python3 and
# mpmath only, and writes nothing but OUTDIR's files (each job's stdout and
# stderr; -B keeps __pycache__ out). Its last lines are complete.py's over
# OUTDIR (every output closes with its script's own last line, no
# traceback, no nonzero "wrong unmarked") and xargs's status, which is 0
# only if every job's was; the script exits with that status.
#
# What each group shows (the study's 3.2 and 8, send-back 1):
#   the fix at volume: fp64 budgets, 10,000 lanes, seed 3, of compound and
#     pown at the worst n in the cancelling zone (zone12000) and at n = 1000
#     (int1000, the region the box found past 1 Bv), pow's negint, rhoedge,
#     redb and zone; each must be under 1 Bv
#   the plant at volume: zone_bound_off (the design before the send-back)
#     on int1000 at the box's own 10,000 lanes and seed 3, where that
#     design was 1.052 Bv (the plant reproduces it: the desktop's 2,000-lane
#     run equals the box's, zone-curve/), and on compound's zone12000 at
#     20,000 lanes; red is past 1 Bv. The zone alone stayed under 1 on the
#     desktop (0.942 at 2,000 lanes): int1000's other lanes make roundings
#     active whose capacity on the zone's lanes then counts (the study's
#     3.2)
#   0 wrong unmarked with the fix: regions_run at fp64 at the first box
#     run's sizes, the zone regions included, and the census at 3,000 (the
#     fix widens the bound the "may be exact" test reads)
#   fp128 and fp256: budgets, 10,000 lanes, of the zone at their largest n
#     on the main path (188,000 and 2,990,000), n = 1000, and pow's zone and
#     rhoedge
PY=${1:-python3}
OUT=${2:-box-out-sb1}
JOBS=${3:-8}
mkdir -p "$OUT"
{
for f in compound pown; do
    echo "budget.fp256-$f-int1000.out.txt budget.py fp256 $f int1000 10000 3"
    echo "budget.fp256-$f-zone2990000.out.txt budget.py fp256 $f zone2990000 10000 3"
done
for r in zone rhoedge; do
    echo "budget.fp256-pow-$r.out.txt budget.py fp256 pow $r 10000 3"
done
echo "budget.fp64-compound-zone12000-zone_bound_off.out.txt budget.py fp64 compound zone12000 20000 3 zone_bound_off"
echo "budget.fp64-compound-int1000-zone_bound_off.out.txt budget.py fp64 compound int1000 10000 3 zone_bound_off"
for f in compound pown; do
    echo "budget.fp128-$f-int1000.out.txt budget.py fp128 $f int1000 10000 3"
    echo "budget.fp128-$f-zone188000.out.txt budget.py fp128 $f zone188000 10000 3"
done
for r in zone rhoedge; do
    echo "budget.fp128-pow-$r.out.txt budget.py fp128 pow $r 10000 3"
done
for f in compound pown; do
    for r in zone12000 int1000; do
        echo "budget.fp64-$f-$r.out.txt budget.py fp64 $f $r 10000 3"
    done
done
for r in negint rhoedge redb zone; do
    echo "budget.fp64-pow-$r.out.txt budget.py fp64 pow $r 10000 3"
done
echo "regions_run.fp64-pow.out.txt regions_run.py fp64 pow 1000"
echo "regions_run.fp64-powr.out.txt regions_run.py fp64 powr 500"
for f in pown rootn compound; do
    echo "regions_run.fp64-$f.out.txt regions_run.py fp64 $f 400"
done
for f in pown compound; do
    echo "regions_run.fp64-$f-zone.out.txt regions_run.py fp64 $f 400 zone1000 zone12000"
done
for fam in intpow root2k pow2 near1 dominant edges smallint hard3p; do
    echo "census.fp64-$fam.out.txt census.py fp64 $fam 3000"
done
} | xargs -P "$JOBS" -L 1 sh -c 'out=$1; shift; "$0" -B "$@" > "'"$OUT"'/$out" 2>&1' "$PY"
st=$?
"$PY" -B complete.py "$OUT"
echo "xargs status $st (0 only if every job's was 0); done $(date '+%F %T')"
exit $st
