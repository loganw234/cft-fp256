#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_wsl_nvidia.sh CORPUS_DIR WORK_DIR
#
# The desktop's runbook: the RTX 4070 (sm_89) and the RTX 5060 Ti (sm_120)
# from a Linux with CUDA 12.9 and HIP 7.2.4's NVIDIA platform (on this
# desktop, the WSL distro the study names; the study records its installs),
# plus the two CPU legs. CORPUS_DIR holds gen_corpus.py's output.
#
#   1. devcopy's own plants, then every build: cpu, cpu-libcft, nvidia
#      (sm_89 + sm_120), and the plant builds (rmm taken as rne; the
#      underflow flag dropped)
#   2. the third plant's corpus: conf-fp256 with one expected bit flipped
#   3. every corpus on each CPU leg and each card (DEVICES, default "1 0":
#      the 5060 Ti first, as the brief prefers), nvidia-smi before each card
#   4. each plant on each CPU leg and card it is run on; each must be RED
#   5. the second kernel (--kernel fixed): the fp256 corpora on the CPU and
#      each card, its plants on each card, and the differential stream
#      against the first kernel (diff: 2^30 cases on the 5060 Ti, 2^28 on
#      the 4070, seed 20261110; 200,000 on the CPU, seed 1)
#   6. the same source through plain nvcc and the study's header (cudahip/,
#      no HIP): every corpus, both kernels, rmm-as-rne, a 2^28 diff a card
#
# Light by design: each card's runs take seconds. Logs go to stdout.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
C=${1:?CORPUS_DIR}; W=${2:?WORK_DIR}
export HIP_PATH=${HIP_PATH:-/opt/rocm-7.2.4}
export PATH=$HIP_PATH/bin:/usr/local/cuda/bin:/usr/lib/wsl/lib:$PATH
B=$W/build; O=$W/out
mkdir -p "$B" "$O"
echo "== run_wsl_nvidia.sh $(date '+%F %T')"
python3 -B "$here/devcopy.py" --selftest || exit 1
bash "$here/build.sh" cpu "$B/cpu" || exit 1
bash "$here/build.sh" cpu-libcft "$B/cpu-libcft" || exit 1
bash "$here/build.sh" nvidia "$B/nvidia" 89 120 || exit 1
DEFS=-DCFT_GPUA_PLANT_RMM_AS_RNE bash "$here/build.sh" cpu "$B/cpu-plant-rmm" || exit 1
DEFS=-DCFT_GPUA_PLANT_RMM_AS_RNE bash "$here/build.sh" nvidia "$B/nvidia-plant-rmm" 89 120 || exit 1
DEFS=-DCFT_GPUA_PLANT_DROP_FLAG=8 bash "$here/build.sh" cpu "$B/cpu-plant-uf" || exit 1
DEFS=-DCFT_GPUA_PLANT_DROP_FLAG=8 bash "$here/build.sh" nvidia "$B/nvidia-plant-uf" 89 120 || exit 1
python3 -B "$here/gen_corpus.py" flip "$C/conf-fp256.bin" "$W/conf-fp256-flip.bin" \
    --index 12345 --bit 0 || exit 1

gpu_state() {
    echo "-- $(date '+%T') nvidia-smi"
    nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used --format=csv,noheader
    nvidia-smi --query-compute-apps=gpu_bus_id,pid,process_name,used_memory --format=csv,noheader
}
# A plant passes when the check goes RED; GREEN means the check cannot see it.
plant() {
    local name=$1; shift
    if "$@"; then echo "PLANT $name: GREEN - the check did not see it"; return 1; fi
    echo "PLANT $name: RED, as it must be"
}

rc=0
bash "$here/run_checks.sh" "$B/cpu/cft_fma" cpu "$C" "$O" || rc=1
bash "$here/run_checks.sh" "$B/cpu-libcft/cft_fma" cpu-libcft "$C" "$O" || rc=1
for d in ${DEVICES:-1 0}; do
    gpu_state
    "$B/nvidia/cft_fma" info --device "$d"
    bash "$here/run_checks.sh" "$B/nvidia/cft_fma" "nv$d" "$C" "$O" --device "$d" || rc=1
done

