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
from math import isqrt

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


def rational_sqrt(value):
    """The exact square root of a rational that is a rational's square, or
    None: a negative value, or one whose root is irrational (2). A Fraction
    is in lowest terms, so p/q is a rational's square exactly when p and q
    are both squares - two integer square roots, at any size (L4: sqrt of
    a constant folds when exact, docs/LANGUAGE.md, "Constants")."""
    value = exact(value)
    if value < 0:
        return None
    n, d = value.numerator, value.denominator
    rn, rd = isqrt(n), isqrt(d)
    if rn * rn != n or rd * rd != d:
        return None
    return Fraction(rn, rd)


def round_once(fmt, rnd, value):
    """(bits, flags) of the exact rational `value` rounded once into
    `fmt` under `rnd`. Zero is +0: the rational has no sign of zero."""
    value = exact(value)
    if value == 0:
        return sf.zero_bits(fmt, 0), 0
    sign = 1 if value < 0 else 0
    v = -value if sign else value
    return chars._round_rational(fmt, sign, v.numerator, v.denominator, rnd)


# ---- ln 2, rounded once: the tangent rules' L --------------------------------

_LN2 = {}


def ln2_bits(fmt, rnd):
    """The encoding of ln 2 correctly rounded once into `fmt` under `rnd`:
    the L of exp2's and log2's tangent rules (docs/LANGUAGE.md, "The
    rules"; M1's study, question 6, decided by Logan on 2026-10-12: "the
    exact ln 2, rounded once at the program's format under its attribute
    (transcend.log of 2)", no new name). It IS transcend.log of 2 - the
    gate holds the two equal at every format and attribute - and is
    computed here by integers alone, so that checking a source never needs
    mpmath (only lang.run of a graph holding one of the eighteen does):
    ln 2 = sum over k >= 1 of 1/(k 2^k), each of the first K terms
    truncated to a multiple of 2^-N, so that 2^N ln 2 lies in
    [S, S + K + 1] (each term loses less than 1, the tail past K = N less
    than 1). Both ends rounded alike decide the rounding; ln 2 is
    irrational, so a wider N always comes to decide it."""
    key = (fmt.name, rnd)
    if key not in _LN2:
        n = fmt.prec + 64
        while True:
            s = sum((1 << n) // (k << k) for k in range(1, n + 1))
            lo = sf.round_pack(fmt, 0, s, -n, rnd)[0]
            hi = sf.round_pack(fmt, 0, s + n + 1, -n, rnd)[0]
            if lo == hi:
                break
            n *= 2
        _LN2[key] = lo
    return _LN2[key]


def ln2_value(fmt, rnd):
    """L's exact value: ln 2 rounded once, as the rational its encoding is
    - a constant like any other, which the canonical form writes as it
    writes any constant (a hexadecimal significand at fp64, fp128 and
    fp256, a decimal at fp32, where it terminates within 24 significant
    digits) and reads back, rounded again to itself."""
    return value_of(fmt, ln2_bits(fmt, rnd))


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


def shown(x, group=False):
    """Any value as a refusal's sentence names it, at any size. An int of
    at most 128 bits as itself (grouped by thousands when `group`); a
    Fraction of at most 128 bits a side as its repr, as the sentences
    always wrote it; a longer int or Fraction through brief(), since
    Python's own str() stops at 4,300 digits (verifier-VI found the
    index-range, run-input and segment-steps sentences raising there);
    anything else as its repr."""
    if isinstance(x, bool) or not isinstance(x, (int, Fraction)):
        return repr(x)
    if isinstance(x, int) and x.bit_length() <= 128:
        return f"{x:,}" if group else repr(x)
    if isinstance(x, Fraction) and x.numerator.bit_length() <= 128 \
            and x.denominator.bit_length() <= 128:
        return repr(x)
    return brief(x)


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


# ---- pow, powr, pown, rootn and compound of constants (M3's build) --------
#
# A power of an exact rational is exact where it is a rational and only
# there; power_fold is the one function the checker's folds (check.py) and
# the exact evaluation of a graph (graph.py, exact_transcendental) both
# take, so that a constant fold and a node run at the same point cannot
# differ. Its operands are exact Fractions, n of pown, rootn and compound an
# integer.

# The most bits a held power's numerator or denominator may need, beyond
# which the power is refused rather than computed: |m| * the larger bit
# length of the base's numerator and denominator, for a base other than 1
# and -1. A constant within 2^+-LIMIT_LOG2 needs about LIMIT_LOG2 bits at
# most where its base is an integer, so four times that bounds every power
# such a base can give; a base within 2^-k of 1 raised to a large m is
# the case it also refuses, though its value is small (bounded, not
# computed).
POWER_BITS = 1 << 22

POWER_OPS = ("pow", "powr", "pown", "rootn", "compound")

# the three whose second operand is the integer n
INT_POWER_OPS = ("pown", "rootn", "compound")


def iroot_exact(n, k):
    """The integer whose k-th power is the positive integer n, or None: an
    exact root, by Newton's method on integers (never a float). k >= 1."""
    if n == 1 or k == 1:
        return n
    bits = n.bit_length()
    if k >= bits:
        return None         # n >= 2 and n < 2^k: its root lies in (1, 2)
    x = 1 << (bits // k + 1)
    while True:
        y = ((k - 1) * x + n // x ** (k - 1)) // k
        if y >= x:
            break
        x = y
    return x if x ** k == n else None


def rational_root(value, k):
    """The exact k-th root of the positive rational `value` where its
    numerator and denominator are both perfect k-th powers (a Fraction is
    in lowest terms, so that is where the root is rational), else None."""
    value = exact(value)
    rn = iroot_exact(value.numerator, k)
    if rn is None:
        return None
    rd = iroot_exact(value.denominator, k)
    if rd is None:
        return None
    return Fraction(rn, rd)


def _int_power(b, m, shown):
    """b^m for a nonzero rational b and an integer m, as power_fold's
    answer: ("value", it), or ("range", sentence) past 2^+-LIMIT_LOG2 or
    needing more than POWER_BITS bits."""
    if b == 1 or m == 0:
        return "value", Fraction(1)
    if b == -1:
        return "value", Fraction(-1 if m % 2 else 1)
    size = max(abs(b.numerator).bit_length(), b.denominator.bit_length())
    if abs(m) * size > POWER_BITS:
        return "range", (f"{shown} needs more than {POWER_BITS} bits to hold "
                         f"exactly, or lies beyond 2^+-{LIMIT_LOG2}, outside "
                         f"every format by far")
    v = b ** m
    if not in_range(v):
        return "range", (f"{shown} lies beyond 2^+-{LIMIT_LOG2}, outside "
                         f"every format by far")
    return "value", v


def power_fold(op, c, d):
    """pow(c, d), powr(c, d), pown(c, d), rootn(c, d) or compound(c, d) of
    exact rationals (d an integer for the last three) as (kind, what):

      ("value", F)         the exact rational value;
      ("unreal", text)     no real number: a negative base and a non-integer
                           power, powr below 0 and powr(0, 0), rootn of
                           order 0 and of a negative with an even order,
                           compound below -1;
      ("pole", text)       a division by zero: 0 to a negative power,
                           compound(-1, n < 0), rootn(0, n < 0);
      ("range", text)      the value is past 2^+-LIMIT_LOG2 (or needs more
                           than POWER_BITS bits);
      ("irrational", text) a value no rational carries (pow(2, 1/2),
                           rootn(2, 2))

    pow(0, 0) is 1, pown(c, 0) is 1 for every c, and compound(c, 0) is 1 at
    c >= -1, as transcend.py's functions have them (IEEE 754-2019 9.2)."""
    c, d = exact(c), exact(d)
    shown = f"{op}({brief(c)}, {brief(d)})"
    if op in ("pow", "powr"):
        if op == "powr" and c < 0:
            return "unreal", (f"{shown} is not a real number: powr of a "
                              f"negative base is invalid")
        if c == 0:
            if d > 0:
                return "value", Fraction(0)
            if d == 0:
                if op == "powr":
                    return "unreal", (f"{shown} is not a real number: "
                                      f"powr(0, 0) is invalid")
                return "value", Fraction(1)
            return "pole", f"{shown} is a pole: 0 to a negative power"
        if d == 0 or c == 1:
            return "value", Fraction(1)
        if d.denominator == 1:
            return _int_power(c, d.numerator, shown)
        if c < 0:
            return "unreal", (f"{shown} is not a real number: a negative "
                              f"base to a power that is not an integer has "
                              f"no value")
        root = rational_root(c, d.denominator)
        if root is None:
            return "irrational", (f"{shown} is irrational: the base is no "
                                  f"rational's s-th power for s = {d.denominator} (a "
                                  f"rational c^(r/s), r/s in lowest terms, "
                                  f"makes c a rational's s-th power)")
        return _int_power(root, d.numerator, shown)
    assert d.denominator == 1, (op, d)
    n = d.numerator
    shown = f"{op}({brief(c)}, {n})"
    if op == "pown":
        if c == 0:
            if n < 0:
                return "pole", f"{shown} is a pole: 0 to a negative power"
            return "value", Fraction(1 if n == 0 else 0)
        return _int_power(c, n, shown)
    if op == "compound":
        b = 1 + c
        if b < 0:
            return "unreal", (f"{shown} is not a real number: compound of "
                              f"a constant below -1 is invalid")
        if b == 0:
            if n < 0:
                return "pole", f"{shown} is a pole: (1 + c)^n at c = -1"
            return "value", Fraction(1 if n == 0 else 0)
        return _int_power(b, n, shown)
    assert op == "rootn", op
    if n == 0:
        return "unreal", (f"{shown} is not a real number: rootn of order 0 "
                          f"has no value")
    if c == 0:
        if n < 0:
            return "pole", f"{shown} is a pole: the root of 0 of a negative order"
        return "value", Fraction(0)
    if c < 0 and n % 2 == 0:
        return "unreal", (f"{shown} is not a real number: an even root of a "
                          f"negative base has no value")
    root = rational_root(abs(c), abs(n))
    if root is None:
        return "irrational", (f"{shown} is irrational: the base is no "
                              f"rational's k-th power for k = {abs(n)}")
    if c < 0:
        root = -root
    if n < 0:
        root = 1 / root
    if not in_range(root):
        return "range", (f"{shown} lies beyond 2^+-{LIMIT_LOG2}, outside "
                         f"every format by far")
    return "value", root
