# M4 model: the unbiased index's failing lane (scratch; the study's 2.2 and
# 3.6, item 7): atan2 at d = 2 - 2^-12, n = 1/8 - 2^-15 - ulp (n's last bit
# set) through the unplanted fragment and the plant sterbenz-bias, at every
# format under rne and rtz: n_h / P, whether n_h - P is exact, |V - f| / Bv,
# the flag word, and equality with transcend.py. Kept after verifier-VM4S's
# note, so that the figures can be re-run from the tree.
#
#   python sbias_probe.py
from fractions import Fraction

import mpmath
from m4core import FORMATS, sf, dec, enc, evaluate2, RNE, RTZ, ATTRS
from m4inv import build
from m4harness import golden
from m4measure import true_value

for name in ("fp64", "fp128", "fp256", "fp32"):
    fmt = FORMATS[name]
    p = fmt.prec
    eps = Fraction(1, 2 ** 12)
    D = 2 - eps
    d = enc(fmt, D)
    assert dec(fmt, d) == D
    ulp_n = Fraction(1, 2 ** (p + 3))          # n in [1/16, 1/8)
    N = Fraction(1, 8) - eps / 8 - ulp_n
    n = enc(fmt, N)
    assert dec(fmt, n) == N
    args = (n, d)
    mpmath.mp.prec = 4 * p + 200
    for plant in (None, "sterbenz-bias"):
        for rnd in (RNE, RTZ):
            f = build(fmt, rnd, "atan2", plant=plant)
            b, fw, pr = evaluate2(f, args, want=["nh", "P", "Nh0", "Kk", "Vh", "Vl", "Bv"], full=True)
            gb, gf = golden(fmt, "atan2", args, rnd)
            nh, P_, N0 = (dec(fmt, pr[k]) for k in ("nh", "P", "Nh0"))
            V = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
            Bv = abs(dec(fmt, pr["Bv"]))
            T = true_value("atan2", args, fmt)
            r = abs(mpmath.mpf(V.numerator) / V.denominator - T) / (mpmath.mpf(Bv.numerator) / Bv.denominator)
            print(f"{name} {plant or 'none'} {sf.RND_NAMES[rnd]}: n_h/P {float(nh / P_) if P_ else 0:.6f}; "
                  f"n_h - P exact: {nh - P_ == N0}; |V - f|/Bv 2^{float(mpmath.log(r, 2)) if r else -999:.1f}; "
                  f"flag {fw:#x}; equal to transcend.py: {(b, fw) == (gb, gf)}", flush=True)
