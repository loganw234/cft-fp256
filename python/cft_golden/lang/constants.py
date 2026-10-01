# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Exact constants, and the one rounding each of them gets.

A constant in the language is a rational, held as a Fraction from the
moment its literal is read - a decimal is D x 10^k exactly, a
hexadecimal significand m x 2^e exactly - and every operation between
constants is exact. It is rounded ONCE, under the program's attribute,
where it meets a run-time operation or the bank, through
chars._round_rational: one integer division and one
softfloat.round_pack, the library's single rounding authority. Never
through binary64, and never twice: h/6 is RN(1/600), not RN(RN(1/100)/6)
(docs/LANGUAGE.md, "Constants").

Also here: the canonical spellings of an exact value, which the
canonical form writes and the parser reads back to the same value, and
a decimal rendering of a relative error made with integers only, so
that the intention-out is the same text on every machine.
"""

from fractions import Fraction

from .. import chars
from .. import softfloat as sf

# A constant's exact value must lie within 2^+-LIMIT_LOG2 to be held at
# all. The widest format, binary256, runs from 2^-262378 to below
# 2^262144, so a value past this bound overflows or rounds to zero in
# every format; refusing it before it is materialised keeps a source
# like 1e99999999 from becoming a multi-gigabyte integer.
LIMIT_LOG2 = 1 << 20

RND_BY_NAME = {name: code for code, name in sf.RND_NAMES.items()}
RND_754 = {
    sf.RND_RNE: "roundTiesToEven",
    sf.RND_RTZ: "roundTowardZero",
    sf.RND_RDN: "roundTowardNegative",
    sf.RND_RUP: "roundTowardPositive",
    sf.RND_RMM: "roundTiesToAway",
}
FORMAT_754 = {"fp32": "binary32", "fp64": "binary64", "fp128": "binary128",
              "fp256": "binary256"}


def log2_bounds(value):
    """(lo, hi) with lo <= log2|value| < hi, for a nonzero Fraction,
    from bit lengths alone."""
    n, d = abs(value.numerator), value.denominator
    return n.bit_length() - d.bit_length() - 1, \
        n.bit_length() - d.bit_length() + 1


def in_range(value):
    """True when the exact value may be held (zero always may)."""
    if value == 0:
        return True
    lo, hi = log2_bounds(value)
    return -LIMIT_LOG2 <= lo and hi <= LIMIT_LOG2


def round_once(fmt, rnd, value):
    """(bits, flags) of the exact rational `value` rounded once into
    `fmt` under `rnd`. Zero is +0: the rational has no sign of zero."""
    if value == 0:
        return sf.zero_bits(fmt, 0), 0
    sign = 1 if value < 0 else 0
    v = -value if sign else value
    return chars._round_rational(fmt, sign, v.numerator, v.denominator, rnd)


def overflowed(flags):
    return bool(flags & sf.FLAG_OVERFLOW)


def rounded_to_zero(fmt, value, bits):
    return value != 0 and (bits & ~fmt.sign_mask) == 0


def value_of(fmt, bits):
    """The exact value of a finite encoding, as a Fraction."""
    u = sf.unpack(fmt, bits)
    if u.kind in (sf.INF, sf.NAN):
        raise ValueError("not a finite encoding")
    if u.kind == sf.ZERO:
        return Fraction(0)
    m = Fraction(u.m) * (Fraction(2) ** u.e)
    return -m if u.sign else m


def relative_error(fmt, bits, value):
    """(rounded - exact) / exact, exactly; 0 for an exact zero."""
    if value == 0:
        return Fraction(0)
    return (value_of(fmt, bits) - value) / value


def sig(q, n=5):
    """An exact rational as n significant decimal digits, rounded half
    to even, in the form +d.dddde-xx - integers only, no binary64."""
    if q == 0:
        return "0"
    sign = "-" if q < 0 else "+"
    q = abs(Fraction(q))
    # the decimal exponent of the leading digit, from bit lengths, then
    # corrected by at most a step either way
    e = (q.numerator.bit_length() - q.denominator.bit_length()) * 30103 \
        // 100000
    while q >= Fraction(10) ** (e + 1):
        e += 1
    while q < Fraction(10) ** e:
        e -= 1
    scaled = q * Fraction(10) ** (n - 1 - e)
    i = scaled.numerator // scaled.denominator
    r = scaled - i
    if r > Fraction(1, 2) or (r == Fraction(1, 2) and i % 2):
        i += 1
    if i == 10 ** n:
        i //= 10
        e += 1
    d = str(i)
    return f"{sign}{d[0]}.{d[1:]}e{e:+03d}"


# ---- canonical spellings ----------------------------------------------

def _pow_2_5(d):
    """(a, b) with d = 2^a 5^b, or None."""
    a = b = 0
    while d % 2 == 0:
        d //= 2
        a += 1
    while d % 5 == 0:
        d //= 5
        b += 1
    return (a, b) if d == 1 else None


def _decimal(value):
    """The terminating decimal of `value` (whose denominator is
    2^a 5^b) as (sign, digits, exp10): value = sign digits x 10^exp10,
    digits without trailing zeros."""
    a, b = _pow_2_5(value.denominator)
    k = max(a, b)
    n = abs(value.numerator) * 10 ** k // value.denominator
    e = -k
    while n and n % 10 == 0:
        n //= 10
        e += 1
    return ("-" if value < 0 else ""), str(n), e


def _hex(value):
    """A dyadic rational as a hexadecimal significand, exactly - the
    shape chars.to_hex writes for an encoding."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    m, d = v.numerator, v.denominator
    e = -(d.bit_length() - 1)
    lead = m.bit_length() - 1
    exp = e + lead
    frac = m - (1 << lead)
    nib = (lead + 3) // 4
    text = ""
    if nib:
        frac <<= 4 * nib - lead
        text = ("%0*x" % (nib, frac)).rstrip("0")
    return "%s0x1%sp%s%d" % (sign, "." + text if text else "",
                             "+" if exp >= 0 else "-", abs(exp))


