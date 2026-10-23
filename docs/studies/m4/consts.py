# M4 model: the irrational constants beside the rounding boundaries
# (scratch; the study's 3.5). Exact rationals: pi to 4,000 bits.
#
# For K = pi/4, pi/2, 3pi/4 and pi at each format: the distance from K to
# the nearest grid point (the directed attributes' boundaries) and to the
# nearest midpoint (rne's and rmm's), relative to K, in units of the bound
# 2^-(p+G) (so in Bv). A lane whose answer is K (atan(+-inf), the axes and
# diagonals of atan2, acos(0), acos(-1)) marks only if that distance is
# under 1 Bv.
#
# Then the nearest boundaries below pi/2 and, for each, the arguments whose
# correction term lands on it: atan(x) = pi/2 - 1/x + ..., acos(x) =
# pi/2 - x - ..., and the size of the window of arguments within Bv,
# COMPUTED: about Bv / |f'(x0)| / ulp(x0).
#
#   python consts.py [FMT ...]

import sys
from fractions import Fraction

from m4core import FORMATS, enc, dec, pi_frac, RNE, RTZ
from m4inv import GUARD


def _ilog2(n):
    import math
    s = max(0, n.bit_length() - 60)
    return s + math.log2(n >> s)


def lg2(q):
    q = abs(Fraction(q))
    if q == 0:
        return float("-inf")
    return _ilog2(q.numerator) - _ilog2(q.denominator)


def ulp_of(fmt, v):
    """The grid step at the positive value v (normal)."""
    b = enc(fmt, v, RTZ)
    return dec(fmt, b + 1) - dec(fmt, b)


def report(fmt):
    p = fmt.prec
    G = GUARD[fmt.name]
    pi = pi_frac()
    print(f"{fmt.name}: p = {p}, G = {G}")
    for nm, K in (("pi/4", pi / 4), ("pi/2", pi / 2), ("3pi/4", 3 * pi / 4),
                  ("pi", pi)):
        lo = dec(fmt, enc(fmt, K, RTZ))
        u = ulp_of(fmt, K)
        dg = min(K - lo, lo + u - K)
        mid = lo + u / 2
        dm = abs(K - mid)
        unit = K / 2 ** (p + G)
        print(f"  {nm:6s} below it {(K - lo) / u:.6f} ulp; to the grid "
              f"{float(dg / unit):.4g} Bv (2^{lg2(dg / K):.2f} of K), to a "
              f"midpoint {float(dm / unit):.4g} Bv (2^{lg2(dm / K):.2f})")
    # the boundaries nearest pi/2 from below, and the windows
    K = pi / 2
    lo = dec(fmt, enc(fmt, K, RTZ))
    u = ulp_of(fmt, K)
    Bv = K / 2 ** (p + G)
    print("  windows next to pi/2 (atan of a large x; acos of a small x):")
    for kind, bs in (("grid (rtz, rdn, rup)", [lo - j * u for j in range(3)]),
                     ("midpoint (rne, rmm)",
                      [lo + u / 2 - j * u for j in range(3)])):
        for b in bs:
            if b >= K:
                continue
            gap = K - b
            x0 = 1 / gap                       # atan: pi/2 - 1/x0 = b
            ux = ulp_of(fmt, x0)
            n_atan = 2 * Bv * x0 * x0 / ux     # |dx| < Bv x0^2
            ua = ulp_of(fmt, gap)
            n_acos = 2 * Bv / ua               # acos: |dx| < Bv
            print(f"    {kind}: pi/2 - b = 2^{lg2(gap):.3f}; atan centre "
                  f"x0 = 2^{lg2(x0):.3f}, about 2^{lg2(n_acos * 0 + n_atan):.1f} "
                  f"arguments within Bv; acos centre +-2^{lg2(gap):.3f}, about "
                  f"2^{lg2(n_acos):.1f}")


def main():
    names = sys.argv[1:] or ["fp32", "fp64", "fp128", "fp256"]
    for nm in names:
        report(FORMATS[nm])


if __name__ == "__main__":
    main()
