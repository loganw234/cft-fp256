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
# stage's log for lines whose first word is SKIP or SKIPPED, and for the
# conformance replay's "<set>: [<op>] skipped, ... on this device". This
# builds a copy of the runner whose stage list is the synthetic stages
# below, runs it, and holds the report to:
#  - a clean stage whose log is full of look-alikes (cocotb's SKIP=0,
#    pytest's "2 skipped", SKIPPING, SKIPPED mid-line, a replay line that
#    skipped nothing) counts nothing, and the run says "PASS, nothing
#    skipped";
#  - a stage with a SKIP line, a pytest line folding three tests and a
#    replay's skipped set counts five, and one whose only gap is the
#    replay's "imul skipped, not on this device" counts one; each line is
#    named under its stage's row, in report.jsonl (escaped, CR-free) and in
#    the census, the VERDICT and census count them by stage, and the run
#    PASSes;
#  - the same under --require-all FAILS, naming the stages on the VERDICT,
#    and so does the imul stage alone;
#  - a --resume runs those stages again instead of serving them from cache;
#  - pytest's marker as a coloured terminal gets it, "ESC[33mSKIPPEDESC[0m
#    [2] ...", counts two and is named without its colour, a coloured
#    "2 skipped" beside it counts nothing, and --require-all FAILS it.
# Four negative controls put a defect back into a copy of the runner -
# the scan disabled, the replay's form dropped, a pass with inner skips
# cached like a clean one, and the colour left in - and the check written
# for each must catch it.
# Then the skip lines the stages' programs print (device-test,
# remote-test, cpp-api-test, remote_check.py, tb/check_results.py), each
# as printed since 2026-09-24 and as printed before: the new one counts
# and fails --require-all alone, the old one counts nothing even under
# --require-all. And a pin per form holds the source to the line the
# fixture claims it prints, and refuses the old one.
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
    '5 passed, 2 skipped in 0.10s' 'SKIPPING is not a skip' 'it SKIPPED nothing' \
    'fp32-rne.jsonl: 19600 cases, none skipped, all on this device' ''
need
stage gappy "a stage that passes having skipped five checks" -- \
  printf '%s\r\n' 'ok    first' '  SKIP  second - cannot run its check here: no "lib" at C:\x\y' \
    'SKIPPED [3] tests\t_x.py:9: gmpy2 not installed' \
    'fp256-rne.jsonl: skipped, fp256 not on this device'
need
stage replay "a replay that skipped one opcode" -- \
  printf '%s\n' 'fp32-rne.jsonl: 19600 cases, all matching' \
    'fp32-rne.jsonl: imul skipped, not on this device'
need
stage colour "a pytest run painted by FORCE_COLOR, as pytest 9.1 paints it on Windows" -- \
  printf '%b\r\n' 'ok    a coloured pass' \
    '\033[33mSKIPPED\033[0m [2] tests/test_y.py:4: painted by FORCE_COLOR' \
    '\033[32m\033[32m\033[1m5 passed\033[0m, \033[33m2 skipped\033[0m\033[32m in 0.10s\033[0m\033[0m'
need
stage dt-format "device-test: a format the device does not carry" -- \
  printf '%s\n' 'fp32' '  buffers, elementwise: 40 checks, 0 failed' \
    'SKIPPED fp128: not on this device' '' '1723 checks, 0 failed' \
    'the device and the software backend agree on every case that RAN, bits and flags - skipped: 1 format, 0 buffers legs, 0 opcodes, each named above'
need
stage dt-format-old "the same, as device-test printed it until 2026-09-24" -- \
  printf '%s\n' 'fp32' '  buffers, elementwise: 40 checks, 0 failed' \
    'fp128  not on this device, skipped' '' '1723 checks, 0 failed' \
    'the device and the software backend agree on every case, bits and flags'
need
stage dt-indexed "device-test -b: no INDEXED, so no indexed program through the buffers" -- \
  printf '%s\n' '  buffers, a program'"'"'s scratch: 90 checks, 0 failed' \
    '  SKIPPED buffers, an indexed program: this device does not publish CFT_SEQ_FEAT_INDEXED'
need
stage dt-indexed-old "the same, as device-test printed it until 2026-09-24" -- \
  printf '%s\n' '  buffers, a program'"'"'s scratch: 90 checks, 0 failed' \
    '  buffers, an indexed program: SKIPPED - this device does not publish CFT_SEQ_FEAT_INDEXED'
