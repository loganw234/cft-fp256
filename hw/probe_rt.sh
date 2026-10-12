#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Probe RT's driver (the step-6 leftovers round, parcel RT): does
# RETIMING=1 retime? For a build host with Vivado 2022.2 - amd-arc-box, by
# the lead, never beside a link or another Vivado.
#
#   bash hw/probe_rt.sh [out_dir]
#
# Runs hw/probe_rt.tcl on THIS tree's rtl/ - cft_krnl out of context with
# rev8a's generics (SEQ_SCRATCH_D=4096, every other parameter at its
# default, EN_AUGADD among them at 1) - in four ways, one at a time:
#
#   a   no -retiming, no clock          a build with RETIMING=0
#   b   -retiming, no clock             what every link has run since 2026-09-02
#   c   -retiming, a clock at FREQ      what RETIMING=1 was believed to do
#   d   the clock, no -retiming         what the clock alone does
#
# The clock of c and d is a create_clock on ap_clk in an XDC read before
# synth_design; a and b get the same clock after synthesis, for their
# estimate only. Each run's funcsim netlist is hashed with its comment
# lines removed (they hold the date and the command) and then gzipped.
#
# WHAT EACH OUTCOME MEANS (the summary prints the one that happened):
#   a == b (the hashes equal)  -retiming without a clock changed nothing
#       in this synthesis. Carrying that to a link's kernel needs b to be
#       the link's synthesis: LINK_LOG sets b's cell usage beside it. On
#       2026-10-12 a == b on the whole revision-8 kernel, but 11 of the
#       26 rows differed from rev8a's link, so the in-link proof was the
#       lead's comparison of revision 7's q135 netlists, krnl_1 with the
#       flag and krnl_4 without (docs/VALIDATION.md, 2026-10-12).
#   a != b  the flag acts without a clock. Then a is run again (a2): a2 ==
#       a says the difference is the flag's, a2 != a that synthesis is not
#       reproducible here and the fingerprint cannot decide.
#   c vs d  what retiming does when it has a clock: c's log carries
#       Vivado's "Retiming Report:" (forward and backward moves, registers
#       added and deleted), its netlist *_bret*/*_fret* registers, and the
#       two WNS figures say what it buys out of context.
#   d vs a  what the clock alone does to synthesis (it is timing-driven by
#       default), which a fix that gives the link's synthesis its clock
#       brings with or without RETIMING.
#
# REPLAY=1 adds the 2026-09-02 replay: hw/ooc_retime.tcl's "same source,
# same commit, one flag" A/B (docs/ROADMAP.md, "Two experiments against
# that finding") had no clock during synthesis either. x0902a and x0902b
# synthesize 2b57cf0's rtl (the commit that recorded it) in ways a and b;
# x0901a synthesizes a445268's (09-01's "shared array, seq diet, ladders
# off" tree, the baseline row's figures) in way a. Both trees come from
# git archive and are asserted by content: 2b57cf0's carries 8f5f149's
# register on the reduce operands (red_add_a_q), a445268's does not.
# Not run: Logan chose to skip it (2026-10-12), the old figures standing
# as not retiming's with their cause believed.
#
# Env: VIVADO_SETTINGS (default /data/Xilinx/Vivado/2022.2/settings64.sh),
#      FREQ (135), PART (xcu50-fsvh2104-2-e), TOP (cft_krnl), CLOCK_PORT
#      (ap_clk), GENERICS ("SEQ_SCRATCH_D=4096", rev8a's), MODES ("a b c
#      d"), THREADS (1: general.maxThreads - the link's kernel synthesis
#      ran "a maximum of 1 processes", so b is the link's run as nearly as
#      a standalone synthesis can be; 8 is faster and the a/b comparison
#      holds either way, since both ways run at one setting), RTL (this
#      tree's rtl/), EXPECT_RTL (rev8a's rtl tree, 44b963dd...; empty
#      skips the tree assertions, for a toy), LINK_LOG (a link's kernel
#      synthesis runme.log, plain or .gz, whose Report Cell Usage b's is
#      set beside), REPLAY (0), TIMEOUT_MIN (180 a run), MIN_GB (16).
#
# Exit 0 PASS (every run finished), 1 refused, 2 usage, 3 FAIL (a run did
# not finish or a check failed), 4 INCOMPLETE (a run timed out).
set -u
out=${1:-build_probe_rt}
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
VIVADO_SETTINGS=${VIVADO_SETTINGS:-/data/Xilinx/Vivado/2022.2/settings64.sh}
FREQ=${FREQ:-135}
PART=${PART:-xcu50-fsvh2104-2-e}
TOP=${TOP:-cft_krnl}
CLOCK_PORT=${CLOCK_PORT:-ap_clk}
GENERICS=${GENERICS-SEQ_SCRATCH_D=4096}
# `-` not `:-`: MODES="" with REPLAY=1 runs the replay alone.
MODES=${MODES-a b c d}
THREADS=${THREADS:-1}
RTL=${RTL:-$root/rtl}
EXPECT_RTL=${EXPECT_RTL-44b963dd6ba2fcf99e002c5face5ca94aad4515c}
LINK_LOG=${LINK_LOG:-}
REPLAY=${REPLAY:-0}
TIMEOUT_MIN=${TIMEOUT_MIN:-180}
MIN_GB=${MIN_GB:-16}

