# M2 model: the error of V against the in-lane bound, mpmath at 4p + 200
# bits the reference (scratch; the study's 3.3).
#
#   python m2measure.py FMT FNS N MODE [ATTRS] [seed]
#
# MODE: random (every bit of x random, its exponent uniform over the
# range), edge (|r| near pi/4: x near (k + 1/2) pi/2), near (x near k pi/2
# for odd k, so r is small: the cancellation, where cos is small and tan
# large), zero (x near k pi/2 for even k, where sin and tan are small:
# added after the budgets' first runs, whose near region held odd k
# only), small (|x| between the tiny gate and
# 4, the r = x path and its neighbours), worst (pi_worstcase's deepest
# cancellations and their neighbours, the pools' own). For each lane whose
# answer is the main path's: |V_h + V_l - f(x)| / Bv, and every lane
# against transcend.py (equal, or marked).

import sys
import time
import math
import random
from fractions import Fraction

import mpmath

from m2core import FORMATS, sf, enc, dec, evaluate, RNE, ATTRS
from m2const import pi_frac
from m2trig import build, gates, RANGE
from m2harness import tc, tr
from cft_golden import vectors


def true_value(fn, X):
    x = mpmath.mpf(X.numerator) / X.denominator
    return {"sin": mpmath.sin, "cos": mpmath.cos, "tan": mpmath.tan}[fn](x)


def in_main(fmt, fn, xa):
    u = sf.unpack(fmt, xa)
    if u.kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    gs, gc = gates(fmt)
    g = gs if fn == "sin" else gc
    ax = xa & ~fmt.sign_mask
    if ax < enc(fmt, Fraction(2) ** g):
        return False
    R = RANGE[fmt.name]
    if R is not None and ax >= enc(fmt, Fraction(2) ** R):
        return False
    return True


def sample(fmt, mode, n, seed):
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    gs, gc = gates(fmt)
    Emax = (RANGE[fmt.name] - 1) if RANGE[fmt.name] else fmt.emax
    out = []
    pio2 = pi_frac() / 2
    if mode == "worst":
        t = 64 if fmt.width <= 64 else 16
        pool = set(tc.radian_pool(fmt, t, 5)) | set(vectors.radian_unary_pool(fmt, 24, 14))
        return sorted(pool)
    for _ in range(n):
        if mode == "random":
            E = rng.randint(min(gs, gc), Emax)
            m = rng.getrandbits(p - 1) | (1 << (p - 1))
            out.append(sf.round_pack(fmt, rng.getrandbits(1), m, E - p + 1, RNE)[0])
        elif mode in ("edge", "near", "zero"):
            E = rng.randint(1, Emax)
            k = rng.getrandbits(max(1, E)) | 1
            if mode == "zero":
                # an EVEN multiple of pi/2, k pi: sin and tan are small
                # there (near's odd multiples make cos small and tan
                # large); both reach the reduction's cancellation
                k = max(2, k - 1)
            v = (Fraction(k) + (Fraction(1, 2) if mode == "edge" else 0)) * pio2
            b = enc(fmt, v)
            j = rng.randint(-3, 3)
            b += j
            if rng.getrandbits(1):
                b |= fmt.sign_mask
            out.append(b)
        elif mode == "small":
            E = rng.randint(min(gs, gc), 2)
            m = rng.getrandbits(p - 1) | (1 << (p - 1))
            out.append(sf.round_pack(fmt, rng.getrandbits(1), m, E - p + 1, RNE)[0])
    return out


def run(fmt, fn, rnd, xs, G=None):
    p = fmt.prec
    f = build(fmt, rnd, fn, G=G)
    mpmath.mp.prec = 4 * p + 200
    worst, wx, main, wrong, marked = -1e9, None, 0, 0, 0
    hist = {}
    for xa in xs:
        bits, fw, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv"], full=True)
        gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
        if fw & 0x80:
            marked += 1
        elif (bits, fw) != (gb, gf):
            wrong += 1
            if wrong <= 5:
                print("   WRONG", fn, sf.RND_NAMES[rnd], hex(xa), hex(bits), fw,
                      hex(gb), gf, flush=True)
        if not in_main(fmt, fn, xa):
            continue
        V = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
        Bv = abs(dec(fmt, pr["Bv"]))
        T = true_value(fn, dec(fmt, xa))
        err = abs(mpmath.mpf(V.numerator) / V.denominator - T)
        ratio = err / (mpmath.mpf(Bv.numerator) / Bv.denominator)
        if ratio == 0:
            continue
        lr = float(mpmath.log(ratio, 2))
        main += 1
        if lr > worst:
            worst, wx = lr, xa
        b = math.floor(lr)
        hist[b] = hist.get(b, 0) + 1
    return {"n": len(xs), "main": main, "wrong": wrong, "marked": marked,
            "worst": worst, "at": hex(wx) if wx is not None else None,
            "hist": dict(sorted(hist.items())), "insns": len(f.body)}


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",")
    n = int(sys.argv[3])
    mode = sys.argv[4]
    rnds = ([int(c) for c in sys.argv[5].split(",")] if len(sys.argv) > 5
            else [RNE])
    seed = int(sys.argv[6]) if len(sys.argv) > 6 else 1
    fmt = FORMATS[name]
    xs = sample(fmt, mode, n, seed)
    t0 = time.perf_counter()
    for fn in fns:
        for rnd in rnds:
            st = run(fmt, fn, rnd, xs)
            print(f"{name} {fn} {sf.RND_NAMES[rnd]} {mode} seed {seed}: "
                  f"{st['main']} main of {st['n']}, wrong {st['wrong']}, "
                  f"marked {st['marked']}; largest |V - f|/Bv "
                  f"2^{st['worst']:.2f} at {st['at']}; histogram "
                  f"{st['hist']}; {time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
