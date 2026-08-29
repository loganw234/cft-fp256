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
#   CFT_SMOKE_DEEP=1 bash hw/emu_smoke.sh   # + every op and multi-burst
#                                             sizes (slow under hw_emu,
#                                             seconds on a card)

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
  fmt=$1; n=$2; op=$3; rnd=${4:-rne}
  echo "=== $fmt $op $rnd n=$n"
  out=$(python3 host/examples/vector_fma.py "$XCLBIN" --format "$fmt" \
        --op "$op" --n "$n" --rounding "$rnd" 2>&1)
  rc=$?
  echo "$out" | grep -E "PASS|FAIL|MISMATCH|Traceback|rror" | head -4
  if echo "$out" | grep -q "^PASS"; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    # No PASS/FAIL line at all means the run was lost in the emulator
    # handoff (python exits 0 with empty output), which happens
    # intermittently under hw_emu - roughly one case in ten, and the
    # same case has passed on every rerun tried. Numerical failures
    # always print MISMATCH/FAIL above, so a silent exit is an
    # infrastructure fault, never a result.
    echo "    (no verdict line; exit code $rc - rerun this case alone before believing it)"
  fi
}

run_one fp32  32 fma
run_one fp64  16 fma
run_one fp128  8 fma
run_one fp256  4 fma

# Deep pass: the other three ops (proving the steering muxes on real
# hardware, not just in cocotb) and sizes past one burst - 296 fp32
# elements is 37 beats, so the streaming engine must issue multiple
# bursts per stream and handle a ragged final one.
if [ "${CFT_SMOKE_DEEP:-0}" != "0" ]; then
  run_one fp32  32 add
  run_one fp32  32 sub
  run_one fp32  32 mul
  run_one fp32 296 fma
  run_one fp64 128 mul
  run_one fp256 40 fma
  # every rounding attribute, through the MODE field on real silicon
  for r in rtz rdn rup rmm; do
    run_one fp32 32 fma "$r"
  done
  run_one fp256 4 fma rdn
fi

echo "=== smoke: $pass pass, $fail fail"
[ "$fail" -eq 0 ]
