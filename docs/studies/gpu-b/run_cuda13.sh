#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B follow-up: the same legs under CUDA 13 (/usr/local/cuda-13.3 here),
# beside 12.9, which stays /usr/local/cuda.   run_cuda13.sh build|gpu [W]
#   W   work root (default ~/gpu-b13); HP13 the HIP prefix (default /opt/gpu-b13);
#       SRC the rocm-systems clone (default ~/gpu-b/src/rs-10.1);
#       HIP724 GPU-A's HIP 7.2.4 prefix (default /opt/rocm-7.2.4, read only);
#       CORPUS (default ~/gpu-a/corpus, read only)
#   build  (a) HIP 7.16 for NVIDIA from the 10.1 sources WITHOUT the C1 patch:
#              build_hip_nv.sh, build_hipcc.sh, the E3 attempt, then the
#              plain and hipcc builds and the toolchain_check binaries;
#          (b) GPU-A's two legs from GPU-A's sources: `nvidia` (HIP 7.2.4's
#              frozen NVIDIA layer) and `cuda` (the 52-line header), which
#              fails on CUDA 13 (clockRate) and is then built again with a
#              one-field shim in a copy of the header (acuda13).
#   gpu    the RTX 5060 Ti only (CUDA device 1), nvidia-smi before each run,
#          one run under 60 s each: toolchain_check (a), conf-fp256 on every
#          build; gen_corpus.py verify after each.
# Logs: $W/*.log, $W/out/.   Needs the studies/gpu-a sources beside this dir.
set -u
MODE=${1:?build|gpu}; W=${2:-$HOME/gpu-b13}
HP13=${HP13:-/opt/gpu-b13}; SRC=${SRC:-$HOME/gpu-b/src/rs-10.1}
HIP724=${HIP724:-/opt/rocm-7.2.4}; CORPUS=${CORPUS:-$HOME/gpu-a/corpus}
here=$(cd "$(dirname "$0")" && pwd); A="$here/../gpu-a"
export CUDA_HOME=/usr/local/cuda-13.3; export CUDA_PATH=$CUDA_HOME
export PATH=$CUDA_HOME/bin:/usr/lib/wsl/lib:$PATH
O="$W/out"; mkdir -p "$O"
say() { echo "== $* $(date '+%T')"; }

if [ "$MODE" = build ]; then
    nvcc --version | tail -2
    say "(a) HIP from source, CUDA 13, no C1"
    mkdir -p "$HP13"
    BLD="$W/build-hip" bash "$here/build_hip_nv.sh" "$SRC" "$HP13" > "$W/hip.log" 2>&1; tail -9 "$W/hip.log"
    BLD="$W/build-hipcc" bash "$here/build_hipcc.sh" "${SRC%/rs-10.1}/llvm-10.1" "$HP13" > "$W/hipcc.log" 2>&1; head -6 "$W/hipcc.log"
    say "attempt A (plain nvcc on toolchain_check.hip, no patch)"
    bash "$here/attempt_a.sh" "$HP13" "$O/a" | head -14
    say "cft_fma, plain nvcc"
    HP="$HP13" bash "$here/build.sh" plain "$O/plain" 89 120 > "$O/plain.log" 2>&1; echo "rc=$?"; grep -m6 ' error\|FAILED' "$O/plain.log"
    say "cft_fma, hipcc"
    HP="$HP13" bash "$here/build.sh" hipcc "$O/hipcc-build" 89 120 > "$O/hipcc-build.log" 2>&1; echo "rc=$?"; grep -m6 ' error\|FAILED' "$O/hipcc-build.log"
    say "toolchain_check binaries"
    bash "$here/build_tc.sh" "$O" "$HP13" 2>&1 | tail -4
    say "(b) GPU-A's HIP 7.2.4 leg (build.sh nvidia)"
    HIP_PATH="$HIP724" PATH="$HIP724/bin:$PATH" bash "$A/build.sh" nvidia "$O/a724" 89 120 > "$O/a724.log" 2>&1
    echo "rc=$?"; grep -m8 ' error\|FAILED' "$O/a724.log"
    say "(b) GPU-A's header leg (build.sh cuda)"
    bash "$A/build.sh" cuda "$O/acuda" 89 120 > "$O/acuda.log" 2>&1; echo "rc=$?"; grep -m8 ' error\|FAILED' "$O/acuda.log"
    say "(b) the header leg again, with a clockRate shim (CUDA 13's cudaDeviceProp has no clockRate)"
    # a copy of GPU-A's header with one field added (mk_shim13.py); GPU-A's file is not touched
    mkdir -p "$O/shim/hip"
    python3 -I -B "$here/mk_shim13.py" "$A/cudahip/hip/hip_runtime.h" "$O/shim/hip/hip_runtime.h"
    diff "$A/cudahip/hip/hip_runtime.h" "$O/shim/hip/hip_runtime.h" | grep -c '^>' | sed 's/^/shim: lines added: /'
    mkdir -p "$O/acuda13"
    G="-gencode arch=compute_89,code=sm_89 -gencode arch=compute_120,code=sm_120"
    nvcc -x cu -I"$O/shim" -O2 -std=c++17 $G -Xptxas -v -I"$O/acuda/devsrc" -I"$O/acuda/sha"         -c "$A/cft_fma.hip" -o "$O/acuda13/cft_fma.o" > "$O/acuda13.log" 2>&1; echo "compile rc=$?"
    grep -m6 ' error' "$O/acuda13.log"
    nvcc "$O/acuda13/cft_fma.o" "$O/acuda/sha256.o" -o "$O/acuda13/cft_fma" >> "$O/acuda13.log" 2>&1; echo "link rc=$?"
    exit 0
fi

# gpu
smi() {
    local i
    for i in 1 2 3 4 5 6; do
        echo "-- $(date '+%T') nvidia-smi"
        nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used --format=csv,noheader
        nvidia-smi --query-compute-apps=gpu_bus_id,pid,process_name,used_memory --format=csv,noheader
        [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ] && return 0
        sleep 10
    done
    echo "card busy: run skipped"; return 1
}
rc=0
for t in tc_plain tc_hipcc; do
    smi && { echo "+ $t"; CUDA_VISIBLE_DEVICES=1 timeout 60 "$O/$t" || rc=1; }
done
for b in plain hipcc-build a724 acuda13; do
    [ -x "$O/$b/cft_fma" ] || { echo "not run: $b (no binary)"; rc=1; continue; }
    smi && { echo "+ cft_fma ($b) conf-fp256"
        timeout 60 "$O/$b/cft_fma" check "$CORPUS/conf-fp256.bin" "$O/$b-conf-fp256.out" --device 1 || rc=1
        python3 -B "$A/gen_corpus.py" verify "$CORPUS/conf-fp256.bin" "$O/$b-conf-fp256.out" || rc=1; }
done
echo "== run_cuda13.sh gpu rc=$rc $(date '+%F %T')"
exit $rc
