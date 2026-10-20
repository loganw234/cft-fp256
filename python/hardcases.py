# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""hardcases: the hard-to-round divisions and square roots, constructed instead of drawn (parcel HC).

The reference generator for the soak tool's `div32-hard`, `div64-hard` and `sqrt64-hard` modes
(host/tools/divsqrt_soak.c). A sampler draws a quotient within 2^-p of a rounding boundary with probability
about 1.5e-16 at fp64; here one modular inverse builds it. docs/studies/SWP-A-coverage.md section 4.2 gives the
mathematics and docs/studies/swp-a/hardcase_div.py the prototype; this file is the prototype made a
deterministic index space that the C tool reproduces operand for operand.

THE INDEX SPACE. A mode is a list of segments; an index [0, E) belongs to one segment, and an index makes `k`
slots (division: the four sign combinations of one operand pair, slot s = (sign of a) + 2 (sign of b); square
root: one). An index whose construction yields no operand pair is a SKIP: all of its slots are skipped, and the
tool prints cases + skipped = k x indices. Within a segment an index i0 is 4 j + v: j picks the base (a
divisor, a pair of odd parts, a strip depth, ...) and v one of four variants of it.

  division (p = 24: div32-hard; p = 53: div64-hard)             positive operands, then the slot's signs
    F3a  ties in the subnormal strip       j = s - 1, s = 1..p: b = 2^(s+3) and a = the normal number of biased
                                           exponent 4 whose significand is o 2^(s-1), for an odd o of p - s + 1
                                           bits in four patterns (v): the exact quotient is o 2^(emin-p), a TIE of
                                           the subnormal grid, s places below the smallest normal. Reachable at
                                           the operand formats: both operands are normal.
    F3b  powers of two, exponent sweep     j = 0..4 bias - 2: the quotient exponent e_q = j - (2 bias - 1) through
                                           every strip, the core and the overflow strip; v: b = 2^m with a = 2 - ulp
                                           or 1.5, or a = 2^m with b = 2 - ulp or 1.5
    F2   b = 1 +- k ulp                    k = j + 1 = 1..2^16; v = 2 (a type) + (b type): a = 1.0 or 2 - ulp;
                                           b = 1 + k ulp or 1 - k ulp. j = 0 with a = 1.0, b = 1 - ulp is the
                                           repository's own failing family (python/tests/test_sequences.py)
    F1   exact quotients                   j picks odd parts ob, oq below 2^((p-1)/2) by a keyed mix; a = ob oq,
                                           b = ob, quotient oq exactly; v picks the exponents: (0, 0), (+E, -E),
                                           (-E, +E), and one whose exact quotient is subnormal
    F0   closest approach, odd divisors    (v = 2 target + sign) for an odd divisor my (A: from the bottom of the
         A: 1.0 up   D: 2.0 down           binade, D: from the top, K: cell-stratified keyed, fp64 only), the
         K: keyed (fp64)                   dividend mx with |N| = 1: the quotient is 1/(my 2^p) from a midpoint
                                           (target 0) or 1/(my 2^(p-1)) from a representable number (target 1),
                                           above (sign 0) or below (sign 1); a SKIP where there is none
  square root (p = 53: sqrt64-hard)                             one operand
    S1   sqrt(1 + k ulp) and its kin       k = 2 j + 1 odd; v: x = 1 + k ulp; x = 4 - k ulp (the ulp of [2, 4));
                                           x = 1 - k ulp (the ulp of [1/2, 1)); x = 4^255 (1 + k ulp)
    S0   the structure of odd squares      n picks rho = 8 m + 1 (1, -7, 9, -15, 17, ...), v = 2 parity + root: the
                                           inputs x nearest the square of a midpoint, at distance |rho| 2^-2p

Every case is verified in exact integers by `verify` (independent of the builders: it decodes the operand bits and
classifies the exact quotient or root with Fractions and isqrt), and the C tool reproduces `dump` line for line.

usage: python hardcases.py space MODE             the segment table
       python hardcases.py dump MODE LO HI        one line a (index, slot): operands or skip
       python hardcases.py count MODE LO HI       per segment: indices, cases, skipped slots; then the total
       python hardcases.py verify MODE [N [SEED]] exact verification: every index of the small segments, N (default
                                                  2000) per large one; exit 1 and a named check on the first failure
       python hardcases.py stats MODE [N [SEED]]  cases and skips per segment (the same sampling)
