# M4 model: the error of V against the in-lane bound, mpmath at 4p + 200
# bits the reference (scratch; the study's 3.3).
#
#   python m4measure.py FMT FNS N MODE [ATTRS] [seed]
#
# MODE, placed where the bound binds:
#   random  every bit random; atan: the exponent uniform from the tiny gate
#           to emax; asin, acos: |x| < 1, the exponent uniform from the
#           gate; atan2: both operands' exponents uniform over a range of
#           +-(p + 40) about each other, all four quadrants
#   edge    n/d at the table's cells' edges, where |s| is largest
#           (t = (k +- 1/2)/(N 63/64) (1 +- eps), each k), and at t near 1
#   big     atan: |x| from 2^(p/2) to emax (C = pi/2, s tiny); atan2: a
#           dominant operand, either; asin, acos: |x| near 1, x = 1 - j
#           2^-p and 1 - 2^-e (w small; acos's small angle)
#   small   atan, asin: |x| from the gate to 1/16 (k = 0, V = atan(s));
#           acos: |x| from 2^-(p+20) to 1/16 (V near pi/2); atan2: x > 0
#           with |y/x| from the tiny-quotient range's edge to 1/16
#   diag    atan2: |y| within 4 ulps of |x|, all quadrants; asin, acos:
#           |x| within a few ulps of 1/sqrt(2), the swap
# For each lane whose answer is the main path's: |V_h + V_l - f| / Bv; and
# every lane against transcend.py (equal, or marked).

import sys
import time
import math
import random
from fractions import Fraction

import mpmath

from m4core import FORMATS, sf, enc, dec, evaluate2, RNE, ATTRS
from m4inv import build, gates, cells, NTAB
from m4harness import golden


def true_value(fn, args, fmt):
    if fn == "atan2":
        Y, X = (dec(fmt, a) for a in args)
        y = mpmath.mpf(Y.numerator) / Y.denominator
        x = mpmath.mpf(X.numerator) / X.denominator
        return mpmath.atan2(y, x)
    X = dec(fmt, args)
    x = mpmath.mpf(X.numerator) / X.denominator
    return {"atan": mpmath.atan, "asin": mpmath.asin,
            "acos": mpmath.acos}[fn](x)


def _fin(fmt, b):
    u = sf.unpack(fmt, b)
    return u.kind not in (sf.NAN, sf.INF, sf.ZERO)


def in_main(fmt, fn, args):
    """Whether the lane's answer is the main path's (not a special, a tiny
    path, atan2's exact-quotient rule or its tiny-quotient range)."""
    p = fmt.prec
    ga, gs = gates(fmt)
    if fn == "atan2":
        y, x = args
        if not (_fin(fmt, y) and _fin(fmt, x)):
            return False
        Y, X = dec(fmt, y), dec(fmt, x)
        if X > 0 and abs(Y) < X:
            t = abs(Y) / X
            if t < Fraction(2) ** (fmt.emin + p + 4):
                return False
            if t < Fraction(2) ** ga:
                return False             # the side rule's region, whether
                                         # exact or not: V is still main's,
                                         # but kept out of the budget's sample
        return True
    x = args
    ax = x & ~fmt.sign_mask
    if not _fin(fmt, x):
        return fn == "acos" and sf.unpack(fmt, x).kind == sf.ZERO
    if fn in ("asin", "acos") and ax >= sf.one_bits(fmt):
        return fn == "acos" and x == sf.one_bits(fmt, 1)
    g = ga if fn == "atan" else gs
    if fn in ("atan", "asin") and ax < enc(fmt, Fraction(2) ** g):
        return False
    return True


def _rand_sig(rng, fmt, E, sign):
    p = fmt.prec
    m = rng.getrandbits(p - 1) | (1 << (p - 1))
    return sf.round_pack(fmt, sign, m, E - p + 1, RNE)[0]


