# M2 model: the mark-rate law with an inflated bound (scratch; the study's
# 3.4). M1's 3.4: a lane's true value lies uniformly within a rounding
# cell, and is marked when within Bv of a boundary (one boundary an ulp
# under every attribute), so P = 2 Bv / ulp. With Bv = 2^-(p+G') |V|,
# that is 2^-G' times the result's significand (in [1, 2)). Averaged over
# a binade with the result spread evenly in log scale, the significand's
# mean is 1/ln 2, which gives M1's 2^(0.53 - G'). sin and cos of random
# arguments are not spread so (their values crowd toward +-1), so this
# script prints both predictions: M1's constant and the sum over the
# lanes of each lane's own 2^-G' sig(V).
#
#   python rate.py FMT FNS N [ATTRS] [Gp] [seed]

import sys
import math
import time

from m2core import FORMATS, sf, dec, evaluate, RNE, RTZ
from m2trig import build, GUARD
from m2measure import sample, in_main
from m2harness import tr


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",")
    n = int(sys.argv[3])
    rnds = ([int(c) for c in sys.argv[4].split(",")] if len(sys.argv) > 4
            else [RNE, RTZ])
    Gp = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    seed = int(sys.argv[6]) if len(sys.argv) > 6 else 3
    fmt = FORMATS[name]
    G = GUARD[name]
    xs = [x for x in sample(fmt, "random", n, seed)]
    t0 = time.perf_counter()
    pred = 2 ** (0.53 - Gp)
    for fn in fns:
        main_xs = [x for x in xs if in_main(fmt, fn, x)]
        for rnd in rnds:
            f = build(fmt, rnd, fn, bound_shift=G - Gp)
            k = right = wrong = 0
            exp_sum = var_sum = 0.0
            for xa in main_xs:
                bits, fw, pr = evaluate(f, xa, want=["Vh"])
                v = abs(dec(fmt, pr["Vh"]))
                sig = 2 * math.frexp(float(v))[0]          # in [1, 2)
                pi_ = min(1.0, 2.0 ** -Gp * sig)
                exp_sum += pi_
                var_sum += pi_ * (1 - pi_)
                gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
                if fw & 0x80:
                    k += 1
                    if bits == gb and (fw & 0x1F) == gf:
                        right += 1
                elif (bits, fw) != (gb, gf):
                    wrong += 1
            N = len(main_xs)
            sig1 = math.sqrt(N * pred * (1 - pred))
            sig2 = math.sqrt(var_sum)
            print(f"{name} {fn} {sf.RND_NAMES[rnd]} G'={Gp} seed {seed}: {N} lanes, "
                  f"marked {k} = {100 * k / N:.2f}%; M1's law {100 * pred:.2f}% "
                  f"({(k - N * pred) / sig1:+.1f} sigma); each lane's own "
                  f"2^-G' sig(V) sums to {exp_sum:.1f} = {100 * exp_sum / N:.2f}% "
                  f"({(k - exp_sum) / sig2:+.1f} sigma); guesses right {right} "
                  f"of {k}; wrong unmarked {wrong}; {time.perf_counter() - t0:.0f}s",
                  flush=True)


if __name__ == "__main__":
    main()
