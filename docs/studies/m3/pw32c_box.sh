#!/bin/sh
# M3XN2: the larger runs of pw32c (compound at fp32 as a triple word, the
# follow-up to pw32n), for the lead to run on amd-arc-box (agents do not touch
# the box). Run from a clone of the commit, in docs/studies/m3/:
#
#   sh pw32c_box.sh python3 OUTDIR LIST [JOBS] [bad]
#
# LIST is one of
#   scan    the n-scan: pw32c_run.py cells' (n, region) cells, 60 of them (the
#           list lives in pw32c_run.py: SCAN_N), each at SCAN_LANES (2,000)
#           lanes, on the UNFIXED model (--model n, the control) and on the
#           FIX (--model c --variant $FIX), seed 1: 2 x 60 = 120 jobs
#   worst   reads OUTDIR's scan outputs of the unfixed model and takes the six
#           n whose cell total is largest (pw32c_run.py worst prints the line
#           `WORST n region total`, six of them, which this script echoes),
#           and runs each at WORST_LANES (12,000) lanes on both models:
#           6 x 2 = 12 jobs. Run it AFTER `scan` has finished.
#   full    compound's 17 regions of the bound at FULL_LANES (12,000) lanes on
#           the fix (17 jobs), the unfixed control at int1000 and zone1000
#           (2 jobs, which must print 1.377296 and 1.007524 as the bound plus
#           residual of pw32n_bound-compound's box run), and the attribution
#           of int1000 and zone1000 at 12,000 lanes on the control and on the
#           fix (4 jobs: pw32c_run.py attribute): 23 jobs
#   rate    the mark-rate law's cells at RATE_LANES (50,000) lanes, compound,
#           on the fix, two n, rne and rtz: 1 job (pw32c_run.py rate wide)
#
# $FIX is the variant name (environment; default `none`, the control's own
# instructions through pw32c.build). The count of cells is limited to the first
# LIMIT of the list when LIMIT is set (the desktop's test of the script runs
# 3 cells at 30 lanes: SCAN_LANES=30 WORST_LANES=30 FULL_LANES=30 LIMIT=3; that
# shows the script works, and says nothing of the budget: 300 lanes read 0.331
# at zone1000 where 12,000 read 1.0075).
#
# One job is one run of pw32c_run.py, its output in OUTDIR; JOBS at a time
# (default 8; 16 is what the estimates below assume), each single-threaded. The
# fifth argument `bad` adds one job that must fail (an unknown region), to show
# the script's status fails on a doctored job (pw32c_box-demo.out.txt); leave
# it out for the real run.
#
# ESTIMATES. From M3XN's box outputs (pw32n_bound at 12,000 lanes: int1000 979
# s, zone1000 1,122 s, the others up to 1,285 s; memory under 300 MB a job):
# a 12,000-lane region takes 979 to 1,285 s, so a 2,000-lane cell takes 2000 /
# 12000 of that, 163 to 214 s (a region with fewer measured lanes takes less).
#   scan   120 jobs x 163 to 214 s / 16 jobs = 1,222 to 1,605 s, 20 to 27
#          minutes (COMPUTED; an upper estimate, many cells at a large n have
#          few lanes and end at once)
#   worst  12 jobs of 12,000 lanes in one wave of 16: 979 to 1,285 s, 16 to 21
#          minutes (the fix's jobs run longer by its extra instructions: the
#          fixed model's cost per lane is within ~1.2 times the control's, a
#          GUESS to be replaced by the scan's own per-job times, which the
#          CELL lines carry as s=)
#   full   23 jobs of 12,000 lanes in two waves of 16 and 7: 2 x (979 to
#          1,285 s) = 33 to 43 minutes
#   rate   50,000 lanes x 4 cells (2 n, rne and rtz) at about 4 ms a lane a
#          cell (pw32n_box.sh's figure): about 800 s
# Memory: 16 jobs x under 300 MB = under 4.8 GB (ESTIMATE). Needs python3 and
# mpmath only (MPFR is not used); it writes nothing but OUTDIR's files (python
# runs with -B). These are not box measurements.
PY=${1:-python3}
OUT=${2:-box-out}
LIST=${3:-scan}
JOBS=${4:-8}
BAD=${5:-}
FIX=${FIX:-none}
SCAN_LANES=${SCAN_LANES:-2000}
WORST_LANES=${WORST_LANES:-12000}
FULL_LANES=${FULL_LANES:-12000}
RATE_LANES=${RATE_LANES:-50000}
LIMIT=${LIMIT:-100000}
mkdir -p "$OUT"

