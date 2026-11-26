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
# Round 3's G3D-1 (the unset fix and the stage `hip-tier`), no GPU:
#  11. the GPU block's unset line names the ten variables the stage must
#      not inherit, CFT_HIP_TIER and CFT_TRANSCEND_MINPREC among them, each
#      one of cert2.ENVIRONMENT_NAMES; a copy with either taken out is red,
#      naming it;
#  12. hip-tier's skips, exactly as hip's: no hipcc (and --require-all
#      FAILS it), no GPU, and HIP_DEVICE past the GPUs listed;
#  13. HIP_TIER_CEILINGS, the number hip-tier prints its seconds against,
#      equal to docs/VERIFICATION.md's hip-tier row; a copy with one
#      changed is red;
#  14. the unset held by a run: with stub tools that let the stage start
#      (hipcc, and a lister that lists one GPU) and CFT_TRANSCEND_MINPREC,
#      XCL_EMULATION_MODE, CFT_SEGRUN_PLANT and CFT_HIP_TIER exported, the
#      stage gets past its environment check and stops where a scratch
#      tree must (no host/ to copy); with CFT_TRANSCEND_MINPREC taken out
#      of a copy's unset it FAILS at the environment check, naming it, in
#      hip and in hip-tier, which share it.
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
# Round 3's G3D-1, with --gpu:
#  15. hip-tier given two plants whose runs are made without them (the
#      bypass of 6, for a list): fixed-rmm, a lane plant, and fixed-refuse,
#      a route plant - the stage FAILS naming both, and nothing runs after
#      the plants;
#  16. the tier word at the device probe: a copy whose unset leaves out
#      CFT_HIP_TIER, run with CFT_HIP_TIER=fixed exported - hip FAILS at
#      the probe, naming it and quoting its line, and nothing runs after;
#  17. the tier word on a leg: every plant run of hip made under
#      CFT_HIP_TIER=fixed by its own command (HIP-PLANT-RUN) - the stage
#      FAILS naming the plant logs whose device lines say fixed;
#  18. the same tier and CFT_TRANSCEND_MINPREC exported to the real runner,
#      cut at the plants by 6's bypass of drop-flag: the only failures are
#      that plant's, and every device line of the stage's log says tier
#      generic - the unset holds where the legs run;
#  19. a first chunk that is not the recorded one: hip-tier with its
#      hip-fmadiff seed changed in a copy (HIP_TIER_FMADIFF_SEED) FAILS
#      naming each stream whose sums moved, and nothing runs after the
#      streams.
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

# 11. the unset (round 3's G3D-1): the names the GPU block's unset line must
# hold, each one of cert2.ENVIRONMENT_NAMES (python/cft_golden/cert2.py),
# and a copy with the tier or CFT_TRANSCEND_MINPREC taken out red by name
unset_want="CFT_DIVSQRT_FULL CFT_DIVSQRT_SEQ CFT_HIP_PLANT CFT_HIP_CHUNK CFT_HIP_PAGE CFT_HIP_UPLOAD CFT_HIP_TIER CFT_TRANSCEND_MINPREC XCL_EMULATION_MODE CFT_SEGRUN_PLANT"
unset_line() { awk '/^# ---- the GPU backend/ { hip = 1 } /^# ---- report/ { hip = 0 } hip && /^  unset CFT_DIVSQRT_FULL /' "$1"; }
unset_missing() {  # <runner>: the names of unset_want its unset line does not name
  local line nm out=""
  line=$(unset_line "$1")
  for nm in $unset_want; do
    case " $line " in *" $nm "*) ;; *) out="$out $nm";; esac
  done
  echo "${out# }"
}
cert2=$(sed -n '/^ENVIRONMENT_NAMES = (/,/)/p' "$ROOT/python/cft_golden/cert2.py" | grep -oE '"[A-Z0-9_]+"' | tr -d '"' | tr '\n' ' ')
notcert=""
for nm in $(unset_line "$RUNSH" | sed 's/^ *unset //'); do
  case " $cert2 " in *" $nm "*) ;; *) notcert="$notcert $nm";; esac
