#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# build_ocl.sh OUTDIR      GPU-D's one build, the same on Linux and macOS:
#   1. devcopy.py: GPU-A's copy of host/src (edit E1 alone), checked;
#   2. oclcopy.py: the OpenCL C text OUTDIR/cft_fma.cl, every edit counted,
#      the whole checked; it prints the text's sha256;
#   3. the harness cft_fma_ocl and libcft's sha256.c (host/src as it is, at
#      the library's CFT_ERRMSG_MAX=1 profile, as GPU-A's build.sh) by cc.
# Nothing for a device is compiled here: the harness builds the text at run
# time. env: ROOT, the tree whose host/ is copied (default this repository);
# CC (default cc).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
ROOT=${ROOT:-$(cd "$here/../../.." && pwd)}
OUT=${1:?OUTDIR}
CC=${CC:-cc}
mkdir -p "$OUT"
echo "== build_ocl.sh $(date '+%F %T') on $(uname -s) $(uname -m)"
python3 -B "$here/../gpu-a/devcopy.py" --root "$ROOT" --out "$OUT/devsrc"
python3 -B "$here/oclcopy.py" "$OUT/devsrc" "$OUT/cft_fma.cl"
case "$(uname -s)" in
Darwin) LIB="-framework OpenCL" ;;
*)      LIB="-lOpenCL" ;;
esac
"$CC" --version > "$OUT/cc-version.txt" 2>&1 || true
sed -n 1p "$OUT/cc-version.txt"
run() { echo "+ $*"; "$@"; }
run "$CC" -O2 -std=c99 -DCFT_ERRMSG_MAX=1 -DCFT_NO_REMOTE -c "$ROOT/host/src/sha256.c" \
    -o "$OUT/sha256.o"
run "$CC" -O2 -std=c99 -Wall -I"$ROOT/host/src" -c "$here/cft_fma_ocl.c" -o "$OUT/cft_fma_ocl.o"
run "$CC" "$OUT/cft_fma_ocl.o" "$OUT/sha256.o" $LIB -o "$OUT/cft_fma_ocl"
echo "== built $OUT/cft_fma_ocl $(date '+%F %T')"
