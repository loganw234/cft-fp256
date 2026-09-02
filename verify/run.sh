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
#   * The exit code is the verdict: nonzero iff any stage FAILED
#     (or, under --require-all, was skipped).
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
    PATH="/c/msys64/mingw64/bin:$PATH" make -C "$ROOT/host" CC=gcc \
      OS=Windows_NT TMP="$WTMP" TEMP="$WTMP" "$@"
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
    --resume) if [ $# -gt 1 ] && [[ ${2:-} != --* ]]; then RESUME=$2; shift 2
              else RESUME=last; shift; fi;;
    --fresh)  FRESH=1; shift;;
    --require-all) REQUIRE_ALL=1; shift;;
    --list)   LIST=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

# KEEP IN STEP with the `stage` calls below. This block is written by
# hand, which makes it a second source of truth for a list that already
# drifted once: clause5 and mpfr were added to the run without being
# added here, and the sim line claimed 15 cocotb targets after the
# aggregate grew to 17. If you add a stage, add a line here in the same
# order, or --list quietly lies about what `make verify` does.
if [ "$LIST" = 1 ]; then
  cat <<'EOF'
golden       golden-model pytest suite (the definition of correct)
vectors      regenerate the conformance sets from the model
sim          cocotb RTL suite, all 17 targets (docker cft-sim)
lint         yosys elaboration gate, every RTL file (docker cft-sim)
formal       property proofs + negative control (docker cft-formal)
libcft       host library: build + contract tests + conformance replay
selfcheck    device-test harness, software-vs-software full matrix
divsqrt      cft_div/cft_sqrt + seeds vs the model, per-element flags
clause5      the clause-5 completion set vs the model, all entry points
diff         library vs model over the alignment boundary
seq          the sequencer: C vs model over fuzzed programs
reduce       reduction ranges: C vs model
bindings     the cftmpfr drop-in vs gmpy2's IEEE emulation
mpfr         MPFR parity - the only external oracle reaching fp128/fp256
soak-quick   native-oracle soak, QUICK depth + sabotage control
images       hw/verify-image.sh over $IMAGES (XRT hosts, if staged)
EOF
  exit 0
fi

# ---- stage-name validation ------------------------------------------
# A typo'd --only used to select NOTHING, print "PASS, nothing
# skipped", and crash the census mid-print with an unbound variable -
# exit 0. A compliance runner must refuse names it does not know.
# THIRD copy of the stage names, after the --list heredoc above and the
# `stage` calls below. All three are hand-maintained and all three must
# be edited together; clause5 and mpfr had already reached two of the
# three, and `bindings` needed all three. If this list grows again,
# deriving it is worth more than another comment.
STAGELIST="golden vectors sim lint formal libcft selfcheck divsqrt \
clause5 diff seq reduce bindings mpfr soak-quick images"
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

in_list() {  # name, comma-list
  case ",$2," in *",$1,"*) return 0;; esac
  return 1
}

note() { ROWS+=("$1"); printf '%s\n' "$1"; }

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
    note "$(printf '%-12s %-7s %s' "$name" "ok" "(cached from earlier in this run)")"
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
    note "$(printf '%-12s %-7s %s' "$name" "SKIP" "$reason")"
    echo "{\"stage\":\"$name\",\"verdict\":\"skip\",\"reason\":\"$reason\"}" >> "$JSONL"
    [ "$REQUIRE_ALL" = 1 ] && FAILED=$((FAILED+1))
    return 0
  fi

  echo "-- $name: $desc"
  t0=$(date +%s)
  if ( set -o pipefail; "$@" ) > "$RUNDIR/$name.log" 2>&1; then
    t1=$(date +%s); dur=$((t1-t0))
    : > "$RUNDIR/$name.ok"
    RAN=$((RAN+1))
    rm -f "$RUNDIR/$name.fail"
    note "$(printf '%-12s %-7s %ss' "$name" "ok" "$dur")"
    echo "{\"stage\":\"$name\",\"verdict\":\"ok\",\"seconds\":$dur}" >> "$JSONL"
  else
    t1=$(date +%s); dur=$((t1-t0))
    : > "$RUNDIR/$name.fail"
    RAN=$((RAN+1))
    FAILED=$((FAILED+1))
    note "$(printf '%-12s %-7s %ss  log: verify/state/%s/%s.log' \
           "$name" "FAIL" "$dur" "$RUNID" "$name")"
    echo "{\"stage\":\"$name\",\"verdict\":\"fail\",\"seconds\":$dur}" >> "$JSONL"
    tail -12 "$RUNDIR/$name.log" | sed 's/^/     | /'
  fi
}

