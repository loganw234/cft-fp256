# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The smallest run that can tell you where the kernel is stuck.

test_krnl is the real gate, but it takes minutes and reports nothing
until it finishes, which makes it useless as a diagnostic: a hang and a
slow simulation look identical from outside. This does the three things
in order and prints between them, so a failure names its own stage.

  1. does time advance at all, and does reset release
  2. does the AXI-Lite control path answer (MAGIC/VERSION)
  3. does ONE tiny run complete, with a beat count small enough that a
     wrong answer is readable rather than a wall of hex

Kept in the tree because "the engine hangs" is a question that will be
asked again, and answering it needed writing this once already.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)

from cft_golden import FP32, PREC_CODE, OP_ADD, RND_RNE, compute  # noqa: E402

CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
A_BASE, B_BASE, C_BASE, D_BASE = 0x00000, 0x40000, 0x80000, 0xC0000


@cocotb.test()
async def smoke(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())

    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
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

    # --- stage 1: does time move? -----------------------------------
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut._log.info("STAGE 1a: clock is running, reset asserted")
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 8)
    dut._log.info("STAGE 1b: reset released, time advancing")

    # --- stage 2: control path --------------------------------------
    magic = await with_timeout(axil.read_dword(MAGIC), 5, "us")
    dut._log.info(f"STAGE 2a: MAGIC = {magic:#010x}")
    assert magic == 0x43465430
    ver = await with_timeout(axil.read_dword(VERSION), 5, "us")
    dut._log.info(f"STAGE 2b: VERSION = {ver:#010x}")

    # --- stage 3: one tiny run --------------------------------------
    n, fmt = 8, FP32
    ebytes = fmt.width // 8
    one = (fmt.bias << fmt.man_w)                      # 1.0
    va = [one] * n
    vc = [one] * n
    ram_a.write(A_BASE, b"".join(v.to_bytes(ebytes, "little") for v in va))
    ram_a.write(C_BASE, b"".join(v.to_bytes(ebytes, "little") for v in vc))
    ram_a.write(D_BASE, b"\xAA" * (n * ebytes))

    await axil.write_dword(MODE, (PREC_CODE[fmt.name] << 8) | OP_ADD
                           | (RND_RNE << 12))
    for addr, val in ((NREG, n), (APTR, A_BASE), (BPTR, B_BASE),
                      (CPTR, C_BASE), (DPTR, D_BASE)):
        await axil.write_dword(addr, val & 0xFFFFFFFF)
        await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)
    dut._log.info("STAGE 3a: CSRs programmed, starting")

    await axil.write_dword(CTRL, 1)

    # Bounded wait, polling ap_done through the CSR exactly as the real
    # bench does. The point is that a hang reports as a hang rather than
    # as a test that never returns.
    for poll in range(500):
        await ClockCycles(dut.ap_clk, 10)
        status = await axil.read_dword(CTRL)
        if status & 0x2:                 # ap_done, clear-on-read
            break
        if poll % 100 == 99:
            dut._log.info(f"STAGE 3b: still running after {(poll + 1) * 10} cycles")
    else:
        raise AssertionError(
            "engine never asserted done in 5000 cycles - it is hung, and "
            "the [CFT-ENGS] AR lines above say how far the readers got")

    dut._log.info(f"STAGE 3c: done after ~{(poll + 1) * 10} cycles")
    _ = RisingEdge  # kept imported for the throughput test below
    got = ram_a.read(D_BASE, n * ebytes)
    want, _ = compute(fmt, OP_ADD, va[0], 0, vc[0], RND_RNE)
    first = int.from_bytes(got[:ebytes], "little")
    assert first == want, f"got {first:#x} want {want:#x}"
    dut._log.info("STAGE 3d: first element bit-exact")


@cocotb.test()
async def throughput(dut):
    """Measure cycles per beat, by DIFFERENCE so the fixed cost cancels.

    A single timed run measures the engine plus everything around it:
    CSR programming, the AXI-Lite poll granularity, pipeline fill and
    drain. Those are constant in n, so running two sizes and dividing
    the difference in cycles by the difference in beats leaves the
    steady-state cost and nothing else.

    That number is the whole point of giving each stream its own AXI
    master. The shared-port design cost 4 transfers per beat through a
    port that retires one per cycle and measured ~4.4 cycles/beat; the
    arithmetic pipe underneath has always accepted a beat every cycle.
    """
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 22)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 22, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 22, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 22, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 8)

    fmt = FP32
    ebytes = fmt.width // 8
    one = fmt.bias << fmt.man_w
    PERIOD_NS = 4

    async def timed_run(n):
        beats = (n * ebytes + 31) // 32
        payload = b"".join(one.to_bytes(ebytes, "little") for _ in range(n))
        ram_a.write(A_BASE, payload)
        ram_a.write(C_BASE, payload)
        await axil.write_dword(MODE, (PREC_CODE[fmt.name] << 8) | OP_ADD
                               | (RND_RNE << 12))
        for addr, val in ((NREG, n), (APTR, A_BASE), (BPTR, B_BASE),
                          (CPTR, C_BASE), (DPTR, D_BASE)):
            await axil.write_dword(addr, val & 0xFFFFFFFF)
            await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)
        t0 = cocotb.utils.get_sim_time("ns")
        await axil.write_dword(CTRL, 1)
        for _ in range(20000):
            await ClockCycles(dut.ap_clk, 4)
            if (await axil.read_dword(CTRL)) & 0x2:
                break
        else:
            raise AssertionError(f"n={n} never finished")
        t1 = cocotb.utils.get_sim_time("ns")
        cycles = (t1 - t0) / PERIOD_NS
        dut._log.info(f"THROUGHPUT n={n} beats={beats} cycles={cycles:.0f} "
                      f"({cycles / beats:.2f} cycles/beat, uncorrected)")
        return beats, cycles

    b1, c1 = await timed_run(512)      # 64 beats
    b2, c2 = await timed_run(4096)     # 512 beats

    per_beat = (c2 - c1) / (b2 - b1)
    dut._log.info(f"THROUGHPUT marginal cost = ({c2:.0f}-{c1:.0f}) / "
                  f"({b2}-{b1}) = {per_beat:.2f} cycles/beat")

    # The shared port could not do better than 4.0 by construction - it
    # needed four transfers per beat. Anything at or above that means
    # the split did not take effect, which is worth failing over rather
    # than noting.
    assert per_beat < 3.0, (
        f"{per_beat:.2f} cycles/beat - the per-stream masters are not "
        f"buying what they should; the shared port already did ~4.4 and "
        f"its floor was 4.0")
    dut._log.info("THROUGHPUT: below the shared port's structural floor of 4")
