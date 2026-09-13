#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Build and stage a bitstream PAIR - one tile, then four - the way every
# pair since 2026-09-02 has been built.
#
# WHY THIS IS A REPO FILE. The recipe kept being rebuilt from memory, and
# memory got it wrong in ways that exit 0. docs/BITSTREAM-BUILDS.md is the
# prose; this is the executable form, and it lives here because the last
# copy lived in a temp directory and a five-hour build was spent on the
# script default instead of the intended clock.
#
# THE RECIPE IS NOT THE DEFAULT. hw/rebuild-2022.sh defaults KERNEL_FREQ
# to 10000000 - a value from first bring-up, before any higher clock had
# been shown to work - and RETIMING and PHYS_OPT to 0. A run on those
# defaults meets timing trivially and belongs to no lineage. All three are
# set here, and a clock under MIN_FREQ is REFUSED rather than accepted
# quietly, because the tell for that mistake is an absurd WNS that nobody
# looks at until the hours are gone.
#
# WHAT IT WILL NOT DO. It will not stage an image that failed
# hw/verify-image.sh, it will not stage a copy whose hash does not match
# the manifest it was built with, and it will not spend hours on the quad
# if the single did not build or verify. A half-staged pair is worse than
# no pair: the staging directory is what a later session trusts.
#
# USAGE
#   hw/build-pair.sh --tag rev4 [options]
#
#   --tag NAME         names the staging dir (~/cardday-NAME) and the logs
#                      (~/r8-logs-NAME). Required.
#   --commit SHA       assert HEAD is exactly this before building. Use it
#                      whenever the pair is meant to be a named commit.
#   --require TOKEN    grep the RTL for TOKEN and refuse if absent. Repeat
#                      freely. This is the check `git rev-parse` cannot do:
#                      a clone reporting the right SHA whose working tree
#                      never updated. Both build hosts produced stale
#                      bundles in one day once.
#   --require-in F:TOK the same, in one named file.
#   --notes FILE       prose appended to the staged README, describing what
#                      this pair is. Without it the README carries only the
#                      measured facts.
#   --freq HZ          default 135000000. Under --min-freq is refused.
#   --min-freq HZ      default 100000000.
#   --single-only      build and stage the single, then stop.
#   --dry-run          run every assertion and print the plan, then stop
#                      WITHOUT building. This is how the checks above get
#                      tested: a guard nobody has seen refuse is a guard
#                      nobody knows works.
#   --repo DIR         default: the repo this script is in.
#
# Run it detached - `setsid nohup hw/build-pair.sh --tag x &` - because a
# pair is four to seven hours and an ssh session is not.
set -uo pipefail

TAG=""; COMMIT=""; NOTES=""; FREQ=135000000; MIN_FREQ=100000000
SINGLE_ONLY=0; DRY_RUN=0; REPO=""
REQUIRE=()
REQUIRE_IN=()

die () { echo "FATAL: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --tag)        TAG="${2:-}"; shift 2 ;;
    --commit)     COMMIT="${2:-}"; shift 2 ;;
    --require)    REQUIRE+=("${2:-}"); shift 2 ;;
    --require-in) REQUIRE_IN+=("${2:-}"); shift 2 ;;
    --notes)      NOTES="${2:-}"; shift 2 ;;
    --freq)       FREQ="${2:-}"; shift 2 ;;
    --min-freq)   MIN_FREQ="${2:-}"; shift 2 ;;
    --single-only) SINGLE_ONLY=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --repo)       REPO="${2:-}"; shift 2 ;;
    -h|--help)    sed -n '1,50p' "$0"; exit 0 ;;
    *)            die "unknown option $1" ;;
  esac
done

[ -n "$TAG" ] || die "--tag is required (it names the staging directory)"

# Default to the repo holding this script, so a clone anywhere works and
# nothing depends on $HOME being laid out a particular way.
if [ -z "$REPO" ]; then
  REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi
cd "$REPO" || die "cannot enter $REPO"
[ -f hw/rebuild-2022.sh ] || die "$REPO does not look like cft-fp256"

# The clock, before anything else: this is the mistake that costs the most
# and announces itself the least.
[ "$FREQ" -ge "$MIN_FREQ" ] 2>/dev/null || die \
  "--freq $FREQ is below --min-freq $MIN_FREQ. hw/rebuild-2022.sh defaults
  to 10 MHz and a run there meets timing trivially and cannot be staged.
  Pass --min-freq deliberately if a slow image is genuinely what you want."

