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
    # 15, 30 and 255 are unassigned: one inside the float block, one
    # just past the composed reductions, one at the top of the byte.
    # This list has now shed a member THREE times - 24 became CFT_SUM,
    # 26 became RECIP_SEED, and on 2026-09-03 28 became CFT_SUMSQ -
    # which is the exact hazard docs/DETERMINISM.md warns about for
    # anyone who issued an unassigned opcode early: the conformance
    # replayer refuses a set whose "reserved" case has since been
    # assigned, and that refusal is what caught 26 here, and 28 again.
    #
    # The seed opcodes themselves get the same per-op budget as the
    # rest: they are unary and quiet, but their special classes (the
    # limit values, and the flush-at-input rule for subnormals) are
    # contract surface an independent implementation can get wrong.
    for op in sf.SIMPLE_OPS + sf.SEED_OPS + (15, 30, 255):
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


# ---- the augmented arithmetic set (754-2019 9.5) ---------------------

def augmented_pairs(fmt: FpFormat, extra: int, seed: int = 16):
    """Operand pairs where an augmented operation can be got wrong.

    A fourth pool again, because what catches an FMA does not catch
    these. The three operations differ from ordinary add/sub/mul in
    exactly four places, and every family below aims at one of them:

    * THE TIE RULE. roundTiesTowardZero and roundTiesToEven part company
      only at an exact midpoint whose lower neighbour has an ODD last
      bit, so the pool builds midpoints at binade edges from odd
      significands on purpose - a random pair reaches one with
      probability about 2^-p. Every binade the format has is swept at
      fp32 and sampled at the wider rungs, because the tie rule and the
      subnormal grid interact only near emin and the overflow threshold
      only near emax.
    * THE ERROR TERM'S SIGN AT ZERO. Exact cancellation with every sign
      combination, so that "e takes the sign of r" is scored rather than
      assumed.
    * THE UNDERFLOW RULE. Sums whose residual lands subnormal (underflow
      with NO inexact - the combination that appears nowhere else in
      this contract) and products whose residual falls off the bottom of
      the grid entirely (underflow AND inexact, with the residual itself
      rounded).
    * THE OVERFLOW THRESHOLD. 9.5 rounds a magnitude EQUAL to
      2^emax x (2 - 2^-p) down to the largest finite and anything above
      it to an infinity, so both sides of that midpoint are here with
      the neighbours either side.
    """
    p = fmt.prec
    rng = random.Random(seed ^ (fmt.width * 601))
    pool = interesting_operands(fmt)
    pairs = [(a, b) for a in pool for b in pool]

    # Binade sweep. Exhaustive at fp32; the wider rungs take a stride
    # plus the edges, since a vector set is replayed on every run.
    step = 1 if fmt.width <= 32 else max(1, (fmt.emax - fmt.emin) // 24)
    exps = sorted({k for k in range(fmt.emin, fmt.emax + 1, step)} |
                  {fmt.emin, fmt.emin + 1, fmt.emin + p, -1, 0, 1, p, 2 * p,
                   fmt.emax - 1, fmt.emax} |
                  {fmt.emin - fmt.man_w, fmt.emin - fmt.man_w + 1,
                   fmt.emin - 1, fmt.emin - p // 2})
    mants = ((1 << (p - 1)), (1 << (p - 1)) | 1, (1 << p) - 1, (1 << p) - 2)
    for k in exps:
        for m in mants:
            x = _val(fmt, 0, m, k - (p - 1))
            if x is None:
                continue
            for sy in (0, 1):
                # half an ulp is the exact tie; a quarter and three
                # quarters straddle it; one ulp is the ordinary case
                for ym, ye in ((1, k - p), (1, k - p - 1), (3, k - p - 2),
                               (1, k - p + 1)):
                    y = _val(fmt, sy, ym, ye)
                    if y is not None:
                        pairs.append((x, y))
                        pairs.append((x | fmt.sign_mask, y))

    # Exact cancellation, every sign combination - the sign of e is the
    # sign of r there, and r's own is 6.3's.
    for m, e in ((1, 0), (3, -1), ((1 << p) - 1, -(p - 1)), (1, fmt.emax),
                 (1, fmt.emin), (1, fmt.emin - fmt.man_w)):
        x = _val(fmt, 0, m, e)
        if x is None:
            continue
        for sx in (0, 1):
            for sy in (0, 1):
                a = x | (fmt.sign_mask if sx else 0)
                b = x | (fmt.sign_mask if sy else 0)
                pairs += [(a, b), (a, b ^ fmt.sign_mask)]

    # Sums whose residual is subnormal: a normal x against a y so far
    # below it that the residual is y itself, walked across the
    # subnormal range. Underflow with no inexact.
    for k in (0, 1, p, 2 * p, fmt.emin + p, fmt.emax // 2, fmt.emax):
        x = _val(fmt, 0, 1, k)
        if x is None:
            continue
        for ye in (fmt.emin - fmt.man_w, fmt.emin - fmt.man_w + 1,
                   fmt.emin - 1, fmt.emin, fmt.emin + 1):
            for ym in (1, 3, (1 << p) - 1):
                y = _val(fmt, 0, ym, ye)
                if y is None:
                    continue
                pairs += [(x, y), (x, y | fmt.sign_mask),
                          (x | fmt.sign_mask, y)]

    # Products whose residual underflows: both operands near the bottom,
    # so the exact 2p-bit product has digits below the subnormal grid.
    for xe in (fmt.emin, fmt.emin + 1, fmt.emin + p // 2, fmt.emin - 1,
               fmt.emin - fmt.man_w // 2, fmt.emin - fmt.man_w):
        for xm in (1, 3, (1 << p) - 1, (1 << (p - 1)) | 1):
            x = _val(fmt, 0, xm, xe - (xm.bit_length() - 1))
            if x is None:
                continue
            for ye in (0, -1, -p // 2, -p, 1):
                for ym in (1, 3, (1 << p) - 1):
                    y = _val(fmt, 0, ym, ye - (ym.bit_length() - 1))
                    if y is not None:
                        pairs += [(x, y), (x | fmt.sign_mask, y)]

    # The overflow threshold: maxfinite plus half an ulp is EXACTLY the
    # midpoint 9.5 sends to maxfinite, and everything above it goes to
    # infinity. Both sides, both signs, plus the products that land
    # there.
    mx = sf.max_normal_bits(fmt)
    for ym, ye in ((1, fmt.emax - p), (1, fmt.emax - p + 1),
                   ((1 << p) - 1, fmt.emax - p - (p - 1)),
                   (1, fmt.emax - p - 1), (1, fmt.emax)):
        y = _val(fmt, 0, ym, ye)
        if y is None:
            continue
        pairs += [(mx, y), (mx, y | fmt.sign_mask),
                  (mx | fmt.sign_mask, y | fmt.sign_mask),
                  (mx ^ 1, y), (mx, mx), (mx, mx | fmt.sign_mask)]
    for m, e in ((1, 1), (3, -1), ((1 << p) - 1, -(p - 1)), (1, 0)):
        y = _val(fmt, 0, m, e)
        if y is not None:
            pairs += [(mx, y), (mx | fmt.sign_mask, y)]

    pairs += [(_rand_bits(rng, fmt), _rand_bits(rng, fmt))
              for _ in range(extra)]
    # A near-cancellation family: y within a few ulps of -x, where the
    # sum is tiny and the residual is exactly zero more often than
    # chance would have it.
    for _ in range(extra):
        x = _rand_finite(rng, fmt, 1, fmt.exp_mask - 2)
        pairs.append((x, (x ^ fmt.sign_mask) + rng.randint(-3, 3)))
    out, seen = [], set()
    for a, b in pairs:
        if a is None or b is None:
            continue
        key = (a & ((1 << fmt.width) - 1), b & ((1 << fmt.width) - 1))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def augmented_cases(fmt: FpFormat, extra: int, seed: int = 16):
    """(fn, a, b) triples for the three augmented operations, in the
    order gen_vectors.py writes them. One pool serves all three: the
    families that stress an augmented sum stress an augmented product
    at the other end of the same exponent range, and a pair that is
    dull for one is cheap to replay."""
    from .augmented import AUG_FNS
    pairs = augmented_pairs(fmt, extra, seed)
    return [(fn, a, b) for fn in AUG_FNS for a, b in pairs]


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


# ---- the reduction sets ----------------------------------------------
#
# A THIRD set type, and it needed one: the published sets before this
# carried no reductions at all. Both of the existing schemas are one
# case per LINE with a fixed number of single-element operands, and a
# reduction's operand is a whole vector whose length is part of the
# case - so a reduction could not be expressed in either without
# redefining what a line means for everything else.
#
# The scaled products need more than that again: they return a PAIR, so
# their cases carry two answers.

REDUCE_FNS = ("sum", "dot", "sumsq", "sumabs",
              "scaled_prod", "scaled_prod_sum", "scaled_prod_diff")

REDUCE_ARITY = {"sum": 1, "dot": 2, "sumsq": 1, "sumabs": 1,
                "scaled_prod": 1, "scaled_prod_sum": 2,
                "scaled_prod_diff": 2}

# Which functions deliver (pr, sf) rather than one element.
REDUCE_SCALED = ("scaled_prod", "scaled_prod_sum", "scaled_prod_diff")

# Lengths. The tree's shape is a function of n and of nothing else, so
# the sizes are the coverage: every small n, then each power of two
# with its neighbours either side, where a perfect subtree gives way to
# a lopsided one. A set that tried only round numbers would score a
# midpoint-splitting implementation as conforming.
REDUCE_LENGTHS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 13, 15, 16, 17,
                  31, 32, 33, 63, 64, 65, 127, 128, 129)

# Where the pools are sampled across every function as well - kept
# short because a case's cost is its length.
REDUCE_POOL_LENGTHS = (2, 5, 17, 33)


def reduce_pools(fmt: FpFormat, extra: int, seed: int = 20):
    """Named operand pools, each at least max(REDUCE_LENGTHS) long.

    Adversarial in the ways a reduction is: products that leave the
    format many times over in both directions, alternating magnitudes,
    signed zeros, an infinity beside a zero (the invalid row of a
    scaled product), NaNs beside infinities (the row 9.4 orders
    differently for sumSquare and sumAbs), and subnormals - whose
    normalised significands are what makes a scaled product's leaf
    extraction non-trivial.
    """
    need = max(REDUCE_LENGTHS)
    rng = random.Random(seed ^ fmt.width)
    big = sf.max_normal_bits(fmt)
    tiny = sf.min_subnormal_bits(fmt)
    pools = {}

    def cycle(values):
        return [values[i % len(values)] for i in range(need)]

    # ordinary work: exponents close enough together that the additions
    # actually interact rather than reducing to "the largest one wins"
    pools["ordinary"] = [_rand_finite(rng, fmt, fmt.bias - 6, fmt.bias + 6)
                         for _ in range(need)]

    # products that overflow and underflow the format many times over
    pools["huge"] = cycle([big, sf.max_normal_bits(fmt, 1),
                           big ^ 1, sf.max_normal_bits(fmt, 1) ^ 1])
    pools["tiny"] = cycle([tiny, sf.min_subnormal_bits(fmt, 1),
                           sf.max_subnormal_bits(fmt),
                           sf.min_normal_bits(fmt)])
    pools["alternating"] = cycle([big, tiny, sf.max_normal_bits(fmt, 1),
                                  sf.min_subnormal_bits(fmt, 1)])

    # signed zeros beside ordinary values: the sign of a scaled
    # product's zero is the XOR over every factor, and an exact
    # cancellation's zero follows the rounding attribute
    pools["zeros"] = cycle([sf.zero_bits(fmt, 0), sf.one_bits(fmt),
                            sf.zero_bits(fmt, 1), sf.one_bits(fmt, 1),
                            sf.zero_bits(fmt, 1), sf.zero_bits(fmt, 0)])

    # an infinity beside a zero: invalid for a scaled product, and
    # nothing at all for sumSquare
    pools["inf_zero"] = cycle([sf.inf_bits(fmt), sf.zero_bits(fmt),
                               sf.one_bits(fmt), sf.inf_bits(fmt, 1),
                               sf.zero_bits(fmt, 1), sf.one_bits(fmt, 1)])

    # NaNs beside infinities: the one row where sumSquare and sumAbs
    # are not the plain composition
    pools["nan_inf"] = cycle([sf.qnan_bits(fmt), sf.inf_bits(fmt),
                              sf.one_bits(fmt), sf.snan_bits(fmt),
                              sf.inf_bits(fmt, 1), sf.qnan_bits(fmt) | 5])

    # the whole exponent range in one vector
    pools["wide"] = [_rand_finite(rng, fmt, 1, fmt.exp_mask - 1)
                     for _ in range(need)]

    for i in range(max(0, extra)):
        pools["random%d" % i] = [_rand_bits(rng, fmt) for _ in range(need)]
    return pools


def reduce_cases(fmt: FpFormat, extra: int, seed: int = 20):
    """(fn, xs, ys) triples for all seven of clause 9.4's reductions.

    ys is None for the unary five. Coverage is deliberately shaped
    around cost: every LENGTH is used for every function (rotating
    through the pools), and every POOL is used for every function at a
    few short lengths - because a case's size is its length, and a
    cross of all lengths against all pools would make an fp256 set tens
    of megabytes for coverage that repeats itself.
    """
    pools = reduce_pools(fmt, extra, seed)
    names = sorted(pools)
    cases = []
    k = 0
    for fn in REDUCE_FNS:
        binary = REDUCE_ARITY[fn] == 2
        for n in REDUCE_LENGTHS:
            src = pools[names[k % len(names)]]
            other = pools[names[(k + 3) % len(names)]]
            k += 1
            cases.append((fn, src[:n], other[:n] if binary else None))
        for name in names:
            for n in REDUCE_POOL_LENGTHS:
                src = pools[name]
                other = pools[names[(names.index(name) + 1) % len(names)]]
                cases.append((fn, src[:n], other[:n] if binary else None))
    return cases
