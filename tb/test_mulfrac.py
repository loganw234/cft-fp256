# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The fractured significand array against exact integer arithmetic.

cft_mulfrac replaces four independent per-format multipliers with one
mode-gated array. The claim it has to earn is narrow and total: for
every mode, every lane's product must equal the exact integer product
of that lane's operands, and no lane may influence any other.

So this bench scores against Python integers rather than against
another RTL implementation. There is no rounding here and no format
semantics - a significand multiply is just a multiply - which makes the
reference unarguable and keeps this test independent of everything the
softfloat model does.

Four things are checked, and the last two are the ones that would catch
a fracture bug:

  1. random operands, each mode, one at a time
  2. edges - zero, one, all-ones significands, single set bits
  3. LANE ISOLATION - drive one lane and prove every other output field
     is exactly zero. A shift that lands a product one bit into its
     neighbour, or a chunk that reaches into the next lane's operand
     bits, shows up here and almost nowhere else.
  4. MIXED-MODE STREAMING - back-to-back operations at different modes
     with several in flight at once. The shift is applied at S2 from
     the mode presented with the operands, and the reduction tree is
     deliberately mode-agnostic; if that reasoning is wrong, a mode
     change mid-pipeline corrupts whatever is still in it.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

# (mode code, name, lanes, significand width)
MODES = [
    (0, "fp32",  8, 24),
    (1, "fp64",  4, 53),
    (2, "fp128", 2, 113),
    (3, "fp256", 1, 237),
]

DEPTH = 5          # cft_mulfrac's pipeline depth
PMAX = 237


def pack(vals, width):
    """Lane values -> the packed operand word, low lane first."""
    w = 0
    for i, v in enumerate(vals):
        assert 0 <= v < (1 << width), f"lane value {v:#x} exceeds {width} bits"
        w |= v << (i * width)
    return w


def expected(avals, bvals, width):
    """Packed products: lane L's a*b placed at L*2*width."""
    w = 0
    for i, (x, y) in enumerate(zip(avals, bvals)):
        w |= (x * y) << (i * 2 * width)
    return w


def unpack(word, lanes, width):
    """Packed products -> per-lane values, for readable failures."""
    m = (1 << (2 * width)) - 1
    return [(word >> (i * 2 * width)) & m for i in range(lanes)]


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.in_valid.value = 0
    dut.mode.value = 3
    dut.a.value = 0
    dut.b.value = 0
    await ClockCycles(dut.clk, 4)


async def one(dut, mode, avals, bvals, width):
    """Push a single operation and collect its result."""
    dut.mode.value = mode
    dut.a.value = pack(avals, width)
    dut.b.value = pack(bvals, width)
    dut.in_valid.value = 1
    await RisingEdge(dut.clk)
    dut.in_valid.value = 0
    # DEPTH-1 more edges land us on the cycle out_valid is high; read
    # after the settle so p is the value for THIS operation.
    await ClockCycles(dut.clk, DEPTH - 1)
    await ClockCycles(dut.clk, 1)
    assert dut.out_valid.value == 1, "result did not arrive at the stated depth"
    return int(dut.p.value)


@cocotb.test()
async def random_per_mode(dut):
    await start(dut)
    rng = random.Random(20260830)
    total = 0
    for code, name, lanes, width in MODES:
        for _ in range(40):
            av = [rng.getrandbits(width) for _ in range(lanes)]
            bv = [rng.getrandbits(width) for _ in range(lanes)]
            got = await one(dut, code, av, bv, width)
            want = expected(av, bv, width)
            if got != want:
                g = unpack(got, lanes, width)
                w = unpack(want, lanes, width)
                bad = [i for i in range(lanes) if g[i] != w[i]]
                raise AssertionError(
                    f"{name}: lanes {bad} wrong\n"
                    f"  a    = {[hex(x) for x in av]}\n"
                    f"  b    = {[hex(x) for x in bv]}\n"
                    f"  got  = {[hex(x) for x in g]}\n"
                    f"  want = {[hex(x) for x in w]}")
            total += lanes
    dut._log.info(f"random: {total} lane products exact across four modes")


