#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The RX 7600 runbook (gfx1102; the RX 7600 machine, hostname nvidia-box,
# ROCm 10.1 at /opt/rocm). Work only in ~/gpu-a there; nothing is installed.
#
# From the desktop, with the corpora made by gen_corpus.py in CORPUS:
#   tar czf gpu-a-tree.tgz docs/studies/gpu-a host/src/bigint.[ch] \
#       host/src/softfloat.[ch] host/src/sha256.[ch] host/src/backend.h \
#       host/include/cft_config.h host/include/cft.h
#   scp gpu-a-tree.tgz CORPUS/*.bin  <box>:gpu-a/          (tree, corpus)
# On the box (ssh -n, one build or run at a time, amd-smi checked first):
#   cd ~/gpu-a && mkdir -p tree corpus && tar xzf gpu-a-tree.tgz -C tree
#   mv *.bin corpus/
#   bash tree/docs/studies/gpu-a/run_rx7600.sh ~/gpu-a/corpus ~/gpu-a/work
#   bash tree/docs/studies/gpu-a/bench.sh ~/gpu-a/work/build/amd-gfx1102/cft_fma \
#       gfx1102 ~/gpu-a/corpus
#   FORMATS=fp256 bash tree/docs/studies/gpu-a/bench.sh \
#       ~/gpu-a/work/build/amd-gfx1102/cft_fma gfx1102-fixed ~/gpu-a/corpus --kernel fixed
#   bash tree/docs/studies/gpu-a/hazards.sh amd ~/gpu-a/corpus ~/gpu-a/work
#
# It builds for gfx1102 and runs everything (run_amd.sh), and builds for
# gfx942 too, without running it: the MI300X's build, shown here without
# the card. The card is shared with whatever else holds it (on 2026-11-10,
# an idle resident llama-server with 6.1 GB of its 8 GB), which the study
# records beside every rate.
exec bash "$(cd "$(dirname "$0")" && pwd)/run_amd.sh" "${1:?CORPUS_DIR}" "${2:?WORK_DIR}" \
    gfx1102 gfx942
