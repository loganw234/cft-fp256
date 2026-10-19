#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# tool_probe_plants.sh - the negative controls for tool_probe.sh. A probe that
# cannot fail proves nothing, so this builds scratch copies of the two soak
# tools with ONE defect each put back, runs tool_probe.sh against each, and
# requires the probe to go red on the check written for that defect. A control
# copy with no defect must pass first. Nothing in the tree is touched: every
# copy lives under WORK.
#
#   usage: bash tool_probe_plants.sh HOSTDIR WORK
#          HOSTDIR  the tree's host/ directory (sources; read only)
#          WORK     an empty or new scratch directory (written; the caller
#                   removes it)
#
# The plants, each a sed edit that the script checks changed the file:
#   P1  scaleb's `count` falls by operands, not by operand x exponent
#         (clause5_soak.c: `count > sub ? count - sub` -> `count > n ? count - n`)
#         must be caught by A: "scaleb32 count=69632 ... cases = count"
#   P2  the seed is used as given, with no `| 1`
#         (divsqrt_soak.c, three places) must be caught by C: seeds 2k and 2k+1
#   P3  the rounding mode shifts the stream
#         (divsqrt_soak.c: the seed gets 2 x the mode index added after the
#         `| 1`, so rne keeps its stream and rtz gets another)
#         must be caught by B: "rtz gives the rne operands"
#   P4  nextup32 forgets its eight edge cases
#         (clause5_soak.c: the call to next_edges32 in drv_next32 removed)
#         must be caught by D: "nextup32 [0,4096): hi - lo + 8"
#   P5  cvtfrom counts one source type, not four
#         (clause5_soak.c: `for (si = 0; si < 4; si++)` -> `si < 1`)
#         must be caught by A: "cvtfrom32 count=4096: 4 source types per lane"

set -u
SRC=${1:?usage: bash tool_probe_plants.sh HOSTDIR WORK}
WORK=${2:?usage: bash tool_probe_plants.sh HOSTDIR WORK}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WORK"
bad=0

build_copy() {   # build_copy NAME : copy $SRC to $WORK/NAME/host and echo its path
  local name=$1
  rm -rf "$WORK/$name"; mkdir -p "$WORK/$name"
  cp -r "$SRC" "$WORK/$name/host"
  echo "$WORK/$name/host"
}

make_tools() {   # make_tools HOSTCOPY
  ( cd "$1" && nice -n 10 make -j2 divsqrt-soak clause5-soak > ../build.log 2>&1 ) \
    || { echo "BUILD FAILED for $1 (see build.log)"; tail -5 "$1/../build.log"; return 1; }
}

# plant NAME FILE SED_SCRIPT EXPECTED_FAILED_CHECK_SUBSTRING
plant() {
  local name=$1 file=$2 script=$3 want=$4
  local h; h=$(build_copy "$name")
  cp "$h/tools/$file" "$h/tools/$file.orig"
  sed -i "$script" "$h/tools/$file"
  if cmp -s "$h/tools/$file" "$h/tools/$file.orig"; then
    echo "PLANT $name: the edit changed nothing in $file - the plant is vacuous  FAILED"
    bad=$((bad + 1)); return
  fi
  echo "PLANT $name: $(diff "$h/tools/$file.orig" "$h/tools/$file" | grep -c '^>') line(s) changed in $file"
  diff "$h/tools/$file.orig" "$h/tools/$file" | sed 's/^/      /'
  make_tools "$h" || { bad=$((bad + 1)); return; }
  local out="$WORK/$name/probe.out"
  bash "$HERE/tool_probe.sh" "$h" > "$out" 2>&1
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "PLANT $name: the probe PASSED on the defective tool  FAILED"
    bad=$((bad + 1)); return
  fi
  if grep -F "FAILED" "$out" | grep -F -q "$want"; then
    echo "PLANT $name: red as written (probe rc $rc), at the check for it:"
    grep -F "FAILED" "$out" | sed 's/^/      /' | head -6
  else
    echo "PLANT $name: red (probe rc $rc) but NOT at the check written for it  FAILED"
    grep -F "FAILED" "$out" | sed 's/^/      /' | head -6
    bad=$((bad + 1))
  fi
}

echo "== CONTROL: an unmodified copy must pass"
h=$(build_copy control)
make_tools "$h" || exit 2
bash "$HERE/tool_probe.sh" "$h" > "$WORK/control/probe.out" 2>&1
rc=$?
tail -1 "$WORK/control/probe.out"
if [ "$rc" -ne 0 ]; then
  echo "CONTROL FAILED: the unmodified tools do not pass the probe"; bad=$((bad + 1))
else
  echo "CONTROL ok (probe rc 0)"
fi

echo
echo "== P1: scaleb counts operands"
plant P1 clause5_soak.c 's/count = count > sub ? count - sub : 0;/count = count > n ? count - n : 0;/' \
      "scaleb32 count=69632"

echo
echo "== P2: no seed | 1"
plant P2 divsqrt_soak.c 's/rng_state = strtoull(argv\[3\], NULL, 0) | 1;/rng_state = strtoull(argv[3], NULL, 0);/' \
      "seeds 0x50AC0002 and 0x50AC0003"

echo
echo "== P3: the mode shifts the stream"
plant P3 divsqrt_soak.c 's/rng_state = strtoull(argv\[3\], NULL, 0) | 1;/rng_state = (strtoull(argv[3], NULL, 0) | 1) + (uint64_t)(mi * 2);/' \
      "rtz gives the rne operands"

echo
echo "== P4: nextup32 without its eight edge cases"
plant P4 clause5_soak.c 's/^    if (next_edges32(up))$/    if (0 \&\& next_edges32(up))/' \
      "nextup32 [0,4096)"

echo
echo "== P5: cvtfrom runs one source type"
plant P5 clause5_soak.c 's/for (si = 0; si < 4; si++) {/for (si = 0; si < 1; si++) {/' \
      "cvtfrom32 count=4096"

echo
if [ "$bad" -eq 0 ]; then
  echo "tool_probe_plants: the control passed and all five plants were caught at their checks"
  exit 0
fi
echo "tool_probe_plants: $bad problem(s)"
exit 1
