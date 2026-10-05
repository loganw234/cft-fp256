# M1 model: constants, from exact rationals or from mpmath at high
# precision, rounded once into the format (scratch).

from fractions import Fraction
import math

import mpmath

from m1core import enc, enc_exact, dec, RNE, RDN, RUP

mpmath.mp.prec = 3000


def mpf_to_frac(v):
    man, ex = mpmath.libmp.to_man_exp(v._mpf_)
    man, ex = int(man), int(ex)
    return Fraction(man) * (Fraction(2) ** ex)


def words_of(fmt, value, n):
    """value (mpf or Fraction) as n words, each the nearest to what is
    left: w0 = RN(v), w1 = RN(v - w0), ... -> [bits]."""
    v = mpf_to_frac(value) if isinstance(value, mpmath.mpf) else Fraction(value)
    out = []
    for _ in range(n):
        b = enc(fmt, v)
        out.append(b)
        v -= dec(fmt, b)
    return out


def truncated(fmt, value, bits):
    """value truncated toward zero to `bits` significant bits, exactly
    representable."""
    v = mpf_to_frac(value) if isinstance(value, mpmath.mpf) else Fraction(value)
    s = -1 if v < 0 else 1
    v = abs(v)
    e = math.floor(math.log2(v)) if v else 0
    # floor(v * 2^(bits-1-e)) / 2^(bits-1-e)
    sc = Fraction(2) ** (bits - 1 - e)
    t = Fraction(math.floor(v * sc)) / sc
    while t.numerator.bit_length() > bits and False:
        pass
    return enc_exact(fmt, s * t)


def ln2():
    return mpmath.log(2)


def residual(value, fmt, words):
    v = mpf_to_frac(value) if isinstance(value, mpmath.mpf) else Fraction(value)
    return v - sum(dec(fmt, w) for w in words)
