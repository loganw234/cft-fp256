# M2 model: the plants (scratch; the study's section 8). Each plant is
# built into a fresh fragment and run through four checks; a check is RED
# when it finds what it exists to find:
#   pools       the pool slice (test_transcend's brute pool, the stage's
#               and the vector sets' deepest cancellations, every 16th
#               power of two, 64 random) against transcend.py, sin, cos
#               and tan under rne and rtz: a wrong unmarked lane is red,
#               and so is a mark off the list (the lanes the unplanted
#               fragment marks there, the committed list's part in the
#               slice; E1's rule, brief correction 1)
#   structured  the committed list of structured lanes that must mark
#               (census.py's: cos at 2^-26, 2^-25, 3 2^-26, 2^-24 under
#               rtz, rdn, rup; tan at 3 2^-26 under rne, rmm; both signs):
#               a lane unmarked is red
#   bound       |V - f(x)| / Bv over placed points (|r| near pi/4, x near
#               odd and even multiples of pi/2, x small, random), mpmath
#               at 4p + 200 bits: a ratio past 1 is red
#   audit       every instruction the reduction calls exact, checked on
#               random arguments, the deepest cancellations and the
#               products' binade edges (m2edges.py): a failure is red
#
#   python plants.py FMT PLANT [N]      (PLANT "none" for the control)

import sys
import time
import math
from fractions import Fraction

import mpmath

from m2core import FORMATS, sf, enc, dec, evaluate, RNE, RTZ, RDN, RUP, RMM
from m2trig import build, PLANTS, GUARD, RANGE, gates
from m2harness import brute_pool, tc, tr
from m2measure import sample, in_main, true_value
from m2red import audit
from m2plan import plan, LOST
from m2edges import edges
from cft_golden import vectors

STRUCT = {"fp64": [("cos", (RTZ, RDN, RUP), [Fraction(1, 2 ** 26), Fraction(1, 2 ** 25),
                                              Fraction(3, 2 ** 26), Fraction(1, 2 ** 24)]),
                   ("tan", (RNE, RMM), [Fraction(3, 2 ** 26)])]}


def pool_slice(fmt, n):
    p = fmt.prec
    t = 64 if fmt.width <= 64 else 16
    stage = tc.radian_pool(fmt, t, 5)
    vec = vectors.radian_unary_pool(fmt, 24, 14)
    out = set(brute_pool(fmt))
    one = sf.one_bits(fmt)
    # the deepest cancellations both pools carry (pi_worstcase's minimisers)
    import pi_worstcase
    stride, top = tc.WORST_SWEEP[fmt.name]
    out |= set(pi_worstcase.worst_encodings(fmt, stride, top))
    pw = sorted(b for b in stage if (b & fmt.man_mask) == 0)
    out |= set(pw[::16])
    out |= set(sample(fmt, "random", n, 11))
    return sorted(out)


def main():
    name, plant = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    plant = None if plant == "none" else plant
    fmt = FORMATS[name]
    p = fmt.prec
    t0 = time.perf_counter()
    red = []
    # pools
    xs = pool_slice(fmt, n)
    wrong = marked = off = 0
    first = firsto = None
    for fn in ("sin", "cos", "tan"):
        for rnd in (RNE, RTZ):
            f = build(fmt, rnd, fn, plant=plant)
            f0 = build(fmt, rnd, fn)                       # the list's source
            for xa in xs:
                b, w, _ = evaluate(f, xa)
                if w & 0x80:
                    marked += 1
                    if not evaluate(f0, xa)[1] & 0x80:
                        off += 1
                        if firsto is None:
                            firsto = (fn, sf.RND_NAMES[rnd], hex(xa))
                    continue
                gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
                if (b, w) != (gb, gf):
                    wrong += 1
                    if first is None:
                        first = (fn, sf.RND_NAMES[rnd], hex(xa))
    print(f"{name} plant {plant}: pools {len(xs)} x 6 lanes: wrong unmarked "
          f"{wrong} {first or ''}; marked {marked}, of them off the list "
          f"{off} {firsto or ''}; {time.perf_counter() - t0:.0f}s", flush=True)
    if wrong or off:
        red.append("pools")
    # structured
    miss = 0
    firstm = None
    for fn, rnds, vals in STRUCT.get(name, []):
        for rnd in rnds:
            f = build(fmt, rnd, fn, plant=plant)
            for v in vals:
                for s in (0, 1):
                    xa = enc(fmt, v) | (fmt.sign_mask if s else 0)
                    b, w, _ = evaluate(f, xa)
                    if not w & 0x80:
                        miss += 1
                        if firstm is None:
                            firstm = (fn, sf.RND_NAMES[rnd], hex(xa))
    print(f"   structured: unmarked {miss} {firstm or ''}", flush=True)
    if miss:
        red.append("structured")
    # bound
    mpmath.mp.prec = 4 * p + 200
    worst, wat = -1e9, None
    for mode in ("edge", "near", "zero", "small", "random"):
        ys = sample(fmt, mode, n, 5)
        for fn in ("sin", "cos", "tan"):
            f = build(fmt, RNE, fn, plant=plant)
            for xa in ys:
                if not in_main(fmt, fn, xa):
                    continue
                _b, _w, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv"], full=True)
                try:
                    V = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
                    Bv = abs(dec(fmt, pr["Bv"]))
                except ValueError:
                    worst, wat = 999.0, (fn, mode, hex(xa))
                    continue
                T = true_value(fn, dec(fmt, xa))
                if Bv == 0:
                    continue
                r = abs(mpmath.mpf(V.numerator) / V.denominator - T) / \
                    (mpmath.mpf(Bv.numerator) / Bv.denominator)
                lr = float(mpmath.log(r, 2)) if r else -999
                if lr > worst:
                    worst, wat = lr, (fn, mode, hex(xa))
    print(f"   bound: largest |V - f|/Bv 2^{worst:.2f} at {wat}", flush=True)
    if worst > 0:
        red.append("bound")
    # audit
    fails = 0
    firsta = None
    f = build(fmt, RNE, "sin", plant=plant)
    gs, gc = gates(fmt)
    R = RANGE[name]
    P = plan(fmt, GUARD[name], LOST[name], (R - 1) if R else fmt.emax,
             min(gs, gc) - 1)
    ed = edges(fmt, P)
    for xa in sample(fmt, "random", n, 13) + pool_slice(fmt, 0) + ed:
        if in_main(fmt, "sin", xa) and audit(f, xa):    # main-path lanes
            fails += 1
            if firsta is None:
                firsta = hex(xa)
    print(f"   audit: lanes with a failed exact claim {fails} {firsta or ''} "
          f"(with the {len(ed)} binade-edge arguments)", flush=True)
    if fails:
        red.append("audit")
    print(f"{name} plant {plant}: RED in {red if red else 'nothing'}; "
          f"{time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
