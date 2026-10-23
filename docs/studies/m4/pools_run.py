# M4 model: the routines against transcend.py over the pools (scratch).
#
#   python pools_run.py FMT [FNS] [ATTRS] [G]
#
# FNS a comma list of atan, asin, acos, atan2; ATTRS a comma list of 0..4
# (rne, rtz, rdn, rup, rmm). Every lane: equal to transcend.py in bits and
# flag word, or marked (bit 7), its guess then checked.

import sys
import time

from m4core import FORMATS, sf, ATTRS
from m4harness import pool, compare
from m4inv import build, FNS


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",") if len(sys.argv) > 2 else list(FNS)
    rnds = ([int(c) for c in sys.argv[3].split(",")] if len(sys.argv) > 3
            else list(ATTRS))
    G = int(sys.argv[4]) if len(sys.argv) > 4 else None
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    for fn in fns:
        xs = pool(fmt, fn)
        print(f"{name} {fn}: {len(xs)} pool arguments, G {G or 'default'}",
              flush=True)
        for rnd in rnds:
            f = build(fmt, rnd, fn, G=G)
            st = compare(f, fn, xs, rnd)
            print(f"  {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                  f"{len(f.words)} words, live {f.live_max()}: "
                  f"{st['n']} lanes, marked {st['marked']} "
                  f"(guess right {st['marked_right']}), wrong "
                  f"{len(st['wrong'])}, flag words "
                  f"{sorted(hex(v) for v in st['words'])}; "
                  f"{time.perf_counter() - t0:.0f}s", flush=True)
            for wr in st["wrong"][:6]:
                print("     WRONG", wr, flush=True)
            if st["marks"]:
                print("     marks:", " ".join(str(m) for m in st["marks"][:10]),
                      "..." if len(st["marks"]) > 10 else "", flush=True)


if __name__ == "__main__":
    main()
