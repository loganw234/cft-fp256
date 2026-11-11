#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-B follow-up: CUDA 13's cudaDeviceProp has no clockRate, which
cft_fma.hip prints from HIP's hipDeviceProp_t.  Copies GPU-A's study header
(cudahip/hip/hip_runtime.h) to OUT and adds a clockRate field filled by
cudaDeviceGetAttribute.  GPU-A's file is not touched.
Usage: mk_shim13.py GPU_A_HEADER OUT_HEADER"""
import sys
s = open(sys.argv[1]).read()
a = "struct hipDeviceProp_t : cudaDeviceProp { char gcnArchName[256]; };"
b = "    return cudaGetDeviceProperties(p, dev);\n"
assert s.count(a) == 1 and s.count(b) == 1
s = s.replace(a, "struct hipDeviceProp_t : cudaDeviceProp { char gcnArchName[256]; int clockRate; };")
s = s.replace(b, "    cudaError_t e = cudaGetDeviceProperties(p, dev);\n"
                 "    if (e == cudaSuccess)\n"
                 "        e = cudaDeviceGetAttribute(&p->clockRate, cudaDevAttrClockRate, dev);\n"
                 "    return e;\n")
open(sys.argv[2], "w").write(s)
