#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B step 3: assemble HIP for NVIDIA from ROCm's own sources at the
# 10.1 release tag (rocm-systems therock-10.1), by the repository's own
# CMake (projects/clr, HIP_PLATFORM=nvidia).  Run in the WSL distro cft-gpu.
#
#   build_hip_nv.sh SRC PREFIX [HIPCC_BIN_DIR]
#     SRC     the rocm-systems clone (projects/hip, clr, hipother present)
#     PREFIX  install prefix of our own (e.g. /opt/gpu-b)
#     HIPCC_BIN_DIR  directory holding hipcc and hipconfig, if built (step 4)
#
# No GPU; configure, build, install only.  Logs: $PREFIX-logs next to it.
set -u
SRC=${1:?SRC}; PREFIX=${2:?PREFIX}; HB=${3:-}
BLD=${BLD:-$HOME/gpu-b/build-hip}
rm -rf "$BLD"; mkdir -p "$BLD"
echo "== configure $(date '+%F %T')"
cmake -S "$SRC/projects/clr" -B "$BLD" \
    -DCLR_BUILD_HIP=ON -DHIP_PLATFORM=nvidia \
    -DHIP_COMMON_DIR="$SRC/projects/hip" \
    -DHIPNV_DIR="$SRC/projects/hipother/hipnv" \
    -DHIPCC_BIN_DIR="$HB" \
    -DROCM_PATH="$PREFIX" -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    > "$BLD/configure.log" 2>&1
echo "configure rc=$?"
grep -n -i 'error\|warning' "$BLD/configure.log" | sed -n 1,20p
echo "== build $(date '+%F %T')"
cmake --build "$BLD" -j4 > "$BLD/build.log" 2>&1
echo "build rc=$?"
grep -n -i 'error' "$BLD/build.log" | sed -n 1,20p
echo "== install $(date '+%F %T')"
cmake --install "$BLD" > "$BLD/install.log" 2>&1
echo "install rc=$?"
grep -n -i 'error' "$BLD/install.log" | sed -n 1,20p
