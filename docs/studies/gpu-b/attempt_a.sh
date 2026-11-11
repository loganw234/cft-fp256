#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B attempt A: plain nvcc (no hipcc), the HIP install built by build_hip_nv.sh
# on the include path, -D__HIP_PLATFORM_NVIDIA__.
# usage: attempt_a.sh PREFIX OUTDIR [extra nvcc flags]   (PREFIX = our HIP install, e.g. /opt/gpu-b)
#   no GPU run; compile only (-c)
set -u
HP=${1:?HIP prefix}; OUT=${2:?outdir}; shift 2
here=$(cd "$(dirname "$0")" && pwd)
export PATH=/usr/local/cuda/bin:$PATH
mkdir -p "$OUT"
S="$here/../gpu-a/toolchain_check.hip"
nvcc -x cu -O2 -std=c++17 -gencode arch=compute_89,code=sm_89 -gencode arch=compute_120,code=sm_120 \
  -D__HIP_PLATFORM_NVIDIA__ -I"$HP/include" \
  "$@" -c "$S" -o "$OUT/toolchain_check.o" > "$OUT/nvcc.log" 2>&1
echo "nvcc rc=$?"
grep -c 'error' "$OUT/nvcc.log"
grep -m12 'error' "$OUT/nvcc.log"
