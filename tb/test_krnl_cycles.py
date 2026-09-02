# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Cycle counts for the kernel, measured on the RTL itself.

This is the honest way to get a throughput PREDICTION before there is a
card. hw_emu was the obvious place to look for it and turned out to be
the wrong one twice over: its wall clock measures the simulator, and
XRT's timeline trace came back as two empty CSVs under emulation
(2026-09-01). But a cycle count does not need the XRT stack at all - it
needs the RTL and a clock - and this bench counts `run_busy` high to
low on the same `cft_krnl` the bitstream carries.

What it produces is cycles per 256-bit beat at each rung. Multiply by
the shipping period and you have a rate; the rate is a PREDICTION and is
labelled one everywhere it appears, because a real number needs the card
(docs/CARDDAY.md gate 6, docs/BENCHMARKS.md's measured/projected line).

Deliberately not asserted tightly. A cycles-per-beat regression is worth
SEEING rather than failing on, since it moves for legitimate reasons -
burst length, FIFO depth, the reduction's tree walk - and a bench that
fails whenever performance changes is a bench people delete. The only
assertions here are that the run completes and that the count is
physically possible.
"""

import math
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, PREC_CODE,
    OP_FMA, OP_SUM, OP_NAMES, RND_RNE,
)

CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50

A_BASE, B_BASE, C_BASE, D_BASE = 0x00000, 0x40000, 0x80000, 0xC0000

BEAT_BITS = 256
# The clock the card-day pair is built at. Only used to turn cycles into
# a labelled prediction; nothing here depends on it.
SHIP_HZ = 135_000_000

FORMATS = (FP32, FP64, FP128, FP256)


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


def normal_stream(fmt, n, rng):
    """Ordinary normal numbers, exponent near the bias - the same
    fast-path population host/tools/cft_bench.c times, and for the same
    reason: a stream of NaNs would measure the special-case path."""
    out = []
    for _ in range(n):
        frac = rng.getrandbits(fmt.man_w)
        exp = fmt.bias + rng.randint(-8, 8)
        out.append((rng.getrandbits(1) << (fmt.width - 1))
                   | (exp << fmt.man_w) | frac)
    return out


async def time_run(dut, axil, ram, fmt, op, n, seed):
    """Stage a run, start it, and count ap_clk edges while run_busy is
    high. Returns (cycles, beats)."""
    ebytes = fmt.width // 8
    rng = random.Random(seed)
    lanes = BEAT_BITS // fmt.width
    beats = math.ceil(n / lanes)

    for base in (A_BASE, B_BASE, C_BASE):
        vals = normal_stream(fmt, n, rng)
        ram.write(base, b"".join(v.to_bytes(ebytes, "little") for v in vals))
    ram.write(D_BASE, b"\x00" * (n * ebytes + BEAT_BITS // 8))

    await axil.write_dword(MODE, op | (PREC_CODE[fmt.name] << 8)
                           | (RND_RNE << 12))
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)

    # busy rises within a few cycles of the accepted start
    for _ in range(4000):
        await RisingEdge(dut.ap_clk)
        if int(dut.run_busy.value):
            break
    else:
        raise AssertionError(f"{fmt.name} {OP_NAMES[op]}: never went busy")

    cycles = 1
    while int(dut.run_busy.value):
        await RisingEdge(dut.ap_clk)
        cycles += 1
        assert cycles < 4_000_000, \
            f"{fmt.name} {OP_NAMES[op]}: still busy after {cycles} cycles"

    # drain the done latch so the next run starts clean
    for _ in range(400):
        if await axil.read_dword(CTRL) & 0x2:
            break
        await ClockCycles(dut.ap_clk, 4)
    assert await axil.read_dword(STATUS) == 0, \
        f"{fmt.name} {OP_NAMES[op]}: bus faults during the timed run"
    return cycles, beats


@cocotb.test()
async def kernel_cycles_per_beat(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 20, mem=ram_a.mem)
    ram = ram_a
    assert ram_b.mem is ram_a.mem and ram_c.mem is ram_a.mem \
        and ram_d.mem is ram_a.mem

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    assert await axil.read_dword(MAGIC) == 0x43465430

    # TWO sizes per rung, so the fixed cost separates from the per-beat
    # one. A single size cannot: at 128 beats every rung reported the
    # same 196 cycles, which looks like 1.53 cycles/beat and is really
    # ~68 cycles of fill/drain plus about one cycle a beat.
    SMALL, LARGE = 64, 512
    rows = []
    for fmt in FORMATS:
        lanes = BEAT_BITS // fmt.width
        c_s, b_s = await time_run(dut, axil, ram, fmt, OP_FMA,
                                  SMALL * lanes, 0x5EED)
        c_l, b_l = await time_run(dut, axil, ram, fmt, OP_FMA,
                                  LARGE * lanes, 0x5EED)
        slope = (c_l - c_s) / (b_l - b_s)
        fixed = c_s - slope * b_s
        rows.append((fmt.name, "fma", lanes, c_s, c_l, slope, fixed,
                     lanes * SHIP_HZ / slope))

    # The reduction is a different shape - it walks a tree whose carries
    # serialise - so it gets the same two-point treatment rather than an
    # assumed rate.
    c_s, b_s = await time_run(dut, axil, ram, FP32, OP_SUM, SMALL * 8, 0x5EED)
    c_l, b_l = await time_run(dut, axil, ram, FP32, OP_SUM, LARGE * 8, 0x5EED)
    slope = (c_l - c_s) / (b_l - b_s)
    fixed = c_s - slope * b_s
    rows.append(("fp32", "sum", 8, c_s, c_l, slope, fixed,
                 8 * SHIP_HZ / slope))

    dut._log.info(f"cycles on cft_krnl: {SMALL} and {LARGE} beats per rung, "
                  f"slope = steady-state cost of one 256-bit beat")
    dut._log.info(f"  {'rung':<6} {'op':<4} {'cyc@' + str(SMALL):>8} "
                  f"{'cyc@' + str(LARGE):>9} {'cyc/beat':>9} {'fixed':>7} "
                  f"{'pred @135MHz':>14}")
    for name, op, lanes, c_s, c_l, slope, fixed, rate in rows:
        dut._log.info(f"  {name:<6} {op:<4} {c_s:>8} {c_l:>9} {slope:>9.3f} "
                      f"{fixed:>7.0f} {rate/1e6:>11.1f} Me/s")
    dut._log.info("cyc/beat is MARGINAL (the slope); `fixed` is the fill, "
                  "burst setup and drain a run pays once - and is why a "
                  "short program is dominated by overhead, which is the "
                  "case docs/SEQUENCER.md argues from")
    dut._log.info("the rate column is a PREDICTION (cycles x period), not "
                  "a measurement - see docs/BENCHMARKS.md")

    # Physically possible, and nothing more: the datapath cannot retire a
    # beat faster than one cycle, and the fixed cost cannot be negative.
    for name, op, lanes, c_s, c_l, slope, fixed, rate in rows:
        assert slope >= 0.99, \
            f"{name} {op}: {slope:.3f} marginal cycles/beat is below one " \
            "beat per cycle, which the datapath cannot do"
        assert slope < 2000.0, f"{name} {op}: {slope:.1f} cycles/beat"
        assert fixed > -1.0, f"{name} {op}: negative fixed cost {fixed:.0f}"
