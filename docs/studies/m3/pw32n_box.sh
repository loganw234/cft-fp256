#!/bin/sh
# M3XN: the larger runs of pw32n (fp32 pown, rootn and compound as a triple
# word), for the lead to run on amd-arc-box (agents do not touch the box). Run
# from a clone of the commit, in docs/studies/m3/:
#
#   sh pw32n_box.sh python3 OUTDIR [JOBS] [bad]
#
# One job is one run of pw32n_run.py, its output in OUTDIR; JOBS at a time
# (default 8), each single-threaded. The fourth argument `bad` adds one job
# that must fail (an unknown region), to show the script's status fails on a
# doctored job (pw32n_box-demo.out.txt); leave it out for the real run.
#
# ESTIMATES (the desktop's own times of the 300-lane runs: pw32n_bound-pown.
# out.txt 254 s for its 13 regions, 9 of them with lanes, so about 0.09 s a
# measured lane, a region of 12,000 lanes about 18 minutes, memory under
# 300 MB; the regions with no lane end at once). The budget jobs: pown 13
# regions, rootn 13, compound 17 = 43 jobs of 12,000 lanes, about 13 hours of
# one core, about 1.7 hours at 8 jobs. The rate at 50,000 lanes (rne and rtz,
# two n a function, one function a job): about 4 ms a lane a cell, 4 cells,
# about 15 minutes a function. Needs python3 and mpmath only (and MPFR is not
# used); it writes nothing but OUTDIR's files. The box's cores are 36 threads
# (CLAUDE.md); these are not box measurements.
PY=${1:-python3}
OUT=${2:-box-out}
JOBS=${3:-8}
BAD=${4:-}
mkdir -p "$OUT"
{
for fn in pown rootn compound; do
    regs="int int-neg int17 int31 int63 int1000 int16777217 int1099511627776 int281474976710657 zone zone1000 zone-3 zone17"
    if [ "$fn" = compound ]; then
        regs="$regs cint2147483647 cint-9223372036854775808 cint16777217 cint4611686018427388929"
    fi
    for r in $regs; do
        echo "pw32n_run.py bound $fn 12000 - - $r > $OUT/pw32n_bound-$fn-$r.out.txt"
    done
    echo "pw32n_run.py rate wide 50000 $fn > $OUT/pw32n_rate-wide-$fn.out.txt"
done
if [ "$BAD" = bad ]; then
    echo "pw32n_run.py bound pown 10 - - nosuchregion > $OUT/pw32n_bound-pown-nosuchregion.out.txt"
fi
} | xargs -P "$JOBS" -I{} sh -c "\"$PY\" -B {}"
# xargs answers 123 when any job exited 1 to 125 (124 for 255, 125 for a
# signal, 126 and 127 for a command that cannot run): the script's own status
# is that, so a failed job fails the run; the `done` line is not a status,
# this is
RC=$?
echo "done $(date '+%F %T') xargs status $RC ($([ "$RC" -eq 0 ] && echo 'every job exited 0' || echo 'AT LEAST ONE JOB FAILED: read OUTDIR and the run log'))"
exit "$RC"
