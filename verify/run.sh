#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The standardized verification run: every gate this project has
# accumulated, in one resumable, skippable, logged invocation.
#
#   bash verify/run.sh                 # the standard set
#   bash verify/run.sh --list          # show stages and their state
#   bash verify/run.sh --skip formal,soak-quick
#   bash verify/run.sh --only golden,sim
#   bash verify/run.sh --resume        # continue the most recent run
#   bash verify/run.sh --resume 20260831-2130-ec86467
#   bash verify/run.sh --fresh         # force a new run id
#   bash verify/run.sh --require-all   # a skipped stage FAILS the run
#   SIM_JOBS=12 bash verify/run.sh    # the cocotb targets twelve at a time
#   bash verify/run.sh --only cpp,node,wasm,lang-rust   # language legs, by name
#   bash verify/run.sh --budget quick   # ~20 min: the docs, generated, buildargs and
#                                      # sweepjudge checks, every model-vs-C check, the
#                                      # GPU's photograph, bindings, the language legs,
#                                      # soak, the five workloads, the browser demos and
#                                      # the remote backend - after a host build
#   bash verify/run.sh --budget gate    # ~2 h quiet, ~4 h loaded: quick + golden,
#                                      # vectors, libcft, transcend, mpfr, cpp, lint, formal,
#                                      # the C auditor's gate (audit), two cases of the
#                                      # estimates study (estimates), the variational
#                                      # equations (tangent) and the acceptance set
#   bash verify/run.sh --budget full    # everything: the census (adds sim, simmc,
#                                      # node, wasm, images, estimates-full,
#                                      # acceptance-far)
#   Measured durations for every stage, quiet and loaded, are in
#   docs/VERIFICATION.md - the simulation suites and the formal gate
#   run for more than an hour each on a busy box.
#
# Why this exists: the gates grew one at a time - pytest, the cocotb
# suite, yosys, the formal proofs, the library's contract tests, the
# conformance replay, the model sweeps, the native-oracle soak - each
# with its own invocation and its own environment quirks. That is fine
# for development and wrong for compliance: an open-core claim, a
# release, or a regression hunt wants ONE command whose report says
# what ran, what passed, what was skipped and WHY, against which
# commit, reproducibly. docs/VALIDATION.md is the census; this is the
# census-taker.
#
# Mechanics:
#   * Each stage writes verify/state/<run-id>/<stage>.log and a
#     .ok/.fail marker. Interrupt the run anywhere; --resume reruns
#     only what has no .ok. The run id encodes timestamp + commit, and
#     resuming refuses to cross commits - a half-run of one tree glued
#     to a half-run of another would be a report about nothing.
#   * A stage whose tools are absent is SKIPPED BY NAME with the
#     reason, never silently passed; --require-all turns those into
#     failures for machines that claim to be full verification hosts.
#   * A check INSIDE a stage that did not run is an INNER skip: its
#     script prints a line whose first word is SKIP or SKIPPED (or the
#     conformance replay's "<set>: ... skipped, ... on this device"),
#     and the runner reads a passing stage's log for those lines, with
#     terminal colour codes removed first. They
#     are named under the stage's row and in the census, counted in the
#     JSONL, the VERDICT and the census, and --require-all fails them
#     like any other skip.
#   * The exit code is the verdict: nonzero iff any stage FAILED
#     (or, under --require-all, was skipped or skipped a check inside).
#   * The report ends with a census block shaped for pasting into
#     docs/VALIDATION.md.
#
# Deliberately NOT here: the multi-hour campaigns (full native-oracle
# soak, RTL deep soak, hw_emu, on-card runs). Those are machine- and
# schedule-bound; they keep their own drivers (hw/run-soak.sh, the
# rtl-soak script, hw/run-device-test.sh) and their own census
# entries. The `images` stage will verify staged artifacts when
# IMAGES=... is exported and xclbinutil exists, because that check is
# cheap everywhere the artifacts are.
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
STATEROOT="$ROOT/verify/state"
COMMIT=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)
DIRTY=$(git -C "$ROOT" status --porcelain 2>/dev/null | head -1)
HOSTNM=$(hostname 2>/dev/null || echo unknown)

# ---- platform ------------------------------------------------------
WIN=0
case "$(uname -s)" in MINGW*|MSYS*) WIN=1;; esac

# Docker path/mangling differences: Git Bash rewrites -w /work into a
# C:\ path unless told not to, and the mount source must be the
# Windows-native path.
if [ "$WIN" = 1 ]; then
  MOUNT=$(cd "$ROOT" && pwd -W)
  DOCKER() { MSYS_NO_PATHCONV=1 docker "$@"; }
else
  MOUNT=$ROOT
  DOCKER() { docker "$@"; }
fi

# The host-library build needs per-platform incantations (see the
# memory of hard-won lessons in host/Makefile's header): on Windows,
# the mingw64 compiler, OS forced, and TMP passed as make vars or gcc
# cannot create its temp files.
if [ "$WIN" = 1 ]; then
  WTMP="$(echo "${USERPROFILE:-C:\\Users\\$USER}" | tr '\\' '/')/AppData/Local/Temp"
  EXE=.exe
else
  WTMP=""
  EXE=""
fi
HOSTMAKE() {
  if [ "$WIN" = 1 ]; then
    # pacman's go (mingw-w64-x86_64-go) is a trimmed binary that
    # cannot find its own GOROOT, and it is only reachable through
    # the PATH prefix below. GOROOT goes in as a MAKE VARIABLE, like
    # TMP and TEMP, because MSYS make hands recipes a stripped
    # environment and an exported variable never arrives - and only
    # when no other go is on the caller's PATH.
    local goroot=()
    if ! command -v go >/dev/null 2>&1 && [ -d /c/msys64/mingw64/lib/go ]; then
      goroot=(GOROOT="${GOROOT:-C:/msys64/mingw64/lib/go}")
    fi
    PATH="/c/msys64/mingw64/bin:$PATH" make -C "$ROOT/host" CC=gcc \
      OS=Windows_NT TMP="$WTMP" TEMP="$WTMP" "${goroot[@]}" "$@"
  else
    make -C "$ROOT/host" "$@"
  fi
}

# Prefer `python` before `python3` on Windows: python3 there is often
# the WindowsApps store alias, which ranges from a real interpreter to
# a shim that exits without running anything - and a runner that can
# be no-opped by PATH accidents is not a verification runner.
PY() {
  if [ "$WIN" = 1 ] && command -v python >/dev/null 2>&1; then python "$@"
  elif command -v python3 >/dev/null 2>&1; then python3 "$@"
  else python "$@"; fi
}

# ---- arguments -----------------------------------------------------
SKIP="${SKIP:-}"
ONLY="${ONLY:-}"
BUDGET=""
# The two named budgets. `quick` is every stage that finishes in
# seconds or a couple of minutes on a loaded desktop - the ctypes
# checks of the C against the model, the Python binding, the language
# legs, the soak - and it pre-builds the host library because those
# stages load it rather than build it. `gate` is what a package's
# reviewer ran before merging in September 2026: quick plus the
# model's own suite, the vectors, the million-case replay, the
# transcendentals, MPFR, the C++ header and the two RTL gates that
# need only a container - and, since 2026-09-29, the C auditor held to
# the golden one (audit), and since 2026-09-30 two cases of the
# certificate estimates' study (estimates), since 2026-10-01 the
# language's variational equations (tangent), and since 2026-10-02 the
# acceptance set (acceptance) and the compiler's routines, split from
# the language's quick stage (lang-routines). `full` is the census.
# Measured on the
# Windows desktop (docs/VERIFICATION.md has the table, quiet against
# loaded): quick ~20 min, gate ~2 h with the box quiet and ~4 h loaded
# now that the formal gate holds thirty proofs and a negative control
# (thirty-one tasks), full longer by the simulation suite and the two
# browser replays; on the WSL distro the replay stages take seconds.
BUDGET_QUICK=docs,generated,buildargs,sweepjudge,innerskips,ensurevectors,selfcheck,divsqrt,clause5,character,augmented,status96,formatof,diff,seq,programs,lang,reduce,photograph,bindings,lang-cpp,lang-rust,lang-julia,lang-go,lang-csharp,lang-r,lang-fortran,workloads,demos,soak-quick,remote
BUDGET_GATE=golden,vectors,lint,formal,libcft,$BUDGET_QUICK,transcend,mpfr,cpp,audit,estimates,lang-routines,tangent,acceptance
RESUME=""
FRESH=0
REQUIRE_ALL=0
LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --skip)   [ $# -ge 2 ] || { echo "--skip needs a value" >&2; exit 2; }
              SKIP="$SKIP,$2"; shift 2;;
    --only)   [ $# -ge 2 ] || { echo "--only needs a value" >&2; exit 2; }
              ONLY="$ONLY,$2"; shift 2;;
    --budget) [ $# -ge 2 ] || { echo "--budget needs quick, gate or full" >&2; exit 2; }
              case "$2" in
                quick) BUDGET=quick; ONLY="$ONLY,$BUDGET_QUICK";;
                gate)  BUDGET=gate;  ONLY="$ONLY,$BUDGET_GATE";;
                full)  BUDGET=full;;
                *) echo "--budget: unknown budget '$2' (quick, gate, full)" >&2; exit 2;;
              esac; shift 2;;
    --resume) if [ $# -gt 1 ] && [[ ${2:-} != --* ]]; then RESUME=$2; shift 2
              else RESUME=last; shift; fi;;
    --fresh)  FRESH=1; shift;;
    --require-all) REQUIRE_ALL=1; shift;;
    --list)   LIST=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

# The stage names and their descriptions are read from the `stage`
# calls below: this file is the only copy of the list. It used to be
# kept by hand in three places - a --list heredoc, a validation list
# and the calls - and the copies drifted twice: clause5 and mpfr
# reached the run without reaching --list, and the sim line claimed 15
# cocotb targets after the aggregate grew to 17. A list that can lie
# about what `make verify` does is worse than no list, and the last
# comment here said deriving it was worth more than another comment
# the next time the list grew. It grew: the language stages.
# Defined here rather than with the other helpers because --list below
# exits before them, and --list must decide "will this stage run?" with
# the SAME predicate stage() uses. Two copies of that rule is how the
# stage list lied twice before it was derived.
in_list() {  # name, comma-list
  case ",$2," in *",$1,"*) return 0;; esac
  return 1
}

