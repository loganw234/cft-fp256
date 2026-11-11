#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B step 3b: build hipcc and hipconfig from ROCm's own source
# (llvm-project, tag therock-10.1, amd/hipcc) with its own CMake, and
# install them into the same prefix as build_hip_nv.sh.
#   build_hipcc.sh SRC PREFIX     SRC = the llvm-project sparse clone
# No GPU.  Logs in $BLD.
set -u
SRC=${1:?SRC}; PREFIX=${2:?PREFIX}
BLD=${BLD:-$HOME/gpu-b/build-hipcc}
rm -rf "$BLD"; mkdir -p "$BLD"
cmake -S "$SRC/amd/hipcc" -B "$BLD" -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_BUILD_TYPE=Release > "$BLD/configure.log" 2>&1
echo "configure rc=$?"; grep -n -i 'error\|warning' "$BLD/configure.log" | sed -n 1,20p
cmake --build "$BLD" -j4 > "$BLD/build.log" 2>&1
echo "build rc=$?"; grep -n -i 'error' "$BLD/build.log" | sed -n 1,20p
cmake --install "$BLD" > "$BLD/install.log" 2>&1
echo "install rc=$?"; grep -n -i 'error' "$BLD/install.log" | sed -n 1,20p
ls -la "$PREFIX/bin"
