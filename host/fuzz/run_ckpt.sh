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

SRC="src/bigint.c src/softfloat.c src/device.c src/divsqrt.c src/clause5.c \
src/chars.c src/augmented.c src/mpfloat.c src/transcend.c src/program.c \
src/reduce.c src/formatof.c src/conformance.c src/backend_remote.c"

for t in collatz enclose mersenne orbits zoom; do
    out="fuzz/bin/cft-$t"
    if [ ! -x "$out" ] || [ "tools/$t.c" -nt "$out" ]; then
        echo "building $out with -fsanitize=address,undefined"
        # shellcheck disable=SC2086
        $CC $CFLAGS_SAN -Wall -Iinclude "tools/$t.c" $SRC -o "$out"
    fi
done

cd fuzz
exec $PYTHON fuzz_ckpt.py --bin bin --seconds "$SECONDS_TOTAL" \
     ${*:+--tool "$@"}