SELF="${BASH_SOURCE[0]}"
STAGELIST=$(grep -E '^stage [a-z0-9-]+ "' "$SELF" | awk '{print $2}' | tr '\n' ' ')
STAGELIST="${STAGELIST% }"
if [ "$LIST" = 1 ]; then
  # `*` marks the stages THIS invocation would run, tested with in_list
  # against the same ONLY that stage() consults. Without it, a --list
  # beside --budget quick printed the whole file and read as though the
  # budget covered all of it.
  while IFS=$'\t' read -r _nm _ds; do
    if [ -z "$ONLY" ] || in_list "$_nm" "$ONLY"; then _mk="*"; else _mk=" "; fi
    printf '%s %-15s%s\n' "$_mk" "$_nm" "$_ds"
  done < <(grep -E '^stage [a-z0-9-]+ "' "$SELF" \
    | sed -E 's/^stage ([a-z0-9-]+) +"([^"]*)".*/\1\t\2/')
  echo
  # The counts are DERIVED and printed, so nothing downstream has to count
  # them. On 2026-09-12 three documents published 37/24/32 because the
  # counting probe was `--list | grep -c '^\*'` and the legend below used to
  # begin with a `*` too - so it counted itself. It no longer starts with one,
  # and the numbers come from here. Cite these; do not re-derive them.
  n_all=$(grep -cE '^stage [a-z0-9-]+ "' "$SELF")
  n_quick=$(echo "$BUDGET_QUICK" | tr ',' '\n' | grep -c .)
  n_gate=$(echo "$BUDGET_GATE" | tr ',' '\n' | grep -c .)
  echo "stages: $n_all total; $n_quick in --budget quick; $n_gate in --budget gate"
  if [ -n "$ONLY" ]; then
    printf 'marked = would run%s. Unmarked stages are NOT part of this selection.\n' \
        "${BUDGET:+ under --budget $BUDGET}"
  else
    echo "marked = would run: every stage, the full census (no --only, no --budget)."
  fi
  exit 0
fi

# ---- stage-name validation ------------------------------------------
# A typo'd --only used to select NOTHING, print "PASS, nothing
# skipped", and crash the census mid-print with an unbound variable -
# exit 0. A compliance runner must refuse names it does not know.
check_names() {  # <flagname> <comma-list>
  local n
  for n in $(echo "$2" | tr ',' ' '); do
    [ -z "$n" ] && continue
    case " $STAGELIST " in
      *" $n "*) ;;
      *) echo "ERROR: $1 names unknown stage '$n'" >&2
         echo "       stages: $STAGELIST" >&2
         exit 2;;
    esac
  done
}
check_names --skip "$SKIP"
check_names --only "$ONLY"

# ---- run identity --------------------------------------------------
mkdir -p "$STATEROOT"
if [ -n "$RESUME" ] && [ "$FRESH" = 1 ]; then
  echo "ERROR: --resume and --fresh contradict each other - pick one" >&2
  exit 2
fi
if [ -n "$RESUME" ]; then
  if [ "$RESUME" = last ]; then
    RUNID=$(ls -1 "$STATEROOT" 2>/dev/null | sort | tail -1)
    [ -n "$RUNID" ] || { echo "nothing to resume" >&2; exit 2; }
  else
    RUNID=$RESUME
  fi
  RUNDIR="$STATEROOT/$RUNID"
  [ -d "$RUNDIR" ] || { echo "no such run: $RUNID" >&2; exit 2; }
  OLDCOMMIT=$(cat "$RUNDIR/commit" 2>/dev/null || echo "")
  if [ "$OLDCOMMIT" != "$COMMIT" ]; then
    echo "REFUSING to resume $RUNID: it ran at commit $OLDCOMMIT and the" >&2
    echo "tree is now at $COMMIT. A report stitched across commits" >&2
    echo "certifies nothing - start fresh." >&2
    exit 2
  fi
  echo "== resuming $RUNID"
else
  # Second resolution plus a collision bump: the minute-resolution id
  # let a second invocation in the same minute silently ADOPT the
  # first one's .ok markers and PASS having run nothing - and made
  # --fresh a no-op inside the minute. mkdir without -p is the atomic
  # claim; an existing dir bumps the suffix.
  base="$(date +%Y%m%d-%H%M%S)-$COMMIT"
  RUNID=$base
  bump=2
  while ! mkdir "$STATEROOT/$RUNID" 2>/dev/null; do
    RUNID="$base-$bump"
    bump=$((bump + 1))
  done
  RUNDIR="$STATEROOT/$RUNID"
  echo "$COMMIT" > "$RUNDIR/commit"
  echo "== run $RUNID"
fi
SUMMARY="$RUNDIR/report.txt"
JSONL="$RUNDIR/report.jsonl"

# One writer per run directory. Two invocations interleaving their
# stage markers and logs in one run id produce a report about neither
# - discovered the practical way, when a killed wrapper's orphaned
# stage kept running beside its own resume. mkdir is the portable
# atomic primitive (Git Bash has no flock).
if ! mkdir "$RUNDIR/.lock" 2>/dev/null; then
  echo "REFUSING: $RUNID appears to be running already" >&2
  echo "  ($RUNDIR/.lock exists - remove it if that run is truly dead)" >&2
  exit 2
fi
trap 'rmdir "$RUNDIR/.lock" 2>/dev/null' EXIT

# ---- stage machinery -----------------------------------------------
FAILED=0
SKIPPED=0
RAN=0
CACHED=0
declare -a ROWS=()
INNER=0                 # inner skips, summed over the run
declare -a INNER_BY=()  # "<stage> (<n>)" for each stage that had any
declare -a INNER_LINES=()  # "<stage>: <its log line>", for the census


note() { ROWS+=("$1"); printf '%s\n' "$1"; }

# A JSON string body: the log lines that reach report.jsonl carry
# Windows paths and quotes. Control characters are gone by then.
json_esc() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '%s' "${s//$'\t'/\\t}"; }

# ---- inner skips ---------------------------------------------------
# A stage's exit status says only that nothing it ran failed. On
# 2026-09-24 `generated` wrote "SKIP  bindings/node/make_seq_corpus.py -
# cannot run its check here" into its log, exited 0, and the run said
# "PASS, nothing skipped" - so the summary, report.jsonl and
# --require-all never saw a check that had not run. The scripts the
# stages call already name such a check the same way: a line whose
# FIRST WORD is SKIP or SKIPPED, upper case, followed by a space, a
# colon or the end of the line (do_generated, reduce_check.py,
# hw/test-rebuild-argv.sh, bindings/node/test.mjs, host/Makefile's
# language legs, hw/verify-image.sh, and pytest's -rs summary). That
# convention is the marker: after a stage passes, its log is read for
# those lines, and each is an INNER skip - a check a HOST reason stopped.
# device-test and remote-test name what the DEVICE under test does not
# publish as "<what>: NOT COMPARED|NOT TESTED|NOT RUN - <why>" instead,
# never SKIP first, so those are not read here: their matrices adapt to
# the device by design (verify/README.md, "Skips are named, never
# silent", has the rule and every such form; device-test's opcode list
# was SKIP first until 2026-09-24).
# First word only, and case-sensitive, because the logs are full of
# the word in other places - cocotb's "SKIP=0", pytest's "5 skipped",
# prose about skipping - and every one of those is a line that names
# no skipped check. A pytest line folds tests with one reason into
# "SKIPPED [n]", so it counts n.
#
# One other form is read, because the runner cannot change it: the
# conformance replay (host/src/conformance.c) reports a set or an opcode
# it could not replay as "<set>: skipped, <what> not on this device" or
# "<set>: <op> skipped, not on this device", one line each, and none of
# the 67 runs kept in the main checkout's verify/state on 2026-09-24
# logged a line of that shape at all. cft-selftest prints that report,
# so it reaches the libcft stage's log, and since 2026-09-24 cpp_api_test
# and remote_check.py print it too - before, they printed only the
# replay's counts, so a set skipped under the cpp or remote stage
# reached no log. A check that reports its skip in any third way is
# invisible here, and should print the SKIP marker.
#
# A line is matched as text, not as a terminal paints it. pytest under
# FORCE_COLOR=1, PY_COLORS=1 or PYTEST_ADDOPTS=--color=yes writes
# "ESC[33mSKIPPEDESC[0m [n] ...", and when only the ESC byte was removed
# the first word read "[33mSKIPPED" - so on 2026-09-24 a coloured
# `--only golden --require-all` said "VERDICT: PASS, nothing skipped"
# over seven skips, exit 0 (verify-P4, measured). The two pytest stages
# pass --color=no, which outranks all three settings (measured, pytest
# 9.1); and every stage's log has its CSI sequences (ESC [ params final)
# and charset selections (ESC ( B) removed here before anything is
# matched, for whatever else colours its output. Any other ESC byte goes
# with the control characters after that.
ANSI_STRIP=$'s/\033\\[[0-9;:<=>?]*[@-~]//g; s/\033[()][0-9A-Za-z]//g'    # INNER-SKIP-ANSI
INNER_SKIP_RE='^[[:space:]]*SKIP(PED)?([[:space:]:]|$)'
REPLAY_SKIP_RE=': ([^[:space:]]+ )?skipped, .*on this device$'    # INNER-SKIP-REPLAY
inner_scan() {  # <log>  ->  its inner-skip lines, trimmed, one per line
  LC_ALL=C sed -E "$ANSI_STRIP" < "$1" | tr -d '\000-\010\013-\037' \
    | grep -E -e "$INNER_SKIP_RE" -e "$REPLAY_SKIP_RE" | sed -E 's/^[[:space:]]+//'
}