lim() { head -n "$LIMIT"; }

jobs_scan() {
    "$PY" -B pw32c_run.py cells | lim | while read -r n r; do
        echo "--model n cell $n $r $SCAN_LANES 1 > $OUT/pw32c_cell-n-$r.out.txt"
        echo "--model c --variant $FIX cell $n $r $SCAN_LANES 1 > $OUT/pw32c_cell-c-$r.out.txt"
    done
}

jobs_worst() {
    # the six n of the unfixed scan with the largest total (one line each)
    "$PY" -B pw32c_run.py worst "$OUT"/pw32c_cell-n-*.out.txt 6 > "$OUT/pw32c_worst6.out.txt" || return 1
    cat "$OUT/pw32c_worst6.out.txt" >&2
    lim < "$OUT/pw32c_worst6.out.txt" | while read -r _w n r _t; do
        echo "--model n cell $n $r $WORST_LANES 1 > $OUT/pw32c_cellW-n-$r.out.txt"
        echo "--model c --variant $FIX cell $n $r $WORST_LANES 1 > $OUT/pw32c_cellW-c-$r.out.txt"
    done
}

jobs_full() {
    for r in int int-neg int17 int31 int63 int1000 int16777217 int1099511627776 int281474976710657 zone zone1000 zone-3 zone17 cint2147483647 cint-9223372036854775808 cint16777217 cint4611686018427388929; do
        echo "--model c --variant $FIX bound $FULL_LANES - - $r > $OUT/pw32c_bound-c-$r.out.txt"
    done | lim
    for r in int1000 zone1000; do
        echo "--model n bound $FULL_LANES - - $r > $OUT/pw32c_bound-n-$r.out.txt"
        echo "--model n attribute $r $FULL_LANES 1 > $OUT/pw32c_attribute-n-$r.out.txt"
        echo "--model c --variant $FIX attribute $r $FULL_LANES 1 > $OUT/pw32c_attribute-c-$r.out.txt"
    done
}

jobs_rate() {
    echo "--model c --variant $FIX rate wide $RATE_LANES > $OUT/pw32c_rate-wide.out.txt"
}

{
case "$LIST" in
    scan) jobs_scan ;;
    worst) jobs_worst ;;
    full) jobs_full ;;
    rate) jobs_rate ;;
    *) echo "unknown list $LIST" >&2; exit 2 ;;
esac
if [ "$BAD" = bad ]; then
    echo "--model c cell 3 nosuchregion 10 1 > $OUT/pw32c_cell-c-nosuchregion.out.txt"
fi
} > "$OUT/pw32c_jobs-$LIST.txt"
if [ "$(wc -l < "$OUT/pw32c_jobs-$LIST.txt")" -eq 0 ]; then
    echo "NO JOBS for list $LIST (an empty list is not a pass)"
    exit 3
fi
echo "list $LIST: $(wc -l < "$OUT/pw32c_jobs-$LIST.txt") jobs, $JOBS at a time, FIX=$FIX, $(date '+%F %T')"
xargs -P "$JOBS" -I{} sh -c "\"$PY\" -B pw32c_run.py {}" < "$OUT/pw32c_jobs-$LIST.txt"
# xargs answers 123 when any job exited 1 to 125 (124 for 255, 125 for a
# signal, 126 and 127 for a command that cannot run): the script's own status
# is that, so a failed job fails the run; the `done` line is not a status,
# this is
RC=$?
echo "done $(date '+%F %T') list $LIST xargs status $RC ($([ "$RC" -eq 0 ] && echo 'every job exited 0' || echo 'AT LEAST ONE JOB FAILED: read OUTDIR and the run log'))"
exit "$RC"
