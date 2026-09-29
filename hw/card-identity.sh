#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The card leg of identity in libcft: the library build and the device
# image, measured where only a card can measure them (docs/HOSTAPI.md,
# "Identity at ABI 0.15"; docs/CARDDAY.md, "Owed to the next card day
# (added 2026-09-28)").
#
#   bash hw/card-identity.sh <image.xclbin> [<another image.xclbin>]
#
# From the root of a checkout of the branch under test, on the box that
# has the card, after
#
#   make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test
#
# (device-test is not in `all`, and links libcft.a statically: CLAUDE.md).
# A second image is optional and worth passing: it is what shows the
# digest follows the image loaded.
#
# What it holds, in order, each an "ok" or a "FAIL" line:
#   1. the build: device-test links XRT; the build id device-test carries
#      is the tree's (make print-build-id); and that id names HEAD. On a
#      CLEAN tree equal ids mean the binary is not stale. On a dirty one
#      they cannot: two different edits of one commit carry one id, so a
#      binary built from the first edit matches a tree at the second
#      (verifier-C3). A dirty tree is therefore said on NOTE lines, not
#      refused and not passed as "not stale": the leg still measures the
#      mechanism, and the run is not reproducible from the commit.
#   2. per image: `device-test <image> -i` exits 0 (device-test's own
#      checks: the digest against its own SHA-256 of the file, the bytes,
#      VERSION, and the raw CAPS words decoding to the handle's caps; and
#      on an image with two tiles or more, the two refusals planted
#      through CFT_XRT_CAPS, each by its own sentence, which this script
#      counts - NOT TESTED, by name, on a single tile; five malformed
#      CFT_XRT_CAPS values refused by name at open; and each planted
#      handle decoding exactly as the unplanted one, both of which this
#      script requires to be SHOWN, not only to have passed); the digest
#      it prints equals `sha256sum` of the file - an implementation that
#      is not libcft's - and the bytes `stat`; and, where rebuild-2022.sh
#      left a manifest beside it, the manifest's sha256 line too.
#   3. the negative controls, a to c each required to FAIL by name:
#      a. device-test's digest check, planted: CFT_DEVICE_TEST_HASH_FILE
#         makes it hash host/device-test in place of the image;
#      b. this script's comparison, fed the digest of another file, and
#         fed two empty strings;
#      c. an identity refusal nobody asked for: CFT_XRT_CAPS=
#         plant-unreadable set from OUTSIDE device-test imitates a CAPS
#         read that failed at open, and its identity leg must fail it
#         (on the first image with two tiles or more);
#      and d, which must PASS by name: the same kind of refusal told to
#      expect - CFT_XRT_CAPS=plant-differ from outside, with
#      --expect-refusal mixed, as a genuinely mixed layout is run.
#   4. with two images: two different digests, each its own file's.
#   5. the open the digest changed still runs the matrix:
#      `device-test <image> -q -n 8` exits 0.
#   6. the remote refusal with a CARD behind the server: cft-serve
#      --artifact <image> on loopback, `device-test cft://... -i` must
#      see the remote handle refuse by name even though the server holds
#      an image. The server is stopped by PID.
#
# It loads each image it is given; a load of the image already loaded is
# a no-op (docs/CARDDAY.md). Steps 1 to 4 and 6 open images and read
# registers and start no run on a tile. Step 5 is the quick matrix, 2,456
# checks on the quad image (the card, 2026-09-28), and a run there can time
# out like any other: if a step reports a timeout, reload the image -
# load another xclbin, then this one - before trusting anything after it.
#
# Exit 0 when every check held, 1 otherwise. The log is stdout; keep it
# beside the card day's record.
set -uo pipefail

