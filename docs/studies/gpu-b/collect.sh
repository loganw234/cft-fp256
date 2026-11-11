#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B: gather the small captured outputs into DEST (the study's captured/),
# scrubbed of this machine's paths.  Run in cft-gpu after the builds.
#   collect.sh DEST
D=${1:?DEST}; mkdir -p "$D"
here=$(cd "$(dirname "$0")" && pwd)
TREE=$(cd "$here/../../.." && pwd)
O=$HOME/gpu-b/out
scrub() { sed -e "s#$TREE#<tree>#g" -e "s#$HOME#~#g"; }
{ echo "# git ls-remote of github.com/ROCm/<repo>: lines (heads+tags) and the newest rocm-* / therock-* tags"
  for r in hipother HIP clr hipcc rocm-systems llvm-project; do
     printf '%s: %s refs; ' $r "$(wc -l < $O/../lsr/$r.txt)"
     cut -f2 $O/../lsr/$r.txt | grep -E 'tags/(rocm|therock)-[0-9.]+$' | sed 's#refs/tags/##' | sort -V | tail -3 | tr '\n' ' '; echo; done
} | sed 's/ *$//' > "$D/refs.txt"
diff -rq ~/gpu-b/src/hipother-7.2.4/hipnv/include/hip/nvidia_detail ~/gpu-b/src/rs-10.1/projects/hipother/hipnv/include/hip/nvidia_detail | scrub > "$D/hipother-7.2.4-vs-10.1.txt"
{ echo "# hipother nvidia_detail, tag rocm-7.2.4 against therock-10.1 (diff -ru)"; grep -c '^+[^+]' $O/../hipother-7.2.4-vs-10.1.diff | sed 's/^/added lines: /'; grep -c '^-[^-]' $O/../hipother-7.2.4-vs-10.1.diff | sed 's/^/removed lines: /'; } >> "$D/hipother-7.2.4-vs-10.1.txt"
{ echo "# attempt A, no change: nvcc 12.9 on toolchain_check.hip (errors only)"; grep -h 'error' $O/a1/nvcc.log | scrub
  echo "# after build_hip_nv.sh (hip_version.h generated), no change to the headers:"; grep -h 'error' $O/a2/nvcc.log | scrub | sed 's#/opt/gpu-b/include/hip/##'
} > "$D/attempt-a-errors.txt"
{ echo "# plain nvcc build of cft_fma.hip after C1: warnings by kind"; grep -h 'warning' $O/plain.log | sed -e 's/.*warning: //' -e 's/(.*//' | cut -c1-60 | sort | uniq -c | sort -rn | head -12
  echo "# errors: $(grep -c ' error' $O/plain.log)"; } > "$D/plain-build.txt"
bash "$here/hipcc_probe.sh" /opt/gpu-b $O/hipcc-probe 2>&1 | scrub > "$D/hipcc-probe.txt"
scrub < $O/gpu_run.log > "$D/gpu-run.txt"
{ for f in ~/gpu-b/debs/*.deb; do dpkg-deb -f "$f" Package Version Depends | tr '\n' ' '; echo; done; } | sed 's/ *$//' > "$D/debs.txt"
ls "$D"
