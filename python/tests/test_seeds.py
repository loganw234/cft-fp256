# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The divide/sqrt seed opcodes, held to the bound the sequences need.

The composed divide and square root start from these seeds and square
their error once per Newton step. The iteration counts in the library
sequences are DERIVED from a guaranteed starting accuracy, so that
bound is the load-bearing property here and it is proven exhaustively,
not sampled: over every table entry, against the worst point of the
entry's input interval, in exact rational arithmetic.

1/m is monotone on each interval, so its worst case is at an endpoint.
1/sqrt(m) likewise. That is what makes the exhaustive check closed:
512 (reciprocal) + 1024 (rsqrt) intervals, two endpoints each.

The bound asserted is 2^-8.5. The table's own quantisation is ~2^-18
and the interval half-width contributes ~2^-10, so there is real
margin - and margin is the point: a sequence proven against 2^-8.5
stays correct if a future table tweak eats some slack.
"""

import struct
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    zero_bits, inf_bits, qnan_bits, snan_bits, one_bits,
    min_subnormal_bits, max_normal_bits, is_nan, vectors,
)
from cft_golden.softfloat import (  # noqa: E402
    SEED_INDEX_BITS, SEED_TABLE_SIZE,
    _seed_recip_entry, _seed_rsqrt_entry,
    recip_seed, rsqrt_seed,
)

ALL_FORMATS = (FP32, FP64, FP128, FP256)
BOUND = Fraction(1, 2) ** Fraction(17, 2)   # 2^-8.5


def sq_le(a: Fraction, b2: Fraction) -> bool:
    """a <= sqrt(b2) without computing a root: a^2 <= b2 for a >= 0."""
    return a * a <= b2


def test_recip_table_bound_exhaustive():
    """Every entry against both endpoints of its interval, exactly."""
    worst = Fraction(0)
    for i in range(SEED_TABLE_SIZE):
        r = _seed_recip_entry(i)
        y = Fraction(r, 1 << 18)
        for m in (Fraction((1 << 9) + i, 1 << 9),
                  Fraction((1 << 9) + i + 1, 1 << 9)):
            err = abs(y - 1 / m) * m       # relative to 1/m: |y*m - 1|
            worst = max(worst, err)
            assert err < BOUND, (i, float(err))
    # Record how much margin actually exists, so a regression is loud.
    assert worst < BOUND, float(worst)
    assert worst > BOUND / 8, "bound is implausibly slack - check the test"


def test_rsqrt_table_bound_exhaustive():
    """As above; sqrt comparisons by squaring, no roots computed."""
    for j in range(2 * SEED_TABLE_SIZE):
        odd = j >> SEED_INDEX_BITS
        i = j & (SEED_TABLE_SIZE - 1)
        r = _seed_rsqrt_entry(j)
        y = Fraction(r, 1 << 17)
        for m in (Fraction(((1 << 9) + i) << odd, 1 << 9),
                  Fraction(((1 << 9) + i + 1) << odd, 1 << 9)):
            # relative error of y against 1/sqrt(m):
            # |y*sqrt(m) - 1| < B  <=>  (1-B)^2 < y^2 m < (1+B)^2
            v = y * y * m
            assert (1 - BOUND) ** 2 < v < (1 + BOUND) ** 2, (j, float(v))


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_recip_seed_value_level(fmt):
    """The packed seed keeps the table's accuracy at the value level,
    normal and subnormal operands alike (away from the range edges,
    where saturation is specified behaviour)."""
    import random
    rng = random.Random(0x5EED)
    checked = 0
    for _ in range(600):
        xa = rng.getrandbits(fmt.width)
        from cft_golden.softfloat import unpack, NAN, INF, ZERO
        ua = unpack(fmt, xa)
        if ua.kind in (NAN, INF, ZERO):
            continue
        if ((xa >> fmt.man_w) & fmt.exp_mask) == 0:
            # subnormal: flush-at-input is spec - zero-class result
            sgn = xa >> (fmt.width - 1)
            b, fl = recip_seed(fmt, xa)
            assert fl == 0 and b == inf_bits(fmt, sgn)
            continue
        v = Fraction(ua.m) * Fraction(2) ** ua.e
        if ua.sign:
            v = -v
        target = 1 / v
        # skip the saturation edges: |1/v| must sit well inside range
        if not (Fraction(2) ** (fmt.emin + 2) < abs(target) <
                Fraction(2) ** (fmt.emax - 1)):
            continue
        bits, fl = recip_seed(fmt, xa if ua.sign == 0 else xa)
        assert fl == 0
        sign = bits >> (fmt.width - 1)
        biased = (bits >> fmt.man_w) & fmt.exp_mask
        frac = bits & fmt.man_mask
        assert biased not in (0, fmt.exp_mask) or biased == 0
        if biased == 0:
            got = Fraction(frac, 1 << fmt.man_w) * Fraction(2) ** fmt.emin
        else:
            got = (1 + Fraction(frac, 1 << fmt.man_w)) * \
                Fraction(2) ** (biased - fmt.bias)
        if sign:
            got = -got
        err = abs(got - target) / abs(target)
        assert err < BOUND, (hex(xa), float(err))
        checked += 1
    assert checked > 100


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_rsqrt_seed_value_level(fmt):
    import random
    rng = random.Random(0x5EED + 1)
    checked = 0
    from cft_golden.softfloat import unpack
    for _ in range(600):
        xa = rng.getrandbits(fmt.width) & ~fmt.sign_mask
        from cft_golden.softfloat import NAN, INF, ZERO
        ua = unpack(fmt, xa)
        if ua.kind in (NAN, INF, ZERO):
            continue
        if ((xa >> fmt.man_w) & fmt.exp_mask) == 0:
            b, fl = rsqrt_seed(fmt, xa)
            assert fl == 0 and b == inf_bits(fmt, 0)
            continue
        v = Fraction(ua.m) * Fraction(2) ** ua.e
        bits, fl = rsqrt_seed(fmt, xa)
        assert fl == 0
        biased = (bits >> fmt.man_w) & fmt.exp_mask
        frac = bits & fmt.man_mask
        if biased == 0:
            got = Fraction(frac, 1 << fmt.man_w) * Fraction(2) ** fmt.emin
        else:
            got = (1 + Fraction(frac, 1 << fmt.man_w)) * \
                Fraction(2) ** (biased - fmt.bias)
        # |got*sqrt(v) - 1| < B  <=>  (1-B)^2 < got^2 v < (1+B)^2
        w = got * got * v
        assert (1 - BOUND) ** 2 < w < (1 + BOUND) ** 2, (hex(xa), float(w))
        checked += 1
    assert checked > 100


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_seed_specials_are_quiet(fmt):
    """Specials map to the limits, and NOTHING here ever raises a flag -
    seeds are scaffolding, and their flags would leak into a composed
    sequence's sticky accumulation."""
    cases_r = [
        (qnan_bits(fmt), lambda b: is_nan(fmt, b)),
        (snan_bits(fmt), lambda b: is_nan(fmt, b)),
        (inf_bits(fmt, 0), lambda b: b == zero_bits(fmt, 0)),
        (inf_bits(fmt, 1), lambda b: b == zero_bits(fmt, 1)),
        (zero_bits(fmt, 0), lambda b: b == inf_bits(fmt, 0)),
        (zero_bits(fmt, 1), lambda b: b == inf_bits(fmt, 1)),
        (min_subnormal_bits(fmt, 0), lambda b: b == inf_bits(fmt, 0)),
        (min_subnormal_bits(fmt, 1), lambda b: b == inf_bits(fmt, 1)),
    ]
    for xa, ok in cases_r:
        b, fl = recip_seed(fmt, xa)
        assert fl == 0 and ok(b), hex(xa)
    cases_s = [
        (qnan_bits(fmt), lambda b: is_nan(fmt, b)),
        (snan_bits(fmt), lambda b: is_nan(fmt, b)),
        (inf_bits(fmt, 0), lambda b: b == zero_bits(fmt, 0)),
        (zero_bits(fmt, 0), lambda b: b == inf_bits(fmt, 0)),
        (zero_bits(fmt, 1), lambda b: b == inf_bits(fmt, 1)),
        (min_subnormal_bits(fmt, 0), lambda b: b == inf_bits(fmt, 0)),
        (min_subnormal_bits(fmt, 1), lambda b: b == inf_bits(fmt, 1)),
        (one_bits(fmt, 1), lambda b: is_nan(fmt, b)),
        (inf_bits(fmt, 1), lambda b: is_nan(fmt, b)),
    ]
    for xa, ok in cases_s:
        b, fl = rsqrt_seed(fmt, xa)
        assert fl == 0 and ok(b), hex(xa)


def test_seed_is_format_consistent():
    """The same leading significand bits produce the same table entry
    in every format - the hardware shares one ROM across the rungs, and
    this is the property that lets it."""
    from cft_golden.softfloat import unpack
    for i in (0, 1, 255, 256, 511):
        vals = []
        for fmt in ALL_FORMATS:
            # build 1.f with fraction = i << (man_w - 9)
            bits = one_bits(fmt) | (i << (fmt.man_w - SEED_INDEX_BITS))
            b, _ = recip_seed(fmt, bits)
            # decode mantissa steps relative to the format
            biased = (b >> fmt.man_w) & fmt.exp_mask
            frac = b & fmt.man_mask
            # normalise to a (exponent, leading-19-bits) pair
            vals.append((biased - fmt.bias,
                         frac >> max(0, fmt.man_w - 19)))
        assert all(v == vals[0] for v in vals), (i, vals)
