#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The embedded gate: everything that can be checked without a board.
#
#   bindings/arduino/verify.sh                     all of it
#   bindings/arduino/verify.sh --quick             skip the full census
#   bindings/arduino/verify.sh --no-boards         skip arduino-cli
#
# Five legs, each one a claim:
#
#   1  the vendored copy is byte-identical to host/    (sync.py --check)
#   2  the loopback builds in all four profiles
#   3  the harness replays the published vectors through each profile
#   4  the harness catches a loopback that lies        (--corrupt)
#   5  every example compiles for every board, warnings on
#
# Every leg prints PASS or FAIL with its own numbers, and the exit
# status is 0 only if all of them passed. A leg whose tool is missing
# says SKIP with the tool's name - a log that quietly checked nothing
# must not read as a pass, which is the rule cft_conformance applies to
# its own summary.
#
# On Windows, run it from an MSYS2 shell with the mingw64 toolchain
# first on PATH, and pass a python that has the vectors' generator:
#
#   PATH="/c/msys64/mingw64/bin:$PATH" PYTHON=/c/path/to/python.exe \
#       bindings/arduino/verify.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
CC="${CC:-cc}"
ARDUINO_CLI="${ARDUINO_CLI:-arduino-cli}"
VECTORS="${VECTORS:-$REPO/vectors/out}"
BUILD="${BUILD:-${TMPDIR:-/tmp}/cft-arduino-verify}"

QUICK=0
BOARDS=1
for a in "$@"; do
  case "$a" in
    --quick)     QUICK=1 ;;
    --no-boards) BOARDS=0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

FQBNS="arduino:avr:uno arduino:avr:nano arduino:avr:mega
       esp32:esp32:esp32 rp2040:rp2040:rpipico"
SKETCHES="Hello VectorReplay Bench"

fails=0
skips=0
mkdir -p "$BUILD"

banner() { printf '\n=== %s ===\n' "$1"; }
pass()   { printf 'PASS  %s\n' "$1"; }
fail()   { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
skip()   { printf 'SKIP  %s\n' "$1"; skips=$((skips + 1)); }

# ---- 1. the vendored copy -------------------------------------------
banner "the vendored copy against host/"
if out=$("$PYTHON" "$HERE/sync.py" --check 2>&1); then
  pass "$out"
else
  printf '%s\n' "$out"
  fail "the copy under cft-arduino/src/cft has drifted from host/"
fi

# ---- 2. the loopback ------------------------------------------------
banner "the loopback, four profiles"
# TMP and TEMP as make VARIABLES, not just in the environment: MSYS2's
# make hands a recipe a stripped environment, and a gcc with no writable
# temporary directory fails with "Cannot create temporary file in
# C:\WINDOWS\: Permission denied" - which reads like a compiler problem
# and is a make one. Harmless everywhere else. $BUILD is writable by
# definition, so it is the fallback.
if make -C "$HERE/loopback" CC="$CC" \
        TMP="${TMP:-$BUILD}" TEMP="${TEMP:-$BUILD}" \
        > "$BUILD/loopback.log" 2>&1; then
  w=$(grep -c "warning:" "$BUILD/loopback.log")
  b=$(grep -m1 "^built:" "$BUILD/loopback.log")
  [ -n "$b" ] || b="already built"
  if [ "$w" = "0" ]; then
    pass "$b"
  else
    grep "warning:" "$BUILD/loopback.log" | sort -u | head -5
    fail "the loopback built with $w warnings"
  fi
else
  tail -20 "$BUILD/loopback.log"
  fail "the loopback did not build"
fi

# The binaries' common prefix, and the suffix this platform gave them.
# Checked in that order and not the other way round: under MSYS a test
# for an executable succeeds on a path with the .exe left off, and the
# Python that has to SPAWN it is a native process that cannot open one.
STEM="$HERE/loopback/cft-replay-loopback"
SUF=""
if [ -f "$STEM-full.exe" ]; then
  SUF=".exe"
elif [ ! -f "$STEM-full" ]; then
  STEM=""
fi

# ---- 3. the census, per profile -------------------------------------
banner "the published vectors, through each profile"
if [ -z "$STEM" ]; then
  skip "no loopback binary to replay through"
elif [ ! -d "$VECTORS" ]; then
  skip "no $VECTORS - run: make vectors"
else
  # profile : the sets that profile can be asked
  #
  # A narrow profile is given the sets it CARRIES rather than all 168,
  # because "153 sets skipped" is not a result. What it is given, it
  # must answer completely.
  #
  # The status comes from the tool and not from the pipeline that
  # summarises it: `cmd | tail` reports tail's exit status, so a
  # failing replay dressed up in a pipe would read as a pass. Written
  # to a file, status taken, then summarised.
  replay() {
    name="$1"; sets="$2"
    exe="$STEM-$name$SUF"
    if [ ! -f "$exe" ]; then skip "$name: no binary at $exe"; return; fi
    if [ -n "$sets" ]; then argsets="--sets $sets"; else argsets=""; fi
    "$PYTHON" "$REPO/host/tools/serial_replay.py" \
        --loopback "$exe" --vectors "$VECTORS" $argsets \
        > "$BUILD/replay-$name.log" 2>&1
    if [ $? -eq 0 ]; then
      pass "$name: $(grep -E 'cases checked' "$BUILD/replay-$name.log" |
                     tail -1)"
    else
      tail -20 "$BUILD/replay-$name.log"
      fail "$name: the replay did not match"
    fi
  }
  if [ "$QUICK" = 1 ]; then
    replay tiny     'fp32,fp64'
    replay full     'fp32,fp64,fp128,fp256'
  else
    replay tiny     'fp32*,fp64*'
    replay tiny128  'fp32*,fp64*,fp128*'
    replay board    ''
    replay full     ''
  fi
