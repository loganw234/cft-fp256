# Question 1's two choices at fp64, G = 46 (the study's) and G = 44
# (verifier-VM1's), measured side by side: the planners' K and D, the
# instructions, and log2(|V - true| / Bv) where each function's bound is
# thinnest - the reduction's ends (exp, exp2), expm1's 2^-k clamp, the log
# family's cancellation cells (k = -1, C = 9) and the C = 9 cell ends, and
# log1p's reduction path near its lower end (where the low word of 1 + x
# weighs most) - with every lane's answer against transcend.py (rne).
# usage: g44.py FMT NREGION SEED
import sys
import time
import random
from fractions import Fraction

import mpmath

from m1core import sf, evaluate, dec, enc, RNE
from m1exp import build_exp
from m1log import build_log, SMALL
from m1harness import FORMATS, tr
from m1measure import true_scaled, in_main

fmtname, nreg, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
fmt = FORMATS[fmtname]
p = fmt.prec
mpmath.mp.prec = 4 * p + 200
LN2 = mpmath.log(2)
LN2Q = Fraction(int(mpmath.floor(LN2 * 2 ** (p + 80))), 2 ** (p + 80))
t0 = time.perf_counter()


def uni(lo, hi, rng):
    return enc(fmt, lo + (hi - lo) * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))


def regions(fn, G, rng):
    n = nreg
    if fn in ("exp", "exp2"):
        unit = LN2Q / 8 if fn == "exp" else Fraction(1, 8)

        def near_half(lo_n, hi_n):
            k = rng.randint(lo_n, hi_n)
            d = Fraction(rng.randint(0, 3 * 10 ** 6), 10 ** 10)
            s = 1 if rng.random() < 0.5 else -1
            return enc(fmt, (k + s * (Fraction(1, 2) - d)) * unit)
        return {"n + 1/2, |n| <= 24": [near_half(-24, 24) for _ in range(n)],
                "n + 1/2, any n": [near_half(8 * (fmt.emin - p) + 16, 8 * (fmt.emax + 1) - 16) for _ in range(n)]}
    if fn == "expm1":
        kc = p + G + 2                     # 2^-k is dropped for k > kc
        return {"k near the 2^-k clamp": [uni((kc - 3) * LN2Q, (kc + 4) * LN2Q, rng) for _ in range(n)],
                "n = 0": [uni(-LN2Q / 16, LN2Q / 16, rng) for _ in range(n)]}
    if fn in ("log", "log2"):
        return {"x in [0.93, 0.945] (k = -1, C = 9)": [uni(Fraction(93, 100), Fraction(945, 1000), rng) for _ in range(n)],
                "x in [1.75, 1.9] (C = 9 cells)": [uni(Fraction(175, 100), Fraction(19, 10), rng) for _ in range(n)]}
    out = {}
    for lo, hi, nm in ((SMALL, Fraction(1, 16), "[15/256, 2^-4)"), (Fraction(1, 16), Fraction(1, 8), "[2^-4, 2^-3)")):
        out["+" + nm] = [uni(lo, hi, rng) for _ in range(n)]
        out["-" + nm] = [sf.negate(fmt, uni(lo, hi, rng)) for _ in range(n)]
    return out


for fn in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
    for G in (46, 44):
        rng = random.Random(seed)            # the same arguments for both G
        f = build_exp(fmt, RNE, fn, G=G) if fn.startswith("exp") else build_log(fmt, RNE, fn, G=G)
        row = []
        wrong = marked = 0
        for rname, xs in regions(fn, G, rng).items():
            worst = -1e9
            for xa in xs:
                bits, fw, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv", "Ek"], full=True)
                gb, gf = tr.compute(fmt, fn, xa, 0, RNE)
                if fw & 0x80:
                    marked += 1
                elif (bits, fw) != (gb, gf):
                    wrong += 1
                if not in_main(fmt, fn, xa):
                    continue
                k = pr["Ek"] - fmt.bias - f.meta["OFF"] if fn.startswith("exp") else 0
                vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
                tv = true_scaled(fmt, fn, xa, k)
                err = abs(mpmath.mpf(vh.numerator) / vh.denominator + mpmath.mpf(vl.numerator) / vl.denominator - tv)
                if err:
                    worst = max(worst, float(mpmath.log(err / (mpmath.mpf(bv.numerator) / bv.denominator), 2)))
            row.append(f"{rname} {worst:+.2f}")
        print(f"{fmtname} {fn:5s} G {G}: K {f.meta['K']} D {f.meta['D']} insns {len(f.body)} words {len(f.words)};"
              f" {nreg} a region, rne: wrong {wrong}, marked {marked}; worst log2(err/Bv): " + "; ".join(row)
              + f"  [{time.perf_counter() - t0:.0f}s]", flush=True)
print(f"done {time.perf_counter() - t0:.0f}s")