need
stage dt-scratch "device-test -b: no SCRATCH_IO, so no program's scratch through the buffers" -- \
  printf '%s\n' '  buffers, publish takes effect: 60 checks, 0 failed' \
    '  SKIPPED buffers, a program'"'"'s scratch: this device does not publish SCRATCH_IO'
need
stage dt-scratch-old "the same, as device-test printed it until 2026-09-24" -- \
  printf '%s\n' '  buffers, publish takes effect: 60 checks, 0 failed' \
    '  buffers, a program'"'"'s scratch: SKIPPED - this device does not publish SCRATCH_IO'
need
stage rt-format "remote-test: a format the server does not carry" -- \
  printf '%s\n' 'bit identity against the software backend, 64 elements:' \
    '  SKIPPED fp128: not on the server' '  fp256  ok'
need
stage rt-format-old "the same, as remote-test printed it until 2026-09-24" -- \
  printf '%s\n' 'bit identity against the software backend, 64 elements:' \
    '  fp128  skipped, not on the server' '  fp256  ok'
need
stage cpp-nosets "cpp-api-test: no vector sets to replay" -- \
  printf '%s\n' 'no vector sets found under ../vectors/out - nothing was checked' \
    'SKIP  cpp-api-test conformance: no vector sets in ../vectors/out (run `make vectors` from the repo root)' \
    'cpp-api-test: all 4130 checks passed'
need
stage cpp-nosets-old "the same, as cpp-api-test printed it until 2026-09-24" -- \
  printf '%s\n' \
    'cpp-api-test: SKIP conformance: no vector sets in ../vectors/out (run `make vectors` from the repo root)' \
    'cpp-api-test: all 4130 checks passed'
need
stage cpp-replay "cpp-api-test: a replay that skipped a set, its report printed" -- \
  printf '%s\n' '../vectors/out/fp32-rne.jsonl: imul skipped, not on this device' \
    '168 sets, 1068915 cases, all matching (the elementwise and transcendental sets replayed twice)' \
    'cpp-api-test: conformance replayed 1068915 cases from ../vectors/out'
need
stage cpp-replay-old "the same replay, as cpp-api-test printed it until 2026-09-24" -- \
  printf '%s\n' 'cpp-api-test: conformance replayed 1068915 cases from ../vectors/out'
need
stage rc-replay "remote_check.py: both replays skipped a set, their reports printed" -- \
  printf '%s\r\n' \
    'local : C:\Users\u\AppData\Local\Temp\cft-remote-vectors-k2/fp32-rne.jsonl: imul skipped, not on this device' \
    'remote: C:\Users\u\AppData\Local\Temp\cft-remote-vectors-k2/fp32-rne.jsonl: imul skipped, not on this device' \
    'local : 12 sets, 40211 cases, all matching (the elementwise sets replayed twice)' \
    'remote: 12 sets, 40211 cases, all matching (the elementwise sets replayed twice)' \
    'PASS conformance replay of C:\Users\u\AppData\Local\Temp\cft-remote-vectors-k2: local and remote agree (40211 cases checked; remote 3.1 s)'
need
stage rc-replay-old "the same replays, as remote_check.py printed them until 2026-09-24" -- \
  printf '%s\r\n' \
    'local : 12 sets, 40211 cases, all matching (the elementwise sets replayed twice)' \
    'remote: 12 sets, 40211 cases, all matching (the elementwise sets replayed twice)' \
    'PASS conformance replay of C:\Users\u\AppData\Local\Temp\cft-remote-vectors-k2: local and remote agree (40211 cases checked; remote 3.1 s)'
need
stage sim-case "tb/check_results.py: a bench that skipped one case" -- \
  printf '%s\n' '  fp32           ok       3 case(s)  (1 skipped)' \
    '  SKIP  fp32: test_fpfma.random_ops' \
    '-- 1 bench(es), 3 case(s), 1 skipped' 'PASS: 1 bench(es), no failures recorded'
need
stage sim-case-old "the same bench, as check_results.py printed it until 2026-09-24" -- \
  printf '%s\n' '  fp32           ok       3 case(s)  (1 skipped)' \
    '-- 1 bench(es), 3 case(s), 1 skipped' 'PASS: 1 bench(es), no failures recorded'
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
  RUNID=$(sed -n -e 's/^== run //p' -e 's/^== resuming //p' "$OUT")
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