HAVE=$(git rev-parse HEAD 2>/dev/null) || die "not a git repo: $REPO"
if [ -n "$COMMIT" ]; then
  [ "$HAVE" = "$COMMIT" ] || die "HEAD is $HAVE, wanted $COMMIT"
fi

# Content, not just the pointer.
for tok in ${REQUIRE+"${REQUIRE[@]}"}; do
  grep -rq -- "$tok" rtl/ 2>/dev/null || die "the RTL lacks '$tok'"
done
for spec in ${REQUIRE_IN+"${REQUIRE_IN[@]}"}; do
  f="${spec%%:*}"; tok="${spec#*:}"
  [ -f "$f" ] || die "--require-in names a file that is not there: $f"
  grep -q -- "$tok" "$f" || die "$f lacks '$tok'"
done
if [ ${#REQUIRE[@]} -gt 0 ] || [ ${#REQUIRE_IN[@]} -gt 0 ]; then
  echo "asserted: every --require token is present in the sources to be built"
fi

export KERNEL_FREQ="$FREQ"
export RETIMING=1
export PHYS_OPT=1

STAGE="$HOME/cardday-$TAG"
LOGDIR="$HOME/r8-logs-$TAG"

# Before the log directory is created, so --dry-run leaves the filesystem
# exactly as it found it. A check that litters is a check people stop
# running.
if [ "$DRY_RUN" -eq 1 ]; then
  echo "cft-fp256 $TAG pair from $HAVE"
  echo "host $(hostname), $(nproc) threads"
  echo "recipe: ${KERNEL_FREQ} Hz, retiming=$RETIMING, phys_opt=$PHYS_OPT, default directives"
  echo "--dry-run: every assertion passed; would now build, creating nothing"
  echo "  single -> build-$TAG-hw   (hw/link.cfg)"
  [ "$SINGLE_ONLY" -eq 1 ] || echo "  quad   -> build-$TAG-quad (hw/link_quad.cfg)"
  echo "  stage  -> $STAGE"
  echo "  logs   -> $LOGDIR"
  exit 0
fi

mkdir -p "$LOGDIR"
S="$LOGDIR/00-summary.txt"
{ echo "cft-fp256 $TAG pair from $HAVE"
  echo "host $(hostname), $(nproc) threads"
  echo "recipe: ${KERNEL_FREQ} Hz, retiming=$RETIMING, phys_opt=$PHYS_OPT, default directives"
  date -Is; } | tee "$S"

WNS_K=""; WNS_R=""

# -> 0 and sets WNS_K / WNS_R on success
build_half () {
  local name="$1" builddir="$2" linkcfg="$3"
  local log="$LOGDIR/$name.log" free_gb t0 t1 rc
  free_gb=$(free -g | awk '/^Mem:/ {print $7}')
  echo "--- $name: ${free_gb} GB available, $linkcfg" | tee -a "$S"
  # A quad place_design wants 25-30 GB. An OOM kill reads like a design
  # failure, which is a day lost to the wrong question.
  [ "$free_gb" -ge 20 ] || { echo "    SKIPPED: under 20 GB" | tee -a "$S"; return 1; }

  t0=$(date +%s)
  BUILD="$builddir" TARGETS="hw" LINK_CFG="$linkcfg" \
      bash hw/rebuild-2022.sh > "$log" 2>&1
  rc=$?
  t1=$(date +%s)
  echo "    rc=$rc in $(( (t1 - t0) / 60 )) min -> $log" | tee -a "$S"
  [ "$rc" -eq 0 ] || return 1

  # The clock and recipe that ACTUALLY applied, read back from the log and
  # the manifest rather than from the intent above.
  grep -m1 "Clock constraint argument" "$log" | sed 's/^/    /' | tee -a "$S"
  grep -hE "^(retiming|phys_opt|kernel_freq):" "$builddir"/*.manifest.txt \
      2>/dev/null | sed 's/^/    /' | tee -a "$S"
  WNS_K=$(grep -m1 "kernel_wns_ns:" "$builddir"/*.manifest.txt | awk '{print $2}')
  WNS_R=$(grep -m1 "routed_wns_ns:" "$builddir"/*.manifest.txt | awk '{print $2}')
  echo "    kernel_wns $WNS_K  routed_wns $WNS_R" | tee -a "$S"

  # Negative WNS is a finding, not a footnote. Determinism is
  # clock-independent, so a slower image that is RIGHT is a complete
  # answer - but it is a different pair and gets said out loud.
  case "$WNS_K" in
    -*) echo "    *** NEGATIVE kernel WNS - this image does not close at ${FREQ} Hz ***" | tee -a "$S" ;;
  esac

  # The static gate, before anything is staged or loaded.
  local vlog="$LOGDIR/$name.verify.log" vrc
  bash hw/verify-image.sh "$builddir/cft_hw.xclbin" > "$vlog" 2>&1
  vrc=$?
  grep -E "PASS|FAIL" "$vlog" | tail -n 2 | sed 's/^/    /' | tee -a "$S"
  [ "$vrc" -eq 0 ] || { echo "    verify-image FAILED - not staging" | tee -a "$S"; return 1; }
  return 0
}

stage_half () {
  local builddir="$1" dest="$2" before after
  mkdir -p "$STAGE"
  before=$(grep -m1 -iE "^sha256:" "$builddir"/*.manifest.txt | awk '{print $2}')
  cp "$builddir/cft_hw.xclbin" "$STAGE/$dest.xclbin"
  cp "$builddir"/*.manifest.txt "$STAGE/$dest.manifest.txt"
  after=$(sha256sum "$STAGE/$dest.xclbin" | awk '{print $1}')
  if [ -n "$before" ] && [ "$before" != "$after" ]; then
    echo "    *** COPY MISMATCH: manifest $before, copy $after ***" | tee -a "$S"
    return 1
  fi
  echo "    staged $dest.xclbin, re-hashed byte-identical ($after)" | tee -a "$S"
  return 0
}

SINGLE_OK=1; QUAD_OK=1; K_S=""; R_S=""; K_Q=""; R_Q=""
if build_half single "build-$TAG-hw" hw/link.cfg; then
  K_S=$WNS_K; R_S=$WNS_R
  stage_half "build-$TAG-hw" cft_hw_single || SINGLE_OK=0
else
  SINGLE_OK=0
fi

if [ "$SINGLE_ONLY" -eq 1 ]; then
  QUAD_OK=0
  echo "--single-only: stopping after the single" | tee -a "$S"
elif [ "$SINGLE_OK" -eq 1 ]; then
  if build_half quad "build-$TAG-quad" hw/link_quad.cfg; then
    K_Q=$WNS_K; R_Q=$WNS_R
    stage_half "build-$TAG-quad" cft_hw_quad || QUAD_OK=0
  else
    QUAD_OK=0
  fi
else
  echo "single did not build or verify; not spending hours on the quad" | tee -a "$S"
  QUAD_OK=0
fi

if [ "$SINGLE_OK" -eq 1 ] && [ "$QUAD_OK" -eq 1 ]; then
  ( cd "$STAGE" && sha256sum cft_hw_single.xclbin cft_hw_quad.xclbin \
      cft_hw_single.manifest.txt cft_hw_quad.manifest.txt > SHA256SUMS )
  { echo "cft-fp256 $TAG pair, both from $HAVE, built on $(hostname):"
    echo "  cft_hw_single.xclbin  one tile , ${FREQ} Hz, retiming+phys_opt, kernel WNS ${K_S:-?}, routed ${R_S:-?}"
    echo "  cft_hw_quad  .xclbin  four tiles, ${FREQ} Hz, retiming+phys_opt, kernel WNS ${K_Q:-?}, routed ${R_Q:-?}"
    echo "  SHA256SUMS            sha256sum -c SHA256SUMS before loading; the manifests carry commit, flags and hashes"
    [ -n "$NOTES" ] && [ -f "$NOTES" ] && { echo; cat "$NOTES"; }
  } > "$STAGE/README"
  echo "=== staged pair ===" | tee -a "$S"
  ls -l "$STAGE" | tee -a "$S"
  ( cd "$STAGE" && sha256sum -c SHA256SUMS ) | tee -a "$S"
elif [ "$SINGLE_OK" -eq 1 ] && [ "$SINGLE_ONLY" -eq 1 ]; then
  echo "=== single staged, quad not requested ===" | tee -a "$S"
  ls -l "$STAGE" | tee -a "$S"
else
  echo "=== NOT a pair: single_ok=$SINGLE_OK quad_ok=$QUAD_OK ===" | tee -a "$S"
  echo "nothing staged as a pair; see the logs above" | tee -a "$S"
fi

{ echo "=== done ==="; date -Is; } | tee -a "$S"
