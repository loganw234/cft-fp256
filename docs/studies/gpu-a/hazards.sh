#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# hazards.sh PLATFORM CORPUS_DIR WORK_DIR [harness flags, e.g. --device 1]
#
# The compilers' hazards, each run rather than argued. Every variant below
# is a build of the same source that must still give the golden model's
# results and flags on every corpus (CORPORA narrows them), so a hazard that
# bites shows as a RED line, by corpus:
#
#   cpu     -fsanitize=undefined,address (shift counts, overflow, bounds;
#           the device copy and libcft's C), -ftrivial-auto-var-init=pattern
#           and =zero (an uninitialised read changes a result), -O0
#   nvidia  --use_fast_math and -G (device code unoptimised); compute-
#           sanitizer memcheck on the conformance corpora when it is
#           installed; the SASS scanned for floating-point instructions,
#           and every HFMA2 listed by kernel with its operands
#
# A leg that does not run (compute-sanitizer absent, or printing no ERROR
# SUMMARY because it refused the device) is "not run: ..." by name with the
# reason it printed, and the verdict names it: it is never counted green.
#   amd     -ffast-math, -O0, -ftrivial-auto-var-init=pattern and =zero; the
#           ISA (--save-temps) scanned for floating-point instructions
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
P=${1:?PLATFORM}; C=${2:?CORPUS_DIR}; W=${3:?WORK_DIR}
shift 3
mkdir -p "$W/hz" "$W/hz-out"
W=$(cd "$W" && pwd); C=$(cd "$C" && pwd)       # the ISA step compiles elsewhere
B=$W/hz; O=$W/hz-out
ARCHS=${ARCHS:-}
rc=0
notrun=""
variant() {     # variant NAME TARGET XFLAGS [harness flags]
    local name=$1 target=$2 x=$3
    shift 3
    echo "== variant $name: $target XFLAGS='$x'"
    XFLAGS="$x" bash "$here/build.sh" "$target" "$B/$name" $ARCHS > "$B/$name.build.log" 2>&1 \
        || { echo "BUILD $name FAILED"; tail -20 "$B/$name.build.log"; rc=1; return; }
    grep -E "warning|runtime error" "$B/$name.build.log" | head -5
    bash "$here/run_checks.sh" "$B/$name/cft_fma" "$name" "$C" "$O" "$@" > "$B/$name.run.log" 2>&1 || rc=1
    [ "$target" = cpu-libcft ] || CORPORA="conf-fp256 stream-fp256" bash "$here/run_checks.sh" \
        "$B/$name/cft_fma" "$name-fixed" "$C" "$O" "$@" --kernel fixed >> "$B/$name.run.log" 2>&1 || rc=1
    grep -E "^(check|run_checks|not run)|runtime error|ERROR: AddressSanitizer" "$B/$name.run.log" \
        | sed 's/ (rne [^)]*)//; s/differing by attribute [0-9/]*; //' | cut -c1-230
}
fpscan() {      # fpscan FILE: count floating-point mnemonics in a disassembly
    grep -oE "$2" "$1" | sort | uniq -c | sort -rn | head -20
    echo "fpscan: $(grep -cE "$2" "$1") floating-point instruction lines in $(basename "$1")"
}
case "$P" in
cpu)
    variant cpu-ubsan-asan cpu "-O1 -g -fsanitize=undefined,address -fno-sanitize-recover=all"
    variant cpu-libcft-ubsan-asan cpu-libcft "-O1 -g -fsanitize=undefined,address -fno-sanitize-recover=all"
    variant cpu-init-pattern cpu "-ftrivial-auto-var-init=pattern"
    variant cpu-init-zero cpu "-ftrivial-auto-var-init=zero"
    variant cpu-O0 cpu "-O0"
    ;;
