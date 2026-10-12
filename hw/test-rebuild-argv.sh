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
    # STUB_NO_LOG=<cu>: that CU's run leaves no runme.log at all.
    [ "$cu" = "${STUB_NO_LOG:-}" ] && continue
    d="$runs/ulp_${cu}_0_synth_1"; mkdir -p "$d"
    if printf '%s\n' "$@" | grep -qx "run.ulp_${cu}_0_synth_1.{STEPS.SYNTH_DESIGN.ARGS.RETIMING}=true"; then
      id=21c6eb981cfcf745; me=$last_r; flag=" -retiming"; else id=1a011ef8b8b87f6a; me=$last_n; flag=""; fi
    # A TCL.PRE hook (SYNTH_CLOCK=1). Vivado's script for such a run has
    # no IP-cache logic, so the CU synthesizes itself; the hook is sourced
    # before synth_design, and is run here as far as a stub can: its
    # read_xdc must name a file that exists and holds a create_clock, and
    # its puts reaches the log. With that clock, -retiming leaves Vivado's
    # Retiming Report; without one, Synth 8-11322 - as the measured runs
    # did (docs/VALIDATION.md, 2026-10-12).
    pre=$(printf '%s\n' "$@" | sed -n "s/^run\.ulp_${cu}_0_synth_1\.{STEPS\.SYNTH_DESIGN\.TCL\.PRE}=//p" | head -1)
    if [ -n "$pre" ]; then
      xdc=$(sed -n 's/^read_xdc -mode out_of_context {\(.*\)}$/\1/p' "$pre" 2>/dev/null | head -1)
      clk=""
      [ -n "$xdc" ] && [ -f "$xdc" ] && grep -q '^create_clock -period ' "$xdc" && clk=1
      {
        sed -n 's/^puts "\(CFT_SYNTH_CLOCK:.*\)"$/\1/p' "$pre" 2>/dev/null
        [ -n "$clk" ] && printf 'Parsing XDC File [%s]\n' "$xdc"
        printf 'Command: synth_design -top ulp_%s_0 -part xcu50%s\n' "$cu" "$flag"
        if [ -n "$flag" ] && [ -n "$clk" ]; then
          printf 'Retiming Report:\n|Forward Retiming    | 3   | \n|Backward Retiming   | 5   | \n'
        elif [ -n "$flag" ]; then
          echo "INFO: [Synth 8-11322] No global retiming is needed without any clock constraint"
        fi
      } > "$d/runme.log"
      continue
    fi
    # STUB_FOREIGN_CACHE=1: every entry was added by an EARLIER build (a
    # reused BUILD or a shared cache), so every CU is a hit whose
    # producer is not in this build.
    if [ "$cu" = "$me" ] && [ "${STUB_FOREIGN_CACHE:-0}" != 1 ]; then
      printf 'Command: synth_design -top ulp_%s_0 -part xcu50%s\nINFO: [Coretcl 2-1648] Added synthesis output to IP cache for IP ulp_%s_0, cache-ID = %s\n' "$cu" "$flag" "$cu" "$id" > "$d/runme.log"
      # No clock in the run: Vivado declines -retiming, in these words.
      [ -n "$flag" ] && echo "INFO: [Synth 8-11322] No global retiming is needed without any clock constraint" >> "$d/runme.log"
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
    KERNEL_FREQ="${KERNEL_FREQ_FOR_RUN-135000000}" \
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

