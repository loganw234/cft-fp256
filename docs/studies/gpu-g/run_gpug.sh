#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_gpug.sh OUTDIR CORPUS_DIR      GPU-G's whole chain on one Linux host (cft-gpu: PoCL, clspv,
# Tint, SPIRV-Tools, gcc), every step's rc shown; OUTDIR must not exist.
#   1. the texts: devcopy.py (GPU-A), oclcopy.py (GPU-D: the control), wgslcopy.py (this study:
#      the edited text), its --selftest and --check;
#   2. the rsqrt seed: wgslcopy.py --seedcheck, gcc with UBSan, all 1,024 inputs equal; the
#      --plant copy (one wrong entry) must be refused;
#   3. clspv, the edited text to SPIR-V, plain and with GPU-A's two plant macros: the
#      capabilities by spirv-dis, Int64 and Int8 refused; sizes and sha256;
#   4. tint, SPIR-V to WGSL and the WGSL read back, rc 0 each; lines and sha256;
#   5. PoCL: GPU-D's bundle (make_bundle.sh: harness, unedited text, corpora, ocl_run.sh), the
#      edited text added, ocl_run.sh on the unedited text (the control) and on the edited one
#      with --wg 64 (PoCL reports 4096 for a kernel that requires 64, and the launch fails);
#   6. the probe page: make_probe.py's subset (1,024 cases a format), the harness on it with the
#      edited text, plain and planted, and the page filled with the digests and the blob.
# env: ROOT (the tree, default this repository), X (the tools, default /opt/gpu-f/bin), and
# PoCL's OCL_ICD_VENDORS. The corpora are gen_corpus.py's, checked against GPU-A's sums here.
# Last line ALL AS EXPECTED (exit 0) or SOMETHING DIFFERS (exit 1).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
ROOT=${ROOT:-$(cd "$here/../../.." && pwd)}; X=${X:-/opt/gpu-f/bin}
O=${1:?OUTDIR}; C=$(realpath "${2:?CORPUS_DIR}")
[ -e "$O" ] && { echo "REFUSED: $O exists"; exit 1; }
mkdir -p "$O"; O=$(realpath "$O"); rc=0
CLSPV_OPTS=(--cl-std=CL1.2 --inline-entry-points --pod-ubo --int8=false)
bad() { echo "NOT AS EXPECTED: $*"; rc=1; }
sum() { sha256sum "$1" | cut -c1-64; }
echo "== run_gpug.sh $(date '+%F %T') on $(uname -sm); tree $(git -C "$ROOT" rev-parse HEAD 2> /dev/null || echo 'not a git checkout')"
echo "== 1. the texts"
python3 -B "$ROOT/docs/studies/gpu-a/devcopy.py" --root "$ROOT" --out "$O/devsrc" > "$O/devcopy.txt" || bad devcopy
tail -1 "$O/devcopy.txt"
python3 -B "$ROOT/docs/studies/gpu-d/oclcopy.py" "$O/devsrc" "$O/cft_fma.cl" > "$O/oclcopy.txt" || bad oclcopy
head -1 "$O/oclcopy.txt"
python3 -B "$here/wgslcopy.py" "$O/devsrc" "$O/cft_fma_g.cl" || bad wgslcopy
python3 -B "$here/wgslcopy.py" "$O/devsrc" - --selftest > "$O/selftest.txt" 2>&1 || bad "wgslcopy --selftest"
tail -1 "$O/selftest.txt"
python3 -B "$here/wgslcopy.py" "$O/devsrc" "$O/cft_fma_g.cl" --check > /dev/null || bad "wgslcopy --check"
echo "== 2. the rsqrt seed, both ways, gcc $(gcc -dumpfullversion)"
for p in "" --plant; do
    n=seedcheck${p:+-plant}
    python3 -B "$here/wgslcopy.py" "$O/devsrc" "$O/$n.c" --seedcheck $p > /dev/null || bad "$n.c"
    gcc -O2 -std=c99 -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all \
        "$O/$n.c" -o "$O/$n" || bad "gcc $n.c"
    "$O/$n" > "$O/$n.txt" 2>&1; r=$?; tail -1 "$O/$n.txt"
    if [ -z "$p" ]; then grep -q "^seedcheck: 1024 inputs, 0 differ: OK$" "$O/$n.txt" && [ $r = 0 ] || bad "$n"
    else grep -q "^seedcheck: 1024 inputs, 1 differ: REFUSED$" "$O/$n.txt" && [ $r = 1 ] \
        && echo "PLANT seedcheck: refused, as it must be" || bad "$n (the plant was not refused)"; fi