stage() {  # <name> <description> -- command...
  local name=$1 desc=$2; shift 3
  local t0 t1 dur verdict="" reason=""

  if [ -n "$ONLY" ] && ! in_list "$name" "$ONLY"; then
    return 0                       # not selected: not even reported
  fi
  if [ -f "$RUNDIR/$name.ok" ]; then
    # A stage that already PASSED in this run stays passed - --skip on
    # a resume must not re-verdict green work as skipped (under
    # --require-all that inverted a finished PASS into a FAIL).
    CACHED=$((CACHED+1))
    note "$(printf '%-14s %-7s %s' "$name" "ok" "(cached from earlier in this run)")"
    echo "{\"stage\":\"$name\",\"verdict\":\"ok-cached\"}" >> "$JSONL"
    return 0
  fi
  if in_list "$name" "$SKIP"; then
    verdict=SKIP; reason="requested"
  elif [ -n "${STAGE_SKIP_REASON:-}" ]; then
    verdict=SKIP; reason=$STAGE_SKIP_REASON
  fi

  if [ "${verdict:-}" = SKIP ]; then
    SKIPPED=$((SKIPPED+1))
    note "$(printf '%-14s %-7s %s' "$name" "SKIP" "$reason")"
    echo "{\"stage\":\"$name\",\"verdict\":\"skip\",\"reason\":\"$(json_esc "$reason")\"}" >> "$JSONL"
    [ "$REQUIRE_ALL" = 1 ] && FAILED=$((FAILED+1))
    return 0
  fi

  echo "-- $name: $desc"
  t0=$(date +%s)
  if ( set -o pipefail; "$@" ) > "$RUNDIR/$name.log" 2>&1; then
    t1=$(date +%s); dur=$((t1-t0))
    local inner n=0 k l js=""
    inner=$(inner_scan "$RUNDIR/$name.log")    # INNER-SKIP-SCAN
    while IFS= read -r l; do
      [ -n "$l" ] || continue
      k=1; [[ $l =~ ^SKIPPED\ \[([0-9]+)\] ]] && k=${BASH_REMATCH[1]}
      n=$((n+k)); js="$js${js:+,}\"$(json_esc "$l")\""
    done <<< "$inner"
    # No .ok for a pass with a gap in it: like a skipped stage, it runs
    # again on --resume, so a resume can never serve its skips from cache
    # as a clean pass.
    [ "$n" -eq 0 ] && : > "$RUNDIR/$name.ok"    # INNER-SKIP-NO-CACHE
    RAN=$((RAN+1))
    rm -f "$RUNDIR/$name.fail"
    if [ "$n" -eq 0 ]; then
      note "$(printf '%-14s %-7s %ss' "$name" "ok" "$dur")"
    else
      INNER=$((INNER+n)); INNER_BY+=("$name ($n)")
      [ "$REQUIRE_ALL" = 1 ] && FAILED=$((FAILED+1))
      note "$(printf '%-14s %-7s %ss  + %s inner skip(s) - checks inside it that did not run:' \
             "$name" "ok" "$dur" "$n")"
      while IFS= read -r l; do
        note "$(printf '%-14s %s' "" "$l")"; INNER_LINES+=("$name: $l")
      done <<< "$inner"
    fi
    echo "{\"stage\":\"$name\",\"verdict\":\"ok\",\"seconds\":$dur,\"inner_skips\":$n,\"inner_skip_lines\":[$js]}" >> "$JSONL"
  else
    t1=$(date +%s); dur=$((t1-t0))
    : > "$RUNDIR/$name.fail"
    RAN=$((RAN+1))
    FAILED=$((FAILED+1))
    note "$(printf '%-14s %-7s %ss  log: verify/state/%s/%s.log' \
           "$name" "FAIL" "$dur" "$RUNID" "$name")"
    echo "{\"stage\":\"$name\",\"verdict\":\"fail\",\"seconds\":$dur}" >> "$JSONL"
    tail -12 "$RUNDIR/$name.log" | sed 's/^/     | /'
  fi
}

# A C compiler HOSTMAKE can use: the one predicate behind `need host-cc`
# and behind do_generated's decision to build the library itself.
have_host_cc() {
  if [ "$WIN" = 1 ]; then [ -x /c/msys64/mingw64/bin/gcc.exe ]
  else command -v cc >/dev/null 2>&1; fi
}

# Tool preconditions, expressed as a skip reason for the NEXT stage.
need() {  # docker|host-cc|xclbinutil ...
  STAGE_SKIP_REASON=""
  for t in "$@"; do
    case "$t" in
      # Present is not usable: a WSL distro without Docker Desktop's
      # integration has a `docker` shim on PATH that only prints how to
      # enable it, and on 2026-09-02 that FAILED sim, lint and formal
      # in 0 s each instead of skipping them by name.
      docker) docker version >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="docker not usable on this host (absent, or present without a reachable engine)";;
      host-cc) have_host_cc || if [ "$WIN" = 1 ]; then
                 STAGE_SKIP_REASON="mingw64 gcc not found"
               else STAGE_SKIP_REASON="no C compiler"; fi;;
      python) command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="no python";;
      # A module, not a command: the interpreter PY() picks must import
      # it, or the pytest stages say so instead of failing in 0 s.
      pytest) PY -c 'import pytest' >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="python has no pytest module (pip install pytest)";;
      mpmath) PY -c 'import mpmath' >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="python has no mpmath module (pip install mpmath)";;
      xclbinutil) command -v xclbinutil >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="xclbinutil not present (XRT hosts only)";;
      mpfr) [ -f "$ROOT/verify/_mpfr-prefix/include/mpfr.h" ] || \
            [ -f /c/msys64/mingw64/include/mpfr.h ] || \
            [ -f /usr/include/mpfr.h ] || \
            [ -f /usr/include/x86_64-linux-gnu/mpfr.h ] \
        || STAGE_SKIP_REASON="libmpfr headers not found (verify/build-mpfr-oracle.sh builds them from pinned sources, no root needed)";;
      # The language toolchains. On Windows the C++ and Fortran
      # compilers are the mingw64 ones HOSTMAKE puts on PATH, so they
      # are looked for there and not only on the caller's PATH.
      cxx) if [ "$WIN" = 1 ]; then
             [ -x /c/msys64/mingw64/bin/g++.exe ] \
               || STAGE_SKIP_REASON="mingw64 g++ not found";
           else command -v g++ >/dev/null 2>&1 || command -v c++ >/dev/null 2>&1 \
               || STAGE_SKIP_REASON="no C++ compiler"; fi;;
      gfortran) if [ "$WIN" = 1 ]; then
             [ -x /c/msys64/mingw64/bin/gfortran.exe ] \
               || command -v gfortran >/dev/null 2>&1 \
               || STAGE_SKIP_REASON="no gfortran (mingw64 or PATH)";
           else command -v gfortran >/dev/null 2>&1 \
               || STAGE_SKIP_REASON="no gfortran on PATH"; fi;;
      images-env) [ -n "${IMAGES:-}" ] \
        || STAGE_SKIP_REASON="no IMAGES=... exported (nothing staged to verify)";;
      # Any other name is a command that must be on PATH - rustc,
      # julia, go, dotnet, Rscript, node - or, on Windows, in the
      # mingw64 bin directory HOSTMAKE prepends (pacman's go lives
      # there and nowhere on the caller's PATH).
      *) command -v "$t" >/dev/null 2>&1 \
        || { [ "$WIN" = 1 ] && [ -x "/c/msys64/mingw64/bin/$t.exe" ]; } \
        || STAGE_SKIP_REASON="no $t on PATH";;
    esac
    [ -n "$STAGE_SKIP_REASON" ] && return 0
  done
  return 0
}

# ---- the stages ----------------------------------------------------
# Order is dependency order: the model before things checked against
# it, vectors before their replay, the library before its sweeps.


# A quick budget skips the libcft stage, which is where the host
# library gets built in a gate or full run; the ctypes checks that
# follow load the library rather than build it, so build it here.
# Not silent: a build that fails prints, and the first stage that
# needs the library then fails by name instead of mysteriously.
if [ "$BUDGET" = quick ]; then
  HOSTMAKE all >/dev/null 2>&1 || HOSTMAKE all || echo "quick budget: host build failed" >&2
fi

need python
stage docs "docs/README.md indexes every document; every document's links and quoted paths resolve; stated counts true; a planted fault per check, each caught by name" -- \
  PY "$ROOT/python/check_docs_index.py" --quiet


# The bitstream script's link line, without a bitstream. hw/rebuild-2022.sh
# builds `--clock.freqHz` into a shell variable and an inner loop once
# reused that variable's name, erasing the clock constraint while the build
# still reported success - two hours to discover, and only by reading a
# timing report rather than an exit code. hw/test-rebuild-argv.sh puts stub
# v++ and vivado on PATH, runs the REAL script with VPP_PROPS set (an empty
# VPP_PROPS is exactly the case that never broke), and reads back the argv.
# Its negative control reintroduces the defect and requires the check to
# catch it.
#
# `need` with no arguments only clears any skip reason the previous stage
# left. The condition here is not a missing tool but a present one: a real
# Vitis is sourced by rebuild-2022.sh before it looks for v++, and that
# prepends the real toolchain, so the stub loses and a two-hour link starts
# on a build host. Measured on amd-arc-box, which is why this is a refusal
# rather than a hope.
need
for _vroot in /data/Xilinx /opt/Xilinx /tools/Xilinx; do
  [ -f "$_vroot/Vitis/2022.2/settings64.sh" ] && STAGE_SKIP_REASON="a real Vitis at $_vroot is sourced by rebuild-2022.sh and takes PATH from the stub"
done
stage buildargs "hw/rebuild-2022.sh hands v++ the clock constraint with VPP_PROPS set, CFT_GENERICS reaches vivado and the manifest, a lying wrapper read-back stops the build before v++; each with its negative control" -- \
  bash "$ROOT/hw/test-rebuild-argv.sh"

# A frequency sweep's verdicts, without a build. hw/sweep_freq.sh judges
# CLOSED / MISSED / NONE from the artifacts a build leaves; its first
# version read the whole-design WNS (the shell's 0.055 ns where the kernel
# had +0.084) and would have taken a staged image for a closed one. The
# test holds 13 synthetic builds to their verdicts and puts each of those
# two defects back into a copy of the script, which the case written for
# it must catch. No Vivado and no card, so nothing here is skipped.
need
stage sweepjudge "hw/sweep_freq.sh judges a sweep point by the kernel clock's own WNS, never the shell's, and a staged image is not a closed one; each with its negative control" -- \
  bash "$ROOT/hw/test-sweep-judge.sh"

# The runner's own two tests, which no stage ran until 2026-09-30: a
# widened stage table broke test-inner-skips.sh for a commit, and only
# a verifier running it by hand saw (verifier-W2, the steps 5 and 6
# round). test-inner-skips.sh holds the count and naming of checks
# skipped inside a passing stage, against synthetic stages, with its
# negative controls: bash only. test-ensure-vectors.sh holds
# ensure_vectors' rules for reusing or remaking vectors/out against
# planted directories, running the generator at small counts: python
# with mpmath. Each is skipped by name only for what it needs.
# Its report quotes skip lines, which is what it tests, and this stage's
# own log is scanned for inner skips like every other: the first run
# counted the quotation "cpp-replay: ...: imul skipped, not on this
# device" as a skip of this stage's (amd-arc-box, 58fea7d). So the
# report goes to innerskips-detail.log beside the stage's log, and the
# stage's log carries the verdict, or the report's tail on a failure.
do_innerskips() {
  local detail="$RUNDIR/innerskips-detail.log" rc
  bash "$ROOT/verify/test-inner-skips.sh" > "$detail" 2>&1; rc=$?
  if [ $rc -eq 0 ]; then tail -n 1 "$detail"; else tail -n 40 "$detail"; fi
  echo "(the whole report: $detail)"
  return $rc
}
need
stage innerskips "verify/run.sh counts and names the checks skipped inside a passing stage, held to synthetic stages, each with its negative control (verify/test-inner-skips.sh)" -- \
  do_innerskips
