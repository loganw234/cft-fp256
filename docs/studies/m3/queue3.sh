#!/bin/sh
# M3 model: the fp64 runs made again after the signed-zero fix (the study's
# 3.6, item 7), after queue2.sh, one at a time, unniced; as queue1.sh.
#
#   sh queue3.sh PYTHON > queue3.log
PY=${1:-python}
run() {
    out=$1; shift
    echo "$(date '+%F %T') start $out: $*"
    timeout 900 "$PY" -B "$@" > "$out" 2>&1
    echo "$(date '+%F %T') end $out (rc $?)"
}
run regions_run.fp64-pow.out.txt regions_run.py fp64 pow 400
run specials.fp64.out.txt specials.py fp64
run costs.fp64.out.txt costs.py fp64
run costs.fp128.out.txt costs.py fp128
run costs.fp256.out.txt costs.py fp256
run share.fp64.out.txt share.py fp64
run share.fp128.out.txt share.py fp128
run share.fp256.out.txt share.py fp256
run rate.fp64-pow-wide.out.txt rate.py fp64 pow wide 600 8 3
run onseq.fp64.out.txt onseq.py fp64 pow powr pown rootn compound --ns 2,-2,3,17,9223372036854775807,-9223372036854775808
run pools_run.fp64.out.txt pools_run.py fp64
run budget.fp64-pow-negedge.out.txt budget.py fp64 pow negedge 120 1
run plants.fp64.out.txt plants.py fp64
for fam in intpow root2k pow2 smallint dominant; do
    run census.fp64-$fam.out.txt census.py fp64 $fam 300
done
for fam in intpow pow2; do
    run census.fp128-$fam.out.txt census.py fp128 $fam 150
    run census.fp256-$fam.out.txt census.py fp256 $fam 150
done
run regions_run.fp128-pow-rhoedge.out.txt regions_run.py fp128 pow 80 rhoedge
run regions_run.fp256-pow-rhoedge.out.txt regions_run.py fp256 pow 80 rhoedge
run regions_run.fp128-powr-rhoedge.out.txt regions_run.py fp128 powr 40 rhoedge
run regions_run.fp256-powr-rhoedge.out.txt regions_run.py fp256 powr 40 rhoedge
run rate.fp128-pow-wide-g2.out.txt rate.py fp128 pow wide 300 2 3
run rate.fp256-pow-wide-g2.out.txt rate.py fp256 pow wide 200 2 3
run rate.fp64-pow-wide-g2.out.txt rate.py fp64 pow wide 300 2 3