done
m0=$(unset_missing "$RUNSH")
sed '/^  unset CFT_DIVSQRT_FULL /s/ CFT_HIP_TIER / /' "$RUNSH" > "$T/unset-tier.sh"
sed '/^  unset CFT_DIVSQRT_FULL /s/ CFT_TRANSCEND_MINPREC / /' "$RUNSH" > "$T/unset-minprec.sh"
m1=$(unset_missing "$T/unset-tier.sh")
m2=$(unset_missing "$T/unset-minprec.sh")
CASES=$((CASES + 1))
if [ -n "$(unset_line "$RUNSH")" ] && [ -z "$m0" ] && [ -z "$notcert" ] && [ "$(echo $cert2 | wc -w)" = 24 ] \
   && [ "$m1" = CFT_HIP_TIER ] && [ "$m2" = CFT_TRANSCEND_MINPREC ]; then
  echo "  ok    11. the unset line names the ten, each of cert2's 24; a copy without CFT_HIP_TIER is red naming it, and one without CFT_TRANSCEND_MINPREC"
else
  FAILS=$((FAILS + 1))
  echo "  FAIL  11. the unset: the runner's line misses '$m0', names '${notcert# }' outside cert2's $(echo $cert2 | wc -w) names; the copies without the tier and MINPREC miss '$m1' and '$m2' (each its one name wanted)"
fi

