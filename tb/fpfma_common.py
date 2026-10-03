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
    CFT_AUG       R21's operand pairs (default: every family below,
                  whole); a number strides them down to about that many
    CFT_EN_AUGADD 1 (default) drives augadd and augerr; 0 leaves the
                  sideband idle, for a wrapper built with EN_AUGADD=0,
                  and holds every other operation to the model there

The rounding attribute is driven per operation and CHANGES between
adjacent operations in flight, which is the whole point of carrying
it down the pipeline instead of latching it per run: an interval
consumer wants a lower and an upper bound from one stream, and this
bench proves an operation cannot pick up its neighbour's attribute.

Since revision 8 (docs/ROADMAP.md, "Revision 8", part 4) the same
stream also carries:

* R21's augadd and augerr (docs/SEQUENCER.md R21) - ADD's operands
  with the pipe's aug_mode sideband at 1 or 2 - against
  cft_golden.augmented, the definition, both results and the flags;
  with an outside attribute that varies over all eight codes, since
  9.5 fixes the rounding and the sideband must win over any of them.
* the outside attribute codes 5 to 7, which MODE[14:12] documents as
  RNE and which no bench drove before: every arithmetic case once more
  at one of them, held to the model's RNE answer. Since R21 they also
  carry its separation: an outside 5 to 7 must not reach R21's mode.

