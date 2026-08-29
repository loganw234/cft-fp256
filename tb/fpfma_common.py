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
"""

import os
import sys
from collections import deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import OP_NAMES, fma, steer, vectors  # noqa: E402


async def run_fma_pipe_test(dut, fmt, directed_default, random_default):
    directed = int(os.getenv("CFT_DIRECTED", str(directed_default)))
    rand_n = int(os.getenv("CFT_RANDOM", str(random_default)))
    seed = int(os.getenv("CFT_SEED", "3"))
    cases = vectors.testset(fmt, directed, rand_n, seed)

    # The pipe is the raw FMA core: apply the golden operand steering
    # here so every op still exercises it. The RTL steering mux is
    # covered by the kernel-level test.
    work = []
    for op, xa, xb, xc in cases:
        fa, fb, fc = steer(fmt, op, xa, xb, xc)
        want_d, want_f = fma(fmt, fa, fb, fc)
        work.append((op, fa, fb, fc, want_d, want_f))

    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.in_valid.value = 0
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
                op, fa, fb, fc, want_d, want_f = expected.popleft()
                got_d = int(dut.d.value)
                got_f = int(dut.flags.value)
                if got_d != want_d or got_f != want_f:
                    errors.append(
                        f"{fmt.name} {OP_NAMES[op]} a={fa:#x} b={fb:#x} "
                        f"c={fc:#x}: got d={got_d:#x} f={got_f:#05b}, "
                        f"want d={want_d:#x} f={want_f:#05b}")
                    if len(errors) <= 20:
                        dut._log.error(errors[-1])
                checked += 1

    chk = cocotb.start_soon(checker())

    for item in work:
        _, fa, fb, fc, _, _ = item
        dut.a.value = fa
        dut.b.value = fb
        dut.c.value = fc
        dut.in_valid.value = 1
        expected.append(item)
        await RisingEdge(dut.clk)
    dut.in_valid.value = 0

    # drain the pipe
    for _ in range(16):
        await RisingEdge(dut.clk)
    chk.kill()

    assert not expected, f"{len(expected)} results never emerged from the pipe"
    assert checked == len(work)
    assert not errors, \
        f"{len(errors)} of {checked} mismatches (first: {errors[0]})"
    dut._log.info(f"{fmt.name}: {checked} vectors bit-exact against cft_golden")
