# VM1b-1: log2(|V - true| / Bv) over N uniform arguments in [LO, HI), every bit of the argument random (so u_l != 0),
# for the model at G, with a time budget. V = Vh + Vl from the model's probes, true = mpmath at 4p + 200 bits. Prints the
# worst ratio, the five worst arguments (bits), the top bins, and how many lanes are above -2, -1 and 0.
# usage: p10_cells.py FMT FN G LO HI N SEED BUDGET_SECONDS      (LO, HI: "a/b", decimals, or "2^k")
import sys
import math
import time
import random
from vm1blib import *      # noqa

from m1measure import true_scaled   # noqa


def P(t):
    if '^' in t:
        b, e = t.split('^')
        sgn = -1 if b.startswith('-') else 1
        return sgn * Fraction(b.lstrip('-')) ** int(e)
    return Fraction(t)


fmtname, fn, G = sys.argv[1], sys.argv[2], int(sys.argv[3])
lo, hi = P(sys.argv[4]), P(sys.argv[5])
N, seed, budget = int(sys.argv[6]), int(sys.argv[7]), float(sys.argv[8])
fmt = FORMATS[fmtname]
p = fmt.prec
mpmath.mp.prec = 4 * p + 200
rng = random.Random(seed)
f = build(fmt, RNE, fn, G=G)
t0 = time.perf_counter()
print(f"{fmtname} {fn} G {G}: K {f.meta['K']} D {f.meta['D']} insns {len(f.body)} words {len(f.words)}; x in [{float(lo):.6f}, {float(hi):.6f}), up to {N} arguments, budget {budget:.0f} s", flush=True)
worst, hist, top = -1e9, {}, []
above = {-2: 0, -1: 0, 0: 0}
n = 0
while n < N and time.perf_counter() - t0 < budget:
    xa = enc(fmt, lo + (hi - lo) * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))
    _, _, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv", "Ek"], full=True)
    k = (pr["Ek"] - fmt.bias - f.meta["OFF"]) if fn.startswith("exp") else 0
    vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
    tv = true_scaled(fmt, fn, xa, k)
    err = abs(M(vh) + M(vl) - tv)
    n += 1
    if not err:
        continue
    lr = float(mpmath.log(err / M(bv), 2))
    hist[math.floor(lr)] = hist.get(math.floor(lr), 0) + 1
    for t in above:
        above[t] += lr > t
    worst = max(worst, lr)
    top.append((lr, xa))
    top.sort(reverse=True)
    del top[5:]
print(f"samples {n}: worst log2(err/Bv) {worst:+.3f} at x = {float(dec(fmt, top[0][1])):+.15f}; above -2: {above[-2]}, above -1: {above[-1]}, above 0: {above[0]};"
      f" top bins {dict(sorted(hist.items())[-4:])}  [{time.perf_counter() - t0:.0f}s]")
print("five worst:", [(round(lr, 3), hex(xa)) for lr, xa in top])
