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
    # 15, 28 and 255 are unassigned: one inside the float block, one
    # just past the seeds, one at the top of the byte. This list has
    # now shed a member TWICE - 24 became CFT_SUM, then 26 became
    # RECIP_SEED - which is the exact hazard docs/DETERMINISM.md warns
    # about for anyone who issued an unassigned opcode early: the
    # conformance replayer refuses a set whose "reserved" case has
    # since been assigned, and that refusal is what caught 26 here.
    #
    # The seed opcodes themselves get the same per-op budget as the
    # rest: they are unary and quiet, but their special classes (the
    # limit values, and the flush-at-input rule for subnormals) are
    # contract surface an independent implementation can get wrong.
    for op in sf.SIMPLE_OPS + sf.SEED_OPS + (15, 28, 255):
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


# ---- the transcendental sets -----------------------------------------

def _val(fmt, sign, m, e):
    """The representable value (-1)^sign * m * 2^e, or None when the
    format cannot hold it exactly - so a family can be written once and
    thin itself out at fp32."""
    bits, flags = sf.round_pack(fmt, sign, m, e, sf.RND_RNE)
    return None if flags else bits


def _extend(out, *values):
    for v in values:
        if v is not None:
            out.append(v)


def transcend_unary_pool(fmt: FpFormat, extra: int, seed: int = 9):
    """Operands where a transcendental can actually be got wrong.

    Random bit patterns score almost nothing here: they never land on an
    exact case, never straddle an overflow threshold, and never sit close
    enough to a rounding boundary to matter. Every family below is one an
    implementation can pass by luck and fail on purpose.
    """
    import mpmath

    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ fmt.width)
    out = list(interesting_operands(fmt))
    _extend(out, one + 1, one - 1, sf.one_bits(fmt, 1) + 1,
            sf.one_bits(fmt, 1) - 1)

    # integers: every exp2 exact case, and the ones past both ends
    for k in list(range(1, 25)) + [p, 2 * p, fmt.emax - 1, fmt.emax,
                                   fmt.emax + 1, fmt.emin, fmt.emin - 1,
                                   fmt.emin - fmt.man_w,
                                   fmt.emin - fmt.man_w - 1]:
        _extend(out, _val(fmt, 0, abs(k), 0), _val(fmt, 1, abs(k), 0))

    # powers of two (log2 is exact there) with a neighbour each side
    for k in (-3, -1, 1, 2, 10, fmt.emax, fmt.emin,
              fmt.emin - fmt.man_w + 1):
        b = _val(fmt, 0, 1, k)
        if b is not None:
            _extend(out, b, b + 1, b - 1)

    # powers of ten (log10 is exact there), likewise
    k = 0
    while 5 ** k < (1 << p):
        b = _val(fmt, 0, 5 ** k, k)
        if b is None:
            break
        _extend(out, b, b + 1, b - 1)
        k += 1

    # the exponential's overflow and underflow edges: n*ln2 for the n
    # that matter, rounded and then walked a couple of ulps either way
    mpmath.mp.prec = 4 * p + 64
    for n in (fmt.emax, fmt.emax + 1, fmt.emin, fmt.emin - fmt.man_w,
              fmt.emin - fmt.man_w - 1, -(p + 2), -(p + 3), p + 1):
        t = mpmath.mpf(n) * mpmath.log(2)
        man, ex = mpmath.libmp.to_man_exp(t._mpf_)
        b = sf.round_pack(fmt, 1 if man < 0 else 0, abs(int(man)), int(ex),
                          sf.RND_RNE)[0]
        _extend(out, b, b + 1, b - 1, b + 2, b - 2)

    # below the neighbour thresholds, and just above them
    for k in (p + 2, p + 3, p + 4, p + 5, p + 10, 2 * p):
        for m, e in ((1, -k), (3, -k - 1)):
            _extend(out, _val(fmt, 0, m, e), _val(fmt, 1, m, e))

    out += [_rand_bits(rng, fmt) for _ in range(extra)]
    return sorted({b & ((1 << fmt.width) - 1) for b in out})


