#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The card leg of the segment runner (docs/CERTIFICATES.md, "The segment
# runner"; the plan of record's step 3, docs/ROADMAP.md): cft-segrun on
# the card over the three ODE programs at fp64 and fp256, each
# certificate's chain equal to the software backend's, and the golden
# audit accepting the card's certificates. Since the plan's step 5
# (2026-09-30) each certificate carries its program's accuracy entries,
# computed from the states the card's runs wrote, and cft-audit, the C
# auditor, must accept each as well.
#
#   bash hw/card-segrun.sh <image.xclbin> [<another image.xclbin>]
#
# From the root of a checkout of the branch under test, on the box that
# has the card, after
#
#   make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test
#
# (cft-segrun and cft-audit are in `all`; device-test is not; each links
# libcft.a statically: CLAUDE.md). python3 runs the golden model, python/cft_golden,
# which needs the standard library only; PYTHON names another.
#
# What it holds, in order, each an "ok" or a "FAIL" line:
#   1. the build: cft-segrun links XRT; the build id it carries
#      (cft-segrun --build-id) is the tree's (make print-build-id); and that
#      id names HEAD. On a CLEAN tree equal ids mean the binary is not
#      stale. On a dirty one they cannot, and NOTE lines say so (the reason
#      hw/card-identity.sh gives).
#   2. per image: device-test -i exits 0, and the identity it prints -
#      VERSION, CAPS (and CAPS2), tiles and formats - with `sha256sum` of
#      the file, is what every certificate's device lines must say. Then
#      host/tests/segrun_check.py --device <image> with those expectations:
#      each program certified ON THE CARD, keyed and open; the golden
#      reader accepting it; the golden writer, from the initial states,
#      writing the same bytes, every accuracy entry's value among them;
#      every boundary file the golden chain's; the golden audit accepting
#      it, in full and sampled, and cft-audit in full, line for line; the
#      identity lines equal to the expectations; and the same program made
#      on the software backend, every run block and the accuracy block
#      byte for byte the card's. The
#      fp64 programs carry a wider fp128 run beside the half-step one, and
#      are run without it (--no-wider, said on a NOTE line) on an image
#      whose formats lack fp128. `flagstep`, whose segments raise flags
#      and a STATUS the ODE programs never do, is certified too; a card
#      that refuses to load it (it needs strict scratch, and a deposit past
#      max_deposits 0) is a NOTE, NOT TESTED, not a failure. The gate's
#      hash vectors and refusals run on this build as well.
#   3. the negative control, required to FAIL by name: the gate handed an
#      image digest that is not this image's (device-test's own SHA-256)
#      must fail the device lines of the certificate it makes.
#
# Every segment is a run on a tile and can time out like any other: if one
# reports a timeout, reload the image - load another xclbin, then this one -
# before trusting anything after it, since an abandoned run poisons its tile
# until then.
#
# Exit 0 when every check held, 1 otherwise. The log is stdout; keep it
# beside the card day's record. Each gate log is kept in the directory the
# last line names when that gate failed.
set -uo pipefail

usage() { echo "usage: bash hw/card-segrun.sh <image.xclbin> [<another image.xclbin>]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SEG="$ROOT/host/cft-segrun"
AUD="$ROOT/host/cft-audit"
DT="$ROOT/host/device-test"
GATE="$ROOT/host/tests/segrun_check.py"
PY=${PYTHON:-python3}
LOGDIR=$(mktemp -d "${TMPDIR:-/tmp}/card-segrun.XXXXXX")
keep=0
trap '[ "$keep" = 1 ] || rm -rf "$LOGDIR"' EXIT

checks=0
failed=0
ok()  { checks=$((checks + 1)); echo "  ok    $*"; }
bad() { checks=$((checks + 1)); failed=$((failed + 1)); echo "  FAIL  $*"; }

for r in /opt/xilinx/xrt /usr/local/xrt; do
    [ -f "$r/setup.sh" ] && { set +u; source "$r/setup.sh" >/dev/null; set -u; break; }
done

imgs=()
for a in "$@"; do
    [ -f "$a" ] || { echo "no such image: $a" >&2; exit 2; }
    imgs+=("$(readlink -f "$a")")
done

echo "== card-segrun: $(date -Iseconds) on $(hostname)"
echo "   tree $ROOT at $(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo '(no git)')"
echo "   python: $("$PY" --version 2>&1)"

# ---- 1. the build ----------------------------------------------------
echo "== 1. the build"
for b in "$SEG" "$AUD" "$DT"; do
    [ -x "$b" ] || { echo "not built: $b - make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test" >&2; exit 2; }
done
echo "   cft-segrun built $(stat -c %y "$SEG")"
if ldd "$SEG" 2>/dev/null | grep -q xrt_coreutil; then
    ok "cft-segrun links XRT ($(ldd "$SEG" | grep -o 'libxrt_coreutil[^ ]*' | head -1))"
else
    bad "cft-segrun does not link XRT - built without XRT=1, it answers every xclbin with 'no such device' (CLAUDE.md)"
fi
tree_id=$(make -s -C "$ROOT/host" print-build-id 2>/dev/null)
bin_id=$("$SEG" --build-id 2>/dev/null)
echo "   the tree's build id:     $tree_id"
echo "   cft-segrun's build id:   $bin_id"
if [ -z "$bin_id" ] || [ "$bin_id" != "$tree_id" ]; then
    bad "cft-segrun carries '$bin_id' and the tree is '$tree_id' - relink it: make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all"
else
    case $tree_id in
        *" tracked=clean untracked=none")
            ok "cft-segrun carries the tree's build id, and the tree is clean: it is not stale" ;;
        *)
            echo "   NOTE: cft-segrun carries the tree's build id, but the tree is not clean ($tree_id), so equal ids do not show it is current: two edits of one commit carry one id" ;;
    esac