"""
import sys
from fractions import Fraction
from math import isqrt

M64 = (1 << 64) - 1
SALT_F0K = 0x5851F42D4C957F2D            # the keyed streams' salts (the C tool carries the same constants)
SALT_F1 = 0x14057B7EF767814F
SMALL_SEGMENT = 1 << 14                  # `verify` checks every index of a segment up to this size


def mix64(x):
    """splitmix64's finalizer of x + the golden-ratio increment (a bijection of 64-bit words)."""
    x = (x + 0x9E3779B97F4A7C15) & M64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & M64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & M64
    return x ^ (x >> 31)


class Space:
    """One mode: its format, its slots an index and its segments [(name, start, count)]."""

    def __init__(self, mode, p, w, bias, k, segs):
        self.mode, self.p, self.w, self.bias, self.k = mode, p, w, bias, k
        self.P1, self.P = 1 << (p - 1), 1 << p
        self.emin = 1 - bias
        self.segs = []
        start = 0
        for name, count in segs:
            self.segs.append((name, start, count))
            start += count
        self.total = start

    def locate(self, idx):
        """(segment name, index within it) of an index in [0, total)."""
        for name, start, count in self.segs:
            if start <= idx < start + count:
                return name, idx - start
        raise ValueError("index %d is outside [0, %d) of %s" % (idx, self.total, self.mode))


def _div_space(mode, p, w, bias, nk):
    segs = [("F3a", 4 * p), ("F3b", 4 * (4 * bias - 1)), ("F2", 4 << 16), ("F1", 4 << 20),
            ("F0A", 4 << 21), ("F0D", 4 << 21)]
    if nk:
        segs.append(("F0K", 4 * nk))
    return Space(mode, p, w, bias, 4, segs)


SPACES = {
    "div32-hard": _div_space("div32-hard", 24, 32, 127, 0),
    "div64-hard": _div_space("div64-hard", 53, 64, 1023, 1 << 26),
    "sqrt64-hard": Space("sqrt64-hard", 53, 64, 1023, 1, [("S1", 4 << 16), ("S0", 4 << 20)]),
}


# ------------------------------------------------------------------------------------------------------------
# the builders: an index -> the positive operand encodings (a, b), or None for a skip
# ------------------------------------------------------------------------------------------------------------

def _enc(sp, e_biased, sig):
    """Encoding of the normal number sig 2^(e_biased - bias - (p-1)), sig in [2^(p-1), 2^p)."""
    assert sp.P1 <= sig < sp.P and 1 <= e_biased <= 2 * sp.bias, (sig, e_biased)
    return (e_biased << (sp.p - 1)) | (sig - sp.P1)


def _enc_int(sp, n, t):
    """Encoding of the exact value n 2^t (n a positive integer below 2^p)."""
    length = n.bit_length()
    assert length <= sp.p
    return _enc(sp, sp.bias + length - 1 + t, n << (sp.p - length))


def _tie_pattern(length, v):
    """An odd integer of exactly `length` bits: all ones, 10..01, 1010..1, and all ones but bit 1."""
    full = (1 << length) - 1
    if v == 0:
        return full
    if v == 1:
        return (1 << (length - 1)) | 1
    if v == 2:
        return (0x5555555555555555 & full) | (1 << (length - 1)) | 1
    return (full & ~2) | (1 << (length - 1)) | 1


def build_f3a(sp, j, v):
    s = j + 1                                           # the strip depth, 1 .. p
    o = _tie_pattern(sp.p - s + 1, v)
    return _enc(sp, 4, o << (s - 1)), _enc(sp, sp.bias + s + 3, sp.P1)


def build_f3b(sp, j, v):
    bias, p = sp.bias, sp.p
    eq = j - (2 * bias - 1)                             # the quotient exponent, -(2 bias - 1) .. 2 bias - 1
    ea, eb = 1 + max(eq, 0), 1 + max(-eq, 0)            # biased; ea - eb = eq; the smaller sits at the smallest normal
    sig = sp.P - 1 if v in (0, 2) else 3 << (p - 2)     # 2 - ulp, or 1.5
    if v < 2:
        return _enc(sp, ea, sig), _enc(sp, eb, sp.P1)   # b = 2^m
    return _enc(sp, ea, sp.P1), _enc(sp, eb, sig)       # a = 2^m


