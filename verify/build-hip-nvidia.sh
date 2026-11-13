#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# HIP for NVIDIA built from ROCm's own sources: the study GPU-B's recipe
# (docs/studies/GPU-B-hip-nvidia.md, section 3 and its appendix; its
# docs/studies/gpu-b/build_hip_nv.sh and build_hipcc.sh) as a script of the
# repository's, for verify/run.sh's `hip-source` stage (Logan, 2026-11-10:
# "install CUDA 13 and make the recipe a stage"). It is this prefix's
# build-mpfr-oracle.sh: it downloads, so it is run by hand at the lead's
# word, and no stage runs it.
#
#   bash verify/build-hip-nvidia.sh --print [PREFIX]   what it would fetch,
#                                     from where, into where, and every
#                                     command; runs nothing
#   bash verify/build-hip-nvidia.sh --yes [PREFIX]     fetch, build, install
#   bash verify/build-hip-nvidia.sh --check PREFIX     is PREFIX this build?
#                                     reads it, runs its hipconfig; no network
#
# With no argument it prints this and stops: nothing reaches the network
# without --yes. PREFIX defaults to verify/_hip-nvidia-prefix (the stage's
# HIPSRC_ROOT default), BUILD to verify/_hip-nvidia-build (both ignored by
# git); CUDA_HOME to /usr/local/cuda-13.3, under which the recipe needs no
# patch (GPU-B section 3b; under 12.9 it needs GPU-B's C1, not made here).
# Needs git, cmake, a C++ compiler and that CUDA's nvcc; no root, and
# nothing written outside PREFIX and BUILD. GPU-B measured the clones and
# trees at about 180 MB and the whole at about six minutes (2026-11-10).
#
# The pins: two tags, and the commit each named when GPU-B built it (the
# study records 12 hex digits; a tag that has moved is refused by name):
set -uo pipefail
RS_URL=https://github.com/ROCm/rocm-systems.git
RS_TAG=therock-10.1
RS_COMMIT=7da43026e4f2
RS_PATHS="projects/hip projects/clr projects/hipother"
LL_URL=https://github.com/ROCm/llvm-project.git
LL_TAG=therock-10.1
LL_COMMIT=d6f6cb691863
LL_PATHS="amd/hipcc"
ROOT=$(cd "$(dirname "$0")/.." && pwd)
MODE=${1:-}
PREFIX=${2:-$ROOT/verify/_hip-nvidia-prefix}
BUILD=${BUILD:-$ROOT/verify/_hip-nvidia-build}
CUDA_HOME=${CUDA_HOME:-/usr/local/cuda-13.3}

plan() {
  echo "build-hip-nvidia: HIP for NVIDIA from ROCm's sources, the study GPU-B's recipe"
  echo "  fetch  $RS_URL tag $RS_TAG (commit $RS_COMMIT...), sparse: $RS_PATHS"
  echo "  fetch  $LL_URL tag $LL_TAG (commit $LL_COMMIT...), sparse: $LL_PATHS"
  echo "         (shallow, blobless: about 180 MB of clones and trees together, GPU-B's figure)"
  echo "  into   $BUILD/src; build trees $BUILD/hip and $BUILD/hipcc"
  echo "  CUDA   $CUDA_HOME ($( [ -x "$CUDA_HOME/bin/nvcc" ] && echo 'nvcc there' || echo 'NO nvcc there'))"
  echo "  install $PREFIX"
  echo "  commands:"
  echo "    git clone --depth 1 --filter=blob:none --sparse --branch $RS_TAG $RS_URL $BUILD/src/rocm-systems"
  echo "    git -C $BUILD/src/rocm-systems sparse-checkout set $RS_PATHS"
  echo "    git clone --depth 1 --filter=blob:none --sparse --branch $LL_TAG $LL_URL $BUILD/src/llvm-project"
  echo "    git -C $BUILD/src/llvm-project sparse-checkout set $LL_PATHS"
  echo "    cmake -S \$RS/projects/clr -B $BUILD/hip -DCLR_BUILD_HIP=ON -DHIP_PLATFORM=nvidia" \
       "-DHIP_COMMON_DIR=\$RS/projects/hip -DHIPNV_DIR=\$RS/projects/hipother/hipnv" \
       "-DROCM_PATH=$PREFIX -DCMAKE_INSTALL_PREFIX=$PREFIX; cmake --build -j4; cmake --install"
  echo "    cmake -S \$LL/amd/hipcc -B $BUILD/hipcc -DCMAKE_INSTALL_PREFIX=$PREFIX" \
       "-DCMAKE_BUILD_TYPE=Release; cmake --build -j4; cmake --install"
}
step() {  # <what> <command...>: run it, its output in BUILD/<what>.log, stop on a failure
  local what=$1; shift
  echo "== $what $(date '+%F %T')"
  if ! "$@" > "$BUILD/$what.log" 2>&1; then
    tail -n 20 "$BUILD/$what.log"; echo "build-hip-nvidia: FAILED at $what ($BUILD/$what.log)"; exit 1
  fi
}
clone() {  # <url> <tag> <commit prefix> <dir> <paths...>
  local url=$1 tag=$2 want=$3 dir=$4 got; shift 4
  step "clone-$(basename "$dir")" git clone --depth 1 --filter=blob:none --sparse --branch "$tag" "$url" "$dir"
  step "sparse-$(basename "$dir")" git -C "$dir" sparse-checkout set "$@"
  got=$(git -C "$dir" rev-parse HEAD)
  case "$got" in "$want"*) echo "  $tag is $got, the pin";;
    *) echo "build-hip-nvidia: REFUSED - $url tag $tag is $got, not the pinned $want...: the tag moved"; exit 1;; esac
}

