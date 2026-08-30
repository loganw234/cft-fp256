#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Run host/tests/device-test against an artifact, in emulation or on a
# card.
#
#   bash hw/run-device-test.sh <artifact.xclbin> [-n N] [-f fp32] [-q]
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

ART=${1:?usage: run-device-test.sh <artifact.xclbin> [device-test args...]}
shift

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

    # Reap orphaned simulators before starting.
    #
    # An emulation run that is interrupted leaves its xsimk alive,
    # holding a socket under /tmp/$USER and a directory under .run.
    # The next run then talks to, or is confused by, the wreckage of
    # the last one - which presents as an emulation that hangs at
    # startup, or as intermittent failure that looks like a design
    # bug. This project has already lost an evening to it once,
    # diagnosing 53 stale run directories and 55 stale sockets as
    # "flakiness".
    #
    # Nothing here should be running if the previous run finished, so
    # killing unconditionally is safe - and if two emulations are
    # wanted at once, they need separate machines anyway.
    if pgrep -f 'xsimk|xsim ' >/dev/null 2>&1; then
      echo "   reaping orphaned simulators from an earlier run"
      pkill -f xsimk 2>/dev/null || true
      pkill -f 'bin/xsim ' 2>/dev/null || true
      sleep 2
      pkill -9 -f xsimk 2>/dev/null || true
    fi
    # Every socket, not just the ones that happen to start with
    # "device".
    #
    # This glob was `device*`, and the emulation shim creates TWO
    # sockets per run: device0_0_<pid>, which it matched, and
    # D2X_unix_sock_device0_0_<pid>, which it did not. So half the
    # litter was swept and half accumulated - 26 of them had built up
    # since the previous afternoon, and a run then died at startup with
    # a protobuf parse failure on xclCopyBufferHost2Device_response
    # followed by SIMULATION EXITED. That reads like a broken artifact
    # or a version-skewed toolchain, and it cost four runs and a
    # three-way bisection before the directory listing was checked.
    #
    # This is the SECOND time stale emulation state has presented as
    # something else here - the first was 53 orphaned .run directories
    # diagnosed as flakiness. The lesson both times is the same, so it
    # is written down rather than re-learned: clear the whole
    # directory, because a pattern that has to be kept in step with a
    # vendor's naming will drift out of step silently.
    rm -rf "/tmp/${USER:-root}"/* 2>/dev/null || true

    # Keep ONE generation of the previous run's simulator directory.
    #
    # These have to be cleared - that is the whole point of the reap -
    # but deleting them outright destroys the only record of why the
    # last run failed. The simulator's own simulate.log is where a
    # crash says what happened; the host just sees a dead socket. On
    # 2026-08-30 four consecutive runs failed and each one erased its
    # predecessor's log at startup, so the evidence was never available
    # at the moment it was wanted.
    #
    # So the outgoing directory is renamed rather than removed, one
    # generation deep. Bounded, and the post-mortem survives exactly
    # long enough to be read.
    for d in "$ROOT" "$ARTDIR"; do
      [ -d "$d/.run" ] || continue
      rm -rf "$d/.run.prev" 2>/dev/null || true
      mv "$d/.run" "$d/.run.prev" 2>/dev/null || rm -rf "$d/.run"
    done
    find "$ROOT" "$ARTDIR" -maxdepth 2 -name '.run' -type d \
         -exec rm -rf {} + 2>/dev/null || true
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
exec "$BIN" "$ART" "$@"
