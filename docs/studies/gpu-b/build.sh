#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B's build of GPU-A's one source against HIP built from ROCm 10.1's own
# sources (build_hip_nv.sh):  build.sh MODE OUTDIR [ARCH...]
#   MODE  plain  nvcc 12.9 with -I$HP/include -D__HIP_PLATFORM_NVIDIA__
#                (no hipcc): the cheapest test of whether current HIP works
#         hipcc  the hipcc built from amd/hipcc (HIP_PLATFORM=nvidia), as
#                GPU-A's `nvidia` target uses 7.2.4's; the same line, only
#                the install differs
#   env   HP  the HIP prefix (default /opt/gpu-b)
#         ROOT  the tree whose host/ is copied (default: this repository)
# The device copy and the sha256 object are made as GPU-A's build.sh makes
# them (devcopy.py, sha256.c).  Compiler output (ptxas -v) -> OUTDIR/resource.log.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
A="$here/../gpu-a"
ROOT=${ROOT:-$(cd "$here/../../.." && pwd)}
HP=${HP:-/opt/gpu-b}
MODE=${1:?MODE}; OUT=${2:?OUTDIR}; shift 2
SRC="$A/cft_fma.hip"
export CUDA_HOME=${CUDA_HOME:-/usr/local/cuda}; export CUDA_PATH=$CUDA_HOME; export PATH=$CUDA_HOME/bin:$PATH
mkdir -p "$OUT/sha"
run() { echo "+ $*"; "$@"; }
echo "== build.sh $MODE $(date '+%F %T') HP=$HP DEFS='${DEFS:-}'"
python3 -B "$A/devcopy.py" --root "$ROOT" --out "$OUT/devsrc"
cp "$ROOT/host/src/sha256.h" "$OUT/sha/"
run cc -O2 -std=c99 -DCFT_ERRMSG_MAX=1 -DCFT_NO_REMOTE -c "$ROOT/host/src/sha256.c" -o "$OUT/sha256.o"
INC="-I$OUT/devsrc -I$OUT/sha"
G=""
for cc in ${@:-89 120}; do G="$G -gencode arch=compute_$cc,code=sm_$cc"; done
case "$MODE" in
plain)
    run nvcc -x cu -D__HIP_PLATFORM_NVIDIA__ -I"$HP/include" -O2 -std=c++17 $G -Xptxas -v ${DEFS:-} $INC \
        -c "$SRC" -o "$OUT/cft_fma.o" 2>&1 | tee "$OUT/resource.log"
    run nvcc "$OUT/cft_fma.o" "$OUT/sha256.o" -o "$OUT/cft_fma"
    ;;
hipcc)
    export HIP_PLATFORM=nvidia HIP_PATH="$HP" ROCM_PATH="$HP" PATH="$HP/bin:$PATH"
    run hipcc --version | sed -n 1,4p || true
    # the same line as GPU-A's `nvidia` target (its hazards N1-N3 are why)
    run hipcc -x cu -isystem "$HP/include" -O2 -std=c++17 $G -Xptxas -v ${DEFS:-} $INC \
        -c "$SRC" -o "$OUT/cft_fma.o" 2>&1 | tee "$OUT/resource.log"
    run hipcc "$OUT/cft_fma.o" "$OUT/sha256.o" -o "$OUT/cft_fma"
    ;;
*) echo "unknown MODE $MODE"; exit 2 ;;
esac
[ -x "$OUT/cft_fma" ] || { echo "BUILD FAILED"; exit 1; }
echo "== built $OUT/cft_fma $(date '+%F %T')"