def build_f2(sp, j, v):
    k = j + 1
    a = _enc(sp, sp.bias, sp.P1 if v < 2 else sp.P - 1)
    b = _enc(sp, sp.bias, sp.P1 + k) if v & 1 == 0 else _enc(sp, sp.bias - 1, sp.P - k)
    return a, b


def build_f1(sp, j, v):
    p, bias = sp.p, sp.bias
    h = (p - 1) // 2
    ob = 2 * (mix64((2 * j) ^ SALT_F1) >> (64 - (h - 1))) + 1
    oq = 2 * (mix64((2 * j + 1) ^ SALT_F1) >> (64 - (h - 1))) + 1
    e, tb3, sh = bias // 3, bias // 2, p - 2
    ta, tb = ((0, 0), (e, -e), (-e, e), (tb3 + sp.emin - sh, tb3))[v]
    return _enc_int(sp, ob * oq, ta), _enc_int(sp, ob, tb)


def f0_divisor(sp, stream, jj):
    p = sp.p
    if stream == "A":
        return sp.P1 + 1 + 2 * jj
    if stream == "D":
        return sp.P - 1 - 2 * jj
    low = mix64(jj ^ SALT_F0K) & ((1 << (p - 13)) - 1)  # K: the top 12 fraction bits take every value once in 4096
    return sp.P1 | (((jj * 2659) & 4095) << (p - 13)) | low | 1   # divisors (2659 is odd: a bijection of the cells)


def build_f0(sp, stream, j, v):
    p = sp.p
    my = f0_divisor(sp, stream, j)
    kk = p if v >> 1 == 0 else p - 1
    r = pow(1 << kk, -1, my)
    if v & 1:
        r = my - r
    x = r + my                                          # x 2^kk = +-1 (mod my), x in (my, 2 my)
    if x < sp.P:
        mx = x
    elif x % 2 == 0:
        mx = x >> 1                                     # a quotient in (1/2, 1): the sampler's doubling
    else:
        return None
    return _enc(sp, sp.bias, mx), _enc(sp, sp.bias, my)


def hensel(rho, t):
    """An odd u, 0 <= u < 2^t, with u^2 = rho (mod 2^t), for rho = 1 (mod 8): lifted one bit at a time."""
    u = 1
    for b in range(3, t):
        if ((u * u - rho) >> b) & 1:
            u += 1 << (b - 1)
    return u % (1 << t)


def build_s0(sp, n, v):
    p, bias = sp.p, sp.bias
    par, r = v >> 1, v & 1
    m = n // 2 if n % 2 == 0 else -((n + 1) // 2)
    rho = 8 * m + 1
    s = p + 1 + par                                     # the input grid, in units of 2^-2p, is 2^s
    u0 = hensel(rho, p + 2)
    size = 1 << s
    cands = sorted({u0 % size, (-u0) % size, (u0 + (size >> 1)) % size, (-u0 + (size >> 1)) % size})
    roots = [u for u in cands if sp.P <= u < 2 * sp.P and (u * u < (1 << (2 * p + 1))) == (par == 0)]
    if r >= len(roots):
        return None
    k = (roots[r] ** 2 + (1 << (s - 1))) >> s
    if not sp.P1 <= k < sp.P:
        return None
    return _enc(sp, bias + par, k), None


def build_s1(sp, j, v):
    k = 2 * j + 1
    bias = sp.bias
    if v == 0:
        return _enc(sp, bias, sp.P1 + k), None
    if v == 1:
        return _enc(sp, bias + 1, sp.P - k), None
    if v == 2:
        return _enc(sp, bias - 1, sp.P - k), None
    return _enc(sp, bias + 510, sp.P1 + k), None


