#!/bin/sh
# M3 model: send-back 1's desktop runs, one at a time, unniced (the round's
# ledger, ledger/M3S.md). fp64's bound gained its |Y k| term (B2), so every
# fp64 output is remade; fp128's and fp256's fragments are unchanged (their
# costs byte-identical), so they gain only the new zone regions. The fp64
# budgets of the design before the send-back are kept in no-b2/.
#
#   sh queue4.sh PYTHON > queue4.log
PY=${1:-python}
run() {
    out=$1; shift
    echo "$(date '+%F %T') start $out: $*"
    timeout 900 "$PY" -B "$@" > "$out" 2>&1
    rc=$?
    echo "$(date '+%F %T') end $out (rc $rc)"
}
run costs.fp64.out.txt costs.py fp64
run sched.fp64.out.txt sched.py fp64
run share.fp64.out.txt share.py fp64
for r in wide near1 edge redb small negint sub tinyy hugey negedge rhoedge zone; do
    run budget.fp64-pow-$r.out.txt budget.py fp64 pow $r 120 1
done
run budget.fp64-powr-wide.out.txt budget.py fp64 powr wide 120 1
for r in int int-neg int17 int1000 int31 int63 zone1000 zone12000; do
    run budget.fp64-pown-$r.out.txt budget.py fp64 pown $r 120 1
done
for r in int int17; do
    run budget.fp64-rootn-$r.out.txt budget.py fp64 rootn $r 120 1
done
for r in int int1000 zone1000 zone12000; do
    run budget.fp64-compound-$r.out.txt budget.py fp64 compound $r 120 1
done
run budget.fp64-pow-edge-bound_tight.out.txt budget.py fp64 pow edge 120 1 bound_tight
run budget.fp64-compound-zone12000-zone_bound_off.out.txt budget.py fp64 compound zone12000 120 1 zone_bound_off
run budget.fp64-pow-zone-zone_bound_off.out.txt budget.py fp64 pow zone 120 1 zone_bound_off
run regions_run.fp64-pow.out.txt regions_run.py fp64 pow 400
run regions_run.fp64-powr.out.txt regions_run.py fp64 powr 200
for f in pown rootn compound; do
    run regions_run.fp64-$f.out.txt regions_run.py fp64 $f 150
done
for f in pown compound; do
    run regions_run.fp64-$f-zone.out.txt regions_run.py fp64 $f 150 zone1000 zone12000
done
run specials.fp64.out.txt specials.py fp64
run plants.fp64.out.txt plants.py fp64
for fam in intpow root2k pow2 near1 dominant edges smallint; do
    run census.fp64-$fam.out.txt census.py fp64 $fam 300
done
run census.fp64-hard3p.out.txt census.py fp64 hard3p 400
run rate.fp64-pow-wide.out.txt rate.py fp64 pow wide 600 8 3
run rate.fp64-pow-wide-g2.out.txt rate.py fp64 pow wide 300 2 3
for f in fp128 fp256; do
    run regions_run.$f-pow-zone.out.txt regions_run.py $f pow 80 zone
    run regions_run.$f-powr-zone.out.txt regions_run.py $f powr 40 zone
    run budget.$f-pow-zone.out.txt budget.py $f pow zone 40 1
done
for f in pown compound; do
    run regions_run.fp128-$f-zone.out.txt regions_run.py fp128 $f 40 zone188000
    run regions_run.fp256-$f-zone.out.txt regions_run.py fp256 $f 40 zone2990000
    run budget.fp128-$f-zone188000.out.txt budget.py fp128 $f zone188000 40 1
    run budget.fp256-$f-zone2990000.out.txt budget.py fp256 $f zone2990000 40 1
done
run onseq.fp64.out.txt onseq.py fp64 pow powr pown rootn compound --ns 2,-2,3,17,9223372036854775807,-9223372036854775808
run pools_run.fp64.out.txt pools_run.py fp64
run poolmarks.fp64.out.txt poolmarks.py fp64
