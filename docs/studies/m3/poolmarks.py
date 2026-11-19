# M3 model: what the pools' marked lanes are (scratch; the study's 3.5).
# Every marked lane of each function's pool, at one format, under rne and
# rtz, classed by transcend.py's own exactness test (census.classify: rep,
# mid, exo, irr, range); the irr lanes (no exact value) are listed, since a
# mark there is the bound's, not the exact family's.
#
#   python poolmarks.py FMT

import sys
from collections import Counter

from m3core import FORMATS, RNE, RTZ, AN, INTARG
import m3harness as H
import m3pow as M
import census as CE


def main():
    fmt = FORMATS[sys.argv[1]]
    for fn in ("pow", "powr", "pown", "rootn", "compound"):
        lanes = H.pool(fmt, fn)
        for rnd in (RNE, RTZ):
            cls = Counter()
            irr = []
            for lane in lanes:
                n = lane[1] if fn in INTARG else None
                bld = H.builder(fn, fmt, rnd, n)
                if isinstance(bld, Exception):
                    continue
                _bits, fl, _ = M.run(bld, fn, lane)
                if not fl & H.MARK:
                    continue
                c = CE.classify(fmt, fn, lane)
                cls[c] += 1
                if c == "irr":
                    irr.append(lane)
            print(f"{fmt.name} {fn:8s} {AN[rnd]}: marked by class "
                  + ", ".join(f"{k} {v}" for k, v in sorted(cls.items())),
                  flush=True)
            for lane in irr[:12]:
                print(f"    irr marked: {H.show(fmt, lane, fn)}")


if __name__ == "__main__":
    main()