def base_case(sp, idx):
    """The positive operand pair of an index (b is None for a square root), or None for a skip."""
    seg, i0 = sp.locate(idx)
    j, v = i0 >> 2, i0 & 3
    if seg == "F3a":
        return build_f3a(sp, j, v)
    if seg == "F3b":
        return build_f3b(sp, j, v)
    if seg == "F2":
        return build_f2(sp, j, v)
    if seg == "F1":
        return build_f1(sp, j, v)
    if seg == "F0A":
        return build_f0(sp, "A", j, v)
    if seg == "F0D":
        return build_f0(sp, "D", j, v)
    if seg == "F0K":
        return build_f0(sp, "K", j, v)
    if seg == "S1":
        return build_s1(sp, j, v)
    return build_s0(sp, j, v)


def gen(mode, idx):
    """The k slots of an index: each None (a skip) or (a, b) with the slot's signs applied."""
    sp = SPACES[mode]
    base = base_case(sp, idx)
    if sp.k == 1:
        return [None if base is None else (base[0], None)]
    sign = 1 << (sp.w - 1)
    return [None if base is None else (base[0] | (sign if s & 1 else 0), base[1] | (sign if s & 2 else 0))
            for s in range(4)]


# ------------------------------------------------------------------------------------------------------------
# the exact classification: written from the definitions; its arithmetic shares nothing with the builders, and
# verify takes its operands from them (and, for a skipped F0 index, its divisor from f0_divisor)
# ------------------------------------------------------------------------------------------------------------

def decode(sp, bits):
    """(sign, significand integer, t): the finite number (-1)^sign sig 2^t, exactly."""
    p = sp.p
    sign = bits >> (sp.w - 1)
    e = (bits >> (p - 1)) & ((1 << (sp.w - p)) - 1)
    f = bits & (sp.P1 - 1)
    if e == 0:
        return sign, f, 1 - sp.bias - (p - 1)
    assert e != (1 << (sp.w - p)) - 1, "an infinity or NaN"
    return sign, sp.P1 | f, e - sp.bias - (p - 1)


def _pow2(e):
    return Fraction(1 << e) if e >= 0 else Fraction(1, 1 << -e)


def _floor_log2(q):
    """floor(log2 q) of a positive Fraction, exactly: the bit lengths bracket it, one comparison decides."""
    n, d = q.numerator, q.denominator
    e = n.bit_length() - d.bit_length()                 # 2^(e-1) < n / d < 2^(e+1)
    if (n << max(-e, 0)) < (d << max(e, 0)):            # n / d < 2^e
        e -= 1
    return e


