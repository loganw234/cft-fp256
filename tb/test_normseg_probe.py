# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Diagnostic probe for tb_normseg. Not part of `make sim`.

test_normseg reported a mismatch whose printed operand did not match
its printed result, which means at least one of two things is wrong and
inspection cannot separate them: the two halves may have different
latencies, or the shared ladder may not be honouring `mode`. This
drives ONE known vector into a quiet pipeline and prints both outputs
on every subsequent cycle, which answers both at once.

    make normprobe
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

SLOTW = 90
WT = 8 * SLOTW
NW = [78, 165, 345, 717]
LN = [8, 4, 2, 1]


def pack(values, width):
    v = 0
    for i, x in enumerate(values):
        v |= (x & ((1 << width) - 1)) << (i * width)
    return v


async def quiet(dut, cycles=6):
    dut.din.value = 0
    dut.csh_v.value = 0
    dut.fsh_v.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)


@cocotb.test()
async def probe(dut):
    cocotb.start_soon(Clock(dut.clk, 2, units="ns").start())

    for mode in (0, 1):
        pitch = SLOTW << mode
        dut.mode.value = mode
        await quiet(dut)

        # One marker bit per lane, at a position that must cross the
        # 90-bit slot boundary when shifted: bit 80 of the lane, shifted
        # left by 20. Under mode 0 that is a boundary the shifter must
        # BLOCK; under mode 1 the same boundary is interior to the lane
        # and it must PASS. One vector distinguishes them.
        din = 0
        for lane in range(LN[mode]):
            din |= (1 << 80) << (lane * pitch)
        shift = 20
        csh = [shift >> 6] * 8
        fsh = [shift & 63] * 8

        dut.din.value = din
        dut.csh_v.value = pack(csh, 4)
        dut.fsh_v.value = pack(fsh, 6)
        await RisingEdge(dut.clk)
        # Everything after this cycle is quiet, so any nonzero output
        # from here on belongs to this one vector and the cycle it
        # appears on IS the latency.
        dut.din.value = 0
        dut.csh_v.value = 0
        dut.fsh_v.value = 0

        dut._log.info("mode %d: din bit 80 per lane, shift %d, pitch %d",
                      mode, shift, pitch)
        for cyc in range(1, 6):
            await RisingEdge(dut.clk)
            shared = int(dut.dout.value)
            ref = int(getattr(dut, f"r{mode}").value)
            dut._log.info(
                "  cycle %d  shared=%s  ref=%s",
                cyc,
                sorted(i for i in range(WT) if (shared >> i) & 1) or "0",
                sorted(i for i in range(WT) if (ref >> i) & 1) or "0",
            )
