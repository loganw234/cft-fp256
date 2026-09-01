# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""An independent IEEE 754-2019 oracle for the test suite.

Written for the 2026-09-01 adversarial review of the clause-5
completion set and promoted to the suite afterwards, because its value
is structural: it shares NO code with cft_golden. Everything here is
exact Fraction arithmetic and the standard's rules restated from
scratch - rounding by rational comparison, 7.4 overflow as
"the unbounded-range rounding exceeds the largest finite", 7.5(a)
tininess after rounding, and totalOrder written rule by rule from
5.10's clauses rather than the key transform the model uses (which is
exactly the property under test). A model bug and an oracle bug would
have to agree to hide a failure.

Deliberately NOT part of cft_golden: the model is the single
definition of correct, and this is a witness against it, which only
works while the two share nothing.
"""
from fractions import Fraction as F
import math

RNE, RTZ, RDN, RUP, RMM = 0, 1, 2, 3, 4
MODES = (RNE, RTZ, RDN, RUP, RMM)
NV, DZ, OF, UF, NX = 1, 2, 4, 8, 16


class Fmt:
    def __init__(self, exp_w, man_w):
        self.exp_w, self.man_w = exp_w, man_w
        self.width = 1 + exp_w + man_w
        self.bias = (1 << (exp_w - 1)) - 1
        self.emax = self.bias
        self.emin = 1 - self.bias
        self.p = man_w + 1
        self.exp_mask = (1 << exp_w) - 1
        self.man_mask = (1 << man_w) - 1
        self.sign_mask = 1 << (self.width - 1)

    def qnan(self):
        return (self.exp_mask << self.man_w) | (1 << (self.man_w - 1))

    def inf(self, s=0):
        return (s << (self.width - 1)) | (self.exp_mask << self.man_w)

    def zero(self, s=0):
        return s << (self.width - 1)

    def maxfin_bits(self, s=0):
        return (s << (self.width - 1)) | ((self.exp_mask - 1) << self.man_w) | self.man_mask

    def maxfin_val(self):
        return F(2) ** (self.emax + 1) - F(2) ** (self.emax - self.p + 1)


def dec(f, bits):
    """('nan', sign, quiet) | ('inf', sign) | ('num', sign, Fraction)."""
    s = (bits >> (f.width - 1)) & 1
    ef = (bits >> f.man_w) & f.exp_mask
    fr = bits & f.man_mask
    if ef == f.exp_mask:
        if fr == 0:
            return ("inf", s, None)
        return ("nan", s, (fr >> (f.man_w - 1)) & 1)
    if ef == 0:
        v = F(fr) * F(2) ** (f.emin - f.man_w)
    else:
        v = F((1 << f.man_w) + fr) * F(2) ** (ef - f.bias - f.man_w)
    return ("num", s, -v if s else v)


def floor_log2(a):
    assert a > 0
    n, d = a.numerator, a.denominator
    k = n.bit_length() - d.bit_length()
    while F(2) ** k > a:
        k -= 1
    while F(2) ** (k + 1) <= a:
        k += 1
    return k


def rnd_int(t, rnd):
    """Round the rational t to an integer under the (signed) attribute."""
    fl = math.floor(t)
    if t == fl:
        return fl
    ce = fl + 1
    if rnd == RDN:
        return fl
    if rnd == RUP:
        return ce
    if rnd == RTZ:
        return fl if t > 0 else ce
    dlo, dhi = t - fl, F(ce) - t
    if dlo < dhi:
        return fl
    if dhi < dlo:
        return ce
    if rnd == RNE:
        return fl if fl % 2 == 0 else ce
    return ce if t > 0 else fl          # RMM: ties away from zero


def enc_exact(f, v):
    """bits of the exactly-representable nonzero rational v, or None."""
    s = 1 if v < 0 else 0
    a = abs(v)
    e2 = floor_log2(a)
    if e2 > f.emax:
        return None
    q = max(e2, f.emin) - (f.p - 1)
    t = a / F(2) ** q
    if t.denominator != 1:
        return None
    n = t.numerator
    if n >= (1 << f.p):
        return None
    if e2 < f.emin:                     # subnormal: n IS the fraction field
        return (s << (f.width - 1)) | n
    frac = n - (1 << (f.p - 1))
    return (s << (f.width - 1)) | ((e2 + f.bias) << f.man_w) | frac


def ref_pack(f, v, rnd):
    """(bits, flags): v (exact nonzero rational) correctly rounded into f.
    7.4 overflow (unbounded-round magnitude exceeds maxfin), 7.5 a)
    after-rounding tininess, underflow = tiny AND inexact."""
    s = 1 if v < 0 else 0
    a = abs(v)
    e2 = floor_log2(a)
    qu = e2 - (f.p - 1)
    ru = abs(rnd_int(v / F(2) ** qu, rnd)) * F(2) ** qu   # unbounded round
    tiny = ru < F(2) ** f.emin
    q = max(e2, f.emin) - (f.p - 1)
    nb = rnd_int(v / F(2) ** q, rnd)
    rb = F(nb) * F(2) ** q
    inexact = rb != v
    flags = NX if inexact else 0
    if abs(rb) > f.maxfin_val():
        flags |= OF | NX
        if rnd in (RNE, RMM):
            return f.inf(s), flags
        if rnd == RTZ:
            return f.maxfin_bits(s), flags
        if rnd == RDN:
            return (f.inf(1) if s else f.maxfin_bits(0)), flags
        return (f.maxfin_bits(1) if s else f.inf(0)), flags
    if nb == 0:
        return f.zero(s), flags | UF
    if tiny and inexact:
        flags |= UF
    bits = enc_exact(f, rb)
    assert bits is not None, (v, rnd)
    return bits, flags


# ---- per-operation references (independent restatements of clause 5) --

def ref_round_int(f, bits, rnd, exact):
    k = dec(f, bits)
    if k[0] == "nan":
        return f.qnan(), (NV if not k[2] else 0)
    if k[0] == "inf":
        return bits, 0
    s, v = k[1], k[2]
    if v == 0:
        return bits, 0
    n = rnd_int(v, rnd)
    changed = F(n) != v
    fl = NX if (exact and changed) else 0
    if n == 0:
        return f.zero(s), fl            # 5.9: zero keeps operand's sign
    return enc_exact(f, F(n)), fl


def ref_convert(sf_, df, bits, rnd):
    k = dec(sf_, bits)
    if k[0] == "nan":
        return df.qnan(), (NV if not k[2] else 0)
    if k[0] == "inf":
        return df.inf(k[1]), 0
    s, v = k[1], k[2]
    if v == 0:
        return df.zero(s), 0
    return ref_pack(df, v, rnd)


def ref_from_int(f, v, rnd):
    if v == 0:
        return f.zero(0), 0
    return ref_pack(f, F(v), rnd)


def ref_to_int(f, bits, width, signed, rnd, exact):
    lo = -(1 << (width - 1)) if signed else 0
    hi = ((1 << (width - 1)) - 1) if signed else ((1 << width) - 1)
    k = dec(f, bits)
    if k[0] == "nan":
        return hi, NV
    if k[0] == "inf":
        return (lo if k[1] else hi), NV
    v = k[2]
    if v == 0:
        return 0, 0
    n = rnd_int(v, rnd)
    if n < lo:
        return lo, NV                   # invalid pre-empts inexact
    if n > hi:
        return hi, NV
    return n, (NX if (exact and F(n) != v) else 0)


def ref_scaleb(f, bits, n, rnd):
    k = dec(f, bits)
    if k[0] == "nan":
        return f.qnan(), (NV if not k[2] else 0)
    if k[0] == "inf" or k[2] == 0:
        return bits, 0
    return ref_pack(f, k[2] * F(2) ** n, rnd)


def ref_logb(f, bits):
    k = dec(f, bits)
    if k[0] == "nan":
        return f.qnan(), (NV if not k[2] else 0)
    if k[0] == "inf":
        return f.inf(0), 0
    v = k[2]
    if v == 0:
        return f.inf(1), DZ
    E = floor_log2(abs(v))
    if E == 0:
        return f.zero(0), 0
    return enc_exact(f, F(E)), 0


def ref_remainder(f, xb, yb):
    kx, ky = dec(f, xb), dec(f, yb)
    if kx[0] == "nan" or ky[0] == "nan":
        sig = (kx[0] == "nan" and not kx[2]) or (ky[0] == "nan" and not ky[2])
        return f.qnan(), (NV if sig else 0)
    if kx[0] == "inf" or (ky[0] == "num" and ky[2] == 0):
        return f.qnan(), NV
    if ky[0] == "inf" or kx[2] == 0:
        return xb, 0
    x, y = kx[2], ky[2]
    n = rnd_int(x / y, RNE)             # nearest integer, ties to even
    r = x - y * n
    if r == 0:
        return f.zero(kx[1]), 0
    bits = enc_exact(f, r)
    assert bits is not None, "754 remainder not representable?!"
    return bits, 0


def ref_total_order(f, xb, yb):
    """754-2019 5.10, restated rule by rule (no key transform)."""
    kx, ky = dec(f, xb), dec(f, yb)
    xn, yn = kx[0] == "nan", ky[0] == "nan"
    if xn or yn:
        if xn and not yn:
            return kx[1] == 1           # -NaN before everything, +NaN after
        if yn and not xn:
            return ky[1] == 0
        # both NaN: sign (neg first), then quiet/signaling, then payload
        if kx[1] != ky[1]:
            return kx[1] == 1
        qx, qy = kx[2], ky[2]
        px, py = xb & (f.man_mask >> 1), yb & (f.man_mask >> 1)
        if kx[1] == 0:                  # positive: sNaN < qNaN, lesser payload first
            if qx != qy:
                return qx < qy
            return px <= py
        else:                           # negative: reversed
            if qx != qy:
                return qx > qy
            return px >= py
    # numbers (inf included): extended-real strict order, -0 == +0
    def num_lt(ka, kb):
        if ka[0] == "inf":
            if ka[1]:                   # -inf < all except -inf
                return not (kb[0] == "inf" and kb[1])
            return False                # +inf < nothing
        if kb[0] == "inf":
            return kb[1] == 0           # finite < +inf only
        return ka[2] < kb[2]
    if num_lt(kx, ky):
        return True
    if num_lt(ky, kx):
        return False
    # numerically equal: -0 before +0; identical datums are <=
    if kx[1] != ky[1]:
        return kx[1] == 1
    return True
