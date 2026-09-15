# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The reduction accumulator against the golden model's tree.

cft_reduce_acc is a streaming binary-counter stack with deferred
carries. `cft_golden.reduce.stream_reduce` is that same machine written
in Python, and a model test already holds it equal to the recursive
tree definition - so scoring the RTL against `fsum` checks the whole
chain at once: hardware, streaming form, and the contract's tree.

What makes this worth testing carefully rather than casually:

  - the shape depends on n, and every n exercises a different set of
    carries. Powers of two are the EASY case, where the tree is perfect
    and the final fold has one entry. Sizes like 7, 11 and 13 leave
    several levels occupied and the fold order becomes load-bearing.
  - carries are deferred, so several adds are in flight at once and a
    result can collide with a level that a later input has since
    filled. That is the interesting concurrency and it only happens at
    particular sizes and input rates.
  - the accumulator asserts backpressure. A driver that ignores
    in_ready would silently drop inputs, and the answer would be a
    reduction over fewer elements - which for many operand sets still
    looks plausible.
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FP32, RND_NAMES, vectors  # noqa: E402
from cft_golden.reduce import fsum, stream_reduce  # noqa: E402

LATENCY = 16


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.rst_n.value = 0
    dut.clear.value = 0
    dut.rnd.value = 0
    dut.in_valid.value = 0
    dut.in_data.value = 0
    # The wide input is driven low here rather than only in the test
    # that uses it: an undriven `win_valid` is X under Icarus, and X on
    # it makes every arbitration decision in the module X - which would
    # present as the ORIGINAL tests failing for no reason.
    dut.win_valid.value = 0
    dut.win_data.value = 0
    dut.win_lvl.value = 0
    dut.flush.value = 0
    await ClockCycles(dut.clk, 6)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 4)


async def reduce_on_dut(dut, values, rnd, gap=0):
    """Stream `values` through the accumulator and read the result.

    `gap` idles that many cycles between inputs, which changes how many
    adds are in flight when the next one arrives - the concurrency the
    deferred carries create.
    """
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    dut.rnd.value = rnd
    await RisingEdge(dut.clk)

    for v in values:
        dut.in_data.value = v
        dut.in_valid.value = 1
        # Honour backpressure, and sample it in the RIGHT cycle. The
        # transfer happens on the rising edge when in_valid and in_ready
        # are both high, so ready has to be read BEFORE that edge -
        # reading it afterwards is the next cycle's value, and an input
        # gets dropped or repeated depending on how the stall lined up.
        # That is rate-dependent, so it presents as the accumulator
        # violating determinism rather than as a driver bug.
        while True:
            await FallingEdge(dut.clk)
            taken = dut.in_ready.value == 1
            await RisingEdge(dut.clk)
            if taken:
                break
        dut.in_valid.value = 0
        for _ in range(gap):
            await RisingEdge(dut.clk)

    dut.in_valid.value = 0
    await RisingEdge(dut.clk)
    dut.flush.value = 1
    await RisingEdge(dut.clk)
    dut.flush.value = 0

    # Bounded wait. The fold walks up to LEVELS occupied slots, each
    # costing one adder pass, so this is generous rather than tight.
    for _ in range(40 * LATENCY + 400):
        await FallingEdge(dut.clk)
        if dut.out_valid.value == 1:
            return int(dut.out_data.value), int(dut.out_flags.value)
        await RisingEdge(dut.clk)
    raise AssertionError(
        f"no result after flush for n={len(values)} - the accumulator is "
        f"stuck, and the fold state machine is where to look")


def rand_finite(rng, spread=12):
    fmt = FP32
    sign = rng.getrandbits(1)
    e = fmt.bias + rng.randint(-spread, spread)
    m = rng.getrandbits(fmt.man_w)
    return (sign << 31) | (e << fmt.man_w) | m


@cocotb.test()
async def every_small_n(dut):
    """Every length from 1 to 40, which is where the shape varies most.

    A power of two leaves one occupied level and a trivial fold; 7 and
    11 and 13 leave several and exercise the fold order. Covering them
    all is cheap and it is the only way to catch a tree that is right
    for round numbers.
    """
    await reset(dut)
    rng = random.Random(20260830)
    for n in range(1, 41):
        xs = [rand_finite(rng) for _ in range(n)]
        got, gflags = await reduce_on_dut(dut, xs, 0)
        want, wflags = fsum(FP32, xs, 0)
        assert got == want, (
            f"n={n}: got {got:#010x} want {want:#010x}\n"
            f"  inputs {[hex(x) for x in xs[:8]]}"
            f"{' ...' if n > 8 else ''}")
        assert gflags == wflags, f"n={n}: flags {gflags:#07b} want {wflags:#07b}"
    dut._log.info("every n from 1 to 40: bit-exact against the model tree")


