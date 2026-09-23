#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# hw/sweep_freq.sh's verdicts, held to synthetic builds: no Vivado, no
# card; seconds on Linux, about a minute under Git Bash, whose process
# start-up is the cost.
#
# The judge is the part of a sweep that can lie - a point that missed,
# reported as one that closed - and the first sweep_freq.sh would have
# done it two ways. Both are negative controls: each defect is put back
# into a copy of the script, and the case written for it must catch it.
#  - the whole-design WNS is the shell's positive 0.055 ns while the
#    kernel clock misses (the first version read the whole-design number);
#  - an image was staged with a negative kernel WNS (build-pair stages
#    whatever v++ let through; "staged" is not "closed").
# The refusals are held too: nothing on disk, a manifest that says
# "unknown", a manifest that no longer agrees with the summary it names,
# a kernel clock missing from the Intra Clock Table, and a kernel clock of
# another name must each be NONE, never a guess.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAILS=0
CHECK_ENV=""

# summary <build-dir> <kernel WNS | -> [file] - a timing summary in the
# shape Vivado writes: the design summary first, carrying the SHELL's
# 0.055 ns; the kernel clock indented in the Intra Clock Table, as a
# derived clock is ("-" leaves it out); the same clock again in the Inter
# Clock Table after it, where the second column is another clock's name.
summary () {
  local d="$1/_x_hw/link/vivado/vpl/prj/prj.runs/impl_1" row=""
  mkdir -p "$d"
  [ "$2" = - ] || row="  clk_out1_ulp_clk_wiz_0            $2        0.000                      0               540213"
  cat > "$d/${3:-hw_bb_locked_timing_summary_routed.rpt}" << EOF
------------------------------------------------------------------------------------------------
| Design Timing Summary
| ---------------------
------------------------------------------------------------------------------------------------

    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)
    -------      -------  ---------------------  -------------------      -------      -------
      0.055        0.000                      0               576352        0.009        0.000


------------------------------------------------------------------------------------------------
| Intra Clock Table
| -----------------
------------------------------------------------------------------------------------------------

Clock                             WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints
-----                             -------      -------  ---------------------  -------------------
io_clk_freerun_00                   7.301        0.000                      0                   12
hbm_aclk                            0.055        0.000                      0                91204
$row


------------------------------------------------------------------------------------------------
| Inter Clock Table
| -----------------
------------------------------------------------------------------------------------------------

From Clock                        To Clock                          WNS(ns)      TNS(ns)
----------                        --------                          -------      -------
clk_out1_ulp_clk_wiz_0            hbm_aclk                            9.999        0.000
EOF
}

# manifest <file> <kernel WNS> [timing_report] - the keys hw/rebuild-2022.sh writes
manifest () {
  mkdir -p "$(dirname "$1")"
  { echo "kernel_freq:   150000000"
    [ -n "${3:-}" ] && echo "timing_report:  $3"
    echo "routed_wns_ns: 0.055   # whole design, shell included"
    echo "kernel_clock:  clk_out1_ulp_clk_wiz_0"
    echo "kernel_wns_ns: $2   # THIS is the design's margin"
  } > "$1"
}

# check <script> <name> <verdict> <kernel WNS> <judge args...>
check () {
  local s=$1 name=$2 want=$3 wantw=$4 out rc got gotw wantrc; shift 4
  out=$(env $CHECK_ENV bash "$s" --judge "$@" 2>&1); rc=$?
  got=$(echo "$out" | sed -n 's/^[^:]*: \([A-Z]*\), kernel WNS .*/\1/p')
  gotw=$(echo "$out" | sed -n 's/.*, kernel WNS \([^ ]*\) ns .*/\1/p')
  case "$want" in CLOSED) wantrc=0 ;; MISSED) wantrc=1 ;; *) wantrc=2 ;; esac
  if [ "$got" = "$want" ] && [ "$gotw" = "$wantw" ] && [ "$rc" -eq "$wantrc" ]; then
    echo "  ok    $name: $out"; return 0
  fi
  echo "  FAIL  $name: wanted $want, kernel WNS $wantw, exit $wantrc; got exit $rc: $out"
  return 1
}

R=hw_bb_locked_timing_summary_routed.rpt
P=hw_bb_locked_timing_summary_postroute_physopted.rpt

summary "$T/closed" 0.120; summary "$T/closed" 0.120 "$P"
manifest "$T/stage-closed/cft_hw_single.manifest.txt" 0.120 "$R"; : > "$T/stage-closed/cft_hw_single.xclbin"
summary "$T/unstaged" 0.084
summary "$T/whole-design" -0.070
summary "$T/staged-neg" -0.050
manifest "$T/stage-neg/cft_hw_single.manifest.txt" -0.050 "$R"; : > "$T/stage-neg/cft_hw_single.xclbin"
summary "$T/physopt" -0.010; summary "$T/physopt" 0.020 "$P"
manifest "$T/physopt/cft_hw.manifest.txt" -0.010 "$R"
summary "$T/dr-only" -0.300 dr_timing_summary.rpt
mkdir -p "$T/manifest-only"; manifest "$T/manifest-only/cft_hw.manifest.txt" 0.050 "$R"
mkdir -p "$T/empty"
mkdir -p "$T/unknown"; manifest "$T/unknown/cft_hw.manifest.txt" unknown
summary "$T/disagree" -0.010; manifest "$T/disagree/cft_hw.manifest.txt" 0.120 "$R"
summary "$T/old-manifest" -0.010; manifest "$T/old-manifest/cft_hw.manifest.txt" 0.120
summary "$T/no-row" -