PASSV="VERDICT: PASS with 6 inner skip(s) in gappy (5), replay (1) - see reasons above"
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

  echo "-- gappy and replay: six checks that did not run, no --require-all"
  go "$d" gappy --only clean,gappy,replay; gappy_run=$RUNID
  same  "gappy: exit 0" "$RC" 0 || bad=$((bad + 1))
  same  "gappy: the VERDICT names and counts them" "$VERDICT" "$PASSV" || bad=$((bad + 1))
  check "gappy: its row counts 5" grep -qE '^gappy +ok +[0-9]+s  \+ 5 inner skip\(s\)' "$OUT" || bad=$((bad + 1))
  check "gappy: the SKIP line named under the row" \
        grep -qxF '             SKIP  second - cannot run its check here: no "lib" at C:\x\y' "$OUT" || bad=$((bad + 1))
  check "gappy: the pytest line named under the row" \
        grep -qxF '             SKIPPED [3] tests\t_x.py:9: gmpy2 not installed' "$OUT" || bad=$((bad + 1))
  check "gappy: the replay's skipped set named under the row" \
        grep -qxF '             fp256-rne.jsonl: skipped, fp256 not on this device' "$OUT" || bad=$((bad + 1))
  check "replay: its row counts 1" grep -qE '^replay +ok +[0-9]+s  \+ 1 inner skip\(s\)' "$OUT" || bad=$((bad + 1))
  check "replay: the imul line named under the row" \
        grep -qxF '             fp32-rne.jsonl: imul skipped, not on this device' "$OUT" || bad=$((bad + 1))
  check "gappy: the census counts them" \
        grep -qF ', 0 skipped, 6 inner skip(s) (gappy (5), replay (1)).' "$OUT" || bad=$((bad + 1))
  check "gappy: the census names them" \
        grep -qxF '    gappy: SKIPPED [3] tests\t_x.py:9: gmpy2 not installed' "$OUT" || bad=$((bad + 1))
  check "replay: the census names it" \
        grep -qxF '    replay: fp32-rne.jsonl: imul skipped, not on this device' "$OUT" || bad=$((bad + 1))
  check "gappy: report.jsonl counts and names them, escaped" grep -qF \
        '"inner_skips":5,"inner_skip_lines":["SKIP  second - cannot run its check here: no \"lib\" at C:\\x\\y","SKIPPED [3] tests\\t_x.py:9: gmpy2 not installed","fp256-rne.jsonl: skipped, fp256 not on this device"]}' \
        "$JSONL" || bad=$((bad + 1))
  check "replay: report.jsonl counts and names it" grep -qF \
        '"inner_skips":1,"inner_skip_lines":["fp32-rne.jsonl: imul skipped, not on this device"]}' "$JSONL" || bad=$((bad + 1))
  check "gappy: clean beside them still counts nothing" grep -qE '^clean +ok +[0-9]+s$' "$OUT" || bad=$((bad + 1))

  echo "-- strict: the same under --require-all"
  go "$d" strict --only clean,gappy,replay --require-all
  same  "strict: exit 1" "$RC" 1 || bad=$((bad + 1))
  same  "strict: the VERDICT fails and names them" "$VERDICT" \
        "VERDICT: FAIL (2 stage(s), including under --require-all 6 inner skip(s) in gappy (5), replay (1))" || bad=$((bad + 1))
  go "$d" strict-replay --only replay --require-all
  same  "strict: the imul skip alone fails --require-all" "$RC" 1 || bad=$((bad + 1))
  same  "strict: the imul skip alone, on the VERDICT" "$VERDICT" \
        "VERDICT: FAIL (1 stage(s), including under --require-all 1 inner skip(s) in replay (1))" || bad=$((bad + 1))

  echo "-- resume: the gappy run, resumed"
  go "$d" resume --resume "$gappy_run" --only clean,gappy,replay
  check "resume: clean is served from cache" \
        grep -qE '^clean +ok +\(cached from earlier in this run\)$' "$OUT" || bad=$((bad + 1))
  check "resume: gappy runs again, not from cache" \
        grep -qE '^gappy +ok +[0-9]+s  \+ 5 inner skip\(s\)' "$OUT" || bad=$((bad + 1))
  same  "resume: the VERDICT still names them" "$VERDICT" "$PASSV" || bad=$((bad + 1))

  echo "-- colour: pytest's marker, painted"
  go "$d" colour --only colour
  same  "colour: exit 0" "$RC" 0 || bad=$((bad + 1))
  check "colour: its row counts 2" grep -qE '^colour +ok +[0-9]+s  \+ 2 inner skip\(s\)' "$OUT" || bad=$((bad + 1))
  check "colour: the line named under the row, colour removed" \
        grep -qxF '             SKIPPED [2] tests/test_y.py:4: painted by FORCE_COLOR' "$OUT" || bad=$((bad + 1))
  check "colour: report.jsonl counts and names it, colour removed" grep -qF \
        '"inner_skips":2,"inner_skip_lines":["SKIPPED [2] tests/test_y.py:4: painted by FORCE_COLOR"]}' "$JSONL" || bad=$((bad + 1))
  go "$d" strict-colour --only colour --require-all
  same  "strict: the coloured skip alone fails --require-all" "$RC" 1 || bad=$((bad + 1))
  same  "strict: the coloured skip alone, on the VERDICT" "$VERDICT" \
        "VERDICT: FAIL (1 stage(s), including under --require-all 2 inner skip(s) in colour (2))" || bad=$((bad + 1))
  return "$bad"
}
NCHECKS=32

