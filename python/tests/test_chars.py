# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the clause-5.12 character conversions and the
clause-9.7 payload operations, against arbiters that share no code with
the model.

The same discipline the rest of the suite keeps:

1. An independent Fraction-based reference. A decimal sequence's value
   is a rational, so `ref754.ref_pack` - which restates 754's rounding,
   7.4 overflow and 7.5 tininess from scratch in exact rationals - is
   the whole oracle for the parse. A model bug and an oracle bug would
   have to agree.
2. fp64 against CPython's own binary64. `float(s)` is a correctly
   rounded decimal parse and `"%.16e" % x` is a correctly rounded
   17-digit decimal write, through a lineage this model shares nothing
   with.
3. Hand-derived 754 edges with expected characters: the spellings
   5.12.1 names, the sign of a zero, the payload suffix, the
   admissibility rule of 9.7 and its +0 fallback.

And two structural properties that are the point of the clause:
exactness (the exact conversion's sequence, read back as a Fraction,
IS the value) and the round trip at Pmin (with its documented failure
one digit short).
"""

import struct
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    FLAG_INEXACT, FLAG_OVERFLOW, FLAG_UNDERFLOW,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_MODES,
    chars, vectors,
    inf_bits, max_normal_bits, max_subnormal_bits, min_normal_bits,
    min_subnormal_bits, one_bits, qnan_bits, snan_bits, zero_bits,
)
from cft_golden import softfloat as sf  # noqa: E402

ALL = (FP32, FP64, FP128, FP256)


def orc_fmt(fmt):
    import ref754 as orc
    return orc.Fmt(fmt.exp_w, fmt.man_w)


def big_int(text, base):
    """int(text, base) with CPython's conversion guard lifted for the
    duration. The 4300-digit cap is a denial-of-service guard against
    quadratic base-10 conversion, not a statement about arithmetic, and
    the exact decimal of a binary256 subnormal is 183,000 digits
    long."""
    try:
        return int(text or "0", base)
    except ValueError:
        old_cap = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(0)
        try:
            return int(text or "0", base)
        finally:
            sys.set_int_max_str_digits(old_cap)


def seq_value(text):
    """The exact value of a finite decimal or hexadecimal sequence, as a
    Fraction - read HERE rather than by the model, so a comparison is
    against the sequence's meaning and not against the model's reading
    of it."""
    t = text
    sign = 1
    if t[0] in "+-":
        sign = -1 if t[0] == "-" else 1
        t = t[1:]
    if t[:2].lower() == "0x":
        t = t[2:]
        mark, base, radix = "p", 16, 2
    else:
        mark, base, radix = "e", 10, 10
    exp = 0
    idx = t.lower().find(mark)
    if idx >= 0:
        exp = int(t[idx + 1:], 10)
        t = t[:idx]
    head, _, tail = t.partition(".")
    return (sign * Fraction(big_int(head + tail, base))
            * Fraction(base) ** (-len(tail)) * Fraction(radix) ** exp)


# ----------------------------------------------------------------------
# Pmin
# ----------------------------------------------------------------------

def test_pmin_matches_the_standards_own_table():
    """5.12.2 lists Pmin for binary32/64/128 outright; the formula
    1 + ceiling(p * log10 2) has to reproduce all three before it can
    be trusted for binary256."""
    assert chars.pmin(FP32) == 9
    assert chars.pmin(FP64) == 17
    assert chars.pmin(FP128) == 36
    assert chars.pmin(FP256) == 73


@pytest.mark.parametrize("fmt", ALL)
def test_pmin_is_the_smallest_k_with_ten_to_the_k_over_two_to_the_p(fmt):
    k = chars.pmin(fmt) - 1
    assert 10 ** k >= 1 << fmt.prec
    assert 10 ** (k - 1) < 1 << fmt.prec


# ----------------------------------------------------------------------
# convertToDecimalCharacter: exactness
# ----------------------------------------------------------------------

def pool(fmt, extra=0):
    out = list(vectors.interesting_operands(fmt))
    out += [min_subnormal_bits(fmt, 0), min_subnormal_bits(fmt, 1),
            max_subnormal_bits(fmt, 0), min_normal_bits(fmt, 0),
            max_normal_bits(fmt, 0), one_bits(fmt, 1)]
    for k in (1, 3, 5, 7, 9, 11, 13):
        for s in (0, 1):
            out.append(sf.round_pack(fmt, s, k, -3, sf.RND_RNE)[0])
            out.append(sf.round_pack(fmt, s, k * 5, -1, sf.RND_RNE)[0])
    return out


@pytest.mark.parametrize("fmt", ALL)
def test_exact_conversion_is_exact(fmt):
    """The whole content of "exact": the sequence, read back as an
    exact rational by code that is not the model, equals the value the
    encoding denotes."""
    for bits in pool(fmt):
        kind, sign, m, e, _, _ = chars._decode(fmt, bits)
        text, flags = chars.to_decimal(fmt, bits, 0)
        assert flags == 0, (fmt.name, hex(bits))
        if kind == "nan":
            continue
        if kind == "inf":
            assert text == ("-inf" if sign else "inf")
            continue
        if kind == "zero":
            assert text == ("-0" if sign else "0")
            continue
        want = Fraction((-1) ** sign * m) * Fraction(2) ** e
        assert seq_value(text) == want, (fmt.name, hex(bits), text[:60])


@pytest.mark.parametrize("fmt", ALL)
def test_exact_hex_is_exact_and_shortest(fmt):
    for bits in pool(fmt):
        kind, sign, m, e, _, _ = chars._decode(fmt, bits)
        text = chars.to_hex(fmt, bits)
        if kind in ("nan", "inf"):
            continue
        if kind == "zero":
            assert text == ("-0x0p+0" if sign else "0x0p+0")
            continue
        assert seq_value(text) == Fraction((-1) ** sign * m) * Fraction(2) ** e
        # shortest: a leading 1 and no trailing zero in the fraction
        body = text.lstrip("-")
        assert body.startswith("0x1")
        if "." in body:
            assert not body.split("p")[0].endswith("0")


# ----------------------------------------------------------------------
# convertFromDecimalCharacter: correctly rounded
# ----------------------------------------------------------------------

DECIMALS = [
    "0", "-0", "1", "-1", "0.1", "0.5", "1.5", "2.5", "1.25", "3.3",
    "1e0", "1e10", "1e-10", "123456789", "9" * 25, "0." + "0" * 20 + "7",
    "1e30", "1e-30", "6.02214076e23", "2.718281828459045235360287",
    "1e400", "1e-400", "1e4000", "1e-4000",
]


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_from_decimal_matches_the_rational_reference(fmt, rnd):
    """ref754 rounds an exact rational by restating 754's rules from
    scratch. A decimal sequence IS an exact rational, so it is the
    oracle for this conversion with nothing shared."""
    import ref754 as orc
    of = orc_fmt(fmt)
    for s in DECIMALS:
        got, flags = chars.from_decimal(fmt, s, rnd)
        v = seq_value(s)
        if v == 0:
            assert got == zero_bits(fmt, 1 if s.startswith("-") else 0)
            assert flags == 0
            continue
        want, wflags = orc.ref_pack(of, v, rnd)
        assert (got, flags) == (want, wflags), (fmt.name, s, rnd, hex(got),
                                                hex(want), flags, wflags)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_exact_ties_are_decided_by_the_attribute(fmt, rnd):
    """The halfway sequence between two neighbouring encodings, written
    out exactly. Nothing but the attribute can decide it, and the
    rational reference decides it independently."""
    import ref754 as orc
    of = orc_fmt(fmt)
    for base in (one_bits(fmt, 0), min_normal_bits(fmt, 0),
                 min_subnormal_bits(fmt, 0)):
        k1, sign, m1, e1, _, _ = chars._decode(fmt, base)
        k2, _, m2, e2, _, _ = chars._decode(fmt, base + 1)
        assert k1 == k2 == "finite"
        e = min(e1, e2) - 1
        mid = ((m1 << (e1 - e)) + (m2 << (e2 - e))) // 2
        ds, exp10 = chars.exact_digits(mid, e)
        for s in (chars._format_finite(0, ds, exp10),
                  chars._format_finite(1, ds, exp10)):
            got, flags = chars.from_decimal(fmt, s, rnd)
            want, wflags = orc.ref_pack(of, seq_value(s), rnd)
            assert (got, flags) == (want, wflags), (fmt.name, s, rnd)


@pytest.mark.parametrize("rnd", RND_MODES)
def test_from_decimal_fp64_against_cpython(rnd):
    """CPython's float() is a correctly rounded binary64 decimal parse,
    reached through a lineage this model shares nothing with. Only the
    nearest attribute can be compared - CPython has no others - which
    is exactly why the rational reference above exists."""
    if rnd != RND_RNE:
        pytest.skip("CPython parses to nearest only")
    for s in DECIMALS + ["1.7976931348623157e308", "5e-324", "2.5e-324",
                         "4.9406564584124654e-324", "1e309", "-1e309"]:
        got, _ = chars.from_decimal(FP64, s, RND_RNE)
        native = float(s)
        want = struct.unpack("<Q", struct.pack("<d", native))[0]
        assert got == want, (s, hex(got), hex(want))


def test_to_decimal_fp64_against_cpython_formatting():
    """"%.16e" is a correctly rounded 17-significant-digit decimal, and
    17 is binary64's Pmin - so the two have to agree character for
    character once the exponent is written the same way."""
    for x in (0.1, 1.5, 1e300, 5e-324, 2.2250738585072014e-308,
              3.141592653589793, -2.718281828459045, 1234.5678):
        bits = struct.unpack("<Q", struct.pack("<d", x))[0]
        got, _ = chars.to_decimal(FP64, bits, 17, RND_RNE)
        mant, exp = ("%.16e" % x).split("e")
        want = "%se%s%d" % (mant, "+" if int(exp) >= 0 else "-",
                            abs(int(exp)))
        assert got == want, (x, got, want)


# ----------------------------------------------------------------------
# The round trip 5.12 opens by requiring
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ALL)
def test_round_trip_at_pmin(fmt):
    h = chars.pmin(fmt)
    for bits in pool(fmt):
        if sf.is_nan(fmt, bits):
            continue
        for rnd in (RND_RNE, RND_RMM):
            text, _ = chars.to_decimal(fmt, bits, h, rnd)
            back, _ = chars.from_decimal(fmt, text, rnd)
            assert back == bits, (fmt.name, hex(bits), text[:60], hex(back))


@pytest.mark.parametrize("fmt", ALL)
def test_round_trip_fails_one_digit_short(fmt):
    """Pmin is not merely sufficient, it is necessary: at Pmin - 1
    there are neighbouring encodings whose decimals collide. Exhibited
    rather than asserted, so the guarantee above is known to be tight."""
    h = chars.pmin(fmt) - 1
    found = None
    for k in range(0, 40):
        top = sf.round_pack(fmt, 0, (1 << fmt.prec) - 1, k - fmt.man_w,
                            RND_RNE)[0]
        for step in range(64):
            x, y = top - step - 1, top - step
            tx, _ = chars.to_decimal(fmt, x, h, RND_RNE)
            ty, _ = chars.to_decimal(fmt, y, h, RND_RNE)
            if tx == ty:
                found = (x, y, tx)
                break
        if found:
            break
    assert found, fmt.name
    x, y, text = found
    back, _ = chars.from_decimal(fmt, text, RND_RNE)
    assert back != x or back != y


@pytest.mark.parametrize("fmt", ALL)
def test_hex_round_trip_is_exact_in_every_attribute(fmt):
    """The hexadecimal form is exact, so nothing is rounded and the
    attribute cannot matter - which is a stronger claim than the
    decimal round trip and is worth checking as one."""
    for bits in pool(fmt):
        if sf.is_nan(fmt, bits):
            continue
        text = chars.to_hex(fmt, bits)
        for rnd in RND_MODES:
            back, flags = chars.from_hex(fmt, text, rnd)
            assert (back, flags) == (bits, 0), (fmt.name, hex(bits), text)


# ----------------------------------------------------------------------
# The 5.12.1 words
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ALL)
def test_special_spellings(fmt):
    assert chars.to_decimal(fmt, inf_bits(fmt, 0), 0)[0] == "inf"
    assert chars.to_decimal(fmt, inf_bits(fmt, 1), 0)[0] == "-inf"
    assert chars.to_decimal(fmt, zero_bits(fmt, 1), 0)[0] == "-0"
    assert chars.to_decimal(fmt, qnan_bits(fmt), 0)[0] == "nan"
    assert chars.to_decimal(fmt, qnan_bits(fmt) | 5, 0)[0] == "nan(0x5)"
    assert chars.to_decimal(fmt, snan_bits(fmt, 5), 0)[0] == "snan(0x5)"
    assert (chars.to_decimal(fmt, fmt.sign_mask | snan_bits(fmt, 1), 0)[0]
            == "-snan(0x1)")
    for text, want in (("inf", inf_bits(fmt, 0)),
                       ("INFINITY", inf_bits(fmt, 0)),
                       ("-Inf", inf_bits(fmt, 1)),
                       ("nan", qnan_bits(fmt)),
                       ("NaN(5)", qnan_bits(fmt) | 5),
                       ("nan(0x5)", qnan_bits(fmt) | 5),
                       ("snan", snan_bits(fmt, 1)),
                       ("-SNAN(0x3)", fmt.sign_mask | snan_bits(fmt, 3))):
        got, flags = chars.from_decimal(fmt, text, RND_RNE)
        assert (got, flags) == (want, 0), (fmt.name, text, hex(got))
        got, flags = chars.from_hex(fmt, text, RND_RNE)
        assert (got, flags) == (want, 0), (fmt.name, "hex", text)


@pytest.mark.parametrize("fmt", ALL)
def test_a_signaling_nan_conversion_raises_nothing(fmt):
    """6.2 exempts "the conversions described in 5.12" from the rule
    that a signaling NaN signals invalid, and 5.12.1 asks for invalid
    only when an sNaN is written as "nan". This contract writes "snan"
    instead, so nothing is raised in either direction and the round
    trip keeps the distinction."""
    bits = snan_bits(fmt, 7)
    text, flags = chars.to_decimal(fmt, bits, 0)
    assert flags == 0 and text == "snan(0x7)"
    back, bflags = chars.from_decimal(fmt, text, RND_RNE)
    assert (back, bflags) == (bits, 0)


@pytest.mark.parametrize("fmt", ALL)
def test_refusals(fmt):
    for s in ("", "+", "-", ".", "e5", "1e", "1e+", "1 ", " 1", "1.5.5",
              "1,5", "0x1p+0", "1p5", "--1", "nan()", "nan(x)", "nan(0x)",
              "infi", "nanx", "1_000", "1.5e5x"):
        with pytest.raises(chars.CharacterSyntaxError):
            chars.from_decimal(fmt, s, RND_RNE)
    for s in ("", "0x", "0x1", "0x1.8", "1.8p+3", "0x1.8e+3", "0xg.1p+0",
              " 0x1p+0", "1e5", "0x1p+0.5"):
        with pytest.raises(chars.CharacterSyntaxError):
            chars.from_hex(fmt, s, RND_RNE)
    # a payload the format cannot hold is in the syntax and still
    # refused - a truncation would silently produce a different NaN
    with pytest.raises(chars.CharacterSyntaxError):
        chars.from_decimal(fmt, "nan(0x%x)" % chars.max_payload(fmt),
                           RND_RNE)
    with pytest.raises(chars.CharacterSyntaxError):
        chars.from_decimal(fmt, "snan(0)", RND_RNE)


# ----------------------------------------------------------------------
# The bands: an exponent no arithmetic can reach still has an answer
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_absurd_exponents_agree_with_a_merely_large_one(fmt, rnd):
    """The library answers "1e999999999999" from a band rather than by
    computing 10^999999999999. The band is only sound if the answer is
    the same one a value inside the band that IS computed would give -
    so this compares the two."""
    big = 10 ** 6 * (fmt.emax // 3 + 40)
    for sign in ("", "-"):
        for tail in ("e999999999999", "e" + str(big)):
            a, fa = chars.from_decimal(fmt, sign + "1" + tail, rnd)
            b, fb = chars.from_decimal(fmt, sign + "9" + tail, rnd)
            assert (a, fa) == (b, fb)
            assert fa == FLAG_OVERFLOW | FLAG_INEXACT
        for tail in ("e-999999999999", "e-" + str(big)):
            a, fa = chars.from_decimal(fmt, sign + "1" + tail, rnd)
            b, fb = chars.from_decimal(fmt, sign + "9" + tail, rnd)
            assert (a, fa) == (b, fb)
            assert fa == FLAG_UNDERFLOW | FLAG_INEXACT


# ----------------------------------------------------------------------
# 9.7
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ALL)
def test_get_payload(fmt):
    assert chars.get_payload(fmt, qnan_bits(fmt)) == zero_bits(fmt, 0)
    assert chars.get_payload(fmt, snan_bits(fmt, 1)) == one_bits(fmt, 0)
    # 9.7: "If the source operand is not a NaN, the result is -1."
    for bits in (zero_bits(fmt, 0), zero_bits(fmt, 1), one_bits(fmt, 0),
                 inf_bits(fmt, 0), inf_bits(fmt, 1),
                 min_subnormal_bits(fmt, 1), max_normal_bits(fmt, 0)):
        assert chars.get_payload(fmt, bits) == one_bits(fmt, 1)
    # the payload comes back as a non-negative floating-point integer,
    # sign 0, whatever the NaN's own sign was
    for payload in (1, 2, 3, 255, chars.max_payload(fmt) - 1):
        for sign in (0, 1):
            for signaling in (0, 1):
                bits = chars.nan_bits(fmt, sign, payload, signaling)
                got = chars.get_payload(fmt, bits)
                assert got == sf.round_pack(fmt, 0, payload, 0, RND_RNE)[0]


@pytest.mark.parametrize("fmt", ALL)
def test_set_payload_admissibility(fmt):
    top = chars.max_payload(fmt)
    for payload in (0, 1, 2, 255, top - 1):
        src = sf.round_pack(fmt, 0, payload, 0, RND_RNE)[0] if payload \
            else zero_bits(fmt, 0)
        assert chars.set_payload(fmt, src) == chars.nan_bits(fmt, 0,
                                                             payload, 0)
        if payload:
            assert (chars.set_payload_signaling(fmt, src)
                    == chars.nan_bits(fmt, 0, payload, 1))
    # payload 0 is admissible for setPayload and NOT for the signaling
    # form: the encoding it would produce is an infinity
    assert chars.set_payload(fmt, zero_bits(fmt, 0)) == qnan_bits(fmt)
    assert chars.set_payload_signaling(fmt, zero_bits(fmt, 0)) == \
        zero_bits(fmt, 0)
    # -0 is the integer zero BY VALUE, which is how the rest of this
    # contract reads it
    assert chars.set_payload(fmt, zero_bits(fmt, 1)) == qnan_bits(fmt)
    assert chars.set_payload_signaling(fmt, zero_bits(fmt, 1)) == \
        zero_bits(fmt, 0)
    # everything outside the set is +0, per 9.7
    outside = [one_bits(fmt, 1), inf_bits(fmt, 0), inf_bits(fmt, 1),
               qnan_bits(fmt), snan_bits(fmt, 1),
               min_subnormal_bits(fmt, 0), max_normal_bits(fmt, 0),
               sf.round_pack(fmt, 0, top, 0, RND_RNE)[0],
               sf.round_pack(fmt, 0, 3, -1, RND_RNE)[0]]
    for bits in outside:
        assert chars.set_payload(fmt, bits) == zero_bits(fmt, 0), hex(bits)
        assert chars.set_payload_signaling(fmt, bits) == zero_bits(fmt, 0)


@pytest.mark.parametrize("fmt", ALL)
def test_payload_round_trip(fmt):
    """setPayload(getPayload(x)) reproduces a quiet NaN's payload, which
    is the property the pair exists to have. 9.7's own NOTE says the two
    sets need not match; here they do, because the admissible set IS the
    payload field."""
    for payload in (0, 1, 5, chars.max_payload(fmt) - 1):
        for signaling in (0, 1):
            if signaling and payload == 0:
                continue
            bits = chars.nan_bits(fmt, 0, payload, signaling)
            got = chars.set_payload(fmt, chars.get_payload(fmt, bits))
            assert got == chars.nan_bits(fmt, 0, payload, 0)


@pytest.mark.parametrize("fmt", ALL)
def test_payload_operations_signal_nothing(fmt):
    """9.7: "These operations signal no exceptions." There is no flag
    word to return, and the model's signatures say so - this pins the
    shape so a later change has to be deliberate."""
    for op in (chars.get_payload, chars.set_payload,
               chars.set_payload_signaling):
        assert isinstance(op(fmt, snan_bits(fmt, 1)), int)


# ----------------------------------------------------------------------
# The H rule
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ALL)
def test_more_digits_than_the_value_has_pads_with_zeros(fmt):
    """5.12.2: "Conversions from supported binary formats to external
    character sequences for which more than H significant digits are
    specified shall pad with trailing zeros." H is unbounded here, so
    the rule that bites is the simpler one: past the exact digit count
    there is nothing left to write but zeros."""
    bits = one_bits(fmt, 0)
    for h in (1, 2, 5, 40):
        text, flags = chars.to_decimal(fmt, bits, h, RND_RNE)
        assert flags == 0
        digits = text.split("e")[0].replace(".", "")
        assert len(digits) == h and digits == "1" + "0" * (h - 1)


@pytest.mark.parametrize("fmt", ALL)
@pytest.mark.parametrize("rnd", RND_MODES)
def test_h_digits_is_the_rounding_of_the_exact_digits(fmt, rnd):
    """Correct rounding to H digits, checked against the exact
    expansion by an independent rational comparison: the H-digit answer
    must be one of the two H-digit decimals bracketing the value, and
    the attribute says which."""
    for bits in pool(fmt)[:60]:
        kind, sign, m, e, _, _ = chars._decode(fmt, bits)
        if kind != "finite":
            continue
        v = Fraction((-1) ** sign * m) * Fraction(2) ** e
        for h in (1, 3, chars.pmin(fmt)):
            text, flags = chars.to_decimal(fmt, bits, h, rnd)
            got = seq_value(text)
            exp10 = int(text.split("e")[1])
            ulp = Fraction(10) ** (exp10 - h + 1)
            assert abs(got - v) <= ulp, (fmt.name, hex(bits), h, rnd)
            assert (got == v) == (flags == 0)
            if rnd == RND_RTZ:
                assert abs(got) <= abs(v)
            elif rnd == RND_RDN:
                assert got <= v
            elif rnd == RND_RUP:
                assert got >= v
            else:
                assert abs(got - v) <= ulp / 2
