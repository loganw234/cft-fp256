#!/bin/sh
# M3 model: the wider formats' runs, after queue1.sh, one at a time, each
# under about ten minutes, unniced; as queue1.sh.
#
#   sh queue2.sh PYTHON > queue2.log
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
run bits.out.txt bits.py
run rewrites.fp64.out.txt rewrites.py fp64
run share.fp64.out.txt share.py fp64
run pools_run.fp64.out.txt pools_run.py fp64
run regions_run.fp64-pow.out.txt regions_run.py fp64 pow 400
run regions_run.fp64-powr.out.txt regions_run.py fp64 powr 200
for g in pown rootn compound; do
    run regions_run.fp64-$g.out.txt regions_run.py fp64 $g 150
done
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
for fam in intpow root2k pow2 near1 dominant edges smallint; do
    run census.fp64-$fam.out.txt census.py fp64 $fam 300
done
run plants.fp64.out.txt plants.py fp64
run census.fp64-hard3p.out.txt census.py fp64 hard3p 400
run sched.fp64.out.txt sched.py fp64
run sched.fp128.out.txt sched.py fp128
run sched.fp256.out.txt sched.py fp256
run poolmarks.fp64.out.txt poolmarks.py fp64
for f in fp128 fp256; do
    run pools_run.$f-pow.out.txt pools_run.py $f pow powr
    run pools_run.$f-pown.out.txt pools_run.py $f pown
    run pools_run.$f-rootn.out.txt pools_run.py $f rootn
    run pools_run.$f-compound.out.txt pools_run.py $f compound
    run regions_run.$f-pow.out.txt regions_run.py $f pow 80
    run regions_run.$f-powr.out.txt regions_run.py $f powr 40
    for g in pown rootn compound; do
        run regions_run.$f-$g.out.txt regions_run.py $f $g 40
    done
    run specials.$f.out.txt specials.py $f
    for r in wide near1 edge redb small negint sub tinyy hugey; do
        run budget.$f-pow-$r.out.txt budget.py $f pow $r 40 1
    done
    for g in pown rootn compound; do
        run budget.$f-$g-int.out.txt budget.py $f $g int 40 1
    done
    run census.$f-intpow.out.txt census.py $f intpow 150
    run census.$f-pow2.out.txt census.py $f pow2 150
    run census.$f-hard3p.out.txt census.py $f hard3p 200
done
run budget.fp128-pow-wide-log_short.out.txt budget.py fp128 pow wide 40 1 log_short
run plants.fp256.out.txt plants.py fp256
run rate.fp128-pow-wide.out.txt rate.py fp128 pow wide 300 8 3
run onseq.fp128.out.txt onseq.py fp128 pow powr pown rootn compound --ns 2,-2,3,17,9223372036854775807,-9223372036854775808
run onseq.fp256.out.txt onseq.py fp256 pow powr pown rootn compound --ns 2,-2,3,17,9223372036854775807,-9223372036854775808
