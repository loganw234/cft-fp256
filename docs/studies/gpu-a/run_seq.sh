#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_seq.sh PLATFORM PROGRAMS_DIR WORK_DIR [ARCH...]     (part 2: programs)
#
# PLATFORM nvidia (HIP_PATH; ARCH compute capabilities, default "89 120") or
# amd (ROCm; ARCH gfx targets, default gfx1102; the first is run, the rest
# built only). PROGRAMS_DIR holds gen_programs.py's corpora and seq_ref's
# outputs for them (ref-*.out), made where the golden model and libcft are:
# their sums are captured/programs.sha256, and a different set is refused.
# DEVICE=n picks the HIP device; REUSE=1 keeps WORK_DIR's builds (a second
# device). Every GPU step is preceded by the device's activity and processes
# (nvidia-smi or amd-smi), recorded, not waited on.
#
#   1. devcopy.py --selftest (both parts' plants); the runner's builds: fp64
#      (CFT_MAX_FORMAT=1), fp256 (40 limbs), fp256 with the fixed path, and
#      the two plants
#   2. every corpus (routines, fuzz, systems, bench) against libcft's
#      output, byte for byte; the refusal
#   3. the plants, each of which must go RED
#   4. the rates: bench.bin's six (exp, sin, atan at fp64 and fp256, typical
#      arguments) and the corpus's own lanes for the same routines, 1M lanes
#   5. a batch curve: fp256 exp on the fixed path, 4K to 4M lanes (16M where
#      BIG=1)
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
P=${1:?PLATFORM}; C=${2:?PROGRAMS_DIR}; W=${3:?WORK_DIR}
shift 3
DEV=${DEVICE:-0}
mkdir -p "$W"
W=$(cd "$W" && pwd); C=$(cd "$C" && pwd)
case "$P" in
nvidia) ARCHS=${*:-89 120}; RUN=$(echo $ARCHS | cut -d' ' -f1)
        smi() { nvidia-smi --query-gpu=index,name,memory.used,utilization.gpu --format=csv,noheader
                nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader; } ;;
amd)    ARCHS=${*:-gfx1102}; RUN=$(echo $ARCHS | cut -d' ' -f1)
        export PATH=${ROCM_PATH:-/opt/rocm}/bin:$PATH
        smi() { amd-smi monitor -v -u 2>&1 | sed -n 2p; amd-smi process 2>&1 | sed -n 2p; } ;;
*)      echo "PLATFORM is nvidia or amd"; exit 2 ;;
esac
S() { sed "s|$C/||g; s|$W/||g"; }
echo "== run_seq.sh $P $ARCHS $(date '+%F %T') on $(hostname)"
(cd "$C" && sha256sum -c --quiet "$here/captured/programs.sha256") || { echo "the program corpora differ: refused"; exit 1; }
python3 -B "$here/devcopy.py" --selftest | tail -1 || exit 1
B() {   # B NAME DEFS [ARCH...]
    local n=$1 d=$2; shift 2
    [ -n "${REUSE:-}" ] && [ -x "$W/$n/cft_seq" ] && return
    DEFS="$d" bash "$here/build_seq.sh" "$P" "$W/$n" "$@" > "$W/$n.build.log" 2>&1 \
        || { echo "BUILD $n FAILED"; tail -20 "$W/$n.build.log"; exit 1; }
}
D64="-DCFT_MAX_FORMAT=1 -DCFT_NO_TRANSCEND"; D256="-DCFT_BN_LIMBS=40 -DCFT_NO_TRANSCEND"
B s64 "$D64" $ARCHS; B s256 "$D256" $ARCHS; B s256f "$D256 -DCFT_GPUA_FIXED" $ARCHS
B s64-mask "$D64 -DCFT_GPUA_PLANT_SEQ_MASK" $ARCHS; B s64-konst "$D64 -DCFT_GPUA_PLANT_SEQ_KONST" $ARCHS
grep -h "devcopy: host/src/program.c" "$W/s256.build.log"
echo "== built $(date '+%F %T')"; smi
rc=0
chk() { "$@" --device "$DEV" | S | tail -2; [ "${PIPESTATUS[0]}" = 0 ] || rc=1; }
for f in fp32 fp64; do chk "$W/s64/cft_seq" run "$C/routines-$f.bin" - --expect "$C/ref-$f.out"; done
for f in fp128 fp256; do chk "$W/s256/cft_seq" run "$C/routines-$f.bin" - --expect "$C/ref-$f.out"; done
for f in fp32 fp64; do chk "$W/s64/cft_seq" run "$C/fuzz-$f.bin" - --expect "$C/ref-fuzz-$f.out"; done
for f in fp128 fp256; do chk "$W/s256/cft_seq" run "$C/fuzz-$f.bin" - --expect "$C/ref-fuzz-$f.out"; done
chk "$W/s256f/cft_seq" run "$C/fuzz-fp256.bin" - --expect "$C/ref-fuzz-fp256.out"
for x in s256 s256f; do
    chk "$W/$x/cft_seq" run "$C/systems.bin" - --expect "$C/ref-systems.out"
    chk "$W/$x/cft_seq" run "$C/bench.bin" - --expect "$C/ref-bench.out"
done
chk "$W/s256f/cft_seq" run "$C/routines-fp256.bin" - --expect "$C/ref-fp256.out"
out=$("$W/s256/cft_seq" run "$C/refuse.bin" - --device "$DEV" 2>&1)   # exit 1: refused
grep "^refused: " <<< "$out"
grep -q "^refused: fp64 augadd: augmentedAddition" <<< "$out" || { echo "refusal: NOT refused"; rc=1; }
for x in s64-mask s64-konst; do
    "$W/$x/cft_seq" run "$C/routines-fp64.bin" - --expect "$C/ref-fp64.out" --device "$DEV" | S | tail -2
    [ "${PIPESTATUS[0]}" = 1 ] && echo "plant $x: RED, as it must be" || { echo "plant $x: NOT red"; rc=1; }
done
smi
bn() { "$@" --device "$DEV" | S | sed 's/ on [^:]*), block/, block/'; }
for k in 0 1 2; do bn "$W/s64/cft_seq" bench "$C/bench.bin" --case $k --lanes 1048576 --reps 5; done
for x in s256 s256f; do
    for k in 3 4 5; do bn "$W/$x/cft_seq" bench "$C/bench.bin" --case $k --lanes 1048576 --reps 3; done
done
for k in 0 60 90; do bn "$W/s64/cft_seq" bench "$C/routines-fp64.bin" --case $k --lanes 1048576 --reps 3; done
for x in s256 s256f; do
    for k in 0 60 92; do bn "$W/$x/cft_seq" bench "$C/routines-fp256.bin" --case $k --lanes 1048576 --reps 3; done
done
smi
for n in 4096 16384 65536 262144 1048576 2097152 4194304 ${BIG:+16777216}; do
    bn "$W/s256f/cft_seq" bench "$C/bench.bin" --case 3 --lanes $n --reps 3
done
"$W/s256/cft_seq" info --device "$DEV" | S
smi
echo "== run_seq.sh $(date '+%F %T'): $([ $rc = 0 ] && echo 'every corpus GREEN, every plant RED' || echo 'SOMETHING FAILED')"
exit $rc
