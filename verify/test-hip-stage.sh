#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# verify/run.sh's `hip` stage held to what it must not call a pass (the GPU
# backend's gate, parcel G1C, 2026-11-12). Run by hand and recorded, as
# hw/test-rebuild-argv.sh is for `buildargs`; no stage runs it.
#
#     bash verify/test-hip-stage.sh          # the skips and hip_named: any
#                                            # host, no GPU, seconds
#     bash verify/test-hip-stage.sh --gpu    # and the five failures, on a host
#                                            # where the stage runs: five real
#                                            # builds, minutes each
#
# Each case runs a copy of the runner with every `need` line outside the
# GPU block taken out, so that `--only hip` asks nothing of the other
# stages' tools (`docker version` stalled for minutes on the Windows desktop
# while Docker Desktop was busy, 2026-11-12), and ROOT is a scratch tree.
# The stage's own block, its `need` and its `stage` line are the runner's
# text. The skips, each held to its row, word for word, and its verdict:
#   1. a HIP_ROOT with no hipcc: SKIP "no hipcc at <root>/bin/hipcc (set
#      HIP_ROOT; ...)", rc 0; the same run under --require-all FAILS, rc 1;
#   2. hipcc there (HIP_ROOT where it has one, else a stub), and listers
#      first on PATH that list nothing: SKIP "no GPU: nvidia-smi -L lists
#      no device for HIP_PLATFORM=nvidia", the platform read from a stub
#      hipconfig that prints a line on stderr first, as HIP 7.2.4's does on
#      a host without its clang; and the same for amd-smi and amd;
#   3. HIP_DEVICE=9 beside a lister that lists one GPU: SKIP naming the one;
#   4. no lister on PATH: SKIP "no GPU: neither nvidia-smi nor amd-smi on
#      PATH" (NOT RUN, named, where a lister lives in a directory the runner
#      needs, as amd-smi in /usr/bin does);
#  10. the stage's hip_named (round 2's G2D), its text taken from the
#      runner, fed three logs: a plant build's, whose `cft hip:
#      CFT_HIP_CHUNK=<n>` line names no device, passes; one with a second
#      device fails, naming it; one with no device line fails.
# With --gpu, on a host where the stage runs - HIP_ROOT, HIP_PLATFORM and
# HIP_DEVICE as for the stage, and ROOT's own top-level entries linked into
# the scratch tree - each a real build in a run of its own:
#   5. the stage's device probe (HIP-OPEN-PROBE) given a stub hip-test that
#      prints what the runtime says when it sees no GPU: the stage FAILS,
#      naming the lister's count and the runtime's sentence, and nothing
#      after the probe runs;
#   6. one plant's run (HIP-PLANT-RUN) made without its plant for the plant
#      HIP_TEST_BYPASS names, which only this copy reads (default drop-flag):
#      its check stays green, the stage FAILS naming that plant, and no leg
#      runs after the plants;
#   7. the same for full-refuse, the plant whose red is the route proof
#      alone (G2C's): the stage FAILS naming it, so its two-sided check
#      fails where the plant is absent;
#   8. the same for aug-flags, a plant judged by hip-test's count of failed
#      checks (G2A's), read by the stage's one reader of those counts;
#   9. the plants' build (HIP-PLANTS-BUILD) cut back to its two tools, so
#      the library in the plants' copy is the default build's: a Python
#      check run under bank-mode through it is green, and the stage FAILS
#      on that run's missing device line, CFT_HIP_PLANT=bank-mode.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNSH="$ROOT/verify/run.sh"
GPU=0
[ "${1:-}" = --gpu ] && GPU=1
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILS=0
CASES=0

for m in '^# ---- the GPU backend' '^# ---- report' 'HIP-OPEN-PROBE' 'HIP-PLANT-RUN' 'HIP-PLANTS-BUILD' '^stage hip '; do
  grep -q "$m" "$RUNSH" || { echo "FAIL  $RUNSH has lost '$m', which this test reads"; exit 1; }
done

