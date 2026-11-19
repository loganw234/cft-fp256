# M3 model: the structured families, a census (scratch; the study's 3.5).
# Each family is generated from its definition, every lane is run on the
# model under the five attributes and compared with transcend.py, and the
# lanes are classed by transcend.py's own exactness test (_pow_dyadic,
# _pown_dyadic, _rootn_dyadic: an exact dyadic or None):
#
#   rep    exact and representable: the inexact flag must be clear
#   mid    exact with an odd part of p + 1 bits: a midpoint
#   exo    exact, odd part past p + 1 bits: no rounding boundary
#   irr    not exact (None: irrational, not dyadic, or too wide)
#
# For each class: lanes, marked, decided in-lane, and WRONG UNMARKED.
#
#   python census.py FMT FAMILY [count]
#
# FAMILY: intpow (an integer y, x's odd part short), root2k (y = Y/2^k, x a
# perfect 2^k-th power), pow2 (x a power of two, y any: integers, halves,
# random), near1 (|t| about golden's 2^-(p+3) rule, both sides of it),
# dominant (compound with a dominant x), edges (x^y at the overflow and
# underflow thresholds), smallint (pown, rootn and compound at n = 2, 3, -2,
# -3 on short odd parts), hard3p (x = 1 +- k u, y = +-(1 +- j u), u the ulp
# of 1: x^y within about u^3 of the grid point 1 -+ k u, the family the
# pools' comment says needs 3p bits; vectors.py's and transcend_check's).

import sys
import random
import time
from fractions import Fraction

from m3core import FORMATS, ATTRS, AN, sf, tr, val, dec, INTARG
import m3harness as H
import m3pow as M


def classify(fmt, fn, lane):
    x, b2 = lane
    ux = sf.unpack(fmt, x)
    p = fmt.prec
    try:
        if fn in ("pow", "powr"):
            uy = sf.unpack(fmt, b2)
            ex = tr._pow_dyadic(fmt, ux, uy)
        elif fn == "pown":
            ex = tr._pown_dyadic(fmt, ux.m, ux.e, b2)
        elif fn == "rootn":
            ex = tr._rootn_dyadic(fmt, ux, b2)
        else:
            sm, se = tr._exact_one_plus(ux)
            ex = tr._pown_dyadic(fmt, sm, se, b2)
    except Exception:
        return "irr"
    if ex is None:
        return "irr"
    m, e = ex
    odd = m >> ((m & -m).bit_length() - 1)
    e2 = e + (m & -m).bit_length() - 1
    vexp = e2 + odd.bit_length() - 1
    if vexp > fmt.emax or vexp < fmt.emin - fmt.man_w - 1:
        return "range"
    bits = odd.bit_length()
    lsb_ok = e2 >= fmt.emin - fmt.man_w          # on the subnormal grid
    if bits <= p and lsb_ok:
        return "rep"
    if bits == p + 1 or (e2 == fmt.emin - fmt.man_w - 1):
        return "mid"
    return "exo"


def power_base(fmt, fn, lane):
    """The lane's base, x (1 + x for compound, exactly), is +-2^E."""
    x = lane[0]
    q = abs(dec(fmt, x) + (1 if fn == "compound" else 0))
    return q > 0 and q.numerator & (q.numerator - 1) == 0 and         q.denominator & (q.denominator - 1) == 0


