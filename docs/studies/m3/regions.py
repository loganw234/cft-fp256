# M3 model: regions of placed arguments that reach every corner of the two
# operands (scratch; the study's 3.3). M4's study passed its own regions and
# failed its verifier's in a corner none of them reached (atan2 with a tiny
# numerator), so these are placed by the quantity the error depends on,
# t = y log2|x|, and by the operands' own ranges:
#
#   wide    x log-uniform from the least subnormal to the largest finite,
#           either sign for pow (y then an integer), t uniform on the main
#           path's whole range, y = t / log2|x| rounded: y from about 2^-18
#           to past 2^p
#   near1   x = 1 +- k ulp (k < 2^8, or 2^(p/2)), y large: t uniform
#   edge    t within 2 of emax + 1 and of emin - p: the overflow and
#           underflow edges, subnormal results among them
#   redb    t within 2^-30 of a sixteenth (the reduction's n/8 boundary at
#           odd sixteenths, the table's j = 0 at the integers)
#   small   |t| log-uniform from 2^-(p+12) to 2^-4: next to 1
#   negint  x < 0 with an integer y, odd and even, |y| up to 2^(p+4)
#   sub     x subnormal, t in range
#   tinyy   y log-uniform from the least subnormal to 2^-(p+2), either sign,
#           x over its whole range: t beside 1, t_h underflowing at the
#           bottom (the corner the first design got wrong, 3.6)
#   negedge x < 0 with an odd integer y and t within 2 of the edges: the
#           signed result at the overflow threshold and on the fixed grid
#   rhoedge x in [0.941, 0.965], where M1's reduction takes the cell C = 16
#           (no table term: L is the polynomial's r Y alone) and |r| is
#           next to its rho, 0.0592, so the polynomial's own error is at its
#           largest relative to L; t uniform over the range (|y| to about
#           3 x 10^5 at fp128): the region where the logarithm's planned
#           guard GL is what holds the bound (the plant log_short)
#   hugey   |y| log-uniform from 2^p to the largest finite (every one an
#           even integer), x within 2^-p of 1 and of -1 or anywhere: the
#           screens and the even-integer sign
#   int     pown, rootn and compound: x log-uniform with t in range, at the
#           n of region_n (one n a region; the budget builds at it);
#           "int<N>" names any n
#   zone    send-back 1: |x| (1 + x for compound) in the cancelling zone
#           of M1's reduction, [1/2, 241/256), where k = -1 and log2 m' up to
#           0.913 make L as small as -0.0871 (241/256 is the reduction's own
#           boundary, MEASURED by bisection on the model's k): six tenths
#           uniform in [0.92, 241/256), two tenths uniform over the whole
#           zone, a tenth log-uniform within 2^-6 of the top, a tenth just
#           above it (k = 0), at a large n only where |n L| is in range;
#           pow's and powr's y from t uniform in range; "zone<N>" at n = N
#           for pown and compound
#
#   region(fmt, fn, name, count, seed) -> [(x, y)] or [(x, n)]

import math
import random
import re
from fractions import Fraction

import mpmath

from m3core import sf, dec, enc, val, INTARG
import m3pow as M

NAMES = ("wide", "near1", "edge", "redb", "small", "negint", "sub",
         "tinyy", "hugey", "negedge", "rhoedge", "zone")
INT_NS = {"int": 3, "int-neg": -3, "int17": 17, "int1000": 1000,
          "int31": (1 << 31) - 1, "int63": -(1 << 63), "int2": 2,
          "intm1": -1, "intm2": -2}


def region_n(fn, name, seed=1):
    if fn not in INTARG:
        return None
    if name in INT_NS:
        return INT_NS[name]
    m = re.fullmatch(r"(?:int|zone)(-?\d+)", name)
    return int(m.group(1)) if m else 3


ZONE_TOP = Fraction(241, 256)     # m = 2X = 241/128: the seed's cells 9, 8


def _zone_x(fmt, rng, lo=0.5):
    """X in the cancelling zone, mostly near its top (see the head); at
    a large n, X >= lo, where |n log2 X| stays on the main path."""
    u = rng.random()
    if u < 0.6:
        return Fraction(rng.uniform(max(0.92, lo), float(ZONE_TOP)))
    if u < 0.8:
        return Fraction(rng.uniform(lo, float(ZONE_TOP)))
    if u < 0.9:
        return ZONE_TOP - Fraction(2.0 ** -rng.uniform(6, 50))
    return ZONE_TOP + Fraction(rng.uniform(0, 0.01))


