# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the directed rounding attributes.

The strongest arbiter available for the four non-default attributes is
the definition itself. Every case here decodes the model's answer back
into an exact rational and re-derives what IEEE 754-2019 4.3 requires
using exact rational floor division - no guard/sticky bits, no shifts,
no shared code path with softfloat.py. Overflow (7.4) and the signed
zero of an exact cancellation (6.3) are mode-dependent, and those are
precisely the rules a directed-rounding implementation gets wrong, so
they are checked as named anchors too.
"""

import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    FLAG_OVERFLOW, FLAG_UNDERFLOW, FLAG_INEXACT,
    OP_ADD, OP_SUB, OP_MUL,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_NAMES, RND_MODES,
    add, sub, mul, fma, compute, steer,
    zero_bits, one_bits, inf_bits,
    min_subnormal_bits, max_normal_bits, negate, vectors,
)

ALL_FORMATS = (FP32, FP64, FP128, FP256)


# ---- exact-rational reference ----------------------------------------

def _floor_log2(a: Fraction) -> int:
    """Largest e with 2^e <= a, for a > 0."""
    e = a.numerator.bit_length() - a.denominator.bit_length()
    while Fraction(2) ** e > a:
        e -= 1
    while Fraction(2) ** (e + 1) <= a:
        e += 1
    return e


def _value(fmt, bits) -> Fraction:
    """Exact rational value of a finite bit pattern."""
    sign = bits >> (fmt.width - 1)
    ef = (bits >> fmt.man_w) & fmt.exp_mask
    frac = bits & fmt.man_mask
    if ef == 0:
        m, e = frac, fmt.emin - fmt.man_w
    else:
        m, e = frac | (1 << fmt.man_w), ef - fmt.bias - fmt.man_w
    v = Fraction(m) * Fraction(2) ** e
    return -v if sign else v


def _kind(fmt, bits):
    ef = (bits >> fmt.man_w) & fmt.exp_mask
    if ef == fmt.exp_mask:
        return "nan" if (bits & fmt.man_mask) else "inf"
    return "finite"


def _ref_round_magnitude(fmt, v: Fraction, rnd, unbounded=False):
    """Round |v| (v != 0) onto the format's grid under `rnd`, from first
    principles. Returns (magnitude, inexact)."""
    s = 1 if v < 0 else 0
    a = abs(v)
    e = _floor_log2(a)
    q = e - (fmt.prec - 1) if unbounded else max(e, fmt.emin) - (fmt.prec - 1)
    scale = Fraction(2) ** q
    k = a / scale
    lo = k.numerator // k.denominator
    if k == lo:
        return lo * scale, False
    frac_part = k - lo
    half = Fraction(1, 2)
    if rnd == RND_RTZ:
        pick = lo
    elif rnd == RND_RDN:
        pick = lo if s == 0 else lo + 1
    elif rnd == RND_RUP:
        pick = lo + 1 if s == 0 else lo
    elif frac_part > half:
        pick = lo + 1
    elif frac_part < half:
        pick = lo
    elif rnd == RND_RMM:
        pick = lo + 1
    else:  # RND_RNE, an exact tie
        pick = lo if lo % 2 == 0 else lo + 1
    return pick * scale, True


def _encode(fmt, mag: Fraction, sign: int) -> int:
    """Bit pattern of an exactly representable finite magnitude."""
    if mag == 0:
        return zero_bits(fmt, sign)
    e = _floor_log2(mag)
    if e < fmt.emin:
        frac = mag / (Fraction(2) ** (fmt.emin - fmt.man_w))
        assert frac.denominator == 1
        return zero_bits(fmt, sign) | int(frac)
    m = mag / (Fraction(2) ** (e - fmt.man_w))
    assert m.denominator == 1
    return zero_bits(fmt, sign) | ((e + fmt.bias) << fmt.man_w) \
        | (int(m) - (1 << fmt.man_w))


def _reference_fma(fmt, xa, xb, xc, rnd):
    """(bits, flags) required by IEEE 754-2019, for finite operands."""
    va, vb, vc = (_value(fmt, x) for x in (xa, xb, xc))
    v = va * vb + vc

    if v == 0:
        # 6.3: a zero product plus a zero addend keeps a shared sign;
        # any other exact cancellation is +0 except under RDN.
        if va * vb == 0 and vc == 0:
            sp = (xa >> (fmt.width - 1)) ^ (xb >> (fmt.width - 1))
            sc = xc >> (fmt.width - 1)
            sign = sp if sp == sc else (1 if rnd == RND_RDN else 0)
        else:
            sign = 1 if rnd == RND_RDN else 0
        return zero_bits(fmt, sign), 0

    sign = 1 if v < 0 else 0
    mag, inexact = _ref_round_magnitude(fmt, v, rnd)
    flags = FLAG_INEXACT if inexact else 0

    if mag > _value(fmt, max_normal_bits(fmt)):
        flags |= FLAG_OVERFLOW | FLAG_INEXACT
        # 7.4: only these mode/sign combinations deliver an infinity
        to_inf = rnd in (RND_RNE, RND_RMM) \
            or (rnd == RND_RDN and sign) or (rnd == RND_RUP and not sign)
        return (inf_bits(fmt, sign) if to_inf
                else max_normal_bits(fmt, sign)), flags
    if mag == 0:
        return zero_bits(fmt, sign), flags | FLAG_UNDERFLOW

    mag_unb, _ = _ref_round_magnitude(fmt, v, rnd, unbounded=True)
    if inexact and mag_unb < Fraction(2) ** fmt.emin:
        flags |= FLAG_UNDERFLOW   # tininess after rounding, and inexact
    return _encode(fmt, mag, sign), flags


def _finite_cases(fmt, n_directed, n_random, seed):
    """Steered operand triples with no infinity or NaN - the specials
    are rounding-mode independent and already covered elsewhere.

    Counts are scaled down for the wide formats: the reference here is
    exact rational arithmetic, so an fp256 case costs orders of
    magnitude more than an fp32 one, while the logic under test is the
    same width-parameterized code. fp32/fp64 carry the case volume;
    fp128/fp256 carry the width-specific risk.
    """
    scale = {32: 1.0, 64: 1.0, 128: 0.35, 256: 0.2}[fmt.width]
    n_directed, n_random = int(n_directed * scale), int(n_random * scale)
    cases = vectors.directed_cases(fmt, n_directed, seed=seed) + \
        vectors.random_cases(fmt, n_random, seed=seed + 1)
    out = []
    for op, xa, xb, xc in cases:
        fa, fb, fc = steer(fmt, op, xa, xb, xc)
        if all(_kind(fmt, x) == "finite" for x in (fa, fb, fc)):
            out.append((fa, fb, fc))
    return out


# ---- the tests -------------------------------------------------------

@pytest.mark.parametrize("rnd", RND_MODES, ids=lambda r: RND_NAMES[r])
def test_rounding_modes_match_the_definition(rnd):
    for fmt in ALL_FORMATS:
        checked = 0
        for fa, fb, fc in _finite_cases(fmt, 1200, 900, seed=51):
            got = fma(fmt, fa, fb, fc, rnd)
            want = _reference_fma(fmt, fa, fb, fc, rnd)
            assert got == want, (
                f"{fmt.name} {RND_NAMES[rnd]} a={fa:#x} b={fb:#x} c={fc:#x}: "
                f"got ({got[0]:#x}, {got[1]:#07b}) "
                f"want ({want[0]:#x}, {want[1]:#07b})")
            checked += 1
        assert checked > 150, f"{fmt.name}: only {checked} finite cases"


def test_directed_modes_bracket_the_exact_value():
    """The property interval arithmetic actually rests on: the two
    directed results straddle the exact value, and when the result is
    inexact they are adjacent, so the interval is as tight as the
    format allows."""
    for fmt in (FP32, FP64, FP256):
        for fa, fb, fc in _finite_cases(fmt, 600, 600, seed=61):
            lo, lo_flags = fma(fmt, fa, fb, fc, RND_RDN)
            hi, _ = fma(fmt, fa, fb, fc, RND_RUP)
            if "inf" in (_kind(fmt, lo), _kind(fmt, hi)):
                continue
            v = _value(fmt, fa) * _value(fmt, fb) + _value(fmt, fc)
            vlo, vhi = _value(fmt, lo), _value(fmt, hi)
            assert vlo <= v <= vhi, \
                f"{fmt.name} a={fa:#x} b={fb:#x} c={fc:#x}: {vlo} <= {v} <= {vhi}"
            if lo_flags & FLAG_INEXACT:
                assert vlo < vhi
                # adjacent: stepping one ulp up from the lower bound
                # lands exactly on the upper one
                step = -1 if (lo >> (fmt.width - 1)) else 1
                assert _value(fmt, lo + step) == vhi, \
                    f"{fmt.name} bounds not adjacent for a={fa:#x}"
            else:
                assert vlo == vhi


def test_overflow_response_table():
    """754 7.4: overflow is signalled in every attribute, but only some
    of them deliver an infinity."""
    f = FP32
    big, one = max_normal_bits(f), one_bits(f)
    nbig = negate(f, big)
    over = FLAG_OVERFLOW | FLAG_INEXACT
    for rnd, want_pos, want_neg in (
            (RND_RNE, inf_bits(f), inf_bits(f, 1)),
            (RND_RMM, inf_bits(f), inf_bits(f, 1)),
            (RND_RTZ, big, nbig),
            (RND_RDN, big, inf_bits(f, 1)),
            (RND_RUP, inf_bits(f), nbig)):
        assert fma(f, big, one, big, rnd) == (want_pos, over), RND_NAMES[rnd]
        assert fma(f, nbig, one, nbig, rnd) == (want_neg, over), RND_NAMES[rnd]


def test_exact_cancellation_sign():
    """754 6.3: +0 in every attribute except roundTowardNegative."""
    for fmt in (FP32, FP256):
        one = one_bits(fmt)
        for rnd in RND_MODES:
            want = zero_bits(fmt, 1 if rnd == RND_RDN else 0)
            assert fma(fmt, one, one, negate(fmt, one), rnd) == (want, 0)
            assert add(fmt, one, negate(fmt, one), rnd) == (want, 0)
            assert sub(fmt, one, one, rnd) == (want, 0)
            # like-signed zeros keep their own sign in every attribute
            assert add(fmt, zero_bits(fmt, 1), zero_bits(fmt, 1), rnd) == \
                (zero_bits(fmt, 1), 0)


def test_tiny_value_edge():
    """Half of the smallest subnormal: below every tie, so the five
    attributes split cleanly on which way they lean."""
    f = FP32
    tiny = min_subnormal_bits(f)             # 2^-149
    half = (f.bias - 1) << f.man_w           # 0.5 exactly
    zero = zero_bits(f)
    # tiny * 0.5 = 2^-150, exactly half an ulp of the subnormal grid
    assert fma(f, tiny, half, zero, RND_RNE) == \
        (zero, FLAG_UNDERFLOW | FLAG_INEXACT)          # ties to even -> +0
    assert fma(f, tiny, half, zero, RND_RMM)[0] == tiny  # ties away -> up
    assert fma(f, tiny, half, zero, RND_RUP)[0] == tiny
    assert fma(f, tiny, half, zero, RND_RTZ)[0] == zero
    assert fma(f, tiny, half, zero, RND_RDN)[0] == zero
    # the same magnitude negated: RDN is now the one that rounds away
    ntiny = negate(f, tiny)
    assert fma(f, ntiny, half, zero, RND_RDN)[0] == ntiny
    assert fma(f, ntiny, half, zero, RND_RUP)[0] == zero_bits(f, 1)
    assert fma(f, ntiny, half, zero, RND_RTZ)[0] == zero_bits(f, 1)


def test_steering_composition_under_every_mode():
    """The ADD/SUB/MUL steering must stay exactly equivalent to the
    direct definitions in every attribute - the signed-zero paths are
    where a directed mode would break it."""
    for fmt in (FP32, FP256):
        cases = vectors.directed_cases(fmt, 1500, seed=71) + \
            vectors.random_cases(fmt, 500, seed=72)
        for rnd in RND_MODES:
            for _, xa, xb, xc in cases:
                assert compute(fmt, OP_ADD, xa, 0, xc, rnd) == \
                    add(fmt, xa, xc, rnd)
                assert compute(fmt, OP_SUB, xa, 0, xc, rnd) == \
                    sub(fmt, xa, xc, rnd)
                assert compute(fmt, OP_MUL, xa, xb, 0, rnd) == \
                    mul(fmt, xa, xb, rnd)


def test_default_mode_is_unchanged():
    """Everything already proven about RNE must still hold when the
    argument is simply omitted."""
    for fmt in ALL_FORMATS:
        for fa, fb, fc in _finite_cases(fmt, 400, 400, seed=81):
            assert fma(fmt, fa, fb, fc) == fma(fmt, fa, fb, fc, RND_RNE)


def test_undefined_encodings_are_rejected():
    one = one_bits(FP32)
    for bad in (5, 6, 7, -1):
        with pytest.raises(ValueError):
            fma(FP32, one, one, one, bad)