for m in $MODES; do
  case "$m" in a|b|c|d) ;; *) echo "MODES holds '$m'; the ways are a b c d" >&2; exit 2;; esac
done
if [ -z "${MODES// /}" ] && [ "$REPLAY" != 1 ]; then
  echo "nothing to run: MODES is empty and REPLAY is not 1" >&2; exit 2
fi

# The tree, asserted by hash AND by content (CLAUDE.md, "Before believing
# a remote build"): a checkout whose SHA is right and whose files never
# updated is the failure rev-parse cannot see. The markers are rev8a's box
# script's: R24's C_QUIET and R22's stp_vec in cft_seq, the 2,048-slot
# default this probe overrides, and EN_AUGADD's default of 1.
if [ -n "$EXPECT_RTL" ]; then
  got=$(git -C "$root" rev-parse HEAD:rtl 2>/dev/null)
  [ "$got" = "$EXPECT_RTL" ] || {
    echo "this tree's rtl is '$got', not rev8a's $EXPECT_RTL" >&2; exit 1; }
  [ -z "$(git -C "$root" status --porcelain --untracked-files=all -- rtl/ 2>/dev/null)" ] || {
    echo "rtl/ differs from HEAD; this probe reads the committed rtl" >&2; exit 1; }
  [ "$RTL" = "$root/rtl" ] || { echo "RTL is set, and EXPECT_RTL asserts this tree's rtl/" >&2; exit 1; }
  grep -q C_QUIET "$RTL/cft_seq.sv" && grep -q stp_vec "$RTL/cft_seq.sv" \
    && grep -q 'parameter int SEQ_SCRATCH_D = 2048' "$RTL/cft_krnl.sv" \
    && grep -q "parameter bit EN_AUGADD     = 1'b1" "$RTL/cft_krnl.sv" || {
    echo "this tree's rtl lacks one of rev8a's markers (C_QUIET, stp_vec, the 2,048-slot default, EN_AUGADD 1)" >&2; exit 1; }
fi
[ -d "$RTL" ] || { echo "no rtl directory at $RTL" >&2; exit 2; }

# One heavy Vivado at a time (CLAUDE.md, trap 4), and the memory a kernel
# synthesis wants.
if pgrep -f 'v\+\+ -l|vivado -mode batch' > /dev/null; then
  echo "refusing: another link or Vivado is running:" >&2
  pgrep -fa 'v\+\+ -l|vivado -mode batch' | head -3 | cut -c1-120 >&2
  exit 1
fi
avail=$(awk '/^MemAvailable:/ {print int($2 / 1048576)}' /proc/meminfo)
[ "${avail:-0}" -ge "$MIN_GB" ] || { echo "refusing: ${avail:-?} GB available, under MIN_GB=$MIN_GB" >&2; exit 1; }

# The vendor script reads unset variables, so -u is off around it, as
# every other hw script sources its setup (verifier-VC12).
# shellcheck disable=SC1090
set +u; source "$VIVADO_SETTINGS" >/dev/null 2>&1; set -u
command -v vivado >/dev/null || { echo "no vivado after $VIVADO_SETTINGS" >&2; exit 1; }
mkdir -p "$out"
out=$(cd "$out" && pwd)
echo "probe RT start $(date '+%F %T') top=$TOP generics='$GENERICS' freq=${FREQ}MHz part=$PART threads=$THREADS load $(cut -d' ' -f1-3 /proc/loadavg) ${avail} GB available"
echo "tree: $(git -C "$root" log --oneline -1 2>/dev/null | cut -c1-90); $(git -C "$root" status --porcelain 2>/dev/null | wc -l) files differ from it"
echo "tree's rtl: $(git -C "$root" rev-parse HEAD:rtl 2>/dev/null); probe reads $RTL"