usage() { echo "usage: bash hw/card-identity.sh <image.xclbin> [<another image.xclbin>]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DT="$ROOT/host/device-test"
SERVE="$ROOT/host/cft-serve"
LOGDIR=$(mktemp -d "${TMPDIR:-/tmp}/card-identity.XXXXXX")
trap 'rm -rf "$LOGDIR"' EXIT

checks=0
failed=0
ok()  { checks=$((checks + 1)); echo "  ok    $*"; }
bad() { checks=$((checks + 1)); failed=$((failed + 1)); echo "  FAIL  $*"; }

# Two digests are the same digest only if both ARE digests.
same_digest() {
    [[ $1 =~ ^[0-9a-f]{64}$ ]] && [[ $2 =~ ^[0-9a-f]{64}$ ]] && [ "$1" = "$2" ]
}

for r in /opt/xilinx/xrt /usr/local/xrt; do
    [ -f "$r/setup.sh" ] && { set +u; source "$r/setup.sh" >/dev/null; set -u; break; }
done

imgs=()
for a in "$@"; do
    [ -f "$a" ] || { echo "no such image: $a" >&2; exit 2; }
    imgs+=("$(readlink -f "$a")")
done

echo "== card-identity: $(date -Iseconds) on $(hostname)"
echo "   tree $ROOT at $(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo '(no git)')"

# ---- 1. the build ----------------------------------------------------
echo "== 1. the build"
[ -x "$DT" ] || { echo "not built: $DT - make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test" >&2; exit 2; }
echo "   device-test built $(stat -c %y "$DT")"
if ldd "$DT" 2>/dev/null | grep -q xrt_coreutil; then
    ok "device-test links XRT ($(ldd "$DT" | grep -o 'libxrt_coreutil[^ ]*' | head -1))"
else
    bad "device-test does not link XRT - built without XRT=1, it answers every xclbin with 'no such device' (CLAUDE.md)"
fi
tree_id=$(make -s -C "$ROOT/host" print-build-id 2>/dev/null)
bin_id=$("$DT" --build-id 2>/dev/null)
echo "   the tree's build id:        $tree_id"
echo "   device-test's build id:     $bin_id"
if [ -z "$bin_id" ] || [ "$bin_id" != "$tree_id" ]; then
    bad "device-test carries '$bin_id' and the tree is '$tree_id' - relink it: make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt device-test"
else
    case $tree_id in
        *" tracked=clean untracked=none")
            ok "device-test carries the tree's build id, and the tree is clean: it is not stale" ;;
        *)
            echo "   NOTE: device-test carries the tree's build id, but the tree is not clean ($tree_id), so equal ids do not show it is current: two edits of one commit carry one id"
            echo "   NOTE: rebuild it from this tree state to be sure - make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all device-test" ;;
    esac
fi
head=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)
case $tree_id in
    "commit=$head tracked=clean untracked=none")
        ok "the build id names HEAD, clean" ;;
    "commit=$head "*)
        ok "the build id names HEAD"
        echo "   NOTE: the tree is not clean ($tree_id) - this run is not reproducible from $head" ;;
    *)
        bad "the build id '$tree_id' does not name HEAD ($head)" ;;
esac

