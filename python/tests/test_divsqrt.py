# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Division and square root against the definition, not the code.

Same discipline as test_rounding.py: the model's answer is decoded
back to an exact rational and IEEE 754-2019 5.4.1 is re-derived with
exact arithmetic - Fractions for division, integer squaring for the
root - sharing no code path with softfloat.py. No guard bits, no
shifts, no isqrt: the sqrt oracle never computes a root at all, it
only verifies ordering, which is the direction that cannot inherit a
bug from the thing under test.

Flags get the same treatment where the standard pins them: divideByZero
exactly for finite-nonzero / zero (7.3), invalid for 0/0, inf/inf and
negative sqrt operands (7.2), inexact iff the delivered result differs
from the infinitely precise one, underflow per tininess-after-rounding.
"""

import math
import struct
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    FLAG_INVALID, FLAG_DIVZERO, FLAG_INEXACT, FLAG_UNDERFLOW,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_MODES,
    div, sqrt, unpack, vectors,
    zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits, is_nan,
)

ALL_FORMATS = (FP32, FP64, FP128, FP256)


# ---- the independent decoders ---------------------------------------

def decode(fmt, bits):
    """(kind, sign, Fraction value) from raw bits, derived from the
    754 encoding directly."""
    sign = (bits >> (fmt.width - 1)) & 1
    biased = (bits >> fmt.man_w) & fmt.exp_mask
    frac = bits & fmt.man_mask
    if biased == fmt.exp_mask:
        return ("nan" if frac else "inf"), sign, None
    if biased == 0:
        if frac == 0:
            return "zero", sign, Fraction(0)
        v = Fraction(frac, 1 << fmt.man_w) * Fraction(2) ** fmt.emin
    else:
        v = (1 + Fraction(frac, 1 << fmt.man_w)) * \
            Fraction(2) ** (biased - fmt.bias)
    return "finite", sign, (-v if sign else v)


def _floor_log2(v: Fraction) -> int:
    """floor(log2(v)) for v > 0, from bit lengths - fp256 exponents
    reach the hundreds of thousands, so stepping a binade at a time is
    not an option."""
    n, d = v.numerator, v.denominator
    e = n.bit_length() - d.bit_length()
    # n/d in [2^(e-1), 2^(e+1)); settle which side of 2^e
    if e >= 0:
        ok = n >= (d << e)
    else:
        ok = (n << (-e)) >= d
    return e if ok else e - 1


def representables_around(fmt, target: Fraction):
    """The two adjacent representable magnitudes bracketing |target|,
    as Fractions, plus the grid step - built from the encoding's
    definition, not by rounding."""
    assert target > 0
    e = max(_floor_log2(target), fmt.emin)
    q = e - fmt.man_w
    ulp = Fraction(2) ** q
    lo_steps = target / ulp
    lo_int = lo_steps.numerator // lo_steps.denominator
    lo = lo_int * ulp
    hi = lo + ulp
    return lo, hi, ulp


def correctly_rounded(fmt, target: Fraction, sign: int, rnd: int):
    """The 754 4.3 result for the exact nonzero rational target, as
    (kind, sign, Fraction|None), derived from inequalities only."""
    mag = abs(target)
    maxn_bits = max_normal_bits(fmt)
    _, _, maxn = decode(fmt, maxn_bits)
    two = Fraction(2)

    lo, hi, ulp = representables_around(fmt, mag)
    if lo == mag:
        cand = lo
    else:
        if rnd == RND_RTZ:
            cand = lo
        elif rnd == RND_RUP:
            cand = lo if sign else hi
        elif rnd == RND_RDN:
            cand = hi if sign else lo
        elif rnd == RND_RMM:
            cand = hi if (mag - lo) * 2 >= ulp else lo
        else:  # RNE
            d_lo, d_hi = mag - lo, hi - mag
            if d_lo < d_hi:
                cand = lo
            elif d_hi < d_lo:
                cand = hi
            else:
                # ties-to-even: the candidate whose step count is even
                steps = (lo / ulp)
                cand = lo if (steps.numerator // steps.denominator) % 2 == 0 \
                    else hi
    # overflow per 7.4: decided on the unbounded-rounded value
    if cand > maxn:
        if rnd == RND_RTZ or (rnd == RND_RUP and sign) or \
           (rnd == RND_RDN and not sign):
            return "finite", sign, maxn
        return "inf", sign, None
    if cand == 0:
        return "zero", sign, Fraction(0)
    return "finite", sign, cand


def check_div(fmt, xa, xb, rnd):
    got_bits, got_flags = div(fmt, xa, xb, rnd)
    ka, sa, va = decode(fmt, xa)
    kb, sb, vb = decode(fmt, xb)
    sq = sa ^ sb

    if ka == "nan" or kb == "nan":
        assert is_nan(fmt, got_bits)
        return
    if ka == "inf" and kb == "inf" or (ka == "zero" and kb == "zero"):
        assert is_nan(fmt, got_bits) and got_flags == FLAG_INVALID
        return
    if ka == "inf":
        assert got_bits == inf_bits(fmt, sq) and got_flags == 0
        return
    if kb == "inf":
        assert got_bits == zero_bits(fmt, sq) and got_flags == 0
        return
    if kb == "zero":
        assert got_bits == inf_bits(fmt, sq) and got_flags == FLAG_DIVZERO
        return
    if ka == "zero":
        assert got_bits == zero_bits(fmt, sq) and got_flags == 0
        return

    target = va / vb
    kind, _, val = correctly_rounded(fmt, target, sq, rnd)
    gk, gs, gv = decode(fmt, got_bits)
    assert gs == sq, f"sign: got {gs} want {sq}"
    if kind == "inf":
        assert gk == "inf"
    else:
        assert gk in ("finite", "zero")
        assert gv == (val if sq == 0 else -val), \
            f"{fmt.name} rnd={rnd}: {hex(xa)}/{hex(xb)} got {gv} want {val}"
    exact = (gk == "finite" and gv == target)
    assert bool(got_flags & FLAG_INEXACT) == (not exact), \
        f"inexact flag wrong for {hex(xa)}/{hex(xb)}"


def check_sqrt(fmt, xa, rnd):
    got_bits, got_flags = sqrt(fmt, xa, rnd)
    ka, sa, va = decode(fmt, xa)

    if ka == "nan":
        assert is_nan(fmt, got_bits)
        return
    if ka == "zero":
        assert got_bits == xa and got_flags == 0     # sqrt(+/-0) = +/-0
        return
    if sa:
        assert is_nan(fmt, got_bits) and got_flags == FLAG_INVALID
        return
    if ka == "inf":
        assert got_bits == xa and got_flags == 0
        return

    gk, gs, gv = decode(fmt, got_bits)
    assert gk == "finite" and gs == 0
    # The ordering oracle: never computes a root. gv is correct iff
    #   RTZ/RDN:  gv^2 <= va < (gv + ulp)^2
    #   RUP:      (gv - ulp)^2 < va <= gv^2
    #   RNE/RMM:  compare va against the squares of the midpoints.
    lo, hi, ulp = representables_around(fmt, gv)
    assert lo == gv, "result is representable by construction"
    below = gv - ulp_below(fmt, gv)
    above = gv + ulp
    if rnd in (RND_RTZ, RND_RDN):
        assert gv * gv <= va < above * above
    elif rnd == RND_RUP:
        assert below * below < va <= gv * gv
    else:
        # nearest: va must be at least as close to gv as to either
        # neighbour; ties by the mode's rule.
        d = abs(va - gv * gv)  # NOT a distance in root space - compare
        # properly: |sqrt(va) - gv| <= |sqrt(va) - nb| iff va is on gv's
        # side of the midpoint mid = (gv+nb)/2, i.e. compare va with
        # mid^2 (all positive).
        mid_up = (gv + above) / 2
        mid_dn = (gv + below) / 2
        assert va <= mid_up * mid_up or (
            va == mid_up * mid_up and False), "rounded past upper midpoint"
        assert va >= mid_dn * mid_dn or (
            va == mid_dn * mid_dn and False), "rounded past lower midpoint"
        if va == mid_up * mid_up:
            # exact tie at the upper midpoint
            if rnd == RND_RMM:
                assert False, "tie must round away (up)"
            steps = gv / ulp
            assert (steps.numerator // steps.denominator) % 2 == 0, \
                "RNE tie must land even"
        if va == mid_dn * mid_dn and rnd == RND_RMM:
            pass  # away from zero = up: gv is the upper neighbour, fine
    exact = (gv * gv == va)
    assert bool(got_flags & FLAG_INEXACT) == (not exact)


def ulp_below(fmt, v: Fraction):
    """The gap just below representable v (differs from the gap above
    exactly at powers of two)."""
    two = Fraction(2)
    e = max(_floor_log2(v), fmt.emin)
    q = e - fmt.man_w
    if v == two ** e and e > fmt.emin:
        return two ** (q - 1)
    return two ** q


# ---- the tests -------------------------------------------------------

def operand_pool(fmt, rng, n):
    pool = list(vectors.interesting_operands(fmt))
    while len(pool) < n:
        pool.append(rng.getrandbits(fmt.width))
    return pool


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_div_directed_and_random(fmt, rnd):
    import random
    rng = random.Random(0xD1F + rnd)
    pool = operand_pool(fmt, rng, 40)
    for xa in pool:
        for xb in pool[:20]:
            check_div(fmt, xa, xb, rnd)
    for _ in range(300):
        check_div(fmt, rng.getrandbits(fmt.width),
                  rng.getrandbits(fmt.width), rnd)


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_sqrt_directed_and_random(fmt, rnd):
    import random
    rng = random.Random(0x5047 + rnd)
    for xa in operand_pool(fmt, rng, 60):
        check_sqrt(fmt, xa, rnd)
    for _ in range(400):
        check_sqrt(fmt, rng.getrandbits(fmt.width), rnd)


def test_div_matches_native_binary64():
    """FP64 RNE against the host's IEEE hardware, on values where the
    host result is trustworthy (normal operands, normal quotient)."""
    import random
    rng = random.Random(7)
    n = 0
    for _ in range(4000):
        fa = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        fb = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        if not (math.isfinite(fa) and math.isfinite(fb)) or fb == 0:
            continue
        want = None
        try:
            want = fa / fb
        except (OverflowError, ZeroDivisionError):
            continue
        xa = struct.unpack("<Q", struct.pack("<d", fa))[0]
        xb = struct.unpack("<Q", struct.pack("<d", fb))[0]
        got, _ = div(FP64, xa, xb, RND_RNE)
        wantb = struct.unpack("<Q", struct.pack("<d", want))[0]
        assert got == wantb, f"{fa!r}/{fb!r}: got {got:#x} want {wantb:#x}"
        n += 1
    assert n > 3000


def test_sqrt_matches_native_binary64():
    import random
    rng = random.Random(8)
    n = 0
    for _ in range(4000):
        fa = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
        if not math.isfinite(fa) or fa < 0:
            continue
        want = math.sqrt(fa)
        xa = struct.unpack("<Q", struct.pack("<d", fa))[0]
        got, _ = sqrt(FP64, xa, RND_RNE)
        wantb = struct.unpack("<Q", struct.pack("<d", want))[0]
        assert got == wantb, f"sqrt({fa!r}): got {got:#x} want {wantb:#x}"
        n += 1
    assert n > 1500


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_algebraic_anchors(fmt):
    """Identities the standard makes exact, plus the named flag cases."""
    one = one_bits(fmt)
    for rnd in RND_MODES:
        # x / 1 == x exactly, flags clear (finite x)
        for x in (one, min_normal_bits(fmt), max_normal_bits(fmt),
                  min_subnormal_bits(fmt), max_subnormal_bits(fmt)):
            assert div(fmt, x, one, rnd) == (x, 0)
        # x / x == 1 exactly for finite nonzero x
        for x in (min_normal_bits(fmt), max_normal_bits(fmt),
                  max_subnormal_bits(fmt)):
            assert div(fmt, x, x, rnd) == (one, 0)
        # sqrt of an exact square is exact: sqrt(4) == 2
        four = div(fmt, one, one, rnd)[0]  # placeholder to keep flow
    # 4 = 1 + 1 + 1 + 1 via bits: exponent + 2
    two = one + (1 << fmt.man_w)
    four = one + (2 << fmt.man_w)
    for rnd in RND_MODES:
        assert sqrt(fmt, four, rnd) == (two, 0)
    # divideByZero: finite nonzero over each zero, both signs
    for s_num in (0, 1):
        for s_den in (0, 1):
            b, fl = div(fmt, one_bits(fmt, s_num), zero_bits(fmt, s_den))
            assert b == inf_bits(fmt, s_num ^ s_den)
            assert fl == FLAG_DIVZERO
    # invalid: 0/0, inf/inf, sqrt(negative), signaling operands
    assert div(fmt, zero_bits(fmt), zero_bits(fmt))[1] == FLAG_INVALID
    assert div(fmt, inf_bits(fmt), inf_bits(fmt, 1))[1] == FLAG_INVALID
    assert sqrt(fmt, one_bits(fmt, 1))[1] == FLAG_INVALID
    assert div(fmt, snan_bits(fmt), one)[1] == FLAG_INVALID
    assert sqrt(fmt, snan_bits(fmt))[1] == FLAG_INVALID
    assert div(fmt, qnan_bits(fmt), one)[1] == 0
    # underflow: a quotient landing in the subnormal range, inexactly
    b, fl = div(fmt, min_normal_bits(fmt),
                one + (2 << fmt.man_w))  # min_normal / 4 -> subnormal
    assert fl == 0 or fl == 0  # exact halving: subnormal but exact
    tiny = div(fmt, min_subnormal_bits(fmt), two)
    # min_subnormal / 2 rounds: inexact + underflow in RNE
    assert tiny[1] & FLAG_INEXACT and tiny[1] & FLAG_UNDERFLOW


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_sqrt_never_underflows_or_overflows(fmt):
    """The root of the largest finite value and of the smallest
    subnormal both land strictly inside the finite range."""
    for x in (max_normal_bits(fmt), min_subnormal_bits(fmt),
              min_normal_bits(fmt)):
        for rnd in RND_MODES:
            b, fl = sqrt(fmt, x, rnd)
            k, s, v = decode(fmt, b)
            assert k == "finite" and s == 0
            assert not (fl & FLAG_UNDERFLOW)
