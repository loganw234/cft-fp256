#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# perm_check.sh - build and run parcel SC's permutation instruments: perm_check.c (all
# sections: bijectivity by exhaustion up to 2^32 inputs, quality, cycle walking, coverage
# accounting, speed, vectors) and perm_check.py (an independent implementation held to the
# C program's vectors). About four minutes on one core, niced.
#
#   usage: bash perm_check.sh [PYTHON]       (default python3)
#
# Writes perm_check.c.out and perm_check.out beside this script, and perm_check.speed.out
# (the speed section alone, five more runs). Exit status 0 only if the C program and the
# Python check both pass.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${1:-python3}
B=${TMPDIR:-/tmp}/swp_a_perm.$$
mkdir -p "$B"
gcc -std=gnu99 -O2 -Wall -Wextra -Wno-format-zero-length -o "$B/perm_check" "$HERE/perm_check.c" -lm || { rm -rf "$B"; exit 2; }
t0=$(date +%s)
nice -n 10 "$B/perm_check" all > "$HERE/perm_check.c.out"
rc1=$?
t1=$(date +%s)
"$PY" -B "$HERE/perm_check.py" "$HERE/perm_check.c.out" > "$HERE/perm_check.out"
rc2=$?
# the speed section alone, five more times: one number from a busy desktop is not a rate
: > "$HERE/perm_check.speed.out"
for k in 1 2 3 4 5; do
    nice -n 10 "$B/perm_check" S > "$B/speed.$k"
    echo "-- speed run $k" >> "$HERE/perm_check.speed.out"
    grep "ns a permutation" "$B/speed.$k" >> "$HERE/perm_check.speed.out"
done
echo "perm_check.c rc=$rc1 in $((t1 - t0)) s; perm_check.py rc=$rc2"
echo "gcc: $(gcc --version | head -1); CPU: $(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)"
rm -rf "$B"
[ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ]
