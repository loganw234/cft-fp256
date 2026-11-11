#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# GPU-B step 4(b): do the sources' own CPack definitions still produce the
# NVIDIA packages (hipcc-nvidia from amd/hipcc, hip-runtime-nvidia and
# hip-dev from clr/hipamd)?  Run after build_hip_nv.sh and build_hipcc.sh;
# packages land in $HOME/gpu-b/debs; nothing is installed.
mkdir -p ~/gpu-b/debs; cd ~/gpu-b/debs
echo "== hipcc: component NVIDIA"
( cd ~/gpu-b/build-hipcc && cpack -G DEB -D CPACK_COMPONENTS_ALL=NVIDIA -D CPACK_PACKAGE_DIRECTORY=$HOME/gpu-b/debs > ~/gpu-b/debs/cpack-hipcc.log 2>&1; echo "cpack rc=$?"; tail -4 ~/gpu-b/debs/cpack-hipcc.log )
echo "== clr/hip: components"
( cd ~/gpu-b/build-hip && cpack -G DEB -D CPACK_PACKAGE_DIRECTORY=$HOME/gpu-b/debs > ~/gpu-b/debs/cpack-hip.log 2>&1; echo "cpack rc=$?"; tail -6 ~/gpu-b/debs/cpack-hip.log )
ls -la ~/gpu-b/debs
for f in ~/gpu-b/debs/*.deb; do [ -e "$f" ] && { echo "-- $f"; dpkg-deb -f "$f" Package Version Depends Provides | cut -c1-200; }; done