# mkhip <dir> [<marker> <replacement line>]...: <dir>/verify/run.sh, the
# runner with the other stages' `need` lines taken out and each marked line
# replaced (each marker on exactly one line)
mkhip() {
  local d=$1 m
  shift
  mkdir -p "$d/verify"
  awk '/^# ---- the GPU backend/ { hip = 1 } /^# ---- report/ { hip = 0 }
       /^need / && !hip { next } { print }' "$RUNSH" > "$d/verify/run.sh"
  while [ $# -ge 2 ]; do
    m=$1
    REPL=$2 awk -v m="$m" 'index($0, m) { print ENVIRON["REPL"]; n++; next } { print }
      END { exit n == 1 ? 0 : 3 }' "$d/verify/run.sh" > "$d/verify/run.new" \
      || { echo "  FAIL  the marker $m is not on exactly one line of the runner"; return 1; }
    mv "$d/verify/run.new" "$d/verify/run.sh"
    shift 2
  done
  bash -n "$d/verify/run.sh" || { echo "  FAIL  the runner's copy in $d does not parse"; return 1; }
}

# go <dir> <tag> [VAR=value ...] [-- runner arguments]: run that copy with
# --only hip and the variables set; OUT, RC, ROW (the stage's row) and VERDICT
go() {
  local d=$1 tag=$2
  local -a vars=() args=()
  shift 2
  while [ $# -gt 0 ] && [ "$1" != -- ]; do vars+=("$1"); shift; done
  [ "${1:-}" = -- ] && shift
  args=("$@")
  OUT="$T/$tag.out"
  env "${vars[@]}" bash "$d/verify/run.sh" --only hip "${args[@]}" > "$OUT" 2>&1
  RC=$?
  ROW=$(grep -m1 '^hip  ' "$OUT")
  VERDICT=$(grep -m1 '^VERDICT:' "$OUT")
}

# expect <name> <rc> <row> <verdict>: one case, held to its exit code, its
# row exactly and its verdict exactly
expect() {
  CASES=$((CASES + 1))
  if [ "$RC" = "$2" ] && [ "$ROW" = "$3" ] && [ "$VERDICT" = "$4" ]; then
    echo "  ok    $1"
    echo "          $ROW"
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  $1"
    echo "          rc $RC, wanted $2"
    echo "          row     '$ROW'"
    echo "          wanted  '$3'"
    echo "          verdict '$VERDICT'"
    echo "          wanted  '$4'"
    tail -n 15 "$OUT" | sed 's/^/          | /'
  fi
}
row() { printf '%-14s %-7s %s' hip SKIP "$1"; }
PASS1="VERDICT: PASS with 1 skip(s) - see reasons above"
FAIL1="VERDICT: FAIL (1 stage(s))"

# Stubs: a HIP installation (hipcc, and a hipconfig that says nvidia after a
# line on stderr), listers that list nothing, and listers that list one GPU
mkdir -p "$T/stubroot/bin" "$T/none" "$T/one"
printf '#!/bin/sh\necho "stub hipcc: not a compiler" >&2\nexit 1\n' > "$T/stubroot/bin/hipcc"
printf '#!/bin/sh\necho "sh: 1: clang++: not found" >&2\necho nvidia\n' > "$T/stubroot/bin/hipconfig"
printf '#!/bin/sh\necho "No devices were found"\nexit 6\n' > "$T/none/nvidia-smi"
printf '#!/bin/sh\nexit 0\n' > "$T/none/amd-smi"
printf '#!/bin/sh\necho "GPU 0: NVIDIA Stub (UUID: GPU-00000000-0000-0000-0000-000000000000)"\n' > "$T/one/nvidia-smi"
printf '#!/bin/sh\nprintf "GPU: 0\\n    BDF: 0000:03:00.0\\n"\n' > "$T/one/amd-smi"
chmod +x "$T/stubroot/bin/hipcc" "$T/stubroot/bin/hipconfig" "$T"/none/* "$T"/one/*
HR=${HIP_ROOT:-}
if [ -z "$HR" ] || [ ! -x "$HR/bin/hipcc" ]; then HR="$T/stubroot"; fi

echo "== the skips (a copy of the runner; ROOT is a scratch tree with nothing in it)"
mkhip "$T/skip" || exit 1

# 1. no hipcc
nowhere="$T/nowhere"
want="no hipcc at $nowhere/bin/hipcc (set HIP_ROOT; HIP_PLATFORM=nvidia for HIP 7.2.4's NVIDIA layer, HIP_ROOT=/opt/rocm-7.2.4)"
go "$T/skip" nohipcc HIP_ROOT="$nowhere"
expect "1. a HIP_ROOT with no hipcc: skipped by name, rc 0" 0 "$(row "$want")" "$PASS1"
go "$T/skip" nohipcc-all HIP_ROOT="$nowhere" -- --require-all
expect "1. the same under --require-all: FAIL, rc 1" 1 "$(row "$want")" "$FAIL1"

# 2. hipcc, and listers that list nothing; the platform from hipconfig
go "$T/skip" nogpu-nv HIP_ROOT="$T/stubroot" HIP_PLATFORM= PATH="$T/none:$PATH"
expect "2. hipconfig says nvidia (after a line on stderr), nvidia-smi lists nothing: skipped by name" \
  0 "$(row "no GPU: nvidia-smi -L lists no device for HIP_PLATFORM=nvidia")" "$PASS1"
go "$T/skip" nogpu-amd HIP_ROOT="$HR" HIP_PLATFORM=amd PATH="$T/none:$PATH"
expect "2. HIP_PLATFORM=amd ($HR), amd-smi lists nothing: skipped by name" \
  0 "$(row "no GPU: amd-smi list lists no device for HIP_PLATFORM=amd")" "$PASS1"
if [ "$HR" != "$T/stubroot" ]; then
  go "$T/skip" nogpu-real HIP_ROOT="$HR" HIP_PLATFORM=nvidia PATH="$T/none:$PATH"
  expect "2. HIP_ROOT=$HR, this host's own, nvidia-smi lists nothing: skipped by name" \
    0 "$(row "no GPU: nvidia-smi -L lists no device for HIP_PLATFORM=nvidia")" "$PASS1"
fi

# 3. HIP_DEVICE past the count
go "$T/skip" past HIP_ROOT="$T/stubroot" HIP_PLATFORM=nvidia HIP_DEVICE=9 PATH="$T/one:$PATH"
expect "3. HIP_DEVICE=9 beside one GPU: skipped by name, the count named" \
  0 "$(row "no GPU: nvidia-smi -L lists 1 device for HIP_PLATFORM=nvidia, and HIP_DEVICE=9 is past the 1 it lists")" "$PASS1"
go "$T/skip" past-amd HIP_ROOT="$T/stubroot" HIP_PLATFORM=amd HIP_DEVICE=1 PATH="$T/one:$PATH"
expect "3. HIP_DEVICE=1 beside one GPU on amd: skipped by name" \
  0 "$(row "no GPU: amd-smi list lists 1 device for HIP_PLATFORM=amd, and HIP_DEVICE=1 is past the 1 it lists")" "$PASS1"

# 4. no lister on PATH: PATH without the directories that hold one
p="" blocked=""
IFS=: read -r -a dirs <<< "$PATH"
for d in "${dirs[@]}"; do
  if [ -n "$d" ] && { [ -e "$d/nvidia-smi" ] || [ -e "$d/nvidia-smi.exe" ] || [ -e "$d/amd-smi" ] \
       || [ -e "$d/rocminfo" ]; }; then
    case "$d" in /bin|/usr/bin|/usr/local/bin) blocked="$blocked $d";; esac
    continue
  fi
  p="$p${p:+:}$d"
done
if [ -n "$blocked" ]; then
  echo "  NOT RUN  4. no lister on PATH: a lister lives in$blocked, which the runner needs"
else
  go "$T/skip" nolister HIP_ROOT="$T/stubroot" HIP_PLATFORM=nvidia PATH="$p"
  expect "4. no lister on PATH: skipped by name" 0 "$(row "no GPU: neither nvidia-smi nor amd-smi on PATH")" "$PASS1"
fi

# 10. hip_named, the runner's own text, fed three logs (no GPU: the logs are
# made here): a plant build's at CFT_HIP_CHUNK=64 passes, a second device
# fails naming it, no device line fails
sed -n '/^hip_devpart() /p; /^hip_devlines() /p; /^hip_named() {/,/^}/p' "$RUNSH" > "$T/named.sh"
dev='NVIDIA Stub (sm_120, 36 multiprocessors, bus 0000:05:00.0, 16283 MiB), HIP platform nvidia, runtime 12090, driver 13040; of 1 visible, CUDA_VISIBLE_DEVICES=1'
two='NVIDIA Stub Two (sm_89, 46 multiprocessors, bus 0000:01:00.0, 12282 MiB), HIP platform nvidia, runtime 12090, driver 13040; of 1 visible, CUDA_VISIBLE_DEVICES=0'
lib='; this libcft: HIP_ARCH 120, stage 64 MiB, page 256 bytes, kernels 40/40/64/40 registers and 0/0/16864/4160 bytes local a thread (run/level/seq/aug), PLANTS COMPILED IN, CFT_HIP_PLANT=none'
printf 'libcft build x\ncft hip: hip:0 = %s%s\ncft hip: CFT_HIP_CHUNK=64\n12720 checks, 0 failed, 0 NOT RUN\n' "$dev" "$lib" > "$T/named-chunk.txt"
printf 'cft hip: hip:0 = %s%s\ncft hip: CFT_HIP_CHUNK=64\ncft hip: hip:0 = %s%s\n' "$dev" "$lib" "$two" "$lib" > "$T/named-two.txt"
printf 'libcft build x\n12720 checks, 0 failed, 0 NOT RUN\n' > "$T/named-none.txt"
named() { HIP_DEV="$dev" bash -c '. "$1"; hip_named "$2" probe' _ "$T/named.sh" "$T/named-$1.txt"; }
o1=$(named chunk); r1=$?
o2=$(named two); r2=$?
o3=$(named none); r3=$?
CASES=$((CASES + 1))
if [ "$r1" = 0 ] && [ -z "$o1" ] && [ "$r2" = 1 ] \
   && [[ $o2 == "  FAIL  probe: 1 of its 2 device lines name another device than the stage's"*"NVIDIA Stub Two"* ]] \
   && [ "$r3" = 1 ] && [[ $o3 == "  FAIL  probe: no CFT_HIP_INFO line"* ]]; then
  echo "  ok    10. hip_named: a plant build's CFT_HIP_CHUNK line is no device line; a second device and no device line still fail"
else
  FAILS=$((FAILS + 1))
  echo "  FAIL  10. hip_named: the CHUNK log rc $r1 '${o1}'; the second device rc $r2 '${o2:0:160}'; no device line rc $r3 '${o3:0:160}'"
fi

if [ "$GPU" = 1 ]; then
  echo "== the failures (a copy of the runner; ROOT links this tree's own entries; real builds)"
  # A tree whose entries are this one's, but for verify/, which holds the copy.
  # The stage copies host/ (no git here) into its run's own directory.
  link_tree() {
    local d=$1 e
    mkdir -p "$d"
    for e in "$ROOT"/* "$ROOT"/.[!.]*; do
      [ -e "$e" ] || continue
      case "$(basename "$e")" in verify|.git) continue;; esac
      ln -s "$e" "$d/$(basename "$e")"
    done
  }
  cat > "$T/stub-hip-test" << 'EOF'
#!/bin/sh
echo "libcft build unknown"
echo 'cft_open("hip:0"): no such device - cft_open: hip:0 names GPU 0, and the HIP runtime sees 0 (hip:0 to hip:-1) - none at all'
exit 2
EOF
  chmod +x "$T/stub-hip-test"

  # 5. the lister shows the GPU, the runtime (a stub) sees none
  link_tree "$T/zero"
  mkhip "$T/zero" HIP-OPEN-PROBE \
    '  hip_cmd "$L/open.txt" env CFT_HIP_INFO=1 "$HIP_TEST_STUB" hip:0 -l open; rc=$?    # the control: the probe is a stub' || exit 1
  t0=$(date +%s)
  go "$T/zero" zero HIP_TEST_STUB="$T/stub-hip-test"
  log=$(ls -d "$T"/zero/verify/state/*/hip.log 2>/dev/null | head -n 1)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q 'but the HIP runtime of this build sees none: cft_open("hip:0"): no such device - cft_open: hip:0 names GPU 0, and the HIP runtime sees 0' "$log" \
     && grep -qE '^FAIL  .* lists [1-9][0-9]* GPU\(s\) for HIP_PLATFORM=[a-z]+ and HIP_DEVICE=[0-9]+ among them' "$log" \
     && ! grep -q '^== plants' "$log"; then
    echo "  ok    5. a runtime that sees no GPU where the lister shows one: FAIL naming both, nothing after the probe ($(( $(date +%s) - t0 )) s)"
    grep -m1 '^FAIL  ' "$log" | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  5. a runtime that sees no GPU where the lister shows one: rc $RC, $VERDICT"
    [ -n "$log" ] && tail -n 20 "$log" | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi

  # 6. a plant whose run is made without it
  pl=${HIP_TEST_BYPASS:-drop-flag}
  link_tree "$T/bypass"
  mkhip "$T/bypass" HIP-PLANT-RUN \
    '  if [ "$pl" = "$HIP_TEST_BYPASS" ]; then "$@" > "$out" 2>&1; rc=$?; else CFT_HIP_PLANT=$pl "$@" > "$out" 2>&1; rc=$?; fi    # the control: one plant not set' || exit 1
  t0=$(date +%s)
  go "$T/bypass" bypass HIP_TEST_BYPASS="$pl"
  log=$(ls -d "$T"/bypass/verify/state/*/hip.log 2>/dev/null | head -n 1)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q "^FAIL  plant $pl did not turn its check red" "$log" \
     && grep -q '^FAIL  the plants: a check a plant cannot turn red proves nothing' "$log" \
     && ! grep -q '^== corpora' "$log"; then
    echo "  ok    6. plant $pl run without its plant: FAIL naming it, no leg after the plants ($(( $(date +%s) - t0 )) s)"
    grep '^FAIL  \|^  RED ' "$log" | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  6. plant $pl run without its plant: rc $RC, $VERDICT"
    [ -n "$log" ] && tail -n 25 "$log" | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi

  # 7 and 8: the same, for one of round 2's plants each, a run each
  bypass() {  # <case> <plant> <how its check is judged>
    local c=$1 bp=$2 w=$3 d="$T/bypass-$2" log
    link_tree "$d"
    mkhip "$d" HIP-PLANT-RUN \
      '  if [ "$pl" = "$HIP_TEST_BYPASS" ]; then "$@" > "$out" 2>&1; rc=$?; else CFT_HIP_PLANT=$pl "$@" > "$out" 2>&1; rc=$?; fi    # the control: one plant not set' || return 1
    t0=$(date +%s)
    go "$d" "bypass-$bp" HIP_TEST_BYPASS="$bp"
    log=$(ls -d "$d"/verify/state/*/hip.log 2>/dev/null | head -n 1)
    CASES=$((CASES + 1))
    if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
       && grep -q "^FAIL  plant $bp did not turn its check red" "$log" \
       && grep -q '^FAIL  the plants: a check a plant cannot turn red proves nothing' "$log" \
       && ! grep -q '^== corpora' "$log"; then
      echo "  ok    $c. plant $bp ($w) run without its plant: FAIL naming it, no leg after the plants ($(( $(date +%s) - t0 )) s)"
      grep "^FAIL  plant $bp " "$log" | sed 's/^/          /'
    else
      FAILS=$((FAILS + 1))
      echo "  FAIL  $c. plant $bp run without its plant: rc $RC, $VERDICT"
      [ -n "$log" ] && tail -n 25 "$log" | sed 's/^/          | /'
      [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
    fi
  }
  bypass 7 full-refuse "the route proof alone, on both sides" || exit 1
  bypass 8 aug-flags "hip-test's count of failed checks" || exit 1

  # 9. the plants' build cut back to its two tools: the plants' copy keeps
  # the default build's library, through which a Python check under a plant
  # is green - the stage must FAIL on the device line that does not name it
  link_tree "$T/nolib"
  mkhip "$T/nolib" HIP-PLANTS-BUILD \
    '  pt=(hip-corpus hip-test)    # the control: the plants build their two tools alone' || exit 1
  t0=$(date +%s)
  go "$T/nolib" nolib
  log=$(ls -d "$T"/nolib/verify/state/*/hip.log 2>/dev/null | head -n 1)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q '^FAIL  plant bank-mode did not turn its check red: .* exited 0, .*and no device line names the plant' "$log" \
     && grep -q '^FAIL  the plants: a check a plant cannot turn red proves nothing' "$log" \
     && ! grep -q '^== corpora' "$log"; then
    echo "  ok    9. the plants' library left the default build's: the Python check under bank-mode green, the stage FAILS on its device line ($(( $(date +%s) - t0 )) s)"
    grep '^FAIL  plant ' "$log" | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  9. the plants' library left the default build's: rc $RC, $VERDICT"
    [ -n "$log" ] && tail -n 25 "$log" | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi
fi

echo
echo "test-hip-stage: $CASES cases, $FAILS failed$([ "$GPU" = 1 ] || echo "; the failures (5 to 9) need --gpu on a host where the stage runs")"
[ "$FAILS" -eq 0 ]
