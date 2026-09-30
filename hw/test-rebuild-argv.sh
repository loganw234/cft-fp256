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
# Which script was it handed?
src=""; prev=""
for a in "$@"; do [ "$prev" = "-source" ] && src="$a"; prev="$a"; done
case "$src" in
  *verify_xo.tcl)
    # The wrapper read-back. Answer every requested generic with the
    # value asked for - unless told to lie, in which case report each at
    # the RTL default of 1, which is exactly the failure this read-back
    # exists to catch.
    for g in ${CFT_GENERICS:-}; do
      n=${g%%=*}; v=${g#*=}
      [ "${STUB_VERIFY_LIE:-0}" = 1 ] && v=1
      echo "WRAPPER_PARAM: .${n}(1'b${v}),"
    done
    exit 0;;
esac
# package_kernel.tcl's contract: -tclargs <part> <build>; make the .xo
# the link step consumes so the real script can carry on. Record the
# generics that reached this process's environment, which is the whole
# question the generics leg asks.
b=""; prev=""
for a in "$@"; do b="$a"; prev="$a"; done
mkdir -p "$b" && : > "$b/cft_krnl.xo"
printf '%s\n' "${CFT_GENERICS:-}" > "$b/generics-seen.txt"
exit 0
STUB

cat > "$TMP/bin/v++" <<'STUB'
#!/usr/bin/env bash
# Record the argv verbatim, one argument a line, then produce the file
# the manifest step will hash so the script reaches its own end.
printf '%s\n' "$@" >> "$VPP_ARGV_LOG"
out=""
prev=""
tmpd=""
for a in "$@"; do
  [ "$prev" = "-o" ] && out="$a"
  [ "$prev" = "--temp_dir" ] && tmpd="$a"
  prev="$a"
done
[ -n "$out" ] && { mkdir -p "$(dirname "$out")"; : > "$out"; }
# The synthesis runs, the way Vivado's IP cache leaves them (measured in
# revision 7's q135, q130 and q135b): CUs with the same properties share
# one cache-ID; the LAST CU of each ID synthesizes and adds the entry,
# the others are hits. A retimed CU's synth_design carries -retiming.
if [ -n "$tmpd" ]; then
  cus=$(sed -n 's/^\([a-z0-9_]*\)\.ap_clk.*/\1/p' <(printf '%s\n' "$@" | tr ',' '\n' | sed 's/^[0-9]*://'))
  runs="$tmpd/link/vivado/vpl/prj/prj.runs"
  last_r=""; last_n=""
  for cu in $cus; do
    if printf '%s\n' "$@" | grep -qx "run.ulp_${cu}_0_synth_1.{STEPS.SYNTH_DESIGN.ARGS.RETIMING}=true"; then
      last_r=$cu; else last_n=$cu; fi
  done
  for cu in $cus; do
    d="$runs/ulp_${cu}_0_synth_1"; mkdir -p "$d"
    if printf '%s\n' "$@" | grep -qx "run.ulp_${cu}_0_synth_1.{STEPS.SYNTH_DESIGN.ARGS.RETIMING}=true"; then
      id=21c6eb981cfcf745; me=$last_r; flag=" -retiming"; else id=1a011ef8b8b87f6a; me=$last_n; flag=""; fi
    # STUB_FOREIGN_CACHE=1: every entry was added by an EARLIER build (a
    # reused BUILD or a shared cache), so every CU is a hit whose
    # producer is not in this build.
    if [ "$cu" = "$me" ] && [ "${STUB_FOREIGN_CACHE:-0}" != 1 ]; then
      printf 'Command: synth_design -top ulp_%s_0 -part xcu50%s\nINFO: [Coretcl 2-1648] Added synthesis output to IP cache for IP ulp_%s_0, cache-ID = %s\n' "$cu" "$flag" "$cu" "$id" > "$d/runme.log"
    else
      printf 'INFO: [IP_Flow 19-4838] Using cached IP synthesis design for IP ulp_%s_0, cache-ID = %s.\n' "$cu" "$id" > "$d/runme.log"
    fi
  done
fi
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
    TARGETS="${TARGETS_FOR_RUN-hw}" \
    KERNEL_FREQ=135000000 \
    RETIMING="${RETIMING_FOR_RUN-1}" \
    VPP_PROPS="run.impl_1.STEPS.OPT_DESIGN.IS_ENABLED=true" \
    LINK_CFG="$cfg" \
    bash "$script" ) > "$TMP/out-$tag.txt" 2>&1
  echo $? > "$TMP/rc-$tag"
  echo "$log"
}

