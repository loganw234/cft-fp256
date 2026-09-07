#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Replay every checked-in reproducer. This is the regression gate for
# the findings in docs/VALIDATION.md's 2026-09-07 entry: a fix that is
# reverted makes this print what went wrong and exit nonzero. Run from
# host/fuzz.
#
# Three classes, because the three findings failed in three different
# ways and a replay that only knows about crashes would pass on two of
# them:
#
#   crashes/<target>/          an input to an in-process harness; it
#                              must not crash
#   crashes/ckpt/*.ckpt        a checkpoint; the tool must REFUSE it by
#                              name (exit 2 and a message), not crash
#                              and not resume
#   crashes/program-differential/  an image; the C loader's verdict must
#                              be the golden model's, and for these it
#                              is REFUSE
set -u

ASAN_OPTIONS="abort_on_error=0:detect_leaks=0:allocator_may_return_null=1"
UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1"
export ASAN_OPTIONS UBSAN_OPTIONS

rc=0
n=0

# ---- the in-process harnesses --------------------------------------
for t in program serve client; do
    bin=./fuzz-$t
    dir=crashes/$t
    [ -d "$dir" ] || continue
    files=$(find "$dir" -type f 2>/dev/null | sort)
    [ -z "$files" ] && continue
    if [ ! -x "$bin" ]; then
        echo "  SKIP  $dir (no $bin - run make -C host fuzz)"
        rc=1
        continue
    fi
    for f in $files; do
        n=$((n + 1))
        if "$bin" --run "$f" > /dev/null 2>&1; then
            echo "  ok    $f"
        else
            echo "  CRASH $f"
            "$bin" --run "$f" 2>&1 | tail -20
            rc=1
        fi
    done
done

# ---- the workload tools' checkpoints --------------------------------
#
# The tool that reads each file is named by the file: collatz-*.ckpt is
# cft-collatz's. A sanitised build in bin/ is preferred (run_ckpt.sh
# makes them); the ordinary build in host/ will do, and catches the
# refusal even though it cannot see a bad write.
ckpt_args() {
    case $1 in
    collatz)  echo "--batch 64 --steps-per-call 7 --stop-after-passes 3 --quiet" ;;
    enclose)  echo "--format fp64 --points 64 --batch 23 --stop-after-passes 4 --quiet" ;;
    mersenne) echo "--exponents 521 --batch 9 --stop-after-squarings 137 --quiet" ;;
    orbits)   echo "--problem kepler --format fp256 --members 8 --periods 2 --steps-per-period 96 --batch 5 --stop-after-steps 37 --quiet" ;;
    zoom)     echo "--ref-iters 2000 --no-pixels --steps-per-call 37 --stop-after-passes 5 --quiet" ;;
    esac
}

for f in $(find crashes/ckpt -name '*.ckpt' 2>/dev/null | sort); do
    tool=$(basename "$f" | sed 's/-.*//')
    bin=bin/cft-$tool
    [ -x "$bin" ] || bin=../cft-$tool
    [ -x "$bin" ] || bin=../cft-$tool.exe
    if [ ! -x "$bin" ]; then
        echo "  SKIP  $f (no cft-$tool built)"
        rc=1
        continue
    fi
    n=$((n + 1))
    # shellcheck disable=SC2046
    err=$("$bin" --resume --checkpoint "$f" $(ckpt_args "$tool") 2>&1 >/dev/null)
    st=$?
    if [ "$st" -eq 2 ] && [ -n "$err" ]; then
        echo "  ok    $f -> $(echo "$err" | head -1)"
    else
        echo "  WRONG $f exited $st rather than refusing by name"
        echo "$err" | head -6
        rc=1
    fi
done

# ---- the loader against the model -----------------------------------
for f in $(find crashes/program-differential -type f 2>/dev/null | sort); do
    if [ ! -x ./fuzz-program ]; then
        echo "  SKIP  $f (no ./fuzz-program)"
        rc=1
        continue
    fi
    n=$((n + 1))
    v=$(./fuzz-program --verdict "$f" 2>&1)
    case "$v" in
    *REFUSE*) echo "  ok    $f -> $(echo "$v" | sed 's/^[^ ]* //')" ;;
    *)        echo "  WRONG $f -> $v (the golden model refuses this image)"
              rc=1 ;;
    esac
done

echo "$n reproducer(s) replayed"
if [ "$n" -eq 0 ]; then
    echo "fuzz-repro: NOTHING WAS REPLAYED - a gate that checks nothing"
    exit 1
fi
if [ "$rc" -eq 0 ]; then
    echo "fuzz-repro: every checked-in reproducer is handled"
else
    echo "fuzz-repro: FAILED"
fi
exit $rc