echo "== plants"
plant "flip/cpu" "$B/cpu/cft_fma" check "$W/conf-fp256-flip.bin" "$O/plant-flip-cpu.out" || rc=1
plant "flip/cpu verify" python3 -B "$here/gen_corpus.py" verify "$W/conf-fp256-flip.bin" "$O/plant-flip-cpu.out" || rc=1
plant "rmm-as-rne/cpu" "$B/cpu-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - || rc=1
plant "drop-underflow/cpu" "$B/cpu-plant-uf/cft_fma" check "$C/conf-fp256.bin" - || rc=1
for d in ${DEVICES:-1 0}; do
    gpu_state
    plant "flip/nv$d" "$B/nvidia/cft_fma" check "$W/conf-fp256-flip.bin" "$O/plant-flip-nv$d.out" --device "$d" || rc=1
    plant "flip/nv$d verify" python3 -B "$here/gen_corpus.py" verify "$W/conf-fp256-flip.bin" "$O/plant-flip-nv$d.out" || rc=1
    plant "rmm-as-rne/nv$d" "$B/nvidia-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$d" || rc=1
    plant "drop-underflow/nv$d" "$B/nvidia-plant-uf/cft_fma" check "$C/conf-fp256.bin" - --device "$d" || rc=1
done
echo "== the second kernel (fma256_fixed.h, binary256): corpora, plants, the differential stream"
CORPORA="conf-fp256 stream-fp256" bash "$here/run_checks.sh" "$B/cpu/cft_fma" cpu-fixed "$C" "$O" \
    --kernel fixed || rc=1
"$B/cpu/cft_fma" diff 200000 1 || rc=1
for d in ${DEVICES:-1 0}; do
    gpu_state
    CORPORA="conf-fp256 stream-fp256" bash "$here/run_checks.sh" "$B/nvidia/cft_fma" "nv$d-fixed" \
        "$C" "$O" --device "$d" --kernel fixed || rc=1
    plant "fixed rmm-as-rne/nv$d" "$B/nvidia-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$d" --kernel fixed || rc=1
    plant "fixed drop-underflow/nv$d" "$B/nvidia-plant-uf/cft_fma" check "$C/conf-fp256.bin" - --device "$d" --kernel fixed || rc=1
    # 2^30 cases on the 5060 Ti, 2^28 on the 4070, which drives the display
    timeout 60 "$B/nvidia/cft_fma" diff "$([ "$d" = 1 ] && echo 1073741824 || echo 268435456)" 20261110 \
        --device "$d" || rc=1
done
echo "== plain nvcc and the study's header (cudahip/), no HIP on the include path"
bash "$here/build.sh" cuda "$B/cuda" 89 120 | grep -E '^\+ nvcc' || exit 1
DEFS=-DCFT_GPUA_PLANT_RMM_AS_RNE bash "$here/build.sh" cuda "$B/cuda-plant-rmm" 89 120 > /dev/null || exit 1
echo "lines of the preprocessed source that name a HIP install: $(nvcc -x cu -E -I"$here/cudahip" \
    -I"$B/cuda/devsrc" -I"$B/cuda/sha" "$here/cft_fma.hip" | grep -c 'rocm\|nvidia_detail')"
for d in ${DEVICES:-1 0}; do
    gpu_state
    bash "$here/run_checks.sh" "$B/cuda/cft_fma" "cuda-nv$d" "$C" "$O" --device "$d" || rc=1
    CORPORA="conf-fp256 stream-fp256" bash "$here/run_checks.sh" "$B/cuda/cft_fma" "cuda-nv$d-fixed" \
        "$C" "$O" --device "$d" --kernel fixed || rc=1
    plant "cuda rmm-as-rne/nv$d" "$B/cuda-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$d" || rc=1
    plant "cuda fixed rmm-as-rne/nv$d" "$B/cuda-plant-rmm/cft_fma" check "$C/conf-fp256.bin" - --device "$d" --kernel fixed || rc=1
    timeout 60 "$B/cuda/cft_fma" diff 268435456 20261110 --device "$d" || rc=1
done
echo "== run_wsl_nvidia.sh $(date '+%F %T'): $([ $rc = 0 ] && echo 'all GREEN, every plant RED' || echo 'SOMETHING WRONG')"
exit $rc
