#!/bin/sh
# M3 model: the larger samples, for the lead to run on amd-arc-box (the
# study's 3.2 and 3.3; agents do not touch the box). Run from a clone of the
# study's commit, in docs/studies/m3/:
#
#   sh box_m3s.sh python3 OUTDIR [JOBS]
#
# Each job is one run of the model's own scripts, its output in OUTDIR; the
# jobs run JOBS at a time (default 8), each single-threaded. ESTIMATE: about
# 30 minutes at 8 jobs and under 300 MB a job (the desktop's runs at a
# tenth of these sizes took 10 to 60 s a region at fp64 and up to 4 times
# that at fp256). It needs python3 and mpmath only (1.3 or 1.4: the model
# reads mpf values through _mpf_ and never calls to_man_exp; the stage's
# transcend_check.py is imported for its pools and loads no library at
# import), and writes nothing but OUTDIR's files (each run's stdout; -B and
# the model's own sys.dont_write_bytecode keep __pycache__ out).
PY=${1:-python3}
OUT=${2:-box-out}
JOBS=${3:-8}
mkdir -p "$OUT"
{
for r in wide near1 edge redb small negint sub tinyy hugey negedge rhoedge; do
    echo "budget.py fp64 pow $r 2000 7 > $OUT/budget.fp64-pow-$r.out.txt"
    echo "budget.py fp128 pow $r 500 7 > $OUT/budget.fp128-pow-$r.out.txt"
    echo "budget.py fp256 pow $r 300 7 > $OUT/budget.fp256-pow-$r.out.txt"
done
for g in pown rootn compound; do
    for f in fp64 fp128 fp256; do
        echo "budget.py $f $g int 500 7 > $OUT/budget.$f-$g-int.out.txt"
    done
done
for f in fp64 fp128 fp256; do
    echo "regions_run.py $f pow 1000 > $OUT/regions_run.$f-pow.out.txt"
    echo "regions_run.py $f powr 500 > $OUT/regions_run.$f-powr.out.txt"
    for g in pown rootn compound; do
        echo "regions_run.py $f $g 400 > $OUT/regions_run.$f-$g.out.txt"
    done
done
echo "rate.py fp64 pow wide 5000 8 7 > $OUT/rate.fp64-pow-wide.out.txt"
echo "rate.py fp64 pow near1 3000 8 7 > $OUT/rate.fp64-pow-near1.out.txt"
echo "rate.py fp128 pow wide 2000 8 7 > $OUT/rate.fp128-pow-wide.out.txt"
for fam in intpow root2k pow2 near1 dominant edges smallint hard3p; do
    echo "census.py fp64 $fam 3000 > $OUT/census.fp64-$fam.out.txt"
done
} | xargs -P "$JOBS" -I{} sh -c "\"$PY\" -B {}"
echo "done $(date '+%F %T')"
