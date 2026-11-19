#!/bin/sh
# M3 model: send-back 1's second desktop queue, after queue4. The zone
# region was redefined (its top at the reduction's own boundary, 241/256,
# and its lanes varied) after queue4 had made pow's fp64 zone budget, so
# that one is remade; then the analytic bound's arithmetic, the zone's
# plant and fix at 2,000 lanes (the desktop's curve, for sizing the box's
# runs), the scan of n, and the completeness and pass check over every
# output.
#
#   sh queue5.sh PYTHON > queue5.log
PY=${1:-python}
run() {
    out=$1; shift
    echo "$(date '+%F %T') start $out: $*"
    timeout 900 "$PY" -B "$@" > "$out" 2>&1
    rc=$?
    echo "$(date '+%F %T') end $out (rc $rc)"
}
mkdir -p zone-curve
run budget.fp64-pow-zone.out.txt budget.py fp64 pow zone 120 1
# the zone at a large n then drew only where |n L| is on the main path
# (regions.py's _zone_x), so queue4's zone12000 and larger runs are remade
for f in compound pown; do
    run budget.fp64-$f-zone12000.out.txt budget.py fp64 $f zone12000 120 1
    run regions_run.fp64-$f-zone.out.txt regions_run.py fp64 $f 150 zone1000 zone12000
    run regions_run.fp128-$f-zone.out.txt regions_run.py fp128 $f 40 zone188000
    run regions_run.fp256-$f-zone.out.txt regions_run.py fp256 $f 40 zone2990000
    run budget.fp128-$f-zone188000.out.txt budget.py fp128 $f zone188000 40 1
    run budget.fp256-$f-zone2990000.out.txt budget.py fp256 $f zone2990000 40 1
done
run budget.fp64-compound-zone12000-zone_bound_off.out.txt budget.py fp64 compound zone12000 120 1 zone_bound_off
run zonebound.out.txt zonebound.py
for args in "compound zone12000 2000 1 zone_bound_off" "compound zone12000 2000 1"             "pow zone 2000 1 zone_bound_off" "pow zone 2000 1"; do
    set -- $args
    run zone-curve/budget.fp64-$1-$2-$3${5:+-$5}.out.txt budget.py fp64 $args
done
# the plant reproduces the design before: the box's own 2,000-lane run of
# compound(x, 1000) at d2bd90fa (box-1119/), lane for lane
run zone-curve/budget.fp64-compound-int1000-2000-zone_bound_off.out.txt budget.py fp64 compound int1000 2000 1 zone_bound_off
# the scan of n in the design before (the plant): where the zone's sum
# outgrows |t| B1 most
mkdir -p n-scan
for f in compound pown; do
    for n in 31 100 300 1000 3000 10000 12000 13000; do
        run n-scan/budget.fp64-$f-zone$n-zone_bound_off.out.txt budget.py fp64 $f zone$n 150 1 zone_bound_off
    done
done
run complete.out.txt complete.py
