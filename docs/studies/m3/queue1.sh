#!/bin/sh
# M3 model: the desktop's runs at fp64, one at a time, each under about ten
# minutes, unniced (a niced run starved under the desktop's load: the
# round's ledger, ledger/M3S.md). Each run's output is kept beside the model
# as *.out.txt; this script's own log records each start and end.
#
#   sh queue1.sh PYTHON > queue1.log
PY=${1:-python}
run() {
    out=$1; shift
    echo "$(date '+%F %T') start $out: $*"
    timeout 900 "$PY" -B "$@" > "$out" 2>&1
    rc=$?
    # $? is read on its own line. Inside the echo below it would be the
    # status of the command substitution, always 0, and the committed queue
    # logs were made with that form: their "rc" is date's, not the run's
    # (the study's 11; complete.py is the check of the runs instead).
    echo "$(date '+%F %T') end $out (rc $rc)"
}
run pools_run.fp64.out.txt pools_run.py fp64
run regions_run.fp64-pow.out.txt regions_run.py fp64 pow 400
run regions_run.fp64-powr.out.txt regions_run.py fp64 powr 200
for f in pown rootn compound; do
    run regions_run.fp64-$f.out.txt regions_run.py fp64 $f 150
done
run specials.fp64.out.txt specials.py fp64
run costs.fp64.out.txt costs.py fp64
run costs.fp128.out.txt costs.py fp128
run costs.fp256.out.txt costs.py fp256
run plants.fp64.out.txt plants.py fp64
for r in wide near1 edge redb small negint sub tinyy hugey; do
    run budget.fp64-pow-$r.out.txt budget.py fp64 pow $r 120 1
done
run budget.fp64-powr-wide.out.txt budget.py fp64 powr wide 120 1
for r in int int-neg int17 int1000 int31 int63; do
    run budget.fp64-pown-$r.out.txt budget.py fp64 pown $r 120 1
done
run budget.fp64-rootn-int.out.txt budget.py fp64 rootn int 120 1
run budget.fp64-rootn-int17.out.txt budget.py fp64 rootn int17 120 1
run budget.fp64-compound-int.out.txt budget.py fp64 compound int 120 1
run budget.fp64-compound-int1000.out.txt budget.py fp64 compound int1000 120 1
run budget.fp64-pow-edge-bound_tight.out.txt budget.py fp64 pow edge 120 1 bound_tight
for fam in intpow root2k pow2 near1 dominant edges smallint; do
    run census.fp64-$fam.out.txt census.py fp64 $fam 300
done
run rate.fp64-pow-wide.out.txt rate.py fp64 pow wide 600 8 3
run rewrites.fp64.out.txt rewrites.py fp64
run share.fp64.out.txt share.py fp64
run share.fp128.out.txt share.py fp128
run share.fp256.out.txt share.py fp256
run onseq.fp64.out.txt onseq.py fp64 pow powr pown rootn compound --ns 2,-2,3,17,9223372036854775807,-9223372036854775808
