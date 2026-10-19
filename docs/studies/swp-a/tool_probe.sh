#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# tool_probe.sh - parcel SC's probe of the two native-oracle soak tools,
# host/tools/divsqrt_soak.c and host/tools/clause5_soak.c, on the SOFTWARE
# backend (no card, no XRT). It MEASURES four things the study uses, on the
# tools as built from this tree:
#
#   A. what one unit of `count` is, per operation: the cases a job reports for
#      a given count. The stress driver's rates are counts a second
#      (sweep.count), so a rate means "operands", "checks" or "lanes" only as
#      far as this table says.
#   B. that a random job's operand stream is a pure function of (operation,
#      seed): the same seed twice gives the same operands, and the rounding
#      mode does not change them.
#   C. the rule `rng_state = seed | 1` (both tools): seeds 2k and 2k+1 give ONE
#      stream, 2k+1 and 2k+2 do not.
#   D. the exhaustive modes' case counts: a slice [lo, hi) reports hi - lo
#      cases, and nextup32/nextdown32 eight more.
#
# The operands are read off the tools' own sabotage control: with
# CFT_SOAK_SABOTAGE=1 the tool flips one result bit and prints the operands of
# the lanes it names (up to 16 lines, MISMATCH ... a=0x... b=0x...), which for
# divsqrt-soak is the first 16 lanes of the first batch. Those lines are
# re-printed here as "OPERANDS <op> <seed> <mode> <lane> <fields>" for
# seed_audit.py to parse. Nothing is changed in the tools.
#
#   usage: bash tool_probe.sh DIR
#          DIR holds the built divsqrt-soak and clause5-soak
#          (make -C host divsqrt-soak clause5-soak, XRT=0)
#
# The captured run is tool_probe.out beside this file.

set -u
D=${1:?usage: bash tool_probe.sh DIR  (DIR holds divsqrt-soak and clause5-soak)}
DS="$D/divsqrt-soak"
C5="$D/clause5-soak"
for b in "$DS" "$C5"; do
  [ -x "$b" ] || { echo "missing $b" >&2; exit 2; }
done

fails=0

