#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# verify/run.sh's inner-skip accounting, held to synthetic stages: no
# host build and no python; seconds on Linux, under a minute in Git Bash.
#
#     bash verify/test-inner-skips.sh      # exit 0 pass, 1 fail
#
# A stage passes on its exit status, and a check inside it that did not
# run used to vanish there: `generated` logged "SKIP  bindings/node/
# make_seq_corpus.py - cannot run its check here" and the run printed
# "VERDICT: PASS, nothing skipped". The runner now reads a passing
# stage's log for lines whose first word is SKIP or SKIPPED. This builds
# a copy of the runner whose stage list is two synthetic stages, runs it,
# and holds the report to:
#  - a clean stage whose log is full of look-alikes (cocotb's SKIP=0,
#    pytest's "2 skipped", SKIPPING, SKIPPED mid-line) counts nothing,
#    and the run still says "PASS, nothing skipped";
#  - a stage that skips one check and prints a pytest line folding three
#    more counts four, names both lines under its row, in report.jsonl
#    (escaped, CR-free) and on the VERDICT and census lines, and PASSes;
#  - the same under --require-all FAILS, naming the stage on the VERDICT;
#  - a --resume runs that stage again instead of serving it from cache.
# Two negative controls put a defect back into a copy of the runner - the
# scan disabled, and a pass with inner skips cached like a clean one -
# and the check written for each must catch it.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILS=0

# The synthetic stages, in the runner's own `stage` form, so its derived
# stage list and its --only validation see them. `gappy` ends its lines
# in CR LF, as Python's print does on Windows.
cat > "$T/stages.sh" << 'EOF'
need
stage clean "a stage whose log only looks as though it skipped" -- \
  printf '%s\n' 'ok    the only check' '** TESTS=3 PASS=3 FAIL=0 SKIP=0 **' \
    '5 passed, 2 skipped in 0.10s' 'SKIPPING is not a skip' 'it SKIPPED nothing' ''
need
stage gappy "a stage that passes having skipped four checks" -- \
  printf '%s\r\n' 'ok    first' '  SKIP  second - cannot run its check here: no "lib" at C:\x\y' \
    'SKIPPED [3] tests\t_x.py:9: gmpy2 not installed'
EOF

# mkrunner <run.sh> <dir>: <dir>/verify/run.sh is that runner with its
# stage list, everything between the two markers, replaced by the
# synthetic stages. ROOT is then <dir>, so its state lands there.
mkrunner () {
  if ! grep -q '^# ---- the stages' "$1" || ! grep -q '^# ---- report' "$1"; then
    echo "  FAIL  $1 has lost its '# ---- the stages' or '# ---- report' marker"
    return 1
  fi
  mkdir -p "$2/verify"
  awk -v stages="$T/stages.sh" '
    /^# ---- the stages/ { print; while ((getline l < stages) > 0) print l; cut = 1; next }
    /^# ---- report/     { cut = 0 }
    !cut' "$1" > "$2/verify/run.sh"
}

# go <dir> <tag> <args...>: run that copy; OUT, RC, VERDICT, RUNID, JSONL
go () {
  local d=$1; OUT="$T/$2.out"; shift 2
  bash "$d/verify/run.sh" "$@" > "$OUT" 2>&1; RC=$?
  VERDICT=$(grep '^VERDICT:' "$OUT")
  RUNID=$(sed -n 's/^== \(run\|resuming\) //p' "$OUT")
  JSONL="$d/verify/state/$RUNID/report.jsonl"
}

check () {  # <name> <command...>
  local name=$1; shift
  if "$@"; then echo "  ok    $name"; return 0; fi
  echo "  FAIL  $name"; return 1
}
same () {  # <name> <got> <want>
  if [ "$2" = "$3" ]; then echo "  ok    $1"; return 0; fi
  echo "  FAIL  $1: got '$2', wanted '$3'"; return 1
}

