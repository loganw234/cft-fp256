# M4 model: the mark-rate law with an inflated bound (scratch; the study's
# 3.4), M2's rate.py on this model. M1's 3.4: a lane is marked when its
# true value lies within Bv of a rounding boundary, one boundary an ulp
# under every attribute, so P = 2 Bv / ulp = 2^-G' sig(V), sig(V) the
# result's significand in [1, 2). The script prints M1's constant 2^(0.53
# - G') and the sum over the lanes of each lane's own 2^-G' sig(V), with
# the bound inflated to G' so that marks are common enough to count.
#
#   python rate.py FMT FNS N [ATTRS] [Gp] [seed] [mode]

import sys
import math
import time

from fractions import Fraction

from m4core import FORMATS, sf, dec, evaluate2, RNE, RTZ, pi_frac
from m4inv import build, GUARD
from m4measure import sample, in_main
from m4harness import golden


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",")
    n = int(sys.argv[3])
    rnds = ([int(c) for c in sys.argv[4].split(",")] if len(sys.argv) > 4
            else [RNE, RTZ])
    Gp = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    seed = int(sys.argv[6]) if len(sys.argv) > 6 else 3
    mode = sys.argv[7] if len(sys.argv) > 7 else "random"
    fmt = FORMATS[name]
    G = GUARD[name]
    t0 = time.perf_counter()
    pred = 2 ** (0.53 - Gp)
    # crowding (send-back 1): a lane whose V lies within one ulp of pi/4,
    # pi/2, 3pi/4 or pi cannot mark unless that constant lies within the
    # inflated bound of a boundary, which none does (the study's 1.4), so
    # the law, which assumes V spread over its cell, is tallied apart for
    # those lanes and for the rest
    PI = pi_frac()
    consts = [PI * k / 4 for k in (1, 2, 3, 4)]

    def ulp(c):
        e = c.numerator.bit_length() - c.denominator.bit_length()
        if Fraction(2) ** e > c:
            e -= 1
        return Fraction(2) ** (e - fmt.prec + 1)
    ulps = [ulp(c) for c in consts]

    def crowded(v):
        return any(abs(v - c) < u for c, u in zip(consts, ulps))
    for fn in fns:
        xs = sample(fmt, fn, mode, n, seed)
        main_xs = [x for x in xs if in_main(fmt, fn, x)]
        for rnd in rnds:
            f = build(fmt, rnd, fn, bound_shift=G - Gp)
            k = right = wrong = 0
            exp_sum = var_sum = 0.0
            cls = {True: [0, 0, 0.0, 0.0], False: [0, 0, 0.0, 0.0]}
            for xa in main_xs:
                bits, fw, pr = evaluate2(f, xa, want=["Vh"])
                v = abs(dec(fmt, pr["Vh"]))
                sig = 2 * math.frexp(float(v))[0] if v else 1.0
                pi_ = min(1.0, 2.0 ** -Gp * sig)
                exp_sum += pi_
                var_sum += pi_ * (1 - pi_)
                c = cls[crowded(v)]
                c[0] += 1
                c[2] += pi_
                c[3] += pi_ * (1 - pi_)
                if fw & 0x80:
                    c[1] += 1
                gb, gf = golden(fmt, fn, xa, rnd)
                if fw & 0x80:
                    k += 1
                    if bits == gb and (fw & 0x1F) == gf:
                        right += 1
                elif (bits, fw) != (gb, gf):
                    wrong += 1
            N = len(main_xs)
            sig1 = math.sqrt(N * pred * (1 - pred))
            sig2 = math.sqrt(var_sum) if var_sum else 1.0
            print(f"{name} {fn} {sf.RND_NAMES[rnd]} G'={Gp} {mode} seed {seed}: "
                  f"{N} lanes, marked {k} = {100 * k / N:.2f}%; M1's law "
                  f"{100 * pred:.2f}% ({(k - N * pred) / sig1:+.1f} sigma); each "
                  f"lane's own 2^-G' sig(V) sums to {exp_sum:.1f} = "
                  f"{100 * exp_sum / N:.2f}% ({(k - exp_sum) / sig2:+.1f} sigma); "
                  f"guesses right {right} of {k}; wrong unmarked {wrong}; "
                  f"{time.perf_counter() - t0:.0f}s", flush=True)
            for key, label in ((True, "within an ulp of pi/4, pi/2, 3pi/4 or pi"),
                               (False, "the rest")):
                nl, mk, es, vs = cls[key]
                sg = (mk - es) / math.sqrt(vs) if vs else 0.0
                print(f"    {label}: {nl} lanes, marked {mk}, each lane's own "
                      f"law {es:.1f} ({sg:+.1f} sigma)", flush=True)
            print(f"    distinct arguments: {len(set(main_xs))} of {N}", flush=True)


if __name__ == "__main__":
    main()
