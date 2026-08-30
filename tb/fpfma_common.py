# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Shared cocotb driver/checker for the FMA pipe testbenches.

Streams the canonical golden test set through the DUT back-to-back
(one operand triple per clock - the pipeline is exercised, not just
the datapath) and compares every result and flag set against
cft_golden bit-for-bit. Budgets come from the environment so CI can
turn the crank harder:

    CFT_DIRECTED  directed-case budget (default per-format below)
    CFT_RANDOM    random-case count
    CFT_SEED      vector seed (default 3)
    CFT_ROUNDING  "all" (default) sweeps every rounding attribute;
                  a mode name or number restricts to that one

The rounding attribute is driven per operation and CHANGES between
adjacent operations in flight, which is the whole point of carrying
it down the pipeline instead of latching it per run: an interval
consumer wants a lower and an upper bound from one stream, and this
bench proves an operation cannot pick up its neighbour's attribute.
"""

import os
import random
import sys
from collections import deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import (  # noqa: E402
    OP_NAMES, RND_NAMES, RND_MODES, SIMPLE_OPS,
    compute, fma, steer, vectors,
)


def _rounding_plan():
    """Which attributes to sweep, from the environment."""
    want = os.getenv("CFT_ROUNDING", "all").strip().lower()
    if want in ("all", ""):
        return list(RND_MODES)
    by_name = {v: k for k, v in RND_NAMES.items()}
    if want in by_name:
        return [by_name[want]]
    return [int(want)]


async def run_fma_pipe_test(dut, fmt, directed_default, random_default):
    directed = int(os.getenv("CFT_DIRECTED", str(directed_default)))
    rand_n = int(os.getenv("CFT_RANDOM", str(random_default)))
    seed = int(os.getenv("CFT_SEED", "3"))
    modes = _rounding_plan()
    cases = vectors.testset(fmt, directed, rand_n, seed)

    # The pipe is the raw FMA core: apply the golden operand steering
    # here so every op still exercises it. The RTL steering mux is
    # covered by the kernel-level test.
    #
    # Each case is issued once per attribute, then the whole stream is
    # shuffled. The shuffle is the point, not cosmetic: issuing the
    # attributes in a fixed rotation gives the stream period 5, and the
    # pipeline is 15 stages deep - so a delay-line misalignment by any
    # multiple of 5 stages would deliver every operation an attribute
    # equal to its own and pass the entire suite. An aperiodic order
    # has no such blind spot, and adjacent operations still differ in
    # attribute most of the time, which is what proves an operation
    # cannot pick up its neighbour's.
    work = []
    for op, xa, xb, xc in cases:
        fa, fb, fc = steer(fmt, op, xa, xb, xc)
        for rnd in modes:
            want_d, want_f = fma(fmt, fa, fb, fc, rnd)
            work.append((op, rnd, fa, fb, fc, want_d, want_f))

    # The non-arithmetic operations take the same operands but bypass
    # the datapath entirely, so they are issued interleaved with the
    # arithmetic ones: a bypassed operation and a computed one are in
    # flight together on every cycle, which is the only way to catch a
    # sideband that carries the wrong one to the output.
    for op in SIMPLE_OPS:
        for _, xa, xb, xc in cases[:max(1, len(cases) // 4)]:
            want_d, want_f = compute(fmt, op, xa, xb, xc)
            work.append((op, RND_MODES[0], xa, xb, xc, want_d, want_f))

    random.Random(seed ^ 0x5EED).shuffle(work)

    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.in_valid.value = 0
    dut.rnd.value = 0
    dut.op.value = 0
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    expected = deque()
    errors = []
    checked = 0

    async def checker():
        nonlocal checked
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if dut.out_valid.value:
                op, rnd, fa, fb, fc, want_d, want_f = expected.popleft()
                got_d = int(dut.d.value)
                got_f = int(dut.flags.value)
                if got_d != want_d or got_f != want_f:
                    errors.append(
                        f"{fmt.name} {OP_NAMES[op]} {RND_NAMES[rnd]} "
                        f"a={fa:#x} b={fb:#x} "
                        f"c={fc:#x}: got d={got_d:#x} f={got_f:#05b}, "
                        f"want d={want_d:#x} f={want_f:#05b}")
                    if len(errors) <= 20:
                        dut._log.error(errors[-1])
                checked += 1

    chk = cocotb.start_soon(checker())

    for item in work:
        op, rnd, fa, fb, fc, _, _ = item
        dut.a.value = fa
        dut.b.value = fb
        dut.c.value = fc
        dut.rnd.value = rnd
        dut.op.value = op
        dut.in_valid.value = 1
        expected.append(item)
        await RisingEdge(dut.clk)
    dut.in_valid.value = 0

    # drain the pipe
    for _ in range(32):
        await RisingEdge(dut.clk)
    chk.kill()

    assert not expected, f"{len(expected)} results never emerged from the pipe"
    assert checked == len(work)
    assert not errors, \
        f"{len(errors)} of {checked} mismatches (first: {errors[0]})"
    n_simple = len(SIMPLE_OPS) * max(1, len(cases) // 4)
    dut._log.info(
        f"{fmt.name}: {checked} vectors bit-exact against cft_golden "
        f"({len(cases)} cases x {len(modes)} rounding "
        f"{'attributes' if len(modes) > 1 else 'attribute'} "
        f"[{', '.join(RND_NAMES[m] for m in modes)}], plus {n_simple} "
        f"non-arithmetic across {len(SIMPLE_OPS)} opcodes)")
