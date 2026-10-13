# M2 model: the reduction's parameters and the static analysis of its
# pieces (scratch).
#
# The reduction (design A, the study's 2.2). x = M 2^e, M the p-bit integer
# significand, e = E - (p-1). 2/pi = sum_k c_k 2^-((k+1)b), c_k b-bit
# integers, stored as integer-valued floats. The bucket g is chosen by the
# exponent so that every chunk before c_(g-1) gives a multiple of 4:
#     g - 1 = floor(G0 / b),  G0 = e - 2 = E - p - 1,
#     sigma = e - g b = G0 + 2 - b - (g-1) b   in [2-b, 1],
# and then
#     x 2/pi = 2^sigma S,   S = sum_j M c_(g-1+j) 2^-(jb)   (mod 4),
# so S is reduced modulo m = 2^(2-sigma), its quadrant unit is
# U = 2^-sigma, and t = (S mod U, centred) 2^sigma. Every product
# T_j = M c 2^-(jb) has a FIXED grid, 2^-(jb), and fixed bounds, whatever
# sigma is: that is why the reduction works in S's units ("S-hat"), and
# what this module analyses, position by position, over every chunk that
# can stand at the position. Chunks before c_0 (small arguments) are
# zero words: Z of them.

import math
from fractions import Fraction

from m2const import chunks

# The deepest cancellation the reduction must carry, |t| >= 2^-(lost+1).
# fp32 and fp64: READ, docs/TRANSCENDENTALS.md, every binade searched by
# host/tools/pi_worstcase.py. fp128 and fp256: MEASURED here over the stated
# range [1, 2^1024) by worst_range.py (pi_worstcase's own search, every
# binade). The docs' 121 and 245 are their whole ranges SAMPLED (every 16th
# and every 512th binade). fp128's range alone reaches 123 (value exponent
# 909), past the docs' figure: a sampled worst is a lower bound, and here it
# sizes the window. fp256's range reaches 244 (value exponents 239, 606,
# 964), and the plan keeps 245, which covers it.
LOST = {"fp32": 29, "fp64": 61, "fp128": 123, "fp256": 245}


class Plan:
    pass


def ulp_exp(v, p):
    """floor(log2 v) - p + 1 for v > 0 (the exponent of v's ulp)."""
    return (v.numerator.bit_length() - v.denominator.bit_length()
            - (1 if Fraction(2) ** (v.numerator.bit_length()
                                    - v.denominator.bit_length()) > v else 0)
            ) - p + 1


def plan(fmt, G, lost, Emax, Egate, delta=3, b=None, L=None, bottom=None,
         low_cap=4):
    """plan_b, at the widest b whose coarse sum the actual chunks keep
    exact: three terms of at most m <= 2^b on the grid of P_1's ulp, which
    a chunk with leading zeros makes finer (searched downward)."""
    P = plan_b(fmt, G, lost, Emax, Egate, delta, b, L, bottom, low_cap)
    while True:
        pgrid1 = P.rows[1][3]
        if math.log2(3) + P.b - min(0, pgrid1) < fmt.prec:
            return P
        if b is not None:
            raise ValueError(f"b = {b}: the coarse sum is not exact")
        P = plan_b(fmt, G, lost, Emax, Egate, delta, P.b - 1, L, bottom,
                   low_cap)


def plan_b(fmt, G, lost, Emax, Egate, delta=3, b=None, L=None, bottom=None,
           low_cap=4):
    """The reduction's parameters at fmt for guard G, a measured
    cancellation `lost` (|t| >= 2^-(lost+1)), arguments |x| < 2^(Emax+1)
    and down to 2^Egate (the smallest a tiny gate passes):
      budget   t's absolute error allowed: 2^-(p+G+delta+lost+1)
      L        chunks a lane: the tail 2^(1+p-(L-1)b) within budget/4
      bottom   the S-hat exponent below which a piece may round: the lower
               pieces' double-word sum within budget/4
      b        the widest chunk for which the coarse sum, the exact
               combination and the window all hold (or as given)."""
    P = Plan()
    p = fmt.prec
    P.fmt, P.G, P.lost, P.delta = fmt, G, lost, delta
    P.budget = -(p + G + delta + lost + 1)            # log2 of t's error
    if bottom is None:
        # lower pieces < low_cap 2^bottom_abs, summed with error <= 3u^2 |sum|
        # bottom_abs + log2(low_cap) + log2(3) - 2p <= budget - 2
        babs = math.floor(P.budget - 2 + 2 * p - math.log2(3 * low_cap))
        bottom = babs - 1                              # S-hat: sigma <= 1
    P.bottom = bottom
    if b is None:
        # the exact combination: TwoSum(f, mid_h) leaves e <= 2^(b-2-p)
        # and mid_l <= 2^(b-3-p), both on grid 2^bottom; their sum is one
        # word exactly when (b - 2 - p + 0.58) - bottom <= p, so
        # b <= 2p + 1 + bottom; the coarse sum's exactness wants
        # b <= p - 4 (three terms within m <= 2^b, on grid 1/2)
        b = min(p - 4, 2 * p + 1 + bottom)
    P.b = b
    if L is None:
        L = 1 + math.ceil((1 + p - (P.budget - 2)) / b)
    P.L = L
    P.Emax, P.Egate = Emax, Egate
    G0min, G0max = Egate - p - 1, Emax - p - 1
    P.gm1_min = G0min // b
    P.gm1_max = G0max // b
    P.Z = max(0, -P.gm1_min)
    P.nchunks = P.gm1_max + L          # c_0 .. c_(nchunks-1)
    P.K = P.Z + P.nchunks              # the stored words
    P.bits = P.nchunks * b
    P.c = chunks(b, P.nchunks)
    P.words = [0] * P.Z + P.c          # the table the window reads
    P.shifts = P.gm1_max - P.gm1_min + 1
    P.rows = analyse(P)
    return P


def positions(P):
    """[(j, cmin_nonzero, cmax, any_zero)] over the chunks that can stand
    at position j, for every bucket the range has."""
    out = []
    for j in range(P.L):
        cs = []
        for gm1 in range(P.gm1_min, P.gm1_max + 1):
            k = gm1 + j
            cs.append(P.c[k] if k >= 0 else 0)
        nz = [c for c in cs if c]
        out.append((j, min(nz) if nz else 0, max(cs), 0 in cs))
    return out


def analyse(P):
    """Static bounds of every piece in S-hat units: for position j,
    T_j in [2^(p-1) cmin, (2^p - 1) cmax] 2^-(jb) on grid 2^-(jb); the
    TwoProd pieces P_j = RN(T_j) (grid >= max(2^-(jb), ulp(Tmin))) and
    rho_j = T_j - P_j (|rho_j| <= ulp(Tmax), grid 2^-(jb)). Returns rows of
    (j, log2 Tmin, log2 Tmax, P grid exp, rho bound exp, rho grid exp)."""
    p = P.fmt.prec
    rows = []
    for j, cmin, cmax, z in positions(P):
        if cmax == 0:
            rows.append((j, None, None, None, None, None))
            continue
        tmin = Fraction((1 << (p - 1)) * cmin, 1 << (j * P.b))
        tmax = Fraction(((1 << p) - 1) * cmax, 1 << (j * P.b))
        ue_min = ulp_exp(tmin, p)
        ue_max = ulp_exp(tmax, p)
        pgrid = max(-j * P.b, ue_min)
        rows.append((j, math.log2(tmin), math.log2(tmax), pgrid, ue_max,
                     -j * P.b))
    return rows