@cocotb.test()
async def edges(dut):
    await start(dut)
    checked = 0
    for code, name, lanes, width in MODES:
        top = (1 << width) - 1
        cases = [
            ([0] * lanes, [0] * lanes),
            ([1] * lanes, [1] * lanes),
            ([top] * lanes, [top] * lanes),        # widest product, all lanes
            ([top] * lanes, [1] * lanes),
            ([1 << (width - 1)] * lanes, [1 << (width - 1)] * lanes),
            ([0] * lanes, [top] * lanes),
        ]
        for av, bv in cases:
            got = await one(dut, code, av, bv, width)
            want = expected(av, bv, width)
            assert got == want, (
                f"{name} edge case failed\n"
                f"  a={[hex(x) for x in av]} b={[hex(x) for x in bv]}\n"
                f"  got  {[hex(x) for x in unpack(got, lanes, width)]}\n"
                f"  want {[hex(x) for x in unpack(want, lanes, width)]}")
            checked += 1
    dut._log.info(f"edges: {checked} cases exact")


@cocotb.test()
async def lane_isolation(dut):
    """One lane live, every other output field must be exactly zero.

    This is the test that catches a fracture bug. A shift constant one
    place out, or a chunk slice that reaches past its lane into the next
    lane's operand bits, produces a nonzero where nothing was driven -
    and random testing hides it, because a wrong bit landing in a
    neighbour that also has data just looks like a wrong product.
    """
    await start(dut)
    checked = 0
    for code, name, lanes, width in MODES:
        top = (1 << width) - 1
        for live in range(lanes):
            av = [0] * lanes
            bv = [0] * lanes
            av[live] = top
            bv[live] = top
            got = await one(dut, code, av, bv, width)
            fields = unpack(got, lanes, width)

            assert fields[live] == top * top, (
                f"{name} lane {live}: got {fields[live]:#x}, "
                f"want {top * top:#x}")
            for other in range(lanes):
                if other == live:
                    continue
                assert fields[other] == 0, (
                    f"{name}: driving only lane {live} put "
                    f"{fields[other]:#x} into lane {other} - the fracture "
                    f"leaks across lanes")
            # Nothing may appear above the last lane either.
            assert got >> (lanes * 2 * width) == 0, (
                f"{name} lane {live}: bits set above the packed product "
                f"region ({got >> (lanes * 2 * width):#x})")
            checked += 1
    dut._log.info(f"lane isolation: {checked} single-lane drives, no leakage")


@cocotb.test()
async def mixed_mode_stream(dut):
    """Back-to-back operations at different modes, several in flight.

    The design applies each operation's shift at S2 from the mode
    presented with its operands, and the reduction tree is deliberately
    mode-agnostic. That is what allows modes to change with no pipeline
    flush. If it is wrong, an operation still in the tree is corrupted
    by the next one's mode.
    """
    await start(dut)
    rng = random.Random(0xFACE)

    ops = []
    for _ in range(60):
        code, name, lanes, width = MODES[rng.randrange(4)]
        av = [rng.getrandbits(width) for _ in range(lanes)]
        bv = [rng.getrandbits(width) for _ in range(lanes)]
        ops.append((code, name, lanes, width, av, bv,
                    expected(av, bv, width)))

    results = []

    async def collect():
        # One sample per cycle for the whole run plus the drain.
        for _ in range(len(ops) + DEPTH + 4):
            await RisingEdge(dut.clk)
            await cocotb.triggers.ReadOnly()
            if dut.out_valid.value == 1:
                results.append(int(dut.p.value))

    task = cocotb.start_soon(collect())

    for code, _n, _l, width, av, bv, _w in ops:
        dut.mode.value = code
        dut.a.value = pack(av, width)
        dut.b.value = pack(bv, width)
        dut.in_valid.value = 1
        await RisingEdge(dut.clk)
    dut.in_valid.value = 0
    await task

    assert len(results) == len(ops), (
        f"{len(results)} results for {len(ops)} operations - the pipeline "
        f"dropped or duplicated work under mode changes")

    for i, (code, name, lanes, width, av, bv, want) in enumerate(ops):
        if results[i] != want:
            g = unpack(results[i], lanes, width)
            w = unpack(want, lanes, width)
            raise AssertionError(
                f"op {i} ({name}) corrupted in a mixed-mode stream\n"
                f"  got  {[hex(x) for x in g]}\n"
                f"  want {[hex(x) for x in w]}")

    modes_used = len({o[0] for o in ops})
    dut._log.info(f"mixed stream: {len(ops)} back-to-back ops across "
                  f"{modes_used} modes, all exact")
