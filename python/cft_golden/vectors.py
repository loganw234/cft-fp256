# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Deterministic conformance-vector generation.

One generator feeds three consumers: the pytest self-tests, the cocotb
testbenches, and vectors/gen_vectors.py (the on-disk conformance sets a
GPU-side library is scored against). Everything is seeded; the same
(format, seed, count) always yields the same cases, which is the point.

The random strategies are chosen for where FMA implementations actually
break: alignment extremes, near-total cancellation, the subnormal
boundary, rounding carry-out, and signed-zero plumbing.
"""

import random

from .formats import FpFormat
from . import softfloat as sf


def interesting_operands(fmt: FpFormat):
    """The directed operand set: every special, every boundary, and a
    few rounding tripwires."""
    ops = []
    for s in (0, 1):
        ops += [
            sf.zero_bits(fmt, s),
            sf.min_subnormal_bits(fmt, s),
            sf.max_subnormal_bits(fmt, s),
            sf.min_normal_bits(fmt, s),
            sf.min_normal_bits(fmt, s) | 1,          # min normal + 1 ulp
            sf.one_bits(fmt, s),
            sf.one_bits(fmt, s) | 1,                 # 1 + 1 ulp
            sf.one_bits(fmt, s) - 1,                 # largest value < 1
            sf.one_bits(fmt, s) | fmt.man_mask,      # all-ones mantissa (carry bait)
            (sf.one_bits(fmt, s) + (1 << fmt.man_w)),  # 2.0
            (sf.one_bits(fmt, s) + (1 << fmt.man_w)) | (1 << (fmt.man_w - 1)),  # 3.0
            sf.max_normal_bits(fmt, s),
            sf.max_normal_bits(fmt, s) ^ 1,          # max normal - 1 ulp
            sf.inf_bits(fmt, s),
        ]
    ops += [sf.qnan_bits(fmt), sf.snan_bits(fmt)]
    # a NaN with a payload, to prove canonicalisation
    ops += [sf.qnan_bits(fmt) | 0x5, fmt.sign_mask | sf.qnan_bits(fmt)]
    return ops


def directed_cases(fmt: FpFormat, budget: int, seed: int = 1):
    """Deterministic sample of the specials cross-product, all four ops.

    The full cross of interesting operands is exhaustive for pairs and
    sampled for triples, trimmed to `budget` cases total.
    """
    rng = random.Random(seed)
    ops = interesting_operands(fmt)
    cases = []
    # every pair, through add/sub/mul (c or b unused there)
    for xa in ops:
        for xb in ops:
            cases.append((sf.OP_ADD, xa, 0, xb))
            cases.append((sf.OP_SUB, xa, 0, xb))
            cases.append((sf.OP_MUL, xa, xb, 0))
    # sampled triples through fma
    n_fma = max(budget - len(cases), budget // 2)
    for _ in range(n_fma):
        cases.append((sf.OP_FMA, rng.choice(ops), rng.choice(ops), rng.choice(ops)))
    rng.shuffle(cases)
    return cases[:budget] if budget < len(cases) else cases


def _rand_bits(rng, fmt):
    return rng.getrandbits(fmt.width)


def _rand_finite(rng, fmt, e_lo, e_hi):
    """Random finite value with biased exponent field in [e_lo, e_hi]."""
    ef = rng.randint(max(0, e_lo), min(fmt.exp_mask - 1, e_hi))
    frac = rng.getrandbits(fmt.man_w)
    if ef == 0 and frac == 0:
        frac = 1
    return (rng.getrandbits(1) << (fmt.width - 1)) | (ef << fmt.man_w) | frac


def _with_exponent_near(rng, fmt, target_unbiased):
    ef = target_unbiased + fmt.bias
    ef = max(0, min(fmt.exp_mask - 1, ef))
    frac = rng.getrandbits(fmt.man_w)
    return (rng.getrandbits(1) << (fmt.width - 1)) | (ef << fmt.man_w) | frac


def random_cases(fmt: FpFormat, count: int, seed: int = 2):
    """Seeded adversarial random cases, all four ops."""
    rng = random.Random(seed ^ fmt.width)
    p = fmt.prec
    cases = []
    while len(cases) < count:
        strat = rng.randrange(6)
        op = rng.choice((sf.OP_FMA, sf.OP_FMA, sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL))
        if strat == 0:
            # raw uniform bit patterns
            xa, xb, xc = (_rand_bits(rng, fmt) for _ in range(3))
        elif strat == 1:
            # subnormal boundary: exponent fields clustered at 0
            xa = _rand_finite(rng, fmt, 0, 2)
            xb = _rand_finite(rng, fmt, 0, 2)
            xc = _rand_finite(rng, fmt, 0, 2)
        elif strat == 2:
            # overflow boundary: exponent fields clustered at the top
            top = fmt.exp_mask - 1
            xa = _rand_finite(rng, fmt, top - 2, top)
            xb = _rand_finite(rng, fmt, top - 2, top)
            xc = _rand_finite(rng, fmt, top - 2, top)
        elif strat == 3:
            # alignment stress: c's exponent swept across the product's
            # entire alignment window, from far-below-sticky to far-above
            xa = _rand_finite(rng, fmt, 1, fmt.exp_mask - 2)
            xb = _rand_finite(rng, fmt, 1, fmt.exp_mask - 2)
            ea = ((xa >> fmt.man_w) & fmt.exp_mask) - fmt.bias
            eb = ((xb >> fmt.man_w) & fmt.exp_mask) - fmt.bias
            delta = rng.randint(-(2 * p + 8), 2 * p + 8)
            xc = _with_exponent_near(rng, fmt, ea + eb + delta)
            op = sf.OP_FMA
        elif strat == 4:
            # near-total cancellation: c = -(a*b rounded), so the fused
            # sum is exactly the negated rounding error of the product
            xa = _rand_finite(rng, fmt, 1, fmt.exp_mask - 2)
            xb = _rand_finite(rng, fmt, 1, fmt.exp_mask - 2)
            prod, _ = sf.mul(fmt, xa, xb)
            if sf.is_nan(fmt, prod):
                continue
            xc = sf.negate(fmt, prod)
            op = sf.OP_FMA
        else:
            # signed zeros and exact ties: force trailing patterns
            xa = _rand_finite(rng, fmt, fmt.bias - 2, fmt.bias + 2) & ~1
            xb = sf.one_bits(fmt, rng.getrandbits(1))
            xc = rng.choice((sf.zero_bits(fmt, 0), sf.zero_bits(fmt, 1),
                             sf.negate(fmt, xa), xa | 1))
        cases.append((op, xa, xb, xc))
    return cases


def testset(fmt: FpFormat, directed_budget: int, random_count: int, seed: int = 3):
    """The canonical combined set used by the RTL testbenches.

    Arithmetic only. The non-arithmetic opcodes take the same operands
    but do not go through the steering mux, so the benches build them
    separately; simple_cases() below is what the published vector sets
    use for them.
    """
    return directed_cases(fmt, directed_budget, seed) + \
        random_cases(fmt, random_count, seed + 1)


def simple_cases(fmt: FpFormat, per_op: int, seed: int = 5):
    """Cases for every non-arithmetic opcode, plus the unassigned ones.

    These belong in the published sets for the same reason the
    arithmetic does: the vectors are how an independent implementation
    is scored, and a set covering four of twenty-three opcodes scores
    almost nothing. The specials pool is weighted heavily here because
    that is where these operations differ from each other at all -
    min and minnum agree on every ordinary pair and part company only
    on NaNs, and abs/select part company from arithmetic only on NaN
    payloads and signed zeros.

    Shift counts get their own treatment: a uniformly random b is
    almost always a huge shift, so the interesting small counts and the
    modulo-width wrap points would never appear by chance.
    """
    rng = random.Random(seed ^ (fmt.width * 7919))
    pool = interesting_operands(fmt)
    shifty = [0, 1, 2, fmt.man_w, fmt.width - 1, fmt.width, fmt.width + 1,
              2 * fmt.width - 1]
    cases = []
    # 15, 26 and 255 are unassigned: one inside the float block, one
    # just past the reductions, one at the top of the byte. 24 used to
    # stand here and cannot any more - it is CFT_SUM now, which is the
    # exact hazard docs/DETERMINISM.md warns about for anyone who
    # issued an unassigned opcode early.
    for op in sf.SIMPLE_OPS + (15, 26, 255):
        is_shift = op in (sf.OP_ISHL, sf.OP_ISHR)
        for i in range(per_op):
            if i % 3 == 0:
                xa, xb = rng.choice(pool), rng.choice(pool)
            else:
                xa = _rand_bits(rng, fmt)
                xb = rng.choice(pool) if i % 3 == 1 else _rand_bits(rng, fmt)
            if is_shift:
                xb = rng.choice(shifty)
            # select reads c, and a c of +-0 versus anything else is
            # the whole decision, so make both outcomes common
            xc = rng.choice(pool + [sf.zero_bits(fmt, 0), sf.zero_bits(fmt, 1),
                                    sf.one_bits(fmt)])
            cases.append((op, xa, xb, xc))
    rng.shuffle(cases)
    return cases
