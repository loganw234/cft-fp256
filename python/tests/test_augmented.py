# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the augmented arithmetic operations, IEEE 754-2019 9.5.

The same arbiter discipline the rest of the suite uses - nothing here
is scored against the thing under test:

1. ref754.ref_augmented: an independent restatement of 9.5 in exact
   Fractions, sharing no code with cft_golden. It rounds by rational
   comparison and decides representability by trying to encode the
   residual, where the model rounds integer significands through
   round_pack.
2. CPython's native binary64. roundTiesTowardZero and roundTiesToEven
   differ ONLY at an exact midpoint, so for every fp64 pair whose exact
   sum or product is not a midpoint the model's r must equal what the
   host CPU's own IEEE hardware computes - an oracle with no lineage in
   common with this project at all.
3. Hand-derived bit patterns for the rows 9.5 states in words: the tie
   toward the smaller magnitude, the overflow threshold and the value
   exactly on it, the sign of a zero error term, the NaN and infinity
   pairs, and the underflow-without-inexact combination that appears
   nowhere else in this contract.
4. The pair identity r + e == x op y, as exact integers, over the whole
   adversarial pool - excluding by NAME the one case 9.5 says breaks it.
"""

import math
import struct
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, FORMATS,
    FLAG_INVALID, FLAG_OVERFLOW, FLAG_UNDERFLOW, FLAG_INEXACT,
    RND_RTTZ, RND_MODES, vectors,
    zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, min_normal_bits, max_normal_bits, negate,
    augmented_add, augmented_sub, augmented_mul,
)
from cft_golden import augmented as aug  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import ref754  # noqa: E402

ALL_FORMATS = (FP32, FP64, FP128, FP256)
OPS = {"add": augmented_add, "sub": augmented_sub, "mul": augmented_mul}

#: The random tail each pool gets on top of its directed families.
POOL_EXTRA = 24

#: How many pool pairs the FRACTION oracle arbitrates, per format. It
#: is thousands of times slower than the model - a subnormal fp256 value
#: is a rational with a 262,378-bit denominator, and every gcd pays for
#: it - so the wide rungs get fewer. What that costs is coverage of
#: cases, not of RULES: 9.5's logic is format-independent, the integer
#: sweeps below run the whole pool at every format, and
#: host/tests/augmented_check.py runs the whole pool against the C.
ORACLE_SAMPLE = {"fp32": 2000, "fp64": 2000, "fp128": 1500, "fp256": 500}


def rf(fmt):
    """The independent oracle's format object for one of ours."""
    return ref754.Fmt(fmt.exp_w, fmt.man_w)


