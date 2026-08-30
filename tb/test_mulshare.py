# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Shared multiplier against private multipliers: identical bits or nothing.

cft_mulfrac is already proven correct against exact integer arithmetic.
That is not the same as proving the tile is unchanged by adopting it,
because the product is only one input to fifteen stages of alignment,
normalisation and rounding - and those are where the contract actually
lives.

So this compares the two arrangements directly, on the same cycle, with
the same operands: eight fp32 lanes (plus four fp64, two fp128, one
fp256) each built twice, once with EXT_MUL=0 and its own multiplier and
once with EXT_MUL=1 fed by a single shared array. Every result and
every flag word must match exactly.

Comparing the two halves against each other rather than each against
the golden model is deliberate. The model comparison already exists and
runs on the internal configuration; what is new here is a claim of
EQUIVALENCE, and equivalence is best tested by subtraction. A bug that
somehow moved both halves the same way would be caught by the existing
model benches; a bug that moves one is caught here, and nothing has to
agree about what the right answer is for that to work.

Operands come from the same pool the kernel bench uses - random
patterns blended with the directed specials - so the shared array meets
NaNs, infinities, subnormals and exact cancellations in flight, not
just well-behaved numbers.
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, PREC_CODE, RND_NAMES, vectors,
)

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
            f"{label}: shared multiplier disagrees with private ones on "
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
    """Every format, every rounding attribute, streamed back to back."""
    await reset(dut)
    rng = random.Random(20260830)
    total = 0
    for fmt, code, lanes in FORMATS:
        for rnd in range(5):
            n = 24
            total += await compare_stream(
                dut, fmt, code, lanes, rnd, n, rng,
                f"{fmt.name}/{RND_NAMES[rnd]}")
        dut._log.info(f"{fmt.name}: {lanes} lanes x 5 attributes, "
                      f"identical bits and flags")
    dut._log.info(f"equivalence: {total} beats, no disagreement")


@cocotb.test()
async def equivalent_under_mode_changes(dut):
    """Switch precision between runs with the pipe still draining.

    The shared array's mode selects which bank's operands it multiplies.
    A mode change while earlier beats are still in flight is the case
    where a shared resource can corrupt work it has already accepted -
    the private multipliers cannot have that bug by construction, so
    any divergence here is the sharing.
    """
    await reset(dut)
    rng = random.Random(4711)
    order = [FORMATS[i] for i in (3, 0, 2, 1, 0, 3, 1, 2)]
    total = 0
    for fmt, code, lanes in order:
        total += await compare_stream(dut, fmt, code, lanes,
                                      rng.randrange(5), 8, rng,
                                      f"{fmt.name} in sequence")
    dut._log.info(f"mode changes: {total} beats across "
                  f"{len(order)} precision switches, identical")


@cocotb.test()
async def equivalent_on_specials(dut):
    """A beat made entirely of the awkward values.

    Random operands reach NaN and infinity only occasionally, and the
    paths that matter here - a product that never gets used because a
    special short-circuits it - are exactly the ones where a wrong
    shared product could hide. Fill every lane from the directed pool
    and check the two halves still agree.
    """
    await reset(dut)
    rng = random.Random(99)
    total = 0
    for fmt, code, lanes in FORMATS:
        pool = vectors.interesting_operands(fmt)

        async def specials_beat():
            v = 0
            for i in range(lanes):
                v |= pool[rng.randrange(len(pool))] << (i * fmt.width)
            return v

        sent = []
        mism = []

        async def collect():
            seen = 0
            for _ in range(40 + LATENCY + 8):
                await FallingEdge(dut.clk)
                if dut.out_valid.value == 1:
                    if (int(dut.d_int.value) != int(dut.d_shr.value)
                            or int(dut.f_int.value) != int(dut.f_shr.value)):
                        mism.append(seen)
                    seen += 1
            return seen

        task = cocotb.start_soon(collect())
        dut.mode.value = code
        dut.rnd.value = 0
        for _ in range(40):
            a, b, c = (await specials_beat(), await specials_beat(),
                       await specials_beat())
            sent.append((a, b, c))
            dut.a_beat.value = a
            dut.b_beat.value = b
            dut.c_beat.value = c
            dut.in_valid.value = 1
            await RisingEdge(dut.clk)
        dut.in_valid.value = 0
        seen = await task
        assert not mism, (
            f"{fmt.name}: all-specials beats diverged at {mism[:4]}")
        total += seen
    dut._log.info(f"specials: {total} all-special beats, identical")
