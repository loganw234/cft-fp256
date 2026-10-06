# VM1b item 2: the error budget of a region, by instruction, from adlib's first-order attribution.
# For N random arguments in the region: per instruction i, the largest |delta_i s_i| seen (in units of
# the lane's Bv) and the largest CAPACITY |s_i| ulp(v_i)/2 (what a worst-case rounding could add),
# for the instructions that ever round (delta_i != 0 on some lane). Then: the sum of the observed
# maxima, the sum of the capacities, the method error M's maximum, and the largest total error seen.
# usage: p5c_budget_end.py FMT FN G LO HI N SEED END [top]   (END hi or lo: half the arguments uniform,
#   half within 2^-8 .. 2^-(p+3) of that end; the usage line was p5_budget.py's, corrected by M1)
#   LO, HI: the region's ends as fractions "a/b" (x for log1p; x for log, log2)
import sys
import time
import random
from adlib import *      # noqa

fmtname, fn, G = sys.argv[1], sys.argv[2], int(sys.argv[3])
def P(t):
    if '^' in t:
        b, e = t.split('^')
        sgn = -1 if b.startswith('-') else 1
        return sgn * Fraction(b.lstrip('-')) ** int(e)
    return Fraction(t)


lo, hi = P(sys.argv[4]), P(sys.argv[5])
N, seed = int(sys.argv[6]), int(sys.argv[7])
END = sys.argv[8]
top = int(sys.argv[9]) if len(sys.argv) > 9 else 8
fmt = FORMATS[fmtname]
p = fmt.prec
f = build(fmt, RNE, fn, G=G)
an = Analyzer(f, fn)
mpmath.mp.prec = an.prec
rng = random.Random(seed)
t0 = time.perf_counter()
n = len(an.body)
obs = [0.0] * n
cap = [0.0] * n
active = [False] * n
Mmax = 0.0
Emax = -1e9
Esum_max = 0.0
rows = []
for _ in range(N):
    if rng.random() < 0.5:
        xa = enc(fmt, lo + (hi - lo) * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))
    else:
        dl = Fraction(2) ** (-rng.randint(8, p + 3)) * (1 + Fraction(rng.getrandbits(20), 2 ** 20))
        dl = min(dl, (hi - lo) / 2)
        xa = enc(fmt, (hi - dl) if END == 'hi' else (lo + dl))
    L = an.analyze(xa)
    kk = (L.vals[an.probes['Ek'][1]] - fmt.bias - f.meta['OFF']) if fn.startswith('exp') else 0
    T = true_scaled(fmt, fn, xa, kk)
    Bv = L.Bv
    E = (L.V - T) / Bv
    Mx = (L.Vex - T) / Bv
    Mmax = max(Mmax, abs(float(Mx)))
    Emax = max(Emax, abs(float(E)))
    tot = 0.0
    for i, contrib, capi, d in an.contributions(L):
        if d != 0:
            active[i] = True
        c = abs(float(contrib / Bv))
        obs[i] = max(obs[i], c)
        cap[i] = max(cap[i], float(capi / Bv))
    rows.append((float(E), float(Mx)))
print(f"{fmtname} {fn} G {G}: {N} arguments in [{float(lo):.5f}, {float(hi):.5f}], {an.body.__len__()} instructions, {sum(active)} ever round; {time.perf_counter() - t0:.0f}s")
print(f"  max |E|/Bv {Emax:.4f} (2^{math.log2(Emax):+.2f}); max |M|/Bv {Mmax:.4f} (2^{math.log2(Mmax) if Mmax else -99:+.2f})")
S_obs = sum(obs[i] for i in range(n) if active[i])
S_cap = sum(cap[i] for i in range(n) if active[i])
print(f"  sum over the rounding instructions: observed maxima {S_obs:.4f} (2^{math.log2(S_obs):+.2f}); capacities (all at their worst) {S_cap:.4f} (2^{math.log2(S_cap):+.2f})")
print(f"  support bound: M_max + sum(capacities) = {Mmax + S_cap:.4f} (2^{math.log2(Mmax + S_cap):+.2f}) of Bv; with the observed maxima: {Mmax + S_obs:.4f} (2^{math.log2(Mmax + S_obs):+.2f})")
byphase = {}
for i in range(n):
    if active[i]:
        ph = an.phases[i]
        a, b = byphase.get(ph, (0.0, 0.0))
        byphase[ph] = (a + obs[i], b + cap[i])
print("  by phase (observed maxima summed, capacities summed), in Bv:")
for ph, (a, b) in sorted(byphase.items(), key=lambda kv: -kv[1][1]):
    print(f"     {ph:10s} {a:.4f}  {b:.4f}")
order = sorted((i for i in range(n) if active[i]), key=lambda i: -cap[i])[:top]
print(f"  the {top} largest capacities:")
for i in order:
    op, r, srcs = an.body[i]
    print(f"     #{i:3d} {sf.OP_NAMES[op]:4s} {an.phases[i]:10s} capacity {cap[i]:.4f}  observed max {obs[i]:.4f}")
