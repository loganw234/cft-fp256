# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Shared normaliser against private normalisers: identical bits or nothing.

tb_normseg already proves the segmented ladder shifts correctly. That is
not the same as proving a LANE is unchanged by taking its normalised
significand from outside, because the shifter is only one stage of
fifteen, and the contract lives in the rounding that follows it.

So this compares the two arrangements directly, on the same cycle, with
the same operands: eight fp32 lanes (plus four fp64, two fp128, one
fp256) each built twice, once with EXT_NORM=0 and its own two shifters
and once with EXT_NORM=1 fed by a single cft_normseg. Every result and
every flag word must match exactly.

This is the tb_mulshare argument, and deliberately the same shape,
because the failure modes it covers are the ones tb_normseg cannot see:

  * the value handed out or taken back a cycle early or late. The pipe
    registers s11_fine in S11 and reads it in S12, so the distance
    travels with its operand; a supplier two cycles deep lines up only
    if the lane presents its value in the right cycle.
  * the wrong half of the distance - csh counts 64-bit granules and fsh
    is the 0..63 remainder, and swapping them is silent at shift 0.
  * a lane reading its neighbour's slice of the shared output. Lane l
    sits at l*(90<<mode), which is NOT l*NW, and the two differ at
    fp64 and fp128 where the padding is widest.

Mode is held for a whole burst and the pipe is drained between bursts.
That is not a convenience: the pipeline is fifteen deep and prec_r
cannot move while anything is in flight, so a mid-flight mode change is
not a case the hardware can present.

    CFT_BEATS   beats per (format, attribute) burst (default 60)
    CFT_SEED    vector seed (default 5)
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FP32, FP64, FP128, FP256, RND_MODES, vectors  # noqa: E402

LATENCY = 15

FORMATS = [
    (FP32,  0, 8),
    (FP64,  1, 4),
    (FP128, 2, 2),
    (FP256, 3, 1),
]


def gen_beat(fmt, lanes, rng):
    """One 256-bit beat of operands for `lanes` elements of `fmt`."""
    pool = vectors.interesting_operands(fmt)
    beat = 0
    for i in range(lanes):
        if rng.random() < 0.45:
            v = pool[rng.randrange(len(pool))]
        else:
            v = rng.getrandbits(fmt.width)
        beat |= v << (i * fmt.width)
    return beat


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.rst_n.value = 0
    dut.in_valid.value = 0
    dut.mode.value = 0
    dut.rnd.value = 0
    dut.a_beat.value = 0
    dut.b_beat.value = 0
    dut.c_beat.value = 0
    await ClockCycles(dut.clk, 6)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)


async def compare_stream(dut, fmt, code, lanes, rnd, n, rng, label):
    """Push n beats back to back and compare both halves as they emerge."""
    sent = []
    mismatches = []

    async def collect():
        seen = 0
        for _ in range(n + LATENCY + 8):
            await FallingEdge(dut.clk)
            if dut.out_valid.value == 1:
                di = int(dut.d_int.value)
                ds = int(dut.d_shr.value)
                fi = int(dut.f_int.value)
                fs = int(dut.f_shr.value)
                if di != ds or fi != fs:
                    mismatches.append((seen, di, ds, fi, fs))
                seen += 1
        return seen

    task = cocotb.start_soon(collect())

    dut.mode.value = code
    dut.rnd.value = rnd
    for _ in range(n):
        a = gen_beat(fmt, lanes, rng)
        b = gen_beat(fmt, lanes, rng)
        c = gen_beat(fmt, lanes, rng)
        sent.append((a, b, c))
        dut.a_beat.value = a
        dut.b_beat.value = b
        dut.c_beat.value = c
        dut.in_valid.value = 1
        await RisingEdge(dut.clk)
    dut.in_valid.value = 0
    seen = await task

    if mismatches:
        i, di, ds, fi, fs = mismatches[0]
        a, b, c = sent[i] if i < len(sent) else (0, 0, 0)
        w = fmt.width
        raise AssertionError(
            f"{label}: shared normaliser disagrees with private ones on "
            f"beat {i} of {n} ({len(mismatches)} mismatches)\n"
            f"  a     = {a:#0{w // 4 + 2}x}\n"
            f"  b     = {b:#0{w // 4 + 2}x}\n"
            f"  c     = {c:#0{w // 4 + 2}x}\n"
            f"  d_int = {di:#066x}  flags {fi:#07b}\n"
            f"  d_shr = {ds:#066x}  flags {fs:#07b}")

    assert seen >= n, (
        f"{label}: only {seen} results for {n} beats - the shared "
        f"configuration dropped work")
    return seen