# The default flow carries no synthesis clock hook (SYNTH_CLOCK is off
# until Logan adopts it), and the manifest says what each run did with
# -retiming: declined, for want of a clock, cache hits followed. Prints
# its findings and returns how many failed, so a control can require one.
default_check() {               # default_check <argv-log> <tag> <cus>
  local log=$1 tag=$2 cus=$3 man me want_eff bad=0
  man="$TMP/build-$tag/cft_hw.manifest.txt"
  if grep -q 'STEPS\.SYNTH_DESIGN\.TCL\.PRE' "$log"; then
    echo "  FAIL $tag: a TCL.PRE hook is in the default argv; SYNTH_CLOCK must default off"; bad=$((bad + 1))
  fi
  grep -qx 'synth_clock:   0' "$man" 2>/dev/null \
    || { echo "  FAIL $tag: the manifest does not say 'synth_clock:   0' by default"; bad=$((bad + 1)); }
  want_eff=$(for c in $cus; do printf '%s:declined-no-clock ' "$c"; done | sed 's/ $//')
  me=$(sed -n 's/^retiming_effect: //p' "$man" 2>/dev/null)
  [ "$me" = "$want_eff" ] \
    || { echo "  FAIL $tag: the manifest's retiming_effect is '$me', not '$want_eff'"; bad=$((bad + 1)); }
  [ "$bad" = 0 ] && echo "  ok   $tag: no synthesis clock hook by default (synth_clock: 0), retiming_effect: $me"
  return "$bad"
}

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
  default_check "$log" "$tag" "$want" || fails=$((fails + 1))
done