need python mpmath
stage ensurevectors "verify/run.sh's ensure_vectors replays vectors/out only when its record is whole and held, and otherwise regenerates it and says why, held to planted directories (verify/test-ensure-vectors.sh)" -- \
  bash "$ROOT/verify/test-ensure-vectors.sh"

# pytest is this stage's precondition. It used to sit on `docs`, which
# does not import it, while the bare `need` calls above cleared it - so
# a python without pytest skipped docs for nothing and FAILED golden in
# a second ("No module named pytest") instead of skipping it by name,
# measured on 2026-09-24 with a venv that lacks it. -rs has pytest
# name every test it skipped, one "SKIPPED [n] <file>:<line>: <reason>"
# line per reason, which is the marker the inner-skip count reads;
# --color=no keeps a coloured environment from painting that marker
# (inner_scan, above).
need python pytest
stage golden "golden-model pytest suite (the definition of correct)" -- \
  PY -m pytest "$ROOT/python/tests" -q -rs --color=no

# The sets every replaying stage reads, and how the runner knows they are
# whole. VECTOR_ARGS is the generator's command line for them, one copy
# for this stage and for ensure_vectors below: every format, all five
# attributes, the generator's own default counts (not `make vectors`'
# smaller ones; docs/VERIFICATION.md gives both totals).
#
# A directory of sets is whole when the generation that wrote it FINISHED
# and nothing has changed it since, and vectors/gen_vectors.py records
# that itself: it removes <out>/SHA256SUMS before it writes a set and
# writes a new one after the last, naming every set with its sha256. So
# vectors_whole asks three things - is there a record, does it name every
# set the profile's own record (vectors/SHA256SUMS) names, does
# `sha256sum -c` hold it - and says by name which one failed. Until
# 2026-09-29 the test was "is anything in the directory": on 2026-09-28 a
# generation that died for want of mpmath left five fp256 sets and every
# later run reused them. cft-selftest, the libcft stage's replay, passes
# on what that crash leaves: reproduced in scratch on 2026-09-29, it
# printed "5 sets, 3200 cases, all matching" and exited 0, and so did
# cpp-api-test and remote's WebSocket leg; only node and wasm refused it.
VECTOR_ARGS=(--rounding rne rtz rdn rup rmm)

sha256_holds() {  # in the directory: check its SHA256SUMS, every line
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c --quiet --strict SHA256SUMS 2>&1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -c --quiet --strict SHA256SUMS 2>&1
  else
    echo "neither sha256sum nor shasum is on PATH to check it with"
    return 1
  fi
}

