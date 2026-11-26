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
#                                      # equations (tangent), the acceptance set and,
#                                      # on a host with a GPU and hipcc, the GPU
#                                      # backend and its fixed tier (hip and
#                                      # hip-tier; skipped by name elsewhere)
#   bash verify/run.sh --budget full    # everything: the census (adds sim, simmc,
#                                      # node, wasm, images, estimates-full,
#                                      # acceptance-far, acceptance-rev8, and
#                                      # the GPU backend's two other NVIDIA
#                                      # builds, hip-nvcc and hip-source)
#   HIP_ROOT=/opt/rocm-7.2.4 HIP_PLATFORM=nvidia HIP_DEVICE=1 bash verify/run.sh --only hip
#                                      # the GPU backend on the second GPU
#                                      # nvidia-smi lists, through HIP 7.2.4's
#                                      # NVIDIA layer (the stage's comment);
#                                      # HIP_FULL=1 adds its full-width tier
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
# the language's quick stage (lang-routines); and since 2026-11-12 the
# GPU backend (hip), which costs nothing where it is skipped by name - a
# host with no hipcc or no GPU, the box and CI among them - and where it
# runs about ten minutes with round 1's checks (564 s on an RTX 5060 Ti
# under WSL with the desktop loaded, 2026-11-12), and 12 to 20 since
# round 2's joined them (738 s on that GPU and 1,189 s on an RX 7600,
# 2026-11-17); and since 2026-11-26 the GPU backend's fixed tier
# (hip-tier, round 3's gate), skipped by name where hip is. `full` is the
# census.
# Measured on the
# Windows desktop (docs/VERIFICATION.md has the table, quiet against
# loaded): quick ~20 min, gate ~2 h with the box quiet and ~4 h loaded
# when the formal gate held thirty proofs and a negative control
# (thirty-one tasks; thirty-eight and the control, thirty-nine tasks,
# since the instruction fetch's eight joined on 2026-10-03, which add
# about six minutes on the desktop), full longer by the simulation suite
# and the two browser replays; on the WSL distro the replay stages take
# seconds.
BUDGET_QUICK=docs,generated,buildargs,sweepjudge,innerskips,ensurevectors,selfcheck,divsqrt,clause5,character,augmented,status96,formatof,diff,seq,programs,lang,reduce,photograph,bindings,lang-cpp,lang-rust,lang-julia,lang-go,lang-csharp,lang-r,lang-fortran,workloads,demos,soak-quick,remote
BUDGET_GATE=golden,vectors,lint,formal,libcft,$BUDGET_QUICK,transcend,mpfr,cpp,audit,estimates,lang-routines,tangent,acceptance,cardstress,hip,hip-tier
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
    printf '%s %-16s%s\n' "$_mk" "$_nm" "$_ds"
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
# do_generated is the stage that does not log what its tools print: it
# runs eight --checks and prints "ok <tool>" for each that passed, and
# until 2026-10-20 that dropped the rest. A tool that passed and printed
# SKIP was invisible here, and on Windows `--require-all --only generated`
# said "PASS, nothing skipped" over the packager's one plant that cannot
# run there (verifier-VFX). do_generated now carries a passing tool's skip
# lines into its log (carry_skips, below) as SKIP lines that name the
# tool, so this scan counts them. The convention is unchanged: the tool
# prints the marker and the runner reads it; what is carried is what this
# scan would count, in whichever form the tool printed it.
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
# <tool> <what it printed> -> one SKIP line, naming the tool, for each line
# of it that inner_scan would count, with the tool's own marker replaced by
# ours (a SKIPPED [n] count is carried as one: no tool of do_generated's
# prints that form). The scan is inner_scan itself, so a line is a skip
# here exactly when it is one in a log. Always succeeds: grep finding
# nothing is the usual case, and do_generated runs under pipefail.
carry_skips() {
  inner_scan <(printf '%s\n' "$2") | sed -E "s|^(SKIP(PED)?[[:space:]:]*)?|  SKIP  $1 - |"
  return 0
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
      # The GPU backend's two (the `hip` stage, below): its compiler, and a
      # device its platform's own lister shows (hip_gpu_reason says which).
      hipcc) [ -x "${HIP_ROOT:-/opt/rocm}/bin/hipcc" ] \
        || STAGE_SKIP_REASON="no hipcc at ${HIP_ROOT:-/opt/rocm}/bin/hipcc (set HIP_ROOT; HIP_PLATFORM=nvidia for HIP 7.2.4's NVIDIA layer, HIP_ROOT=/opt/rocm-7.2.4)";;
      gpu) STAGE_SKIP_REASON=$(hip_gpu_reason);;
      # The full census's two other NVIDIA builds of it (`hip-nvcc`, `hip-source`).
      nvcc) [ -x "${HIP_CUDA:-/usr/local/cuda}/bin/nvcc" ] \
        || STAGE_SKIP_REASON="no nvcc at ${HIP_CUDA:-/usr/local/cuda}/bin/nvcc (HIP_CUDA)";;
      hipsrc) { [ -x "$(hipsrc_root)/bin/hipcc" ] && [ -d "$(hipsrc_root)/include/hip" ]; } \
        || STAGE_SKIP_REASON="no HIP built from source at $(hipsrc_root) (verify/build-hip-nvidia.sh builds it from pinned sources: a download of about 180 MB, the lead's word)";;
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
# Since 2026-10-22 (KL-196) it asks a fourth thing: was the directory made
# by this tree's model (vectors/out/MODEL, the generator's stamp: the
# digest of python/cft_golden/*.py and vectors/gen_vectors.py), because a
# whole directory of the old model's sets is replayed against a library
# that lacks a model change, and passes. Not whole in that sense is
# regenerated, like the rest.
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
  # Whole is not current (KL-196): a directory the generator finished holds
  # its own sets and passes the three tests above after the model it was
  # made by has changed, and a replay of it checks the library against the
  # old model. The generator stamps each directory with the digest of the
  # model's source it ran under (vectors/out/MODEL) and says whether that
  # is this tree's; the tracked vectors/SHA256SUMS cannot be the comparison,
  # which holds `make vectors`' counts where the runner generates at the
  # generator's own (KL-198).
  if ! out=$(PY "$ROOT/vectors/gen_vectors.py" --check-model "$d" 2>&1); then    # VECTORS-WHOLE-MODEL
    echo "$lbl is whole but was not made by this tree's model: $(printf '%s\n' "$out" | tail -n 1)"
    return 1
  fi
  echo "$lbl/SHA256SUMS names all $nwant sets vectors/SHA256SUMS names, and all $(grep -c . "$d/SHA256SUMS") it names hold; $(printf '%s\n' "$out" | tail -n 1)"
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
# python AND mpmath: every stage that can run the generator needs both - this
# one, and libcft, cpp, node and wasm through ensure_vectors (remote already
# did) - because the generator's transcendental sets are mpmath's, and a host
# without it fails in the generator, where a skip would name the cause (a
# generation that died that way left five sets on 2026-09-28). Until
# 2026-10-22 (KL-213) vectors and libcft named python alone, and cpp, node and
# wasm neither. verify/test-ensure-vectors.sh holds the list to the stages'
# own text.
need python mpmath
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
stage sim "cocotb RTL suite, all 29 targets, SIM_JOBS at a time (docker cft-sim)" -- do_sim

# The same benches with the multiplier iterated and the array paced
# (tb/Makefile simmc, MC=10 unless MC= says otherwise): the multi-cycle
# tile's own census, beside the shipping default rather than instead
# of it. Not in the quick or gate budgets - it is the third tier's
# gate. On 2026-09-29 it took 1 h 16 min at four jobs on amd-arc-box,
# where sim took 1 h 40 min at six (docs/VERIFICATION.md). Since
# 2026-10-05 it also runs seq_corestr_full, the sequencer's bench whole
# through the fetch at three read latencies, under Verilator: Icarus
# cannot finish it inside the target's timeout (tb/Makefile). Since
# 2026-10-22 (KL-472) it also runs seq_coreu50mc, the sequencer's bench at
# the U50's capacities with the multiplier iterated, about as long as
# seq_coreu50 under Icarus. CI runs no simmc, so that bench is held by this
# stage and by hand and by nothing else.
need docker
stage simmc "cocotb suite at the multi-cycle pass budget MC, the sequencer's bench at the U50's capacities with the multiplier iterated, and the sequencer's bench whole through the fetch under Verilator (docker cft-sim)" -- do_simmc

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
  echo "ensure_vectors: not reusable as it is, so it is regenerated - $msg"
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
need host-cc python mpmath
stage libcft "host library: build + contract tests + the build id regenerated + conformance replay + every build profile compiles" -- do_libcft

# Placed after `libcft` on purpose: make_seq_corpus.py's check loads
# libcft through ctypes, and that stage is what builds it. Sitting
# earlier (as this did when written) meant the corpus check took its
# skip path on any clean checkout - including CI, where it would then
# never have run the one check that had actually caught drift.
# Seven generators' committed files, each held to its generator, and an
# eighth that holds a packager to the tree it packages. Not
# every generated file in the tree: host/include/cft_seq_flags.h is held
# by `make seqflags` (python/gen_seq_flags.py --check) and
# rtl/cft_seed_rom.svh by the golden suite's test_seed_rom_sync.py.
# The seventh, python/project_figures.py (2026-10-19), holds the project's
# figures (docs/img/figures/), their sidecars and the gallery
# (docs/FIGURES.md) to the committed data they are drawn from. Its --check
# reads no git, network or card, plants its own faults first, and prints
# "STALE figure NAME: FILE differs from a fresh generation" on drift, which
# the pattern below recognises.
# The eighth, python/project_packager.py (2026-10-19), owns no committed
# file: it makes the dated status archive (docs/EXPORT.md) into an ignored
# directory. Its --check is that archive's self-test: can one still be made
# from this tree (the README, the gallery, the sidecars and the ledger
# still say what its readers expect), does one build, verify and reproduce
# byte for byte, and is each refusal and each archive fault named when
# planted in a scratch copy. It needs no converter, so it prints no SKIP line
# for that: the PNG legs (--check --png) need librsvg's rsvg-convert, which
# CI may not have, and are not part of this stage. It prints one SKIP line
# on Windows only, for the one plant that platform cannot run (an archive
# entry named with a backslash); a passing tool's SKIP lines are carried
# into this stage's log (carry_skips), so that one is an inner skip there
# and none on Linux. Its failure output never uses
# the words the pattern below looks for, so a failure is a FAIL and not a
# STALE: it has nothing to regenerate.
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
           python/gen_divfull.py bindings/arduino/sync.py \
           python/project_figures.py python/project_packager.py; do
    out=$(PY "$ROOT/$g" --check 2>&1); grc=$?
    if [ $grc -eq 0 ]; then
      printf '  ok    %s\n' "$g"
      carry_skips "$g" "$out"    # INNER-SKIP-CARRY
    elif printf '%s' "$out" | grep -qiE "stale|differs from a fresh|has drifted from host/"; then
      # the figures' generator writes only with --write; the others rewrite their files when run bare
      case "$g" in
        python/project_figures.py) fix="python $g --write" ;;
        *) fix="python $g" ;;
      esac
      printf '  STALE %s - regenerate with: %s\n' "$g" "$fix"
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
stage generated "the committed output of seven generators still matches a fresh generation, by each one's --check (the Arduino copy of host/ and the project's figures, sidecars and gallery among them), and the status archive's packager can still package the tree, by its own --check" -- do_generated

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
# flags, loops of both. Since M1's build, item 5 (2026-10-19) the stage
# holds the math library's six the same way: each alone at every format and
# attribute, generated sources that call them, and a call loop over a batch
# of them, run on seq.py against lang.run under the marked-lane rule
# (programs/lang_check.py: a lane whose byte carries the mark is replayed by
# the definition and its guess counted, every other lane bit for bit with
# its byte's flags, FLAGS and STATUS held to the bytes), the structured
# families' arguments in the lanes; the rule's own controls on a hand-written
# image that marks lanes; the six's part of the tally. Since M2's build,
# wave 4 (parcel M2SL, 2026-11-04) sin, cos and tan have legs of their own
# beside the six's: each alone (T1, with the families' centres, the
# minimisers' neighbours, the lanes past 2^1024 at fp128 and fp256, and a
# count of the one-call images' wrong guesses against the golden function),
# generated sources (T2), a call loop (T3) and a third part of the tally.
# Since M4's build, wave 5 (parcel M4SL, 2026-11-11) atan, asin, acos and
# atan2 have legs of their own the same way: each alone (U1, with the inverse
# family's centres, atan2's tiny-quotient range pairs at every format, the
# committed structured lanes of mathlib_inv_harness and the count of the
# one-call images' wrong guesses against the golden function), generated
# sources (U2), a call loop (U3) and a fourth part of the tally. Those legs
# skip by name without mpmath. In the gate budget, not quick (the lead's split,
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
stage lang-routines "the language's run-time division and square root, compiled as routines: every flag of both through the interpreter; Kepler and generated sources that divide or take a root, at every format, attribute and integrator, on seq.py against lang.run bit for bit with FLAGS and tangents, refused by name on revision 7's targets; the 40 routines against softfloat on their full pools; the call loop past 32,768 instructions, held, certified and audited; the math library's six, sin, cos and tan, and atan, asin, acos and atan2, compiled and run the same way, alone at every format and attribute and in generated sources and a call loop, with structured-family arguments, lanes past the range and atan2's tiny-quotient range in the lanes and every marked lane replayed by the definition (the alone legs of sin, cos and tan and of atan, asin, acos and atan2 also count the one-call images' wrong guesses against the golden function), and the marked-lane rule's own controls; its tally" -- do_lang_routines

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
# against lang.run, and refused `target-feature` on revision 7's targets;
# and since M1's build, item 5 (2026-10-19), the math library's six compiled
# with one tangent vector or two and run on seq.py against lang.run under the
# marked-lane rule that programs/lang_check.py states, a marked lane replayed
# whole, its states and its tangents the definition's (leg N); and since M2's
# build, wave 4 (parcel M2SL), sin, cos and tan compiled the same way (leg T),
# with lanes past 2^1024 at fp128 and fp256 whose guesses and tangents are
# wrong, and controls with a tangent vector; and since M4's build, wave 5
# (parcel M4SL), atan, asin, acos and atan2 compiled the same way (leg U), with
# the families' centres and atan2's tiny-quotient range pairs in the primal and
# controls with a tangent vector.
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
stage tangent "the language's variational equations: every image with tangent vectors on seq.py against lang.run bit for bit with FLAGS, states and tangents (references, written shapes and a generated corpus at every format), the primal unchanged, the tangent equal to exact dual numbers; Lorenz-63's largest Lyapunov exponent through cft-segrun, and at fp256 from a certified chain both auditors accept; the compiled references certified, deterministic, committed; refusals by name, its plants red; and the math library's six, sin, cos and tan, and atan, asin, acos and atan2, compiled with one tangent vector or two and run the same way, marked lanes replayed whole" -- do_tangent

# The acceptance set (programs/acceptance.py, whose docstring is the
# definition; the step-6 round's parcel A1, 2026-10-02): everything that
# runs on revision 7's quad and so on every U50 card, each entry one run
# fixed in the repository (the revision-8 set is acceptance-rev8's) - the
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
# 289 s together, niced (2026-10-02). Since 2026-10-16 (Logan's word, the
# small tasks after M1's build, item 4) it compiles Lorenz-tangent
# extended too, which no revision-8 image holds and no stage compiled:
# its compile alone took 7,077 s on amd-arc-box under cftc's output
# version 5 and 7,275 s under 6 (2026-10-15).
need python
stage acceptance-far "the hard workloads' own oracle on the four images past the card, Gray-Scott and Lorenz-tangent hard and wide, and on Lorenz-tangent extended: compiled for sw:32768, each on seq.py equal to the pack's one-step vector, states, FLAGS and each lane's FLAGS" -- \
  PY "$ROOT/programs/acceptance.py" --legs far

# `acceptance-rev8`, in no budget, so only the full census runs it (parcel
# W8's proposal, 2026-10-12, the lead's to place): the revision-8 set
# (programs/acceptance.py --set rev8, whose docstring is the definition) -
# the hard workloads that missed revision 7's quad and a revision-8 image
# holds, each compiled here for the image the rule picks and held byte for
# byte to programs/acceptance-rev8.json's digests, run through cft-segrun
# on libcft's software backend at that image's scratch depth, and held to
# the record's boundary hashes, flags and STATUS, cft-audit in full, the
# golden spot check, the device's identity and the rule, its controls
# caught; then its own oracle, each image on seq.py against the pack's
# one-step vector. The eight entries whose compile takes minutes: 2,251 s
# through the runner on the desktop in use, 2,014 of them compiling, and
# the same compiles 1,531 s with it quieter (parcel W8, 2026-10-12) -
# about half an hour, so the census and not the gate. The set's other
# two, Gray-Scott extended (on the deep single) and Riccati extended,
# compiled for 40 minutes and 2.2 hours on amd-arc-box, and were left to
# a card day, which reads the box's compile back through --images; since
# 2026-10-16 (Logan's word, the small tasks after M1's build, item 4) the
# census runs all ten, so that every extended workload is compiled by
# some stage of it. Since parcel MA (M1's build, item 6) it also runs the
# set's six routine entries - the committed Lotka-Volterra, diode and
# culture references of the math library's six, at fp64 and fp256, a
# structured lane a tile that marks - which need no compile and no mpmath
# and add seconds: they are held to the record like the workloads, and
# their per-lane blocks are read through libcft's shared library by ctypes
# (a version-1 certificate carries none), so this stage builds it too.
# Since parcel M2A (M2's build, wave 4) it runs four more, the radian case:
# the committed pendulum and attitude references at fp64 and fp256 (sin,
# cos, tan), the pendulum at fp64 with no structured lane by name and the
# two fp256 entries with the range lane declared. Since parcel M4A (M4's
# build, wave 5) it runs two more, the inverse-trigonometric case: the
# committed phase follower at fp64 and fp256 (atan2, asin, acos and atan),
# four structured lanes a tile that mark, atan2's a pair. An entry left out
# of this list is run by no stage.
REV8_CENSUS=gray_scott_hard_fp64,gray_scott_wide_fp256,lorenz_tangent_hard_fp64,lorenz_tangent_wide_fp256,gray_scott_extended_fp64,fput_extended_fp64,phi4_extended_fp64,kuramoto_sivashinsky_extended_fp64,reservoir_extended_fp64,riccati_extended_fp64,lotkavolterra-rk4-tangent-fp64,lotkavolterra-rk4-tangent-fp256,diode-rk4-tangent-fp64,diode-rk4-tangent-fp256,culture-rk4-tangent-fp64,culture-rk4-tangent-fp256,pendulum-rk4-tangent-fp64,pendulum-rk4-tangent-fp256,attitude-rk4-tangent-fp64,attitude-rk4-tangent-fp256,phasefollower-rk4-tangent-fp64,phasefollower-rk4-tangent-fp256
do_acceptance_rev8() {
  HOSTMAKE "cft-segrun$EXE" "cft-audit$EXE" "$SHLIB_NAME" || return 1
  PY "$ROOT/programs/acceptance.py" --set rev8 --legs set,oracle \
     --only "$REV8_CENSUS" \
     --segrun "$ROOT/host/cft-segrun$EXE" --audit "$ROOT/host/cft-audit$EXE" \
     --lib "$ROOT/host/$SHLIB_NAME"
}
need host-cc python
stage acceptance-rev8 "the revision-8 set on libcft's software backend, all twenty-two of its entries: ten hard workloads that missed revision 7 and a revision-8 image holds, each compiled for the image the rule picks, and twelve routine references of the math library's six, of sin, cos and tan, and of atan, asin, acos and atan2, their committed images, each with a structured lane a tile that marks (but the pendulum at fp64, by name) and, at fp256 for sin, cos and tan, the range lane declared; one fixed run each at the image's depth, held to committed boundary hashes, flags and STATUS (and the routine entries' marked lanes and per-lane blocks, read by a ctypes probe of libcft), cft-audit in full, the golden spot check (and the golden mark check), the device's identity and the rule, its controls caught; each workload's image on seq.py equal to the pack's one-step vector" -- do_acceptance_rev8

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
need host-cc cxx python mpmath
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
need node python mpmath
stage node "Node binding: unit tests and program_test.mjs, then the vectors through cft_node.wasm" -- do_node