def sample(pairs, want):
    """A deterministic stride through a pool.

    The Fraction oracle is thousands of times slower than the model it
    arbitrates, and fp32's pool sweeps every binade the format has. A
    stride keeps every FAMILY represented - the pool is built family by
    family, so every k-th entry crosses all of them - while the exact
    identity and flag-domain sweeps below, which are integer-only and
    cheap, still run over the whole pool. host/tests/augmented_check.py
    and the conformance replay are what run the full pool against the C.
    """
    step = max(1, len(pairs) // want)
    return pairs[::step]


def val(fmt, bits):
    """The exact value of a finite encoding, as a Fraction."""
    m, e = aug.exact_value(fmt, bits)
    return Fraction(m) * Fraction(2) ** e


# ---- exact dyadic arithmetic, in integers ----------------------------
#
# (m, e) means m * 2^e with m a signed integer, normalised so that m is
# odd (or zero). The identity r + e == x op y is a statement about exact
# dyadic rationals, and this keeps it in the same integers the model
# computes with rather than routing it through anything that rounds -
# or through Fraction, whose gcd on a 2^-262378 denominator costs more
# than the whole model does.

def dnorm(m, e):
    if m == 0:
        return (0, 0)
    t = (m & -m).bit_length() - 1
    return (m >> t, e + t)


def dyadic(fmt, bits):
    m, e = aug.exact_value(fmt, bits)
    return dnorm(m, e)


def dadd(x, y):
    e0 = min(x[1], y[1])
    return dnorm((x[0] << (x[1] - e0)) + (y[0] << (y[1] - e0)), e0)


def dmul(x, y):
    return dnorm(x[0] * y[0], x[1] + y[1])


def dneg(x):
    return (-x[0], x[1])


def f64(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def bits64(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def is_nan_bits(fmt, bits):
    return sf.is_nan(fmt, bits)


# ---- 1. against the independent Fraction oracle -----------------------

@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_matches_the_independent_oracle(fmt):
    """Every pair in the adversarial pool, all three operations, r and e
    and flags, against ref754's reading of 9.5."""
    f = rf(fmt)
    whole = vectors.augmented_pairs(fmt, POOL_EXTRA)
    assert len(whole) > 3000, "the pool got smaller - check the generator"
    pairs = sample(whole, ORACLE_SAMPLE[fmt.name])
    for a, b in pairs:
        for name, fn in OPS.items():
            got = fn(fmt, a, b)
            want = ref754.ref_augmented(f, a, b, name)
            assert got == want, (fmt.name, name, hex(a), hex(b),
                                 [hex(v) for v in got[:2]], got[2],
                                 [hex(v) for v in want[:2]], want[2])


# ---- 2. against the host CPU's own binary64 --------------------------

def test_fp64_r_matches_native_double_off_the_ties():
    """roundTiesTowardZero and the CPU's roundTiesToEven agree except at
    an exact midpoint, so away from midpoints the model's r must be
    exactly what `a + b` and `a * b` produce in CPython."""
    pairs = sample(vectors.augmented_pairs(FP64, POOL_EXTRA), 1600)
    checked = 0
    for a, b in pairs:
        xa, xb = f64(a), f64(b)
        if math.isnan(xa) or math.isnan(xb):
            continue
        for name, native in (("add", lambda p, q: p + q),
                             ("mul", lambda p, q: p * q)):
            if math.isinf(xa) or math.isinf(xb):
                continue
            # a midpoint is exactly where the two rules may differ, and
            # 9.5's tie rule is the thing under test elsewhere
            exact = (val(FP64, a) + val(FP64, b)) if name == "add" \
                else (val(FP64, a) * val(FP64, b))
            if exact == 0:
                continue
            fr = rf(FP64)
            rne_bits, _ = ref754.ref_pack(fr, exact, ref754.RNE)
            rttz_bits, _ = ref754.ref_pack(fr, exact, ref754.RTTZ)
            if rne_bits != rttz_bits:
                continue                       # a tie: not this test's job
            try:
                nat = native(xa, xb)
            except OverflowError:              # pragma: no cover
                continue
            if math.isinf(nat):
                continue                       # overflow: 7.4, tested apart
            r, _, _ = OPS[name](FP64, a, b)
            assert r == bits64(nat), (name, hex(a), hex(b), hex(r),
                                      hex(bits64(nat)))
            checked += 1
    assert checked > 900, checked


# ---- 3. the rows 9.5 states in words ---------------------------------

def test_tie_goes_to_the_smaller_magnitude():
    """"if the two nearest floating-point numbers bracketing an
    unrepresentable infinitely precise result are equally near, the one
    with smaller magnitude shall be delivered" - which is a DIFFERENT
    answer from all five rounding attributes' addition here, since the
    lower neighbour's last bit is odd."""
    fmt = FP32
    x = one_bits(fmt) | 1                       # 1 + 2^-23, odd last bit
    y = sf.round_pack(fmt, 0, 1, -24, sf.RND_RNE)[0]      # half an ulp
    r, e, flags = augmented_add(fmt, x, y)
    assert r == 0x3F800001 and e == 0x33800000 and flags == 0
    # roundTiesToEven and roundTiesToAway both step UP from this
    # midpoint; roundTowardZero and roundTowardNegative reach the same
    # value the augmented operation does, but by truncating rather than
    # by a tie rule - so no attribute reproduces the pair.
    assert sf.add(fmt, x, y, sf.RND_RNE)[0] == 0x3F800002
    assert sf.add(fmt, x, y, sf.RND_RMM)[0] == 0x3F800002
    assert sf.add(fmt, x, y, sf.RND_RUP)[0] == 0x3F800002
    assert sf.add(fmt, x, y, sf.RND_RTZ)[0] == 0x3F800001
    # the negative side, where ties toward zero is the OTHER direction
    r2, e2, fl2 = augmented_add(fmt, negate(fmt, x), negate(fmt, y))
    assert r2 == 0xBF800001 and e2 == 0xB3800000 and fl2 == 0
    assert sf.add(fmt, negate(fmt, x), negate(fmt, y), sf.RND_RDN)[0] \
        == 0xBF800002


def test_tie_rule_is_magnitude_symmetric():
    """The rule is about MAGNITUDE, so for the sum and the difference
    negating both operands negates both results and changes no flag -
    which roundTowardNegative, say, does not do, and which is the
    property that makes these three attribute-free at all.

    Zero results are excluded and tested separately: their signs come
    from 6.3's cancellation rule, which is deliberately not symmetric
    (+0 for a cancellation whichever way round the operands were)."""
    for fmt in ALL_FORMATS:
        for a, b in sample(vectors.augmented_pairs(fmt, 8), 900):
            for name in ("add", "sub"):
                fn = OPS[name]
                r, e, fl = fn(fmt, a, b)
                if is_nan_bits(fmt, r):
                    continue
                if (r & ~fmt.sign_mask) == 0:
                    continue                   # a zero r: 6.3, not this
                rn, en, fln = fn(fmt, negate(fmt, a), negate(fmt, b))
                assert fln == fl, (fmt.name, name, hex(a), hex(b))
                assert rn == negate(fmt, r), \
                    (fmt.name, name, hex(a), hex(b), hex(r), hex(rn))
                assert en == negate(fmt, e), \
                    (fmt.name, name, hex(a), hex(b), hex(e), hex(en))


def test_overflow_threshold_is_the_midpoint_and_lands_on_maxfinite():
    """"An infinitely precise result with magnitude equal to
    b^emax x (b - 1/2 b^(1-p)) shall round to b^emax x (b - b^(1-p))
    with no change in sign" - and 9.5 signals inexact ONLY on overflow,
    so landing exactly on the threshold raises NOTHING even though the
    residual is half an ulp."""
    for fmt in ALL_FORMATS:
        mx = max_normal_bits(fmt)
        half_ulp = sf.round_pack(fmt, 0, 1, fmt.emax - fmt.prec,
                                 sf.RND_RNE)[0]       # 2^(emax-p)
        r, e, flags = augmented_add(fmt, mx, half_ulp)
        assert r == mx, fmt.name
        assert e == half_ulp, fmt.name
        assert flags == 0, (fmt.name, flags)
        assert val(fmt, r) + val(fmt, e) == val(fmt, mx) + val(fmt, half_ulp)
        # a hair above the threshold: overflow to an infinity, both
        # results, overflow and inexact
        one_ulp = sf.round_pack(fmt, 0, 1, fmt.emax - fmt.prec + 1,
                                sf.RND_RNE)[0]
        r2, e2, fl2 = augmented_add(fmt, mx, one_ulp)
        assert r2 == inf_bits(fmt, 0) and e2 == inf_bits(fmt, 0)
        assert fl2 == FLAG_OVERFLOW | FLAG_INEXACT
        r3, e3, fl3 = augmented_add(fmt, negate(fmt, mx), negate(fmt, one_ulp))
        assert r3 == inf_bits(fmt, 1) and e3 == inf_bits(fmt, 1)
        assert fl3 == FLAG_OVERFLOW | FLAG_INEXACT


def test_zero_error_term_takes_the_sign_of_r():
    """"where if x + y - roundTiesTowardZero(x + y) equals zero, it is
    returned with the sign of roundTiesTowardZero(x + y)" - NOT the sign
    the arithmetic would give a zero."""
    for fmt in ALL_FORMATS:
        neg_one = sf.one_bits(fmt, 1)
        r, e, fl = augmented_add(fmt, neg_one, zero_bits(fmt, 0))
        assert (r, e, fl) == (neg_one, zero_bits(fmt, 1), 0), fmt.name
        # exact cancellation: 6.3 makes r a PLUS zero in every attribute
        # but roundTowardNegative, and roundTiesTowardZero is not it
        r, e, fl = augmented_add(fmt, one_bits(fmt), neg_one)
        assert (r, e, fl) == (zero_bits(fmt, 0), zero_bits(fmt, 0), 0)
        # like-signed zeros keep their sign, and e follows r
        r, e, fl = augmented_add(fmt, zero_bits(fmt, 1), zero_bits(fmt, 1))
        assert (r, e, fl) == (zero_bits(fmt, 1), zero_bits(fmt, 1), 0)
        # a product's zero takes the XOR of the operand signs
        r, e, fl = augmented_mul(fmt, zero_bits(fmt, 0), sf.one_bits(fmt, 1))
        assert (r, e, fl) == (zero_bits(fmt, 1), zero_bits(fmt, 1), 0)
        # subtraction is addition of the negation, zeros included
        r, e, fl = augmented_sub(fmt, zero_bits(fmt, 0), zero_bits(fmt, 0))
        assert (r, e, fl) == (zero_bits(fmt, 0), zero_bits(fmt, 0), 0)
        r, e, fl = augmented_sub(fmt, zero_bits(fmt, 1), zero_bits(fmt, 0))
        assert (r, e, fl) == (zero_bits(fmt, 1), zero_bits(fmt, 1), 0)


def test_nan_and_infinity_pairs():
    """"The operation propagates a NaN as both results if any input is a
    NaN", "If roundTiesTowardZero(x + y) is infinite, both produced
    results are the result", "If the operation signals the invalid
    operation exception, it produces the same quiet NaN for both
    outputs"."""
    for fmt in ALL_FORMATS:
        q = qnan_bits(fmt)
        for fn in (augmented_add, augmented_sub, augmented_mul):
            assert fn(fmt, q, one_bits(fmt)) == (q, q, 0)
            assert fn(fmt, snan_bits(fmt), one_bits(fmt)) == \
                (q, q, FLAG_INVALID)
            assert fn(fmt, one_bits(fmt), q | 0x5) == (q, q, 0)
        # an infinity that is not an overflow signals nothing
        inf = inf_bits(fmt, 0)
        assert augmented_add(fmt, inf, one_bits(fmt)) == (inf, inf, 0)
        assert augmented_add(fmt, inf, inf) == (inf, inf, 0)
        assert augmented_mul(fmt, inf, sf.one_bits(fmt, 1)) == \
            (inf_bits(fmt, 1), inf_bits(fmt, 1), 0)
        assert augmented_sub(fmt, inf, inf) == (q, q, FLAG_INVALID)
        assert augmented_add(fmt, inf, inf_bits(fmt, 1)) == \
            (q, q, FLAG_INVALID)
        assert augmented_mul(fmt, inf, zero_bits(fmt, 0)) == \
            (q, q, FLAG_INVALID)


def test_subnormal_residual_raises_underflow_without_inexact():
    """"If x + y - roundTiesTowardZero(x + y) is non-zero and lies
    strictly between +-b^emin, the underflow exception shall be
    signaled" - and inexact is signalled "only when
    roundTiesTowardZero(x + y) overflows". So an exact subnormal
    residual raises UNDERFLOW ALONE, a combination this contract admits
    nowhere else."""
    for fmt in ALL_FORMATS:
        big = one_bits(fmt)
        tiny = min_subnormal_bits(fmt)
        r, e, flags = augmented_add(fmt, big, tiny)
        assert r == big and e == tiny
        assert flags == FLAG_UNDERFLOW, (fmt.name, flags)
        assert not (flags & FLAG_INEXACT)
        assert val(fmt, r) + val(fmt, e) == val(fmt, big) + val(fmt, tiny)
        # the residual one step ABOVE the subnormal range raises nothing
        r, e, flags = augmented_add(fmt, sf.round_pack(
            fmt, 0, 1, fmt.emin + fmt.prec, sf.RND_RNE)[0],
            min_normal_bits(fmt))
        assert e == min_normal_bits(fmt) and flags == 0, (fmt.name, flags)


def test_multiplication_residual_that_the_format_cannot_hold():
    """"the results are roundTiesTowardZero(x x y) and the infinitely
    precise result of x x y - roundTiesTowardZero(x x y) rounded to
    sourceFormat using roundTiesTowardZero. Default exception handling
    raises the underflow flag and signals the inexact exception in this
    case." The witness: the smallest subnormal squared is far below the
    grid, so r is +0 and the residual rounds to +0 too."""
    for fmt in ALL_FORMATS:
        s = min_subnormal_bits(fmt)
        r, e, flags = augmented_mul(fmt, s, s)
        assert r == zero_bits(fmt, 0) and e == zero_bits(fmt, 0)
        assert flags == FLAG_UNDERFLOW | FLAG_INEXACT, (fmt.name, flags)
        # sign: a residual that ROUNDS to zero keeps the sign of the
        # exact value (6.3), which is not r's rule for an exact zero
        r, e, flags = augmented_mul(fmt, s, sf.one_bits(fmt, 1))
        assert r == sf.zero_bits(fmt, 1) or r == negate(fmt, s)
    # a residual that is non-zero, below the grid, and NEGATIVE while r
    # is positive: p+1 significant bits in the product, rounded up
    fmt = FP32
    a = sf.round_pack(fmt, 0, (1 << fmt.prec) - 1,
                      fmt.emin - fmt.man_w, sf.RND_RNE)[0]
    b = sf.round_pack(fmt, 0, (1 << fmt.prec) - 1, -(fmt.prec - 1),
                      sf.RND_RNE)[0]
    r, e, flags = augmented_mul(fmt, a, b)
    assert flags & FLAG_UNDERFLOW
    if flags & FLAG_INEXACT:
        assert val(fmt, r) + val(fmt, e) != val(fmt, a) * val(fmt, b)


# ---- 4. the pair identity --------------------------------------------

@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_r_plus_e_is_exactly_x_op_y(fmt):
    """The whole point of the pair, as exact integers rather than as a
    tolerance: r + e == x + y and r + e == x * y over the entire pool,
    with the two documented exclusions - an overflowed result (both
    outputs are an infinity) and augmentedMultiplication's
    non-representable residual, which 9.5 delivers rounded and marks
    with underflow AND inexact."""
    pairs = vectors.augmented_pairs(fmt, POOL_EXTRA)
    exact_cases = lost_cases = 0
    for a, b in pairs:
        for name, fn in OPS.items():
            r, e, flags = fn(fmt, a, b)
            if is_nan_bits(fmt, r) or flags & FLAG_OVERFLOW:
                continue
            ua, ub = sf.unpack(fmt, a), sf.unpack(fmt, b)
            if sf.INF in (ua.kind, ub.kind):
                continue
            if name == "mul" and (flags & FLAG_INEXACT):
                lost_cases += 1                # the one 9.5 case that loses
                continue
            xa, xb = dyadic(fmt, a), dyadic(fmt, b)
            want = dmul(xa, xb) if name == "mul" else \
                (dadd(xa, dneg(xb)) if name == "sub" else dadd(xa, xb))
            assert dadd(dyadic(fmt, r), dyadic(fmt, e)) == want, \
                (fmt.name, name, hex(a), hex(b), hex(r), hex(e))
            exact_cases += 1
    assert exact_cases > 8000, exact_cases
    assert lost_cases > 0, "the non-representable residual case is unreached"


# ---- 5. the sixth rounding stays where it was put --------------------

def test_no_public_operation_accepts_the_sixth_rounding():
    """RND_RTTZ is a rounding DIRECTION round_pack understands, not an
    attribute. Every operation that takes an attribute must refuse it,
    or 9.5's rule would leak into arithmetic the standard defines
    otherwise."""
    fmt = FP32
    one = one_bits(fmt)
    for call in (lambda r: sf.add(fmt, one, one, r),
                 lambda r: sf.sub(fmt, one, one, r),
                 lambda r: sf.mul(fmt, one, one, r),
                 lambda r: sf.fma(fmt, one, one, one, r),
                 lambda r: sf.div(fmt, one, one, r),
                 lambda r: sf.sqrt(fmt, one, r),
                 lambda r: sf.round_int(fmt, one, r),
                 lambda r: sf.scaleb(fmt, one, 1, r),
                 lambda r: sf.convert(fmt, FP64, one, r),
                 lambda r: sf.from_int(fmt, 3, r),
                 lambda r: sf.to_int(fmt, one, 32, True, r)):
        for bad in (RND_RTTZ, 5, 6, 7, -1, 99):
            with pytest.raises(ValueError):
                call(bad)
    assert RND_RTTZ not in RND_MODES
    assert RND_RTTZ not in sf.RND_NAMES
    assert RND_RTTZ >= 8, "must not fit MODE[14:12], the attribute field"


def test_round_pack_still_answers_the_five_attributes_unchanged():
    """The sixth direction was added to round_pack, so this asserts the
    five it already had are untouched, against the exact-rational
    reference that shares no code with it. (The conformance replay makes
    the same statement over every published vector; this one fails
    first, and in this file.)"""
    for fmt in (FP32, FP64):
        f = rf(fmt)
        for a, b in sample(vectors.augmented_pairs(fmt, 4), 700):
            ua, ub = sf.unpack(fmt, a), sf.unpack(fmt, b)
            if ua.kind in (sf.NAN, sf.INF, sf.ZERO):
                continue
            if ub.kind in (sf.NAN, sf.INF, sf.ZERO):
                continue
            exact = val(fmt, a) + val(fmt, b)
            if exact == 0:
                continue
            for rnd in RND_MODES:
                assert sf.add(fmt, a, b, rnd) == \
                    ref754.ref_pack(f, exact, rnd), (fmt.name, rnd, hex(a),
                                                     hex(b))


def test_flag_words_are_only_the_combinations_95_admits():
    """Five, and no others: nothing, invalid, underflow alone,
    underflow with inexact (multiplication's lost residual), and
    overflow with inexact. In particular inexact NEVER appears alone and
    divideByZero can never appear at all."""
    admitted = {0, FLAG_INVALID, FLAG_UNDERFLOW,
                FLAG_UNDERFLOW | FLAG_INEXACT,
                FLAG_OVERFLOW | FLAG_INEXACT}
    seen = set()
    for fmt in ALL_FORMATS:
        for a, b in vectors.augmented_pairs(fmt, POOL_EXTRA):
            for fn in OPS.values():
                flags = fn(fmt, a, b)[2]
                assert flags in admitted, (fmt.name, hex(a), hex(b), flags)
                seen.add(flags)
    assert seen == admitted, seen


def test_dispatch_by_name():
    fmt = FP64
    for name, fn in zip(aug.AUG_FNS, (augmented_add, augmented_sub,
                                      augmented_mul)):
        assert aug.compute(fmt, name, one_bits(fmt), 1) == \
            fn(fmt, one_bits(fmt), 1)
    with pytest.raises(ValueError):
        aug.compute(fmt, "augmentedDivision", 0, 0)
    assert set(aug.AUG_IMPL) == set(aug.AUG_FNS)
    assert list(FORMATS)                                  # sanity on imports
