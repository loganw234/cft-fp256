#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# UCBTEST's ucbdivtest, ucbsqrtest and ucbmultest with libcft as the
# arithmetic under test (docs/EXTERNAL-GENERATORS.md).
#
#   host/tools/ucb_run.sh UCBDIR HOSTDIR BUILDDIR [NTESTS]
#   host/tools/ucb_run.sh --replay BUILDDIR
#
#   UCBDIR    the extracted archive's directory that holds ucbtest/ and
#             ucbctest/. It is READ and never written, and nothing of it is
#             copied into this repository.
#   HOSTDIR   host/ of a tree whose libcft.a is built (make -C host libcft.a).
#   BUILDDIR  a directory that does not exist yet: this script makes it, and
#             puts every object, binary, log and dump of the run in it. It
#             refuses a directory that exists, so it can never touch what
#             another run left. (--replay takes the directory a run made.)
#   NTESTS    UCBTEST's -DNTESTS, the number of divisors (division), of cases
#             /4 (square root) or of draws (multiplication); default 100000.
#
# Environment: UCB_PRECS (default "SP DP") and UCB_TESTS (default
# "div sqr mul") select what is built and run; CFT_SOAK_ARTIFACT names an
# .xclbin to run on instead of the software backend, as the soak tools read
# it; CFT_UCB_HOSTCHECK=1 is set here (every call is also computed by the
# host CPU and compared, flags included; see host/tools/ucb_hooks.c) and
# CFT_UCB_DUMP=BUILDDIR/dump makes the hooks write the operands of every call
# for replay through cft-tf-subject and testfloat_ver. The replay runs at the
# end of a run, and alone under --replay, when UCB_REPLAY_TF (the directory
# holding the built testfloat_ver) and UCB_REPLAY_SUBJECT (the built
# cft-tf-subject) are both set: SoftFloat then judges the same hard cases.
#
# The UCBTEST sources are compiled as they are, with -std=gnu89 (they are
# Kernighan and Ritchie C of 1995) and -w, from UCBDIR into BUILDDIR; what
# replaces its platform layer is ucb_hooks.c, ours. The verdict of each run
# is UCBTEST's own: exit status 0 and a UCBPASS line, or 42 and UCBFAIL; and
# the host check's: exit 3 on a mismatch. This script exits 1 if any run did
# not pass, 2 on a usage or build error.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
fail=0

replay() {
    [ -n "${UCB_REPLAY_TF:-}" ] && [ -n "${UCB_REPLAY_SUBJECT:-}" ] || {
        echo "ucb_run.sh: the replay needs UCB_REPLAY_TF and UCB_REPLAY_SUBJECT" >&2
        return 2; }
    for d in "$1"/dump.*; do
        [ -f "$d" ] || continue
        case $d in *.err|*.out) continue;; esac
        b=${d##*/}; rest=${b#dump.}; op=${rest%%.*}; mode=${rest#*.}
        case $op in
            divs) fn=f32_div;;   divd) fn=f64_div;;
            sqrts) fn=f32_sqrt;; sqrtd) fn=f64_sqrt;;
            muls) fn=f32_mul;;   muld) fn=f64_mul;;
            *) echo "ucb_run.sh: unknown dump $b" >&2; fail=1; continue;;
        esac
        start=$(date +%s)
        "$UCB_REPLAY_SUBJECT" $fn $mode < "$d" 2> "$d.subject.err" \
            | "$UCB_REPLAY_TF/testfloat_ver" -errors 0 -r$mode -tininessafter \
                $fn > "$d.ver.out" 2> "$d.ver.err"
        st=$?
        tests=$(tr '\r' '\n' < "$d.ver.err" | grep -o '[0-9]* tests performed[^.]*' | tail -1)
        echo "replay $fn $mode: ${tests:-no count} ($(( $(date +%s) - start ))s)"
        [ "$st" = 0 ] || fail=1
    done
}

if [ "${1:-}" = "--replay" ] && [ $# -eq 2 ]; then
    replay "$2" || exit 2
    exit $fail
fi

if [ $# -lt 3 ] || [ $# -gt 4 ]; then
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
fi
UCB=$1
HOST=$2
BUILD=$3
NTESTS=${4:-100000}
PRECS=${UCB_PRECS:-"SP DP"}
TESTS=${UCB_TESTS:-"div sqr mul"}

[ -f "$UCB/ucbtest/div.c" ] && [ -f "$UCB/ucbctest/divmain.c" ] || {
    echo "ucb_run.sh: $UCB has no ucbtest/div.c and ucbctest/divmain.c" >&2; exit 2; }
[ -f "$HOST/libcft.a" ] || {
    echo "ucb_run.sh: no $HOST/libcft.a (make -C host libcft.a)" >&2; exit 2; }
mkdir "$BUILD" || { echo "ucb_run.sh: $BUILD exists or cannot be made" >&2; exit 2; }

${CC:-cc} -std=c99 -O2 -Wall -Wextra -Wpedantic -Wshadow -frounding-math \
    -fno-math-errno -I"$HOST/include" -c "$HERE/ucb_hooks.c" \
    -o "$BUILD/ucb_hooks.o" || exit 2

for prec in $PRECS; do
    for t in $TESTS; do
        name=ucb${t}test_$prec
        ${CC:-cc} -std=gnu89 -w -O1 -D$prec -DNTESTS=$NTESTS \
            -I"$UCB/ucbtest" "$UCB/ucbctest/${t}main.c" "$UCB/ucbtest/$t.c" \
            "$UCB/ucbtest/init.c" "$BUILD/ucb_hooks.o" "$HOST/libcft.a" -lm \
            -o "$BUILD/$name" || { echo "ucb_run.sh: $name did not build" >&2; exit 2; }
        start=$(date +%s)
        CFT_UCB_HOSTCHECK=1 CFT_UCB_DUMP="$BUILD/dump" \
            nice -n 10 "$BUILD/$name" > "$BUILD/$name.log" 2>&1
        rc=$?
        secs=$(( $(date +%s) - start ))
        verdict=$(grep -o 'UCBPASS\|UCBFAIL' "$BUILD/$name.log" | head -1)
        cases=$(grep -o 'out of [0-9]* cases' "$BUILD/$name.log" | head -1)
        echo "$name: rc=$rc ${verdict:-no verdict} ${cases:-} ${secs}s"
        grep 'cft-ucb-hooks:' "$BUILD/$name.log" | sed 's/^/    /'
        [ $rc -eq 0 ] && [ "$verdict" = UCBPASS ] || fail=1
    done
done

if [ -n "${UCB_REPLAY_TF:-}" ] && [ -n "${UCB_REPLAY_SUBJECT:-}" ]; then
    replay "$BUILD" || fail=1
fi
exit $fail
