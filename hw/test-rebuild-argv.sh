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
# It needs a writable repository root: the relative-BUILD legs make
# build/buildargs-<pid>-<n>/ there (and build/ if it is absent), and
# remove only those.
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
# The relative-BUILD legs need a BUILD path relative to the repository
# root, as BITSTREAM-BUILDS writes it (BUILD=build-<name>). They use
# REL_BASE, under the repository's own gitignored build/, named for this
# run and made by it: with $TMP, the only things this test removes.
# build/ itself goes only if this run made it and left it empty.
REL_BASE="build/buildargs-$$-${RANDOM:-0}"
REL_MADE=0
MADE_BUILD=0; [ -d "$ROOT/build" ] || MADE_BUILD=1
cleanup() {
  rm -rf "$TMP"
  [ "$REL_MADE" = 1 ] && rm -rf "${ROOT:?}/$REL_BASE"
  [ "$MADE_BUILD" = 1 ] && rmdir "$ROOT/build" 2>/dev/null
  return 0
}
trap cleanup EXIT
mkdir -p "$TMP/bin" "$TMP/plat/xilinx_u50_gen3x16_xdma_5_202210_1"

# hw_emu's last step in rebuild-2022.sh, so that a run with hw_emu in
# TARGETS ends as one without it does.
cat > "$TMP/bin/emconfigutil" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

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
# the others are hits. A CU given RETIMING's property runs synth_design
# with -retiming.
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
chmod +x "$TMP/bin/vivado" "$TMP/bin/v++" "$TMP/bin/emconfigutil"

# Run the script under the stubs and echo where the argv landed.
run_it() {                       # run_it <script> <link-cfg> <tag>
  local script=$1 cfg=$2 tag=$3
  local log="$TMP/argv-$tag.txt"
  : > "$log"
  ( cd "$ROOT" && \
    PATH="$TMP/bin:$PATH" \
    VPP_ARGV_LOG="$log" \
    PLATFORM_REPO_PATHS="$TMP/plat" \
    BUILD="${BUILD_FOR_RUN-$TMP/build-$tag}" \
    TARGETS="${TARGETS_FOR_RUN-hw}" \
    KERNEL_FREQ="${KERNEL_FREQ_FOR_RUN-135000000}" \
    RETIMING="${RETIMING_FOR_RUN-1}" \
    VPP_PROPS="run.impl_1.STEPS.OPT_DESIGN.IS_ENABLED=true" \
    LINK_CFG="$cfg" \
    bash "$script" ) > "$TMP/out-$tag.txt" 2>&1
  echo $? > "$TMP/rc-$tag"
  echo "$log"
}

# The CUs whose synthesis run the argv gives -retiming, in argv order.
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