fi
head=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)
case $tree_id in
    "commit=$head tracked=clean untracked=none")
        ok "the build id names HEAD, clean" ;;
    "commit=$head "*)
        ok "the build id names HEAD"
        echo "   NOTE: the tree is not clean ($tree_id) - this run is not reproducible from $head" ;;
    *)
        bad "the build id '$tree_id' does not name HEAD ($head)" ;;
esac

# ---- 2. each image ---------------------------------------------------
n=0
for img in "${imgs[@]}"; do
    n=$((n + 1))
    echo "== 2.$n $img"
    want=$(sha256sum "$img" | cut -c 1-64)
    echo "   sha256sum: $want"
    log="$LOGDIR/id$n.log"
    bash "$ROOT/hw/run-device-test.sh" "$img" -i > "$log" 2>&1
    rc=$?
    line=$(grep -m1 '^image: sha256 ' "$log" || true)
    dev=$(grep -m1 '^device: backend ' "$log" || true)
    echo "   | $line"
    echo "   | $dev"
    ver=$(printf '%s' "$line" | sed -n 's/.*VERSION 0x\([0-9a-f]\{8\}\).*/\1/p')
    caps=$(printf '%s' "$line" | sed -n 's/.*, CAPS 0x\([0-9a-f]\{8\}\).*/\1/p')
    caps2=$(printf '%s' "$line" | sed -n 's/.*CAPS2 0x\([0-9a-f]\{8\}\).*/\1/p')
    tiles=$(printf '%s' "$dev" | sed -n 's/^device: backend xrt, \([0-9]*\) tiles\{0,1\},.*/\1/p')
    if [ $rc -eq 0 ] && [ -n "$ver" ] && [ -n "$caps" ] && [ -n "$tiles" ]; then
        ok "device-test -i exits 0 and names the image: VERSION $ver, CAPS $caps${caps2:+ $caps2}, $tiles tile(s)"
    else
        bad "device-test -i exited $rc, or its identity lines did not parse - the log: $log (kept)"
        keep=1
        continue
    fi
    nowider=()
    if ! printf '%s' "$dev" | grep -qw fp128; then
        nowider=(--no-wider)
        echo "   NOTE: this image carries no fp128, so the fp64 programs run without their wider run"
    fi
    glog="$LOGDIR/gate$n.log"
    CFT_EXPECT_BUILD_ID="$tree_id" "$PY" "$GATE" --tool "$SEG" --device "$img" \
        --audit "$AUD" \
        --expect-xclbin "$want" --expect-version "$ver" \
        --expect-caps "$caps${caps2:+ $caps2}" --expect-tiles "$tiles" \
        ${nowider[@]+"${nowider[@]}"} > "$glog" 2>&1
    rc=$?
    grep -E '^  (FAIL|NOTE)|^segrun_check: ' "$glog" | sed 's/^/   | /'
    if [ $rc -eq 0 ] && [ "$(tail -1 "$glog")" = "SEGRUN CHECK OK" ]; then
        ok "the certificates made on this card: $(grep '^segrun_check: ' "$glog" | tail -1 | sed 's/^segrun_check: //')"
    else
        bad "the gate on this card exited $rc - its log: $glog (kept)"
        keep=1
    fi
done

# ---- 3. the negative control -------------------------------------------
echo "== 3. the negative control"
img=${imgs[0]}
wrong=$(sha256sum "$DT" | cut -c 1-64)
clog="$LOGDIR/control.log"
line=$(grep -m1 '^image: sha256 ' "$LOGDIR/id1.log" 2>/dev/null || true)
ver=$(printf '%s' "$line" | sed -n 's/.*VERSION 0x\([0-9a-f]\{8\}\).*/\1/p')
caps=$(printf '%s' "$line" | sed -n 's/.*, CAPS 0x\([0-9a-f]\{8\}\).*/\1/p')
caps2=$(printf '%s' "$line" | sed -n 's/.*CAPS2 0x\([0-9a-f]\{8\}\).*/\1/p')
tiles=$(sed -n 's/^device: backend xrt, \([0-9]*\) tiles\{0,1\},.*/\1/p' "$LOGDIR/id1.log" 2>/dev/null | head -1)
CFT_EXPECT_BUILD_ID="$tree_id" "$PY" "$GATE" --tool "$SEG" --device "$img" \
    --audit "$AUD" \
    --expect-xclbin "$wrong" --expect-version "${ver:-00000000}" \
    --expect-caps "${caps:-00000000}${caps2:+ $caps2}" --expect-tiles "${tiles:-1}" \
    --programs lorenz63-rk4-fp64 --no-wider > "$clog" 2>&1
rc=$?
if [ $rc -ne 0 ] && grep -q '^  FAIL  lorenz63-rk4-fp64 keyed card: backend and device lines' "$clog"; then
    ok "control: handed device-test's SHA-256 as the image's, the gate FAILED the device lines by name (rc $rc)"
else
    bad "control: with a wrong image digest the gate exited $rc without failing the device lines - its identity check cannot fail. The log: $clog (kept)"
    keep=1
fi

echo "== card-segrun: $checks checks, $failed failed"
[ "$keep" = 1 ] && echo "   logs kept in $LOGDIR"
[ "$failed" -eq 0 ]
