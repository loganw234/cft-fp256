#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_seq_chipstar.sh PROGRAMS_DIR WORK_DIR   (part 2 of GPU-A through chipStar)
# PROGRAMS_DIR: gen_programs.py's corpora plus seq_ref's ref-*.out (GPU-A's
# run_seq.sh describes them; their sums are gpu-a/captured/programs.sha256).
# Same env as run_chipstar.sh.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
A="$here/../gpu-a"
C=${1:?PROGRAMS_DIR}; W=${2:?WORK_DIR}
CHIPSTAR=${CHIPSTAR:-/opt/gpu-c/chipstar}
export LD_LIBRARY_PATH=$CHIPSTAR/lib:${LD_LIBRARY_PATH:-}
export CHIP_BE=${CHIP_BE:-opencl} CHIP_DEVICE_TYPE=${CHIP_DEVICE_TYPE:-pocl} CHIP_LOGLEVEL=${CHIP_LOGLEVEL:-err}
DEV=${DEVICE:-0}
mkdir -p "$W"
echo "== run_seq_chipstar.sh $(date '+%F %T') $CHIP_BE/$CHIP_DEVICE_TYPE device $DEV on $(hostname)"
(cd "$C" && sha256sum -c --quiet <(grep -E "  (routines|fuzz)-fp(64|256)\.bin|systems|bench|refuse|ref-(fp64|fp256|fuzz-fp64|fuzz-fp256|systems|bench)\.out" "$A/captured/programs.sha256")) \
    || { echo "the program corpora or references differ from GPU-A's sums: refused"; exit 1; }
D64="-DCFT_MAX_FORMAT=1 -DCFT_NO_TRANSCEND"; D256="-DCFT_BN_LIMBS=40 -DCFT_NO_TRANSCEND"
B() { DEFS="$2" bash "$here/build_chipstar.sh" "$W/$1" "$A/cft_seq.hip" > "$W/$1.build.log" 2>&1 || { echo "BUILD $1 FAILED"; tail -20 "$W/$1.build.log"; exit 1; }; }
B s64 "$D64"; B s256 "$D256"
B s64-mask "$D64 -DCFT_GPUA_PLANT_SEQ_MASK"; B s64-konst "$D64 -DCFT_GPUA_PLANT_SEQ_KONST"
rc=0
chk() { local b=$1 c=$2 r=$3
    "$W/$b/cft_seq" run "$C/$c.bin" - --expect "$C/$r.out" --device "$DEV" 2>&1 | grep -v "^CHIP" | sed "s|$C/||g; s|$W/||g" | tail -1
    [ "${PIPESTATUS[0]}" = 0 ] || rc=1; }
chk s64 routines-fp64 ref-fp64;  chk s256 routines-fp256 ref-fp256
chk s64 fuzz-fp64 ref-fuzz-fp64; chk s256 fuzz-fp256 ref-fuzz-fp256
chk s256 systems ref-systems;    chk s256 bench ref-bench
out=$("$W/s256/cft_seq" run "$C/refuse.bin" - --device "$DEV" 2>&1 | grep -v "^CHIP")
grep "^refused: " <<< "$out"
grep -q "^refused: fp64 augadd: augmentedAddition" <<< "$out" || { echo "refusal: NOT refused"; rc=1; }
for x in s64-mask s64-konst; do
    "$W/$x/cft_seq" run "$C/routines-fp64.bin" - --expect "$C/ref-fp64.out" --device "$DEV" > "$W/$x.run.log" 2>&1
    if [ $? = 1 ]; then echo "plant $x: RED, as it must be"; else echo "plant $x: NOT red"; rc=1; fi
done
echo "== run_seq_chipstar.sh $(date '+%F %T') rc=$rc"
exit $rc
