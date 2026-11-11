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
{ echo "# CUDA 13.3 packages (12): version, bytes, SHA256 of the repository index"; cat $HOME/gpu-b/apt13-pkgs.txt
  echo "# sum of the 12 sizes (bytes): $(awk '{s+=$3} END{print s}' $HOME/gpu-b/apt13-pkgs.txt)"
  echo "# apt's own lines (apt13-install.log):"; grep -E '^(Need to get|After this operation)' $HOME/gpu-b/apt13-install.log
  echo "# /usr/local/cuda-13.3 after the install (du -sh): $(du -sh /usr/local/cuda-13.3 | cut -f1)"
  echo "# apt history.log, this install:"; awk '/Start-Date: 2026-11-10  18:21:04/{f=1} f&&/^(Start-Date|End-Date)/{print} f&&/End-Date/{exit}' /var/log/apt/history.log
  echo "# 12 names in its Install line: $(awk '/Start-Date: 2026-11-10  18:21:04/{f=1} f&&/^Install:/{print; exit}' /var/log/apt/history.log | tr ',' '
' | grep -c ':amd64\|:all')"
  echo "# the alternatives lines (apt13-install.log; no timestamp in apt's log):"; grep 'update-alternatives' $HOME/gpu-b/apt13-install.log
  echo "# present before: $(dpkg -l cuda-toolkit-config-common | awk '/^ii/{print $2, $3}') (from the 12.9 install, history.log 15:17:00)"; } | scrub > "$D/cuda13-packages.txt"
ls "$D"