# The skip lines the stages' own programs print. On 2026-09-24 four
# programs' were reprinted with the marker first (device-test's three,
# remote-test's, cpp-api-test's and tb/check_results.py's), and the
# replay's report was printed by the two programs that had kept only its
# counts (cpp-api-test, host/tests/remote_check.py). Each form has a
# stage above as its program prints it now, and a stage carrying the same
# gap as it was printed before. The first must count, and fail --require-all
# alone; the second must count nothing even under --require-all - the
# proof that the reprint was needed, not merely harmless. dt-format also
# carries device-test's closing summary, which since the same day counts
# what did not run by kind ("that RAN ... - skipped: 1 format, ..."),
# without the marker: each skip has its own line already, so the summary
# must not add to the count.
FORMS="dt-format dt-indexed dt-scratch rt-format cpp-nosets cpp-replay rc-replay sim-case"
nskips () { if [ "$1" = rc-replay ]; then echo 2; else echo 1; fi; }
named () {  # <stage> <the line as the runner names it under the row>
  check "$1: named under its row: ${2:0:64}" grep -qxF "             $2" "$OUT"
}
forms () {  # <runner>  ->  returns the number of checks it got wrong
  local d="$T/f.$RANDOM$RANDOM" bad=0 st n new="" old="" by=""
  mkrunner "$1" "$d" || return 1
  for st in $FORMS; do
    new="$new${new:+,}$st"; old="$old${old:+,}$st-old"
    by="$by${by:+, }$st ($(nskips "$st"))"
  done

  echo "-- forms: each line as its program prints it now"
  go "$d" forms --only "$new"
  same  "forms: exit 0" "$RC" 0 || bad=$((bad + 1))
  same  "forms: the VERDICT counts every one, by stage" "$VERDICT" \
        "VERDICT: PASS with 9 inner skip(s) in $by - see reasons above" || bad=$((bad + 1))
  for st in $FORMS; do
    n=$(nskips "$st")
    check "$st: its row counts $n" grep -qE "^$st +ok +[0-9]+s  \\+ $n inner skip\\(s\\)" "$OUT" || bad=$((bad + 1))
  done
  named dt-format  'SKIPPED fp128: not on this device' || bad=$((bad + 1))
  named dt-indexed 'SKIPPED buffers, an indexed program: this device does not publish CFT_SEQ_FEAT_INDEXED' || bad=$((bad + 1))
  named dt-scratch "SKIPPED buffers, a program's scratch: this device does not publish SCRATCH_IO" || bad=$((bad + 1))
  named rt-format  'SKIPPED fp128: not on the server' || bad=$((bad + 1))
  named cpp-nosets 'SKIP  cpp-api-test conformance: no vector sets in ../vectors/out (run `make vectors` from the repo root)' || bad=$((bad + 1))
  named cpp-replay '../vectors/out/fp32-rne.jsonl: imul skipped, not on this device' || bad=$((bad + 1))
  named rc-replay  'local : C:\Users\u\AppData\Local\Temp\cft-remote-vectors-k2/fp32-rne.jsonl: imul skipped, not on this device' || bad=$((bad + 1))
  named rc-replay  'remote: C:\Users\u\AppData\Local\Temp\cft-remote-vectors-k2/fp32-rne.jsonl: imul skipped, not on this device' || bad=$((bad + 1))
  named sim-case   'SKIP  fp32: test_fpfma.random_ops' || bad=$((bad + 1))

  echo "-- forms: each one alone, under --require-all"
  for st in $FORMS; do
    n=$(nskips "$st")
    go "$d" "strict-$st" --only "$st" --require-all
    same "$st: alone, --require-all exits 1" "$RC" 1 || bad=$((bad + 1))
    same "$st: alone, on the VERDICT" "$VERDICT" \
         "VERDICT: FAIL (1 stage(s), including under --require-all $n inner skip(s) in $st ($n))" || bad=$((bad + 1))
  done

  echo "-- the control: the same gaps, printed as they were until 2026-09-24"
  go "$d" forms-old --only "$old" --require-all
  same "old forms: exit 0, under --require-all" "$RC" 0 || bad=$((bad + 1))
  same "old forms: the VERDICT" "$VERDICT" "VERDICT: PASS, nothing skipped" || bad=$((bad + 1))
  for st in $FORMS; do
    check "$st-old: its row carries no count" grep -qE "^$st-old +ok +[0-9]+s\$" "$OUT" || bad=$((bad + 1))
  done
  return "$bad"
}
NFORMS=45