done
echo "== 3. clspv ${CLSPV_OPTS[*]} and 4. tint; the tools' sha256:"
(cd "$X" && sha256sum clspv tint spirv-dis | sed 's/^/    /')
for v in plain rmm-as-rne drop-flag; do
    case $v in plain) D=() ;; rmm-as-rne) D=(-DCFT_GPUA_PLANT_RMM_AS_RNE) ;;
               drop-flag) D=(-DCFT_GPUA_PLANT_DROP_FLAG=8) ;; esac
    s=$O/fma-$v
    "$X/clspv" "${CLSPV_OPTS[@]}" "${D[@]}" "$O/cft_fma_g.cl" -o "$s.spv" > "$s.clspv.txt" 2>&1 || bad "clspv $v"
    "$X/spirv-dis" "$s.spv" -o "$s.spvasm" || bad "spirv-dis $v"
    caps=$(grep -E '^ *OpCapability' "$s.spvasm" | awk '{print $2}' | tr '\n' ' ')
    echo "$v: clspv ${D[*]:-(no -D)}: $(stat -c %s "$s.spv") B of SPIR-V, sha256 $(sum "$s.spv"); capabilities: $caps"
    grep -qE 'OpCapability (Int64|Int8)\b' "$s.spvasm" && bad "$v: Int64 or Int8 in the SPIR-V"
    "$X/tint" "$s.spv" --format wgsl -o "$s.wgsl" > "$s.tint.txt" 2>&1 || { bad "tint $v"; head -5 "$s.tint.txt"; continue; }
    "$X/tint" "$s.wgsl" --input-format wgsl --format wgsl -o "$s.back.wgsl" > "$s.back.txt" 2>&1 \
        || { bad "tint read-back $v"; head -5 "$s.back.txt"; }
    echo "$v: tint spv -> wgsl rc 0: $(wc -l < "$s.wgsl") lines, $(stat -c %s "$s.wgsl") B, sha256 $(sum "$s.wgsl"); read back rc 0"
done
grep -h -c 'warning' "$O"/fma-*.clspv.txt | tr '\n' ' ' | sed 's/^/clspv warnings (plain, rmm, drop): /'; echo
echo "== 5. PoCL: GPU-D's bundle, ocl_run.sh on the unedited text (control), then on the edited one"
(cd "$C" && sha256sum -c --quiet "$ROOT/docs/studies/gpu-a/captured/corpus.sha256") && echo "corpora: GPU-A's sums" || bad corpora
(cd "$ROOT" && bash docs/studies/gpu-d/make_bundle.sh "$O/ocl-bundle.tar.gz" "$C" "$O/bundle-work" > "$O/make_bundle.log" 2>&1) || bad make_bundle.sh
mkdir -p "$O/run" && tar -C "$O/run" -xzf "$O/ocl-bundle.tar.gz" && cp "$O/cft_fma_g.cl" "$O/run/b/" || bad unpack
export POCL_CACHE_DIR=${POCL_CACHE_DIR:-$O/pocl-cache}; mkdir -p "$POCL_CACHE_DIR"
(cd "$O/run/b" && OUT=out-control bash ./ocl_run.sh) > "$O/ocl-control.txt" 2>&1 || bad "ocl_run.sh, the unedited text"
(cd "$O/run/b" && CL=cft_fma_g.cl OUT=out-edited bash ./ocl_run.sh --wg 64) > "$O/ocl-edited.txt" 2>&1 \
    || bad "ocl_run.sh, the edited text"
for t in control edited; do
    grep -E '^(program|PLANT|check|verify|bench|== ocl_run.sh .* rc=)' "$O/ocl-$t.txt" | sed "s/^/$t: /" | cut -c1-200
done
echo "== 6. the probe page: 1,024 cases a format from the conformance corpora, PoCL's sums on them, the page"
python3 -B "$here/make_probe.py" subset "$C" "$O/probe" || bad "make_probe.py subset"
for f in fp32 fp64 fp128 fp256; do
    for v in plain rmm-as-rne drop-flag; do
        case $v in plain) D=() ;; rmm-as-rne) D=(--opts -DCFT_GPUA_PLANT_RMM_AS_RNE) ;;
                   drop-flag) D=(--opts -DCFT_GPUA_PLANT_DROP_FLAG=8) ;; esac
        (cd "$O/run/b" && timeout 110 bin/cft_fma_ocl check "$O/probe/probe-$f.bin" "$O/probe/$v-$f.out" \
            --cl cft_fma_g.cl --wg 64 "${D[@]}") > "$O/probe/$v-$f.txt" 2>&1        # a plant's rc is 1
        tail -1 "$O/probe/$v-$f.txt" | sed -E "s/^check: .*: (fp[0-9]+), ([0-9]+) cases .*; ([0-9]+ results and [0-9]+ flags differ).*(sha256 [0-9a-f]{16}).*: (RED|GREEN)$/$v \1: \2 cases, \3, \4..., \5/"
    done
done
python3 -B "$here/make_probe.py" page "$O/probe" "$O" "$here/fma_probe.html" "$O/fma_probe.html" || bad "make_probe.py page"
cmp -s "$O/fma_probe.html" "$here/fma_probe.html" && echo "fma_probe.html: equal to the committed page, byte for byte" \
    || echo "fma_probe.html: NOT the committed page's bytes (the new one is in $O)"
echo "== run_gpug.sh $(date '+%F %T') rc=$rc  ($([ $rc = 0 ] && echo 'ALL AS EXPECTED' || echo 'SOMETHING DIFFERS'))"
exit $rc
