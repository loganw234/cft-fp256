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


def exact(value):
    """The value as a Fraction, refusing a float: no binary64 may reach
    a constant (a Python float is binary64 already, and Fraction would
    take one silently)."""
    if isinstance(value, float):
        raise AssertionError(f"a float ({value!r}) reached the constant "
                             f"code, which is exact rationals only")
    return value if isinstance(value, Fraction) else Fraction(value)


def round_once(fmt, rnd, value):
    """(bits, flags) of the exact rational `value` rounded once into
    `fmt` under `rnd`. Zero is +0: the rational has no sign of zero."""
    value = exact(value)
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

# log2(5) = 2.32192809488736234787..., and log10(2) = 0.30102999566398119...
# as integer ratios, each within 10^-15 of the true value: enough to
# place a power of 5 or of 10 within one at any size a constant may have
# (2^+-LIMIT_LOG2), where the error they leave is below 10^-9.
_LOG2_5 = (23219280948873623, 10 ** 16)
_LOG10_2 = (30102999566398, 10 ** 14)          # below log10(2)


def _pow_2_5(d):
    """(a, b) with d = 2^a 5^b, or None - in a few big-integer
    operations at any size. Dividing out one factor at a time was
    quadratic in the exponent: 1e-78900 took a minute to write out
    (verifier-VL1)."""
    a = (d & -d).bit_length() - 1
    odd = d >> a
    if odd == 1:
        return a, 0
    if odd % 5:
        return None
    # 5^b has floor(b log2 5) + 1 bits, so odd's bit length fixes b to
    # one of two neighbours
    b = (odd.bit_length() - 1) * _LOG2_5[1] // _LOG2_5[0]
    lo = max(b - 1, 1)
    p = 5 ** lo
    for cand in range(lo, b + 3):
        if p == odd:
            return a, cand
        if p > odd:
            return None
        p *= 5
    return None


def digits(n):
    """A non-negative integer's decimal digits, at any length: Python's
    own str() stops at 4,300 digits, and a constant may have more."""
    return chars._digits_from_int(n)


def _decimal(value):
    """The terminating decimal of `value` (whose denominator is
    2^a 5^b) as (sign, digits, exp10): value = sign digits x 10^exp10,
    digits without trailing zeros - or None when it has more than
    MAX_DECIMAL_DIGITS significant digits, which is found without
    writing it out: the digits are written only when there are few."""
    a, b = _pow_2_5(value.denominator)
    k = max(a, b)
    n = abs(value.numerator) << (k - a)
    n *= 5 ** (k - b)                              # |value| x 10^k
    # with at most MAX_DECIMAL_DIGITS significant digits, n ends in at
    # least t0 zeros: n has more than (L - 1) log10 2 digits
    t0 = max(0, (n.bit_length() - 1) * _LOG10_2[0] // _LOG10_2[1]
             - MAX_DECIMAL_DIGITS)
    if t0:
        n, r = divmod(n, 10 ** t0)
        if r:
            return None
    text = digits(n)
    stripped = text.rstrip("0") or "0"
    if len(stripped) > MAX_DECIMAL_DIGITS:
        return None
    e = -k + t0 + (len(text) - len(stripped))
    return ("-" if value < 0 else ""), stripped, e


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


def _short_decimal(value):
    """The decimal spelling of a terminating value with at most
    MAX_DECIMAL_DIGITS significant digits - positional for a leading
    digit between 10^-6 and 10^20, else with an exponent - or None."""
    if _pow_2_5(value.denominator) is None:
        return None
    parts = _decimal(value)
    if parts is None:
        return None
    sign, ds, e = parts
    lead = e + len(ds) - 1
    if -6 <= lead <= 20:
        if e >= 0:
            return sign + ds + "0" * e
        point = len(ds) + e
        if point > 0:
            return sign + ds[:point] + "." + ds[point:]
        return sign + "0." + "0" * (-point) + ds
    body = ds[0] + ("." + ds[1:] if len(ds) > 1 else "")
    return f"{sign}{body}e{lead}"


def _fraction_text(value):
    sign = "-" if value < 0 else ""
    num = digits(abs(value.numerator))
    if value.denominator == 1:
        return sign + num
    return f"{sign}{num}/{digits(value.denominator)}"


