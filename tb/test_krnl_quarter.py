# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The quarter-tile: a 64-bit beat carrying fp32 and fp64 only.

Same golden model, same CSR contract, a quarter of the geometry. This
is what proves BEAT_BITS is a working parameter rather than a declared
one - and it is the configuration an Alchitry Au conformance node and
a deposition-buffer-heavy chiplet both want.

Two things it checks that the full-tile bench structurally cannot:

* **CAPS tells the truth about a trimmed build.** The precision mask
  must report fp32 and fp64 only. A host that trusted the full tile's
  0xF here would issue fp256 and get a deterministic but meaningless
  all-zero beat, which is exactly why capability discovery exists.
* **The beat arithmetic follows the parameter.** Elements per beat,
  the AXI transfer size, and the byte address step are all derived
  from BEAT_BITS; if any of them stayed at 256 the run would read the
  wrong addresses and mismatch immediately.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)

from cft_golden import (  # noqa: E402
    FP32, FP64, OP_FMA, OP_ADD, OP_MUL, OP_MIN, OP_ISHR, OP_SELECT,
    RND_RDN, RND_RNE, RND_RUP,
)

from test_krnl import (run_op, check_op_groups,  # noqa: E402
                       CAPS, MAGIC, VERSION, CTRL)
from test_krnl_reduce import run_sum  # noqa: E402


@cocotb.test()
async def quarter_tile_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    # Four masters, one shared memory - see test_krnl for why the
    # sharing is what makes this bench able to fail.
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)
    ram = ram_a

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000500

    caps = await axil.read_dword(CAPS)
    assert (caps & 0xF) == 0b0011, (
        f"quarter tile must advertise fp32+fp64 only, got {caps & 0xF:#06b}")
    # Trimming rungs must not trim opcode groups - every group still
    # works on the formats that remain, reductions included.
    check_op_groups(caps)

    status = await axil.read_dword(CTRL)
    assert status & 0x4, "kernel must come up idle"

    # Two fp32 lanes per beat now, and one fp64. Sizes chosen to cross
    # several bursts and to leave a ragged tail.
    await run_op(dut, axil, ram, FP32, OP_FMA, 64, seed=301)
    await run_op(dut, axil, ram, FP32, OP_ADD, 34, seed=302)   # 17 beats
    await run_op(dut, axil, ram, FP32, OP_MUL, 2, seed=303)    # single beat
    await run_op(dut, axil, ram, FP64, OP_FMA, 24, seed=304)
    await run_op(dut, axil, ram, FP64, OP_ADD, 1, seed=305)    # single beat

    # the non-arithmetic groups still work at the narrow geometry
    await run_op(dut, axil, ram, FP32, OP_MIN, 32, seed=306)
    await run_op(dut, axil, ram, FP32, OP_ISHR, 32, seed=307)
    await run_op(dut, axil, ram, FP64, OP_SELECT, 8, seed=308)

    # and so do the rounding attributes
    await run_op(dut, axil, ram, FP32, OP_FMA, 32, seed=309, rnd=RND_RDN)
    await run_op(dut, axil, ram, FP64, OP_FMA, 16, seed=310, rnd=RND_RUP)

    # Reductions, which this bench asserted CAPS for and never ran.
    #
    # That gap had already cost something. The serializer's
    # elements-per-beat was a hardcoded 8/4/2/1 while the beat COUNT
    # was derived from LANE_SH, and the two only agree at
    # BEAT_BITS=256. Here a beat holds 2 fp32, not 8, so the
    # serializer walked four elements off the end of every beat and
    # the remaining-element count underflowed on the second beat -
    # twelve "elements" folded for an n of four. Nothing could see it,
    # because the only bench at this geometry ran no reductions and
    # the only reduction bench ran at 256.
    #
    # The sizes are chosen against that: n=4 is the exact case above,
    # and 1, 3 and 5 are partial final beats at 2 elements per beat.
    # fp64 is 1 element per beat here, so its beats are all full and
    # it isolates the count rather than the serializer.
    await run_sum(dut, axil, ram, FP32, 1, RND_RNE, seed=320)
    await run_sum(dut, axil, ram, FP32, 2, RND_RNE, seed=321)
    await run_sum(dut, axil, ram, FP32, 3, RND_RNE, seed=322)
    await run_sum(dut, axil, ram, FP32, 4, RND_RNE, seed=323)
    await run_sum(dut, axil, ram, FP32, 5, RND_RNE, seed=324)
    await run_sum(dut, axil, ram, FP32, 33, RND_RNE, seed=325)
    await run_sum(dut, axil, ram, FP64, 1, RND_RNE, seed=326)
    await run_sum(dut, axil, ram, FP64, 7, RND_RNE, seed=327)
    await run_sum(dut, axil, ram, FP32, 9, RND_RDN, seed=328)

    dut._log.info("quarter tile (BEAT_BITS=64, fp32+fp64): bit-exact "
                  "against the same golden model as the full tile, "
                  "elementwise and reductions")