def transcend_pow_pairs(fmt: FpFormat, extra: int, seed: int = 10):
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 31))
    pairs = []
    specials = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.inf_bits(fmt),
                sf.inf_bits(fmt, 1), sf.qnan_bits(fmt), sf.snan_bits(fmt),
                one, sf.one_bits(fmt, 1), _val(fmt, 0, 3, -1),
                _val(fmt, 1, 3, -1), _val(fmt, 0, 1, 1), _val(fmt, 1, 1, 1),
                _val(fmt, 0, 3, 0), _val(fmt, 1, 3, 0),
                sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)]
    for a in specials:
        for b in specials:
            pairs.append((a, b))
    # integer exponents: exact until the odd part outruns the format
    for base in (2, 3, 5, 7, 10, 4097):
        if base.bit_length() > p:
            continue
        for n in (1, 2, 3, 4, 5, 8, 17, p - 1, p, p + 1, p + 2, -1, -2, -3,
                  1000):
            b = _val(fmt, 1 if n < 0 else 0, abs(n), 0)
            if b is None:
                continue
            for sgn in (0, 1):
                pairs.append((_val(fmt, sgn, base, 0), b))
    # dyadic exponents against perfect powers and near-misses
    for m in (4, 9, 16, 25, 81, 256, 625, 1024):
        if m.bit_length() > p:
            continue
        mb = _val(fmt, 0, m, 0)
        for ey in (-1, -2, -3):
            pairs.append((mb, _val(fmt, 0, 1, ey)))
            pairs.append((mb, _val(fmt, 0, 3, ey - 1)))
            pairs.append((mb + 1, _val(fmt, 0, 1, ey)))
            pairs.append((mb, _val(fmt, 1, 1, ey)))
    # a base one ulp from 1 against exponents across the whole range -
    # the family a fixed-point evaluator cannot survive
    for dy in (1, 3, 1 << (p // 2), (1 << fmt.man_w) - 1):
        for ey in (0, 10, p, 2 * p, fmt.emax // 2, fmt.emax - 1, fmt.emax,
                   -(p + 20), -(p + 3)):
            b = _val(fmt, 0, 1, ey)
            if b is None:
                continue
            for base in (one + dy, one - dy):
                pairs.append((base, b))
                pairs.append((base, b | fmt.sign_mask))
    # The one family measured to make the Ziv loop escalate at all:
    # pow(1+u, -(1+u)) is 1 - u + u^3/2, so it sits three precisions
    # from the representable 1-u and the first attempt cannot see the
    # gap. The u^2 term cancels only for this exponent, and no
    # representable y can cancel the u^3 one as well, which is the
    # argument that bounds the whole family at 3p bits.
    for du in (1, 2, 3, 5):
        for dv in (0, 1, 2, 3, 5):
            base = one + du
            expo = (one + dv) | fmt.sign_mask
            pairs.append((base, expo))
            pairs.append((one - du, expo))
            pairs.append((base, one + dv))
    for _ in range(extra):
        pairs.append((_rand_bits(rng, fmt), _rand_bits(rng, fmt)))
    return [(a, b) for a, b in pairs if a is not None and b is not None]


def transcend_hypot_pairs(fmt: FpFormat, extra: int, seed: int = 11):
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 61))
    pairs = []
    for (x, y) in ((3, 4), (5, 12), (8, 15), (7, 24), (20, 21), (9, 40),
                   (1, 1), (2, 2), (6, 8), (12, 16)):
        if max(x, y).bit_length() > p:
            continue
        for sx in (0, 1):
            for sy in (0, 1):
                pairs.append((_val(fmt, sx, x, 0), _val(fmt, sy, y, 0)))
        pairs.append((_val(fmt, 0, x, 0), _val(fmt, 0, y, 0) + 1))
        pairs.append((_val(fmt, 0, x, 0) - 1, _val(fmt, 0, y, 0)))
        for e in (fmt.emax - 8, fmt.emin + 2, -p, fmt.emin - fmt.man_w):
            pairs.append((_val(fmt, 0, x, e), _val(fmt, 0, y, e)))
    # widely different magnitudes, straddling the dominance threshold
    for k in (1, 2, p // 2 - 1, p // 2, p // 2 + 1, p, 2 * p, fmt.emax // 2,
              fmt.emax):
        pairs.append((one, _val(fmt, 0, 1, -k)))
        pairs.append((_val(fmt, 0, 1, -k), one))
        pairs.append((sf.max_normal_bits(fmt), _val(fmt, 0, 1, fmt.emax - k)))
    pairs += [
        (sf.max_normal_bits(fmt), sf.max_normal_bits(fmt)),
        (sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)),
        (sf.min_subnormal_bits(fmt), sf.min_subnormal_bits(fmt)),
        (sf.max_subnormal_bits(fmt), sf.max_subnormal_bits(fmt)),
        (sf.min_normal_bits(fmt), sf.min_subnormal_bits(fmt)),
        (sf.zero_bits(fmt, 1), sf.zero_bits(fmt, 1)),
        (sf.zero_bits(fmt), sf.max_normal_bits(fmt, 1)),
        (sf.inf_bits(fmt), sf.qnan_bits(fmt)),
        (sf.qnan_bits(fmt), sf.inf_bits(fmt, 1)),
        (sf.snan_bits(fmt), sf.inf_bits(fmt)),
        (sf.qnan_bits(fmt), sf.qnan_bits(fmt)),
    ]
    for _ in range(extra):
        pairs.append((_rand_bits(rng, fmt), _rand_bits(rng, fmt)))
    return [(a, b) for a, b in pairs if a is not None and b is not None]