# Tool preconditions, expressed as a skip reason for the NEXT stage.
need() {  # docker|host-cc|xclbinutil ...
  STAGE_SKIP_REASON=""
  for t in "$@"; do
    case "$t" in
      docker) command -v docker >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="docker not present on this host";;
      host-cc) if [ "$WIN" = 1 ]; then
                 [ -x /c/msys64/mingw64/bin/gcc.exe ] \
                   || STAGE_SKIP_REASON="mingw64 gcc not found";
               else command -v cc >/dev/null 2>&1 \
                   || STAGE_SKIP_REASON="no C compiler"; fi;;
      python) command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="no python";;
      xclbinutil) command -v xclbinutil >/dev/null 2>&1 \
        || STAGE_SKIP_REASON="xclbinutil not present (XRT hosts only)";;
      mpfr) [ -f "$ROOT/verify/_mpfr-prefix/include/mpfr.h" ] || \
            [ -f /c/msys64/mingw64/include/mpfr.h ] || \
            [ -f /usr/include/mpfr.h ] || \
            [ -f /usr/include/x86_64-linux-gnu/mpfr.h ] \
        || STAGE_SKIP_REASON="libmpfr headers not found (verify/build-mpfr-oracle.sh builds them from pinned sources, no root needed)";;
      images-env) [ -n "${IMAGES:-}" ] \
        || STAGE_SKIP_REASON="no IMAGES=... exported (nothing staged to verify)";;
    esac
    [ -n "$STAGE_SKIP_REASON" ] && return 0
  done
  return 0
}

# ---- the stages ----------------------------------------------------
# Order is dependency order: the model before things checked against
# it, vectors before their replay, the library before its sweeps.


need python
stage golden "golden-model pytest" -- \
  PY -m pytest "$ROOT/python/tests" -q

need python
stage vectors "regenerate conformance sets (all five attributes)" -- \
  PY "$ROOT/vectors/gen_vectors.py" --out "$ROOT/vectors/out" \
     --rounding rne rtz rdn rup rmm

ensure_sim_image() {
  docker image inspect cft-sim >/dev/null 2>&1 && return 0
  DOCKER build -t cft-sim -f "$MOUNT/docker/Dockerfile.sim" "$MOUNT"
}
do_sim()  { ensure_sim_image && \
            DOCKER run --rm -v "$MOUNT:/work" -w /work/tb cft-sim make sim; }
do_lint() { ensure_sim_image && \
            DOCKER run --rm -v "$MOUNT:/work" -w /work cft-sim make yosys-lint; }

need docker
stage sim "cocotb RTL suite in cft-sim" -- do_sim

need docker
stage lint "yosys elaboration gate" -- do_lint

do_formal() {
  docker image inspect cft-formal >/dev/null 2>&1 || \
    DOCKER build -t cft-formal -f "$MOUNT/docker/Dockerfile.formal" "$MOUNT/docker" || return 1
  DOCKER run --rm -v "$MOUNT:/work" -w /work cft-formal ./formal/run.sh
}
need docker
stage formal "formal proofs + negative control" -- do_formal

# One interpreter for every python-touching stage, chosen by PY()'s
# rule - the libcft stage used to hand make `command -v python3`,
# which on Windows is the WindowsApps alias PY() exists to avoid.
SHLIB_NAME=$(if [ "$WIN" = 1 ]; then echo cft.dll; else echo libcft.so; fi)
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
do_libcft() {
  HOSTMAKE clean >/dev/null 2>&1
  HOSTMAKE test PYTHON="$PYBIN"
}
need host-cc python
stage libcft "host library contract tests + conformance replay" -- do_libcft

