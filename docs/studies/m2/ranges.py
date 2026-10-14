# M2 model: what a stated range costs (scratch; the study's 2.3 and 5.3).
#
#   python ranges.py FMT [R ...]
#
# For each range |x| < 2^R: the plan (chunk width b, chunks a lane L, the
# stored words K and the bits of 2/pi they hold), the window's SELECT
# log-shifter (levels and SELECTs) against L stepped LDXs from a scratch
# copy of K words, and, where the bank can hold the words beside the rest
# of the routine (K <= 300), sin's built fragment: instructions and words.
# The cancellation used is m2plan.LOST, the measured worst over the
# format's whole range (TRANSCENDENTALS.md), a bound for any narrower one.

import sys
import math

from m2core import FORMATS, RNE
from m2plan import plan, LOST
from m2trig import build, gates, GUARD


def shifter_selects(P):
    nbits = max(1, (P.shifts - 1).bit_length())
    return nbits, sum(P.L + (1 << i) - 1 for i in range(nbits))


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    Rs = [int(a) for a in sys.argv[2:]] or [128, 256, 512, 1024, 2048, 4096,
                                            16384, fmt.emax + 1]
    gs, gc = gates(fmt)
    G = GUARD[name]
    for R in Rs:
        Emax = min(R - 1, fmt.emax)
        P = plan(fmt, G, LOST[name], Emax, min(gs, gc) - 1)
        nb, sels = shifter_selects(P)
        line = (f"{name} |x| < 2^{R}: b {P.b}, L {P.L}, words {P.K} "
                f"({P.Z} zero, {P.nchunks} chunks = {P.bits} bits of 2/pi), "
                f"shifts {P.shifts}: SELECT shifter {nb} levels, {sels} "
                f"SELECTs + {nb} bit tests; LDX: {P.L} stepped loads from "
                f"{P.K} scratch slots")
        if P.K <= 300:
            f = build(fmt, RNE, "sin", range_exp=R if R <= fmt.emax else None,
                      Pr=P)
            line += f"; sin built: {len(f.body)} instructions, {len(f.words)} words, live {f.live_max()}"
            red = {k[4:]: v for k, v in f.by_phase().items() if k.startswith("red-")}
            line += f"; the reduction's parts {red}"
        print(line, flush=True)


if __name__ == "__main__":
    main()
