# M2 model: the deepest cancellation over a stated range (scratch; the
# study's 2.3). host/tools/pi_worstcase.py's own search
# (worst_over_format), every binade of |x| from 2^VMIN to 2^(VMAX+1).
#
#   python worst_range.py FMT VMIN VMAX

import sys
import time
from collections import Counter

from m2core import ROOT                      # noqa: F401 (the paths)
import m2const                               # noqa: F401 (host/tools)
import pi_worstcase
from cft_golden.formats import FORMATS


def main():
    name, vmin, vmax = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    best, rows = pi_worstcase.worst_over_format(fmt, 1, vmin, vmax)
    v, m, e, lost = best
    hist = Counter(r[3] for r in rows)
    top = sorted(rows, key=lambda r: -r[3])[:8]
    print(f"{name}: {len(rows)} binades (every one, value exponents {vmin} "
          f"to {vmax}): deepest cancellation {lost} bits at value exponent "
          f"{v} (m = {m:#x}); {time.perf_counter() - t0:.0f}s")
    print(f"  the eight deepest: {[(r[0], r[3]) for r in top]}")
    print(f"  lost bits, histogram: {dict(sorted(hist.items()))}")


if __name__ == "__main__":
    main()
