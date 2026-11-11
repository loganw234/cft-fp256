#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B follow-up: run run_cuda13.sh build and gpu, keep the scrubbed logs.
#   collect13.sh DEST      (in cft-gpu; the card runs are the 5060 Ti's, ~5 s)
D=${1:?DEST}; mkdir -p "$D"
here=$(cd "$(dirname "$0")" && pwd); TREE=$(cd "$here/../../.." && pwd)
W=$HOME/gpu-b13; mkdir -p "$W"
scrub() { sed -e "s#$TREE#<tree>#g" -e "s#$HOME#~#g" -e 's/ *$//'; }
bash "$here/run_cuda13.sh" build "$W" 2>&1 | grep -v 'CUDA_DEPRECATED\|\^~~~\|^ *|' | scrub > "$D/cuda13-build.txt"
bash "$here/run_cuda13.sh" gpu "$W" 2>&1 | cut -c1-200 | scrub > "$D/cuda13-gpu.txt"
# the one error GPU-A's header leg gives under CUDA 13, from its own log
grep ' error' "$W/out/acuda.log" | scrub > "$D/cuda13-errors.txt"
{ echo "# CUDA 13.3 packages: version, size, SHA256 of the repository index"; cat $HOME/gpu-b/apt13-pkgs.txt; } | scrub > "$D/cuda13-packages.txt"
ls "$D"
