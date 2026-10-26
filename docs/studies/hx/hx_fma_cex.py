#!/usr/bin/env python3
"""hx_fma_cex.py - parcel HX: the FMA ladder fails at every real rung under RNE and under RMM
(docs/studies/HX-wide-sweeps.md, 4.1). Exact rationals: fma(97 2^40, 172961 2^36, c) with c = 2^-149 and its mirror
c = -2^-149, rounded once to fp32 against rounded to fp64, fp128 or fp256 first, under RNE and under RMM.
97 x 172961 = 2^24 + 1, so a*b is an fp32 midpoint and |c| lies below half an ulp of every wide format at a*b: the
wide result is a*b, whose narrowing breaks the tie by the attribute's rule (to even, or away from zero), while the
direct rounding sees the side c put the exact value on. So c = 2^-149 must fail under RNE and agree under RMM, and
its mirror fail under RMM and agree under RNE. Standard library only. usage: python hx_fma_cex.py"""
from fractions import Fraction as F
def near(x, p, emin, away):
    # round positive x to p bits, to nearest, ties to even (RNE) or away (RMM); subnormals below 2^emin, no overflow
    e = x.numerator.bit_length() - x.denominator.bit_length()
    if F(2) ** e > x: e -= 1
    q = max(e, emin) - (p - 1)
    s = x / F(2) ** q
    k = s.numerator // s.denominator
    r = s - k
    if r > F(1, 2) or (r == F(1, 2) and (away or k % 2 == 1)): k += 1
    return k * F(2) ** q
a, b = 97 * F(2) ** 40, 172961 * F(2) ** 36
assert 97 * 172961 == 2 ** 24 + 1 and 97 < 2 ** 24 and 172961 < 2 ** 24
LO, HI = F(2) ** 100, (2 ** 24 + 2) * F(2) ** 76            # a*b's fp32 neighbours: LO's significand is even
NAME = {LO: "2^100", HI: "(2^24 + 2) 2^76"}
bad = 0
for attr, c, want, fails in (("rne", F(2) ** -149, HI, True), ("rmm", F(2) ** -149, HI, False),
                             ("rne", -F(2) ** -149, LO, False), ("rmm", -F(2) ** -149, LO, True)):
    x = a * b + c                                          # (attribute, c, fp32 directly, must the ladder fail)
    direct = near(x, 24, -126, attr == "rmm")
    print("%s, c = %s2^-149: fp32 directly %s" % (attr, "" if c > 0 else "-", NAME.get(direct, "UNEXPECTED")))
    bad += direct != want
    for name, p, emin in (("fp64", 53, -1022), ("fp128", 113, -16382), ("fp256", 237, -262142)):
        w = near(x, p, emin, attr == "rmm")
        via = near(w, 24, -126, attr == "rmm")
        print("  through %-5s: the wide result is %s; narrowed to fp32 %s: %s"
              % (name, "a*b exactly (c lost)" if w == a * b else "not a*b", NAME.get(via, str(via)),
                 "DIFFERS from fp32 directly" if via != direct else "equal"))
        bad += w != a * b or (via != direct) != fails
print("hx_fma_cex: %s" % ("c = 2^-149 under RNE and c = -2^-149 under RMM fail at every rung, each agrees under the"
                          " other, as stated" if bad == 0 else "%d UNEXPECTED" % bad))
raise SystemExit(1 if bad else 0)