cases () {  # <runner>  ->  returns the number of checks it got wrong
  local d="$T/r.$RANDOM$RANDOM" bad=0 gappy_run
  mkrunner "$1" "$d" || return 1

  echo "-- clean: the look-alikes"
  go "$d" clean --only clean
  same  "clean: exit 0" "$RC" 0 || bad=$((bad + 1))
  same  "clean: the VERDICT" "$VERDICT" "VERDICT: PASS, nothing skipped" || bad=$((bad + 1))
  check "clean: its row carries no count" grep -qE '^clean +ok +[0-9]+s$' "$OUT" || bad=$((bad + 1))
  check "clean: the census counts 0 inner skips" grep -qF ', 0 skipped, 0 inner skip(s).' "$OUT" || bad=$((bad + 1))
  check "clean: report.jsonl records 0" grep -qF '"inner_skips":0,"inner_skip_lines":[]}' "$JSONL" || bad=$((bad + 1))

  echo "-- gappy: four checks that did not run, no --require-all"
  go "$d" gappy --only clean,gappy; gappy_run=$RUNID
  same  "gappy: exit 0" "$RC" 0 || bad=$((bad + 1))
  same  "gappy: the VERDICT names and counts them" "$VERDICT" \
        "VERDICT: PASS with 4 inner skip(s) in gappy (4) - see reasons above" || bad=$((bad + 1))
  check "gappy: its row counts 4" grep -qE '^gappy +ok +[0-9]+s  \+ 4 inner skip\(s\)' "$OUT" || bad=$((bad + 1))
  check "gappy: the SKIP line named under the row" \
        grep -qxF '             SKIP  second - cannot run its check here: no "lib" at C:\x\y' "$OUT" || bad=$((bad + 1))
  check "gappy: the pytest line named under the row" \
        grep -qxF '             SKIPPED [3] tests\t_x.py:9: gmpy2 not installed' "$OUT" || bad=$((bad + 1))
  check "gappy: the census counts them" grep -qF ', 0 skipped, 4 inner skip(s) (gappy (4)).' "$OUT" || bad=$((bad + 1))
  check "gappy: report.jsonl counts and names them, escaped" grep -qF \
        '"inner_skips":4,"inner_skip_lines":["SKIP  second - cannot run its check here: no \"lib\" at C:\\x\\y","SKIPPED [3] tests\\t_x.py:9: gmpy2 not installed"]}' \
        "$JSONL" || bad=$((bad + 1))
  check "gappy: clean beside it still counts nothing" grep -qE '^clean +ok +[0-9]+s$' "$OUT" || bad=$((bad + 1))

  echo "-- strict: the same under --require-all"
  go "$d" strict --only clean,gappy --require-all
  same  "strict: exit 1" "$RC" 1 || bad=$((bad + 1))
  same  "strict: the VERDICT fails and names them" "$VERDICT" \
        "VERDICT: FAIL (1 stage(s), including under --require-all 4 inner skip(s) in gappy (4))" || bad=$((bad + 1))

  echo "-- resume: the gappy run, resumed"
  go "$d" resume --resume "$gappy_run" --only clean,gappy
  check "resume: clean is served from cache" \
        grep -qE '^clean +ok +\(cached from earlier in this run\)$' "$OUT" || bad=$((bad + 1))
  check "resume: gappy runs again, not from cache" \
        grep -qE '^gappy +ok +[0-9]+s  \+ 4 inner skip\(s\)' "$OUT" || bad=$((bad + 1))
  same  "resume: the VERDICT still names them" "$VERDICT" \
        "VERDICT: PASS with 4 inner skip(s) in gappy (4) - see reasons above" || bad=$((bad + 1))
  return "$bad"
}
NCHECKS=18

echo "== verify/run.sh, as committed"
cases "$ROOT/verify/run.sh"; n=$?
[ "$n" -eq 0 ] || { echo "FAIL: $n of $NCHECKS check(s) wrong"; FAILS=$((FAILS + 1)); }

# Each control: the defect put back into a copy that still parses, and
# the check written for it must be among those that catch it.
control () {  # <name> <marker> <replacement line> <the check that must catch it>
  local c="$T/run.$1.sh"
  grep -q "$2" "$ROOT/verify/run.sh" || { echo "FAIL: control $1 - marker $2 not found"; FAILS=$((FAILS + 1)); return; }
  REPL="$3" awk -v m="$2" 'index($0, m) {print ENVIRON["REPL"]; next} {print}' "$ROOT/verify/run.sh" > "$c"
  echo "== negative control, $1"
  bash -n "$c" || { echo "FAIL: control $1 - the copy does not parse, so it proves nothing"; FAILS=$((FAILS + 1)); return; }
  cases "$c" > "$T/control.out" 2>&1
  if grep -qF "FAIL  $4" "$T/control.out"; then
    grep -F "FAIL  $4" "$T/control.out" | cut -c1-200
    echo "  caught by \"$4\" ($(grep -c 'FAIL  ' "$T/control.out") check(s) wrong in all)"
  else
    cat "$T/control.out"
    echo "FAIL: control $1 - the defect was put back and \"$4\" did not catch it"
    FAILS=$((FAILS + 1))
  fi
}
control scan-disabled INNER-SKIP-SCAN \
  '    inner=""    # the control: nothing read from the log' \
  "gappy: the VERDICT names and counts them"
control cached-like-clean INNER-SKIP-NO-CACHE \
  '    : > "$RUNDIR/$name.ok"    # the control: a gap cached as a clean pass' \
  "resume: gappy runs again, not from cache"

if [ "$FAILS" -eq 0 ]; then
  echo "PASS: $NCHECKS checks right, both controls caught by their own checks"
  exit 0
fi
echo "FAIL: $FAILS problem(s)"
exit 1
