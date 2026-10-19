#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# sha_speed.sh - SHA-256 throughput of one core, for section 4.6 of the study (the cost of a
# per-batch digest). openssl speed, niced, run twice; the figure used is the 16 KB column.
#
#   usage: bash sha_speed.sh        (writes sha_speed.out beside this script)
#
# The study multiplies the rate into a case's bytes: 16 bytes of output and flags a case,
# so (16 / rate) seconds a case, against the card's 500 ns (div32) and 650 ns (div64).

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/sha_speed.out"
{
    echo "sha_speed.sh: SHA-256 on one core, openssl speed -evp sha256 -seconds 3, niced"
    echo "openssl: $(openssl version)"
    echo "CPU: $(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)"
    echo
    for run in 1 2; do
        nice -n 10 openssl speed -evp sha256 -seconds 3 > "${TMPDIR:-/tmp}/swp_a_sha.$$" 2>/dev/null
        echo "-- run $run (lines of the openssl table)"
        grep -E "^(type|sha256)" "${TMPDIR:-/tmp}/swp_a_sha.$$"
        # the last column is the 16384-byte block, in thousands of bytes a second
        awk -v run="$run" '/^sha256/ {
            v = $NF; sub(/k$/, "", v); gbs = v * 1000.0 / 1e9;
            printf "   run %s: %.3f GB/s at 16 KB; 16 bytes a case = %.2f ns; against div32 500 ns: %.1f%%, div64 650 ns: %.1f%%\n",
                   run, gbs, 16.0 / gbs, 100.0 * (16.0 / gbs) / 500.0, 100.0 * (16.0 / gbs) / 650.0 }' "${TMPDIR:-/tmp}/swp_a_sha.$$"
        rm -f "${TMPDIR:-/tmp}/swp_a_sha.$$"
    done
} > "$OUT"
cat "$OUT"
