#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Frequency sweep: build the single tile at one clock after another and
# say, for each, whether the KERNEL clock closed - judged from the
# artifacts, never from an exit code - and where its worst path runs.
#
#   bash hw/sweep_freq.sh --tag s1 --commit <sha> --dry-run 145 150 155
#   setsid nohup bash hw/sweep_freq.sh --tag s1 --commit <sha> --card \
#       145 150 155 160 > ~/sweep-s1.out 2>&1 < /dev/null &
#   bash hw/sweep_freq.sh --judge <build-dir> [--image <staged.xclbin>]
#
# Why a sweep and not a calculation: Vitis implementation is
# constraint-driven. It optimises until the clock you asked for is met
# and then stops, so a routed WNS tells you the design met its target,
# not how much faster it could have gone (docs/BRINGUP.md gate 3). The
# only way to find the ceiling is to ask for it and see.
#
# REWRITTEN 2026-09-23. The first version (27f94cf, 2026-08-29) predated
# the recipe, and a sweep run with it would have misreported:
#  - it called hw/rebuild-2022.sh directly, so RETIMING and PHYS_OPT took
#    that script's defaults of 0: a build of no lineage. Each point now
#    goes through `hw/build-pair.sh --single-only`, the recipe of every
#    pair since 2026-09-02, which also verifies and stages the image;
#  - it read the WHOLE-DESIGN WNS, which on this shell is a PCIe or HBM
#    number - the 130 and 145 MHz singles both read the shell's 0.055 ns
#    while their kernel margins differed. The kernel clock is read by name;
#  - it ran every point at once, ~12 GB each, where CLAUDE.md says one
#    heavy link at a time. Points now run in turn, each waiting for
#    memory, and the kernel log is read for OOM kills after each;
#  - it called every failed build "did not close".
#
# VERDICTS, from artifacts only - build-pair exits 0 whatever its builds
# did:
#   CLOSED   kernel WNS >= 0. A point counts only if build-pair also
#            staged the image, which means hw/verify-image.sh passed it.
#   MISSED   kernel WNS < 0, staged or not: build-pair stages a negative
#            image whenever v++ lets one through.
#   NONE     no kernel WNS on disk, or a manifest that no longer agrees
#            with the timing summary it names. No verdict: the sweep stops.
# The kernel WNS is the last timing summary the flow wrote - post-route
# phys_opt, else routed, else dr_timing_summary, the one a failed link
# may leave alone - and the manifest (the staged image's, else the
# build's) is held to the summary it says it was read from.
#
# THE SWEEP. Frequencies run in ascending order. A MISSED point gets one
# retry with PLACE_DIRECTIVE=ExtraTimingOpt ROUTE_DIRECTIVE=AggressiveExplore
# (--no-retry skips it). The sweep stops at the first frequency without a
# staged CLOSED image; --all carries on past misses, but nothing carries
# on past a point with no verdict. With --card each staged CLOSED image
# goes on the card - device-test's quick matrix, then the whole
# conformance replay - because an image that closed timing is not yet an
# image shown to compute right at that clock.
#
# OPTIONS
#   --tag PREFIX         points are tagged PREFIX-<MHz>, retries PREFIX-<MHz>x
#   --commit SHA         } handed to hw/build-pair.sh, which asserts them
#   --require TOKEN      }   before anything is built
#   --require-in F:TOK   }
#   --no-retry           no directive retry after a miss
#   --all                carry on past misses
#   --card               card-test each staged CLOSED image (XRT host, card present)
#   --out DIR            summary.txt and the logs; default ~/sweep-PREFIX
#   --dry-run            every assertion, build-pair --dry-run for each point;
#                        builds nothing and creates nothing
#   --judge DIR          judge the build directory DIR as it stands, and exit:
#                        one line, and exit 0 CLOSED, 1 MISSED, 2 NONE
#   --image XCLBIN       with --judge: the staged image, its manifest beside it
#
# The summary is the report. The sweep's exit code says only whether it
# could measure: 0 when every point built got a verdict, 2 when it stopped
# without one, 1 when it refused to start. hw/test-sweep-judge.sh holds
# the verdicts to synthetic builds, with the old version's two misreadings
# as negative controls.
#
# Environment: NEED_GB (default 24) GB of MemAvailable before each build -
# a U50 single's implementation peaked at ~15 GB on amd-arc-box, and
# build-pair itself refuses under 20; NEED_DISK_GB (15); KERNEL_CLK, as
# for hw/rebuild-2022.sh.
set -uo pipefail