def literal(value):
    """The canonical spelling of an exact value, which the parser reads
    back to the same rational, at any size: a decimal (an integer among
    them) when it terminates within MAX_DECIMAL_DIGITS significant
    digits, positional or with an exponent; a hexadecimal significand
    when it is dyadic and longer; else p, or p/q, in full."""
    value = exact(value)
    short = _short_decimal(value)
    if short is not None:
        return short
    d = value.denominator
    if d != 1 and d & (d - 1) == 0:
        return _hex(value)                     # dyadic, and long
    return _fraction_text(value)


def math_literal(value):
    """The mathematical form's spelling: a decimal within
    MAX_DECIMAL_DIGITS significant digits, else p or p/q in full -
    never a hexadecimal significand, which is not conventional
    notation."""
    value = exact(value)
    short = _short_decimal(value)
    return short if short is not None else _fraction_text(value)


def frac_text(value):
    """An exact value as the step graph writes it: p or p/q, at any
    size."""
    return _fraction_text(exact(value))


def parse_frac(text):
    """frac_text read back, at any size (Fraction's own parser stops at
    Python's 4,300-digit limit)."""
    if not isinstance(text, str) or not text:
        raise ValueError(f"{text!r} is not an exact value")
    sign = -1 if text.startswith("-") else 1
    body = text[1:] if sign < 0 else text
    num, slash, den = body.partition("/")
    if not num.isdigit() or (slash and not den.isdigit()) or \
            (slash and den.startswith("0")) or \
            (len(num) > 1 and num.startswith("0")):
        raise ValueError(f"{text!r} is not p or p/q")
    n = chars._int_from_digits(num)
    q = chars._int_from_digits(den) if slash else 1
    value = Fraction(sign * n, q)
    if frac_text(value) != text:
        raise ValueError(f"{text!r} is not in lowest terms")
    return value


def brief(value):
    """A constant as a refusal's sentence names it: its canonical
    spelling when that is at most forty characters (-1e5000), else its
    value to five significant digits - a sentence is not the place for
    a value of five thousand digits. Cheap at any size: a p/q is
    written out only when it is short."""
    value = exact(value)
    if value == 0:
        return "0"
    text = _short_decimal(value)
    if text is None:
        d = value.denominator
        if d != 1 and d & (d - 1) == 0:
            text = _hex(value)
        elif abs(value.numerator).bit_length() + d.bit_length() <= 140:
            text = _fraction_text(value)     # past 140 bits, over 40 digits
    if text is not None and len(text) <= 40:
        return text
    return f"{five_digits(value)} (to five digits)"


def five_digits(value):
    """A nonzero value to five significant digits, rounded half to even,
    as -1.0000e+5000 - from bit lengths and a few big-integer operations,
    at any size. (sig() is the same for the small numbers it prints.)"""
    sign = "-" if value < 0 else ""
    n, d = abs(value.numerator), value.denominator
    # e0 at or below floor(log10 |value|): |value| > 2^(bits n - bits d - 1)
    e0 = ((n.bit_length() - d.bit_length() - 1) * _LOG10_2[0]
          // _LOG10_2[1] - 1)
    if e0 <= 4:
        num, den = n * 10 ** (4 - e0), d
    else:
        num, den = n, d * 10 ** (e0 - 4)
    # num / den = |value| / 10^(e0 - 4) holds 5 to 8 digits before the
    # point; keep five, and round the rest once
    shift = len(str(num // den)) - 5
    den *= 10 ** shift
    q, r = divmod(num, den)
    if 2 * r > den or (2 * r == den and q % 2):
        q += 1
    e = e0 + shift
    if q == 10 ** 5:
        q, e = 10 ** 4, e + 1
    s = str(q)
    return f"{sign}{s[0]}.{s[1:]}e{e:+d}"


def h_form(factor):
    """An h-scaled constant's spelling from its factor: h, h/q, p*h or
    p*h/q, with the sign in front. Read back it is that factor times h
    exactly - the parser's unary minus binds tighter than * and /."""
    f = exact(factor)
    if f == 1:
        return "h"
    if f == -1:
        return "-h"
    sign = "-" if f < 0 else ""
    p, q = digits(abs(f.numerator)), digits(f.denominator)
    if f.denominator == 1:
        return f"{sign}{p}*h"
    if abs(f.numerator) == 1:
        return f"{sign}h/{q}"
    return f"{sign}{p}*h/{q}"


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