worst=0
note() { [ "$1" -gt "$worst" ] && worst=$1; }

# run_one <name> <mode> <rtl_dir> <generics>
run_one() {
  local name=$1 m=$2 rtl=$3 gen=$4 t0 rc d
  d="$out/$name"
  rm -rf "$d"; mkdir -p "$d"
  t0=$(date +%s)
  ( cd "$d" && PROBE_RT_GENERICS="$gen" nice -n 10 timeout "$((TIMEOUT_MIN * 60))" \
      vivado -mode batch -nojournal -nolog -source "$here/probe_rt.tcl" \
      -tclargs "$m" "$FREQ" "$PART" "." "$rtl" "$TOP" "$CLOCK_PORT" "$THREADS" > run.log 2>&1 )
  rc=$?
  if [ -f "$d/netlist.v" ]; then
    grep -v '^//' "$d/netlist.v" | sha256sum | cut -d' ' -f1 > "$d/netlist.sha256"
    gzip -f "$d/netlist.v"
  fi
  # Vivado's own peak: the last "Synthesis current peak Physical Memory"
  # line, parent and children together.
  local pss
  pss=$(grep 'Synthesis current peak Physical Memory' "$d/run.log" | tail -1 | sed -n 's/.*peak = \([0-9.]*\).*/\1/p')
  echo "$(date +%T) $name (way $m) rc=$rc $(( ($(date +%s) - t0) / 60 )) min, peak ${pss:-?} MB, netlist $(cut -c1-16 "$d/netlist.sha256" 2>/dev/null || echo none)"
  if [ "$rc" = 124 ]; then note 4
  elif [ "$rc" != 0 ] || ! grep -q '^PROBE_RT_DONE' "$d/run.log"; then note 3
  fi
  grep -q '^PROBE_RT_CHECK: FAIL' "$d/run.log" && note 3
  grep -q '^PROBE_RT_ERR' "$d/run.log" && grep '^PROBE_RT_ERR' "$d/run.log" | head -3
  return 0
}

for m in $MODES; do
  run_one "$m" "$m" "$RTL" "$GENERICS"
done
# The control, only when it can decide something: a and b differ.
if [ -f "$out/a/netlist.sha256" ] && [ -f "$out/b/netlist.sha256" ] \
   && ! cmp -s "$out/a/netlist.sha256" "$out/b/netlist.sha256"; then
  echo "a and b differ: running a again (a2), to tell the flag from run-to-run noise"
  run_one a2 a "$RTL" "$GENERICS"
fi

if [ "$REPLAY" = 1 ]; then
  for sha in 2b57cf0ad3c1a69eb5f78d391878b8e8b296af21 a445268ee3d68779bf0d5776d74326a4489b2022; do
    if ! git -C "$root" cat-file -e "$sha^{commit}" 2>/dev/null; then
      echo "REPLAY: commit $sha is not in this clone's history; replay skipped by name"; continue
    fi
    td="$out/trees/$sha"
    rm -rf "$td"; mkdir -p "$td"
    git -C "$root" archive "$sha" rtl | tar -x -C "$td"
  done
  t02="$out/trees/2b57cf0ad3c1a69eb5f78d391878b8e8b296af21/rtl"
  t01="$out/trees/a445268ee3d68779bf0d5776d74326a4489b2022/rtl"
  if [ -d "$t02" ] && grep -q red_add_a_q "$t02/cft_engine_stream.sv"; then
    run_one x0902a a "$t02" ""
    run_one x0902b b "$t02" ""
  else
    echo "REPLAY: 2b57cf0's rtl missing or without 8f5f149's register; not run"; note 3
  fi
  if [ -d "$t01" ] && ! grep -q red_add_a_q "$t01/cft_engine_stream.sv"; then
    run_one x0901a a "$t01" ""
  else
    echo "REPLAY: a445268's rtl missing or already carrying 8f5f149's register; not run"; note 3
  fi
