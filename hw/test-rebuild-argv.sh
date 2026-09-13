#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The stub-v++ argv test. hw/rebuild-2022.sh has credited it since the
# bug it describes was fixed; it did not exist until 2026-09-13.
#
# WHAT IT GUARDS. That script builds the v++ link line in pieces:
#
#     extra=""
#     [ "$t" = "hw" ] && extra="--clock.freqHz ${KERNEL_FREQ}:${CLOCK_ARG}"
#     vprop=()
#     ...
#     for vp in $VPP_PROPS; do vprop+=(--vivado.prop "$vp"); done
#
# That inner loop once used `extra` as its variable, which already held
# the clock constraint. Setting VPP_PROPS therefore ERASED
# --clock.freqHz, and v++ fell back to the platform default while the
# build reported success - the failure CLAUDE.md still warns about
# ("the tell is an absurd kernel WNS"). Two hours to find out, and only
# if someone read the timing report rather than the exit code.
#
# HOW IT TESTS IT. Not by re-implementing the argv logic - a copy of the
# code cannot catch the code drifting. It puts stub `v++` and `vivado`
# on PATH, runs the REAL script, and reads back the argv v++ was
# actually handed. VPP_PROPS is set throughout, because an empty
# VPP_PROPS is exactly the case the original bug did not break.
#
# AND IT PROVES IT CAN STILL FAIL. The negative control reintroduces the
# historical bug into a copy of the script - `for vp` back to
# `for extra` - and requires that this test catches it. A gate that
# cannot be made to fail has stopped being a gate, which is the rule
# formal/ keeps with its own negative control.
#
#     bash hw/test-rebuild-argv.sh          # exit 0 pass, 1 fail, 77 skip
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SCRIPT="$ROOT/hw/rebuild-2022.sh"
[ -f "$SCRIPT" ] || { echo "no $SCRIPT"; exit 1; }

# Refuse to run where a real Vitis is installed. rebuild-2022.sh sources
# $root/Vitis/2022.2/settings64.sh BEFORE it looks for v++, and that
# prepends the real toolchain: measured on amd-arc-box, where a stub
# first on PATH became /data/Xilinx/Vitis/2022.2/bin/v++ after the
# source. The stub would lose, the real v++ would run, and the test
# would start a two-hour link on a build host. 77 so a runner can tell
# this apart from a pass.
for r in /data/Xilinx /opt/Xilinx /tools/Xilinx; do
  if [ -f "$r/Vitis/2022.2/settings64.sh" ]; then
    echo "SKIP: $r/Vitis/2022.2/settings64.sh exists and rebuild-2022.sh"
    echo "      sources it, which takes PATH away from the stub. Run this"
    echo "      where Vitis is absent - CI does."
    exit 77
  fi
done

TMP=$(mktemp -d) || exit 1
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/plat/xilinx_u50_gen3x16_xdma_5_202210_1"

cat > "$TMP/bin/vivado" <<'STUB'
#!/usr/bin/env bash
# -version is asked for in a $(...) before the real call.
case "${1:-}" in -version) echo "Vivado v2022.2 (64-bit)"; exit 0;; esac
# package_kernel.tcl's contract: -tclargs <part> <build>; make the .xo
# the link step consumes so the real script can carry on.
b=""
prev=""
for a in "$@"; do [ "$prev" = "-tclargs" ] && part="$a"; b="$a"; prev="$a"; done
mkdir -p "$b" && : > "$b/cft_krnl.xo"
exit 0
STUB

cat > "$TMP/bin/v++" <<'STUB'
#!/usr/bin/env bash
# Record the argv verbatim, one argument a line, then produce the file
# the manifest step will hash so the script reaches its own end.
printf '%s\n' "$@" >> "$VPP_ARGV_LOG"
out=""
prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
[ -n "$out" ] && { mkdir -p "$(dirname "$out")"; : > "$out"; }
exit 0
STUB
chmod +x "$TMP/bin/vivado" "$TMP/bin/v++"

