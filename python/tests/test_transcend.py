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
        y = val(xb)
        if fn == "pow":
            return iv.power(x, y)
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
                 "log10": gmpy2.log10}
        if fn in table:
            v = table[fn](a)
        elif fn == "pow":
            v = a ** conv(xb)
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
    for fn in tr.TRANSCEND_FNS:
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
        tr.compute(FP32, "atan", one_bits(FP32))
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
    assert tr.STATS["escalations"] > 100 > ordinary, tr.STATS
    assert tr.STATS["max_prec"] <= tr.prec_cap(fmt)