do_wasm() {
  ensure_vectors || return 1
  node "$ROOT/bindings/wasm/verify.mjs" "$ROOT/vectors/out"
}
need node python mpmath
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

# Which MPFR the stage below builds against, said by name (KL-212). A fresh
# clone has no verify/_mpfr-prefix, so the stage used to build against the
# host's own MPFR - 4.2.1 on amd-arc-box, where the repository pins 4.2.2 -
# and said nothing of it (the binary prints the library's version as its
# first line, and never says whether that is the pin). The one comparison the
# record has, the audit round's 37 mismatches (docs/VALIDATION.md,
# 2026-09-30), came out the same against both, but a verdict reached against
# an oracle other than the pinned one should name it. The pin is read from
# verify/build-mpfr-oracle.sh, so the number exists once; the version a
# build sees is asked of the compiler, with the include flags the build will
# use (a prefix header that lost to a system one would be reported as the
# system's), as the MPFR_VERSION_STRING of the mpfr.h it includes. host_cc is
# the compiler HOSTMAKE builds with: the mingw64 gcc first on PATH on
# Windows, and make's own `cc`, or $CC, elsewhere.
host_cc() {
  if [ "$WIN" = 1 ]; then PATH="/c/msys64/mingw64/bin:$PATH" gcc "$@"
  else "${CC:-cc}" "$@"; fi
}
mpfr_pin() {
  sed -n 's/^MPFR_V=//p' "$ROOT/verify/build-mpfr-oracle.sh" 2>/dev/null | head -1
}
mpfr_header_version() {  # [cc flags...]
  printf '#include <mpfr.h>\n' | host_cc -E -dM -x c "$@" - 2>/dev/null \
    | sed -n 's/^#define MPFR_VERSION_STRING "\(.*\)".*$/\1/p' | head -1
}

do_mpfr() {
  # A repo-local prefix (verify/build-mpfr-oracle.sh) outranks system
  # packages: it is version-pinned, SHA-verified, and static, so the
  # oracle is the same everywhere it runs.
  #
  # The stage's first lines say which MPFR it is building against, and a
  # line that starts NOTE says it is not the pinned one. That is not an
  # inner skip: every comparison below runs, against a real GNU MPFR, and
  # the record has the same 37 mismatches against the box's 4.2.1 and the
  # pinned 4.2.2 (docs/VALIDATION.md, 2026-09-30). Counting it as one would
  # fail every --require-all gate in a fresh clone on a host whose MPFR is
  # not the pin, for no check that did not run. The mpfr-check binary then
  # prints the library's own version as its first line.
  local pfx="$ROOT/verify/_mpfr-prefix" pin seen
  pin=$(mpfr_pin)
  if [ -f "$pfx/include/mpfr.h" ]; then
    seen=$(mpfr_header_version "-I$pfx/include")
    if [ -n "$pin" ] && [ "$seen" = "$pin" ]; then
      echo "mpfr: built against the pinned MPFR $pin (verify/_mpfr-prefix: static, from verify/build-mpfr-oracle.sh)"    # MPFR-SAYS-PINNED
    else
      echo "NOTE  mpfr: NOT the pinned MPFR - verify/_mpfr-prefix holds ${seen:-(version not reported by the compiler)} and verify/build-mpfr-oracle.sh pins ${pin:-(unreadable: no MPFR_V in it)}; remove the prefix and rebuild it"    # MPFR-SAYS-STALE
    fi
    HOSTMAKE "mpfr-check$EXE" "mp-err-check$EXE" \
      CFLAGS="-O2 -I$pfx/include" LDLIBS="-L$pfx/lib" || return 1
  else
    seen=$(mpfr_header_version)
    if [ -n "$pin" ] && [ "$seen" = "$pin" ]; then
      echo "mpfr: no verify/_mpfr-prefix, so built against the system's MPFR $seen, which is the pinned version (not the SHA-256-verified static build that bash verify/build-mpfr-oracle.sh makes)"    # MPFR-SAYS-SYSTEM-EQUALS
    else
      echo "NOTE  mpfr: no verify/_mpfr-prefix, so built against the system's MPFR ${seen:-(version not reported by the compiler)}, NOT the pinned ${pin:-(unreadable: no MPFR_V in verify/build-mpfr-oracle.sh)}; bash verify/build-mpfr-oracle.sh builds the pin, static, without root"    # MPFR-SAYS-SYSTEM-DIFFERS
    fi
    HOSTMAKE "mpfr-check$EXE" "mp-err-check$EXE" || return 1    # MPFR-BUILD-SYSTEM
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
# Parcel M4X2: the stage also runs the routine sweep's own test (hw/test_routine_sweep.py) on the groups that hold the tool and its images to the card
# driver's table of digests - `build`, `images` (the generator's `digest` lines equal hw/card_stress_lib.py's ROUTINE_DIGESTS: a moved fragment fails the
# gate at its merge, not a night), `oracle`, `refuse`, `sabotage`, `plants`, `legs`, `marks`, and since parcel M4RR `rule` (atan2's range rule: the
# tool's classes against python/tests/mathlib_inv_harness.py's _tq_shape and _tq_band_tw, and its range plants red; about 30 s). Not `agree`, `whole`,
# `fast` or `rate` (by hand), nor `unchanged` (it needs a baseline tree and MPFR 4.2). The test skips itself by name, a SKIP line the runner counts
# as an inner skip, off POSIX and without MPFR, mpmath or pytest. do_mpfr above is run unchanged and first; its text is what
# verify/test-inner-skips.sh extracts.
do_mpfr_stage() {
  do_mpfr || return 1
  PY -B "$ROOT/hw/test_routine_sweep.py" --only build,images,oracle,refuse,sabotage,plants,legs,marks,rule
}
need host-cc mpfr
stage mpfr "MPFR parity, all rungs and modes, flags - the only external oracle reaching fp128/fp256, and the only one at all for the thirty-nine transcendentals; then the evaluator's error claims, exactly, in GMP and MPFR; then the routine sweep's tool, images, oracle, refusals, sabotage, plants and marks, and its digests held to the card driver's table (hw/test_routine_sweep.py)" -- do_mpfr_stage

need host-cc
stage soak-quick "native-oracle soak, QUICK depth + sabotage control" -- do_soakquick

# The long-run stress driver's own suite (hw/test-card-stress.sh), which the card runs every night (hw/card_stress.py): no stage, workflow or
# Makefile target ran it until 2026-10-22 (KL-28). It starts the driver and its stand-in dozens of times, dry - no XRT, no card - and reads the
# verdict parsers against real logs of the tools; `--no-plants` leaves out its negative controls (a defect put back into a copy of the code,
# which the scenario written for it must catch), which take about twice as long as everything else together (docs/CARDDAY.md has the figures: one and a half to two times; 1,761 s
# whole on 2026-10-21 against about 600 s without them, under WSL) and are run by hand when the driver's code changes. What it
# asks of its host that no other stage does:
#   * No other process on this system may use the card. The driver's guard refuses to start while one does (guard_refused), and its stand-ins
#     carry an xclbin argument or CFT_SOAK_ARTIFACT, the marks that guard looks for: the nights' own run of the driver, another copy of this
#     suite, a card tool someone has open. Then the stage is SKIPPED, by name, with the pids the driver's own guard sees (card_stress.find_card_users,
#     asked here with the guard's own rules and none of ours) - never a suite that could not start its drivers reported as a pass, and
#     --require-all fails the skip.
#   * The checkout may be built. In a gate's fresh clone host/ has been built by the stages before this one, and the suite's `buildreal` group
#     used to copy that host/ whole into its scratch repository (KL-13); it copies the files git tracks now.
# Four of its checks need the lead's own run directories and say SKIP, by name, without them: CARD_STRESS_METRICS (the `notes` group's), CARD_STRESS_RESUME_RUN
# (the `resume` group's, and the report's test, which its `testfiles` group runs) and CARD_STRESS_PROGRESS_RUNS (the nightly page's test, the same group); on
# Windows the groups that need POSIX say it too. They are inner skips, counted and named in the verdict like any stage's.
#   * On Windows the suite's timing groups - stopfile, guard and pool - are SKIPPED by name (the suite's --skip-groups, with the reason printed
#     beside each): the guard's process listing is a PowerShell call there, and on a loaded desktop it stalled for about two minutes at a time
#     (MEASURED 2026-10-22: the stopfile scenario failed identically with the base's driver code, the log's gap before the next leg 117 s), so
#     those groups' timing windows fail by the load and not by a defect, and a gate must not fail for the desktop's weather. A named skip is
#     counted, and --require-all fails it; the stage's home is Linux, WSL and the box, where nothing is skipped for this.
cardstress_users() {  # -> "pid N why; ..." for each process the driver's own guard sees using the card, or nothing
  PY -B -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import card_stress as m; print("; ".join("pid %d %s" % (u["pid"], u["why"]) for u in m.find_card_users()[0]))' "$ROOT/hw" 2>/dev/null
}
do_cardstress() {
  # the runner's own interpreter, named for the suite's wrapper (it takes python3 first, which on Windows is often the store's shim)
  local py=python
  if [ "$WIN" != 1 ] && command -v python3 >/dev/null 2>&1; then py=python3; fi
  if [ "$WIN" = 1 ]; then
    local why="Windows: the guard's process listing is a PowerShell call that stalled for about two minutes at a time on a loaded desktop (MEASURED 2026-10-22: the same scenario fails the same way with the base's driver code), so these groups' timing windows fail by the load and not by a defect; they run under WSL and on the box"
    PYTHON=$py bash "$ROOT/hw/test-card-stress.sh" --no-plants --skip-groups stopfile,guard,pool --skip-why "$why"
  else
    PYTHON=$py bash "$ROOT/hw/test-card-stress.sh" --no-plants
  fi
}
need python
# The probe (about a second: a python and the process list) is asked only when stage() below will get as far as running or skipping the stage: --list
# has exited long before this line, and the first three decisions of stage() are the three conditions here - not selected by --only or the budget (its
# first early return), passed already in this run (its second, the .ok marker), named by --skip (a SKIP verdict, its third).
if [ -z "$STAGE_SKIP_REASON" ] && { [ -z "$ONLY" ] || in_list cardstress "$ONLY"; } && ! in_list cardstress "$SKIP" && [ ! -f "$RUNDIR/cardstress.ok" ]; then
  _csu=$(cardstress_users)
  [ -n "$_csu" ] && STAGE_SKIP_REASON="another process uses the card on this system, so the driver's guard would refuse every driver the suite starts (guard_refused): $_csu"
fi
stage cardstress "the long-run stress driver's suite, hw/test-card-stress.sh --no-plants: the verdict parsers on real logs, the legs and the failure policy, the sweep and its resume, the host pool, the seeds, coverage per tree, the images' manifests and vectors/out, the report - the driver against its stand-ins, no card; skipped by name while another process uses the card, and on Windows its timing groups" -- \
  do_cardstress

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

# ---- the GPU backend (docs/HOSTAPI.md, "The GPU backend") ------------------
# A GPU held to the contract through the API the card is held to. The GPU
# backend (host/src/backend_hip.cpp, `make -C host HIP=1`) opens hip:N and
# runs libcft's own code there, so every result must be the software
# backend's, bits and flags. Until 2026-11-12 nothing in the repository ran
# its tests: the card had this runner's stages, the GPU a ledger. The stage
# builds the backend from this tree on a GPU host and holds it to the
# software handle, plants first, so that a green means something:
#   * a COPY of host/ ($RUNDIR/hip-tree), never host/ itself. host/Makefile's
#     %.o rule follows the headers and not XRTDEF, so a HIP=1 build over
#     HIP=0 objects (or the reverse) keeps device.o, program.o and divsqrt.o
#     built the other way; and `make clean` removes every tool (CLAUDE.md).
#     The copy is the files git tracks in host/, with the working tree's
#     edits, and the untracked ones git does not ignore; without git, host/
#     whole, cleaned by its own `make clean` in the copy. Every binary is
#     named on the make line and its build time printed (`all` builds no
#     test binary, and they link libcft.a statically);
#   * the build's own checks: hip-symcheck's line (no symbol of the device
#     unit is a host object's too), hip-symcheck-plant RED (the check can
#     fail), and `ldd` of the test binaries and libcft.so naming the GPU
#     runtime, libamdhip64 or libcudart;
#   * the device: HIP_DEVICE (default 0) of the platform's own lister, made
#     the only one the runtime sees - CUDA_VISIBLE_DEVICES, with
#     CUDA_DEVICE_ORDER=PCI_BUS_ID so that CUDA numbers the GPUs as
#     nvidia-smi does, or HIP_VISIBLE_DEVICES on ROCm - so every leg opens
#     hip:0. Every GPU process runs with CFT_HIP_INFO=1; every device line a
#     leg prints must be the first one's (the lister's bus, one GPU
#     visible), a leg that prints none is not a result, and the log's last
#     line is the device's. A lister that shows the GPU while the runtime of
#     this build sees none is a FAIL naming both facts, never a skip: a
#     skip comes from the host, before anything is built;
#   * the plants, in a copy of the build made with HIP_PLANTS=1 - its two
#     tools, its library and cft-selftest, so that a check run through any
#     of them carries the plant: flip and drop-flag on conf-fp64, seq-mask
#     on routines-fp64 against the software handle's sum, reduce-carry on
#     hip-test's small fp64 reductions; and round 2's twelve, each against
#     its own check alone: aug-flip, aug-flags, aug-swap and seq-aug on
#     hip-test's fp64 aug leg, idx-chunk, idx-none and src-trunc on its
#     small fp64 indexed leg at CFT_HIP_CHUNK=8, depth-clamp on its fp64
#     depth leg, bank-mode and full-flag on divsqrt_check with the whole
#     operation forced, full-refuse on the divsqrt leg's route proof with
#     the bits green, chunk-tail on the fp64 aug leg at CFT_HIP_CHUNK=64 -
#     each RED, with its plant named by the device line, and GREEN without
#     it; with no plant, the chunk crossings no default build makes and the
#     route proof's 24 lines; and hip-test's plants leg. A plant that does
#     not turn its check red fails the stage by name, and nothing runs
#     after it;
#   * study GPU-A's corpora (docs/studies/gpu-a), made here: each through
#     hip-corpus on sw, on hip:0 and on hip:0 --resident, the three sha256s
#     equal (sw is the definition: GPU-A's captured sums are printed beside
#     them as information only, and routines-fp32's is stale since M4F2),
#     and the routine corpora's equal to the golden model's own output too
#     (refuse.bin, GPU-A's one augmentedAddition case, is one of the
#     corpora since round 2 runs it); an image no device holds (n_consts 513:
#     program.c's check, before any device's own), made here from
#     refuse.bin's case, refused by its sentence on sw and on hip:0,
#     whatever features the device publishes. Not the 1M stream, about
#     95 s of GPU time a run;
#   * a bounded vector set at every format and attribute - the elementwise,
#     magnitude, augmented (whole: --augmented 24) and reduction sets -
#     replayed by cft-selftest on sw and on hip:0: the same sets and cases,
#     every case matching (HIP_FULL_REPLAY=1 replays vectors/out whole
#     instead, its character, formatOf and transcendental sets too:
#     1,228,415 cases at the runner's counts);
#   * seq_check, the `seq` stage's command, through --device hip:0, at the
#     default depth and opened at 2,048 slots: every program compared, so
#     a program refused for a bit the device does not publish is a failure;
#   * the certificate corpus's conformance test (certificates/corpus.py
#     check --device hip:0, run from this tree so that its history leg has
#     the repository), every case cft-segrun remakes made on the GPU but
#     deepwrap-fp64-2048, which cft-segrun refuses beside a device;
#   * device-test -n 96, -b -n 96 and --scratch-depth 2048: NOT COMPARED a
#     failure, NOT TESTED and NOT RUN a NOTE where they move from round 2's
#     counts; hip-test -s small, leg by leg, and round 2's aug, indexed (at
#     -s all), depth and divsqrt legs;
#   * augmented_check.py and divsqrt_check.py (the default and the
#     whole-operation routes) through hip:0, each held to the software
#     handle's count in the same run; the formatOf sets (754-2019 5.4.1),
#     made here, on sw and on hip:0 under those two routes.
# HIP_FULL=1, off by default, is the full-width tier: it adds divsqrt.c's
# chunk route (CFT_DIVSQRT_SEQ=0) to divsqrt_check, to its control in the
# plants' build and to the formatOf replay, about 67 s of runs on the RTX
# 5060 Ti and 168 s on the RX 7600 - the stage with it 774 s and 1,397 s
# (2026-11-17), the RX 7600's within 103 s of a 1,500 s timeout.
# What it asks of its host: hipcc (HIP_ROOT, default /opt/rocm; the
# platform HIP_PLATFORM, else that installation's hipconfig, else amd), a
# GPU the platform's lister shows (nvidia-smi -L, or amd-smi list or
# rocminfo), a C compiler, and python with mpmath (the corpora and the
# vectors are made from the golden model). HIP_ARCH is the device's own
# unless set (nvidia-smi's compute capability, rocminfo's gfx name; a NOTE,
# and the Makefile's default, where neither answers); HIP_CUDA passes
# through. Skipped by name where any is missing - CI, amd-arc-box and the
# Windows desktop have no GPU toolchain - and --require-all fails the skip,
# which is right for a host that claims to be a full verification host.
hip_platform() {
  local p=${HIP_PLATFORM:-} cfg="${HIP_ROOT:-/opt/rocm}/bin/hipconfig"
  if [ -z "$p" ] && [ -x "$cfg" ]; then
    p=$("$cfg" --platform 2>/dev/null | tail -n 1 | tr -d '\r[:space:]')
  fi
  echo "${p:-amd}"
}
hip_list() {  # <platform>: HIP_LISTER, the platform's lister, and HIP_LISTED, the GPUs it shows
  HIP_LISTER=""; HIP_LISTED=0
  case "$1" in
    nvidia|cuda)
      if command -v nvidia-smi >/dev/null 2>&1; then
        HIP_LISTER="nvidia-smi -L"
        HIP_LISTED=$(nvidia-smi -L 2>/dev/null | grep -cE '^GPU [0-9]+:')
      fi;;
    *)
      if command -v amd-smi >/dev/null 2>&1; then
        HIP_LISTER="amd-smi list"
        HIP_LISTED=$(amd-smi list 2>/dev/null | grep -cE '^GPU: [0-9]+')
      elif command -v rocminfo >/dev/null 2>&1; then
        HIP_LISTER="rocminfo"
        HIP_LISTED=$(rocminfo 2>/dev/null | grep -cE '^[[:space:]]*Device Type:[[:space:]]*GPU')
      fi;;
  esac
}
hip_gpu_reason() {  # -> need's skip reason for `gpu`, or nothing when the lister shows HIP_DEVICE
  local p n=${HIP_DEVICE:-0} s
  p=$(hip_platform)
  hip_list "$p"
  if [ -z "$HIP_LISTER" ]; then
    if ! command -v nvidia-smi >/dev/null 2>&1 && ! command -v amd-smi >/dev/null 2>&1; then
      echo "no GPU: neither nvidia-smi nor amd-smi on PATH"
    elif [ "$p" != amd ]; then
      echo "no GPU: no nvidia-smi on PATH, the lister for HIP_PLATFORM=$p"
    else
      echo "no GPU: neither amd-smi nor rocminfo on PATH, the listers for HIP_PLATFORM=$p"
    fi
  elif [ "$HIP_LISTED" -eq 0 ]; then
    echo "no GPU: $HIP_LISTER lists no device for HIP_PLATFORM=$p"
  elif [[ $n =~ ^[0-9]{1,9}$ ]] && [ "$((10#$n))" -ge "$HIP_LISTED" ]; then
    s=s; [ "$HIP_LISTED" -eq 1 ] && s=""
    echo "no GPU: $HIP_LISTER lists $HIP_LISTED device$s for HIP_PLATFORM=$p, and HIP_DEVICE=$n is past the $HIP_LISTED it lists"
  fi
}