Each item carries a family name, and a mismatch names its family, so a
fault is red in a named case and the summary counts every family.
"""

import os
import random
import sys
from collections import Counter, deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import (  # noqa: E402
    OP_ADD, OP_NAMES, RND_NAMES, RND_MODES, RND_RNE, SIMPLE_OPS,
    augmented_add, compute, fma, one_bits, steer, vectors,
)

#: aug_mode's codes, as rtl/cft_fpfma_pipe.sv and cft_lanes.sv name them
AUG_NONE, AUG_ADD, AUG_ERR = 0, 1, 2
AUG_NAMES = {AUG_ADD: "augadd", AUG_ERR: "augerr"}


def _rounding_plan():
    """Which attributes to sweep, from the environment."""
    want = os.getenv("CFT_ROUNDING", "all").strip().lower()
    if want in ("all", ""):
        return list(RND_MODES)
    by_name = {v: k for k, v in RND_NAMES.items()}
    if want in by_name:
        return [by_name[want]]
    return [int(want)]


def _rnd_name(rnd):
    """The attribute's name; 5 to 7 are reserved codes the RTL maps to
    RNE (MODE[14:12]), which the model has no name for."""
    return RND_NAMES.get(rnd, f"code{rnd}")


def _encode(fmt, sign, ef, frac):
    return (sign << (fmt.width - 1)) | (ef << fmt.man_w) | frac


def aug_pairs(fmt, budget=None, seed=3):
    """Operand pairs (x, y) for R21, the families revision 8's plan names
    (part 4: ties, either operand anchoring, the far case and a partly
    shifted-out operand, cancellation, overflow, underflow without
    inexact, specials and signed zeros), as (family, x, y).

    * pool: cft_golden's own adversarial set for clause 9.5
      (vectors.augmented_pairs) - ties at binade edges from odd
      significands, every binade at fp32; exact cancellation in every
      sign combination; sums whose residual is subnormal (underflow
      WITHOUT inexact); both sides of the overflow threshold; every
      special and signed zero against every other.
    * swap: the same pairs the other way round, so that the operand the
      pipe anchors (the larger exponent, a on a tie) is x in one and y
      in the other - the two clusters of the six places.
    * partial: y between P + 2 and 4P + 8 binades below x, in both
      orders, so the smaller operand is left whole, partly shifted out
      of the window (the marker set WITHOUT s6_far) or wholly (s6_far).
    * near: y within a few ulps of -x, deep cancellation.
    * close: exponents within 3P of each other, either sign - the six
      places, carries and borrows.
    * raw: uniform bit patterns.
    """
    rng = random.Random(seed ^ 0xA0621)
    p, man = fmt.prec, fmt.man_w
    emax_f = fmt.exp_mask - 1
    fams = []
    pool = vectors.augmented_pairs(fmt, 24, 16)
    fams += [("pool", x, y) for x, y in pool]
    fams += [("swap", y, x) for x, y in pool]
    for _ in range(300):
        ex = rng.randint(1, emax_f)
        d = rng.randint(p + 2, 4 * p + 8)
        ey = max(0, ex - d)
        x = _encode(fmt, rng.getrandbits(1), ex, rng.getrandbits(man))
        y = _encode(fmt, rng.getrandbits(1), ey, rng.getrandbits(man) | 1)
        fams += [("partial", x, y), ("partial", y, x)]
    for _ in range(200):
        x = _encode(fmt, rng.getrandbits(1), rng.randint(1, emax_f),
                    rng.getrandbits(man))
        y = (x ^ fmt.sign_mask) + rng.randint(-4, 4)
        fams.append(("near", x, y & ((1 << fmt.width) - 1)))
    for _ in range(400):
        ex = rng.randint(0, emax_f)
        ey = max(0, min(emax_f, ex + rng.randint(-3 * p, 3 * p)))
        x = _encode(fmt, rng.getrandbits(1), ex, rng.getrandbits(man))
        y = _encode(fmt, rng.getrandbits(1), ey, rng.getrandbits(man))
        fams.append(("close", x, y))
    for _ in range(200):
        fams.append(("raw", rng.getrandbits(fmt.width),
                     rng.getrandbits(fmt.width)))
    out, seen = [], set()
    for fam, x, y in fams:
        if (x, y) not in seen:
            seen.add((x, y))
            out.append((fam, x, y))
    if budget is not None and 0 < budget < len(out):
        step = len(out) / budget
        out = [out[int(i * step)] for i in range(budget)]
    return out


async def run_fma_pipe_test(dut, fmt, directed_default, random_default):
    directed = int(os.getenv("CFT_DIRECTED", str(directed_default)))
    rand_n = int(os.getenv("CFT_RANDOM", str(random_default)))
    seed = int(os.getenv("CFT_SEED", "3"))
    aug_budget = os.getenv("CFT_AUG", "").strip()
    aug_budget = int(aug_budget) if aug_budget else None
    en_aug = os.getenv("CFT_EN_AUGADD", "1").strip() != "0"
    modes = _rounding_plan()
    cases = vectors.testset(fmt, directed, rand_n, seed)

    # The pipe is the raw FMA core: apply the golden operand steering
    # here so every op still exercises it. The RTL steering mux is
    # covered by the kernel-level test.
    #
    # Each case is issued once per attribute, then the whole stream is
    # shuffled. The shuffle is the point, not cosmetic: issuing the
    # attributes in a fixed rotation gives the stream period 5, and the
    # pipeline is 16 stages deep - so a delay-line misalignment by any
    # multiple of 5 stages would deliver every operation an attribute
    # equal to its own and pass the entire suite. An aperiodic order
    # has no such blind spot, and adjacent operations still differ in
    # attribute most of the time, which is what proves an operation
    # cannot pick up its neighbour's.
    #
    # An item is (family, op, rnd, aug, fa, fb, fc, want_d, want_f).
    work = []
    for op, xa, xb, xc in cases:
        fa, fb, fc = steer(fmt, op, xa, xb, xc)
        for rnd in modes:
            want_d, want_f = fma(fmt, fa, fb, fc, rnd)
            work.append(("arith", op, rnd, AUG_NONE, fa, fb, fc,
                         want_d, want_f))

    # The outside codes 5 to 7: reserved, documented as RNE (MODE[14:12]
    # in rtl/cft_csr.sv), and refused by the model, so the expectation is
    # the model's RNE answer. Every arithmetic case once, at one of them.
    for i, (op, xa, xb, xc) in enumerate(cases):
        fa, fb, fc = steer(fmt, op, xa, xb, xc)
        want_d, want_f = fma(fmt, fa, fb, fc, RND_RNE)
        work.append(("rnd57", op, 5 + i % 3, AUG_NONE, fa, fb, fc,
                     want_d, want_f))

    # The non-arithmetic operations take the same operands but bypass
    # the datapath entirely, so they are issued interleaved with the
    # arithmetic ones: a bypassed operation and a computed one are in
    # flight together on every cycle, which is the only way to catch a
    # sideband that carries the wrong one to the output.
    # The rounding attribute is varied across them even though they
    # ignore it. That is the point: the contract asserts they ignore
    # it, and an assertion nothing exercises is an assumption. It holds
    # by construction - the bypass overrides before any rounding logic
    # is reached - but construction arguments are what this project
    # checks rather than trusts.
    for i, op in enumerate(SIMPLE_OPS):
        for j, (_, xa, xb, xc) in enumerate(cases[:max(1, len(cases) // 4)]):
            rnd = modes[(i + j) % len(modes)]
            want_d, want_f = compute(fmt, op, xa, xb, xc)
            work.append(("simple", op, rnd, AUG_NONE, xa, xb, xc,
                         want_d, want_f))

    # Unassigned opcodes are part of the contract too: canonical quiet
    # NaN, invalid raised, in hardware and model alike.
    for op in (15, 24, 200, 255):
        for _, xa, xb, xc in cases[:8]:
            want_d, want_f = compute(fmt, op, xa, xb, xc)
            work.append(("unassigned", op, modes[0], AUG_NONE, xa, xb, xc,
                         want_d, want_f))

    # R21: augadd and augerr, as the sequencer fires them - ADD's
    # operands (x, 1.0, y) with the sideband - against augmented.py,
    # which delivers both results of 754-2019 9.5's augmentedAddition and
    # its flags. The outside attribute rides along at every code 0 to 7:
    # 9.5 fixes the rounding (ties toward zero), so none of them may
    # change a bit.
    n_aug = Counter()
    if en_aug:
        one = one_bits(fmt, 0)
        arng = random.Random(seed ^ 0xA06D)
        for fam, x, y in aug_pairs(fmt, aug_budget, seed):
            r, e, fl = augmented_add(fmt, x, y)
            for aug, want in ((AUG_ADD, r), (AUG_ERR, e)):
                work.append((f"{AUG_NAMES[aug]}:{fam}", OP_ADD,
                             arng.randrange(8), aug, x, one, y, want, fl))
                n_aug[AUG_NAMES[aug]] += 1

    random.Random(seed ^ 0x5EED).shuffle(work)

    cocotb.start_soon(Clock(dut.clk, 4, units="ns").start())
    dut.in_valid.value = 0
    dut.rnd.value = 0
    dut.aug_mode.value = 0
    dut.op.value = 0
    dut.rst_n.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    expected = deque()
    errors = []
    bad_fam = Counter()
    checked = 0

    async def checker():
        nonlocal checked
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            if dut.out_valid.value:
                fam, op, rnd, aug, fa, fb, fc, want_d, want_f = \
                    expected.popleft()
                got_d = int(dut.d.value)
                got_f = int(dut.flags.value)
                if got_d != want_d or got_f != want_f:
                    bad_fam[fam] += 1
                    what = AUG_NAMES[aug] if aug else \
                        OP_NAMES.get(op, f"op{op}")
                    errors.append(
                        f"[{fam}] {fmt.name} {what} {_rnd_name(rnd)} "
                        f"a={fa:#x} b={fb:#x} "
                        f"c={fc:#x}: got d={got_d:#x} f={got_f:#07b}, "
                        f"want d={want_d:#x} f={want_f:#07b}")
                    if len(errors) <= 20:
                        dut._log.error(errors[-1])
                checked += 1

    chk = cocotb.start_soon(checker())

    # A wrapper paced at a multi-cycle pass budget exposes in_ready: the
    # pipe samples in_valid only in a cycle it is high, so an item is
    # held until it is. The single-pass wrappers hold it high, and this
    # loop is then the back-to-back stream it always was.
    ready = getattr(dut, "in_ready", None)
    for item in work:
        fam, op, rnd, aug, fa, fb, fc, _, _ = item
        dut.a.value = fa
        dut.b.value = fb
        dut.c.value = fc
        dut.rnd.value = rnd
        dut.aug_mode.value = aug
        dut.op.value = op
        dut.in_valid.value = 1
        expected.append(item)
        while True:
            await ReadOnly()
            taken = ready is None or int(ready.value) == 1
            await RisingEdge(dut.clk)
            if taken:
                break
    dut.in_valid.value = 0
    dut.aug_mode.value = 0

    # drain the pipe: LATENCY enabled edges, at whatever period
    for _ in range(32 * 16):
        await RisingEdge(dut.clk)
        if not expected:
            break
    for _ in range(4):
        await RisingEdge(dut.clk)
    chk.kill()

    fams = Counter(item[0].split(":")[0] if item[0].startswith("aug")
                   else item[0] for item in work)
    if bad_fam:
        dut._log.error("mismatches by family: " + ", ".join(
            f"{f} {n}" for f, n in sorted(bad_fam.items())))
    assert not expected, f"{len(expected)} results never emerged from the pipe"
    assert checked == len(work)
    assert not errors, \
        f"{len(errors)} of {checked} mismatches (first: {errors[0]})"
    n_simple = len(SIMPLE_OPS) * max(1, len(cases) // 4) + 4 * 8
    dut._log.info(
        f"{fmt.name}: {checked} vectors bit-exact against cft_golden "
        f"({len(cases)} cases x {len(modes)} rounding "
        f"{'attributes' if len(modes) > 1 else 'attribute'} "
        f"[{', '.join(RND_NAMES[m] for m in modes)}], plus {n_simple} "
        f"non-arithmetic across {len(SIMPLE_OPS)} opcodes, "
        f"{fams['rnd57']} at the outside codes 5-7 held to RNE, and "
        f"{n_aug['augadd']} augadd + {n_aug['augerr']} augerr against "
        f"cft_golden.augmented"
        f"{'' if en_aug else ' - R21 not driven (CFT_EN_AUGADD=0)'})")
