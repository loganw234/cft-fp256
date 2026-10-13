# M2 model: how far the double word goes at fp32 (scratch; the study's
# 2.7). For each G, the plan and sin's, cos's and tan's fragments built at
# fp32, or the static proof that fails (the generator asserts each one
# before any lane runs).
#
#   python fp32_guard.py [G ...]

import sys
import math

from m2core import FORMATS, RNE
from m2plan import plan, LOST
from m2trig import build, gates


def main():
    Gs = [int(a) for a in sys.argv[1:]] or [16, 18, 20, 22, 30, 40]
    fmt = FORMATS["fp32"]
    p = fmt.prec
    gs, gc = gates(fmt)
    for G in Gs:
        # m2plan.plan_b's own bottom and widest b, written out
        budget = -(p + G + 3 + LOST["fp32"] + 1)
        bottom = math.floor(budget - 2 + 2 * p - math.log2(3 * 4)) - 1
        bmax = min(p - 4, 2 * p + 1 + bottom)
        if bmax < 2:
            print(f"fp32 G {G}: no plan: the exact combination needs "
                  f"b <= 2p + 1 + bottom = {2 * p + 1 + bottom} "
                  f"(budget {budget}, bottom {bottom})", flush=True)
            continue
        try:
            P = plan(fmt, G, LOST["fp32"], fmt.emax, min(gs, gc) - 1)
            line = (f"fp32 G {G}: plan b {P.b} L {P.L} bottom {P.bottom} "
                    f"budget {P.budget} words of 2/pi {P.K}")
        except (AssertionError, ValueError, IndexError) as e:
            print(f"fp32 G {G}: the plan fails: {e!r}", flush=True)
            continue
        for fn in ("sin", "cos", "tan"):
            try:
                f = build(fmt, RNE, fn, G=G)
                line += (f"; {fn} {len(f.body)} instructions, {len(f.words)} "
                         f"words, live {f.live_max()}")
            except AssertionError as e:
                line += f"; {fn}: a static proof fails: {e!r}"
        print(line, flush=True)


if __name__ == "__main__":
    main()
