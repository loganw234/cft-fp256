#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# bench.sh BIN LABEL CORPUS_DIR [harness flags, e.g. --device 1]
#
# The rates: each format's stream corpus (1,000,000 lanes, the five
# attributes in equal parts) at each block size in BLOCKS (default
# "64 128 256"), REPS timed repetitions (default 10) after one warm-up,
# kernel time by events and end to end with the transfers; then fp256 at
# BIG_LANES lanes (default 4000000: the 1,000,000 inputs replicated). For a
# CPU build give BLOCKS=1 REPS=3: the block is unused there. Clocks are not
# controlled; record the machine's load beside the output.
set -uo pipefail
BIN=${1:?BIN}; LABEL=${2:?LABEL}; C=${3:?CORPUS_DIR}
shift 3
REPS=${REPS:-10}
echo "== bench.sh $LABEL $(date '+%F %T') on $(hostname)"
for f in ${FORMATS:-fp32 fp64 fp128 fp256}; do
    for b in ${BLOCKS:-64 128 256}; do
        timeout 110 "$BIN" bench "$C/stream-$f.bin" --block "$b" --reps "$REPS" "$@"
    done
done
for n in ${BIG_LANES:-4000000}; do
    timeout 110 "$BIN" bench "$C/stream-fp256.bin" --block "${BIG_BLOCK:-128}" --reps "$REPS" \
        --lanes "$n" "$@"
done
echo "== bench.sh $LABEL $(date '+%F %T') done"