def div_class(sp, a, b):
    """The exact position of |a / b| on the rounding grid. Returns a dict:
    eq (floor log2 of the quotient), g (the grid's exponent: ulp = 2^g), n/d (the quotient in grid units, reduced),
    n_mid (the integer N of the midpoint distance: |N| / d half-grid units, N = 0 for an exact tie),
    n_rep (the integer N' = n - j d for the nearest grid point j), exact (d = 1), strip (below the smallest normal)."""
    _, sa, ta = decode(sp, a)
    _, sb, tb = decode(sp, b)
    q = Fraction(sa, sb) * _pow2(ta - tb)
    eq = _floor_log2(q)
    g = max(eq, sp.emin) - (sp.p - 1)
    u = q / _pow2(g)
    n, d = u.numerator, u.denominator
    c = 2 * ((2 * n) // (2 * d)) + 1                    # the odd integer nearest 2 u
    j = n // d
    if 2 * (n - j * d) > d:
        j += 1
    return {"eq": eq, "g": g, "n": n, "d": d, "n_mid": 2 * n - c * d, "n_rep": n - j * d,
            "exact": d == 1, "strip": eq < sp.emin}


def sqrt_class(sp, x):
    """The exact position of sqrt(x) against the midpoints of the result's grid: D = 4 y - (2 J + 1)^2 is the
    signed distance of x from the square of the nearest midpoint, in units 2^-2p of a root in [1, 2) (the
    study's d is |D|); J is the root's integer part in grid units; exact when x is a perfect square of the grid."""
    p = sp.p
    _, sig, t = decode(sp, x)
    e2 = sig.bit_length() - 1 + t                       # floor(log2 x)
    er = e2 // 2
    c = er - (p - 1)
    y = Fraction(sig) * _pow2(t - 2 * c)
    assert y.denominator == 1
    y = y.numerator
    jj = isqrt(y)
    assert sp.P1 <= jj < sp.P
    return {"D": 4 * y - (2 * jj + 1) ** 2, "J": jj, "er": er, "exact": jj * jj == y}


def independent_dividends(sp, my, target, sign):
    """The dividend significands mx in [2^(p-1), 2^p) with N = +-1 for an odd divisor, by the two-binade
    congruences: mx 2^k = sign (mod my) for mx in [my, 2^p) (a quotient in [1, 2)), and mx 2^(k+1) = sign (mod my)
    for mx in [2^(p-1), my) (a quotient in (1/2, 1)); k = p (midpoint) or p - 1 (representable). Different from
    the builders' single window with the doubling, so it also confirms a skip."""
    p = sp.p
    kk = p if target == 0 else p - 1
    out = []
    for e, lo, hi in ((kk, my, sp.P), (kk + 1, sp.P1, my)):
        s = pow(1 << e, -1, my) % my
        s = s if sign == 0 else (my - s) % my
        mx = s + ((lo - s + my - 1) // my) * my         # the least solution at or above lo
        if mx < hi:
            out.append(mx)
    return out


def _check(cond, name, detail):
    if not cond:
        raise AssertionError("%s: %s" % (name, detail))


def verify(mode, idx):
    """Exact verification of one index: every slot's operands against the family's claim, in integers. Returns
    the number of cases (0 for a skip); raises AssertionError('<check name>: <detail>') on a failure."""
    sp = SPACES[mode]
    seg, i0 = sp.locate(idx)
    j, v = i0 >> 2, i0 & 3
    slots = gen(mode, idx)
    p, w = sp.p, sp.w
    if sp.k == 1:
        if slots[0] is None:
            if seg == "S0":
                _verify_s0_skip(sp, j, v)
            return 0
        x = slots[0][0]
        cl = sqrt_class(sp, x)
        if seg == "S0":
            m = j // 2 if j % 2 == 0 else -((j + 1) // 2)
            rho = 8 * m + 1
            _check(cl["D"] == -rho and not cl["exact"],
                   "S0 odd-square input: the nearest input is rho 2^-2p from the square of a midpoint",
                   "idx %d: D = %d, rho = %d" % (idx, cl["D"], rho))
        else:
            k = 2 * j + 1
            _check(abs(cl["D"]) == k * k and not cl["exact"], "S1 sqrt(1 + k ulp) family: |D| = k^2",
                   "idx %d: D = %d, k^2 = %d" % (idx, cl["D"], k * k))
        return 1
    signs = [(s & 1, (s >> 1) & 1) for s in range(4)]
    if slots[0] is None:
        if seg.startswith("F0"):
            stream = seg[2]
            my = f0_divisor(sp, stream, j)
            _check(independent_dividends(sp, my, v >> 1, v & 1) == [],
                   "F0 skip is genuine: no dividend has |N| = 1", "idx %d: my = %d" % (idx, my))
        else:
            _check(False, "only F0 skips", "idx %d in %s skipped" % (idx, seg))
        return 0
    for s, (a, b) in enumerate(slots):
        _check(a >> (w - 1) == signs[s][0] and b >> (w - 1) == signs[s][1], "slot signs",
               "idx %d slot %d" % (idx, s))
    a, b = slots[0]
    cl = div_class(sp, a, b)
    _, sa, ta = decode(sp, a)
    _, sb, tb = decode(sp, b)
    if seg.startswith("F0"):
        target, nsgn = v >> 1, v & 1
        want = -1 if nsgn else 1
        got = cl["n_mid"] if target == 0 else cl["n_rep"]
        _check(got == want and cl["d"] == sb and not cl["exact"],
               "F0 closest approach: N = +-1 exactly, denominator the divisor",
               "idx %d: N = %d (want %d), d = %d, divisor %d" % (idx, got, want, cl["d"], sb))
        my = sb
        _check(sa in independent_dividends(sp, my, target, nsgn),
               "F0 dividend is a solution of the two-binade congruence", "idx %d" % idx)
    elif seg == "F1":
        q = Fraction(sa, sb) * _pow2(ta - tb)
        ob = sb >> ((sb & -sb).bit_length() - 1)        # the odd parts of the divisor and of the quotient
        oq = q.numerator >> ((q.numerator & -q.numerator).bit_length() - 1)
        h = (p - 1) // 2
        _check(cl["exact"], "F1 exact quotient: the quotient is a representable number (d = 1)",
               "idx %d: d = %d" % (idx, cl["d"]))
        _check(ob.bit_length() <= h and oq.bit_length() <= h and oq % 2 == 1,
               "F1 odd parts: the divisor's and the quotient's odd parts are below 2^((p-1)/2)", "idx %d" % idx)
        _check(cl["strip"] == (v == 3), "F1 exact quotient is subnormal in variant 3 only",
               "idx %d: eq = %d" % (idx, cl["eq"]))
    elif seg == "F2":
        k = j + 1
        av = Fraction(sa) * _pow2(ta)
        bv = Fraction(sb) * _pow2(tb)
        _check(av == (1 if v < 2 else 2 - Fraction(1, 1 << (p - 1))), "F2 dividend is 1.0 or 2 - ulp",
               "idx %d: a = %s" % (idx, av))
        want_b = 1 + Fraction(k, 1 << (p - 1)) if v & 1 == 0 else 1 - Fraction(k, 1 << p)
        _check(bv == want_b, "F2 divisor is 1 + k ulp or 1 - k ulp", "idx %d: b = %s, want %s" % (idx, bv, want_b))
    elif seg == "F3a":
        s = j + 1
        _check(cl["n_mid"] == 0 and cl["d"] == 2 and cl["strip"] and cl["eq"] == sp.emin - s,
               "F3a tie in the subnormal strip: the exact quotient is a half-integer of the grid, s places below",
               "idx %d: N = %d, d = %d, eq = %d, want eq %d" % (idx, cl["n_mid"], cl["d"], cl["eq"], sp.emin - s))
        _check(sb == sp.P1, "F3a divisor is a power of two", "idx %d" % idx)
    elif seg == "F3b":
        eq = j - (2 * sp.bias - 1)
        pow2, other = (sb, sa) if v < 2 else (sa, sb)
        _check(pow2 == sp.P1, "F3b one operand is a power of two", "idx %d" % idx)
        _check(other == (sp.P - 1 if v in (0, 2) else 3 << (p - 2)),
               "F3b the other significand is all ones (variants 0, 2) or 1.5 (1, 3)", "idx %d" % idx)
        _check(ta - tb == eq, "F3b the operand exponents differ by the designed quotient exponent",
               "idx %d: %d against %d" % (idx, ta - tb, eq))
        want = eq if v < 2 else eq - 1                  # a = 2 - ulp or 1.5 over 2^m, then 2^m over a significand
        _check(cl["eq"] == want, "F3b the quotient's binade, exactly", "idx %d: eq %d, want %d" % (idx, cl["eq"], want))
    return sp.k


def _verify_s0_skip(sp, j, v):
    """A skipped S0 index has no root in range: by a second method (a search over every residue bit by bit)."""
    p = sp.p
    m = j // 2 if j % 2 == 0 else -((j + 1) // 2)
    rho = 8 * m + 1
    par, r = v >> 1, v & 1
    s = p + 1 + par
    roots = [u for u in (1, 3, 5, 7) if (u * u - rho) % 8 == 0]
    for b in range(3, s):
        nxt = []
        for u in roots:
            for c in (u, u + (1 << b)):
                if (c * c - rho) % (1 << (b + 1)) == 0:
                    nxt.append(c)
        roots = nxt
    inr = sorted(u for u in roots if sp.P <= u < 2 * sp.P and (u * u < (1 << (2 * p + 1))) == (par == 0))
    if r < len(inr):
        k = (inr[r] ** 2 + (1 << (s - 1))) >> s
        _check(not sp.P1 <= k < sp.P, "S0 skip is genuine: no root of rho in range",
               "j %d v %d: root %d is in range" % (j, v, inr[r]))


# ------------------------------------------------------------------------------------------------------------
# the command line
# ------------------------------------------------------------------------------------------------------------

def fmt_hex(sp, x):
    return "0x%0*x" % (sp.w // 4, x)


def dump_lines(mode, lo, hi):
    sp = SPACES[mode]
    out = []
    for idx in range(lo, hi):
        for s, c in enumerate(gen(mode, idx)):
            if c is None:
                out.append("%d %d skip" % (idx, s))
            elif c[1] is None:
                out.append("%d %d %s" % (idx, s, fmt_hex(sp, c[0])))
            else:
                out.append("%d %d %s %s" % (idx, s, fmt_hex(sp, c[0]), fmt_hex(sp, c[1])))
    return out


def space_lines(mode):
    sp = SPACES[mode]
    out = ["%s k=%d total=%d" % (mode, sp.k, sp.total)]
    out += ["%s %d %d" % seg for seg in sp.segs]
    return out


def count_lines(mode, lo, hi):
    """Per segment of [lo, hi): its indices, cases (k a built index) and skipped slots, then the total, then the longest
    run of consecutive skipped indices - what the tool's `hard-count` prints (the exact count behind
    cases + skipped = k x indices; the run is what the refusal of an all-skipped slice must stay below)."""
    sp = SPACES[mode]
    out, ti, tc, ts, run, maxrun = [], 0, 0, 0, 0, 0
    for name, start, count in sp.segs:
        a_lo, a_hi = max(lo, start), min(hi, start + count)
        if a_lo < a_hi:
            built = 0
            for i in range(a_lo, a_hi):
                if base_case(sp, i) is None:
                    run += 1
                    maxrun = max(maxrun, run)
                else:
                    built += 1
                    run = 0
            n = a_hi - a_lo
            out.append("%s %d %d %d" % (name, n, built * sp.k, (n - built) * sp.k))
            ti, tc, ts = ti + n, tc + built * sp.k, ts + (n - built) * sp.k
    out.append("total %d %d %d" % (ti, tc, ts))
    out.append("maxskip %d" % maxrun)
    return out


def sample_indices(sp, n, seed):
    """Every index of a segment up to SMALL_SEGMENT, else the segment's first and last 2 n // 4 and n // 2 drawn
    from a fixed mix of the seed: deterministic."""
    out = []
    for name, start, count in sp.segs:
        if count <= SMALL_SEGMENT:
            out += range(start, start + count)
            continue
        q = max(n // 4, 1)
        out += range(start, start + q)
        out += range(start + count - q, start + count)
        out += [start + mix64(seed ^ (start << 8) ^ i) % count for i in range(n - 2 * q)]
    return out


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")            # the dump is compared byte for byte with the C tool's
    except (AttributeError, ValueError):
        pass
    if len(argv) >= 3 and argv[1] == "space" and argv[2] in SPACES:
        print("\n".join(space_lines(argv[2])))
        return 0
    if len(argv) == 5 and argv[1] == "dump" and argv[2] in SPACES:
        print("\n".join(dump_lines(argv[2], int(argv[3], 0), int(argv[4], 0))))
        return 0
    if len(argv) == 5 and argv[1] == "count" and argv[2] in SPACES:
        print("\n".join(count_lines(argv[2], int(argv[3], 0), int(argv[4], 0))))
        return 0
    if len(argv) >= 3 and argv[1] in ("verify", "stats") and argv[2] in SPACES:
        mode = argv[2]
        n = int(argv[3], 0) if len(argv) > 3 else 2000
        seed = int(argv[4], 0) if len(argv) > 4 else 1
        sp = SPACES[mode]
        idxs = sample_indices(sp, n, seed)
        per = {}
        for idx in idxs:
            seg = sp.locate(idx)[0]
            try:
                cases = verify(mode, idx) if argv[1] == "verify" else (sp.k if gen(mode, idx)[0] else 0)
            except AssertionError as e:
                print("FAILED %s" % e)
                return 1
            st = per.setdefault(seg, [0, 0, 0])
            st[0] += 1
            st[1] += 1 if cases else 0
            st[2] += cases
        for name, start, count in sp.segs:
            st = per[name]
            print("%-4s %9d indices %9d checked %9d built %5.1f%% skipped, %9d cases" % (
                name, count, st[0], st[1], 100.0 * (st[0] - st[1]) / st[0], st[2]))
        print("%s: %d indices checked, every case verified in exact integers" % (mode, len(idxs)))
        return 0
    print(__doc__.split("usage:")[1].rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
