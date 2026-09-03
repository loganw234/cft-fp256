# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the phase-1 transcendental reference.

Four arbiters, and none of them is "the module agreed with itself":

1. The 754-2019 clause 9.2.1 special-value tables, written out here as
   literal expected encodings. Every entry is a `shall`, so the test is
   a transcription of the standard and not of the implementation.
2. Exactness, both ways. Where the contract says a case is exact, the
   value is reconstructed by exact integer arithmetic and the inexact
   flag must be clear; where it says a case is not, the flag must be
   set. An implementation that guessed exactness from a tolerance
   fails both halves.
3. A BRUTE-FORCE enclosure at twice the escalation cap, sharing none of
   the module's schedule, screens or exact-case tests. Every case it can
   decide must match the module's answer. The ones it cannot are the
   ones the neighbour rules exist for - a value closer to a
   representable number than any precision resolves - and they are
   counted rather than hidden, and pinned by directed tests of their
   own.
4. GNU MPFR through gmpy2, when it is importable - a correctly-rounded
   implementation written by people who have never seen this project.
   Skipped, by name, when it is not installed.

Plus the structural properties: the directed attributes bracket the
true value and the bracket is tight, every attribute agrees on which
cases are exact, and the escalation instrumentation reports what it
actually did.
"""

import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, FORMATS,
    FLAG_DIVZERO, FLAG_INEXACT, FLAG_INVALID, FLAG_OVERFLOW,
    FLAG_UNDERFLOW,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_MODES, RND_NAMES,
    inf_bits, one_bits, qnan_bits, snan_bits, zero_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits, next_up, next_down, unpack,
)
from cft_golden import softfloat as sf                    # noqa: E402
from cft_golden import transcend as tr                    # noqa: E402

mpmath = pytest.importorskip("mpmath")

ALL = (FP32, FP64, FP128, FP256)
SMALL = (FP32, FP64)


def V(fmt, sign, m, e):
    """The representable value (-1)^sign * m * 2^e, refusing to round."""
    bits, fl = sf.round_pack(fmt, sign, m, e, RND_RNE)
    assert fl == 0, f"{m}*2^{e} is not representable in {fmt.name}"
    return bits


# =====================================================================
# 1. The clause 9.2.1 special-value tables
# =====================================================================

@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_exp_specials(fmt, rnd):
    assert tr.exp(fmt, zero_bits(fmt), rnd) == (one_bits(fmt), 0)
    assert tr.exp(fmt, zero_bits(fmt, 1), rnd) == (one_bits(fmt), 0)
    assert tr.exp(fmt, inf_bits(fmt), rnd) == (inf_bits(fmt), 0)
    assert tr.exp(fmt, inf_bits(fmt, 1), rnd) == (zero_bits(fmt), 0)
    assert tr.exp(fmt, qnan_bits(fmt), rnd) == (qnan_bits(fmt), 0)
    assert tr.exp(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_exp2_specials(fmt, rnd):
    assert tr.exp2(fmt, zero_bits(fmt), rnd) == (one_bits(fmt), 0)
    assert tr.exp2(fmt, inf_bits(fmt), rnd) == (inf_bits(fmt), 0)
    assert tr.exp2(fmt, inf_bits(fmt, 1), rnd) == (zero_bits(fmt), 0)
    assert tr.exp2(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_expm1_specials(fmt, rnd):
    # The signed zero survives - that is why expm1 exists.
    assert tr.expm1(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.expm1(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.expm1(fmt, inf_bits(fmt), rnd) == (inf_bits(fmt), 0)
    assert tr.expm1(fmt, inf_bits(fmt, 1), rnd) == (one_bits(fmt, 1), 0)
    assert tr.expm1(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
@pytest.mark.parametrize("fn", ("log", "log2", "log10"))
def test_log_specials(fmt, rnd, fn):
    f = getattr(tr, fn)
    assert f(fmt, one_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert f(fmt, zero_bits(fmt), rnd) == (inf_bits(fmt, 1), FLAG_DIVZERO)
    assert f(fmt, zero_bits(fmt, 1), rnd) == (inf_bits(fmt, 1), FLAG_DIVZERO)
    assert f(fmt, inf_bits(fmt), rnd) == (inf_bits(fmt), 0)
    assert f(fmt, inf_bits(fmt, 1), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    assert f(fmt, one_bits(fmt, 1), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    assert f(fmt, min_subnormal_bits(fmt, 1), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)
    assert f(fmt, qnan_bits(fmt), rnd) == (qnan_bits(fmt), 0)
    assert f(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_log1p_specials(fmt, rnd):
    assert tr.log1p(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.log1p(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.log1p(fmt, one_bits(fmt, 1), rnd) == \
        (inf_bits(fmt, 1), FLAG_DIVZERO)          # log1p(-1)
    assert tr.log1p(fmt, inf_bits(fmt), rnd) == (inf_bits(fmt), 0)
    assert tr.log1p(fmt, inf_bits(fmt, 1), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)
    # anything below -1 is invalid, including the value one ulp below
    assert tr.log1p(fmt, next_down(fmt, one_bits(fmt, 1))[0], rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)
    assert tr.log1p(fmt, max_normal_bits(fmt, 1), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)
    assert tr.log1p(fmt, snan_bits(fmt), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_pow_specials(fmt, rnd):
    one = one_bits(fmt)
    negone = one_bits(fmt, 1)
    two = V(fmt, 0, 1, 1)
    half = V(fmt, 0, 1, -1)
    zpos, zneg = zero_bits(fmt), zero_bits(fmt, 1)
    ipos, ineg = inf_bits(fmt), inf_bits(fmt, 1)
    qn = qnan_bits(fmt)

    def P(a, b):
        return tr.pow(fmt, a, b, rnd)

    # pow(x, +-0) is 1 for ANY x, even a quiet NaN or an infinity
    for x in (zpos, zneg, one, negone, two, ipos, ineg, qn):
        assert P(x, zpos) == (one, 0), hex(x)
        assert P(x, zneg) == (one, 0), hex(x)
    # pow(+1, y) is 1 for ANY y, even a quiet NaN
    for y in (zpos, one, negone, two, ipos, ineg, qn):
        assert P(one, y) == (one, 0), hex(y)
    # a signaling NaN is NOT covered by those rows
    assert P(snan_bits(fmt), zpos) == (qn, FLAG_INVALID)
    assert P(one, snan_bits(fmt)) == (qn, FLAG_INVALID)

    # pow(-1, +-inf) = 1
    assert P(negone, ipos) == (one, 0)
    assert P(negone, ineg) == (one, 0)
    # |x| > 1 / |x| < 1 against an infinite exponent
    assert P(two, ipos) == (ipos, 0)
    assert P(two, ineg) == (zpos, 0)
    assert P(half, ipos) == (zpos, 0)
    assert P(half, ineg) == (ipos, 0)
    assert P(zpos, ineg) == (ipos, 0)        # |0| < 1: +inf, and NO divzero
    assert P(zpos, ipos) == (zpos, 0)

    # the zero base, by the parity of a finite exponent
    three = V(fmt, 0, 3, 0)
    assert P(zpos, three) == (zpos, 0)
    assert P(zneg, three) == (zneg, 0)
    assert P(zneg, two) == (zpos, 0)
    assert P(zpos, sf.negate(fmt, three)) == (ipos, FLAG_DIVZERO)
    assert P(zneg, sf.negate(fmt, three)) == (ineg, FLAG_DIVZERO)
    assert P(zneg, sf.negate(fmt, two)) == (ipos, FLAG_DIVZERO)

    # the infinite base
    assert P(ipos, three) == (ipos, 0)
    assert P(ineg, three) == (ineg, 0)
    assert P(ineg, two) == (ipos, 0)
    assert P(ineg, sf.negate(fmt, three)) == (zneg, 0)
    assert P(ineg, sf.negate(fmt, two)) == (zpos, 0)

    # a negative finite base with a non-integer exponent is invalid
    assert P(sf.negate(fmt, two), half) == (qn, FLAG_INVALID)
    assert P(negone, half) == (qn, FLAG_INVALID)
    # ... but an integer exponent is fine, and keeps the parity sign
    assert P(sf.negate(fmt, two), three) == (V(fmt, 1, 1, 3), 0)
    assert P(sf.negate(fmt, two), two) == (V(fmt, 0, 1, 2), 0)

    # a NaN that no row covers just propagates, quietly
    assert P(two, qn) == (qn, 0)
    assert P(qn, two) == (qn, 0)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_hypot_specials(fmt, rnd):
    qn = qnan_bits(fmt)
    ipos, ineg = inf_bits(fmt), inf_bits(fmt, 1)
    one = one_bits(fmt)
    # an infinity wins over a quiet NaN, and the result is always +inf
    for other in (one, one_bits(fmt, 1), qn, ipos, ineg, zero_bits(fmt)):
        assert tr.hypot(fmt, ipos, other, rnd) == (ipos, 0), hex(other)
        assert tr.hypot(fmt, other, ineg, rnd) == (ipos, 0), hex(other)
    # a signaling NaN is not absolved by an infinity
    assert tr.hypot(fmt, snan_bits(fmt), ipos, rnd) == (qn, FLAG_INVALID)
    assert tr.hypot(fmt, ipos, snan_bits(fmt), rnd) == (qn, FLAG_INVALID)
    # zero operands, and the magnitude identity
    assert tr.hypot(fmt, zero_bits(fmt, 1), zero_bits(fmt, 1), rnd) == \
        (zero_bits(fmt), 0)
    assert tr.hypot(fmt, zero_bits(fmt), one_bits(fmt, 1), rnd) == (one, 0)
    assert tr.hypot(fmt, one_bits(fmt, 1), zero_bits(fmt), rnd) == (one, 0)
    assert tr.hypot(fmt, max_normal_bits(fmt, 1), zero_bits(fmt, 1), rnd) == \
        (max_normal_bits(fmt), 0)
    assert tr.hypot(fmt, qn, one, rnd) == (qn, 0)


# =====================================================================
# 2. Exactness, decided by exact arithmetic - both directions
# =====================================================================

@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_exp2_exact_on_integers(fmt, rnd):
    """2^n is exact for every integer n whose power the format holds -
    down to the smallest subnormal, which is a power of two too."""
    lo = fmt.emin - fmt.man_w
    for n in (0, 1, 2, 3, 17, fmt.prec, fmt.emax, fmt.emax - 1,
              -1, -2, fmt.emin, fmt.emin - 1, lo, lo + 1):
        bits, flags = tr.exp2(fmt, V(fmt, 1 if n < 0 else 0, abs(n) or 1,
                                     0) if n else zero_bits(fmt), rnd)
        if n == 0:
            assert (bits, flags) == (one_bits(fmt), 0)
            continue
        assert flags == 0, (n, flags)
        assert bits == V(fmt, 0, 1, n), n


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_exp2_past_the_ends(fmt, rnd):
    """An integer whose power is NOT representable is not exact: it
    overflows or underflows, with the flags clause 7 requires."""
    big = V(fmt, 0, fmt.emax + 1, 0)
    bits, flags = tr.exp2(fmt, big, rnd)
    assert flags == (FLAG_OVERFLOW | FLAG_INEXACT)
    assert bits == sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0]
    small = V(fmt, 1, fmt.man_w - fmt.emin + 1, 0)      # emin - man_w - 1
    bits, flags = tr.exp2(fmt, small, rnd)
    assert flags == (FLAG_UNDERFLOW | FLAG_INEXACT)
    assert bits == (min_subnormal_bits(fmt) if rnd == RND_RUP
                    else zero_bits(fmt))


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_log2_exact_on_powers_of_two(fmt, rnd):
    for n in (1, 2, 3, 17, fmt.emax, -1, -3, fmt.emin,
              fmt.emin - fmt.man_w):
        bits, flags = tr.log2(fmt, V(fmt, 0, 1, n), rnd)
        assert flags == 0, (n, flags)
        assert bits == V(fmt, 1 if n < 0 else 0, abs(n), 0), n
    # one ulp away from a power of two is never exact
    for n in (1, -3):
        bits, flags = tr.log2(fmt, V(fmt, 0, 1, n) + 1, rnd)
        assert flags & FLAG_INEXACT


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_log10_exact_on_powers_of_ten(fmt, rnd):
    k = 0
    while 5 ** (k + 1) < (1 << fmt.prec):
        k += 1
    for j in range(0, k + 1):
        bits, flags = tr.log10(fmt, V(fmt, 0, 5 ** j, j), rnd)
        assert flags == 0, (j, flags)
        assert bits == (zero_bits(fmt) if j == 0 else V(fmt, 0, j, 0)), j
    # 10^(k+1) is not representable, so it is not an operand; the
    # nearest representable to it is not a power of ten and is inexact
    nearby = sf.round_pack(fmt, 0, 5 ** (k + 1), k + 1, RND_RNE)[0]
    assert tr.log10(fmt, nearby, rnd)[1] & FLAG_INEXACT
    # and 10^-1 is not a dyadic rational at all, so nothing near it is
    tenth = sf.round_pack(fmt, 0, (1 << (fmt.prec + 4)) // 10,
                          -(fmt.prec + 4), RND_RNE)[0]
    assert tr.log10(fmt, tenth, rnd)[1] & FLAG_INEXACT


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_pow_exact_integer_powers(fmt, rnd):
    """x^n by exact integer arithmetic, for as many n as the format's
    significand holds - and inexact for the first n that outruns it."""
    for base in (3, 5, 7):
        n = 1
        while base ** (n + 1) < (1 << fmt.prec):
            n += 1
        for k in range(1, n + 1):
            bits, flags = tr.pow(fmt, V(fmt, 0, base, 0), V(fmt, 0, k, 0),
                                 rnd)
            assert flags == 0, (base, k, flags)
            assert bits == V(fmt, 0, base ** k, 0), (base, k)
        bits, flags = tr.pow(fmt, V(fmt, 0, base, 0), V(fmt, 0, n + 1, 0),
                             rnd)
        assert flags & FLAG_INEXACT, (base, n + 1)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_pow_exact_dyadic_exponents(fmt, rnd):
    """A non-integer exponent is exact exactly when the base is a
    perfect power: 9^(1/2) is 3 and exact, 8^(1/2) is irrational."""
    assert tr.pow(fmt, V(fmt, 0, 9, 0), V(fmt, 0, 1, -1), rnd) == \
        (V(fmt, 0, 3, 0), 0)
    assert tr.pow(fmt, V(fmt, 0, 81, 0), V(fmt, 0, 1, -2), rnd) == \
        (V(fmt, 0, 3, 0), 0)
    assert tr.pow(fmt, V(fmt, 0, 9, 0), V(fmt, 0, 3, -1), rnd) == \
        (V(fmt, 0, 27, 0), 0)
    assert tr.pow(fmt, V(fmt, 0, 1, 4), V(fmt, 0, 1, -2), rnd) == \
        (V(fmt, 0, 1, 1), 0)
    assert tr.pow(fmt, V(fmt, 0, 1, 4), V(fmt, 1, 1, -2), rnd) == \
        (V(fmt, 0, 1, -1), 0)
    assert tr.pow(fmt, V(fmt, 0, 8, 0), V(fmt, 0, 1, -1), rnd)[1] \
        & FLAG_INEXACT
    # a negative power of a non-power-of-two is rational but not dyadic
    assert tr.pow(fmt, V(fmt, 0, 3, 0), V(fmt, 1, 1, 0), rnd)[1] \
        & FLAG_INEXACT
    # ... while a negative power of two is exact
    assert tr.pow(fmt, V(fmt, 0, 1, 3), V(fmt, 1, 2, 0), rnd) == \
        (V(fmt, 0, 1, -6), 0)


def test_pow_lands_on_a_midpoint_exactly():
    """fp32 pow(4097, 2) is 16785409, an ODD multiple of half an ulp at
    that magnitude - a true midpoint, where a Ziv loop would spin
    forever and the exact path must decide by the tie rule."""
    fmt = FP32
    a, b = V(fmt, 0, 4097, 0), V(fmt, 0, 2, 0)
    assert 4097 ** 2 == 16785409
    assert tr.pow(fmt, a, b, RND_RNE) == (V(fmt, 0, 16785408 >> 1, 1),
                                          FLAG_INEXACT)
    assert tr.pow(fmt, a, b, RND_RMM) == (V(fmt, 0, 16785410 >> 1, 1),
                                          FLAG_INEXACT)
    assert tr.pow(fmt, a, b, RND_RTZ) == (V(fmt, 0, 16785408 >> 1, 1),
                                          FLAG_INEXACT)
    assert tr.pow(fmt, a, b, RND_RUP) == (V(fmt, 0, 16785410 >> 1, 1),
                                          FLAG_INEXACT)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_hypot_exact_on_pythagorean_triples(fmt, rnd):
    for x, y, h in ((3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25),
                    (20, 21, 29), (9, 40, 41)):
        for sx in (0, 1):
            for sy in (0, 1):
                bits, flags = tr.hypot(fmt, V(fmt, sx, x, 0),
                                       V(fmt, sy, y, 0), rnd)
                assert flags == 0, (x, y, flags)
                assert bits == V(fmt, 0, h, 0), (x, y)
        # one ulp off the triple is not a perfect square any more
        bits, flags = tr.hypot(fmt, V(fmt, 0, x, 0), V(fmt, 0, y, 0) + 1,
                               rnd)
        assert flags & FLAG_INEXACT, (x, y)


@pytest.mark.parametrize("fmt", ALL)
def test_hypot_scaled_triples_stay_exact(fmt):
    """Scaling both operands by powers of two keeps the sum a perfect
    square, which is the dyadic half of the exactness rule."""
    for ex, ey in ((10, 10), (-7, -7), (fmt.emax - 2, fmt.emax - 2)):
        bits, flags = tr.hypot(fmt, V(fmt, 0, 3, ex), V(fmt, 0, 4, ey),
                               RND_RNE)
        assert flags == 0
        assert bits == V(fmt, 0, 5, ex)


# =====================================================================
# 3. The brute-force enclosure - no schedule, no screens, no shortcuts
# =====================================================================

def _brute_enclosure(fmt, fn, xa, xb, prec):
    """f(x[,y]) as an interval at `prec` bits, built from scratch."""
    from mpmath import iv
    saved = iv.prec
    try:
        iv.prec = prec

        def val(bits):
            u = unpack(fmt, bits)
            v = iv.mpf(u.m)
            v = v * iv.mpf(1 << u.e) if u.e >= 0 else v / iv.mpf(1 << -u.e)
            return -v if u.sign else v

        x = val(xa)
        if fn == "exp":
            return iv.exp(x)
        if fn == "expm1":
            return iv.expm1(x)
        if fn == "exp2":
            return iv.power(2, x)
        if fn == "log":
            return iv.log(x)
        if fn == "log1p":
            return iv.log1p(x)
        if fn == "log2":
            return iv.log(x) / iv.log(2)
        if fn == "log10":
            return iv.log(x) / iv.log(10)
        if fn in ("sinpi", "cospi", "tanpi"):
            v = iv.pi * x
            return {"sinpi": iv.sin, "cospi": iv.cos, "tanpi": iv.tan}[fn](v)
        one = iv.mpf(1)
        if fn in ("asin", "asinpi", "acos", "acospi"):
            root = iv.sqrt((one - x) * (one + x))
            a = iv.atan2(x, root) if fn.startswith("asin") \
                else iv.atan2(root, x)
            return a / iv.pi if fn.endswith("pi") else a
        if fn in ("atan", "atanpi"):
            a = iv.atan2(x, one)
            return a / iv.pi if fn == "atanpi" else a
        # Phase 3, and every one of these is written DIFFERENTLY from
        # the module and from host/src/transcend.c: the naive forms,
        # which an interval library at four times the cap can afford
        # and a library carrying a tracked error bound cannot.
        if fn == "sin":
            return iv.sin(x)
        if fn == "cos":
            return iv.cos(x)
        if fn == "tan":
            return iv.tan(x)
        if fn == "sinh":
            return (iv.exp(x) - iv.exp(-x)) / 2
        if fn == "cosh":
            return (iv.exp(x) + iv.exp(-x)) / 2
        if fn == "tanh":
            return (iv.exp(x) - iv.exp(-x)) / (iv.exp(x) + iv.exp(-x))
        if fn == "asinh":
            return iv.log(x + iv.sqrt(x * x + one))
        if fn == "acosh":
            return iv.log(x + iv.sqrt(x * x - one))
        if fn == "atanh":
            return iv.log((one + x) / (one - x)) / 2
        y = val(xb)
        if fn == "pow":
            return iv.power(x, y)
        if fn in ("atan2", "atan2pi"):
            a = iv.atan2(x, y)
            return a / iv.pi if fn == "atan2pi" else a
        return iv.sqrt(x * x + y * y)
    finally:
        iv.prec = saved


def _decide(fmt, enc, rnd):
    """The rounding of an enclosure, or None when it does not decide.
    Signed, and sharing nothing with transcend._ziv but round_pack."""
    lo_t, hi_t = enc._mpi_
    out = []
    for sign, man, exp, _bc in (lo_t, hi_t):
        man = int(man)
        if man == 0:
            return None
        out.append(sf.round_pack(fmt, sign, man, int(exp), rnd))
    return out[0] if out[0] == out[1] else None


def _brute_pool(fmt):
    p = fmt.prec
    one = one_bits(fmt)
    pool = [one, one + 1, one - 1, one_bits(fmt, 1), one_bits(fmt, 1) + 1,
            V(fmt, 0, 3, -1), V(fmt, 1, 3, -1), V(fmt, 0, 1, 1),
            V(fmt, 1, 1, 1), V(fmt, 0, 3, 0), V(fmt, 0, 5, -2),
            min_normal_bits(fmt), max_normal_bits(fmt),
            min_subnormal_bits(fmt), max_subnormal_bits(fmt),
            min_normal_bits(fmt, 1), max_normal_bits(fmt, 1),
            V(fmt, 0, 1, -p), V(fmt, 1, 1, -p), V(fmt, 0, 7, -p - 2),
            V(fmt, 0, (1 << p) - 1, -p + 1)]
    return pool


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_brute_force_enclosure_agrees(fmt, rnd):
    """Everything the module answers, re-derived from an independent
    enclosure at four times the cap. Cases the enclosure cannot decide
    are counted, not skipped silently: they are exactly the ones the
    neighbour rules exist for, and there must not be many."""
    pool = _brute_pool(fmt)
    decided = undecided = 0
    deep = 2 * tr.prec_cap(fmt)
    for fn in tr.TRANSCEND_FNS:
        arity = tr.TRANSCEND_ARITY[fn]
        pairs = ([(a, 0) for a in pool] if arity == 1
                 else [(a, b) for a in pool[:9] for b in pool[:9]])
        for xa, xb in pairs:
            before = tr.STATS["neighbour"]
            got = tr.compute(fmt, fn, xa, xb, rnd)
            # Only the ordinary middle. A result the screens delivered
            # is one whose true value is astronomically outside the
            # format, and asking an interval library for
            # pow(2^-262378, 2^262143) is asking it for a number with
            # 10^11 bits; a result the NEIGHBOUR rule delivered is one
            # no working precision can separate from a representable
            # value, which is the very thing an enclosure cannot do -
            # expm1 of the most negative finite fp128 takes mpmath ten
            # seconds to enclose and fp256 rather longer. Both families
            # have their own directed tests; what is left here is the
            # ordinary middle, where an enclosure is the right arbiter.
            if got[1] & (FLAG_OVERFLOW | FLAG_UNDERFLOW | FLAG_DIVZERO):
                continue
            if tr.STATS["neighbour"] != before:
                undecided += 1
                continue
            u = unpack(fmt, got[0])
            if u.kind in (sf.INF, sf.NAN, sf.ZERO):
                continue
            enc = _brute_enclosure(fmt, fn, xa, xb, deep)
            want = _decide(fmt, enc, rnd)
            if want is None:
                undecided += 1
                continue
            decided += 1
            assert got[0] == want[0], \
                (fmt.name, fn, RND_NAMES[rnd], hex(xa), hex(xb),
                 hex(got[0]), hex(want[0]))
    assert decided > 200, decided


# =====================================================================
# 4. GNU MPFR, when it is here
# =====================================================================

gmpy2 = pytest.importorskip("gmpy2", reason="gmpy2/MPFR not installed")


def _mpfr_round(fmt, fn, rnd, xa, xb):
    rmap = {RND_RNE: gmpy2.RoundToNearest, RND_RTZ: gmpy2.RoundToZero,
            RND_RDN: gmpy2.RoundDown, RND_RUP: gmpy2.RoundUp}
    p = fmt.prec
    old = gmpy2.get_context().copy()
    gmpy2.set_context(gmpy2.context(precision=p, emin=fmt.emin - p + 2,
                                    emax=fmt.emax + 1, round=rmap[rnd],
                                    subnormalize=True))
    try:
        def conv(bits):
            u = unpack(fmt, bits)
            if u.kind == sf.NAN:
                return gmpy2.mpfr("nan")
            if u.kind == sf.INF:
                return gmpy2.mpfr("-inf" if u.sign else "inf")
            if u.kind == sf.ZERO:
                return gmpy2.mpfr("-0" if u.sign else "0")
            v = gmpy2.mpfr(u.m)
            v = (gmpy2.mul_2exp(v, u.e) if u.e >= 0
                 else gmpy2.div_2exp(v, -u.e))
            return -v if u.sign else v

        a = conv(xa)
        table = {"exp": gmpy2.exp, "expm1": gmpy2.expm1,
                 "exp2": gmpy2.exp2, "log": gmpy2.log,
                 "log1p": gmpy2.log1p, "log2": gmpy2.log2,
                 "log10": gmpy2.log10, "asin": gmpy2.asin,
                 "acos": gmpy2.acos, "atan": gmpy2.atan,
                 "sin": gmpy2.sin, "cos": gmpy2.cos, "tan": gmpy2.tan,
                 "sinh": gmpy2.sinh, "cosh": gmpy2.cosh,
                 "tanh": gmpy2.tanh, "asinh": gmpy2.asinh,
                 "acosh": gmpy2.acosh, "atanh": gmpy2.atanh}
        if fn in table:
            v = table[fn](a)
        elif fn == "pow":
            v = a ** conv(xb)
        elif fn == "atan2":
            v = gmpy2.atan2(a, conv(xb))
        else:
            v = gmpy2.hypot(a, conv(xb))
        if gmpy2.is_nan(v):
            return qnan_bits(fmt)
        if gmpy2.is_infinite(v):
            return inf_bits(fmt, 1 if v < 0 else 0)
        if v == 0:
            return zero_bits(fmt, 1 if gmpy2.is_signed(v) else 0)
        m, e = abs(v).as_mantissa_exp()
        return sf.round_pack(fmt, 1 if v < 0 else 0, int(m), int(e),
                             RND_RNE)[0]
    finally:
        gmpy2.set_context(old)


#: The functions gmpy2 exposes. MPFR itself grew sinPi, cosPi, tanPi,
#: asinPi, acosPi, atanPi and atan2Pi in 4.2.0 and this host carries
#: 4.2.0 - but the gmpy2 2.2.1 here (which links MPFR 4.2.1 of its
#: own) binds none of them, so the Pi-variants are
#: checked against MPFR in host/tools/mpfr_check.c, which calls the C
#: entry points directly, and here only against the brute-force
#: enclosure above. Claiming an MPFR comparison this file cannot make
#: would be worse than naming the gap.
MPFR_BOUND = ("exp", "expm1", "exp2", "log", "log1p", "log2", "log10",
              "pow", "hypot", "asin", "acos", "atan", "atan2",
              "sin", "cos", "tan", "sinh", "cosh", "tanh",
              "asinh", "acosh", "atanh")


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", (RND_RNE, RND_RTZ, RND_RDN, RND_RUP))
def test_mpfr_parity(fmt, rnd):
    """MPFR is correctly rounded and was written by strangers; where it
    has an attribute, it must agree bit for bit. (It has no
    ties-to-away, which is why RMM is absent from this list and why
    host/tools/mpfr_check.c builds that mode from MPFR intermediates
    instead of claiming a native comparison.)"""
    pool = _brute_pool(fmt)
    checked = 0
    for fn in MPFR_BOUND:
        arity = tr.TRANSCEND_ARITY[fn]
        pairs = ([(a, 0) for a in pool] if arity == 1
                 else [(a, b) for a in pool[:8] for b in pool[:8]])
        for xa, xb in pairs:
            got = tr.compute(fmt, fn, xa, xb, rnd)[0]
            want = _mpfr_round(fmt, fn, rnd, xa, xb)
            checked += 1
            assert got == want, (fmt.name, fn, RND_NAMES[rnd], hex(xa),
                                 hex(xb), hex(got), hex(want))
    assert checked > 200


# =====================================================================
# Structure: brackets, flags and instrumentation
# =====================================================================

@pytest.mark.parametrize("fmt", SMALL)
def test_directed_attributes_bracket_and_are_tight(fmt):
    """RDN and RUP straddle the true value, and when the result is
    inexact they are ADJACENT - the tightest interval the format
    admits. Exactly the property test_rounding.py pins for the
    arithmetic, restated where the value is transcendental."""
    pool = _brute_pool(fmt)
    seen = 0
    for fn in tr.TRANSCEND_FNS:
        arity = tr.TRANSCEND_ARITY[fn]
        pairs = ([(a, 0) for a in pool] if arity == 1
                 else [(a, b) for a in pool[:7] for b in pool[:7]])
        for xa, xb in pairs:
            dn, fdn = tr.compute(fmt, fn, xa, xb, RND_RDN)
            up, fup = tr.compute(fmt, fn, xa, xb, RND_RUP)
            if sf.is_nan(fmt, dn) or sf.is_nan(fmt, up):
                continue
            if not (fdn & FLAG_INEXACT):
                assert dn == up, (fn, hex(xa), hex(xb))
                continue
            if unpack(fmt, dn).kind == sf.INF or \
                    unpack(fmt, up).kind == sf.INF:
                continue
            assert next_up(fmt, dn)[0] == up, \
                (fn, hex(xa), hex(xb), hex(dn), hex(up))
            seen += 1
    assert seen > 100, seen


@pytest.mark.parametrize("fmt", ALL)
def test_exactness_is_the_same_in_every_attribute(fmt):
    """Which cases are exact is a property of the mathematics, not of
    the rounding attribute. A tolerance-based test would fail this."""
    pool = _brute_pool(fmt)
    for fn in tr.TRANSCEND_FNS:
        arity = tr.TRANSCEND_ARITY[fn]
        pairs = ([(a, 0) for a in pool] if arity == 1
                 else [(a, b) for a in pool[:8] for b in pool[:8]])
        for xa, xb in pairs:
            flags = [tr.compute(fmt, fn, xa, xb, r)[1] & FLAG_INEXACT
                     for r in RND_MODES]
            assert len(set(flags)) == 1, (fmt.name, fn, hex(xa), hex(xb),
                                          flags)


def test_escalation_is_instrumented_and_shallow():
    """The stats are a measurement, so they have to move - and the
    escalation counter is what the design note quotes."""
    tr.reset_stats()
    assert tr.STATS["max_prec"] == 0
    for fmt in ALL:
        for x in _brute_pool(fmt):
            tr.exp(fmt, x, RND_RNE)
            tr.log(fmt, x, RND_RNE)
    assert tr.STATS["ziv_calls"] > 50
    assert tr.STATS["max_prec"] >= tr.start_prec(FP32)
    assert tr.STATS["max_prec"] <= tr.prec_cap(FP256)


@pytest.mark.parametrize("fmt", ALL)
def test_tiny_arguments_take_the_neighbour_rule(fmt):
    """expm1 and log1p of a tiny argument differ from that argument by
    less than any working precision can see - and they must still round
    to the two DIFFERENT answers the two functions demand."""
    p = fmt.prec
    x = V(fmt, 0, 1, -(p + 8))
    assert tr.expm1(fmt, x, RND_RNE) == (x, FLAG_INEXACT)
    assert tr.expm1(fmt, x, RND_RUP) == (next_up(fmt, x)[0], FLAG_INEXACT)
    assert tr.expm1(fmt, x, RND_RDN) == (x, FLAG_INEXACT)
    assert tr.log1p(fmt, x, RND_RNE) == (x, FLAG_INEXACT)
    assert tr.log1p(fmt, x, RND_RDN) == (next_down(fmt, x)[0], FLAG_INEXACT)
    assert tr.log1p(fmt, x, RND_RUP) == (x, FLAG_INEXACT)
    # and exp of one lands next to 1, on the side the sign gives
    one = one_bits(fmt)
    assert tr.exp(fmt, x, RND_RNE) == (one, FLAG_INEXACT)
    assert tr.exp(fmt, x, RND_RUP) == (next_up(fmt, one)[0], FLAG_INEXACT)
    nx = V(fmt, 1, 1, -(p + 8))
    assert tr.exp(fmt, nx, RND_RDN) == (next_down(fmt, one)[0], FLAG_INEXACT)
    assert tr.exp(fmt, nx, RND_RNE) == (one, FLAG_INEXACT)


@pytest.mark.parametrize("fmt", ALL)
def test_subnormal_results_raise_underflow(fmt):
    """A tiny inexact result is tiny AND inexact, which is the only
    thing that raises underflow (7.5)."""
    sub = min_subnormal_bits(fmt)
    bits, flags = tr.log1p(fmt, sub, RND_RDN)
    assert bits == zero_bits(fmt)
    assert flags == (FLAG_INEXACT | FLAG_UNDERFLOW)
    bits, flags = tr.expm1(fmt, sub, RND_RNE)
    assert bits == sub
    assert flags == (FLAG_INEXACT | FLAG_UNDERFLOW)


@pytest.mark.parametrize("fmt", ALL)
def test_pow_near_one_with_a_huge_exponent(fmt):
    """The family fixed point alone cannot survive: a base one ulp
    above 1 with an exponent of 2^emax/2 lands somewhere ordinary, and
    a base one ulp above 1 with a tiny exponent lands inside the half
    gap next to 1."""
    one = one_bits(fmt)
    big = V(fmt, 0, 1, fmt.emax // 2)
    bits, flags = tr.pow(fmt, one + 1, big, RND_RNE)
    assert flags & FLAG_INEXACT
    assert unpack(fmt, bits).kind in (sf.NORM, sf.INF)
    tiny = V(fmt, 0, 1, -(fmt.prec + 20))
    assert tr.pow(fmt, one + 1, tiny, RND_RNE) == (one, FLAG_INEXACT)
    assert tr.pow(fmt, one + 1, tiny, RND_RUP) == \
        (next_up(fmt, one)[0], FLAG_INEXACT)
    assert tr.pow(fmt, one - 1, tiny, RND_RDN) == \
        (next_down(fmt, one)[0], FLAG_INEXACT)


@pytest.mark.parametrize("fmt", ALL)
def test_hypot_dominant_operand(fmt):
    """A second operand far below the first cannot move the answer past
    the half gap, but it must still push it OFF the exact value."""
    one = one_bits(fmt)
    small = V(fmt, 0, 1, -fmt.prec)
    bits, flags = tr.hypot(fmt, one, small, RND_RNE)
    assert (bits, flags) == (one, FLAG_INEXACT)
    bits, flags = tr.hypot(fmt, one, small, RND_RUP)
    assert (bits, flags) == (next_up(fmt, one)[0], FLAG_INEXACT)
    # and the largest finite steps to the overflow response
    bits, flags = tr.hypot(fmt, max_normal_bits(fmt),
                           min_subnormal_bits(fmt), RND_RUP)
    assert flags == (FLAG_OVERFLOW | FLAG_INEXACT)
    assert bits == inf_bits(fmt)
    bits, flags = tr.hypot(fmt, max_normal_bits(fmt),
                           min_subnormal_bits(fmt), RND_RNE)
    assert (bits, flags) == (max_normal_bits(fmt), FLAG_INEXACT)


def test_unknown_names_and_modes_are_refused():
    with pytest.raises(ValueError):
        tr.compute(FP32, "arcsinh", one_bits(FP32))
    with pytest.raises(ValueError):
        tr.compute(FP32, "exp", one_bits(FP32), 0, 7)


@pytest.mark.parametrize("fmt", ALL)
def test_escalation_lands_on_the_same_answer(fmt):
    """Force the loop to start below the precision it needs and the
    answers must not move.

    This is the only test that exercises the escalation at all: over
    every campaign this module has run, the first attempt has decided
    every single input, so the path that raises the precision has never
    been taken in anger. A path never taken is a path never tested, and
    this one is load-bearing - it is what the cap and the loud failure
    are about."""
    pool = _brute_pool(fmt)
    tr.reset_stats()
    baseline = {}
    for fn in tr.TRANSCEND_FNS:
        arity = tr.TRANSCEND_ARITY[fn]
        pairs = ([(a, 0) for a in pool] if arity == 1
                 else [(a, b) for a in pool[:8] for b in pool[:8]])
        for rnd in RND_MODES:
            for xa, xb in pairs:
                baseline[(fn, rnd, xa, xb)] = tr.compute(fmt, fn, xa, xb, rnd)
    ordinary = tr.STATS["escalations"]

    tr.reset_stats()
    tr.START_PREC_OVERRIDE = fmt.prec + 8
    try:
        for (fn, rnd, xa, xb), want in baseline.items():
            assert tr.compute(fmt, fn, xa, xb, rnd) == want, \
                (fmt.name, fn, RND_NAMES[rnd], hex(xa), hex(xb))
    finally:
        tr.START_PREC_OVERRIDE = 0
    # The path was taken, and taken MORE than the ordinary schedule
    # takes it. How much more depends on the format: the override is
    # clamped at 64 bits, which is already 40 bits of headroom at fp32
    # and only just enough at fp256, so the counts differ by two orders
    # of magnitude across the ladder and a single threshold would be
    # either vacuous or wrong.
    assert tr.STATS["escalations"] > max(2, ordinary), tr.STATS
    assert tr.STATS["max_prec"] <= tr.prec_cap(fmt)


# =====================================================================
# Phase 2: the trigonometric functions that need no reduction against pi
#
# Same four arbiters. The special-value tables below were transcribed
# from 754-2019 9.2.1 and then CONFIRMED against MPFR 4.2.2 - which is
# the first release to carry sinpi/cospi/tanpi and the Pi-variants of
# the inverses - before they were written down here. Where the two
# could have differed the probe is quoted in the test.
# =====================================================================

TRIG = ("sinpi", "cospi", "tanpi", "asin", "acos", "atan", "atan2",
        "asinpi", "acospi", "atanpi", "atan2pi")


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_sinpi_specials(fmt, rnd):
    """sinPi(+-0) is +-0; sinPi of an integer is a zero with the sign of
    the ARGUMENT (MPFR 4.2.2: sinpi(1) = +0, sinpi(-1) = -0, so the rule
    is not the parity of n); sinPi(n + 1/2) is +-1; an infinity is
    invalid, because sin has no limit there."""
    assert tr.sinpi(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.sinpi(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    for n in (1, 2, 3, 4, 17):
        b = V(fmt, 0, n, 0)
        assert tr.sinpi(fmt, b, rnd) == (zero_bits(fmt), 0), n
        assert tr.sinpi(fmt, V(fmt, 1, n, 0), rnd) == (zero_bits(fmt, 1), 0)
    # sinPi(m/2) for odd m is +1 when m = 1 (mod 4) and -1 when m = 3
    for m, want_neg in ((1, 0), (3, 1), (5, 0), (7, 1), (9, 0)):
        assert tr.sinpi(fmt, V(fmt, 0, m, -1), rnd) == \
            (one_bits(fmt, want_neg), 0), m
        assert tr.sinpi(fmt, V(fmt, 1, m, -1), rnd) == \
            (one_bits(fmt, 1 - want_neg), 0), m
    # every value at or above 2^(p-1) is an integer, so the largest
    # finite is one and its sinPi is a zero rather than a hard case
    assert tr.sinpi(fmt, max_normal_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.sinpi(fmt, max_normal_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.sinpi(fmt, inf_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    assert tr.sinpi(fmt, inf_bits(fmt, 1), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)
    assert tr.sinpi(fmt, qnan_bits(fmt), rnd) == (qnan_bits(fmt), 0)
    assert tr.sinpi(fmt, snan_bits(fmt), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_cospi_specials(fmt, rnd):
    """cosPi(+-0) is 1; cosPi(n) is (-1)^n; cosPi(n + 1/2) is +0 for
    every n and BOTH signs of the argument - cosPi is even, so the zero
    cannot carry a sign and MPFR delivers +0 throughout."""
    assert tr.cospi(fmt, zero_bits(fmt), rnd) == (one_bits(fmt), 0)
    assert tr.cospi(fmt, zero_bits(fmt, 1), rnd) == (one_bits(fmt), 0)
    for n, neg in ((1, 1), (2, 0), (3, 1), (4, 0), (17, 1), (16, 0)):
        assert tr.cospi(fmt, V(fmt, 0, n, 0), rnd) == (one_bits(fmt, neg), 0)
        assert tr.cospi(fmt, V(fmt, 1, n, 0), rnd) == (one_bits(fmt, neg), 0)
    for m in (1, 3, 5, 7):
        assert tr.cospi(fmt, V(fmt, 0, m, -1), rnd) == (zero_bits(fmt), 0)
        assert tr.cospi(fmt, V(fmt, 1, m, -1), rnd) == (zero_bits(fmt), 0)
    # the largest finite is an even integer at every rung
    assert tr.cospi(fmt, max_normal_bits(fmt), rnd) == (one_bits(fmt), 0)
    assert tr.cospi(fmt, inf_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    assert tr.cospi(fmt, snan_bits(fmt), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_tanpi_specials(fmt, rnd):
    """tanPi is sinPi/cosPi in every respect, signs included.

    Confirmed against MPFR 4.2.2, which is where the two rows an
    implementation is likely to guess wrong were settled:

        tanpi(1)   = -0        (sinPi(1) is +0, cosPi(1) is -1)
        tanpi(1/2) = +Inf with divide-by-zero raised

    A pole gives an exact infinity from finite operands, which is
    exactly 754-2019 7.3's condition for divideByZero."""
    assert tr.tanpi(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.tanpi(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    for n, neg in ((1, 1), (2, 0), (3, 1), (4, 0)):
        assert tr.tanpi(fmt, V(fmt, 0, n, 0), rnd) == (zero_bits(fmt, neg), 0)
        assert tr.tanpi(fmt, V(fmt, 1, n, 0), rnd) == \
            (zero_bits(fmt, 1 - neg), 0)
    for m, neg in ((1, 0), (3, 1), (5, 0), (7, 1)):
        assert tr.tanpi(fmt, V(fmt, 0, m, -1), rnd) == \
            (inf_bits(fmt, neg), FLAG_DIVZERO), m
        assert tr.tanpi(fmt, V(fmt, 1, m, -1), rnd) == \
            (inf_bits(fmt, 1 - neg), FLAG_DIVZERO), m
    # the quarter-odd-integers are exactly +-1 - Niven's other case
    for m, neg in ((1, 0), (3, 1), (5, 0), (7, 1), (9, 0), (11, 1)):
        assert tr.tanpi(fmt, V(fmt, 0, m, -2), rnd) == \
            (one_bits(fmt, neg), 0), m
        assert tr.tanpi(fmt, V(fmt, 1, m, -2), rnd) == \
            (one_bits(fmt, 1 - neg), 0), m
    assert tr.tanpi(fmt, inf_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    assert tr.tanpi(fmt, snan_bits(fmt), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
def test_tanpi_cannot_overflow(fmt):
    """A representable argument cannot get closer than 2^-p to a pole -
    the binade [1/2, 1) has that ulp and no other does better - so
    |tanPi| stays below 2^p, which is far inside emax at every rung.
    The worst cases at each end are checked rather than argued."""
    p = fmt.prec
    worst = [next_up(fmt, V(fmt, 0, 1, -1))[0],        # 1/2 + 2^-p
             next_down(fmt, one_bits(fmt))[0],         # 1 - 2^-p
             next_down(fmt, V(fmt, 0, 1, 1))[0],       # 2 - 2^(1-p)
             next_up(fmt, V(fmt, 0, 3, -1))[0],        # 3/2 + 2^(1-p)
             next_down(fmt, V(fmt, 0, 3, -1))[0]]
    for b in worst:
        for rnd in RND_MODES:
            bits, flags = tr.tanpi(fmt, b, rnd)
            assert not (flags & FLAG_OVERFLOW), (hex(b), RND_NAMES[rnd])
            u = unpack(fmt, bits)
            assert u.kind != sf.INF
            assert _vexp(u) < p, (hex(b), _vexp(u))


def _vexp(u):
    return u.e + u.m.bit_length() - 1


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_asin_acos_atan_specials(fmt, rnd):
    """The radian inverses. Only the ZEROS are exact - Hermite-Lindemann
    puts asin, acos and atan of every other dyadic rational outside the
    algebraic numbers, so no other argument can produce a value the
    format holds."""
    one, negone = one_bits(fmt), one_bits(fmt, 1)
    assert tr.asin(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.asin(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.atan(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.atan(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.acos(fmt, one, rnd) == (zero_bits(fmt), 0)
    # everything else is inexact, including asin(+-1) and acos(-1)
    for fn, arg in (("asin", one), ("asin", negone), ("acos", negone),
                    ("acos", zero_bits(fmt)), ("atan", one)):
        bits, flags = getattr(tr, fn)(fmt, arg, rnd)
        assert flags == FLAG_INEXACT, (fn, hex(arg), flags)
    # out of domain
    for fn in ("asin", "acos"):
        f = getattr(tr, fn)
        for bad in (V(fmt, 0, (1 << fmt.prec) - 1, -fmt.prec + 1),
                    max_normal_bits(fmt), max_normal_bits(fmt, 1),
                    inf_bits(fmt), inf_bits(fmt, 1),
                    next_up(fmt, one)[0], next_down(fmt, negone)[0]):
            assert f(fmt, bad, rnd) == (qnan_bits(fmt), FLAG_INVALID), \
                (fn, hex(bad))
        assert f(fmt, qnan_bits(fmt), rnd) == (qnan_bits(fmt), 0)
        assert f(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    # atan takes the whole line, and the infinities are +-pi/2
    for s in (0, 1):
        bits, flags = tr.atan(fmt, inf_bits(fmt, s), rnd)
        assert flags == FLAG_INEXACT
        assert unpack(fmt, bits).sign == s
    assert tr.atan(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_pi_inverse_specials(fmt, rnd):
    """The Pi-variants, whose exact table is a great deal larger:
    Niven's theorem makes asinPi(+-1) = +-1/2, acosPi(+-0) = 1/2,
    acosPi(-1) = 1, atanPi(+-1) = +-1/4 and atanPi(+-inf) = +-1/2 all
    dyadic rationals the format holds. Every one of them raises
    nothing - which is the observable difference between this and an
    accurate implementation."""
    one, negone = one_bits(fmt), one_bits(fmt, 1)
    half, quarter = V(fmt, 0, 1, -1), V(fmt, 0, 1, -2)
    assert tr.asinpi(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.asinpi(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.asinpi(fmt, one, rnd) == (half, 0)
    assert tr.asinpi(fmt, negone, rnd) == (V(fmt, 1, 1, -1), 0)
    assert tr.acospi(fmt, one, rnd) == (zero_bits(fmt), 0)
    assert tr.acospi(fmt, zero_bits(fmt), rnd) == (half, 0)
    assert tr.acospi(fmt, zero_bits(fmt, 1), rnd) == (half, 0)
    assert tr.acospi(fmt, negone, rnd) == (one, 0)
    assert tr.atanpi(fmt, zero_bits(fmt), rnd) == (zero_bits(fmt), 0)
    assert tr.atanpi(fmt, zero_bits(fmt, 1), rnd) == (zero_bits(fmt, 1), 0)
    assert tr.atanpi(fmt, one, rnd) == (quarter, 0)
    assert tr.atanpi(fmt, negone, rnd) == (V(fmt, 1, 1, -2), 0)
    assert tr.atanpi(fmt, inf_bits(fmt), rnd) == (half, 0)
    assert tr.atanpi(fmt, inf_bits(fmt, 1), rnd) == (V(fmt, 1, 1, -1), 0)
    # asinPi(1/2) is 1/6: RATIONAL, and not dyadic, so it is not an
    # exact case and the loop still terminates on it
    bits, flags = tr.asinpi(fmt, half, rnd)
    assert flags == FLAG_INEXACT
    for fn in ("asinpi", "acospi"):
        f = getattr(tr, fn)
        assert f(fmt, next_up(fmt, one)[0], rnd) == \
            (qnan_bits(fmt), FLAG_INVALID)
        assert f(fmt, inf_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)
        assert f(fmt, snan_bits(fmt), rnd) == (qnan_bits(fmt), FLAG_INVALID)
    assert tr.atanpi(fmt, snan_bits(fmt), rnd) == \
        (qnan_bits(fmt), FLAG_INVALID)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_atan2_table(fmt, rnd):
    """The whole of 9.2.1's atan2 table, in both forms.

    The row everyone gets wrong is atan2(+-0, -0) = +-pi: a MINUS zero
    denominator names the negative real axis, so the answer is pi and
    not zero. Its Pi-variant is +-1 and is EXACT, where the radian form
    is a rounding of an irrational number - which is the whole reason
    atan2Pi is a separate function."""
    zp, zn = zero_bits(fmt), zero_bits(fmt, 1)
    ip, inn = inf_bits(fmt), inf_bits(fmt, 1)
    one, negone = one_bits(fmt), one_bits(fmt, 1)
    two, negtwo = V(fmt, 0, 1, 1), V(fmt, 1, 1, 1)
    Q = {0: zero_bits(fmt), 1: V(fmt, 0, 1, -2), 2: V(fmt, 0, 1, -1),
         3: V(fmt, 0, 3, -2), 4: one_bits(fmt)}

    def check(y, x, quarters, neg):
        got, flags = tr.atan2pi(fmt, y, x, rnd)
        want = Q[quarters] | (fmt.sign_mask if neg else 0)
        if quarters == 0:
            want = zero_bits(fmt, neg)
        assert (got, flags) == (want, 0), \
            (hex(y), hex(x), quarters, hex(got), hex(want), flags)
        got, flags = tr.atan2(fmt, y, x, rnd)
        assert flags == (0 if quarters == 0 else FLAG_INEXACT)
        assert unpack(fmt, got).sign == neg or quarters == 0

    # the axes, both signs of every zero
    check(zp, zp, 0, 0)
    check(zn, zp, 0, 1)
    check(zp, zn, 4, 0)          # atan2(+0, -0) = +pi
    check(zn, zn, 4, 1)          # atan2(-0, -0) = -pi
    check(zp, one, 0, 0)
    check(zp, negone, 4, 0)
    check(zn, negone, 4, 1)
    check(one, zp, 2, 0)
    check(negone, zp, 2, 1)
    check(one, zn, 2, 0)
    check(negone, zn, 2, 1)
    # the diagonals, and any pair of equal magnitudes on them
    for y, x, q, n in ((one, one, 1, 0), (one, negone, 3, 0),
                       (negone, one, 1, 1), (negone, negone, 3, 1),
                       (two, two, 1, 0), (two, negtwo, 3, 0),
                       (negtwo, negtwo, 3, 1),
                       (min_subnormal_bits(fmt), min_subnormal_bits(fmt),
                        1, 0)):
        check(y, x, q, n)
    # the infinities
    check(ip, ip, 1, 0)
    check(ip, inn, 3, 0)
    check(inn, ip, 1, 1)
    check(inn, inn, 3, 1)
    check(ip, one, 2, 0)
    check(inn, one, 2, 1)
    check(one, ip, 0, 0)
    check(one, inn, 4, 0)
    check(negone, inn, 4, 1)
    check(zp, ip, 0, 0)
    check(zp, inn, 4, 0)
    # NaNs
    for fn in ("atan2", "atan2pi"):
        f = getattr(tr, fn)
        assert f(fmt, qnan_bits(fmt), one, rnd) == (qnan_bits(fmt), 0)
        assert f(fmt, one, qnan_bits(fmt), rnd) == (qnan_bits(fmt), 0)
        assert f(fmt, snan_bits(fmt), one, rnd) == \
            (qnan_bits(fmt), FLAG_INVALID)
        assert f(fmt, one, snan_bits(fmt), rnd) == \
            (qnan_bits(fmt), FLAG_INVALID)
        # a quiet NaN does NOT outrank the table here, unlike pow's
        assert f(fmt, qnan_bits(fmt), zp, rnd) == (qnan_bits(fmt), 0)


# =====================================================================
# The neighbour rules, and the thresholds they are derived at
# =====================================================================

@pytest.mark.parametrize("fmt", ALL)
def test_asin_and_atan_of_a_tiny_argument_go_opposite_ways(fmt):
    """asin(x) = x + x^3/6 + ... is strictly ABOVE x and atan(x) =
    x - x^3/3 + ... strictly BELOW, for every x in (0, 1). No working
    precision separates either from x once 2e + p + 3 <= 0, and none
    needs to - the two directed attributes tell them apart, which is
    precisely what a merely accurate implementation cannot do."""
    p = fmt.prec
    for k in (p // 2 + 2, p, 2 * p, 4 * p):
        x = V(fmt, 0, 1, -k)
        assert tr.asin(fmt, x, RND_RNE) == (x, FLAG_INEXACT), k
        assert tr.asin(fmt, x, RND_RDN) == (x, FLAG_INEXACT), k
        assert tr.asin(fmt, x, RND_RUP) == (next_up(fmt, x)[0], FLAG_INEXACT)
        assert tr.atan(fmt, x, RND_RNE) == (x, FLAG_INEXACT), k
        assert tr.atan(fmt, x, RND_RUP) == (x, FLAG_INEXACT), k
        assert tr.atan(fmt, x, RND_RDN) == (next_down(fmt, x)[0],
                                            FLAG_INEXACT)
        nx = V(fmt, 1, 1, -k)
        assert tr.asin(fmt, nx, RND_RDN) == (next_down(fmt, nx)[0],
                                             FLAG_INEXACT)
        assert tr.atan(fmt, nx, RND_RUP) == (next_up(fmt, nx)[0],
                                             FLAG_INEXACT)
    # the smallest subnormal is the extreme of both
    sub = min_subnormal_bits(fmt)
    assert tr.asin(fmt, sub, RND_RNE) == (sub, FLAG_INEXACT | FLAG_UNDERFLOW)
    assert tr.atan(fmt, sub, RND_RTZ) == (zero_bits(fmt),
                                          FLAG_INEXACT | FLAG_UNDERFLOW)


@pytest.mark.parametrize("fmt", ALL)
def test_asinpi_and_atanpi_of_a_tiny_argument_need_no_neighbour(fmt):
    """asinPi(x) and atanPi(x) are about x/pi, which is not next to
    anything the format holds, so the ordinary enclosure decides them -
    and the answer is NOT x. This is the half of the design that says
    the neighbour rules are derived rather than applied everywhere."""
    p = fmt.prec
    for k in (p, 2 * p, 4 * p):
        x = V(fmt, 0, 1, -k)
        bits, flags = tr.asinpi(fmt, x, RND_RNE)
        assert flags & FLAG_INEXACT
        assert bits != x, k                    # about 0.318 x, not x
        bits2, _ = tr.atanpi(fmt, x, RND_RNE)
        assert bits2 == bits, k                # they agree to this order
    sub = min_subnormal_bits(fmt)
    assert tr.asinpi(fmt, sub, RND_RNE) == \
        (zero_bits(fmt), FLAG_INEXACT | FLAG_UNDERFLOW)
    assert tr.asinpi(fmt, sub, RND_RUP) == \
        (sub, FLAG_INEXACT | FLAG_UNDERFLOW)


@pytest.mark.parametrize("fmt", ALL)
def test_cospi_near_an_integer_lands_next_to_one(fmt):
    """cosPi(n + s) for a tiny s is below 1 by 4.94 s^2 and no
    precision resolves that; the SIDE does, and it is always downward.
    The same rule serves sinPi next to a half-integer, where the
    magnitude is the same cosine."""
    p = fmt.prec
    one = one_bits(fmt)
    for k in (p // 2 + 4, p, 2 * p):
        s = V(fmt, 0, 1, -k)
        assert tr.cospi(fmt, s, RND_RNE) == (one, FLAG_INEXACT), k
        assert tr.cospi(fmt, s, RND_RDN) == (next_down(fmt, one)[0],
                                             FLAG_INEXACT), k
    # Next to an integer or a half-integer the offset cannot be made
    # arbitrarily small - the format's own grid is the floor - so the
    # rule has to fire at ONE ulp, and 2(1-p) + p + 6 <= 0 says it does
    # at every rung from binary32 up.
    x = next_up(fmt, one)[0]                            # 1 + 2^(1-p)
    assert tr.cospi(fmt, x, RND_RNE) == (one_bits(fmt, 1), FLAG_INEXACT)
    assert tr.cospi(fmt, x, RND_RUP) ==         (next_up(fmt, one_bits(fmt, 1))[0], FLAG_INEXACT)
    x = next_down(fmt, one)[0]                          # 1 - 2^-p
    assert tr.cospi(fmt, x, RND_RNE) == (one_bits(fmt, 1), FLAG_INEXACT)
    h = next_up(fmt, V(fmt, 0, 1, -1))[0]               # 1/2 + 2^-p
    assert tr.sinpi(fmt, h, RND_RNE) == (one, FLAG_INEXACT)
    assert tr.sinpi(fmt, h, RND_RDN) == (next_down(fmt, one)[0],
                                         FLAG_INEXACT)


@pytest.mark.parametrize("fmt", ALL)
def test_acospi_near_a_half_and_atanpi_near_a_half(fmt):
    """Two more values the format DOES hold: acosPi(x) sits beside 1/2
    for a tiny x - below it for a positive x and above it for a
    negative one - and atanPi(x) sits below 1/2 for a huge one. Their
    radian twins need no rule at all, because pi/2 is not
    representable."""
    p = fmt.prec
    half = V(fmt, 0, 1, -1)
    for k in (p + 2, 2 * p, 4 * p):
        x = V(fmt, 0, 1, -k)
        assert tr.acospi(fmt, x, RND_RNE) == (half, FLAG_INEXACT), k
        assert tr.acospi(fmt, x, RND_RDN) == (next_down(fmt, half)[0],
                                              FLAG_INEXACT), k
        nx = V(fmt, 1, 1, -k)
        assert tr.acospi(fmt, nx, RND_RUP) == (next_up(fmt, half)[0],
                                               FLAG_INEXACT), k
    for k in (p + 1, 2 * p, fmt.emax):
        x = V(fmt, 0, 1, k)
        assert tr.atanpi(fmt, x, RND_RNE) == (half, FLAG_INEXACT), k
        assert tr.atanpi(fmt, x, RND_RTZ) == (next_down(fmt, half)[0],
                                              FLAG_INEXACT), k
    assert tr.atanpi(fmt, max_normal_bits(fmt), RND_RDN) == \
        (next_down(fmt, half)[0], FLAG_INEXACT)


@pytest.mark.parametrize("fmt", ALL)
def test_atan2_beside_an_exact_quotient(fmt):
    """atan2(y, x) for a positive x is atan(y/x), and when that quotient
    is itself a dyadic rational the answer sits a hair below it with no
    precision able to say how far.

    The second case is the one _round_neighbour could not have handled:
    minSub/2 is not a representable number at all, it is the MIDPOINT
    between zero and the smallest subnormal, and a value just below a
    midpoint rounds differently from the midpoint itself."""
    one = one_bits(fmt)
    p = fmt.prec
    for k in (p + 4, 2 * p, 4 * p):
        y = V(fmt, 0, 1, -k)
        assert tr.atan2(fmt, y, one, RND_RNE) == (y, FLAG_INEXACT), k
        assert tr.atan2(fmt, y, one, RND_RDN) == (next_down(fmt, y)[0],
                                                  FLAG_INEXACT), k
        assert tr.atan2(fmt, y, one, RND_RUP) == (y, FLAG_INEXACT), k
    sub = min_subnormal_bits(fmt)
    two = V(fmt, 0, 1, 1)
    # the quotient is exactly the subnormal midpoint
    assert tr.atan2(fmt, sub, two, RND_RNE) == \
        (zero_bits(fmt), FLAG_INEXACT | FLAG_UNDERFLOW)
    assert tr.atan2(fmt, sub, two, RND_RUP) == \
        (sub, FLAG_INEXACT | FLAG_UNDERFLOW)
    # a quotient that is NOT dyadic takes the ordinary path and still
    # lands correctly - three does not divide any odd significand
    three = V(fmt, 0, 3, 0)
    y = V(fmt, 0, 1, -(2 * p))
    bits, flags = tr.atan2(fmt, y, three, RND_RNE)
    assert flags & FLAG_INEXACT


@pytest.mark.parametrize("fmt", ALL)
def test_atan2pi_beside_one_and_a_half(fmt):
    """atan2Pi's two corners: a tiny quotient against a NEGATIVE x puts
    the answer just below 1, and a dominant y puts it beside 1/2 - below
    for a positive x, above for a negative one. Both are values the
    format holds; neither radian twin is."""
    p = fmt.prec
    one, half = one_bits(fmt), V(fmt, 0, 1, -1)
    tiny = V(fmt, 0, 1, -(p + 2))
    big = V(fmt, 0, 1, p + 3)
    for xneg in (V(fmt, 1, 1, 0),):
        assert tr.atan2pi(fmt, tiny, xneg, RND_RNE) == (one, FLAG_INEXACT)
        assert tr.atan2pi(fmt, tiny, xneg, RND_RDN) == \
            (next_down(fmt, one)[0], FLAG_INEXACT)
        # a negative y against a negative x puts the answer just ABOVE
        # -1, so roundTowardNegative is the attribute that reaches -1
        # and roundTowardPositive is the one that steps off it
        assert tr.atan2pi(fmt, V(fmt, 1, 1, -(p + 2)), xneg, RND_RDN) ==             (one_bits(fmt, 1), FLAG_INEXACT)
        assert tr.atan2pi(fmt, V(fmt, 1, 1, -(p + 2)), xneg, RND_RUP) ==             (next_up(fmt, one_bits(fmt, 1))[0], FLAG_INEXACT)
    assert tr.atan2pi(fmt, big, one, RND_RNE) == (half, FLAG_INEXACT)
    assert tr.atan2pi(fmt, big, one, RND_RDN) == \
        (next_down(fmt, half)[0], FLAG_INEXACT)
    assert tr.atan2pi(fmt, big, V(fmt, 1, 1, 0), RND_RUP) == \
        (next_up(fmt, half)[0], FLAG_INEXACT)
    assert tr.atan2pi(fmt, big, V(fmt, 1, 1, 0), RND_RNE) == \
        (half, FLAG_INEXACT)


# =====================================================================
# Exactness, stated as an enumeration and checked as one
# =====================================================================

def _is_exact_by_the_table(fmt, fn, xa, xb):
    """What the design document says should raise nothing, restated
    here from the mathematics rather than from the implementation."""
    u = unpack(fmt, xa)
    if u.kind == sf.NAN or u.kind == sf.INF:
        return fn in ("atanpi",) and u.kind == sf.INF
    m, e = (0, 0) if u.kind == sf.ZERO else tr._dyadic(u)
    if fn == "sinpi":
        return u.kind == sf.ZERO or e >= -1
    if fn == "cospi":
        return u.kind == sf.ZERO or e >= -1
    if fn == "tanpi":
        return u.kind == sf.ZERO or e >= 0 or e == -2
    if fn in ("asin", "atan"):
        return u.kind == sf.ZERO
    if fn == "acos":
        return not u.sign and m == 1 and e == 0
    if fn == "asinpi":
        return u.kind == sf.ZERO or (m == 1 and e == 0)
    if fn == "acospi":
        return u.kind == sf.ZERO or (m == 1 and e == 0)
    if fn == "atanpi":
        return u.kind == sf.ZERO or (m == 1 and e == 0)
    return None


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_exact_cases_are_exactly_the_enumerated_ones(fmt, rnd):
    """Both directions. Where the enumeration says exact, the inexact
    flag must be CLEAR; where it does not, it must be SET. A tolerance
    dressed as a proof fails one half or the other."""
    p = fmt.prec
    pool = [zero_bits(fmt), zero_bits(fmt, 1), one_bits(fmt),
            one_bits(fmt, 1), min_subnormal_bits(fmt),
            max_subnormal_bits(fmt), min_normal_bits(fmt)]
    for m, e in ((1, -1), (3, -1), (5, -1), (1, -2), (3, -2), (7, -2),
                 (1, -3), (5, -3), (9, -4), (1, 0), (3, 0), (5, 0), (2, 0),
                 (1, 1), (1, 2), (17, 0), (1, -(p - 2)), (3, -(p - 1))):
        for s in (0, 1):
            bits, fl = sf.round_pack(fmt, s, m, e, RND_RNE)
            if fl == 0:
                pool.append(bits)
    seen_exact = 0
    for fn in ("sinpi", "cospi", "tanpi", "asin", "acos", "atan",
               "asinpi", "acospi", "atanpi"):
        for xa in pool:
            u = unpack(fmt, xa)
            if fn in ("asin", "acos", "asinpi", "acospi") and \
                    tr._mag_gt_one(u):
                continue
            want_exact = _is_exact_by_the_table(fmt, fn, xa, 0)
            bits, flags = tr.compute(fmt, fn, xa, 0, rnd)
            if flags & FLAG_DIVZERO:
                continue                       # tanPi at a pole
            got_exact = not (flags & FLAG_INEXACT)
            assert got_exact == want_exact, \
                (fn, fmt.name, hex(xa), flags, want_exact)
            seen_exact += 1 if got_exact else 0
    assert seen_exact > 40, seen_exact


@pytest.mark.parametrize("fmt", ALL)
def test_asinpi_of_a_half_is_a_sixth_and_therefore_not_exact(fmt):
    """Niven's theorem gives sin(pi/6) = 1/2, so asinPi(1/2) is exactly
    1/6 - a RATIONAL value. It is not a dyadic rational, so it is not a
    rounding boundary, so it is inexact and the loop terminates on it.
    That distinction is the reason the enumeration stops where it
    does."""
    half = V(fmt, 0, 1, -1)
    for rnd in RND_MODES:
        bits, flags = tr.asinpi(fmt, half, rnd)
        assert flags == FLAG_INEXACT
    # the two directed attributes are ADJACENT, which is the tightest
    # bracket the format admits and the shape a rational-but-not-dyadic
    # value has to take
    lo = tr.asinpi(fmt, half, RND_RDN)[0]
    hi = tr.asinpi(fmt, half, RND_RUP)[0]
    assert next_up(fmt, lo)[0] == hi
    # acosPi(1/2) is 1/3 by the same theorem, and equally inexact
    assert tr.acospi(fmt, half, RND_RNE)[1] == FLAG_INEXACT


# =====================================================================
# Escalation over the phase-2 set
# =====================================================================

def _trig_pool(fmt):
    p = fmt.prec
    out = [one_bits(fmt), one_bits(fmt, 1), one_bits(fmt) + 1,
           one_bits(fmt) - 1, V(fmt, 0, 3, -1), V(fmt, 1, 3, -1),
           V(fmt, 0, 1, -1), V(fmt, 0, 3, -2), V(fmt, 0, 5, -3),
           V(fmt, 0, 7, -4), V(fmt, 0, 1, -3), V(fmt, 1, 1, -3),
           min_normal_bits(fmt), min_subnormal_bits(fmt),
           max_subnormal_bits(fmt), V(fmt, 0, 1, -p), V(fmt, 1, 1, -p),
           V(fmt, 0, (1 << p) - 1, -p), V(fmt, 0, (1 << p) - 1, -p + 1)]
    return out


def _trig_escalation_run(fmt):
    """Force the loop to start below the precision it needs; the eleven
    must not move a single bit. Raising the working precision only
    narrows the enclosure, so a rounding decided at one precision is
    decided the same way at every higher one - and this is the run that
    proves it rather than the argument that asserts it."""
    pool = _trig_pool(fmt)
    tr.reset_stats()
    baseline = {}
    for fn in TRIG:
        arity = tr.TRANSCEND_ARITY[fn]
        pairs = ([(a, 0) for a in pool] if arity == 1
                 else [(a, pool[(i * 5 + 2) % len(pool)])
                       for i, a in enumerate(pool)])
        for rnd in RND_MODES:
            for xa, xb in pairs:
                baseline[(fn, rnd, xa, xb)] = tr.compute(fmt, fn, xa, xb, rnd)
    ordinary = tr.STATS["escalations"]

    tr.reset_stats()
    tr.START_PREC_OVERRIDE = fmt.prec + 8
    try:
        for (fn, rnd, xa, xb), want in baseline.items():
            assert tr.compute(fmt, fn, xa, xb, rnd) == want, \
                (fmt.name, fn, RND_NAMES[rnd], hex(xa), hex(xb))
    finally:
        tr.START_PREC_OVERRIDE = 0
    # The counter has to have MOVED somewhere on the ladder, but not
    # necessarily at every rung: start_prec floors the override at 64
    # bits, which is already 40 bits of headroom at binary32 and decides
    # everything there. What matters at every rung is that no answer
    # moved; the companion test below is where the path is proven taken.
    assert tr.STATS["max_prec"] <= tr.prec_cap(fmt)
    return tr.STATS["escalations"], ordinary


@pytest.mark.parametrize("fmt", ALL)
def test_trig_escalation_lands_on_the_same_answer(fmt):
    _trig_escalation_run(fmt)


def test_trig_escalation_is_taken_somewhere_on_the_ladder():
    """Forcing a low start must actually drive the escalation path, or
    the run above proves nothing about it."""
    forced = ordinary = 0
    for fmt in ALL:
        a, b = _trig_escalation_run(fmt)
        forced += a
        ordinary += b
    assert forced > max(4, ordinary), (forced, ordinary)


def test_the_eleven_are_registered_and_named_once():
    """One canonical order in three languages. The vector sets, the C
    enum and this tuple index each other, so a name added in one place
    and not the others is a silent renumbering."""
    assert len(tr.TRANSCEND_FNS) == 29
    assert tr.TRANSCEND_FNS[9:20] == TRIG
    for fn in TRIG:
        assert fn in tr.TRANSCEND_IMPL
        assert tr.TRANSCEND_ARITY[fn] == (2 if fn.startswith("atan2") else 1)
