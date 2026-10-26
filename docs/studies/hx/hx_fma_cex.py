#!/usr/bin/env python3
"""hx_fma_cex.py - parcel HX: the FMA ladder fails at every real rung (docs/studies/HX-wide-sweeps.md, 4.1). One fp32
triple, exact rationals: fma(97 2^40, 172961 2^36, 2^-149) under RNE, rounded once to fp32 against rounded to fp64,
fp128 or fp256 first. 97 x 172961 = 2^24 + 1, so a*b is an fp32 midpoint and c lies below half an ulp of every wide
format at a*b. Standard library only. usage: python hx_fma_cex.py"""
from fractions import Fraction as F
def rne(x, p, emin):
    # round positive x to p bits, RNE, subnormals below 2^emin (no overflow in this check)
    e = x.numerator.bit_length() - x.denominator.bit_length()
    if F(2) ** e > x: e -= 1
    q = max(e, emin) - (p - 1)
    s = x / F(2) ** q
    k = s.numerator // s.denominator
    r = s - k
    if r > F(1, 2) or (r == F(1, 2) and k % 2 == 1): k += 1
    return k * F(2) ** q
a, b, c = 97 * F(2) ** 40, 172961 * F(2) ** 36, F(2) ** -149
assert 97 * 172961 == 2 ** 24 + 1 and 97 < 2 ** 24 and 172961 < 2 ** 24
x = a * b + c
direct = rne(x, 24, -126)
bad = 0
print("fp32 directly: %s" % ("(2^24 + 2) 2^76, rounded up past the midpoint" if direct == (2 ** 24 + 2) * F(2) ** 76
                              else "UNEXPECTED %s" % direct))
bad += direct != (2 ** 24 + 2) * F(2) ** 76
for name, p, emin in (("fp64", 53, -1022), ("fp128", 113, -16382), ("fp256", 237, -262142)):
    w = rne(x, p, emin)
    via = rne(w, 24, -126)
    print("through %-5s: the wide result is %s; narrowed to fp32 it is %s: %s"
          % (name, "a*b exactly (c lost)" if w == a * b else "not a*b", "2^100 (the tie to even)" if via == F(2) ** 100
             else str(via), "DIFFERS from fp32 directly" if via != direct else "equal"))
    bad += via == direct
print("hx_fma_cex: %s" % ("the ladder fails for FMA at every rung, as stated" if bad == 0 else "%d UNEXPECTED" % bad))
raise SystemExit(1 if bad else 0)