# The device part of a CFT_HIP_INFO line - its name, architecture, bus,
# platform, runtime and what is visible - without this build's own figures,
# which a plant build's registers change.
hip_devpart() { sed -n 's/^cft hip: hip:0 = \(.*\); this libcft: .*/\1/p'; }
# <leg log>: its device lines - every `cft hip: ` line but a plant build's
# `cft hip: CFT_HIP_CHUNK=<n>`, which backend_hip.cpp prints at open beside
# the device's line and which names no device (counted as one, it failed
# every chunk-crossing run of the plants' build)
hip_devlines() { grep '^cft hip: ' "$1" | grep -vE '^cft hip: CFT_HIP_CHUNK=[0-9]+$'; }
# <leg log> <leg>: every GPU process of the leg named the stage's device
hip_named() {
  local n m odd
  n=$(hip_devlines "$1" | grep -c .)
  if [ "$n" -eq 0 ]; then
    echo "  FAIL  $2: no CFT_HIP_INFO line - a run whose log does not name its device is not a result"
    return 1
  fi
  m=$(hip_devlines "$1" | hip_devpart | grep -cxF -- "$HIP_DEV")
  if [ "$m" -ne "$n" ]; then
    odd=$(hip_devlines "$1" | grep -vF -- "= $HIP_DEV; this libcft: " | head -n 2)
    echo "  FAIL  $2: $((n - m)) of its $n device lines name another device than the stage's ($HIP_DEV): $odd"
    return 1
  fi
}
# <leg log> <leg> <tier>: every device line of the leg says that tier - the
# handle's own reading of CFT_HIP_TIER at open, the INFO line's "; tier
# generic, " or "; tier fixed, " (backend_hip.cpp) - so that a tier the
# caller's shell exported, or a leg's own command, cannot change unseen
# what the leg means (round 3's G3D-1). Silent when it holds, as hip_named
# is; a leg with no device line is hip_named's failure, not this one's.
hip_tier() {
  local n m odd
  n=$(hip_devlines "$1" | grep -c .)
  m=$(hip_devlines "$1" | grep -cF -- "; tier $3, ")
  if [ "$m" -ne "$n" ]; then
    odd=$(hip_devlines "$1" | grep -vF -- "; tier $3, " | head -n 1)
    echo "  FAIL  $2: $((n - m)) of its $n device lines say another tier than $3, which this leg runs: $odd"
    return 1
  fi
}
# <log> <command...>: one run, its command and its whole output in the stage's log
hip_cmd() {
  local log=$1 rc; shift
  echo "\$ $*"
  "$@" > "$log" 2>&1; rc=$?
  cat "$log"
  return $rc
}
# <plant> <log> <command...>: one run under a plant (CFT_HIP_PLANT, compiled in by HIP_PLANTS=1)
hip_plant_run() {
  local pl=$1 out=$2 rc; shift 2
  echo "\$ CFT_HIP_PLANT=$pl $*"
  CFT_HIP_PLANT=$pl "$@" > "$out" 2>&1; rc=$?    # HIP-PLANT-RUN
  cat "$out"
  return $rc
}
# <log>: "M|line" from the summary a check prints of its own failures -
# hip-test's "N checks, M failed, K NOT RUN", divsqrt_check.py's "FAIL: M
# of N disagree" - or nothing (a crash, a refusal, no count): one reader
# for every plant and control of round 2, so a red is a number, read alike
hip_failed() {
  sed -n -e 's/^\([0-9][0-9]* checks, \([0-9][0-9]*\) failed.*\)/\2|\1/p' \
         -e 's/^\(FAIL: \([0-9][0-9]*\) of [0-9][0-9]* disagree.*\)/\2|\1/p' "$1" | head -n 1
}
# <log of hip-test -l divsqrt, the plants' build>: the route proof read by
# the leg's own words. 24 lines (four formats, the divide and the root,
# three routes), each saying that the route forced is the one its head
# names - "no program after the marker (the chunk route)", "the program
# route's", "the whole image's", the leg computing each image's head
# itself - with reach 0 and lane pool 0. Prints the heads seen, by route;
# returns 1, saying what it read, when any of that is not so.
hip_proof() {
  awk '
    /^    route proof, / {
      n++; r = ""
      if ($0 ~ /the chunk route forced: head [0-9]+ - no program after the marker \(the chunk route\); /) r = "chunk"
      if ($0 ~ /the program route forced: head [0-9]+ - the program route.s; /) r = "program"
      if ($0 ~ /the whole-operation route forced: head [0-9]+ - the whole image.s; /) r = "whole"
      if (r == "" || $0 !~ /, reach 0, lane pool 0, launches [0-9]+$/) { bad++; if (!first) first = $0; next }
      h = $0; sub(/.* forced: head /, "", h); sub(/ .*/, "", h)
      if (!((r, h) in seen)) { seen[r, h] = 1; heads[r] = heads[r] " " h }
    }
    END {
      if (n != 24 || bad) {
        printf "%d route-proof line(s), 24 wanted, %d not naming its forced route with reach 0 and lane pool 0%s\n", n, bad, first ? ": " first : ""
        exit 1
      }
      printf "24 route-proof lines, each naming its forced route: the chunk route head%s after the marker program - no program ran, an absence a host fallback would also show (VG2C note 1); the program route head%s; the whole operation head%s; reach 0 and lane pool 0 on all\n", heads["chunk"], heads["program"], heads["whole"]
    }' "$1"
}
hip_sum() { sha256sum "$1" 2>/dev/null | cut -c1-64; }
hip_same() { if [ -n "$1" ] && [ "$1" = "$2" ]; then echo "= sw"; else echo "${1:-none}"; fi; }
# GPU-A's captured output sum for a corpus (docs/studies/gpu-a/captured), or "-"
hip_captured() {
  local cap="$ROOT/docs/studies/gpu-a/captured" key="" s=""
  case "$1" in
    conf-*) s=$(grep -m1 " $1.bin (" "$cap/expect.sha256" 2>/dev/null | cut -c1-64);;
    routines-*) key="ref-${1#routines-}.out";;
    *) key="ref-$1.out";;
  esac
  [ -n "$key" ] && s=$(grep -m1 "  $key\$" "$cap/programs.sha256" 2>/dev/null | cut -c1-64)
  echo "${s:--}"
}

# The set-up the two GPU stages share, `hip` and `hip-tier` - one copy, so
# that they cannot drift (round 3's G3D-1): the environment, the platform
# and the device, the copy of host/ and its build, the device probe, the
# build's own checks, the corpora and the software handle's sums
# (hip_setup); then the plants' copy and its build (hip_plants_build). Each
# runs in its caller's scope and sets the caller's own locals - plat, dev,
# root, arch, tree, ptree, L, C, O, H, P, t0, rc, b, line, busl, busd, c,
# vendor, mk, pt and SW - and HIP_INFO and HIP_DEV. Their arguments are the
# tools a stage builds beside `hip`'s, into both builds (hip-tier's two
# differentials); with none, every line they print is `hip`'s as it was.
hip_setup() {
  local -a extra=("$@")
  # A variable the caller's shell exports must not change what a run here
  # is. cert2.ENVIRONMENT_NAMES lists the 24 that libcft and cft-segrun
  # read, and each is unset here or left out for a reason in the code.
  # Unset: divsqrt.c reads CFT_DIVSQRT_FULL and CFT_DIVSQRT_SEQ at every
  # cft_div and cft_sqrt, so an exported FULL=1 would make every
  # default-route run below the whole operation's, and no log would say
  # so; an inherited plant-build instrument (CFT_HIP_PLANT and _CHUNK, which
  # this stage sets run by run, _PAGE, _UPLOAD) would change every control
  # of the plants' build; backend_hip.cpp reads CFT_HIP_TIER at every open,
  # so an exported tier would make every default leg the other tier's
  # (round 3's G3D-1: hip_tier reads each leg's word); transcend.c reads
  # CFT_TRANSCEND_MINPREC, the first precision of a transcendental on the
  # software handle, in every process here that runs one there; device-test
  # reads XCL_EMULATION_MODE (two of its legs NOT RUN "under emulation"),
  # and cft-segrun its own plant, CFT_SEGRUN_PLANT. Left out: CFT_HIP_INFO,
  # CUDA_VISIBLE_DEVICES and HIP_VISIBLE_DEVICES are the stage's own, set
  # below and on every GPU run's line, every device line held to them
  # (hip_named); CFT_TIMEOUT_MS is read by the remote backend
  # (backend_remote.c), which no run here opens, and by backend_xrt.cpp, as
  # are the ten CFT_XRT_* - and a HIP=1 build has no backend_xrt.o
  # (host/Makefile refuses HIP=1 with XRT=1), while device-test reads
  # CFT_XRT_CAPS for its card plants, on an xclbin alone. A run that forces
  # a route names it on the command line it prints.
  unset CFT_DIVSQRT_FULL CFT_DIVSQRT_SEQ CFT_HIP_PLANT CFT_HIP_CHUNK CFT_HIP_PAGE CFT_HIP_UPLOAD CFT_HIP_TIER CFT_TRANSCEND_MINPREC XCL_EMULATION_MODE CFT_SEGRUN_PLANT
  # ...and held, as a process of this stage sees its environment (env, a
  # child of it): none of the unset names but the tier may reach a run.
  # CFT_TRANSCEND_MINPREC cannot change a result (transcend.c), so no leg's
  # bits would show it; the tier is read where it acts instead, on every
  # leg's device lines (the probe's below, and hip_tier's).
  b=$(env | sed -n -E 's/^(CFT_DIVSQRT_FULL|CFT_DIVSQRT_SEQ|CFT_HIP_PLANT|CFT_HIP_CHUNK|CFT_HIP_PAGE|CFT_HIP_UPLOAD|CFT_TRANSCEND_MINPREC|XCL_EMULATION_MODE|CFT_SEGRUN_PLANT)=.*/\1/p' | tr '\n' ' ')
  if [ -n "$b" ]; then
    echo "FAIL  the environment: the stage's runs would inherit ${b% } - the unset above did not take, so a run here would not be the run its line names"
    return 1
  fi
  plat=$(hip_platform)
  case "$plat" in nvidia|amd|cuda) ;;
    *) echo "FAIL  HIP_PLATFORM=$plat: the stage builds for nvidia, amd or cuda (plain nvcc)"; return 1;; esac
  [ "$plat" = amd ] && vendor=amd || vendor=nvidia
  if ! [[ $dev =~ ^[0-9]{1,9}$ ]]; then
    echo "FAIL  HIP_DEVICE=$dev is not a device number (a decimal: 0 is the first GPU the platform's lister shows)"
    return 1
  fi
  dev=$((10#$dev))
  mkdir -p "$L" "$C" "$O" ${V:+"$V"}
  hip_list "$plat"
  # The chosen GPU is the only one this stage's processes see: hip:0 inside
  # is HIP_DEVICE outside.
  if [ "$vendor" = nvidia ]; then
    export CUDA_VISIBLE_DEVICES=$dev CUDA_DEVICE_ORDER=PCI_BUS_ID
    unset HIP_VISIBLE_DEVICES
    line=$(nvidia-smi --query-gpu=name,pci.bus_id,compute_cap,memory.used,utilization.gpu \
           --format=csv,noheader -i "$dev" 2>&1)
    busl=$(printf '%s\n' "$line" | sed -n 's/^[^,]*, *\([0-9A-Fa-f]*:[0-9A-Fa-f]*:[0-9A-Fa-f]*\.[0-9]\).*/\1/p' | tr 'A-F' 'a-f')
    [ -z "$arch" ] && arch=$(printf '%s\n' "$line" | sed -n 's/^[^,]*,[^,]*, *\([0-9]*\)\.\([0-9]*\),.*/\1\2/p')
  else
    export HIP_VISIBLE_DEVICES=$dev
    unset CUDA_VISIBLE_DEVICES
    line=$(amd-smi list 2>/dev/null | awk -v d="$dev" '$1 == "GPU:" { on = ($2 == d) } on && $1 == "BDF:" { print $2; exit }')
    busl=$(printf '%s\n' "$line" | tr 'A-F' 'a-f')
    if [ -z "$arch" ] && command -v rocminfo >/dev/null 2>&1; then
      arch=$(rocminfo 2>/dev/null | sed -n 's/^[[:space:]]*Name:[[:space:]]*\(gfx[0-9a-f]*\)[[:space:]]*$/\1/p' | sed -n "$((dev + 1))p")
    fi
  fi
  b=""
  if [ "$vendor" = nvidia ]; then
    b=", HIP_CUDA ${HIP_CUDA:-/usr/local/cuda, as the Makefile defaults it,} = $(readlink -f "${HIP_CUDA:-/usr/local/cuda}")"
  fi
  echo "hip: platform $plat, HIP_ROOT $root$b; $HIP_LISTER lists $HIP_LISTED GPU(s), HIP_DEVICE=$dev: ${line:-(no line from the lister)}"
  if [ "$vendor" = nvidia ]; then b="CUDA_VISIBLE_DEVICES=$dev CUDA_DEVICE_ORDER=PCI_BUS_ID"; else b="HIP_VISIBLE_DEVICES=$dev"; fi
  echo "hip: every process here sees that GPU alone, as hip:0 - $b"
  if [ -n "${HIP_ARCH:-}" ]; then
    echo "hip: HIP_ARCH=$arch, as set"
  elif [ -n "$arch" ]; then
    if [ "$vendor" = nvidia ]; then b="the compute capability nvidia-smi gives"; else b="the gfx name rocminfo gives"; fi
    echo "hip: HIP_ARCH=$arch, the device's own: $b"
  else
    echo "NOTE  hip: the device's architecture could not be read, so the build takes host/Makefile's default HIP_ARCH (every architecture it names)"
  fi
  mk=(make -j4 HIP=1 "HIP_PLATFORM=$plat" "HIP_ROOT=$root" "PYTHON=$PYBIN")
  [ -n "$arch" ] && mk+=("HIP_ARCH=$arch")
  [ -n "${HIP_CUDA:-}" ] && mk+=("HIP_CUDA=$HIP_CUDA")

  # ---- the copy, and the build in it
  rm -rf "$tree" "$ptree"
  mkdir -p "$tree"
  if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    (cd "$ROOT" && git ls-files -z --cached --others --exclude-standard -- host docs/studies/gpu-a/cudahip \
      | while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done \
      | tar --null -T - -cf -) | tar -xf - -C "$tree" || { echo "FAIL  the copy of host/ into $tree"; return 1; }
    b=""; [ -n "$DIRTY" ] && b=" (the tree is DIRTY)"
    echo "hip: the copy, $tree/host: $(find "$tree/host" -type f | wc -l) files - host/ as git tracks it at $COMMIT with the working tree's edits, and the untracked files git does not ignore$b"
  else
    # host/'s contents, never a link to it: `make clean` below runs in the copy
    mkdir -p "$tree/host" "$tree/docs/studies/gpu-a" && cp -a "$ROOT/host/." "$tree/host/" && [ ! -L "$tree/host" ] \
      && cp -a "$ROOT/docs/studies/gpu-a/cudahip" "$tree/docs/studies/gpu-a/" \
      && make -C "$tree/host" clean >/dev/null 2>&1 \
      || { echo "FAIL  the copy of host/ into $tree"; return 1; }
    echo "hip: the copy, $tree/host: $(find "$tree/host" -type f | wc -l) files - host/ whole (no git here: commit $COMMIT), cleaned by its own make clean in the copy"
  fi
  H="$tree/host"; P="$ptree/host"
  t0=$(date +%s)
  echo "\$ ${mk[*]} -C $H all device-test hip-test hip-corpus cft-bench cft-selftest cft-segrun${extra[*]:+ ${extra[*]}}"
  "${mk[@]}" -C "$H" all device-test hip-test hip-corpus cft-bench cft-selftest cft-segrun "${extra[@]}" \
    > "$L/build.txt" 2>&1 || { tail -n 40 "$L/build.txt"; echo "FAIL  the HIP=1 build"; return 1; }
  echo "hip: built in $(( $(date +%s) - t0 )) s; warnings: $(grep -ci 'warning' "$L/build.txt")"
  grep -i 'warning' "$L/build.txt" | head -n 20
  grep '^hip-symcheck: ' "$L/build.txt"
  for b in libcft.a libcft.so device-test hip-test hip-corpus cft-bench cft-selftest cft-segrun "${extra[@]}"; do
    printf '  built  %-14s %s\n' "$b" "$(date -r "$H/$b" '+%F %T' 2>/dev/null || echo MISSING)"
  done

  # ---- the device, by this build's own runtime: a lister that shows the
  # GPU while the runtime sees none is a failure naming both
  hip_cmd "$L/open.txt" env CFT_HIP_INFO=1 "$H/hip-test" hip:0 -l open; rc=$?    # HIP-OPEN-PROBE
  if grep -qE 'the HIP runtime sees 0 |found no usable GPU' "$L/open.txt"; then
    echo "FAIL  $HIP_LISTER lists $HIP_LISTED GPU(s) for HIP_PLATFORM=$plat and HIP_DEVICE=$dev among them, but the HIP runtime of this build sees none: $(grep -m1 -E 'the HIP runtime sees 0 |found no usable GPU' "$L/open.txt")"
    return 1
  fi
  [ $rc -eq 0 ] || { echo "FAIL  hip-test hip:0 -l open exited $rc"; return 1; }
  HIP_INFO=$(grep -m1 '^cft hip: hip:0 = ' "$L/open.txt")
  HIP_DEV=$(printf '%s\n' "$HIP_INFO" | hip_devpart)
  [ -n "$HIP_DEV" ] || { echo "FAIL  hip-test printed no CFT_HIP_INFO line it can be named by"; return 1; }
  # The probe opens hip:0 with no tier set by this stage, so its handle is
  # the default's, generic: anything else is CFT_HIP_TIER past the unset,
  # and every leg below would run another tier than its line names
  case "$HIP_INFO" in *"; tier generic, "*) ;;
    *) echo "FAIL  the device probe (hip-test hip:0 -l open, no tier set by this stage) does not say tier generic: $HIP_INFO"; return 1;; esac
  busd=$(printf '%s\n' "$HIP_DEV" | sed -n 's/.*, bus [0-9a-f]*:\([0-9a-f]*:[0-9a-f]*\.[0-9]\),.*/\1/p')
  case "$HIP_DEV" in *"; of 1 visible"*) ;;
    *) echo "FAIL  the runtime sees more than the one GPU the stage chose: $HIP_INFO"; return 1;; esac
  if [ -z "$busl" ] || [ "${busl: -7}" != "$busd" ]; then
    echo "FAIL  the runtime's GPU (bus $busd) is not the one $HIP_LISTER names HIP_DEVICE=$dev (bus ${busl:-unknown}): $HIP_INFO"
    return 1
  fi
  echo "hip: the device - $HIP_INFO"

  # ---- the build's own checks
  hip_cmd "$L/symplant.txt" "${mk[@]}" -C "$H" hip-symcheck-plant \
    && grep -q '^hip-symcheck-plant: RED, as it must be' "$L/symplant.txt" \
    || { echo "FAIL  hip-symcheck-plant did not say RED: the symbol check is not shown to fail"; return 1; }
  for b in device-test hip-test hip-corpus cft-bench cft-selftest cft-segrun libcft.so "${extra[@]}"; do
    line=$(ldd "$H/$b" 2>&1 | grep -E 'libamdhip64|libcudart' | head -n 1)
    if [ -n "$line" ]; then printf '  ldd    %-14s %s\n' "$b" "$(echo $line)"
    else echo "FAIL  ldd $H/$b names no GPU runtime (libamdhip64 or libcudart): a result from it would not be the GPU's"; rc=1; fi
  done
  [ $rc -eq 0 ] || return 1

  # ---- the corpora (GPU-A's generators, the commands G1B used) and the
  # software handle's sums, the definition every GPU run is held to
  t0=$(date +%s)
  hip_cmd "$L/gen-conformance.txt" "$PYBIN" -B "$ROOT/docs/studies/gpu-a/gen_corpus.py" conformance "$C" \
    || { echo "FAIL  gen_corpus.py conformance"; return 1; }
  hip_cmd "$L/gen-programs.txt" "$PYBIN" -B "$ROOT/docs/studies/gpu-a/gen_programs.py" "$C" \
      --formats fp32 fp64 fp128 fp256 --golden \
    || { echo "FAIL  gen_programs.py"; return 1; }
  echo "hip: the corpora made in $(( $(date +%s) - t0 )) s"
  for c in $HIP_CORPORA; do
    hip_cmd "$L/sw-$c.txt" "$H/hip-corpus" sw "$C/$c.bin" "$O/$c.sw" \
      || { echo "FAIL  hip-corpus sw $c.bin"; return 1; }
    SW[$c]=$(hip_sum "$O/$c.sw")
  done
}
hip_plants_build() {
  echo "== plants (HIP_PLANTS=1, a copy of the build: $P)"
  cp -a "$tree" "$ptree" || { echo "FAIL  the plants' copy"; return 1; }
  t0=$(date +%s)
  # The copy holds the default build's library and tools, which carry no
  # plant, so a check run through its library (CFT_LIB=$P/libcft.so) or
  # its cft-selftest would be green under every plant: both are named here
  # to be rebuilt with the plants (host/Makefile: backend_hip.o and .lo
  # follow gen/hip/backend-flags; device-test is not, and no plant's check
  # runs it), and each plant run's own device line, CFT_HIP_PLANT=<name>,
  # is the proof that what ran carried it.
  pt=(hip-corpus hip-test "$SHLIB_NAME" cft-selftest)    # HIP-PLANTS-BUILD
  pt+=("$@")
  "${mk[@]}" -C "$P" HIP_PLANTS=1 "${pt[@]}" > "$L/build-plants.txt" 2>&1 \
    || { tail -n 40 "$L/build-plants.txt"; echo "FAIL  the HIP_PLANTS=1 build"; return 1; }
  echo "hip: the plants' build (${pt[*]}) in $(( $(date +%s) - t0 )) s; warnings: $(grep -ci 'warning' "$L/build-plants.txt")"
  for b in "${pt[@]}"; do
    printf '  built  %-14s %s\n' "$b" "$(date -r "$P/$b" '+%F %T' 2>/dev/null || echo MISSING)"
  done
}

