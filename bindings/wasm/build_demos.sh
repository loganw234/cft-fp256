#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Build bindings/wasm/demos.html: the five contract workloads of
# docs/BENCHMARKS.md, each panel a faithful port of its C tool's
# `--engine loop` path, running on THE SAME wasm module the
# conformance page embeds - assembled into ONE self-contained HTML
# file that runs from file:// with no server, no CDN and no network.
#
#     bash bindings/wasm/build_demos.sh
#
# Run it from anywhere; the only requirement is Docker. Everything
# happens inside the emscripten image build.sh pins, and the pin is
# READ OUT OF build.sh rather than typed again here - two spellings of
# one version is how they disagree.
#
# WHAT THIS BUILD DOES NOT DO: it does not touch conformance.html, it
# does not regenerate the vector sets, and it does not produce a new
# wasm module. bindings/node/cft_node.wasm is a committed build
# product whose sha256 is quoted by the conformance page and by three
# documents; stage 2 recompiles the module only so that the SINGLE_FILE
# loader exists, and stage 3 REFUSES to assemble a page whose embedded
# bytes are not byte-identical to that committed module. If emcc ever
# stops being reproducible, this build fails loudly instead of shipping
# a second module.
#
# Stages (all inside the container):
#
#   0  refuse an emcc that is not the version build.sh pins, before
#      spending a minute compiling. CFT_WASM_EMCC_ANY=1 downgrades it
#      to a warning, for trying a new emsdk on purpose.
#   1  emcc the library sources - DERIVED from host/Makefile, exactly
#      as build.sh derives them - plus wasm_api.c, twice with identical
#      flags: once split (.js + .wasm, so the identity check below has
#      a plain file to hash) and once -sSINGLE_FILE (module embedded in
#      the loader) for splicing into the page.
#
#      The ONE flag that differs from build.sh: -sENVIRONMENT=web,worker
#      instead of -sENVIRONMENT=web, because this page computes in a
#      Web Worker. ENVIRONMENT selects branches of the JavaScript
#      loader and nothing else; the .wasm it emits is the same file,
#      which stage 2's sha256 does not assume - it checks.
#   2  the identity check: the split .wasm must equal
#      bindings/node/cft_node.wasm byte for byte.
#   3  make_demos.py splices the loader, the compute core, the worker
#      bootstrap and the recorded native chains into the page, and
#      re-checks the identity a third way by walking the module bytes
#      back out of the assembled HTML.
#   4  the same assembly again with --corrupt, into
#      build/demos_negative_control.html (untracked): one panel's step
#      sabotaged, so anyone can watch the chain comparison fail. A
#      checker that has never been seen to fail proves nothing.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

# The toolchain pin, read out of build.sh. Both files must use the
# same image or the two committed pages would be built by different
# compilers while claiming one provenance.
pin() {
    sed -n "s/^$1=\"\\([^\"]*\\)\".*/\\1/p" "$HERE/build.sh" | sed -n 1p
}
EMSDK_TAG="$(pin EMSDK_TAG)"
EMSDK_DIGEST="$(pin EMSDK_DIGEST)"
[ -n "$EMSDK_TAG" ] && [ -n "$EMSDK_DIGEST" ] || {
    echo "build_demos.sh: could not read EMSDK_TAG/EMSDK_DIGEST out of" \
         "build.sh - the pin moved; teach this script where it went" >&2
    exit 1
}
IMAGE="emscripten/emsdk:${EMSDK_TAG}@${EMSDK_DIGEST}"
EMCC_EXPECT="$EMSDK_TAG"

if [ "${1:-}" != "--inside" ]; then
    # Host side: re-run this same script inside the pinned container.
    # MSYS_NO_PATHCONV stops Git Bash rewriting /src into a Windows
    # path; cygpath makes the bind source a path the daemon
    # understands. Both are build.sh's, for build.sh's reasons.
    BIND="$ROOT"
    if command -v cygpath >/dev/null 2>&1; then
        BIND="$(cygpath -w "$ROOT")"
    fi
    exec env MSYS_NO_PATHCONV=1 docker run --rm \
        -e CFT_WASM_EMCC_ANY="${CFT_WASM_EMCC_ANY:-0}" \
        -v "$BIND:/src" -w /src "$IMAGE" \
        bash bindings/wasm/build_demos.sh --inside
fi

# ---------------- container side from here on ----------------

die() { echo "build_demos.sh: $*" >&2; exit 1; }

OUT=bindings/wasm/build
mkdir -p "$OUT"

echo "== stage 0: toolchain =="
EMCC_BANNER="$(emcc --version)"
EMCC_VERSION="$(printf '%s\n' "$EMCC_BANNER" |
    grep -oE '[0-9]+\.[0-9]+\.[0-9]+ \([0-9a-f]+\)' | sed -n '1p')"
