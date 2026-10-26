#!/bin/bash
# box_hx_probe.sh - parcel HX's card probe (docs/studies/HX-wide-sweeps.md, section 4), for the LEAD to run on
# amd-arc-box; agents never touch the box or the card. About 100 seconds of card time on one quad image.
# What it measures: the card's rate for cft_div, cft_sqrt, cft_rint, cft_scaleb and cft_run's FMA, MUL and ADD at
# fp64, fp128 and fp256, one call of N = 4096 elements at a time (the soaks' BATCH), each call checked against the
# software backend (bytes and flags) before it is timed; first on tile 1 alone, then on the quad's four tiles at
# once (one process a tile, as the sweep runs them); then the soak tool's own rate for random div64 and sqrt64 on
# tile 1, so that the probe's fp64 rows can be held to the sweep's rates (status.txt's div64-hard@quad etc.).
#   1. refuses if its summary exists, if the box clock is past 17:40, if any card, runner or scheduler process is
#      alive, if the probe source's sha256 is not the one given, or if the quad image's sha256 is not the driver's;
#   2. a fresh clone of the bundle at the given pushed commit, the SHA and the content asserted apart (HEAD, a clean
#      status, the rtl tree the images were built from, the hard-case modes in the soak's source);
#   3. make -C host XRT=1 libcft.a divsqrt-soak, the probe compiled against that libcft.a; ldd must show xrt in both;
#   4. the three phases under `timeout`, then sha256sum of every output.
# Expected: 3 to 5 minutes in all (the build most of it), well under 1 GB of memory, nothing written outside
# /data/m1e1/hx-probe* and /data/hx-probe-src. Its own command line matches none of the nightly launcher's guard
# patterns, and it ends long before 18:00.
# usage: bash box_hx_probe.sh <full sha> <bundle under /data/m1e1/bundles> <path of hx_probe.c> <its sha256>
set -u
SHA=${1:?full sha}; BUNDLE=${2:?bundle file name under /data/m1e1/bundles}; PROBE=${3:?hx_probe.c}; PSHA=${4:?its sha256}
W=/data/m1e1; SRC=/data/hx-probe-src; L=$W/hx-probe; S=$W/hx-probe-summary.txt; SUMS=$W/hx-probe-SHA256SUMS
IMG=$HOME/cardday-rev8q/cft_hw_quad.xclbin; IMGSHA=4f9921a25af65444abc5c267fff1117a8e14abbc16a75de643e43c9dbf6ef53b
RTL=44b963dd6ba2fcf99e002c5face5ca94aad4515c
say() { echo "$(date '+%F %T') hx-probe: $*" >> $S; }
done_() { echo "=== done" >> $S; exit ${1:-1}; }
[ -e $S ] && { echo "REFUSED, $S exists" >> $W/hx-probe-refused.txt; exit 1; }
for p in $SRC $L $SUMS; do [ -e $p ] && { say "REFUSED, $p exists"; done_ 1; }; done
[ "$(date +%H%M)" -lt 1740 ] || { say "REFUSED, past 17:40: the night starts at 18:00"; done_ 1; }
n=$(pgrep -fc 'card_stress.py|card-stress.sh|divsqrt-soak|clause5-soak|chunk_card.py|verify/run.sh|cft_sched.py' 2>/dev/null)
[ "${n:-0}" = 0 ] || { say "REFUSED, $n card, runner or scheduler process(es) alive"; done_ 1; }
[ "$(sha256sum < $PROBE | cut -d' ' -f1)" = "$PSHA" ] || { say "REFUSED, $PROBE is not sha256 $PSHA"; done_ 1; }
[ "$(sha256sum < $IMG | cut -d' ' -f1)" = "$IMGSHA" ] || { say "REFUSED, $IMG is not the quad image $IMGSHA"; done_ 1; }
mkdir $L
say "start; load $(cut -d' ' -f1-3 /proc/loadavg); sha $SHA, bundle $BUNDLE, probe $PSHA, image $IMGSHA"
git clone -q $W/bundles/$BUNDLE $SRC -b main 2>> $S || { say "clone failed"; done_ 1; }
git -C $SRC checkout -q --detach $SHA 2>> $S || { say "checkout failed"; done_ 1; }
h=$(git -C $SRC rev-parse HEAD); d=$(git -C $SRC status --porcelain | wc -l); r=$(git -C $SRC rev-parse HEAD:rtl)
n1=$(grep -c 'sqrt64-hard' $SRC/host/tools/divsqrt_soak.c)
say "HEAD $h status $d rtl $r sqrt64-hard-in-soak x$n1"
if [ "$h" = "$SHA" ] && [ "$d" = 0 ] && [ "$r" = "$RTL" ] && [ "$n1" -ge 1 ]; then :; else say "ASSERTION FAILED"; done_ 1; fi
for x in /opt/xilinx/xrt /usr/local/xrt; do [ -f $x/setup.sh ] && { set +u; source $x/setup.sh > /dev/null 2>&1; set -u; XR=$x; break; }; done
[ -n "${XR:-}" ] || { say "no XRT setup.sh"; done_ 1; }
t0=$(date +%s); nice -n 10 make -C $SRC/host XRT=1 XRT_ROOT=$XR libcft.a divsqrt-soak > $L/build.log 2>&1; rc=$?
gcc -std=c99 -O2 -Wall -Wextra -I$SRC/host/include $PROBE $SRC/host/libcft.a -o $L/hx-probe \
  -L$XR/lib -lxrt_coreutil -lstdc++ -lpthread -luuid -lm >> $L/build.log 2>&1; rc2=$?
x1=$(ldd $L/hx-probe | grep -c xrt); x2=$(ldd $SRC/host/divsqrt-soak | grep -c xrt)
say "build rc=$rc probe rc=$rc2, $(( $(date +%s) - t0 )) s; ldd xrt lines: probe $x1, soak $x2"
[ $rc = 0 ] && [ $rc2 = 0 ] && [ "$x1" -ge 1 ] && [ "$x2" -ge 1 ] || done_ 1
t0=$(date +%s); CFT_XRT_TILES=1 timeout 300 $L/hx-probe $IMG 2 > $L/probe-tile1.txt 2>&1; rc=$?
say "phase A (tile 1 alone) rc=$rc, $(( $(date +%s) - t0 )) s: $(tail -1 $L/probe-tile1.txt)"
t0=$(date +%s)
for t in 1 2 3 4; do CFT_XRT_TILES=$t timeout 300 $L/hx-probe $IMG 2 > $L/probe-quad-t$t.txt 2>&1 & done
wait
say "phase B (four tiles at once), $(( $(date +%s) - t0 )) s: $(for t in 1 2 3 4; do tail -1 $L/probe-quad-t$t.txt; done | tr '\n' '|')"
for job in "div64 4194304 1353449473" "sqrt64 4194304 1353449481"; do
  set -- $job
  t0=$(date +%s.%N)
  CFT_SOAK_ARTIFACT=$IMG CFT_XRT_TILES=1 timeout 120 $SRC/host/divsqrt-soak $1 $2 $3 rne > $L/soak-$1.txt 2>&1; rc=$?
  t1=$(date +%s.%N)
  say "phase C soak $1 $2 rne rc=$rc, $(awk "BEGIN { printf \"%.2f\", $t1 - $t0 }") s: $(grep -E '^'$1' rne: ' $L/soak-$1.txt)"
done
sha256sum $PROBE $L/* > $SUMS 2>> $S
say "sums of $(wc -l < $SUMS) files in $SUMS"
done_ 0
