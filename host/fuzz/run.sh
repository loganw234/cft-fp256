#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Run each in-process harness for a bounded time, restarting it when a
# crash ends the process so the rest of the budget is still spent
# fuzzing. Run from host/fuzz.
#
#   ./run.sh [SECONDS_PER_TARGET] [TARGET ...]
#
# The corpus grows in corpus/<target>; crashes and hangs land in
# crashes/<target> with the exact input that produced them, which is
# what fuzz-repro replays.
set -u

SECONDS_PER=${1:-60}
shift 2>/dev/null || true
TARGETS=${*:-"program serve client"}

# abort_on_error so a sanitiser finding reaches the engine's handler,
# which is what writes the input out; halt_on_error so the first
# undefined operation is the one reported rather than the last.
#
# allocator_may_return_null=1 on purpose: a BUF_ALLOC of two exabytes
# is a legitimate request for cft_alloc to refuse with
# CFT_ERR_OUT_OF_MEMORY, and it does. Without this ASan aborts on the
# size instead, and the fuzzer spends its budget re-finding a policy
# rather than a fault.
#
# detect_leaks=0 because the engine's corpus is deliberately never
# freed and LeakSanitizer at exit would report the fuzzer, not the
# target. leaks.sh replays the seed corpus with detection ON, which is
# where a leak in the target actually shows up.
ASAN_OPTIONS="abort_on_error=1:detect_leaks=0:allocator_may_return_null=1"
UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1"
export ASAN_OPTIONS UBSAN_OPTIONS

for t in $TARGETS; do
    bin=./fuzz-$t
    if [ ! -x "$bin" ]; then
        echo "$t: SKIP (no $bin - run make -C host fuzz)"
        continue
    fi
    mkdir -p "corpus/$t" "crashes/$t"
    start=$(date +%s)
    seed=1
    while :; do
        now=$(date +%s)
        left=$((SECONDS_PER - (now - start)))
        [ "$left" -le 0 ] && break
        "$bin" --seconds "$left" --seed "$seed" \
               --corpus "corpus/$t" --crashes "crashes/$t"
        rc=$?
        [ "$rc" -eq 0 ] && break
        echo "$t: harness exited $rc (input saved under crashes/$t); restarting"
        seed=$((seed + 1))
    done
    n=$(find "crashes/$t" -type f 2>/dev/null | wc -l)
    echo "$t: done, $n file(s) in crashes/$t"
done
