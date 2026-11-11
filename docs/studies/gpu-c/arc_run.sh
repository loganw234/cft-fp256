#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# arc_run.sh [DEVICE]   run from inside the unpacked bundle (make_bundle.sh).
# Environment (defaults are for an Intel GPU through its OpenCL runtime):
#   CHIP_BE=opencl  CHIP_DEVICE_TYPE=gpu   (rehearsal on a CPU: pocl)
#   OCL_ICD_VENDORS   a directory with the OpenCL ICD file to use ONLY (keeps the box's other ICDs out)
# Reads and writes only inside this directory. Starts no service, loads no module.
set -uo pipefail
cd "$(dirname "$0")"
DEV=${1:-0}
export LD_LIBRARY_PATH=$PWD/lib:${LD_LIBRARY_PATH:-}
export CHIP_BE=${CHIP_BE:-opencl} CHIP_DEVICE_TYPE=${CHIP_DEVICE_TYPE:-gpu} CHIP_LOGLEVEL=${CHIP_LOGLEVEL:-err}
mkdir -p out; rc=0
echo "== arc_run.sh $(date '+%F %T') on $(hostname), $CHIP_BE/$CHIP_DEVICE_TYPE device $DEV"
sha256sum -c --quiet SHA256SUMS || { echo "bundle sums differ: stop"; exit 1; }
ldd bin/cft_fma | grep -E "not found" && { echo "missing library: stop"; exit 1; }
clinfo -l 2>&1 | head -8
timeout 100 bin/cft_fma info --device $DEV 2>&1 | grep -v "^CHIP" | head -12   # hipDeviceGetLimit may error under chipStar: known
S() { grep -v "^CHIP"; }
# expected output hashes (from gen_corpus.py, = the corpus's own 'expect')
declare -A EXP=( [conf-fp32]=dd3d83be8ba2477c93246ff9e41214923ceb0687367b4d159d06ba251e7636ae
  [conf-fp64]=3a8a9b2cb98a5be99890a164720c2efd97f1653a5a9445b5de9ed5276c0e769f
  [conf-fp128]=fcc92da36e24b19ce6a83d21f6459b1b04502a6518f60266259845ac21fccf25
  [conf-fp256]=da932116555557bef8fcd6980da18963b1420bfc892163c67b32d1cc53a2eba9
  [stream-fp256]=9c7f2f6e9130003b024c94a665222b53f2176d0cff7903d532a293cae8687cb7 )
echo "== plants first (each must be RED)"
plant() { n=$1; shift; timeout 110 "$@" 2>&1 | S | tail -1 > out/plant-$n.txt
    if grep -q ": RED$" out/plant-$n.txt; then echo "PLANT $n: RED, as it must be"; else echo "PLANT $n: NOT RED"; rc=1; fi
    cut -c1-90 out/plant-$n.txt | sed 's/^/    /'; sed 's/.*differing by/    differing by/; s/;.*sha256/; sha256/' out/plant-$n.txt | cut -c1-200; }
plant flip      bin/cft_fma check corpus/conf-fp256-flip.bin out/plant-flip.out --device $DEV
plant rmm-as-rne bin/cft_fma-plant-rmm check corpus/conf-fp256.bin - --device $DEV
plant drop-flag bin/cft_fma-plant-uf check corpus/conf-fp256.bin - --device $DEV
echo "== corpora"
for f in conf-fp32 conf-fp64 conf-fp128 conf-fp256 stream-fp256; do
    o=$(timeout 110 bin/cft_fma check corpus/$f.bin out/$f.out --device $DEV 2>&1 | S | tail -1)
    echo "$o" | cut -c1-300
    grep -q "GREEN" <<< "$o" && grep -q "sha256 ${EXP[$f]}" <<< "$o" || { echo "$f: NOT as expected"; rc=1; }
done
echo "== programs (GPU-A part 2; sums of the corpora and references checked first)"
(cd programs && sha256sum -c --quiet <(grep -E "  (routines-fp64|routines-fp256|fuzz-fp64|fuzz-fp256|systems|bench|refuse)\.bin|ref-(fp64|fp256|fuzz-fp64|fuzz-fp256|systems|bench)\.out" ../programs.sha256)) || { echo "programs differ"; rc=1; }
chk() { o=$(timeout 110 bin/$1 run programs/$2.bin - --expect programs/$3.out --device $DEV 2>&1 | S | tail -1 | sed 's|programs/||g'); echo "$o" | cut -c1-300; grep -q GREEN <<< "$o" || rc=1; }
chk cft_seq-s64 routines-fp64 ref-fp64; chk cft_seq-s256 routines-fp256 ref-fp256
chk cft_seq-s64 fuzz-fp64 ref-fuzz-fp64; chk cft_seq-s256 fuzz-fp256 ref-fuzz-fp256
chk cft_seq-s256 systems ref-systems; chk cft_seq-s256 bench ref-bench
for x in s64-mask s64-konst; do
    timeout 110 bin/cft_seq-$x run programs/routines-fp64.bin - --expect programs/ref-fp64.out --device $DEV >/dev/null 2>&1
    [ $? = 1 ] && echo "plant seq-$x: RED, as it must be" || { echo "plant seq-$x: NOT RED"; rc=1; }
done
echo "== rates (fp256 FMA, 1M lanes, 10 reps; the runner's bench.bin above)"
timeout 200 bin/cft_fma bench corpus/stream-fp256.bin --device $DEV 2>&1 | S | tail -1 | cut -c1-400
echo "== arc_run.sh $(date '+%F %T') rc=$rc  ($([ $rc = 0 ] && echo 'ALL AS EXPECTED' || echo 'SOMETHING DIFFERS'))"
exit $rc