# 12. hip-tier's skips, exactly as hip's (its own row, the same reasons)
gotier() {  # as go, for --only hip-tier
  local d=$1 tag=$2
  local -a vars=() args=()
  shift 2
  while [ $# -gt 0 ] && [ "$1" != -- ]; do vars+=("$1"); shift; done
  [ "${1:-}" = -- ] && shift
  args=("$@")
  OUT="$T/$tag.out"
  env "${vars[@]}" bash "$d/verify/run.sh" --only hip-tier "${args[@]}" > "$OUT" 2>&1
  RC=$?
  ROW=$(grep -m1 '^hip-tier  ' "$OUT")
  VERDICT=$(grep -m1 '^VERDICT:' "$OUT")
}
rowt() { printf '%-14s %-7s %s' hip-tier SKIP "$1"; }
want="no hipcc at $nowhere/bin/hipcc (set HIP_ROOT; HIP_PLATFORM=nvidia for HIP 7.2.4's NVIDIA layer, HIP_ROOT=/opt/rocm-7.2.4)"
gotier "$T/skip" t-nohipcc HIP_ROOT="$nowhere"
expect "12. hip-tier: a HIP_ROOT with no hipcc: skipped by name, rc 0" 0 "$(rowt "$want")" "$PASS1"
gotier "$T/skip" t-nohipcc-all HIP_ROOT="$nowhere" -- --require-all
expect "12. hip-tier: the same under --require-all: FAIL, rc 1" 1 "$(rowt "$want")" "$FAIL1"
gotier "$T/skip" t-nogpu-nv HIP_ROOT="$T/stubroot" HIP_PLATFORM= PATH="$T/none:$PATH"
expect "12. hip-tier: hipconfig says nvidia, nvidia-smi lists nothing: skipped by name" \
  0 "$(rowt "no GPU: nvidia-smi -L lists no device for HIP_PLATFORM=nvidia")" "$PASS1"
gotier "$T/skip" t-past HIP_ROOT="$T/stubroot" HIP_PLATFORM=nvidia HIP_DEVICE=9 PATH="$T/one:$PATH"
expect "12. hip-tier: HIP_DEVICE=9 beside one GPU: skipped by name, the count named" \
  0 "$(rowt "no GPU: nvidia-smi -L lists 1 device for HIP_PLATFORM=nvidia, and HIP_DEVICE=9 is past the 1 it lists")" "$PASS1"

# 13. HIP_TIER_CEILINGS and docs/VERIFICATION.md's hip-tier row: the same
# seconds a device, and a copy of the runner with one changed red
ceil_runner() { sed -n 's/^HIP_TIER_CEILINGS="NVIDIA GeForce RTX 5060 Ti=\([0-9]*\);AMD Radeon RX 7600=\([0-9]*\)"$/\1 \2/p' "$1"; }
ceil_docs=$(grep -m1 '^| `hip-tier`' "$ROOT/docs/VERIFICATION.md" \
  | sed -n 's/.*its ceilings are \([0-9,]*\) s on the RTX 5060 Ti and \([0-9,]*\) s on the RX 7600.*/\1 \2/p' | tr -d ',')
sed 's/^\(HIP_TIER_CEILINGS="NVIDIA GeForce RTX 5060 Ti=\)\([0-9]*\)/\11\2/' "$RUNSH" > "$T/ceil-moved.sh"
c0=$(ceil_runner "$RUNSH"); c1=$(ceil_runner "$T/ceil-moved.sh")
CASES=$((CASES + 1))
if [ -n "$c0" ] && [ "$c0" = "$ceil_docs" ] && [ -n "$c1" ] && [ "$c1" != "$ceil_docs" ]; then
  echo "  ok    13. HIP_TIER_CEILINGS is docs/VERIFICATION.md's row ($c0 s on the 5060 Ti and the RX 7600); a copy with one moved ($c1) is red"
else
  FAILS=$((FAILS + 1))
  echo "  FAIL  13. the ceilings: the runner's '${c0}', the row's '${ceil_docs}', the moved copy's '${c1}' (the first two equal and the third not, wanted)"
fi

# 14. the unset held by a run, no GPU: stub tools let the stage start, and
# a scratch tree with no host/ stops it at the copy; with
# CFT_TRANSCEND_MINPREC out of a copy's unset it stops at the environment
# check instead, naming the variable - in hip and in hip-tier, which share
# hip_setup
envvars=(CFT_TRANSCEND_MINPREC=4000 XCL_EMULATION_MODE=hw_emu CFT_SEGRUN_PLANT=x CFT_HIP_TIER=fixed)
repl=$(grep '^  unset CFT_DIVSQRT_FULL ' "$RUNSH" | sed 's/ CFT_TRANSCEND_MINPREC / /')
mkhip "$T/env0" || exit 1
mkhip "$T/env1" 'unset CFT_DIVSQRT_FULL' "$repl" || exit 1
stagelog() { ls -d "$1"/verify/state/*/"$2".log 2>/dev/null | tail -n 1; }
go "$T/env0" env0 HIP_ROOT="$T/stubroot" HIP_PLATFORM=nvidia PATH="$T/one:$PATH" "${envvars[@]}"
l0=$(stagelog "$T/env0" hip); r0=$RC
go "$T/env1" env1 HIP_ROOT="$T/stubroot" HIP_PLATFORM=nvidia PATH="$T/one:$PATH" "${envvars[@]}"
l1=$(stagelog "$T/env1" hip); r1=$RC
gotier "$T/env1" env1t HIP_ROOT="$T/stubroot" HIP_PLATFORM=nvidia PATH="$T/one:$PATH" "${envvars[@]}"
l2=$(stagelog "$T/env1" hip-tier); r2=$RC
CASES=$((CASES + 1))
if [ "${ROW:-}" != "" ] && [[ $ROW == *SKIP* ]]; then
  echo "  NOT RUN  14. the stage was skipped here, so the stubs did not let it start: $ROW"
  CASES=$((CASES - 1))
elif [ "$r0" = 1 ] && [ -n "$l0" ] && ! grep -q '^FAIL  the environment' "$l0" && grep -q '^FAIL  the copy of host/' "$l0" \
     && [ "$r1" = 1 ] && [ -n "$l1" ] && grep -q '^FAIL  the environment: the stage.s runs would inherit CFT_TRANSCEND_MINPREC - ' "$l1" \
     && [ "$r2" = 1 ] && [ -n "$l2" ] && grep -q '^FAIL  the environment: the stage.s runs would inherit CFT_TRANSCEND_MINPREC - ' "$l2"; then
  echo "  ok    14. with ${envvars[*]} exported the stage passes its environment check (it stops at the copy of host/); without CFT_TRANSCEND_MINPREC in the unset, hip and hip-tier FAIL at it, naming it"
  grep -m1 '^FAIL  the environment' "$l1" | cut -c1-160 | sed 's/^/          /'
else
  FAILS=$((FAILS + 1))
  echo "  FAIL  14. the unset by a run: the real runner rc $r0 ($(grep -m1 '^FAIL' "${l0:-/dev/null}" | cut -c1-120)); the copy rc $r1 ($(grep -m1 '^FAIL' "${l1:-/dev/null}" | cut -c1-120)) and hip-tier rc $r2 ($(grep -m1 '^FAIL' "${l2:-/dev/null}" | cut -c1-120))"
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

  # round 3's G3D-1: 15 to 19
  # the bypass of 6 for a list of plants, by name (HIP_TEST_BYPASS)
  bplist='  case " $HIP_TEST_BYPASS " in *" $pl "*) "$@" > "$out" 2>&1; rc=$?;; *) CFT_HIP_PLANT=$pl "$@" > "$out" 2>&1; rc=$?;; esac    # the control: the named plants not set'
  # 15. hip-tier: a lane plant and a route plant, each run made without it
  link_tree "$T/tbypass"
  mkhip "$T/tbypass" HIP-PLANT-RUN "$bplist" || exit 1
  t0=$(date +%s)
  gotier "$T/tbypass" tbypass HIP_TEST_BYPASS="fixed-rmm fixed-refuse"
  log=$(stagelog "$T/tbypass" hip-tier)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q '^FAIL  plant fixed-rmm did not turn its check red' "$log" \
     && grep -q '^FAIL  plant fixed-refuse did not turn its check red' "$log" \
     && grep -q '^FAIL  the plants: a check a plant cannot turn red proves nothing' "$log" \
     && ! grep -q '^== the differential streams' "$log"; then
    echo "  ok    15. hip-tier: fixed-rmm (a lane plant) and fixed-refuse (a route plant) run without their plants: FAIL naming both, no leg after the plants ($(( $(date +%s) - t0 )) s)"
    grep '^FAIL  plant fixed-r' "$log" | cut -c1-220 | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  15. hip-tier's plants run without them: rc $RC, $VERDICT"
    [ -n "$log" ] && tail -n 25 "$log" | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi

  # 16. the device probe's tier word: the unset without the tier, the tier exported
  link_tree "$T/notier"
  mkhip "$T/notier" 'unset CFT_DIVSQRT_FULL' "$(grep '^  unset CFT_DIVSQRT_FULL ' "$RUNSH" | sed 's/ CFT_HIP_TIER / /')" || exit 1
  t0=$(date +%s)
  go "$T/notier" notier CFT_HIP_TIER=fixed
  log=$(stagelog "$T/notier" hip)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q '^FAIL  the device probe (hip-test hip:0 -l open, no tier set by this stage) does not say tier generic: cft hip: hip:0 = .*; tier fixed, ' "$log" \
     && ! grep -q '^== plants' "$log"; then
    echo "  ok    16. the unset without CFT_HIP_TIER, the tier exported: FAIL at the device probe, naming it and quoting its line, nothing after it ($(( $(date +%s) - t0 )) s)"
    grep -m1 '^FAIL  the device probe' "$log" | cut -c1-200 | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  16. the device probe's tier word: rc $RC, $VERDICT"
    [ -n "$log" ] && tail -n 20 "$log" | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi

  # 17. a leg's own command setting the tier: every plant run of hip under it
  link_tree "$T/legtier"
  mkhip "$T/legtier" HIP-PLANT-RUN \
    '  CFT_HIP_TIER=fixed CFT_HIP_PLANT=$pl "$@" > "$out" 2>&1; rc=$?    # the control: each plant run made under the fixed tier' || exit 1
  t0=$(date +%s)
  go "$T/legtier" legtier
  log=$(stagelog "$T/legtier" hip)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q '^  FAIL  plants, plant-flip: 1 of its 1 device lines say another tier than generic, which this leg runs: cft hip: hip:0 = .*; tier fixed, ' "$log" \
     && grep -q '^FAIL  plant-flip: a device line says another tier than generic' "$log" \
     && ! grep -q '^== corpora' "$log"; then
    echo "  ok    17. every plant run of hip made under CFT_HIP_TIER=fixed by its command: FAIL naming the plant logs whose lines say fixed ($(grep -c '^FAIL  plant-.*: a device line says another tier than generic' "$log") of them; $(( $(date +%s) - t0 )) s)"
    grep -m1 '^  FAIL  plants, plant-flip: ' "$log" | cut -c1-200 | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  17. a leg's tier word: rc $RC, $VERDICT"
    [ -n "$log" ] && tail -n 20 "$log" | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi

  # 18. the real runner under an exported tier and CFT_TRANSCEND_MINPREC, cut at the plants
  link_tree "$T/heldtier"
  mkhip "$T/heldtier" HIP-PLANT-RUN \
    '  if [ "$pl" = "$HIP_TEST_BYPASS" ]; then "$@" > "$out" 2>&1; rc=$?; else CFT_HIP_PLANT=$pl "$@" > "$out" 2>&1; rc=$?; fi    # the control: one plant not set' || exit 1
  t0=$(date +%s)
  go "$T/heldtier" heldtier HIP_TEST_BYPASS=drop-flag CFT_HIP_TIER=fixed CFT_TRANSCEND_MINPREC=4000
  log=$(stagelog "$T/heldtier" hip)
  nd=$(grep -a '^cft hip: hip:0 = ' "${log:-/dev/null}" | grep -c .)
  ng=$(grep -a '^cft hip: hip:0 = ' "${log:-/dev/null}" | grep -cF '; tier generic, ')
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] && [ "$nd" -gt 0 ] && [ "$ng" = "$nd" ] \
     && [ "$(grep -c '^FAIL  ' "$log")" = 2 ] && grep -q '^FAIL  plant drop-flag did not turn its check red' "$log" \
     && grep -q '^FAIL  the plants: a check a plant cannot turn red proves nothing' "$log"; then
    echo "  ok    18. CFT_HIP_TIER=fixed and CFT_TRANSCEND_MINPREC=4000 exported to the real runner: the only FAIL lines drop-flag's, bypassed; $nd device lines, every one tier generic ($(( $(date +%s) - t0 )) s)"
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  18. the unset under an exported tier: rc $RC, $VERDICT; $ng of $nd device lines say tier generic; FAIL lines: $(grep -c '^FAIL  ' "${log:-/dev/null}") (2 wanted)"
    [ -n "$log" ] && grep '^FAIL  ' "$log" | head -n 8 | sed 's/^/          | /'
  fi

  # 19. a stream that is not the recorded one: hip-tier's hip-fmadiff seed moved
  link_tree "$T/seed"
  mkhip "$T/seed" 'HIP_TIER_FMADIFF_SEED=' 'HIP_TIER_FMADIFF_SEED=20261111' || exit 1
  t0=$(date +%s)
  gotier "$T/seed" seed
  log=$(stagelog "$T/seed" hip-tier)
  CASES=$((CASES + 1))
  if [ "$RC" = 1 ] && [ "$VERDICT" = "$FAIL1" ] && [ -n "$log" ] \
     && grep -q "^FAIL  the stream hip-fmadiff --format fp256 --stream study --op fma; the first chunk's inputs [0-9a-f]*, not the recorded b07642724a9ebae3" "$log" \
     && [ "$(grep -c '^FAIL  the stream hip-fmadiff ' "$log")" = 16 ] && ! grep -q '^FAIL  the stream hip-progdiff ' "$log" \
     && grep -q '^FAIL  the streams: ' "$log" && ! grep -q '^== corpora' "$log"; then
    echo "  ok    19. hip-tier's hip-fmadiff seed moved: FAIL naming each of its 16 streams by its first chunk, hip-progdiff's held, nothing after the streams ($(( $(date +%s) - t0 )) s)"
    grep -m1 '^FAIL  the stream hip-fmadiff ' "$log" | cut -c1-200 | sed 's/^/          /'
  else
    FAILS=$((FAILS + 1))
    echo "  FAIL  19. a stream off the record: rc $RC, $VERDICT; $(grep -c '^FAIL  the stream hip-fmadiff ' "${log:-/dev/null}") of 16 fmadiff streams named"
    [ -n "$log" ] && grep '^FAIL  ' "$log" | head -n 6 | cut -c1-200 | sed 's/^/          | /'
    [ -z "$log" ] && tail -n 20 "$OUT" | sed 's/^/          | /'
  fi
fi

echo
echo "test-hip-stage: $CASES cases, $FAILS failed$([ "$GPU" = 1 ] || echo "; the failures (5 to 9 and 15 to 19) need --gpu on a host where the stage runs")"
[ "$FAILS" -eq 0 ]
