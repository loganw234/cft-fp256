# M4 model: the structured families, by census (scratch; the study's 3.5).
# Every lane through the model and transcend.py under all five attributes:
# counted marked (by attribute), marked with the guess right, and wrong
# unmarked.
#
#   python census.py FMT FAMILY
#
# FAMILY
#   tiny    atan and asin at +-c 2^-e, c = 1..16, e from (p + G)/4 - 4 up
#           past the tiny gate; and atan2(c 2^-e x, x) for x = 1, 3 and
#           5 2^7, whose quotient is exactly c 2^-e
#   near    the windows next to pi/2 and pi: atan(x) about x0 = 1/(pi/2 -
#           b), acos(x) about +-(pi/2 - b), atan2(y, -1) about y0 = pi - b,
#           for the two boundaries b nearest the constant from below, grid
#           points and midpoints, 2J + 1 arguments each (J = 64), every
#           attribute; at fp32 and fp64 also a scan j = +-2^i for the
#           window's extent
#   acos1   acos(1 - j 2^-p) and acos(-1 + j 2^-p), j = 1..64
#   ratio   atan2(2^k, 1 + j ulp) for j = 1..40: y/x = 2^k (1 - j u + j^2
#           u^2 ...) sits j^2 u^2 relative above the grid point 2^k (1 - j
#           u): one of division's hard cases, for k = -10, -40, -(p + 10)
#   diag    atan2(x + j, x), 40 random x, j = -4..4, all four quadrants

import sys
import random
from fractions import Fraction

from m4core import FORMATS, sf, enc, dec, evaluate2, ATTRS, RNE, RTZ, pi_frac
from m4inv import build, gates, GUARD
from m4harness import golden

NAMES = {a: sf.RND_NAMES[a] for a in ATTRS}


def run(fmt, fn, args_list, frags, label):
    marked = {a: 0 for a in ATTRS}
    right = wrong = 0
    first_mark = {}
    for args in args_list:
        for rnd in ATTRS:
            b, fw, _ = evaluate2(frags[(fn, rnd)], args)
            gb, gf = golden(fmt, fn, args, rnd)
            if fw & 0x80:
                marked[rnd] += 1
                first_mark.setdefault(rnd, args)
                if b == gb and (fw & 0x1F) == gf:
                    right += 1
            elif (b, fw) != (gb, gf):
                wrong += 1
                if wrong <= 3:
                    print(f"   WRONG {label} {NAMES[rnd]} {args} {hex(b)} {fw} {hex(gb)} {gf}",
                          flush=True)
    tot = sum(marked.values())
    print(f"{fmt.name} {label}: {len(args_list)} arguments; marked "
          + ", ".join(f"{NAMES[a]} {marked[a]}" for a in ATTRS)
          + f"; guesses right {right} of {tot}; wrong {wrong}", flush=True)
    return marked, wrong


def V(fmt, s, m, e):
    return sf.round_pack(fmt, s, m, e, RNE)[0]


