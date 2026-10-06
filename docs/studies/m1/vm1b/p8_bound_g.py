# VM1 item 2: the bound, many more samples than M1's 2,000 a function, with the sampling weighted to where
# the terms are largest. log2(|V - true| / Bv) per lane, mpmath at 4p+200 bits as the reference (independent of
# transcend.py). The V is attribute-independent, so one attribute (rne) is used.
# usage: p8_bound_g.py FN FMT NSAMPLES SEED BUDGET [G]   (VM1's p8_bound.py with a G argument: the only change, besides the import)
import math
import random
import sys
import time
from vm1blib import *   # noqa

fn, fmtname, ns, seed, budget = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
G = int(sys.argv[6]) if len(sys.argv) > 6 else 46
fmt = FORMATS[fmtname]
p = fmt.prec
mw = fmt.man_w
rng = random.Random(seed)
mpmath.mp.prec = 4 * p + 200
LN2 = mpmath.log(2)
t0 = time.perf_counter()
f = build(fmt, RNE, fn, G=G)
print(f"{fn} {fmtname} G {G}: K {f.meta['K']} D {f.meta['D']} insns {len(f.body)}", flush=True)


def frac_rand(lo, hi):
    return Fraction(rng.randint(0, 10 ** 12), 10 ** 12) * (hi - lo) + lo


def pick_delta():
    r = rng.random()
    if r < 0.4:
        return Fraction(rng.randint(-499999, 499999), 10 ** 6)
    if r < 0.8:                                   # near the edge of the reduction's interval, both signs
        s = 1 if rng.random() < 0.5 else -1
        return s * (Fraction(1, 2) - Fraction(rng.randint(0, 3000), 10 ** 7))
    return Fraction(rng.randint(-5, 5), 100)


def sample():
    nlo = 8 * (fmt.emin - p)
    nhi = 8 * (fmt.emax + 1)
    if fn in ("exp", "exp2"):
        if rng.random() < 0.5:
            n = rng.randint(-24, 24)
        else:
            n = rng.randint(nlo + 16, nhi - 16)
        d = pick_delta()
        v = (Fraction(n) + d) * (fr(LN2) if fn == "exp" else 1) / 8
        return enc(fmt, v)
    if fn == "expm1":
        r = rng.random()
        n = rng.randint(-24, 24) if r < 0.6 else rng.randint(-8 * (p + 3), nhi - 16)
        d = pick_delta()
        return enc(fmt, (Fraction(n) + d) * fr(LN2) / 8)
    if fn in ("log", "log2"):
        k = rng.choice([0, 0, -1, 1, 2, -2, rng.randint(fmt.emin, fmt.emax - 1)])
        i = rng.randint(0, 511)
        r = rng.random()
        mant = (i * 2 ** (mw - 9) + (rng.randint(0, 40) if r < 0.3 else (2 ** (mw - 9) - 1 - rng.randint(0, 40) if r < 0.6 else rng.randint(0, 2 ** (mw - 9) - 1))))
        bits = ((k + fmt.bias) << mw) | mant
        return bits
    # log1p
    r = rng.random()
    if r < 0.3:                                   # the small path, weighted to its upper end
        t = Fraction(rng.randint(1, 10 ** 6), 10 ** 6)
        a = Fraction(1, 16) * (1 - Fraction(8, 100) * t * t)          # (0.0575, 1/16), weighted to 1/16
        return enc(fmt, a * (1 if rng.random() < 0.5 else -1))
    k = rng.choice([0, -1, 1, 2, rng.randint(-8, 60)])
    i = rng.randint(0, 511)
    mant = i * 2 ** (mw - 9) + (rng.randint(0, 40) if rng.random() < 0.3 else rng.randint(0, 2 ** (mw - 9) - 1))
    u = dec(fmt, ((k + fmt.bias) << mw) | mant)
    return enc(fmt, u - 1)


worst = -1e9
worst_x = None
hist = {}
n = 0
tail = []
while n < ns and time.perf_counter() - t0 < budget:
    xa = sample()
    u = sf.unpack(fmt, xa)
    if u.kind in (sf.NAN, sf.INF, sf.ZERO):
        continue
    xv = dec(fmt, xa)
    if fn == "exp":
        if not (fmt.emin - p + 2) * 0.6931 < float(xv) < (fmt.emax + 1) * 0.6931 - 2 and not abs(xv) < 1:
            pass
    bits, fw, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv", "Ek"], full=True)
    # only lanes the main path answers (no screen, tiny gate, exact path)
    xf = float(xv) if abs(xv) < Fraction(2) ** 1000 else 1e300
    if fn in ("exp", "exp2"):
        lo = (fmt.emin - p) * (0.6931471805599453 if fn == "exp" else 1.0) + 1
        hi = (fmt.emax + 1) * (0.6931471805599453 if fn == "exp" else 1.0) - 1
        if not (lo < xf < hi) or abs(xv) < Fraction(1, 2 ** (p + 3)):
            continue
        if fn == "exp2" and xv.denominator == 1:
            continue
    elif fn == "expm1":
        if not (-(p + 2) * 0.6931471805599453 + 1 < xf < (fmt.emax + 1) * 0.6931471805599453 - 1) or abs(xv) < Fraction(1, 2 ** (p + 2)):
            continue
    elif fn in ("log", "log2"):
        if u.sign or xv == 1:
            continue
        if fn == "log2" and xv.numerator & (xv.numerator - 1) == 0 and xv.denominator & (xv.denominator - 1) == 0:
            continue
    else:
        if xv <= -1 or abs(xv) < Fraction(1, 2 ** (p + 2)):
            continue
    vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
    if bv == 0:
        continue
    k = (pr["Ek"] - fmt.bias - f.meta["OFF"]) if fn.startswith("exp") else 0
    x = mpmath.mpf(xv.numerator) / xv.denominator
    if fn == "exp":
        tv = mpmath.exp(x)
    elif fn == "exp2":
        tv = mpmath.power(2, x)
    elif fn == "expm1":
        tv = mpmath.expm1(x)
    elif fn == "log":
        tv = mpmath.log(x)
    elif fn == "log2":
        tv = mpmath.log(x) / LN2
    else:
        tv = mpmath.log1p(x)
    tv = tv * mpmath.mpf(2) ** (-k)
    v = mpmath.mpf(vh.numerator) / vh.denominator + mpmath.mpf(vl.numerator) / vl.denominator
    err = abs(v - tv)
    n += 1
    if err == 0:
        continue
    lr = float(mpmath.log(err / (mpmath.mpf(bv.numerator) / bv.denominator), 2))
    b = math.floor(lr)
    hist[b] = hist.get(b, 0) + 1
    if lr > worst:
        worst, worst_x = lr, xa
    if lr > -3.5:
        tail.append((round(lr, 2), hex(xa), float(xv)))
print(f"  samples {n}, worst log2(err/Bv) = {worst:.2f} at x bits {hex(worst_x) if worst_x is not None else None}  [{time.perf_counter()-t0:.0f}s]")
print("  histogram of floor(log2(err/Bv)), top 8 bins:", dict(sorted(hist.items())[-8:]))
print("  lanes within 2^3.5 of the bound:", len(tail), sorted(tail, reverse=True)[:10])
