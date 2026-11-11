#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# ocl_run.sh [harness flags, e.g. --platform 0 --device 0]
# GPU-D's checks on one OpenCL device, run from inside the unpacked bundle
# (make_bundle.sh: bin/cft_fma_ocl, cft_fma.cl, corpus/, gen_corpus.py).
# BIN, CL, CORP and OUT override the paths (the Mac runs its own build: BIN).
#   1. the plants first, each must be RED: the flipped corpus (one result,
#      and the output still the golden one), rmm-as-rne and drop-flag
#      (GPU-A's macros as build options), each output at GPU-A's planted hash;
#   2. conf-fp32/64/128/256, stream-fp32 and stream-fp256 GREEN at the hashes
#      gen_corpus.py expects, then gen_corpus.py verify on each if python3 runs;
#   3. the fp256 FMA rate: stream-fp256, 1,000,000 lanes, median of 10.
# Reads and writes only inside this directory; Linux or macOS (bash 3.2).
# Last line ALL AS EXPECTED (exit 0) or SOMETHING DIFFERS (exit 1).
set -uo pipefail
cd "$(dirname "$0")"
BIN=${BIN:-bin/cft_fma_ocl}; CL=${CL:-cft_fma.cl}; CORP=${CORP:-corpus}; OUT=${OUT:-out}
T=${T:-110}                                   # seconds one harness run may take
mkdir -p "$OUT"; rm -f "$OUT"/*.out; : > "$OUT/log.txt"; rc=0
# PoCL runs a work-group on one thread of this process, and at the kernel's own
# work-group size (4096 there) the lanes' private memory overflows glibc's default
# 8 MB thread stack: a segfault (MEASURED). glibc sizes thread stacks from this
# limit, for this process alone. A GPU's lanes do not live on these stacks.
ulimit -s "${STACK_KB:-65536}" 2> /dev/null || echo "note: the stack limit stays $(ulimit -s) KB"
exp_of() { case $1 in                         # gen_corpus.py's "expect", GPU-A's sums
    conf-fp32) echo dd3d83be8ba2477c93246ff9e41214923ceb0687367b4d159d06ba251e7636ae ;;
    conf-fp64) echo 3a8a9b2cb98a5be99890a164720c2efd97f1653a5a9445b5de9ed5276c0e769f ;;
    conf-fp128) echo fcc92da36e24b19ce6a83d21f6459b1b04502a6518f60266259845ac21fccf25 ;;
    conf-fp256) echo da932116555557bef8fcd6980da18963b1420bfc892163c67b32d1cc53a2eba9 ;;
    stream-fp32) echo 15545866e2b21b6fc6c6ca91f8cb8dbb78b094e2d788004edfffe6afe7c98577 ;;
    stream-fp256) echo 9c7f2f6e9130003b024c94a665222b53f2176d0cff7903d532a293cae8687cb7 ;;
    rmm-as-rne) echo ffe3f2eb93608966eb4c277fdf3114b0a1b29479465131e4e81d0227758a59af ;;
    drop-flag) echo f0ca15e06fcbefb522183f534497e8e9405a35db6529f1f59217e69fe07503d4 ;;
    esac; }
tmo() { if command -v timeout > /dev/null; then timeout "$T" "$@"
        else perl -e 'alarm shift; exec @ARGV' "$T" "$@"; fi; }      # macOS: no timeout
sum256() { if command -v sha256sum > /dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
# one harness run: everything to the log; its build line and last line shown
one() { tmo "$BIN" "$@" --cl "$CL" ${H+"${H[@]}"} > "$OUT/run.txt" 2>&1; r=$?
        cat "$OUT/run.txt" >> "$OUT/log.txt"
        [ -n "$first" ] && { grep -E "^(device|program|kernel):" "$OUT/run.txt"; first=; }
        grep -E "^(build|launch|timing):" "$OUT/run.txt" | sed 's/^/    /'
        last=$(tail -1 "$OUT/run.txt"); return $r; }
H=("$@"); first=1
echo "== ocl_run.sh $(date '+%F %T'), harness flags: ${*:-(none)}, OCL_ICD_VENDORS=${OCL_ICD_VENDORS:-unset}, stack limit $(ulimit -s) KB"
if [ -f SHA256SUMS ]; then
    sum256 -c --quiet SHA256SUMS || { echo "bundle sums differ: stop"; exit 1; }
    echo "bundle sums: OK"
fi
echo "== plants first (each must be RED)"
plant() { n=$1; shift; one "$@"; echo "$last" | cut -c1-160
    h=$(echo "$last" | sed -nE 's/.*sha256 ([0-9a-f]{64}).*/\1/p')
    case $n in flip) want=$(exp_of conf-fp256); grep -q "; 1 results and 0 flags differ" <<< "$last" || h=x ;;
               *) want=$(exp_of $n) ;; esac
    if grep -q ": RED$" <<< "$last" && [ "$h" = "$want" ]; then
        echo "PLANT $n: RED, as it must be; output sha256 ${h:0:16}... as GPU-A's"
    else echo "PLANT $n: NOT AS EXPECTED (RED with GPU-A's output sha256 ${want:0:16}... wanted)"; rc=1; fi; }
plant flip check "$CORP/conf-fp256-flip.bin" "$OUT/plant-flip.out"
plant rmm-as-rne check "$CORP/conf-fp256.bin" - --opts -DCFT_GPUA_PLANT_RMM_AS_RNE
plant drop-flag check "$CORP/conf-fp256.bin" - --opts -DCFT_GPUA_PLANT_DROP_FLAG=8
echo "== corpora (each must be GREEN at its expected sha256)"
for f in conf-fp32 conf-fp64 conf-fp128 conf-fp256 stream-fp32 stream-fp256; do
    one check "$CORP/$f.bin" "$OUT/$f.out"
    echo "$last" | sed -E 's/ on .*: (fp[0-9]+), ([0-9]+) cases.*(sha256 [0-9a-f]{64}); (kernel.*)$/ \1 \2 cases, \3, \4/'
    if grep -q ": GREEN$" <<< "$last" && grep -q "sha256 $(exp_of $f);" <<< "$last"; then :
    else echo "$f: NOT AS EXPECTED"; rc=1; fi
    if [ -f gen_corpus.py ] && [ -f "$OUT/$f.out" ] && python3 -c "" 2> /dev/null; then
        python3 -B gen_corpus.py verify "$CORP/$f.bin" "$OUT/$f.out" || rc=1
    fi
done
echo "== rate (fp256 FMA, 1,000,000 lanes, median of 10)"
one bench "$CORP/stream-fp256.bin" --reps 10 || rc=1
echo "$last" | sed -E 's/ on .*: fp256,/: fp256,/'
echo "== ocl_run.sh $(date '+%F %T') rc=$rc  ($([ $rc = 0 ] && echo 'ALL AS EXPECTED' || echo 'SOMETHING DIFFERS'))"
exit $rc