do_selfcheck() {
  HOSTMAKE "device-test$EXE" || return 1
  (cd "$ROOT/host" && "./device-test$EXE" sw -n 96)
}
need host-cc
stage selfcheck "device-test software self-matrix (seeds + div/sqrt included)" \
  -- do_selfcheck

need host-cc python
stage divsqrt "cft_div/cft_sqrt/seeds vs model" -- \
  PY "$ROOT/host/tests/divsqrt_check.py"

need host-cc python
stage clause5 "clause-5 completion set vs model" -- \
  PY "$ROOT/host/tests/clause5_check.py"

need host-cc python
stage diff "library vs model, alignment boundary" -- \
  PY "$ROOT/host/tests/diff_check.py" --trials 3000

need host-cc python
stage seq "sequencer C-vs-model over fuzzed programs" -- \
  PY "$ROOT/host/tests/seq_check.py" --trials 250 \
     --formats fp32 fp64 fp128 fp256

need host-cc python
stage reduce "reduction ranges C-vs-model" -- \
  PY "$ROOT/host/tests/reduce_check.py" --trials 1500

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
# So this stage is useful on a bare box and sharper on one with gmpy2.
do_bindings() {
  HOSTMAKE "$SHLIB_NAME" >/dev/null 2>&1 || HOSTMAKE all >/dev/null 2>&1 || true
  CFT_LIB="$ROOT/host/$SHLIB_NAME" PY -m pytest -q \
    "$ROOT/bindings/python/test_cftmpfr.py"
}
need host-cc python
stage bindings "cftmpfr drop-in: encodings, flags and refusals vs gmpy2" \
  -- do_bindings

do_mpfr() {
  # A repo-local prefix (verify/build-mpfr-oracle.sh) outranks system
  # packages: it is version-pinned, SHA-verified, and static, so the
  # oracle is the same everywhere it runs.
  local pfx="$ROOT/verify/_mpfr-prefix"
  if [ -f "$pfx/include/mpfr.h" ]; then
    HOSTMAKE "mpfr-check$EXE" CFLAGS="-O2 -I$pfx/include" \
      LDLIBS="-L$pfx/lib" || return 1
  else
    HOSTMAKE "mpfr-check$EXE" || return 1
  fi
  (cd "$ROOT/host" && "./mpfr-check$EXE" 24 7)
}

do_soakquick() {
  # Pre-build via HOSTMAKE so run-soak.sh's own plain `make` finds the
  # binary fresh and never compiles - which is what lets the script
  # stay platform-naive while this runner carries the Windows quirks.
  HOSTMAKE "divsqrt-soak$EXE" || return 1
  QUICK=1 OUT="$RUNDIR/soak-quick-out" bash "$ROOT/hw/run-soak.sh"
}
need host-cc mpfr
stage mpfr "MPFR parity: all rungs, all modes, flags (third oracle)" -- do_mpfr

need host-cc
stage soak-quick "native-oracle soak (QUICK) + sabotage control" -- do_soakquick

do_images() {
  local rc=0 img
  for img in $IMAGES; do        # word-split intended; no spaces in paths
    echo "==== $img"
    bash "$ROOT/hw/verify-image.sh" "$img" || rc=1
  done
  return $rc
}
need xclbinutil images-env
stage images "verify staged artifacts against their manifests" -- do_images

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
  if [ "$FAILED" -gt 0 ]; then
    echo "VERDICT: FAIL ($FAILED stage(s))"
  elif [ "$SKIPPED" -gt 0 ]; then
    echo "VERDICT: PASS with $SKIPPED skip(s) - see reasons above"
  else
    echo "VERDICT: PASS, nothing skipped"
  fi
  echo
  echo "-- census block (paste into docs/VALIDATION.md) --------------"
  echo "## $(date +%Y-%m-%d) - standardized verification run ($HOSTNM)"
  echo
  echo "verify/run.sh at $COMMIT: $RAN stage(s) executed," \
       "$CACHED cached from earlier in the run, $FAILED failed," \
       "$SKIPPED skipped."
  echo "Run id $RUNID; per-stage logs under verify/state/."
} | tee "$SUMMARY"

[ "$FAILED" -gt 0 ] && exit 1
exit 0
