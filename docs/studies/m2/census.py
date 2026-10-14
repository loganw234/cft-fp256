# M2 model: the structured families (scratch; the study's 3.5).
#
#   python census.py FMT FAMILY [FNS] [ATTRS] [args...]
#
# FAMILY tiny: x = +-c 2^-e, c = 1..16, e from E0 to E1 (default: from
# floor((p+G)/4) - 4 up to the tiny gate), the arguments next to an exact
# case (sin x and tan x about x, cos x about 1 - x^2/2).
# FAMILY near: x = the representable numbers nearest k pi/2 for
# k = 1..K (default 64) and j ulps either side (j = -2..2), and the
# deepest cancellations pi_worstcase.py finds (the stage's own sweep,
# transcend_check.WORST_SWEEP): the arguments nearest multiples of pi/2.
# FAMILY minnbr V0 V1 [J]: the minimiser of every binade V0..V1 (value
# exponents; pi_worstcase.worst_in_binade) and its neighbours m0 + j,
# j = -J..J (default 4), positive (sin is odd and cos even, and the three
# directed attributes cover the mirror): verifier-VM2S's family, the
# NEIGHBOURS of the arguments nearest multiples of pi/2. With
# r = j ulp + delta, (j ulp)^2/2 lands on the result's grid below 1 once
# the exponent is about p/2 or more, and the true value then sits
# j ulp delta from a grid point (added after the study's first commit).
# Every lane against transcend.py: marked (its guess checked) or equal;
# the marks listed.

import sys
import time
from fractions import Fraction

from m2core import FORMATS, sf, enc, RNE, ATTRS
from m2const import pi_frac
from m2trig import build, gates, GUARD, RANGE
from m2harness import compare, tc

import pi_worstcase


def tiny_family(fmt, E0=None, E1=None, cmax=16):
    p, G = fmt.prec, GUARD[fmt.name]
    gs, gc = gates(fmt)
    if E0 is None:
        E0 = (p + G) // 4 - 4
    if E1 is None:
        E1 = -min(gs, gc)
    out = []
    for e in range(E0, E1 + 1):
        for c in range(1, cmax + 1):
            v = Fraction(c, 2 ** e)
            b = enc(fmt, v)
            out += [b, b | fmt.sign_mask]
    return sorted(set(out))


def near_family(fmt, K=64, J=2):
    pio2 = pi_frac() / 2
    out = []
    for k in range(1, K + 1):
        b = enc(fmt, k * pio2)
        for j in range(-J, J + 1):
            out += [b + j, (b + j) | fmt.sign_mask]
    stride, top = tc.WORST_SWEEP[fmt.name]
    vmax = (RANGE[fmt.name] - 1) if RANGE[fmt.name] else fmt.emax
    # within a stated range the stage's stride would reach one binade or
    # two: sweep at least 64 of the range's
    stride = max(1, min(stride, (vmax + 1) // 64))
    out += pi_worstcase.worst_encodings(fmt, stride, top, 0, vmax)
    return sorted(set(out))


def minnbr_family(fmt, v0, v1, J=4):
    p = fmt.prec
    lo, hi = 1 << (p - 1), (1 << p) - 1
    out = []
    for v in range(v0, v1 + 1):
        m, e, _lost, _mag, _N = pi_worstcase.worst_in_binade(fmt, v)
        for j in range(-J, J + 1):
            if lo <= m + j <= hi:
                out.append(pi_worstcase._enc(fmt, 0, m + j, e))
    return sorted(set(out))


def main():
    name, fam = sys.argv[1], sys.argv[2]
    fns = sys.argv[3].split(",") if len(sys.argv) > 3 else ["sin", "cos", "tan"]
    rnds = ([int(c) for c in sys.argv[4].split(",")] if len(sys.argv) > 4
            else list(ATTRS))
    extra = [int(a) for a in sys.argv[5:]]
    fmt = FORMATS[name]
    if fam == "tiny":
        xs = tiny_family(fmt, *extra)
    elif fam == "minnbr":
        xs = minnbr_family(fmt, *extra)
    else:
        xs = near_family(fmt, *extra)
    t0 = time.perf_counter()
    print(f"{name} {fam}: {len(xs)} arguments", flush=True)
    for fn in fns:
        for rnd in rnds:
            f = build(fmt, rnd, fn)
            st = compare(f, fn, xs, rnd)
            print(f"  {fn} {sf.RND_NAMES[rnd]}: marked {st['marked']} "
                  f"(guess right {st['marked_right']}), wrong "
                  f"{len(st['wrong'])}; {time.perf_counter() - t0:.0f}s",
                  flush=True)
            for wr in st["wrong"][:6]:
                print("     WRONG", wr, flush=True)
            if st["marks"]:
                print("     marks:", " ".join(st["marks"][:40]),
                      "..." if len(st["marks"]) > 40 else "", flush=True)
                if fam == "minnbr":
                    vs = sorted({((int(h, 16) >> fmt.man_w) & fmt.exp_mask)
                                 - fmt.bias for h in st["marks"]})
                    print("     the binades (value exponents) of the marks:",
                          vs, flush=True)


if __name__ == "__main__":
    main()