EMCC_DOTTED="${EMCC_VERSION%% *}"
echo "emcc ${EMCC_VERSION:-$(printf '%s\n' "$EMCC_BANNER" | sed -n '1p')}"
if [ "$EMCC_DOTTED" != "$EMCC_EXPECT" ]; then
    if [ "${CFT_WASM_EMCC_ANY:-0}" = "1" ]; then
        echo "build_demos.sh: WARNING - emcc ${EMCC_DOTTED:-?}, expected" \
             "$EMCC_EXPECT (CFT_WASM_EMCC_ANY=1). The page this produces" \
             "is NOT the pinned build; do not commit it without changing" \
             "the pin in build.sh and saying why." >&2
    else
        die "emcc ${EMCC_DOTTED:-?}, but this build is pinned to $EMCC_EXPECT
    (image $IMAGE, pinned in build.sh). Run the script without --inside
    and let it pull the pinned image, or set CFT_WASM_EMCC_ANY=1 to
    build with this one anyway - knowing the result is not the pinned
    page."
    fi
fi

echo "== stage 1: emcc =="
# Derived from host/Makefile, and cross-checked against host/src/*.c,
# for the reason build.sh's header spells out: a list that can go
# stale silently is a list that will.
MAKE_SRC="$(make -C host --no-print-directory \
    --eval='cft-wasm-print-src: ; @printf "%s\n" $(SRC)' \
    cft-wasm-print-src)"
[ -n "$MAKE_SRC" ] || die "host/Makefile named no sources - derivation failed"

LIB_SRC=()
while read -r s; do
    [ -n "$s" ] || continue
    [ -f "host/$s" ] || die "host/Makefile builds host/$s, which is not there"
    LIB_SRC+=("host/$s")
done <<< "$MAKE_SRC"

DIR_SRC=()
for s in host/src/*.c; do DIR_SRC+=("$s"); done
sorted() { printf '%s\n' "$@" | LC_ALL=C sort | tr '\n' ' '; }
if [ "$(sorted "${LIB_SRC[@]}")" != "$(sorted "${DIR_SRC[@]}")" ]; then
    die "host/Makefile builds [$(sorted "${LIB_SRC[@]}")] but host/src holds
    [$(sorted "${DIR_SRC[@]}")]. One of them is wrong."
fi
echo "sources (${#LIB_SRC[@]}, from host/Makefile): ${LIB_SRC[*]}"

# Identical to build.sh's list except -sENVIRONMENT (see the header).
EMCC_FLAGS=(
    -std=c99 -O2 -Wall -Wextra
    -Ihost/include
    "${LIB_SRC[@]}"
    bindings/wasm/wasm_api.c
    -sEXPORTED_FUNCTIONS=_malloc,_free
    -sEXPORTED_RUNTIME_METHODS=FS,ccall,cwrap,UTF8ToString,stringToUTF8,lengthBytesUTF8,HEAPU8,HEAPU32
    -sMODULARIZE=1
    -sEXPORT_NAME=createCftModule
    -sFORCE_FILESYSTEM=1
    -sALLOW_MEMORY_GROWTH=1
)

emcc "${EMCC_FLAGS[@]}" -sENVIRONMENT=web,worker -o "$OUT/cft_demos_split.js"
emcc "${EMCC_FLAGS[@]}" -sENVIRONMENT=web,worker -sSINGLE_FILE=1 \
    -o "$OUT/cft_demos_runtime.js"
ls -l "$OUT/cft_demos_split.wasm" "$OUT/cft_demos_runtime.js"

echo "== stage 2: the module identity =="
WANT="$(sha256sum bindings/node/cft_node.wasm | cut -d' ' -f1)"
GOT="$(sha256sum "$OUT/cft_demos_split.wasm" | cut -d' ' -f1)"
echo "committed bindings/node/cft_node.wasm  $WANT"
echo "this build  cft_demos_split.wasm       $GOT"
if [ "$WANT" != "$GOT" ]; then
    die "the module this build produced is NOT the committed module. The
    demos page exists to run the conformance page's own bits; embedding
    a different module would make its chains a claim about some other
    build. Refused. (If the module is meant to change, that is a
    bindings/wasm/build.sh job, and three documents quote the old
    hash.)"
fi

echo "== stage 3: the page =="
python3 bindings/wasm/make_demos.py \
    --runtime "$OUT/cft_demos_runtime.js" \
    --wasm "$OUT/cft_demos_split.wasm" \
    --module bindings/node/cft_node.wasm \
    --core bindings/wasm/demos_core.js \
    --worker bindings/wasm/demos_worker.js \
    --chains bindings/wasm/demos_chains.json \
    --template bindings/wasm/demos_template.html \
    --out bindings/wasm/demos.html \
    --image "$IMAGE" \
    --emcc-version "$EMCC_VERSION"

echo "== stage 4: the negative control (build/, untracked) =="
python3 bindings/wasm/make_demos.py \
    --runtime "$OUT/cft_demos_runtime.js" \
    --wasm "$OUT/cft_demos_split.wasm" \
    --module bindings/node/cft_node.wasm \
    --core bindings/wasm/demos_core.js \
    --worker bindings/wasm/demos_worker.js \
    --chains bindings/wasm/demos_chains.json \
    --template bindings/wasm/demos_template.html \
    --out "$OUT/demos_negative_control.html" \
    --image "$IMAGE" \
    --emcc-version "$EMCC_VERSION" \
    --corrupt

echo "== done =="
sha256sum bindings/wasm/demos.html "$OUT/demos_negative_control.html"
