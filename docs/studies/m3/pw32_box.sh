#!/bin/sh
# M3X: the larger runs of pw32 (fp32 pow and powr as a triple word), for the
# lead to run on amd-arc-box (agents do not touch the box). Run from a clone
# of the commit, in docs/studies/m3/:
#
#   sh pw32_box.sh python3 OUTDIR [JOBS]
#
# One job is one run of pw32_run.py, its output in OUTDIR; JOBS at a time
# (default 8), each single-threaded.
#
# ESTIMATES (the desktop's own times, each measured while other work ran, by
# lane): the budget 300 lanes of one region in 6 to 14 s of the 12-region
# run's 137 s (pw32_bound-pow.out.txt), so about 0.05 s a lane: a region of
# 12,000 lanes is about 10 minutes, memory under 300 MB; the 24 budget jobs
# are about 4 hours of one core, 30 minutes at 8 jobs. The rate at 50,000
# lanes (rne and rtz, one function): about 4 ms a lane a cell, 7 minutes a
# function. The scratch figures are not box measurements; the box's cores
# are 36 threads and its Python 3.12 (CLAUDE.md). It needs python3 and
# mpmath only, and writes nothing but OUTDIR's files.
PY=${1:-python3}
OUT=${2:-box-out}
JOBS=${3:-8}
mkdir -p "$OUT"
{
for fn in pow powr; do
    for r in wide near1 edge redb small negint sub tinyy hugey negedge rhoedge zone; do
        echo "pw32_run.py bound $fn 12000 - - $r > $OUT/pw32_bound-$fn-$r.out.txt"
    done
    echo "pw32_run.py rate wide 50000 $fn > $OUT/pw32_rate-wide-$fn.out.txt"
done
} | xargs -P "$JOBS" -I{} sh -c "\"$PY\" -B {}"
# xargs answers 123 when any job exited 1 to 125 (124 for 255, 125 for a
# signal, 126 and 127 for a command that cannot run): the script's own status is that, so a failed job
# fails the run; the `done` line is not a status, this is
RC=$?
echo "done $(date '+%F %T') xargs status $RC ($([ "$RC" -eq 0 ] && echo 'every job exited 0' || echo 'AT LEAST ONE JOB FAILED: read OUTDIR and the run log'))"
exit "$RC"
