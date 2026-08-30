#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Run host/tests/device-test against an artifact, in emulation or on a
# card.
#
#   bash hw/run-device-test.sh <artifact.xclbin> [elements]
#
# Emulation is selected by the artifact's name: an xclbin built for
# hw_emu needs XCL_EMULATION_MODE set, needs EMCONFIG_PATH pointing at
# the emconfig.json that was generated beside it, and needs the full
# Vitis environment rather than just XRT - the emulation model shells
# out to tools under $XILINX_VITIS and fails late and unhelpfully
# without it:
#
#   ERROR: [HW-EMU 27] $XILINX_VITIS variable is not SET
#
# A hardware xclbin needs none of that, so the same command line works
# on card day with a different file.
set -euo pipefail

ART=${1:?usage: run-device-test.sh <artifact.xclbin> [elements]}
N=${2:-64}

[ -f "$ART" ] || { echo "no such artifact: $ART" >&2; exit 1; }
ART=$(readlink -f "$ART")
ARTDIR=$(dirname "$ART")
ROOT=$(cd "$(dirname "$0")/.." && pwd)

for r in /opt/xilinx/xrt /usr/local/xrt; do
  [ -f "$r/setup.sh" ] && { set +u; source "$r/setup.sh" >/dev/null; set -u; break; }
done
command -v xbutil >/dev/null || echo "warning: XRT not found on PATH" >&2

case "$(basename "$ART")" in
  *hw_emu*)
    for v in /data/Xilinx/Vitis/2022.2 /opt/Xilinx/Vitis/2022.2 \
             /tools/Xilinx/Vitis/2022.2; do
      if [ -f "$v/settings64.sh" ]; then
        set +u; source "$v/settings64.sh" >/dev/null; set -u
        break
      fi
    done
    [ -n "${XILINX_VITIS:-}" ] || {
      echo "ERROR: emulation needs the Vitis environment, not just XRT," >&2
      echo "       and no settings64.sh was found" >&2; exit 1; }
    [ -f "$ARTDIR/emconfig.json" ] || {
      echo "ERROR: no emconfig.json beside $ART" >&2
      echo "       (rebuild-2022.sh writes one for a hw_emu target)" >&2
      exit 1; }
    export XCL_EMULATION_MODE=hw_emu
    export EMCONFIG_PATH="$ARTDIR"
    echo "== emulation: XCL_EMULATION_MODE=hw_emu EMCONFIG_PATH=$ARTDIR"
    ;;
  *)
    echo "== hardware"
    ;;
esac

BIN="$ROOT/host/device-test"
[ -x "$BIN" ] || { echo "build it first: make -C host XRT=1 device-test" >&2
                   exit 1; }

# emconfig.json is found relative to the working directory by some XRT
# versions and by EMCONFIG_PATH in others, so satisfy both.
cd "$ARTDIR"
exec "$BIN" "$ART" "$N"
