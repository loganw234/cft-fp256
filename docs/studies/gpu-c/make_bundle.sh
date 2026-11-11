#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# make_bundle.sh OUT.tar.gz CORPUS_DIR PROGRAMS_DIR
# Builds, here (cft-gpu, Ubuntu 24.04, same glibc as amd-arc-box), everything the Arc run
# needs: GPU-A's cft_fma and cft_seq through chipStar (SPIR-V embedded), chipStar's
# libCHIP.so, the corpora, the planted builds and corpus, arc_run.sh and sums.
# The box then needs NO compiler, LLVM or chipStar: libCHIP.so + an OpenCL ICD.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); A="$here/../gpu-a"
OUT=$(realpath -m "${1:?OUT.tar.gz}"); C=${2:?CORPUS_DIR}; P=${3:?PROGRAMS_DIR}
CHIPSTAR=${CHIPSTAR:-/opt/gpu-c/chipstar}
T=$(mktemp -d /root/gpu-c/bundle.XXXXXX); mkdir -p $T/b/{bin,lib,corpus,programs}
bb() { DEFS="$3" bash "$here/build_chipstar.sh" "$T/w/$1" "$2" > "$T/$1.log" 2>&1 || { tail -20 "$T/$1.log"; exit 1; }; }
bb fma $A/cft_fma.hip ""
bb fma-rmm $A/cft_fma.hip "-DCFT_GPUA_PLANT_RMM_AS_RNE"
bb fma-uf $A/cft_fma.hip "-DCFT_GPUA_PLANT_DROP_FLAG=8"
bb s64 $A/cft_seq.hip "-DCFT_MAX_FORMAT=1 -DCFT_NO_TRANSCEND"
bb s256 $A/cft_seq.hip "-DCFT_BN_LIMBS=40 -DCFT_NO_TRANSCEND"
bb s64-mask $A/cft_seq.hip "-DCFT_MAX_FORMAT=1 -DCFT_NO_TRANSCEND -DCFT_GPUA_PLANT_SEQ_MASK"
bb s64-konst $A/cft_seq.hip "-DCFT_MAX_FORMAT=1 -DCFT_NO_TRANSCEND -DCFT_GPUA_PLANT_SEQ_KONST"
cp $T/w/fma/cft_fma $T/b/bin/cft_fma; cp $T/w/fma-rmm/cft_fma $T/b/bin/cft_fma-plant-rmm
cp $T/w/fma-uf/cft_fma $T/b/bin/cft_fma-plant-uf
for x in s64 s256 s64-mask s64-konst; do cp $T/w/$x/cft_seq $T/b/bin/cft_seq-$x; done
cp $CHIPSTAR/lib/libCHIP.so $T/b/lib/
cp $C/conf-fp*.bin $C/stream-fp256.bin $T/b/corpus/
python3 -B $A/gen_corpus.py flip $C/conf-fp256.bin $T/b/corpus/conf-fp256-flip.bin --index 12345 --bit 0 > /dev/null
cp $P/*.bin $P/ref-*.out $T/b/programs/
cp $A/captured/programs.sha256 $T/b/programs.sha256
cp "$here/arc_run.sh" $T/b/
(cd $T/b && find . -type f ! -name SHA256SUMS | sort | xargs sha256sum > SHA256SUMS)
tar -C $T -czf "$OUT" b; sha256sum "$OUT"; ls -la "$OUT"; rm -rf $T
