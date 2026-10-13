# M2 model: the window around a structured centre (scratch; the study's
# 3.5). For x0 and its neighbours x0 + j ulp, j = -J..J (the encoding
# stepped by j, so below a power of two the steps are the finer ulp), how
# many mark, the extent of the marked run, and every lane against
# transcend.py (marked with its guess right, or equal).
#
#   python window.py FMT FN ATTR X0 J      (X0 as c/2^e, e.g. 1/2^26)

import sys
import time
from fractions import Fraction

from m2core import FORMATS, sf, enc, evaluate
from m2trig import build
from m2harness import tr


def main():
    name, fn, rnd = sys.argv[1], sys.argv[2], int(sys.argv[3])
    num, den = sys.argv[4].split("/")
    x0 = Fraction(int(num), int(den.split("^")[0]) ** int(den.split("^")[1])
                  if "^" in den else int(den))
    J = int(sys.argv[5])
    fmt = FORMATS[name]
    f = build(fmt, rnd, fn)
    b0 = enc(fmt, x0)
    t0 = time.perf_counter()
    marked, right, wrong, js = 0, 0, 0, []
    for j in range(-J, J + 1):
        xa = b0 + j
        bits, fw, _ = evaluate(f, xa)
        gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
        if fw & 0x80:
            marked += 1
            js.append(j)
            if (bits, fw & 0x1F) == (gb, gf):
                right += 1
        elif (bits, fw) != (gb, gf):
            wrong += 1
    run = f"j from {min(js)} to {max(js)}" if js else "none"
    print(f"{name} {fn} {sf.RND_NAMES[rnd]} around {sys.argv[4]} "
          f"({hex(b0)}), j = -{J}..{J}: marked {marked} ({run}; guess right "
          f"{right}), wrong unmarked {wrong}; {time.perf_counter() - t0:.0f}s",
          flush=True)


if __name__ == "__main__":
    main()
