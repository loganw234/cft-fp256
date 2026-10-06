# log1p's reduction (general) path near its lower end, term by term. There
# |V| is about 2^-4.1 while the low word of 1 + x is up to 2^-p absolute, so
# the terms of size 2^-2p around it - the correction r_l / (1 + r) and its
# rounding, the error of y ~ 1/(1 + r), the correction's neglected square
# term, and the two single-word sums that carry it - are 2^-(2p - 4.1)
# relative: at fp64 they reach the bound's last two bits (2^-(p+G) =
# 2^-99), which the planners' floor (12u^2, from the log family's other
# double-word steps) does not count. Measured here: log2(|term| / Bv), the
# worst over random arguments, for the total and each part.
# usage: log1p_floor.py FMT NRANDOM SEED [G]
import sys
import time
import random
from fractions import Fraction

import mpmath

from m1core import sf, evaluate, dec, enc, RNE
from m1log import build_log, SMALL
from m1harness import FORMATS

fmtname, nr, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
G = int(sys.argv[4]) if len(sys.argv) > 4 else 46
fmt = FORMATS[fmtname]
p = fmt.prec
mpmath.mp.prec = 4 * p + 200
rng = random.Random(seed)
t0 = time.perf_counter()
f = build_log(fmt, RNE, "log1p", G=G)
print(f"{fmtname} log1p G {G}: K {f.meta['K']} D {f.meta['D']} insns {len(f.body)}", flush=True)


def M(q):
    return mpmath.mpf(q.numerator) / q.denominator


def lg(v, bv):
    return float(mpmath.log(abs(v) / bv, 2)) if v else -1e9


def uni(lo, hi):
    return enc(fmt, lo + (hi - lo) * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))


O16 = Fraction(1, 16)
regions = {
    "+[15/256, 2^-4)": (SMALL, O16, 1), "-[15/256, 2^-4)": (SMALL, O16, -1),
    "+[2^-4, 2^-3)": (O16, Fraction(1, 8), 1), "-[2^-4, 2^-3)": (O16, Fraction(1, 8), -1),
    "+[2^-3, 1)": (Fraction(1, 8), Fraction(1), 1), "-[2^-3, 1/2)": (Fraction(1, 8), Fraction(1, 2), -1),
}
names = ("total", "corr (all)", "  y's error", "  corr's rounding", "  square term", "the rest")
for rname, (lo, hi, s) in regions.items():
    worst = {k: -1e9 for k in names}
    wx = None
    nonexact = 0
    for _ in range(nr):
        xa = uni(lo, hi)
        if s < 0:
            xa = sf.negate(fmt, xa)
        _, _, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv", "r", "rl", "ul", "kf", "c", "yinv", "corr"], full=True)
        x = dec(fmt, xa)
        T = mpmath.log1p(M(x))
        bv = M(dec(fmt, pr["Bv"]))
        V = M(dec(fmt, pr["Vh"])) + M(dec(fmt, pr["Vl"]))
        R, RL, UL = dec(fmt, pr["r"]), dec(fmt, pr["rl"]), dec(fmt, pr["ul"])
        k, c = dec(fmt, pr["kf"]), dec(fmt, pr["c"])
        if RL != UL * Fraction(2) ** int(-k) * c:
            nonexact += 1
        Y, CORR = dec(fmt, pr["yinv"]), dec(fmt, pr["corr"])
        q = M(RL) / (1 + M(R))
        target = mpmath.log1p(q)
        parts = {
            "total": V - T,
            "corr (all)": M(CORR) - target,
            "  y's error": M(RL) * (M(Y) - 1 / (1 + M(R))),
            "  corr's rounding": M(CORR) - M(RL * Y),
            "  square term": q - target,
        }
        parts["the rest"] = parts["total"] - parts["corr (all)"]
        for k2, v in parts.items():
            lv = lg(v, bv)
            if k2 == "total" and lv > worst["total"]:
                wx = xa
            worst[k2] = max(worst[k2], lv)
    print(f"  {rname:16s} n {nr}: " + "; ".join(f"{k2.strip()} {worst[k2]:+.2f}" for k2 in names)
          + f"  (worst total at x = {float(dec(fmt, wx)):+.10f}; r_l inexact {nonexact})"
          + f"  [{time.perf_counter() - t0:.0f}s]", flush=True)
print(f"done {time.perf_counter() - t0:.0f}s")