fi

python3 - "$out" "$LINK_LOG" > "$out/summary.txt" <<'PY'
import gzip
import re
import sys
from pathlib import Path

out, link_log = Path(sys.argv[1]), sys.argv[2]

def cell_usage(t):
    """synth_design's own "Report Cell Usage" table, which a link's run log
    and a standalone run's log both carry in one format."""
    m = re.search(r"Report Cell Usage:(.*?)\n-{20,}", t, re.S)
    if not m:
        return {}
    return dict((k, int(v)) for k, v in re.findall(r"\|\s*\d+\s*\|(\S+)\s*\|\s*(\d+)\|", m.group(1)))

def read(name):
    d = out / name
    f = d / "run.log"
    if not f.exists():
        return None
    t = f.read_text(errors="replace")
    r = {"name": name, "done": "PROBE_RT_DONE" in t}
    for key in ("PROBE_RT", "PROBE_RT_CLOCK_AT_SYNTH", "PROBE_RT_MSG", "PROBE_RT_RETIMED",
                "PROBE_RT_DSP", "PROBE_RT_DSP_0902", "PROBE_RT_WNS", "PROBE_RT_CHECK",
                "PROBE_RT_PRIM", "PROBE_RT_TOOL", "PROBE_RT_SYNTH"):
        m = re.search(r"^" + key + r": (.*)$", t, re.M)
        r[key] = m.group(1) if m else ""
    r["util"] = re.findall(r"^PROBE_RT_UTIL: (.*)$", t, re.M)
    r["errs"] = re.findall(r"^PROBE_RT_ERR: (.*)$", t, re.M)
    r["cells"] = cell_usage(t)
    # Vivado's "Retiming Report:" tables, summed: a partitioned synthesis
    # may print one a partition.
    rep = {}
    n = len(re.findall(r"^Retiming Report:", t, re.M))
    if n:
        rep["reports"] = n
        for k in ("Forward Retiming", "Backward Retiming", "New registers added", "Registers deleted"):
            rep[k] = sum(int(v) for v in re.findall(r"^\|" + k + r"\s*\|\s*(\d+)", t, re.M))
    r["report"] = rep
    h = d / "netlist.sha256"
    r["hash"] = h.read_text().strip() if h.exists() else ""
    return r

def kv(s):
    return dict(x.split("=", 1) for x in s.split() if "=" in x)

def util(r, name):
    for u in r["util"]:
        m = re.match(r"\|\s*" + re.escape(name) + r"\*?\s*\|\s*([0-9.]+)", u)
        if m:
            return m.group(1)
    return "-"

runs = {n: read(n) for n in ("a", "b", "c", "d", "a2", "x0902a", "x0902b", "x0901a")}
runs = {n: r for n, r in runs.items() if r is not None}
print("== probe RT")
for n, r in runs.items():
    print(f"-- {n}: {r['PROBE_RT'][:150]}")
    print(f"   {r['PROBE_RT_TOOL']}; clock at synthesis {r['PROBE_RT_CLOCK_AT_SYNTH'] or '?'}; finished {'yes' if r['done'] else 'NO'}")
    print(f"   messages:{r['PROBE_RT_MSG'] or ' ?'}; retimed registers {r['PROBE_RT_RETIMED'] or '?'}; "
          f"Retiming Report {r['report'] or 'none'}")
    print(f"   LUT {util(r, 'CLB LUTs')}  FF {util(r, 'CLB Registers')}  CARRY8 {util(r, 'CARRY8')}  "
          f"BRAM tiles {util(r, 'Block RAM Tile')}  URAM {util(r, 'URAM')}  DSP {util(r, 'DSPs')}")
    print(f"   DSP registers: {r['PROBE_RT_DSP'] or '?'}; counted as ooc_retime.tcl did: {r['PROBE_RT_DSP_0902'] or '?'}")
    print(f"   timing: {r['PROBE_RT_WNS'] or '?'}")
    if r["PROBE_RT_CHECK"]:
        print(f"   check: {r['PROBE_RT_CHECK']}")
    print(f"   netlist sha256 (comment lines removed): {r['hash'] or 'none'}")
    for e in r["errs"]:
        print(f"   ERR {e}")

def same(x, y):
    return x in runs and y in runs and runs[x]["hash"] and runs[x]["hash"] == runs[y]["hash"]

