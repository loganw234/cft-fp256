#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-A's one build from one source:  build.sh TARGET OUTDIR [ARCH...]
#
#   TARGET  cpu         the device copy compiled for the host by g++ (no GPU)
#           cpu-libcft  libcft's own C (host/src as it is, by cc) under the
#                       same harness, the reference for "the copy changed
#                       nothing"
#           nvidia      HIP over CUDA: hipcc with HIP_PLATFORM=nvidia
#           amd         HIP over ROCm: hipcc with HIP_PLATFORM=amd
#   ARCH    nvidia: compute capabilities, default "89 120";
#           amd: gfx targets, default gfx1102
#   env     DEFS  extra -D flags, e.g. "-DCFT_BN_LIMBS=38 -DCFT_NO_TRANSCEND",
#                 or a plant: -DCFT_GPUA_PLANT_RMM_AS_RNE,
#                 -DCFT_GPUA_PLANT_DROP_FLAG=8
#           ROOT  the tree whose host/ is copied (default: this repository)
#           XFLAGS  extra flags on every compile and link of the harness and
#                 the arithmetic (sanitizers, -ftrivial-auto-var-init, fast
#                 math, -O0, -G: the hazard runs)
#           HIP_PATH  for nvidia (HIP 7.2.4's NVIDIA platform)
#
# Every build first remakes the device copy and checks it (devcopy.py): a
# copy that differs from host/src by anything but E1 stops the build. The
# compilers' resource reports land in OUTDIR/resource.log.
#
# The build lines differ by platform, the source does not. On NVIDIA,
# HIP 7.2.4's hipcc hands --offload-arch to nvcc, which rejects it, and nvcc
# does not know the .hip suffix; given -x cu, hipcc drops its own -isystem.
# So the NVIDIA line says -x cu, -isystem and -gencode itself.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
ROOT=${ROOT:-$(cd "$here/../../.." && pwd)}
TARGET=${1:?TARGET}
OUT=${2:?OUTDIR}
shift 2
DEFS=${DEFS:-}
XFLAGS=${XFLAGS:-}
SRC="$here/cft_fma.hip"
mkdir -p "$OUT/sha"
run() { echo "+ $*"; "$@"; }
# a tool's version, without a pipe into head (pipefail and SIGPIPE)
banner() { "$@" > "$OUT/version.txt" 2>&1 || true; sed -n '1,4p' "$OUT/version.txt"; }

echo "== build.sh $TARGET $(date '+%F %T') DEFS='$DEFS' XFLAGS='$XFLAGS' ROOT=$ROOT"
python3 -B "$here/devcopy.py" --root "$ROOT" --out "$OUT/devsrc"
cp "$ROOT/host/src/sha256.h" "$OUT/sha/"
# libcft's sha256.c as it is, at the library's own profile in which
# cft_clear_error() is a no-op (backend.h), so it links alone.
run cc -O2 -std=c99 -DCFT_ERRMSG_MAX=1 -DCFT_NO_REMOTE -c "$ROOT/host/src/sha256.c" -o "$OUT/sha256.o"
INC="-I$OUT/devsrc -I$OUT/sha"

case "$TARGET" in
cpu)
    banner g++ --version
    run g++ -O2 -std=c++17 -Wall -Wno-unknown-pragmas -x c++ -DCFT_GPUA_CPU $DEFS $XFLAGS $INC \
        -c "$SRC" -o "$OUT/cft_fma.o"
    run g++ $XFLAGS "$OUT/cft_fma.o" "$OUT/sha256.o" -o "$OUT/cft_fma"
    ;;
cpu-libcft)
    banner cc --version
    run cc -O2 -std=c99 -Wall $DEFS $XFLAGS -c "$ROOT/host/src/bigint.c" -o "$OUT/bigint.o"
    run cc -O2 -std=c99 -Wall $DEFS $XFLAGS -c "$ROOT/host/src/softfloat.c" -o "$OUT/softfloat.o"
    run g++ -O2 -std=c++17 -Wall -Wno-unknown-pragmas -x c++ -DCFT_GPUA_CPU -DCFT_GPUA_LIBCFT_C $DEFS $XFLAGS \
        -I"$ROOT/host/src" -I"$OUT/sha" -c "$SRC" -o "$OUT/cft_fma.o"
    run g++ $XFLAGS "$OUT/cft_fma.o" "$OUT/bigint.o" "$OUT/softfloat.o" "$OUT/sha256.o" -o "$OUT/cft_fma"
    ;;
nvidia)
    : "${HIP_PATH:?HIP_PATH must point at HIP for NVIDIA}"
    export HIP_PLATFORM=nvidia
    banner hipcc --version
    G=""
    for cc in ${@:-89 120}; do G="$G -gencode arch=compute_$cc,code=sm_$cc"; done
    run hipcc -x cu -isystem "$HIP_PATH/include" -O2 -std=c++17 $G -Xptxas -v $DEFS $XFLAGS $INC \
        -c "$SRC" -o "$OUT/cft_fma.o" 2>&1 | tee "$OUT/resource.log"
    run hipcc $XFLAGS "$OUT/cft_fma.o" "$OUT/sha256.o" -o "$OUT/cft_fma"
    ;;
amd)
    export HIP_PLATFORM=amd
    banner hipcc --version
    A=""
    for g in ${@:-gfx1102}; do A="$A --offload-arch=$g"; done
    run hipcc -O2 -std=c++17 $A -Rpass-analysis=kernel-resource-usage $DEFS $XFLAGS $INC \
        -c "$SRC" -o "$OUT/cft_fma.o" 2>&1 | tee "$OUT/resource.log"
    run hipcc $A $XFLAGS "$OUT/cft_fma.o" "$OUT/sha256.o" -o "$OUT/cft_fma"
    ;;
*)
    echo "unknown TARGET $TARGET"; exit 2 ;;
esac
[ -x "$OUT/cft_fma" ] || { echo "BUILD FAILED"; exit 1; }
echo "== built $OUT/cft_fma $(date '+%F %T')"
