#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Build bindings/wasm/conformance.html: libcft's software backend
# compiled to WebAssembly plus an embedded sample of the published
# conformance vectors, assembled into ONE self-contained HTML file
# that runs from file:// with no server, no CDN and no network.
#
#     bash bindings/wasm/build.sh
#
# Run it from anywhere; the only requirement is Docker. The whole
# build - vector generation, compilation, page assembly - happens
# inside the emscripten image pinned below by tag AND digest, so the
# toolchain is identical on every machine and "it built differently
# here" is not an available failure mode. No host compiler, no host
# emsdk, no host Python is consulted.
#
# Stages (all inside the container):
#
#   0  refuse an emcc that is not the pinned version, before spending
#      a minute on vectors. CFT_WASM_EMCC_ANY=1 downgrades it to a
#      warning, for trying a new emsdk on purpose.
#   1  regenerate the published vector sets into build/vectors/ with
#      the exact `make vectors` arguments. Vectors are derived data
#      (gitignored); the build regenerates its own copy rather than
#      trusting whatever vectors/out currently holds.
#   2  emcc the library sources - DERIVED from host/Makefile, see
#      below - plus wasm_api.c, twice with identical flags: once
#      split (.js + .wasm, so the wasm size below is a measured fact)
#      and once -sSINGLE_FILE (wasm embedded as base64) for splicing
#      into the page.
#   3  make_page.py samples the sets and assembles the page. THE
#      SAMPLING RULE (also stated in make_page.py and on the page):
#      from each of the 20 sets (4 formats x 5 rounding attributes,
#      11,800 lines each) take every 59th line - 0-based lines 0, 59,
#      118, ... = exactly 200 per set - then add the set's first line
#      of any opcode name the stride missed, so every opcode class is
#      embedded per set by construction, seeds 26/27 and the
#      unassigned reserved15/28/255 included.
#   4  the same assembly again with --corrupt, into
#      build/negative_control.html (untracked): one expected value
#      deliberately flipped, so anyone can watch the page fail. A
#      checker that has never been seen to fail proves nothing.
#   5  the same module a third time for node (-sENVIRONMENT=node),
#      into build/ and, when bindings/node exists, into the package.
#      The .wasm is byte-identical to the page's - only the loader
#      differs - which is what lets a node harness replay all 236,000
#      cases against THE PAGE'S module instead of a lookalike.
#      bindings/wasm/verify.mjs checks that identity rather than
#      assuming it.
#
# WHY THE SOURCE LIST IS DERIVED (2026-09-02). It used to be typed
# here, and it drifted: host/Makefile grew src/clause5.c with ABI 0.2
# and this file kept compiling six sources. Nothing caught it, because
# nothing in the other six references clause5.c - the wasm build still
# linked, and simply had none of the clause-5 entry points in it while
# reporting the ABI version that names them. A list that can go stale
# silently is a list that will, so there is no list here any more:
# stage 2 asks host/Makefile what it builds and compiles exactly that,
# and cross-checks the answer against host/src/*.c so a source neither
# of them builds is a loud failure rather than a quiet omission.
#
# Why the arithmetic survives this trip untouched: the software
# backend computes in uint32 limbs with uint64 intermediates and no
# host floating point anywhere (host/src/bigint.c), and wasm integer
# semantics are fully specified. Compiling to wasm therefore cannot
# change a result bit - which is the whole reason a browser tab is a
# legitimate conformance venue. bindings/wasm/README.md spells the
# argument out.

set -euo pipefail

# The toolchain, pinned twice over: the tag is the emcc version these
# images carry (emscripten/emsdk:X.Y.Z ships emcc X.Y.Z), the digest
# is the exact image. EMCC_EXPECT is derived from the tag rather than
# typed again - two spellings of one version is how they disagree.
EMSDK_TAG="6.0.9"
EMSDK_DIGEST="sha256:96617f27fe16421588241def73908fd348a7f9d260440ed0d00b36dcf7a063cc"
IMAGE="emscripten/emsdk:${EMSDK_TAG}@${EMSDK_DIGEST}"
EMCC_EXPECT="$EMSDK_TAG"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

