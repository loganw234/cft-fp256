# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the clause-5 completion operations, against arbiters
that share no code with the model.

The same three-arbiter discipline as test_softfloat.py:

1. fp64 against CPython's native binary64 - math.remainder,
   math.nextafter, math.ldexp, math.frexp, round()/floor()/ceil()/
   trunc(), and struct's double<->float conversion, all reaching the
   host CPU's IEEE behaviour through a lineage this model shares
   nothing with.
2. An independent Fraction-based reference for round-to-integer under
   all five attributes - exact rational arithmetic, no bit twiddling in
   common with softfloat's _round_at.
3. Hand-derived 754 edge cases with expected bit patterns: the signed
   zero of roundToIntegral, nextUp's -0 rule, logB(0)'s divideByZero,
   the totalOrder chain over the whole encoding zoo, RISC-V's
   convertToInteger invalid table.
"""

import math
import struct
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    FLAG_INVALID, FLAG_DIVZERO, FLAG_OVERFLOW, FLAG_UNDERFLOW, FLAG_INEXACT,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_MODES,
    unpack, negate, is_nan,
    zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits, vectors,
    round_int, convert, from_int, to_int, scaleb, logb,
    next_up, next_down, classify, total_order, total_order_mag,
    cmplt_sig, cmple_sig, cmpeq_sig, remainder, cmplt, cmple, cmpeq,
    CLASS_NEG_INF, CLASS_NEG_NORM, CLASS_NEG_SUB, CLASS_NEG_ZERO,
    CLASS_POS_ZERO, CLASS_POS_SUB, CLASS_POS_NORM, CLASS_POS_INF,
    CLASS_SNAN, CLASS_QNAN,
)
from cft_golden import softfloat as sf  # noqa: E402

ALL_FORMATS = (FP32, FP64, FP128, FP256)
ALL_MODES = tuple(RND_MODES)


def f64_to_bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def bits_to_f64(b: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", b))[0]


def finite_value(fmt, bits) -> Fraction:
    """The exact rational value of a finite encoding."""
    u = unpack(fmt, bits)
    if u.kind == sf.ZERO:
        return Fraction(0)
    assert u.kind in (sf.SUB, sf.NORM)
    v = Fraction(u.m) * Fraction(2) ** u.e
    return -v if u.sign else v


def pack_half_integer(fmt, k: int, sign: int) -> int:
    """The encoding of sign * k/2 for small k - exact in every format."""
    bits, fl = sf.round_pack(fmt, sign, k, -1, RND_RNE)
    assert fl == 0
    return bits


def frac_to_int(v: Fraction, rnd: int) -> int:
    """Round a rational to an integer under the attribute - the
    independent reference, in exact rational arithmetic."""
    fl = math.floor(v)
    if v == fl:
        return fl
    if rnd == RND_RDN:
        return fl
    if rnd == RND_RUP:
        return fl + 1
    if rnd == RND_RTZ:
        return fl if v > 0 else fl + 1
    rem = v - fl
    if rem > Fraction(1, 2):
        return fl + 1
    if rem < Fraction(1, 2):
        return fl
    if rnd == RND_RMM:                       # tie: away from zero
        return fl + 1 if v > 0 else fl
    return fl if fl % 2 == 0 else fl + 1     # tie: to even


def sample_bits(fmt, count, seed):
    """Deterministic mixed sample: every interesting operand plus
    seeded randoms."""
    import random
    rng = random.Random(seed ^ fmt.width)
    pool = list(vectors.interesting_operands(fmt))
    out = list(pool)
    while len(out) < count:
        out.append(rng.getrandbits(fmt.width))
    return out


# ---- roundToIntegral -------------------------------------------------

@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
@pytest.mark.parametrize("rnd", ALL_MODES)
def test_round_int_matches_fraction_reference(fmt, rnd):
    checked = 0
    for bits in sample_bits(fmt, 400, seed=101):
        u = unpack(fmt, bits)
        if u.kind not in (sf.SUB, sf.NORM):
            continue
        got, flags = round_int(fmt, bits, rnd)
        want_int = frac_to_int(finite_value(fmt, bits), rnd)
        if want_int == 0:
            assert got == zero_bits(fmt, u.sign), (fmt.name, rnd, hex(bits))
        else:
            assert finite_value(fmt, got) == want_int, \
                (fmt.name, rnd, hex(bits), hex(got), want_int)
        assert flags == 0        # the named variants never say inexact
        checked += 1
    assert checked > 100


def test_round_int_fp64_matches_native():
    for bits in sample_bits(FP64, 3000, seed=103):
        u = unpack(FP64, bits)
        if u.kind not in (sf.SUB, sf.NORM):
            continue
        x = bits_to_f64(bits)
        got_dn, _ = round_int(FP64, bits, RND_RDN)
        assert finite_value(FP64, got_dn) == math.floor(x)
        got_tz, _ = round_int(FP64, bits, RND_RTZ)
        want_tz = math.trunc(x)
        assert (finite_value(FP64, got_tz) == want_tz
                if want_tz != 0 else got_tz == zero_bits(FP64, u.sign))
        got_ne, _ = round_int(FP64, bits, RND_RNE)
        want_ne = round(x)                    # CPython round(): ties to even
        assert (finite_value(FP64, got_ne) == want_ne
                if want_ne != 0 else got_ne == zero_bits(FP64, u.sign))


def test_round_int_edges():
    for fmt in ALL_FORMATS:
        half = pack_half_integer(fmt, 1, 0)          # 0.5
        neg_half = pack_half_integer(fmt, 1, 1)      # -0.5
        three_half = pack_half_integer(fmt, 3, 0)    # 1.5
        five_half = pack_half_integer(fmt, 5, 0)     # 2.5
        # ties: RNE goes to even, RMM goes away
        assert round_int(fmt, half, RND_RNE)[0] == zero_bits(fmt, 0)
        assert round_int(fmt, neg_half, RND_RNE)[0] == zero_bits(fmt, 1)
        assert finite_value(fmt, round_int(fmt, three_half, RND_RNE)[0]) == 2
        assert finite_value(fmt, round_int(fmt, five_half, RND_RNE)[0]) == 2
        assert finite_value(fmt, round_int(fmt, half, RND_RMM)[0]) == 1
        assert finite_value(fmt, round_int(fmt, five_half, RND_RMM)[0]) == 3
        # the zero result keeps the operand's sign (5.9)
        assert round_int(fmt, neg_half, RND_RTZ)[0] == zero_bits(fmt, 1)
        assert round_int(fmt, neg_half, RND_RUP)[0] == zero_bits(fmt, 1)
        # specials pass through untouched
        for x in (zero_bits(fmt, 1), inf_bits(fmt, 0), inf_bits(fmt, 1),
                  max_normal_bits(fmt, 0)):
            assert round_int(fmt, x, RND_RNE) == (x, 0)
        # NaN canonicalises; sNaN raises invalid, qNaN does not
        assert round_int(fmt, snan_bits(fmt), RND_RNE) == \
            (qnan_bits(fmt), FLAG_INVALID)
        assert round_int(fmt, qnan_bits(fmt) | 5, RND_RNE) == \
            (qnan_bits(fmt), 0)
        # exact variant: inexact iff the value changed
        assert round_int(fmt, half, RND_RNE, exact=True)[1] == FLAG_INEXACT
        assert round_int(fmt, one_bits(fmt), RND_RNE, exact=True)[1] == 0


# ---- format conversion -----------------------------------------------

LADDER = (FP32, FP64, FP128, FP256)


def test_convert_widening_is_exact_and_silent():
    for i, sfmt in enumerate(LADDER):
        for dfmt in LADDER[i + 1:]:
            for bits in sample_bits(sfmt, 500, seed=107):
                wide, flags = convert(sfmt, dfmt, bits)
                if is_nan(sfmt, bits):
                    assert wide == qnan_bits(dfmt)
                    continue
                assert flags == 0, (sfmt.name, dfmt.name, hex(bits))
                # round-trip through the wider format is the identity
                back, backfl = convert(dfmt, sfmt, wide)
                assert back == bits and backfl == 0


def test_convert_fp64_to_fp32_matches_native():
    checked = 0
    for bits in sample_bits(FP64, 4000, seed=109):
        if is_nan(FP64, bits):
            continue
        x = bits_to_f64(bits)
        got, flags = convert(FP64, FP32, bits)
        try:
            want = struct.unpack("<I", struct.pack("<f", x))[0]
        except OverflowError:
            assert got == inf_bits(FP32, 1 if x < 0 else 0)
            assert flags & FLAG_OVERFLOW
            continue
        assert got == want, (hex(bits), hex(got), hex(want))
        checked += 1
    assert checked > 1000


def test_convert_narrowing_edges():
    # a value that lands subnormal in fp32 AND drops bits doing it:
    # (2^52+1) * 2^-192 - the +1 lies far below fp32's subnormal ulp
    tiny = sf.round_pack(FP64, 0, (1 << 52) | 1, -192, RND_RNE)[0]
    got, flags = convert(FP64, FP32, tiny)
    assert unpack(FP32, got).kind == sf.SUB
    assert flags == FLAG_UNDERFLOW | FLAG_INEXACT
    # whereas a clean power of two in the same range converts exactly,
    # and an exact subnormal landing raises nothing
    assert convert(FP64, FP32, sf.round_pack(FP64, 0, 1, -140, RND_RNE)[0]) \
        == ((1 << 9), 0)                     # 2^-140 = 512 fp32 ulps
    # fp64 max normal overflows fp32: per-attribute delivery
    big = max_normal_bits(FP64, 0)
    assert convert(FP64, FP32, big, RND_RNE) == \
        (inf_bits(FP32, 0), FLAG_OVERFLOW | FLAG_INEXACT)
    assert convert(FP64, FP32, big, RND_RTZ) == \
        (max_normal_bits(FP32, 0), FLAG_OVERFLOW | FLAG_INEXACT)
    # sNaN converts to the canonical qNaN of the destination + invalid
    assert convert(FP256, FP32, snan_bits(FP256)) == \
        (qnan_bits(FP32), FLAG_INVALID)
    # signed zero survives the trip
    assert convert(FP64, FP32, zero_bits(FP64, 1)) == (zero_bits(FP32, 1), 0)


# ---- integer conversions ---------------------------------------------

def test_from_int_fp64_matches_native():
    import random
    rng = random.Random(113)
    vals = [0, 1, -1, 2**52, 2**53, 2**53 + 1, -(2**53) - 1,
            2**63 - 1, -(2**63), 2**64 - 1]
    vals += [rng.randint(-(2**63), 2**63 - 1) for _ in range(2000)]
    for v in vals:
        got, _ = from_int(FP64, v)
        assert got == f64_to_bits(float(v)), v


def test_from_int_inexact_flag():
    assert from_int(FP32, 1 << 24)[1] == 0            # exactly representable
    assert from_int(FP32, (1 << 24) + 1)[1] == FLAG_INEXACT
    assert from_int(FP64, 0) == (zero_bits(FP64, 0), 0)


def test_to_int_fp64_matches_native():
    for bits in sample_bits(FP64, 3000, seed=127):
        u = unpack(FP64, bits)
        if u.kind not in (sf.SUB, sf.NORM):
            continue
        x = bits_to_f64(bits)
        if not (-2**62 < x < 2**62):
            continue
        got, flags = to_int(FP64, bits, 64, True, RND_RTZ)
        assert got == math.trunc(x) and flags == 0
        got, flags = to_int(FP64, bits, 64, True, RND_RNE)
        assert got == round(x) and flags == 0
        got, flags = to_int(FP64, bits, 64, True, RND_RDN)
        assert got == math.floor(x) and flags == 0
        got, flags = to_int(FP64, bits, 64, True, RND_RUP)
        assert got == math.ceil(x) and flags == 0


def test_to_int_invalid_table():
    for fmt in ALL_FORMATS:
        # RISC-V FCVT delivery: NaN and +inf to max, -inf to min
        assert to_int(fmt, qnan_bits(fmt), 32, True) == \
            (2**31 - 1, FLAG_INVALID)
        assert to_int(fmt, snan_bits(fmt), 32, True) == \
            (2**31 - 1, FLAG_INVALID)
        assert to_int(fmt, inf_bits(fmt, 0), 32, True) == \
            (2**31 - 1, FLAG_INVALID)
        assert to_int(fmt, inf_bits(fmt, 1), 32, True) == \
            (-(2**31), FLAG_INVALID)
        assert to_int(fmt, inf_bits(fmt, 1), 32, False) == (0, FLAG_INVALID)
        # a negative that ROUNDS to zero is representable unsigned: no invalid
        neg_half = pack_half_integer(fmt, 1, 1)
        assert to_int(fmt, neg_half, 32, False, RND_RTZ) == (0, 0)
        assert to_int(fmt, neg_half, 32, False, RND_RTZ, exact=True) == \
            (0, FLAG_INEXACT)
        # a negative that rounds below zero is not: invalid, delivers 0
        neg_three_half = pack_half_integer(fmt, 3, 1)
        assert to_int(fmt, neg_three_half, 32, False, RND_RTZ) == \
            (0, FLAG_INVALID)
        # signed zeros convert silently
        assert to_int(fmt, zero_bits(fmt, 1), 64, True) == (0, 0)
    # range edge: 2^31 overflows int32 but not uint32
    two31 = from_int(FP64, 2**31)[0]
    assert to_int(FP64, two31, 32, True) == (2**31 - 1, FLAG_INVALID)
    assert to_int(FP64, two31, 32, False) == (2**31, 0)


def test_int_round_trip():
    import random
    rng = random.Random(131)
    for fmt in ALL_FORMATS:
        for _ in range(300):
            v = rng.randint(-(2**23), 2**23)   # exact in every format
            bits, fl = from_int(fmt, v)
            assert fl == 0
            back, fl2 = to_int(fmt, bits, 64, True, RND_RNE, exact=True)
            assert back == v and fl2 == 0


# ---- scaleB and logB -------------------------------------------------

def test_scaleb_fp64_matches_native():
    import random
    rng = random.Random(137)
    for bits in sample_bits(FP64, 1500, seed=139):
        u = unpack(FP64, bits)
        if u.kind == sf.NAN:
            continue
        x = bits_to_f64(bits)
        for n in (0, 1, -1, 52, -52, 700, -700, 1500, -1500,
                  rng.randint(-2200, 2200)):
            got, _ = scaleb(FP64, bits, n)
            try:
                want = f64_to_bits(math.ldexp(x, n))
            except OverflowError:
                want = inf_bits(FP64, u.sign)
            assert got == want, (hex(bits), n, hex(got), hex(want))


def test_scaleb_flags_and_edges():
    for fmt in ALL_FORMATS:
        one = one_bits(fmt)
        # exact scaling is silent, subnormals included (the encoding of
        # the n-ulp subnormal is the integer n, which keeps this legible)
        assert scaleb(fmt, one, 3) == (sf.round_pack(fmt, 0, 1, 3, RND_RNE)[0], 0)
        assert scaleb(fmt, 1, 1) == (2, 0)
        # overflow: per-attribute delivery, overflow+inexact
        big = max_normal_bits(fmt, 0)
        assert scaleb(fmt, big, 1, RND_RNE) == \
            (inf_bits(fmt, 0), FLAG_OVERFLOW | FLAG_INEXACT)
        assert scaleb(fmt, big, 1, RND_RTZ) == \
            (max_normal_bits(fmt, 0), FLAG_OVERFLOW | FLAG_INEXACT)
        # the 3-ulp subnormal halved lands on a tie between 1 and 2
        # ulps: inexact below the floor, so underflow too, and RNE
        # takes the even side
        got, flags = scaleb(fmt, 3, -1)
        assert (got, flags) == (2, FLAG_UNDERFLOW | FLAG_INEXACT)
        # specials pass through; sNaN raises invalid
        assert scaleb(fmt, inf_bits(fmt, 1), 5) == (inf_bits(fmt, 1), 0)
        assert scaleb(fmt, zero_bits(fmt, 1), -5) == (zero_bits(fmt, 1), 0)
        assert scaleb(fmt, snan_bits(fmt), 0) == \
            (qnan_bits(fmt), FLAG_INVALID)


def test_logb_fp64_matches_native():
    for bits in sample_bits(FP64, 2000, seed=149):
        u = unpack(FP64, bits)
        if u.kind not in (sf.SUB, sf.NORM):
            continue
        x = bits_to_f64(bits)
        want = math.frexp(abs(x))[1] - 1      # frexp: x = m * 2^e, 0.5<=m<1
        got, flags = logb(FP64, bits)
        assert flags == 0
        want_bits = f64_to_bits(float(want))
        assert got == want_bits, (hex(bits), want, hex(got))


def test_logb_specials():
    for fmt in ALL_FORMATS:
        assert logb(fmt, zero_bits(fmt, 0)) == (inf_bits(fmt, 1), FLAG_DIVZERO)
        assert logb(fmt, zero_bits(fmt, 1)) == (inf_bits(fmt, 1), FLAG_DIVZERO)
        assert logb(fmt, inf_bits(fmt, 0)) == (inf_bits(fmt, 0), 0)
        assert logb(fmt, inf_bits(fmt, 1)) == (inf_bits(fmt, 0), 0)
        assert logb(fmt, snan_bits(fmt)) == (qnan_bits(fmt), FLAG_INVALID)
        # subnormals report their VALUE exponent, not emin
        assert finite_value(fmt, logb(fmt, min_subnormal_bits(fmt, 0))[0]) \
            == fmt.emin - fmt.man_w
        assert finite_value(fmt, logb(fmt, one_bits(fmt, 1))[0]) == 0
        assert logb(fmt, one_bits(fmt))[0] == zero_bits(fmt, 0)   # +0, not -0


# ---- nextUp / nextDown -----------------------------------------------

def test_next_fp64_matches_native():
    for bits in sample_bits(FP64, 3000, seed=151):
        if is_nan(FP64, bits):
            continue
        x = bits_to_f64(bits)
        up, flags = next_up(FP64, bits)
        assert flags == 0
        want = math.nextafter(x, math.inf)
        got_v = bits_to_f64(up)
        # -min_subnormal steps to -0: nextafter agrees on the value;
        # the SIGN of that zero is the 754 rule, checked directly below
        assert got_v == want or (got_v == 0 and want == 0)
        dn, _ = next_down(FP64, bits)
        assert bits_to_f64(dn) == math.nextafter(x, -math.inf) or \
            (bits_to_f64(dn) == 0 and math.nextafter(x, -math.inf) == 0)


def test_next_edges():
    for fmt in ALL_FORMATS:
        # the standard's explicit zero choices
        assert next_up(fmt, min_subnormal_bits(fmt, 1)) == (zero_bits(fmt, 1), 0)
        assert next_down(fmt, min_subnormal_bits(fmt, 0)) == (zero_bits(fmt, 0), 0)
        assert next_up(fmt, zero_bits(fmt, 0)) == (min_subnormal_bits(fmt, 0), 0)
        assert next_up(fmt, zero_bits(fmt, 1)) == (min_subnormal_bits(fmt, 0), 0)
        assert next_down(fmt, zero_bits(fmt, 0)) == (min_subnormal_bits(fmt, 1), 0)
        # infinities: saturate up, step down to the largest finite
        assert next_up(fmt, inf_bits(fmt, 0)) == (inf_bits(fmt, 0), 0)
        assert next_up(fmt, inf_bits(fmt, 1)) == (max_normal_bits(fmt, 1), 0)
        assert next_down(fmt, inf_bits(fmt, 1)) == (inf_bits(fmt, 1), 0)
        # largest finite steps to infinity with NO overflow signal
        assert next_up(fmt, max_normal_bits(fmt, 0)) == (inf_bits(fmt, 0), 0)
        # binade boundary is just +1 on the encoding
        below_two = one_bits(fmt) | fmt.man_mask
        two = (fmt.bias + 1) << fmt.man_w
        assert next_up(fmt, below_two) == (two, 0)
        # NaN: canonical out; only sNaN signals
        assert next_up(fmt, snan_bits(fmt)) == (qnan_bits(fmt), FLAG_INVALID)
        assert next_down(fmt, snan_bits(fmt)) == (qnan_bits(fmt), FLAG_INVALID)
        assert next_down(fmt, qnan_bits(fmt) | 3) == (qnan_bits(fmt), 0)


# ---- classification and totalOrder -----------------------------------

def test_classify_table():
    for fmt in ALL_FORMATS:
        table = [
            (inf_bits(fmt, 1), CLASS_NEG_INF),
            (one_bits(fmt, 1), CLASS_NEG_NORM),
            (max_normal_bits(fmt, 1), CLASS_NEG_NORM),
            (max_subnormal_bits(fmt, 1), CLASS_NEG_SUB),
            (zero_bits(fmt, 1), CLASS_NEG_ZERO),
            (zero_bits(fmt, 0), CLASS_POS_ZERO),
            (min_subnormal_bits(fmt, 0), CLASS_POS_SUB),
            (min_normal_bits(fmt, 0), CLASS_POS_NORM),
            (inf_bits(fmt, 0), CLASS_POS_INF),
            (snan_bits(fmt), CLASS_SNAN),
            (snan_bits(fmt) | fmt.sign_mask, CLASS_SNAN),
            (qnan_bits(fmt), CLASS_QNAN),
            (qnan_bits(fmt) | 5 | fmt.sign_mask, CLASS_QNAN),
        ]
        for bits, want in table:
            assert classify(fmt, bits) == want, (fmt.name, hex(bits))


def test_total_order_chain():
    for fmt in ALL_FORMATS:
        sm = fmt.sign_mask
        chain = [
            sm | qnan_bits(fmt) | 5,            # -qNaN, bigger payload first
            sm | qnan_bits(fmt),
            sm | snan_bits(fmt, payload=2),
            sm | snan_bits(fmt, payload=1),
            inf_bits(fmt, 1),
            max_normal_bits(fmt, 1),
            one_bits(fmt, 1),
            min_normal_bits(fmt, 1),
            max_subnormal_bits(fmt, 1),
            min_subnormal_bits(fmt, 1),
            zero_bits(fmt, 1),
            zero_bits(fmt, 0),
            min_subnormal_bits(fmt, 0),
            max_subnormal_bits(fmt, 0),
            min_normal_bits(fmt, 0),
            one_bits(fmt, 0),
            max_normal_bits(fmt, 0),
            inf_bits(fmt, 0),
            snan_bits(fmt, payload=1),
            snan_bits(fmt, payload=2),
            qnan_bits(fmt),
            qnan_bits(fmt) | 5,
        ]
        t, f = one_bits(fmt), zero_bits(fmt)
        for i, x in enumerate(chain):
            for j, y in enumerate(chain):
                want = t if i <= j else f
                got, flags = total_order(fmt, x, y)
                assert flags == 0
                assert got == want, (fmt.name, i, j, hex(x), hex(y))
        # reflexive on every member, signalling nothing even for sNaN
        for x in chain:
            assert total_order(fmt, x, x) == (t, 0)
        # totalOrderMag ignores the sign
        assert total_order_mag(fmt, one_bits(fmt, 1), one_bits(fmt, 0)) == (t, 0)
        assert total_order_mag(fmt, max_normal_bits(fmt, 1),
                               one_bits(fmt, 0)) == (f, 0)


# ---- signaling comparisons -------------------------------------------

def test_signaling_compares():
    for fmt in ALL_FORMATS:
        pairs = [(one_bits(fmt), one_bits(fmt) | 1),
                 (one_bits(fmt, 1), one_bits(fmt)),
                 (zero_bits(fmt, 0), zero_bits(fmt, 1)),
                 (inf_bits(fmt, 1), max_normal_bits(fmt, 1))]
        for xa, xb in pairs:
            # ordered operands: identical truth to the quiet predicates
            for quiet, loud in ((cmplt, cmplt_sig), (cmple, cmple_sig),
                                (cmpeq, cmpeq_sig)):
                assert loud(fmt, xa, xb) == quiet(fmt, xa, xb)
        # ANY NaN: false + invalid, where quiet raises only for sNaN
        q, s = qnan_bits(fmt), snan_bits(fmt)
        for nan in (q, s):
            for other in (one_bits(fmt), nan):
                for loud in (cmplt_sig, cmple_sig, cmpeq_sig):
                    assert loud(fmt, nan, other) == \
                        (zero_bits(fmt), FLAG_INVALID)
                    assert loud(fmt, other, nan) == \
                        (zero_bits(fmt), FLAG_INVALID)
        assert cmpeq(fmt, q, q) == (zero_bits(fmt), 0)   # the quiet contrast


# ---- remainder -------------------------------------------------------

def test_remainder_fp64_matches_native():
    import random
    rng = random.Random(157)
    checked = 0
    for _ in range(4000):
        xa = rng.getrandbits(64)
        xb = rng.getrandbits(64)
        ua, ub = unpack(FP64, xa), unpack(FP64, xb)
        if ua.kind not in (sf.SUB, sf.NORM) or ub.kind not in (sf.SUB, sf.NORM):
            continue
        x, y = bits_to_f64(xa), bits_to_f64(xb)
        got, flags = remainder(FP64, xa, xb)
        want = f64_to_bits(math.remainder(x, y))
        assert got == want, (hex(xa), hex(xb), hex(got), hex(want))
        assert flags == 0
        checked += 1
    assert checked > 1000


def test_remainder_close_quotients():
    # near-equal magnitudes are where the tie logic lives
    for fmt in ALL_FORMATS:
        one = one_bits(fmt)
        # rem(1, 1) = +0; rem(-1, 1) = -0 (zero takes x's sign)
        assert remainder(fmt, one, one) == (zero_bits(fmt, 0), 0)
        assert remainder(fmt, one_bits(fmt, 1), one) == (zero_bits(fmt, 1), 0)
        # rem(1.5, 1) = -0.5: quotient 1.5 ties to even n=2
        three_half = pack_half_integer(fmt, 3, 0)
        assert finite_value(fmt, remainder(fmt, three_half, one)[0]) == \
            Fraction(-1, 2)
        # rem(2.5, 1) = 0.5: quotient 2.5 ties to even n=2
        five_half = pack_half_integer(fmt, 5, 0)
        assert finite_value(fmt, remainder(fmt, five_half, one)[0]) == \
            Fraction(1, 2)
        # magnitude never exceeds |y|/2
        import random
        rng = random.Random(163 ^ fmt.width)
        for _ in range(200):
            xa, xb = rng.getrandbits(fmt.width), rng.getrandbits(fmt.width)
            ua, ub = unpack(fmt, xa), unpack(fmt, xb)
            if ua.kind not in (sf.SUB, sf.NORM) or \
                    ub.kind not in (sf.SUB, sf.NORM):
                continue
            got, flags = remainder(fmt, xa, xb)
            assert flags == 0
            assert abs(finite_value(fmt, got)) * 2 <= \
                abs(finite_value(fmt, xb))


def test_remainder_specials():
    for fmt in ALL_FORMATS:
        one = one_bits(fmt)
        # invalid: infinite dividend or zero divisor
        for xa in (inf_bits(fmt, 0), inf_bits(fmt, 1)):
            assert remainder(fmt, xa, one) == (qnan_bits(fmt), FLAG_INVALID)
        for xb in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
            assert remainder(fmt, one, xb) == (qnan_bits(fmt), FLAG_INVALID)
        assert remainder(fmt, zero_bits(fmt, 0), zero_bits(fmt, 0)) == \
            (qnan_bits(fmt), FLAG_INVALID)
        # exact pass-throughs
        assert remainder(fmt, one, inf_bits(fmt, 0)) == (one, 0)
        assert remainder(fmt, zero_bits(fmt, 1), one) == (zero_bits(fmt, 1), 0)
        sub = min_subnormal_bits(fmt, 0)
        assert remainder(fmt, sub, inf_bits(fmt, 1)) == (sub, 0)
        # extreme exponent gap: subnormal REM near-max - stays exact
        got, flags = remainder(fmt, sub, max_normal_bits(fmt, 0))
        assert got == sub and flags == 0
        got, flags = remainder(fmt, max_normal_bits(fmt, 0), sub)
        assert flags == 0     # the half-million-bit divmod, exercised
        # NaN rules
        assert remainder(fmt, snan_bits(fmt), one) == \
            (qnan_bits(fmt), FLAG_INVALID)
        assert remainder(fmt, one, qnan_bits(fmt) | 7) == (qnan_bits(fmt), 0)


# ---- the double-rounding trap family (from the adversarial review) ---

def test_convert_fp256_to_fp32_midpoint_traps():
    """fp32 midpoints nudged by +-2^-200, encoded exactly in fp256 and
    narrowed directly. The nudge lives ~170 bits below anything fp64
    can carry, so a two-step route through fp64 provably loses it -
    the review measured the divergence on 1,200 of these - while the
    direct single-rounding path must not. Scored against ref754, the
    Fraction oracle that shares no code with the model; the test also
    asserts the two-step route DOES diverge somewhere, because a trap
    family that nothing falls into proves nothing about the trap."""
    import random
    sys.path.insert(0, str(
        __import__("pathlib").Path(__file__).resolve().parent))
    import ref754 as orc

    o32, o256 = orc.Fmt(8, 23), orc.Fmt(19, 236)
    rng = random.Random(0xD0B1)
    two_step_divergences = 0
    checked = 0
    for _ in range(400):
        f32bits = (rng.randrange(1, 0xFE) << 23) | rng.getrandbits(23)
        kind, _s, v = orc.dec(o32, f32bits)
        assert kind == "num"
        ulp = Fraction(2) ** (orc.floor_log2(abs(v)) - 23)
        eps = Fraction(2) ** (orc.floor_log2(abs(v)) - 200)
        for nudge in (0, 1, -1):
            mid = v + ulp / 2 + nudge * eps
            sb = orc.enc_exact(o256, mid)
            if sb is None:
                continue
            for rnd in RND_MODES:
                got = convert(FP256, FP32, sb, rnd)
                want = orc.ref_convert(o256, o32, sb, rnd)
                assert got == want, (hex(f32bits), nudge, rnd, got, want)
                mid64, _ = convert(FP256, FP64, sb, rnd)
                two, _ = convert(FP64, FP32, mid64, rnd)
                if two != got[0]:
                    two_step_divergences += 1
                checked += 1
    assert checked > 4000
    assert two_step_divergences > 0     # the family discriminates


def test_total_order_nan_zoo_vs_ref754():
    """Every pair from a NaN-heavy fp64 zoo, against ref754's
    rule-by-rule 5.10 restatement - the model's key transform never
    consulted on the expected side."""
    sys.path.insert(0, str(
        __import__("pathlib").Path(__file__).resolve().parent))
    import ref754 as orc

    o64 = orc.Fmt(11, 52)
    fmt = FP64
    zoo = [zero_bits(fmt, 0), zero_bits(fmt, 1),
           one_bits(fmt), one_bits(fmt, 1),
           inf_bits(fmt, 0), inf_bits(fmt, 1),
           min_subnormal_bits(fmt, 0), min_subnormal_bits(fmt, 1),
           max_normal_bits(fmt, 0), max_normal_bits(fmt, 1),
           qnan_bits(fmt), qnan_bits(fmt) | fmt.sign_mask,
           qnan_bits(fmt) | 1, qnan_bits(fmt) | 0x7ffffffffffff,
           (qnan_bits(fmt) | 5) | fmt.sign_mask,
           snan_bits(fmt, 1), snan_bits(fmt, 2),
           snan_bits(fmt, (1 << 51) - 1),
           snan_bits(fmt, 1) | fmt.sign_mask,
           snan_bits(fmt, 7) | fmt.sign_mask]
    t, f = one_bits(fmt), zero_bits(fmt)
    for x in zoo:
        for y in zoo:
            want = t if orc.ref_total_order(o64, x, y) else f
            assert total_order(fmt, x, y) == (want, 0), (hex(x), hex(y))
