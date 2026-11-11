#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-C: GPU-A's cft_fma.hip (or cft_seq.hip), unchanged, through chipStar.
#   build_chipstar.sh OUTDIR [SRC]      SRC default: gpu-a/cft_fma.hip
#   env  CHIPSTAR  chipStar prefix (default /opt/gpu-c/chipstar)
#        LLVM      LLVM prefix (default /usr/lib/llvm-22)
#        DEFS XFLAGS  as GPU-A's build.sh (plants: -DCFT_GPUA_PLANT_*)
# The device copy is remade and checked by GPU-A's devcopy.py first.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
A="$here/../gpu-a"
ROOT=${ROOT:-$(cd "$here/../../.." && pwd)}
OUT=${1:?OUTDIR}
SRC=${2:-$A/cft_fma.hip}
CHIPSTAR=${CHIPSTAR:-/opt/gpu-c/chipstar}
LLVM=${LLVM:-/usr/lib/llvm-22}
DEFS=${DEFS:-}; XFLAGS=${XFLAGS:-}
mkdir -p "$OUT/sha"
run() { echo "+ $*"; "$@"; }
echo "== build_chipstar.sh $(date '+%F %T') SRC=$SRC DEFS='$DEFS'"
B=$(basename "$SRC" .hip)
SEQ=""; INC2=""
if [ "$B" = cft_seq ]; then   # the program runner: GPU-A's build_seq.sh lines
    SEQ=--seq; INC2="-I$OUT/devsrc/include -I$A"; DEFS="-DCFT_NO_AUGMENTED $DEFS"
fi
python3 -B "$A/devcopy.py" --root "$ROOT" --out "$OUT/devsrc" $SEQ
cp "$ROOT/host/src/sha256.h" "$OUT/sha/"
run cc -O2 -std=c99 -DCFT_ERRMSG_MAX=1 -DCFT_NO_REMOTE -c "$ROOT/host/src/sha256.c" -o "$OUT/sha256.o"
export PATH="$LLVM/bin:$CHIPSTAR/bin:$PATH"
export HIP_PLATFORM=spirv
run hipcc -O2 -std=c++17 $DEFS $XFLAGS -I"$OUT/devsrc" $INC2 -I"$OUT/sha" -c "$SRC" -o "$OUT/$B.o"
run hipcc $XFLAGS "$OUT/$B.o" "$OUT/sha256.o" -o "$OUT/$B"
echo "== built $OUT/$B $(date '+%F %T')"