if [ "${1:-}" != "--inside" ]; then
    # Host side: re-run this same script inside the pinned container.
    # MSYS_NO_PATHCONV stops Git Bash rewriting /src into a Windows
    # path; it is inert everywhere else. The bind SOURCE has to be a
    # path the daemon understands, and under Git Bash $PWD is an MSYS
    # path (/c/Users/...) that Docker Desktop reads as a container
    # path and silently mounts empty - so cygpath it where cygpath
    # exists, and leave it alone everywhere else.
    BIND="$ROOT"
    if command -v cygpath >/dev/null 2>&1; then
        BIND="$(cygpath -w "$ROOT")"
    fi
    exec env MSYS_NO_PATHCONV=1 docker run --rm \
        -e CFT_WASM_EMCC_ANY="${CFT_WASM_EMCC_ANY:-0}" \
        -v "$BIND:/src" -w /src "$IMAGE" \
        bash bindings/wasm/build.sh --inside
fi

# ---------------- container side from here on ----------------

die() { echo "build.sh: $*" >&2; exit 1; }

OUT=bindings/wasm/build
mkdir -p "$OUT"

# The toolchain check comes FIRST, before a minute of vector
# generation, because a build that is going to be refused should be
# refused immediately. "6.0.9 (4e42238...)": the version and commit,
# not the banner prose.
EMCC_BANNER="$(emcc --version)"
EMCC_VERSION="$(printf '%s\n' "$EMCC_BANNER" |
    grep -oE '[0-9]+\.[0-9]+\.[0-9]+ \([0-9a-f]+\)' | sed -n '1p')"
EMCC_DOTTED="${EMCC_VERSION%% *}"
echo "== stage 0: toolchain =="
echo "emcc ${EMCC_VERSION:-$(printf '%s\n' "$EMCC_BANNER" | sed -n '1p')}"

# The page is a committed build product and its provenance block names
# the toolchain that made it, so a build from a DIFFERENT emcc would
# either produce a page whose provenance is a surprise to the next
# reader or, worse, get committed as if it were the pinned one. It is
# refused. The escape hatch exists because trying a new emsdk is a
# legitimate thing to do - it is just never the thing you ship without
# saying so.
if [ "$EMCC_DOTTED" != "$EMCC_EXPECT" ]; then
    if [ "${CFT_WASM_EMCC_ANY:-0}" = "1" ]; then
        echo "build.sh: WARNING - emcc ${EMCC_DOTTED:-?}, expected" \
             "$EMCC_EXPECT (CFT_WASM_EMCC_ANY=1). The page this produces" \
             "is NOT the pinned build; do not commit it without changing" \
             "EMSDK_TAG and saying why." >&2
    else
        die "emcc ${EMCC_DOTTED:-?}, but this build is pinned to $EMCC_EXPECT
    (image $IMAGE). Run the script without --inside and let it pull the
    pinned image, or set CFT_WASM_EMCC_ANY=1 to build with this one
    anyway - knowing the result is not the pinned page."
    fi
fi

# The user-facing regeneration command: identical arguments to `make
# vectors`, and to stage 1 below except for --out. It is what the
# page tells people to run for droppable full sets, so the sample and
# the files they drop come from the same deterministic generator run.
GEN_ARGS="--formats fp32 fp64 fp128 fp256 --rounding rne rtz rdn rup rmm \
--directed 3000 --random 4000 --simple 200"
GEN_COMMAND="python3 vectors/gen_vectors.py --out vectors/out $GEN_ARGS"

echo "== stage 1: vectors (deterministic, seed 3) =="
# shellcheck disable=SC2086  # GEN_ARGS is a word list on purpose
python3 vectors/gen_vectors.py --out "$OUT/vectors" $GEN_ARGS

echo "== stage 2: emcc =="
# The library sources, asked of host/Makefile rather than typed here.
# --eval injects a target into the real Makefile, so SRC is whatever
# that file says today, with its own conditionals applied (XRT stays
# off: wasm32 has no PCIe and needs none, and backend_xrt.cpp is the
# only source that would add).
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

