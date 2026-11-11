#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The MI300X runbook (gfx942), for the lead to run when Logan has the time.
# Nothing here has run on an MI300X. Every step has run on the RX 7600
# (gfx1102), and both kernels have been compiled for gfx942 there, without
# the card (run_rx7600.sh). The study's section "The MI300X" lists the
# heavier runs worth the card's time; none is planned without Logan's word.
#
# Needs: Linux with ROCm (hipcc on PATH or under ROCM_PATH, any release that
# knows gfx942), python3, ~2 GB of disk and ~1 GB of device memory, and
# the eight corpora gen_corpus.py made (they need the golden model and
# mpmath to make, so copy them rather than remake them on the host).
#
# Copy (from a tree at the study's commit):
#   tar czf gpu-a-tree.tgz docs/studies/gpu-a host/src/bigint.[ch] \
#       host/src/softfloat.[ch] host/src/sha256.[ch] host/src/backend.h \
#       host/include/cft_config.h host/include/cft.h
#   scp gpu-a-tree.tgz CORPUS/*.bin <host>:gpu-a/
# On the host:
#   cd ~/gpu-a && mkdir -p tree corpus && tar xzf gpu-a-tree.tgz -C tree
#   mv *.bin corpus/
#   bash tree/docs/studies/gpu-a/run_mi300x.sh ~/gpu-a/corpus ~/gpu-a/work \
#       [~/gpu-a/programs] > mi300x.log 2>&1
# Part 2 (programs): give a third directory with gen_programs.py's corpora
# and seq_ref's outputs for them (scp PROGRAMS/*.bin PROGRAMS/ref-*.out),
# made on a host with the golden model and libcft; the tree's tar then also
# needs host/src/program.c (devcopy.py --seq takes the executor from it).
# DEVICE=n picks the HIP device (one per GPU in SPX mode, more in CPX).
#
# What it does, in order (ESTIMATE: under 10 minutes in all; the RX 7600
# took 30 s for step 3's first half and 20 s for its 2^30-case diff):
#   1. the toolchain check (toolchain_check.hip, gfx942)
#   2. the corpora against captured/corpus.sha256 (refuses a different one)
#   3. run_amd.sh gfx942: every corpus, the plants, the second kernel's
#      corpora, plants and a 2^30-case differential stream
#   4. the rates: bench.sh for both kernels, 1M and 16M lanes at fp256
#   5. every lane one case (divergence), both kernels
#   6. with PROGRAMS_DIR, part 2: run_seq.sh amd gfx942 (the runner's builds,
#      every program corpus against libcft's output, the refusal, the two
#      plants red, the rates of exp, sin and atan, a batch curve to 16M
#      lanes). Built for gfx942 on the RX 7600 machine without the card;
#      never run on one (ESTIMATE: under 5 minutes more).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
C=${1:?CORPUS_DIR}; W=${2:?WORK_DIR}; PROGS=${3:-}
export PATH=${ROCM_PATH:-/opt/rocm}/bin:$PATH
DEV=${DEVICE:-0}
mkdir -p "$W"
echo "== run_mi300x.sh $(date '+%F %T') on $(hostname)"
hipcc --version 2>&1 | sed -n '1,2p'
amd-smi static --asic 2>&1 | grep -E "MARKET_NAME|TARGET_GRAPHICS_VERSION" | head -4
hipcc -O2 --offload-arch=gfx942 "$here/toolchain_check.hip" -o "$W/toolchain_check" \
    && "$W/toolchain_check" || { echo "toolchain check FAILED"; exit 1; }
(cd "$C" && sha256sum -c "$here/captured/corpus.sha256") || { echo "corpora differ: refused"; exit 1; }
DEVICE=$DEV bash "$here/run_amd.sh" "$C" "$W" gfx942
rc=$?
BIN=$W/build/amd-gfx942/cft_fma
BIG_LANES="4000000 16000000" bash "$here/bench.sh" "$BIN" gfx942 "$C" --device "$DEV"
FORMATS=fp256 BIG_LANES="4000000 16000000" bash "$here/bench.sh" "$BIN" gfx942-fixed "$C" \
    --device "$DEV" --kernel fixed
for k in 5 4 1 2; do
    for kern in generic fixed; do
        "$BIN" bench "$C/stream-fp256.bin" --device "$DEV" --block 128 --reps 10 \
            --lanes 4000000 --case "$k" --kernel "$kern"
    done
done
echo "== run_mi300x.sh $(date '+%F %T'): run_amd.sh exit $rc"
if [ -n "$PROGS" ]; then
    BIG=1 DEVICE=$DEV bash "$here/run_seq.sh" amd "$PROGS" "$W/seq" gfx942 || rc=1
    echo "== run_mi300x.sh $(date '+%F %T'): with part 2, exit $rc"
fi
exit $rc
