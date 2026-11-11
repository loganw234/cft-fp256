#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B step 3b: what hipcc (built from amd/hipcc at 10.1) does on the NVIDIA
# platform, from the plainest command to GPU-A's workaround.  hipcc_probe.sh HP OUTDIR
# (compile only; no GPU)
HP=${1:?HIP prefix}; O=${2:?outdir}; mkdir -p "$O"
here=$(cd "$(dirname "$0")" && pwd)
T="$here/../gpu-a/toolchain_check.hip"
export HIP_PLATFORM=nvidia HIP_PATH=$HP ROCM_PATH=$HP PATH=$HP/bin:/usr/local/cuda/bin:$PATH
cd "$O"
step() { echo "--- $*"; "$@" > "$O/step.out" 2>&1; echo "rc=$?"; sed -n 1,8p "$O/step.out" | cut -c1-220; }
step hipconfig --platform
step hipconfig --version
step hipconfig --compiler
step hipconfig --full
step hipcc --version
# P1: the plainest command (what a user types)
step hipcc -O2 -c "$T" -o p1.o
# P2: with an arch, the AMD way
step hipcc -O2 --offload-arch=sm_89 -c "$T" -o p2.o
# P3: with nvcc's own flags, and the .hip suffix
step hipcc -O2 -gencode arch=compute_89,code=sm_89 -c "$T" -o p3.o
# P4: -x cu
step hipcc -x cu -O2 -gencode arch=compute_89,code=sm_89 -c "$T" -o p4.o
# P5: GPU-A's workaround line
step hipcc -x cu -isystem "$HP/include" -O2 -std=c++17 -gencode arch=compute_89,code=sm_89 -gencode arch=compute_120,code=sm_120 -c "$T" -o p5.o