@cocotb.test()
async def larger_and_every_attribute(dut):
    await reset(dut)
    rng = random.Random(4242)
    total = 0
    for rnd in range(5):
        for n in (63, 64, 65, 100, 127, 128, 129):
            xs = [rand_finite(rng) for _ in range(n)]
            got, gflags = await reduce_on_dut(dut, xs, rnd)
            want, wflags = fsum(FP32, xs, rnd)
            assert (got, gflags) == (want, wflags), (
                f"n={n} {RND_NAMES[rnd]}: got {got:#010x}/{gflags:#07b} "
                f"want {want:#010x}/{wflags:#07b}")
            total += n
    dut._log.info(f"{total} elements across 7 sizes x 5 attributes, exact")


@cocotb.test()
async def input_rate_does_not_change_the_answer(dut):
    """Same values, different arrival rates.

    Deferring carries means the number of adds in flight depends on how
    fast inputs arrive, so a result can land on a level that a later
    input has since filled - or not - purely because of timing. The
    answer must not notice. This is the module's own version of the
    determinism argument the whole project rests on.
    """
    await reset(dut)
    rng = random.Random(1234)
    for n in (5, 7, 11, 16, 23, 37, 64):
        xs = [rand_finite(rng) for _ in range(n)]
        want, wflags = fsum(FP32, xs, 0)
        for gap in (0, 1, 3, 17):
            got, gflags = await reduce_on_dut(dut, xs, 0, gap=gap)
            assert (got, gflags) == (want, wflags), (
                f"n={n} gap={gap}: got {got:#010x} want {want:#010x} - the "
                f"answer depends on the input rate, which means the pairing "
                f"is not fixed by index")
    dut._log.info("arrival rate does not reach the answer, 7 sizes x 4 rates")


@cocotb.test()
async def specials_and_edges(dut):
    await reset(dut)
    rng = random.Random(99)
    pool = vectors.interesting_operands(FP32)

    # single element: no adds happen, so nothing may be raised
    for v in (pool[rng.randrange(len(pool))] for _ in range(6)):
        got, gflags = await reduce_on_dut(dut, [v], 0)
        assert (got, gflags) == fsum(FP32, [v], 0), \
            f"n=1 must return the input verbatim with no flags, got {got:#010x}"

    for n in (2, 3, 5, 8, 13):
        for _ in range(6):
            xs = [pool[rng.randrange(len(pool))] for _ in range(n)]
            got, gflags = await reduce_on_dut(dut, xs, 0)
            want, wflags = fsum(FP32, xs, 0)
            assert (got, gflags) == (want, wflags), (
                f"specials n={n}: got {got:#010x}/{gflags:#07b} "
                f"want {want:#010x}/{wflags:#07b}\n"
                f"  {[hex(x) for x in xs]}")
    dut._log.info("specials: NaN, inf, zero and subnormal streams exact")


async def wait_for_result(dut):
    """Flush and read, the tail of reduce_on_dut, shared so the grouped
    driver below cannot drift from it."""
    dut.in_valid.value = 0
    dut.win_valid.value = 0
    await RisingEdge(dut.clk)
    dut.flush.value = 1
    await RisingEdge(dut.clk)
    dut.flush.value = 0
    for _ in range(40 * LATENCY + 400):
        await FallingEdge(dut.clk)
        if dut.out_valid.value == 1:
            return int(dut.out_data.value), int(dut.out_flags.value)
        await RisingEdge(dut.clk)
    raise AssertionError("no result after flush - the fold is stuck")