def fam_tiny(fmt, frags):
    p, G = fmt.prec, GUARD[fmt.name]
    ga, gs = gates(fmt)
    lo = max(1, (p + G) // 4 - 4)
    hi = -min(ga, gs) + 6
    for fn in ("atan", "asin"):
        args = []
        for e in range(lo, hi + 1):
            for c in range(1, 17):
                for s in (0, 1):
                    args.append(V(fmt, s, c, -e))
        run(fmt, fn, args, frags, f"tiny {fn}, c 1..16, e {lo}..{hi}")
    args = []
    for xm, xe in ((1, 0), (3, 0), (5, 7)):
        x = V(fmt, 0, xm, xe)
        for e in range(lo, hi + 1):
            for c in range(1, 17):
                for s in (0, 1):
                    args.append((V(fmt, s, c * xm, xe - e), x))
    run(fmt, "atan2", args, frags, f"tiny atan2(c 2^-e x, x), x = 1, 3, 5 2^7")


def boundaries_below(fmt, K, kind, count=2):
    lo = dec(fmt, enc(fmt, K, RTZ))
    u = dec(fmt, enc(fmt, K, RTZ) + 1) - lo
    if kind == "grid":
        out = [lo - j * u for j in range(count)]
    else:
        out = [lo + u / 2 - j * u for j in range(count + 1)]
        out = [b for b in out if b < K][:count]
    return out


def fam_near(fmt, frags):
    pi = pi_frac()
    J = 64
    for kind in ("grid", "midpoint"):
        for i, b in enumerate(boundaries_below(fmt, pi / 2, kind)):
            gap = pi / 2 - b
            x0 = enc(fmt, 1 / gap)
            run(fmt, "atan", [x0 + j for j in range(-J, J + 1)], frags,
                f"near pi/2 atan, {kind} boundary {i}, x0 = 1/(pi/2 - b) {hex(x0)}")
            a0 = enc(fmt, gap)
            run(fmt, "acos", [a0 + j for j in range(-J, J + 1)], frags,
                f"near pi/2 acos, {kind} boundary {i}, x0 = pi/2 - b {hex(a0)}")
        for i, b in enumerate(boundaries_below(fmt, pi, kind)):
            y0 = enc(fmt, pi - b)
            run(fmt, "atan2", [(y0 + j, sf.one_bits(fmt, 1)) for j in range(-J, J + 1)],
                frags, f"near pi atan2(y, -1), {kind} boundary {i}, y0 = pi - b {hex(y0)}")
    if fmt.prec <= 53:
        # the window's extent, nearest grid boundary, atan under rtz
        b = boundaries_below(fmt, pi / 2, "grid")[0]
        x0 = enc(fmt, 1 / (pi / 2 - b))
        ext = []
        for i in range(0, 14):
            for sgn in (1, -1):
                xa = x0 + sgn * (1 << i)
                bits, fw, _ = evaluate2(frags[("atan", RTZ)], xa)
                ext.append((sgn * (1 << i), bool(fw & 0x80)))
        print(f"{fmt.name} near pi/2 atan rtz, the window's extent: "
              + " ".join(f"{j:+d}:{'M' if m else '.'}" for j, m in ext), flush=True)


def fam_acos1(fmt, frags):
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    run(fmt, "acos", [one - j for j in range(1, 65)], frags, "acos(1 - j 2^-p), j 1..64")
    run(fmt, "acos", [mone - j for j in range(1, 65)], frags, "acos(-1 + j 2^-p), j 1..64")
    run(fmt, "asin", [one - j for j in range(1, 65)], frags, "asin(1 - j 2^-p), j 1..64")


def fam_ratio(fmt, frags):
    p = fmt.prec
    one = sf.one_bits(fmt)
    for k in (-10, -40, -(p + 10)):
        y = V(fmt, 0, 1, k)
        run(fmt, "atan2", [(y, one + j) for j in range(1, 41)], frags,
            f"ratio atan2(2^{k}, 1 + j ulp), j 1..40")


def fam_diag(fmt, frags):
    rng = random.Random(77 + fmt.width)
    p = fmt.prec
    args = []
    for _ in range(40):
        E = rng.randint(-p, p)
        m = rng.getrandbits(p - 1) | (1 << (p - 1))
        x = V(fmt, 0, m, E - p + 1)
        for j in range(-4, 5):
            for sy in (0, 1):
                for sx in (0, 1):
                    args.append(((x + j) | (fmt.sign_mask if sy else 0),
                                 x | (fmt.sign_mask if sx else 0)))
    run(fmt, "atan2", args, frags, "diag atan2(x + j, x), 40 x, j -4..4, four quadrants")


def main():
    name, family = sys.argv[1], sys.argv[2]
    fmt = FORMATS[name]
    frags = {(fn, rnd): build(fmt, rnd, fn)
             for fn in ("atan", "asin", "acos", "atan2") for rnd in ATTRS}
    {"tiny": fam_tiny, "near": fam_near, "acos1": fam_acos1,
     "ratio": fam_ratio, "diag": fam_diag}[family](fmt, frags)


if __name__ == "__main__":
    main()