case "$MODE" in
  --print) plan; exit 0;;
  --check)
    [ $# -ge 2 ] || { echo "build-hip-nvidia: --check PREFIX"; exit 2; }
    v=$("$PREFIX/bin/hipconfig" --version 2>/dev/null | tail -n 1)
    p=$("$PREFIX/bin/hipconfig" --platform 2>/dev/null | tail -n 1)
    if [ -x "$PREFIX/bin/hipcc" ] && [ -d "$PREFIX/include/hip" ] && [ "$p" = nvidia ] \
       && case "$v" in *"-${RS_COMMIT:0:10}"*) true;; *) false;; esac; then
      echo "build-hip-nvidia: $PREFIX is this recipe's build: hipcc, include/hip, platform $p, version $v (rocm-systems $RS_COMMIT...)"
      exit 0
    fi
    echo "build-hip-nvidia: $PREFIX is not this recipe's build: hipcc $( [ -x "$PREFIX/bin/hipcc" ] && echo there || echo missing), include/hip $( [ -d "$PREFIX/include/hip" ] && echo there || echo missing), platform '${p:-none}', version '${v:-none}' (want ...-${RS_COMMIT:0:10}...)"
    exit 1;;
  --yes) ;;
  *) sed -n '2,/^set -uo pipefail$/p' "$0" | sed -n '/^#   bash/,/^# trees at/p' | sed 's/^# \{0,1\}//'
     echo; plan; echo; echo "build-hip-nvidia: nothing done - give --yes to fetch and build, or --print"; exit 2;;
esac

plan
for t in git cmake c++; do command -v "$t" >/dev/null 2>&1 || { echo "build-hip-nvidia: no $t on PATH"; exit 1; }; done
[ -x "$CUDA_HOME/bin/nvcc" ] || { echo "build-hip-nvidia: no nvcc at $CUDA_HOME/bin (CUDA_HOME)"; exit 1; }
[ -e "$PREFIX/bin/hipcc" ] && { echo "build-hip-nvidia: $PREFIX already holds a hipcc - remove it first, or --check it"; exit 1; }
export CUDA_HOME CUDA_PATH=$CUDA_HOME PATH="$CUDA_HOME/bin:$PATH"
rm -rf "$BUILD" && mkdir -p "$BUILD/src" "$PREFIX" || exit 1
RS="$BUILD/src/rocm-systems"; LL="$BUILD/src/llvm-project"
clone "$RS_URL" "$RS_TAG" "$RS_COMMIT" "$RS" $RS_PATHS
clone "$LL_URL" "$LL_TAG" "$LL_COMMIT" "$LL" $LL_PATHS
step configure-hip cmake -S "$RS/projects/clr" -B "$BUILD/hip" -DCLR_BUILD_HIP=ON -DHIP_PLATFORM=nvidia \
  -DHIP_COMMON_DIR="$RS/projects/hip" -DHIPNV_DIR="$RS/projects/hipother/hipnv" \
  -DROCM_PATH="$PREFIX" -DCMAKE_INSTALL_PREFIX="$PREFIX"
step build-hip cmake --build "$BUILD/hip" -j4
step install-hip cmake --install "$BUILD/hip"
step configure-hipcc cmake -S "$LL/amd/hipcc" -B "$BUILD/hipcc" -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_BUILD_TYPE=Release
step build-hipcc cmake --build "$BUILD/hipcc" -j4
step install-hipcc cmake --install "$BUILD/hipcc"
bash "$0" --check "$PREFIX"
