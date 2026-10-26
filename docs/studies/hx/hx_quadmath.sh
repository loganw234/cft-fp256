#!/bin/bash
# hx_quadmath.sh - builds hx_quadmath.c and runs it twice: plainly, and with HX_QUAD_SABOTAGE=1, where every one of
# the 48 cells must show mismatches (rc 1: the comparison can fail). Checks: the sabotage is caught in every cell;
# add, sub, mul, div and fmaq agree with MPFR in all 40 of their cells (values and the inexact flag). sqrtq's 8 cells
# are reported, not asserted: they are the finding (docs/studies/HX-wide-sweeps.md, 4.3). WSL cft2204 (gcc,
# libquadmath, MPFR, GMP).
#   bash hx_quadmath.sh <worktree> <empty work dir> [N]
set -u
TREE=${1:?worktree}; WORK=${2:?work dir}; N=${3:-100000}
[ -d "$WORK" ] && [ -z "$(ls -A "$WORK")" ] || { echo "work dir must exist and be empty"; exit 2; }
gcc -O2 -frounding-math -Wall -Wextra "$TREE/docs/studies/hx/hx_quadmath.c" -o "$WORK/hx-quadmath" \
  -lquadmath -lmpfr -lgmp -lm || { echo "build failed"; exit 1; }
echo "libquadmath: $(dpkg -l libquadmath0 2>/dev/null | awk '/^ii/ {print $3}')"
nice -n 10 "$WORK/hx-quadmath" "$N" > "$WORK/plain.out"
cat "$WORK/plain.out"
fails=0
ok=$(grep -cE '^  (random|fp32w) +(add|sub|mul|div|fmaq) +(rne|rtz|rdn|rup): 0 value mismatches, 0 inexact-flag mismatches' "$WORK/plain.out")
if [ "$ok" = 40 ]; then echo "CHECK add, sub, mul, div and fmaq agree with MPFR in all 40 cells: ok"
else echo "CHECK add, sub, mul, div and fmaq agree with MPFR in all 40 cells: FAILED ($ok of 40)"; fails=$((fails + 1)); fi
echo "FINDING sqrtq's cells:"; grep -E '^  (random|fp32w) +sqrtq ' "$WORK/plain.out"
HX_QUAD_SABOTAGE=1 nice -n 10 "$WORK/hx-quadmath" 20000 > "$WORK/sabotage.out"; rc=$?
grep -E '^hx-quadmath: [0-9]+ \(stream' "$WORK/sabotage.out"
if [ $rc = 1 ] && grep -q '^hx-quadmath: 48 (stream' "$WORK/sabotage.out"; then echo "CHECK sabotage control: all 48 cells show it, rc 1: caught"
else echo "CHECK sabotage control: NOT caught in every cell (rc $rc)"; fails=$((fails + 1)); fi
echo "hx_quadmath: $fails check(s) failed"
exit $fails