# Second derivation, from the directory, and the two must agree. This
# catches the other direction: a .c that exists and that host/Makefile
# does NOT build would otherwise be invisible here. If one ever needs
# excluding, exclude it by name and say why - the point is that no
# source goes missing without somebody deciding it should.
DIR_SRC=()
for s in host/src/*.c; do DIR_SRC+=("$s"); done
sorted() { printf '%s\n' "$@" | LC_ALL=C sort | tr '\n' ' '; }
if [ "$(sorted "${LIB_SRC[@]}")" != "$(sorted "${DIR_SRC[@]}")" ]; then
    die "host/Makefile builds [$(sorted "${LIB_SRC[@]}")] but host/src holds
    [$(sorted "${DIR_SRC[@]}")]. One of them is wrong, and a wasm module
    quietly missing an entry point is exactly the failure this check
    exists for (it happened: clause5.c, 2026-09-01 to 09-02)."
fi
echo "sources (${#LIB_SRC[@]}, from host/Makefile): ${LIB_SRC[*]}"

EMCC_FLAGS=(
    -std=c99 -O2 -Wall -Wextra
    -Ihost/include
    "${LIB_SRC[@]}"
    bindings/wasm/wasm_api.c
    # cftw_* exports are EMSCRIPTEN_KEEPALIVE in wasm_api.c, which is
    # the complete list of what the module exposes; malloc/free are
    # the only runtime extras the page needs for its buffers.
    -sEXPORTED_FUNCTIONS=_malloc,_free
    -sEXPORTED_RUNTIME_METHODS=FS,ccall,cwrap,UTF8ToString,stringToUTF8,lengthBytesUTF8,HEAPU8,HEAPU32
    -sMODULARIZE=1
    -sEXPORT_NAME=createCftModule
    # conformance.c reads the sets back through fopen(); in the page
    # that directory is MEMFS, so the replay is the library's own
    # file-reading code path, not a shortcut around it.
    -sFORCE_FILESYSTEM=1
    # a full 20-set drop holds ~50 MB of text transiently
    -sALLOW_MEMORY_GROWTH=1
)

emcc "${EMCC_FLAGS[@]}" -sENVIRONMENT=web -o "$OUT/cft_split.js"
emcc "${EMCC_FLAGS[@]}" -sENVIRONMENT=web -sSINGLE_FILE=1 \
    -o "$OUT/cft_runtime.js"
ls -l "$OUT/cft_split.wasm" "$OUT/cft_runtime.js"

echo "== stage 3: the page =="
python3 bindings/wasm/make_page.py \
    --vectors "$OUT/vectors" \
    --runtime "$OUT/cft_runtime.js" \
    --wasm "$OUT/cft_split.wasm" \
    --template bindings/wasm/page_template.html \
    --out bindings/wasm/conformance.html \
    --image "$IMAGE" \
    --emcc-version "$EMCC_VERSION" \
    --gen-command "$GEN_COMMAND"

echo "== stage 4: the negative control (build/, untracked) =="
python3 bindings/wasm/make_page.py \
    --vectors "$OUT/vectors" \
    --runtime "$OUT/cft_runtime.js" \
    --wasm "$OUT/cft_split.wasm" \
    --template bindings/wasm/page_template.html \
    --out "$OUT/negative_control.html" \
    --image "$IMAGE" \
    --emcc-version "$EMCC_VERSION" \
    --gen-command "$GEN_COMMAND" \
    --corrupt

echo "== stage 5: the node loader =="
# Same sources, same flags, one different -sENVIRONMENT. A browser
# cannot run a vectors replay unattended and a page cannot be a test
# in CI; node can be both, and the module it loads has to be THE
# page's module for that to mean anything - hence the sha256 line
# below, and verify.mjs, which refuses to report a replay against a
# module whose hash does not match the page's.
emcc "${EMCC_FLAGS[@]}" -sENVIRONMENT=node -o "$OUT/cft_node.js"
if [ -d bindings/node ]; then
    cp "$OUT/cft_node.js" "$OUT/cft_node.wasm" bindings/node/
    echo "installed into bindings/node/"
fi
sha256sum "$OUT/cft_split.wasm" "$OUT/cft_node.wasm"

echo "== done =="
sha256sum bindings/wasm/conformance.html "$OUT/negative_control.html"