do_hip() {
  local plat dev=${HIP_DEVICE:-0} root=${HIP_ROOT:-/opt/rocm} arch=${HIP_ARCH:-} \
        tree="$RUNDIR/hip-tree" ptree="$RUNDIR/hip-tree-plants" L="$RUNDIR/hip-logs" \
        C="$RUNDIR/hip-corpora" O="$RUNDIR/hip-out" V="$RUNDIR/hip-vectors" \
        H P t0 rc=0 n f b line busl busd want got pl nd nf c s h r g cap vendor \
        V2="$RUNDIR/hip-vectors-formatof" ch args e named what why api rp dp
  local -a mk bad=() pt=()
  local -A SW=()
  hip_setup || return 1

  # ---- the plants, before anything is believed
  hip_plants_build || return 1
  for pl in flip drop-flag; do
    hip_plant_run "$pl" "$L/plant-$pl.txt" env CFT_HIP_INFO=1 "$P/hip-corpus" hip:0 "$C/conf-fp64.bin" "$O/plant-$pl.out"; rc=$?
    line=$(grep -m1 "against the corpus's expected values [0-9]* results and [0-9]* flags differ" "$L/plant-$pl.txt")
    nd=$(printf '%s\n' "$line" | sed -n 's/.*expected values \([0-9]*\) results and \([0-9]*\) flags differ.*/\1/p')
    nf=$(printf '%s\n' "$line" | sed -n 's/.*expected values \([0-9]*\) results and \([0-9]*\) flags differ.*/\2/p')
    if [ "$pl" = flip ]; then n=${nd:-0}; f=results; else n=${nf:-0}; f=flags; fi
    if [ $rc -eq 1 ] && [ "$n" -gt 0 ] && grep -q "^cft hip: .*CFT_HIP_PLANT=$pl\$" "$L/plant-$pl.txt"; then
      echo "  RED   plant $pl: conf-fp64 on hip:0 exits 1, $n $f differing from the corpus's expected values"
    else
      bad+=("plant $pl did not turn its check red: hip-corpus hip:0 conf-fp64 exited $rc with ${n:-no} $f differing$(grep -q "CFT_HIP_PLANT=$pl\$" "$L/plant-$pl.txt" || echo ', and no device line names the plant')")
    fi
  done
  hip_plant_run seq-mask "$L/plant-seq-mask.txt" env CFT_HIP_INFO=1 "$P/hip-corpus" hip:0 "$C/routines-fp64.bin" "$O/plant-seq-mask.out"; rc=$?
  h=$(hip_sum "$O/plant-seq-mask.out")
  if [ $rc -eq 0 ] && [ -n "$h" ] && [ "$h" != "${SW[routines-fp64]}" ] \
     && grep -q '^cft hip: .*CFT_HIP_PLANT=seq-mask$' "$L/plant-seq-mask.txt"; then
    echo "  RED   plant seq-mask: routines-fp64 on hip:0 gives $h, the software handle $(echo "${SW[routines-fp64]}")"
  else
    bad+=("plant seq-mask did not turn its check red: routines-fp64 on hip:0 exited $rc with sha256 ${h:-none}, the software handle's ${SW[routines-fp64]}")
  fi
  hip_plant_run reduce-carry "$L/plant-reduce-carry.txt" env CFT_HIP_INFO=1 "$P/hip-test" hip:0 -l reduce -s small -f fp64; rc=$?
  line=$(grep -m1 '^[0-9]* checks, [0-9]* failed' "$L/plant-reduce-carry.txt")
  n=$(printf '%s\n' "$line" | sed -n 's/^[0-9]* checks, \([0-9]*\) failed.*/\1/p')
  if [ $rc -eq 1 ] && [ "${n:-0}" -gt 0 ] && grep -q '^cft hip: .*CFT_HIP_PLANT=reduce-carry$' "$L/plant-reduce-carry.txt"; then
    echo "  RED   plant reduce-carry: hip-test's small fp64 reductions, $line"
  else
    bad+=("plant reduce-carry did not turn its check red: hip-test -l reduce -s small -f fp64 exited $rc (${line:-no summary})")
  fi
  # Round 2's plants, each run against its own check alone - the cheapest
  # red its parcel measured - and judged by its own number: <plant> <its
  # reader> <CFT_HIP_CHUNK, or -> <hip-test's arguments>. `ht` is hip-test,
  # red at "N checks, M failed" with M > 0; `dsc` is divsqrt_check.py
  # through the plants' library with the whole operation forced
  # (CFT_DIVSQRT_FULL=1), red at "FAIL: M of N disagree" with M > 0. Only a
  # plant build reads CFT_HIP_CHUNK: 8 lanes puts every table window past a
  # chunk boundary, 64 elements cuts the aug leg's calls of 300 and 1,024
  # pairs. G2C's three act on any BANK_EXT program of 42 or more constants
  # (the whole-operation images), so each meets its own check only: other
  # checks would be red under them too (measured once, off the stage:
  # docs/VALIDATION.md, parcel G2D).
  for e in "aug-flip ht - -l aug -f fp64" "aug-flags ht - -l aug -f fp64" \
           "aug-swap ht - -l aug -f fp64" "seq-aug ht - -l aug -f fp64" \
           "idx-chunk ht 8 -l indexed -s small -f fp64" "idx-none ht 8 -l indexed -s small -f fp64" \
           "src-trunc ht 8 -l indexed -s small -f fp64" "depth-clamp ht - -l depth -f fp64" \
           "bank-mode dsc -" "full-flag dsc -" "chunk-tail ht 64 -l aug -f fp64"; do
    read -r pl b ch args <<< "$e"
    [ "$ch" = - ] && ch=""
    f="$L/plant-$pl.txt"
    if [ "$b" = ht ]; then
      what="hip-test hip:0 $args${ch:+, CFT_HIP_CHUNK=$ch}"
      hip_plant_run "$pl" "$f" env CFT_HIP_INFO=1 ${ch:+CFT_HIP_CHUNK=$ch} "$P/hip-test" hip:0 $args; rc=$?
    else
      what="divsqrt_check.py --device hip:0, CFT_DIVSQRT_FULL=1, the plants' $SHLIB_NAME"
      (cd "$ROOT" && hip_plant_run "$pl" "$f" env CFT_HIP_INFO=1 CFT_LIB="$P/$SHLIB_NAME" CFT_DIVSQRT_FULL=1 \
         "$PYBIN" -B host/tests/divsqrt_check.py --device hip:0); rc=$?
    fi
    r=$(hip_failed "$f"); n=${r%%|*}; line=${r#*|}
    named=$(grep -m1 "^cft hip: .*CFT_HIP_PLANT=$pl\$" "$f")
    why=""
    [ -n "$named" ] || why="$why, and no device line names the plant"
    [ -z "$ch" ] || grep -qx "cft hip: CFT_HIP_CHUNK=$ch" "$f" || why="$why, and no line says CFT_HIP_CHUNK=$ch took"
    if [ $rc -eq 1 ] && [ "${n:-0}" -gt 0 ] && [ -z "$why" ]; then
      echo "  RED   plant $pl: $what - $line"
      grep -m1 '^  FAIL: ' "$f" | sed 's/^ */          the first: /'
      if [ "$b" = dsc ]; then echo "          what ran: ${named#*; this libcft: }"; fi
    else
      bad+=("plant $pl did not turn its check red: $what exited $rc, ${line:-no count of failed checks}$why")
    fi
  done
  # full-refuse, judged on both sides: its red is the route proof's alone.
  # It refuses the whole-operation image by name, and divsqrt.c's ladder
  # falls through to the program route, whose bits are the same, so the
  # divsqrt leg's route proof (the plant build's probe of the last program
  # run) must say that the program route ran where the whole operation was
  # forced, while the leg's four "through the API" lines say 0 failed and
  # divsqrt_check, with the whole operation forced and without, is green.
  # A route claim the fall-through also satisfies is a check that cannot
  # fail; a red of the bits would be another fault's.
  pl=full-refuse; f="$L/plant-$pl.txt"
  hip_plant_run "$pl" "$f" env CFT_HIP_INFO=1 "$P/hip-test" hip:0 -l divsqrt; rc=$?
  r=$(hip_failed "$f"); n=${r%%|*}; line=${r#*|}
  rp=$(grep -m1 -E "^  FAIL: the route proof: cft_(div|sqrt) fp[0-9]+, the whole-operation route forced: ok, the probe's head [0-9]+ \(the program route's\)" "$f")
  api=$(grep -cE '^    fp(32|64|128|256) through the API, each route forced: .*: [1-9][0-9]* checks, 0 failed$' "$f")
  why=""
  [ $rc -eq 1 ] && [ "${n:-0}" -gt 0 ] || why="$why; hip-test -l divsqrt exited $rc, ${line:-no count of failed checks}"
  [ -n "$rp" ] || why="$why; no route-proof FAIL line says the program route ran where the whole operation was forced"
  [ "$api" = 4 ] || why="$why; $api of the leg's four \"through the API\" lines say 0 failed, and its bits must stay green"
  grep -q "^cft hip: .*CFT_HIP_PLANT=$pl\$" "$f" || why="$why; no device line of the leg names the plant"
  for v in "" 1; do
    g="$L/plant-$pl-dsc${v:+-full}.txt"
    (cd "$ROOT" && hip_plant_run "$pl" "$g" env CFT_HIP_INFO=1 CFT_LIB="$P/$SHLIB_NAME" ${v:+CFT_DIVSQRT_FULL=1} \
       "$PYBIN" -B host/tests/divsqrt_check.py --device hip:0); r=$?
    s=$(grep -m1 -E '^OK: [0-9]+ cases|^FAIL: ' "$g")
    named=$(grep -m1 "^cft hip: .*CFT_HIP_PLANT=$pl\$" "$g")
    if [ $r -ne 0 ] || [ "${s#OK: }" = "$s" ] || [ -z "$named" ]; then
      why="$why; divsqrt_check${v:+ under CFT_DIVSQRT_FULL=1} exited $r (${s:-no summary})$([ -n "$named" ] || echo ', and no device line names the plant')"
    fi
  done
  if [ -z "$why" ]; then
    echo "  RED   plant full-refuse: the route proof red, the bits green - ${rp#  FAIL: }"
    echo "          the leg: $line; its four \"through the API\" lines 0 failed; divsqrt_check green under the plant, the whole operation forced and not: $(grep -m1 '^OK: ' "$L/plant-$pl-dsc-full.txt") and $(grep -m1 '^OK: ' "$L/plant-$pl-dsc.txt")"
    echo "          what ran: ${named#*; this libcft: }"
  else
    bad+=("plant full-refuse did not turn its check red as it must, by the route proof alone: ${why#; }")
  fi
  # the same checks on the plants' build with no plant: GREEN, so the red was the plant's
  hip_cmd "$L/plant-none-conf.txt" env CFT_HIP_INFO=1 "$P/hip-corpus" hip:0 "$C/conf-fp64.bin" "$O/plant-none.out" \
    && grep -q "expected values 0 results and 0 flags differ" "$L/plant-none-conf.txt" \
    || bad+=("the plants' build with no plant is not green on conf-fp64, so its reds prove nothing")
  hip_cmd "$L/plant-none-routines.txt" env CFT_HIP_INFO=1 "$P/hip-corpus" hip:0 "$C/routines-fp64.bin" "$O/plant-none-routines.out" \
    && [ "$(hip_sum "$O/plant-none-routines.out")" = "${SW[routines-fp64]}" ] \
    || bad+=("the plants' build with no plant does not give the software handle's routines-fp64")
  hip_cmd "$L/plant-none-reduce.txt" env CFT_HIP_INFO=1 "$P/hip-test" hip:0 -l reduce -s small -f fp64 \
    || bad+=("the plants' build with no plant is not green on hip-test's small fp64 reductions")
  # Round 2's controls: each plant's own command with no plant, 0 failed of
  # a count above 0; and the chunk crossings no leg of a default build
  # makes (there an augmented call's chunk is what the 64 MiB stage holds,
  # 524,277 pairs at fp256, and a program's starts at 2,048 lanes), here in
  # the PLANTS' build at CFT_HIP_CHUNK, each run's log carrying that line -
  # chunk-tail's red above is this crossing's - and divsqrt's route proof
  # read where the probe exists (hip_proof), with no NOT RUN.
  for e in "aug - -l aug -f fp64" "aug-chunk64 64 -l aug" "indexed-chunk8 8 -l indexed -s small -f fp64" \
           "depth - -l depth -f fp64" "depth-chunk64 64 -l depth" "divsqrt - -l divsqrt" \
           "divsqrt-chunk64 64 -l divsqrt"; do
    read -r c ch args <<< "$e"
    [ "$ch" = - ] && ch=""
    f="$L/plant-none-$c.txt"
    hip_cmd "$f" env CFT_HIP_INFO=1 ${ch:+CFT_HIP_CHUNK=$ch} "$P/hip-test" hip:0 $args; rc=$?
    r=$(hip_failed "$f"); n=${r%%|*}; line=${r#*|}
    why=""; s=""
    [ $rc -eq 0 ] && [ "$n" = 0 ] && [ "${line%% *}" -gt 0 ] 2>/dev/null || why=", exited $rc, ${line:-no count of checks}"
    [ -z "$ch" ] || grep -qx "cft hip: CFT_HIP_CHUNK=$ch" "$f" || why="$why, and no line says CFT_HIP_CHUNK=$ch took"
    if [ "${c%%-*}" = divsqrt ]; then
      s=$(hip_proof "$f") || why="$why, and its route proof: $s"
      case $line in *", 0 NOT RUN") ;; *) why="$why, and NOT RUN in a plant build, which has the probe and fail-launch";; esac
    fi
    if [ -z "$why" ]; then
      echo "  GREEN no plant, hip-test hip:0 $args${ch:+, CFT_HIP_CHUNK=$ch}: $line"
      [ -n "$s" ] && echo "          $s"
      grep ': the probe says [0-9]* launches of ' "$f" | sed 's/^ */          /'
    else
      bad+=("the plants' build with no plant is not green on hip-test hip:0 $args${ch:+, CFT_HIP_CHUNK=$ch}$why")
    fi
  done
  # divsqrt_check through the plants' library, no plant: the default route
  # and the whole operation; the chunk route is HIP_FULL=1's, as everywhere
  for v in default whole chunk; do
    case $v in
      whole) e=CFT_DIVSQRT_FULL=1;;
      chunk) e=CFT_DIVSQRT_SEQ=0
             if [ "${HIP_FULL:-0}" != 1 ]; then echo "  (the chunk route's control, CFT_DIVSQRT_SEQ=0, runs under HIP_FULL=1)"; continue; fi;;
      *) e="";;
    esac
    f="$L/plant-none-dsc-$v.txt"
    (cd "$ROOT" && hip_cmd "$f" env CFT_HIP_INFO=1 CFT_LIB="$P/$SHLIB_NAME" $e "$PYBIN" -B host/tests/divsqrt_check.py --device hip:0); rc=$?
    s=$(grep -m1 '^OK: [0-9]* cases' "$f")
    if [ $rc -eq 0 ] && [ -n "$s" ]; then
      echo "  GREEN no plant, divsqrt_check.py --device hip:0${e:+, $e}: $s"
    else
      bad+=("the plants' build with no plant is not green on divsqrt_check.py --device hip:0${e:+, $e}: exit $rc ($(grep -m1 '^FAIL: ' "$f"))")
    fi
  done
  hip_cmd "$L/plant-leg.txt" env CFT_HIP_INFO=1 "$P/hip-test" hip:0 -l plants \
    || bad+=("hip-test's plants leg: a malformed CFT_HIP_PLANT, CFT_HIP_CHUNK, CFT_HIP_PAGE or CFT_HIP_INFO is not refused by name")
  for f in "$L"/plant-*.txt; do hip_named "$f" "plants, $(basename "$f" .txt)" || bad+=("$(basename "$f" .txt): its device is not the stage's"); done
  for f in "$L"/plant-*.txt; do hip_tier "$f" "plants, $(basename "$f" .txt)" generic || bad+=("$(basename "$f" .txt): a device line says another tier than generic, the tier of every run here"); done
  if [ ${#bad[@]} -gt 0 ]; then
    printf 'FAIL  %s\n' "${bad[@]}"
    echo "FAIL  the plants: a check a plant cannot turn red proves nothing, so no leg runs after them"
    return 1
  fi
  echo "hip: every plant RED, and GREEN without it"

  # ---- b. the corpora: sw, hip:0 and hip:0 --resident, the same sha256
  echo "== corpora (docs/studies/gpu-a): sw, hip:0, hip:0 --resident; GPU-A's captured sum beside, as information"
  echo "   (each sha256 of the output in full; \"= sw\" where it is the software handle's, compared whole)"
  printf '%-15s %-64s %-7s %-7s %-7s %s\n' corpus "sw" "hip:0" resident golden "GPU-A captured"
  : > "$L/corpora.txt"
  for c in $HIP_CORPORA; do
    { echo "\$ CFT_HIP_INFO=1 $H/hip-corpus hip:0 $C/$c.bin $O/$c.hip"
      CFT_HIP_INFO=1 "$H/hip-corpus" hip:0 "$C/$c.bin" "$O/$c.hip" 2>&1; } > "$L/hip-$c.txt"; r=$?
    { echo "\$ CFT_HIP_INFO=1 $H/hip-corpus hip:0 $C/$c.bin $O/$c.res --resident"
      CFT_HIP_INFO=1 "$H/hip-corpus" hip:0 "$C/$c.bin" "$O/$c.res" --resident 2>&1; } > "$L/res-$c.txt"; rc=$?
    cat "$L/hip-$c.txt" "$L/res-$c.txt" >> "$L/corpora.txt"
    h=$(hip_sum "$O/$c.hip"); s=$(hip_sum "$O/$c.res")
    g="-"; [ -f "$C/$c.golden" ] && g=$(hip_sum "$C/$c.golden")
    cap=$(hip_captured "$c")
    printf '%-15s %-64s %-7s %-7s %-7s %s\n' "$c" "${SW[$c]}" "$(hip_same "$h" "${SW[$c]}")" \
      "$(hip_same "$s" "${SW[$c]}")" "$( [ "$g" = - ] && echo - || hip_same "$g" "${SW[$c]}")" \
      "$( if [ "$cap" = - ]; then echo "- (none captured)"; elif [ "$cap" = "${SW[$c]}" ]; then echo "= sw"; else echo "$cap (not sw's)"; fi)"
    if [ $r -ne 0 ] || [ $rc -ne 0 ] || [ "$h" != "${SW[$c]}" ] || [ "$s" != "${SW[$c]}" ] \
       || { [ "$g" != "-" ] && [ "$g" != "${SW[$c]}" ]; }; then
      bad+=("$c: hip:0 exited $r and --resident $rc; sha256 sw ${SW[$c]}, hip:0 ${h:-none}, resident ${s:-none}$([ "$g" != "-" ] && echo ", golden $g")")
    fi
  done
  cat "$L/corpora.txt"
  # The refusal leg: an image no device holds - n_consts 513, past the 512 an
  # instruction addresses (program.c's check, before any device's own) - made
  # from refuse.bin's case with its image replaced (a BANK_EXT header and one
  # HALT, by the golden model's own encoder), refused by its sentence on sw
  # and on hip:0. Round 2 publishes AUGADD, so refuse.bin itself no longer is.
  hip_cmd "$L/bank513-make.txt" "$PYBIN" -B - "$C/refuse.bin" "$C/bank513.bin" "$ROOT/python" <<'PY' \
    || bad+=("bank513.bin: not made from refuse.bin")
import struct, sys
src, dst, py = sys.argv[1:4]
sys.path.insert(0, py)
from cft_golden import seq
d = open(src, "rb").read()
assert d[:8] == b"CFTSEQA1", "refuse.bin: not a hip-corpus case"
w = list(struct.unpack_from("<10I", d, 8))
rest = d[48 + w[9] + w[2]:]
img = struct.pack("<8I", seq.MAGIC, seq.VERSION, 1, 513, 1, seq.PREC_CODE["fp64"], 1, 0)
img += struct.pack("<Q", seq.halt())
name = b"fp64 bank513"
w[2], w[9] = len(img), len(name)
out = b"CFTSEQA1" + struct.pack("<10I", *w) + name + img + rest
open(dst, "wb").write(out)
print("bank513.bin: %d bytes; its image a BANK_EXT header with n_consts 513 and one HALT" % len(out))
PY
  for dv in sw hip; do
    rdev=$dv; [ $dv = hip ] && rdev=hip:0
    hip_cmd "$L/refuse-$dv.txt" env CFT_HIP_INFO=1 "$H/hip-corpus" "$rdev" "$C/bank513.bin" "$O/bank513.$dv"; rc=$?
    if [ $rc -eq 1 ] && grep -q '^refused by libcft: .*n_consts.*at most 512' "$L/refuse-$dv.txt"; then
      echo "  ok    bank513.bin: refused by name on $rdev (n_consts 513, at most 512)"
    else
      bad+=("bank513.bin: not refused by its sentence on $rdev (exit $rc)")
    fi
  done
  hip_named "$L/corpora.txt" corpora || bad+=("the corpora: a run did not name the stage's device")
  hip_tier "$L/corpora.txt" corpora generic || bad+=("the corpora: a run's device line says another tier than generic")
  hip_named "$L/refuse-hip.txt" refuse || bad+=("bank513.bin: its run on hip:0 did not name the stage's device")
  hip_tier "$L/refuse-hip.txt" refuse generic || bad+=("bank513.bin: its run on hip:0 says another tier than generic")
  [ ${#bad[@]} -eq 0 ] && echo "hip: $(echo $HIP_CORPORA | wc -w) corpora, each the software handle's sha256 on hip:0 and on hip:0 --resident"

  # ---- c. the vectors: the same sets and cases on sw and on hip:0
  echo "== vectors (cft-selftest, sw and hip:0)"
  if [ "${HIP_FULL_REPLAY:-0}" = 1 ]; then
    ensure_vectors || return 1
    V="$ROOT/vectors/out"
  else
    # every format and attribute: the elementwise sets (every opcode), the
    # magnitude forms, the augmented and the reduction sets. Not the
    # character, formatOf and transcendental sets, whose directed pools are
    # fixed and large (MEASURED 2026-11-12: with them a bounded set was
    # 291,298 cases, 151 s on sw alone in cft-gpu, past 120 s on the GPU;
    # the fp256 transcendental sets about a minute each to generate) - they
    # are HIP_FULL_REPLAY's; the formatOf sets have a leg of their own,
    # below. The augmented sets whole (--augmented 24, vectors/out's count:
    # 552 cases past the 89,064 of 1), one a format, their rounding 9.5's,
    # each case through cft_augmented_* - on hip:0 the GPU's since G2A
    hip_cmd "$L/gen-vectors.txt" "$PYBIN" -B "$ROOT/vectors/gen_vectors.py" --out "$V" \
        --formats fp32 fp64 fp128 fp256 --rounding rne rtz rdn rup rmm \
        --directed 120 --random 160 --simple 24 --transcend 0 --minmaxmag 1 \
        --augmented 24 --reduce 1 --character 0 --formatof 0 \
      || { echo "FAIL  gen_vectors.py"; return 1; }
  fi
  (cd "$H" && hip_cmd "$L/vectors-sw.txt" ./cft-selftest "$V"); r=$?
  (cd "$H" && hip_cmd "$L/vectors-hip.txt" env CFT_HIP_INFO=1 ./cft-selftest "$V" hip:0); rc=$?
  s=$(grep -E '^[0-9]+ sets?, [0-9]+ cases, all matching' "$L/vectors-sw.txt" | cut -d'(' -f1)
  h=$(grep -E '^[0-9]+ sets?, [0-9]+ cases, all matching' "$L/vectors-hip.txt" | cut -d'(' -f1)
  n=$(grep -E '^[0-9]+ cases checked' "$L/vectors-sw.txt"); f=$(grep -E '^[0-9]+ cases checked' "$L/vectors-hip.txt")
  if [ $r -eq 0 ] && [ $rc -eq 0 ] && [ -n "$s" ] && [ "$s" = "$h" ] && [ -n "$n" ] && [ "$n" = "$f" ]; then
    echo "  ok    vectors: sw and hip:0 alike - ${h}; $f"
  else
    bad+=("vectors: sw exited $r (${s:-no sets line}; ${n:-no count}), hip:0 exited $rc (${h:-no sets line}; ${f:-no count})")
  fi
  hip_named "$L/vectors-hip.txt" vectors || bad+=("vectors: the replay did not name the stage's device")
  hip_tier "$L/vectors-hip.txt" vectors generic || bad+=("vectors: the replay's device line says another tier than generic")

  # ---- d. seq_check, the `seq` stage's command, through the device: at
  # the default depth, and opened at 2,048 slots (--device-depth, G2B's
  # cft_open_ex), where the indexed corpus and the deep programs run at the
  # card's depth. hip:N publishes the software handle's features since
  # round 2, so a program NOT COMPARED for a bit it does not publish is a
  # failure now, its line printed as before; the positive lines must say
  # so. The indexed corpus's "refused by both" (an index at its source's
  # length, the host's bound check) is not such a line: it is shown.
  for dp in "" 2048; do
    echo "== seq_check --device hip:0${dp:+ --device-depth $dp}"
    t0=$(date +%s)
    f="$L/seq${dp:+-$dp}.txt"
    (cd "$ROOT" && hip_cmd "$f" env CFT_HIP_INFO=1 CFT_LIB="$H/$SHLIB_NAME" "$PYBIN" -B host/tests/seq_check.py \
       --trials 250 --formats fp32 fp64 fp128 fp256 --device hip:0 ${dp:+--device-depth $dp}); rc=$?
    if [ $rc -eq 0 ] && grep -q '^device hip:0: backend hip,' "$f" && ! grep -q 'MISMATCH' "$f"; then
      echo "  ok    seq_check through hip:0${dp:+ at --device-depth $dp}, $(( $(date +%s) - t0 )) s: $(grep -m1 '^device hip:0: backend hip,' "$f")"
      grep -E '^[0-9]+ programs from the indexed corpus run through both' "$f" | sed 's/^/        /'
    else
      bad+=("seq_check --device hip:0${dp:+ --device-depth $dp}: exit $rc, $(grep -c MISMATCH "$f") MISMATCH line(s)$(grep -q '^device hip:0: backend hip,' "$f" || echo ', and no device line of its own')")
    fi
    if grep -qE 'programs NOT COMPARED - each needs a bit the device does not publish|^  it does not publish' "$f"; then
      grep -E 'programs NOT COMPARED - each needs a bit the device does not publish|^  it does not publish' "$f" \
        | sed 's/^ */        /'
      bad+=("seq_check${dp:+ at --device-depth $dp}: hip:0 does not publish a bit a program needs, where it publishes the software handle's features since round 2: $(grep -m1 -E '^  it does not publish|programs NOT COMPARED - each needs a bit' "$f")")
    fi
    grep -qx '  it publishes every bit cft.h defines' "$f" \
      && grep -qx 'the device refused no program for a bit it lacks: every program was compared' "$f" \
      || bad+=("seq_check${dp:+ at --device-depth $dp}: no line says that hip:0 publishes every bit and that every program was compared")
    if [ -n "$dp" ] && ! grep -q "^device hip:0: backend hip, .*, max_scratch $dp; " "$f"; then
      bad+=("seq_check --device-depth $dp: the device line does not say max_scratch $dp - the depth did not take")
    fi
    hip_named "$f" "seq_check${dp:+ at $dp}" || bad+=("seq_check${dp:+ at $dp}: it did not name the stage's device")
    hip_tier "$f" "seq_check${dp:+ at $dp}" generic || bad+=("seq_check${dp:+ at $dp}: its device line says another tier than generic")
  done

  # ---- e. the certificate corpus's conformance test through the device
  echo "== certificates/corpus.py check --device hip:0"
  t0=$(date +%s)
  (cd "$ROOT" && hip_cmd "$L/corpus.txt" env CFT_HIP_INFO=1 "$PYBIN" -B certificates/corpus.py check \
     --tool "$H/cft-segrun" --device hip:0); rc=$?
  line=$(grep -m1 '^corpus check --device hip:0: ' "$L/corpus.txt")
  # Its count line held: the one case refused by name is deepwrap-fp64-2048
  # - cft-segrun's usage refusal of a stated depth beside a device
  # (host/tools/segrun.c), not the GPU's: G2B's hip:N opens at 2,048, but
  # cft-segrun does not ask - and augsum-fp64, whose AUGERR needs AUGADD,
  # is made on hip:0 since G2A, in no refusal. corpus.py fails unless every
  # case is remade and held or refused as expected, so with that one
  # refusal the count remade (18 at 2026-11-17) is every other case.
  n=$(printf '%s\n' "$line" | sed -n 's/^corpus check --device hip:0: \([0-9]*\) cases remade .*/\1/p')
  r=$(printf '%s\n' "$line" | sed -n 's/.*; \([0-9]*\) refused by name as expected.*/\1/p')
  s=$(printf '%s\n' "$line" | sed -n 's/.*; [0-9]* refused by name as expected (\(.*\))$/\1/p')
  want="deepwrap-fp64-2048: its depth 2048, a stated depth beside a device (cft-segrun's usage refusal)"
  if [ $rc -eq 0 ] && [ -n "$line" ] && [ "${n:-0}" -gt 0 ] && [ "$r" = 1 ] && [ "$s" = "$want" ]; then
    echo "  ok    $line ($(( $(date +%s) - t0 )) s)"
    echo "        $n cases remade on hip:0, augsum-fp64 among them; 1 refused by name, $want"
  else
    bad+=("corpus.py check --device hip:0: exit $rc - $(grep -m1 '^corpus check: ' "$L/corpus.txt"); its count line: ${line:-none}; it must remake every case but one and refuse that one by name - $want")
  fi
  hip_named "$L/corpus.txt" "the certificate corpus" || bad+=("the certificate corpus: a run did not name the stage's device")
  hip_tier "$L/corpus.txt" "the certificate corpus" generic || bad+=("the certificate corpus: a run's device line says another tier than generic")

  # ---- f. device-test, both legs, and at 2,048 scratch slots (G2B's
  # depth, a few seconds). Since round 2 hip:N publishes the software
  # handle's features, so a NOT COMPARED line (a leg the device cannot be
  # compared on) is a failure; NOT TESTED and NOT RUN are what a tile or an
  # HBM channel it has not got leaves, a NOTE where they move from round
  # 2's counts (17 and 4, 23 and 0, 9 and 4: G2B's, G2C's at the merge)
  echo "== device-test hip:0 -n 96, then -b -n 96, then --scratch-depth 2048 -n 96"
  for e in ":17:4" "-b:23:0" "--scratch-depth 2048:9:4"; do
    b=${e%%:*}; want=${e#*:}
    g="$L/devtest${b:+-${b//[ -]/}}.txt"
    (cd "$H" && hip_cmd "$g" env CFT_HIP_INFO=1 ./device-test hip:0 $b -n 96); rc=$?
    line=$(grep -m1 '^[0-9]* checks, [0-9]* failed' "$g")
    # the lines that name one absence each, not the summary line that counts them
    n=$(grep -v '^not on this device' "$g" | grep -c ': NOT COMPARED')
    f=$(grep -v '^not on this device' "$g" | grep -c ': NOT TESTED')
    s=$(grep -v '^not on this device' "$g" | grep -c ': NOT RUN')
    if [ $rc -eq 0 ] && [ -n "$line" ]; then
      echo "  ok    device-test hip:0 ${b:+$b }-n 96: $line; NOT COMPARED $n, NOT TESTED $f, NOT RUN $s lines ($(grep -m1 '^not on this device' "$g"))"
      [ "$f:$s" = "$want" ] \
        || echo "NOTE  device-test hip:0 ${b:+$b }-n 96: NOT TESTED $f, NOT RUN $s, where round 2 recorded ${want%%:*} and ${want#*:}"
    else
      bad+=("device-test hip:0 ${b:+$b }-n 96: exit $rc (${line:-no summary})")
    fi
    if [ "$n" != 0 ]; then
      grep -v '^not on this device' "$g" | grep ': NOT COMPARED' | sed 's/^ */        /'
      bad+=("device-test hip:0 ${b:+$b }-n 96: $n NOT COMPARED line(s), where hip:N publishes the software handle's features since round 2: $(grep -v '^not on this device' "$g" | grep -m1 ': NOT COMPARED')")
    fi
    hip_named "$g" "device-test${b:+ $b}" || bad+=("device-test${b:+ $b}: it did not name the stage's device")
    hip_tier "$g" "device-test${b:+ $b}" generic || bad+=("device-test${b:+ $b}: its device line says another tier than generic")
  done

  # ---- g. hip-test, leg by leg, the small reductions (the large ones are
  # recorded runs, not the stage's), then round 2's four legs, every
  # format each: aug (G2A), indexed and depth (G2B), divsqrt (G2C).
  # indexed runs at -s all: its 96 MiB source (96 MiB of host memory and
  # as much in the device's source buffer, which both GPUs hold) is read
  # through a table by 200,000 lanes that cross chunk boundaries in a
  # default build - the default build's only crossing of a table's
  # window. A leg must report checks: one that ran none is not a pass.
  echo "== hip-test hip:0 -s small, leg by leg (the open leg ran as the device's probe, above), then aug, indexed (-s all), depth and divsqrt"
  for n in alias two buffers reduce:fp32 reduce:fp64 reduce:fp128 reduce:fp256 \
           seg:fp32 seg:fp64 seg:fp128 seg:fp256 compose:fp32 compose:fp64 compose:fp128 compose:fp256 \
           aug indexed depth divsqrt; do
    f=${n#*:}; [ "$f" = "$n" ] && f=""
    s=small; [ "$n" = indexed ] && s=all
    t0=$(date +%s)
    { echo "\$ CFT_HIP_INFO=1 $H/hip-test hip:0 -l ${n%%:*} -s $s${f:+ -f $f}"
      CFT_HIP_INFO=1 "$H/hip-test" hip:0 -l "${n%%:*}" -s $s ${f:+-f $f} 2>&1; } > "$L/hiptest-${n/:/-}.txt"; rc=$?
    line=$(grep -m1 '^[0-9]* checks, [0-9]* failed' "$L/hiptest-${n/:/-}.txt")
    if [ $rc -eq 0 ] && [ "${line%% *}" -gt 0 ] 2>/dev/null; then
      echo "  ok    hip-test -l ${n%%:*}${f:+ -f $f}$([ $s = all ] && echo ' -s all'): $line ($(( $(date +%s) - t0 )) s)"
      grep ': NOT RUN' "$L/hiptest-${n/:/-}.txt" | sed 's/^ */        /'
    else
      cat "$L/hiptest-${n/:/-}.txt"
      bad+=("hip-test hip:0 -l ${n%%:*} -s $s${f:+ -f $f}: exit $rc (${line:-no summary})$([ "${line%% *}" = 0 ] && echo ' - it ran no check')")
    fi
    hip_named "$L/hiptest-${n/:/-}.txt" "hip-test ${n}" || bad+=("hip-test $n: it did not name the stage's device")
    hip_tier "$L/hiptest-${n/:/-}.txt" "hip-test ${n}" generic || bad+=("hip-test $n: its device line says another tier than generic")
  done

  # ---- h. augmentedAddition through the API (G2A): augmented_check.py on
  # the software handle and through hip:0, as many comparisons on the GPU
  # as the software handle's run of the same script makes here
  echo "== augmented_check.py, the software handle, then --device hip:0"
  t0=$(date +%s)
  (cd "$ROOT" && hip_cmd "$L/augcheck-sw.txt" env CFT_LIB="$H/$SHLIB_NAME" "$PYBIN" -B host/tests/augmented_check.py); r=$?
  (cd "$ROOT" && hip_cmd "$L/augcheck.txt" env CFT_HIP_INFO=1 CFT_LIB="$H/$SHLIB_NAME" "$PYBIN" -B host/tests/augmented_check.py \
     --device hip:0); rc=$?
  s=$(sed -n 's/^augmented_check: \([0-9]*\) comparisons, C == model on every one.*/\1/p' "$L/augcheck-sw.txt")
  h=$(sed -n 's/^augmented_check: \([0-9]*\) comparisons, C == model on every one.*/\1/p' "$L/augcheck.txt")
  if [ $r -eq 0 ] && [ $rc -eq 0 ] && grep -qx 'augmented_check: device hip:0' "$L/augcheck.txt" \
     && [ "${s:-0}" -gt 0 ] && [ "$s" = "$h" ]; then
    echo "  ok    augmented_check through hip:0: $h comparisons, the software handle's $s ($(( $(date +%s) - t0 )) s)"
  else
    bad+=("augmented_check: the software handle exited $r with ${s:-no} comparisons, hip:0 exited $rc with ${h:-no}$(grep -qx 'augmented_check: device hip:0' "$L/augcheck.txt" || echo ', and no line names the device')")
  fi
  hip_named "$L/augcheck.txt" augmented_check || bad+=("augmented_check: it did not name the stage's device")
  hip_tier "$L/augcheck.txt" augmented_check generic || bad+=("augmented_check: its device line says another tier than generic")

  # ---- i. the divide and the square root through the API (G2C):
  # divsqrt_check.py on the software handle, then through hip:0 under each
  # of divsqrt.c's routes, forced on the command line printed: the default
  # (the program route), the whole operation (CFT_DIVSQRT_FULL=1) and,
  # under HIP_FULL=1, the chunk route (CFT_DIVSQRT_SEQ=0), each OK with the
  # software handle's count. They hold bits, not routes: a refused image
  # falls through to the program route and the same bits. The routes are
  # proved in the plants' build, by the route proof (hip_proof) and
  # full-refuse, above.
  echo "== divsqrt_check.py, the software handle, then --device hip:0 under each route"
  (cd "$ROOT" && hip_cmd "$L/dsc-sw.txt" env CFT_LIB="$H/$SHLIB_NAME" "$PYBIN" -B host/tests/divsqrt_check.py); r=$?
  s=$(sed -n 's/^OK: \([0-9]*\) cases, library matches the model exactly$/\1/p' "$L/dsc-sw.txt")
  [ $r -eq 0 ] && [ "${s:-0}" -gt 0 ] || bad+=("divsqrt_check on the software handle: exit $r, ${s:-no} cases")
  echo "  (each run below holds the bits of the route it forces and does not prove that route ran: a refused image falls through to the same bits - the plants' route proof and full-refuse, above, do)"
  for v in default whole chunk; do
    case $v in
      whole) e=CFT_DIVSQRT_FULL=1;;
      chunk) e=CFT_DIVSQRT_SEQ=0
             if [ "${HIP_FULL:-0}" != 1 ]; then echo "  (the chunk route, CFT_DIVSQRT_SEQ=0, runs under HIP_FULL=1)"; continue; fi;;
      *) e="";;
    esac
    t0=$(date +%s)
    f="$L/dsc-$v.txt"
    (cd "$ROOT" && hip_cmd "$f" env CFT_HIP_INFO=1 CFT_LIB="$H/$SHLIB_NAME" $e "$PYBIN" -B host/tests/divsqrt_check.py \
       --device hip:0); rc=$?
    h=$(sed -n 's/^OK: \([0-9]*\) cases, library matches the model exactly$/\1/p' "$f")
    if [ $rc -eq 0 ] && grep -qx 'divsqrt_check: device hip:0' "$f" && [ -n "$h" ] && [ "$h" = "$s" ]; then
      echo "  ok    divsqrt_check through hip:0${e:+, $e}: OK, $h cases, the software handle's $s ($(( $(date +%s) - t0 )) s)"
    else
      bad+=("divsqrt_check --device hip:0${e:+, $e}: exit $rc, ${h:-no} cases against the software handle's ${s:-none} ($(grep -m1 '^FAIL: ' "$f"))")
    fi
    hip_named "$f" "divsqrt_check${e:+ $e}" || bad+=("divsqrt_check${e:+ $e}: it did not name the stage's device")
    hip_tier "$f" "divsqrt_check${e:+ $e}" generic || bad+=("divsqrt_check${e:+ $e}: its device line says another tier than generic")
  done

  # ---- j. the formatOf sets (754-2019 5.4.1), whose divides and roots are
  # cft_div's and cft_sqrt's: made here in a directory of their own, then
  # cft-selftest on sw and on hip:0 under the default route and the whole
  # operation (where the image runs, which the plants' route proof shows,
  # its bits against the vectors; like divsqrt_check, a refused image
  # would fall through to the same bits) and, under HIP_FULL=1, the chunk
  # route; each the sets and cases of the software handle's replay of the
  # same directory in this run
  echo "== the formatOf sets: made, then cft-selftest on sw and on hip:0 under each route"
  t0=$(date +%s)
  if hip_cmd "$L/gen-formatof.txt" "$PYBIN" -B "$ROOT/vectors/gen_vectors.py" --out "$V2" \
       --formats fp32 fp64 fp128 fp256 --rounding rne rtz rdn rup rmm --formatof 8 \
       --augmented 0 --directed 0 --random 0 --simple 0 --transcend 0 --reduce -1 \
       --character 0 --minmaxmag 0 --jobs 4; then
    nd=$(cat "$V2"/*-formatof*.jsonl 2>/dev/null | grep -cE '"fn": *"div"')
    nf=$(cat "$V2"/*-formatof*.jsonl 2>/dev/null | grep -cE '"fn": *"sqrt"')
    echo "hip: the formatOf sets made in $(( $(date +%s) - t0 )) s: $(grep -m1 'SHA256SUMS: the record of' "$L/gen-formatof.txt" | sed 's/.*SHA256SUMS: //'); $nd divides and $nf square roots among their cases"
    [ "$nd" -gt 0 ] && [ "$nf" -gt 0 ] || bad+=("the formatOf sets hold $nd divides and $nf square roots: nothing of cft_div or cft_sqrt to hold")
    (cd "$H" && hip_cmd "$L/formatof-sw.txt" ./cft-selftest "$V2"); r=$?
    s=$(grep -E '^[0-9]+ sets?, [0-9]+ cases, all matching' "$L/formatof-sw.txt" | cut -d'(' -f1)
    n=$(grep -E '^[0-9]+ cases checked' "$L/formatof-sw.txt")
    [ $r -eq 0 ] && [ -n "$s" ] && [ -n "$n" ] || bad+=("the formatOf sets on sw: exit $r (${s:-no sets line}; ${n:-no count})")
    for v in default whole chunk; do
      case $v in
        whole) e=CFT_DIVSQRT_FULL=1;;
        chunk) e=CFT_DIVSQRT_SEQ=0
               if [ "${HIP_FULL:-0}" != 1 ]; then echo "  (the chunk route's replay, CFT_DIVSQRT_SEQ=0, runs under HIP_FULL=1)"; continue; fi;;
        *) e="";;
      esac
      t0=$(date +%s)
      g="$L/formatof-$v.txt"
      (cd "$H" && hip_cmd "$g" env CFT_HIP_INFO=1 $e ./cft-selftest "$V2" hip:0); rc=$?
      h=$(grep -E '^[0-9]+ sets?, [0-9]+ cases, all matching' "$g" | cut -d'(' -f1)
      f=$(grep -E '^[0-9]+ cases checked' "$g")
      if [ $rc -eq 0 ] && [ -n "$h" ] && [ "$h" = "$s" ] && [ -n "$f" ] && [ "$f" = "$n" ]; then
        echo "  ok    the formatOf sets through hip:0${e:+, $e}: sw and hip:0 alike - ${h}; $f ($(( $(date +%s) - t0 )) s)"
      else
        bad+=("the formatOf sets${e:+, $e}: sw ${s:-no sets line} (${n:-no count}), hip:0 exited $rc (${h:-no sets line}; ${f:-no count})")
      fi
      hip_named "$g" "formatOf${e:+ $e}" || bad+=("the formatOf sets${e:+ $e}: the replay did not name the stage's device")
      hip_tier "$g" "formatOf${e:+ $e}" generic || bad+=("the formatOf sets${e:+ $e}: the replay's device line says another tier than generic")
    done
  else
    bad+=("gen_vectors.py, the formatOf sets: it exited nonzero, so nothing of them was replayed")
  fi

  if [ ${#bad[@]} -gt 0 ]; then
    printf 'FAIL  %s\n' "${bad[@]}"
    echo "device: $HIP_INFO"
    return 1
  fi
  echo "hip: every leg green on the device below"
  echo "device: $HIP_INFO"
}
HIP_CORPORA="conf-fp32 conf-fp64 conf-fp128 conf-fp256 routines-fp32 routines-fp64 routines-fp128 routines-fp256 fuzz-fp32 fuzz-fp64 fuzz-fp128 fuzz-fp256 systems bench refuse"
# <hip-fmadiff log> <leg>: its last line names the stage's device. The tool
# links no libcft and prints no CFT_HIP_INFO line, so its own "on <name>
# (<architecture>, bus <bus>)" is held to the stage's device line's name
# and bus (round 3's G3D-1)
hip_fxnamed() {
  local nm bus got
  nm=${HIP_DEV%% (*}
  bus=$(printf '%s\n' "$HIP_DEV" | sed -n 's/.*, bus \([0-9a-fA-F:.]*\), .*/\1/p' | tr 'A-F' 'a-f')
  got=$(sed -n 's/.*, on \(.*\): generic and fixed differ on .*/\1/p' "$1" | tail -n 1)
  case "$(printf '%s' "$got" | tr 'A-F' 'a-f')" in
    "$(printf '%s' "$nm" | tr 'A-F' 'a-f') ("*", bus $bus)") return 0;;
  esac
  echo "  FAIL  $2: its last line names ${got:-no device}, not the stage's device ($nm, bus $bus)"
  return 1
}
need hipcc gpu host-cc python mpmath
stage hip "the GPU backend on this host's GPU through hip:0, in a copy of host/ built with HIP=1: plants first (round 1's four and round 2's twelve, each red on its own check and green without it; with no plant the chunk crossings and the divide's route proof), then study GPU-A's corpora on sw, the GPU and the GPU resident, the same sha256, a bounded vector replay, seq_check at two depths, the certificate corpus's conformance test, device-test, hip-test with round 2's aug, indexed, depth and divsqrt legs, augmented_check, divsqrt_check and the formatOf sets, each leg's log naming its device, every device line the stage's one and its tier word generic; HIP_FULL=1 adds the divide's chunk route; skipped by name without hipcc or a GPU" -- do_hip

# ---- the stage `hip-tier`: the fixed tier on every build (round 3's G3D-1)
# Round 3 put a second implementation of the FMA class under hip:N: fp256's
# and fp128's FMA, ADD, SUB and MUL in cft_run on fma256_fixed.h and
# fma128_fixed.h (G3A, G3A2), and inside programs through the executor's
# lane ALU, k_seq_fx and k_seq_fx128 (G3B), on a handle opened with
# CFT_HIP_TIER=fixed. The default stays generic, libcft's own arithmetic,
# until the overnight proof has passed on both vendors (Logan's answer 3 to
# the round's plan), and `hip` above runs that default alone and keeps its
# meaning. This stage runs the fixed tier on every build. It shares hip's
# set-up (hip_setup and hip_plants_build: the same copy, builds, probe,
# checks, corpora and sums, in directories of its own, with hip-fmadiff and
# hip-progdiff built into both builds), then holds the fixed tier to the
# generic tier, the software handle and the golden model, plants first:
#   * the plants (HIP_TIER_PLANTS), each on its cheapest red, read as a
#     number, its run's device line naming it, and GREEN without it on the
#     same command: round 3's 27 - G3A's and G3A2's seven a format on the
#     elementwise corpora under the tier and on hip-test's `fixed` leg,
#     G3B's thirteen on its `progtier` leg, the cover plants and seqna-aug
#     by the literal test's own sentence, the refuse plants by the route
#     proof alone with the bits green - and beside them hip-fmadiff's own
#     eight on its stream, G3B's lane plants on hip-progdiff and the rmm
#     pair at the routines files' ties and on the referee's file, and the
#     earlier rounds' program plants (seq-mask, seq-deposit) under the tier
#     on the six corpora G3B named. A stray plant on the default build is
#     refused by name, exit 2, by each tool; a refusal is never a red (an
#     unknown name, a plant of the other format, exit 2 from any tool fails
#     the stage, saying which). A plant that does not turn its check red
#     fails the stage by name, and nothing runs after the plants;
#   * the differential streams on the default build, bounded: hip-fmadiff
#     (the two lanes the kernels call, on the device) and hip-progdiff (the
#     same streams as program lanes on two handles, drawn on the host) for
#     FMA, ADD, SUB and MUL at both formats on both streams, every lane
#     green and the first chunk's sums the recorded ones (HIP_TIER_SUMS),
#     so that a stream that changed under the stage is red by name; a
#     failure here stops the stage, as the plants' does;
#   * GPU-A's fifteen corpora under each tier, staged and resident, each
#     output the software handle's sha256 and the routine corpora the
#     golden model's (only the fp128 and fp256 ones can differ between the
#     tiers; the rest are the fixed tier's controls: fp32, fp64 and every
#     program with AUGADD or AUGERR stay on k_seq);
#   * the referee, the arm that is not the generic tier: fma_edge_corpus.py's
#     FMA hard classes at both formats, every expected value the golden
#     model's, through hip-corpus under each tier, the output its .expect;
#   * hip-test's `fixed` and `progtier` legs on the default build (on the
#     plants' build with no plant they are the plants' controls, above,
#     their route proofs read);
#   * seq_check under the tier (`seq`'s command through hip:0 with
#     CFT_HIP_TIER=fixed, the default depth), the golden model the
#     authority: every program compared, 0 MISMATCH (VG3B's mutants of the
#     route's AUGADD scan were red there alone);
#   * its last lines: the tier words seen, the stage's seconds against its
#     ceiling on this device (HIP_TIER_CEILINGS: a NOTE when over, never a
#     FAIL) and the device.
# Each leg's log names its device (hip_named; hip-fmadiff's by its own line,
# hip_fxnamed) and its tier (hip_tier, or the leg's own line where it opens
# both tiers itself). The certificate corpus under the tier is parcel
# G3D-2's, and not this stage's until it lands (its place is marked below).
# `hip-tier` is for `hip` alone: hip-nvcc and hip-source are two more builds
# of the same code in the full census, and get no tier stage (the lead's
# decision, 2026-11-25).
do_hip_tier() {
  local plat dev=${HIP_DEVICE:-0} root=${HIP_ROOT:-/opt/rocm} arch=${HIP_ARCH:-} \
        tree="$RUNDIR/hip-tier-tree" ptree="$RUNDIR/hip-tier-tree-plants" L="$RUNDIR/hip-tier-logs" \
        C="$RUNDIR/hip-tier-corpora" O="$RUNDIR/hip-tier-out" \
        H P t0 ts rc=0 n f b line busl busd pl rd k c s h r g t e vendor what why named lg nd nf q \
        tool st op fl want_in want_out got_in got_g got_f cel nm
  local -a mk bad=() pt=()
  local -A SW=() EXP=()
  ts=$(date +%s)
  hip_setup hip-fmadiff hip-progdiff || return 1

  # ---- the referee's corpora: fma_edge_corpus.py, the FMA's hard classes,
  # every expected value python/cft_golden's (never a kernel's); fp256's
  # file follows --jobs, so --jobs 2 makes it the same on every host
  t0=$(date +%s)
  for f in fp256 fp128; do
    hip_cmd "$L/gen-edge-$f.txt" "$PYBIN" -B "$ROOT/host/tests/fma_edge_corpus.py" "$C" \
        --format $f --count "$HIP_TIER_EDGE" --jobs 2 \
      || { echo "FAIL  fma_edge_corpus.py --format $f"; return 1; }
    EXP[$f]=$(cut -c1-64 "$C/edge-$f.expect")
  done
  echo "hip-tier: the referee's corpora made in $(( $(date +%s) - t0 )) s: edge-fp256 and edge-fp128, $HIP_TIER_EDGE cases each, expect ${EXP[fp256]} and ${EXP[fp128]}"

  # ---- the plants, before anything is believed
  hip_plants_build hip-fmadiff hip-progdiff || return 1
  for b in hip-test hip-corpus hip-fmadiff hip-progdiff; do
    line=$(ldd "$P/$b" 2>&1 | grep -E 'libamdhip64|libcudart' | head -n 1)
    if [ -n "$line" ]; then printf '  ldd    %-14s %s (the plants'"'"' build)\n' "$b" "$(echo $line)"
    else echo "FAIL  ldd $P/$b names no GPU runtime (libamdhip64 or libcudart): a plant's red from it would not be the GPU's"; return 1; fi
  done
  while read -r pl rd f k <&3; do
    [ -n "$pl" ] || continue
    lg="$L/plant-$pl-$rd-$f${k:+-$k}.txt"
    why=""; n=0; line=""
    case $rd in
      elem)       # an elementwise corpus under the tier. The referee's file runs
                  # --sample (pass 1 on 4,096 of its cases, pass 2's five calls
                  # on every case's d): a red there is a red of its whole run,
                  # whose pass 1 holds every case's d
        q=""; [ "${k#edge-}" != "$k" ] && q="--sample 4096:1"
        what="hip-corpus hip:0 $k.bin${q:+ $q}, CFT_HIP_TIER=fixed"
        hip_plant_run "$pl" "$lg" env CFT_HIP_INFO=1 CFT_HIP_TIER=fixed "$P/hip-corpus" hip:0 "$C/$k.bin" "$O/plant-$pl-$k.out" $q; rc=$?
        nd=$(sed -n "s/.* \([0-9]*\) results and \([0-9]*\) flags differ.*/\1/p" "$lg" | head -n 1)
        nf=$(sed -n "s/.* \([0-9]*\) results and \([0-9]*\) flags differ.*/\2/p" "$lg" | head -n 1)
        g=$(grep -c "^pass 2: attribute .* differs from the corpus's expected d\$" "$lg")
        n=$(( ${nd:-0} + ${nf:-0} + g ))
        line="${nd:-no} results and ${nf:-no} flags differing from the corpus's expected values${q:+ in the sample, and $g pass-2 lines of a d differing from them (the first five are printed)}"
        [ $rc -eq 1 ] || why="$why, exited $rc"
        hip_tier "$lg" "plants, $pl" fixed >/dev/null || why="$why, and a device line says another tier than fixed";;
      prog)       # a program corpus under the tier: its output's sha256 against the software handle's
        what="hip-corpus hip:0 $k.bin, CFT_HIP_TIER=fixed"
        hip_plant_run "$pl" "$lg" env CFT_HIP_INFO=1 CFT_HIP_TIER=fixed "$P/hip-corpus" hip:0 "$C/$k.bin" "$O/plant-$pl-$k.out"; rc=$?
        h=$(hip_sum "$O/plant-$pl-$k.out")
        [ -n "$h" ] && [ "$h" != "${SW[$k]}" ] && n=1
        line="sha256 ${h:-none}, the software handle's ${SW[$k]}"
        [ $rc -eq 0 ] || why="$why, exited $rc"
        hip_tier "$lg" "plants, $pl" fixed >/dev/null || why="$why, and a device line says another tier than fixed";;
      leg-fixed*|leg-progtier*)
        t=${rd#leg-}; t=${t%%-*}
        what="hip-test hip:0 -l $t -f $f"
        hip_plant_run "$pl" "$lg" env CFT_HIP_INFO=1 "$P/hip-test" hip:0 -l $t -f $f; rc=$?
        r=$(hip_failed "$lg"); n=${r%%|*}; line=${r#*|}
        [ -n "$r" ] || { n=0; line="no count of failed checks"; }
        [ $rc -eq 1 ] || why="$why, exited $rc"
        grep -q "^  a plant build; the route probe present; CFT_HIP_PLANT $pl; CFT_HIP_TIER of the caller unset\$" "$lg" \
          || why="$why, and the leg's own line does not say a plant build with the probe, the plant and the caller's tier unset"
        case $rd in
          *-cover)    # every printed failure the branch's literal test, by its sentence
            s=$(grep -c '^  FAIL: ' "$lg"); g=$(grep -c '^  FAIL: .*which it does not cover' "$lg")
            [ "$s" -gt 0 ] && [ "$g" = "$s" ] || why="$why, and $g of its $s printed failures are the literal test's refusal (\"which it does not cover\")";;
          *-route)    # the route proof alone, the bits green
            s=$(grep -c '^  FAIL: ' "$lg"); g=$(grep -c "^  FAIL: .*the probe says kernel" "$lg")
            [ "$s" -gt 0 ] && [ "$g" = "$s" ] || why="$why, and $g of its $s printed failures are route lines (\"the probe says kernel\")";;
          *-sent)     # (e): the fixed handle's failed runs refused by the literal test's sentence, none without it
            s=$(sed -n "s/^  (e) the refusals under CFT_HIP_PLANT=$pl: \([0-9]*\) failed runs of the fixed handle refused by the literal test's own sentence, \([0-9]*\) failed without it\$/\1 \2/p" "$lg")
            [ -n "$s" ] && [ "${s% *}" -gt 0 ] && [ "${s#* }" = 0 ] || why="$why, and (e) does not say every failed run of the fixed handle was refused by the literal test's sentence (${s:-no line})";;
          *-proute)   # (e): the route proof red, every other check green
            s=$(sed -n 's/^  (e) the program route proof: .*: \([0-9]*\) not the kernel wanted; every other check of the leg: \([0-9]*\) failed$/\1 \2/p' "$lg")
            [ -n "$s" ] && [ "${s% *}" -gt 0 ] && [ "${s#* }" = 0 ] || why="$why, and (e) does not say the route proof red with every other check green (${s:-no line})";;
        esac;;
      fx)         # hip-fmadiff's own plant, at 2^21 of the study stream (one chunk)
        op=""; [ "$k" != fma ] && op="--op $k"
        what="hip-fmadiff diff 2097152 20261110 $op --format $f"
        hip_plant_run "$pl" "$lg" "$P/hip-fmadiff" diff 2097152 20261110 $op --format $f; rc=$?
        n=$(sed -n 's/.*: generic and fixed differ on \([0-9]*\); .*/\1/p' "$lg" | tail -n 1)
        line="${n:-no} lanes differing"; n=${n:-0}
        [ $rc -eq 1 ] || why="$why, exited $rc"
        grep -q "; plants PLANTS COMPILED IN, CFT_HIP_PLANT=$pl: RED\$" "$lg" || why="$why, and its last line does not name the plant"
        hip_fxnamed "$lg" "plants, $pl" >/dev/null || why="$why, and its last line does not name the stage's device";;
      pd|pd-route) # hip-progdiff on the plants' library, 2^18 lanes of the study stream
        what="hip-progdiff diff 262144 1 --op $k --format $f --sw 4096"
        hip_plant_run "$pl" "$lg" env CFT_HIP_INFO=1 "$P/hip-progdiff" diff 262144 1 --op $k --format $f --sw 4096; rc=$?
        s=$(sed -n 's/.*: generic and fixed differ on \([0-9]*\) lanes (one, chain; staged, resident) and \([0-9]*\) run words; the software handle \([0-9]*\); .*; route \([0-9]*\) runs read, \([0-9]*\) not the kernel wanted; plants .*/\1 \2 \3 \4 \5/p' "$lg" | tail -n 1)
        read -r nd nf g r e <<< "${s:-x x x x x}"
        if [ "$rd" = pd ]; then
          [[ $nd$nf$g =~ ^[0-9]+$ ]] && n=$(( nd + nf + g ))
          line="$nd lanes and $nf run words differing, the software handle $g"
        else
          [[ $nd$nf$g$e =~ ^[0-9]+$ ]] && [ $(( nd + nf + g )) = 0 ] && n=$e
          line="route $r runs read, $e not the kernel wanted; $nd lanes and $nf run words differing"
          [[ $nd$nf$g =~ ^[0-9]+$ ]] && [ $(( nd + nf + g )) = 0 ] || why="$why, and its bits are not green"
        fi
        [ $rc -eq 1 ] || why="$why, exited $rc"
        grep -q "; plants $pl: RED\$" "$lg" || why="$why, and its last line does not name the plant";;
      *) why=", the stage's table names no reader $rd";;
    esac
    case $rd in fx) ;; *) grep -q "^cft hip: .*CFT_HIP_PLANT=$pl\$" "$lg" || why="$why, and no device line names the plant";; esac
    if [ $rc -eq 2 ]; then
      why="$why: a refusal, not a red - $(grep -m1 -iE 'refused|REFUSED|expected one of|is set, and this|acts on the' "$lg" | cut -c1-240)"
    fi
    if [ "${n:-0}" -gt 0 ] 2>/dev/null && [ -z "$why" ]; then
      echo "  RED   plant $pl: $what - $line"
      case $rd in
        fx) grep -m1 '^  DIFF ' "$lg" | sed 's/^ */          the first: /';;
        *) grep -m1 '^  FAIL: ' "$lg" | sed 's/^ */          the first: /';;
      esac
    else
      bad+=("plant $pl did not turn its check red: $what - ${line:-no count}${why}")
    fi
    # a refuse plant's other side: the bits green under it, on its corpus
    case $rd in
      leg-fixed-route|leg-progtier-proute)
        c=conf-$f; [ $rd = leg-progtier-proute ] && c=routines-$f
        g="$L/plant-$pl-bits-$c.txt"
        hip_plant_run "$pl" "$g" env CFT_HIP_INFO=1 CFT_HIP_TIER=fixed "$P/hip-corpus" hip:0 "$C/$c.bin" "$O/plant-$pl-bits.out"; rc=$?
        h=$(hip_sum "$O/plant-$pl-bits.out")
        if [ $rc -eq 0 ] && [ "$h" = "${SW[$c]}" ] && grep -q "^cft hip: .*CFT_HIP_PLANT=$pl\$" "$g"; then
          echo "          the bits green under it: $c on hip:0, CFT_HIP_TIER=fixed, the software handle's sha256"
        else
          bad+=("plant $pl: its bits are not green under it ($c, CFT_HIP_TIER=fixed, exited $rc, sha256 ${h:-none}, the software handle's ${SW[$c]})")
        fi;;
    esac
  done 3<<< "$HIP_TIER_PLANTS"
  # the same commands on the plants' build with no plant: GREEN, so each red was its plant's
  for e in "conf-fp256" "conf-fp128" "edge-fp256 --sample 4096:1" "edge-fp128 --sample 4096:1" \
           "routines-fp64" "routines-fp256" "routines-fp128" "fuzz-fp64" "fuzz-fp256" "fuzz-fp128"; do
    read -r c q <<< "$e"
    g="$L/plant-none-$c.txt"
    hip_cmd "$g" env CFT_HIP_INFO=1 CFT_HIP_TIER=fixed "$P/hip-corpus" hip:0 "$C/$c.bin" "$O/plant-none-$c.out" $q; rc=$?
    case $c in
      conf-*|edge-*) s=$(grep -m1 -oE "[0-9]+ results and [0-9]+ flags (differ|differing)" "$g")
                     [ $rc -eq 0 ] && [ "${s%% *}" = 0 ] && grep -q " 0 results and 0 flags differ" "$g" \
                       && { [ -z "$q" ] || grep -q "equal to the corpus's expected d" "$g"; } \
                       || bad+=("the plants' build with no plant: $c${q:+ $q} under the tier is not green (exit $rc, ${s:-no count})");;
      *) h=$(hip_sum "$O/plant-none-$c.out")
         [ $rc -eq 0 ] && [ "$h" = "${SW[$c]}" ] || bad+=("the plants' build with no plant: $c under the tier is not the software handle's (exit $rc, sha256 ${h:-none})");;
    esac
    hip_tier "$g" "plants, no plant, $c" fixed || bad+=("plant-none-$c: a device line says another tier than fixed")
  done
  for e in "fixed fp256" "fixed fp128" "progtier fp256" "progtier fp128" "progtier fp32"; do
    read -r t f <<< "$e"
    g="$L/plant-none-$t-$f.txt"
    hip_cmd "$g" env CFT_HIP_INFO=1 "$P/hip-test" hip:0 -l $t -f $f; rc=$?
    r=$(hip_failed "$g"); n=${r%%|*}; line=${r#*|}
    why=""
    [ $rc -eq 0 ] && [ "$n" = 0 ] && [ "${line%% *}" -gt 0 ] 2>/dev/null || why=", exited $rc, ${line:-no count of checks}"
    case $line in *", 0 NOT RUN") ;; *) why="$why, and NOT RUN in a plant build, which has the probe and fail-launch";; esac
    if [ $t = fixed ]; then
      s=$(sed -n "s/^  (f) the route proof: \([0-9]*\) calls' kernel read from the probe .*/\1/p" "$g")
      [ "${s:-0}" -gt 0 ] || why="$why, and no route proof read"
      s="the route proof read on ${s:-no} calls"
    else
      s=$(sed -n 's/^  (e) the program route proof: \([0-9]*\) runs. kernel read .*: \([0-9]*\) not the kernel wanted; every other check of the leg: \([0-9]*\) failed$/\1 \2 \3/p' "$g")
      [ -n "$s" ] && [ "${s%% *}" -gt 0 ] && [ "$(echo $s | cut -d' ' -f2-)" = "0 0" ] || why="$why, and its route proof does not say every run the kernel wanted (${s:-no line})"
      s="the route proof read on ${s%% *} runs, each the kernel wanted"
    fi
    if [ -z "$why" ]; then
      echo "  GREEN no plant, hip-test hip:0 -l $t -f $f: $line; $s"
    else
      bad+=("the plants' build with no plant is not green on hip-test hip:0 -l $t -f $f$why")
    fi
  done
  for e in "fp256 fma" "fp256 sub" "fp256 mul" "fp128 fma" "fp128 sub" "fp128 mul"; do
    read -r f k <<< "$e"
    op=""; [ "$k" != fma ] && op="--op $k"
    g="$L/plant-none-fx-$f-$k.txt"
    hip_cmd "$g" "$P/hip-fmadiff" diff 2097152 20261110 $op --format $f; rc=$?
    if [ $rc -eq 0 ] && grep -q ': generic and fixed differ on 0; .*; plants PLANTS COMPILED IN, CFT_HIP_PLANT=none: GREEN$' "$g"; then
      echo "  GREEN no plant, hip-fmadiff diff 2097152 $op --format $f, the plants' build: 0 lanes differing"
    else
      bad+=("the plants' build with no plant: hip-fmadiff --format $f $op is not green (exit $rc)")
    fi
    hip_fxnamed "$g" "plants, no plant, hip-fmadiff $f $k" || bad+=("plant-none-fx-$f-$k: its device is not the stage's")
    g="$L/plant-none-pd-$f-$k.txt"
    hip_cmd "$g" env CFT_HIP_INFO=1 "$P/hip-progdiff" diff 262144 1 --op $k --format $f --sw 4096; rc=$?
    s=$(grep -oE 'route [0-9]+ runs read, [0-9]+ not the kernel wanted; plants none set: GREEN$' "$g")
    if [ $rc -eq 0 ] && grep -q ': generic and fixed differ on 0 lanes (one, chain; staged, resident) and 0 run words; the software handle 0; ' "$g" \
       && [ -n "$s" ] && [ "$(echo "$s" | cut -d' ' -f2)" -gt 0 ] && [ "$(echo "$s" | cut -d' ' -f5)" = 0 ]; then
      echo "  GREEN no plant, hip-progdiff diff 262144 1 --op $k --format $f --sw 4096, the plants' build: 0 lanes differing, $(echo "$s" | sed 's/; plants.*//')"
    else
      bad+=("the plants' build with no plant: hip-progdiff --op $k --format $f is not green with its route read (exit $rc, ${s:-no route line})")
    fi
  done
  # a stray plant on the default build: refused by name, exit 2, by every tool (VG3A's M5)
  for e in "fixed-rmm fx" "fixed-cover fixed" "seqfx-cover progtier" "seqfx-rmm pd"; do
    read -r pl t <<< "$e"
    g="$L/plant-stray-$t.txt"
    case $t in
      fx) what="hip-fmadiff"
          hip_plant_run "$pl" "$g" "$H/hip-fmadiff" diff 2097152 20261110; rc=$?
          s="is set, and this hip-fmadiff is a default build, which has no plants";;
      pd) what="hip-progdiff"
          hip_plant_run "$pl" "$g" env CFT_HIP_INFO=1 "$H/hip-progdiff" diff 262144 1; rc=$?
          s="is set, and this libcft is a default build (no cfth_plant_tier_probe), which has no plants";;
      *)  what="hip-test -l $t"
          hip_plant_run "$pl" "$g" env CFT_HIP_INFO=1 "$H/hip-test" hip:0 -l $t -f fp256; rc=$?
          s="$t: REFUSED - CFT_HIP_PLANT=\"$pl\" is set, and this libcft is a default build";;
    esac
    if [ $rc -eq 2 ] && grep -qF -- "$s" "$g"; then
      echo "  ok    a stray plant on the default build: CFT_HIP_PLANT=$pl through $what refused by name, exit 2"
    else
      bad+=("a stray CFT_HIP_PLANT=$pl on the default build: $what exited $rc, not 2 with its sentence (\"$s\")")
    fi
  done
  # every libcft run above named the stage's device (hip-fmadiff's runs are
  # held by their own line, hip_fxnamed; a refused stray plant ran nothing)
  for f in "$L"/plant-*.txt; do
    case $(basename "$f") in plant-*-fx-*|plant-stray-*) continue;; esac
    hip_named "$f" "plants, $(basename "$f" .txt)" || bad+=("$(basename "$f" .txt): its device is not the stage's")
  done
  if [ ${#bad[@]} -gt 0 ]; then
    printf 'FAIL  %s\n' "${bad[@]}"
    echo "FAIL  the plants: a check a plant cannot turn red proves nothing, so no leg runs after them"
    return 1
  fi
  echo "hip-tier: every plant RED, and GREEN without it"

  # ---- the differential streams on the default build, held to the record
  echo "== the differential streams (the default build): hip-fmadiff, $HIP_TIER_FMADIFF_N lanes a run at seed $HIP_TIER_FMADIFF_SEED; hip-progdiff, $HIP_TIER_PROGDIFF_N at seed $HIP_TIER_PROGDIFF_SEED"
  while read -r tool f st op want_in want_out <&3; do
    [ -n "$tool" ] || continue
    q=""; [ $op != fma ] && q="--op $op"
    g="$L/stream-$tool-$f-$st-$op.txt"
    t0=$(date +%s)
    if [ $tool = fmadiff ]; then
      hip_cmd "$g" "$H/hip-fmadiff" diff "$HIP_TIER_FMADIFF_N" "$HIP_TIER_FMADIFF_SEED" $q --stream $st --format $f; rc=$?
      line=$(grep -E '^diff --format .*: (GREEN|RED)$' "$g" | tail -n 1)
      n=$(printf '%s\n' "$line" | sed -n 's/.*: generic and fixed differ on \([0-9]*\); .*/\1/p')
      hip_fxnamed "$g" "stream $tool $f $st $op" || bad+=("stream hip-$tool $f $st $op: its device is not the stage's")
    else
      hip_cmd "$g" env CFT_HIP_INFO=1 "$H/hip-progdiff" diff "$HIP_TIER_PROGDIFF_N" "$HIP_TIER_PROGDIFF_SEED" --op $op --stream $st --format $f; rc=$?
      line=$(grep -E '^progdiff --format .*: (GREEN|RED)$' "$g" | tail -n 1)
      s=$(printf '%s\n' "$line" | sed -n 's/.*: generic and fixed differ on \([0-9]*\) lanes (one, chain; staged, resident) and \([0-9]*\) run words; the software handle \([0-9]*\); .*/\1 \2 \3/p')
      n=x; [ -n "$s" ] && n=$(( $(echo $s | tr ' ' '+') ))
      grep -qE '^  one   the fixed handle.s lanes against the stream.s fixed lane on the host \(deposit and five flags\): [1-9][0-9]* lanes, 0 differ$' "$g" \
        || n="${n}, and the host lane check not green"
      hip_named "$g" "stream $tool $f $st $op" || bad+=("stream hip-$tool $f $st $op: its device is not the stage's")
      [ "$(hip_devlines "$g" | grep -cF '; tier generic, ')" = 1 ] && [ "$(hip_devlines "$g" | grep -cF '; tier fixed, ')" = 1 ] \
        || bad+=("stream hip-$tool $f $st $op: its device lines are not one generic handle's and one fixed handle's")
    fi
    got_in=$(printf '%s\n' "$line" | sed -n 's/.* sha256 inputs \([0-9a-f]*\), generic \([0-9a-f]*\), fixed \([0-9a-f]*\);.*/\1/p')
    got_g=$(printf '%s\n' "$line" | sed -n 's/.* sha256 inputs \([0-9a-f]*\), generic \([0-9a-f]*\), fixed \([0-9a-f]*\);.*/\2/p')
    got_f=$(printf '%s\n' "$line" | sed -n 's/.* sha256 inputs \([0-9a-f]*\), generic \([0-9a-f]*\), fixed \([0-9a-f]*\);.*/\3/p')
    why=""
    [ $rc -eq 0 ] && [ "$n" = 0 ] && [ "${line##*: }" = GREEN ] || why="$why; exited $rc, ${n:-no count of} lanes differing"
    [ "$got_in" = "$want_in" ] || why="$why; the first chunk's inputs ${got_in:-none}, not the recorded $want_in - not the stream on record"
    [ "$got_g" = "$want_out" ] && [ "$got_f" = "$want_out" ] || why="$why; the first chunk's outputs generic ${got_g:-none} and fixed ${got_f:-none}, not the recorded $want_out"
    if [ -z "$why" ]; then
      echo "  ok    hip-$tool $f $st $op: 0 lanes differing, the first chunk the recorded sums (inputs ${want_in:0:16}..., generic = fixed ${want_out:0:16}...), $(( $(date +%s) - t0 )) s"
    else
      bad+=("the stream hip-$tool --format $f --stream $st --op $op${why}")
    fi
  done 3<<< "$HIP_TIER_SUMS"
  if [ ${#bad[@]} -gt 0 ]; then
    printf 'FAIL  %s\n' "${bad[@]}"
    echo "FAIL  the streams: a tier that differs from the generic tier, or a stream that is not the one on record, so nothing runs after them"
    return 1
  fi

  # ---- the corpora under both tiers: sw, hip:0 and hip:0 --resident, the same sha256
  echo "== corpora (docs/studies/gpu-a) under each tier: hip:0 and hip:0 --resident against sw (and the golden model's where it has one)"
  printf '%-15s %-64s %-9s %-9s %-9s %-9s %s\n' corpus sw "generic" resident "fixed" resident golden
  for t in generic fixed; do : > "$L/corpora-$t.txt"; done
  for c in $HIP_CORPORA; do
    for t in generic fixed; do
      { echo "\$ CFT_HIP_INFO=1 CFT_HIP_TIER=$t $H/hip-corpus hip:0 $C/$c.bin $O/$c.$t"
        CFT_HIP_INFO=1 CFT_HIP_TIER=$t "$H/hip-corpus" hip:0 "$C/$c.bin" "$O/$c.$t" 2>&1; } > "$L/$t-$c.txt"; r=$?
      { echo "\$ CFT_HIP_INFO=1 CFT_HIP_TIER=$t $H/hip-corpus hip:0 $C/$c.bin $O/$c.$t-res --resident"
        CFT_HIP_INFO=1 CFT_HIP_TIER=$t "$H/hip-corpus" hip:0 "$C/$c.bin" "$O/$c.$t-res" --resident 2>&1; } > "$L/$t-res-$c.txt"; rc=$?
      cat "$L/$t-$c.txt" "$L/$t-res-$c.txt" >> "$L/corpora-$t.txt"
      h=$(hip_sum "$O/$c.$t"); s=$(hip_sum "$O/$c.$t-res")
      [ $r -eq 0 ] && [ $rc -eq 0 ] && [ "$h" = "${SW[$c]}" ] && [ "$s" = "${SW[$c]}" ] \
        || bad+=("$c under CFT_HIP_TIER=$t: hip:0 exited $r and --resident $rc; sha256 sw ${SW[$c]}, hip:0 ${h:-none}, resident ${s:-none}")
      EXP[$c-$t]=$(hip_same "$h" "${SW[$c]}"); EXP[$c-$t-res]=$(hip_same "$s" "${SW[$c]}")
    done
    g="-"; [ -f "$C/$c.golden" ] && g=$(hip_sum "$C/$c.golden")
    [ "$g" = "-" ] || [ "$g" = "${SW[$c]}" ] || bad+=("$c: the golden model's output $g is not the software handle's ${SW[$c]}")
    printf '%-15s %-64s %-9s %-9s %-9s %-9s %s\n' "$c" "${SW[$c]}" "${EXP[$c-generic]}" "${EXP[$c-generic-res]}" \
      "${EXP[$c-fixed]}" "${EXP[$c-fixed-res]}" "$( [ "$g" = - ] && echo - || hip_same "$g" "${SW[$c]}")"
  done
  cat "$L/corpora-generic.txt" "$L/corpora-fixed.txt"
  for t in generic fixed; do
    hip_named "$L/corpora-$t.txt" "corpora, $t" || bad+=("the corpora under CFT_HIP_TIER=$t: a run did not name the stage's device")
    hip_tier "$L/corpora-$t.txt" "corpora, $t" $t || bad+=("the corpora under CFT_HIP_TIER=$t: a run's device line says another tier")
  done

  # ---- the referee: the golden model's expected values, under each tier
  echo "== the referee: fma_edge_corpus.py's corpora through hip-corpus hip:0 under each tier, staged, against their .expect (the golden model's)"
  for f in fp256 fp128; do
    for t in generic fixed; do
      g="$L/edge-$f-$t.txt"
      t0=$(date +%s)
      hip_cmd "$g" env CFT_HIP_INFO=1 CFT_HIP_TIER=$t "$H/hip-corpus" hip:0 "$C/edge-$f.bin" "$O/edge-$f.$t"; rc=$?
      h=$(hip_sum "$O/edge-$f.$t")
      if [ $rc -eq 0 ] && grep -q "against the corpus's expected values 0 results and 0 flags differ" "$g" && [ "$h" = "${EXP[$f]}" ]; then
        echo "  ok    the referee edge-$f under CFT_HIP_TIER=$t: 0 results and 0 flags differ, sha256 its .expect ${EXP[$f]:0:16}... ($(( $(date +%s) - t0 )) s)"
      else
        bad+=("the referee edge-$f under CFT_HIP_TIER=$t: exit $rc, $(grep -m1 -oE "[0-9]+ results and [0-9]+ flags differ" "$g"), sha256 ${h:-none}, its .expect ${EXP[$f]}")
      fi
      hip_named "$g" "the referee, edge-$f $t" || bad+=("the referee edge-$f $t: it did not name the stage's device")
      hip_tier "$g" "the referee, edge-$f $t" $t || bad+=("the referee edge-$f $t: its device line says another tier")
    done
  done

  # ---- hip-test's fixed and progtier legs on the default build
  echo "== hip-test hip:0 -l fixed, then -l progtier (the default build: each opens its own handles at each tier)"
  for t in fixed progtier; do
    g="$L/leg-$t.txt"
    t0=$(date +%s)
    hip_cmd "$g" env CFT_HIP_INFO=1 "$H/hip-test" hip:0 -l $t; rc=$?
    line=$(grep -m1 '^[0-9]* checks, [0-9]* failed' "$g")
    if [ $rc -eq 0 ] && [ "${line%% *}" -gt 0 ] 2>/dev/null && [ "$(echo "$line" | cut -d' ' -f3)" = 0 ] \
       && grep -q '^  a default build; the route probe absent; CFT_HIP_PLANT unset; CFT_HIP_TIER of the caller unset$' "$g"; then
      echo "  ok    hip-test -l $t: $line ($(( $(date +%s) - t0 )) s); the caller's CFT_HIP_TIER unset"
      grep ': NOT RUN' "$g" | sed 's/^ */        /'
    else
      bad+=("hip-test hip:0 -l $t (the default build): exit $rc (${line:-no summary})$(grep -q 'CFT_HIP_TIER of the caller unset$' "$g" || echo ', and its line does not say the caller'"'"'s CFT_HIP_TIER unset')")
    fi
    hip_named "$g" "hip-test $t" || bad+=("hip-test $t: it did not name the stage's device")
  done

  # ---- seq_check under the tier: the golden model the authority
  echo "== seq_check --device hip:0, CFT_HIP_TIER=fixed"
  t0=$(date +%s)
  f="$L/seq-fixed.txt"
  (cd "$ROOT" && hip_cmd "$f" env CFT_HIP_INFO=1 CFT_HIP_TIER=fixed CFT_LIB="$H/$SHLIB_NAME" "$PYBIN" -B host/tests/seq_check.py \
     --trials 250 --formats fp32 fp64 fp128 fp256 --device hip:0); rc=$?
  if [ $rc -eq 0 ] && grep -q '^device hip:0: backend hip,' "$f" && ! grep -q 'MISMATCH' "$f" \
     && grep -qx '  it publishes every bit cft.h defines' "$f" \
     && grep -qx 'the device refused no program for a bit it lacks: every program was compared' "$f"; then
    echo "  ok    seq_check through hip:0 under CFT_HIP_TIER=fixed, $(( $(date +%s) - t0 )) s: $(grep -m1 '^device hip:0: backend hip,' "$f")"
    grep -E 'routine-corpus( \([a-z]+\))? programs compared' "$f" | sed 's/^ */        /'
  else
    bad+=("seq_check --device hip:0 under CFT_HIP_TIER=fixed: exit $rc, $(grep -c MISMATCH "$f") MISMATCH line(s)$(grep -q 'every program was compared' "$f" || echo ', and no line says every program was compared')")
  fi
  hip_named "$f" "seq_check, fixed" || bad+=("seq_check under the tier: it did not name the stage's device")
  hip_tier "$f" "seq_check, fixed" fixed || bad+=("seq_check under the tier: its device line says another tier than fixed")

  # ---- (the certificate corpus under the tier: parcel G3D-2's item 11, here when it lands)

  if [ ${#bad[@]} -gt 0 ]; then
    printf 'FAIL  %s\n' "${bad[@]}"
    echo "device: $HIP_INFO"
    return 1
  fi
  n=$(( $(date +%s) - ts ))
  nm=${HIP_DEV%% (*}
  cel=$(printf '%s\n' "$HIP_TIER_CEILINGS" | tr ';' '\n' | sed -n "s/^$nm=\([0-9]*\)\$/\1/p")
  echo "hip-tier: every leg green on the device below; its device lines' tier words: $(cat "$L"/*.txt | grep -a '^cft hip: hip:0 = ' | grep -oE '; tier [a-z]+, ' | sort | uniq -c | sed -E 's/^ *([0-9]+) ; tier ([a-z]+), /\2 \1/' | tr '\n' ',' | sed 's/,$//; s/,/, /g')"
  if [ -z "$cel" ]; then
    echo "NOTE  hip-tier: $n s; no ceiling on record for $nm (HIP_TIER_CEILINGS, docs/VERIFICATION.md's row)"
  elif [ "$n" -gt "$cel" ]; then
    echo "NOTE  hip-tier: $n s, past its ceiling of $cel s on $nm (docs/VERIFICATION.md's row): a slow machine is not a wrong answer; re-measure the ceiling if a change moved it"
  else
    echo "hip-tier: $n s, within its ceiling of $cel s on $nm (docs/VERIFICATION.md's row)"
  fi
  echo "device: $HIP_INFO"
}
# The stage's tables. Its plants, each on its cheapest red (measured on both
# GPUs at the base, docs/VALIDATION.md's G3D-1 entry): <plant> <reader>
# <format> [<corpus or op>], the readers in do_hip_tier.
HIP_TIER_PLANTS="
fixed-rmm elem fp256 conf-fp256
fixed-flag elem fp256 conf-fp256
fixed-steer leg-fixed fp256
fixed-mulsign leg-fixed fp256
fixed-scalar leg-fixed fp256
fixed-cover leg-fixed-cover fp256
fixed-refuse leg-fixed-route fp256
fixed128-rmm elem fp128 conf-fp128
fixed128-flag elem fp128 conf-fp128
fixed128-steer leg-fixed fp128
fixed128-mulsign leg-fixed fp128
fixed128-scalar leg-fixed fp128
fixed128-cover leg-fixed-cover fp128
fixed128-refuse leg-fixed-route fp128
seqfx-rmm leg-progtier fp256
seqfx-flag leg-progtier fp256
seqfx-steer leg-progtier fp256
seqfx-mulsign leg-progtier fp256
seqfx-cover leg-progtier-sent fp128
seqna-aug leg-progtier-sent fp32
seqfx-refuse leg-progtier-proute fp256
seqfx128-rmm leg-progtier fp128
seqfx128-flag leg-progtier fp128
seqfx128-steer leg-progtier fp128
seqfx128-mulsign leg-progtier fp128
seqfx128-cover leg-progtier-sent fp256
seqfx128-refuse leg-progtier-proute fp128
fixed-rmm fx fp256 fma
fixed-flag fx fp256 fma
fixed-steer fx fp256 sub
fixed-mulsign fx fp256 mul
fixed128-rmm fx fp128 fma
fixed128-flag fx fp128 fma
fixed128-steer fx fp128 sub
fixed128-mulsign fx fp128 mul
seqfx-rmm pd fp256 fma
seqfx-flag pd fp256 fma
seqfx-steer pd fp256 sub
seqfx-mulsign pd fp256 mul
seqfx-refuse pd-route fp256 fma
seqfx128-rmm pd fp128 fma
seqfx128-flag pd fp128 fma
seqfx128-steer pd fp128 sub
seqfx128-mulsign pd fp128 mul
seqfx128-refuse pd-route fp128 fma
seqfx-rmm prog fp256 routines-fp256
seqfx128-rmm prog fp128 routines-fp128
fixed-rmm elem fp256 edge-fp256
fixed128-rmm elem fp128 edge-fp128
seq-mask prog fp64 routines-fp64
seq-mask prog fp256 routines-fp256
seq-mask prog fp128 routines-fp128
seq-deposit prog fp64 fuzz-fp64
seq-deposit prog fp256 fuzz-fp256
seq-deposit prog fp128 fuzz-fp128
"
# The streams' lanes a run (sized on both GPUs at the base: G3D-1's entry)
# and seeds. hip-fmadiff's first chunk is min(N, 2^21) lanes and
# hip-progdiff's min(N, 2^19), so these N give the chunks the sums below
# were recorded on; hip-progdiff's seed is 1, G3B's, whose are its only sums
# on record. The referee's cases a format.
HIP_TIER_FMADIFF_N=67108864
HIP_TIER_FMADIFF_SEED=20261110
HIP_TIER_PROGDIFF_N=524288
HIP_TIER_PROGDIFF_SEED=1
HIP_TIER_EDGE=131250
# The first chunk's sha256s on record, the same on both vendors: <tool>
# <format> <stream> <op> <the inputs> <the output, generic = fixed>.
# hip-fmadiff's: fp256's study stream GPU-A's (docs/studies/gpu-a/captured/
# part2-extra.txt), its edge stream G3A's, fp128's G3A2's (docs/VALIDATION.md,
# their entries); hip-progdiff's G3B's (its entry, "The program
# differential"); every one reproduced at the base by G3D-1.
HIP_TIER_SUMS="
fmadiff fp256 study fma b07642724a9ebae30acb76fd0df3e7ca34f23397c62d9ee81b0b1f5a9d40918b 0bb5295edfc0754f893cd7bb5ce169175fdc3f9263271597f54d90ffcf03adc9
fmadiff fp256 study add 21ae7619bd17863f2b7d4bd4ded47b8be1310bd24e033d464db4d46c18b9419e b2b0aa080494f8e9b51a0a10a1579c4b9f5b3fb69593618d12304396cc295f73
fmadiff fp256 study sub 86ad800f077a685a202ca4469e6c7c36f445ccb34eec5802efe5e065296494ba b2b0aa080494f8e9b51a0a10a1579c4b9f5b3fb69593618d12304396cc295f73
fmadiff fp256 study mul b07642724a9ebae30acb76fd0df3e7ca34f23397c62d9ee81b0b1f5a9d40918b c59668cd06e62d3066579bf173f9e36e4cb80c3315f0d6c4e40b3843eeac4c55
fmadiff fp256 edge fma f79642a4244dea6a0239d854afda2f85c96bf96b56755f5ff552c46e027d3cec 164856ff7af28b95d1135a85cc976e9b27c5bffd0d45190264769f2a2dd828a8
fmadiff fp256 edge add b5ce004f068949322c099b0394cae69e9b545d73344a97e60db43334f1097d3f f2bd1bfbcea4e1a59199dd362527204d273688393796b0ca41d02f32d41ca070
fmadiff fp256 edge sub 3ea77a84c67c99331cc6956758b38d9b8dc624d95c0b09235d81fbbe98ab49b9 f2bd1bfbcea4e1a59199dd362527204d273688393796b0ca41d02f32d41ca070
fmadiff fp256 edge mul f79642a4244dea6a0239d854afda2f85c96bf96b56755f5ff552c46e027d3cec 78369da118c7a6ce8e37e7d13864783d856a1d4c8b1a81180f986c112d97b13b
fmadiff fp128 study fma 19f9e1a1c38af69f403964c9a5e9ecb03a805b6422abba623f51e8ec18a55281 cbea6f91d1973fc235187d54322c15dd63e7961e400c1d77b2ffe4d2a10218fc
fmadiff fp128 study add 6c6a0602cea80e44b6c1bca41d43682fb9ee6e8c1fe9644b3811d942e7bc40fd 8033fe389c52a80ec2b8c4c9e6072c3a078229d114e8a8f22227505990066611
fmadiff fp128 study sub be06221932c2add1a8b3f85bdac801437f1a8425a7a3a6a06aec2f8d757425ea 8033fe389c52a80ec2b8c4c9e6072c3a078229d114e8a8f22227505990066611
fmadiff fp128 study mul 19f9e1a1c38af69f403964c9a5e9ecb03a805b6422abba623f51e8ec18a55281 dba8a2b2c7a8466376112bc4a95eff5746204e0adb67e8ad60d6c79c2a58b6e4
fmadiff fp128 edge fma 7959679a4197eadec84b0ac66ff8f3ac8375e419a1d787216e3f7dfb6ea8c5a3 160ea435c932a0f301618e418c65907e893c40336087d23bfb3d1aabc2884f2c
fmadiff fp128 edge add 54b69914979fbfbaebb95aec42c5dfa438a126f6114cf603f21840c5e563886c 9a9ace6810bc36162d4d860f26d1e870e7a1723d630371f295cb8ebe59571b53
fmadiff fp128 edge sub fec40efa7fd3113acdf02b107f0da78cbc78246e205c7569edcda28a6dfe23fc 9a9ace6810bc36162d4d860f26d1e870e7a1723d630371f295cb8ebe59571b53
fmadiff fp128 edge mul 7959679a4197eadec84b0ac66ff8f3ac8375e419a1d787216e3f7dfb6ea8c5a3 1c97ce88e345f1aba09c796eb8a9e248738f12edd12cf3a9dc5c8e2a639cf2f9
progdiff fp256 study fma 56811b4b111b0f5a104d1fec5f7c5dc899875416e59134851ce9ea2393dbc331 4759cf91dd3144b95b8f9a508bb631c9b3184dea23e1d547cad50692b0c2ff7b
progdiff fp256 study add e5382b6fda4b50938af06c266d5adae3d16126615e0fc93addb7979f5650714f 471c7909c9a1081ecc82b32cace3b11648fa5be5679dbc9ea1945406eecfa2e3
progdiff fp256 study sub 51bb40ef7e0a6cb153276325ac72e7f4a4ea8923d65fd0dd0866bbed4c2dd959 6f696e6cf3c86ffb43089c663173152546011af45c123c9eec08ebb060637a72
progdiff fp256 study mul 56811b4b111b0f5a104d1fec5f7c5dc899875416e59134851ce9ea2393dbc331 e2cd324c8ab01397885aa4099fcd9fbddb6351b2009199a271466160fb6d4375
progdiff fp256 edge fma baa717128dbc36a44bdf3bbdadd1dbedee7cb335b66ec1db1353c3bad45dd6eb a4bcf7be20f23aeb9fe7dd86d43c08a91ce8a33c689688893ab5930a82c3b51e
progdiff fp256 edge add 0a0599ce1388b86bbbb3ebcd47843994f557ce529229d4078f4c509c39c9d892 2e246758051cde7890ebd048fcac6905f63316466f1dc12970b20fa89afee4b9
progdiff fp256 edge sub a7e92e8d646496c9b5bffd966cee7976c696914233cf9411a58d15e0d1a3eac3 7cc221ea18507688922d4f9f3dbce658a6832b0fdc1b0c06abb90e2ef5118937
progdiff fp256 edge mul baa717128dbc36a44bdf3bbdadd1dbedee7cb335b66ec1db1353c3bad45dd6eb fd53f4798e68d5fbc799cebf6a6f2bc269dad6423aa787995745ad2cabe8a477
progdiff fp128 study fma 3343ba173a3504c598e1cb178cd95d24c50159e183d24cb695abe8b0f7187d5d eabc49bcbc79c5bb41c28e74fe91647e4e8b2df13b59a302e052370f572f7b9a
progdiff fp128 study add 4c00fb1e081bdb115993884d2f7ee02da569787049d81e6d78b9722dff8563c0 ae41133ba905b49a3d3b23027f2ac30a46ebb3435e400bf9e11c09ea0702606c
progdiff fp128 study sub 07e7349e600858c47ac79a1639f0d6365e89e876aee630362ce68e493fb7ebb8 ad2020390e93b13204c76dfbd84be0a6a0f3b13b0c9a57b81754f9c9a97c1c6d
progdiff fp128 study mul 3343ba173a3504c598e1cb178cd95d24c50159e183d24cb695abe8b0f7187d5d 0a103b64271247f14587b7f20318e5f5eeee6a9541de2e996dd4cb7c268bb642
progdiff fp128 edge fma 26728df98926a6b4510a84886ab138b32162948af7890cc4b7c4670161fc2838 c1449166a75ce5eb9ac817c7c00b8a0f06050adca4a323b1f68b6408bfad0fe1
progdiff fp128 edge add 937df6c4584b42e87e092723966fb6c1de3c3f228d726aa764cc18b215298123 d7f8435d7d5db3b645b8a8aab07112acb603d429d41ac1310f0d152c4ce756b5
progdiff fp128 edge sub 0c81b277518a4ce3af2490336e8f40bcb96325beb37c2169394738287017bd23 aded6daaf1fbad2b594dd18072151e795e6b2ef8b02729c9145faa2201f491b7
progdiff fp128 edge mul 26728df98926a6b4510a84886ab138b32162948af7890cc4b7c4670161fc2838 6dd6b90286c230f6d7ad112c424d1916e4229ce1f77363afd172fbed6bce62fe
"
# hip-tier's ceilings, a device's name (its CFT_HIP_INFO line's) = seconds:
# docs/VERIFICATION.md's row, the next 100 s above the slower of two quiet
# runs at the commit the row names. The stage prints its seconds against
# its device's, a NOTE when over and never a FAIL; verify/test-hip-stage.sh
# holds this line and the row to each other.
HIP_TIER_CEILINGS="NVIDIA GeForce RTX 5060 Ti=1100;AMD Radeon RX 7600=1200"
need hipcc gpu host-cc python mpmath
stage hip-tier "the GPU backend's fixed tier (CFT_HIP_TIER=fixed, round 3) on this host's GPU through hip:0, beside hip and sharing its set-up: plants first (round 3's 27, each on its cheapest red and green without it, the differentials' own, the earlier rounds' program plants under the tier, a stray plant refused by name), then the differential streams held to their recorded sums, GPU-A's corpora under each tier against sw, the golden referee under each tier, hip-test's fixed and progtier legs and seq_check under the tier, each leg's log naming its device and its tier, its seconds against its ceiling; skipped by name without hipcc or a GPU" -- do_hip_tier

# The same stage on the two other ways to build the backend for NVIDIA
# (plan decision 3; Logan, 2026-11-10: "install CUDA 13 and make the recipe
# a stage"), each in the full census alone: they need a toolchain the gate's
# hosts do not have. `hip-nvcc` is plain nvcc and no HIP at all,
# host/Makefile's HIP_PLATFORM=cuda, through study GPU-A's header extended
# for the backend (docs/studies/gpu-a/cudahip); HIP_CUDA chooses the CUDA.
# `hip-source` is HIP built from ROCm's own sources for NVIDIA, the study
# GPU-B's recipe, which verify/build-hip-nvidia.sh makes from pinned tags
# into HIPSRC_ROOT (default verify/_hip-nvidia-prefix; it downloads, so it
# is run by hand, never by a stage), under CUDA 13 (HIPSRC_CUDA, default
# /usr/local/cuda-13.3: the recipe needs no patch there). Each is skipped by
# name without its toolchain, as `images` is without IMAGES, or without an
# NVIDIA GPU. Both hold the GPU to everything `hip` does: the same legs, the
# same plants, the same sums.
do_hip_nvcc() { HIP_PLATFORM=cuda do_hip; }
HIP_PLATFORM=cuda need nvcc gpu host-cc python mpmath
stage hip-nvcc "the GPU backend built by plain nvcc with no HIP (HIP_PLATFORM=cuda through study GPU-A's header) on this host's NVIDIA GPU, held as the hip stage holds it: plants first, the same corpora, sums, vectors, seq_check, certificate corpus, device-test and hip-test, each leg's log naming its device, every device line the stage's one; skipped by name without nvcc or an NVIDIA GPU" -- do_hip_nvcc

hipsrc_root() { echo "${HIPSRC_ROOT:-$ROOT/verify/_hip-nvidia-prefix}"; }
do_hip_source() {
  HIP_ROOT=$(hipsrc_root) HIP_PLATFORM=nvidia HIP_CUDA=${HIPSRC_CUDA:-/usr/local/cuda-13.3} do_hip
}
HIP_ROOT=$(hipsrc_root) HIP_PLATFORM=nvidia need hipsrc gpu host-cc python mpmath
stage hip-source "the GPU backend built by HIP compiled from ROCm's own sources for NVIDIA (HIPSRC_ROOT, made by verify/build-hip-nvidia.sh from pinned tags) under CUDA 13, held as the hip stage holds it: plants first, the same corpora, sums, vectors, seq_check, certificate corpus, device-test and hip-test, each leg's log naming its device, every device line the stage's one; skipped by name without that prefix or an NVIDIA GPU" -- do_hip_source

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
