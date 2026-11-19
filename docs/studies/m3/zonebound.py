# M3 model, send-back 1 (and 2): the analytic bound on the logarithm's
# sum's capacity at fp64 (the study's 3.2, COMPUTED), beside the sampled
# budgets it bounds.
#
# Where |x| (1 + x for compound) is in [1/2, X_b), M1's reduction takes
# k = -1 and m' = 2|x|, so L = k + log2 m' cancels: X_b, the reduction's
# own boundary, is found here by bisection on the model's k (MEASURED), and
# so are its cells, C = 9 to 16 (c = C/16), by bisection on the model's c.
#
# The sum (m3pow.py, "log-sum", M1's _build_log_dw line for line):
#   F, fe = Fast2Sum(L_j, lph)          exact
#   Fl1 = RN(fe + L_l)                  rounding a
#   Fl  = RN(Fl1 - nlpl)                rounding b   (nlpl: the polynomial's
#                                                     low part, less corr for
#                                                     compound)
#   gh  = RN(F IL2H), nge = FMA residual          exact together
#   ngl1 = RN(F (-IL2L) + nge)          rounding c
#   ngl  = RN(Fl (-IL2H) + ngl1)        rounding d
#   S, e = Fast2Sum(k, gh)              exact
#   lo  = RN(e - ngl)                   rounding e
#   L   = Fast2Sum(S, lo)               exact
# A rounding's capacity is |dV/dv| ulp(v)/2; dV/dL = V ln2 Y, and dL/dv is
# IL2H = 1/ln2 for a and b (natural-log units) and 1 for c, d and e. Each
# |v| is bounded from the words' magnitudes on every lane whose k is -1 and
# |x| < 1, and ulp(v)/2 <= 2^(floor(log2 |v|_max) - 53). S = k + gh is
# exact where gh >= 1/2; below, Fast2Sum's error e is at most ulp(S)/2 =
# 2^-54, which leaves lo in the same binade (send-back 2, VM3S's note).
#
# compound's 1 + x is the double word (u_h, u_l), |u_l| <= 2^-54 where
# u_h < 1, and its low word moves r by r_l = u_l 2^-k c, c = C/16 the
# cell's; corr = r_l yv, yv = 1/(1 + r) by Newton steps, adds four
# roundings of the same scale. The first count took c <= 9/16, which holds
# only in the top cell (send-back 2: c is 1 in the cell C = 16, at the
# zone's bottom); so the bound is taken cell by cell, each cell's c with
# its own F, r and |L|, and over the whole zone with c <= 1 as a check.
#
#   python zonebound.py

import math
from fractions import Fraction

import mpmath

from m3core import FORMATS, RNE, enc, dec
import m3pow as M

LN2 = math.log(2)
with mpmath.workprec(200):
    IL2H = float(1 / mpmath.log(2))          # RN(1/ln 2), as the bank holds it
# |IL2L| < 2^-53, the bound the first count took (its value, 2^-55.4, would
# lower U; the bound is kept, so the figures of send-back 1 stand)
IL2L = 2.0 ** -53
B1 = 2.0 ** -100
B2 = 2.0 ** -101
FMT = FORMATS["fp64"]


def half_ulp(vmax):
    """ulp(v)/2 for |v| <= vmax at fp64 (0 for v = 0)."""
    if vmax <= 0:
        return 0.0
    return 2.0 ** (math.floor(math.log2(vmax)) - 53)


def _probe(b, X, name):
    _r, _f, pr = M.run(b, "pown", (enc(FMT, Fraction(X)), 1000), (name,))
    return float(dec(FMT, pr[name]))


def boundary(b):
    a, c = 0.9, 0.99
    assert _probe(b, a, "kf") == -1 and _probe(b, c, "kf") == 0
    for _ in range(60):
        m = (a + c) / 2
        if _probe(b, m, "kf") == -1:
            a = m
        else:
            c = m
    return a


def cells(b, Xb):
    """[(C, Xa, Xz)]: the zone's cells, X in [Xa, Xz) taking c = C/16."""
    pts = [0.5 + (Xb - 0.5) * i / 800 for i in range(800)] + [Xb]
    cs = [round(16 * _probe(b, X, "cc")) for X in pts]
    out, start = [], 0.5
    for i in range(1, len(pts)):
        if cs[i] != cs[i - 1]:
            a, z = pts[i - 1], pts[i]
            for _ in range(55):
                m = (a + z) / 2
                if round(16 * _probe(b, m, "cc")) == cs[i - 1]:
                    a = m
                else:
                    z = m
            out.append((cs[i - 1], start, z))
            start = z
    out.append((cs[-1], start, Xb))
    return out


