# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The multi-cycle lane array against the single-pass one: identical bits.

tb_mulcycle builds cft_lanes twice, at MUL_PASSES=1 and at MUL_PASSES=MC,
and hands both the same beat on the same edge. This bench streams
operands through both - random patterns blended with the directed
specials, every format, every rounding attribute, opcodes that compute
and opcodes that bypass - and asserts that every result word and every
lane's flag word agree exactly.

What it is really testing is the pacing. The multi-cycle array iterates
its wide rungs' multipliers and holds the whole pipe between passes;
the operands it multiplies, the rounding attribute it applies, the
sideband that carries a special past the datapath, the bypass that
carries a non-arithmetic result - all of them ride delay lines that
have to stay aligned across the holds, and a slip of one enabled edge
anywhere hands an operation its neighbour's attribute or its
neighbour's product. The reference array cannot have that bug, so any
divergence here is the multi-cycle mechanism.

The issue cadence is the property under test, so it is varied: beats
are presented with random gaps between them, and the same operand
stream is run twice under two different gap patterns and required to
produce the same results both times. Precision changes only between
streams with the pipe drained, which is the drivers' contract (both
snapshot prec at start and hold it until their last result retires);
mid-flight it is undefined here as it is in the tile.
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, RND_NAMES, SIMPLE_OPS, vectors,
)

LATENCY = 15

FORMATS = [
    (FP32,  0, 8),
    (FP64,  1, 4),
    (FP128, 2, 2),
    (FP256, 3, 1),
]

# Opcodes the array computes through the datapath (fma/add/sub/mul are
# steered FMAs) plus the whole bypass set, so a bypassed and a computed
# operation are in flight together across the holds.
ARITH_OPS = [0, 1, 2, 3]


def gen_beat(fmt, lanes, rng):
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
    dut.op.value = 0
    dut.rnd.value = 0
    dut.prec.value = 0
    dut.a.value = 0
    dut.b.value = 0
    dut.c.value = 0
    await ClockCycles(dut.clk, 6)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)


async def run_stream(dut, code, beats, gap_rng, max_gap, label):
    """Present `beats` (op, rnd, a, b, c) to both arrays, one per cycle
    the multi-cycle array is ready, with random idle gaps; return the
    two result lists in order."""
    ref, mc = [], []
    done = {"ref": False, "mc": False}

    async def collect(ov, d, lf, sink, key):
        while len(sink) < len(beats):
            await FallingEdge(dut.clk)
            if int(ov.value) == 1:
                sink.append((int(d.value), int(lf.value)))
        done[key] = True

    cocotb.start_soon(collect(dut.ov_ref, dut.d_ref, dut.lf_ref, ref, "ref"))
    cocotb.start_soon(collect(dut.ov_mc, dut.d_mc, dut.lf_mc, mc, "mc"))

    dut.prec.value = code
    for op, rnd, a, b, c in beats:
        # an idle gap of 0..max_gap cycles, so the beat lands at a random
        # phase of the multi-cycle array's period
        for _ in range(gap_rng.randrange(max_gap + 1)):
            await RisingEdge(dut.clk)
            await Timer(1, units="ns")
            dut.in_valid.value = 0
        while True:
            await RisingEdge(dut.clk)
            await Timer(1, units="ns")
            if int(dut.ready_mc.value) == 1:
                dut.op.value = op
                dut.rnd.value = rnd
                dut.a.value = a
                dut.b.value = b
                dut.c.value = c
                dut.in_valid.value = 1
                break
            dut.in_valid.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, units="ns")
    dut.in_valid.value = 0

    # drain: both arrays must deliver every beat
    limit = (LATENCY + 4) * 16 + 64
    for _ in range(limit):
        if done["ref"] and done["mc"]:
            break
        await RisingEdge(dut.clk)
    assert done["ref"] and done["mc"], (
        f"{label}: {len(ref)} reference and {len(mc)} multi-cycle results "
        f"for {len(beats)} beats - the multi-cycle array dropped work")

    for i, ((dr, fr), (dm, fm)) in enumerate(zip(ref, mc)):
        if dr != dm or fr != fm:
            op, rnd, a, b, c = beats[i]
            raise AssertionError(
                f"{label}: multi-cycle array disagrees with the single-pass one "
                f"on beat {i} of {len(beats)} (op {op}, {RND_NAMES[rnd]})\n"
                f"  a     = {a:#066x}\n  b     = {b:#066x}\n  c     = {c:#066x}\n"
                f"  d_ref = {dr:#066x}  flags {fr:#012x}\n"
                f"  d_mc  = {dm:#066x}  flags {fm:#012x}")
    return mc


