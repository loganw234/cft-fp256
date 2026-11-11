#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-B change C1: ROCm 10.1's nvidia_hip_runtime_api.h uses CUDA 13 runtime
names (green contexts: cudaExecutionContext_t, cudaDev*Resource*, ...; the
error cudaErrorStreamDetached) with no CUDA_VERSION guard, so it does not
compile against CUDA 12.9.  This wraps those pieces in
`#if CUDA_VERSION >= 13010` in the INSTALLED copy (the sources are not
touched).  Usage: patch_cuda12.py PATH_TO_nvidia_hip_runtime_api.h
Prints what it wrapped; exits 1 if an anchor is missing."""
import sys, re

path = sys.argv[1]
s = open(path).read()
GUARD = "#if CUDA_VERSION >= 13010  /* GPU-B C1 */\n"
n = 0

def wrap(text, first, last_incl, closing_extra=""):
    """wrap from the line starting with `first` through the line `last_incl`"""
    global n
    i = text.index(first)
    j = text.index(last_incl, i)
    j = text.index("\n", j) + 1
    n += 1
    return text[:i] + GUARD + text[i:j] + "#endif  /* GPU-B C1 */\n" + text[j:]

# 1. typedefs and defines
s = wrap(s, "typedef cudaExecutionContext_t hipExecutionCtx_t;",
         "typedef cudaDevWorkqueueResource hipDevWorkqueueResource;")
# 2. the four StreamDetached case pairs
for pat in ("    case cudaErrorStreamDetached:\n      return hipErrorStreamDetached;\n",
            "    case CUDA_ERROR_STREAM_DETACHED:\n      return hipErrorStreamDetached;\n",
            "    case hipErrorStreamDetached:\n      return CUDA_ERROR_STREAM_DETACHED;\n",
            "    case hipErrorStreamDetached:\n      return cudaErrorStreamDetached;\n"):
    assert pat in s, pat
    s = s.replace(pat, GUARD + pat + "#endif  /* GPU-B C1 */\n", 1)
    n += 1
# 3. the green-context functions
i = s.index("inline static hipError_t hipDevResourceGenerateDesc(")
j = s.index("inline static hipError_t hipCtxPopCurrent(")
s = s[:i] + GUARD + s[i:j] + "#endif  /* GPU-B C1 */\n\n" + s[j:]
n += 1
open(path, "w").write(s)
print("wrapped %d pieces in %s" % (n, path))