@cocotb.test()
async def equivalent_per_format(dut):
    """Every format, every rounding attribute, streamed back to back.

    Back to back is the point. A supplier that latched the wrong cycle's
    distance is correct on isolated operations and wrong on a stream,
    and a stream is the only thing the engine issues.
    """
    await reset(dut)
    beats = int(os.environ.get("CFT_BEATS", "60"))
    rng = random.Random(int(os.environ.get("CFT_SEED", "5")))
    total = 0

    for fmt, code, lanes in FORMATS:
        for rnd in RND_MODES:
            total += await compare_stream(
                dut, fmt, code, lanes, rnd, beats, rng,
                f"{fmt.name} rnd={rnd}")
            # Drain before changing anything: fifteen stages deep, and
            # prec_r cannot move mid-flight in the engine either.
            await ClockCycles(dut.clk, LATENCY + 4)

    dut._log.info("normshare: %d beats compared across %d format/attribute "
                  "combinations", total, len(FORMATS) * len(RND_MODES))


@cocotb.test()
async def cancellation_and_subnormals(dut):
    """The operands that make the normalise distance large and irregular.

    A shifter is exercised by what it has to shift. Near-total
    cancellation produces the long left shifts - up to NW-1 - and
    subnormal results produce the empty-window case where the lane must
    drive zero rather than leave the distance undefined, because that
    distance now reaches a ladder other lanes are sharing.
    """
    await reset(dut)
    rng = random.Random(int(os.environ.get("CFT_SEED", "5")) + 1)
    beats = int(os.environ.get("CFT_BEATS", "60"))

    for fmt, code, lanes in FORMATS:
        pool = vectors.interesting_operands(fmt)
        sent, mismatches = [], []

        async def collect(n):
            seen = 0
            for _ in range(n + LATENCY + 8):
                await FallingEdge(dut.clk)
                if dut.out_valid.value == 1:
                    di, ds = int(dut.d_int.value), int(dut.d_shr.value)
                    fi, fs = int(dut.f_int.value), int(dut.f_shr.value)
                    if di != ds or fi != fs:
                        mismatches.append((seen, di, ds, fi, fs))
                    seen += 1
            return seen

        dut.mode.value = code
        dut.rnd.value = 0
        task = cocotb.start_soon(collect(beats))

        for _ in range(beats):
            a = b = c = 0
            for i in range(lanes):
                # x*y - (x*y +/- 1ulp): the product very nearly cancels
                # the addend, so the result needs almost the whole
                # window shifted left.
                x = pool[rng.randrange(len(pool))]
                y = pool[rng.randrange(len(pool))]
                z = (x ^ rng.randrange(4)) | fmt.sign_mask
                a |= x << (i * fmt.width)
                b |= y << (i * fmt.width)
                c |= z << (i * fmt.width)
            sent.append((a, b, c))
            dut.a_beat.value = a
            dut.b_beat.value = b
            dut.c_beat.value = c
            dut.in_valid.value = 1
            await RisingEdge(dut.clk)
        dut.in_valid.value = 0
        await task

        if mismatches:
            i, di, ds, fi, fs = mismatches[0]
            a, b, c = sent[i]
            raise AssertionError(
                f"{fmt.name} cancellation: mismatch on beat {i}\n"
                f"  a     = {a:#066x}\n  b     = {b:#066x}\n  c     = {c:#066x}\n"
                f"  d_int = {di:#066x}  flags {fi:#07b}\n"
                f"  d_shr = {ds:#066x}  flags {fs:#07b}")
        await ClockCycles(dut.clk, LATENCY + 4)

    dut._log.info("cancellation: all four formats agree")
