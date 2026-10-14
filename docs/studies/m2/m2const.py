# M2 model: constants (scratch). Every constant is an exact rational, or
# derived from mpmath at high precision and rounded once; 2/pi's bits are
# also held to host/src/mp_2opi.h, the header the library reduces with
# (read through host/tools/pi_worstcase.py, which reads it).

import functools
import math
import sys
from fractions import Fraction

import mpmath

from m2core import ROOT, frac, enc, dec, words_of

sys.path.insert(0, str(ROOT / "host" / "tools"))
import pi_worstcase                                   # noqa: E402


@functools.lru_cache(maxsize=None)
def two_over_pi_int(nbits):
    """floor(2/pi * 2^nbits), from mpmath at nbits + 64 bits; held to the
    header's bits wherever the header reaches (270,336 bits)."""
    with mpmath.workprec(nbits + 64):
        v = frac(mpmath.mpf(2) / mpmath.pi * (mpmath.mpf(2) ** nbits))
    n = v.numerator // v.denominator
    hdr = pi_worstcase.two_over_pi(nbits)
    # the two floors may differ in the last bit only if 2/pi 2^nbits is
    # within 2^-64 of an integer, which a direct comparison would show
    if n != hdr:
        raise AssertionError(f"2/pi to {nbits} bits: mpmath and "
                             f"mp_2opi.h differ")
    return n


def chunks(b, count):
    """c_0 .. c_(count-1): 2/pi = sum c_k 2^-((k+1)b), each c_k a b-bit
    integer (the bits [kb, (k+1)b) after the binary point)."""
    nb = b * count
    t = two_over_pi_int(nb)
    out = []
    for k in range(count):
        shift = nb - (k + 1) * b
        out.append((t >> shift) & ((1 << b) - 1))
    return out


@functools.lru_cache(maxsize=None)
def pi_frac(bits=4000):
    with mpmath.workprec(bits):
        return frac(+mpmath.pi)


def pio2_words(fmt, n):
    return words_of(fmt, pi_frac() / 2, n)


def sin_coef(k):
    """The coefficient of z^k in S(z) = sin(r)/r, z = r^2:
    (-1)^k / (2k+1)!, exact."""
    return Fraction((-1) ** k, math.factorial(2 * k + 1))


def cos_coef(k):
    """The coefficient of z^k in C(z) = cos(r), z = r^2: (-1)^k / (2k)!."""
    return Fraction((-1) ** k, math.factorial(2 * k))


def lead_bits(c):
    return c.bit_length()
