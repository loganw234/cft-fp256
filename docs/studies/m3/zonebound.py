# M3 model, send-back 1: the analytic bound on the logarithm's sum's
# capacity at fp64 (the study's 3.2, COMPUTED), beside the sampled budgets
# it bounds.
#
# Where |x| (1 + x for compound) is in [1/2, X_b), M1's reduction takes
# k = -1 and m' = 2|x|, so L = k + log2 m' cancels: X_b, the reduction's
# own boundary, is found here by bisection on the model's k (MEASURED).
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
# |v| is bounded on every lane whose k is -1 and |x| < 1 from the words'
# magnitudes (|F| < ln(241/128) < 0.64, |L_j| <= ln(16/9) < 0.58, so their
# ulps are at most 2^-53 and fe, L_l, nge at most 2^-54; IL2L < 2^-53;
# |lph| < 0.06 and nlpl < 2^-57; S = k + gh is exact there, so e = 0), and
# ulp(v)/2 <= 2^(floor(log2 |v|_max) - 53).
#
#   python zonebound.py

import math
from fractions import Fraction

from m3core import FORMATS, RNE, enc, dec
import m3pow as M

LN2 = math.log(2)
IL2H = 1 / LN2


def half_ulp(vmax):
    """ulp(v)/2 for |v| <= vmax at fp64."""
    return 2.0 ** (math.floor(math.log2(vmax)) - 53)


def boundary():
    fmt = FORMATS["fp64"]
    b = M.build("pown", fmt, RNE, n=1000)

    def kf(X):
        _r, _f, pr = M.run(b, "pown", (enc(fmt, Fraction(X)), 1000), ("kf",))
        return float(dec(fmt, pr["kf"]))
    a, c = 0.9, 0.99
    assert kf(a) == -1 and kf(c) == 0
    for _ in range(60):
        m = (a + c) / 2
        if kf(m) == -1:
            a = m
        else:
            c = m
    return a


def main():
    Xb = boundary()
    Lmin = -math.log2(Xb)
    print(f"the cancelling zone's top X_b = {Xb!r} ({Fraction(Xb).limit_denominator(1 << 12)}),"
          f" |L| >= {Lmin:.6f} there (MEASURED by bisection on k)")
    # the magnitudes, in the zone (k = -1, |x| < 1)
    fe = Ll = 2.0 ** -54
    nlpl = 2.0 ** -57 + 2.0 ** -58
    Fl1 = fe + Ll
    Fl = Fl1 + nlpl
    F = 0.64
    nge = 2.0 ** -54
    ngl1 = F * 2.0 ** -53 + nge
    ngl = IL2H * Fl + ngl1
    lo = ngl
    rows = [("a Fl1", Fl1, IL2H), ("b Fl", Fl, IL2H), ("c ngl1", ngl1, 1.0),
            ("d ngl", ngl, 1.0), ("e lo", lo, 1.0)]
    U = 0.0
    for name, vmax, c in rows:
        u = c * half_ulp(vmax)
        U += u
        print(f"  {name:7s} |v| <= 2^{math.log2(vmax):.2f}: ulp/2 <= 2^{math.log2(half_ulp(vmax)):.0f},"
              f" dL/dv {c:.4f}: {u / 2.0 ** -106:.3f} 2^-106 in L")
    print(f"  U, the sum's five roundings: {U / 2.0 ** -106:.3f} 2^-106 in L")
    # compound: 1 + x's low word moves r by rl = u_l 2^-k c; |u_l| <= 2^-54
    # where 1 + x < 1, 2^-k = 2, c <= 9/16; corr = rl yv, yv = 1/(1 + r) <= 1.07
    rl = 2.0 ** -54 * 2 * 9 / 16
    corr = rl * 1.07
    Flc = Fl1 + nlpl + corr
    nglc = IL2H * Flc + ngl1
    rowsc = [("a Fl1", Fl1, IL2H), ("b Fl", Flc, IL2H), ("c ngl1", ngl1, 1.0),
             ("d ngl", nglc, 1.0), ("e lo", nglc, 1.0),
             ("p nlpl-corr", nlpl + corr, IL2H), ("w rl", rl, IL2H * 1.07),
             ("w corr", corr, IL2H), ("w Newton", 2.0 ** -53, 3 * IL2H * rl)]
    Uc = 0.0
    for name, vmax, c in rowsc:
        Uc += c * half_ulp(vmax)
    print(f"  compound, with the low word's four (p, w): {Uc / 2.0 ** -106:.3f} 2^-106 in L")
    B1 = 2.0 ** -100
    B2 = 2.0 ** -101
    print("the design before send-back 1, Bv/|V| = 2^-97 + |t| 2^-100: the sum's"
          " capacity at the zone's top, ln2 U n / (2^-97 + n |L| 2^-100):")
    for n in (31, 100, 300, 1000, 3000, 10000, 12000):
        cap = LN2 * U * n / (2.0 ** -97 + n * Lmin * B1)
        print(f"  n = {n:6d}: {cap:.3f} Bv"
              + ("   (|t| past T_f: the top is screened)" if n * Lmin >= 1077 else ""))
    print(f"  n -> inf: {LN2 * U / (Lmin * B1):.3f} Bv; in closed form "
          f"{LN2 * U / 2.0 ** -100:.5f} n / (8 + {Lmin:.5f} n)")
    print("the fix, Bv/|V| >= |Y k| 2^-101 (k = -1): the capacity at most ln2 U / B2:")
    print(f"  the sum's five: {LN2 * U / B2:.3f} Bv; compound's nine: "
          f"{LN2 * Uc / B2:.3f} Bv (every lane whose k is -1 and |x| < 1)")


if __name__ == "__main__":
    main()