fi

# ---- 4. the negative control ----------------------------------------
banner "the negative control: a loopback that answers wrongly"
if [ -z "$STEM" ] || [ ! -d "$VECTORS" ]; then
  skip "needs the loopback and $VECTORS"
else
  "$PYTHON" "$REPO/host/tools/serial_replay.py" \
      --loopback "$STEM-full$SUF" --vectors "$VECTORS" --corrupt \
      > "$BUILD/corrupt.log" 2>&1
  if [ $? -eq 0 ]; then
    grep -E "CAUGHT|MISSED" "$BUILD/corrupt.log"
    pass "$(tail -1 "$BUILD/corrupt.log")"
  else
    cat "$BUILD/corrupt.log"
    fail "a corruption went unnoticed - the harness cannot be trusted"
  fi
fi

# ---- 5. the boards --------------------------------------------------
banner "arduino-cli, every example for every board"
if [ "$BOARDS" = 0 ]; then
  skip "--no-boards"
elif ! command -v "$ARDUINO_CLI" > /dev/null 2>&1; then
  skip "arduino-cli is not on PATH"
else
  for fq in $FQBNS; do
    for sk in $SKETCHES; do
      tag="$(printf '%s' "$fq" | tr ':' '-')--$sk"
      if "$ARDUINO_CLI" compile --fqbn "$fq" --libraries "$HERE" \
           --output-dir "$BUILD/$tag" --warnings all \
           "$HERE/cft-arduino/examples/$sk" > "$BUILD/$tag.log" 2>&1; then
        w=$(grep -c "warning:" "$BUILD/$tag.log")
        sz=$(grep -E "^Sketch uses|^Global variables" "$BUILD/$tag.log" \
             | tr '\n' ' ')
        if [ "$w" = "0" ]; then
          pass "$fq $sk: $sz"
        else
          grep "warning:" "$BUILD/$tag.log" | head -5
          fail "$fq $sk: $w warnings"
        fi
      else
        tail -8 "$BUILD/$tag.log"
        fail "$fq $sk: did not compile"
      fi
    done
  done
fi

# ---------------------------------------------------------------------
printf '\n'
if [ "$fails" -eq 0 ] && [ "$skips" -eq 0 ]; then
  echo "every leg passed"
elif [ "$fails" -eq 0 ]; then
  echo "every leg that ran passed; $skips skipped, by name above"
else
  echo "$fails leg(s) FAILED"
fi
printf 'logs and build output: %s\n' "$BUILD"
[ "$fails" -eq 0 ] || exit 1