def rows_for(Fmax, Lj, rmin, rmax, c, ghmin, compound):
    """The roundings' (name, |v| max, dL/dv) for one cell, or for the zone
    with each magnitude at its largest."""
    rabs = max(abs(rmin), abs(rmax))
    fe = half_ulp(Fmax) if Lj else 0.0           # F = lph exactly where L_j = 0
    Ll = half_ulp(Lj)
    nlpl = half_ulp(rabs * 1.01) + 2.0 ** -53 * rabs
    Fl1 = fe + Ll
    yv = 1 / (1 + min(rmin, 0.0))
    rl = 2.0 ** -54 * 2 * c if compound else 0.0
    corr = rl * yv
    Fl = Fl1 + nlpl + corr
    nge = half_ulp(Fmax * IL2H)
    ngl1 = Fmax * IL2L + nge
    ngl = IL2H * Fl + ngl1
    e = half_ulp(1 - ghmin) if ghmin < 0.5 else 0.0
    lo = e + ngl
    rows = [("a Fl1", Fl1, IL2H), ("b Fl", Fl, IL2H), ("c ngl1", ngl1, 1.0),
            ("d ngl", ngl, 1.0), ("e lo", lo, 1.0)]
    if compound:
        rows += [("p nlpl-corr", nlpl + corr, IL2H), ("w rl", rl, IL2H * yv),
                 ("w corr", corr, IL2H), ("w Newton", yv, 3 * IL2H * rl)]
    return rows


def U_of(rows):
    return sum(c * half_ulp(v) for _n, v, c in rows)


def main():
    b = M.build("pown", FMT, RNE, n=1000)
    Xb = boundary(b)
    Lmin = -math.log2(Xb)
    print(f"the cancelling zone's top X_b = {Xb!r} ({Fraction(Xb).limit_denominator(1 << 12)}),"
          f" |L| >= {Lmin:.6f} there (MEASURED by bisection on k)")
    # the sum's five over the whole zone, each magnitude at its largest
    five = rows_for(0.64, math.log(16 / 9), -0.0625, 0.0625, 0.0, 0.0, False)
    U = U_of(five)
    for name, vmax, c in five:
        print(f"  {name:7s} |v| <= 2^{math.log2(vmax):.2f}: ulp/2 <= 2^{math.log2(half_ulp(vmax)):.0f},"
              f" dL/dv {c:.4f}: {c * half_ulp(vmax) / 2.0 ** -106:.3f} 2^-106 in L")
    print(f"  U, the sum's five roundings: {U / 2.0 ** -106:.3f} 2^-106 in L"
          f" (e at most 2^-54 where gh < 1/2: lo stays in its binade)")
    print("the design before send-back 1, Bv/|V| = 2^-97 + |t| 2^-100: the sum's"
          " capacity at the zone's top, ln2 U n / (2^-97 + n |L| 2^-100):")
    for n in (31, 100, 300, 1000, 3000, 10000, 12000):
        cap = LN2 * U * n / (2.0 ** -97 + n * Lmin * B1)
        print(f"  n = {n:6d}: {cap:.3f} Bv"
              + ("   (|t| past T_f: the top is screened)" if n * Lmin >= 1077 else ""))
    print(f"  n -> inf: {LN2 * U / (Lmin * B1):.3f} Bv; in closed form "
          f"{LN2 * U / 2.0 ** -100:.5f} n / (8 + {Lmin:.5f} n)")
    print("the fix, Bv/|V| >= |Y k| 2^-101 (k = -1): the capacity at most ln2 U / B2:")
    print(f"  the sum's five, over the whole zone: {LN2 * U / B2:.3f} Bv")
    # compound over the whole zone with c <= 1 (each magnitude at its largest)
    whole = rows_for(0.64, math.log(16 / 9), -0.0625, 0.0625, 1.0, 0.0, True)
    print(f"  compound's nine over the whole zone with c <= 1, |L| B1 left out:"
          f" U = {U_of(whole) / 2.0 ** -106:.3f} 2^-106, {LN2 * U_of(whole) / B2:.3f} Bv")
    # compound cell by cell: each cell's c with its own F, r and |L|
    print("  compound's nine by the reduction's cells (c = C/16; Bv/|V| >= |Y| (|L| B1 + B2),"
          " |L| the cell's least):")
    worst = 0.0
    worst5 = 0.0
    for C, Xa, Xz in cells(b, Xb):
        ma, mz = 2 * Xa, 2 * Xz
        Fmax = math.log(mz)
        Lj = math.log(16 / C)
        rmin, rmax = ma * C / 16 - 1, mz * C / 16 - 1
        ghmin = math.log(ma) * IL2H
        Lc = -math.log2(Xz)
        rows = rows_for(Fmax, Lj, rmin, rmax, C / 16, ghmin, True)
        Uc = U_of(rows)
        cap = LN2 * Uc / (Lc * B1 + B2)
        cap5 = LN2 * U_of(rows_for(Fmax, Lj, rmin, rmax, 0.0, ghmin, False)) / (Lc * B1 + B2)
        worst, worst5 = max(worst, cap), max(worst5, cap5)
        print(f"    C = {C:2d}: X in [{Xa:.5f}, {Xz:.5f}), |L| >= {Lc:.4f}, r in "
              f"[{rmin:+.4f}, {rmax:+.4f}]: U = {Uc / 2.0 ** -106:.3f} 2^-106, {cap:.3f} Bv"
              f" (the five alone {cap5:.3f})")
    print(f"  compound's nine, the largest cell: {worst:.3f} Bv; the five's, by cell: {worst5:.3f} Bv"
          f" (every lane whose k is -1 and |x| < 1)")


if __name__ == "__main__":
    main()