TAG=""; RETRY=1; ALL=0; CARD=0; OUT=""; DRY_RUN=0; JUDGE=""; IMAGE=""
BP=()
FREQS=()
NEED_GB=${NEED_GB:-24}
NEED_DISK_GB=${NEED_DISK_GB:-15}
KCLK=${KERNEL_CLK:-clk_out1_ulp_clk_wiz_0}

die () { echo "FATAL: $*" >&2; exit 1; }
abspath () { [ -n "${1:-}" ] && readlink -f -- "$1"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)        TAG="${2:-}"; shift 2 ;;
    --commit)     BP+=(--commit "${2:-}"); shift 2 ;;
    --require)    BP+=(--require "${2:-}"); shift 2 ;;
    --require-in) BP+=(--require-in "${2:-}"); shift 2 ;;
    --no-retry)   RETRY=0; shift ;;
    --all)        ALL=1; shift ;;
    --card)       CARD=1; shift ;;
    --out)        OUT=$(abspath "${2:-}") || die "--out: cannot resolve '${2:-}'"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --judge)      JUDGE=$(abspath "${2:-}") || die "--judge: no such directory '${2:-}'"; shift 2 ;;
    --image)      IMAGE=$(abspath "${2:-}") || die "--image: no such file '${2:-}'"; shift 2 ;;
    -h|--help)    sed -n '5,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    -*)           die "unknown option $1" ;;
    *)            [[ "$1" =~ ^[0-9]+$ ]] || die "not a frequency in MHz: $1"
                  FREQS+=("$1"); shift ;;
  esac
done

# ---- the judge -----------------------------------------------------------
num () { [[ "${1:-}" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; }

# The kernel clock's WNS from a timing summary's Intra Clock Table, by the
# clock's NAME. Never the Design Timing Summary above it: on this shell
# that is a PCIe or HBM path's number.
kwns_of () {
  awk -v c="$KCLK" '/Intra Clock Table/ {f = 1} f && /Inter Clock Table/ {exit} f && $1 == c {print $2; exit}' "$1" 2> /dev/null  # JUDGE-READS-KERNEL-CLOCK
}

rname () {
  case "$1" in
    *postroute_physopted*)    echo "post-route" ;;
    *timing_summary_routed*)  echo "routed" ;;
    *dr_timing_summary*)      echo "dr" ;;
    *)                        basename "$1" ;;
  esac
}

