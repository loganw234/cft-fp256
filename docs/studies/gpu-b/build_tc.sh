#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B: the two toolchain_check binaries gpu_run.sh runs, against the HIP
# built by build_hip_nv.sh and build_hipcc.sh.   build_tc.sh OUTDIR [HP]
#   OUTDIR/tc_plain  plain nvcc, -I$HP/include -D__HIP_PLATFORM_NVIDIA__
#   OUTDIR/tc_hipcc  the hipcc built from source, GPU-A's line
# (gpu_run.sh also needs OUTDIR/plain and OUTDIR/hipcc-build from
# build.sh plain|hipcc.)  Compile and link only; no GPU.
set -eu
OUT=${1:?OUTDIR}; HP=${2:-/opt/gpu-b}
here=$(cd "$(dirname "$0")" && pwd)
T="$here/../gpu-a/toolchain_check.hip"
G="-gencode arch=compute_89,code=sm_89 -gencode arch=compute_120,code=sm_120"
export PATH=/usr/local/cuda/bin:$PATH
mkdir -p "$OUT"
nvcc -x cu -D__HIP_PLATFORM_NVIDIA__ -I"$HP/include" -O2 $G "$T" -o "$OUT/tc_plain"
HIP_PLATFORM=nvidia HIP_PATH="$HP" "$HP/bin/hipcc" -x cu -isystem "$HP/include" -O2 $G "$T" -o "$OUT/tc_hipcc"
ls -l "$OUT/tc_plain" "$OUT/tc_hipcc"
