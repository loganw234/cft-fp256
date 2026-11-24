#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The lead's box run of parcel M3X2 (2026-11-24): the fixtures of the pow family that need MPFR 4.2.0 or newer (mpfr_powr, mpfr_rootn_si and mpfr_compound_si
# do not exist below it), made on amd-arc-box (MPFR 4.2.2) from a build of the parcel's commit. NOT RUN BY THE PARCEL (agents do not touch the box); its exit
# status is shown to fail on a doctored job by hw/test_routine_sweep.py's `legs` group (a tool that is not the real one, a digest that is not the images').
#
#   bash hw/card_stress_fixtures/box_m3x2_fixtures.sh REPO TOOL OUTDIR
#     REPO    the checkout (host/tools/gen_sweep_images.py makes the images into a new directory)
#     TOOL    the built routine-sweep (make -C host MPFR=1 [MPFR_PREFIX=DIR] routine-sweep; XRT=1 is not needed: the software backend)
#     OUTDIR  where the rs3-box-*.txt files go (made if absent; a file there is overwritten)
#   PYTHON  the interpreter (default python3)
#
# Each log is the tool's stderr and then its stdout (the order of the rs-* fixtures), the images path written $HOME/m3x2-images. The INDEX rows (name, exit status,
# command, seconds) are printed on stdout, to append to hw/card_stress_fixtures/INDEX.txt under the rs3 comment. Expected time: under a minute (the slices are 256 lanes
# of the software backend: about 0.2 s each; the generator about 4 s). Exit 0 only when every command had the exit status and the lines expected of it.
set -u
REPO=${1:?usage: box_m3x2_fixtures.sh REPO TOOL OUTDIR}
TOOL=${2:?usage: box_m3x2_fixtures.sh REPO TOOL OUTDIR}
OUT=${3:?usage: box_m3x2_fixtures.sh REPO TOOL OUTDIR}
PY=${PYTHON:-python3}
mkdir -p "$OUT" || exit 2
IMGS=$(mktemp -d "${TMPDIR:-/tmp}/m3x2-box.XXXXXX")/images
"$PY" -B "$REPO/host/tools/gen_sweep_images.py" --out "$IMGS" > /dev/null || { echo "box_m3x2_fixtures: the generator failed" >&2; exit 2; }
cp "$IMGS/manifest.txt" "$OUT/rs3-box-images-manifest.txt" || exit 2
POWR_D=$(sed -n 's/^digest powr \([0-9a-f]\{8\}\)$/\1/p' "$IMGS/manifest.txt")
[ -n "$POWR_D" ] || { echo "box_m3x2_fixtures: the manifest has no powr digest" >&2; exit 2; }
fails=0

# run FILE EXPECTED_RC WORD -- ARGS...   (stdin from $STDIN, an echo -e text, when it is not empty)
run() {
  local file=$1 want_rc=$2 word=$3
  shift 4
  local t0=$SECONDS rc inp
  inp=$(mktemp "${TMPDIR:-/tmp}/m3x2-in.XXXXXX")
  [ -n "${STDIN:-}" ] && printf '%b' "$STDIN" > "$inp"
  CFT_SWEEP_IMAGES="$IMGS" "$TOOL" "$@" < "$inp" > "$inp.out" 2> "$inp.err"; rc=$?
  cat "$inp.err" "$inp.out" | sed "s#$IMGS#\$HOME/m3x2-images#g" > "$OUT/$file"
  rm -f "$inp" "$inp.out" "$inp.err"
  if [ "$rc" != "$want_rc" ]; then echo "box_m3x2_fixtures: $file: exit $rc, expected $want_rc" >&2; fails=$((fails + 1)); fi
  if [ -n "$word" ] && ! grep -q -- "$word" "$OUT/$file"; then echo "box_m3x2_fixtures: $file: the log lacks '$word'" >&2; fails=$((fails + 1)); fi
  local cmd="env CFT_SWEEP_IMAGES=\$IMAGES host/routine-sweep $*"
  [ -n "${STDIN:-}" ] && cmd="printf '${STDIN}' | $cmd"
  printf '%s	%s	%s [%s s]
' "$file" "$rc" "$cmd" "$((SECONDS - t0))"
}

# the whole `list` (the box has MPFR 4.2.2: nothing differs from the desktop's list, which the parcel made; this is the box's own)
run rs3-box-list.txt 0 "powr-f32: images rne rtz rdn rup rmm, digest $POWR_D" -- list
# powr at each shape: x fixed at 3 (every y; lanes of y from 1.0), y fixed at 2 (every x from 3.0: the exact class)
run rs3-box-powr-x-all.txt 0 "marked on an exact lane" -- "powr-f32-x40400000-d$POWR_D" 0x3f800000 0x3f800100 all
run rs3-box-powr-y-exact-all.txt 0 "5 marked on an exact lane" -- "powr-f32-y40000000-d$POWR_D" 0x40400000 0x40400100 all
# rootn and compound need no image for `oracle`, at two n each (3 and -3): the lanes are x (3, 1, -1, the largest normal, 0)
STDIN='40400000\n3f800000\nbf800000\n7f7fffff\n00000000\n'
for n in 3 m3; do
  run "rs3-box-oracle-rootn-n$n.txt" 0 "oracle: MPFR" -- oracle "rootn-f32-n$n" rne
  run "rs3-box-oracle-compound-n$n.txt" 0 "oracle: MPFR" -- oracle "compound-f32-n$n" rne
done
STDIN='40400000\n40800000\n3fc00000\n40000000\n3f800000\n40490fdb\n'
run rs3-box-exact-powr-y2.txt 0 "40400000 exact" -- exact powr-f32-y40000000
STDIN=''
exit $((fails > 0))