def sample(fmt, fn, mode, n, seed):
    rng = random.Random(seed * 1000003 + fmt.width * 7 + len(fn))
    p = fmt.prec
    ga, gs = gates(fmt)
    out = []
    one = sf.one_bits(fmt)
    M = NTAB * Fraction(63, 64)
    edges = []
    for k, (lo, hi) in enumerate(cells(NTAB)):
        edges += [lo, hi]
    edges = [e for e in edges if 0 < e <= 1]
    for _ in range(n):
        s = rng.getrandbits(1)
        if fn == "atan2":
            sy, sx = rng.getrandbits(1), rng.getrandbits(1)
            Ex = rng.randint(fmt.emin + 2 * p, fmt.emax - 2 * p)
            if mode == "random":
                Ey = Ex + rng.randint(-(p + 40), p + 40)
                out.append((_rand_sig(rng, fmt, Ey, sy), _rand_sig(rng, fmt, Ex, sx)))
            elif mode in ("edge", "diag"):
                xb = _rand_sig(rng, fmt, Ex, 0)
                X = dec(fmt, xb)
                if mode == "edge":
                    t = rng.choice(edges) * (1 + Fraction(rng.randint(-64, 64), 2 ** 16))
                    t = min(t, Fraction(1))
                else:
                    t = Fraction(1)
                yb = enc(fmt, X * t) + (rng.randint(-4, 4))
                yb, xb = (yb, xb) if rng.getrandbits(1) else (xb, yb)
                out.append((yb | (fmt.sign_mask if sy else 0),
                            xb | (fmt.sign_mask if sx else 0)))
            elif mode == "big":
                Ey = Ex + rng.randint(p // 2, 2 * p + 20)
                a, b = _rand_sig(rng, fmt, Ey, sy), _rand_sig(rng, fmt, Ex, sx)
                out.append((a, b) if rng.getrandbits(1) else (b ^ (fmt.sign_mask if sx != sy else 0), a))
            elif mode == "small":
                Ey = Ex - rng.randint(4, min(p + 40, Ex - fmt.emin - p - 6))
                out.append((_rand_sig(rng, fmt, Ey, sy), _rand_sig(rng, fmt, Ex, 0)))
            elif mode == "tinyn":
                # send-back 1's corner: a subnormal or tiny |y| (exponent from
                # the subnormal grid to emin + 3p + 4) against a larger |x|.
                # 50% x > 0 with t = |y/x| from the tiny-quotient range's
                # edge to 1/4 (where V is t itself: the lanes the first
                # prescale left with an inexact remainder); 20% x > 0 with t
                # in the band from that edge to 2^(emin+2p+4), where three
                # words keep only two; 10% x > 0 with |x| over the whole
                # range above |y| (most of them marked); 10% x < 0 and 10%
                # swapped (|y| > |x|), t as the first
                Ey = rng.randint(fmt.emin - p + 1, fmt.emin + 3 * p + 4)
                if Ey < fmt.emin:
                    k = Ey - fmt.emin + p - 1
                    nb = (1 << k) | rng.getrandbits(k)
                else:
                    nb = _rand_sig(rng, fmt, Ey, 0)
                u = rng.random()
                if 0.70 <= u < 0.80:
                    Ex = rng.randint(Ey + 1, fmt.emax)
                elif 0.50 <= u < 0.70:
                    Ex = Ey - rng.randint(fmt.emin + p + 2, fmt.emin + 2 * p + 4)
                else:
                    Ex = Ey - rng.randint(fmt.emin + p + 2, -2)
                db = _rand_sig(rng, fmt, Ex, 0)
                ys = fmt.sign_mask if sy else 0
                if u < 0.80:
                    out.append((nb | ys, db))
                elif u < 0.90:
                    out.append((nb | ys, db | fmt.sign_mask))
                else:
                    out.append((db | ys, nb | (fmt.sign_mask if sx else 0)))
            continue
        if mode == "random":
            if fn == "atan":
                E = rng.randint(ga, fmt.emax)
            else:
                E = rng.randint(gs if fn == "asin" else -(p + 20), -1)
            out.append(_rand_sig(rng, fmt, E, s))
        elif mode == "edge":
            t = rng.choice(edges) * (1 + Fraction(rng.randint(-64, 64), 2 ** 16))
            t = min(t, Fraction(1))
            if fn == "atan":
                X = t if rng.getrandbits(1) else 1 / t
            else:
                # n/d = t: |x| = t / sqrt(1 + t^2) (|x| < w) or its mirror
                v = math.sqrt(float(t * t / (1 + t * t)))
                X = Fraction(v) if rng.getrandbits(1) else Fraction(math.sqrt(max(0.0, 1 - v * v)))
            b = enc(fmt, X) + rng.randint(-2, 2)
            out.append(b | (fmt.sign_mask if s else 0))
        elif mode == "big":
            if fn == "atan":
                E = rng.randint(p // 2, fmt.emax)
                out.append(_rand_sig(rng, fmt, E, s))
            else:
                j = rng.randint(1, 1 << 12) if rng.getrandbits(1) else 0
                if j:
                    b = one - j
                else:
                    b = enc(fmt, 1 - Fraction(1, 2 ** rng.randint(1, p)))
                out.append(b | (fmt.sign_mask if s else 0))
        elif mode == "small":
            lo = ga if fn == "atan" else (gs if fn == "asin" else -(p + 20))
            E = rng.randint(lo, -5)
            out.append(_rand_sig(rng, fmt, E, s))
        elif mode == "diag":
            b = enc(fmt, Fraction(math.sqrt(0.5))) + rng.randint(-8, 8)
            out.append(b | (fmt.sign_mask if s else 0))
    return out


def run(fmt, fn, rnd, xs, G=None):
    p = fmt.prec
    f = build(fmt, rnd, fn, G=G)
    mpmath.mp.prec = 4 * p + 200
    worst, wx, main, wrong, marked = -1e9, None, 0, 0, 0
    for xa in xs:
        bits, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "Bv"], full=True)
        gb, gf = golden(fmt, fn, xa, rnd)
        if fw & 0x80:
            marked += 1
        elif (bits, fw) != (gb, gf):
            wrong += 1
            if wrong <= 5:
                print("   WRONG", fn, sf.RND_NAMES[rnd], xa, hex(bits), fw,
                      hex(gb), gf, flush=True)
        if not in_main(fmt, fn, xa):
            continue
        V = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
        Bv = abs(dec(fmt, pr["Bv"]))
        T = true_value(fn, xa, fmt)
        err = abs(mpmath.mpf(V.numerator) / V.denominator - T)
        ratio = err / (mpmath.mpf(Bv.numerator) / Bv.denominator)
        main += 1
        if ratio == 0:
            continue
        lr = float(mpmath.log(ratio, 2))
        if lr > worst:
            worst, wx = lr, xa
    return {"n": len(xs), "main": main, "wrong": wrong, "marked": marked,
            "worst": worst, "at": wx, "insns": len(f.body)}


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",")
    n = int(sys.argv[3])
    mode = sys.argv[4]
    rnds = ([int(c) for c in sys.argv[5].split(",")] if len(sys.argv) > 5
            else [RNE])
    seed = int(sys.argv[6]) if len(sys.argv) > 6 else 1
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    for fn in fns:
        xs = sample(fmt, fn, mode, n, seed)
        for rnd in rnds:
            st = run(fmt, fn, rnd, xs)
            at = (tuple(hex(v) for v in st["at"]) if isinstance(st["at"], tuple)
                  else (hex(st["at"]) if st["at"] is not None else None))
            print(f"{name} {fn} {sf.RND_NAMES[rnd]} {mode} seed {seed}: "
                  f"{st['main']} main of {st['n']}, wrong {st['wrong']}, "
                  f"marked {st['marked']}; largest |V - f|/Bv "
                  f"2^{st['worst']:.2f} at {at}; "
                  f"{time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