# ...and the sources still print them so. A fixture line is a claim
# about a program's output; these hold each claim to the line of source
# that makes it, and refuse the form it replaced. A form that was never
# printed before has no old line to refuse.
pins () {  # -> returns the number of pins that do not hold
  local row f new old bad=0 rows
  mapfile -t rows << 'PINS'
host/tests/device_test.c|printf("SKIPPED %s: not on this device\n",|printf("%-6s not on this device, skipped\n",
host/tests/device_test.c|printf("  SKIPPED buffers, an indexed program: "|"SKIPPED - this device does not "
host/tests/device_test.c|printf("  SKIPPED buffers, a program's scratch: this "|printf("  buffers, a program's scratch: SKIPPED - this "
host/tests/device_test.c|"that RAN, bits and flags - skipped: %d format%s, %d "|"that RAN, bits and flags\n"
host/tests/remote_test.c|printf("  SKIPPED %s: not on the server\n",|printf("  %-6s skipped, not on the server\n",
host/tests/cpp_api_test.cpp|std::printf("SKIP  cpp-api-test conformance: no vector sets in "|std::printf("cpp-api-test: SKIP conformance: no vector sets in "
host/tests/cpp_api_test.cpp|std::fputs(r.report.c_str(), stdout);|
host/tests/remote_check.py|print(tag + rep_line)|
tb/check_results.py|print("  SKIP  %s: %s" % (bench, line))|
PINS
  for row in "${rows[@]}"; do
    IFS='|' read -r f new old <<< "$row"
    if ! grep -qF -- "$new" "$ROOT/$f"; then
      echo "  FAIL  $f no longer carries: $new"; bad=$((bad + 1))
    elif [ -n "$old" ] && grep -qF -- "$old" "$ROOT/$f"; then
      echo "  FAIL  $f prints the old form again: $old"; bad=$((bad + 1))
    else
      echo "  ok    $f: $new"
    fi
  done
  return "$bad"
}
NPINS=9

echo "== verify/run.sh, as committed"
cases "$ROOT/verify/run.sh"; n=$?
[ "$n" -eq 0 ] || { echo "FAIL: $n of $NCHECKS check(s) wrong"; FAILS=$((FAILS + 1)); }
echo "== the programs' skip lines, as committed"
forms "$ROOT/verify/run.sh"; n=$?
[ "$n" -eq 0 ] || { echo "FAIL: $n of $NFORMS check(s) wrong"; FAILS=$((FAILS + 1)); }
echo "== the sources that print them"
pins; n=$?
[ "$n" -eq 0 ] || { echo "FAIL: $n of $NPINS pin(s) do not hold"; FAILS=$((FAILS + 1)); }

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
control replay-form-dropped INNER-SKIP-REPLAY \
  "REPLAY_SKIP_RE='^the control: a pattern no log line matches\$'" \
  "strict: the imul skip alone fails --require-all"
control cached-like-clean INNER-SKIP-NO-CACHE \
  '    : > "$RUNDIR/$name.ok"    # the control: a gap cached as a clean pass' \
  "resume: gappy runs again, not from cache"
control colour-left-in INNER-SKIP-ANSI \
  "ANSI_STRIP='s/^//'    # the control: no colour removed, only the ESC byte" \
  "strict: the coloured skip alone fails --require-all"

if [ "$FAILS" -eq 0 ]; then
  echo "PASS: $NCHECKS checks right, all four controls caught by their own checks;" \
       "$NFORMS checks of the programs' skip lines right, and $NPINS pins held"
  exit 0
fi
echo "FAIL: $FAILS problem(s)"
exit 1