def known(x, y):
    return x in runs and y in runs and runs[x]["hash"] and runs[y]["hash"]

print()
print("== what it says")
if known("a", "b"):
    if same("a", "b"):
        n = kv(runs["b"]["PROBE_RT_MSG"]).get("Synth_8-11322", "?")
        print(f"a == b: -retiming without a clock changed NOTHING in this synthesis - the two netlists are byte")
        print(f"   for byte the same, and b's synthesis declined it {n} times (Synth 8-11322). It speaks for a")
        print(f"   link's kernel as far as b is the link's synthesis: see the LINK_LOG table, when given.")
    else:
        print("a != b: the flag changed the netlist without a clock.")
        if known("a", "a2"):
            print("   a2 == a: the difference is the flag's." if same("a", "a2")
                  else "   a2 != a: synthesis is not reproducible here; the fingerprint cannot decide.")
else:
    print("a and b: not both finished; nothing to compare.")
if known("c", "d"):
    rc, rd = runs["c"], runs["d"]
    wc, wd = kv(rc["PROBE_RT_WNS"]).get("wns", "?"), kv(rd["PROBE_RT_WNS"]).get("wns", "?")
    print(f"c vs d: {'IDENTICAL netlists - retiming found nothing to move at this clock' if same('c', 'd') else 'different netlists'};"
          f" c's Retiming Report {rc['report'] or 'absent'}, retimed registers {rc['PROBE_RT_RETIMED']};"
          f" WNS c {wc} against d {wd}.")
if known("a", "d"):
    wa = kv(runs["a"]["PROBE_RT_WNS"]).get("wns", "?")
    wd = kv(runs["d"]["PROBE_RT_WNS"]).get("wns", "?")
    print(f"d vs a: {'IDENTICAL - the clock alone changed nothing' if same('a', 'd') else 'different - the clock alone changes synthesis'};"
          f" WNS a {wa} (its clock applied after synthesis) against d {wd}.")
if known("x0902a", "x0902b"):
    print(f"replay of 2026-09-02 (2b57cf0's rtl): a {'==' if same('x0902a', 'x0902b') else '!='} b;"
          f" WNS a {kv(runs['x0902a']['PROBE_RT_WNS']).get('wns', '?')}, b {kv(runs['x0902b']['PROBE_RT_WNS']).get('wns', '?')};"
          f" LUT {util(runs['x0902a'], 'CLB LUTs')} / {util(runs['x0902b'], 'CLB LUTs')};"
          f" FF {util(runs['x0902a'], 'CLB Registers')} / {util(runs['x0902b'], 'CLB Registers')}.")
    print("   The entry's rows: baseline +0.307, 139,404 LUT, 55,362 FF, 292 DSP; -retiming +1.681, 139,545, 55,716, 277, PREG 188.")
if "x0901a" in runs:
    r = runs["x0901a"]
    print(f"replay of 2026-09-01's tree (a445268's rtl, way a): WNS {kv(r['PROBE_RT_WNS']).get('wns', '?')},"
          f" LUT {util(r, 'CLB LUTs')}, FF {util(r, 'CLB Registers')}, DSP {util(r, 'DSPs')}.")

if link_log and "b" in runs:
    p = Path(link_log)
    try:
        t = (gzip.open(p, "rt", errors="replace") if p.suffix == ".gz" else p.open(errors="replace")).read()
    except OSError as e:
        t = ""
        print(f"LINK_LOG {link_log}: {e}")
    cells, bcells = cell_usage(t), runs["b"]["cells"]
    if cells and bcells:
        print()
        print(f"== b against the link's kernel synthesis ({p.name}): synth_design's Report Cell Usage, both sides")
        diffs = 0
        for k in sorted(set(cells) | set(bcells)):
            lv, bv = cells.get(k), bcells.get(k)
            mark = "" if lv == bv else "   <- differs"
            diffs += bool(mark)
            print(f"   {k:16s} link {lv if lv is not None else '-':>8}  b {bv if bv is not None else '-':>8}{mark}")
        print(f"   {diffs} of {len(set(cells) | set(bcells))} rows differ")
    else:
        print(f"LINK_LOG {link_log}: no Report Cell Usage on one side; not compared")
PY
cat "$out/summary.txt"
echo "probe RT done $(date '+%F %T') exit $worst"
exit "$worst"