async def reduce_grouped_on_dut(dut, values, k, rnd, gap=0):
    """Hand ALIGNED GROUPS of 2**k elements through the wide input and
    whatever is left over through the single-element input.

    That is what the engine's beat-wide tree does with a beat and its
    tail, and doing it here with the group partials computed by the
    MODEL's own tree tests the accumulator's claim on its own: a group
    that enters at level k pairs exactly as it would have if its
    elements had streamed in one at a time. The group's internal adds
    happened outside, so their flags are ORed in by the caller - the
    engine collects them from the tree's lanes for the same reason.
    """
    g = 1 << k
    ngroups = len(values) // g
    flags = 0

    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    dut.rnd.value = rnd
    await RisingEdge(dut.clk)

    dut.win_lvl.value = k
    for t in range(ngroups):
        part, f = stream_reduce(FP32, values[t * g:(t + 1) * g], rnd)
        flags |= f
        dut.win_data.value = part
        dut.win_valid.value = 1
        while True:
            await FallingEdge(dut.clk)
            taken = dut.win_ready.value == 1
            await RisingEdge(dut.clk)
            if taken:
                break
        dut.win_valid.value = 0
        for _ in range(gap):
            await RisingEdge(dut.clk)
    dut.win_valid.value = 0

    # The tail, AFTER every group: its elements have the highest
    # indices, so they must reach the counter last.
    for v in values[ngroups * g:]:
        dut.in_data.value = v
        dut.in_valid.value = 1
        while True:
            await FallingEdge(dut.clk)
            taken = dut.in_ready.value == 1
            await RisingEdge(dut.clk)
            if taken:
                break
        dut.in_valid.value = 0
        for _ in range(gap):
            await RisingEdge(dut.clk)

    got, gflags = await wait_for_result(dut)
    return got, gflags | flags


@cocotb.test()
async def groups_entering_above_level_zero(dut):
    """The wide input against the same tree, at every group size and
    every tail length.

    n from 1 to 40 and k from 1 to 3 covers a group size larger than n
    (all tail), n an exact multiple of the group (no tail), and every
    remainder in between - which is the seam the engine has between a
    run of full beats and its partial last one.
    """
    await reset(dut)
    rng = random.Random(20260915)
    for k in (1, 2, 3):
        for n in range(1, 41):
            xs = [rand_finite(rng) for _ in range(n)]
            got, gflags = await reduce_grouped_on_dut(dut, xs, k, 0)
            want, wflags = fsum(FP32, xs, 0)
            assert got == want, (
                f"k={k} n={n}: got {got:#010x} want {want:#010x} - a group "
                f"entering at level {k} did not pair the way the counter "
                f"pairs\n  inputs {[hex(x) for x in xs[:8]]}")
            assert gflags == wflags, \
                f"k={k} n={n}: flags {gflags:#07b} want {wflags:#07b}"
    dut._log.info("groups at levels 1..3 with every tail from 0 to 7: "
                  "bit-exact against the model tree")


@cocotb.test()
async def grouped_rate_and_attributes_do_not_change_the_answer(dut):
    """Groups at four arrival rates and five attributes. The rate
    changes how many adds are in flight when a group lands, which is
    the concurrency the deferred carries create - now with two input
    ports feeding it instead of one."""
    await reset(dut)
    rng = random.Random(606)
    pool = vectors.interesting_operands(FP32)
    for rnd in range(5):
        for k in (2, 3):
            for n in (16, 23, 64, 65, 100):
                xs = [rand_finite(rng) for _ in range(n)]
                want, wflags = fsum(FP32, xs, rnd)
                for gap in (0, 1, 5):
                    got, gflags = await reduce_grouped_on_dut(
                        dut, xs, k, rnd, gap=gap)
                    assert (got, gflags) == (want, wflags), (
                        f"k={k} n={n} gap={gap} {RND_NAMES[rnd]}: got "
                        f"{got:#010x}/{gflags:#07b} want "
                        f"{want:#010x}/{wflags:#07b}")
    # specials through the wide port: a NaN or an infinity inside a
    # group is the group's problem, but the flags still have to arrive
    for n in (8, 12, 16):
        xs = [pool[rng.randrange(len(pool))] for _ in range(n)]
        got, gflags = await reduce_grouped_on_dut(dut, xs, 2, 0)
        assert (got, gflags) == fsum(FP32, xs, 0), \
            f"specials n={n}: got {got:#010x}/{gflags:#07b}"
    dut._log.info("grouped input: rate, attribute and specials all "
                  "leave the answer alone")


@cocotb.test()
async def streaming_form_is_the_spec(dut):
    """Belt and braces: the RTL against stream_reduce specifically.

    fsum is the recursive definition; stream_reduce is the accumulator
    algorithm. A model test holds them equal, so this is redundant - but
    it is redundant in the useful direction. If that model test ever
    fails, this one names which side the RTL followed.
    """
    await reset(dut)
    rng = random.Random(5150)
    for n in (1, 2, 3, 7, 15, 31, 33, 63):
        xs = [rand_finite(rng) for _ in range(n)]
        got, gflags = await reduce_on_dut(dut, xs, 0)
        assert (got, gflags) == stream_reduce(FP32, xs, 0)
        assert (got, gflags) == fsum(FP32, xs, 0)
    dut._log.info("RTL matches both the streaming and recursive forms")
