# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The iterated chunk-column multiplier against exact integer arithmetic.

cft_mulpass computes a P x P significand product over several passes
of a few chunk columns, and the claim it has to earn is that the
integer it hands back is a * b - exactly, at every geometry, at the
pipeline level the side-by-side tree delivered it, held for the whole
enabled interval. No rounding and no format semantics are involved, so
the reference is Python's integers and nothing else.

tb_mulpass holds ten instances (fp64, fp128 and fp256 at every column
count a pass budget can produce), each behind a model of the pipe's S1
register and paced at its own period. The bench changes the operands
EVERY cycle - a value is only an operand if an enabled edge captured
it - and checks, every cycle, that each instance's product is the
product of the operands captured five enabled edges earlier.

Two things are checked beside the products. The period each instance's
counter actually runs at is compared against a Python derivation of
ceil(chunks / cols) - a second implementation of the include's
arithmetic - and the product is required to be STABLE across the
interval, not merely right on its last cycle, because the pipe's S7
reads it on the enabled edge and a value that is right for one cycle
and wrong for the rest is a value that is right by accident.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

# (instance, P, COLS) - the table in tb_mulpass.sv, restated so the
# bench can derive each period on its own and compare.
INSTANCES = [
    (0, 53, 1), (1, 53, 2),
    (2, 113, 1), (3, 113, 2), (4, 113, 3),
    (5, 237, 1), (6, 237, 2), (7, 237, 5), (8, 237, 3), (9, 237, 4),
]
MCH = 24          # the chunk width cft_mulgeom.svh fixes; a second copy on purpose
LEVEL = 5         # enabled intervals from S1 capture to product


def passes(p, cols):
    chunks = (p + MCH - 1) // MCH
    return (chunks + cols - 1) // cols


def operand(rng, width):
    """A significand-shaped value: mostly random, with the corners."""
    r = rng.random()
    if r < 0.10:
        return (1 << width) - 1
    if r < 0.20:
        return 1 << rng.randrange(width)
    if r < 0.30:
        return (1 << width) - (1 << rng.randrange(width))
    if r < 0.35:
        return 0
    return rng.getrandbits(width)


@cocotb.test()
async def exact_at_every_geometry(dut):
    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    rng = random.Random(20260906)
    dut.rst_n.value = 0
    dut.a.value = 0
    dut.b.value = 0
    # long enough for every instance's delayed-enable line to fill with
    # zeros before the first enabled edge
    await ClockCycles(dut.clk, 12)
    dut.rst_n.value = 1

    # per instance: the operands captured at each enabled edge, and the
    # count of enabled edges seen; the product during interval j must
    # be that of the operands captured at edge j - LEVEL.
    captured = {k: [] for k, _, _ in INSTANCES}
    en_edges = {k: 0 for k, _, _ in INSTANCES}
    en_gaps = {k: [] for k, _, _ in INSTANCES}
    last_en_cycle = {k: None for k, _, _ in INSTANCES}
    checks = {k: 0 for k, _, _ in INSTANCES}
    errors = []

    ncycles = 3000
    for cyc in range(ncycles):
        await RisingEdge(dut.clk)
        # fresh operands every cycle; the S1 models decide which count
        a = operand(rng, 237)
        b = operand(rng, 237)
        dut.a.value = a
        dut.b.value = b
        await FallingEdge(dut.clk)
        for k, p, cols in INSTANCES:
            en = int(getattr(dut, f"en_{k}").value)
            j = en_edges[k]
            # j enabled edges have ended, the last of them E_{j-1}, so this
            # cycle lies in [E_{j-1}, E_j) - the interval in which the
            # product of the operands captured at E_{j-1-LEVEL} is due.
            # Before that many edges the module holds nothing meaningful,
            # and its output may still carry X, so it is not even read.
            if j >= LEVEL + 1:
                got = int(getattr(dut, f"p_{k}").value)
                ca, cb = captured[k][j - LEVEL - 1]
                want = ca * cb
                if got != want:
                    errors.append((k, p, cols, cyc, j, ca, cb, got, want))
                checks[k] += 1
            if en:
                # the S1 model captures this cycle's operands at the edge
                # that ends it: op number len(captured[k])
                captured[k].append((a & ((1 << p) - 1), b & ((1 << p) - 1)))
                if last_en_cycle[k] is not None:
                    en_gaps[k].append(cyc - last_en_cycle[k])
                last_en_cycle[k] = cyc
                en_edges[k] += 1

    if errors:
        k, p, cols, cyc, j, ca, cb, got, want = errors[0]
        raise AssertionError(
            f"instance {k} (P={p}, COLS={cols}, {passes(p, cols)} passes): "
            f"{len(errors)} wrong products, first at cycle {cyc} interval {j}\n"
            f"  a    = {ca:#x}\n  b    = {cb:#x}\n"
            f"  got  = {got:#x}\n  want = {want:#x}")

    for k, p, cols in INSTANCES:
        want_np = passes(p, cols)
        gaps = set(en_gaps[k])
        assert gaps == {want_np}, (
            f"instance {k} (P={p}, COLS={cols}): enable period(s) {sorted(gaps)}, "
            f"want {want_np} - the include and the bench disagree about the geometry")
        assert checks[k] >= ncycles - 12 * want_np, (
            f"instance {k}: only {checks[k]} product checks in {ncycles} cycles")
        dut._log.info(
            f"instance {k}: P={p} COLS={cols} -> {want_np} passes, "
            f"{len(captured[k])} operations, {checks[k]} exact product samples")
