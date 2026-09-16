# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lane-mask kernel bench at the card's memory latency.

    make -f cocotb.mk SIM=verilator TOPLEVEL=cft_krnl \\
        MODULE=probe_mask_latency SIM_BUILD=sim_build/probe_mask_latency
    (with CFT_RD_LATENCY / CFT_WR_LATENCY in the environment)

On 2026-09-15 the round-2 image wrote every masked lane on the U50
while `krnl_lane_mask` passed under both simulators, and a register
trace proved the host had sent the bit, the pointer and the bytes. The
one thing the bench's memory model lacks is latency: cocotbext-axi
answers in zero cycles, and `RD_LATENCY=200 WR_LATENCY=200` on `make
krnlseq` installs nothing because only the cycles bench calls
tb/busfx.py. This module runs the SAME test with busfx's pipelined
latency installed on the four RAMs, by wrapping the classes the bench
constructs them from - so a pass or a fail here is `krnl_lane_mask` at
the card's round trip and nothing else.
"""
import os
import sys
from pathlib import Path

import cocotb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import busfx  # noqa: E402
import test_krnl_seq as T  # noqa: E402

RD, WR = busfx.env_latency()


class _LatRead(T.AxiRamRead):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        busfx.latency(self, clk=a[1], read=RD, write=WR)


class _LatWrite(T.AxiRamWrite):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        busfx.latency(self, clk=a[1], read=RD, write=WR)


@cocotb.test()
async def lane_mask_at_latency(dut):
    """krnl_lane_mask with the memory answering `CFT_RD_LATENCY` cycles
    late on every read beat and `CFT_WR_LATENCY` on every write
    response (0 and 0 install nothing, and this is then krnl_lane_mask
    itself)."""
    dut._log.info(f"probe: read latency {RD}, write latency {WR} "
                  f"(CFT_RD_LATENCY / CFT_WR_LATENCY)")
    T.AxiRamRead = _LatRead
    T.AxiRamWrite = _LatWrite
    await T.krnl_lane_mask(dut)


@cocotb.test()
async def sequencer_at_latency(dut):
    """The whole krnl_sequencer bench at the same latency: the gather
    states, the header refusals, the dense programs - everything the
    card runs - so a latency-shaped defect anywhere in the sequencer's
    reads shows beside the mask's."""
    T.AxiRamRead = _LatRead
    T.AxiRamWrite = _LatWrite
    await T.krnl_sequencer(dut)