# run NAME BIN ARGS...: print the command and the tool's output lines
# (stdout and stderr, so the "soaking the software backend" line is part of
# the record), and the exit status.
run() {
  local name=$1; shift
  local bin=$1; shift
  printf '$ %s %s\n' "$name" "$*"
  local out rc
  out=$(nice -n 10 "$bin" "$@" 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/    /'
  printf '    exit %s\n' "$rc"
  LAST_OUT=$out
  LAST_RC=$rc
}

# cases_of: the number printed before " cases," in the last output
cases_of() {
  printf '%s\n' "$LAST_OUT" | sed -n 's/.*: \([0-9][0-9]*\) cases,.*/\1/p' | tail -1
}

expect() {   # expect LABEL GOT WANT
  if [ "$2" = "$3" ]; then
    printf 'CHECK %-58s %s = %s  ok\n' "$1" "$2" "$3"
  else
    printf 'CHECK %-58s got %s, wanted %s  FAILED\n' "$1" "$2" "$3"
    fails=$((fails + 1))
  fi
}

echo "== A. what one unit of count is"
echo "   (the verdict line's cases against the count asked for)"

run "clause5-soak" "$C5" scaleb32 1 1 rne
expect "scaleb32 count=1: one operand x 17 exponents" "$(cases_of)" 17
run "clause5-soak" "$C5" scaleb32 4096 1 rne
expect "scaleb32 count=4096: 4096 operands x 17 exponents" "$(cases_of)" 69632
run "clause5-soak" "$C5" scaleb32 69632 1 rne
expect "scaleb32 count=69632 (=4096x17): one batch, cases = count" "$(cases_of)" 69632
run "clause5-soak" "$C5" scaleb32 696320 1 rne
expect "scaleb32 count=696320 (=10x69632): cases = count" "$(cases_of)" 696320
run "clause5-soak" "$C5" scaleb64 4096 1 rne
expect "scaleb64 count=4096: 4096 operands x 27 exponents" "$(cases_of)" 110592
run "clause5-soak" "$C5" scaleb64 110592 1 rne
expect "scaleb64 count=110592 (=4096x27): cases = count" "$(cases_of)" 110592

run "clause5-soak" "$C5" cvtfrom32 4096 1 rne
expect "cvtfrom32 count=4096: 4 source types per lane" "$(cases_of)" 16384
run "clause5-soak" "$C5" cvtfrom64 4096 1 rne
expect "cvtfrom64 count=4096: 4 source types per lane" "$(cases_of)" 16384

run "clause5-soak" "$C5" cvtto32 4096 1 rne
echo "NOTE  cvtto32 count=4096 reports $(cases_of) cases: in-range (lane, target) pairs only, of at most 16384"
run "clause5-soak" "$C5" cvtto64 4096 1 rne
echo "NOTE  cvtto64 count=4096 reports $(cases_of) cases: in-range (lane, target) pairs only, of at most 16384"

run "clause5-soak" "$C5" conv64to32 4096 1 rne
expect "conv64to32 count=4096: one case an operand" "$(cases_of)" 4096
run "clause5-soak" "$C5" conv32to64 4096 1
expect "conv32to64 count=4096: one case an operand" "$(cases_of)" 4096
run "clause5-soak" "$C5" rint64 4096 1 rne
expect "rint64 count=4096: one case an operand" "$(cases_of)" 4096
run "clause5-soak" "$C5" rem32 4096 1
expect "rem32 count=4096: one case a pair" "$(cases_of)" 4096
run "clause5-soak" "$C5" rem64 4096 1
expect "rem64 count=4096: one case a pair" "$(cases_of)" 4096
run "clause5-soak" "$C5" class64 4096 1
expect "class64 count=4096: one case an operand" "$(cases_of)" 4096
run "clause5-soak" "$C5" logb64 4096 1
expect "logb64 count=4096: one case an operand" "$(cases_of)" 4096
run "clause5-soak" "$C5" nextup64 4096 1
echo "NOTE  nextup64 count=4096 reports $(cases_of) cases (the eight edge cases of next_edges64 are counted too)"
run "divsqrt-soak" "$DS" div32 4096 1 rne
expect "div32 count=4096: one case a pair" "$(cases_of)" 4096
run "divsqrt-soak" "$DS" div64 4096 1 rne
expect "div64 count=4096: one case a pair" "$(cases_of)" 4096
run "divsqrt-soak" "$DS" sqrt64 4096 1 rne
expect "sqrt64 count=4096: one case an operand" "$(cases_of)" 4096

echo
echo "== D. the exhaustive modes' case counts"
run "divsqrt-soak" "$DS" sqrt32 0 4096 rne
expect "sqrt32 [0,4096): hi - lo" "$(cases_of)" 4096
run "clause5-soak" "$C5" rint32 0 4096 rne
expect "rint32 [0,4096): hi - lo" "$(cases_of)" 4096
run "clause5-soak" "$C5" nextup32 0 4096
expect "nextup32 [0,4096): hi - lo + 8" "$(cases_of)" 4104
run "clause5-soak" "$C5" nextdown32 0 4096
expect "nextdown32 [0,4096): hi - lo + 8" "$(cases_of)" 4104
run "clause5-soak" "$C5" logb32 0 4096
expect "logb32 [0,4096): hi - lo" "$(cases_of)" 4096
run "clause5-soak" "$C5" class32 0 4096
expect "class32 [0,4096): hi - lo" "$(cases_of)" 4096

# ---- B and C: the operand stream is read off the sabotage control ---------
# operands OP SEED MODE: print "OPERANDS ..." lines for the first 16 lanes
# the tool names, from `CFT_SOAK_SABOTAGE=1 divsqrt-soak OP 4096 SEED MODE`.
operands() {
  local op=$1 seed=$2 mode=$3
  CFT_SOAK_SABOTAGE=1 nice -n 10 "$DS" "$op" 4096 "$seed" "$mode" 2>/dev/null |
    awk -v op="$op" -v seed="$seed" -v mode="$mode" '
      /^  MISMATCH/ { n++;
        f = "";
        for (i = 2; i <= NF; i++) if ($i ~ /^[ab]=/) f = f " " $i;
        printf "OPERANDS %s %s %s %d%s\n", op, seed, mode, n - 1, f }'
}

echo
echo "== B. the operand stream is a function of (operation, seed)"
for op in div32 div64 sqrt64; do
  for seed in 0x50AC0001 0x50AC1F20 0x50AC0007; do
    operands "$op" "$seed" rne > /tmp/swp_a.$$.1
    operands "$op" "$seed" rne > /tmp/swp_a.$$.2
    operands "$op" "$seed" rtz > /tmp/swp_a.$$.3
    cat /tmp/swp_a.$$.1
    n=$(wc -l < /tmp/swp_a.$$.1 | tr -d ' ')
    expect "$op seed $seed: 16 lanes named" "$n" 16
    if cmp -s /tmp/swp_a.$$.1 /tmp/swp_a.$$.2; then r=IDENTICAL; else r=DIFFERENT; fi
    expect "$op seed $seed: second run of the same seed" "$r" IDENTICAL
    if cmp -s <(sed 's/ rne / M /' /tmp/swp_a.$$.1) <(sed 's/ rtz / M /' /tmp/swp_a.$$.3); then r=IDENTICAL; else r=DIFFERENT; fi
    expect "$op seed $seed: rtz gives the rne operands" "$r" IDENTICAL
  done
done
rm -f /tmp/swp_a.$$.1 /tmp/swp_a.$$.2 /tmp/swp_a.$$.3

echo
echo "== C. rng_state = seed | 1: seeds 2k and 2k+1 are one stream"
# the operands without the seed column, to compare streams across seeds
strip() { sed 's/^OPERANDS \([a-z0-9]*\) [^ ]* /OPERANDS \1 S /'; }
for op in div32 div64 sqrt64; do
  operands "$op" 0x50AC0002 rne | strip > /tmp/swp_a.$$.e
  operands "$op" 0x50AC0003 rne | strip > /tmp/swp_a.$$.o
  operands "$op" 0x50AC0004 rne | strip > /tmp/swp_a.$$.n
  if cmp -s /tmp/swp_a.$$.e /tmp/swp_a.$$.o; then r=IDENTICAL; else r=DIFFERENT; fi
  expect "$op seeds 0x50AC0002 and 0x50AC0003" "$r" IDENTICAL
  if cmp -s /tmp/swp_a.$$.o /tmp/swp_a.$$.n; then r=IDENTICAL; else r=DIFFERENT; fi
  expect "$op seeds 0x50AC0003 and 0x50AC0004" "$r" DIFFERENT
  # print the two streams once, so the capture holds what was compared
  operands "$op" 0x50AC0002 rne
  operands "$op" 0x50AC0003 rne
  operands "$op" 0x50AC0004 rne
done
rm -f /tmp/swp_a.$$.e /tmp/swp_a.$$.o /tmp/swp_a.$$.n

echo
if [ "$fails" -eq 0 ]; then
  echo "tool_probe: every CHECK held"
  exit 0
fi
echo "tool_probe: $fails CHECK(s) FAILED"
exit 1
