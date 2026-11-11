#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-A part 2's builds:  build_seq.sh TARGET OUTDIR [ARCH...]
#
#   TARGET  cpu      cft_seq.hip by g++ (no GPU), the runner's CPU build
#           nvidia   cft_seq.hip by hipcc, HIP over CUDA (HIP_PATH, as build.sh)
#           amd      cft_seq.hip by hipcc, HIP over ROCm
#           ref      seq_ref.c against libcft.a, built from a copy of host/
#                    in OUTDIR (the tree is never built in place), one job
#   ARCH    nvidia: compute capabilities, default "89 120"; amd: default gfx1102
#   env     DEFS  the format's container, "-DCFT_MAX_FORMAT=1 -DCFT_NO_TRANSCEND" (fp32 and fp64,
#                 9 limbs) or "-DCFT_BN_LIMBS=40 -DCFT_NO_TRANSCEND" (to
#                 fp256); -DCFT_GPUA_FIXED for the fp256 path; a plant,
#                 -DCFT_GPUA_PLANT_SEQ_MASK or -DCFT_GPUA_PLANT_SEQ_KONST
#           ROOT, XFLAGS, HIP_PATH as build.sh's
#
# Every runner build first remakes the device copy with the sequencer's
# executor and checks it (devcopy.py --seq); a copy that differs from
# host/src by anything but E1 to E4 stops the build. CFT_NO_AUGMENTED is
# always defined: augmented.c is not copied, and the runner refuses its two
# control codes by name.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
ROOT=${ROOT:-$(cd "$here/../../.." && pwd)}
TARGET=${1:?TARGET}
OUT=${2:?OUTDIR}
shift 2
DEFS=${DEFS:-}
XFLAGS=${XFLAGS:-}
mkdir -p "$OUT/sha"
OUT=$(cd "$OUT" && pwd)
run() { echo "+ $*"; "$@"; }
banner() { "$@" > "$OUT/version.txt" 2>&1 || true; sed -n '1,4p' "$OUT/version.txt"; }

echo "== build_seq.sh $TARGET $(date '+%F %T') DEFS='$DEFS' XFLAGS='$XFLAGS' ROOT=$ROOT"
if [ "$TARGET" = ref ]; then
    rm -rf "$OUT/lib" && mkdir -p "$OUT/lib"
    cp -r "$ROOT/host" "$OUT/lib/host"
    rm -f "$OUT/lib/host"/src/*.o "$OUT/lib/host"/*.a
    run make -C "$OUT/lib/host" -j1 libcft.a > "$OUT/libcft.log" 2>&1 || { tail -20 "$OUT/libcft.log"; exit 1; }
    banner cc --version
    run cc -O2 -std=c99 -Wall $XFLAGS -I"$OUT/lib/host/include" -I"$OUT/lib/host/src" \
        "$here/seq_ref.c" "$OUT/lib/host/libcft.a" -lm -o "$OUT/seq_ref"
    [ -x "$OUT/seq_ref" ] || { echo "BUILD FAILED"; exit 1; }
    echo "== built $OUT/seq_ref $(date '+%F %T')"
    exit 0
fi
python3 -B "$here/devcopy.py" --root "$ROOT" --out "$OUT/devsrc" --seq
cp "$ROOT/host/src/sha256.h" "$OUT/sha/"
run cc -O2 -std=c99 -DCFT_ERRMSG_MAX=1 -DCFT_NO_REMOTE -c "$ROOT/host/src/sha256.c" -o "$OUT/sha256.o"
INC="-I$OUT/devsrc -I$OUT/devsrc/include -I$OUT/sha -I$here"
D="-DCFT_NO_AUGMENTED $DEFS"
SRC="$here/cft_seq.hip"
case "$TARGET" in
cpu)
    banner g++ --version
    run g++ -O2 -std=c++17 -Wall -Wno-unknown-pragmas -x c++ -DCFT_GPUA_CPU $D $XFLAGS $INC \
        -c "$SRC" -o "$OUT/cft_seq.o"
    run g++ $XFLAGS "$OUT/cft_seq.o" "$OUT/sha256.o" -o "$OUT/cft_seq"
    ;;
nvidia)
    : "${HIP_PATH:?HIP_PATH must point at HIP for NVIDIA}"
    export HIP_PLATFORM=nvidia
    banner hipcc --version
    G=""
    for cc in ${@:-89 120}; do G="$G -gencode arch=compute_$cc,code=sm_$cc"; done
    run hipcc -x cu -isystem "$HIP_PATH/include" -O2 -std=c++17 $G -Xptxas -v $D $XFLAGS $INC \
        -c "$SRC" -o "$OUT/cft_seq.o" > "$OUT/resource.log" 2>&1 || { tail -30 "$OUT/resource.log"; exit 1; }
    run hipcc $XFLAGS "$OUT/cft_seq.o" "$OUT/sha256.o" -o "$OUT/cft_seq"
    ;;
amd)
    export HIP_PLATFORM=amd
    banner hipcc --version
    A=""
    for g in ${@:-gfx1102}; do A="$A --offload-arch=$g"; done
    run hipcc -O2 -std=c++17 $A -Rpass-analysis=kernel-resource-usage $D $XFLAGS $INC \
        -c "$SRC" -o "$OUT/cft_seq.o" > "$OUT/resource.log" 2>&1 || { tail -30 "$OUT/resource.log"; exit 1; }
    run hipcc $A $XFLAGS "$OUT/cft_seq.o" "$OUT/sha256.o" -o "$OUT/cft_seq"
    ;;
*)
    echo "unknown TARGET $TARGET"; exit 2 ;;
esac
[ -x "$OUT/cft_seq" ] || { echo "BUILD FAILED"; exit 1; }
echo "== built $OUT/cft_seq $(date '+%F %T')"
