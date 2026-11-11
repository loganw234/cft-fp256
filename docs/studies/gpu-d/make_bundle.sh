#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# make_bundle.sh OUT.tar.gz CORPUS_DIR WORK_DIR
# Builds here (cft-gpu: Ubuntu 24.04, amd-arc-box's glibc) GPU-D's harness and
# its OpenCL C text (build_ocl.sh), and packs what any OpenCL device needs to
# run GPU-D's checks: bin/cft_fma_ocl, cft_fma.cl, the corpora (conf-fp32 to
# -fp256, stream-fp32, stream-fp256) and the flipped plant, ocl_run.sh,
# GPU-A's gen_corpus.py (for verify, unchanged) and SHA256SUMS. The box then
# needs no compiler: libOpenCL.so.1 and the vendor's runtime, which compiles
# the text at run time (on Intel's NEO, through libigdfcl1, its OpenCL C front
# end). The plants are build options, so no planted binary is packed.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
OUT=$(realpath -m "${1:?OUT.tar.gz}"); C=${2:?CORPUS_DIR}; W=${3:?WORK_DIR}
rm -rf "$W/bundle"; mkdir -p "$W/bundle/b/bin" "$W/bundle/b/corpus"
bash "$here/build_ocl.sh" "$W/build" > "$W/build.log" 2>&1 || { tail -20 "$W/build.log"; exit 1; }
grep -E "^(devcopy: OK|oclcopy:)" "$W/build.log"
B=$W/bundle/b
cp "$W/build/cft_fma_ocl" "$B/bin/"; cp "$W/build/cft_fma.cl" "$B/"
for f in conf-fp32 conf-fp64 conf-fp128 conf-fp256 stream-fp32 stream-fp256; do cp "$C/$f.bin" "$B/corpus/"; done
python3 -B "$here/../gpu-a/gen_corpus.py" flip "$C/conf-fp256.bin" "$B/corpus/conf-fp256-flip.bin" \
    --index 12345 --bit 0
cp "$here/ocl_run.sh" "$here/../gpu-a/gen_corpus.py" "$B/"
(cd "$B" && find . -type f ! -name SHA256SUMS | sort | xargs sha256sum > SHA256SUMS)
echo "ldd bin/cft_fma_ocl:"; ldd "$B/bin/cft_fma_ocl" | sed 's/ (0x[0-9a-f]*)//'
tar -C "$W/bundle" -czf "$OUT" b; sha256sum "$OUT"; ls -la "$OUT"
