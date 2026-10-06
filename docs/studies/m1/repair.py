# verifier-VM1's (b)-1 and its repair. log1p's r = x path ran the polynomial
# at |r| = |x| up to 2^-4, past the planners' rho = 0.0592 (2^-4.08): at
# fp256 the truncation passed the in-lane bound there. Two repairs:
#   (a) VM1's: keep the threshold 2^-4, plan log1p's D from rho = 2^-4
#       (D + 1: one FMA more);
#   (b) the model's: lower the threshold to 15/256 <= RHO (no instruction:
#       the bank word SMALL changes value), so one (rho, K, D) serves every
#       path, and [15/256, 2^-4) moves to the reduction (general) path.
# Measured here, against mpmath at 4p + 200 bits: log2(|V - true| / Bv) by
# region, for the first model ("before"), (a) and (b). V does not depend on
# the attribute, so rne is built. With "lanes", also VM1's four constructed
# fp256 arguments under all five attributes against transcend.py.
# usage: repair.py FMT NRANDOM SEED [lanes]
import sys
import time
import random
from fractions import Fraction

import mpmath

from m1core import sf, evaluate, dec, enc, RNE
from m1log import build_log, log_plan, SMALL, RHO
from m1harness import FORMATS, tr

fmtname, nr, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
fmt = FORMATS[fmtname]
p = fmt.prec
mpmath.mp.prec = 4 * p + 200
rng = random.Random(seed)
t0 = time.perf_counter()
K, D = log_plan(fmt)
O16 = Fraction(1, 16)
builds = {
    "before (2^-4, D)": dict(small=O16),
    "(a) (2^-4, D+1)": dict(small=O16, D=D + 1),
    "(b) (15/256, D)": dict(small=SMALL),
}
frags = {k: build_log(fmt, RNE, "log1p", **v) for k, v in builds.items()}
print(f"{fmtname} log1p: K {K}, D {D}; RHO {RHO}; SMALL {SMALL} = {float(SMALL)};"
      f" insns " + ", ".join(f"{k} {len(f.body)}" for k, f in frags.items()), flush=True)


def ratio(f, xa):
    _, _, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv"], full=True)
    x = dec(fmt, xa)
    tv = mpmath.log1p(mpmath.mpf(x.numerator) / x.denominator)
    vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
    err = abs(mpmath.mpf(vh.numerator) / vh.denominator + mpmath.mpf(vl.numerator) / vl.denominator - tv)
    return float(mpmath.log(err / (mpmath.mpf(bv.numerator) / bv.denominator), 2)) if err else -1e9


def uni(lo, hi):
    """a uniform argument in [lo, hi) with every bit of the format random"""
    v = lo + (hi - lo) * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20))
    return enc(fmt, v)


U5 = Fraction(1, 2 ** (p + 4))       # the ulp on [2^-5, 2^-4)
U4 = Fraction(1, 2 ** (p + 3))       # the ulp on [2^-4, 2^-3)
regions = {}
for s, sn in ((1, "+"), (-1, "-")):
    fx = [s * (SMALL - j * U5) for j in (1, 2, 3, 5, 16, 17, 100, 10 ** 4, 10 ** 7)]
    regions[f"{sn}small end: |x| in [0.054, 15/256)"] = (
        [enc(fmt, v) for v in fx] + [uni(Fraction(54, 1000), SMALL) if s > 0 else
                                     sf.negate(fmt, uni(Fraction(54, 1000), SMALL)) for _ in range(nr)])
    fx = ([s * SMALL] + [s * (SMALL + j * U5) for j in (1, 2, 5, 16, 17)]
          + [s * (O16 - j * U5) for j in (1, 2, 5, 16, 17, 10 ** 4)])
    regions[f"{sn}band: |x| in [15/256, 2^-4)"] = (
        [enc(fmt, v) for v in fx] + [uni(SMALL, O16) if s > 0 else sf.negate(fmt, uni(SMALL, O16))
                                     for _ in range(nr)])
    fx = [s * O16] + [s * (O16 + j * U4) for j in (1, 2, 5, 16, 17)]
    regions[f"{sn}past 2^-4: |x| in [2^-4, 2^-3)"] = (
        [enc(fmt, v) for v in fx] + [uni(O16, Fraction(1, 8)) if s > 0 else
                                     sf.negate(fmt, uni(O16, Fraction(1, 8))) for _ in range(nr)])

for rname, xs in regions.items():
    for bname, f in frags.items():
        worst, wx, above15, above0 = -1e9, None, 0, 0
        for xa in xs:
            lr = ratio(f, xa)
            if lr > worst:
                worst, wx = lr, xa
            above15 += lr > -1.5
            above0 += lr > 0
        print(f"  {rname:34s} {bname:17s} n {len(xs)}: worst log2(err/Bv) {worst:+.2f}"
              f" at x = {float(dec(fmt, wx)):+.12f}; above -1.5: {above15}, above 0: {above0}"
              f"  [{time.perf_counter() - t0:.0f}s]", flush=True)

if len(sys.argv) > 4 and sys.argv[4] == "lanes":
    assert fmtname == "fp256"
    # verifier-VM1's four constructed arguments (its p3_construct_log1p.py,
    # checked three ways in its p3b_verify_lane.py): wrong and unmarked under
    # the first model, 10 lane-attribute pairs
    LANES = (0x3fffafdc7157a0f0fe299aff23ff8f95ba4447f23ab3b11a977a734856c53281,
             0x3fffafdc7157a0f0fe299aff23ff8f95ba4447f23ab3b11a977a882e25e14766,
             0xbfffafdc7157a0f0fe299aff23ff8f95ba4447f23ab3b11a977a97eea099d1df,
             0xbfffafdc7157a0f0fe299aff23ff8f95ba4447f23ab3b11a977f111cd3d11fdf)
    for bname, kw in builds.items():
        tally = {"equal": 0, "MARKED": 0, "WRONG UNMARKED": 0}
        for rnd in sf.RND_MODES:
            f = build_log(fmt, rnd, "log1p", **kw)
            row = []
            for i, xb in enumerate(LANES):
                bits, fw, _ = evaluate(f, xb)
                gb, gf = tr.compute(fmt, "log1p", xb, 0, rnd)
                v = "MARKED" if fw & 0x80 else ("equal" if (bits, fw) == (gb, gf) else "WRONG UNMARKED")
                if fw & 0x80 and (bits, fw & 0x1F) == (gb, gf):
                    v = "MARKED"          # the guess under the mark is right too: counted as marked
                tally[v] += 1
                row.append(f"lane {i + 1} {v}")
            print(f"  lanes {bname:17s} {sf.RND_NAMES[rnd]}: " + "; ".join(row), flush=True)
        print(f"  lanes {bname:17s} 20 lane-attribute pairs: {tally}", flush=True)
print(f"done {time.perf_counter() - t0:.0f}s")
