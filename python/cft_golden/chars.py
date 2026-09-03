# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""IEEE 754-2019 clause 5.12 character sequences, and clause 9.7 payloads.

The definition of correct for host/src/chars.c, exactly as
softfloat.py is for softfloat.c. Everything here is exact integer
arithmetic on Python's unbounded ints - no float, no Decimal, no
locale, no printf - and every rounding goes through
softfloat.round_pack, which is the library's single rounding
authority.

WHAT 5.12 ASKS FOR, AND WHAT THIS DELIVERS

  5.12.2  conversions between every supported binary format and
          external DECIMAL character sequences, correctly rounded in
          both directions with correct exceptions. The standard lets
          an implementation cap the digit count it will round
          correctly at some H >= M + 3, and says H "should be
          unbounded". Here it IS unbounded, in both directions: the
          value of a decimal sequence is a rational and the value of
          an encoding is a dyadic rational, both held exactly, so
          there is no digit count at which this stops being correctly
          rounded and nothing here ever pads or truncates to reach an
          answer.
  5.12.3  conversions to and from hexadecimal-significand sequences,
          exact on the way out and correctly rounded on the way in.
  5.12.1  the spellings of zeros, infinities and NaNs, including the
          payload suffix the standard asks language standards to
          provide ("There should be means to read and write payloads
          from and to external character sequences", 6.2.3).

THE EXACTNESS ARGUMENT, IN ONE PARAGRAPH

  A decimal sequence denotes (-1)^s * D * 10^K exactly, with D a
  natural number and K an integer - a RATIONAL. Write it as num/den
  (den = 1 or 10^-K). The binary window is ONE integer division: with
  q chosen from the bit lengths of num and den, m = floor(num /
  (den * 2^q)) has p+3 or p+4 bits and the remainder says whether
  anything is left below it. The value is then exactly (m + eps) * 2^q
  with eps in [0, 1), non-zero exactly when the remainder is - which
  is round_pack's own precondition, so one round_pack call delivers
  the value and every flag. No approximation enters at any point, at
  any length.

THE CANONICAL-NaN POLICY DOES NOT APPLY HERE

  docs/DETERMINISM.md's rule - any NaN in, one canonical quiet NaN out
  - governs ARITHMETIC, where "which operand's payload survives" is
  where implementations diverge. The operations in this file are
  ENCODING operations, like abs/negate/copySign/select and the three
  9.7 payload operations below: they carry the payload and the
  signaling bit through unchanged in both directions, because 5.12's
  own requirement is that the round trip "recovers the original
  floating-point representation".
"""

import sys

from .formats import FpFormat
from . import softfloat as sf


class CharacterSyntaxError(ValueError):
    """A sequence that is not in the syntax this module accepts.

    A refusal, never a guess: the C library answers the same case with
    CFT_ERR_INVALID_ARGUMENT and writes nothing to the destination.
    """


# CPython 3.11 caps int <-> str conversion in base 10 at 4300 digits by
# default, which is a denial-of-service guard against quadratic
# conversions and not a statement about arithmetic. The exact decimal
# of the smallest binary256 subnormal runs to about 183,000 digits, so
# the guard has to be lifted for the length of the conversion and put
# back. Lifting it globally at import would change interpreter state
# for whatever else is running.

def _int_from_digits(text: str) -> int:
    try:
        return int(text or "0", 10)
    except ValueError:
        old = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(0)
        try:
            return int(text or "0", 10)
        finally:
            sys.set_int_max_str_digits(old)


def _digits_from_int(n: int) -> str:
    try:
        return str(n)
    except ValueError:
        old = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(0)
        try:
            return str(n)
        finally:
            sys.set_int_max_str_digits(old)


# ----------------------------------------------------------------------
# Pmin - the digit count at which the round trip is guaranteed
# ----------------------------------------------------------------------

def pmin(fmt: FpFormat) -> int:
    """5.12.2's Pmin(bf) = 1 + ceiling(p * log10(2)).

    DERIVED, not tabulated: ceiling(p * log10(2)) is the smallest k
    with 10^k >= 2^p, which is an exact integer question. The standard
    lists 9, 17 and 36 for binary32/64/128 and this reproduces all
    three; binary256 comes out at 73.
    """
    k = 0
    while 10 ** k < 1 << fmt.prec:
        k += 1
    return 1 + k


# ----------------------------------------------------------------------
# The encoding, decomposed and rebuilt. Pure field work.
# ----------------------------------------------------------------------

def _decode(fmt: FpFormat, bits: int):
    """-> (kind, sign, m, e, payload, signaling).

    kind is "zero", "finite", "inf" or "nan"; for "finite" the value is
    (-1)^sign * m * 2^e with m > 0."""
    sign = (bits >> (fmt.width - 1)) & 1
    biased = (bits >> fmt.man_w) & fmt.exp_mask
    frac = bits & fmt.man_mask
    if biased == fmt.exp_mask:
        if frac == 0:
            return "inf", sign, 0, 0, 0, 0
        quiet = (frac >> (fmt.man_w - 1)) & 1
        return ("nan", sign, 0, 0, frac & (max_payload(fmt) - 1),
                0 if quiet else 1)
    if biased == 0:
        if frac == 0:
            return "zero", sign, 0, 0, 0, 0
        return "finite", sign, frac, fmt.emin - fmt.man_w, 0, 0
    return ("finite", sign, frac | (1 << fmt.man_w),
            biased - fmt.bias - fmt.man_w, 0, 0)


def max_payload(fmt: FpFormat) -> int:
    """One past the largest admissible payload.

    6.2.1 puts the payload in bits d2..d(p-1) of the trailing
    significand - everything below the quiet bit - so the admissible
    set is 0 .. 2^(man_w - 1) - 1."""
    return 1 << (fmt.man_w - 1)


def nan_bits(fmt: FpFormat, sign: int, payload: int, signaling: int) -> int:
    """A NaN encoding carrying `payload` in d2..d(p-1) (6.2.1).

    payload must be admissible, and non-zero for a signaling NaN: a
    zero trailing significand with the quiet bit clear is an INFINITY
    encoding and not a NaN at all."""
    assert 0 <= payload < max_payload(fmt)
    assert signaling == 0 or payload != 0
    bits = (sign << (fmt.width - 1)) | (fmt.exp_mask << fmt.man_w) | payload
    if not signaling:
        bits |= max_payload(fmt)
    return bits


# ----------------------------------------------------------------------
# Rounding an exact rational into the format, through round_pack
# ----------------------------------------------------------------------

# The window: p + 3 bits of the value plus a sticky. p + 2 would do -
# round_pack needs strictly more than p bits whenever a sticky rides
# along - and the third bit is margin that costs nothing.
_WINDOW = 3


def _round_rational(fmt: FpFormat, sign: int, num: int, den: int, rnd: int):
    """Round the exact non-zero value (-1)^sign * num/den into the
    format under `rnd`. Returns (bits, flags). num, den > 0.

    One integer division and one round_pack; the module docstring is
    why that is exact.
    """
    assert num > 0 and den > 0
    w = fmt.prec + _WINDOW

    # floor(log2(num/den)) is one of (bn-bd-1, bn-bd), because
    # 2^(bn-bd-1) < num/den < 2^(bn-bd+1). Either way m lands with w or
    # w+1 bits, which is more than p - round_pack's precondition for
    # accepting a sticky.
    q = (num.bit_length() - den.bit_length()) - w
    if q >= 0:
        m, rem = divmod(num, den << q)
    else:
        m, rem = divmod(num << -q, den)
    assert m.bit_length() >= w

    if rem:
        # (m + eps) * 2^q with 0 < eps < 1 rounds exactly as
        # (2m + 1) * 2^(q-1) does. The rounding position is at least
        # q + 2 (m carries at least p + 2 bits), so no rounding
        # boundary lies strictly inside (m*2^q, (m+1)*2^q) and the
        # decision is constant across that whole interval. This is the
        # same reduction host/src/chars.c makes by handing round_pack
        # its sticky argument directly.
        return sf.round_pack(fmt, sign, 2 * m + 1, q - 1, rnd)
    return sf.round_pack(fmt, sign, m, q, rnd)


# Clamping. A sequence's exponent is a caller-supplied integer and can
# be astronomically large; materialising 10^K for it would be a denial
# of service rather than a conversion. Two bands can be answered
# without doing the work, and answering them is not an approximation:
#
#   * a value whose leading bit sits at emax + 1 or above overflows in
#     every attribute, and round_pack's overflow delivery and flags
#     depend on nothing but the attribute and the sign;
#   * a value strictly below half the smallest subnormal - leading bit
#     at emin - man_w - 2 or below - rounds to zero or to the smallest
#     subnormal by attribute and sign alone, inexact and underflow
#     raised either way.
#
# So each band is replaced by ONE representative inside it and the
# answer is identical by construction. log2(10) is bracketed by exact
# rational bounds, so the band test itself uses no floating point.
_L10_LO = 3321928        # 10^-6 * a lower bound on log2(10)
_L10_HI = 3321929        # ... and an upper bound
_L10_DEN = 1000000


def _log2_10_bounds(t: int):
    """(lo, hi) with lo <= t * log2(10) <= hi, exact integers."""
    if t >= 0:
        return (t * _L10_LO) // _L10_DEN, -((-t * _L10_HI) // _L10_DEN)
    return (t * _L10_HI) // _L10_DEN, -((-t * _L10_LO) // _L10_DEN)


def _clamped_round(fmt: FpFormat, sign: int, e_lo: int, e_hi: int, rnd: int):
    """The band answer for a non-zero value whose leading-bit position
    is known to lie in [e_lo, e_hi], or None when the bands do not
    decide it."""
    w = fmt.prec + _WINDOW
    if e_lo > fmt.emax + 1:
        return sf.round_pack(fmt, sign, (1 << w) + 1,
                             fmt.emax + 1 - w, rnd)
    if e_hi <= fmt.emin - fmt.man_w - 2:
        return sf.round_pack(fmt, sign, (1 << w) + 1,
                             fmt.emin - fmt.man_w - 2 - w, rnd)
    return None


def _round_decimal(fmt: FpFormat, sign: int, digits: int, k: int, rnd: int):
    """Round (-1)^sign * digits * 10^k, digits > 0, into the format."""
    # floor(log2(digits)) is in [b-1, b), and k*log2(10) is bracketed
    # exactly, so the leading bit lands in [b-2+lo, b+hi]. Bounds
    # rather than a value, because computing the value is the thing
    # the bands exist to avoid.
    b = digits.bit_length()
    lo, hi = _log2_10_bounds(k)
    banded = _clamped_round(fmt, sign, b - 2 + lo, b + hi, rnd)
    if banded is not None:
        return banded
    if k >= 0:
        return _round_rational(fmt, sign, digits * 10 ** k, 1, rnd)
    return _round_rational(fmt, sign, digits, 10 ** -k, rnd)


def _round_binary(fmt: FpFormat, sign: int, m: int, e: int, rnd: int):
    """Round (-1)^sign * m * 2^e, m > 0, into the format - the hex
    sequence's arithmetic, where the value is already dyadic."""
    lead = e + m.bit_length() - 1
    banded = _clamped_round(fmt, sign, lead, lead, rnd)
    if banded is not None:
        return banded
    return sf.round_pack(fmt, sign, m, e, rnd)


# ----------------------------------------------------------------------
# The lexer. One syntax description, two entry points.
# ----------------------------------------------------------------------

_DIGITS = "0123456789"
_HEXDIGITS = "0123456789abcdefABCDEF"


def _split_sign(s: str):
    if s[:1] == "-":
        return 1, s[1:]
    if s[:1] == "+":
        return 0, s[1:]
    return 0, s


def _lex_special(body: str, sign: int, fmt: FpFormat):
    """The 5.12.1 words, or None if `body` is not one.

    "inf"/"infinity" and "nan"/"snan" in any case, the NaN forms with
    an optional payload suffix in "(0x...)" or "(decimal)" form. A
    suffix the format cannot hold is a refusal rather than a
    truncation.
    """
    low = body.lower()
    if low in ("inf", "infinity"):
        return sf.inf_bits(fmt, sign)
    head = low
    payload = None
    if low.endswith(")"):
        opening = low.find("(")
        if opening < 0:
            return None
        head = low[:opening]
        inner = body[opening + 1:-1]
        if inner[:2].lower() == "0x":
            text = inner[2:]
            if not text or any(c not in _HEXDIGITS for c in text):
                return None
            payload = int(text, 16)
        else:
            if not inner or any(c not in _DIGITS for c in inner):
                return None
            payload = _int_from_digits(inner)
    if head not in ("nan", "snan"):
        return None
    signaling = 1 if head == "snan" else 0
    if payload is None:
        # A bare "nan" is the canonical quiet NaN. A bare "snan" needs
        # SOME payload, because payload 0 with the quiet bit clear is
        # an infinity encoding - so it takes the smallest admissible
        # one, which is what setPayloadSignaling accepts as well.
        payload = 1 if signaling else 0
    if payload >= max_payload(fmt) or (signaling and payload == 0):
        raise CharacterSyntaxError(
            "payload %d is not admissible in %s: the format holds "
            "0 .. %d%s" % (payload, fmt.name, max_payload(fmt) - 1,
                           " and a signaling NaN needs a non-zero one"
                           if signaling else ""))
    return nan_bits(fmt, sign, payload, signaling)


def _lex_exponent(rest: str, marks: str):
    """(exponent, ok). `rest` is whatever followed the significand."""
    if not rest:
        return 0, True
    if rest[0] not in marks:
        return 0, False
    esign, body = _split_sign(rest[1:])
    if not body or any(c not in _DIGITS for c in body):
        return 0, False
    v = _int_from_digits(body)
    return -v if esign else v, True


def lex_decimal(fmt: FpFormat, s: str):
    """-> ("special", bits) or ("finite", sign, digits, k) with the
    value exactly (-1)^sign * digits * 10^k.

    The syntax, and nothing else: an optional sign, decimal digits with
    an optional point (at least one digit overall), an optional
    exponent part - or one of 5.12.1's words. No whitespace, no
    separators, no hexadecimal, no locale, no NUL-terminated slack.
    Anything else raises.
    """
    if not isinstance(s, str):
        raise CharacterSyntaxError("expected a str, got %s"
                                   % type(s).__name__)
    sign, body = _split_sign(s)
    if not body:
        raise CharacterSyntaxError("empty sequence")
    special = _lex_special(body, sign, fmt)
    if special is not None:
        return ("special", special)

    i = 0
    intpart = ""
    while i < len(body) and body[i] in _DIGITS:
        intpart += body[i]
        i += 1
    fracpart = ""
    if i < len(body) and body[i] == ".":
        i += 1
        while i < len(body) and body[i] in _DIGITS:
            fracpart += body[i]
            i += 1
    if not intpart and not fracpart:
        raise CharacterSyntaxError("not a decimal sequence: %r" % (s,))
    exp, ok = _lex_exponent(body[i:], "eE")
    if not ok:
        raise CharacterSyntaxError("not a decimal sequence: %r" % (s,))
    return ("finite", sign, _int_from_digits(intpart + fracpart),
            exp - len(fracpart))


def lex_hex(fmt: FpFormat, s: str):
    """-> ("special", bits) or ("finite", sign, m, e) with the value
    exactly (-1)^sign * m * 2^e.

    5.12.3's grammar, in the standard's own terms: an optional sign,
    "0x", a hexSignificand, and a decExponent that is NOT optional -
    the grammar writes {decExponent}, not {decExponent}?. 5.12.1's
    words are accepted too, because they are the same words in either
    radix and convertToHexCharacter writes them.
    """
    if not isinstance(s, str):
        raise CharacterSyntaxError("expected a str, got %s"
                                   % type(s).__name__)
    sign, body = _split_sign(s)
    if not body:
        raise CharacterSyntaxError("empty sequence")
    special = _lex_special(body, sign, fmt)
    if special is not None:
        return ("special", special)
    if body[:2].lower() != "0x":
        raise CharacterSyntaxError("not a hexadecimal sequence: %r" % (s,))
    body = body[2:]
    i = 0
    intpart = ""
    while i < len(body) and body[i] in _HEXDIGITS:
        intpart += body[i]
        i += 1
    fracpart = ""
    if i < len(body) and body[i] == ".":
        i += 1
        while i < len(body) and body[i] in _HEXDIGITS:
            fracpart += body[i]
            i += 1
    if not intpart and not fracpart:
        raise CharacterSyntaxError("not a hexadecimal sequence: %r" % (s,))
    rest = body[i:]
    if not rest:
        raise CharacterSyntaxError(
            "%r has no binary exponent: 5.12.3's grammar requires one "
            "(p+0 for a value that needs no scaling)" % (s,))
    exp, ok = _lex_exponent(rest, "pP")
    if not ok:
        raise CharacterSyntaxError("not a hexadecimal sequence: %r" % (s,))
    return ("finite", sign, int(intpart + fracpart or "0", 16),
            exp - 4 * len(fracpart))


# ----------------------------------------------------------------------
# convertFromDecimalCharacter / convertFromHexCharacter (5.4.2, 5.4.3)
# ----------------------------------------------------------------------

def from_decimal(fmt: FpFormat, s: str, rnd: int = sf.RND_RNE):
    """A decimal character sequence to `fmt`, correctly rounded under
    `rnd`, with the flags round_pack gives. Raises
    CharacterSyntaxError for a sequence outside the syntax."""
    sf._check_mode(rnd)
    tok = lex_decimal(fmt, s)
    if tok[0] == "special":
        return tok[1], 0
    _, sign, digits, k = tok
    if digits == 0:
        # A zero decimal is a zero, and rounding never changes a sign
        # (754 6.3), so a negative one is -0 in every attribute.
        return sf.zero_bits(fmt, sign), 0
    return _round_decimal(fmt, sign, digits, k, rnd)


def from_hex(fmt: FpFormat, s: str, rnd: int = sf.RND_RNE):
    """A hexadecimal-significand sequence to `fmt` (5.12.3). Exact when
    the sequence fits the format, correctly rounded under `rnd` when it
    carries more bits than the format holds."""
    sf._check_mode(rnd)
    tok = lex_hex(fmt, s)
    if tok[0] == "special":
        return tok[1], 0
    _, sign, m, e = tok
    if m == 0:
        return sf.zero_bits(fmt, sign), 0
    return _round_binary(fmt, sign, m, e, rnd)


# ----------------------------------------------------------------------
# convertToDecimalCharacter (5.4.2) - exact, or H significant digits
# ----------------------------------------------------------------------

def exact_digits(m: int, e: int):
    """The exact decimal of m * 2^e (m > 0) as (digits, exp10), where
    digits[0] carries weight 10^exp10. No leading and no trailing zero.

    Every binary float IS a finite decimal, because 2^-k = 5^k * 10^-k,
    so this always terminates. The price is length - the smallest
    binary256 subnormal runs to about 183,000 significant digits - and
    that price is the honest one: the string reads back to the same
    bits with no agreement about what "shortest" means."""
    if e >= 0:
        text = _digits_from_int(m << e)
        p10 = 0
    else:
        text = _digits_from_int(m * 5 ** (-e))
        p10 = e
    return text.rstrip("0"), len(text) - 1 + p10


def _round_digits(digits: str, exp10: int, h: int, sign: int, rnd: int):
    """Round the exact digit string to h significant digits under
    `rnd`. Returns (digits, exp10, inexact)."""
    if h >= len(digits):
        return digits + "0" * (h - len(digits)), exp10, False
    head = digits[:h]
    drop = int(digits[h])
    tail = any(c != "0" for c in digits[h + 1:])
    # The binary guard/sticky pair, on a decimal grid. guard is "the
    # dropped tail is at least half an ulp", which is drop >= 5;
    # sticky has to make (guard or sticky) mean "the tail is non-zero"
    # and (guard and sticky) mean "strictly more than half", so it is
    # "the tail is neither exactly zero nor exactly one half".
    guard = 1 if drop >= 5 else 0
    sticky = 1 if (tail or (drop != 0 and drop != 5)) else 0
    if sf._round_up(rnd, sign, guard, sticky, int(head[-1]) & 1):
        carried = _digits_from_int(_int_from_digits(head) + 1)
        if len(carried) > h:            # 999... carried out to 1000...
            carried = carried[:h]
            exp10 += 1
        head = carried
    # digits has no trailing zero, so digits[h:] ends in a non-zero
    # digit: dropping any of it is always inexact.
    return head, exp10, True


def _format_finite(sign: int, digits: str, exp10: int) -> str:
    body = digits[0] if len(digits) == 1 else digits[0] + "." + digits[1:]
    return "%s%se%s%d" % ("-" if sign else "", body,
                          "+" if exp10 >= 0 else "-", abs(exp10))


def special_text(fmt: FpFormat, bits: int):
    """The 5.12.1 spelling of a zero, an infinity or a NaN, or None for
    a finite non-zero value. Shared by both output conversions,
    because 5.12.1 is about the words rather than about the radix."""
    kind, sign, _, _, payload, signaling = _decode(fmt, bits)
    neg = "-" if sign else ""
    if kind == "inf":
        return neg + "inf"
    if kind == "nan":
        # "snan" rather than "nan" for a signaling NaN, which 5.12.1
        # allows and which is the spelling that raises NOTHING: the
        # alternative it offers - write "nan" and signal invalid -
        # loses the distinction the round trip is required to keep.
        word = "snan" if signaling else "nan"
        if payload:
            return "%s%s(0x%x)" % (neg, word, payload)
        return neg + word
    return None


def to_decimal(fmt: FpFormat, bits: int, digits: int = 0,
               rnd: int = sf.RND_RNE):
    """`fmt` to a decimal character sequence. Returns (text, flags).

    digits == 0 selects the EXACT mode: every digit of the exact value,
    however many that is, with no trailing zeros. digits >= 1 asks for
    exactly that many significant digits, correctly rounded under
    `rnd`, trailing zeros included - so a caller who asked for H digits
    can count H of them.

    inexact is the only flag this can raise: the exponent is written
    out in full, so 5.12.2's "exponent not of sufficient width"
    overflow and underflow cannot arise.
    """
    sf._check_mode(rnd)
    if digits < 0:
        raise ValueError("digits must be 0 (exact) or a positive count")
    text = special_text(fmt, bits)
    if text is not None:
        return text, 0
    kind, sign, m, e, _, _ = _decode(fmt, bits)
    if kind == "zero":
        # A zero has no significant digits to round or to pad, at any
        # H, so both modes write the same two characters.
        return ("-0" if sign else "0"), 0
    ds, exp10 = exact_digits(m, e)
    if digits == 0:
        return _format_finite(sign, ds, exp10), 0
    ds, exp10, inexact = _round_digits(ds, exp10, digits, sign, rnd)
    return (_format_finite(sign, ds, exp10),
            sf.FLAG_INEXACT if inexact else 0)


# ----------------------------------------------------------------------
# convertToHexCharacter (5.4.3) - the shortest exact form
# ----------------------------------------------------------------------

def to_hex(fmt: FpFormat, bits: int) -> str:
    """`fmt` to a hexadecimal-significand sequence, exactly.

    5.12.3: "in the absence of an explicit precision specification,
    enough hexadecimal characters shall be used to represent the binary
    floating-point number exactly". The form is canonical - one leading
    1, no trailing zeros in the fraction, an explicitly signed binary
    exponent - so a SUBNORMAL prints with its true exponent
    (0x1p-149 for the smallest binary32) rather than with a leading
    zero digit, and the spelling depends on the VALUE rather than on
    which side of the format's subnormal boundary it sits.

    Always exact, so there is no rounding attribute to consult and
    nothing at all to signal.
    """
    text = special_text(fmt, bits)
    if text is not None:
        return text
    kind, sign, m, e, _, _ = _decode(fmt, bits)
    neg = "-" if sign else ""
    if kind == "zero":
        return neg + "0x0p+0"
    length = m.bit_length()
    exp = e + length - 1
    frac = m - (1 << (length - 1))
    nib = (length + 2) // 4                 # ceil((length - 1) / 4)
    if nib:
        frac <<= 4 * nib - (length - 1)
        text = ("%0*x" % (nib, frac)).rstrip("0")
    else:
        text = ""
    return "%s0x1%sp%s%d" % (neg, "." + text if text else "",
                             "+" if exp >= 0 else "-", abs(exp))


# ----------------------------------------------------------------------
# The 9.7 NaN payload operations
# ----------------------------------------------------------------------
#
# Quiet-computational, and 9.7 says in as many words that they "signal
# no exceptions" - so none of the three has a flag word, and a
# signaling NaN operand raises nothing here either. They are ENCODING
# operations: getPayload reads a bit field and setPayload writes one,
# which is exactly why the contract's canonical-NaN rule does not
# reach them (docs/DETERMINISM.md).

def get_payload(fmt: FpFormat, bits: int) -> int:
    """9.7 getPayload: the payload as a non-negative floating-point
    integer, or -1 when the operand is not a NaN. Signaling and quiet
    NaNs both answer with their payload - the operation reads an
    encoding and signals nothing, so there is no sNaN case to make.
    The standard's "preferred exponent is 0" binds decimal formats and
    has no force here."""
    kind, _, _, _, payload, _ = _decode(fmt, bits)
    if kind != "nan":
        return sf.one_bits(fmt, 1)                     # -1
    if payload == 0:
        return sf.zero_bits(fmt, 0)                    # +0
    # A payload is below 2^(man_w - 1) < 2^p, so it is a representable
    # integer at every rung and this rounding is exact by construction.
    out, flags = sf.round_pack(fmt, 0, payload, 0, sf.RND_RNE)
    assert flags == 0
    return out


def payload_operand(fmt: FpFormat, bits: int):
    """9.7's admissible-payload test, as one predicate.

    "a non-negative floating-point integer whose value is one of an
    implementation-defined set of admissible payloads": the set here is
    exactly what the format's payload field holds, 0 .. 2^(man_w-1) - 1
    (and 1 upward for the signaling form, since payload 0 with the
    quiet bit clear is an infinity encoding).

    The test is on the VALUE, so -0 passes it as the integer zero: 754
    settles that -0 equals 0, and every other value-based operation in
    this contract (logB, the comparisons) reads it the same way.

    Returns the payload, or None when the operand is not admissible."""
    kind, sign, m, e, _, _ = _decode(fmt, bits)
    if kind == "zero":
        return 0
    if kind != "finite" or sign:
        return None
    if e < 0:
        if -e >= m.bit_length() or m & ((1 << -e) - 1):
            return None                                # not an integer
        value = m >> -e
    else:
        value = m << e
    if value >= max_payload(fmt):
        return None
    return value


def set_payload(fmt: FpFormat, bits: int) -> int:
    """9.7 setPayload: a quiet NaN carrying the operand's value when
    that value is an admissible payload, and +0 otherwise. The standard
    fixes the sign of the fallback (+0) and leaves the NaN's open; this
    contract writes sign 0, matching the non-negative operand it came
    from."""
    payload = payload_operand(fmt, bits)
    if payload is None:
        return sf.zero_bits(fmt, 0)
    return nan_bits(fmt, 0, payload, 0)


def set_payload_signaling(fmt: FpFormat, bits: int) -> int:
    """9.7 setPayloadSignaling: the signaling form. Payload 0 is NOT
    admissible here - the encoding it would produce is an infinity -
    so setPayloadSignaling(+-0) is +0."""
    payload = payload_operand(fmt, bits)
    if not payload:
        return sf.zero_bits(fmt, 0)
    return nan_bits(fmt, 0, payload, 1)