def family(fmt, name, count, seed=1):
    rng = random.Random(seed * 7919 + fmt.width)
    p = fmt.prec
    out = []                                  # (fn, lane)
    one = sf.one_bits(fmt)
    if name == "intpow":
        for _ in range(count):
            mb = rng.randint(1, max(2, p // 3))
            M_ = rng.getrandbits(mb) | 1
            E = rng.randint(-8, 8)
            nmax = max(2, (p + 1) // max(1, M_.bit_length()))
            n = rng.randint(2, nmax + 2)
            x = val(fmt, rng.random() < 0.3, M_, E)
            y = val(fmt, rng.random() < 0.1, n, 0)
            if x is None or y is None:
                continue
            out.append(("pow", (x, y)))
    elif name == "root2k":
        for _ in range(count):
            k = rng.randint(1, 3)
            R = rng.getrandbits(rng.randint(1, max(2, p // (2 ** k)))) | 1
            Mx = R ** (2 ** k)
            if Mx.bit_length() > p:
                continue
            E = rng.randint(-4, 4) * 2 ** k
            Y = rng.getrandbits(rng.randint(1, 6)) | 1
            x = val(fmt, 0, Mx, E)
            y = val(fmt, rng.random() < 0.2, Y, -k)
            if x is None or y is None:
                continue
            out.append(("pow", (x, y)))
    elif name == "pow2":
        for _ in range(count):
            E = rng.randint(fmt.emin - p + 1, fmt.emax)
            x = val(fmt, rng.random() < 0.2, 1, E)
            kind = rng.random()
            if kind < 0.4 and E:
                lim = max(1, (fmt.emax + p) // abs(E))
                y = val(fmt, rng.random() < 0.5, rng.randint(1, lim + 2), 0)
            elif kind < 0.7:
                y = val(fmt, rng.random() < 0.5,
                        rng.getrandbits(5) | 1, -rng.randint(1, 4))
            else:
                y = val(fmt, rng.random() < 0.5,
                        rng.getrandbits(p) | (1 << (p - 1)),
                        -p - rng.randint(-4, 12))
            if x is None or y is None:
                continue
            out.append(("pow", (x, y)))
    elif name == "near1":
        for _ in range(count):
            k = rng.randint(1, 8)
            x = one + k if rng.random() < 0.5 else one - k
            # |t| = |y| k 2^-(p-1) / ln 2 about 2^-(p+3): y about 2^-4 / k
            sh = rng.uniform(-3, 3)
            y = M.ml._enc(fmt, Fraction(2) ** int(-4 + sh) / k
                          * (1 + Fraction(rng.getrandbits(20), 1 << 21)))
            if rng.random() < 0.5:
                y |= fmt.sign_mask
            out.append(("pow", (x, y)))
            out.append(("powr", (x, y)))
    elif name == "dominant":
        for _ in range(count):
            n = rng.choice((1, 2, 3, -1, -2, 5))
            if n == 1:
                n = 2
            e = rng.randint(p + 2 + abs(n).bit_length(),
                            max(p + 3 + abs(n).bit_length(),
                                fmt.emax // max(1, abs(n))))
            M_ = rng.choice((1, 3, 5, 7))
            x = val(fmt, 0, M_, e)
            if x is None:
                continue
            out.append(("compound", (x, n)))
    elif name == "edges":
        for _ in range(count):
            # x^y within a few ulps of the largest finite or of the subnormal
            # grid's least points: y from the exact threshold's logarithm
            x = val(fmt, 0, rng.getrandbits(p - 1) | (1 << (p - 1)),
                    -p + 1 + rng.randint(1, 6))
            import mpmath
            with mpmath.workprec(4 * p):
                X = mpmath.mpf(dec(fmt, x).numerator) / dec(fmt, x).denominator
                if rng.random() < 0.5:
                    tgt = mpmath.mpf(2) ** fmt.emax * (2 - mpmath.mpf(2) ** (1 - p)
                                                        * rng.choice((0.5, 1, 1.5)))
                else:
                    tgt = mpmath.mpf(2) ** (fmt.emin - fmt.man_w) * \
                        rng.choice((0.5, 1, 1.5, 2, 3))
                yv = mpmath.log(tgt) / mpmath.log(X)
                y = M.ml._enc(fmt, M.ml._frac(yv))
            out.append(("pow", (x, y)))
    elif name == "hard3p":
        u = 1
        for k in range(1, 9):
            for j in range(0, 9):
                for xs in (one + k * u, one - k * u):
                    for ys in (one + j * u, one - j * u if j else None):
                        if ys is None:
                            continue
                        for sg in (0, fmt.sign_mask):
                            out.append(("pow", (xs, ys | sg)))
        out = out[:count] if count < len(out) else out
    elif name == "smallint":
        for _ in range(count):
            fn = rng.choice(("pown", "rootn", "compound"))
            n = rng.choice((2, 3, -2, -3))
            mb = rng.randint(1, max(2, p // 3))
            M_ = rng.getrandbits(mb) | 1
            if fn == "rootn":
                M_ = M_ ** abs(n) if (M_ ** abs(n)).bit_length() <= p else M_
                E = rng.randint(-6, 6) * abs(n)
            else:
                E = rng.randint(-6, 6)
            x = val(fmt, fn != "compound" and rng.random() < 0.3 and
                    (fn != "rootn" or n % 2), M_, E)
            if x is None:
                continue
            out.append((fn, (x, n)))
    else:
        raise ValueError(name)
    return out


def main():
    fmt = FORMATS[sys.argv[1]]
    name = sys.argv[2]
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    t0 = time.time()
    lanes = family(fmt, name, count)
    cls = {}
    for fn, lane in lanes:
        cls.setdefault(classify(fmt, fn, lane), []).append((fn, lane))
    print(f"{fmt.name} family {name}: {len(lanes)} lanes; classes "
          + ", ".join(f"{k} {len(v)}" for k, v in sorted(cls.items())))
    total_wrong = 0
    off_rule = 0            # decided exact lanes whose base is no power of 2
    for rnd in ATTRS:
        line = []
        for k, items in sorted(cls.items()):
            marked = wrong = gw = 0
            ex_wrong = []
            for fn, lane in items:
                n = lane[1] if fn in INTARG else None
                bld = H.builder(fn, fmt, rnd, n)
                if isinstance(bld, Exception):
                    continue
                bits, fl, _ = M.run(bld, fn, lane)
                want = H.golden(fmt, fn, lane, rnd)
                if fl & H.MARK:
                    marked += 1
                    gw += (bits, fl & ~H.MARK) != want
                elif (bits, fl) != want:
                    wrong += 1
                    ex_wrong.append((fn, lane, bits, fl, want))
                elif k == "rep" and not power_base(fmt, fn, lane):
                    off_rule += 1
            total_wrong += wrong
            line.append(f"{k}: {len(items)} lanes, marked {marked} "
                        f"(guess wrong {gw}), decided {len(items) - marked}, "
                        f"WRONG {wrong}")
            for fn, lane, bits, fl, want in ex_wrong[:4]:
                print(f"    {AN[rnd]} WRONG {fn} {H.show(fmt, lane, fn)} "
                      f"got ({bits:#x}, {fl:#x}) want ({want[0]:#x}, "
                      f"{want[1]:#x})")
        print(f"  {AN[rnd]}: " + "; ".join(line), flush=True)
    print(f"{fmt.name} {name}: {total_wrong} wrong unmarked; exact lanes "
          f"representable and decided unmarked whose base (x, or 1 + x for "
          f"compound) is not a "
          f"power of two, over the five attributes: {off_rule}; "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