# judge <build-dir> [staged xclbin]  ->  J_VERDICT J_KWNS J_WHY J_IMAGE J_RPT
judge () {
  local b=$1 x=${2:-} i r m mv="" mr="" ms="" v fv=""
  J_VERDICT=NONE; J_KWNS=""; J_WHY=""; J_IMAGE=""; J_RPT=""
  [ -n "$x" ] && [ -f "$x" ] && J_IMAGE=$x
  i="$b/_x_hw/link/vivado/vpl/prj/prj.runs/impl_1"

  # The last timing summary the flow wrote is the image's timing.
  for r in hw_bb_locked_timing_summary_postroute_physopted.rpt \
           hw_bb_locked_timing_summary_routed.rpt dr_timing_summary.rpt; do
    [ -f "$i/$r" ] && { J_RPT="$i/$r"; break; }
  done
  if [ -n "$J_RPT" ]; then fv=$(kwns_of "$J_RPT"); num "$fv" || fv=""; fi

  # The manifest, and the summary it says it read - hw/rebuild-2022.sh
  # records that as timing_report, and before it did, read routed first.
  if [ -n "$J_IMAGE" ]; then m="${J_IMAGE%.xclbin}.manifest.txt"
  else m=$(ls "$b"/*.manifest.txt 2> /dev/null | head -1); fi
  if [ -n "$m" ] && [ -f "$m" ]; then
    mv=$(awk '$1 == "kernel_wns_ns:" {print $2; exit}' "$m"); num "$mv" || mv=""
    mr=$(awk '$1 == "timing_report:" {print $2; exit}' "$m")
    if [ -n "$mr" ]; then ms="$i/$mr"
    elif [ -f "$i/hw_bb_locked_timing_summary_routed.rpt" ]; then ms="$i/hw_bb_locked_timing_summary_routed.rpt"
    else ms="$i/dr_timing_summary.rpt"; fi
  fi
  if [ -n "$mv" ] && [ -f "$ms" ]; then
    v=$(kwns_of "$ms")
    if [ "$v" != "$mv" ]; then
      J_WHY="the manifest says $mv from the $(rname "$ms") summary, which reads ${v:-no $KCLK}"
      return
    fi
  fi

  if [ -n "$fv" ]; then
    J_KWNS=$fv; J_WHY="$(rname "$J_RPT") timing summary"
    if [ -n "$mv" ] && [ "$mv" != "$fv" ]; then
      J_WHY="$J_WHY; post-route phys_opt moved it from the manifest's $mv ($(rname "$ms"))"
    elif [ -n "$mv" ]; then
      J_WHY="$J_WHY, the manifest agrees"
    fi
  elif [ -n "$mv" ]; then
    J_KWNS=$mv; J_WHY="the manifest; no timing summary on disk"
  else
    J_WHY="no $KCLK WNS in a manifest or a timing summary"
    return
  fi
  case "$J_KWNS" in -*) J_VERDICT=MISSED ;; *) J_VERDICT=CLOSED ;; esac   # JUDGE-SIGN-ONLY
}

judge_line () {
  printf '%s, kernel WNS %s ns (%s: %s), image %s' "$J_VERDICT" "${J_KWNS:-none}" \
    "$KCLK" "$J_WHY" "${J_IMAGE:-not staged}"
}

if [ -n "$JUDGE" ]; then
  [ -d "$JUDGE" ] || die "--judge: not a directory: $JUDGE"
  [ -z "$IMAGE" ] || [ -f "$IMAGE" ] || die "--image: no such file: $IMAGE"
  judge "$JUDGE" "$IMAGE"
  echo "$(basename "$JUDGE"): $(judge_line)"
  case "$J_VERDICT" in CLOSED) exit 0 ;; MISSED) exit 1 ;; *) exit 2 ;; esac
fi

# ---- the sweep: refusals before anything is built -----------------------
cd "$(dirname "$0")/.." || die "cannot find the repo"
REPO=$(pwd)
[ -f hw/build-pair.sh ] || die "$REPO does not look like cft-fp256"
[ -n "$TAG" ] || die "--tag is required"
[ ${#FREQS[@]} -gt 0 ] || die "no frequencies given"
[ -z "$IMAGE" ] || die "--image belongs with --judge"
mapfile -t FREQS < <(printf '%s\n' "${FREQS[@]}" | sort -n -u)
OUT=${OUT:-$HOME/sweep-$TAG}
SUM=$OUT/summary.txt

avail_gb () { awk '/MemAvailable/ {print int($2 / 1048576)}' /proc/meminfo; }
disk_gb () { df -BG --output=avail "$HOME" | tail -1 | tr -dc 0-9; }

# Nothing a verdict could be read off may predate the point that reads it.
for f in "${FREQS[@]}"; do
  for t in "$TAG-$f" "$TAG-${f}x" "$TAG-${f}r" "$TAG-${f}xr"; do
    for d in "$HOME/cardday-$t" "$HOME/r8-logs-$t" "$REPO/build-$t-hw"; do
      [ -e "$d" ] && die "$d already exists - a verdict could be read off a stale artifact; choose another --tag"
    done
  done
done

# build-pair's own assertions, for every point, without building: a
# refusal must read as a refusal, not as "did not close".
for f in "${FREQS[@]}"; do
  o=$(bash hw/build-pair.sh --tag "$TAG-$f" ${BP[@]+"${BP[@]}"} --freq "${f}000000" --single-only --dry-run 2>&1) \
    || die "build-pair refused the $f MHz point:
$(echo "$o" | tail -5 | sed 's/^/    /')"
done

# XRT's environment only around the card. hw/rebuild-2022.sh sources
# Vitis 2022.2 and nothing of XRT, so every earlier build ran without it,
# and the builds here run the same way.
XRT_SETUP=""; XRT_ROOT=""
if [ "$CARD" -eq 1 ]; then
  for r in /opt/xilinx/xrt /usr/local/xrt; do
    [ -f "$r/setup.sh" ] && { XRT_SETUP=$r/setup.sh; XRT_ROOT=$r; break; }
  done
  [ -n "$XRT_SETUP" ] || die "--card: no XRT here (no setup.sh in /opt/xilinx/xrt or /usr/local/xrt)"
fi
xrt () { ( set +u; source "$XRT_SETUP" > /dev/null 2>&1; set -u; "$@" ); }

if [ "$DRY_RUN" -eq 1 ]; then
  echo "sweep $TAG --dry-run: every assertion passed; would build, creating nothing"
  echo "  repo    $REPO at $(git rev-parse --short HEAD 2> /dev/null), rtl $(git rev-parse HEAD:rtl 2> /dev/null | cut -c1-8)"
  echo "  points  ${FREQS[*]} MHz, ascending; retry=$RETRY all=$ALL card=$CARD"
  echo "  tags    $TAG-<MHz>, a retry $TAG-<MHz>x; summary -> $SUM"
  echo "  memory  $(avail_gb) GB available now; each build waits for $NEED_GB"
  if [ "$CARD" -eq 1 ]; then
    card=$(xrt xbutil examine 2>&1 | grep -m1 -E '\[[0-9a-f]{4}:[0-9a-f:.]+\]' | tr -s ' |' ' ')
    echo "  card    ${card:-NONE listed by xbutil examine - a real run would refuse}"
  fi
  exit 0
fi

mkdir -p "$OUT" || die "cannot create $OUT"
say () { echo "$(date -Is) $*" | tee -a "$SUM"; }
fail () { say "FATAL $*"; exit 1; }
say "---- sweep $TAG: ${FREQS[*]} MHz; $REPO at $(git rev-parse HEAD) (rtl $(git rev-parse HEAD:rtl)); host $(hostname), $(nproc) threads; retry=$RETRY all=$ALL card=$CARD"
journalctl -k -n 1 --no-pager > /dev/null 2>&1 && OOMLOG=1 || OOMLOG=0
[ "$OOMLOG" -eq 1 ] || say "the kernel log is not readable here: an OOM kill would read as a build failure"

# Memory beside the builds, a line a minute.
( while kill -0 $$ 2> /dev/null; do
    echo "$(date -Is) avail=$(avail_gb)G disk=$(disk_gb)G top: $(ps -eo rss,comm --sort=-rss \
      | awk 'NR > 1 && NR <= 6 {printf "%s:%.1f ", $2, $1 / 1048576}')" >> "$OUT/mem.log"
    sleep 60
  done ) &

if [ "$CARD" -eq 1 ]; then
  # The tests named on the make line: `all` does not build them, and they
  # link libcft.a statically (CLAUDE.md).
  make -C host XRT=1 XRT_ROOT="$XRT_ROOT" all device-test > "$OUT/host-build.log" 2>&1 \
    || fail "--card: the host build failed, see $OUT/host-build.log"
  for b in device-test cft-selftest; do
    xrt ldd "host/$b" | grep -q "libxrt_coreutil[^ ]* => /" \
      || fail "--card: host/$b does not resolve libxrt_coreutil under $XRT_SETUP"
  done
  say "card tools, XRT-linked: device-test $(date -r host/device-test -Is), cft-selftest $(date -r host/cft-selftest -Is); $(grep -c 'warning:' "$OUT/host-build.log") warning(s)"
  if [ ! -d vectors/out ] || [ -z "$(ls vectors/out 2> /dev/null)" ]; then
    make vectors > "$OUT/vectors.log" 2>&1 || fail "--card: make vectors failed, see $OUT/vectors.log"
  fi
  say "vectors: $(ls vectors/out | wc -l) sets"
  xrt xbutil examine > "$OUT/xbutil-examine.txt" 2>&1
  card=$(grep -m1 -E '\[[0-9a-f]{4}:[0-9a-f:.]+\]' "$OUT/xbutil-examine.txt" | tr -s ' |' ' ')
  [ -n "$card" ] || fail "--card: xbutil examine lists no device, see $OUT/xbutil-examine.txt"
  say "card:$card"
fi

# ---- one point ------------------------------------------------------------
wait_mem () {
  local n=0
  while [ "$(avail_gb)" -lt "$NEED_GB" ]; do
    [ "$n" -eq 0 ] && say "  waiting for $NEED_GB GB available (now $(avail_gb))"
    n=$((n + 1))
    [ "$n" -le 144 ] || { say "  gave up after 12 h waiting for memory"; return 1; }
    sleep 300
  done
  [ "$n" -eq 0 ] || say "  $(avail_gb) GB available after $((n * 5)) min"
}

build_point () {  # <tag> <MHz>  ->  P and J_*
  local tag=$1 f=$2 t0 bp="$OUT/$1.build-pair.out" x oom
  P=NONE; J_KWNS=""; J_IMAGE=""; J_RPT=""
  if [ "$(disk_gb)" -lt "$NEED_DISK_GB" ]; then
    say "  $tag: $(disk_gb) GB of disk left, under $NEED_DISK_GB"; P=NODISK; return
  fi
  wait_mem || { P=NOMEM; return; }
  t0=$(date '+%Y-%m-%d %H:%M:%S')
  say "  $tag: building at $f MHz with $(avail_gb) GB available, place=${PLACE_DIRECTIVE:-default} route=${ROUTE_DIRECTIVE:-default}"
  bash hw/build-pair.sh --tag "$tag" ${BP[@]+"${BP[@]}"} --freq "${f}000000" --single-only > "$bp" 2>&1
  grep -E "rc=|Clock constraint|kernel_wns|NEGATIVE|SKIPPED|verify-image|PASS|FAIL|staged" "$bp" \
    | sed 's/^/    /' | tee -a "$SUM"
  if [ "$OOMLOG" -eq 1 ]; then
    oom=$(journalctl -k --since "$t0" --no-pager 2> /dev/null | grep -i -E "out of memory|oom-kill|killed process" | tail -3)
    if [ -n "$oom" ]; then
      say "  $tag: the kernel log records OOM activity since $t0:"; echo "$oom" | sed 's/^/    /' | tee -a "$SUM"
    fi
  fi
  if grep -q "SKIPPED: under" "$bp"; then P=SKIPPED; say "  $tag: build-pair's memory guard refused to start"; return; fi
  x="$HOME/cardday-$tag/cft_hw_single.xclbin"
  [ -f "$x" ] || x=""
  judge "$REPO/build-$tag-hw" "$x"
  P=$J_VERDICT
  if [ -n "$J_RPT" ]; then
    gzip -c "$J_RPT" > "$OUT/$tag.timing_summary.rpt.gz"
    if command -v python3 > /dev/null; then
      python3 hw/kernel_worst.py "$J_RPT" > "$OUT/$tag.worst.txt" 2>&1
      sed '1d' "$OUT/$tag.worst.txt" | head -16 | sed 's/^/  /' | tee -a "$SUM"
    fi
  fi
  say "  $tag: $(judge_line)"
}

card_test () {  # <xclbin> <tag>
  local x=$1 t=$2 rc
  bash hw/run-device-test.sh "$x" -q -n 8 > "$OUT/$t.device-test.log" 2>&1; rc=$?
  say "  $t device-test -q -n 8: rc=$rc, $(grep -E '^[0-9]+ checks, [0-9]+ failed' "$OUT/$t.device-test.log" | tail -1)"
  xrt timeout 3600 host/cft-selftest vectors/out "$x" > "$OUT/$t.selftest.log" 2>&1; rc=$?
  say "  $t conformance replay: rc=$rc, backend $(awk '$1 == "backend" {print $2; exit}' "$OUT/$t.selftest.log"), $(grep -E 'cases checked|CONFORMANCE FAILED|cft_open' "$OUT/$t.selftest.log" | tr '\n' ' ')"
}

# ---- the sweep ------------------------------------------------------------
RESULTS=(); NOVERDICT=0
for f in "${FREQS[@]}"; do
  staged=""; verdicts=""; tag=""
  for mode in std x; do
    [ "$mode" = x ] && [ "$RETRY" -eq 0 ] && break
    if [ "$mode" = x ]; then
      export PLACE_DIRECTIVE=ExtraTimingOpt ROUTE_DIRECTIVE=AggressiveExplore
    else
      unset PLACE_DIRECTIVE ROUTE_DIRECTIVE
    fi
    tag="$TAG-$f"; [ "$mode" = x ] && tag="${tag}x"
    say "== $f MHz, $([ "$mode" = x ] && echo 'ExtraTimingOpt/AggressiveExplore' || echo 'the standard recipe'), tag $tag"
    build_point "$tag" "$f"
    if [ "$P" = SKIPPED ]; then tag="${tag}r"; build_point "$tag" "$f"; fi
    verdicts="$verdicts $mode:$P(${J_KWNS:-none})"
    RESULTS+=("$(printf '%4s MHz  %-9s %-6s kernel WNS %-7s %s' "$f" "$mode" "$P" "${J_KWNS:-none}" "${J_IMAGE:-}")")
    if [ "$P" = CLOSED ] && [ -n "$J_IMAGE" ]; then staged=$J_IMAGE; break; fi
    [ "$P" = MISSED ] || break      # only a kernel-timing miss earns the second recipe
  done
  unset PLACE_DIRECTIVE ROUTE_DIRECTIVE
  if [ -n "$staged" ]; then
    say "  CLOSED at $f MHz: $staged ($(sha256sum "$staged" | cut -c1-16))"
    [ "$CARD" -eq 1 ] && card_test "$staged" "$tag"
    continue
  fi
  case "$verdicts" in
    *NONE*|*SKIPPED*|*NOMEM*|*NODISK*)
      say "STOP at $f MHz with no verdict:$verdicts - see $OUT/$tag.build-pair.out"; NOVERDICT=1; break ;;
    *CLOSED*)
      say "STOP at $f MHz: the kernel met timing but no image was staged:$verdicts - see $OUT/$tag.build-pair.out"; NOVERDICT=1; break ;;
  esac
  say "  $f MHz MISSED:$verdicts"
  [ "$ALL" -eq 1 ] || { say "STOP: $f MHz is the first frequency without a staged CLOSED image"; break; }
done

say "sweep $TAG finished:"
printf '%s\n' "${RESULTS[@]}" | sed 's/^/    /' | tee -a "$SUM"
exit $((NOVERDICT * 2))
