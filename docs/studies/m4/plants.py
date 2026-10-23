# M4 model: the plants, each a fresh fragment with one named fault, and the
# checks that must turn red (scratch; the study's section 8). M2's four
# checks, and a fifth for the specials:
#   pools       the unary pool and atan2's pairs under rne and rtz, every
#               function: red on a wrong unmarked lane, or on a mark the
#               unplanted fragment does not make there
#   structured  the arguments the unplanted fragment marks on purpose,
#               found by running it over the candidates below: red where
#               the plant leaves one unmarked
#   bound       |V - f| / Bv past 1, mpmath at 4p + 200 bits, over placed
#               points (m4measure's edge, small and big, 48 each)
#   specials    specials.py's rows under all five attributes: red on a
#               wrong unmarked lane
#   audit       the index's exactness, lane by lane (the study's 8, item 2)
#   corner      send-back 1's region, atan2 with a tiny |y| (100 lanes,
#               rne and rtz): red on a wrong unmarked lane, a bound past 1
#               or a Bv that underflowed
#   control     the unplanted fragments: red in nothing
#
#   python plants.py FMT [PLANT ...]

import sys
import time
from fractions import Fraction

import mpmath

from m4core import FORMATS, sf, dec, enc, evaluate2, RNE, RTZ, ATTRS
from m4inv import build, PLANTS, FNS, gates, GUARD
from m4harness import pool, golden
from m4measure import sample, in_main, true_value
import specials

CHECK_RNDS = (RNE, RTZ)


