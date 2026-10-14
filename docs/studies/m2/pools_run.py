# M2 model: the routines against transcend.py over the radian pools
# (scratch).
#
#   python pools_run.py FMT [FNS] [ATTRS] [variant] [G]
#
# FNS a comma list of sin, cos, tan; ATTRS a comma list of 0..4 (rne, rtz,
# rdn, rup, rmm). Every lane: equal to transcend.py in bits and flag word,
# or marked (bit 7), its guess then checked.

import sys
import time

from m2core import FORMATS, sf, ATTRS
from m2harness import pools, compare
from m2trig import build


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",") if len(sys.argv) > 2 else ["sin", "cos", "tan"]
    rnds = ([int(c) for c in sys.argv[3].split(",")] if len(sys.argv) > 3
            else list(ATTRS))
    variant = sys.argv[4] if len(sys.argv) > 4 else "A"
    G = int(sys.argv[5]) if len(sys.argv) > 5 else None
    fmt = FORMATS[name]
    xs = pools(fmt)
    t0 = time.perf_counter()
    print(f"{name}: {len(xs)} pool arguments, variant {variant}, G {G or 'default'}", flush=True)
    for fn in fns:
        for rnd in rnds:
            f = build(fmt, rnd, fn, variant=variant, G=G)
            st = compare(f, fn, xs, rnd)
            print(f"  {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                  f"{len(f.words)} words, live {f.live_max()}: "
                  f"{st['n']} lanes, marked {st['marked']} "
                  f"(guess right {st['marked_right']}), wrong "
                  f"{len(st['wrong'])}, flag words "
                  f"{sorted(hex(w) for w in st['words'])}; "
                  f"{time.perf_counter() - t0:.0f}s", flush=True)
            for wr in st["wrong"][:6]:
                print("     WRONG", wr, flush=True)
            if st["marks"]:
                print("     marks:", " ".join(st["marks"][:12]),
                      "..." if len(st["marks"]) > 12 else "", flush=True)


if __name__ == "__main__":
    main()