def _log2(fmt, x):
    with mpmath.workprec(fmt.prec + 64):
        return mpmath.log(abs(mpmath.mpf(dec(fmt, x).numerator)
                              / dec(fmt, x).denominator), 2)


def _rand_mag(fmt, rng, lo_e, hi_e):
    """A random positive finite encoding with exponent in [lo_e, hi_e]."""
    e = rng.randint(lo_e, hi_e)
    m = rng.getrandbits(fmt.prec - 1) | (1 << (fmt.prec - 1))
    b = val(fmt, 0, m, e - fmt.prec + 1)
    if b is None:
        b = sf.round_pack(fmt, 0, m, e - fmt.prec + 1, 0)[0]
    return b


def _y_for(fmt, x, t):
    """y = t / log2|x|, rounded to the format, or None."""
    L = _log2(fmt, x)
    if L == 0:
        return None
    with mpmath.workprec(fmt.prec + 64):
        q = mpmath.mpf(t) / L
        bits = enc(fmt, M.ml._frac(q))
    if (bits & ~fmt.sign_mask) >= sf.inf_bits(fmt) or not \
            (bits & ~fmt.sign_mask):
        return None
    return bits


def _tf(fmt):
    return M.t_reach(fmt) - 3


def main_lane(fmt, fn, lane):
    """The lane is one the main path answers: no special row."""
    x, b2 = lane
    ux = sf.unpack(fmt, x)
    if ux.kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    qx = dec(fmt, x)
    if fn in ("pow", "powr"):
        uy = sf.unpack(fmt, b2)
        if uy.kind in (sf.NAN, sf.INF, sf.ZERO):
            return False
        qy = dec(fmt, b2)
        if qx == 1 or qy == 1:
            return False
        if qx < 0 and (fn == "powr" or qy.denominator != 1):
            return False
        return True
    n = b2
    if n in (0, 1):
        return False
    if fn == "rootn":
        return not (qx < 0 and n % 2 == 0)
    if fn == "compound":
        return qx > -1
    return True


