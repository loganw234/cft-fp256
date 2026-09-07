#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Replay each target's corpus once with LeakSanitizer ON. The fuzzing
# loop runs with detect_leaks=0 because the engine's own corpus is
# deliberately never freed and LSan at exit would be reporting the
# fuzzer; --run replays without ever growing that corpus, so what LSan
# sees here is the target. Run from host/fuzz.
set -u

ASAN_OPTIONS="detect_leaks=1:allocator_may_return_null=1:abort_on_error=0"
UBSAN_OPTIONS="print_stacktrace=1"
export ASAN_OPTIONS UBSAN_OPTIONS

rc=0
for t in program serve client; do
    bin=./fuzz-$t
    dir=corpus/$t
    if [ ! -x "$bin" ] || [ ! -d "$dir" ]; then
        echo "$t: SKIP"
        continue
    fi
    n=$(find "$dir" -type f | wc -l)
    # shellcheck disable=SC2046
    if "$bin" --run $(find "$dir" -type f | sort) > /dev/null 2>/tmp/leak-$t; then
        echo "$t: $n corpus entries replayed, no leak reported"
    else
        echo "$t: LEAK or fault over $n corpus entries"
        head -30 /tmp/leak-$t
        rc=1
    fi
done
exit $rc
