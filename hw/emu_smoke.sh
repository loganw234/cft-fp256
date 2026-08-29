#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Emulation smoke: one small vector op per advertised precision,
# through the real XRT stack (pyxrt) against the golden model.
#
#   XCL_EMULATION_MODE=hw_emu (default here) with build/emconfig.json
#   present, or CFT_SMOKE_MODE=hw against a live card - the same
#   script is the card-day first-light check. hw_emu needs BOTH
#   environments sourced (the device model ships with Vitis):
#     source <vitis>/settings64.sh && source /opt/xilinx/xrt/setup.sh
#
#   bash hw/emu_smoke.sh [xclbin]           # default build/cft_hw_emu.xclbin
#   CFT_SMOKE_MODE=hw bash hw/emu_smoke.sh build/cft_hw.xclbin

set -u
cd "$(dirname "$0")/.."

XCLBIN=${1:-build/cft_hw_emu.xclbin}
MODE=${CFT_SMOKE_MODE:-hw_emu}
if [ "$MODE" = "hw_emu" ]; then
  export XCL_EMULATION_MODE=hw_emu
  export EMCONFIG_PATH=${EMCONFIG_PATH:-$PWD/build}
else
  unset XCL_EMULATION_MODE
fi

pass=0
fail=0
run_one() {
  fmt=$1; n=$2; op=$3
  echo "=== $fmt $op n=$n"
  out=$(python3 host/examples/vector_fma.py "$XCLBIN" --format "$fmt" --op "$op" --n "$n" 2>&1)
  echo "$out" | grep -E "PASS|FAIL|MISMATCH|Traceback|rror" | head -4
  if echo "$out" | grep -q "^PASS"; then pass=$((pass+1)); else fail=$((fail+1)); fi
}

run_one fp32  32 fma
run_one fp64  16 fma
run_one fp128  8 fma
run_one fp256  4 fma

echo "=== smoke: $pass pass, $fail fail"
[ "$fail" -eq 0 ]