def trig_unary_pool(fmt: FpFormat, extra: int, seed: int = 12):
    """Operands where a TRIGONOMETRIC function can be got wrong, which
    is a different list from the exponential's.

    The families here are the ones an implementation passes by luck and
    fails on purpose: the half-integers and quarter-integers where
    sinPi and tanPi are exact, the integers where sinPi's zero takes the
    sign of the argument rather than the parity of n, the two sides of
    1 where asin's domain ends, and every neighbour threshold this set
    has - each with a neighbour above and below, so an exactness test
    has to be right rather than optimistic.
    """
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 101))
    out = list(interesting_operands(fmt))
    _extend(out, one + 1, one - 1, sf.one_bits(fmt, 1) + 1,
            sf.one_bits(fmt, 1) - 1)

    # half-integers (sinPi = +-1, cosPi = +0, tanPi a pole),
    # quarter-integers (tanPi = +-1) and integers (sinPi = +-0), each
    # with a neighbour on both sides
    for m, e in ([(k, -1) for k in (1, 3, 5, 7, 9, 17, 33)] +
                 [(k, -2) for k in (1, 3, 5, 7, 9, 11, 13)] +
                 [(k, 0) for k in (1, 2, 3, 4, 5, 8, 17)] +
                 [(k, -3) for k in (1, 3, 5, 7, 11, 13)]):
        for sgn in (0, 1):
            b = _val(fmt, sgn, m, e)
            if b is not None:
                _extend(out, b, b + 1, b - 1)

    # the top of the range, where every representable value is an even
    # integer and sinPi is decided by integer arithmetic alone
    for k in (p - 1, p, p + 1, 2 * p, fmt.emax - 1, fmt.emax):
        for sgn in (0, 1):
            b = _val(fmt, sgn, 1, k)
            if b is not None:
                _extend(out, b, b - 1)

    # every neighbour threshold, and a step either side of it
    for k in (p // 2, p // 2 + 1, p // 2 + 2, p, p + 1, p + 2, p + 3,
              2 * p, 4 * p):
        for m, e in ((1, -k), (3, -k - 1)):
            for sgn in (0, 1):
                _extend(out, _val(fmt, sgn, m, e))

    # just inside and just outside the asin/acos domain
    for sgn in (0, 1):
        b = _val(fmt, sgn, (1 << p) - 1, -p)
        if b is not None:
            _extend(out, b, b - 1)

    out += [_rand_bits(rng, fmt) for _ in range(extra)]
    return sorted({b & ((1 << fmt.width) - 1) for b in out})


