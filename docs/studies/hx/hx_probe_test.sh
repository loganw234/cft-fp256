#!/bin/bash
# hx_probe_test.sh - builds hx_probe.c against a scratch copy of host/'s libcft (the software backend
# only, no XRT) and runs it twice: once plainly, where every check must be equal, and once with
# HX_PROBE_SABOTAGE=1, where the first row must report 4095 of 4096 equal and the run must exit 1.
# A test of the probe, not of any card. Run in WSL cft2204 (gcc, make):
#   bash hx_probe_test.sh <worktree> <empty work dir>
set -u
TREE=${1:?worktree}; WORK=${2:?work dir}
[ -d "$WORK" ] && [ -z "$(ls -A "$WORK")" ] || { echo "work dir must exist and be empty"; exit 2; }
cp -r "$TREE/host" "$WORK/host"
( cd "$WORK/host" && nice -n 10 make -s libcft.a > ../build.log 2>&1 ) || { echo "libcft build failed"; tail "$WORK/build.log"; exit 1; }
gcc -std=c99 -O2 -Wall -Wextra -I"$WORK/host/include" "$TREE/docs/studies/hx/hx_probe.c" "$WORK/host/libcft.a" -lm \
  -o "$WORK/hx-probe" || { echo "probe build failed"; exit 1; }
fails=0
nice -n 10 "$WORK/hx-probe" - 0.2 > "$WORK/plain.out"; rc=$?
cat "$WORK/plain.out"
if [ $rc = 0 ] && grep -q '^hx-probe: every check equal$' "$WORK/plain.out" && [ "$(grep -c ' check 4096 of 4096 equal' "$WORK/plain.out")" = 21 ]; then
  echo "CHECK plain run: 21 rows, every check equal, rc 0: ok"
else echo "CHECK plain run: FAILED (rc $rc)"; fails=$((fails + 1)); fi
HX_PROBE_SABOTAGE=1 nice -n 10 "$WORK/hx-probe" - 0.02 > "$WORK/sabotage.out"; rc=$?
head -2 "$WORK/sabotage.out"
if [ $rc = 1 ] && [ "$(grep -c ' check 4095 of 4096 equal' "$WORK/sabotage.out")" = 21 ] && grep -q '^hx-probe: A CHECK FAILED$' "$WORK/sabotage.out"; then
  echo "CHECK sabotage control: every row 4095 of 4096, rc 1: caught"
else echo "CHECK sabotage control: NOT caught (rc $rc)"; fails=$((fails + 1)); fi
echo "hx_probe_test: $fails check(s) failed"
exit $fails