# ---- 2. each image ---------------------------------------------------
declare -A digest_of
declare -A tiles_of
n=0
for img in "${imgs[@]}"; do
    n=$((n + 1))
    echo "== 2.$n $img"
    want=$(sha256sum "$img" | cut -c 1-64)
    bytes=$(stat -c %s "$img")
    echo "   sha256sum: $want, $bytes bytes"
    log="$LOGDIR/id$n.log"
    bash "$ROOT/hw/run-device-test.sh" "$img" -i > "$log" 2>&1
    rc=$?
    sed 's/^/   | /' "$log"
    line=$(grep -m1 '^image: sha256 ' "$log" || true)
    got=$(printf '%s' "$line" | sed -n 's/^image: sha256 \([0-9a-f]*\), \([0-9]*\) bytes.*/\1/p')
    gotb=$(printf '%s' "$line" | sed -n 's/^image: sha256 \([0-9a-f]*\), \([0-9]*\) bytes.*/\2/p')
    [ $rc -eq 0 ] && ok "device-test -i exits 0: its own digest, bytes, VERSION and CAPS checks held" ||
        bad "device-test -i exited $rc"
    # The two planted refusals (CFT_XRT_CAPS): both refused by name on an
    # image with two tiles or more, both NOT TESTED by name on one tile.
    tiles=$(sed -n 's/^device: backend xrt, \([0-9]*\) tiles\{0,1\},.*/\1/p' "$log" | head -1)
    refused=$(grep -c '^  planted CFT_XRT_CAPS=plant-[a-z]*: refused by name' "$log")
    untested=$(grep -c '^  planted CFT_XRT_CAPS=plant-[a-z]*: NOT TESTED' "$log")
    if [ "${tiles:-0}" -ge 2 ] && [ "$refused" -eq 2 ]; then
        ok "both planted refusals (tiles that differ, a tile unread) refused by name on $tiles tiles"
    elif [ "${tiles:-0}" -eq 1 ] && [ "$untested" -eq 2 ]; then
        echo "   NOTE: the planted refusals are NOT TESTED on a single tile - no tile 1 to plant in"
    else
        bad "the planted refusals: ${tiles:-no} tiles, $refused refused by name, $untested NOT TESTED - wanted both refused on two tiles or more"
    fi
    tiles_of[$img]=${tiles:-0}
    # The instrument's own edges (2026-09-28, P2c): a malformed
    # CFT_XRT_CAPS refused by name at open, and each planted handle
    # decoding exactly as the unplanted one. device-test prints each line
    # only when its checks held; the line's absence is a check not run.
    grep -q '^  CFT_XRT_CAPS: all 5 malformed values refused by name at open' "$log" &&
        ok "five malformed CFT_XRT_CAPS values refused by name at open" ||
        bad "device-test did not show the five malformed CFT_XRT_CAPS values refused by name"
    grep -q '^  the planted handles decode as the unplanted one' "$log" &&
        ok "the planted handles decode as the unplanted one: formats, features, capacities, the seven groups" ||
        bad "device-test did not show the planted handles decoding as the unplanted one"
    if same_digest "$got" "$want"; then
        ok "the library's digest is sha256sum's: $got"
    else
        bad "the library reports '${got:-nothing}' and sha256sum says $want"
    fi
    [ "$gotb" = "$bytes" ] && ok "the library's byte count is stat's: $bytes" ||
        bad "the library reports '${gotb:-nothing}' bytes and stat says $bytes"
    # The manifest as hw/verify-image.sh finds it: the derived name, else
    # the one *manifest* file beside the image, else none.
    man="${img%.xclbin}.manifest.txt"
    if [ ! -f "$man" ]; then
        cands=( "$(dirname "$img")"/*manifest* )
        [ ${#cands[@]} -eq 1 ] && [ -f "${cands[0]}" ] && man=${cands[0]}
    fi
    if [ -f "$man" ]; then
        mdig=$(sed -n 's/^sha256:[[:space:]]*\([0-9a-f]\{64\}\).*/\1/p' "$man" | head -1)
        same_digest "$got" "$mdig" && ok "the library's digest is the manifest's ($man)" ||
            bad "the manifest $man says '${mdig:-nothing}', the library '$got'"
    else
        echo "   manifest: NOT COMPARED - no $man beside the image"
    fi
    digest_of[$img]=$got
done

# ---- 3. the negative controls ----------------------------------------
echo "== 3. the negative controls"
img=${imgs[0]}
log="$LOGDIR/plant.log"
CFT_DEVICE_TEST_HASH_FILE="$DT" bash "$ROOT/hw/run-device-test.sh" "$img" -i > "$log" 2>&1
rc=$?
sed 's/^/   | /' "$log"
if [ $rc -ne 0 ] && grep -q 'which is not the SHA-256 of' "$log"; then
    ok "control a: device-test hashing host/device-test in place of the image FAILED by name (rc $rc)"
else
    bad "control a: with CFT_DEVICE_TEST_HASH_FILE planted device-test exited $rc without the named failure - its digest check cannot fail"
fi
other=$(sha256sum "$DT" | cut -c 1-64)
if ! same_digest "${digest_of[$img]}" "$other" && ! same_digest "" ""; then
    ok "control b: this script's comparison tells the image from host/device-test, and refuses two empty strings"
else
    bad "control b: this script's comparison cannot fail"
fi
# c and d need an image with two tiles or more: the plant acts on tile 1.
multi=
for i in "${imgs[@]}"; do
    [ "${tiles_of[$i]:-0}" -ge 2 ] && { multi=$i; break; }
done
if [ -n "$multi" ]; then
    # c. A CAPS read failure at open that nobody asked for, imitated from
    #    OUTSIDE device-test: its identity leg must FAIL it by name.
    log="$LOGDIR/unexpected.log"
    CFT_XRT_CAPS=plant-unreadable bash "$ROOT/hw/run-device-test.sh" "$multi" -i > "$log" 2>&1
    rc=$?
    sed 's/^/   | /' "$log"
    if [ $rc -ne 0 ] && grep -q 'and nothing told this run to expect it' "$log"; then
        ok "control c: a CAPS read failure nobody asked for (CFT_XRT_CAPS=plant-unreadable from outside) FAILED the identity leg by name (rc $rc)"
    else
        bad "control c: with CFT_XRT_CAPS=plant-unreadable set from outside, device-test exited $rc without failing the refusal by name - an unexpected refusal passes"
    fi
    # d. The same kind of refusal, EXPECTED: tiles that differ, planted
    #    from outside, with --expect-refusal mixed, as a mixed layout
    #    would be run. It must pass, by name.
    log="$LOGDIR/expected.log"
    CFT_XRT_CAPS=plant-differ bash "$ROOT/hw/run-device-test.sh" "$multi" -i --expect-refusal mixed > "$log" 2>&1
    rc=$?
    sed 's/^/   | /' "$log"
    if [ $rc -eq 0 ] && grep -q 'as this run was told to expect (--expect-refusal mixed)' "$log"; then
        ok "control d: the same refusal, expected (--expect-refusal mixed, CFT_XRT_CAPS=plant-differ from outside), passed by name"
    else
        bad "control d: an expected refusal did not pass by name (rc $rc)"
    fi
else
    echo "   controls c and d: NOT RUN - no image given has two tiles or more"
fi

# ---- 4. two images ---------------------------------------------------
if [ ${#imgs[@]} -eq 2 ]; then
    echo "== 4. two images"
    a=${digest_of[${imgs[0]}]}
    b=${digest_of[${imgs[1]}]}
    if [[ $a =~ ^[0-9a-f]{64}$ ]] && [[ $b =~ ^[0-9a-f]{64}$ ]] && [ "$a" != "$b" ]; then
        ok "two images, two digests, each its own file's (2.1 and 2.2): the digest follows the image loaded"
    else
        bad "two images gave '$a' and '$b'"
    fi
else
    echo "== 4. two images: NOT RUN - one image given"
fi

# ---- 5. the matrix still runs ----------------------------------------
echo "== 5. the open the digest changed still runs the matrix"
log="$LOGDIR/q.log"
bash "$ROOT/hw/run-device-test.sh" "$img" -q -n 8 > "$log" 2>&1
rc=$?
tail -4 "$log" | sed 's/^/   | /'
[ $rc -eq 0 ] && ok "device-test -q -n 8 on $img exits 0 ($(grep -m1 -E '^[0-9]+ checks, ' "$log"))" ||
    bad "device-test -q -n 8 on $img exited $rc - the whole log: $log (kept)"
[ $rc -eq 0 ] || trap - EXIT

# ---- 6. the remote refusal with a card behind the server -------------
echo "== 6. a remote handle to a card-backed server"
if [ -x "$SERVE" ]; then
    rm -f "$LOGDIR/port" "$LOGDIR/pid"
    "$SERVE" --artifact "$img" --port 0 --port-file "$LOGDIR/port" \
             --pid-file "$LOGDIR/pid" --max-conns 1 > "$LOGDIR/serve.log" 2>&1 &
    spid=$!
    for _ in $(seq 1 100); do [ -s "$LOGDIR/port" ] && break; sleep 0.2; done
    port=$(cat "$LOGDIR/port" 2>/dev/null)
    if [ -n "$port" ]; then
        log="$LOGDIR/remote.log"
        "$DT" "cft://127.0.0.1:$port" -i > "$log" 2>&1
        rc=$?
        sed 's/^/   | /' "$log"
        if [ $rc -eq 0 ] && grep -q 'image identity (remote): refused by name' "$log"; then
            ok "the remote handle refused by name with $img behind the server"
        else
            bad "the remote handle did not refuse by name (rc $rc)"
        fi
    else
        bad "cft-serve --artifact $img did not report a port: $(tail -2 "$LOGDIR/serve.log")"
    fi
    kill "$spid" 2>/dev/null
    wait "$spid" 2>/dev/null
    kill -0 "$spid" 2>/dev/null && bad "cft-serve (pid $spid) is still running" ||
        echo "   cft-serve pid $spid stopped"
else
    echo "   NOT RUN - no $SERVE (make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt all builds it)"
fi

echo "== card-identity: $checks checks, $failed failed"
[ "$failed" -eq 0 ]