vectors_whole() {  # <dir>: prints what it found; returns 1 unless whole
  local d=$1 lbl=${1#"$ROOT"/} prof="$ROOT/vectors/SHA256SUMS"
  local want have miss out n nwant nlines
  if [ ! -f "$prof" ]; then
    echo "vectors/SHA256SUMS is missing, so which sets the profile names is unknown"
    return 1
  fi
  # sha256sum's two forms of a line, "<hash>  <name>" and, as MSYS
  # writes it, "<hash> *<name>": `sha256sum -c` reads both, so this does.
  want=$(tr -d '\r' < "$prof" | sed -n 's#^[0-9a-fA-F]\{64\} [ *]out/##p' | LC_ALL=C sort)
  nwant=$(printf '%s\n' "$want" | grep -c .)
  nlines=$(tr -d '\r' < "$prof" | grep -c .)
  if [ "$nwant" -eq 0 ] || [ "$nwant" -ne "$nlines" ]; then
    echo "vectors/SHA256SUMS has $nlines lines and $nwant of them read as '<sha256>  out/<set>'"
    return 1
  fi
  if [ ! -d "$d" ]; then
    if [ -e "$d" ]; then echo "$lbl is not a directory"; else echo "$lbl does not exist"; fi
    return 1
  fi
  if [ ! -f "$d/SHA256SUMS" ]; then
    echo "$lbl has no SHA256SUMS: no generation of it finished, or the one that wrote it predates the record (2026-09-29)"
    return 1
  fi
  have=$(tr -d '\r' < "$d/SHA256SUMS" | sed -n 's#^[0-9a-fA-F]\{64\} [ *]##p' | LC_ALL=C sort)
  miss=$(LC_ALL=C comm -23 <(printf '%s\n' "$want") <(printf '%s\n' "$have"))
  if [ -n "$miss" ]; then    # VECTORS-WHOLE-NAMES
    n=$(printf '%s\n' "$miss" | grep -c .)
    echo "$lbl/SHA256SUMS leaves out $n of the $nwant sets vectors/SHA256SUMS names: $(printf '%s\n' "$miss" | sed -n '1,4p' | tr '\n' ' ')$([ "$n" -gt 4 ] && echo "and $((n - 4)) more")"
    return 1
  fi
  if ! out=$(cd "$d" && sha256_holds); then    # VECTORS-WHOLE-DIGESTS
    echo "$lbl/SHA256SUMS does not hold: $(printf '%s\n' "$out" | sed -n '1,6p' | tr '\n' ';')"
    return 1
  fi
  echo "$lbl/SHA256SUMS names all $nwant sets vectors/SHA256SUMS names, and all $(grep -c . "$d/SHA256SUMS") it names hold"
}

do_vectors() {
  local msg
  if ! PY "$ROOT/vectors/gen_vectors.py" --out "$ROOT/vectors/out" "${VECTOR_ARGS[@]}"; then
    echo "vectors: FAILED - the generator exited nonzero, so vectors/out is not a whole set"
    return 1
  fi
  if ! msg=$(vectors_whole "$ROOT/vectors/out"); then
    echo "vectors: FAILED - the generator exited 0, but $msg"
    return 1
  fi
  echo "vectors: $msg"
}
need python
stage vectors "regenerate the conformance sets from the model, all five attributes, and hold the generation's own SHA256SUMS to every set the profile names" -- \
  do_vectors

ensure_sim_image() {
  docker image inspect cft-sim >/dev/null 2>&1 && return 0
  DOCKER build -t cft-sim -f "$MOUNT/docker/Dockerfile.sim" "$MOUNT"
}
do_sim()  { ensure_sim_image && \
            DOCKER run --rm -v "$MOUNT:/work" -w /work/tb cft-sim make -k -j"${SIM_JOBS:-1}" sim; }
do_simmc() { ensure_sim_image && \
            DOCKER run --rm -v "$MOUNT:/work" -w /work/tb cft-sim make -k -j"${SIM_JOBS:-1}" MC="${MC:-10}" simmc; }
do_lint() { ensure_sim_image && \
            DOCKER run --rm -v "$MOUNT:/work" -w /work cft-sim make yosys-lint; }

need docker
stage sim "cocotb RTL suite, all 27 targets, SIM_JOBS at a time (docker cft-sim)" -- do_sim

# The same benches with the multiplier iterated and the array paced
# (tb/Makefile simmc, MC=10 unless MC= says otherwise): the multi-cycle
# tile's own census, beside the shipping default rather than instead
# of it. Not in the quick or gate budgets - it is the third tier's
# gate. On 2026-09-29 it took 1 h 16 min at four jobs on amd-arc-box,
# where sim took 1 h 40 min at six (docs/VERIFICATION.md).
need docker
stage simmc "cocotb suite at the multi-cycle pass budget MC (docker cft-sim)" -- do_simmc

need docker
stage lint "yosys elaboration gate, every RTL file (docker cft-sim)" -- do_lint

do_formal() {
  docker image inspect cft-formal >/dev/null 2>&1 || \
    DOCKER build -t cft-formal -f "$MOUNT/docker/Dockerfile.formal" "$MOUNT/docker" || return 1
  DOCKER run --rm -v "$MOUNT:/work" -w /work cft-formal ./formal/run.sh
}
need docker
stage formal "property proofs + negative control (docker cft-formal)" -- do_formal

# One interpreter for every python-touching stage, chosen by PY()'s
# rule - the libcft stage used to hand make `command -v python3`,
# which on Windows is the WindowsApps alias PY() exists to avoid.
# cft.dll on Windows, libcft.dylib on Darwin (2026-09-09), libcft.so elsewhere
SHLIB_NAME=$(if [ "$WIN" = 1 ]; then echo cft.dll; elif [ "$(uname -s)" = Darwin ]; then echo libcft.dylib; else echo libcft.so; fi)
PYBIN=$(if [ "$WIN" = 1 ] && command -v python >/dev/null 2>&1; then
          command -v python
        else command -v python3 2>/dev/null || command -v python; fi)
# Clean before building, always. The host tree is one checkout shared
# between Windows (Git Bash) and WSL (through /mnt/c), and a WSL build
# leaves elf64 objects that Windows make then sees as up to date and
# hands to the mingw linker - which reports `undefined reference to
# cft_open` and glibc's `__snprintf_chk`, not a format error. On
# 2026-09-02 that failed this stage in 0 s and every host-binary stage
# after it in 1-3 s, ten FAILs from one stale build. The library
# builds in seconds; a census that could be poisoned by whichever
# platform touched the tree last is not a census.
#
# Then the library compiled at every build profile and every
# cft_config.h switch alone, and the combinations cft_config.h refuses
# held to their refusal (host/Makefile's profiles-check, which says
# why): the default build cannot see a call that only a CFT_NO_PROGRAM
# or CFT_TINY build leaves undeclared, and one did, unseen, from
# 2026-09-14 to 2026-09-24. It runs whether or not `test` passed, and
# with -k, so one log names every profile that fails as well as a
# failing test.
#
# The vectors: `test` replays vectors/out, and so do cpptest, the Node
# binding, the wasm page and remote's WebSocket leg below. The `vectors`
# stage regenerates them earlier in a full run; an --only run may not
# have them, or may find what a crashed generation left. A directory
# that is not whole (vectors_whole, above the `vectors` stage) is
# regenerated, not replayed and not skipped past: a replay of part of
# the census is not the census, and a replay of nothing is not a replay.
# If it cannot be made whole, the stage fails, naming why. Defined here,
# above the first stage that calls it, because a stage runs where it is
# declared: until 2026-09-24 this sat beside do_cpp, do_libcft did not
# call it, and `--only libcft` in a fresh checkout failed with "no
# vector sets found".
ensure_vectors() {
  local d="$ROOT/vectors/out" msg
  if msg=$(vectors_whole "$d"); then    # ENSURE-VECTORS-WHOLE
    echo "ensure_vectors: $msg"
    return 0
  fi
  echo "ensure_vectors: not a whole set, so it is regenerated - $msg"
  if ! PY "$ROOT/vectors/gen_vectors.py" --out "$d" "${VECTOR_ARGS[@]}"; then
    echo "ensure_vectors: FAILED - the generator exited nonzero, so vectors/out is still not a whole set and nothing here replays it"
    return 1
  fi
  if ! msg=$(vectors_whole "$d"); then
    echo "ensure_vectors: FAILED - regenerated, and still not a whole set: $msg"
    return 1
  fi
  echo "ensure_vectors: regenerated - $msg"
}

do_libcft() {
  local rc=0
  # A bare `make -C host` must build: the default goal is `all`, not
  # whichever rule sits first (f953f4c made it print-src, 2026-09-25 to
  # 2026-09-28, and no stage noticed, because every stage names its
  # targets).
  local goal
  goal=$(HOSTMAKE -s --no-print-directory print-default-goal 2>/dev/null)
  if [ "$goal" != "all" ]; then
    echo "host/Makefile's default goal is \"$goal\", not \"all\": a bare make -C host would not build"
    rc=1
  fi
  HOSTMAKE clean >/dev/null 2>&1
  ensure_vectors && HOSTMAKE test PYTHON="$PYBIN" || rc=1
  HOSTMAKE -k profiles-check || rc=1
  return $rc
}
need host-cc python
stage libcft "host library: build + contract tests + the build id regenerated + conformance replay + every build profile compiles" -- do_libcft

# Placed after `libcft` on purpose: make_seq_corpus.py's check loads
# libcft through ctypes, and that stage is what builds it. Sitting
# earlier (as this did when written) meant the corpus check took its
# skip path on any clean checkout - including CI, where it would then
# never have run the one check that had actually caught drift.
# Six generators' committed files, each held to its generator. Not
# every generated file in the tree: host/include/cft_seq_flags.h is held
# by `make seqflags` (python/gen_seq_flags.py --check) and
# rtl/cft_seed_rom.svh by the golden suite's test_seed_rom_sync.py.
#
# Each of these scripts already carried a --check mode that exits 1 when
# the file on disk differs from a fresh generation, and until 2026-09-13
# nothing invoked any of them. Two had drifted by the time anyone ran
# them: hw/layouts/*.cfg, five files whose commented-out clock line still
# carried a superseded WNS note, and bindings/node/seq_corpus.jsonl,
# stale since the kx corruption kinds landed - so the wasm harness was
# replaying a 192-case corpus containing none of them and passing.
#
# A generated file that says "GENERATED by X; edit the table there" and
# is checked by nothing is a comment, not a guarantee. This is the gate
# that makes the comment true.
#
# make_seq_corpus.py is the one with a prerequisite beyond python: it
# drives libcft through ctypes, host/$SHLIB_NAME. So this stage builds
# that library itself - `make -C host cft.dll` on Windows, libcft.so on
# Linux, libcft.dylib on Darwin: the Makefile's $(SHLIB) target - on any
# host with a C compiler, as `reduce` builds reduce-parts. The libcft
# stage runs first and builds it too, but an --only run without libcft,
# a --skip libcft run and a clean checkout would otherwise take the skip
# path, and measured on 2026-09-24 `--only generated` on a clean
# checkout did, on a desktop whose compiler could have built it in
# seconds. Only with no compiler AND no library is the check skipped BY
# NAME rather than counted as agreement - the distinction this suite
# exists to keep. That SKIP line is an inner skip (stage(), above): it
# reaches the stage's row, the VERDICT and the census, and fails the run
# under --require-all.
#
# Any other nonzero --check is a FAIL. Staleness is recognised by the
# generator's own message and printed as STALE; anything else is a check
# that broke, and until 2026-09-24 that was printed as a SKIP as well -
# a traceback in any of the five read as "cannot run its check here".
do_generated() {
  local rc=0 g out grc cc=0
  if have_host_cc; then
    cc=1
    HOSTMAKE "$SHLIB_NAME" || {
      printf '  FAIL  make -C host %s: the library make_seq_corpus.py loads did not build\n' \
             "$SHLIB_NAME"
      rc=1
    }
  fi
  for g in hw/gen_layouts.py host/tools/gen_2opi.py \
           host/tools/gen_mp_consts.py bindings/node/make_seq_corpus.py \
           python/gen_divfull.py bindings/arduino/sync.py; do
    out=$(PY "$ROOT/$g" --check 2>&1); grc=$?
    if [ $grc -eq 0 ]; then
      printf '  ok    %s\n' "$g"
    elif printf '%s' "$out" | grep -qiE "stale|differs from a fresh|has drifted from host/"; then
      printf '  STALE %s - regenerate with: python %s\n' "$g" "$g"
      printf '%s\n' "$out" | tail -3 | sed 's/^/        /'
      rc=1
    elif [ "$cc" = 0 ] && [ "$g" = bindings/node/make_seq_corpus.py ] \
         && [ ! -f "$ROOT/host/$SHLIB_NAME" ]; then
      printf '  SKIP  %s - no C compiler here to build host/%s, which its check loads: %s\n' \
             "$g" "$SHLIB_NAME" "$(printf '%s' "$out" | tail -1)"
    else
      printf '  FAIL  %s - its --check exited %s:\n' "$g" "$grc"
      printf '%s\n' "$out" | tail -3 | sed 's/^/        /'
      rc=1
    fi
  done
  return $rc
}
need python
stage generated "the committed output of six generators still matches a fresh generation, by each one's --check (the Arduino copy of host/ among them)" -- do_generated

do_selfcheck() {
  HOSTMAKE "device-test$EXE" || return 1
  # Both legs. -b is the device-resident one: the same matrix and the
  # same reductions through cft_alloc'd operands, every byte and every
  # flag held to the host-pointer path. Against `sw` it cannot prove
  # the SAVING - there are no device copies to serve from - but it
  # proves the CONTRACT and it proves the leg can fail, which is what a
  # census wants running on every machine rather than only where a card
  # is (docs/HOSTAPI.md, "Device-resident buffers").
  (cd "$ROOT/host" && "./device-test$EXE" sw -n 96 \
                   && "./device-test$EXE" sw -b -n 96)
}
need host-cc
stage selfcheck "device-test harness, software-vs-software full matrix (seeds + div/sqrt included), then the same through cft_alloc'd buffers" \
  -- do_selfcheck

need host-cc python
stage divsqrt "cft_div/cft_sqrt + seeds vs the model, per-element flags" -- \
  PY "$ROOT/host/tests/divsqrt_check.py"

need host-cc python
stage clause5 "the clause-5 completion set vs the model, all entry points" -- \
  PY "$ROOT/host/tests/clause5_check.py"

# The clause-5.12 character conversions and the clause-9.7 payload
# operations. The fp256 leg is the slow one and honestly so: the exact
# decimal of a value at either end of that format's exponent range runs
# to tens of thousands of digits and the library derives every one of
# them (cft.h carries the cost note), so the sweep spends most of its
# time on a handful of deliberate extremes rather than on the bulk.
need host-cc python
stage character "the clause-5.12 conversions and the 9.7 payloads vs the model, both directions and the Pmin round trip" -- \
  PY "$ROOT/host/tests/character_check.py"

# The transcendentals, twice. The first run is at the contract's
# own working precision, where the Ziv loop seldom escalates: 805
# times over the whole run with the error count that has no ceiling,
# and 84 with the count as it was before, saturating at 2^40 (both
# counted by the lead on amd-arc-box on 2026-09-30 - the 805 in S4's
# timed run of the sweep, the 84 in an instrumented library); the
# second forces the library to
# START below the precision it needs, so the escalation path runs at
# scale - against an UNESCALATED model, which is what makes it a
# comparison rather than a coincidence. That second run is what found the
# exact-cancellation hole in the evaluator's error bound, twice: once
# in phase 1 and once on 2026-09-03, when the first repair turned out
# to be unsound at any working precision above 41 bits.
do_transcend() {
  PY "$ROOT/host/tests/transcend_check.py" || return 1
  PY "$ROOT/host/tests/transcend_check.py" --min-prec 64 --trials 16
}
need host-cc python
stage transcend "the thirty-nine transcendentals vs the model, and again through the escalation path" -- \
  do_transcend

# The augmented arithmetic operations of 754-2019 9.5. Their own stage
# rather than a line inside clause5, because what they check is
# different in kind: TWO outputs per element, a rounding that is not
# one of the five attributes, and the pair identity r + e == x op y,
# which the harness verifies in exact integers on the LIBRARY's output.
need host-cc python
stage augmented "the clause-9.5 augmented operations vs the model: both outputs, flags, and the exact pair identity" -- \
  PY "$ROOT/host/tests/augmented_check.py"

# ABI 0.7 package B: the sticky status word (7.1, 5.7.4), the three
# conformance predicates (5.7.1), and clause 9.6's four magnitude forms
# of minimum and maximum. Its own stage rather than a line inside
# clause5, because half of what it checks is not arithmetic at all: the
# status word is STATE, the golden model has nothing corresponding to
# it, and every assertion about it is against a sentence of 7.1 or
# 5.7.4 rather than against a computed value. The 9.6 half is scored
# the way clause5 is - the model defines every bit, the C is replayed
# against it - over seeded pools at all four formats, including every
# equal-magnitude pair, which is the family 9.6 defers to the base
# operation on and the one an implementation gets wrong.
need host-cc python
stage status96 "the 7.1/5.7.4 status word, the 5.7.1 predicates, and clause 9.6's four magnitude forms vs the model" -- \
  PY "$ROOT/host/tests/minmax_mag_check.py"

# The formatOf arithmetic of 754-2019 5.4.1. Its own stage rather than a
# line inside clause5, because what it checks is different in kind: TWO
# formats per call, sixteen ordered pairs, and the one family whose
# every exception belongs to a format the operands are not in. It also
# carries the eighteen double-rounding witnesses - the cases that
# separate this implementation from the plausible one that rounds in the
# source format and converts down - and asserts BOTH halves of each, so
# a witness that stopped separating the two fails the stage rather than
# quietly passing it.
need host-cc python
stage formatof "the clause-5.4.1 formatOf arithmetic vs the model: every ordered pair, the destination's exceptions, and the double-rounding witnesses" -- \
  PY "$ROOT/host/tests/formatof_check.py"

need host-cc python
stage diff "library vs model over the alignment boundary" -- \
  PY "$ROOT/host/tests/diff_check.py" --trials 3000

need host-cc python
stage seq "the sequencer: C vs model over fuzzed programs, plain and with indexed constants and IMUL" -- \
  PY "$ROOT/host/tests/seq_check.py" --trials 250 \
     --formats fp32 fp64 fp128 fp256

# The program library (programs/, docs/PROGRAMS.md): every .cfta assembled
# by cft-asm and by python/cft_golden/asm.py and held to the committed
# MANIFEST, both disassemblers and the re-assembly round trip, the
# generated revision-2 and revision-3 corpora, and each row's own check -
# the three ODE rows' 300-digit arm among them, the one part that needs
# mpmath (below). It is host/Makefile's asmtest, which is programs/check.py; the
# Collatz row's check reads cft-collatz's own records, so that tool is
# built first. Until 2026-09-25 this ran only by hand (`make
# programs-check`, docs/VERIFICATION.md said so): a library row whose
# check no stage runs was not gated.
#
# Then the segment runner's differential gate (host/Makefile's
# segruntest, host/tests/segrun_check.py; docs/CERTIFICATES.md, "The
# segment runner"): cft-segrun certifies the three ODE rows at fp64 and
# fp256 - with a half-step run, and a wider fp128 run beside each fp64 row
# - and a small program whose segments raise several flags and a STATUS,
# keyed and open; the golden writer, handed each certificate's identity
# lines, the salt and the initial states, runs every segment itself and
# must write the same bytes, and the golden audit must accept each, in
# full and sampled. Since version 2's C half (2026-10-02) cft-segrun
# writes certificate version 2 by default: those sections ask for version
# 1 (--format-version 1), and its section 14 (host/tests/segrun_check_v2.py)
# holds version 2 byte for byte to the golden writer - the per-lane
# blocks, a marked lane replayed, a source and its manifest, a
# wider-source run, every header line and every refusal by name. A stage
# of its own would have moved the runner's stage count, which CLAUDE.md
# states; the gate is about the library's programs, so it lives here. -k,
# so a failing asmtest still lets the certificate gate report.
#
# Then the golden certificates (host/Makefile's corpustest,
# certificates/corpus.py; docs/CERTIFICATES.md, "Golden certificates"):
# a committed corpus of twelve programs and their certificates, each made
# again by the golden writer and by cft-segrun and held to its committed
# bytes, and audited. segruntest holds the two writers to each other, so
# a change that moves both at once passes it; this one does not. It
# joined this stage beside segruntest by the lead's decision (2026-09-29),
# about 25 s of it on the desktop. Since 2026-10-02 it holds certificate
# format version 2's cases too, made again by the golden writer and,
# since version 2's C half, the seven a C writer makes by cft-segrun as
# well, and thirty controls each refused by its name.
do_programs() {
  HOSTMAKE -k collatz asmtest segruntest corpustest PYTHON="$PYBIN"
}
# Not mpmath: programs/check.py needs it only for the ODE rows' 300-digit
# arm, which it skips by name - an inner skip this runner counts on the
# VERDICT line and --require-all fails. Requiring it here skipped every
# other check with it, the stdlib-only textbook arm included
# (verifier-V3, 2026-09-25).
need host-cc python
stage programs "the program library: both assemblers against the MANIFEST, the readback, the generated corpora, and every row's own check; then cft-segrun's certificates of the ODE rows, byte for byte the golden writer's, audited; then the golden certificates, both writers held to committed bytes" -- do_programs

# The language's compiler held to the language (python/cftc; the
# language is docs/LANGUAGE.md; programs/lang_check.py's docstring names
# the legs, and its GROUPS which stage runs which). Every image the
# compiler writes runs on seq.py against the language's reference
# interpreter, lang.run, bit for bit with FLAGS, on many lanes at 1, 2,
# 5 and the image's own steps - a wrong semantics can hide on one lane at
# the final step: the three references at four formats and five
# attributes, nine written shapes and a seeded generated corpus at every
# format; the references beside gen_odes.py's images and classic banks,
# their costs pinned; the halved bank, the params, resume. Then
# cft-segrun certifies each compiled reference - Kepler's, whose image
# holds routines (parcel C4), among them - with a half-step run and a
# step-halving estimate, and the golden audit and cft-audit accept each
# in full and sampled; both C tools refuse a version-1 wider run of a
# routine image, `aux-image`; two processes under two PYTHONHASHSEEDs
# write the bytes programs/systems/compiled/ holds, and cftc's output
# version is the record's last (programs/systems/cftc-outputs.txt);
# every refusal by name, the routines' `target-feature` on revision 7's
# targets and `bank-capacity` among them; plants in a copy of the
# package - five of the lowering's, four of the routines' and three of
# the call loop's - each stopped by the compiler's internal check and
# red on seq.py with it off; every source the language accepts reads
# back; and the core tally. A source that divides or takes a root at
# run time compiles since C4 - L4's interim `runtime-routine` went with
# it - and the routines' own legs are the next stage's. In the quick
# budget (L2, 2026-10-01; the lead's rule, quick at about three minutes
# or less): since the split below (2026-10-02) its legs take about two
# and a half minutes run directly on a quiet desktop (149 s of the 296 s
# every leg took at 370e0b2, the desktop 3 to 5% busy), and took 969 s
# through the runner there with a game in the foreground; until the
# split the stage ran every leg, 276 s through the runner on amd-arc-box
# at 370e0b2 and 129 s at 7ccc441.
do_lang() {
  HOSTMAKE "cft-segrun$EXE" "cft-audit$EXE" || return 1
  PY "$ROOT/programs/lang_check.py" --group core \
     --segrun "$ROOT/host/cft-segrun$EXE" --audit "$ROOT/host/cft-audit$EXE"
}
need host-cc python
stage lang "the language's compiler held to its interpreter: every image on seq.py against lang.run bit for bit with FLAGS at several step counts (the references at four formats and five attributes, written shapes and a generated corpus at every format, the references beside gen_odes.py's images and classic banks), certified through cft-segrun and accepted by both auditors, a routine image's wider run refused by both C tools, deterministic, its output version recorded, every refusal by name, its plants red, every accepted source read back, its tally" -- do_lang

# The language's run-time division and square root in the compiler
# (parcel C4; programs/lang_check.py's routines group: legs K, K2, L and
# the tally I2). Every flag of both through the interpreter at every
# format; Kepler's reference at every format and under every attribute,
# its costs pinned; generated sources that divide or take a root - in
# equations and lets, with and without tangent vectors, under every
# integrator, format and attribute - compiled for the software targets,
# one image for sw, sw:4096 and sw:32768, and run on seq.py against
# lang.run at 1, 2 and 5 steps, states, tangents and FLAGS, each refused
# `target-feature` on revision 7's targets and through the command line,
# exit 3; the 40 routines (cft_golden/routines.py: two operations, four
# formats, five attributes) run as programs against softfloat on their
# full pools, bits and each lane's flag word; and the call loop - eight
# bodies under rk4, which the compiler's constant of 32,768 instructions
# loops, and Kepler under rk4 with the constant lowered, every batch
# looped and the largest alone, the image with every batch looped
# certified through cft-segrun and accepted by both auditors. Its tally:
# div and sqrt at every format, attribute and integrator, the five
# flags, loops of both. In the gate budget, not quick (the lead's split,
# 2026-10-02: these legs took `lang` to 276 s through the runner on
# amd-arc-box, past quick's three minutes): about two and a half minutes
# run directly on a quiet desktop (147 s of the 296 s at 370e0b2 - leg K
# 104 s, K2 14 s, L 29 s), and 669 s through the runner there with a
# game in the foreground.
do_lang_routines() {
  HOSTMAKE "cft-segrun$EXE" "cft-audit$EXE" || return 1
  PY "$ROOT/programs/lang_check.py" --group routines \
     --segrun "$ROOT/host/cft-segrun$EXE" --audit "$ROOT/host/cft-audit$EXE"
}
need host-cc python
stage lang-routines "the language's run-time division and square root, compiled as routines: every flag of both through the interpreter; Kepler and generated sources that divide or take a root, at every format, attribute and integrator, on seq.py against lang.run bit for bit with FLAGS and tangents, refused by name on revision 7's targets; the 40 routines against softfloat on their full pools; the call loop past 32,768 instructions, held, certified and audited; its tally" -- do_lang_routines

# The language's variational equations held (docs/LANGUAGE.md, "The
# variational equations"; programs/tangent_check.py's docstring names the
# legs). A system that declares `tangent v` carries its step's derivative
# along tangent vectors; every image the compiler writes for one runs on
# seq.py against lang.run bit for bit with FLAGS, states and tangents, at
# 1, 2, 5 and its own steps - the references with tangents at four
# formats, five attributes and two vectors, written shapes and a
# generated corpus at every format, on lanes whose tangents hold a
# signalling NaN, -0, a subnormal and the largest finite - with the
# primal unchanged by its tangent; the tangent sections equal to the
# stage's own exact dual numbers. Lorenz-63's largest Lyapunov exponent
# from the compiled reference through cft-segrun, renormalised on the
# host by exact powers of two (8 lanes to t = 1,000 at fp64, within 0.01
# of 0.9056), the renormalisation shown exact; the exponent again at
# fp256 from one certified chain both auditors accept (4 lanes to
# t = 1,000, within 0.02); each compiled variational reference certified
# and accepted by both auditors; the bytes programs/systems/compiled-
# tangent/ holds, and the `lang` stage's 64 still; refusals by name;
# wrong derivations red on the derivative and the exponent, a rule
# rounded otherwise red on the committed bytes, and four compiler plants
# red on seq.py; since L4 (2026-10-02), the quotient's and the root's
# rules, exactly and by a central difference, with plants - golden-only
# until C4, and since then compiled, their routines inlined, on seq.py
# against lang.run, and refused `target-feature` on revision 7's targets.
# In the gate budget: 196 s run directly and 346 s
# through the runner on the desktop, niced and in use, and past 13
# minutes, unfinished, beside another process holding it at 100% (L3,
# 2026-10-01).
do_tangent() {
  HOSTMAKE "cft-segrun$EXE" "cft-audit$EXE" || return 1
  PY "$ROOT/programs/tangent_check.py" --segrun "$ROOT/host/cft-segrun$EXE" \
     --audit "$ROOT/host/cft-audit$EXE"
}
need host-cc python
stage tangent "the language's variational equations: every image with tangent vectors on seq.py against lang.run bit for bit with FLAGS, states and tangents (references, written shapes and a generated corpus at every format), the primal unchanged, the tangent equal to exact dual numbers; Lorenz-63's largest Lyapunov exponent through cft-segrun, and at fp256 from a certified chain both auditors accept; the compiled references certified, deterministic, committed; refusals by name, its plants red" -- do_tangent

# The acceptance set (programs/acceptance.py, whose docstring is the
# definition; the step-6 round's parcel A1, 2026-10-02): everything that
# runs on the card today, each entry one run fixed in the repository - the
# six compiled references and the four variational ones as committed, and
# the ten hard workloads that fit u50-rev7-quad (programs/workloads/),
# compiled here and held byte for byte to committed digests - on lanes
# filling one block a tile of the quad, through cft-segrun on libcft's
# software backend at the card's scratch depth, 2,048 slots a lane. Every
# boundary's state hash and every segment's flags and STATUS must be
# programs/acceptance.json's; cft-audit must accept each certificate in
# full; the golden audit re-runs a segment of the six entries where seq.py
# takes ten seconds or less for one, cft-audit handed the same choice
# printing its verdict line for line; a golden spot check re-runs every
# entry's last segment on seq.py for a few lanes; and its controls plant a
# digest, a flag word, a parameter and a flipped bit, each caught. Then the
# hard workloads' own oracle, the pack's one-step vectors from the other
# model's exact evaluator: lang.run on all 21 programs, and the ten card
# images on seq.py. With --device <xclbin> the same driver is the
# admission test for a card. In the gate budget (the lead's choice,
# 2026-10-02): 375 s on the desktop, the driver run directly, niced, with
# the desktop in use - the set 314 s, about 240 s of it compiling the ten
# workloads, and the oracle 61 s; its run through the runner is the
# lead's.
do_acceptance() {
  HOSTMAKE "cft-segrun$EXE" "cft-audit$EXE" || return 1
  PY "$ROOT/programs/acceptance.py" --legs set,oracle \
     --segrun "$ROOT/host/cft-segrun$EXE" --audit "$ROOT/host/cft-audit$EXE"
}
need host-cc python
stage acceptance "the acceptance set, a device's admission test, on libcft's software backend: the compiled references, the variational ones and the ten hard workloads that fit the card, each one fixed run held to committed boundary hashes, flags and STATUS, cft-audit in full, the golden audit where it fits and a golden spot check on every entry, its controls caught; the hard workloads' own one-step vectors against lang.run on all 21 and the ten card images on seq.py" -- do_acceptance

# `acceptance-far`, in no budget, so only the full census runs it (the
# lead's choice, 2026-10-02): the hard workloads' own oracle on the four
# hard and wide programs past the card, Gray-Scott and Lorenz-tangent -
# their images compiled for sw:32768 and run on seq.py against the pack's
# one-step vectors, which the pack's own runner already verified on
# amd-arc-box. Python alone: about ten minutes on the desktop, nearly all
# compiling - two of the four, Gray-Scott and Lorenz-tangent wide, took
# 289 s together, niced (2026-10-02).
need python
stage acceptance-far "the hard workloads' own oracle on the four images past the card, Gray-Scott and Lorenz-tangent hard and wide: compiled for sw:32768, each on seq.py equal to the pack's one-step vector, states, FLAGS and each lane's FLAGS" -- \
  PY "$ROOT/programs/acceptance.py" --legs far

# The C auditor held to the golden one (host/Makefile's audittest,
# host/tests/audit_check.py; docs/CERTIFICATES.md, "The audit tool"):
# cft-audit and cert.audit are handed the same inputs and must give the
# same verdict - a refusal's name, exit code and location, or both
# ACCEPTED with the same lines. The inputs: every parse call test_cert.py
# and test_cert2.py make, and every audit call whose arguments files and
# options can carry, shadowed in-process (so pytest; the rest are counted
# and named), a version-2 call held to the golden auditor handed no
# source and not asked to regenerate, since cft-audit takes neither
# (version 2's C half, parcel CV2CA, 2026-10-02); cft-segrun's
# certificates of segrun_check's programs, in full, from the initial
# states and sampled; the golden corpus, version 2's cases and controls
# among it, the same way; two narrow builds of libcft and the tool at
# CFT_MAX_FORMAT=2, at its own bigint and at CFT_BN_LIMBS=64, which must
# refuse build-width and build-format and audit the rest in full; the
# tool's numerics; and its Ed25519 and SHA-512 against every vector
# test_ed25519.py carries and SHA-512's published examples, through a
# probe build - so a C compiler. Section 1 holds cft.h's CFT_PROFILE_*
# and CFT_LANGUAGE_* to profile.py and lang/version.py. A stage of its
# own in the gate budget (the lead, 2026-09-29): about four minutes on
# the desktop until version 2's C half, about seven since (test_cert2.py's
# shadow its most), too long for quick, where programs keeps both
# writers' checks.
do_audit() {
  HOSTMAKE audittest PYTHON="$PYBIN"
}
need host-cc python pytest
stage audit "the C auditor held to the golden one: test_cert.py's and test_cert2.py's parse calls and every audit call files can carry (version 2's without the source), cft-segrun's certificates and the golden corpus through both, the same refusal by name, code and location or the same verdict; two narrow builds refusing build-width and build-format; its numerics, Ed25519 and SHA-512 against their vectors; cft.h's profile and language macros against the golden model's" -- do_audit

# A certificate's two estimates, scored (docs/studies/ACC-A-estimates.md,
# programs/estimates.py). Each runs --against the committed runs in
# docs/studies/acc-a/: every section the script prints is held line for
# line to the committed section with the same first line, `time` lines
# apart, and the first difference fails the stage naming the file, the
# section and the committed line, with both lines. Every committed section
# of the cases it was ASKED for (every case, without --cases) must have
# been printed, and every case --cases names must have been scored. Until
# 35ec784 it asked only for the cases the run had loaded, so a run that
# dropped one, or all, passed (verifier-W2's P3a, P3b).
#
# `estimates`, in the gate budget (the lead, 2026-09-30): lorenz63-rk4-fp64
# and lorenz96-rk4-fp64, every lane. That covers the step-halving estimate
# against the converged reference (check.py's 300-digit arm with the bank's
# h-slots halved until two levels agree to 1e-6 of the method error), the
# wider estimate against the arm itself, odefun's cross-check and the time
# shift. 50 and 51 s on the desktop, two clean runs through this runner at
# cc4f6c4 (verifier-W2's, the author's). The certified states are the corpus's
# committed files, so it runs no C: python and mpmath only. mpmath 1.3.0
# (gmpy) and 1.4.1 (pure Python) print the same sections (measured
# 2026-09-30).
need python mpmath
stage estimates "a certificate's two estimates scored, lorenz63 and lorenz96 at fp64, every lane: step-halving against a converged reference, wider against the 300-digit arm, held line for line to the committed run (docs/studies/ACC-A-estimates.md)" -- \
  PY "$ROOT/programs/estimates.py" certified \
     --cases lorenz63-rk4-fp64,lorenz96-rk4-fp64 \
     --against "$ROOT/docs/studies/acc-a/certified.out.txt"

# `estimates-full`, in no budget, so only the full census runs it (the lead,
# 2026-09-30): the study made again whole. Every ODE case of the corpus is
# scored, and the sweep runs: lane 0 of each system as h shrinks, each
# level a certificate that cft-segrun, built here first, makes and the
# golden audit samples. Both are held to their committed runs. 9 to 14
# minutes on the desktop: the committed runs' halves took 355 s and 206 s,
# and verifier-W2's the same day 441 s and 406 s, the desktop 5% busy just
# before the first of those and 1% before the second.
do_estimates_full() {
  HOSTMAKE "cft-segrun$EXE" || return 1
  PY "$ROOT/programs/estimates.py" all --tool "$ROOT/host/cft-segrun$EXE" \
     --against "$ROOT/docs/studies/acc-a/certified.out.txt" \
     --against "$ROOT/docs/studies/acc-a/sweep.out.txt"
}
need host-cc python mpmath
stage estimates-full "docs/studies/ACC-A-estimates.md made again whole: every ODE case of the corpus scored, and the sweep's cft-segrun certificates made and audited again, held line for line to both committed runs" -- do_estimates_full

# reduce_check.py holds the model's partition tree to the C partitioner
# through host/reduce-parts, and SKIPs that half by name when the binary
# is absent. `make test` (the libcft stage) builds it; the quick budget's
# `make all` does not, and nothing else here did - so both quick runs of
# 2026-09-15 passed `reduce` with the cross-check skipped (their
# reduce.log), and where a binary was left over it was one linked against
# whatever libcft.a existed then. Built here, as selfcheck builds
# device-test, so the cross-check runs against this tree's library.
do_reduce() {
  HOSTMAKE "reduce-parts$EXE" || return 1
  PY "$ROOT/host/tests/reduce_check.py" --trials 1500
}
need host-cc python
stage reduce "all seven clause-9.4 reductions: C vs model, the tree, the two composition identities, the scaled products' invariant" -- \
  do_reduce

# The one stage whose expected bits this project did not compute. Every
# stage above holds the C to the golden model, and the model is ours; a
# defect shared by both would pass them all. This one holds the library
# to an NVIDIA GPU: atlas-engine's deterministic camera around a plate,
# lowered to a sequencer program, four passes of 1,048,576 samples, and
# the SHA-256 of each pass's deposit buffer as the GPU recorded it while
# rendering the same frame from pinned GLSL (host/tests/photograph/hopf,
# and its README). The passes run side by side - about a minute and a
# half on a desktop, which is what keeps it in the quick budget. With
# the library's multiply forced to round toward zero all four passes
# differ, and a fixture with one bit flipped is named as a damaged
# fixture and nothing is run (docs/VALIDATION.md, 2026-09-18).
do_photograph() {
  HOSTMAKE "positive-run$EXE" || return 1
  PY "$ROOT/host/tests/photograph_check.py"
}
need host-cc python
stage photograph "a GPU's record of a real workload, bit for bit: atlas-engine's hopf photograph, four passes of 1,048,576 samples, each deposit buffer held to the SHA-256 an NVIDIA GPU wrote" -- do_photograph

# The MPFR-compatible Python binding, which is a different claim from
# the MPFR ORACLE below. do_mpfr asks whether libcft's arithmetic agrees
# with GNU MPFR; this asks whether the drop-in that advertises that
# agreement actually delivers it - the context/precision/rounding
# plumbing, the batch path against the scalar path, the flag words, and
# the refusals. A binding can be wrong in every one of those while the
# arithmetic under it is perfect.
#
# gmpy2 is optional by the test's own design: without it the interop
# comparisons skip and the refusal and batch-vs-scalar checks still run.
# So this stage is useful on a bare box and sharper on one with gmpy2 -
# and -rs names what the bare box skipped, as inner skips.
do_bindings() {
  HOSTMAKE "$SHLIB_NAME" >/dev/null 2>&1 || HOSTMAKE all >/dev/null 2>&1 || true
  CFT_LIB="$ROOT/host/$SHLIB_NAME" PY -m pytest -q -rs --color=no \
    "$ROOT/bindings/python/test_cftmpfr.py"
}
need host-cc python pytest
stage bindings "the cftmpfr drop-in vs gmpy2's IEEE emulation: encodings, flags, refusals" \
  -- do_bindings

# ---- the other languages -------------------------------------------
# One stage per language, so the report names each one and a push that
# breaks a binding fails by name: the C++ layer's own test, then every
# example in the checksum diff against the C example (host/examples,
# docs/COMPATIBILITY.md), then the two JavaScript surfaces. A toolchain
# that is absent SKIPs by name; one that is present and prints
# different bits FAILs, which is the point of the diff.
#
# The vectors: cpptest, the Node binding and the wasm page all replay
# vectors/out, through ensure_vectors - defined above do_libcft, the
# first stage that replays them.

do_cpp() { ensure_vectors && HOSTMAKE cpptest; }
need host-cc cxx
stage cpp "cft.hpp vs cft.h at C++17 and C++20: every entry point, same bits and flags" -- do_cpp

need host-cc cxx
stage lang-cpp "C++ example vs the C example: same bits" -- HOSTMAKE lang-cpp

need host-cc rustc
stage lang-rust "Rust example vs the C example: same bits" -- HOSTMAKE lang-rust

need host-cc julia
stage lang-julia "Julia example vs the C example: same bits" -- HOSTMAKE lang-julia

need host-cc go
stage lang-go "Go example vs the C example: same bits" -- HOSTMAKE lang-go

need host-cc dotnet
stage lang-csharp "C# example vs the C example: same bits" -- HOSTMAKE lang-csharp

need host-cc Rscript
stage lang-r "R example vs the C example: same bits" -- HOSTMAKE lang-r

need host-cc gfortran
stage lang-fortran "Fortran example builds and runs through iso_c_binding (prints no checksum line)" -- HOSTMAKE fortran

do_node() {
  ensure_vectors || return 1
  (cd "$ROOT/bindings/node" && node test.mjs && node program_test.mjs \
     && node conformance.mjs "$ROOT/vectors/out")
}
need node
stage node "Node binding: unit tests and program_test.mjs, then the vectors through cft_node.wasm" -- do_node

do_wasm() {
  ensure_vectors || return 1
  node "$ROOT/bindings/wasm/verify.mjs" "$ROOT/vectors/out"
}
need node
stage wasm "the committed conformance page, verified without a browser" -- do_wasm

# The five workloads written for the contract (docs/BENCHMARKS.md,
# "Workloads designed for the contract"): each tool against its oracle
# - Python big integers, exact rationals, or mpmath at 300 digits - and
# against its own determinism claims: batch-size independence,
# interrupt/resume equivalence, program-versus-loop bit identity. They
# are make targets in host/, handed the interpreter PY() picked because
# three of the five import mpmath; together they take about a minute.
do_workloads() {
  HOSTMAKE collatz enclose mersenne orbits zoom || return 1
  HOSTMAKE collatztest enclosetest mersennetest orbitstest zoomtest PYTHON="$PYBIN"
}
need host-cc python mpmath
stage workloads "the five contract workloads vs their oracles - Collatz, enclose, Mersenne, orbits, zoom - and their own determinism properties" -- do_workloads

# The browser demos' compute core, driven under node at each panel's
# default configuration, against the chains the C tools produce for the
# same configurations (docs/DEMOS.md). Needs the tools built, and node.
do_demos() {
  HOSTMAKE collatz enclose mersenne orbits zoom || return 1
  node "$ROOT/bindings/wasm/verify_demos.mjs"
}
need host-cc node
stage demos "the browser demos' compute core reproduces the C tools' chains, without a browser" -- do_demos

do_mpfr() {
  # A repo-local prefix (verify/build-mpfr-oracle.sh) outranks system
  # packages: it is version-pinned, SHA-verified, and static, so the
  # oracle is the same everywhere it runs.
  local pfx="$ROOT/verify/_mpfr-prefix"
  if [ -f "$pfx/include/mpfr.h" ]; then
    HOSTMAKE "mpfr-check$EXE" "mp-err-check$EXE" \
      CFLAGS="-O2 -I$pfx/include" LDLIBS="-L$pfx/lib" || return 1
  else
    HOSTMAKE "mpfr-check$EXE" "mp-err-check$EXE" || return 1
  fi
  (cd "$ROOT/host" && "./mpfr-check$EXE" 24 7) || return 1
  # The evaluator's error claims held exactly (host/tests/mp_err_check.c):
  # mpfloat.c's rules in GMP, W = 6 exhaustively and a fixed-seed
  # sample; then, against MPFR, the constants' count and transcend.c's
  # logarithm conversion, through a probe build of transcend.c that
  # only that tool compiles. About half a minute on the desktop; its
  # controls must fail. It needs GMP and MPFR, which the probe that
  # skips this stage already asks for - mpfr.h includes gmp.h, and the
  # pinned prefix installs both.
  (cd "$ROOT/host" && "./mp-err-check$EXE")
}

do_soakquick() {
  # Pre-build via HOSTMAKE so run-soak.sh's own plain `make` finds the
  # binary fresh and never compiles - which is what lets the script
  # stay platform-naive while this runner carries the Windows quirks.
  HOSTMAKE "divsqrt-soak$EXE" || return 1
  QUICK=1 OUT="$RUNDIR/soak-quick-out" bash "$ROOT/hw/run-soak.sh"
}
need host-cc mpfr
stage mpfr "MPFR parity, all rungs and modes, flags - the only external oracle reaching fp128/fp256, and the only one at all for the thirty-nine transcendentals; then the evaluator's error claims, exactly, in GMP and MPFR" -- do_mpfr

need host-cc
stage soak-quick "native-oracle soak, QUICK depth + sabotage control" -- do_soakquick

do_images() {
  local rc=0 img
  for img in $IMAGES; do        # word-split intended; no spaces in paths
    echo "==== $img"
    bash "$ROOT/hw/verify-image.sh" "$img" || rc=1
  done
  return $rc
}
need xclbinutil images-env
stage images "hw/verify-image.sh over IMAGES against their manifests (XRT hosts, if staged)" -- do_images

# ---- the remote backend (docs/REMOTE.md) ------------------------------
# The tile behind a socket, held to the contract on loopback. The stage
# builds the server and the client tools and hands the server's
# LIFECYCLE to host/tests/remote_check.py, which starts cft-serve on a
# free loopback port as its own child, records the PID here beside the
# run's logs ($RUNDIR/remote-server.pid), drives every check through
# it - the protocol refusals, device-test's full matrix against the
# software backend, a bounded conformance replay local and remote, one
# Collatz chain both ways, the round-trip counts on both div/sqrt
# routes - and then terminates THAT PID. Never an image name: this is
# a shared host, and a kill keyed on a name has destroyed other
# people's work here before. mpmath because the bounded vector set is
# generated from the model, transcendentals included.
do_remote() {
  HOSTMAKE "cft-serve$EXE" "remote-test$EXE" "device-test$EXE" \
           "cft-selftest$EXE" "cft-collatz$EXE" || return 1
  REMOTE_PIDFILE="$RUNDIR/remote-server.pid" \
    PY "$ROOT/host/tests/remote_check.py" || return 1
  # The WebSocket transport (2026-09-07), held to the same contract from
  # JavaScript: bindings/node/remote_test.mjs starts its own server on a
  # free loopback port, replays a vector subset over WebSocket and over
  # TCP, compares both with the local wasm module and the published
  # answers, and runs the negative controls. Node 22 carries a WebSocket
  # client of its own; without node the leg is an inner skip, named on
  # the stage's row and counted, not failed. The leg replays vectors/out,
  # so an --only run generates it first, as the other replays do.
  if command -v node >/dev/null 2>&1; then
    ensure_vectors && HOSTMAKE wstest
  else
    echo "SKIP  remote's WebSocket leg (make -C host wstest): no node on PATH"
  fi
}
need host-cc python mpmath
stage remote "the remote backend on loopback: cft-serve started and stopped by PID, remote held against software - refusals, device-test, a bounded replay, one workload chain, the round-trip counts; then the same contract over WebSocket from node" -- do_remote

# ---- report --------------------------------------------------------
{
  echo "cft-fp256 verification run $RUNID"
  echo "commit:  $COMMIT$([ -n "$DIRTY" ] && echo '  (TREE DIRTY - this run certifies nothing)')"
  echo "host:    $HOSTNM ($(uname -s))"
  echo "date:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "flags:   skip=[${SKIP#,}] only=[${ONLY#,}] require-all=$REQUIRE_ALL"
  echo
  printf '%s\n' "${ROWS[@]}"
  echo
  # The inner skips, named by stage, on the verdict line itself: a
  # verdict that says "nothing skipped" over a skipped check is the
  # defect this line exists to prevent.
  inner_list=""; inner_txt=""
  if [ "$INNER" -gt 0 ]; then
    for s in "${INNER_BY[@]}"; do inner_list="$inner_list${inner_list:+, }$s"; done
    inner_txt="$INNER inner skip(s) in $inner_list"
  fi
  if [ "$FAILED" -gt 0 ]; then
    if [ -n "$inner_txt" ] && [ "$REQUIRE_ALL" = 1 ]; then
      echo "VERDICT: FAIL ($FAILED stage(s), including under --require-all $inner_txt)"
    else
      echo "VERDICT: FAIL ($FAILED stage(s))${inner_txt:+ - also $inner_txt}"
    fi
  elif [ "$SKIPPED" -gt 0 ] || [ -n "$inner_txt" ]; then
    what=""
    [ "$SKIPPED" -gt 0 ] && what="$SKIPPED skip(s)"
    [ -n "$inner_txt" ] && what="$what${what:+ and }$inner_txt"
    echo "VERDICT: PASS with $what - see reasons above"
  else
    echo "VERDICT: PASS, nothing skipped"
  fi
  echo
  echo "-- census block (paste into docs/VALIDATION.md) --------------"
  echo "## $(date +%Y-%m-%d) - standardized verification run ($HOSTNM)"
  echo
  echo "verify/run.sh at $COMMIT: $RAN stage(s) executed," \
       "$CACHED cached from earlier in the run, $FAILED failed," \
       "$SKIPPED skipped, $INNER inner skip(s)${inner_list:+ ($inner_list)}."
  if [ "$INNER" -gt 0 ]; then
    echo "Inner skips - checks inside a stage that passed, which did not run:"
    for s in "${INNER_LINES[@]}"; do echo "    $s"; done
  fi
  echo "Run id $RUNID; per-stage logs under verify/state/."
} | tee "$SUMMARY"

[ "$FAILED" -gt 0 ] && exit 1
exit 0
