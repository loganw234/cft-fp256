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


# ---- the phase-1 transcendental sets ---------------------------------

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


def transcend_cases(fmt: FpFormat, extra: int, seed: int = 9):
    """(fn, a, b) triples for the nine transcendentals, in the order
    gen_vectors.py writes them. b is 0 for the unary seven, which do not
    emit it at all."""
    from .transcend import TRANSCEND_ARITY, TRANSCEND_FNS

    pool = transcend_unary_pool(fmt, extra, seed)
    cases = []
    for fn in TRANSCEND_FNS:
        if TRANSCEND_ARITY[fn] == 1:
            cases += [(fn, a, 0) for a in pool]
        elif fn == "pow":
            cases += [(fn, a, b)
                      for a, b in transcend_pow_pairs(fmt, extra, seed + 1)]
        else:
            cases += [(fn, a, b)
                      for a, b in transcend_hypot_pairs(fmt, extra, seed + 2)]
    return cases
