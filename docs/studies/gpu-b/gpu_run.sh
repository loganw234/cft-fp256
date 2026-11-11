#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B step 3c: toolchain_check and the fp256 conformance corpus on the
# RTX 5060 Ti (CUDA device 1 in this desktop's order), for the builds made
# by build.sh and build_hip_nv.sh.  gpu_run.sh OUTROOT CORPUS_DIR [DEVICE]
# OUTROOT holds tc_plain and tc_hipcc (build_tc.sh), plain/ (build.sh plain)
# and hipcc-build/ (build.sh hipcc).
# nvidia-smi before each run; a card with another compute process is waited
# for (up to 60 s), then the run is skipped and said so.
OUT=${1:?OUTROOT}; C=${2:?CORPUS_DIR}; D=${3:-1}
here=$(cd "$(dirname "$0")" && pwd)
export PATH=/usr/local/cuda/bin:/usr/lib/wsl/lib:$PATH
smi() {
    echo "-- $(date '+%T') nvidia-smi"
    nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used --format=csv,noheader
    nvidia-smi --query-compute-apps=gpu_bus_id,pid,process_name,used_memory --format=csv,noheader
}
clear_card() {
    local i
    for i in 1 2 3 4 5 6; do
        smi
        if [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]; then return 0; fi
        sleep 10
    done
    echo "card busy: run skipped"; return 1
}
echo "== gpu_run.sh $(date '+%F %T') device $D"
rc=0
clear_card && { echo "+ tc_plain"; CUDA_VISIBLE_DEVICES=$D timeout 60 "$OUT/tc_plain" || rc=1; }
clear_card && { echo "+ tc_hipcc"; CUDA_VISIBLE_DEVICES=$D timeout 60 "$OUT/tc_hipcc" || rc=1; }
for b in plain hipcc-build; do
    clear_card && { echo "+ cft_fma ($b) conf-fp256"; \
        timeout 60 "$OUT/$b/cft_fma" check "$C/conf-fp256.bin" "$OUT/$b-conf-fp256.out" --device "$D" || rc=1; \
        python3 -B "$here/../gpu-a/gen_corpus.py" verify "$C/conf-fp256.bin" "$OUT/$b-conf-fp256.out" || rc=1; }
done
echo "== gpu_run.sh $(date '+%F %T') rc=$rc"
exit $rc