MAX_DECIMAL_DIGITS = 24


def literal(value):
    """The canonical spelling of an exact value, which the parser reads
    back to the same rational: an integer; a decimal when it terminates
    within MAX_DECIMAL_DIGITS significant digits (positional for a
    leading digit between 10^-6 and 10^20, else with an exponent); a
    hexadecimal significand when it is dyadic and longer; else p/q."""
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    if _pow_2_5(value.denominator) is not None:
        sign, digits, e = _decimal(value)
        if len(digits) <= MAX_DECIMAL_DIGITS:
            lead = e + len(digits) - 1
            if -6 <= lead <= 20:
                if e >= 0:
                    return sign + digits + "0" * e
                point = len(digits) + e
                if point > 0:
                    return sign + digits[:point] + "." + digits[point:]
                return sign + "0." + "0" * (-point) + digits
            body = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
            return f"{sign}{body}e{lead}"
        if value.denominator & (value.denominator - 1) == 0:
            return _hex(value)
    return f"{value.numerator}/{value.denominator}"


def math_literal(value):
    """The mathematical form's spelling: an integer, a terminating
    decimal within MAX_DECIMAL_DIGITS digits, or p/q - never a
    hexadecimal significand, which is not conventional notation."""
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    if _pow_2_5(value.denominator) is not None:
        sign, digits, e = _decimal(value)
        if len(digits) <= MAX_DECIMAL_DIGITS:
            return literal(value)
    return f"{value.numerator}/{value.denominator}"


def h_form(factor):
    """An h-scaled constant's spelling from its factor: h, h/q, p*h or
    p*h/q, with the sign in front. Read back it is that factor times h
    exactly - the parser's unary minus binds tighter than * and /."""
    f = Fraction(factor)
    if f == 1:
        return "h"
    if f == -1:
        return "-h"
    p, q = f.numerator, f.denominator
    if q == 1:
        return f"{p}*h"
    if p == 1:
        return f"h/{q}"
    if p == -1:
        return f"-h/{q}"
    return f"{p}*h/{q}"


def is_compound(text):
    """True when a constant's spelling is not one token (it has a sign,
    a division or a product), so that as an operand of a binary
    operator it is written in parentheses."""
    if text.startswith("-"):
        return True
    if text.startswith("0x"):
        return False
    return "/" in text or "*" in text


def bits_hex(fmt, bits):
    return "0x" + format(bits, f"0{fmt.width // 4}x")


def describe(fmt, rnd, value, bits, flags):
    """`exact`, or `inexact[, underflow], relative error +x.xxxxe-yy`."""
    if not flags:
        return "exact"
    words = []
    if flags & sf.FLAG_INEXACT:
        words.append("inexact")
    if flags & sf.FLAG_UNDERFLOW:
        words.append("underflow")
    text = ", ".join(words)
    rel = relative_error(fmt, bits, value)
    return f"{text}, relative error {sig(rel)}"