def trig_atan2_pairs(fmt: FpFormat, extra: int, seed: int = 13):
    """atan2 ON the axes and diagonals and one ulp off them.

    Every axis and diagonal is an EXACT case of atan2Pi and an inexact
    rounding of a multiple of pi for atan2, so one pair scores both
    halves of the design. The dyadic-quotient family is here too,
    including minSubnormal over two, whose quotient is a subnormal
    MIDPOINT rather than a representable number."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 211))
    axes = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), one,
            sf.one_bits(fmt, 1), sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
            sf.qnan_bits(fmt), sf.snan_bits(fmt), _val(fmt, 0, 1, 1),
            _val(fmt, 1, 1, 1), _val(fmt, 0, 3, 0), _val(fmt, 1, 3, 0),
            sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt),
            sf.min_subnormal_bits(fmt, 1)]
    pairs = [(a, b) for a in axes for b in axes]
    for e in (0, 1, -1, p, -p, fmt.emax - 1, fmt.emin,
              fmt.emin - fmt.man_w):
        b = _val(fmt, 0, 1, e)
        if b is None:
            continue
        for sy in (0, 1):
            for sx in (0, 1):
                y = b | (fmt.sign_mask if sy else 0)
                x = b | (fmt.sign_mask if sx else 0)
                pairs += [(y, x), (y + 1, x), (y, x + 1), (y - 1, x)]
    two = _val(fmt, 0, 1, 1)
    sub = sf.min_subnormal_bits(fmt)
    pairs += [(sub, two), (sub, _val(fmt, 0, 1, 2)), (sub, one),
              (sub | fmt.sign_mask, two), (sub, _val(fmt, 1, 1, 1))]
    for k in (p, p + 4, 2 * p, 4 * p):
        y = _val(fmt, 0, 1, -k)
        if y is None:
            continue
        pairs += [(y, one), (y, _val(fmt, 1, 1, 0)), (y, two),
                  (y | fmt.sign_mask, one), (y, _val(fmt, 0, 3, 0))]
    for k in (p, p + 1, p + 2, p + 3, 2 * p):
        big, small = _val(fmt, 0, 1, k), _val(fmt, 0, 1, -k)
        if big is None or small is None:
            continue
        pairs += [(big, one), (one, big), (small, one), (one, small),
                  (big, _val(fmt, 1, 1, 0)), (small, _val(fmt, 1, 1, 0))]
    pairs += [(_rand_bits(rng, fmt), _rand_bits(rng, fmt))
              for _ in range(extra)]
    return [(a, b) for a, b in pairs if a is not None and b is not None]


#: How coarsely the reduction's worst-case search sweeps the binades
#: when it seeds the radian pool, and how many of the deepest it keeps.
#: Deliberately coarser than host/tests/transcend_check.py's sweep: a
#: vector set is replayed by every consumer on every run, so its pool
#: buys breadth where the check harness buys depth.
_WORST_SWEEP = {"fp32": (8, 4), "fp64": (64, 4),
                "fp128": (2048, 3), "fp256": (32768, 3)}


def _reduction_worst_cases(fmt: FpFormat):
    """The arguments closest to a multiple of pi/2 that the measurement
    finds, as encodings with a grid neighbour on either side.

    Drawn from host/tools/pi_worstcase.py rather than typed, for the
    reason every constant in this project is derived rather than
    transcribed: a list of "known hard cases" copied from a paper is a
    list nobody can regenerate, and one of them being wrong would make a
    vector set that passes mean nothing. The tool reads the same
    host/src/mp_2opi.h the library reduces against, so these are the
    arguments that make THIS reduction work hardest."""
    import sys
    from pathlib import Path
    tools = Path(__file__).resolve().parents[2] / "host" / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import pi_worstcase
    stride, top = _WORST_SWEEP[fmt.name]
    return pi_worstcase.worst_encodings(fmt, stride, top)


def radian_unary_pool(fmt: FpFormat, extra: int, seed: int = 14):
    """Operands where sin, cos or tan of a RADIAN argument can be got
    wrong - a third list again, because what catches sinPi does not
    catch sin.

    The argument reduction is the whole of what phase 3 added, so the
    pool is what stresses it: every power of two across the exponent
    range, because the window's START is the argument's exponent; the
    deepest cancellations the continued-fraction search finds, which are
    what make the window WIDEN; and the tiny-argument thresholds of all
    three functions, straddled."""
    p = fmt.prec
    rng = random.Random(seed ^ (fmt.width * 307))
    out = list(interesting_operands(fmt))

    step = 1 if fmt.width <= 64 else max(1, (fmt.emax + 1) // 48)
    for k in range(fmt.emin - fmt.man_w, fmt.emax + 1, step):
        for sgn in (0, 1):
            _extend(out, _val(fmt, sgn, 1, k))
    for k in (fmt.emax, fmt.emax - 1, 0, 1, 2, p, 2 * p, fmt.emin,
              fmt.emin - fmt.man_w):
        for sgn in (0, 1):
            b = _val(fmt, sgn, 1, k)
            if b is not None:
                _extend(out, b, b - 1)

    out += _reduction_worst_cases(fmt)

    for k in (p // 2 - 1, p // 2, p // 2 + 1, p // 2 + 2, p, p + 2, 2 * p):
        for m, e in ((1, -k), (3, -k - 1)):
            for sgn in (0, 1):
                _extend(out, _val(fmt, sgn, m, e))

    out += [_rand_bits(rng, fmt) for _ in range(extra)]
    return sorted({b & ((1 << fmt.width) - 1) for b in out})


def hyperbolic_unary_pool(fmt: FpFormat, extra: int, seed: int = 15):
    """Operands for the six hyperbolics, whose domains differ from each
    other and from everything else in the set.

    Around 1 from both sides, which is acosh's domain edge and atanh's
    pole; the sinh/cosh overflow threshold walked two ulps either way;
    the argument where tanh stops being separable from 1; every tiny
    threshold in the family; and negatives throughout, since three of
    the six are odd, two are invalid below their domain and one is
    even."""
    import mpmath

    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 409))
    out = list(interesting_operands(fmt))
    _extend(out, one + 1, one - 1, sf.one_bits(fmt, 1) + 1,
            sf.one_bits(fmt, 1) - 1)

    for m, e in ([(k, 0) for k in (1, 2, 3, 4, 5, 8, 17, 100)] +
                 [(k, -1) for k in (1, 3, 5, 7, 9)] +
                 [(k, -2) for k in (1, 3, 5, 7)]):
        for sgn in (0, 1):
            b = _val(fmt, sgn, m, e)
            if b is not None:
                _extend(out, b, b + 1, b - 1)

    mpmath.mp.prec = 4 * p + 64
    for n in (fmt.emax, fmt.emax + 1, fmt.emax + 2, fmt.emin,
              fmt.emin - fmt.man_w):
        t = mpmath.mpf(n) * mpmath.log(2)
        man, ex = mpmath.libmp.to_man_exp(t._mpf_)
        b = sf.round_pack(fmt, 1 if man < 0 else 0, abs(int(man)),
                          int(ex), sf.RND_RNE)[0]
        for d in (-2, -1, 0, 1, 2):
            _extend(out, b + d, (b + d) | fmt.sign_mask)

    bl = (p + 2).bit_length()
    for k in (bl - 1, bl, bl + 1):
        for sgn in (0, 1):
            b = _val(fmt, sgn, 1, k)
            if b is not None:
                _extend(out, b, b - 1, b + 1)

    for k in (p // 2 - 1, p // 2, p // 2 + 1, p // 2 + 2, p, p + 2, 2 * p,
              4 * p):
        for m, e in ((1, -k), (3, -k - 1)):
            for sgn in (0, 1):
                _extend(out, _val(fmt, sgn, m, e))

    out += [_rand_bits(rng, fmt) for _ in range(extra)]
    return sorted({b & ((1 << fmt.width) - 1) for b in out})


def transcend_cases(fmt: FpFormat, extra: int, seed: int = 9):
    """(fn, a, b) triples for all twenty-nine transcendentals, in the
    order gen_vectors.py writes them. b is 0 for the unary twenty-five,
    which do not emit it at all.

    Four operand pools, because the families are different: the
    exponential set turns on exact powers and overflow thresholds, the
    Pi-trigonometric set on half-integers and the edge of the asin
    domain, the radian set on the argument reduction's worst cases, and
    the hyperbolic set on its own domain edges. Each slice of
    TRANSCEND_FNS is named by INDEX below, so appending a phase does not
    silently re-point an earlier one at the wrong pool."""
    from .transcend import TRANSCEND_ARITY, TRANSCEND_FNS

    pool = transcend_unary_pool(fmt, extra, seed)
    tpool = trig_unary_pool(fmt, extra, seed + 3)
    rpool = radian_unary_pool(fmt, extra, seed + 5)
    hpool = hyperbolic_unary_pool(fmt, extra, seed + 6)
    trig = set(TRANSCEND_FNS[9:20])
    radian = set(TRANSCEND_FNS[20:23])
    hyper = set(TRANSCEND_FNS[23:])
    assert radian == {"sin", "cos", "tan"}, TRANSCEND_FNS[20:23]
    cases = []
    for fn in TRANSCEND_FNS:
        if TRANSCEND_ARITY[fn] == 1:
            if fn in radian:
                src = rpool
            elif fn in hyper:
                src = hpool
            elif fn in trig:
                src = tpool
            else:
                src = pool
            cases += [(fn, a, 0) for a in src]
        elif fn == "pow":
            cases += [(fn, a, b)
                      for a, b in transcend_pow_pairs(fmt, extra, seed + 1)]
        elif fn == "hypot":
            cases += [(fn, a, b)
                      for a, b in transcend_hypot_pairs(fmt, extra, seed + 2)]
        else:
            cases += [(fn, a, b)
                      for a, b in trig_atan2_pairs(fmt, extra, seed + 4)]
    return cases


# ---- the character-conversion sets -----------------------------------

# Sequences that are NOT in 5.12's syntax and must be refused rather
# than guessed at. Kept free of quotes and backslashes so the emitted
# JSON needs no escapes and cft_conformance's scanner needs no
# unescaper - gen_vectors.py asserts that rather than trusting it.
DECIMAL_REFUSALS = (
    "", "+", "-", ".", "-.", "e5", "1e", "1e+", "1e-", "1 ", " 1", "1.5.5",
    "1,5", "0x1p+0", "1p5", "--1", "1-", "nan(", "nan()", "nan(x)",
    "nan(0x)", "nan(-1)", "infi", "nanx", "snan()", "1.5e5x", "1_000",
)

HEX_REFUSALS = (
    "", "0x", "0x1", "0x.p+0", "0xp+1", "0x1p", "0x1p+", "0x1.8",
    "1.8p+3", "0x1.8e+3", "0x1.8p+3x", "0xg.1p+0", "0x1..8p+0",
    " 0x1p+0", "1e5", "0x1p+0.5",
)

# Every spelling of every special 5.12.1 names, read by both parsers.
SPECIAL_SEQUENCES = (
    "inf", "-inf", "+inf", "INF", "Inf", "infinity", "-INFINITY",
    "nan", "-nan", "NaN", "NAN", "snan", "-snan", "SNaN",
    "nan(1)", "nan(0x1)", "-nan(0x2)", "NAN(0X3)", "snan(0x1)",
    "-snan(5)", "0", "-0", "+0", "0.0", "-0.0e10",
)


def character_cases(fmt: FpFormat, extra: int, seed: int = 20):
    """The clause-5.12 and 9.7 cases, as tagged tuples gen_vectors.py
    turns into records:

        ("from_decimal", s)          a sequence to convert in
        ("from_decimal_refuse", s)   a sequence that must be refused
        ("to_decimal", bits, h)      an encoding to write out, h digits
                                     (0 = the exact conversion)
        ("from_hex", s) / ("from_hex_refuse", s) / ("to_hex", bits)
        ("payload", op, bits)        one of the three 9.7 operations

    The families are the ones a conversion is actually got wrong on:
    exact halfway sequences that only the last digit decides, digit
    strings far longer than the format's precision, exponents inside
    and past the bands where the library answers without computing,
    subnormal landings, the round-trip digit counts at exactly Pmin and
    at Pmin - 1, and every spelling of every special. Random digit
    strings are in there too, but they are the part that scores least:
    a uniformly random decimal essentially never lands on a rounding
    boundary."""
    from . import chars

    rng = random.Random(seed)
    h = chars.pmin(fmt)
    cases = []

    # -- encodings to write out ------------------------------------
    outs = list(interesting_operands(fmt))
    outs += [sf.qnan_bits(fmt) | 1, sf.snan_bits(fmt, 1),
             sf.qnan_bits(fmt) | (chars.max_payload(fmt) - 1),
             fmt.sign_mask | sf.snan_bits(fmt, 3)]
    for k in (1, 3, 5, 9, 11):
        for s in (0, 1):
            _extend(outs, _val(fmt, s, k, -3), _val(fmt, s, k * 5, -1))
    span = 30 if fmt.width > 64 else fmt.emax
    for _ in range(extra):
        m = rng.getrandbits(fmt.prec) | (1 << (fmt.prec - 1))
        outs.append(sf.round_pack(fmt, rng.getrandbits(1), m,
                                  rng.randint(-span, span) - fmt.man_w,
                                  sf.RND_RNE)[0])
    for bits in outs:
        # The wide formats' exponent extremes are left out of the dense
        # sweep and covered deliberately just below. Their exact
        # decimals run to tens of thousands of digits, which the
        # library derives in full at every digit count (cft.h carries
        # the cost note), so sweeping them here would put minutes of
        # replay into every consumer's run and add no case the edge
        # pass does not already carry.
        kind, _, em, ee, _, _ = chars._decode(fmt, bits)
        dense = (fmt.width <= 64 or kind != "finite" or
                 abs(ee + em.bit_length() - 1) <= 400)
        for digits in (0, 1, 2, h - 1, h, h + 3):
            if dense:
                cases.append(("to_decimal", bits, digits))
        cases.append(("to_hex", bits))

    # The ends of the exponent range, where the exact decimal runs to
    # tens of thousands of digits and the powering path is the whole
    # cost of the conversion. A deliberate handful, not a sample: at
    # fp256 one of these is a 183,000-character sequence.
    edges = [sf.min_subnormal_bits(fmt, 0), sf.min_subnormal_bits(fmt, 1),
             sf.max_subnormal_bits(fmt, 0), sf.min_normal_bits(fmt, 0),
             sf.max_normal_bits(fmt, 0)]
    for bits in edges:
        for digits in (0, 1, h - 1, h):
            cases.append(("to_decimal", bits, digits))
        cases.append(("to_hex", bits))

    # -- sequences to read in --------------------------------------
    seqs = list(SPECIAL_SEQUENCES)
    seqs += ["1", "-1", "1.", ".5", "1.5", "1e0", "1E0", "1e+0", "10e-1",
             "0.1", "2.5", "1.25", "9" * 30, "0." + "0" * 25 + "1",
             "1e999999999999", "-1e-999999999999", "1e99999", "1e-99999"]
    for bits in edges + [sf.one_bits(fmt, 0)]:
        text, _ = chars.to_decimal(fmt, bits, 0)
        seqs.append(text)
        seqs.append(chars.to_decimal(fmt, bits, h)[0])
        seqs.append(chars.to_decimal(fmt, bits, h - 1)[0])

    # Exact halfway sequences between neighbouring encodings, and the
    # same sequence nudged either side of the tie: the cases where the
    # attribute, and nothing else, decides the answer.
    for bits in (sf.one_bits(fmt, 0), sf.min_normal_bits(fmt, 0),
                 sf.min_subnormal_bits(fmt, 0), _val(fmt, 0, 3, -1)):
        if bits is None:
            continue
        k1, sign, m1, e1, _, _ = chars._decode(fmt, bits)
        k2, _, m2, e2, _, _ = chars._decode(fmt, bits + 1)
        if k1 != "finite" or k2 != "finite":
            continue
        e = min(e1, e2) - 1
        mid = ((m1 << (e1 - e)) + (m2 << (e2 - e))) // 2
        ds, exp10 = chars.exact_digits(mid, e)
        seqs.append(chars._format_finite(sign, ds, exp10))
        seqs.append(chars._format_finite(1, ds, exp10))
        seqs.append(chars._format_finite(sign, ds + "1", exp10))
        if ds[-1] != "0":
            seqs.append(chars._format_finite(
                sign, ds[:-1] + str(int(ds[-1]) - 1) + "9", exp10))

    for _ in range(extra * 2):
        nd = rng.randint(1, 40)
        d = "".join(rng.choice("0123456789") for _ in range(nd))
        k = rng.randint(-(fmt.emax // 3 + 20), fmt.emax // 3 + 20)
        seqs.append(("-" if rng.getrandbits(1) else "") + d + "e" + str(k))

    cases += [("from_decimal", s) for s in seqs]
    cases += [("from_decimal_refuse", s) for s in DECIMAL_REFUSALS]
    cases.append(("from_decimal_refuse", "nan(0x%x)" % chars.max_payload(fmt)))

    hexes = list(SPECIAL_SEQUENCES[:20])
    hexes += ["0x0p+0", "-0x0p+0", "0x1p+0", "-0x1p+0", "0X1P+0",
              "0x1.8p+1", "0x.8p+1", "0x8.p-3", "0x1p+999999999999",
              "0x1p-999999999999", "0xfffffffffffffffffffffffffffffffffp-4"]
    for bits in edges + [sf.one_bits(fmt, 0)]:
        hexes.append(chars.to_hex(fmt, bits))
    for _ in range(extra):
        nd = rng.randint(1, fmt.prec // 4 + 4)
        d = "".join(rng.choice("0123456789abcdefABCDEF") for _ in range(nd))
        e = rng.randint(-(fmt.emax + 30), fmt.emax + 30)
        hexes.append(("-" if rng.getrandbits(1) else "") + "0x" + d + "p" +
                     ("+" if e >= 0 else "") + str(e))
    cases += [("from_hex", s) for s in hexes]
    cases += [("from_hex_refuse", s) for s in HEX_REFUSALS]

    # -- the 9.7 payload operations --------------------------------
    pay = list(outs[:40])
    pay += [sf.qnan_bits(fmt), sf.snan_bits(fmt, 1),
            sf.qnan_bits(fmt) | (chars.max_payload(fmt) - 1),
            sf.zero_bits(fmt, 0), sf.zero_bits(fmt, 1),
            sf.one_bits(fmt, 0), sf.one_bits(fmt, 1)]
    # the admissibility edge: the largest admissible payload, the first
    # inadmissible one, and a non-integer just below both
    for v in (chars.max_payload(fmt) - 1, chars.max_payload(fmt)):
        _extend(pay, _val(fmt, 0, v, 0), _val(fmt, 1, v, 0),
                _val(fmt, 0, 2 * v - 1, -1))
    for op in ("get_payload", "set_payload", "set_payload_signaling"):
        cases += [("payload", op, bits) for bits in pay]
    return cases
