#!/bin/sh
# M4 model: run a list of the model's scripts one at a time, niced, each
# output kept as <name>.out.txt beside the model, each start and end time
# in the named log (scratch). Run from this directory:
#
#   sh queue.sh LOG "out-name|script args" ...
#   sh queue.sh LOG -f JOBFILE        (one "out-name|script args" a line)
#
# The rc in queue1.log to queue9.log is date's, not the job's: the end line
# expanded $(date) before $?, so every job there reads rc=0, the two that
# crashed included (the study's 3.6, item 8). Fixed after queue 9; read
# those runs' outputs, not their rc.
PY=${PY:-python}
LOG=$1
shift
run() {
    out=${1%%|*}
    cmd=${1#*|}
    echo "$(date '+%F %T') start $out: $cmd" >> "$LOG"
    nice -n 10 "$PY" -B $cmd > "$out.out.txt" 2>&1
    rc=$?
    echo "$(date '+%F %T') end $out rc=$rc" >> "$LOG"
}
if [ "$1" = "-f" ]; then
    while IFS= read -r job; do
        [ -n "$job" ] && run "$job"
    done < "$2"
else
    for job in "$@"; do
        run "$job"
    done
fi
