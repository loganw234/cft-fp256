# M4 model: asin's and acos's 1 - x^2 in the direct form, 1 - RN(x^2) by
# Fast2Sum plus x^2's exact TwoProd error, against the product form
# (1 - |x|)(1 + |x|), and against the direct form normalised by one more
# Fast2Sum ("renorm") (scratch; the study's 2.4). The pools against
# transcend.py under every attribute, and |V - f| / Bv over the edge, big
# and diag regions (mpmath at 4p + 200 bits), every form, the same lanes.
#
#   python uform.py FMT N

import sys

import mpmath

from m4core import FORMATS, sf, dec, evaluate2, ATTRS, RNE
from m4inv import build
from m4harness import pool, compare
from m4measure import sample, in_main, true_value


def main():
    name, n = sys.argv[1], int(sys.argv[2])
    fmt = FORMATS[name]
    for fn in ("asin", "acos"):
        for form in ("product", "direct", "renorm"):
            wrong = marked = 0
            for rnd in ATTRS:
                st = compare(build(fmt, rnd, fn, u_form=form), fn, pool(fmt, fn), rnd)
                wrong += len(st["wrong"])
                marked += st["marked"]
            f = build(fmt, RNE, fn, u_form=form)
            mpmath.mp.prec = 4 * fmt.prec + 200
            worst = 0.0
            for mode in ("edge", "big", "diag"):
                for xa in sample(fmt, fn, mode, n, 4):
                    if not in_main(fmt, fn, xa):
                        continue
                    b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "Bv"], full=True)
                    V = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"])
                    Bv = abs(dec(fmt, pr["Bv"]))
                    r = abs(mpmath.mpf(V.numerator) / V.denominator - true_value(fn, xa, fmt)) / (
                        mpmath.mpf(Bv.numerator) / Bv.denominator)
                    worst = max(worst, float(r))
            print(f"{name} {fn} u {form}: {len(f.body)} instructions; pools, five "
                  f"attributes: wrong {wrong}, marked {marked}; largest |V - f|/Bv "
                  f"over edge, big, diag ({n} each): {worst:.4g}", flush=True)


if __name__ == "__main__":
    main()
