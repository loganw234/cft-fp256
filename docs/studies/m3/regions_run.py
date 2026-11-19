# M3 model: the regions of placed arguments against transcend.py, bits and
# flags (scratch; the study's 3.3). Every lane of each region, every
# attribute; a failure is an unmarked lane that differs.
#
#   python regions_run.py FMT FN N [region ...]

import sys
import time

from m3core import FORMATS, ATTRS, AN, INTARG
import m3harness as H
import regions as RG


def main():
    fmt = FORMATS[sys.argv[1]]
    fn, n = sys.argv[2], int(sys.argv[3])
    names = sys.argv[4:] or (["int", "int-neg", "int17", "int1000", "int31"]
                             if fn in INTARG else list(RG.NAMES))
    t0 = time.time()
    bad = 0
    for name in names:
        lanes = RG.region(fmt, fn, name, n, 1)
        res = [H.compare(fmt, fn, lanes, rnd) for rnd in ATTRS]
        wrong = sum(r["wrong"] for r in res)
        bad += wrong
        print(f"{fmt.name} {fn} region {name}: {len(lanes)} lanes x 5 "
              f"attributes, marked " + "/".join(str(r["marked"]) for r in res)
              + f" (rne/rtz/rdn/rup/rmm), WRONG UNMARKED {wrong}", flush=True)
        for r, rnd in zip(res, ATTRS):
            for lane, bits, fl, want in r["wrong_ex"][:3]:
                print(f"    {AN[rnd]} WRONG {H.show(fmt, lane, fn)} got "
                      f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, {want[1]:#x})")
    print(f"{fmt.name} {fn}: {bad} wrong unmarked in all; "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
