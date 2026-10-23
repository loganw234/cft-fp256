#!/bin/sh
# M4 model: run a list of the model's scripts one at a time, niced, each
# output kept as <name>.out.txt beside the model, each start and end time
# in the named log (scratch). Run from this directory:
#
#   sh queue.sh LOG "out-name|script args" ...
#   sh queue.sh LOG -f JOBFILE        (one "out-name|script args" a line)
PY=${PY:-python}
LOG=$1
shift
run() {
    out=${1%%|*}
    cmd=${1#*|}
    echo "$(date '+%F %T') start $out: $cmd" >> "$LOG"
    nice -n 10 "$PY" -B $cmd > "$out.out.txt" 2>&1
    echo "$(date '+%F %T') end $out rc=$?" >> "$LOG"
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