def candidates(fmt):
    """Arguments some of which the unplanted routine marks on purpose: the
    tiny family's centres, atan2's quotient near a grid point, the windows
    next to pi/2 and pi (census.py's families, a slice)."""
    p, G = fmt.prec, GUARD[fmt.name]
    ga, gs = gates(fmt)
    out = []

    def Vb(s, m, e):
        return sf.round_pack(fmt, s, m, e, RNE)[0]
    for e in range(max(1, (p + G) // 4 - 4), -min(ga, gs) + 3):
        for c in (3, 5, 6, 7, 9, 11, 12, 13, 15):
            out.append(("atan", Vb(0, c, -e)))
            out.append(("asin", Vb(0, c, -e)))
    one = sf.one_bits(fmt)
    for j in range(1, 9):
        out.append(("atan2", (Vb(0, 1, -40), one + j)))
    import census
    from m4core import enc, pi_frac
    pi = pi_frac()
    for kind in ("grid", "midpoint"):
        b = census.boundaries_below(fmt, pi / 2, kind)[0]
        x0 = enc(fmt, 1 / (pi / 2 - b))
        a0 = enc(fmt, pi / 2 - b)
        for j in (-2, 0, 2):
            out.append(("atan", x0 + j))
            out.append(("acos", a0 + j))
    return out


def lanes(fmt, frags, cases):
    """{(fn, args, rnd): (bits, flag word)} for the cases."""
    out = {}
    for fn, args in cases:
        for rnd in ATTRS:
            b, fw, _ = evaluate2(frags[(fn, rnd)], args)
            out[(fn, args, rnd)] = (b, fw)
    return out


def check(fmt, plant, ctrl_marks, must_mark, placed, corner):
    red, cases = [], {}
    frags = {(fn, rnd): build(fmt, rnd, fn, plant=plant)
             for fn in FNS for rnd in ATTRS}
    # pools
    for fn in FNS:
        for rnd in CHECK_RNDS:
            for xa in pool(fmt, fn):
                b, fw, _ = evaluate2(frags[(fn, rnd)], xa)
                gb, gf = golden(fmt, fn, xa, rnd)
                if fw & 0x80:
                    if (fn, xa, rnd) not in ctrl_marks:
                        cases.setdefault("pools", f"{fn} {sf.RND_NAMES[rnd]} {xa} marked off the list")
                elif (b, fw) != (gb, gf):
                    cases.setdefault("pools", f"{fn} {sf.RND_NAMES[rnd]} {xa} wrong")
                if "pools" in cases:
                    break
            if "pools" in cases:
                break
        if "pools" in cases:
            break
    # structured
    for (fn, args, rnd) in must_mark:
        b, fw, _ = evaluate2(frags[(fn, rnd)], args)
        if not fw & 0x80:
            gb, gf = golden(fmt, fn, args, rnd)
            what = "unmarked" if (b, fw) == (gb, gf) else "unmarked and wrong"
            cases["structured"] = f"{fn} {sf.RND_NAMES[rnd]} {args} {what}"
            break
    # bound
    mpmath.mp.prec = 4 * fmt.prec + 200
    worst = 0.0
    for fn, xs in placed.items():
        f = frags[(fn, RNE)]
        for xa in xs:
            b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "Bv"], full=True)
            Vv = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
            Bv = abs(dec(fmt, pr["Bv"]))
            if Bv == 0:
                continue
            T = true_value(fn, xa, fmt)
            r = abs(mpmath.mpf(Vv.numerator) / Vv.denominator - T) / (
                mpmath.mpf(Bv.numerator) / Bv.denominator)
            if r > worst:
                worst = float(r)
            if r > 1 and "bound" not in cases:
                cases["bound"] = f"{fn} rne {xa}: 2^{float(mpmath.log(r, 2)):.1f} Bv"
    # specials
    for fn in FNS:
        for label, args in specials.rows(fmt, fn):
            for rnd in ATTRS:
                b, fw, _ = evaluate2(frags[(fn, rnd)], args)
                gb, gf = golden(fmt, fn, args, rnd)
                if not fw & 0x80 and (b, fw) != (gb, gf):
                    cases.setdefault("specials", f"{fn} {sf.RND_NAMES[rnd]} '{label}' wrong")
    # audit: the index's proof obligation, lane by lane (the study's 8, item
    # 2): for every k >= 1, n_h / P in [1/2, 2] (Sterbenz's premise) and
    # n_h - P computed exactly, over atan2 lanes placed where an index
    # chosen from an overestimating seed meets k = 1 with t just under 1/16
    # (audit_lanes), and over the cells' ends; each lane also against
    # transcend.py. Counted: the premise broken, the difference inexact,
    # the answer wrong and unmarked.
    MAGIC = sf.round_pack(fmt, 0, 3, fmt.prec - 2, RNE)[0]
    broken, inexact, wrong, first = 0, 0, 0, {}
    for args in audit_lanes(fmt):
        b, fw, pr = evaluate2(frags[("atan2", RNE)], args,
                              want=["nh", "P", "Nh0", "Kk"], full=True)
        if not fw & 0x80 and (b, fw) != tuple(golden(fmt, "atan2", args, RNE)):
            wrong += 1
            first.setdefault("wrong", args)
        if pr["Kk"] == MAGIC:
            continue
        nh, P_, N0 = (dec(fmt, pr[k]) for k in ("nh", "P", "Nh0"))
        if P_ and not (Fraction(1, 2) <= nh / P_ <= 2):
            broken += 1
            first.setdefault("premise", (args, float(nh / P_)))
        if nh - P_ != N0:
            inexact += 1
            first.setdefault("inexact", args)
    if broken or inexact or wrong:
        cases["audit"] = (f"of {len(audit_lanes(fmt))} lanes, the premise "
                          f"broken on {broken}, n_h - P inexact on {inexact}, "
                          f"wrong unmarked {wrong}; first: " + "; ".join(
                              f"{k} {v}" for k, v in first.items()))
    # corner: send-back 1's region (m4measure's "tinyn": atan2 with a tiny
    # |y| against |x| over the range above it) under rne and rtz: red on a
    # wrong unmarked lane, or, under rne, on an unmarked main-path lane
    # whose |V - f| passes Bv or whose Bv underflowed to 0
    for rnd in CHECK_RNDS:
        f = frags[("atan2", rnd)]
        for xa in corner:
            b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "Bv"], full=True)
            if fw & 0x80:
                continue
            if (b, fw) != tuple(golden(fmt, "atan2", xa, rnd)):
                cases.setdefault("corner", f"atan2 {sf.RND_NAMES[rnd]} {xa} wrong")
                break
            if rnd != RNE or fw != 0x10 or not (xa[0] & ~fmt.sign_mask):
                continue
            Bv = abs(dec(fmt, pr["Bv"]))
            if Bv == 0:
                cases.setdefault("corner", f"atan2 rne {xa}: Bv underflowed to 0")
                break
            Vv = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
            r = abs(mpmath.mpf(Vv.numerator) / Vv.denominator
                    - true_value("atan2", xa, fmt)) / (mpmath.mpf(Bv.numerator) / Bv.denominator)
            if r > 1:
                cases.setdefault("corner", f"atan2 rne {xa}: "
                                 f"2^{float(mpmath.log(r, 2)):.1f} Bv")
                break
        if "corner" in cases:
            break
    red = [k for k in ("pools", "structured", "bound", "specials", "audit",
                       "corner") if k in cases]
    return red, cases, worst