# ------------------------------------------------------------ SYNTH_CLOCK
# SYNTH_CLOCK=1 gives the synthesis run of EVERY CU the nk= line names a
# TCL.PRE hook, whose read_xdc names a clock at 1e9/KERNEL_FREQ ns and
# marks it used_in_implementation false; each run then synthesizes itself
# (no IP cache with a hook), and the manifest names the runs that ran the
# hook and what -retiming did. sc_check prints its findings and returns
# how many checks failed, so the controls below can require a failure.
sc_check() {                    # sc_check <script> <cfg> <tag>
  local script=$1 cfg=$2 tag=$3 log want got pre xdc man me sr bad=0
  log=$(SYNTH_CLOCK=1 run_it "$script" "$cfg" "$tag")
  man="$TMP/build-$tag/cft_hw.manifest.txt"
  pre="$TMP/build-$tag/synth_clock_pre.tcl"
  xdc="$TMP/build-$tag/synth_clock.xdc"
  want=$(sed -n 's/^[[:space:]]*nk=[^:]*:[0-9]*:\(.*\)$/\1/p' "$ROOT/$cfg" | tr '.' ' ')
  got=$(sed -n 's/^run\.ulp_\(.*\)_0_synth_1\.{STEPS\.SYNTH_DESIGN\.TCL\.PRE}=.*$/\1/p' "$log" | tr '\n' ' ' | sed 's/ $//')
  [ "$got" = "$want" ] || { echo "  FAIL $tag: the hook reaches '$got', not every CU '$want'"; bad=$((bad + 1)); }
  # One file for all, absolute, existing - Vivado sources it from the run's directory.
  if [ "$(sed -n 's/^run\.ulp_.*_0_synth_1\.{STEPS\.SYNTH_DESIGN\.TCL\.PRE}=//p' "$log" | sort -u)" != "$(cd "$TMP/build-$tag" 2>/dev/null && pwd)/synth_clock_pre.tcl" ] || [ ! -f "$pre" ]; then
    echo "  FAIL $tag: the hook is not one absolute, existing \$BUILD/synth_clock_pre.tcl"; bad=$((bad + 1))
  fi
  grep -qx 'create_clock -period 7.407 -name cft_synth_ooc_clk \[get_ports ap_clk\]' "$xdc" 2>/dev/null \
    || { echo "  FAIL $tag: synth_clock.xdc is not a 7.407 ns create_clock on ap_clk"; bad=$((bad + 1)); }
  grep -qxF "read_xdc -mode out_of_context {$(dirname "$pre")/synth_clock.xdc}" "$pre" 2>/dev/null \
    && grep -qxF "set_property used_in_implementation false [get_files -all {$(dirname "$pre")/synth_clock.xdc}]" "$pre" \
    || { echo "  FAIL $tag: the hook does not read the XDC out of context and keep it out of implementation"; bad=$((bad + 1)); }
  case "$(clock_arg_of "$log")" in
    135000000:*) ;;
    *) echo "  FAIL $tag: --clock.freqHz went missing with SYNTH_CLOCK=1"; bad=$((bad + 1));;
  esac
  [ "$(retimed_cus_of "$log")" = "$want" ] \
    || { echo "  FAIL $tag: RETIMING no longer reaches every CU with SYNTH_CLOCK=1"; bad=$((bad + 1)); }
  if grep -l 'Using cached IP synthesis design' "$TMP/build-$tag"/_x_hw/link/vivado/vpl/prj/prj.runs/ulp_*_synth_1/runme.log > /dev/null 2>&1; then
    echo "  FAIL $tag: a hooked run is a cache hit; Vivado gives a run with a TCL.PRE no cache"; bad=$((bad + 1))
  fi
  grep -q '^synth_clock:   1 ' "$man" 2>/dev/null || { echo "  FAIL $tag: the manifest does not say synth_clock: 1"; bad=$((bad + 1)); }
  sr=$(sed -n 's/^synth_clock_runs: //p' "$man" 2>/dev/null)
  [ "$sr" = "$want" ] || { echo "  FAIL $tag: the manifest's synth_clock_runs is '$sr', not '$want'"; bad=$((bad + 1)); }
  me=$(sed -n 's/^retiming_effect: //p' "$man" 2>/dev/null)
  [ "$me" = "$(for c in $want; do printf '%s:retimed(forward=3,backward=5,reports=1) ' "$c"; done | sed 's/ $//')" ] \
    || { echo "  FAIL $tag: the manifest's retiming_effect is '$me'"; bad=$((bad + 1)); }
  [ "$bad" = 0 ] && echo "  ok   $tag: the hook on every CU ($got), a 7.407 ns clock kept out of implementation, no cache, retiming_effect retimed"
  return "$bad"
}
echo "== SYNTH_CLOCK=1: every CU's synthesis run reads the kernel clock =="
for pair in "hw/link.cfg:sc-single" "hw/link_quad.cfg:sc-quad"; do
  cfg=${pair%%:*}; tag=${pair#*:}
  sc_check "$SCRIPT" "$cfg" "$tag" || fails=$((fails + 1))
done

# A KERNEL_FREQ the period cannot be taken from is refused before v++.
echo "== SYNTH_CLOCK=1 with a KERNEL_FREQ that is not Hz: refused =="
log=$(SYNTH_CLOCK=1 KERNEL_FREQ_FOR_RUN=135MHz run_it "$SCRIPT" "hw/link.cfg" "scbadfreq")
if [ "$(cat "$TMP/rc-scbadfreq")" = 0 ]; then
  say_fail "SYNTH_CLOCK=1 built with KERNEL_FREQ=135MHz"
elif [ -s "$log" ]; then
  say_fail "SYNTH_CLOCK=1 with KERNEL_FREQ=135MHz failed only after v++ ran"
elif ! grep -q "SYNTH_CLOCK=1 needs KERNEL_FREQ in Hz" "$TMP/out-scbadfreq.txt"; then
  say_fail "SYNTH_CLOCK=1 with KERNEL_FREQ=135MHz stopped, but not for the frequency"
else
  echo "  ok   refused before v++ (rc=$(cat "$TMP/rc-scbadfreq"))"
fi

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

# A CU whose run left no log is unknown: named on retiming_unresolved:,
# and in neither list otherwise.
echo "== a run with no log: named, not counted =="
log=$(STUB_NO_LOG=cft_krnl_2 run_it "$SCRIPT" "hw/link_quad.cfg" "nolog")
man="$TMP/build-nolog/cft_hw.manifest.txt"
mr=$(sed -n 's/^retimed_runs:  //p' "$man" 2>/dev/null)
un=$(sed -n 's/^retiming_unresolved: \([^#]*\).*/\1/p' "$man" 2>/dev/null | sed 's/ *$//')
if [ "$(cat "$TMP/rc-nolog")" != 0 ]; then
  say_fail "no log: the script exited $(cat "$TMP/rc-nolog")"
elif [ "$un" != "cft_krnl_2:no-runme.log" ]; then
  say_fail "no log: retiming_unresolved is '$un', not 'cft_krnl_2:no-runme.log'"
elif [ "$mr" != "cft_krnl_1 cft_krnl_3 cft_krnl_4" ]; then
  say_fail "no log: retimed_runs is '$mr'"
else
  echo "  ok   no log: cft_krnl_2 named unresolved, the other three retimed"
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

# The SYNTH_CLOCK defects put back, each through the same check that
# passed above, which must now fail. sab <name> <sed-expression> writes
# the sabotaged copy to $TMP/<name>.sh and fails when the pattern no
# longer matches, which would make the control prove nothing.
sab() {
  sed "$2" "$SCRIPT" > "$TMP/$1.sh"
  ! cmp -s "$SCRIPT" "$TMP/$1.sh"
}
echo "== negative controls: SYNTH_CLOCK =="
# On by default: the default leg's check must refuse it.
if ! sab sab-sc-default 's/^SYNTH_CLOCK=\${SYNTH_CLOCK:-0}$/SYNTH_CLOCK=${SYNTH_CLOCK:-1}/'; then
  say_fail "control sab-sc-default: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
else
  log=$(run_it "$TMP/sab-sc-default.sh" "hw/link.cfg" "sab-sc-default")
  if default_check "$log" "sab-sc-default" "cft_krnl_1" > "$TMP/ctl-default.txt"; then
    say_fail "control: SYNTH_CLOCK on by default passed the default check"
  else
    echo "  ok   control: SYNTH_CLOCK on by default fails the default check ($(grep -c FAIL "$TMP/ctl-default.txt") findings)"
  fi
fi
# The hook on cft_krnl_1's run alone, the shape of the 2026-09-30 retiming defect.
if ! sab sab-sc-one 's/^    for scu in \${CLOCK_CUS\/\/.\/ }; do$/    for scu in cft_krnl_1; do/'; then
  say_fail "control sab-sc-one: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif sc_check "$TMP/sab-sc-one.sh" "hw/link_quad.cfg" "sab-sc-one" > "$TMP/ctl-one.txt"; then
  say_fail "control: a quad hooked on cft_krnl_1 alone passed the SYNTH_CLOCK check"
else
  echo "  ok   control: a quad hooked on cft_krnl_1 alone fails the SYNTH_CLOCK check ($(grep -c FAIL "$TMP/ctl-one.txt") findings)"
fi
# The hook without used_in_implementation false: its clock could then
# ride the checkpoint into the platform's implementation.
if ! sab sab-sc-impl '/used_in_implementation false/d'; then
  say_fail "control sab-sc-impl: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif sc_check "$TMP/sab-sc-impl.sh" "hw/link.cfg" "sab-sc-impl" > "$TMP/ctl-impl.txt"; then
  say_fail "control: a hook that does not keep its clock out of implementation passed the SYNTH_CLOCK check"
else
  echo "  ok   control: a hook without used_in_implementation false fails the SYNTH_CLOCK check ($(grep -c FAIL "$TMP/ctl-impl.txt") findings)"
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "rebuild-2022.sh: the clock constraint survives VPP_PROPS, RETIMING=1"
  echo "reaches the synthesis run of every CU, CFT_GENERICS"
  echo "reaches vivado and the manifest, a lying wrapper read-back stops the"
  echo "build before v++, TARGETS=\"\" packages without linking, SYNTH_CLOCK"
  echo "is off by default and with it every CU's synthesis reads the kernel"
  echo "clock, and each check still fails when its defect is put back."
  exit 0
fi
echo "$fails failure(s); stub output under $TMP (kept only until exit)"
exit 1
