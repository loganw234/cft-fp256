#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# seed_replay.sh - parcel SC's measurement of what a SECOND stress run covers,
# using the real driver's dry-run (hw/card_stress.py --dry-run --quick: stand-in
# tools, no XRT, no card, no amd-arc-box). Three invocations, then
# seed_replay_check.py reads their metrics.jsonl files:
#
#   A  a fresh --out            B  another fresh --out        C  --resume on A
#
#   usage: bash seed_replay.sh WORK [PYTHON]
#          WORK    a new or empty directory (written; the caller removes it)
#          PYTHON  the interpreter (default python3)
#
# About a minute an invocation on the desktop. The driver wants an image file
# with a SHA256SUMS beside it for each of quad, single and deep; in a dry run it
# only reads them, so this makes three tiny fakes under WORK. Run from anywhere.
# The captured run is seed_replay.out beside this file.

set -u
WORK=${1:?usage: bash seed_replay.sh WORK [PYTHON]}
PY=${2:-python3}
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
mkdir -p "$WORK"

for n in quad single deep; do
  mkdir -p "$WORK/fake-images/$n"
  printf 'fake image for the dry run: %s\n' "$n" > "$WORK/fake-images/$n/$n.xclbin"
  (cd "$WORK/fake-images/$n" && sha256sum "$n.xclbin" > SHA256SUMS)
done
IMG=(--image "quad=$WORK/fake-images/quad/quad.xclbin"
     --image "single=$WORK/fake-images/single/single.xclbin"
     --image "deep=$WORK/fake-images/deep/deep.xclbin")

drive() {   # drive LABEL ARGS...
  local label=$1; shift
  local t0 t1
  t0=$(date +%s)
  "$PY" -B "$ROOT/hw/card_stress.py" --dry-run --quick "${IMG[@]}" "$@" > "$WORK/$label.log" 2>&1
  local rc=$?
  t1=$(date +%s)
  echo "$label: rc $rc in $((t1 - t0)) s; last line: $(tail -1 "$WORK/$label.log" | sed 's/^\[[^]]*\] //')"
  return $rc
}

echo "== the three invocations (stand-in tools; dry run, no card)"
echo "A: card_stress.py --dry-run --quick --out WORK/replay-A"
drive A --out "$WORK/replay-A" || exit 2
echo "B: card_stress.py --dry-run --quick --out WORK/replay-B        (a NEW directory)"
drive B --out "$WORK/replay-B" || exit 2
echo "C: card_stress.py --dry-run --quick --resume --out WORK/replay-A  (A, continued)"
drive C --resume --out "$WORK/replay-A" || exit 2

echo
echo "== what the records say"
"$PY" -B "$HERE/seed_replay_check.py" "$WORK/replay-A/metrics.jsonl" "$WORK/replay-B/metrics.jsonl"