cases () {  # <script>  ->  returns the number of cases it judged wrong
  local s=$1 bad=0
  check "$s" "closed, staged, three records agree"  CLOSED 0.120 "$T/closed" --image "$T/stage-closed/cft_hw_single.xclbin" || bad=$((bad + 1))
  check "$s" "closed, not staged"                   CLOSED 0.084 "$T/unstaged" || bad=$((bad + 1))
  check "$s" "CONTROL shell +0.055, kernel -0.070"  MISSED -0.070 "$T/whole-design" || bad=$((bad + 1))
  check "$s" "CONTROL staged with a negative WNS"   MISSED -0.050 "$T/staged-neg" --image "$T/stage-neg/cft_hw_single.xclbin" || bad=$((bad + 1))
  check "$s" "post-route phys_opt closed it"        CLOSED 0.020 "$T/physopt" || bad=$((bad + 1))
  check "$s" "a failed link, dr summary only"       MISSED -0.300 "$T/dr-only" || bad=$((bad + 1))
  check "$s" "the manifest alone"                   CLOSED 0.050 "$T/manifest-only" || bad=$((bad + 1))
  check "$s" "nothing on disk"                      NONE none "$T/empty" || bad=$((bad + 1))
  check "$s" "manifest says unknown"                NONE none "$T/unknown" || bad=$((bad + 1))
  check "$s" "manifest disagrees with its summary"  NONE none "$T/disagree" || bad=$((bad + 1))
  check "$s" "older manifest, routed disagrees"     NONE none "$T/old-manifest" || bad=$((bad + 1))
  check "$s" "kernel clock not in the Intra table"  NONE none "$T/no-row" || bad=$((bad + 1))
  CHECK_ENV="KERNEL_CLK=clk_kernel_00"
  check "$s" "a kernel clock of another name"       NONE none "$T/closed" || bad=$((bad + 1))
  CHECK_ENV=""
  return "$bad"
}
NCASES=13

echo "== hw/sweep_freq.sh --judge, as committed"
cases "$ROOT/hw/sweep_freq.sh"; n=$?
[ "$n" -eq 0 ] || { echo "FAIL: $n of $NCASES case(s) judged wrong"; FAILS=$((FAILS + 1)); }

# Each control: the defect put back into a copy that still parses, and the
# case written for it must be among those that catch it.
control () {  # <name> <marker> <replacement line> <the case that must catch it>
  local c="$T/sweep_freq.$1.sh"
  grep -q "$2" "$ROOT/hw/sweep_freq.sh" || { echo "FAIL: control $1 - marker $2 not found"; FAILS=$((FAILS + 1)); return; }
  # The line through ENVIRON, which awk takes literally; -v would read its
  # backslashes as escapes and put back a line other than the one written.
  REPL="$3" awk -v m="$2" 'index($0, m) {print ENVIRON["REPL"]; next} {print}' "$ROOT/hw/sweep_freq.sh" > "$c"
  echo "== negative control, $1"
  bash -n "$c" || { echo "FAIL: control $1 - the copy does not parse, so it proves nothing"; FAILS=$((FAILS + 1)); return; }
  cases "$c" > "$T/control.out" 2>&1
  if grep -q "FAIL  $4:" "$T/control.out"; then
    grep "FAIL  $4:" "$T/control.out" | cut -c1-200
    echo "  caught by \"$4\" ($(grep -c 'FAIL  ' "$T/control.out") case(s) wrong in all)"
  else
    cat "$T/control.out"
    echo "FAIL: control $1 - the defect was put back and \"$4\" did not catch it"
    FAILS=$((FAILS + 1))
  fi
}
control whole-design-wns JUDGE-READS-KERNEL-CLOCK \
  "  awk '/Design Timing Summary/ {f = 1} f && \$1 ~ /^-?[0-9]+\\.[0-9]+\$/ {print \$1; exit}' \"\$1\" 2> /dev/null" \
  "CONTROL shell +0.055, kernel -0.070"
control staged-is-closed JUDGE-SIGN-ONLY \
  "  if [ -n \"\$J_IMAGE\" ]; then J_VERDICT=CLOSED; else case \"\$J_KWNS\" in -*) J_VERDICT=MISSED ;; *) J_VERDICT=CLOSED ;; esac; fi" \
  "CONTROL staged with a negative WNS"

if [ "$FAILS" -eq 0 ]; then
  echo "PASS: $NCASES verdicts right, both controls caught by their own cases"
  exit 0
fi
echo "FAIL: $FAILS problem(s)"
exit 1
