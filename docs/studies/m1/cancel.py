# The log family's cancellation cells at one format and G: k = -1 with
# C = 9 (x from 0.875 to 0.9414 for log and log2; x from -0.125 to -15/256
# for log1p), where k ln2 and L_j nearly cancel and the sum's roundings,
# counted against the terms, reach V amplified by up to about 22. Random
# arguments with every bit random; log2(|V - true| / Bv), its worst and
# its top bins.
# usage: cancel.py FMT N SEED [G]
import math
import sys
import time
import random
from fractions import Fraction

import mpmath

from m1core import sf, evaluate, dec, enc, RNE
from m1log import build_log, SMALL
from m1harness import FORMATS
from m1measure import true_scaled

fmtname, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
G = int(sys.argv[4]) if len(sys.argv) > 4 else 46
fmt = FORMATS[fmtname]
p = fmt.prec
mpmath.mp.prec = 4 * p + 200
t0 = time.perf_counter()
for fn, lo, hi in (("log1p", Fraction(-1, 8), -SMALL), ("log2", Fraction(7, 8), Fraction(241, 256)),
                   ("log", Fraction(7, 8), Fraction(241, 256))):
    rng = random.Random(seed)
    f = build_log(fmt, RNE, fn, G=G)
    worst, wx, hist = -1e9, None, {}
    for _ in range(n):
        xa = enc(fmt, lo + (hi - lo) * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))
        _, _, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv"], full=True)
        vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
        tv = true_scaled(fmt, fn, xa, 0)
        err = abs(mpmath.mpf(vh.numerator) / vh.denominator + mpmath.mpf(vl.numerator) / vl.denominator - tv)
        if not err:
            continue
        lr = float(mpmath.log(err / (mpmath.mpf(bv.numerator) / bv.denominator), 2))
        hist[math.floor(lr)] = hist.get(math.floor(lr), 0) + 1
        if lr > worst:
            worst, wx = lr, xa
    top = dict(sorted(hist.items())[-4:])
    print(f"{fmtname} {fn:5s} G {G}: x in [{float(lo):.6f}, {float(hi):.6f}), {n} random: worst log2(err/Bv) {worst:+.2f}"
          f" at x = {float(dec(fmt, wx)):+.15f}; top bins {top}  [{time.perf_counter() - t0:.0f}s]", flush=True)
print(f"done {time.perf_counter() - t0:.0f}s")
