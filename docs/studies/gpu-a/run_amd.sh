#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_amd.sh CORPUS_DIR WORK_DIR ARCH [BUILD_ONLY_ARCH...]
#
# The body both AMD runbooks share (run_rx7600.sh, run_mi300x.sh): on a
# Linux with ROCm (hipcc on PATH or in ROCM_PATH/bin), and a GPU of ARCH as
# HIP device DEVICE (default 0):
#
#   1. devcopy's plants; builds: cpu, amd ARCH, the two plant builds for
#      ARCH, and amd for each BUILD_ONLY_ARCH (built, not run)
#   2. the flip plant's corpus
#   3. every corpus on the CPU build and on the GPU; each plant on the GPU
#   4. the second kernel (--kernel fixed): the fp256 corpora on the GPU and
#      the CPU, its two plants on the GPU, and the differential stream
#      against the first kernel (DIFF_N cases, default 2^30, seed 20261110)
#
# Before each GPU step it records amd-smi's activity and processes, and
# waits (up to WAIT_MAX seconds, default 120) while GFX activity is at or
# above BUSY_PCT (default 50): someone else's work is not run beside.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
C=${1:?CORPUS_DIR}; W=${2:?WORK_DIR}; ARCH=${3:?ARCH}
shift 3
export PATH=${ROCM_PATH:-/opt/rocm}/bin:$PATH
DEV=${DEVICE:-0}
B=$W/build; O=$W/out
mkdir -p "$B" "$O"
echo "== run_amd.sh $ARCH $(date '+%F %T') on $(hostname)"
python3 -B "$here/devcopy.py" --selftest || exit 1
bash "$here/build.sh" cpu "$B/cpu" || exit 1
bash "$here/build.sh" amd "$B/amd-$ARCH" "$ARCH" || exit 1
DEFS=-DCFT_GPUA_PLANT_RMM_AS_RNE bash "$here/build.sh" amd "$B/amd-$ARCH-plant-rmm" "$ARCH" || exit 1
DEFS=-DCFT_GPUA_PLANT_DROP_FLAG=8 bash "$here/build.sh" amd "$B/amd-$ARCH-plant-uf" "$ARCH" || exit 1
for x in "$@"; do
    bash "$here/build.sh" amd "$B/amd-$x" "$x" || exit 1
done
python3 -B "$here/gen_corpus.py" flip "$C/conf-fp256.bin" "$W/conf-fp256-flip.bin" \
    --index 12345 --bit 0 || exit 1

gpu_state() {
    local t=0 g
    while :; do
        echo "-- $(date '+%T') amd-smi"
        amd-smi metric --usage 2>&1 | grep -E "^GPU|GFX_ACTIVITY|UMC_ACTIVITY"
        amd-smi process 2>&1 | grep -E "NAME|PID|VRAM_MEM"
        g=$(amd-smi metric --usage 2>/dev/null | awk '/GFX_ACTIVITY/{print $2; exit}')
        [ -z "$g" ] || [ "$g" = "N/A" ] || [ "$g" -lt "${BUSY_PCT:-50}" ] && return 0
        [ "$t" -ge "${WAIT_MAX:-120}" ] && { echo "still busy after ${t}s: going on, noted"; return 0; }
        sleep 10; t=$((t + 10))
    done
}
plant() {
    local name=$1; shift
    if "$@"; then echo "PLANT $name: GREEN - the check did not see it"; return 1; fi
    echo "PLANT $name: RED, as it must be"
}

rc=0
bash "$here/run_checks.sh" "$B/cpu/cft_fma" "cpu-$(hostname)" "$C" "$O" || rc=1
gpu_state
"$B/amd-$ARCH/cft_fma" info --device "$DEV"
bash "$here/run_checks.sh" "$B/amd-$ARCH/cft_fma" "$ARCH" "$C" "$O" --device "$DEV" || rc=1
echo "== plants"
gpu_state
plant "flip/$ARCH" "$B/amd-$ARCH/cft_fma" check "$W/conf-fp256-flip.bin" "$O/plant-flip-$ARCH.out" --device "$DEV" || rc=1
plant "flip/$ARCH verify" python3 -B "$here/gen_corpus.py" verify "$W/conf-fp256-flip.bin" "$O/plant-flip-$ARCH.out" || rc=1
plant "rmm-as-rne/$ARCH" "$B/amd-$ARCH-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$DEV" || rc=1
plant "drop-underflow/$ARCH" "$B/amd-$ARCH-plant-uf/cft_fma" check "$C/conf-fp256.bin" - --device "$DEV" || rc=1
plant "flip/cpu-$(hostname)" "$B/cpu/cft_fma" check "$W/conf-fp256-flip.bin" - || rc=1

echo "== the second kernel (fma256_fixed.h, binary256): corpora, plants, the differential stream"
gpu_state
CORPORA="conf-fp256 stream-fp256" bash "$here/run_checks.sh" "$B/amd-$ARCH/cft_fma" "$ARCH-fixed" \
    "$C" "$O" --device "$DEV" --kernel fixed || rc=1
CORPORA="conf-fp256 stream-fp256" bash "$here/run_checks.sh" "$B/cpu/cft_fma" "cpu-$(hostname)-fixed" \
    "$C" "$O" --kernel fixed || rc=1
plant "fixed rmm-as-rne/$ARCH" "$B/amd-$ARCH-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$DEV" --kernel fixed || rc=1
plant "fixed drop-underflow/$ARCH" "$B/amd-$ARCH-plant-uf/cft_fma" check "$C/conf-fp256.bin" - --device "$DEV" --kernel fixed || rc=1
gpu_state
timeout 110 "$B/amd-$ARCH/cft_fma" diff "${DIFF_N:-1073741824}" 20261110 --device "$DEV" || rc=1
echo "== run_amd.sh $ARCH $(date '+%F %T'): $([ $rc = 0 ] && echo 'all GREEN, every plant RED' || echo 'SOMETHING WRONG')"
exit $rc