# Run the script under the stubs and echo where the argv landed.
run_it() {                       # run_it <script> <link-cfg> <tag>
  local script=$1 cfg=$2 tag=$3
  local log="$TMP/argv-$tag.txt"
  : > "$log"
  ( cd "$ROOT" && \
    PATH="$TMP/bin:$PATH" \
    VPP_ARGV_LOG="$log" \
    PLATFORM_REPO_PATHS="$TMP/plat" \
    BUILD="$TMP/build-$tag" \
    TARGETS=hw \
    KERNEL_FREQ=135000000 \
    VPP_PROPS="run.impl_1.STEPS.OPT_DESIGN.IS_ENABLED=true" \
    LINK_CFG="$cfg" \
    bash "$script" ) > "$TMP/out-$tag.txt" 2>&1
  echo "$log"
}

# --clock.freqHz present, and the value the environment asked for.
clock_arg_of() {                 # clock_arg_of <argv-log> -> the value, or ""
  awk '/^--clock\.freqHz$/ { getline; print; exit }' "$1"
}

fails=0
say_fail() { echo "  FAIL $*"; fails=$((fails + 1)); }

echo "== the real script, single and quad link configs =="
for pair in "hw/link.cfg:single:1" "hw/link_quad.cfg:quad:4"; do
  cfg=${pair%%:*}; rest=${pair#*:}; tag=${rest%%:*}; want_cus=${rest##*:}
  [ -f "$ROOT/$cfg" ] || { echo "  SKIP $cfg absent"; continue; }
  log=$(run_it "$SCRIPT" "$cfg" "$tag")
  if [ ! -s "$log" ]; then
    say_fail "$tag: v++ was never invoked - see $TMP/out-$tag.txt"
    sed 's/^/        /' "$TMP/out-$tag.txt" | tail -4
    continue
  fi
  got=$(clock_arg_of "$log")
  if [ -z "$got" ]; then
    say_fail "$tag: --clock.freqHz is absent from the v++ argv"
    continue
  fi
  case "$got" in
    135000000:*) ;;
    *) say_fail "$tag: --clock.freqHz is '$got', not the 135000000 asked for";;
  esac
  n=$(printf '%s' "$got" | tr ',' '\n' | grep -c 'ap_clk')
  if [ "$n" != "$want_cus" ]; then
    say_fail "$tag: clock constraint names $n compute units, expected $want_cus"
  else
    echo "  ok   $tag: --clock.freqHz $got"
  fi
  # The property that erased it must itself have survived.
  grep -q -- '--vivado.prop' "$log" \
    || say_fail "$tag: --vivado.prop missing, so VPP_PROPS never reached v++"
done

# ---------------------------------------------------------------- control
# Put the historical defect back and require that the above catches it.
echo "== negative control: the 2026 bug reintroduced =="
SAB="$TMP/sabotaged.sh"
sed 's/for vp in \$VPP_PROPS; do vprop+=(--vivado\.prop "\$vp"); done/for extra in $VPP_PROPS; do vprop+=(--vivado.prop "$extra"); done/' \
    "$SCRIPT" > "$SAB"
if cmp -s "$SCRIPT" "$SAB"; then
  say_fail "control: the loop this test guards no longer matches - the"
  echo "        sabotage pattern found nothing, so the control proves nothing."
  echo "        Re-read hw/rebuild-2022.sh and re-aim it."
else
  log=$(run_it "$SAB" "hw/link.cfg" "sabotage")
  got=$(clock_arg_of "$log")
  if [ -n "$got" ]; then
    say_fail "control: the sabotaged script still passed --clock.freqHz '$got'"
    echo "        - this test would NOT have caught the original bug."
  else
    echo "  ok   control: sabotage drops --clock.freqHz, and this test sees it"
  fi
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "rebuild-2022.sh argv: the clock constraint survives VPP_PROPS, and"
  echo "the check still fails when the defect is put back."
  exit 0
fi
echo "$fails failure(s); stub output under $TMP (kept only until exit)"
exit 1