def region(fmt, fn, name, count, seed=1):
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    lo_e, hi_e = fmt.emin - p + 1, fmt.emax
    Tf = _tf(fmt)
    out = []
    tries = 0
    while len(out) < count and tries < 50 * count + 100:
        tries += 1
        lane = None
        if name.startswith("zone"):
            nz = region_n(fn, name, seed) if fn in INTARG else None
            lo = 0.5
            if nz and fn != "rootn":
                lo = max(0.5, 2.0 ** (-Tf / abs(nz)))
            X = _zone_x(fmt, rng, lo)
            if fn == "compound":
                x = enc(fmt, X - 1)
                lane = (x, region_n(fn, name, seed))
            elif fn in INTARG:
                x = enc(fmt, X)
                n = region_n(fn, name, seed)
                if rng.random() < 0.5 and (fn != "rootn" or n % 2):
                    x |= fmt.sign_mask
                lane = (x, n)
            else:
                x = enc(fmt, X)
                t = rng.uniform(-Tf, Tf)
                y = _y_for(fmt, x, t)
                if y is None:
                    continue
                if fn == "pow" and rng.random() < 0.3:
                    # a negative base with an integer y
                    yi = round(dec(fmt, y))
                    if yi in (0, 1, -1):
                        continue
                    y = enc(fmt, Fraction(yi))
                    x |= fmt.sign_mask
                lane = (x, y)
        elif fn in INTARG:
            n = region_n(fn, name, seed)
            if fn == "compound":
                # 1 + x across (0, max]: x from just above -1 to the largest
                sgn = rng.random() < 0.3
                if sgn:
                    x = _rand_mag(fmt, rng, -p - 4, -1)
                    x |= fmt.sign_mask
                else:
                    x = _rand_mag(fmt, rng, lo_e, hi_e)
                q = dec(fmt, x) + 1
                with mpmath.workprec(p + 64):
                    L = mpmath.log(mpmath.mpf(q.numerator) / q.denominator, 2)
                if abs(n * L) >= Tf:
                    continue
                lane = (x, n)
            else:
                # x placed so that t = n log2|x| (or log2|x| / n) is in range
                if fn == "rootn":
                    x = _rand_mag(fmt, rng, lo_e, hi_e)
                else:
                    t = rng.uniform(-Tf, Tf)
                    with mpmath.workprec(p + 64):
                        xv = mpmath.power(2, mpmath.mpf(t) / n)
                        x = enc(fmt, M.ml._frac(xv))
                    if not (x & ~fmt.sign_mask) or \
                            (x & ~fmt.sign_mask) >= sf.inf_bits(fmt):
                        continue
                if rng.random() < 0.5 and (fn != "rootn" or n % 2):
                    x |= fmt.sign_mask
                lane = (x, n)
        elif name == "wide":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            t = rng.uniform(-Tf, Tf)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "near1":
            k = rng.randint(1, 255) if rng.random() < 0.7 else \
                rng.randint(1, 1 << (p // 2))
            one = sf.one_bits(fmt)
            x = one + k if rng.random() < 0.5 else one - k
            t = rng.uniform(-Tf, Tf)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "edge":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            if rng.random() < 0.5:
                t = fmt.emax + 1 + rng.uniform(-2, 0.99)
            else:
                t = fmt.emin - p + rng.uniform(-1.99, 2)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "redb":
            x = _rand_mag(fmt, rng, -8, 8)
            k = rng.randint(-16 * 40, 16 * 40)
            t = k / 16 + rng.uniform(-1, 1) * 2.0 ** -30
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "small":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            t = 2.0 ** rng.uniform(-(p + 12), -4) * rng.choice((-1, 1))
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "negint":
            if fn == "powr":
                return []
            m = rng.getrandbits(fmt.prec - 1) | (1 << (fmt.prec - 1))
            ey = rng.randint(0, p + 4)
            yv = m >> max(0, p - 1 - ey) if ey < p else m << (ey - p + 1)
            yv = max(2, yv)
            if rng.random() < 0.5:
                yv = yv | 1 if ey < p else yv
            # x near enough to 1 that t stays in range
            L = rng.uniform(-Tf, Tf) / yv
            with mpmath.workprec(p + 64):
                xv = mpmath.power(2, mpmath.mpf(L))
                x = enc(fmt, M.ml._frac(xv))
            if x == sf.one_bits(fmt):
                continue
            yb = enc(fmt, Fraction(yv) * rng.choice((1, -1)))
            lane = (x | fmt.sign_mask, yb)
        elif name == "tinyy":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            if fn == "pow" and rng.random() < 0.2:
                x |= fmt.sign_mask
                y = None
            else:
                y = _rand_mag(fmt, rng, lo_e, -(p + 2))
                if rng.random() < 0.5:
                    y |= fmt.sign_mask
            if y is None:
                continue
            lane = (x, y)
        elif name == "hugey":
            y = _rand_mag(fmt, rng, p, hi_e)
            if rng.random() < 0.5:
                y |= fmt.sign_mask
            one = sf.one_bits(fmt)
            k = rng.randint(1, 4)
            x = rng.choice((one + k, one - k, _rand_mag(fmt, rng, lo_e, hi_e)))
            if fn == "pow" and rng.random() < 0.5:
                x |= fmt.sign_mask
            lane = (x, y)
        elif name == "rhoedge":
            u = rng.uniform(0.6, 1.0)
            x = enc(fmt, 1 - Fraction(592, 10000) * Fraction(u))
            t = rng.uniform(-Tf, Tf)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "negedge":
            if fn != "pow":
                return []
            yv = rng.randrange(3, 2001, 2)
            if rng.random() < 0.5:
                t = fmt.emax + 1 + rng.uniform(-2, 0.99)
            else:
                t = fmt.emin - p + rng.uniform(-1.99, 2)
            if rng.random() < 0.3:
                yv = -yv
            with mpmath.workprec(p + 64):
                xv = mpmath.power(2, mpmath.mpf(t) / yv)
                x = enc(fmt, M.ml._frac(xv))
            if not (x & ~fmt.sign_mask) or x == sf.one_bits(fmt):
                continue
            lane = (x | fmt.sign_mask, enc(fmt, Fraction(yv)))
        elif name == "sub":
            x = _rand_mag(fmt, rng, lo_e, fmt.emin - 1)
            t = rng.uniform(-Tf, Tf)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        else:
            raise ValueError(name)
        if lane is not None and main_lane(fmt, fn, lane):
            out.append(lane)
    return out


def show(lane, fn):
    x, b2 = lane
    if fn in INTARG:
        return f"x={x:#x} n={b2}"
    return f"x={x:#x} y={b2:#x}"
