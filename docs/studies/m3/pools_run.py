# M3 model: every pool lane of each function, at one format and every
# attribute, on the model against transcend.py (the study's 3.3).
#
#   python pools_run.py FMT [fn ...]
#
# A failure is an UNMARKED lane whose bits or flags differ from transcend's.
# A marked lane's guess is counted, not a failure (the replay answers it).

import sys
import time

from m3core import FORMATS, ATTRS, AN, FNS
import m3harness as H


def main():
    fmt = FORMATS[sys.argv[1]]
    fns = sys.argv[2:] or FNS
    t0 = time.time()
    total_wrong = 0
    for fn in fns:
        lanes = H.pool(fmt, fn)
        for rnd in ATTRS:
            r = H.compare(fmt, fn, lanes, rnd)
            total_wrong += r["wrong"]
            print(f"{fmt.name} {fn:8s} {AN[rnd]}: lanes {r['lanes']}, "
                  f"marked {r['marked']}, wrong guesses {r['guess_wrong']}, "
                  f"refused {r['refused']}, WRONG UNMARKED {r['wrong']}",
                  flush=True)
            for lane, bits, fl, want in r["wrong_ex"][:6]:
                print(f"    wrong: {H.show(fmt, lane, fn)} got "
                      f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, "
                      f"{want[1]:#x})")
    print(f"{fmt.name}: {total_wrong} wrong unmarked lanes in all; "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
