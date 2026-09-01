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
#   1  regenerate the published vector sets into build/vectors/ with
#      the exact `make vectors` arguments. Vectors are derived data
#      (gitignored); the build regenerates its own copy rather than
#      trusting whatever vectors/out currently holds.
#   2  emcc the six library sources (bigint, softfloat, device,
#      divsqrt, program, conformance - the XRT backend is not
#      compiled: wasm32 has no PCIe and needs none) plus wasm_api.c,
#      twice with identical flags: once split (.js + .wasm, so the
#      wasm size below is a measured fact) and once -sSINGLE_FILE
#      (wasm embedded as base64) for splicing into the page.
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
#
# Why the arithmetic survives this trip untouched: the software
# backend computes in uint32 limbs with uint64 intermediates and no
# host floating point anywhere (host/src/bigint.c), and wasm integer
# semantics are fully specified. Compiling to wasm therefore cannot
# change a result bit - which is the whole reason a browser tab is a
# legitimate conformance venue. bindings/wasm/README.md spells the
# argument out.

set -euo pipefail

IMAGE="emscripten/emsdk:6.0.9@sha256:96617f27fe16421588241def73908fd348a7f9d260440ed0d00b36dcf7a063cc"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

if [ "${1:-}" != "--inside" ]; then
    # Host side: re-run this same script inside the pinned container.
    # MSYS_NO_PATHCONV stops Git Bash rewriting /src into a Windows
    # path; it is inert everywhere else.
    exec env MSYS_NO_PATHCONV=1 docker run --rm \
        -v "$ROOT:/src" -w /src "$IMAGE" \
        bash bindings/wasm/build.sh --inside
fi

# ---------------- container side from here on ----------------

OUT=bindings/wasm/build
mkdir -p "$OUT"

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
emcc --version | head -n1
# "6.0.9 (4e42238...)": the version and commit, not the banner prose.
EMCC_VERSION="$(emcc --version | head -n1 |
    grep -oE '[0-9]+\.[0-9]+\.[0-9]+ \([0-9a-f]+\)')"

EMCC_FLAGS=(
    -std=c99 -O2 -Wall -Wextra
    -Ihost/include
    host/src/bigint.c
    host/src/softfloat.c
    host/src/device.c
    host/src/divsqrt.c
    host/src/program.c
    host/src/conformance.c
    bindings/wasm/wasm_api.c
    # cftw_* exports are EMSCRIPTEN_KEEPALIVE in wasm_api.c, which is
    # the complete list of what the module exposes; malloc/free are
    # the only runtime extras the page needs for its buffers.
    -sEXPORTED_FUNCTIONS=_malloc,_free
    -sEXPORTED_RUNTIME_METHODS=FS,ccall,cwrap,UTF8ToString,stringToUTF8,lengthBytesUTF8,HEAPU8,HEAPU32
    -sMODULARIZE=1
    -sEXPORT_NAME=createCftModule
    -sENVIRONMENT=web
    # conformance.c reads the sets back through fopen(); in the page
    # that directory is MEMFS, so the replay is the library's own
    # file-reading code path, not a shortcut around it.
    -sFORCE_FILESYSTEM=1
    # a full 20-set drop holds ~50 MB of text transiently
    -sALLOW_MEMORY_GROWTH=1
)

emcc "${EMCC_FLAGS[@]}" -o "$OUT/cft_split.js"
emcc "${EMCC_FLAGS[@]}" -sSINGLE_FILE=1 -o "$OUT/cft_runtime.js"
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

echo "== done =="
sha256sum bindings/wasm/conformance.html "$OUT/negative_control.html"