def make_beats(fmt, lanes, rng, n, rnds, ops):
    beats = []
    for _ in range(n):
        beats.append((ops[rng.randrange(len(ops))], rnds[rng.randrange(len(rnds))],
                      gen_beat(fmt, lanes, rng), gen_beat(fmt, lanes, rng),
                      gen_beat(fmt, lanes, rng)))
    return beats


@cocotb.test()
async def identical_per_format(dut):
    """Every format, every attribute, arithmetic and bypass interleaved."""
    await reset(dut)
    rng = random.Random(20260906)
    total = 0
    for fmt, code, lanes in FORMATS:
        for rnd in range(5):
            beats = make_beats(fmt, lanes, rng, 24, [rnd], ARITH_OPS + list(SIMPLE_OPS))
            await run_stream(dut, code, beats, random.Random(rnd), 3,
                             f"{fmt.name}/{RND_NAMES[rnd]}")
            total += len(beats)
        dut._log.info(f"{fmt.name}: {lanes} lanes x 5 attributes, identical bits and flags")
    dut._log.info(f"identity: {total} beats, no disagreement")


@cocotb.test()
async def identical_across_cadences(dut):
    """The same stream twice, under different issue gaps: same bits.

    Both runs are compared against the reference array as always; the
    two multi-cycle result lists are then compared against each other,
    which is the direct statement that the issue cadence does not reach
    the result.
    """
    await reset(dut)
    rng = random.Random(4711)
    for fmt, code, lanes in FORMATS:
        beats = make_beats(fmt, lanes, rng, 20, list(range(5)), ARITH_OPS)
        first = await run_stream(dut, code, beats, random.Random(1), 0,
                                 f"{fmt.name} back-to-back")
        second = await run_stream(dut, code, beats, random.Random(2), 13,
                                  f"{fmt.name} gapped")
        assert first == second, (
            f"{fmt.name}: the multi-cycle array's results depend on the issue cadence")
        dut._log.info(f"{fmt.name}: {len(beats)} beats, back-to-back and gapped, identical")


@cocotb.test()
async def identical_on_specials(dut):
    """Beats made entirely of the awkward values, with attributes mixed."""
    await reset(dut)
    rng = random.Random(99)
    total = 0
    for fmt, code, lanes in FORMATS:
        pool = vectors.interesting_operands(fmt)

        def sbeat():
            v = 0
            for i in range(lanes):
                v |= pool[rng.randrange(len(pool))] << (i * fmt.width)
            return v

        beats = [(ARITH_OPS[rng.randrange(len(ARITH_OPS))], rng.randrange(5),
                  sbeat(), sbeat(), sbeat()) for _ in range(40)]
        await run_stream(dut, code, beats, random.Random(7), 2, f"{fmt.name} specials")
        total += len(beats)
    dut._log.info(f"specials: {total} all-special beats, identical")


@cocotb.test()
async def identical_under_precision_changes(dut):
    """Switch precision between drained streams, in a scrambled order.

    The pass period changes with the precision; each switch restarts
    the phase counter mid-count, which is the run boundary the tile
    crosses between two runs of different rungs.
    """
    await reset(dut)
    rng = random.Random(31337)
    order = [FORMATS[i] for i in (3, 0, 2, 1, 0, 3, 1, 2, 3, 3, 0)]
    total = 0
    for fmt, code, lanes in order:
        beats = make_beats(fmt, lanes, rng, 8, list(range(5)), ARITH_OPS)
        await run_stream(dut, code, beats, rng, 4, f"{fmt.name} in sequence")
        total += len(beats)
    dut._log.info(f"precision changes: {total} beats across {len(order)} switches, identical")
