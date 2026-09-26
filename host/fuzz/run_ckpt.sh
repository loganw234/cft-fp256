#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Build the five workload tools with the sanitisers into fuzz/bin and
# run fuzz_ckpt.py against them. Run from host/fuzz.
#
#   ./run_ckpt.sh [TOTAL_SECONDS] [TOOL ...]
#
# The tools are built into a directory of their own so that a sanitised
# cft-collatz never lands where `make test` would pick it up: the
# sanitised binaries are for this lane and nothing else.
set -eu

SECONDS_TOTAL=${1:-300}
shift 2>/dev/null || true

CC=${CC:-cc}
PYTHON=${PYTHON:-python3}
SAN="-fsanitize=address,undefined -fno-sanitize-recover=all"
CFLAGS_SAN="-std=c99 -O1 -g -fno-omit-frame-pointer $SAN"

mkdir -p bin
cd ..

# The library's sources, asked of host/Makefile rather than copied here:
# a hand list in this file missed src/sha256.c from 2026-09-08 until
# 2026-09-25, so the tools could not link and nothing ran the lane to
# notice (verifier-V7 - and f953f4c's message said this edit was made
# when it was not).
SRC=$(make -s --no-print-directory print-src) || {
    echo "run_ckpt.sh: 'make print-src' failed; the library's source" \
         "list comes from host/Makefile" >&2
    exit 1
}
if [ -z "$SRC" ]; then
    echo "run_ckpt.sh: 'make print-src' printed no sources" >&2
    exit 1
fi

for t in collatz enclose mersenne orbits zoom; do
    out="fuzz/bin/cft-$t"
    # Rebuilt when ANYTHING it is built from is newer - its own source, the
    # library's, a header. Until 2026-09-26 only tools/$t.c was compared,
    # so after a library change the lane went on fuzzing the library the
    # tools were first built from (verifier-V8).
    stale=0
    if [ ! -x "$out" ]; then
        stale=1
    fi
    for f in "tools/$t.c" $SRC include/*.h src/*.h; do
        if [ "$f" -nt "$out" ]; then
            stale=1
        fi
    done
    if [ "$stale" = 1 ]; then
        echo "building $out with -fsanitize=address,undefined"
        # shellcheck disable=SC2086
        $CC $CFLAGS_SAN -Wall -Iinclude "tools/$t.c" $SRC -o "$out"
    fi
done

cd fuzz
exec $PYTHON fuzz_ckpt.py --bin bin --seconds "$SECONDS_TOTAL" \
     ${*:+--tool "$@"}