def audit_lanes(fmt):
    """atan2 (n, d) lanes: (1) d = 1 + frac/2048, the upper half of the
    seed's cell 0, where d RECIP_SEED(d) > 1, with n just under d/16: an
    unbiased index takes k = 1 at t/c < 1/2, but n and P - n share a binade
    and the difference stays exact; (2) d = 2 - 2^-e (e = 12, 14, 20), the
    top seed cell's upper part, with n just under 1/8 - (2 - d)/8 and its
    last bit set: there 1/8 lies between n and P - n, and the unbiased
    index's n_h - P is inexact (the study's 3.6, item 7); (3) the cells'
    ends."""
    p = fmt.prec
    out = []
    for frac_ in (3, 5, 7):                  # d = 1 + frac/2048: cell 0's top
        d = sf.round_pack(fmt, 0, (1 << (p - 1)) + (frac_ << (p - 12)),
                          -(p - 1), RNE)[0]
        D = dec(fmt, d)
        for j in range(0, 40):
            n = enc(fmt, D / 16 * (1 - Fraction(j, 2 ** 16)), RTZ)
            out.append((n, d))
    ulp_n = Fraction(1, 2 ** (p + 3))        # n in [1/16, 1/8)
    for e in (12, 14, 20):                   # d = 2 - 2^-e: the top cell
        eps = Fraction(1, 2 ** e)
        d = enc(fmt, 2 - eps)
        for j in range(0, 8):
            out.append((enc(fmt, Fraction(1, 8) - eps / 8 - (2 * j + 1) * ulp_n), d))
    from m4inv import cells
    for k, (lo, hi) in enumerate(cells(8)):
        for t in (lo, hi):
            for j in (-2, -1, 0, 1, 2):
                if 0 < t <= 1:
                    out.append((enc(fmt, t) + j, sf.one_bits(fmt)))
    return out


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    which = sys.argv[2:] or ["none"] + list(PLANTS)
    t0 = time.perf_counter()
    ctrl = {(fn, rnd): build(fmt, rnd, fn) for fn in FNS for rnd in ATTRS}
    ctrl_marks = set()
    for fn in FNS:
        for rnd in CHECK_RNDS:
            for xa in pool(fmt, fn):
                b, fw, _ = evaluate2(ctrl[(fn, rnd)], xa)
                if fw & 0x80:
                    ctrl_marks.add((fn, xa, rnd))
    cl = lanes(fmt, ctrl, candidates(fmt))
    must_mark = [k for k, (b, fw) in cl.items() if fw & 0x80]
    placed = {}
    for fn in FNS:
        xs = []
        for mode in ("edge", "small", "big"):
            xs += [x for x in sample(fmt, fn, mode, 48, 11) if in_main(fmt, fn, x)]
        placed[fn] = xs
    corner = sample(fmt, "atan2", "tinyn", 100, 17)
    print(f"{name}: the control marks {len(ctrl_marks)} pool lanes (rne, rtz) "
          f"and {len(must_mark)} structured lanes of {len(cl)}; "
          f"{sum(len(v) for v in placed.values())} placed points; "
          f"{time.perf_counter() - t0:.0f}s", flush=True)
    for plant in which:
        red, cases, worst = check(fmt, None if plant == "none" else plant,
                                  ctrl_marks, must_mark, placed, corner)
        print(f"{name} plant {plant}: red in {', '.join(red) if red else 'NOTHING'}; "
              f"largest placed error 2^{float(mpmath.log(worst, 2)) if worst else -999:.1f} Bv; "
              f"{time.perf_counter() - t0:.0f}s", flush=True)
        for k in red:
            print(f"     {k}: {cases[k]}", flush=True)


if __name__ == "__main__":
    main()