# The CUs whose synthesis run the argv retimes, in argv order.
retimed_cus_of() {              # retimed_cus_of <argv-log> -> "cu cu ..."
  sed -n 's/^run\.ulp_\(.*\)_0_synth_1\.{STEPS\.SYNTH_DESIGN\.ARGS\.RETIMING}=true$/\1/p' "$1" \
    | tr '\n' ' ' | sed 's/ $//'
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
  # RETIMING=1 reaches the synthesis run of EVERY CU the nk= line
  # names. Until 2026-09-30 it reached cft_krnl_1's alone, and three
  # tiles of every quad went unretimed.
  want=$(sed -n 's/^[[:space:]]*nk=[^:]*:[0-9]*:\(.*\)$/\1/p' "$ROOT/$cfg" | tr '.' ' ')
  rt=$(retimed_cus_of "$log")
  if [ "$rt" != "$want" ]; then
    say_fail "$tag: RETIMING=1 retimes '$rt', not every CU '$want'"
  else
    echo "  ok   $tag: RETIMING=1 retimes every CU: $rt"
  fi
  # And the manifest says what the runs did: cache hits followed to the
  # run that synthesized their entry.
  # The quad's four identical CUs must share a synthesis through the
  # stub's cache, or the manifest's hit-following is never exercised
  # and a manifest that read each CU's own log would pass (F1's P3b).
  if [ "$tag" = quad ]; then
    hits=$(grep -l 'Using cached IP synthesis design' \
             "$TMP/build-$tag"/_x_hw/link/vivado/vpl/prj/prj.runs/ulp_*_synth_1/runme.log 2>/dev/null | wc -l)
    if [ "$hits" -lt 1 ]; then
      say_fail "$tag: the stub's runs hold no cache hit, so retimed_runs' hit-following is untested"
    else
      echo "  ok   $tag: $hits of the CUs are cache hits, as Vivado leaves them"
    fi
  fi
  mr=$(sed -n 's/^retimed_runs:  //p' "$TMP/build-$tag/cft_hw.manifest.txt" 2>/dev/null)
  if [ "$mr" != "$want" ]; then
    say_fail "$tag: the manifest's retimed_runs is '$mr', not '$want'"
  else
    echo "  ok   $tag: the manifest's retimed_runs: $mr"
  fi
done

# ------------------------------------------------------------- generics
# CFT_GENERICS must reach vivado's environment unchanged and be written
# into the manifest as what was asked for.
echo "== generics: the request reaches vivado, and the manifest =="
log=$(CFT_GENERICS="EN_FP256=0" run_it "$SCRIPT" "hw/link.cfg" "generics")
seen=$(cat "$TMP/build-generics/generics-seen.txt" 2>/dev/null)
if [ "$seen" != "EN_FP256=0" ]; then
  say_fail "generics: vivado saw CFT_GENERICS='$seen', not 'EN_FP256=0'"
elif ! grep -q '^generics:      EN_FP256=0$' "$TMP/build-generics/cft_hw.manifest.txt" 2>/dev/null; then
  say_fail "generics: the manifest does not record 'generics:      EN_FP256=0'"
  grep -E '^generics:' "$TMP/build-generics/cft_hw.manifest.txt" 2>/dev/null | sed 's/^/        /'
elif [ -z "$(clock_arg_of "$log")" ]; then
  say_fail "generics: --clock.freqHz went missing with CFT_GENERICS set"
else
  echo "  ok   generics: reached vivado, recorded in the manifest, clock intact"
fi

# And the control for the read-back: the stub reports the generic at its
# RTL default, so rebuild-2022.sh must refuse to link. v++ must never be
# reached - a build that stops here has saved the two hours.
echo "== generics control: a generic that did not survive packaging =="
log=$(CFT_GENERICS="EN_FP256=0" STUB_VERIFY_LIE=1 run_it "$SCRIPT" "hw/link.cfg" "genlie")
rc=$(cat "$TMP/rc-genlie")
if [ "$rc" = 0 ]; then
  say_fail "control: the wrapper reported EN_FP256 at its default and the build still succeeded"
elif [ -s "$log" ]; then
  say_fail "control: the build failed but v++ had already been invoked - the read-back did not stop it"
elif ! grep -q "does not carry EN_FP256=0" "$TMP/out-genlie.txt"; then
  say_fail "control: the build stopped, but not for the wrapper mismatch"
  tail -4 "$TMP/out-genlie.txt" | sed 's/^/        /'
else
  echo "  ok   control: the lie is caught before v++ runs (rc=$rc)"
fi

# --------------------------------------------------------- package only
# TARGETS="" packages the .xo, reads the wrapper back, and links NOTHING:
# rc 0, the generics seen by vivado, and v++ never invoked. Until
# 2026-09-14 the empty spelling fell through to "hw hw_emu" and started a
# two-hour link on a box another session was using; this leg is the
# control that keeps `${TARGETS-...}` from drifting back to `:-`.
echo "== package only: TARGETS=\"\" packages, verifies, links nothing =="
log=$(TARGETS_FOR_RUN="" CFT_GENERICS="EN_FP32=0 EN_FP256=0" run_it "$SCRIPT" "hw/link.cfg" "pkgonly")
rc=$(cat "$TMP/rc-pkgonly")
seen=$(cat "$TMP/build-pkgonly/generics-seen.txt" 2>/dev/null)
if [ "$rc" != 0 ]; then
  say_fail "package only: rc=$rc"
  tail -4 "$TMP/out-pkgonly.txt" | sed 's/^/        /'
elif [ -s "$log" ]; then
  say_fail "package only: v++ was invoked - an empty TARGETS still links"
  head -3 "$log" | sed 's/^/        /'
elif [ "$seen" != "EN_FP32=0 EN_FP256=0" ]; then
  say_fail "package only: vivado saw CFT_GENERICS='$seen', not 'EN_FP32=0 EN_FP256=0'"
else
  echo "  ok   package only: packaged and verified, v++ never invoked (rc=0)"
fi

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

# Every CU a cache hit of an entry no run of this build added. The script
# must finish with its whole manifest and name the hits unresolved - under
# set -euo pipefail, fd25e9f's form of this loop ended the script there.
echo "== unresolved cache hits: the build finishes and names them =="
log=$(STUB_FOREIGN_CACHE=1 run_it "$SCRIPT" "hw/link_quad.cfg" "foreign")
rc=$(cat "$TMP/rc-foreign")
man="$TMP/build-foreign/cft_hw.manifest.txt"
un=$(sed -n 's/^retiming_unresolved: \([^#]*\).*/\1/p' "$man" 2>/dev/null | sed 's/ *$//')
if [ "$rc" != 0 ]; then
  say_fail "unresolved: the script exited $rc - see $TMP/out-foreign.txt"
elif ! grep -q '^clock_arg:' "$man" 2>/dev/null; then
  say_fail "unresolved: the manifest stops before clock_arg:"
elif [ "$un" != "cft_krnl_1:21c6eb981cfcf745 cft_krnl_2:21c6eb981cfcf745 cft_krnl_3:21c6eb981cfcf745 cft_krnl_4:21c6eb981cfcf745" ]; then
  say_fail "unresolved: retiming_unresolved is '$un'"
else
  echo "  ok   unresolved: rc 0, the manifest whole, and retiming_unresolved names all four"
fi

# The retiming defect put back: cft_krnl_1's run alone, as the script
# had it until 2026-09-30. The quad must then retime cft_krnl_1 alone,
# which the check above refuses.
echo "== negative control: RETIMING on cft_krnl_1's run alone =="
SAB1="$TMP/sabotaged-retiming.sh"
# Aimed at exactly one line: F1 found the pattern also matching the
# manifest's loop, which then took the sabotage without the cmp noticing.
nmatch=$(grep -c '^    for cu in .*CLOCK_CUS.*; do$' "$SCRIPT" || true)
[ "$nmatch" = 1 ] || say_fail "control: the retiming loop's pattern matches $nmatch lines, not 1 - re-aim it"
awk '!done_ && /^    for cu in [$][{]CLOCK_CUS[/][/][.][/] [}]; do$/ { print "    for cu in cft_krnl_1; do"; done_ = 1; next } { print }' \
    "$SCRIPT" > "$SAB1"
if cmp -s "$SCRIPT" "$SAB1"; then
  say_fail "control: the retiming loop no longer matches the sabotage"
  echo "        pattern, so this control proves nothing. Re-aim it."
else
  log=$(run_it "$SAB1" "hw/link_quad.cfg" "sabotage-retiming")
  rt=$(retimed_cus_of "$log")
  mr=$(sed -n 's/^retimed_runs:  //p' "$TMP/build-sabotage-retiming/cft_hw.manifest.txt" 2>/dev/null)
  if [ "$rt" = "cft_krnl_1" ] && [ "$mr" = "cft_krnl_1" ]; then
    echo "  ok   control: the sabotaged quad retimes '$rt' alone, its manifest says '$mr', and this test sees it"
  elif [ "$rt" = "cft_krnl_1" ]; then
    say_fail "control: the argv retimes cft_krnl_1 alone, but the manifest says '$mr'"
  else
    say_fail "control: the sabotaged quad retimed '$rt', not the defect's cft_krnl_1"
  fi
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "rebuild-2022.sh: the clock constraint survives VPP_PROPS, RETIMING=1"
  echo "reaches the synthesis run of every CU, CFT_GENERICS"
  echo "reaches vivado and the manifest, a lying wrapper read-back stops the"
  echo "build before v++, TARGETS=\"\" packages without linking, and each check"
  echo "still fails when its defect is put back."
  exit 0
fi
echo "$fails failure(s); stub output under $TMP (kept only until exit)"
exit 1
