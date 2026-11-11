#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_chipstar.sh CORPUS_DIR WORK_DIR        (CORPUS_DIR: gen_corpus.py conformance output)
#
# GPU-A's cft_fma.hip through chipStar on one OpenCL/SPIR-V device. Plants first,
# then the corpora.  Env: CHIPSTAR (/opt/gpu-c/chipstar), LLVM (/usr/lib/llvm-22),
# CHIP_DEVICE_TYPE (pocl: PoCL's CPU device; on an Intel GPU: gpu), CHIP_BE
# (opencl; level0 on an Intel GPU with Level Zero), OCL_ICD_VENDORS/LD_LIBRARY_PATH
# for a PoCL that is not installed system-wide, DEVICE (0), CORPORA.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
A="$here/../gpu-a"
C=${1:?CORPUS_DIR}; W=${2:?WORK_DIR}
CHIPSTAR=${CHIPSTAR:-/opt/gpu-c/chipstar}
export LD_LIBRARY_PATH=$CHIPSTAR/lib:${LD_LIBRARY_PATH:-}
export CHIP_BE=${CHIP_BE:-opencl} CHIP_DEVICE_TYPE=${CHIP_DEVICE_TYPE:-pocl}
export CHIP_LOGLEVEL=${CHIP_LOGLEVEL:-err}
DEV=${DEVICE:-0}
B=$W/build; O=$W/out; mkdir -p "$B" "$O"
echo "== run_chipstar.sh $(date '+%F %T') $CHIP_BE/$CHIP_DEVICE_TYPE device $DEV on $(hostname)"
bash "$here/build_chipstar.sh" "$B/ok" > "$B/ok.log" 2>&1 || { tail -20 "$B/ok.log"; exit 1; }
DEFS=-DCFT_GPUA_PLANT_RMM_AS_RNE bash "$here/build_chipstar.sh" "$B/plant-rmm" > "$B/plant-rmm.log" 2>&1 || exit 1
DEFS=-DCFT_GPUA_PLANT_DROP_FLAG=8 bash "$here/build_chipstar.sh" "$B/plant-uf" > "$B/plant-uf.log" 2>&1 || exit 1
python3 -B "$A/gen_corpus.py" flip "$C/conf-fp256.bin" "$W/conf-fp256-flip.bin" --index 12345 --bit 0 || exit 1
plant() {   # a plant passes when the check goes RED
    local name=$1; shift
    if "$@" > "$O/plant-$name.log" 2>&1; then echo "PLANT $name: GREEN - the check did not see it"; rc=1
    else echo "PLANT $name: RED, as it must be"; grep -h "^check:" "$O/plant-$name.log" | cut -c1-400; fi
}
rc=0
echo "== plants"
plant flip "$B/ok/cft_fma" check "$W/conf-fp256-flip.bin" "$O/plant-flip.out" --device "$DEV"
python3 -B "$A/gen_corpus.py" verify "$W/conf-fp256-flip.bin" "$O/plant-flip.out" > "$O/plant-flip-verify.log" 2>&1 \
    && { echo "PLANT flip verify: GREEN - the Python check did not see it"; rc=1; } || { echo "PLANT flip verify: RED, as it must be"; tail -1 "$O/plant-flip-verify.log" | cut -c1-300; }
plant rmm-as-rne "$B/plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$DEV"
plant drop-underflow "$B/plant-uf/cft_fma" check "$C/conf-fp256.bin" - --device "$DEV"
echo "== corpora"
CORPORA=${CORPORA:-conf-fp256 conf-fp32 conf-fp64 conf-fp128} bash "$A/run_checks.sh" "$B/ok/cft_fma" chip "$C" "$O" --device "$DEV" 2>&1 | grep -v "^CHIP" || rc=1
echo "== run_chipstar.sh $(date '+%F %T') rc=$rc"
exit $rc