nvidia)
    ARCHS=${ARCHS:-"89 120"}
    variant nv-fastmath nvidia "--use_fast_math" "$@"
    variant nv-G nvidia "-G" "$@"
    if command -v compute-sanitizer > /dev/null; then
        for f in conf-fp32 conf-fp64 conf-fp128 conf-fp256; do
            out=$(compute-sanitizer --tool memcheck --print-limit 5 "$B/nv-fastmath/cft_fma" check \
                "$C/$f.bin" - "$@" 2>&1); src=$?
            sum=$(grep -m1 -E "ERROR SUMMARY: [0-9]+ error" <<< "$out")
            # "========= Error: ..." is the tool's own failure (a refused device,
            # no debugger interface), which it counts in its ERROR SUMMARY while
            # the program runs uninstrumented: not run. A memcheck finding is not
            # an "Error:" line, and a summary without one is the tool's verdict.
            if [ -z "$sum" ] || grep -qE "^=+ Error:" <<< "$out"; then
                why=$(grep -E "^=+ Error:" <<< "$out" | sed 's/^=* *Error: *//' | sort -u | tr '\n' ' ' | cut -c1-240)
                echo "not run: compute-sanitizer on $f (${why:-no ERROR SUMMARY, exit $src})"
                notrun="$notrun compute-sanitizer($f)"
                continue
            fi
            grep -E "^check" <<< "$out" | cut -c1-200
            echo "compute-sanitizer $f: $sum, exit $src"
            case "$sum" in *"ERROR SUMMARY: 0 errors"*) [ "$src" = 0 ] || rc=1 ;; *) rc=1 ;; esac
        done
    else
        echo "not run: compute-sanitizer (not installed)"
        notrun="$notrun compute-sanitizer"
    fi
    cuobjdump -sass "$W/build/nvidia/cft_fma" > "$O/sass.txt" 2>&1 || cuobjdump -sass "$B/nv-fastmath/cft_fma" > "$O/sass.txt"
    echo "SASS: $(grep -cE '^\s+/\*[0-9a-f]{4}\*/' "$O/sass.txt") instruction lines"
    fpscan "$O/sass.txt" '\b(FADD|FFMA|FMUL|FSETP|FSET|FMNMX|FCHK|FRND|F2I|F2F|I2F|I2FP|F2IP|MUFU|DADD|DFMA|DMUL|DSETP|DMNMX|HADD2|HFMA2|HMUL2|HSETP2|FSWZADD)(\.[A-Z0-9_.]+)?\b'
    # every HFMA2 by architecture and kernel, its registers as R#: count, form
    echo "HFMA2 by kernel (count, architecture, kernel, instruction):"
    awk '/code for sm_/ { arch = $3 } /Function :/ { fn = $3 }
         /HFMA2/ { l = $0; sub(/.*HFMA2/, "HFMA2", l); sub(/ *;.*/, "", l);
                   gsub(/R[0-9]+/, "R#", l); print arch, fn, l }' "$O/sass.txt" \
        | sort | uniq -c | sort -k2,3 -k1,1rn
    ;;
amd)
    ARCHS=${ARCHS:-gfx1102}
    variant amd-fastmath amd "-ffast-math" "$@"
    variant amd-O0 amd "-O0" "$@"
    variant amd-init-pattern amd "-ftrivial-auto-var-init=pattern" "$@"
    variant amd-init-zero amd "-ftrivial-auto-var-init=zero" "$@"
    mkdir -p "$B/isa" && (cd "$B/isa" && hipcc -O2 -std=c++17 --offload-arch=${ARCHS%% *} --save-temps \
        -I"$W/build/amd-${ARCHS%% *}/devsrc" -I"$W/build/amd-${ARCHS%% *}/sha" -c "$here/cft_fma.hip" \
        -o isa.o > isa.log 2>&1)
    S=$(ls "$B"/isa/*amdgcn*.s 2>/dev/null | head -1)
    if [ -n "$S" ]; then
        echo "ISA: $(grep -cE '^\s+[sv]_' "$S") instruction lines in $(basename "$S")"
        fpscan "$S" '\bv_[a-z0-9_]*_f(16|32|64)\b|\bv_(rcp|rsq|sqrt|div|frexp|ldexp|fract|trig)[a-z0-9_]*'
    else
        echo "not run: the ISA scan (no .s from --save-temps)"; rc=1
    fi
    ;;
*) echo "PLATFORM is cpu, nvidia or amd"; exit 2 ;;
esac
verdict=$([ $rc = 0 ] && echo 'every variant GREEN on every corpus run' || echo 'SOMETHING RED or FAILED')
[ -z "$notrun" ] || verdict="${verdict/every variant/every variant that ran}; NOT RUN, so not counted green:$notrun"
echo "== hazards.sh $P: $verdict"
exit $rc
