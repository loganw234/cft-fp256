# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The formatOf arithmetic of IEEE 754-2019 5.4.1, and 5.11's
cross-format comparison.

The pattern this file copies is python/tests/test_rounding.py's, and
for the same reason: an operation is checked against an INDEPENDENT
statement of what it should be, never against a second call into the
same code. Here the independent statements are

  * exact rational arithmetic (Fraction) rounded to the destination by
    a reference rounder written from 4.3's text, for the four
    algebraic operations - a route that shares no line with
    softfloat.round_pack;
  * the composition identity in the narrow-to-wide direction, where
    widening is exact so convert-then-operate IS the operation;
  * bit-identity with the single-format functions when the two formats
    are the same, which is a statement about this module being a
    generalisation rather than a rewrite;
  * and the double-rounding witnesses, which are constructed from the
    format descriptors and then RUN, so that "the composed route is
    wrong" is a demonstration rather than a claim.
"""

from fractions import Fraction

import pytest

from cft_golden import FP32, FP64, FP128, FP256
from cft_golden import formatof as fo
from cft_golden import softfloat as sf

FMTS = (FP32, FP64, FP128, FP256)
PAIRS = [(s, d) for s in FMTS for d in FMTS]
NARROWING = [(s, d) for s, d in PAIRS if d.prec < s.prec]
WIDENING = [(s, d) for s, d in PAIRS if d.prec >= s.prec]
MODES = sf.RND_MODES


def ids(pairs):
    return [f"{s.name}->{d.name}" for s, d in pairs]


# ---- an independent rounder, from clause 4.3's words ------------------

def exact_value(fmt, bits):
    """The exact value of a finite encoding, as a Fraction."""
    u = sf.unpack(fmt, bits)
    if u.kind in (sf.INF, sf.NAN):
        raise ValueError("not finite")
    if u.kind == sf.ZERO:
        return Fraction(0)
    v = Fraction(u.m) * Fraction(2) ** u.e
    return -v if u.sign else v


def ref_round(fmt, value, rnd, sign_hint=0):
    """Round an exact Fraction into `fmt` and report the flags, written
    from the standard rather than from round_pack.

    Returns (bits, flags). `sign_hint` gives the sign of a zero result
    when `value` is exactly zero, which 6.3 decides and arithmetic
    supplies.
    """
    if value == 0:
        return sf.zero_bits(fmt, sign_hint), 0
    sign = 1 if value < 0 else 0
    mag = abs(value)

    def snap(q):
        """The multiple of 2^q nearest `mag` under `rnd`, as an integer
        count of 2^q, plus whether anything was discarded."""
        scaled = mag / (Fraction(2) ** q)
        lo = scaled.numerator // scaled.denominator
        frac = scaled - lo
        if frac == 0:
            return lo, False
        if rnd == sf.RND_RTZ:
            up = False
        elif rnd == sf.RND_RDN:
            up = bool(sign)
        elif rnd == sf.RND_RUP:
            up = not sign
        elif rnd == sf.RND_RMM:
            up = frac >= Fraction(1, 2)
        else:                                    # RND_RNE
            up = (frac > Fraction(1, 2) or
                  (frac == Fraction(1, 2) and lo % 2 == 1))
        return lo + (1 if up else 0), True

    # 7.5, tininess AFTER rounding: round with an unbounded exponent
    # range first and ask where that lands.
    e_norm = mag.numerator.bit_length() - mag.denominator.bit_length()
    while Fraction(2) ** e_norm > mag:
        e_norm -= 1
    while Fraction(2) ** (e_norm + 1) <= mag:
        e_norm += 1
    ku, _ = snap(e_norm - (fmt.prec - 1))
    e_unb = e_norm - (fmt.prec - 1) + ku.bit_length() - 1
    tiny = e_unb < fmt.emin

    q = max(e_norm, fmt.emin) - (fmt.prec - 1)
    kept, inexact = snap(q)
    flags = sf.FLAG_INEXACT if inexact else 0
    if kept == 0:
        return sf.zero_bits(fmt, sign), flags | sf.FLAG_UNDERFLOW
    e_res = q + kept.bit_length() - 1
    if e_res > fmt.emax:
        # 7.4: every mode signals; the delivery depends on the mode
        inf = (rnd in (sf.RND_RNE, sf.RND_RMM) or
               (rnd == sf.RND_RUP and not sign) or
               (rnd == sf.RND_RDN and sign))
        bits = (sf.inf_bits(fmt, sign) if inf
                else sf.max_normal_bits(fmt, sign))
        return bits, flags | sf.FLAG_OVERFLOW | sf.FLAG_INEXACT
    if tiny and inexact:
        flags |= sf.FLAG_UNDERFLOW
    if e_res < fmt.emin:
        return sf.zero_bits(fmt, sign) | kept, flags
    if kept.bit_length() == fmt.prec + 1:
        kept >>= 1
    frac_field = kept - (1 << (fmt.prec - 1))
    return (sf.zero_bits(fmt, sign) |
            ((e_res + fmt.bias) << fmt.man_w) | frac_field), flags


# ---- operand pools ----------------------------------------------------

def pool(fmt, seed):
    """A short pool of finite operands, built from the descriptor: the
    binade edges, the subnormal edges, the exact powers, and randoms."""
    import random
    rng = random.Random(seed ^ (fmt.width * 977))
    out = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.one_bits(fmt),
           sf.one_bits(fmt, 1), sf.min_subnormal_bits(fmt),
           sf.max_subnormal_bits(fmt), sf.min_normal_bits(fmt),
           sf.max_normal_bits(fmt), sf.max_normal_bits(fmt, 1)]
    for _ in range(24):
        out.append(rng.getrandbits(fmt.width) & ~(fmt.exp_mask << fmt.man_w)
                   | (rng.randrange(1, fmt.exp_mask) << fmt.man_w))
    return out


# ---- the four algebraic operations against exact rationals ------------

@pytest.mark.parametrize("s,d", PAIRS, ids=ids(PAIRS))
@pytest.mark.parametrize("rnd", MODES, ids=[sf.RND_NAMES[m] for m in MODES])
def test_add_sub_mul_fma_against_exact_rationals(s, d, rnd):
    xs = pool(s, 3)
    for i, xa in enumerate(xs):
        xb = xs[(i * 7 + 3) % len(xs)]
        xc = xs[(i * 11 + 5) % len(xs)]
        va, vb, vc = (exact_value(s, xa), exact_value(s, xb),
                      exact_value(s, xc))
        for fn, value, hint in (
                (fo.FN_FO_ADD, va + vb,
                 sf.zero_sign_for_exact_cancellation(rnd)),
                (fo.FN_FO_SUB, va - vb,
                 sf.zero_sign_for_exact_cancellation(rnd)),
                (fo.FN_FO_MUL, va * vb,
                 sf.unpack(s, xa).sign ^ sf.unpack(s, xb).sign),
                (fo.FN_FO_FMA, va * vb + vc,
                 sf.zero_sign_for_exact_cancellation(rnd))):
            got = fo.compute(s, d, fn, xa, xb, xc, rnd)
            # The zero-sign hint only matters when the exact value is
            # zero AND that zero came from cancellation; the "one
            # operand was a zero" rows keep the operand's sign, which
            # the reference cannot know, so skip only those.
            if value == 0 and (va == 0 or vb == 0 or
                               (fn == fo.FN_FO_FMA and vc == 0)):
                continue
            want = ref_round(d, value, rnd, hint)
            assert got == want, (fn, s.name, d.name, sf.RND_NAMES[rnd],
                                 hex(xa), hex(xb), hex(xc))


@pytest.mark.parametrize("s,d", PAIRS, ids=ids(PAIRS))
@pytest.mark.parametrize("rnd", MODES, ids=[sf.RND_NAMES[m] for m in MODES])
def test_div_and_sqrt_against_exact_rationals(s, d, rnd):
    xs = [x for x in pool(s, 5)]
    for i, xa in enumerate(xs):
        xb = xs[(i * 5 + 1) % len(xs)]
        va, vb = exact_value(s, xa), exact_value(s, xb)
        if vb != 0:
            got = fo.compute(s, d, fo.FN_FO_DIV, xa, xb, 0, rnd)
            sq = (sf.unpack(s, xa).sign ^ sf.unpack(s, xb).sign)
            want = ref_round(d, va / vb, rnd, sq)
            assert got == want, ("div", s.name, d.name, hex(xa), hex(xb))
        if va > 0:
            bits, flags = fo.compute(s, d, fo.FN_FO_SQRT, xa, 0, 0, rnd)
            assert_sqrt_correct(d, va, bits, flags, rnd,
                                (s.name, d.name, hex(xa)))


def assert_sqrt_correct(d, va, bits, flags, rnd, where):
    """The DEFINITION of a correctly rounded square root, checked by
    squaring rather than by taking a root - so nothing here computes a
    root at all and the check shares no code with what it judges.

    `va` is the operand's exact value as a Fraction, positive. The
    neighbours of a positive finite encoding are its encoding plus and
    minus one, which crosses binade edges and the subnormal boundary
    correctly by construction (that is what the biased-exponent layout
    is for).
    """
    assert (bits >> (d.width - 1)) == 0, where
    assert not flags & (sf.FLAG_INVALID | sf.FLAG_DIVZERO), where
    if flags & sf.FLAG_OVERFLOW:
        # 7.4: the exact root left the destination's range. Delivery is
        # the infinity or the largest finite, per attribute.
        assert flags & sf.FLAG_INEXACT, where
        assert bits in (sf.inf_bits(d), sf.max_normal_bits(d)), where
        mx = exact_value(d, sf.max_normal_bits(d))
        assert va > mx * mx, where
        return
    ef = (bits >> d.man_w) & d.exp_mask
    assert ef != d.exp_mask, where
    r = exact_value(d, bits)
    up = exact_value(d, bits + 1)
    dn = exact_value(d, bits - 1) if bits > 0 else None
    exact = (r * r == va)
    assert bool(flags & sf.FLAG_INEXACT) == (not exact), where
    # underflow is tininess AFTER rounding AND inexact, and tininess
    # after rounding is exactly "the delivered result is subnormal or
    # zero" - a rounding that carried up to the least normal is not tiny
    assert bool(flags & sf.FLAG_UNDERFLOW) == (ef == 0 and not exact), where
    if rnd in (sf.RND_RTZ, sf.RND_RDN):
        assert r * r <= va < up * up, where
    elif rnd == sf.RND_RUP:
        assert va <= r * r and (dn is None or dn * dn < va), where
    else:
        mhi = (r + up) / 2
        assert va <= mhi * mhi, where
        if va == mhi * mhi:                 # a tie resolved DOWNWARD
            assert rnd == sf.RND_RNE and (bits & 1) == 0, where
        if dn is not None:
            mlo = (r + dn) / 2
            assert mlo * mlo <= va, where
            if mlo * mlo == va and rnd == sf.RND_RNE:
                assert (bits & 1) == 0, where   # a tie resolved UPWARD


# ---- the narrow-to-wide composition identity --------------------------

@pytest.mark.parametrize("s,d", WIDENING, ids=ids(WIDENING))
@pytest.mark.parametrize("rnd", MODES, ids=[sf.RND_NAMES[m] for m in MODES])
def test_widening_equals_convert_then_operate(s, d, rnd):
    """5.4.1 with a destination at least as wide as the source is a
    COMPOSITION: widening is exact, so convert-then-operate keeps the
    single rounding. This is the identity libcft's implementation relies
    on in that direction, so it is asserted rather than assumed."""
    xs = pool(s, 11) + [sf.qnan_bits(s), sf.snan_bits(s), sf.inf_bits(s),
                        sf.inf_bits(s, 1)]
    single = {fo.FN_FO_ADD: lambda a, b, c: sf.add(d, a, b, rnd),
              fo.FN_FO_SUB: lambda a, b, c: sf.sub(d, a, b, rnd),
              fo.FN_FO_MUL: lambda a, b, c: sf.mul(d, a, b, rnd),
              fo.FN_FO_DIV: lambda a, b, c: sf.div(d, a, b, rnd),
              fo.FN_FO_SQRT: lambda a, b, c: sf.sqrt(d, a, rnd),
              fo.FN_FO_FMA: lambda a, b, c: sf.fma(d, a, b, c, rnd)}
    for i, xa in enumerate(xs):
        xb = xs[(i * 13 + 2) % len(xs)]
        xc = xs[(i * 17 + 9) % len(xs)]
        ca, fa = sf.convert(s, d, xa, rnd)
        cb, fb = sf.convert(s, d, xb, rnd)
        cc, fc = sf.convert(s, d, xc, rnd)
        assert (fa | fb | fc) & ~sf.FLAG_INVALID == 0, "widening is exact"
        for fn in fo.FORMATOF_FNS:
            arity = fo.FORMATOF_ARITY[fn]
            conv = fa | (fb if arity >= 2 else 0) | (fc if arity >= 3 else 0)
            wbits, wfl = single[fn](ca, cb, cc)
            got = fo.compute(s, d, fn, xa, xb, xc, rnd)
            assert got == (wbits, wfl | conv), (
                fn, s.name, d.name, sf.RND_NAMES[rnd], hex(xa), hex(xb),
                hex(xc))


@pytest.mark.parametrize("f", FMTS, ids=[f.name for f in FMTS])
@pytest.mark.parametrize("rnd", MODES, ids=[sf.RND_NAMES[m] for m in MODES])
def test_same_format_is_the_existing_function(f, rnd):
    """sfmt == dfmt must be bit-identical to softfloat's own six, flags
    included. A generalisation that changed the base case would be a
    different contract wearing the same name."""
    xs = pool(f, 13) + [sf.qnan_bits(f), sf.snan_bits(f), sf.inf_bits(f),
                        sf.inf_bits(f, 1)]
    for i, xa in enumerate(xs):
        xb = xs[(i * 3 + 1) % len(xs)]
        xc = xs[(i * 19 + 7) % len(xs)]
        assert fo.fo_add(f, f, xa, xb, rnd) == sf.add(f, xa, xb, rnd)
        assert fo.fo_sub(f, f, xa, xb, rnd) == sf.sub(f, xa, xb, rnd)
        assert fo.fo_mul(f, f, xa, xb, rnd) == sf.mul(f, xa, xb, rnd)
        assert fo.fo_div(f, f, xa, xb, rnd) == sf.div(f, xa, xb, rnd)
        assert fo.fo_sqrt(f, f, xa, rnd) == sf.sqrt(f, xa, rnd)
        assert fo.fo_fma(f, f, xa, xb, xc, rnd) == sf.fma(f, xa, xb, xc, rnd)


# ---- the double-rounding witnesses ------------------------------------

@pytest.mark.parametrize("s,d", NARROWING, ids=ids(NARROWING))
@pytest.mark.parametrize("fn", (fo.FN_FO_FMA, fo.FN_FO_DIV, fo.FN_FO_SQRT))
def test_double_rounding_is_not_innocuous(s, d, fn):
    """The composed route - round in the source format, then convert -
    gives the WRONG answer, for all three of fusedMultiplyAdd, division
    and squareRoot, on every ordered pair of this ladder.

    That is worth stating precisely, because it contradicts a rule that
    is true elsewhere. Figueroa's theorem says double rounding through
    an intermediate of q >= 2p + 2 bits is innocuous for the basic
    operations, and 53 >= 2*24+2, 113 >= 2*53+2 and 237 >= 2*113+2 all
    hold on this ladder. The theorem does not apply, because its
    hypothesis is that the OPERANDS have p bits - the same p as the
    destination. Here they have the source's, and a quotient of two
    wide values can sit as close as it likes to a narrow midpoint.

    Each witness below is CONSTRUCTED from the format descriptors, not
    searched for and not typed in.
    """
    xa, xb, xc, wfmt = fo.double_rounding_witness(s, d, fn)
    once = fo.compute(s, d, fn, xa, xb, xc, sf.RND_RNE)
    twice = fo.composed_route(s, d, wfmt, fn, xa, xb, xc, sf.RND_RNE)
    assert once[0] != twice[0], (
        f"{s.name}->{d.name} {fn}: the composed route agreed, so this "
        f"witness no longer witnesses anything")
    # and the single rounding is the one that is right: the exact value
    # is strictly above the destination midpoint, so it rounds UP
    lo = twice[0]                      # the tie broken to even, downward
    assert once[0] == lo + 1, (hex(once[0]), hex(lo))


@pytest.mark.parametrize("wprec", (30, 53, 64, 113, 237, 400, 1000))
def test_fma_witness_defeats_any_intermediate_width(wprec):
    """9.5's FMA argument, exercised rather than asserted: the addend is
    a free choice of source value, so it can be put below the half-ulp
    of an intermediate of ANY precision the source's exponent range can
    undercut. binary64's smallest subnormal is 2^-1074, so every
    intermediate up to about a thousand bits is defeated by the same
    construction."""
    s, d = FP64, FP32
    xa, xb, xc, wfmt = fo.double_rounding_witness(s, d, fo.FN_FO_FMA,
                                                  wprec=wprec)
    once = fo.compute(s, d, fo.FN_FO_FMA, xa, xb, xc, sf.RND_RNE)
    twice = fo.composed_route(s, d, wfmt, fo.FN_FO_FMA, xa, xb, xc,
                              sf.RND_RNE)
    assert once[0] != twice[0], wprec


# ---- destination boundaries -------------------------------------------

@pytest.mark.parametrize("s,d", NARROWING, ids=ids(NARROWING))
@pytest.mark.parametrize("rnd", MODES, ids=[sf.RND_NAMES[m] for m in MODES])
def test_destination_overflow_and_tininess(s, d, rnd):
    """Every exception here belongs to the DESTINATION. Operands that are
    unremarkable in the source overflow or go subnormal in the
    destination, and the flags must say so - which is the whole
    difference between this operation and convert-then-operate."""
    one = sf.one_bits(s)
    # a product that is finite in the source and overflows the
    # destination: maxnormal(d) squared, expressed in the source
    big, fb = sf.convert(d, s, sf.max_normal_bits(d), sf.RND_RNE)
    assert fb == 0
    bits, flags = fo.fo_mul(s, d, big, big, rnd)
    assert flags & sf.FLAG_OVERFLOW, (s.name, d.name, sf.RND_NAMES[rnd])
    assert flags & sf.FLAG_INEXACT

    # a source value exactly on the destination's smallest subnormal:
    # exact, so nothing is raised
    tiny, ft = sf.convert(d, s, sf.min_subnormal_bits(d), sf.RND_RNE)
    assert ft == 0
    bits, flags = fo.fo_add(s, d, tiny, sf.zero_bits(s), rnd)
    assert bits == sf.min_subnormal_bits(d) and flags == 0

    # half of it - representable in the source, below the destination's
    # grid, so tiny and inexact
    half, fh = fo.fo_mul(s, s, tiny, sf.round_pack(s, 0, 1, -1,
                                                   sf.RND_RNE)[0], rnd)
    assert fh == 0, "halving the destination's least subnormal is exact " \
                    "in the source"
    bits, flags = fo.fo_add(s, d, half, sf.zero_bits(s), rnd)
    assert flags & sf.FLAG_INEXACT and flags & sf.FLAG_UNDERFLOW

    # and the exact-tie direction: RNE takes the even neighbour (zero),
    # RUP/RMM take the subnormal
    if rnd in (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN):
        assert bits == sf.zero_bits(d)
    else:
        assert bits == sf.min_subnormal_bits(d)
    del one


@pytest.mark.parametrize("s,d", PAIRS, ids=ids(PAIRS))
def test_specials_are_built_in_the_destination(s, d):
    """NaNs canonicalise into dfmt, infinities and zeros carry dfmt's
    encoding, and a signaling operand raises invalid in every one of
    the six (6.2.1)."""
    q, sn = sf.qnan_bits(s), sf.snan_bits(s)
    one, zero = sf.one_bits(s), sf.zero_bits(s)
    inf, ninf = sf.inf_bits(s), sf.inf_bits(s, 1)
    for fn in fo.FORMATOF_FNS:
        arity = fo.FORMATOF_ARITY[fn]
        bits, flags = fo.compute(s, d, fn, q, one, one)
        assert bits == sf.qnan_bits(d) and flags == 0, fn
        bits, flags = fo.compute(s, d, fn, sn, one, one)
        assert bits == sf.qnan_bits(d) and flags == sf.FLAG_INVALID, fn
        if arity >= 2:
            bits, flags = fo.compute(s, d, fn, one, sn, one)
            assert bits == sf.qnan_bits(d)
            assert flags == sf.FLAG_INVALID, fn
        if arity >= 3:
            bits, flags = fo.compute(s, d, fn, one, one, sn)
            assert bits == sf.qnan_bits(d)
            assert flags == sf.FLAG_INVALID, fn
    assert fo.fo_add(s, d, inf, one) == (sf.inf_bits(d), 0)
    assert fo.fo_add(s, d, inf, ninf) == (sf.qnan_bits(d), sf.FLAG_INVALID)
    assert fo.fo_mul(s, d, inf, zero) == (sf.qnan_bits(d), sf.FLAG_INVALID)
    assert fo.fo_div(s, d, one, zero) == (sf.inf_bits(d), sf.FLAG_DIVZERO)
    assert fo.fo_div(s, d, zero, zero) == (sf.qnan_bits(d), sf.FLAG_INVALID)
    assert fo.fo_div(s, d, inf, inf) == (sf.qnan_bits(d), sf.FLAG_INVALID)
    assert fo.fo_sqrt(s, d, sf.one_bits(s, 1)) == (sf.qnan_bits(d),
                                                   sf.FLAG_INVALID)
    assert fo.fo_sqrt(s, d, ninf) == (sf.qnan_bits(d), sf.FLAG_INVALID)
    assert fo.fo_sqrt(s, d, sf.zero_bits(s, 1)) == (sf.zero_bits(d, 1), 0)
    assert fo.fo_fma(s, d, inf, zero, one) == (sf.qnan_bits(d),
                                               sf.FLAG_INVALID)
    assert fo.fo_fma(s, d, inf, one, ninf) == (sf.qnan_bits(d),
                                               sf.FLAG_INVALID)


@pytest.mark.parametrize("s,d", PAIRS, ids=ids(PAIRS))
@pytest.mark.parametrize("rnd", MODES, ids=[sf.RND_NAMES[m] for m in MODES])
def test_exact_zero_signs(s, d, rnd):
    """6.3 at the destination: an exact cancellation is +0 in every
    attribute except roundTowardNegative; like-signed zeros keep their
    sign; a zero product takes the XOR."""
    one, none = sf.one_bits(s), sf.one_bits(s, 1)
    pz, nz = sf.zero_bits(s), sf.zero_bits(s, 1)
    want = sf.zero_bits(d, 1 if rnd == sf.RND_RDN else 0)
    assert fo.fo_add(s, d, one, none, rnd) == (want, 0)
    assert fo.fo_sub(s, d, one, one, rnd) == (want, 0)
    assert fo.fo_add(s, d, pz, pz, rnd) == (sf.zero_bits(d, 0), 0)
    assert fo.fo_add(s, d, nz, nz, rnd) == (sf.zero_bits(d, 1), 0)
    assert fo.fo_add(s, d, pz, nz, rnd) == (want, 0)
    assert fo.fo_mul(s, d, one, nz, rnd) == (sf.zero_bits(d, 1), 0)
    assert fo.fo_mul(s, d, none, nz, rnd) == (sf.zero_bits(d, 0), 0)
    assert fo.fo_fma(s, d, pz, one, nz, rnd) == (want, 0)


def test_rejects_a_rounding_direction_that_is_not_an_attribute():
    """The gate every public operation passes: 9.5's roundTiesTowardZero
    is a rounding DIRECTION and not one of 4.3's five, so no formatOf
    entry point accepts it."""
    for fn in fo.FORMATOF_FNS:
        with pytest.raises(ValueError):
            fo.compute(FP64, FP32, fn, sf.one_bits(FP64), sf.one_bits(FP64),
                       sf.one_bits(FP64), sf.RND_RTTZ)
        with pytest.raises(ValueError):
            fo.compute(FP64, FP32, fn, sf.one_bits(FP64), sf.one_bits(FP64),
                       sf.one_bits(FP64), 5)


def test_unknown_operation_name_is_refused():
    with pytest.raises(ValueError):
        fo.compute(FP64, FP32, "addition ", 0, 0, 0)


# ---- 5.11, cross-format comparison ------------------------------------

@pytest.mark.parametrize("a,b", PAIRS, ids=ids(PAIRS))
def test_cross_format_comparison_is_exact(a, b):
    """5.11: "Comparisons of two data of different binary formats shall
    be exact, as if the data were converted to a common format with
    unbounded exponent range and precision."

    Here the common format is the wider of the two and the conversion
    into it is exact, so the composition IS the comparison - which is
    why no entry point is added for it. Checked against exact rationals,
    which is the "unbounded exponent range and precision" the clause
    names.
    """
    xs_a = pool(a, 21)
    xs_b = pool(b, 22)
    for i, xa in enumerate(xs_a):
        xb = xs_b[i % len(xs_b)]
        (lt, eq, gt), flags = fo.compare(a, b, xa, xb)
        va, vb = exact_value(a, xa), exact_value(b, xb)
        assert (lt, eq, gt) == (va < vb, va == vb, va > vb), (
            a.name, b.name, hex(xa), hex(xb))
        assert flags == 0


@pytest.mark.parametrize("a,b", PAIRS, ids=ids(PAIRS))
def test_cross_format_comparison_nans_and_infinities(a, b):
    qa, sa = sf.qnan_bits(a), sf.snan_bits(a)
    one_b = sf.one_bits(b)
    assert fo.compare(a, b, qa, one_b) == ((False, False, False), 0)
    assert fo.compare(a, b, sa, one_b) == ((False, False, False),
                                           sf.FLAG_INVALID)
    assert fo.compare(a, b, qa, one_b, signaling=True) == (
        (False, False, False), sf.FLAG_INVALID)
    assert fo.compare(a, b, sf.inf_bits(a), sf.inf_bits(b)) == (
        (False, True, False), 0)
    assert fo.compare(a, b, sf.inf_bits(a, 1), sf.inf_bits(b)) == (
        (True, False, False), 0)
    # signed zeros compare equal across formats, exactly as within one
    assert fo.compare(a, b, sf.zero_bits(a, 1), sf.zero_bits(b, 0)) == (
        (False, True, False), 0)
    # the narrower format's largest finite is less than the wider's,
    # which is the whole reason a cross-format comparison is not a
    # bit comparison
    if a.prec < b.prec:
        assert fo.compare(a, b, sf.max_normal_bits(a),
                          sf.max_normal_bits(b))[0] == (True, False, False)