# The default flow carries no synthesis clock hook (SYNTH_CLOCK is off;
# Logan keeps it off for now, 2026-10-12), and the manifest says what
# each run did with -retiming: declined, for want of a clock, cache hits
# followed. Prints its findings and returns how many failed, so a
# control can require one.
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
  # tiles of every quad went without it.
  want=$(sed -n 's/^[[:space:]]*nk=[^:]*:[0-9]*:\(.*\)$/\1/p' "$ROOT/$cfg" | tr '.' ' ')
  rt=$(retimed_cus_of "$log")
  if [ "$rt" != "$want" ]; then
    say_fail "$tag: RETIMING=1 reaches '$rt', not every CU '$want'"
  else
    echo "  ok   $tag: RETIMING=1 reaches the synthesis run of every CU: $rt"
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
sc_check() {                    # sc_check <script> <cfg> <tag> [build dir, to read]
  # BUILD_FOR_RUN in the caller's environment reaches run_it, for a
  # relative BUILD; the fourth argument is where that BUILD lands.
  local script=$1 cfg=$2 tag=$3 bdir=${4:-$TMP/build-$3} log want got hook pre xdc man me sr rl sl bad=0
  log=$(SYNTH_CLOCK=1 run_it "$script" "$cfg" "$tag")
  man="$bdir/cft_hw.manifest.txt"
  pre="$bdir/synth_clock_pre.tcl"
  xdc="$bdir/synth_clock.xdc"
  want=$(sed -n 's/^[[:space:]]*nk=[^:]*:[0-9]*:\(.*\)$/\1/p' "$ROOT/$cfg" | tr '.' ' ')
  got=$(sed -n 's/^run\.ulp_\(.*\)_0_synth_1\.{STEPS\.SYNTH_DESIGN\.TCL\.PRE}=.*$/\1/p' "$log" | tr '\n' ' ' | sed 's/ $//')
  [ "$got" = "$want" ] || { echo "  FAIL $tag: the hook reaches '$got', not every CU '$want'"; bad=$((bad + 1)); }
  # One file for all, absolute, existing - Vivado sources it from the
  # run's directory, so a path relative to the repository root would not
  # be found there (the relative-BUILD leg is what makes this checkable).
  hook=$(sed -n 's/^run\.ulp_.*_0_synth_1\.{STEPS\.SYNTH_DESIGN\.TCL\.PRE}=//p' "$log" | sort -u)
  case "$hook" in
    /*) ;;
    *) echo "  FAIL $tag: the hook path '$hook' is not absolute"; bad=$((bad + 1));;
  esac
  if [ "$hook" != "$(cd "$bdir" 2>/dev/null && pwd)/synth_clock_pre.tcl" ] || [ ! -f "$pre" ]; then
    echo "  FAIL $tag: the hook is not one existing \$BUILD/synth_clock_pre.tcl"; bad=$((bad + 1))
  fi
  grep -qx 'create_clock -period 7.407 -name cft_synth_ooc_clk \[get_ports ap_clk\]' "$xdc" 2>/dev/null \
    || { echo "  FAIL $tag: synth_clock.xdc is not a 7.407 ns create_clock on ap_clk"; bad=$((bad + 1)); }
  grep -qxF "read_xdc -mode out_of_context {$(cd "$bdir" 2>/dev/null && pwd)/synth_clock.xdc}" "$pre" 2>/dev/null \
    && grep -qxF "set_property used_in_implementation false [get_files -all {$(cd "$bdir" 2>/dev/null && pwd)/synth_clock.xdc}]" "$pre" \
    || { echo "  FAIL $tag: the hook does not read the XDC out of context and mark it used_in_implementation false"; bad=$((bad + 1)); }
  # In that order: set_property on a file not yet read finds nothing and
  # fails the run (Vivado's run script sources the hook inside a catch).
  rl=$(grep -n '^read_xdc ' "$pre" 2>/dev/null | head -1 | cut -d: -f1)
  sl=$(grep -n '^set_property used_in_implementation false' "$pre" 2>/dev/null | head -1 | cut -d: -f1)
  if [ -z "$rl" ] || [ -z "$sl" ] || [ "$rl" -ge "$sl" ]; then
    echo "  FAIL $tag: the hook does not read the XDC before it marks it (lines ${rl:-none} and ${sl:-none})"; bad=$((bad + 1))
  fi
  case "$(clock_arg_of "$log")" in
    135000000:*) ;;
    *) echo "  FAIL $tag: --clock.freqHz went missing with SYNTH_CLOCK=1"; bad=$((bad + 1));;
  esac
  [ "$(retimed_cus_of "$log")" = "$want" ] \
    || { echo "  FAIL $tag: RETIMING no longer reaches every CU with SYNTH_CLOCK=1"; bad=$((bad + 1)); }
  if grep -l 'Using cached IP synthesis design' "$bdir"/_x_hw/link/vivado/vpl/prj/prj.runs/ulp_*_synth_1/runme.log > /dev/null 2>&1; then
    echo "  FAIL $tag: a hooked run is a cache hit; Vivado gives a run with a TCL.PRE no cache"; bad=$((bad + 1))
  fi
  grep -q '^synth_clock:   1 ' "$man" 2>/dev/null || { echo "  FAIL $tag: the manifest does not say synth_clock: 1"; bad=$((bad + 1)); }
  sr=$(sed -n 's/^synth_clock_runs: //p' "$man" 2>/dev/null)
  [ "$sr" = "$want" ] || { echo "  FAIL $tag: the manifest's synth_clock_runs is '$sr', not '$want'"; bad=$((bad + 1)); }
  me=$(sed -n 's/^retiming_effect: //p' "$man" 2>/dev/null)
  [ "$me" = "$(for c in $want; do printf '%s:retimed(forward=3,backward=5,reports=1) ' "$c"; done | sed 's/ $//')" ] \
    || { echo "  FAIL $tag: the manifest's retiming_effect is '$me'"; bad=$((bad + 1)); }
  [ "$bad" = 0 ] && echo "  ok   $tag: the hook on every CU ($got) at an absolute path, a 7.407 ns clock read out of context and then marked, no cache, retiming_effect retimed"
  return "$bad"
}
echo "== SYNTH_CLOCK=1: every CU's synthesis run reads the kernel clock =="
for pair in "hw/link.cfg:sc-single" "hw/link_quad.cfg:sc-quad"; do
  cfg=${pair%%:*}; tag=${pair#*:}
  sc_check "$SCRIPT" "$cfg" "$tag" || fails=$((fails + 1))
done

# A relative BUILD, as BITSTREAM-BUILDS writes it: the hook's path must
# still be absolute. Every leg above passes an absolute BUILD, where a
# hook path left as given would pass unseen (verifier-VRT's F15).
echo "== SYNTH_CLOCK=1 with a relative BUILD: the hook's path is still absolute =="
if [ -e "$ROOT/$REL_BASE" ]; then
  say_fail "relative BUILD: $REL_BASE exists and is not this run's, so the leg is not run"
else
  REL_MADE=1
  BUILD_FOR_RUN="$REL_BASE/rel" sc_check "$SCRIPT" "hw/link.cfg" "sc-rel" "$ROOT/$REL_BASE/rel" \
    || fails=$((fails + 1))
fi

# hw_emu synthesizes no kernel: the hook goes on hw's link alone, and
# hw_emu's manifest says synth_clock: 0 (verifier-VRT's F7).
emu_check() {                   # emu_check <script> <tag>
  local script=$1 tag=$2 log per bad=0
  log=$(SYNTH_CLOCK=1 TARGETS_FOR_RUN="hw hw_emu" run_it "$script" "hw/link.cfg" "$tag")
  per=$(awk '$0 == "-l" { inv++ }
             prev == "-t" { t[inv] = $0 }
             { if ($0 ~ /STEPS\.SYNTH_DESIGN\.TCL\.PRE/) h[inv]++; prev = $0 }
             END { for (i = 1; i <= inv; i++) printf "%s%s:%d", (i > 1 ? " " : ""), t[i], h[i] + 0 }' "$log")
  [ "$per" = "hw:1 hw_emu:0" ] || { echo "  FAIL $tag: the hooks per link are '$per', not 'hw:1 hw_emu:0'"; bad=$((bad + 1)); }
  [ "$(cat "$TMP/rc-$tag")" = 0 ] || { echo "  FAIL $tag: the build exited $(cat "$TMP/rc-$tag")"; bad=$((bad + 1)); }
  grep -qx 'synth_clock:   0' "$TMP/build-$tag/cft_hw_emu.manifest.txt" 2>/dev/null \
    || { echo "  FAIL $tag: hw_emu's manifest does not say synth_clock: 0"; bad=$((bad + 1)); }
  [ "$bad" = 0 ] && echo "  ok   $tag: the hook on hw's link alone ($per), and hw_emu's manifest says synth_clock: 0"
  return "$bad"
}
echo "== SYNTH_CLOCK=1 with TARGETS=\"hw hw_emu\": the hook on hw's link alone =="
emu_check "$SCRIPT" "sc-emu" || fails=$((fails + 1))

# RETIMING, PHYS_OPT and SYNTH_CLOCK refuse anything but 0 or 1, by name
# and before any work - no BUILD directory made - so that "true" or
# "yes" cannot quietly build with the flag off.
refuse_check() {                # refuse_check <script> <tag> <variable> <value>
  local script=$1 tag=$2 var=$3 v=$4 log
  if [ "$var" = RETIMING ]; then
    log=$(RETIMING_FOR_RUN="$v" run_it "$script" "hw/link.cfg" "$tag")
  else
    log=$(export "$var=$v"; run_it "$script" "hw/link.cfg" "$tag")
  fi
  if [ "$(cat "$TMP/rc-$tag")" = 0 ]; then
    echo "  FAIL $tag: $var=$v built"; return 1
  elif [ -s "$log" ]; then
    echo "  FAIL $tag: $var=$v failed only after v++ ran"; return 1
  elif [ -e "$TMP/build-$tag" ]; then
    echo "  FAIL $tag: $var=$v was refused only after work began (BUILD was made)"; return 1
  elif ! grep -q "$var is 0 or 1; got '$v'" "$TMP/out-$tag.txt"; then
    echo "  FAIL $tag: $var=$v stopped, but not by name"; return 1
  fi
  echo "  ok   $tag: $var=$v refused by name before any work (rc=$(cat "$TMP/rc-$tag"), no BUILD made)"
}
echo "== RETIMING, PHYS_OPT and SYNTH_CLOCK other than 0 or 1: refused by name, before any work =="
for pair in SYNTH_CLOCK:yes SYNTH_CLOCK:true SYNTH_CLOCK:2 RETIMING:yes PHYS_OPT:true; do
  refuse_check "$SCRIPT" "val-${pair%%:*}-${pair#*:}" "${pair%%:*}" "${pair#*:}" || fails=$((fails + 1))
done

# retiming_effect:, the real function cut from rebuild-2022.sh, on a log
# of each kind. What each prints, and why, is the script's own comment;
# the stub's logs above reach only two of the thirteen (verifier-VRT's
# F11, F16 and the edges it named; verifier-VRTb's tag, report-without-
# flag and path cases; a CRLF log whose command ends in the flag).
effect_check() {                # effect_check <script> <tag>
  local script=$1 tag=$2 d="$TMP/eff-$2" fn got want name pair bad=0
  local cmd_rt='Command: synth_design -top ulp_cft_krnl_1_0 -part xcu50 -retiming -mode out_of_context'
  local cmd='Command: synth_design -top ulp_cft_krnl_1_0 -part xcu50 -mode out_of_context'
  local decl='INFO: [Synth 8-11322] No global retiming is needed without any clock constraint'
  mkdir -p "$d"
  fn="$d/retime_effect.sh"
  awk '/^    retime_effect\(\) \{$/ { f = 1 } f { print } f && /^    \}$/ { exit }' "$script" > "$fn"
  if ! ( . "$fn" && type retime_effect > /dev/null 2>&1 ); then
    echo "  FAIL $tag: retime_effect() could not be cut from $(basename "$script"); re-aim the cut"
    return 1
  fi
  eff_report() { printf 'Retiming Report:\n|Forward Retiming    | %s   | \n|Backward Retiming   | %s   | \n' "$1" "$2"; }
  { echo "$cmd_rt"; eff_report 3 5; } > "$d/moves"
  { echo "$cmd_rt"; eff_report 0 0; } > "$d/nomoves"
  { echo "$cmd_rt"; eff_report 3 5; eff_report 1 1; } > "$d/two"
  { echo "$cmd_rt"; echo "$decl"; eff_report 3 5; } > "$d/both"
  { echo "$cmd_rt"; echo "$decl"; } > "$d/declined"
  echo "$cmd_rt" > "$d/asked"
  { echo "$cmd"; echo "$decl"; } > "$d/unflagged"
  : > "$d/empty"
  # The message's words echoed untagged, as a probe's log echoes its Tcl.
  { echo "$cmd_rt"; echo "#   foreach id {{Synth 8-11322} {Synth 8-5816}} {"; } > "$d/echoed"
  { echo "$cmd_rt"; echo "#   foreach id {{Synth 8-11322} {Synth 8-5816}} {"; eff_report 3 5; } > "$d/echoedrep"
  { echo "$cmd"; eff_report 3 5; } > "$d/unflaggedrep"
  echo 'Command: synth_design -top ulp_cft_krnl_1_0 -part xcu50 -include_dirs /data/x-retiming/rtl -mode out_of_context' > "$d/pathflag"
  printf '%s\r\n%s\r\n' 'Command: synth_design -top ulp_cft_krnl_1_0 -part xcu50 -mode out_of_context -retiming' "$decl" > "$d/crlf"
  for pair in "moves:retimed(forward=3,backward=5,reports=1)" \
              "nomoves:ran-no-moves(reports=1)" \
              "two:retimed(forward=4,backward=6,reports=2)" \
              "both:retimed(forward=3,backward=5,reports=1,declined=1)" \
              "declined:declined-no-clock" \
              "asked:asked-no-report" \
              "unflagged:not-asked" \
              "empty:not-asked" \
              "echoed:asked-no-report" \
              "echoedrep:retimed(forward=3,backward=5,reports=1)" \
              "unflaggedrep:not-asked" \
              "pathflag:not-asked" \
              "crlf:declined-no-clock"; do
    name=${pair%%:*}; want=${pair#*:}
    got=$( . "$fn" && retime_effect "$d/$name" )
    [ "$got" = "$want" ] || { echo "  FAIL $tag: a '$name' log gives '$got', not '$want'"; bad=$((bad + 1)); }
  done
  [ "$bad" = 0 ] && echo "  ok   $tag: thirteen kinds of log, each named as the script's comment says"
  return "$bad"
}
echo "== retiming_effect: the real function on a log of each kind =="
effect_check "$SCRIPT" "effect" || fails=$((fails + 1))

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
  echo "  ok   no log: cft_krnl_2 named unresolved, the other three given -retiming"
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
    echo "  ok   control: the sabotaged quad gives -retiming to '$rt' alone, its manifest says '$mr', and this test sees it"
  elif [ "$rt" = "cft_krnl_1" ]; then
    say_fail "control: the argv gives -retiming to cft_krnl_1 alone, but the manifest says '$mr'"
  else
    say_fail "control: the sabotaged quad gave -retiming to '$rt', not the defect's cft_krnl_1"
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
# The hook without used_in_implementation false. In the toys the clock
# stayed out of the in-context design without it too (that read_xdc
# -mode out_of_context is what did that is believed, not shown), so this
# control holds Vivado's own idiom for an IP's out-of-context XDC, not a
# measured leak.
if ! sab sab-sc-impl '/used_in_implementation false/d'; then
  say_fail "control sab-sc-impl: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif sc_check "$TMP/sab-sc-impl.sh" "hw/link.cfg" "sab-sc-impl" > "$TMP/ctl-impl.txt"; then
  say_fail "control: a hook without used_in_implementation false passed the SYNTH_CLOCK check"
else
  echo "  ok   control: a hook without used_in_implementation false fails the SYNTH_CLOCK check ($(grep -c FAIL "$TMP/ctl-impl.txt") findings)"
fi
# The hook's directory left as BUILD gave it (F15): only the relative
# leg can see it.
if ! sab sab-sc-rel 's/^    scdir=\$(cd "\$BUILD" && pwd)$/    scdir=$BUILD/'; then
  say_fail "control sab-sc-rel: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif [ "$REL_MADE" != 1 ]; then
  say_fail "control sab-sc-rel: the relative-BUILD leg did not run, so neither can this"
elif BUILD_FOR_RUN="$REL_BASE/sab" sc_check "$TMP/sab-sc-rel.sh" "hw/link.cfg" "sab-sc-rel" "$ROOT/$REL_BASE/sab" > "$TMP/ctl-rel.txt"; then
  say_fail "control: a hook path left relative passed the SYNTH_CLOCK check"
else
  echo "  ok   control: a hook path left relative fails the SYNTH_CLOCK check ($(grep -c FAIL "$TMP/ctl-rel.txt") findings)"
fi
# The hook on hw_emu's link too (F7).
if ! sab sab-sc-emu 's/^  if \[ "\$SYNTH_CLOCK" = 1 \] && \[ "\$t" = "hw" \]; then$/  if [ "$SYNTH_CLOCK" = 1 ]; then/'; then
  say_fail "control sab-sc-emu: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif emu_check "$TMP/sab-sc-emu.sh" "sab-sc-emu" > "$TMP/ctl-emu.txt"; then
  say_fail "control: a hook on hw_emu's link passed the hw_emu check"
else
  echo "  ok   control: a hook on hw_emu's link too fails the hw_emu check ($(grep -c FAIL "$TMP/ctl-emu.txt") findings)"
fi
# The hook marking the XDC before it reads it (F8): Vivado would fail
# the run at the hook.
if ! sab sab-sc-order '/echo "read_xdc -mode out_of_context/{h;d;};/echo "set_property used_in_implementation false/G'; then
  say_fail "control sab-sc-order: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif sc_check "$TMP/sab-sc-order.sh" "hw/link.cfg" "sab-sc-order" > "$TMP/ctl-order.txt"; then
  say_fail "control: a hook that marks the XDC before reading it passed the SYNTH_CLOCK check"
else
  echo "  ok   control: a hook that marks the XDC before reading it fails the SYNTH_CLOCK check ($(grep -c FAIL "$TMP/ctl-order.txt") findings)"
fi
# The decline tested before the report (F11).
if ! sab sab-eff-order 's/^      local f=\$1$/      local f=$1; if grep -q "Synth 8-11322" "$f"; then echo declined-no-clock; return; fi/'; then
  say_fail "control sab-eff-order: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif effect_check "$TMP/sab-eff-order.sh" "sab-eff-order" > "$TMP/ctl-eff-order.txt"; then
  say_fail "control: retime_effect testing the decline first passed the log check"
else
  echo "  ok   control: retime_effect testing the decline first fails the log check ($(grep -c FAIL "$TMP/ctl-eff-order.txt") findings)"
fi
# The asked-no-report branch gone (F16).
if ! sab sab-eff-asked 's/else echo "asked-no-report"/else echo "not-asked"/'; then
  say_fail "control sab-eff-asked: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif effect_check "$TMP/sab-eff-asked.sh" "sab-eff-asked" > "$TMP/ctl-eff-asked.txt"; then
  say_fail "control: retime_effect without its asked-no-report branch passed the log check"
else
  echo "  ok   control: retime_effect without its asked-no-report branch fails the log check ($(grep -c FAIL "$TMP/ctl-eff-asked.txt") findings)"
fi
# The value check gone: "yes" would build with the flag off.
if ! sab sab-sc-val 's/^    0 | 1) ;;$/    *) ;;/'; then
  say_fail "control sab-sc-val: its pattern no longer matches hw/rebuild-2022.sh; re-aim it"
elif refuse_check "$TMP/sab-sc-val.sh" "sab-sc-val" "SYNTH_CLOCK" "yes" > "$TMP/ctl-val.txt"; then
  say_fail "control: a script without the value check refused SYNTH_CLOCK=yes anyway"
else
  echo "  ok   control: without the value check SYNTH_CLOCK=yes builds, and the refusal check sees it"
fi

# The rest, as sed scripts (quoted here-documents, so nothing in them is
# the shell's): sab_f <name> <sed-script> writes $TMP/<name>.sh and fails
# when the script changes nothing.
sab_f() {
  sed -f "$2" "$SCRIPT" > "$TMP/$1.sh"
  ! cmp -s "$SCRIPT" "$TMP/$1.sh"
}
ctl_effect() {                  # ctl_effect <name> <what it plants>
  if ! sab_f "$1" "$TMP/$1.sed"; then
    say_fail "control $1: its sed script no longer changes hw/rebuild-2022.sh; re-aim it"
  elif effect_check "$TMP/$1.sh" "$1" > "$TMP/ctl-$1.txt"; then
    say_fail "control: $2 passed the log check"
  else
    echo "  ok   control: $2 fails the log check ($(grep -c FAIL "$TMP/ctl-$1.txt") findings)"
  fi
}
# The decline matched untagged again, in the branch and in the count
# (verifier-VRTb's P4 and P4b): echoed script text would read as one.
cat > "$TMP/sab-eff-untag.sed" <<'SED'
/then echo "declined-no-clock"$/c\
      elif grep -q 'Synth 8-11322' "$f"; then echo "declined-no-clock"
SED
ctl_effect sab-eff-untag "retime_effect matching the decline untagged"
cat > "$TMP/sab-eff-untagcount.sed" <<'SED'
/{ d++ }$/c\
                   /Synth 8-11322/ { d++ }
SED
ctl_effect sab-eff-untagcount "retime_effect counting the decline untagged"
# The flag tested only where no report is (P1): a report without the
# flag would read as retimed.
cat > "$TMP/sab-eff-reportfirst.sed" <<'SED'
/then echo "not-asked"$/c\
      if ! grep -qE 'Command: synth_design.* -retiming([[:space:]]|$)' "$f" && ! grep -q '^Retiming Report:' "$f"; then echo "not-asked"
SED
ctl_effect sab-eff-reportfirst "retime_effect testing the flag only without a report"
# The flag as a substring again: a path holding "-retiming" would read
# as the flag.
cat > "$TMP/sab-eff-substring.sed" <<'SED'
/then echo "not-asked"$/c\
      if ! grep -q 'Command: synth_design.*-retiming' "$f"; then echo "not-asked"
SED
ctl_effect sab-eff-substring "retime_effect testing the flag as a substring"
# The value check moved after the build directory is made (the gap
# verifier-VRTb's N6d found): still before v++, no longer before any work.
cat > "$TMP/sab-val-late.sed" <<'SED'
/^for v in RETIMING PHYS_OPT SYNTH_CLOCK; do$/,/^done$/{
H
d
}
/^mkdir -p "\$BUILD"$/{
p
x
s/^\n//
}
SED
if ! sab_f sab-val-late "$TMP/sab-val-late.sed"; then
  say_fail "control sab-val-late: its sed script no longer changes hw/rebuild-2022.sh; re-aim it"
elif refuse_check "$TMP/sab-val-late.sh" "sab-val-late" "SYNTH_CLOCK" "yes" > "$TMP/ctl-val-late.txt"; then
  say_fail "control: a value check after the build directory is made passed the refusal check"
else
  echo "  ok   control: a value check after the build directory is made fails the refusal check"
fi

echo
if [ "$fails" -eq 0 ]; then
  echo "rebuild-2022.sh: the clock constraint survives VPP_PROPS, RETIMING=1"
  echo "reaches the synthesis run of every CU, CFT_GENERICS"
  echo "reaches vivado and the manifest, a lying wrapper read-back stops the"
  echo "build before v++, TARGETS=\"\" packages without linking, SYNTH_CLOCK"
  echo "is off by default; it, RETIMING and PHYS_OPT refuse anything but 0 or"
  echo "1 before any work; with SYNTH_CLOCK=1 every CU's hw synthesis reads"
  echo "the kernel clock through an absolute hook, also under a relative"
  echo "BUILD; retiming_effect names thirteen kinds of log; and each check"
  echo "still fails when its defect is put back."
  exit 0
fi
echo "$fails failure(s); stub output under $TMP (kept only until exit)"
exit 1
